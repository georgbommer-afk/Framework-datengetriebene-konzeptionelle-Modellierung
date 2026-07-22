"""Tests der strukturierten Domänenobjekte und Kataloge."""

from datetime import date

import pytest

from framework_mvp.domain.exceptions import Domaenenfehler, UngueltigerBetrachtungszeitraum
from framework_mvp.domain.kataloge import bereinige_kpi_auswahl, leite_kpi_kandidaten_ab
from framework_mvp.domain.models import (
    BeteiligtePerson,
    Betrachtungszeitraum,
    BetrachtungszeitraumModus,
    Intralogistikklassifikation,
    LogistischeZielgroesse,
    Produktionsklassifikation,
    Systemklassifikation,
    Systemtyp,
    Untersuchungsauftrag,
)


def test_beteiligte_person_normalisiert_werte_und_erlaubt_freie_rolle() -> None:
    """Namen und eine frei gewählte Rolle werden bereinigt."""
    assert BeteiligtePerson(" Ada ", " Lovelace ", " Leitung ") == BeteiligtePerson(
        "Ada", "Lovelace", "Leitung"
    )


def test_beteiligte_person_benoetigt_einen_namen() -> None:
    """Mindestens einer der beiden Namensteile muss vorhanden sein."""
    with pytest.raises(Domaenenfehler):
        BeteiligtePerson(" ", " ", "Rolle")


def test_zielgroessen_und_ids_sind_stabil_und_mehrfach_waehlbar() -> None:
    """Mehrere technische Ziel-IDs bleiben in Eingabereihenfolge erhalten."""
    ziele = (LogistischeZielgroesse.DURCHLAUFZEIT, LogistischeZielgroesse.QUALITAET)
    auftrag = Untersuchungsauftrag(
        "Problem", "Analyse", Systemtyp.PRODUKTION, "Grenze", logistische_zielgroessen=ziele
    )
    assert auftrag.logistische_zielgroessen == ziele
    assert LogistischeZielgroesse.DURCHLAUFZEIT.value == "durchlaufzeit_reduzieren"


def test_kpis_werden_abgeleitet_und_kontrolliert_bereinigt() -> None:
    """Entfernte Zielgrößen entfernen nicht mehr passende KPI-IDs."""
    kandidaten = leite_kpi_kandidaten_ab((LogistischeZielgroesse.DURCHLAUFZEIT,))
    assert {k.kpi_id for k in kandidaten} == {"gesamtdurchlaufzeit", "durchlaufzeit_variante"}
    assert bereinige_kpi_auswahl((), ("gesamtdurchlaufzeit",)) == ()


@pytest.mark.parametrize(
    ("systemtyp", "produktion", "intralogistik"),
    [
        (Systemtyp.PRODUKTION, Produktionsklassifikation(), None),
        (Systemtyp.INTRALOGISTIK, None, Intralogistikklassifikation()),
        (Systemtyp.KOMBINIERT, Produktionsklassifikation(), Intralogistikklassifikation()),
    ],
)
def test_systemklassifikation_fuer_alle_systemtypen(
    systemtyp: Systemtyp,
    produktion: Produktionsklassifikation | None,
    intralogistik: Intralogistikklassifikation | None,
) -> None:
    """Die drei Systemtypen tragen die jeweils passenden Teilmodelle."""
    system = Systemklassifikation(produktion=produktion, intralogistik=intralogistik)
    auftrag = Untersuchungsauftrag(
        "Problem", "Analyse", systemtyp, "Grenze", systemklassifikation=system
    )
    assert auftrag.systemklassifikation.produktion is produktion
    assert auftrag.systemklassifikation.intralogistik is intralogistik


def test_zeitraummodi_aus_daten_und_offen() -> None:
    """Automatischer und offener Modus benötigen keine Datumswerte."""
    assert Betrachtungszeitraum().modus is BetrachtungszeitraumModus.AUS_DATEN
    assert Betrachtungszeitraum(BetrachtungszeitraumModus.OFFEN).beginn is None


def test_manueller_zeitraum_benoetigt_beide_daten() -> None:
    """Ein manueller Zeitraum ist nur mit Beginn und Ende gültig."""
    with pytest.raises(UngueltigerBetrachtungszeitraum):
        Betrachtungszeitraum(BetrachtungszeitraumModus.MANUELL, date(2026, 1, 1))


def test_manueller_zeitraum_prueft_reihenfolge() -> None:
    """Das Ende darf auch im neuen Zeitraumobjekt nicht vor dem Beginn liegen."""
    with pytest.raises(UngueltigerBetrachtungszeitraum):
        Betrachtungszeitraum(BetrachtungszeitraumModus.MANUELL, date(2026, 2, 1), date(2026, 1, 1))


def test_neue_vollstaendigkeitsregel() -> None:
    """Nur Problem, Grenze und Untersuchungszweck bestimmen die Vollständigkeit."""
    assert Untersuchungsauftrag(
        "Problem", "Analyse", Systemtyp.KOMBINIERT, "Grenze"
    ).ist_vollstaendig()
    assert not Untersuchungsauftrag(
        "Problem", "", Systemtyp.KOMBINIERT, "Grenze", individuelles_ziel="Altziel"
    ).ist_vollstaendig()
