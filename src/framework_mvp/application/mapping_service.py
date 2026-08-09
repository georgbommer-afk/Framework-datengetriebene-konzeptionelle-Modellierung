"""Kompatible Persistenz der Event-Log-Konfiguration aus Schritt 4."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

import pandas as pd

from framework_mvp.application.mapping import MappingErgebnis, validiere_mapping
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.models import Mappingstatus, SemantischesMapping
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte.artefakt_speicher import (
    GespeichertesArtefakt,
    ImportartefaktSpeicher,
)
from framework_mvp.infrastructure.persistence.sqlite_mapping_repository import (
    SQLiteMappingRepository,
)

MAPPING_ARTEFAKT_VERSION = 2
UNTERSTUETZTE_MAPPING_ARTEFAKTVERSIONEN = {1, MAPPING_ARTEFAKT_VERSION}


def _json_kompatibel(wert: object) -> object:
    """Normalisiert Dataclasses, UUIDs und Zeitwerte wie das gespeicherte JSON."""
    return json.loads(json.dumps(wert, ensure_ascii=False, default=str))


class MappingService:
    """Historischer Servicename für Event-Log-Rollen- und Strukturkonfigurationen."""

    def __init__(
        self,
        repository: SQLiteMappingRepository,
        transformations_service: TransformationsService,
        artefakte: ImportartefaktSpeicher,
    ) -> None:
        self._repository = repository
        self._transformations_service = transformations_service
        self._artefakte = artefakte

    def datensatz_laden(self, datensatz_id: UUID) -> pd.DataFrame:
        """Lädt einen integritätsgeprüften Zwischendatensatz für das Mapping."""
        return self._transformations_service.zwischendatensatz_laden(datensatz_id)[1]

    def validieren(
        self, mapping: SemantischesMapping, daten: pd.DataFrame
    ) -> tuple[SemantischesMapping, MappingErgebnis]:
        """Validiert und ersetzt Status sowie Validierungsergebnis kontrolliert."""
        ergebnis = validiere_mapping(daten, mapping)
        status = (
            Mappingstatus.VALIDIERT if ergebnis.validierung.gueltig else Mappingstatus.UNGUELTIG
        )
        aktualisiert = replace(
            mapping,
            validierung=ergebnis.validierung,
            status=status,
            geaendert_am=datetime.now(UTC),
        )
        return aktualisiert, ergebnis

    def speichern(self, mapping: SemantischesMapping) -> str:
        """Speichert Mapping-JSON atomar und Metadaten anschließend in SQLite."""
        if mapping.status is not Mappingstatus.VALIDIERT:
            raise Importintegritaetsfehler(
                "Nur eine fachlich validierte Event-Log-Konfiguration kann gespeichert werden."
            )
        datensatz, daten = self._transformations_service.zwischendatensatz_laden(
            mapping.zwischendatensatz_id
        )
        if datensatz.projekt_id != mapping.projekt_id:
            raise Importintegritaetsfehler(
                "Event-Log-Konfiguration und Zwischendatensatz gehören nicht zum selben Projekt."
            )
        if not validiere_mapping(daten, mapping).validierung.gueltig:
            raise Importintegritaetsfehler(
                "Die Event-Log-Konfiguration ist für ihren gespeicherten Zwischendatensatz "
                "nicht gültig."
            )
        relativer_pfad = (
            PurePosixPath("projects")
            / str(mapping.projekt_id)
            / "mappings"
            / f"{mapping.mapping_id}.json"
        ).as_posix()
        struktur = {
            "artefakt_version": MAPPING_ARTEFAKT_VERSION,
            "mapping": asdict(mapping),
        }
        inhalt = json.dumps(
            struktur, ensure_ascii=False, sort_keys=True, indent=2, default=str
        ).encode()
        vorher = self._artefakte.artefakt_ersetzen(relativer_pfad, inhalt)
        try:
            json.loads(self._artefakte.lesen(relativer_pfad))
            self._repository.speichern(mapping, relativer_pfad)
        except Exception:
            if vorher is None:
                self._artefakte.neu_erstelltes_artefakt_entfernen(
                    GespeichertesArtefakt(relativer_pfad, True)
                )
            else:
                self._artefakte.artefakt_ersetzen(relativer_pfad, vorher)
            raise
        return relativer_pfad

    def laden(self, mapping_id: UUID) -> SemantischesMapping | None:
        """Lädt Mapping und prüft Version sowie Projektpfad des JSON-Artefakts."""
        geladen = self._repository.laden(mapping_id)
        if geladen is None:
            return None
        mapping, pfad = geladen
        if not pfad.startswith(f"projects/{mapping.projekt_id}/mappings/"):
            raise Importintegritaetsfehler("Der Mappingpfad passt nicht zum Projekt.")
        struktur = json.loads(self._artefakte.lesen(pfad))
        artefakt_version = struktur.get("artefakt_version")
        if artefakt_version not in UNTERSTUETZTE_MAPPING_ARTEFAKTVERSIONEN:
            raise Importintegritaetsfehler("Die Mapping-Artefaktversion wird nicht unterstützt.")
        if artefakt_version == MAPPING_ARTEFAKT_VERSION and struktur.get(
            "mapping"
        ) != _json_kompatibel(asdict(mapping)):
            raise Importintegritaetsfehler(
                "Mapping-Artefakt und persistierte Event-Log-Konfiguration sind inkonsistent."
            )
        return mapping

    def fuer_projekt(self, projekt_id: UUID) -> list[SemantischesMapping]:
        """Listet alle kompatiblen Event-Log-Konfigurationen eines Projekts."""
        ergebnis: list[SemantischesMapping] = []
        for mapping, _ in self._repository.fuer_projekt(projekt_id):
            geladen = self.laden(mapping.mapping_id)
            if geladen is not None:
                ergebnis.append(geladen)
        return ergebnis


# Neuer fachlicher Name; MappingService bleibt für bestehende Aufrufer und Artefakte erhalten.
EventLogKonfigurationService = MappingService
