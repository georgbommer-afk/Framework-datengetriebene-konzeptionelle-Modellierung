"""Framework-Schritt 10: Report- und Excel-Ausgabe eines validierten K*."""

from uuid import UUID

import streamlit as st

from framework_mvp.application.modellausgabe_service import (
    ModellausgabeService,
    StrukturierteModellausgabe,
)
from framework_mvp.application.modellvalidierung_service import ModellvalidierungService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.navigation import framework_bereich_oeffnen


def _aktive_ids() -> tuple[UUID, UUID, UUID] | None:
    try:
        return (
            UUID(str(st.session_state.get("aktuelles_projekt_id"))),
            UUID(str(st.session_state.get("aktuelle_validierungslauf_id"))),
            UUID(str(st.session_state.get("aktuelle_k_stern_id"))),
        )
    except (TypeError, ValueError, AttributeError):
        return None


def zeige_modellausgabe_seite(
    projekt_service: ProjektService,
    validierungs_service: ModellvalidierungService,
    ausgabe_service: ModellausgabeService,
) -> None:
    """Setzt Algorithmus 10 ohne Mutation, Ergänzung oder erneute Modellbildung um."""
    st.header("10 Konzeptionelles Modell ausgeben")
    ids = _aktive_ids()
    if ids is None:
        st.error("Schritt 10 benötigt ein aktives, fachlich validiertes K* aus Schritt 9.")
        if st.button("Zurück zu Schritt 9: Modell ergänzen und validieren"):
            framework_bereich_oeffnen(schritt=9)
        return
    projekt_id, validierungslauf_id, k_stern_id = ids
    if projekt_service.projekt_laden(projekt_id) is None:
        st.error("Das aktive Projekt wurde nicht gefunden.")
        return
    try:
        k_stern = validierungs_service.uebergabe_schritt10(
            validierungslauf_id, projekt_id, k_stern_id
        )
    except (Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
        st.error(f"Ohne gültiges und fachlich validiertes K* ist keine Ausgabe möglich: {fehler}")
        if st.button("Zurück zu Schritt 9: Modell ergänzen und validieren"):
            framework_bereich_oeffnen(schritt=9, projekt_id=projekt_id)
        return
    st.subheader("1. Aktives validiertes konzeptionelles Modell K*")
    st.success(
        f"K* `{k_stern['k_stern_id']}` ist projektgebunden, checksum-validiert und fachlich "
        "validiert. Schritt 10 verändert dieses Modell nicht."
    )
    st.caption(
        f"Projekt `{k_stern['projekt_id']}` · Validierungslauf "
        f"`{k_stern['validierungslauf_id']}` · Erstellt `{k_stern['erstellt_am']}`"
    )
    for index, bestandteil in enumerate(k_stern["modellbestandteile"], 1):
        with st.expander(f"{index}. {bestandteil['bezeichnung']}"):
            st.write(
                f"Ursprüngliche Informationen: "
                f"**{len(bestandteil['urspruenglicher_bestandteil'].get('informationen', []))}**"
            )
            st.write(
                f"Menschliche Ergänzungen oder Anpassungen: "
                f"**{len(bestandteil.get('menschliche_eintraege', []))}**"
            )
    st.subheader("2. Ausgabeformen wählen")
    formate = st.multiselect("Ausgabeformen", ["Report", "Excel"], default=["Report", "Excel"])
    signatur = (str(validierungslauf_id), str(k_stern_id), tuple(formate))
    if st.button("Ausgewählte Dateien erzeugen", disabled=not formate, type="primary"):
        try:
            st.session_state.schritt10_ausgabe = ausgabe_service.erzeugen(
                validierungslauf_id=validierungslauf_id,
                projekt_id=projekt_id,
                k_stern_id=k_stern_id,
                report="Report" in formate,
                excel="Excel" in formate,
            )
            st.session_state.schritt10_ausgabe_signatur = signatur
        except (Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            st.error(f"Die strukturierte Ausgabe konnte nicht erzeugt werden: {fehler}")
    ausgabe = st.session_state.get("schritt10_ausgabe")
    if isinstance(ausgabe, StrukturierteModellausgabe):
        if st.session_state.get("schritt10_ausgabe_signatur") != signatur:
            st.warning("K* oder die Formatauswahl wurde geändert; die Ausgabe ist veraltet.")
            return
        st.subheader("3. Strukturierte Ausgabe herunterladen")
        if ausgabe.report_pdf is not None and ausgabe.report_dateiname is not None:
            st.download_button(
                "PDF-Report herunterladen",
                ausgabe.report_pdf,
                ausgabe.report_dateiname,
                "application/pdf",
            )
        if ausgabe.excel_xlsx is not None and ausgabe.excel_dateiname is not None:
            st.download_button(
                "Excel-Ausgabe herunterladen",
                ausgabe.excel_xlsx,
                ausgabe.excel_dateiname,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
