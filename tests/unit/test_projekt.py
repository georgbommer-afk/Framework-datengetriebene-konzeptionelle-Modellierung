"""Unit-Tests für die Projekt-Domäne."""

from dataclasses import replace
from datetime import UTC, date, datetime, tzinfo

import pytest

from framework_mvp.domain.exceptions import (
    UngueltigeProjektbezeichnung,
    UngueltigerBetrachtungszeitraum,
    UngueltigerZeitstempel,
)
from framework_mvp.domain.models import (
    BeteiligtePerson,
    Betrachtungszeitraum,
    BetrachtungszeitraumModus,
    Projekt,
    Projektstatus,
    Systemtyp,
    Untersuchungsauftrag,
)


def _vollstaendiger_auftrag() -> Untersuchungsauftrag:
    return Untersuchungsauftrag(
        problemstellung="  Lange Durchlaufzeiten  ",
        untersuchungszweck=" System analysieren ",
        systemtyp=Systemtyp.PRODUKTION,
        systemgrenze=" Montagelinie ",
    )


@pytest.mark.parametrize("bezeichnung", ["", "   "])
def test_leere_projektbezeichnung_wird_abgelehnt(bezeichnung: str) -> None:
    """Eine bereinigte Projektbezeichnung muss Inhalt besitzen."""
    with pytest.raises(UngueltigeProjektbezeichnung):
        Projekt.neu(bezeichnung, _vollstaendiger_auftrag())


def test_vollstaendiger_untersuchungsauftrag() -> None:
    """Die drei Mindestangaben ergeben einen vollständigen Auftrag."""
    assert _vollstaendiger_auftrag().ist_vollstaendig()


def test_unvollstaendiger_untersuchungsauftrag() -> None:
    """Ein fehlendes Mindestfeld ergibt einen unvollständigen Auftrag."""
    auftrag = Untersuchungsauftrag(
        problemstellung="Problem",
        untersuchungszweck="   ",
        systemtyp=Systemtyp.INTRALOGISTIK,
        systemgrenze="Lager",
    )

    assert not auftrag.ist_vollstaendig()
    assert Projekt.neu("Entwurf", auftrag).status is Projektstatus.ENTWURF


def test_ungueltiger_betrachtungszeitraum() -> None:
    """Das Enddatum darf nicht vor dem Startdatum liegen."""
    with pytest.raises(UngueltigerBetrachtungszeitraum):
        Untersuchungsauftrag(
            problemstellung="Problem",
            untersuchungszweck="Ziel",
            systemtyp=Systemtyp.KOMBINIERT,
            systemgrenze="Werk",
            betrachtungszeitraum=Betrachtungszeitraum(
                BetrachtungszeitraumModus.MANUELL,
                date(2026, 2, 1),
                date(2026, 1, 31),
            ),
        )


def test_id_und_zeitstempel_werden_automatisch_erzeugt() -> None:
    """Neue Projekte besitzen eine UUID und UTC-Zeitstempel."""
    projekt = Projekt.neu("Analyse", _vollstaendiger_auftrag())

    assert projekt.projekt_id.version == 4
    assert projekt.erstellt_am.tzinfo is UTC
    assert projekt.geaendert_am.tzinfo is UTC
    assert projekt.geaendert_am >= projekt.erstellt_am


class ZeitzoneOhneOffset(tzinfo):
    """Test-Zeitzone, die keinen UTC-Versatz bestimmen kann."""

    def utcoffset(self, dt: datetime | None) -> None:
        """Liefert absichtlich keinen UTC-Versatz."""

    def dst(self, dt: datetime | None) -> None:
        """Liefert absichtlich keine Sommerzeitabweichung."""

    def tzname(self, dt: datetime | None) -> str:
        """Liefert eine Bezeichnung für die Test-Zeitzone."""
        return "Ohne Versatz"


def test_zeitstempel_ohne_bestimmbaren_utc_versatz_wird_abgelehnt() -> None:
    """Ein gesetztes tzinfo ohne UTC-Versatz gilt nicht als zeitzonenbewusst."""
    projekt = Projekt.neu("Analyse", _vollstaendiger_auftrag())
    zeitstempel = projekt.erstellt_am.replace(tzinfo=ZeitzoneOhneOffset())

    with pytest.raises(UngueltigerZeitstempel):
        replace(projekt, erstellt_am=zeitstempel, geaendert_am=zeitstempel)


def test_texte_und_listeneintraege_werden_bereinigt() -> None:
    """Rand-Leerzeichen und leere Listeneinträge werden normalisiert."""
    auftrag = Untersuchungsauftrag(
        problemstellung=" Problem ",
        untersuchungszweck=" Ziel ",
        systemtyp=Systemtyp.PRODUKTION,
        systemgrenze=" Grenze ",
        legacy_leistungskennzahlen=(" Durchlaufzeit ", " ", "Auslastung"),
    )
    projekt = Projekt.neu(
        " Projekt ",
        auftrag,
        beteiligte_personen=(BeteiligtePerson(" Ada ", " Lovelace ", " Analyse "),),
    )

    assert projekt.bezeichnung == "Projekt"
    assert projekt.beteiligte_personen[0] == BeteiligtePerson("Ada", "Lovelace", "Analyse")
    assert auftrag.problemstellung == "Problem"
    assert auftrag.legacy_leistungskennzahlen == ("Durchlaufzeit", "Auslastung")
