"""Schlanker Einstiegspunkt der Streamlit-Anwendung."""

import streamlit as st

from framework_mvp import __version__
from framework_mvp.bootstrap import erstelle_projekt_service
from framework_mvp.ui.pages.projektverwaltung import zeige_projektverwaltung

st.set_page_config(
    page_title="Framework-MVP",
    page_icon="🏭",
    layout="wide",
)

st.title("Datengetriebene konzeptionelle Modellierung")
st.caption(f"Framework-MVP · Version {__version__}")
st.write(
    "Diese Software instanziiert das in der Masterarbeit entwickelte Framework zur "
    "datengetriebenen Ableitung konzeptioneller Modelle."
)

zeige_projektverwaltung(erstelle_projekt_service())
