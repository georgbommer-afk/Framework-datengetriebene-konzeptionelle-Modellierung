"""Wiederverwendbarer, handlungsorientierter Hinweis bei veralteter Fachlineage."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import streamlit as st

from framework_mvp.ui.navigation import framework_bereich_oeffnen


def zeige_voraussetzungshinweis(
    *,
    grund: str,
    konsequenz: str,
    ziel_schritt: int,
    aktionslabel: str,
    projekt_id: UUID,
    technische_details: Mapping[str, Any] | None = None,
) -> None:
    """Erklärt Ursache, Folge und nächste Aktion ohne technische IDs im Haupttext."""
    with st.container(border=True):
        st.warning("Dieser Schritt muss erneut durchgeführt werden")
        st.write(grund)
        st.caption(konsequenz)
        if st.button(aktionslabel, type="primary", width="stretch"):
            framework_bereich_oeffnen(schritt=ziel_schritt, projekt_id=projekt_id)
        if technische_details:
            with st.expander("Technische Details", expanded=False):
                st.json(dict(technische_details))
