"""Streamlit-Integrationstests des fachlichen Schritt-4-Ablaufs."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from streamlit.testing.v1 import AppTest

from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    Attributrolle,
    MappingModus,
    Mappingstatus,
    SemantischesMapping,
    Spaltenzuordnung,
    ZeitstempelZuordnung,
    ZusammengesetzteFallId,
)

APP = r"""
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.application.mapping import validiere_mapping
from framework_mvp.domain.models import (
    Mappingeintrag, Mappingstatus, Mappingtabelle, Zwischendatensatz,
)
from framework_mvp.ui.pages.event_log import zeige_event_log_seite

P = UUID("11111111-1111-1111-1111-111111111111")
T = UUID("22222222-2222-2222-2222-222222222222")
DATENSATZ = Zwischendatensatz(
    T, P, UUID("33333333-3333-3333-3333-333333333333"),
    (UUID("44444444-4444-4444-4444-444444444444"),),
    "T.csv.gz", "T.schema.json", "T.transformation.json", "a" * 64,
    2, 7, datetime.now(UTC),
)
DATEN = pd.DataFrame({
    "auftrag": ["A", "A"],
    "aktion": ["Start", "Ende"],
    "zeit": ["2025-01-02", "2025-01-01"],
    "startzeit": ["2025-01-01", None],
    "endzeit": ["2025-01-02", "2025-01-03"],
    "soll_start": ["2025-01-01", "2025-01-02"],
    "soll_ende": ["2025-01-02", "2025-01-03"],
    "ressource": ["R1", "R2"],
    "status": ["started", "complete"],
    "merkmal_a": ["x", "y"],
    "merkmal_b": [1, 2],
})
MAPPING = replace(
    Mappingtabelle.neu(P, T),
    mapping_id=UUID("55555555-5555-5555-5555-555555555555"),
).eintrag_hinzufuegen(
    Mappingeintrag.fuer_spalte("auftrag", "Produktionsauftrag")
).bestaetigen()

class Projekte:
    def projekt_laden(self, projekt_id):
        return SimpleNamespace(projekt_id=projekt_id, bezeichnung="E-Projekt")

class Transformationen:
    def datensaetze_fuer_projekt(self, projekt_id): return [DATENSATZ]
    def zwischendatensatz_laden(self, datensatz_id): return DATENSATZ, DATEN.copy(deep=True)
    def plan_laden(self, plan_id): return None
    def importe_fuer_projekt(self, projekt_id): return []

class Mappingtabellen:
    def fuer_datensatz(self, projekt_id, datensatz_id):
        return None if st.session_state.get("ohne_m") else MAPPING
    def laden(self, mapping_id):
        return MAPPING if mapping_id == MAPPING.mapping_id else None

class Konfigurationen:
    def fuer_projekt(self, projekt_id):
        wert = st.session_state.get("test_konfiguration")
        return [wert] if wert is not None else []
    def validieren(self, mapping, daten):
        ergebnis = validiere_mapping(daten, mapping)
        mapping = replace(
            mapping, validierung=ergebnis.validierung, status=Mappingstatus.VALIDIERT
        )
        return mapping, ergebnis
    def speichern(self, mapping):
        st.session_state["test_konfiguration"] = mapping
        return "konfiguration.json"
    def laden(self, mapping_id):
        return st.session_state.get("test_konfiguration")

class EventLogs:
    def speichern(self, event_log_id, konfigurations_id):
        st.session_state["test_event_log_id"] = event_log_id
        return SimpleNamespace(
            relativer_csv_pfad="E.csv.gz",
            relativer_schema_pfad="E.schema.json",
            relativer_lineage_pfad="E.lineage.json",
        )

