"""Rollenfreigaben und atomare, gehashte Gruppeneinladungen."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest

from framework_mvp.application.autorisierung import AutorisierungsService
from framework_mvp.application.kursgruppen_service import EinladungsService, KursgruppenService
from framework_mvp.domain.exceptions import ZugriffVerweigert
from framework_mvp.domain.models.zugriff import GlobaleRolle, Zugriffskontext
from framework_mvp.infrastructure.persistence.sqlite_zugriffs_repository import (
    SQLiteZugriffsRepository,
)


def _benutzer(repository: SQLiteZugriffsRepository, subject: str, email: str):
    return repository.oidc_benutzer_speichern(
        issuer="https://idp.example", subject=subject, email=email, anzeigename=subject
    )


def test_nur_freigeschaltete_gruppenleitung_erstellt_gruppe(tmp_path: Path) -> None:
    repository = SQLiteZugriffsRepository(tmp_path / "gruppen.sqlite")
    benutzer = _benutzer(repository, "leitung", "leitung@example.org")
    kontext = Zugriffskontext.angemeldet(benutzer.benutzer_id)
    service = KursgruppenService(repository, AutorisierungsService(repository))
    with pytest.raises(ZugriffVerweigert):
        service.gruppe_anlegen(kontext, bezeichnung="Nicht erlaubt")
    repository.globale_rolle_setzen(
        benutzer.benutzer_id, GlobaleRolle.GRUPPENLEITUNG, vergeben_von=None
    )
    gruppe = service.gruppe_anlegen(kontext, bezeichnung="Privater Kurs")
    assert service.gruppen_auflisten(kontext) == [gruppe]


def test_einladung_speichert_nur_hash_und_prueft_email_domain(tmp_path: Path) -> None:
    repository = SQLiteZugriffsRepository(tmp_path / "einladung.sqlite")
    leitung = _benutzer(repository, "leitung", "leitung@example.org")
    repository.globale_rolle_setzen(
        leitung.benutzer_id, GlobaleRolle.GRUPPENLEITUNG, vergeben_von=None
    )
    kontext = Zugriffskontext.angemeldet(leitung.benutzer_id)
    autorisierung = AutorisierungsService(repository)
    gruppe = KursgruppenService(repository, autorisierung).gruppe_anlegen(
        kontext, bezeichnung="Kurs"
    )
    einladungen = EinladungsService(repository, autorisierung)
    einladung, token = einladungen.erstellen(
        kontext,
        gruppe.gruppen_id,
        erlaubte_email_domain="example.org",
        maximale_nutzungen=2,
    )
    assert len(token) >= 43
    assert einladung.token_sha256 == hashlib.sha256(token.encode()).hexdigest()
    assert repository.einladung_laden_per_hash(token) is None
    fremd = _benutzer(repository, "fremd", "fremd@invalid.test")
    with pytest.raises(ZugriffVerweigert):
        einladungen.einloesen(Zugriffskontext.angemeldet(fremd.benutzer_id), token)


def test_nutzungslimit_wird_bei_parallelem_beitritt_nicht_ueberschritten(
    tmp_path: Path,
) -> None:
    db = tmp_path / "parallel.sqlite"
    repository = SQLiteZugriffsRepository(db)
    leitung = _benutzer(repository, "leitung", "leitung@example.org")
    repository.globale_rolle_setzen(
        leitung.benutzer_id, GlobaleRolle.GRUPPENLEITUNG, vergeben_von=None
    )
    kontext = Zugriffskontext.angemeldet(leitung.benutzer_id)
    autorisierung = AutorisierungsService(repository)
    gruppe = KursgruppenService(repository, autorisierung).gruppe_anlegen(
        kontext, bezeichnung="Kurs"
    )
    _, token = EinladungsService(repository, autorisierung).erstellen(
        kontext, gruppe.gruppen_id, maximale_nutzungen=1
    )
    personen = [_benutzer(repository, f"t{index}", f"t{index}@example.org") for index in range(2)]

    def beitreten(index: int) -> bool:
        lokales_repository = SQLiteZugriffsRepository(db)
        try:
            EinladungsService(
                lokales_repository, AutorisierungsService(lokales_repository)
            ).einloesen(Zugriffskontext.angemeldet(personen[index].benutzer_id), token)
        except ZugriffVerweigert:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        ergebnisse = list(pool.map(beitreten, range(2)))
    assert ergebnisse.count(True) == 1
    gespeichert = repository.einladung_laden_per_hash(hashlib.sha256(token.encode()).hexdigest())
    assert gespeichert is not None and gespeichert.anzahl_nutzungen == 1


def test_abgelaufene_und_widerrufene_einladung_wird_abgelehnt(tmp_path: Path) -> None:
    repository = SQLiteZugriffsRepository(tmp_path / "status.sqlite")
    leitung = _benutzer(repository, "leitung", "leitung@example.org")
    teilnehmer = _benutzer(repository, "t", "t@example.org")
    repository.globale_rolle_setzen(
        leitung.benutzer_id, GlobaleRolle.GRUPPENLEITUNG, vergeben_von=None
    )
    kontext = Zugriffskontext.angemeldet(leitung.benutzer_id)
    autorisierung = AutorisierungsService(repository)
    gruppe = KursgruppenService(repository, autorisierung).gruppe_anlegen(
        kontext, bezeichnung="Kurs"
    )
    service = EinladungsService(repository, autorisierung)
    einladung, token = service.erstellen(
        kontext, gruppe.gruppen_id, gueltig_fuer=timedelta(microseconds=1)
    )
    with pytest.raises(ZugriffVerweigert):
        service.einloesen(Zugriffskontext.angemeldet(teilnehmer.benutzer_id), token)
    _, token2 = service.erstellen(kontext, gruppe.gruppen_id)
    einladung2 = repository.einladung_laden_per_hash(hashlib.sha256(token2.encode()).hexdigest())
    assert einladung2 is not None
    service.widerrufen(kontext, gruppe.gruppen_id, einladung2.einladungs_id)
    with pytest.raises(ZugriffVerweigert):
        service.einloesen(Zugriffskontext.angemeldet(teilnehmer.benutzer_id), token2)


def test_gruppenleitung_kann_nur_einladungen_der_eigenen_gruppe_widerrufen(
    tmp_path: Path,
) -> None:
    repository = SQLiteZugriffsRepository(tmp_path / "einladungsgrenzen.sqlite")
    autorisierung = AutorisierungsService(repository)
    kursgruppen = KursgruppenService(repository, autorisierung)
    einladungen = EinladungsService(repository, autorisierung)
    leitung_a = _benutzer(repository, "leitung-a", "a@example.org")
    leitung_b = _benutzer(repository, "leitung-b", "b@example.org")
    for leitung in (leitung_a, leitung_b):
        repository.globale_rolle_setzen(
            leitung.benutzer_id, GlobaleRolle.GRUPPENLEITUNG, vergeben_von=None
        )
    kontext_a = Zugriffskontext.angemeldet(leitung_a.benutzer_id)
    kontext_b = Zugriffskontext.angemeldet(leitung_b.benutzer_id)
    gruppe_a = kursgruppen.gruppe_anlegen(kontext_a, bezeichnung="Gruppe A")
    gruppe_b = kursgruppen.gruppe_anlegen(kontext_b, bezeichnung="Gruppe B")
    einladung_b, _ = einladungen.erstellen(kontext_b, gruppe_b.gruppen_id)

    with pytest.raises(ZugriffVerweigert):
        einladungen.widerrufen(kontext_a, gruppe_a.gruppen_id, einladung_b.einladungs_id)

    gespeichert = repository.einladung_laden_per_hash(einladung_b.token_sha256)
    assert gespeichert is not None
    assert gespeichert.widerrufen_am is None
    assert einladungen.auflisten(kontext_a, gruppe_a.gruppen_id) == []
    with pytest.raises(ZugriffVerweigert):
        einladungen.auflisten(kontext_a, gruppe_b.gruppen_id)
