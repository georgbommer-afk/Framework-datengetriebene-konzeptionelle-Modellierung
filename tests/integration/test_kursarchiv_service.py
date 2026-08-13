"""Kursarchive enthalten Projekte, aber keine lokal wirksamen Rechte oder Einladungen."""

import io
import sqlite3
import zipfile
from pathlib import Path

import pytest

from framework_mvp.application.autorisierung import AutorisierungsService
from framework_mvp.application.kursarchiv_service import KursarchivService
from framework_mvp.application.kursgruppen_service import EinladungsService, KursgruppenService
from framework_mvp.application.loesch_service import LoeschService
from framework_mvp.application.mandanten_projekt_service import MandantenProjektService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.projektarchiv_service import ProjektArchivService
from framework_mvp.domain.exceptions import ZugriffVerweigert
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
from framework_mvp.domain.models.zugriff import GlobaleRolle, Zugriffskontext
from framework_mvp.infrastructure.persistence.sqlite_loesch_repository import (
    SQLiteLoeschRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_zugriffs_repository import (
    SQLiteZugriffsRepository,
)
from framework_mvp.workspace import WorkspaceKonfiguration


def _dienste(db: Path, workspace: WorkspaceKonfiguration):
    zugriff = SQLiteZugriffsRepository(db)
    autorisierung = AutorisierungsService(zugriff)
    projekte = ProjektService(SQLiteProjektRepository(db))
    loeschen = LoeschService(SQLiteLoeschRepository(db), workspace)
    projektarchive = ProjektArchivService(db, workspace, zugriff, autorisierung)
    return (
        zugriff,
        autorisierung,
        projekte,
        KursarchivService(zugriff, autorisierung, projektarchive, projekte, loeschen),
    )


def test_kursarchiv_roundtrip_uebernimmt_keine_einladungen(tmp_path: Path) -> None:
    quelle_db = tmp_path / "quelle.sqlite"
    quelle_workspace = WorkspaceKonfiguration(tmp_path / "quelle")
    zugriff, autorisierung, projekte, kursarchive = _dienste(quelle_db, quelle_workspace)
    leitung = zugriff.oidc_benutzer_speichern(
        issuer="https://idp.example", subject="prof", email="prof@example.org", anzeigename="Prof"
    )
    zugriff.globale_rolle_setzen(
        leitung.benutzer_id, GlobaleRolle.GRUPPENLEITUNG, vergeben_von=None
    )
    kontext = Zugriffskontext.angemeldet(leitung.benutzer_id)
    gruppe = KursgruppenService(zugriff, autorisierung).gruppe_anlegen(
        kontext, bezeichnung="Lehrveranstaltung"
    )
    projekt = MandantenProjektService(projekte, zugriff, autorisierung).projekt_anlegen(
        kontext,
        gruppen_id=gruppe.gruppen_id,
        bezeichnung="Teamprojekt",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Problem", "Zweck", Systemtyp.PRODUKTION, "Grenze"
        ),
    )
    quelle_workspace.fuer_projekt_anlegen(projekt.projekt_id)
    EinladungsService(zugriff, autorisierung).erstellen(kontext, gruppe.gruppen_id)
    archiv = kursarchive.exportieren(kontext, gruppe.gruppen_id)
    with zipfile.ZipFile(io.BytesIO(archiv)) as zip_archiv:
        assert not any("einladung" in name.casefold() for name in zip_archiv.namelist())

    ziel_db = tmp_path / "ziel.sqlite"
    ziel_workspace = WorkspaceKonfiguration(tmp_path / "ziel")
    ziel_zugriff, _, _, ziel_kursarchive = _dienste(ziel_db, ziel_workspace)
    ziel_leitung = ziel_zugriff.oidc_benutzer_speichern(
        issuer="https://idp.example", subject="prof", email="neu@example.org", anzeigename="Prof"
    )
    ziel_zugriff.globale_rolle_setzen(
        ziel_leitung.benutzer_id, GlobaleRolle.GRUPPENLEITUNG, vergeben_von=None
    )
    importierte_gruppe = ziel_kursarchive.importieren(
        Zugriffskontext.angemeldet(ziel_leitung.benutzer_id), archiv
    )
    assert importierte_gruppe.gruppen_id == gruppe.gruppen_id
    assert len(ziel_zugriff.projekt_ids_fuer_gruppe(gruppe.gruppen_id)) == 1
    with sqlite3.connect(ziel_db) as verbindung:
        assert verbindung.execute("SELECT count(*) FROM gruppeneinladungen").fetchone()[0] == 0


def test_abweichende_leitungsidentitaet_wird_abgelehnt(tmp_path: Path) -> None:
    quelle_db = tmp_path / "quelle.sqlite"
    quelle_workspace = WorkspaceKonfiguration(tmp_path / "quelle")
    zugriff, autorisierung, _, kursarchive = _dienste(quelle_db, quelle_workspace)
    leitung = zugriff.oidc_benutzer_speichern(
        issuer="https://idp.example", subject="prof", email="prof@example.org", anzeigename="Prof"
    )
    zugriff.globale_rolle_setzen(
        leitung.benutzer_id, GlobaleRolle.GRUPPENLEITUNG, vergeben_von=None
    )
    kontext = Zugriffskontext.angemeldet(leitung.benutzer_id)
    gruppe = KursgruppenService(zugriff, autorisierung).gruppe_anlegen(kontext, bezeichnung="Kurs")
    archiv = kursarchive.exportieren(kontext, gruppe.gruppen_id)

    ziel_db = tmp_path / "ziel.sqlite"
    ziel_workspace = WorkspaceKonfiguration(tmp_path / "ziel")
    ziel_zugriff, _, _, ziel_kursarchive = _dienste(ziel_db, ziel_workspace)
    fremd = ziel_zugriff.oidc_benutzer_speichern(
        issuer="https://idp.example", subject="fremd", email="f@example.org", anzeigename="F"
    )
    ziel_zugriff.globale_rolle_setzen(
        fremd.benutzer_id, GlobaleRolle.GRUPPENLEITUNG, vergeben_von=None
    )
    with pytest.raises(ZugriffVerweigert):
        ziel_kursarchive.importieren(Zugriffskontext.angemeldet(fremd.benutzer_id), archiv)
