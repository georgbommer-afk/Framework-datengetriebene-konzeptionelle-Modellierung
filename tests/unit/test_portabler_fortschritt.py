"""Zentrale Fortschrittsdefinition für Projektansicht und Kursdashboard."""

from framework_mvp.application.fortschritt_service import (
    FACHLICHE_UNTERSCHRITTE,
    LEERER_ABSCHLUSS,
    berechne_fortschritt,
    berechne_phasenfortschritt,
)
from framework_mvp.domain.models.zugriff import phase_fuer_schritt


def test_phasengrenzen_bleiben_eindeutig() -> None:
    assert [phase_fuer_schritt(nr) for nr in (5, 6, 7, 8)] == [1, 2, 2, 3]


def test_technische_unterschritte_erhoehen_fortschritt_nicht() -> None:
    assert berechne_fortschritt(LEERER_ABSCHLUSS) == 0


def test_erster_unterschritt_von_schritt_1_ergibt_2_prozent_und_phase_1_4_prozent() -> None:
    abschluesse = (1, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    assert berechne_fortschritt(abschluesse) == 2
    assert berechne_phasenfortschritt(abschluesse) == (4, 0, 0)


def test_jeder_framework_schritt_traegt_exakt_10_prozentpunkte_bei() -> None:
    for schritt, unterschritte in FACHLICHE_UNTERSCHRITTE.items():
        abschluesse = [0] * 10
        abschluesse[schritt - 1] = len(unterschritte)
        assert berechne_fortschritt(tuple(abschluesse)) == 10


def test_phasen_werden_unabhaengig_normalisiert() -> None:
    schritt_1 = (5, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    schritt_5 = (5, 5, 3, 4, 4, 0, 0, 0, 0, 0)
    schritt_7 = (5, 5, 3, 4, 4, 3, 1, 0, 0, 0)
    alles = (5, 5, 3, 4, 4, 3, 1, 1, 1, 1)
    assert berechne_fortschritt(schritt_1) == 10
    assert berechne_phasenfortschritt(schritt_1)[0] == 20
    assert berechne_fortschritt(schritt_5) == 50
    assert berechne_phasenfortschritt(schritt_5)[0] == 100
    assert berechne_fortschritt(schritt_7) == 70
    assert berechne_phasenfortschritt(schritt_7)[1] == 100
    assert berechne_fortschritt(alles) == 100
    assert berechne_phasenfortschritt(alles)[2] == 100
