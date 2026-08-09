"""Schlanker Einstiegspunkt der Streamlit-Anwendung."""

from uuid import UUID

import streamlit as st

from framework_mvp import __version__
from framework_mvp.bootstrap import (
    erstelle_datenimport_service,
    erstelle_datenqualitaet_service,
    erstelle_datenquelle_service,
    erstelle_event_log_konfigurations_service,
    erstelle_event_log_service,
    erstelle_importvorgang_service,
    erstelle_mappingtabelle_service,
    erstelle_process_mining_service,
    erstelle_projekt_service,
    erstelle_transformations_service,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.navigation import FRAMEWORK_BEREICHE
from framework_mvp.ui.pages.datenqualitaet import zeige_datenqualitaet_seite
from framework_mvp.ui.pages.etl import zeige_etl_seite
from framework_mvp.ui.pages.event_log import zeige_event_log_seite
from framework_mvp.ui.pages.process_mining import zeige_process_mining_seite
from framework_mvp.ui.pages.projektverwaltung import zeige_projektverwaltung
from framework_mvp.ui.pages.semantisches_mapping import zeige_semantisches_mapping
from framework_mvp.workspace import WorkspaceKonfiguration

st.set_page_config(
    page_title="Framework-MVP",
    page_icon="🏭",
    layout="wide",
)

st.title("Datengetriebene konzeptionelle Modellierung")
st.caption(f"Framework-MVP · Version {__version__}")

if naechster_bereich := st.session_state.pop("naechster_framework_bereich", None):
    st.session_state.framework_bereich = naechster_bereich

seite = st.sidebar.radio(
    "Framework-Bereich",
    FRAMEWORK_BEREICHE,
    key="framework_bereich",
)
projekt_service = erstelle_projekt_service()
workspace = WorkspaceKonfiguration.ermitteln()
if seite == "Schritt 1: Projektrahmen definieren":
    zeige_projektverwaltung(projekt_service)
elif seite == "2 ETL durchführen":
    zeige_etl_seite(
        projekt_service,
        erstelle_datenquelle_service(),
        erstelle_datenimport_service(),
        erstelle_importvorgang_service(workspace=workspace),
        erstelle_transformations_service(workspace=workspace),
        workspace,
    )
elif seite == "3 Semantisches Mapping":
    transformations_service = erstelle_transformations_service(workspace=workspace)
    zeige_semantisches_mapping(
        projekt_service,
        transformations_service,
        erstelle_mappingtabelle_service(workspace=workspace),
        erstelle_datenquelle_service(),
    )
elif seite == "4 Event Log aufbauen":
    zeige_event_log_seite(
        projekt_service,
        erstelle_event_log_konfigurations_service(workspace=workspace),
        erstelle_mappingtabelle_service(workspace=workspace),
        erstelle_transformations_service(workspace=workspace),
        erstelle_event_log_service(workspace=workspace),
        erstelle_datenquelle_service(),
    )
elif seite == "5 Datenqualität prüfen":
    event_log_service = erstelle_event_log_service(workspace=workspace)
    zeige_datenqualitaet_seite(
        projekt_service,
        event_log_service,
        erstelle_datenqualitaet_service(workspace=workspace),
    )
elif seite == "6 Process Mining durchführen":
    zeige_process_mining_seite(
        projekt_service,
        erstelle_datenqualitaet_service(workspace=workspace),
        erstelle_process_mining_service(workspace=workspace),
    )
else:
    st.header("7 Ergebnisse aggregieren")
    try:
        projekt_id = UUID(str(st.session_state.get("aktuelles_projekt_id")))
        freigabe_id = UUID(str(st.session_state.get("aktuelle_freigabe_id")))
        analyse_id = UUID(str(st.session_state.get("aktuelle_analyse_id")))
        analyse, a_d, _ = erstelle_process_mining_service(workspace=workspace).uebergabe_laden(
            analyse_id, projekt_id, freigabe_id
        )
        st.success(
            "Die Eingaben aus Schritt 6 wurden erneut validiert: "
            f"Prozessmodell P und Discovery-Ergebnisse A_D der Analyse {analyse.analyse_id}."
        )
        st.caption(
            f"Freigabe {analyse.qualitaetspruefung_id} · Event Log {analyse.event_log_id} · "
            f"Notation {a_d['prozessnotation']}"
        )
        st.info("Der fachliche Ablauf von Schritt 7 ist nicht Bestandteil dieses Auftrags.")
    except (
        TypeError,
        ValueError,
        KeyError,
        Domaenenfehler,
        Importintegritaetsfehler,
    ) as fehler:
        st.error(
            "Schritt 7 benötigt eine erfolgreich gespeicherte und erneut validierte Kombination "
            f"aus P und A_D aus Schritt 6: {fehler}"
        )
