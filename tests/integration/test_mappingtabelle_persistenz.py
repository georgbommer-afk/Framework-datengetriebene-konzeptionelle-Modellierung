"""Persistenz-, Integritäts- und Bindungstests für M aus Schritt 3."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
import pytest

from framework_mvp.application.mappingtabelle_service import MappingtabelleService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Mappingeintrag,
    Mappingtabelle,
    Projekt,
    Systemtyp,
    Transformationsplan,
    Untersuchungsauftrag,
    Zwischendatensatz,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.infrastructure.persistence.sqlite_etl_repository import SQLiteETLRepository
from framework_mvp.infrastructure.persistence.sqlite_mappingtabelle_repository import (
    SQLiteMappingtabelleRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.workspace import WorkspaceKonfiguration


class _Transformationen:
    def __init__(self, datensatz: Zwischendatensatz, daten: pd.DataFrame) -> None:
        self.datensatz = datensatz
        self.daten = daten

    def zwischendatensatz_laden(self, datensatz_id: UUID) -> tuple[Zwischendatensatz, pd.DataFrame]:
        if datensatz_id != self.datensatz.zwischendatensatz_id:
            raise Domaenenfehler("Der Zwischendatensatz wurde nicht gefunden.")
        return self.datensatz, self.daten.copy(deep=True)


def _service(
    tmp_path: Path,
) -> tuple[MappingtabelleService, Projekt, Zwischendatensatz, pd.DataFrame, Path]:
    db = tmp_path / "mapping.sqlite"
    workspace_pfad = tmp_path / "workspace"
    projekt = Projekt.neu(
        "Mappingtabelle",
        Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
    SQLiteProjektRepository(db).speichern(projekt)
    jetzt = datetime.now(UTC)
    plan = Transformationsplan(uuid4(), projekt.projekt_id, (uuid4(),), (), jetzt, jetzt)
    etl = SQLiteETLRepository(db)
    etl.plan_speichern(plan)
    daten = pd.DataFrame(
        {
            "t_pdno": [1001, 1002],
            "transaction": ["ticst0201m000", "ticst0201m000"],
            "status": [1, 2],
        }
    )
    datensatz = Zwischendatensatz(
        uuid4(),
        projekt.projekt_id,
        plan.transformationsplan_id,
        plan.import_ids,
        f"projects/{projekt.projekt_id}/interim/T.csv.gz",
        f"projects/{projekt.projekt_id}/interim/T.schema.json",
        f"projects/{projekt.projekt_id}/interim/T.transformation.json",
        "a" * 64,
        len(daten),
        len(daten.columns),
        jetzt,
    )
    etl.datensatz_speichern(datensatz)
    service = MappingtabelleService(
        SQLiteMappingtabelleRepository(db),
        _Transformationen(datensatz, daten),  # type: ignore[arg-type]
        ImportartefaktSpeicher(WorkspaceKonfiguration(workspace_pfad)),
    )
    return service, projekt, datensatz, daten, workspace_pfad


def test_befuelltes_m_wird_versioniert_gespeichert_und_vollstaendig_geladen(
    tmp_path: Path,
) -> None:
    service, projekt, datensatz, daten, workspace = _service(tmp_path)
    vorher = daten.copy(deep=True)
    mapping = Mappingtabelle.neu(projekt.projekt_id, datensatz.zwischendatensatz_id)
    mapping = mapping.eintrag_hinzufuegen(
        Mappingeintrag.fuer_spalte("t_pdno", "Produktionsauftrag")
    )
    mapping = mapping.eintrag_hinzufuegen(
        Mappingeintrag.fuer_wert("transaction", "ticst0201m000", "Produktionsauftrag abschließen")
    ).bestaetigen()

    pfad = service.speichern(mapping)
    assert service.speichern(mapping) == pfad

    assert service.laden(mapping.mapping_id) == mapping
    assert service.fuer_datensatz(projekt.projekt_id, datensatz.zwischendatensatz_id) == mapping
    assert service.fuer_datensatz(projekt.projekt_id, uuid4()) is None
    assert service.fuer_datensatz(uuid4(), datensatz.zwischendatensatz_id) is None
    assert service.fuer_projekt(projekt.projekt_id) == [mapping]
    pd.testing.assert_frame_equal(daten, vorher)
    struktur = json.loads((workspace / pfad).read_bytes())
    assert struktur["artefaktversion"] == 1
    assert struktur["artefaktart"] == "Mappingtabelle M"
    assert struktur["mappingtabelle"]["zwischendatensatz_id"] == str(datensatz.zwischendatensatz_id)


def test_leeres_bestaetigtes_m_ist_persistierbar(tmp_path: Path) -> None:
    service, projekt, datensatz, _, _ = _service(tmp_path)
    mapping = Mappingtabelle.neu(projekt.projekt_id, datensatz.zwischendatensatz_id).bestaetigen(
        kein_mapping_erforderlich=True
    )
    service.speichern(mapping)
    assert service.laden(mapping.mapping_id) == mapping


def test_nur_in_t_vorhandene_spalten_und_werte_koennen_gespeichert_werden(
    tmp_path: Path,
) -> None:
    service, projekt, datensatz, _, _ = _service(tmp_path)
    basis = Mappingtabelle.neu(projekt.projekt_id, datensatz.zwischendatensatz_id)
    falsche_spalte = basis.eintrag_hinzufuegen(
        Mappingeintrag.fuer_spalte("nicht_in_T", "Unbekannt")
    ).bestaetigen()
    with pytest.raises(Domaenenfehler, match="nicht vorhanden"):
        service.speichern(falsche_spalte)
    falscher_wert = basis.eintrag_hinzufuegen(
        Mappingeintrag.fuer_wert("status", 999, "Unbekannt")
    ).bestaetigen()
    with pytest.raises(Domaenenfehler, match="nicht vorhanden"):
        service.speichern(falscher_wert)


def test_projektbindung_und_eindeutigkeit_pro_t_werden_erzwungen(tmp_path: Path) -> None:
    service, projekt, datensatz, _, _ = _service(tmp_path)
    fremd = Mappingtabelle.neu(uuid4(), datensatz.zwischendatensatz_id).bestaetigen(
        kein_mapping_erforderlich=True
    )
    with pytest.raises(Domaenenfehler, match="selben Projekt"):
        service.speichern(fremd)

    erstes = Mappingtabelle.neu(projekt.projekt_id, datensatz.zwischendatensatz_id).bestaetigen(
        kein_mapping_erforderlich=True
    )
    service.speichern(erstes)
    zweites = Mappingtabelle.neu(projekt.projekt_id, datensatz.zwischendatensatz_id).bestaetigen(
        kein_mapping_erforderlich=True
    )
    with pytest.raises(Domaenenfehler, match="bereits eine andere"):
        service.speichern(zweites)


def test_manipuliertes_artefakt_wird_beim_laden_abgelehnt(tmp_path: Path) -> None:
    service, projekt, datensatz, _, workspace = _service(tmp_path)
    mapping = Mappingtabelle.neu(projekt.projekt_id, datensatz.zwischendatensatz_id).bestaetigen(
        kein_mapping_erforderlich=True
    )
    pfad = service.speichern(mapping)
    (workspace / pfad).write_text("{}", encoding="utf-8")
    with pytest.raises(Importintegritaetsfehler, match="Prüfsumme"):
        service.laden(mapping.mapping_id)


def test_nicht_unterstuetzte_mappingtabellen_version_wird_abgelehnt(
    tmp_path: Path,
) -> None:
    service, projekt, datensatz, _, workspace = _service(tmp_path)
    mapping = Mappingtabelle.neu(projekt.projekt_id, datensatz.zwischendatensatz_id).bestaetigen(
        kein_mapping_erforderlich=True
    )
    pfad = service.speichern(mapping)
    absolut = workspace / pfad
    struktur = json.loads(absolut.read_bytes())
    struktur["artefaktversion"] = 99
    inhalt = json.dumps(struktur, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    absolut.write_bytes(inhalt)
    with sqlite3.connect(tmp_path / "mapping.sqlite") as verbindung:
        verbindung.execute(
            "UPDATE mappingtabellen SET sha256=? WHERE mapping_id=?",
            (hashlib.sha256(inhalt).hexdigest(), str(mapping.mapping_id)),
        )
    with pytest.raises(Importintegritaetsfehler, match="Artefaktversion"):
        service.laden(mapping.mapping_id)


def test_alte_event_log_konfiguration_wird_nicht_als_m_geladen(tmp_path: Path) -> None:
    service, projekt, datensatz, _, _ = _service(tmp_path)
    jetzt = datetime.now(UTC).isoformat()
    with sqlite3.connect(tmp_path / "mapping.sqlite") as verbindung:
        verbindung.execute(
            "INSERT INTO semantische_mappings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                str(projekt.projekt_id),
                str(datensatz.zwischendatensatz_id),
                "{}",
                "{}",
                "entwurf",
                f"projects/{projekt.projekt_id}/mappings/legacy.json",
                jetzt,
                jetzt,
            ),
        )
    assert service.fuer_datensatz(projekt.projekt_id, datensatz.zwischendatensatz_id) is None
