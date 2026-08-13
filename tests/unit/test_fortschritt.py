"""Verträge der zentralen fachlichen Fortschrittsanzeige."""

from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.ui.fortschritt import fortschrittsstand
from framework_mvp.ui.navigation import FRAMEWORK_BEREICHE


@pytest.mark.parametrize(
    ("schritt", "phase", "phase_name"),
    (
        (5, 1, "Phase 1 – Aufbereitung der Datenbasis"),
        (6, 2, "Phase 2 – Datengetriebene Analyse des Systems"),
        (7, 2, "Phase 2 – Datengetriebene Analyse des Systems"),
        (8, 3, "Phase 3 – Überführung in das konzeptionelle Modell"),
    ),
)
def test_phasengrenzen_sind_zentral_definiert(
    schritt: int, phase: int, phase_name: str
) -> None:
    stand = fortschrittsstand(FRAMEWORK_BEREICHE[schritt - 1], {})
    assert stand.phase == phase
    assert stand.phase_name == phase_name


def test_projektbezogener_fachlicher_unterschritt_wird_beruecksichtigt() -> None:
    projekt_id = uuid4()
    stand = fortschrittsstand(
        FRAMEWORK_BEREICHE[3],
        {
            "aktuelles_projekt_id": str(projekt_id),
            "event_log_zustaende": {str(projekt_id): {"schritt": 3}},
        },
    )
    assert stand.framework_schritt == 4
    assert stand.unterschritt == 3
    assert stand.unterschritt_name == "Semantische Rollen und Attribute auswählen"


def test_renderer_erzeugt_genau_einen_fortschrittsbalken() -> None:
    app = AppTest.from_string(
        """
from framework_mvp.ui.fortschritt import fortschrittsstand, zeige_gesamtfortschritt
from framework_mvp.ui.navigation import FRAMEWORK_BEREICHE
zeige_gesamtfortschritt(fortschrittsstand(FRAMEWORK_BEREICHE[8], {}))
"""
    ).run()
    assert not app.exception
    assert len(app.get("progress")) == 1
    assert any("Phase 3" in wert.value for wert in app.caption)
    assert any("Schritt 9" in wert.value for wert in app.markdown)
