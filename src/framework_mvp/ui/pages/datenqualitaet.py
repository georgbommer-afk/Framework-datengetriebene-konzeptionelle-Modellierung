"""Framework-Schritt 5: regelbasierte Datenqualität prüfen."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
import streamlit as st

from framework_mvp.application.datenqualitaet import filtere_befunde, standardregeln
from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.event_log_service import EventLogService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.models import (
    Massnahmenaktion,
    Qualitaetsmassnahme,
    Qualitaetsmassnahmenplan,
    Schweregrad,
)
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt

SCHRITTE = (
    "Event Log auswählen",
    "Qualitätsprüfung konfigurieren",
    "Prüfung ausführen",
    "Auffälligkeiten bewerten",
    "Maßnahmen festlegen",
    "Ergebnis prüfen und speichern",
)
KURZ = ("Event Log", "Regeln", "Prüfung", "Bewertung", "Maßnahmen", "Speichern")


def _zustand(projekt_id: UUID) -> dict[str, Any]:
    return st.session_state.setdefault("qualitaet_zustaende", {}).setdefault(
        str(projekt_id), {"schritt": 1}
    )


def _projekt(service: ProjektService) -> UUID | None:
    projekte = service.projekte_auflisten()
    if not projekte:
        st.warning("Es muss zuerst ein Projekt angelegt werden.")
        return None
    return st.selectbox(
        "Projekt",
        [wert.projekt_id for wert in projekte],
        format_func=lambda wert: next(
            projekt.bezeichnung for projekt in projekte if projekt.projekt_id == wert
        ),
        key="qualitaet_projekt",
    )


def _navigation(zustand: dict[str, Any], weiter: bool) -> None:
    links, rechts = st.columns(2)
    if links.button("Zurück", disabled=zustand["schritt"] == 1, width="stretch"):
        zustand["schritt"] -= 1
        st.rerun()
    if rechts.button(
        "Weiter",
        disabled=zustand["schritt"] == len(SCHRITTE) or not weiter,
        type="primary",
        width="stretch",
    ):
        zustand["schritt"] += 1
        st.rerun()


def _befundtabelle(ergebnis: Any) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Regel": wert.bezeichnung,
                "Dimension": wert.dimension.value,
                "Schweregrad": wert.schweregrad.value,
                "Ereignisse": wert.betroffene_ereignisse,
                "Fälle": wert.betroffene_faelle,
                "Anteil": wert.anteil,
                "Spalten": ", ".join(wert.betroffene_spalten),
                "Beispiele": ", ".join(str(index) for index in wert.beispielindizes),
                "Warum relevant": wert.technische_erlaeuterung,
                "Empfehlung": wert.fachliche_empfehlung,
            }
            for wert in ergebnis.befunde
        ]
    )


def zeige_datenqualitaet_seite(
    projekt_service: ProjektService,
    event_log_service: EventLogService,
    qualitaet_service: DatenqualitaetService,
) -> None:
    """Zeigt den sechsstufigen Qualitäts-Wizard."""
    st.header("5 Datenqualität prüfen")
    projekt_id = _projekt(projekt_service)
    if projekt_id is None:
        return
    zustand = _zustand(projekt_id)
    zeige_kompakten_fortschritt(schritt=zustand["schritt"], kurze_namen=KURZ, lange_namen=SCHRITTE)
    logs = event_log_service.fuer_projekt(projekt_id)
    weiter = False
    if zustand["schritt"] == 1:
        if not logs:
            st.warning("Für das Projekt ist noch kein Event Log vorhanden.")
        else:
            zustand["event_log_id"] = st.selectbox(
                "Kanonisches Event Log", [wert.event_log_id for wert in logs]
            )
            weiter = True
    elif zustand["schritt"] == 2:
        regeln = []
        for regel in standardregeln():
            aktiviert = st.checkbox(
                f"{regel.bezeichnung} · {regel.schweregrad.value}",
                value=regel.aktiviert,
                key=f"regel_{regel.regel_id}",
            )
            regeln.append(
                regel if aktiviert == regel.aktiviert else replace(regel, aktiviert=aktiviert)
            )
        zustand["regeln"] = tuple(regeln)
        st.info("Keine Regel verändert oder entfernt Ereignisse automatisch.")
        weiter = True
    elif zustand["schritt"] == 3:
        ergebnis = qualitaet_service.pruefen(zustand["event_log_id"], zustand["regeln"])
        zustand["pruefung"] = ergebnis
        grade = {wert: 0 for wert in Schweregrad}
        for wert in ergebnis.befunde:
            grade[wert.schweregrad] += 1
        st.dataframe(
            pd.DataFrame(
                [
                    ("Geprüfte Ereignisse", ergebnis.ereignisanzahl),
                    ("Geprüfte Fälle", ergebnis.fallanzahl),
                    ("Bestandene Regeln", ergebnis.bestandene_regeln),
                    *[(wert.value, grade[wert]) for wert in Schweregrad],
                ],
                columns=["Kennzahl", "Wert"],
            ),
            hide_index=True,
        )
        st.dataframe(_befundtabelle(ergebnis), hide_index=True, width="stretch")
        weiter = True
    elif zustand["schritt"] == 4:
        ergebnis = zustand["pruefung"]
        dimensionen = st.multiselect(
            "Qualitätsdimension", sorted({wert.dimension.value for wert in ergebnis.befunde})
        )
        schwere = st.multiselect("Schweregrad", [wert.value for wert in Schweregrad])
        regel_ids = st.multiselect("Regel", [wert.regel_id for wert in ergebnis.befunde])
        _, event_daten = event_log_service.laden(zustand["event_log_id"])
        aktivitaet = st.selectbox(
            "Aktivität", ["", *sorted(event_daten["activity"].dropna().astype(str).unique())]
        )
        fall_id = st.selectbox(
            "Fall-ID", ["", *sorted(event_daten["case_id"].dropna().astype(str).unique())]
        )
        spalten = st.multiselect(
            "Betroffene Spalte",
            sorted({spalte for befund in ergebnis.befunde for spalte in befund.betroffene_spalten}),
        )
        sichtbar = filtere_befunde(
            ergebnis.befunde,
            dimensionen=tuple(dimensionen),
            schweregrade=tuple(schwere),
            regel_ids=tuple(regel_ids),
            spalten=tuple(spalten),
            aktivitaet=aktivitaet,
            fall_id=fall_id,
            event_log=event_daten,
        )
        st.dataframe(_befundtabelle(type("E", (), {"befunde": sichtbar})()), width="stretch")
        weiter = True
    elif zustand["schritt"] == 5:
        befunde = zustand["pruefung"].befunde
        plan = zustand.get("plan", Qualitaetsmassnahmenplan(()))
        if befunde:
            regel_id = str(st.selectbox("Auffälligkeit", [wert.regel_id for wert in befunde]))
            aktion = st.selectbox(
                "Explizite Maßnahme",
                list(Massnahmenaktion),
                format_func=lambda wert: wert.value,
            )
            parameter: dict[str, object] = {}
            if aktion is Massnahmenaktion.FESTEN_WERT_SETZEN:
                parameter["spalte"] = st.selectbox(
                    "Zu ersetzende Spalte",
                    next(wert.betroffene_spalten for wert in befunde if wert.regel_id == regel_id),
                )
                parameter["wert"] = st.text_input("Expliziter fester Wert")
            begruendung = st.text_input("Fachliche Begründung")
            if st.button("Maßnahme hinzufügen"):
                befund = next(wert for wert in befunde if wert.regel_id == regel_id)
                massnahme = Qualitaetsmassnahme(
                    uuid4(),
                    regel_id,
                    aktion,
                    json.dumps(parameter, ensure_ascii=False),
                    begruendung,
                    befund.betroffene_ereignisse,
                    datetime.now(UTC),
                    len(plan.massnahmen) + 1,
                )
                plan = Qualitaetsmassnahmenplan((*plan.massnahmen, massnahme))
                zustand["plan"] = plan
                st.rerun()
        st.dataframe(
            pd.DataFrame([asdict(wert) for wert in plan.massnahmen]),
            hide_index=True,
            width="stretch",
        )
        weiter = True
    else:
        plan = zustand.get("plan", Qualitaetsmassnahmenplan(()))
        vorschau = qualitaet_service.massnahmen_vorschau(
            zustand["event_log_id"], zustand["regeln"], plan
        )
        vorher = zustand["pruefung"]
        st.dataframe(
            pd.DataFrame(
                [
                    ("Ereignisse", vorher.ereignisanzahl, vorschau.pruefung.ereignisanzahl),
                    ("Fälle", vorher.fallanzahl, vorschau.pruefung.fallanzahl),
                    ("Befunde", len(vorher.befunde), len(vorschau.pruefung.befunde)),
                    (
                        "Blockierende Probleme",
                        sum(wert.schweregrad is Schweregrad.BLOCKIEREND for wert in vorher.befunde),
                        sum(
                            wert.schweregrad is Schweregrad.BLOCKIEREND
                            for wert in vorschau.pruefung.befunde
                        ),
                    ),
                ],
                columns=["Kennzahl", "Vorher", "Nachher"],
            ),
            hide_index=True,
        )
        st.dataframe(_befundtabelle(vorschau.pruefung), width="stretch")
        artefakt = zustand.get("artefakt")
        if artefakt is None and st.button("Qualitätsgeprüften Datensatz speichern", type="primary"):
            zustand["artefakt"] = qualitaet_service.speichern(
                uuid4(), zustand["event_log_id"], zustand["regeln"], plan
            )
            st.rerun()
        elif artefakt is not None:
            st.success("Qualitätsbericht, Maßnahmen und Arbeitskopie wurden gespeichert.")
            st.write(f"`{artefakt.relativer_report_pfad}`")
            st.write(f"`{artefakt.relativer_massnahmen_pfad}`")
            st.write(f"`{artefakt.relativer_csv_pfad}`")
    _navigation(zustand, weiter)
