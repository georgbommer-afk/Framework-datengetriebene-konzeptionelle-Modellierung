"""Schlanker Einstiegspunkt der Streamlit-Anwendung."""

import streamlit as st

from framework_mvp import __version__
from framework_mvp.bootstrap import (
    erstelle_datenimport_service,
    erstelle_datenqualitaet_service,
    erstelle_datenquelle_service,
    erstelle_event_log_service,
    erstelle_importvorgang_service,
    erstelle_mapping_service,
    erstelle_projekt_service,
    erstelle_transformations_service,
)
from framework_mvp.ui.pages.datenqualitaet import zeige_datenqualitaet_seite
from framework_mvp.ui.pages.etl import zeige_etl_seite
from framework_mvp.ui.pages.event_log import zeige_event_log_seite
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

seite = st.sidebar.radio(
    "Framework-Bereich",
    (
        "1 Projektverwaltung",
        "2 ETL durchführen",
        "3 Semantisches Mapping",
        "4 Event Log aufbauen",
        "5 Datenqualität prüfen",
    ),
)
projekt_service = erstelle_projekt_service()
workspace = WorkspaceKonfiguration.ermitteln()
if seite == "1 Projektverwaltung":
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
        erstelle_mapping_service(workspace=workspace),
    )
elif seite == "4 Event Log aufbauen":
    zeige_event_log_seite(
        projekt_service,
        erstelle_mapping_service(workspace=workspace),
        erstelle_event_log_service(workspace=workspace),
    )
else:
    event_log_service = erstelle_event_log_service(workspace=workspace)
    zeige_datenqualitaet_seite(
        projekt_service,
        event_log_service,
        erstelle_datenqualitaet_service(workspace=workspace),
    )
