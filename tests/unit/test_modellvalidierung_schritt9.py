"""Domänenverträge der Human-in-the-Loop-Entscheidungen in Schritt 9."""

from dataclasses import replace

import pytest

from framework_mvp.application.modellvalidierung_service import ModellvalidierungService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    BehandlungOffenerEintrag,
    Gesamtvalidierungsstatus,
    ModellbestandteilId,
    Offenheitsentscheidung,
    Offenheitskategorie,
    ZusaetzlicheModellanpassung,
)


def _behandlung(
    *,
    kategorie: Offenheitskategorie = Offenheitskategorie.FACHLICH_UNSICHER,
    entscheidung: Offenheitsentscheidung = Offenheitsentscheidung.BESTAETIGT,
    inhalt: str = "",
    begruendung: str = "Durch die Prozesseignerin fachlich geprüft.",
) -> BehandlungOffenerEintrag:
    return BehandlungOffenerEintrag(
        "offen-1",
        ModellbestandteilId.PROBLEMSTELLUNG,
        kategorie,
        "Eine fachliche Prüfung ist erforderlich.",
        entscheidung,
        inhalt,
        begruendung,
    )


@pytest.mark.parametrize(
    ("entscheidung", "inhalt"),
    [
        (Offenheitsentscheidung.BESTAETIGT, ""),
        (Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST, "Fachlicher Zielzustand"),
        (Offenheitsentscheidung.NICHT_ANWENDBAR, ""),
    ],
)
def test_fachlich_unsicher_erlaubt_alle_drei_entscheidungen(
    entscheidung: Offenheitsentscheidung, inhalt: str
) -> None:
    assert _behandlung(entscheidung=entscheidung, inhalt=inhalt).entscheidung is entscheidung


@pytest.mark.parametrize(
    "kategorie",
    [Offenheitskategorie.FEHLEND, Offenheitskategorie.NICHT_ABLEITBAR],
)
def test_fehlend_und_nicht_ableitbar_duerfen_nicht_nur_bestaetigt_werden(
    kategorie: Offenheitskategorie,
) -> None:
    with pytest.raises(Domaenenfehler, match="fachlich unsicherer"):
        _behandlung(kategorie=kategorie)


def test_entscheidungsspezifische_pflichtfelder_werden_erzwungen() -> None:
    with pytest.raises(Domaenenfehler, match="Inhalt und Begründung"):
        _behandlung(
            entscheidung=Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST,
            inhalt="",
        )
    with pytest.raises(Domaenenfehler, match="benötigt eine Begründung"):
        _behandlung(entscheidung=Offenheitsentscheidung.NICHT_ANWENDBAR, begruendung="")
    with pytest.raises(Domaenenfehler, match="keinen Modellinhalt"):
        _behandlung(entscheidung=Offenheitsentscheidung.NICHT_ANWENDBAR, inhalt="künstlich")
    with pytest.raises(Domaenenfehler, match="benötigt eine Begründung"):
        _behandlung(entscheidung=Offenheitsentscheidung.BESTAETIGT, begruendung="")


def test_zusaetzliche_anpassung_braucht_inhalt_und_begruendung() -> None:
    with pytest.raises(Domaenenfehler, match="Inhalt und Begründung"):
        ZusaetzlicheModellanpassung(ModellbestandteilId.DATEN, "", "Begründung")
    with pytest.raises(Domaenenfehler, match="Inhalt und Begründung"):
        ZusaetzlicheModellanpassung(ModellbestandteilId.DATEN, "Inhalt", "")


def test_entscheidungsfingerabdruck_reagiert_auf_alle_fachlichen_eingaben() -> None:
    behandlung = _behandlung(
        entscheidung=Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST,
        inhalt="Fachlicher Inhalt",
    )
    anpassung = ZusaetzlicheModellanpassung(
        ModellbestandteilId.DATEN, "Zusätzlicher Inhalt", "Zusätzliche Begründung"
    )

    def fingerabdruck(
        behandlungen: tuple[BehandlungOffenerEintrag, ...] = (behandlung,),
        anpassungen: tuple[ZusaetzlicheModellanpassung, ...] = (anpassung,),
        status: Gesamtvalidierungsstatus = Gesamtvalidierungsstatus.FACHLICH_VALIDIERT,
        vermerk: str = "Gesamtvermerk",
        bestaetigt: bool = True,
    ) -> str:
        return ModellvalidierungService.entscheidungsfingerabdruck(
            behandlungen, anpassungen, status, vermerk, bestaetigt
        )

    basis = fingerabdruck()
    varianten = {
        fingerabdruck(
            behandlungen=(
                replace(
                    behandlung,
                    entscheidung=Offenheitsentscheidung.NICHT_ANWENDBAR,
                    fachlicher_inhalt="",
                ),
            )
        ),
        fingerabdruck(behandlungen=(replace(behandlung, fachlicher_inhalt="Anderer Inhalt"),)),
        fingerabdruck(behandlungen=(replace(behandlung, begruendung="Andere Begründung"),)),
        fingerabdruck(anpassungen=(replace(anpassung, fachlicher_inhalt="Andere Anpassung"),)),
        fingerabdruck(status=Gesamtvalidierungsstatus.ANPASSUNGSBEDARF),
        fingerabdruck(vermerk="Anderer Gesamtvermerk"),
        fingerabdruck(bestaetigt=False),
    }
    assert basis not in varianten
    assert len(varianten) == 7
    assert basis == fingerabdruck()
