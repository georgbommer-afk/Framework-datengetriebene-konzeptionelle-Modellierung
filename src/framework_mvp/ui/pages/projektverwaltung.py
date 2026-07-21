"""Streamlit-Seite zum Anlegen und Bearbeiten von Projekten."""

import logging
from datetime import date
from uuid import UUID

import streamlit as st

from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Projekt,
    Projektstatus,
    Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion
from framework_mvp.ui.helpers import liste_als_mehrzeiliger_text, mehrzeiliger_text_als_liste

LOGGER = logging.getLogger(__name__)


def _statusbezeichnung(status: Projektstatus) -> str:
    return {
        Projektstatus.ENTWURF: "Entwurf",
        Projektstatus.AKTIV: "Aktiv",
        Projektstatus.ABGESCHLOSSEN: "Abgeschlossen",
    }[status]


def _systemtypbezeichnung(systemtyp: Systemtyp) -> str:
    return {
        Systemtyp.PRODUKTION: "Produktion",
        Systemtyp.INTRALOGISTIK: "Intralogistik",
        Systemtyp.KOMBINIERT: "Kombiniert",
    }[systemtyp]


def _initialisiere_oberflaechenzustand() -> None:
    if "ausgewaehlte_projekt_id" not in st.session_state:
        st.session_state.ausgewaehlte_projekt_id = None
    if "formular_generation" not in st.session_state:
        st.session_state.formular_generation = 0
    if "auswahl_generation" not in st.session_state:
        st.session_state.auswahl_generation = 0


def _projekt_nach_id(projekte: list[Projekt], projekt_id: UUID | None) -> Projekt | None:
    return next((projekt for projekt in projekte if projekt.projekt_id == projekt_id), None)


def _auswahltext(projekt_id_als_text: str, projekte: list[Projekt]) -> str:
    if not projekt_id_als_text:
        return "Neues Projekt"
    projekt = _projekt_nach_id(projekte, UUID(projekt_id_als_text))
    if projekt is None:
        return "Unbekanntes Projekt"
    return f"{projekt.bezeichnung} · {_statusbezeichnung(projekt.status)}"


def _zeige_seitenleiste(projekte: list[Projekt]) -> Projekt | None:
    st.sidebar.header("Projektverwaltung")
    gespeicherte_id = st.session_state.ausgewaehlte_projekt_id
    gueltige_ids = {projekt.projekt_id for projekt in projekte}
    if gespeicherte_id not in gueltige_ids:
        gespeicherte_id = None
        st.session_state.ausgewaehlte_projekt_id = None

    optionen = ["", *(str(projekt.projekt_id) for projekt in projekte)]
    gespeicherte_option = "" if gespeicherte_id is None else str(gespeicherte_id)
    ausgewaehlte_option = st.sidebar.selectbox(
        "Vorhandenes Projekt auswählen",
        options=optionen,
        index=optionen.index(gespeicherte_option),
        format_func=lambda projekt_id: _auswahltext(projekt_id, projekte),
        key=f"projektauswahl_{st.session_state.auswahl_generation}",
    )
    ausgewaehlt = UUID(ausgewaehlte_option) if ausgewaehlte_option else None
    if ausgewaehlt != gespeicherte_id:
        st.session_state.ausgewaehlte_projekt_id = ausgewaehlt
        st.session_state.formular_generation += 1
        st.rerun()

    if st.sidebar.button("Neues Projekt", use_container_width=True):
        st.session_state.ausgewaehlte_projekt_id = None
        st.session_state.formular_generation += 1
        st.session_state.auswahl_generation += 1
        st.rerun()

    projekt = _projekt_nach_id(projekte, ausgewaehlt)
    if projekt is not None:
        zeitpunkt = projekt.geaendert_am.astimezone().strftime("%d.%m.%Y, %H:%M %Z")
        st.sidebar.caption(f"Zuletzt geändert: {zeitpunkt}")
    elif not projekte:
        st.sidebar.info("Noch keine Projekte vorhanden.")
    return projekt


def _leerer_auftrag() -> Untersuchungsauftrag:
    return Untersuchungsauftrag(
        problemstellung="",
        zielsetzung="",
        systemtyp=Systemtyp.KOMBINIERT,
        systemgrenze="",
    )


def _zeige_erfolgsmeldung() -> None:
    if meldung := st.session_state.pop("erfolgsmeldung", None):
        st.success(meldung)


