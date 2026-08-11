"""Streamlit-Integrationstests des Quality-Gates und seiner Rücksprünge."""

from uuid import UUID

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.domain.models import FachlicheEntscheidung

APP = r"""
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.domain.models import (
    FachlicheEntscheidung, Freigabestatus, Mappingzustand, Qualitaetsfreigabe,
    QualityGateBefund, QualityGateBereich, QualityGateErgebnis, QualityGateStatus,
)
from framework_mvp.ui.pages.datenqualitaet import zeige_datenqualitaet_seite

P = UUID("11111111-1111-1111-1111-111111111111")
E = UUID("22222222-2222-2222-2222-222222222222")
T = UUID("33333333-3333-3333-3333-333333333333")
C = UUID("44444444-4444-4444-4444-444444444444")
F = UUID("55555555-5555-5555-5555-555555555555")
Q = UUID("66666666-6666-6666-6666-666666666666")
JETZT = datetime(2025, 1, 2, tzinfo=UTC)
DATEN = pd.DataFrame({
    "case_id": ["A"], "activity": ["Start"],
    "timestamp": pd.to_datetime(["2025-01-01"], utc=True), "event_id": ["e1"],
})
ARTEFAKT = SimpleNamespace(
    event_log_id=E, projekt_id=P, sha256="a" * 64,
    zeitraum_von=JETZT, zeitraum_bis=JETZT,
)
KONTEXT = SimpleNamespace(
    artefakt=ARTEFAKT,
    ereignisse=DATEN,
    zwischendatensatz=SimpleNamespace(zeilenanzahl=1, spaltenanzahl=3),
    mappingtabelle=None,
    lineage={
        "herkunft_standardspalten": {
            "case_id": "fall", "activity": "aktion", "timestamp": "zeit"
        },
        "herkunft_zusaetzliche_attribute": {},
    },
)
SNAPSHOT = json.dumps([{
    "datenquelle": {
        "bezeichnung": "ERP", "konkretes_quellsystem": "ERP Produktiv",
        "quellenart": "csv", "fachliche_beschreibung": "Aufträge",
        "herkunft_oder_verantwortungsbereich": "Planung", "datenquellen_id": str(Q),
    },
    "tabellenbezeichnung": "auftrag.csv", "import_id": str(UUID(int=7)),
}])

def ergebnis(entscheidungen=()):
    nach_id = {wert.kriterium_id: wert for wert in entscheidungen}
    befunde = [
        QualityGateBefund("q_auto", QualityGateBereich.DATENQUELLENKATALOG,
            "Herkunft und Grundlagen der verwendeten Daten nachvollziehbar dokumentiert",
            QualityGateStatus.AUTOMATISCH_BESTANDEN, "Q technisch bestanden", False),
        QualityGateBefund("t_auto", QualityGateBereich.ZWISCHENDATENSATZ,
            "Für die weitere Verarbeitung erforderliche Daten vollständig vorhanden",
            QualityGateStatus.AUTOMATISCH_BESTANDEN, "T technisch bestanden", False),
        QualityGateBefund("m_auto", QualityGateBereich.MAPPINGTABELLE,
            "Technische Bezeichnungen eindeutig und fachlich verständlich zugeordnet",
            QualityGateStatus.NICHT_ANWENDBAR, "Kein semantisches Mapping erforderlich", False),
        QualityGateBefund("e_auto", QualityGateBereich.EVENT_LOG,
            "Mindestbestandteile vollständig und interpretierbar vorhanden",
            QualityGateStatus.AUTOMATISCH_BESTANDEN, "E technisch bestanden", False),
    ]
    for kriterium_id, bereich, ruecksprung in (
        ("q_nachvollziehbar", QualityGateBereich.DATENQUELLENKATALOG, 1),
        ("e_interpretierbar", QualityGateBereich.EVENT_LOG, 4),
    ):
        entscheidung = nach_id.get(kriterium_id)
        status = (
            QualityGateStatus.FACHLICHE_BESTAETIGUNG_ERFORDERLICH
            if entscheidung is None else
            QualityGateStatus.FACHLICH_ALS_MANGEL_BEWERTET
            if entscheidung.ist_mangel else
            QualityGateStatus.FACHLICH_BEGRUENDET_KEIN_MANGEL
        )
        befunde.append(QualityGateBefund(
            kriterium_id, bereich, "Menschliche Verwendbarkeitsbewertung", status,
            "Fachliche Bestätigung erforderlich", False,
            ruecksprung if entscheidung is not None and entscheidung.ist_mangel else None,
            begruendung=entscheidung.begruendung if entscheidung is not None else "",
        ))
    block = st.session_state.get("test_block_step")
    if block:
        bereich = (QualityGateBereich.DATENQUELLENKATALOG,
                   QualityGateBereich.ZWISCHENDATENSATZ,
                   QualityGateBereich.MAPPINGTABELLE,
                   QualityGateBereich.EVENT_LOG)[block - 1]
        befunde.append(QualityGateBefund(
            f"block_{block}", bereich, "Pflichtprüfung", QualityGateStatus.AUTOMATISCHER_MANGEL,
            f"Ursache in Schritt {block}", True, block,
        ))
    return QualityGateErgebnis(
        P, E, T, C, None, Mappingzustand.NICHT_VORHANDEN, (Q,), SNAPSHOT,
        "ereignisorientiert", "a" * 64, "b" * 64, "", "c" * 64, "d" * 64,
        "e" * 64, 1, 1, 1, JETZT, JETZT, tuple(befunde), (), tuple(entscheidungen),
    )

FREIGABE = Qualitaetsfreigabe(
    F, P, E, "a" * 64, T, "b" * 64, C, None, "", Mappingzustand.NICHT_VORHANDEN,
    (Q,), "d" * 64, "c" * 64, "e" * 64,
    f"projects/{P}/quality/{F}.release.json", "f" * 64,
    Freigabestatus.FREIGEGEBEN, JETZT,
)

class Projekte:
    def projekt_laden(self, projekt_id):
        return SimpleNamespace(projekt_id=projekt_id, bezeichnung="Quality-Projekt")

class EventLogs:
    def fuer_projekt(self, projekt_id): return [ARTEFAKT]
    def kontext_laden(self, event_log_id): return KONTEXT

class Qualitaet:
    def quality_gate_pruefen(self, projekt_id, event_log_id, entscheidungen=()):
        return ergebnis(entscheidungen)
    def freigaben_fuer_event_log(self, projekt_id, event_log_id): return []
    def freigeben(self, freigabe_id, projekt_id, event_log_id, entscheidungen): return FREIGABE
    def freigabe_laden(self, freigabe_id): return FREIGABE, DATEN.copy(deep=True)

zeige_datenqualitaet_seite(Projekte(), EventLogs(), Qualitaet())
"""


