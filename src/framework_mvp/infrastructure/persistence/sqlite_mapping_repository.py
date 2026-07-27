"""SQLite-Repository für semantische Mappingmetadaten."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import UUID

from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    Attributrolle,
    Ereignisrolle,
    MappingModus,
    Mappingstatus,
    MappingValidierung,
    MappingWarnung,
    SemantischesMapping,
    Spaltenzuordnung,
    Warnungsstufe,
    ZeitstempelZuordnung,
    ZusammengesetzteFallId,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class SQLiteMappingRepository:
    """Speichert Mappingkonfiguration und Validierung, jedoch keinen Event Log."""

    def __init__(self, datenbankpfad: Path | str = STANDARD_DATENBANKPFAD) -> None:
        self._datenbankpfad = Path(datenbankpfad)

    @contextmanager
    def _verbindung(self) -> Iterator[sqlite3.Connection]:
        self._datenbankpfad.parent.mkdir(parents=True, exist_ok=True)
        verbindung = sqlite3.connect(self._datenbankpfad)
        verbindung.row_factory = sqlite3.Row
        verbindung.execute("PRAGMA foreign_keys = ON")
        try:
            initialisiere_schema(verbindung)
            yield verbindung
        finally:
            verbindung.close()

    def speichern(self, mapping: SemantischesMapping, relativer_pfad: str) -> None:
        """Speichert oder aktualisiert ein Mapping transaktional."""
        mapping_json = json.dumps(asdict(mapping), ensure_ascii=False, default=str, sort_keys=True)
        validierung_json = json.dumps(
            asdict(mapping.validierung) if mapping.validierung else None,
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT INTO semantische_mappings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mapping_id) DO UPDATE SET
                    mapping_json=excluded.mapping_json,
                    validierung_json=excluded.validierung_json,
                    status=excluded.status,
                    relativer_mapping_pfad=excluded.relativer_mapping_pfad,
                    geaendert_am_utc=excluded.geaendert_am_utc
                """,
                (
                    str(mapping.mapping_id),
                    str(mapping.projekt_id),
                    str(mapping.zwischendatensatz_id),
                    mapping_json,
                    validierung_json,
                    mapping.status.value,
                    relativer_pfad,
                    mapping.erstellt_am.isoformat(),
                    mapping.geaendert_am.isoformat(),
                ),
            )

    def laden(self, mapping_id: UUID) -> tuple[SemantischesMapping, str] | None:
        """Lädt ein Mapping und den relativen Artefaktpfad."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM semantische_mappings WHERE mapping_id=?", (str(mapping_id),)
            ).fetchone()
        return None if zeile is None else (self._mapping(zeile), zeile["relativer_mapping_pfad"])

    def fuer_projekt(self, projekt_id: UUID) -> list[tuple[SemantischesMapping, str]]:
        """Listet Mappings eines Projekts stabil auf."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT * FROM semantische_mappings WHERE projekt_id=? "
                "ORDER BY erstellt_am_utc, mapping_id",
                (str(projekt_id),),
            ).fetchall()
        return [(self._mapping(zeile), zeile["relativer_mapping_pfad"]) for zeile in zeilen]

    @staticmethod
    def _mapping(zeile: sqlite3.Row) -> SemantischesMapping:
        struktur = json.loads(zeile["mapping_json"])
        validierung_roh = json.loads(zeile["validierung_json"])
        validierung = None
        if validierung_roh:
            warnungen = tuple(
                MappingWarnung(
                    Warnungsstufe(wert["stufe"]), wert["code"], wert["meldung"], wert["anzahl"]
                )
                for wert in validierung_roh["warnungen"]
            )
            validierung = MappingValidierung(
                **{name: wert for name, wert in validierung_roh.items() if name != "warnungen"},
                warnungen=warnungen,
            )
        zuordnungen = tuple(
            Spaltenzuordnung(
                wert["spaltenname"],
                Ereignisrolle(wert["rolle"])
                if wert["rolle"] in {rolle.value for rolle in Ereignisrolle}
                else Attributrolle(wert["rolle"]),
            )
            for wert in struktur["spaltenzuordnungen"]
        )
        aktivitaetsdefinition_roh = struktur.get("aktivitaetsdefinition")
        aktivitaetsdefinition = (
            Aktivitaetsdefinition(
                bildungsart=Aktivitaetsbildungsart(aktivitaetsdefinition_roh["bildungsart"]),
                quellspalten=tuple(aktivitaetsdefinition_roh["quellspalten"]),
                trennzeichen=aktivitaetsdefinition_roh.get("trennzeichen", ""),
                praefix=aktivitaetsdefinition_roh.get("praefix", ""),
                suffix=aktivitaetsdefinition_roh.get("suffix", ""),
                fehlwertstrategie=aktivitaetsdefinition_roh.get(
                    "fehlwertstrategie",
                    "Nur vorhandene Bestandteile kombinieren",
                ),
                ersatztext=aktivitaetsdefinition_roh.get("ersatztext", ""),
            )
            if aktivitaetsdefinition_roh
            else None
        )
        return SemantischesMapping(
            UUID(struktur["mapping_id"]),
            UUID(struktur["projekt_id"]),
            UUID(struktur["zwischendatensatz_id"]),
            MappingModus(struktur["mapping_modus"]),
            ZusammengesetzteFallId(
                tuple(struktur["fall_id"]["spalten"]), struktur["fall_id"]["trennzeichen"]
            ),
            struktur["aktivitaetsspalte"],
            struktur["zeitstempelspalte"],
            struktur["startzeitstempelspalte"],
            struktur["endzeitstempelspalte"],
            struktur["lifecycle_spalte"],
            struktur["ressourcen_spalte"],
            zuordnungen,
            tuple(ZeitstempelZuordnung(**wert) for wert in struktur["zeitstempelzuordnungen"]),
            validierung,
            datetime.fromisoformat(struktur["erstellt_am"]),
            datetime.fromisoformat(struktur["geaendert_am"]),
            Mappingstatus(struktur["status"]),
            aktivitaetsdefinition,
        )