def _speichere_projekt(
    service: ProjektService,
    bestehendes_projekt: Projekt | None,
    *,
    bezeichnung: str,
    beteiligte_personen: str,
    status: Projektstatus,
    problemstellung: str,
    zielsetzung: str,
    systemtyp: Systemtyp,
    systemgrenze: str,
    input_beschreibung: str,
    transformation_beschreibung: str,
    output_beschreibung: str,
    detaillierungsgrad: str,
    leistungskennzahlen: str,
    rahmenbedingungen: str,
    beginn_aktiv: bool,
    beginn: date,
    ende_aktiv: bool,
    ende: date,
    anmerkungen: str,
) -> Projekt:
    auftrag = Untersuchungsauftrag(
        problemstellung=problemstellung,
        zielsetzung=zielsetzung,
        systemtyp=systemtyp,
        systemgrenze=systemgrenze,
        input_beschreibung=input_beschreibung,
        transformation_beschreibung=transformation_beschreibung,
        output_beschreibung=output_beschreibung,
        detaillierungsgrad=detaillierungsgrad,
        leistungskennzahlen=mehrzeiliger_text_als_liste(leistungskennzahlen),
        rahmenbedingungen=rahmenbedingungen,
        betrachtungszeitraum_beginn=beginn if beginn_aktiv else None,
        betrachtungszeitraum_ende=ende if ende_aktiv else None,
        anmerkungen=anmerkungen,
    )
    personen = mehrzeiliger_text_als_liste(beteiligte_personen)
    if bestehendes_projekt is None:
        return service.projekt_anlegen(
            bezeichnung=bezeichnung,
            untersuchungsauftrag=auftrag,
            status=status,
            beteiligte_personen=personen,
        )
    return service.projekt_aktualisieren(
        bestehendes_projekt.projekt_id,
        bezeichnung=bezeichnung,
        untersuchungsauftrag=auftrag,
        status=status,
        beteiligte_personen=personen,
    )


