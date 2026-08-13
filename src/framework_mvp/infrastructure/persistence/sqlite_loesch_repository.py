"""Explizite SQLite-Löschreihenfolge ohne pauschale Kaskaden."""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from framework_mvp.application.ports.loesch_repository import (
    LoeschRepository,
    ZwischendatensatzLoeschplan,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class SQLiteLoeschRepository(LoeschRepository):
    """Löscht ausschließlich zuvor projektgebunden aufgelöste Datensätze."""

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

    @staticmethod
    def _ids(
        verbindung: sqlite3.Connection, abfrage: str, parameter: Sequence[str]
    ) -> tuple[str, ...]:
        return tuple(str(zeile[0]) for zeile in verbindung.execute(abfrage, parameter))

    @staticmethod
    def _platzhalter(werte: Sequence[str]) -> str:
        return ",".join("?" for _ in werte)

    @classmethod
    def _pfade(
        cls,
        verbindung: sqlite3.Connection,
        tabelle: str,
        spalten: Sequence[str],
        id_spalte: str,
        ids: Sequence[str],
    ) -> list[str]:
        if not ids:
            return []
        abfrage = (
            f"SELECT {', '.join(spalten)} FROM {tabelle} "  # noqa: S608 - nur Konstanten
            f"WHERE {id_spalte} IN ({cls._platzhalter(ids)})"
        )
        return [
            str(wert) for zeile in verbindung.execute(abfrage, tuple(ids)) for wert in zeile if wert
        ]

    def zwischendatensatz_loeschplan(
        self, projekt_id: UUID, zwischendatensatz_id: UUID
    ) -> ZwischendatensatzLoeschplan | None:
        projekt, datensatz = str(projekt_id), str(zwischendatensatz_id)
        with self._verbindung() as verbindung:
            t = verbindung.execute(
                "SELECT transformationsplan_id, relativer_daten_pfad, relativer_schema_pfad, "
                "relativer_transformation_pfad FROM zwischendatensaetze "
                "WHERE projekt_id=? AND zwischendatensatz_id=?",
                (projekt, datensatz),
            ).fetchone()
            if t is None:
                return None
            mapping_ids = self._ids(
                verbindung,
                "SELECT mapping_id FROM semantische_mappings WHERE projekt_id=? "
                "AND zwischendatensatz_id=?",
                (projekt, datensatz),
            )
            event_ids = self._ids(
                verbindung,
                "SELECT event_log_id FROM event_logs WHERE projekt_id=? AND zwischendatensatz_id=?",
                (projekt, datensatz),
            )
            quality_ids = self._abhaengige_ids(
                verbindung, "qualitaetspruefungen", "quality_run_id", "event_log_id", event_ids
            )
            analyse_ids = self._abhaengige_ids(
                verbindung,
                "process_mining_analysen",
                "analyse_id",
                "qualitaetspruefung_id",
                quality_ids,
            )
            aggregations_ids = self._abhaengige_ids(
                verbindung, "ergebnisaggregationen", "aggregations_id", "analyse_id", analyse_ids
            )
            ableitungs_ids = self._abhaengige_ids(
                verbindung,
                "modellableitungen",
                "modellableitungs_id",
                "aggregations_id",
                aggregations_ids,
            )
            validierungs_ids = self._abhaengige_ids(
                verbindung,
                "modellvalidierungen",
                "validierungslauf_id",
                "modellableitungs_id",
                ableitungs_ids,
            )
            pfade = [str(t[1]), str(t[2]), str(t[3])]
            pfade += self._pfade(
                verbindung,
                "semantische_mappings",
                ("relativer_mapping_pfad",),
                "mapping_id",
                mapping_ids,
            )
            pfade += self._pfade(
                verbindung,
                "mappingtabellen",
                ("relativer_mapping_pfad",),
                "zwischendatensatz_id",
                (datensatz,),
            )
            pfade += self._pfade(
                verbindung,
                "event_logs",
                (
                    "relativer_csv_pfad",
                    "relativer_schema_pfad",
                    "relativer_lineage_pfad",
                    "relativer_xes_pfad",
                ),
                "event_log_id",
                event_ids,
            )
            pfade += self._pfade(
                verbindung,
                "qualitaetspruefungen",
                ("relativer_report_pfad", "relativer_massnahmen_pfad", "relativer_csv_pfad"),
                "quality_run_id",
                quality_ids,
            )
            pfade += self._pfade(
                verbindung,
                "process_mining_analysen",
                (
                    "relativer_ergebnis_pfad",
                    "relativer_varianten_pfad",
                    "relativer_dfg_pfad",
                    "relativer_modell_pfad",
                    "relativer_visualisierung_pfad",
                ),
                "analyse_id",
                analyse_ids,
            )
            pfade += self._pfade(
                verbindung,
                "ergebnisaggregationen",
                ("relativer_aggregations_pfad",),
                "aggregations_id",
                aggregations_ids,
            )
            pfade += self._pfade(
                verbindung,
                "modellableitungen",
                ("relativer_k_pfad", "relativer_o_pfad"),
                "modellableitungs_id",
                ableitungs_ids,
            )
            pfade += self._pfade(
                verbindung,
                "modellvalidierungen",
                ("relativer_k_stern_pfad",),
                "validierungslauf_id",
                validierungs_ids,
            )
            return ZwischendatensatzLoeschplan(UUID(t[0]), tuple(dict.fromkeys(pfade)))

    @classmethod
    def _abhaengige_ids(
        cls,
        verbindung: sqlite3.Connection,
        tabelle: str,
        zielspalte: str,
        fremdspalte: str,
        ids: Sequence[str],
    ) -> tuple[str, ...]:
        if not ids:
            return ()
        return cls._ids(
            verbindung,
            f"SELECT {zielspalte} FROM {tabelle} "  # noqa: S608 - nur interne Konstanten
            f"WHERE {fremdspalte} IN ({cls._platzhalter(ids)})",
            tuple(ids),
        )

    @staticmethod
    def _loesche_ids(
        verbindung: sqlite3.Connection,
        tabelle: str,
        id_spalte: str,
        ids: Sequence[str],
    ) -> None:
        if ids:
            verbindung.execute(
                f"DELETE FROM {tabelle} WHERE {id_spalte} IN "  # noqa: S608
                f"({SQLiteLoeschRepository._platzhalter(ids)})",
                tuple(ids),
            )

    def zwischendatensatz_loeschen(
        self, projekt_id: UUID, zwischendatensatz_id: UUID, transformationsplan_id: UUID
    ) -> None:
        projekt, datensatz = str(projekt_id), str(zwischendatensatz_id)
        with self._verbindung() as verbindung, verbindung:
            zeile = verbindung.execute(
                "SELECT transformationsplan_id FROM zwischendatensaetze "
                "WHERE projekt_id=? AND zwischendatensatz_id=?",
                (projekt, datensatz),
            ).fetchone()
            if zeile is None or zeile[0] != str(transformationsplan_id):
                raise Domaenenfehler("Der Zwischendatensatz gehört nicht zum gewählten Projekt.")
            event_ids = self._ids(
                verbindung,
                "SELECT event_log_id FROM event_logs WHERE projekt_id=? AND zwischendatensatz_id=?",
                (projekt, datensatz),
            )
            quality_ids = self._abhaengige_ids(
                verbindung, "qualitaetspruefungen", "quality_run_id", "event_log_id", event_ids
            )
            analyse_ids = self._abhaengige_ids(
                verbindung,
                "process_mining_analysen",
                "analyse_id",
                "qualitaetspruefung_id",
                quality_ids,
            )
            aggregations_ids = self._abhaengige_ids(
                verbindung, "ergebnisaggregationen", "aggregations_id", "analyse_id", analyse_ids
            )
            ableitungs_ids = self._abhaengige_ids(
                verbindung,
                "modellableitungen",
                "modellableitungs_id",
                "aggregations_id",
                aggregations_ids,
            )
            validierungs_ids = self._abhaengige_ids(
                verbindung,
                "modellvalidierungen",
                "validierungslauf_id",
                "modellableitungs_id",
                ableitungs_ids,
            )
            self._loesche_ids(
                verbindung, "modellvalidierungen", "validierungslauf_id", validierungs_ids
            )
            self._loesche_ids(
                verbindung, "modellableitungen", "modellableitungs_id", ableitungs_ids
            )
            self._loesche_ids(
                verbindung, "ergebnisaggregationen", "aggregations_id", aggregations_ids
            )
            self._loesche_ids(verbindung, "process_mining_analysen", "analyse_id", analyse_ids)
            self._loesche_ids(verbindung, "qualitaetsregeln", "quality_run_id", quality_ids)
            self._loesche_ids(verbindung, "qualitaetsmassnahmen", "quality_run_id", quality_ids)
            self._loesche_ids(verbindung, "qualitaetspruefungen", "quality_run_id", quality_ids)
            self._loesche_ids(verbindung, "event_logs", "event_log_id", event_ids)
            verbindung.execute(
                "DELETE FROM semantische_mappings WHERE projekt_id=? AND zwischendatensatz_id=?",
                (projekt, datensatz),
            )
            verbindung.execute(
                "DELETE FROM mappingtabellen WHERE projekt_id=? AND zwischendatensatz_id=?",
                (projekt, datensatz),
            )
            geloescht = verbindung.execute(
                "DELETE FROM zwischendatensaetze WHERE projekt_id=? AND zwischendatensatz_id=?",
                (projekt, datensatz),
            ).rowcount
            if geloescht != 1:
                raise Domaenenfehler(
                    "Der Zwischendatensatz konnte nicht eindeutig gelöscht werden."
                )
            rest = verbindung.execute(
                "SELECT 1 FROM zwischendatensaetze WHERE transformationsplan_id=? LIMIT 1",
                (str(transformationsplan_id),),
            ).fetchone()
            if rest is None:
                verbindung.execute(
                    "DELETE FROM transformationsplaene WHERE projekt_id=? "
                    "AND transformationsplan_id=?",
                    (projekt, str(transformationsplan_id)),
                )

    def projekt_loeschen(self, projekt_id: UUID) -> bool:
        projekt = str(projekt_id)
        with self._verbindung() as verbindung, verbindung:
            vorhanden = verbindung.execute(
                "SELECT 1 FROM projekte WHERE projekt_id=?", (projekt,)
            ).fetchone()
            if vorhanden is None:
                return False
            quality_ids = self._ids(
                verbindung,
                "SELECT quality_run_id FROM qualitaetspruefungen WHERE projekt_id=?",
                (projekt,),
            )
            self._loesche_ids(verbindung, "qualitaetsregeln", "quality_run_id", quality_ids)
            self._loesche_ids(verbindung, "qualitaetsmassnahmen", "quality_run_id", quality_ids)
            for tabelle in (
                "modellvalidierungen",
                "modellableitungen",
                "ergebnisaggregationen",
                "process_mining_analysen",
                "qualitaetspruefungen",
                "event_logs",
                "semantische_mappings",
                "mappingtabellen",
                "zwischendatensaetze",
                "transformationsplaene",
                "importvorgaenge",
                "datenquellen",
            ):
                verbindung.execute(f"DELETE FROM {tabelle} WHERE projekt_id=?", (projekt,))  # noqa: S608
            return (
                verbindung.execute("DELETE FROM projekte WHERE projekt_id=?", (projekt,)).rowcount
                == 1
            )
