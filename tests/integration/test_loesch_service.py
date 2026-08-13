"""Integrationsprüfungen der kontrollierten T- und Projektlöschung."""

import sqlite3
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

from framework_mvp.application.loesch_service import LoeschService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.infrastructure.persistence.sqlite_loesch_repository import (
    SQLiteLoeschRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema
from framework_mvp.workspace import WorkspaceKonfiguration

HASH = "a" * 64


def _projekt_einfuegen(verbindung: sqlite3.Connection, projekt_id: UUID, name: str) -> None:
    verbindung.execute(
        "INSERT INTO projekte VALUES (?, ?, '[]', 'aktiv', ?, ?, '{}')",
        (str(projekt_id), name, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )


def _datei(workspace: Path, relativ: str) -> None:
    pfad = workspace / relativ
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(relativ, encoding="utf-8")


def _vollstaendige_kette(
    verbindung: sqlite3.Connection, workspace: Path, projekt_id: UUID
) -> dict[str, UUID | list[str]]:
    ids: dict[str, UUID | list[str]] = {
        name: uuid4()
        for name in (
            "quelle",
            "import",
            "plan",
            "t",
            "sem_mapping",
            "mappingtabelle",
            "event",
            "quality",
            "analyse",
            "aggregation",
            "ableitung",
            "k",
            "o",
            "validierung",
            "k_stern",
        )
    }
    basis = f"projects/{projekt_id}"
    raw = f"{basis}/raw/import.csv"
    profil = f"{basis}/profiles/profil.json"
    artefakte = [
        f"{basis}/interim/t.csv.gz",
        f"{basis}/interim/t.schema.json",
        f"{basis}/interim/t.lineage.json",
        f"{basis}/mappings/sem.json",
        f"{basis}/mappings/m.json",
        f"{basis}/event_logs/e.csv.gz",
        f"{basis}/event_logs/e.schema.json",
        f"{basis}/event_logs/e.lineage.json",
        f"{basis}/event_logs/e.xes",
        f"{basis}/quality/report.json",
        f"{basis}/quality/massnahmen.json",
        f"{basis}/quality/e-star.csv.gz",
        f"{basis}/process_mining/ergebnis.json",
        f"{basis}/process_mining/varianten.json",
        f"{basis}/process_mining/dfg.json",
        f"{basis}/process_mining/modell.pnml",
        f"{basis}/process_mining/modell.svg",
        f"{basis}/aggregations/a-g.json",
        f"{basis}/model_derivations/k.json",
        f"{basis}/model_derivations/o.json",
        f"{basis}/model_validations/k-star.json",
    ]
    for pfad in [raw, profil, *artefakte]:
        _datei(workspace, pfad)
    jetzt = "2026-01-01T00:00:00+00:00"
    verbindung.execute(
        "INSERT INTO datenquellen VALUES (?, ?, 'Q', 'erp_system', '', '', '', 'csv', "
        "'[]', '[]', ?, ?)",
        (str(ids["quelle"]), str(projekt_id), jetzt, jetzt),
    )
    verbindung.execute(
        "INSERT INTO importvorgaenge VALUES (?, ?, ?, 'import.csv', 'import.csv', 'CSV', 1, "
        "?, '{}', 'Tabelle', 1, 1, 1, ?, ?, '{}', '[]', 'bestaetigt', ?, ?)",
        (
            str(ids["import"]),
            str(projekt_id),
            str(ids["quelle"]),
            HASH,
            raw,
            profil,
            jetzt,
            jetzt,
        ),
    )
    verbindung.execute(
        "INSERT INTO transformationsplaene VALUES (?, ?, '[]', '{}', ?, ?)",
        (str(ids["plan"]), str(projekt_id), jetzt, jetzt),
    )
    verbindung.execute(
        "INSERT INTO zwischendatensaetze VALUES (?, ?, ?, '[]', ?, ?, ?, ?, 1, 1, ?)",
        (
            str(ids["t"]),
            str(projekt_id),
            str(ids["plan"]),
            *artefakte[:3],
            HASH,
            jetzt,
        ),
    )
    verbindung.execute(
        "INSERT INTO semantische_mappings VALUES (?, ?, ?, '{}', '{}', 'validiert', ?, ?, ?)",
        (str(ids["sem_mapping"]), str(projekt_id), str(ids["t"]), artefakte[3], jetzt, jetzt),
    )
    verbindung.execute(
        "INSERT INTO mappingtabellen VALUES (?, ?, ?, '{}', 'bestaetigt', ?, ?, ?, ?)",
        (
            str(ids["mappingtabelle"]),
            str(projekt_id),
            str(ids["t"]),
            artefakte[4],
            HASH,
            jetzt,
            jetzt,
        ),
    )
    verbindung.execute(
        "INSERT INTO event_logs VALUES "
        "(?, ?, ?, ?, 'erzeugt', 1, 1, 1, NULL, NULL, ?, ?, ?, ?, ?, ?)",
        (
            str(ids["event"]),
            str(projekt_id),
            str(ids["t"]),
            str(ids["sem_mapping"]),
            *artefakte[5:9],
            HASH,
            jetzt,
        ),
    )
    verbindung.execute(
        "INSERT INTO qualitaetspruefungen VALUES (?, ?, ?, '{}', '{}', ?, ?, ?, ?, ?)",
        (
            str(ids["quality"]),
            str(projekt_id),
            str(ids["event"]),
            *artefakte[9:12],
            HASH,
            jetzt,
        ),
    )
    verbindung.execute(
        "INSERT INTO qualitaetsregeln VALUES (?, 'regel', '{}')",
        (str(ids["quality"]),),
    )
    verbindung.execute(
        "INSERT INTO qualitaetsmassnahmen VALUES (?, 'massnahme', '{}', 1)",
        (str(ids["quality"]),),
    )
    verbindung.execute(
        "INSERT INTO process_mining_analysen VALUES (?, ?, ?, ?, '{}', '[]', "
        "'inductive_miner', '{}', 1, 1, 1, 1, 1, 1, 1, 1, '{}', '[]', '1', "
        "?, ?, ?, ?, ?, 'ausgefuehrt', ?, ?)",
        (
            str(ids["analyse"]),
            str(projekt_id),
            str(ids["quality"]),
            str(ids["event"]),
            *artefakte[12:17],
            jetzt,
            jetzt,
        ),
    )
    verbindung.execute(
        "INSERT INTO ergebnisaggregationen VALUES (?, ?, 'spez', ?, ?, ?, ?, ?, ?, ?, "
        "'gespeichert', ?)",
        (
            str(ids["aggregation"]),
            str(projekt_id),
            str(ids["quality"]),
            str(ids["event"]),
            str(ids["analyse"]),
            HASH,
            HASH,
            artefakte[17],
            HASH,
            jetzt,
        ),
    )
    verbindung.execute(
        "INSERT INTO modellableitungen VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, "
        "'gespeichert', ?)",
        (
            str(ids["ableitung"]),
            str(ids["k"]),
            str(ids["o"]),
            str(projekt_id),
            str(ids["aggregation"]),
            str(ids["analyse"]),
            str(ids["event"]),
            HASH,
            HASH,
            artefakte[18],
            HASH,
            artefakte[19],
            HASH,
            jetzt,
        ),
    )
    verbindung.execute(
        "INSERT INTO modellvalidierungen VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "'fachlich_validiert', ?)",
        (
            str(ids["validierung"]),
            str(ids["k_stern"]),
            str(projekt_id),
            str(ids["ableitung"]),
            str(ids["k"]),
            str(ids["o"]),
            HASH,
            HASH,
            artefakte[20],
            HASH,
            jetzt,
        ),
    )
    ids["artefakte"] = artefakte
    ids["raw_pfade"] = [raw, profil]
    return ids


def _vorbereiten(tmp_path: Path) -> tuple[Path, Path, UUID, UUID, dict[str, UUID | list[str]]]:
    workspace, datenbank = tmp_path / "workspace", tmp_path / "db.sqlite"
    projekt_id, fremdes_projekt_id = uuid4(), uuid4()
    with sqlite3.connect(datenbank) as verbindung:
        verbindung.execute("PRAGMA foreign_keys = ON")
        initialisiere_schema(verbindung)
        _projekt_einfuegen(verbindung, projekt_id, "Ziel")
        _projekt_einfuegen(verbindung, fremdes_projekt_id, "Fremd")
        ids = _vollstaendige_kette(verbindung, workspace, projekt_id)
    _datei(workspace, f"projects/{fremdes_projekt_id}/raw/unberuehrt.csv")
    return workspace, datenbank, projekt_id, fremdes_projekt_id, ids


def test_t_loeschung_entfernt_kette_aber_behaelt_raw_und_fremdes_projekt(
    tmp_path: Path,
) -> None:
    workspace, datenbank, projekt_id, fremdes_projekt_id, ids = _vorbereiten(tmp_path)
    service = LoeschService(
        SQLiteLoeschRepository(datenbank), WorkspaceKonfiguration.ermitteln(workspace)
    )

    service.zwischendatensatz_loeschen(projekt_id, cast(UUID, ids["t"]))

    for pfad in cast(list[str], ids["artefakte"]):
        assert not (workspace / pfad).exists()
    for pfad in cast(list[str], ids["raw_pfade"]):
        assert (workspace / pfad).is_file()
    assert (workspace / f"projects/{fremdes_projekt_id}/raw/unberuehrt.csv").is_file()
    with sqlite3.connect(datenbank) as verbindung:
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
        ):
            assert verbindung.execute(f"SELECT COUNT(*) FROM {tabelle}").fetchone()[0] == 0
        assert verbindung.execute("SELECT COUNT(*) FROM importvorgaenge").fetchone()[0] == 1
        assert verbindung.execute("SELECT COUNT(*) FROM datenquellen").fetchone()[0] == 1
        assert (
            verbindung.execute(
                "SELECT COUNT(*) FROM projekte WHERE projekt_id=?", (str(fremdes_projekt_id),)
            ).fetchone()[0]
            == 1
        )


