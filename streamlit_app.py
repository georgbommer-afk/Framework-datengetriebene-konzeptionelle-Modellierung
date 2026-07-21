"""Einstiegspunkt der Streamlit-Anwendung."""

import streamlit as st

from framework_mvp import __version__

st.set_page_config(
    page_title="Framework-MVP",
    page_icon="🏭",
    layout="wide",
)

st.title("Datengetriebene konzeptionelle Modellierung")
st.caption(f"Framework-MVP · Version {__version__}")

st.info(
    "Die Anwendung wird schrittweise als softwaretechnische "
    "Instanziierung des in der Masterarbeit entwickelten Frameworks aufgebaut."
)
