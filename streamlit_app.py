"""Schlanker Einstiegspunkt der Streamlit-Anwendung."""

import streamlit as st

from framework_mvp import __version__
from framework_mvp.bootstrap import (
    erstelle_datenimport_service,
    erstelle_datenquelle_service,
    erstelle_importvorgang_service,
    erstelle_projekt_service,
)
from framework_mvp.ui.pages.etl import zeige_etl_seite
from framework_mvp.ui.pages.projektverwaltung import zeige_projektverwaltung
from framework_mvp.workspace import WorkspaceKonfiguration

st.set_page_config(
    page_title="Framework-MVP",
    page_icon="🏭",
    layout="wide",
)

st.title("Datengetriebene konzeptionelle Modellierung")
st.caption(f"Framework-MVP · Version {__version__}")

seite = st.sidebar.radio("Framework-Bereich", ("1 Projektverwaltung", "2 ETL durchführen"))
projekt_service = erstelle_projekt_service()
if seite == "1 Projektverwaltung":
    zeige_projektverwaltung(projekt_service)
else:
    workspace = WorkspaceKonfiguration.ermitteln()
    zeige_etl_seite(
        projekt_service,
        erstelle_datenquelle_service(),
        erstelle_datenimport_service(),
        erstelle_importvorgang_service(workspace=workspace),
        workspace,
    )