def test_datenbankfehler_rollt_dateistaging_und_transaktion_zurueck(tmp_path: Path) -> None:
    workspace, datenbank, projekt_id, _, ids = _vorbereiten(tmp_path)
    with sqlite3.connect(datenbank) as verbindung:
        verbindung.execute(
            "CREATE TRIGGER t_loeschen_verhindern BEFORE DELETE ON zwischendatensaetze "
            "BEGIN SELECT RAISE(ABORT, 'simulierter Fehler'); END"
        )
    service = LoeschService(
        SQLiteLoeschRepository(datenbank), WorkspaceKonfiguration.ermitteln(workspace)
    )

    with pytest.raises(sqlite3.IntegrityError, match="simulierter Fehler"):
        service.zwischendatensatz_loeschen(projekt_id, cast(UUID, ids["t"]))

    for pfad in cast(list[str], ids["artefakte"]):
        assert (workspace / pfad).is_file()
    with sqlite3.connect(datenbank) as verbindung:
        assert verbindung.execute("SELECT COUNT(*) FROM zwischendatensaetze").fetchone()[0] == 1
        assert verbindung.execute("SELECT COUNT(*) FROM modellvalidierungen").fetchone()[0] == 1


def test_projektloeschung_entfernt_nur_gewaehltes_projekt(tmp_path: Path) -> None:
    workspace, datenbank, projekt_id, fremdes_projekt_id, _ = _vorbereiten(tmp_path)
    service = LoeschService(
        SQLiteLoeschRepository(datenbank), WorkspaceKonfiguration.ermitteln(workspace)
    )

    service.projekt_loeschen(projekt_id)

    assert not (workspace / f"projects/{projekt_id}").exists()
    assert (workspace / f"projects/{fremdes_projekt_id}/raw/unberuehrt.csv").is_file()
    with sqlite3.connect(datenbank) as verbindung:
        assert (
            verbindung.execute(
                "SELECT COUNT(*) FROM projekte WHERE projekt_id=?", (str(projekt_id),)
            ).fetchone()[0]
            == 0
        )
        assert (
            verbindung.execute(
                "SELECT COUNT(*) FROM projekte WHERE projekt_id=?", (str(fremdes_projekt_id),)
            ).fetchone()[0]
            == 1
        )


