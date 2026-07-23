"""Framework-Schritt 4: kanonisches Event Log aufbauen."""

from typing import Any
from uuid import UUID, uuid4

import pandas as pd
import streamlit as st

from framework_mvp.application.event_log_service import EventLogService
from framework_mvp.application.mapping_service import MappingService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt

SCHRITTE = (
    "Projekt und Mapping auswählen",
    "Mapping und Datensatz prüfen",
    "Event Log konfigurieren",
    "Event Log erzeugen",
    "Event Log prüfen und speichern",
)
KURZ = ("Auswahl", "Prüfung", "Konfiguration", "Erzeugen", "Speichern")


def _zustand(projekt_id: UUID) -> dict[str, Any]:
    return st.session_state.setdefault("event_log_zustaende", {}).setdefault(
        str(projekt_id), {"schritt": 1}
    )


def _projekt(service: ProjektService) -> UUID | None:
    projekte = service.projekte_auflisten()
    if not projekte:
        st.warning("Es muss zuerst ein Projekt angelegt werden.")
        return None
    optionen = [wert.projekt_id for wert in projekte]
    return st.selectbox(
        "Projekt",
        optionen,
        format_func=lambda wert: next(
            projekt.bezeichnung for projekt in projekte if projekt.projekt_id == wert
        ),
    )


def _navigation(zustand: dict[str, Any], weiter_moeglich: bool) -> None:
    links, rechts = st.columns(2)
    if links.button("Zurück", disabled=zustand["schritt"] == 1, width="stretch"):
        zustand["schritt"] -= 1
        st.rerun()
    if rechts.button(
        "Weiter",
        disabled=zustand["schritt"] == len(SCHRITTE) or not weiter_moeglich,
        type="primary",
        width="stretch",
    ):
        zustand["schritt"] += 1
        st.rerun()


def zeige_event_log_seite(
    projekt_service: ProjektService,
    mapping_service: MappingService,
    event_log_service: EventLogService,
) -> None:
    """Zeigt den fünfstufigen Event-Log-Wizard."""
    st.header("4 Event Log aufbauen")
    projekt_id = _projekt(projekt_service)
    if projekt_id is None:
        return
    zustand = _zustand(projekt_id)
    zeige_kompakten_fortschritt(schritt=zustand["schritt"], kurze_namen=KURZ, lange_namen=SCHRITTE)
    mappings = mapping_service.fuer_projekt(projekt_id)
    weiter = False
    if zustand["schritt"] == 1:
        if not mappings:
            st.warning("Für das Projekt ist noch kein gespeichertes Mapping vorhanden.")
        else:
            mapping_id = st.selectbox(
                "Validiertes semantisches Mapping",
                [wert.mapping_id for wert in mappings],
            )
            zustand["mapping_id"] = mapping_id
            weiter = True
    elif zustand["schritt"] == 2:
        mapping = mapping_service.laden(zustand["mapping_id"])
        if mapping is None:
            st.error("Das Mapping wurde nicht gefunden.")
        else:
            st.write(f"**Mappingmodus:** {mapping.mapping_modus.value}")
            st.write(f"**Zwischendatensatz:** `{mapping.zwischendatensatz_id}`")
            st.write(f"**Fall-ID:** {', '.join(mapping.fall_id.spalten)}")
            weiter = True
    elif zustand["schritt"] == 3:
        st.info(
            "Das gespeicherte Mapping wird unverändert angewendet. CSV.GZ ist das "
            "kanonische Artefakt; ein XES-Export wird in diesem Inkrement nicht erzeugt."
        )
        st.checkbox("Technische Herkunftsspalten in der Vorschau anzeigen", key="event_lineage")
        weiter = True
    elif zustand["schritt"] == 4:
        ergebnis = event_log_service.vorschau(zustand["mapping_id"])
        zustand["ergebnis"] = ergebnis
        kennzahlen = pd.DataFrame(
            [
                ("Ereignisse", ergebnis.ereignisanzahl),
                ("Fälle", ergebnis.fallanzahl),
                ("Aktivitäten", ergebnis.aktivitaetsanzahl),
                ("Frühester Zeitpunkt", ergebnis.fruehester_zeitpunkt),
                ("Spätester Zeitpunkt", ergebnis.spaetester_zeitpunkt),
            ],
            columns=["Kennzahl", "Wert"],
        ).astype("string")
        st.dataframe(kennzahlen, hide_index=True, width="stretch")
        spalten = list(ergebnis.ereignisse.columns)
        if not st.session_state.get("event_lineage"):
            spalten = [wert for wert in spalten if not wert.startswith("_source")]
        st.dataframe(ergebnis.ereignisse.loc[:, spalten].head(200), width="stretch")
        st.write("**Ereignisse pro Fall**")
        st.dataframe(
            ergebnis.ereignisse["case_id"]
            .value_counts()
            .rename_axis("case_id")
            .reset_index(name="ereignisse"),
            hide_index=True,
            width="stretch",
        )
        standard = {
            "case_id",
            "activity",
            "timestamp",
            "start_timestamp",
            "end_timestamp",
            "lifecycle",
            "resource",
            "event_id",
        }
        standardisierte = ", ".join(wert for wert in spalten if wert in standard)
        zusaetzliche = ", ".join(
            wert for wert in spalten if wert not in standard and not wert.startswith("_")
        )
        st.write(f"**Standardisierte Spalten:** {standardisierte}")
        st.write(f"**Zusätzliche Attribute:** {zusaetzliche or 'keine'}")
        st.bar_chart(ergebnis.ereignisse["activity"].value_counts())
        with st.expander("Technische Herkunft"):
            st.json(ergebnis.herkunft_standardspalten)
            st.dataframe(
                ergebnis.ereignisse[
                    [
                        "event_id",
                        "_source_row",
                        "_source_timestamp_column",
                    ]
                ].head(200),
                hide_index=True,
                width="stretch",
            )
        for warnung in ergebnis.warnungen:
            st.warning(warnung)
        weiter = ergebnis.ereignisanzahl > 0
    else:
        event_log_id = zustand.setdefault("event_log_id", uuid4())
        artefakt = zustand.get("artefakt")
        if artefakt is None and st.button("Event Log verbindlich speichern", type="primary"):
            zustand["artefakt"] = event_log_service.speichern(event_log_id, zustand["mapping_id"])
            st.rerun()
        elif artefakt is not None:
            st.success("Das kanonische Event Log wurde gespeichert.")
            st.write(f"**CSV.GZ:** `{artefakt.relativer_csv_pfad}`")
            st.write(f"**Schema:** `{artefakt.relativer_schema_pfad}`")
            st.write(f"**Lineage:** `{artefakt.relativer_lineage_pfad}`")
    _navigation(zustand, weiter)
