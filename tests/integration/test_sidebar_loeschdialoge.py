"""Regressionstests der Löschdialoge im Sidebar-Projektrahmen."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from streamlit.testing.v1 import AppTest

from framework_mvp.ui.pages.projektverwaltung import (
    _datensatzloeschung_ausfuehren,
    _projektloeschung_ausfuehren,
)

APP = r"""
from datetime import UTC, datetime
from uuid import UUID

import streamlit as st

from framework_mvp.domain.models import (
    Projekt, Projektstatus, Systemtyp, Untersuchungsauftrag, Zwischendatensatz,
)
from framework_mvp.ui.pages.projektverwaltung import zeige_projektverwaltung

P = UUID("11111111-1111-1111-1111-111111111111")
D1 = UUID("22222222-2222-2222-2222-222222222222")
D2 = UUID("33333333-3333-3333-3333-333333333333")
JETZT = datetime(2026, 1, 1, tzinfo=UTC)
PROJEKT = Projekt(
    P, "Projekt Löschtest", (), Projektstatus.ENTWURF, JETZT, JETZT,
    Untersuchungsauftrag("Problem", "System analysieren", Systemtyp.PRODUKTION, "Grenze"),
)
def datensatz(datensatz_id, tag):
    return Zwischendatensatz(
        datensatz_id, P, UUID(int=10 + tag), (UUID(int=20 + tag),),
        f"daten-{tag}.parquet", f"schema-{tag}.json", f"plan-{tag}.json",
        str(tag) * 64, 10 * tag, 3, JETZT,
    )
DATENSAETZE = [datensatz(D1, 1), datensatz(D2, 2)]

class Projekte:
    def projekte_auflisten(self): return [PROJEKT]
class Transformationen:
    def datensaetze_fuer_projekt(self, projekt_id):
        assert projekt_id == P
        return DATENSAETZE if st.session_state.get("mit_datensaetzen", True) else []
class Loeschen:
    def projekt_loeschen(self, projekt_id):
        st.session_state["geloeschtes_projekt"] = str(projekt_id)
    def zwischendatensatz_loeschen(self, projekt_id, datensatz_id):
        st.session_state["geloeschter_datensatz"] = (str(projekt_id), str(datensatz_id))

if "test_initialisiert" not in st.session_state:
    st.session_state.test_initialisiert = True
    st.session_state.ausgewaehlte_projekt_id = P
    st.session_state.aktuelles_projekt_id = str(P)
    st.session_state.aktueller_zwischendatensatz_id = str(D2)
st.sidebar.radio(
    "Framework-Bereich",
    ["1 Projektrahmen definieren"],
    key="framework_bereich",
)
zeige_projektverwaltung(Projekte(), Transformationen(), Loeschen())
"""


def _app(*, mit_datensaetzen: bool = True) -> AppTest:
    app = AppTest.from_string(APP, default_timeout=10)
    app.session_state["mit_datensaetzen"] = mit_datensaetzen
    return app.run()


def test_loeschaktionen_liegen_im_sidebar_projektrahmen_ohne_bestaetigungstext() -> None:
    app = _app()
    assert not app.exception
    sidebar_labels = {wert.label for wert in app.sidebar.button}
    assert {"Projekt löschen", "Datensatz löschen"} <= sidebar_labels
    assert not any(
        "Bestätigung" in wert.label or "Kurz-ID" in wert.label for wert in app.text_input
    )

    ohne_datensatz = _app(mit_datensaetzen=False)
    assert "Projekt löschen" in {wert.label for wert in ohne_datensatz.sidebar.button}
    assert "Datensatz löschen" not in {wert.label for wert in ohne_datensatz.sidebar.button}


def test_projektloeschung_setzt_nur_pending_navigation_ohne_widgetabsturz() -> None:
    app = _app()
    next(wert for wert in app.sidebar.button if wert.label == "Projekt löschen").click().run()
    assert len(app.get("dialog")) == 1
    assert any("Projekt Löschtest" in wert.value for wert in app.warning)
    assert not app.exception

    projekt_id = UUID("11111111-1111-1111-1111-111111111111")
    aufrufe = []
    service = SimpleNamespace(projekt_loeschen=lambda ziel: aufrufe.append(ziel))
    zustand = {"framework_bereich": "7 Ergebnisse aggregieren"}
    _projektloeschung_ausfuehren(
        cast(Any, SimpleNamespace(projekt_id=projekt_id, bezeichnung="Projekt Löschtest")),
        cast(Any, service),
        zustand,
    )
    assert aufrufe == [projekt_id]
    assert zustand["framework_bereich"] == "7 Ergebnisse aggregieren"
    assert zustand["naechster_framework_bereich"] == "1 Projektrahmen definieren"


def test_datensatzloeschung_trifft_aktive_auswahl_und_oeffnet_schritt_zwei() -> None:
    app = _app()
    next(wert for wert in app.sidebar.button if wert.label == "Datensatz löschen").click().run()
    assert len(app.get("dialog")) == 1
    assert any("20 Zeilen" in wert.value for wert in app.warning)
    assert not app.exception

    projekt_id = UUID("11111111-1111-1111-1111-111111111111")
    datensatz_id = UUID("33333333-3333-3333-3333-333333333333")
    aufrufe = []
    service = SimpleNamespace(
        zwischendatensatz_loeschen=lambda projekt, datensatz: aufrufe.append((projekt, datensatz))
    )
    datensatz = SimpleNamespace(
        zwischendatensatz_id=datensatz_id,
        erstellt_am=datetime(2026, 1, 1, tzinfo=UTC),
        zeilenanzahl=20,
        spaltenanzahl=3,
    )
    zustand = {
        "framework_bereich": "1 Projektrahmen definieren",
        "aktueller_zwischendatensatz_id": str(datensatz_id),
    }
    _datensatzloeschung_ausfuehren(
        cast(Any, SimpleNamespace(projekt_id=projekt_id)),
        datensatz,
        cast(Any, service),
        zustand,
    )
    assert aufrufe == [(projekt_id, datensatz_id)]
    assert zustand["framework_bereich"] == "1 Projektrahmen definieren"
    assert zustand["naechster_framework_bereich"] == "2 ETL durchführen"
