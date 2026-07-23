"""Persistenz und erneute Integritätsprüfung semantischer Mappings."""

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

MAPPING_ARTEFAKT_VERSION = 1


class MappingService:
    """Validiert, speichert und lädt Mappingkonfigurationen ohne Event-Log-Erzeugung."""

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
        if struktur.get("artefakt_version") != MAPPING_ARTEFAKT_VERSION:
            raise Importintegritaetsfehler("Die Mapping-Artefaktversion wird nicht unterstützt.")
        return mapping

    def fuer_projekt(self, projekt_id: UUID) -> list[SemantischesMapping]:
        """Listet alle Mappingkonfigurationen eines Projekts."""
        return [wert[0] for wert in self._repository.fuer_projekt(projekt_id)]
