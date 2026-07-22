"""ETL-Hauptseite und bedienbarer Datenquellenkatalog Q."""

import logging
from uuid import UUID

import streamlit as st

from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import Datenquelle, Quellenart, Quellsystemtyp
from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion
from framework_mvp.ui.components.framework_navigation import zeige_framework_navigation
from framework_mvp.workspace import WorkspaceKonfiguration

LOGGER = logging.getLogger(__name__)

ETL_SCHRITTE = (
    "Datenquelle registrieren",
    "Datei hochladen",
    "Importeinstellungen festlegen",
    "Tabelle oder Tabellenblatt auswählen",
    "Datenvorschau",
    "Datenprofil und Qualitätsübersicht",
    "Import prüfen und bestätigen",
)


def _zeilen(text: str) -> tuple[str, ...]:
    return tuple(bereinigt for zeile in text.splitlines() if (bereinigt := zeile.strip()))


def _enum_text(wert: Quellsystemtyp | Quellenart) -> str:
    return wert.value.replace("_", " ").upper()


def _projekt_auswaehlen(projekt_service: ProjektService) -> UUID | None:
    projekte = projekt_service.projekte_auflisten()
    if not projekte:
        st.warning("Für den Datenquellenkatalog muss zuerst ein Projekt angelegt werden.")
        return None
    optionen = [str(projekt.projekt_id) for projekt in projekte]
    texte = {
        str(p.projekt_id): f"{p.bezeichnung} · {p.status.value.capitalize()}" for p in projekte
    }
    aktuelle_id = st.session_state.get("aktuelles_projekt_id")
    index = optionen.index(aktuelle_id) if aktuelle_id in optionen else 0
    auswahl = st.selectbox(
        "Aktuelles Projekt",
        optionen,
        index=index,
        format_func=lambda projekt_id: texte[projekt_id],
        key="etl_projektauswahl",
    )
    st.session_state.aktuelles_projekt_id = auswahl
    return UUID(auswahl)


def _zeige_etl_fortschritt() -> None:
    st.subheader("ETL-Wizard")
    st.caption("Teilschritt 1 von 7")
    st.progress(1 / 7)
    spalten = st.columns(7)
    for nummer, (spalte, name) in enumerate(zip(spalten, ETL_SCHRITTE, strict=True), 1):
        with spalte.container(border=True):
            st.markdown(f"**{nummer}. {name}**")
            st.caption("Aktiv" if nummer == 1 else "Noch nicht verfügbar")


def _quelle_auswaehlen(service: DatenquelleService, projekt_id: UUID) -> Datenquelle | None:
    datenquellen = service.datenquellen_fuer_projekt(projekt_id)
    optionen = ["", *(str(quelle.datenquellen_id) for quelle in datenquellen)]
    texte = {str(q.datenquellen_id): q.bezeichnung for q in datenquellen}
    auswahl = st.selectbox(
        "Gespeicherte Datenquelle öffnen",
        optionen,
        format_func=lambda wert: "Neue Datenquelle" if not wert else texte[wert],
    )
    if not auswahl:
        return None
    return next(q for q in datenquellen if str(q.datenquellen_id) == auswahl)


def _formular(
    service: DatenquelleService,
    workspace: WorkspaceKonfiguration,
    projekt_id: UUID,
) -> None:
    quelle = _quelle_auswaehlen(service, projekt_id)
    with st.form("datenquelle_formular"):
        bezeichnung = st.text_input("Bezeichnung", quelle.bezeichnung if quelle else "")
        systemtypen = list(Quellsystemtyp)
        quellsystemtyp = st.selectbox(
            "Quellsystemtyp",
            systemtypen,
            index=systemtypen.index(quelle.quellsystemtyp) if quelle else 0,
            format_func=_enum_text,
        )
        konkretes_system = st.text_input(
            "Konkretes Quellsystem (optional)",
            quelle.konkretes_quellsystem if quelle else "",
        )
        quellenarten = list(Quellenart)
        quellenart = st.selectbox(
            "Quellenart",
            quellenarten,
            index=quellenarten.index(quelle.quellenart) if quelle else 0,
            format_func=_enum_text,
        )
        if quellenart is Quellenart.DATENBANK:
            st.info("Technische Datenbankanbindungen folgen in einer späteren Ausbaustufe.")
        beschreibung = st.text_area(
            "Fachliche Beschreibung", quelle.fachliche_beschreibung if quelle else ""
        )
        herkunft = st.text_input(
            "Herkunft beziehungsweise Verantwortungsbereich",
            quelle.herkunft_oder_verantwortungsbereich if quelle else "",
        )
        tabellen = st.text_area(
            "Erwartete Tabellen oder Tabellenblätter (ein Eintrag pro Zeile)",
            "\n".join(quelle.erwartete_tabellen_oder_blaetter) if quelle else "",
        )
        schluessel = st.text_area(
            "Bekannte Schlüsselattribute (ein Eintrag pro Zeile)",
            "\n".join(quelle.bekannte_schluesselattribute) if quelle else "",
        )
        speichern = st.form_submit_button("Datenquelle speichern", type="primary")
    if not speichern:
        return
    try:
        argumente = {
            "bezeichnung": bezeichnung,
            "quellsystemtyp": quellsystemtyp,
            "quellenart": quellenart,
            "konkretes_quellsystem": konkretes_system,
            "fachliche_beschreibung": beschreibung,
            "herkunft_oder_verantwortungsbereich": herkunft,
            "erwartete_tabellen_oder_blaetter": _zeilen(tabellen),
            "bekannte_schluesselattribute": _zeilen(schluessel),
        }
        if quelle is None:
            service.datenquelle_anlegen(projekt_id=projekt_id, **argumente)
        else:
            service.datenquelle_aktualisieren(quelle.datenquellen_id, **argumente)
        workspace.fuer_projekt_anlegen(projekt_id)
    except Domaenenfehler as fehler:
        st.error(str(fehler))
        return
    except Exception:
        LOGGER.exception("Unerwarteter Fehler beim Speichern einer Datenquelle.")
        st.error(
            "Die Datenquelle konnte aufgrund eines technischen Fehlers nicht gespeichert werden."
        )
        return
    st.session_state.etl_erfolgsmeldung = "Die Datenquelle wurde erfolgreich gespeichert."
    st.rerun()


def zeige_etl_seite(
    projekt_service: ProjektService,
    datenquelle_service: DatenquelleService,
    workspace: WorkspaceKonfiguration,
) -> None:
    """Zeigt Framework-Schritt 2 und den ersten ETL-Teilschritt."""
    st.header("2 ETL durchführen")
    if meldung := st.session_state.pop("etl_erfolgsmeldung", None):
        st.success(meldung)
    zeige_framework_navigation(current_step=2, completed_steps={1})
    st.write(
        "Eingaben sind die Rohdaten D und der Datenquellenkatalog Q. Spätere Ausgaben sind "
        "Zwischendatensätze T und das Datenprofil R."
    )
    _zeige_etl_fortschritt()
    try:
        projekt_id = _projekt_auswaehlen(projekt_service)
        if projekt_id is not None:
            _formular(datenquelle_service, workspace, projekt_id)
    except NichtUnterstuetzteSchemaversion as fehler:
        st.error(str(fehler))
    except Exception:
        LOGGER.exception("Unerwarteter Fehler beim Laden der ETL-Seite.")
        st.error("Die ETL-Seite konnte aufgrund eines technischen Fehlers nicht geladen werden.")
