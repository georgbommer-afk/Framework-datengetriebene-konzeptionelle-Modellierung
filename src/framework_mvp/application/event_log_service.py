# pyright: reportAttributeAccessIssue=false
"""Orchestrierung kanonischer Event-Log-Artefakte."""

import gzip
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from uuid import UUID

import pandas as pd

from framework_mvp.application.aktive_lineage_service import AktiveLineageService, LineageEndpunkt
from framework_mvp.application.event_log import EventLogErgebnis, erzeuge_event_log
from framework_mvp.application.mapping_service import EventLogKonfigurationService
from framework_mvp.application.mappingtabelle_service import MappingtabelleService
from framework_mvp.application.ports.event_log_repository import EventLogRepository
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    EventLogArtefakt,
    EventLogStatus,
    Mappingtabelle,
    SemantischesMapping,
    Zwischendatensatz,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher

EVENT_LOG_ARTEFAKTVERSION = 2


@dataclass(frozen=True, slots=True)
class EventLogKontext:
    """Integritätsgeprüfte, exakt zusammengehörige Artefaktkette aus Schritt 4."""

    artefakt: EventLogArtefakt
    ereignisse: pd.DataFrame
    konfiguration: SemantischesMapping
    zwischendatensatz: Zwischendatensatz
    zwischendaten: pd.DataFrame
    mappingtabelle: Mappingtabelle | None
    schema: dict[str, object]
    lineage: dict[str, object]


