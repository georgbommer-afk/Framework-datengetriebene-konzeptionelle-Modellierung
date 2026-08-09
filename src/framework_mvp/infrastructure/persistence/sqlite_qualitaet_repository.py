"""SQLite-Persistenz von E*-Freigaben und getrennten Legacy-Prüfungen."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import UUID

from framework_mvp.domain.models import (
    Freigabestatus,
    Mappingzustand,
    Qualitaetsfreigabe,
    Qualitaetsmassnahmenplan,
    QualitaetspruefungArtefakt,
    Qualitaetsregel,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class SQLiteQualitaetRepository:
    """Speichert neue Freigaben und vorhandene Legacy-Prüfungen getrennt."""

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

    def speichern(
        self,
        artefakt: QualitaetspruefungArtefakt,
        regeln: tuple[Qualitaetsregel, ...],
        plan: Qualitaetsmassnahmenplan,
        report: dict[str, object],
        vergleich: dict[str, object],
    ) -> None:
        """Speichert sämtliche Metadaten einer Qualitätsprüfung atomar."""
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                "INSERT OR IGNORE INTO qualitaetspruefungen VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(artefakt.quality_run_id),
                    str(artefakt.projekt_id),
                    str(artefakt.event_log_id),
                    json.dumps(report, ensure_ascii=False, default=str),
                    json.dumps(vergleich, ensure_ascii=False, default=str),
                    artefakt.relativer_report_pfad,
                    artefakt.relativer_massnahmen_pfad,
                    artefakt.relativer_csv_pfad,
                    artefakt.sha256,
                    artefakt.erstellt_am.isoformat(),
                ),
            )
            for regel in regeln:
                verbindung.execute(
                    "INSERT OR IGNORE INTO qualitaetsregeln VALUES (?, ?, ?)",
                    (
                        str(artefakt.quality_run_id),
                        regel.regel_id,
                        json.dumps(asdict(regel), ensure_ascii=False, default=str),
                    ),
                )
            for massnahme in plan.massnahmen:
                verbindung.execute(
                    "INSERT OR IGNORE INTO qualitaetsmassnahmen VALUES (?, ?, ?, ?)",
                    (
                        str(artefakt.quality_run_id),
                        str(massnahme.massnahme_id),
                        json.dumps(asdict(massnahme), ensure_ascii=False, default=str),
                        massnahme.reihenfolge,
                    ),
                )

    def laden(self, quality_run_id: UUID) -> QualitaetspruefungArtefakt | None:
        """Lädt die Artefaktmetadaten einer Qualitätsprüfung."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM qualitaetspruefungen WHERE quality_run_id=?",
                (str(quality_run_id),),
            ).fetchone()
        if zeile is None or self._ist_freigabe(zeile):
            return None
        return self._artefakt(zeile)

    def fuer_projekt(self, projekt_id: UUID) -> list[QualitaetspruefungArtefakt]:
        """Listet Qualitätsprüfungen eines Projekts stabil auf."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT * FROM qualitaetspruefungen WHERE projekt_id=? "
                "ORDER BY erstellt_am_utc, quality_run_id",
                (str(projekt_id),),
            ).fetchall()
        return [self._artefakt(zeile) for zeile in zeilen if not self._ist_freigabe(zeile)]

    def freigabe_speichern(
        self,
        freigabe: Qualitaetsfreigabe,
        report: dict[str, object],
        report_sha256: str,
    ) -> None:
        """Speichert E* ohne duplizierte oder veränderte Event-Log-CSV."""
        vergleich = {
            "artefaktart": "quality_gate_freigabe_e_stern",
            "report_sha256": report_sha256,
        }
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                "INSERT OR IGNORE INTO qualitaetspruefungen VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(freigabe.freigabe_id),
                    str(freigabe.projekt_id),
                    str(freigabe.event_log_id),
                    json.dumps(report, ensure_ascii=False, default=str),
                    json.dumps(vergleich, ensure_ascii=False),
                    freigabe.relativer_report_pfad,
                    "",
                    "",
                    freigabe.event_log_sha256,
                    freigabe.erstellt_am.isoformat(),
                ),
            )

    def freigabe_laden(self, freigabe_id: UUID) -> Qualitaetsfreigabe | None:
        """Lädt ausschließlich Metadaten einer neuen E*-Freigabe."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM qualitaetspruefungen WHERE quality_run_id=?",
                (str(freigabe_id),),
            ).fetchone()
        if zeile is None or not self._ist_freigabe(zeile):
            return None
        return self._freigabe(zeile)

    def freigaben_fuer_projekt(self, projekt_id: UUID) -> list[Qualitaetsfreigabe]:
        """Listet neue Freigaben stabil und ohne Legacy-Arbeitskopien."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT * FROM qualitaetspruefungen WHERE projekt_id=? "
                "ORDER BY erstellt_am_utc, quality_run_id",
                (str(projekt_id),),
            ).fetchall()
        return [self._freigabe(zeile) for zeile in zeilen if self._ist_freigabe(zeile)]

    @staticmethod
    def _ist_freigabe(zeile: sqlite3.Row) -> bool:
        try:
            return (
                json.loads(zeile["vergleich_json"]).get("artefaktart")
                == "quality_gate_freigabe_e_stern"
            )
        except (json.JSONDecodeError, TypeError):
            return False

    @staticmethod
    def _freigabe(zeile: sqlite3.Row) -> Qualitaetsfreigabe:
        report = json.loads(zeile["report_json"])
        struktur = report["freigabe"]
        vergleich = json.loads(zeile["vergleich_json"])
        return Qualitaetsfreigabe(
            UUID(struktur["freigabe_id"]),
            UUID(struktur["projekt_id"]),
            UUID(struktur["event_log_id"]),
            struktur["event_log_sha256"],
            UUID(struktur["zwischendatensatz_id"]),
            struktur["zwischendatensatz_sha256"],
            UUID(struktur["mapping_id"]),
            UUID(struktur["mappingtabelle_id"]) if struktur["mappingtabelle_id"] else None,
            struktur["mappingtabelle_sha256"],
            Mappingzustand(struktur["mappingzustand"]),
            tuple(UUID(wert) for wert in struktur["datenquellen_ids"]),
            struktur["datenquellen_snapshot_sha256"],
            struktur["konfiguration_sha256"],
            struktur["kettenfingerabdruck"],
            struktur["relativer_report_pfad"],
            vergleich["report_sha256"],
            Freigabestatus(struktur["status"]),
            datetime.fromisoformat(struktur["erstellt_am"]),
        )

    @staticmethod
    def _artefakt(zeile: sqlite3.Row) -> QualitaetspruefungArtefakt:
        return QualitaetspruefungArtefakt(
            UUID(zeile["quality_run_id"]),
            UUID(zeile["projekt_id"]),
            UUID(zeile["event_log_id"]),
            zeile["relativer_report_pfad"],
            zeile["relativer_massnahmen_pfad"],
            zeile["relativer_csv_pfad"],
            zeile["sha256"],
            datetime.fromisoformat(zeile["erstellt_am_utc"]),
        )
