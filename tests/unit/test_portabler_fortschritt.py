"""Zentrale Fortschrittsdefinition für Projektansicht und Kursdashboard."""

from framework_mvp.application.fortschritt_service import (
    FACHLICHE_UNTERSCHRITTE,
    berechne_fortschritt,
)
from framework_mvp.domain.models.zugriff import phase_fuer_schritt


def test_phasengrenzen_bleiben_eindeutig() -> None:
    assert [phase_fuer_schritt(nr) for nr in (5, 6, 7, 8)] == [1, 2, 2, 3]


def test_technische_unterschritte_erhoehen_fortschritt_nicht() -> None:
    basis = berechne_fortschritt(4, "")
    assert berechne_fortschritt(4, "Technische Details") == basis
    assert berechne_fortschritt(4, FACHLICHE_UNTERSCHRITTE[4][0])[0] == basis[0] + 1