def test_t_loeschung_lehnt_projektfremde_artefaktpfade_ab(tmp_path: Path) -> None:
    workspace, datenbank, projekt_id, fremdes_projekt_id, ids = _vorbereiten(tmp_path)
    fremder_pfad = f"projects/{fremdes_projekt_id}/raw/unberuehrt.csv"
    with sqlite3.connect(datenbank) as verbindung:
        verbindung.execute(
            "UPDATE zwischendatensaetze SET relativer_daten_pfad=? WHERE zwischendatensatz_id=?",
            (fremder_pfad, str(cast(UUID, ids["t"]))),
        )
    service = LoeschService(
        SQLiteLoeschRepository(datenbank), WorkspaceKonfiguration.ermitteln(workspace)
    )

    with pytest.raises(Domaenenfehler, match="außerhalb eines Projekts"):
        service.zwischendatensatz_loeschen(projekt_id, cast(UUID, ids["t"]))

    assert (workspace / fremder_pfad).is_file()
    with sqlite3.connect(datenbank) as verbindung:
        assert verbindung.execute("SELECT COUNT(*) FROM zwischendatensaetze").fetchone()[0] == 1
        raw_pfad = cast(list[str], ids["raw_pfade"])[0]
        verbindung.execute(
            "UPDATE zwischendatensaetze SET relativer_daten_pfad=? WHERE zwischendatensatz_id=?",
            (raw_pfad, str(cast(UUID, ids["t"]))),
        )

    with pytest.raises(Domaenenfehler, match="Rohimporte"):
        service.zwischendatensatz_loeschen(projekt_id, cast(UUID, ids["t"]))
    assert (workspace / raw_pfad).is_file()