class EventLogService:
    """Erzeugt, speichert und lädt Event Logs aus validierten Konfigurationen."""

    def __init__(
        self,
        repository: EventLogRepository,
        konfigurations_service: EventLogKonfigurationService,
        transformations_service: TransformationsService,
        artefakte: ImportartefaktSpeicher,
        mappingtabelle_service: MappingtabelleService | None = None,
        aktive_lineage: AktiveLineageService | None = None,
    ) -> None:
        self._repository = repository
        self._konfigurations_service = konfigurations_service
        self._transformations_service = transformations_service
        self._artefakte = artefakte
        self._mappingtabelle_service = mappingtabelle_service
        self._aktive_lineage = aktive_lineage

    def _kontext_laden(
        self, konfigurations_id: UUID
    ) -> tuple[SemantischesMapping, Zwischendatensatz, pd.DataFrame, Mappingtabelle | None]:
        konfiguration = self._konfigurations_service.laden(konfigurations_id)
        if konfiguration is None:
            raise Domaenenfehler("Die Event-Log-Konfiguration wurde nicht gefunden.")
        datensatz, daten = self._transformations_service.zwischendatensatz_laden(
            konfiguration.zwischendatensatz_id
        )
        if datensatz.projekt_id != konfiguration.projekt_id:
            raise Domaenenfehler(
                "Event-Log-Konfiguration und Zwischendatensatz gehören nicht zum selben Projekt."
            )
        mappingtabelle = None
        if konfiguration.mappingtabelle_id is not None:
            if self._mappingtabelle_service is None:
                raise Domaenenfehler(
                    "Die referenzierte Mappingtabelle M kann nicht geladen werden."
                )
            mappingtabelle = self._mappingtabelle_service.laden(konfiguration.mappingtabelle_id)
            if mappingtabelle is None:
                raise Domaenenfehler("Die referenzierte Mappingtabelle M wurde nicht gefunden.")
            if (
                mappingtabelle.projekt_id != konfiguration.projekt_id
                or mappingtabelle.zwischendatensatz_id != konfiguration.zwischendatensatz_id
            ):
                raise Domaenenfehler(
                    "Mappingtabelle M und Event-Log-Konfiguration gehören nicht zum selben T."
                )
        return konfiguration, datensatz, daten, mappingtabelle

    def vorschau(self, konfigurations_id: UUID) -> EventLogErgebnis:
        """Wendet Konfiguration und optional M auf eine tiefe Arbeitskopie von T an."""
        konfiguration, datensatz, daten, mappingtabelle = self._kontext_laden(konfigurations_id)
        return erzeuge_event_log(
            daten,
            konfiguration,
            datensatz.zwischendatensatz_id,
            mappingtabelle,
        )

    def speichern(self, event_log_id: UUID, konfigurations_id: UUID) -> EventLogArtefakt:
        """Speichert CSV.GZ, Schema und Lineage atomar und idempotent."""
        vorhanden = self._repository.laden(event_log_id)
        if vorhanden is not None:
            if vorhanden.mapping_id != konfigurations_id:
                raise Domaenenfehler(
                    "Die Event-Log-ID gehört bereits zu einer anderen Konfiguration."
                )
            self._integritaet_pruefen(vorhanden)
            return vorhanden
        konfiguration, datensatz, daten, mappingtabelle = self._kontext_laden(konfigurations_id)
        ergebnis = erzeuge_event_log(
            daten,
            konfiguration,
            datensatz.zwischendatensatz_id,
            mappingtabelle,
        )
        jetzt = datetime.now(UTC)
        basis = PurePosixPath("projects") / str(konfiguration.projekt_id) / "event_logs"
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
            "fachliche_spalten": [
                wert
                for wert in ergebnis.ereignisse.columns
                if wert in {"case_id", "activity", "timestamp"}
                or (
                    konfiguration.konfigurationsversion >= 3
                    and wert
                    in {
                        "start_timestamp",
                        "end_timestamp",
                        "plan_start_timestamp",
                        "plan_end_timestamp",
                        "lifecycle",
                        "resource",
                    }
                )
                or wert in ergebnis.attributherkunft
            ],
            "technische_metadatenspalten": [
                wert
                for wert in ergebnis.ereignisse.columns
                if str(wert).startswith("_") or wert == "event_id"
            ],
            "technische_datentypen": {
                str(name): str(typ) for name, typ in ergebnis.ereignisse.dtypes.items()
            },
            "zusaetzliche_attribute": ergebnis.attributherkunft,
            "zeitformat": "ISO-8601; Zeitzone wird nur bei vorhandener Quellzeitzone bewahrt",
            "ereignisanzahl": ergebnis.ereignisanzahl,
            "fallanzahl": ergebnis.fallanzahl,
            "sha256": sha256,
        }
        plan = self._transformations_service.plan_laden(datensatz.transformationsplan_id)
        lineage = {
            "artefaktversion": EVENT_LOG_ARTEFAKTVERSION,
            "projekt_id": str(konfiguration.projekt_id),
            "zwischendatensatz_id": str(konfiguration.zwischendatensatz_id),
            "event_log_konfigurations_id": str(konfiguration.mapping_id),
            "mapping_id": str(konfiguration.mapping_id),
            "mappingtabelle_id": (
                str(konfiguration.mappingtabelle_id)
                if konfiguration.mappingtabelle_id is not None
                else None
            ),
            "event_log_konfiguration": asdict(konfiguration),
            "angewandte_fachliche_zuordnungen": ergebnis.angewandte_mappingeintraege,
            "transformationsplan_id": str(datensatz.transformationsplan_id),
            "quellimporte": [str(wert) for wert in datensatz.import_ids],
            "herkunft_standardspalten": ergebnis.herkunft_standardspalten,
            "herkunft_zusaetzliche_attribute": ergebnis.attributherkunft,
            "technische_ereignisherkunft": {
                "quellzeile": "_source_row",
                "urspruengliche_zeitstempelspalte": "_source_timestamp_column",
                "urspruenglicher_zeitstempelwert": "_source_timestamp_raw",
                "urspruengliche_fallidentifikation": "_source_case_id_raw",
                "urspruengliche_aktivitaetswerte": "_source_activity_raw",
            },
            "transformationsplan_vorhanden": plan is not None,
            "erstellt_am": jetzt.isoformat(),
            "software_schemaversion": 7,
        }
        status = EventLogStatus.ERZEUGT
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
                    json.dumps(
                        lineage,
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                        default=str,
                    ).encode(),
                )
            )
            artefakt = EventLogArtefakt(
                event_log_id,
                konfiguration.projekt_id,
                konfiguration.zwischendatensatz_id,
                konfiguration.mapping_id,
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
            if self._aktive_lineage is not None:
                self._aktive_lineage.aktivieren(
                    artefakt.projekt_id,
                    LineageEndpunkt.E,
                    {
                        "aktueller_zwischendatensatz_id": artefakt.zwischendatensatz_id,
                        "aktuelle_mapping_id": artefakt.mapping_id,
                        "mapping_id": artefakt.mapping_id,
                        "aktuelle_event_log_konfiguration_id": artefakt.mapping_id,
                        "aktuelles_event_log_id": artefakt.event_log_id,
                        "event_log_id": artefakt.event_log_id,
                    },
                )
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

    def kontext_laden(self, event_log_id: UUID) -> EventLogKontext:
        """Lädt E, Konfiguration, T und optional M ausschließlich in ihrer Lineage-Kette."""
        artefakt, ereignisse = self.laden(event_log_id)
        konfiguration, datensatz, daten, mappingtabelle = self._kontext_laden(artefakt.mapping_id)
        if (
            artefakt.projekt_id != konfiguration.projekt_id
            or artefakt.zwischendatensatz_id != datensatz.zwischendatensatz_id
        ):
            raise Importintegritaetsfehler(
                "Event Log, Konfiguration und Zwischendatensatz gehören nicht zusammen."
            )
        schema = json.loads(self._artefakte.lesen(artefakt.relativer_schema_pfad))
        lineage = json.loads(self._artefakte.lesen(artefakt.relativer_lineage_pfad))
        return EventLogKontext(
            artefakt,
            ereignisse.copy(deep=True),
            konfiguration,
            datensatz,
            daten.copy(deep=True),
            mappingtabelle,
            schema,
            lineage,
        )

    def fuer_projekt(self, projekt_id: UUID) -> list[EventLogArtefakt]:
        """Listet Event Logs eines Projekts."""
        return self._repository.fuer_projekt(projekt_id)

    def _integritaet_pruefen(self, artefakt: EventLogArtefakt) -> bytes:
        inhalt = self._artefakte.lesen(artefakt.relativer_csv_pfad)
        if hashlib.sha256(inhalt).hexdigest() != artefakt.sha256:
            raise Importintegritaetsfehler("Die Event-Log-Prüfsumme stimmt nicht überein.")
        try:
            gzip.decompress(inhalt)
            schema = json.loads(self._artefakte.lesen(artefakt.relativer_schema_pfad))
            lineage = json.loads(self._artefakte.lesen(artefakt.relativer_lineage_pfad))
            if schema.get("sha256") != artefakt.sha256:
                raise Importintegritaetsfehler(
                    "Schema und CSV.GZ des Event Logs sind inkonsistent."
                )
            if (
                lineage.get("projekt_id") != str(artefakt.projekt_id)
                or lineage.get("zwischendatensatz_id") != str(artefakt.zwischendatensatz_id)
                or lineage.get("mapping_id") != str(artefakt.mapping_id)
            ):
                raise Importintegritaetsfehler("Lineage und Event-Log-Metadaten sind inkonsistent.")
        except Importintegritaetsfehler:
            raise
        except (gzip.BadGzipFile, json.JSONDecodeError, UnicodeDecodeError) as fehler:
            raise Importintegritaetsfehler("Die Event-Log-Artefakte sind inkonsistent.") from fehler
        return inhalt