zeige_event_log_seite(
    Projekte(), Konfigurationen(), Mappingtabellen(), Transformationen(), EventLogs()
)
"""


def _app(*, ohne_m: bool = False) -> AppTest:
    app = AppTest.from_string(APP)
    app.session_state["aktuelles_projekt_id"] = "11111111-1111-1111-1111-111111111111"
    app.session_state["aktueller_zwischendatensatz_id"] = "22222222-2222-2222-2222-222222222222"
    app.session_state["ohne_m"] = ohne_m
    return app.run()


def _button(app: AppTest, label: str):  # type: ignore[no-untyped-def]
    return next(wert for wert in app.button if wert.label == label)


def test_schritt_vier_verwendet_zentralen_kontext_und_zeigt_t_und_m() -> None:
    app = _app()
    assert not app.exception
    assert not any(wert.label == "Projekt" for wert in app.selectbox)
    assert not any(wert.label == "Zwischendatensatz" for wert in app.selectbox)
    assert any("Aktuelles Projekt: E-Projekt" in wert.value for wert in app.markdown)
    assert any("Semantische Sicht" in wert.value for wert in app.markdown)
    assert any("Unveränderte Vorschau" in wert.value for wert in app.markdown)
    assert any(wert.label == "Wie sind die Ereignisse in T dargestellt?" for wert in app.radio)


def test_schritt_vier_ist_auch_ohne_m_zulaessig() -> None:
    app = _app(ohne_m=True)
    assert not app.exception
    assert any("kein M vorhanden" in wert.value for wert in app.info)
    assert any(wert.label == "Weiter" and not wert.disabled for wert in app.button)


def test_regulaere_oberflaeche_hat_genau_eine_fallspalte_und_begrenzte_aktivitaet() -> None:
    app = _app()
    _button(app, "Weiter").click().run()
    assert {wert.label for wert in app.selectbox} >= {
        "Fallidentifikation",
        "Aktivitätsspalte",
        "Ereigniszeitstempel",
    }
    assert not any("Fall-ID-Bestandteil" in wert.label for wert in app.selectbox)
    next(w for w in app.radio if w.label == "Aktivitätsbeschreibung").set_value(
        "Aus mehreren Attributen zusammensetzen"
    ).run()
    next(w for w in app.selectbox if w.label == "1. Bestandteil").select_index(0).run()
    next(w for w in app.selectbox if w.label == "2. Bestandteil").select_index(0).run()
    labels = {wert.label for wert in (*app.text_input, *app.selectbox, *app.number_input)}
    assert "Verknüpfungselement (optional)" in labels
    assert "1. Bestandteil" in labels and "2. Bestandteil" in labels
    assert not {"Präfix (optional)", "Suffix (optional)", "Verhalten bei leeren Werten"} & labels


def test_breite_oberflaeche_erfasst_beschreibung_je_zeitstempelspalte() -> None:
    app = _app()
    next(w for w in app.radio if w.label == "Wie sind die Ereignisse in T dargestellt?").set_value(
        "breiter_zeitstempeldatensatz"
    ).run()
    _button(app, "Weiter").click().run()
    next(w for w in app.multiselect if w.label == "Relevante Zeitstempelspalten").set_value(
        ["startzeit", "endzeit"]
    ).run()
    labels = {wert.label for wert in app.text_input}
    assert any("startzeit" in wert for wert in labels)
    assert any("endzeit" in wert for wert in labels)


def test_rollenschritt_zeigt_optionale_rollen_und_kanonische_vorschau() -> None:
    app = AppTest.from_string(APP)
    projekt_id = UUID("11111111-1111-1111-1111-111111111111")
    datensatz_id = UUID("22222222-2222-2222-2222-222222222222")
    app.session_state["aktuelles_projekt_id"] = str(projekt_id)
    app.session_state["aktueller_zwischendatensatz_id"] = str(datensatz_id)
    app.session_state["event_log_zustaende"] = {
        str(projekt_id): {
            "schritt": 3,
            "datensatz_id": str(datensatz_id),
            "konfigurations_id": uuid4(),
            "erstellt_am": datetime.now(UTC),
            "mapping_modus": MappingModus.EREIGNISORIENTIERT,
            "fall_id": "auftrag",
            "aktivitaetsquellen": ("aktion",),
            "zeitstempelspalte": "zeit",
            "zeitstempelzuordnungen": (),
            "zusaetzliche_attribute": (),
        }
    }
    app = app.run()

    labels = {wert.label for wert in app.selectbox}
    assert {
        "Ressourcenspalte",
        "Ist-Startzeitpunkt",
        "Ist-Endzeitpunkt",
        "Lifecycle-/Statusspalte",
    } <= labels
    startauswahl = next(w for w in app.selectbox if w.label == "Ist-Startzeitpunkt")
    endauswahl = next(w for w in app.selectbox if w.label == "Ist-Endzeitpunkt")
    assert "zeit" in startauswahl.options
    assert "zeit" in endauswahl.options
    assert any("Ereigniszeitstempel ordnet" in wert.value for wert in app.caption)
    next(w for w in app.selectbox if w.label == "Ressourcenspalte").set_value("ressource").run()
    next(w for w in app.selectbox if w.label == "Ist-Startzeitpunkt").set_value("zeit").run()
    assert "zeit" not in next(w for w in app.selectbox if w.label == "Ist-Endzeitpunkt").options
    next(w for w in app.selectbox if w.label == "Ist-Endzeitpunkt").set_value("endzeit").run()
    next(w for w in app.selectbox if w.label == "Lifecycle-/Statusspalte").set_value("status").run()
    zusatzattribute = next(
        w for w in app.multiselect if w.label == "Weitere Attribute in E übernehmen"
    )
    assert "ressource" not in zusatzattribute.options

    _button(app, "Weiter").click().run()

    assert not app.exception
    gespeicherte_konfiguration = app.session_state["test_konfiguration"]
    assert gespeicherte_konfiguration.konfigurationsversion == 5
    assert gespeicherte_konfiguration.zeitstempelspalte == "zeit"
    assert gespeicherte_konfiguration.startzeitstempelspalte == "zeit"
    assert gespeicherte_konfiguration.endzeitstempelspalte == "endzeit"
    herkunft = next(
        wert
        for wert in app.dataframe
        if list(wert.value.columns) == ["Spalte in E", "Rolle", "Quellspalte(n) in T"]
    ).value
    assert {"resource", "start_timestamp", "end_timestamp", "lifecycle"} <= set(
        herkunft["Spalte in E"]
    )
    assert (
        herkunft.loc[herkunft["Spalte in E"] == "resource", "Quellspalte(n) in T"].iloc[0]
        == "ressource"
    )
    assert (
        herkunft.loc[herkunft["Spalte in E"] == "start_timestamp", "Quellspalte(n) in T"].iloc[0]
        == "zeit"
    )


def test_breiter_rollenschritt_bietet_ressource_und_status_je_zeitzuordnung() -> None:
    app = AppTest.from_string(APP)
    projekt_id = UUID("11111111-1111-1111-1111-111111111111")
    datensatz_id = UUID("22222222-2222-2222-2222-222222222222")
    app.session_state["aktuelles_projekt_id"] = str(projekt_id)
    app.session_state["aktueller_zwischendatensatz_id"] = str(datensatz_id)
    app.session_state["event_log_zustaende"] = {
        str(projekt_id): {
            "schritt": 3,
            "datensatz_id": str(datensatz_id),
            "konfigurations_id": uuid4(),
            "erstellt_am": datetime.now(UTC),
            "mapping_modus": MappingModus.BREITER_ZEITSTEMPELDATENSATZ,
            "fall_id": "auftrag",
            "aktivitaetsquellen": (),
            "zeitstempelspalte": "",
            "zeitstempelzuordnungen": (
                ZeitstempelZuordnung("startzeit", "Start"),
                ZeitstempelZuordnung("endzeit", "Ende"),
            ),
            "zusaetzliche_attribute": (),
        }
    }
    app = app.run()

    assert sum(w.label == "Ressourcenspalte" for w in app.selectbox) == 2
    assert sum(w.label == "Lifecycle-/Statusspalte" for w in app.selectbox) == 2
    assert not any("Ist-Startzeitpunkt →" in w.label for w in app.selectbox)
    assert not any("Ist-Endzeitpunkt →" in w.label for w in app.selectbox)


def test_ereignisorientierter_ablauf_speichert_e_und_setzt_aktiven_kontext() -> None:
    app = AppTest.from_string(APP)
    projekt_id = UUID("11111111-1111-1111-1111-111111111111")
    datensatz_id = UUID("22222222-2222-2222-2222-222222222222")
    app.session_state["aktuelles_projekt_id"] = str(projekt_id)
    app.session_state["aktueller_zwischendatensatz_id"] = str(datensatz_id)
    app.session_state["event_log_zustaende"] = {
        str(projekt_id): {
            "schritt": 4,
            "datensatz_id": str(datensatz_id),
            "konfigurations_id": uuid4(),
            "erstellt_am": datetime.now(UTC),
            "mapping_modus": MappingModus.EREIGNISORIENTIERT,
            "fall_id": "auftrag",
            "aktivitaetsquellen": ("aktion",),
            "zeitstempelspalte": "zeit",
            "zeitstempelzuordnungen": (),
            "zusaetzliche_attribute": ("ressource",),
        }
    }
    app = app.run()
    assert not app.exception
    assert any("Fallbezogener Event Log (E)" in wert.value for wert in app.markdown)
    _button(app, "Event Log E speichern und zu Schritt 5: Datenqualität prüfen").click().run()
    assert not app.exception
    assert app.session_state["aktuelles_event_log_id"] == str(
        app.session_state["test_event_log_id"]
    )
    assert app.session_state["naechster_framework_bereich"] == "5 Datenqualität prüfen"
    assert any("wurde gespeichert" in wert.value for wert in app.success)

    zustand = app.session_state["event_log_zustaende"][str(projekt_id)]
    konfigurations_id = zustand["konfigurations_id"]
    _button(app, "Zurück").click().run()
    zustand = app.session_state["event_log_zustaende"][str(projekt_id)]
    assert zustand["schritt"] == 3
    assert zustand["konfigurations_id"] == konfigurations_id
    assert app.session_state["aktuelles_event_log_id"] == str(
        app.session_state["test_event_log_id"]
    )


def test_gespeicherte_konfiguration_rehydriert_mindestbestandteile_und_zeitrollen() -> None:
    projekt_id = UUID("11111111-1111-1111-1111-111111111111")
    datensatz_id = UUID("22222222-2222-2222-2222-222222222222")
    konfigurations_id = uuid4()
    jetzt = datetime.now(UTC)
    konfiguration = SemantischesMapping(
        mapping_id=konfigurations_id,
        projekt_id=projekt_id,
        zwischendatensatz_id=datensatz_id,
        mapping_modus=MappingModus.EREIGNISORIENTIERT,
        fall_id=ZusammengesetzteFallId(("auftrag",)),
        aktivitaetsspalte="aktion",
        zeitstempelspalte="startzeit",
        startzeitstempelspalte="startzeit",
        endzeitstempelspalte="endzeit",
        lifecycle_spalte="status",
        ressourcen_spalte="ressource",
        spaltenzuordnungen=(
            Spaltenzuordnung("merkmal_a", Attributrolle.EREIGNISATTRIBUT),
            Spaltenzuordnung("merkmal_b", Attributrolle.EREIGNISATTRIBUT),
        ),
        zeitstempelzuordnungen=(),
        validierung=None,
        erstellt_am=jetzt,
        geaendert_am=jetzt,
        status=Mappingstatus.VALIDIERT,
        aktivitaetsdefinition=Aktivitaetsdefinition(
            Aktivitaetsbildungsart.VORHANDENE_SPALTE, ("aktion",)
        ),
        mappingtabelle_id=UUID("55555555-5555-5555-5555-555555555555"),
        konfigurationsversion=5,
        plan_startzeitstempelspalte="soll_start",
        plan_endzeitstempelspalte="soll_ende",
    )
    app = AppTest.from_string(APP)
    app.session_state["aktuelles_projekt_id"] = str(projekt_id)
    app.session_state["aktueller_zwischendatensatz_id"] = str(datensatz_id)
    app.session_state["aktuelle_event_log_konfiguration_id"] = str(konfigurations_id)
    app.session_state["test_konfiguration"] = konfiguration
    app = app.run()

    _button(app, "Weiter").click().run()
    assert next(w for w in app.selectbox if w.label == "Fallidentifikation").value == "auftrag"
    assert next(w for w in app.selectbox if w.label == "Aktivitätsspalte").value == "aktion"
    assert next(w for w in app.selectbox if w.label == "Ereigniszeitstempel").value == "startzeit"
    _button(app, "Weiter").click().run()
    assert next(w for w in app.selectbox if w.label == "Ist-Startzeitpunkt").value == "startzeit"
    assert next(w for w in app.selectbox if w.label == "Ist-Endzeitpunkt").value == "endzeit"
    assert next(w for w in app.selectbox if w.label == "Ressourcenspalte").value == ("ressource")
    assert (
        next(w for w in app.selectbox if w.label == "Plan-/Soll-Startzeitpunkt").value
        == "soll_start"
    )
    assert (
        next(w for w in app.selectbox if w.label == "Plan-/Soll-Endzeitpunkt").value == "soll_ende"
    )
    assert next(
        w for w in app.multiselect if w.label == "Weitere Attribute in E übernehmen"
    ).value == ["merkmal_a", "merkmal_b"]