def _zeige_formular(service: ProjektService, projekt: Projekt | None) -> None:
    auftrag = projekt.untersuchungsauftrag if projekt is not None else _leerer_auftrag()
    generation = st.session_state.formular_generation
    schluessel = f"{projekt.projekt_id if projekt else 'neu'}_{generation}"

    st.subheader("Projekt bearbeiten" if projekt else "Neues Projekt anlegen")
    with st.form(f"projektformular_{schluessel}"):
        st.markdown("### Projekt")
        bezeichnung = st.text_input(
            "Projektbezeichnung",
            value=projekt.bezeichnung if projekt else "",
            key=f"bezeichnung_{schluessel}",
        )
        beteiligte_personen = st.text_area(
            "Beteiligte Personen (eine Person pro Zeile)",
            value=liste_als_mehrzeiliger_text(projekt.beteiligte_personen) if projekt else "",
            key=f"personen_{schluessel}",
        )
        status = st.selectbox(
            "Projektstatus",
            options=list(Projektstatus),
            index=list(Projektstatus).index(projekt.status if projekt else Projektstatus.ENTWURF),
            format_func=_statusbezeichnung,
            key=f"status_{schluessel}",
        )

        st.markdown("### Problem und Ziel")
        problemstellung = st.text_area(
            "Problemstellung", value=auftrag.problemstellung, key=f"problem_{schluessel}"
        )
        zielsetzung = st.text_area(
            "Zielsetzung", value=auftrag.zielsetzung, key=f"ziel_{schluessel}"
        )
        systemgrenze = st.text_area(
            "Systemgrenze", value=auftrag.systemgrenze, key=f"grenze_{schluessel}"
        )

        st.markdown("### Betrachtetes System")
        systemtyp = st.selectbox(
            "Systemtyp",
            options=list(Systemtyp),
            index=list(Systemtyp).index(auftrag.systemtyp),
            format_func=_systemtypbezeichnung,
            key=f"systemtyp_{schluessel}",
        )
        input_beschreibung = st.text_area(
            "Beschreibung des Inputs",
            value=auftrag.input_beschreibung,
            key=f"input_{schluessel}",
        )
        transformation_beschreibung = st.text_area(
            "Beschreibung der Transformation",
            value=auftrag.transformation_beschreibung,
            key=f"transformation_{schluessel}",
        )
        output_beschreibung = st.text_area(
            "Beschreibung des Outputs",
            value=auftrag.output_beschreibung,
            key=f"output_{schluessel}",
        )
        detaillierungsgrad = st.text_input(
            "Gewünschter Detaillierungsgrad",
            value=auftrag.detaillierungsgrad,
            key=f"details_{schluessel}",
        )

        st.markdown("### Bewertung und Rahmenbedingungen")
        leistungskennzahlen = st.text_area(
            "Relevante Leistungskennzahlen (eine Kennzahl pro Zeile)",
            value=liste_als_mehrzeiliger_text(auftrag.leistungskennzahlen),
            key=f"kennzahlen_{schluessel}",
        )
        rahmenbedingungen = st.text_area(
            "Rahmenbedingungen",
            value=auftrag.rahmenbedingungen,
            key=f"rahmen_{schluessel}",
        )

        st.markdown("### Betrachtungszeitraum und Anmerkungen")
        datums_spalten = st.columns(2)
        with datums_spalten[0]:
            beginn_aktiv = st.checkbox(
                "Beginn festlegen",
                value=auftrag.betrachtungszeitraum_beginn is not None,
                key=f"beginn_aktiv_{schluessel}",
            )
            beginn = st.date_input(
                "Beginn",
                value=auftrag.betrachtungszeitraum_beginn or date.today(),
                disabled=not beginn_aktiv,
                key=f"beginn_{schluessel}",
            )
        with datums_spalten[1]:
            ende_aktiv = st.checkbox(
                "Ende festlegen",
                value=auftrag.betrachtungszeitraum_ende is not None,
                key=f"ende_aktiv_{schluessel}",
            )
            ende = st.date_input(
                "Ende",
                value=auftrag.betrachtungszeitraum_ende or date.today(),
                disabled=not ende_aktiv,
                key=f"ende_{schluessel}",
            )
        anmerkungen = st.text_area(
            "Anmerkungen", value=auftrag.anmerkungen, key=f"anmerkungen_{schluessel}"
        )

        vorschau = Untersuchungsauftrag(
            problemstellung=problemstellung,
            zielsetzung=zielsetzung,
            systemtyp=systemtyp,
            systemgrenze=systemgrenze,
        )
        if vorschau.ist_vollstaendig():
            st.success("Untersuchungsauftrag vollständig")
        else:
            st.warning(
                "Untersuchungsauftrag unvollständig. Erforderlich sind Problemstellung, "
                "Zielsetzung und Systemgrenze."
            )

        speichern = st.form_submit_button("Projekt speichern", type="primary")

    if not speichern:
        return
    try:
        gespeichert = _speichere_projekt(
            service,
            projekt,
            bezeichnung=bezeichnung,
            beteiligte_personen=beteiligte_personen,
            status=status,
            problemstellung=problemstellung,
            zielsetzung=zielsetzung,
            systemtyp=systemtyp,
            systemgrenze=systemgrenze,
            input_beschreibung=input_beschreibung,
            transformation_beschreibung=transformation_beschreibung,
            output_beschreibung=output_beschreibung,
            detaillierungsgrad=detaillierungsgrad,
            leistungskennzahlen=leistungskennzahlen,
            rahmenbedingungen=rahmenbedingungen,
            beginn_aktiv=beginn_aktiv,
            beginn=beginn,
            ende_aktiv=ende_aktiv,
            ende=ende,
            anmerkungen=anmerkungen,
        )
    except Domaenenfehler as fehler:
        st.error(str(fehler))
        return
    except NichtUnterstuetzteSchemaversion as fehler:
        st.error(str(fehler))
        return
    except Exception:
        LOGGER.exception("Unerwarteter technischer Fehler beim Speichern eines Projekts.")
        st.error("Das Projekt konnte aufgrund eines technischen Fehlers nicht gespeichert werden.")
        return

    st.session_state.ausgewaehlte_projekt_id = gespeichert.projekt_id
    st.session_state.erfolgsmeldung = "Das Projekt wurde erfolgreich gespeichert."
    st.session_state.formular_generation += 1
    st.session_state.auswahl_generation += 1
    st.rerun()


def zeige_projektverwaltung(service: ProjektService) -> None:
    """Zeigt die vollständige Projektverwaltung in Streamlit an."""
    _initialisiere_oberflaechenzustand()
    _zeige_erfolgsmeldung()
    try:
        projekte = service.projekte_auflisten()
    except NichtUnterstuetzteSchemaversion as fehler:
        st.error(str(fehler))
        return
    except Exception:
        LOGGER.exception("Unerwarteter technischer Fehler beim Laden der Projekte.")
        st.error("Die Projekte konnten aufgrund eines technischen Fehlers nicht geladen werden.")
        return
    projekt = _zeige_seitenleiste(projekte)
    _zeige_formular(service, projekt)
