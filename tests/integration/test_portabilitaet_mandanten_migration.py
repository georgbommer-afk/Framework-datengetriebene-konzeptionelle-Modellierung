"""Migration und serverseitige Mandantentrennung der Community-Cloud-Schicht."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from framework_mvp.application.autorisierung import AutorisierungsService, geheimnis_hash
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import ZugriffVerweigert
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
from framework_mvp.domain.models.zugriff import (
    GlobaleRolle,
    Gruppenmitgliedschaft,
    Gruppenrolle,
    Gruppenstatus,
    Kursgruppe,
    Mitgliedschaftsstatus,
    Projektaktion,
    Projektmitglied,
    Projektzugehoerigkeit,
    Projektzugriffsart,
    Zugriffskontext,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema
from framework_mvp.infrastructure.persistence.sqlite_zugriffs_repository import (
    SQLiteZugriffsRepository,
)


def _projekt_anlegen(db: Path):
    return ProjektService(SQLiteProjektRepository(db)).projekt_anlegen(
        bezeichnung="Mandantentest",
        untersuchungsauftrag=Untersuchungsauftrag(
            problemstellung="Problem",
            untersuchungszweck="Zweck",
            systemtyp=Systemtyp.PRODUKTION,
            systemgrenze="Grenze",
        ),
    )


def test_migration_10_zu_11_markiert_bestand_nicht_oeffentlich(tmp_path: Path) -> None:
    db = tmp_path / "migration.sqlite"
    projekt = _projekt_anlegen(db)
    with sqlite3.connect(db) as verbindung:
        verbindung.execute("DELETE FROM projektzugehoerigkeiten")
        verbindung.execute("PRAGMA user_version = 10")
        verbindung.commit()
        initialisiere_schema(verbindung)
        zeile = verbindung.execute(
            "SELECT zugriffsart, gruppen_id, gast_geheimnis_sha256 "
            "FROM projektzugehoerigkeiten WHERE projekt_id = ?",
            (str(projekt.projekt_id),),
        ).fetchone()
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 12
    assert zeile == ("legacy_unassigned", None, None)


def test_gastnachweis_isoliert_projekte_und_laeuft_ab(tmp_path: Path) -> None:
    db = tmp_path / "zugriff.sqlite"
    projekt = _projekt_anlegen(db)
    repository = SQLiteZugriffsRepository(db)
    jetzt = datetime.now(UTC)
    repository.projektzugehoerigkeit_speichern(
        Projektzugehoerigkeit(
            projekt_id=projekt.projekt_id,
            zugriffsart=Projektzugriffsart.GAST,
            gruppen_id=None,
            gast_geheimnis_sha256=geheimnis_hash("a" * 32),
            gast_ablauf_am=jetzt + timedelta(hours=1),
            zuletzt_aktiv_am=jetzt,
            revision=1,
            erstellt_am=jetzt,
        )
    )
    service = AutorisierungsService(repository)
    service.projekt_zugriff_pruefen(
        Zugriffskontext.gast("a" * 32), projekt.projekt_id, Projektaktion.BEARBEITEN
    )
    with pytest.raises(ZugriffVerweigert, match="nicht verfügbar"):
        service.projekt_zugriff_pruefen(
            Zugriffskontext.gast("b" * 32), projekt.projekt_id, Projektaktion.ANSEHEN
        )
    with pytest.raises(ZugriffVerweigert, match="nicht verfügbar"):
        service.projekt_zugriff_pruefen(
            Zugriffskontext.gast("a" * 32),
            projekt.projekt_id,
            Projektaktion.ANSEHEN,
            zeitpunkt=jetzt + timedelta(hours=2),
        )


def test_entfernte_mitgliedschaft_wird_bei_jedem_zugriff_neu_geprueft(tmp_path: Path) -> None:
    db = tmp_path / "gruppe.sqlite"
    projekt = _projekt_anlegen(db)
    repository = SQLiteZugriffsRepository(db)
    leitung = repository.oidc_benutzer_speichern(
        issuer="https://idp.example", subject="leitung", email="l@example.org", anzeigename="L"
    )
    teilnehmer = repository.oidc_benutzer_speichern(
        issuer="https://idp.example", subject="t1", email="t@example.org", anzeigename="T"
    )
    jetzt = datetime.now(UTC)
    gruppe = Kursgruppe(
        gruppen_id=__import__("uuid").uuid4(),
        bezeichnung="Kurs A",
        beschreibung="",
        gruppenleitung_benutzer_id=leitung.benutzer_id,
        beginn_am=None,
        ende_am=None,
        maximale_teilnehmende=10,
        maximale_projekte=15,
        speicherlimit_pro_projekt_bytes=100_000,
        aufbewahrung_bis=None,
        status=Gruppenstatus.AKTIV,
        erstellt_am=jetzt,
        geaendert_am=jetzt,
    )
    repository.kursgruppe_speichern(gruppe)
    mitgliedschaft = Gruppenmitgliedschaft(
        gruppen_id=gruppe.gruppen_id,
        benutzer_id=teilnehmer.benutzer_id,
        rolle=Gruppenrolle.TEILNEHMER,
        status=Mitgliedschaftsstatus.AKTIV,
        berechtigungen=frozenset(),
        beigetreten_am=jetzt,
        geaendert_am=jetzt,
    )
    repository.gruppenmitgliedschaft_speichern(mitgliedschaft)
    repository.projektzugehoerigkeit_speichern(
        Projektzugehoerigkeit(
            projekt_id=projekt.projekt_id,
            zugriffsart=Projektzugriffsart.KURSGRUPPE,
            gruppen_id=gruppe.gruppen_id,
            gast_geheimnis_sha256=None,
            gast_ablauf_am=None,
            zuletzt_aktiv_am=jetzt,
            revision=1,
            erstellt_am=jetzt,
        )
    )
    repository.projektmitglied_speichern(
        Projektmitglied(projekt.projekt_id, teilnehmer.benutzer_id, True, True),
        zeitpunkt=jetzt,
    )
    service = AutorisierungsService(repository)
    kontext = Zugriffskontext.angemeldet(teilnehmer.benutzer_id)
    service.projekt_zugriff_pruefen(kontext, projekt.projekt_id, Projektaktion.BEARBEITEN)
    repository.gruppenmitgliedschaft_speichern(
        Gruppenmitgliedschaft(
            gruppen_id=gruppe.gruppen_id,
            benutzer_id=teilnehmer.benutzer_id,
            rolle=Gruppenrolle.TEILNEHMER,
            status=Mitgliedschaftsstatus.ENTFERNT,
            berechtigungen=frozenset(),
            beigetreten_am=jetzt,
            geaendert_am=jetzt,
        )
    )
    with pytest.raises(ZugriffVerweigert):
        service.projekt_zugriff_pruefen(kontext, projekt.projekt_id, Projektaktion.BEARBEITEN)


def test_systemadmin_hat_keinen_impliziten_kursprojektzugriff(tmp_path: Path) -> None:
    db = tmp_path / "admin.sqlite"
    projekt = _projekt_anlegen(db)
    repository = SQLiteZugriffsRepository(db)
    admin = repository.oidc_benutzer_speichern(
        issuer="https://idp.example", subject="admin", email="a@example.org", anzeigename="A"
    )
    leitung = repository.oidc_benutzer_speichern(
        issuer="https://idp.example", subject="leitung", email="l@example.org", anzeigename="L"
    )
    repository.globale_rolle_setzen(admin.benutzer_id, GlobaleRolle.SYSTEMADMIN, vergeben_von=None)
    jetzt = datetime.now(UTC)
    gruppe = Kursgruppe(
        __import__("uuid").uuid4(),
        "Privat",
        "",
        leitung.benutzer_id,
        None,
        None,
        10,
        15,
        100_000,
        None,
        Gruppenstatus.AKTIV,
        jetzt,
        jetzt,
    )
    repository.kursgruppe_speichern(gruppe)
    repository.projektzugehoerigkeit_speichern(
        Projektzugehoerigkeit(
            projekt.projekt_id,
            Projektzugriffsart.KURSGRUPPE,
            gruppe.gruppen_id,
            None,
            None,
            jetzt,
            1,
            jetzt,
        )
    )
    with pytest.raises(ZugriffVerweigert):
        AutorisierungsService(repository).projekt_zugriff_pruefen(
            Zugriffskontext.angemeldet(admin.benutzer_id),
            projekt.projekt_id,
            Projektaktion.ANSEHEN,
        )
