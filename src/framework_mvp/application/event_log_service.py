# pyright: reportAttributeAccessIssue=false
"""Orchestrierung kanonischer Event-Log-Artefakte."""

import gzip
import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from uuid import UUID

import pandas as pd

from framework_mvp.application.event_log import EventLogErgebnis, erzeuge_event_log
from framework_mvp.application.mapping_service import MappingService
from framework_mvp.application.ports.event_log_repository import EventLogRepository
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import EventLogArtefakt, EventLogStatus
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher

EVENT_LOG_ARTEFAKTVERSION = 1


class EventLogService:
    """Erzeugt, speichert und lädt Event Logs aus validierten Mappings."""

    def __init__(
        self,
        repository: EventLogRepository,
        mapping_service: MappingService,
        transformations_service: TransformationsService,
        artefakte: ImportartefaktSpeicher,
    ) -> None:
        self._repository = repository
        self._mapping_service = mapping_service
        self._transformations_service = transformations_service
        self._artefakte = artefakte

    def vorschau(self, mapping_id: UUID) -> EventLogErgebnis:
        """Wendet ein gespeichertes Mapping auf seinen Zwischendatensatz an."""
        mapping = self._mapping_service.laden(mapping_id)
        if mapping is None:
            raise Domaenenfehler("Das semantische Mapping wurde nicht gefunden.")
        datensatz, daten = self._transformations_service.zwischendatensatz_laden(
            mapping.zwischendatensatz_id
        )
        return erzeuge_event_log(daten, mapping, datensatz.zwischendatensatz_id)

    def speichern(self, event_log_id: UUID, mapping_id: UUID) -> EventLogArtefakt:
        """Speichert CSV.GZ, Schema und Lineage atomar und idempotent."""
        vorhanden = self._repository.laden(event_log_id)
        if vorhanden is not None:
            self._integritaet_pruefen(vorhanden)
            return vorhanden
        mapping = self._mapping_service.laden(mapping_id)
        if mapping is None:
            raise Domaenenfehler("Das semantische Mapping wurde nicht gefunden.")
        datensatz, _ = self._transformations_service.zwischendatensatz_laden(
            mapping.zwischendatensatz_id
        )
        ergebnis = self.vorschau(mapping_id)
        jetzt = datetime.now(UTC)
        basis = PurePosixPath("projects") / str(mapping.projekt_id) / "event_logs"
        csv_pfad = (basis / f"{event_log_id}.csv.gz").as_posix()
        schema_pfad = (basis / f"{event_log_id}.schema.json").as_posix()
        lineage_pfad = (basis / f"{event_log_id}.lineage.json").as_posix()
        csv_text = ergebnis.ereignisse.to_csv(
            index=False, date_format="%Y-%m-%dT%H:%M:%S.%f%z", na_rep=""
        )
        csv_bytes = gzip.compress(csv_text.encode("utf-8"), mtime=0)
        sha256 = hashlib.sha256(csv_bytes).hexdigest()
        schema = {
            "artefaktversion": EVENT_LOG_ARTEFAKTVERSION,
            "standardisierte_spalten": [
                wert
                for wert in (
                    "case_id",
                    "activity",
                    "timestamp",
                    "start_timestamp",
                    "end_timestamp",
                    "lifecycle",
                    "resource",
                    "event_id",
                )
                if wert in ergebnis.ereignisse
            ],
            "technische_datentypen": {
                str(name): str(typ) for name, typ in ergebnis.ereignisse.dtypes.items()
            },
            "attributrollen": ergebnis.attributrollen,
            "zeitformat": "ISO-8601; Zeitzone wird nur bei vorhandener Quellzeitzone bewahrt",
            "ereignisanzahl": ergebnis.ereignisanzahl,
            "fallanzahl": ergebnis.fallanzahl,
            "sha256": sha256,
        }
        plan = self._transformations_service.plan_laden(datensatz.transformationsplan_id)
        lineage = {
            "artefaktversion": EVENT_LOG_ARTEFAKTVERSION,
            "projekt_id": str(mapping.projekt_id),
            "zwischendatensatz_id": str(mapping.zwischendatensatz_id),
            "mapping_id": str(mapping.mapping_id),
            "transformationsplan_id": str(datensatz.transformationsplan_id),
            "quellimporte": [str(wert) for wert in datensatz.import_ids],
            "herkunft_standardspalten": ergebnis.herkunft_standardspalten,
            "transformationsplan_vorhanden": plan is not None,
            "erstellt_am": jetzt.isoformat(),
            "software_schemaversion": 5,
        }
        pflichtfehler = (
            ergebnis.ereignisse["case_id"].isna()
            | ergebnis.ereignisse["case_id"].astype("string").str.strip().eq("")
            | ergebnis.ereignisse["activity"].isna()
            | ergebnis.ereignisse["activity"].astype("string").str.strip().eq("")
            | ergebnis.ereignisse["timestamp"].isna()
        )
        status = EventLogStatus.UNGUELTIG if bool(pflichtfehler.any()) else EventLogStatus.ERZEUGT
        erzeugt = []
        try:
            erzeugt.append(self._artefakte.artefakt_speichern(csv_pfad, csv_bytes))
            erzeugt.append(
                self._artefakte.artefakt_speichern(
                    schema_pfad,
                    json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2).encode(),
                )
            )
            erzeugt.append(
                self._artefakte.artefakt_speichern(
                    lineage_pfad,
                    json.dumps(lineage, ensure_ascii=False, sort_keys=True, indent=2).encode(),
                )
            )
            artefakt = EventLogArtefakt(
                event_log_id,
                mapping.projekt_id,
                mapping.zwischendatensatz_id,
                mapping.mapping_id,
                status,
                ergebnis.ereignisanzahl,
                ergebnis.fallanzahl,
                ergebnis.aktivitaetsanzahl,
                ergebnis.fruehester_zeitpunkt,
                ergebnis.spaetester_zeitpunkt,
                csv_pfad,
                schema_pfad,
                lineage_pfad,
                "",
                sha256,
                jetzt,
            )
            self._repository.speichern(artefakt)
            return artefakt
        except Exception:
            for wert in reversed(erzeugt):
                self._artefakte.neu_erstelltes_artefakt_entfernen(wert)
            raise

    def laden(self, event_log_id: UUID) -> tuple[EventLogArtefakt, pd.DataFrame]:
        """Lädt und prüft das kanonische CSV.GZ-Artefakt."""
        artefakt = self._repository.laden(event_log_id)
        if artefakt is None:
            raise Domaenenfehler("Das Event Log wurde nicht gefunden.")
        inhalt = self._integritaet_pruefen(artefakt)
        daten = pd.read_csv(BytesIO(gzip.decompress(inhalt)), keep_default_na=False)
        for name in ("timestamp", "start_timestamp", "end_timestamp"):
            if name in daten:
                daten[name] = pd.to_datetime(daten[name], errors="coerce")
        return artefakt, daten

    def fuer_projekt(self, projekt_id: UUID) -> list[EventLogArtefakt]:
        """Listet Event Logs eines Projekts."""
        return self._repository.fuer_projekt(projekt_id)

    def _integritaet_pruefen(self, artefakt: EventLogArtefakt) -> bytes:
        inhalt = self._artefakte.lesen(artefakt.relativer_csv_pfad)
        if hashlib.sha256(inhalt).hexdigest() != artefakt.sha256:
            raise Importintegritaetsfehler("Die Event-Log-Prüfsumme stimmt nicht überein.")
        try:
            gzip.decompress(inhalt)
            json.loads(self._artefakte.lesen(artefakt.relativer_schema_pfad))
            json.loads(self._artefakte.lesen(artefakt.relativer_lineage_pfad))
        except (gzip.BadGzipFile, json.JSONDecodeError) as fehler:
            raise Importintegritaetsfehler("Die Event-Log-Artefakte sind inkonsistent.") from fehler
        return inhalt
