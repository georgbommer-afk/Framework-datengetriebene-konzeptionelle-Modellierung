"""Schlanker Einstiegspunkt der Streamlit-Anwendung."""

import streamlit as st

from framework_mvp import __version__
from framework_mvp.bootstrap import (
    erstelle_datenimport_service,
    erstelle_datenqualitaet_service,
    erstelle_datenquelle_service,
    erstelle_ergebnisaggregation_service,
    erstelle_event_log_konfigurations_service,
    erstelle_event_log_service,
    erstelle_importvorgang_service,
    erstelle_loesch_service,
    erstelle_mappingtabelle_service,
    erstelle_modellableitung_service,
    erstelle_modellausgabe_service,
    erstelle_modellvalidierung_service,
    erstelle_process_mining_service,
    erstelle_projekt_service,
    erstelle_transformations_service,
)
from framework_mvp.ui.navigation import FRAMEWORK_BEREICHE
from framework_mvp.ui.pages.datenqualitaet import zeige_datenqualitaet_seite
from framework_mvp.ui.pages.ergebnisaggregation import zeige_ergebnisaggregation_seite
from framework_mvp.ui.pages.etl import zeige_etl_seite
from framework_mvp.ui.pages.event_log import zeige_event_log_seite
from framework_mvp.ui.pages.modellableitung import zeige_modellableitung_seite
from framework_mvp.ui.pages.modellausgabe import zeige_modellausgabe_seite
from framework_mvp.ui.pages.modellvalidierung import zeige_modellvalidierung_seite
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
    zeige_projektverwaltung(projekt_service, erstelle_loesch_service(workspace=workspace))
elif seite == "2 ETL durchführen":
    zeige_etl_seite(
        projekt_service,
        erstelle_datenquelle_service(),
        erstelle_datenimport_service(),
        erstelle_importvorgang_service(workspace=workspace),
        erstelle_transformations_service(workspace=workspace),
        workspace,
        erstelle_loesch_service(workspace=workspace),
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
elif seite == "7 Ergebnisse aggregieren":
    zeige_ergebnisaggregation_seite(
        projekt_service,
        erstelle_ergebnisaggregation_service(workspace=workspace),
    )
elif seite == "8 Modellbestandteile ableiten":
    zeige_modellableitung_seite(
        projekt_service,
        erstelle_modellableitung_service(workspace=workspace),
    )
elif seite == "9 Modell ergänzen und validieren":
    zeige_modellvalidierung_seite(
        projekt_service,
        erstelle_modellvalidierung_service(workspace=workspace),
    )
else:
    validierungs_service = erstelle_modellvalidierung_service(workspace=workspace)
    zeige_modellausgabe_seite(
        projekt_service,
        validierungs_service,
        erstelle_modellausgabe_service(workspace=workspace),
    )