def _app(*, schritt: int = 1, block: int | None = None) -> AppTest:
    app = AppTest.from_string(APP)
    projekt = UUID("11111111-1111-1111-1111-111111111111")
    event = UUID("22222222-2222-2222-2222-222222222222")
    app.session_state["aktuelles_projekt_id"] = str(projekt)
    app.session_state["aktuelles_event_log_id"] = str(event)
    app.session_state["test_block_step"] = block
    app.session_state["quality_gate_zustaende"] = {
        str(projekt): {
            "schritt": schritt,
            "event_log_id": str(event),
            "freigabe_id": UUID("55555555-5555-5555-5555-555555555555"),
            "entscheidungen": (
                FachlicheEntscheidung("q_nachvollziehbar", False, "Q ist nachvollziehbar."),
                FachlicheEntscheidung("e_interpretierbar", False, "E ist interpretierbar."),
            ),
        }
    }
    return app.run()


def _button(app: AppTest, label: str):  # type: ignore[no-untyped-def]
    return next(wert for wert in app.button if wert.label == label)


def test_schritt_fuenf_uebernimmt_projekt_und_aktives_e_ohne_lokale_auswahl() -> None:
    app = _app()
    assert not app.exception
    assert not any(wert.label in {"Projekt", "Event Log"} for wert in app.selectbox)
    assert any("Aktuelles Projekt: Quality-Projekt" in wert.value for wert in app.markdown)
    assert any("Datenquellenkatalog (Q)" in wert.value for wert in app.markdown)
    assert any("Zwischendatensatz (T)" in wert.value for wert in app.markdown)
    assert any("Event Log (E)" in wert.value for wert in app.markdown)


def test_nicht_eindeutige_e_ursache_wird_fachlich_einem_vorherigen_schritt_zugeordnet() -> None:
    app = _app(schritt=3)
    bewertungen = [wert for wert in app.radio if wert.label == "Fachliche Entscheidung"]
    bewertungen[-1].set_value("Als Mangel bewertet").run()
    ursache = next(
        wert for wert in app.selectbox if wert.label == "Ursächlicher vorheriger Schritt"
    )
    assert ursache.options == [
        "Schritt 2 – Ursache in T",
        "Schritt 3 – Ursache in M",
        "Schritt 4 – Konfiguration oder Erzeugung von E",
    ]


@pytest.mark.parametrize(
    ("block", "bereich"),
    (
        (1, "Schritt 1: Projektrahmen definieren"),
        (2, "2 ETL durchführen"),
        (3, "3 Semantisches Mapping"),
        (4, "4 Event Log aufbauen"),
    ),
)
def test_technischer_mangel_blockiert_e_stern_und_navigiert_zur_ursache(
    block: int, bereich: str
) -> None:
    app = _app(schritt=4, block=block)
    assert any("Rücksprung erforderlich" in wert.value for wert in app.error)
    assert not any("Schritt 6" in wert.label for wert in app.button)
    _button(app, f"Zu Schritt {block} zurückspringen").click().run()
    assert app.session_state["aktuelles_projekt_id"] == "11111111-1111-1111-1111-111111111111"
    assert app.session_state["naechster_framework_bereich"] == bereich


def test_erfolgreiche_freigabe_setzt_e_stern_kontext_und_erlaubt_schritt_sechs() -> None:
    app = _app(schritt=4)
    _button(app, "Event Log E unverändert als E* freigeben").click().run()
    assert not app.exception
    assert app.session_state["aktuelle_freigabe_id"] == "55555555-5555-5555-5555-555555555555"
    assert app.session_state["freigegebenes_event_log_id"] == (
        "22222222-2222-2222-2222-222222222222"
    )
    assert any("keine zusätzliche Qualitäts-CSV" in wert.value for wert in app.success)
    _button(app, "Weiter").click().run()
    assert app.session_state["naechster_framework_bereich"] == "6 Process Mining durchführen"


def test_automatische_pruefung_verwendet_die_fachliche_ueberschrift() -> None:
    app = _app(schritt=2)
    assert any(
        "Datenqualitätsprüfung der erzeugten Artefakte" in wert.value for wert in app.markdown
    )
    assert not any("Verbindliche Kriterien aus Tabelle 3.14" in wert.value for wert in app.markdown)
