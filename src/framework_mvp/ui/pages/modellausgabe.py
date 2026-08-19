"""Framework-Schritt 10: Browser- und PDF-Ausgabe eines validierten K*."""

import html
from uuid import UUID

import streamlit as st
from streamlit import runtime

from framework_mvp.application.dateinamen import (
    sicherer_dateiname,
    sicherer_dateinamenbestandteil,
)
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


def _html_link(ziel: str) -> str:
    """Erzeugt einen isoliert öffnenden Link auf eine von Streamlit erreichbare Ressource."""
    normalisiert = f"/{ziel.lstrip('/')}"
    if "/media/" not in normalisiert or not normalisiert.endswith(".html") or ".." in normalisiert:
        raise ValueError(
            f"Der HTML-Bericht benötigt einen gültigen Streamlit-Ressourcenlink: {ziel!r}"
        )
    return (
        f'<a href="{html.escape(normalisiert, quote=True)}" target="_blank" '
        'rel="noopener noreferrer">Konzeptionelles Modell in neuem Tab öffnen</a>'
    )


def _html_ressource(report_html: bytes, *, koordinaten: str) -> str:
    """Registriert das vollständige Dokument stabil im aktiven Streamlit-Mediaspeicher."""
    if not runtime.exists():
        raise RuntimeError(
            "Der HTML-Bericht kann nur in einer aktiven Streamlit-Sitzung geöffnet werden."
        )
    return runtime.get_instance().media_file_mgr.add(
        report_html,
        "text/html",
        koordinaten,
    )


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
    projekt = projekt_service.projekt_laden(projekt_id)
    if projekt is None:
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
        f"Das konzeptionelle Modell für **{projekt.bezeichnung}** ist projektgebunden, "
        "checksum-validiert und fachlich "
        "validiert. Schritt 10 verändert dieses Modell nicht."
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
    with st.expander("Technische Details", expanded=False):
        st.json(
            {
                "projekt_id": str(projekt_id),
                "validierungslauf_id": str(validierungslauf_id),
                "k_stern_id": str(k_stern_id),
                "erstellt_am": k_stern["erstellt_am"],
                "gesamtpruefsumme": k_stern.get("gesamtpruefsumme"),
                "eingabefingerabdruck": k_stern.get("eingabefingerabdruck"),
                "entscheidungsfingerabdruck": k_stern.get("entscheidungsfingerabdruck"),
            },
            expanded=False,
        )
    st.subheader("2. Ausgabe erzeugen")
    xlsx_dateiname = sicherer_dateiname(
        f"Konzeptionelles Modell {sicherer_dateinamenbestandteil(projekt.bezeichnung)}",
        "xlsx",
    )
    st.button(f"{xlsx_dateiname} – noch nicht implementiert", disabled=True)
    signatur = (str(validierungslauf_id), str(k_stern_id))
    if st.button("HTML und PDF erzeugen", type="primary"):
        try:
            st.session_state.schritt10_ausgabe = ausgabe_service.erzeugen(
                validierungslauf_id=validierungslauf_id,
                projekt_id=projekt_id,
                k_stern_id=k_stern_id,
                html=True,
                pdf=True,
            )
            st.session_state.schritt10_ausgabe_signatur = signatur
        except (Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            st.error(f"Die strukturierte Ausgabe konnte nicht erzeugt werden: {fehler}")
    ausgabe = st.session_state.get("schritt10_ausgabe")
    if isinstance(ausgabe, StrukturierteModellausgabe):
        if st.session_state.get("schritt10_ausgabe_signatur") != signatur:
            st.warning("Das aktive K* wurde geändert; die Ausgabe ist veraltet.")
            return
        st.subheader("3. Ausgabe öffnen oder herunterladen")
        if ausgabe.report_html is not None and ausgabe.html_dateiname is not None:
            report_url = _html_ressource(
                ausgabe.report_html,
                koordinaten=f"konzeptbericht-{projekt_id}-{validierungslauf_id}-{k_stern_id}",
            )
            st.markdown(
                _html_link(report_url),
                unsafe_allow_html=True,
            )
            st.download_button(
                "HTML-Report herunterladen",
                ausgabe.report_html,
                ausgabe.html_dateiname,
                "text/html",
            )
        if ausgabe.report_pdf is not None and ausgabe.pdf_dateiname is not None:
            st.download_button(
                "PDF-Report herunterladen",
                ausgabe.report_pdf,
                ausgabe.pdf_dateiname,
                "application/pdf",
            )
