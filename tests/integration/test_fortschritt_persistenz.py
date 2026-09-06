"""Persistierter Fortschritt bleibt über Servicesitzungen hinweg identisch."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from framework_mvp.application.autorisierung import AutorisierungsService, geheimnis_hash
from framework_mvp.application.fortschritt_service import FortschrittService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
from framework_mvp.domain.models.zugriff import (
    Projektzugehoerigkeit,
    Projektzugriffsart,
    Zugriffskontext,
)
from framework_mvp.infrastructure.persistence.sqlite_fortschritt_repository import (
    SQLiteFortschrittRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_zugriffs_repository import (
    SQLiteZugriffsRepository,
)


def test_fortschritt_kommt_nicht_aus_session_state(tmp_path: Path) -> None:
    db = tmp_path / "fortschritt.sqlite"
    projekt = ProjektService(SQLiteProjektRepository(db)).projekt_anlegen(
        bezeichnung="Fortschritt",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Problem", "Zweck", Systemtyp.PRODUKTION, "Grenze"
        ),
    )
    geheimnis = "g" * 40
    jetzt = datetime.now(UTC)
    repository = SQLiteZugriffsRepository(db)
    repository.projektzugehoerigkeit_speichern(
        Projektzugehoerigkeit(
            projekt.projekt_id,
            Projektzugriffsart.GAST,
            None,
            geheimnis_hash(geheimnis),
            jetzt + timedelta(hours=2),
            jetzt,
            1,
            jetzt,
        )
    )
    kontext = Zugriffskontext.gast(geheimnis)
    service = FortschrittService(
        repository, SQLiteFortschrittRepository(db), AutorisierungsService(repository)
    )
    service.position_aktualisieren(
        kontext,
        projekt.projekt_id,
        schritt=4,
        unterschritt="Semantische Rollen und Attribute auswählen",
    )
    gespeichert = service.unterschritt_abschliessen(
        kontext,
        projekt.projekt_id,
        schritt=4,
        unterschritt=1,
    )
    neues_repository = SQLiteZugriffsRepository(db)
    neue_sitzung = FortschrittService(
        neues_repository,
        SQLiteFortschrittRepository(db),
        AutorisierungsService(neues_repository),
    ).laden(kontext, projekt.projekt_id)
    assert neue_sitzung.prozent == gespeichert.prozent
    assert neue_sitzung.schritt == 4
    assert neue_sitzung.unterschritt == "Semantische Rollen und Attribute auswählen"
    assert neue_sitzung.abgeschlossene_unterschritte[3] == 1


def test_neue_etl_datenbasis_setzt_persistierten_fortschritt_kontrolliert_zurueck(
    tmp_path: Path,
) -> None:
    db = tmp_path / "zuruecksetzen.sqlite"
    projekt = ProjektService(SQLiteProjektRepository(db)).projekt_anlegen(
        bezeichnung="Neue Datenbasis",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Problem", "Zweck", Systemtyp.PRODUKTION, "Grenze"
        ),
    )
    geheimnis = "z" * 40
    jetzt = datetime.now(UTC)
    repository = SQLiteZugriffsRepository(db)
    repository.projektzugehoerigkeit_speichern(
        Projektzugehoerigkeit(
            projekt.projekt_id,
            Projektzugriffsart.GAST,
            None,
            geheimnis_hash(geheimnis),
            jetzt + timedelta(hours=2),
            jetzt,
            1,
            jetzt,
        )
    )
    kontext = Zugriffskontext.gast(geheimnis)
    service = FortschrittService(
        repository, SQLiteFortschrittRepository(db), AutorisierungsService(repository)
    )
    for schritt in range(1, 11):
        service.schritt_abschliessen(kontext, projekt.projekt_id, schritt=schritt)

    service.auf_datenbasis_zuruecksetzen(
        kontext,
        projekt.projekt_id,
        unterschritt="Transformieren und verknüpfen",
    )

    stand = service.laden(kontext, projekt.projekt_id)
    assert stand.schritt == 2
    assert stand.unterschritt == "Transformieren und verknüpfen"
    assert stand.prozent == 10
    assert stand.abgeschlossene_unterschritte == (5, 0, 0, 0, 0, 0, 0, 0, 0, 0)


def test_identischer_ui_rerun_veraendert_abgeschlossenen_fortschritt_nicht(
    tmp_path: Path,
) -> None:
    db = tmp_path / "idempotent.sqlite"
    projekt = ProjektService(SQLiteProjektRepository(db)).projekt_anlegen(
        bezeichnung="Abgeschlossen",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Problem", "Zweck", Systemtyp.PRODUKTION, "Grenze"
        ),
    )
    geheimnis = "i" * 40
    jetzt = datetime.now(UTC)
    repository = SQLiteZugriffsRepository(db)
    repository.projektzugehoerigkeit_speichern(
        Projektzugehoerigkeit(
            projekt.projekt_id,
            Projektzugriffsart.GAST,
            None,
            geheimnis_hash(geheimnis),
            jetzt + timedelta(hours=2),
            jetzt,
            1,
            jetzt,
        )
    )
    service = FortschrittService(
        repository, SQLiteFortschrittRepository(db), AutorisierungsService(repository)
    )
    kontext = Zugriffskontext.gast(geheimnis)
    for schritt in range(1, 11):
        service.schritt_abschliessen(kontext, projekt.projekt_id, schritt=schritt)
    service.position_aktualisieren(
        kontext,
        projekt.projekt_id,
        schritt=10,
        unterschritt="Konzeptionelles Modell ausgeben",
    )
    vorher = repository.fortschritt_laden(projekt.projekt_id)

    service.position_aktualisieren(
        kontext,
        projekt.projekt_id,
        schritt=10,
        unterschritt="Konzeptionelles Modell ausgeben",
    )
    service.laden(kontext, projekt.projekt_id)

    assert repository.fortschritt_laden(projekt.projekt_id) == vorher


def test_reine_navigation_erzeugt_keinen_fachlichen_fortschritt(tmp_path: Path) -> None:
    db = tmp_path / "navigation.sqlite"
    projekt = ProjektService(SQLiteProjektRepository(db)).projekt_anlegen(
        bezeichnung="Navigation",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Problem", "Zweck", Systemtyp.PRODUKTION, "Grenze"
        ),
    )
    geheimnis = "n" * 40
    jetzt = datetime.now(UTC)
    repository = SQLiteZugriffsRepository(db)
    repository.projektzugehoerigkeit_speichern(
        Projektzugehoerigkeit(
            projekt.projekt_id,
            Projektzugriffsart.GAST,
            None,
            geheimnis_hash(geheimnis),
            jetzt + timedelta(hours=2),
            jetzt,
            1,
            jetzt,
        )
    )
    kontext = Zugriffskontext.gast(geheimnis)
    service = FortschrittService(
        repository, SQLiteFortschrittRepository(db), AutorisierungsService(repository)
    )

    stand = service.position_aktualisieren(
        kontext,
        projekt.projekt_id,
        schritt=5,
        unterschritt="Fachlich bewerten",
    )

    assert stand.schritt == 5
    assert stand.prozent == 0
    assert stand.abgeschlossene_unterschritte == (0,) * 10
