"""Kompakte native Fortschrittsanzeige für alle Anwendungs-Wizards."""

import streamlit as st


def zeige_kompakten_fortschritt(
    *,
    schritt: int,
    kurze_namen: tuple[str, ...],
    lange_namen: tuple[str, ...],
) -> None:
    """Zeigt aktuellen Schritt, schmalen Balken und optional die vollständige Liste."""
    gesamt = len(kurze_namen)
    st.caption(f"Schritt {schritt} von {gesamt} — {lange_namen[schritt - 1]}")
    st.progress(schritt / gesamt)
    elemente = []
    for nummer, name in enumerate(kurze_namen, 1):
        if nummer < schritt:
            elemente.append(f"✓ {nummer} {name}")
        elif nummer == schritt:
            elemente.append(f"**{nummer} {name}**")
        else:
            elemente.append(f"{nummer} {name}")
    st.markdown(" → ".join(elemente))
    with st.expander("Alle Schritte anzeigen", expanded=False):
        for nummer, name in enumerate(lange_namen, 1):
            status = (
                "abgeschlossen" if nummer < schritt else "aktuell" if nummer == schritt else "offen"
            )
            st.caption(f"{'✓' if nummer < schritt else '•'} {nummer}. {name} — {status}")
