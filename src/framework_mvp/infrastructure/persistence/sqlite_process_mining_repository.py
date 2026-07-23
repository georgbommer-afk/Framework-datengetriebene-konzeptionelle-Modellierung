"""SQLite-Persistenz für Process-Mining-Analysen."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from framework_mvp.domain.models import (
    DiscoveryVerfahren,
    ProcessMiningAnalyse,
    ProcessMiningStatus,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class SQLiteProcessMiningRepository:
    """Speichert Analysemetadaten transaktional."""

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

    def speichern(self, analyse: ProcessMiningAnalyse) -> None:
        """Speichert eine Analyse idempotent."""
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                "INSERT OR IGNORE INTO process_mining_analysen VALUES "
                f"({','.join('?' for _ in range(27))})",
                (
                    str(analyse.analyse_id),
                    str(analyse.projekt_id),
                    str(analyse.qualitaetspruefung_id),
                    str(analyse.event_log_id),
                    analyse.konfiguration_json,
                    analyse.filter_json,
                    analyse.discovery_verfahren.value,
                    analyse.parameter_json,
                    analyse.ereignisanzahl_vorher,
                    analyse.fallanzahl_vorher,
                    analyse.aktivitaetsanzahl_vorher,
                    analyse.variantenanzahl_vorher,
                    analyse.ereignisanzahl_nachher,
                    analyse.fallanzahl_nachher,
                    analyse.aktivitaetsanzahl_nachher,
                    analyse.variantenanzahl_nachher,
                    analyse.modellstatistik_json,
                    analyse.warnungen_json,
                    analyse.pm4py_version,
                    analyse.relativer_ergebnis_pfad,
                    analyse.relativer_varianten_pfad,
                    analyse.relativer_dfg_pfad,
                    analyse.relativer_modell_pfad,
                    analyse.relativer_visualisierung_pfad,
                    analyse.status.value,
                    analyse.erstellt_am.isoformat(),
                    analyse.geaendert_am.isoformat(),
                ),
            )

    def laden(self, analyse_id: UUID) -> ProcessMiningAnalyse | None:
        """Lädt eine Analyse."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM process_mining_analysen WHERE analyse_id=?",
                (str(analyse_id),),
            ).fetchone()
        return None if zeile is None else self._analyse(zeile)

    def fuer_projekt(self, projekt_id: UUID) -> list[ProcessMiningAnalyse]:
        """Listet Analysen eines Projekts stabil auf."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT * FROM process_mining_analysen WHERE projekt_id=? "
                "ORDER BY erstellt_am_utc, analyse_id",
                (str(projekt_id),),
            ).fetchall()
        return [self._analyse(zeile) for zeile in zeilen]

    @staticmethod
    def _analyse(zeile: sqlite3.Row) -> ProcessMiningAnalyse:
        return ProcessMiningAnalyse(
            UUID(zeile["analyse_id"]),
            UUID(zeile["projekt_id"]),
            UUID(zeile["qualitaetspruefung_id"]),
            UUID(zeile["event_log_id"]),
            zeile["konfiguration_json"],
            zeile["filter_json"],
            DiscoveryVerfahren(zeile["discovery_verfahren"]),
            zeile["parameter_json"],
            zeile["ereignisanzahl_vorher"],
            zeile["fallanzahl_vorher"],
            zeile["aktivitaetsanzahl_vorher"],
            zeile["variantenanzahl_vorher"],
            zeile["ereignisanzahl_nachher"],
            zeile["fallanzahl_nachher"],
            zeile["aktivitaetsanzahl_nachher"],
            zeile["variantenanzahl_nachher"],
            zeile["modellstatistik_json"],
            zeile["warnungen_json"],
            zeile["pm4py_version"],
            zeile["relativer_ergebnis_pfad"],
            zeile["relativer_varianten_pfad"],
            zeile["relativer_dfg_pfad"],
            zeile["relativer_modell_pfad"],
            zeile["relativer_visualisierung_pfad"],
            ProcessMiningStatus(zeile["status"]),
            datetime.fromisoformat(zeile["erstellt_am_utc"]),
            datetime.fromisoformat(zeile["geaendert_am_utc"]),
        )
