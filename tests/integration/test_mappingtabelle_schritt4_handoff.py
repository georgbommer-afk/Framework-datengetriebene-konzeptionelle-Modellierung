"""AppTests des expliziten M-Handoffs von Schritt 3 an Schritt 4."""

from streamlit.testing.v1 import AppTest

SCHRITT_VIER_APP = r"""
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.domain.models import Mappingeintrag, Mappingtabelle, Zwischendatensatz
from framework_mvp.ui.pages.event_log import zeige_event_log_seite

PROJEKT_ID = UUID("11111111-1111-1111-1111-111111111111")
DATENSATZ_ID = UUID("22222222-2222-2222-2222-222222222222")
DATENSATZ = Zwischendatensatz(
    DATENSATZ_ID, PROJEKT_ID, UUID("33333333-3333-3333-3333-333333333333"),
    (UUID("44444444-4444-4444-4444-444444444444"),),
    "T.csv.gz", "T.schema.json", "T.transformation.json", "a" * 64,
    1, 2, datetime.now(UTC),
)
DATEN = pd.DataFrame({"t_pdno": [1001], "transaction": ["ticst0201m000"]})

class Projekte:
    def projekte_auflisten(self):
        return [SimpleNamespace(projekt_id=PROJEKT_ID, bezeichnung="M-Projekt")]
    def projekt_laden(self, projekt_id):
        return SimpleNamespace(projekt_id=projekt_id, bezeichnung="M-Projekt")

class Transformationen:
    def datensaetze_fuer_projekt(self, projekt_id):
        return [DATENSATZ]
    def zwischendatensatz_laden(self, datensatz_id):
        return DATENSATZ, DATEN.copy(deep=True)
    def plan_laden(self, plan_id):
        return None
    def importe_fuer_projekt(self, projekt_id):
        return []

class Mappingtabellen:
    def fuer_datensatz(self, projekt_id, datensatz_id):
        mapping = Mappingtabelle.neu(PROJEKT_ID, DATENSATZ_ID)
        if st.session_state.get("handoff_befuelltes_m"):
            return mapping.eintrag_hinzufuegen(
                Mappingeintrag.fuer_spalte("t_pdno", "Produktionsauftrag")
            ).bestaetigen()
        return mapping.bestaetigen(kein_mapping_erforderlich=True)

class EventLogKonfigurationen:
    def fuer_projekt(self, projekt_id):
        return []

class EventLogs:
    pass

zeige_event_log_seite(
    Projekte(), EventLogKonfigurationen(), Mappingtabellen(), Transformationen(), EventLogs()
)
"""


def _app(*, befuellt: bool) -> AppTest:
    app = AppTest.from_string(SCHRITT_VIER_APP)
    app.session_state["aktuelles_projekt_id"] = "11111111-1111-1111-1111-111111111111"
    app.session_state["aktueller_zwischendatensatz_id"] = "22222222-2222-2222-2222-222222222222"
    app.session_state["handoff_befuelltes_m"] = befuellt
    return app.run()


def test_schritt_vier_akzeptiert_ausdruecklich_leeres_m() -> None:
    app = _app(befuellt=False)
    assert not app.exception
    assert any("bestätigt leer" in wert.value for wert in app.info)
    assert any(wert.label == "Wie sind die Ereignisse in T dargestellt?" for wert in app.radio)


def test_schritt_vier_akzeptiert_befuelltes_m_und_zeigt_beide_kernspalten() -> None:
    app = _app(befuellt=True)
    assert not app.exception
    assert any("Semantische Sicht aus Schritt 3" in wert.value for wert in app.markdown)
    assert any(
        {"Technische Bezeichnung", "Fachliche Bezeichnung"} <= set(wert.value.columns)
        for wert in app.dataframe
    )
