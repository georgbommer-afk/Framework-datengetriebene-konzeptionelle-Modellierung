"""Kleine Streamlit-Testanwendung für Importprüfung und Bestätigung."""

import streamlit as st

from framework_mvp.bootstrap import (
    erstelle_datenimport_service,
    erstelle_datenquelle_service,
    erstelle_importvorgang_service,
    erstelle_projekt_service,
)
from framework_mvp.domain.models import (
    CsvImportparameter,
    Quellenart,
    Quellsystemtyp,
    Systemtyp,
    Trennzeichenwahl,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.pages.etl import (
    _datenprofil_und_bestaetigung,
    _gespeicherte_importe_fuer_quelle,
)
from framework_mvp.workspace import WorkspaceKonfiguration

projekt_service = erstelle_projekt_service()
datenquelle_service = erstelle_datenquelle_service()
workspace = WorkspaceKonfiguration.ermitteln()
importvorgang_service = erstelle_importvorgang_service(workspace=workspace)
datenimport_service = erstelle_datenimport_service()
projekte = projekt_service.projekte_auflisten()
if projekte:
    projekt = projekte[0]
else:
    projekt = projekt_service.projekt_anlegen(
        bezeichnung="UI-Importprojekt",
        untersuchungsauftrag=Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
quellen = datenquelle_service.datenquellen_fuer_projekt(projekt.projekt_id)
if quellen:
    datenquelle = quellen[0]
else:
    datenquelle = datenquelle_service.datenquelle_anlegen(
        projekt_id=projekt.projekt_id,
        bezeichnung="UI-Quelle",
        quellsystemtyp=Quellsystemtyp.DATEI_EXPORT,
        quellenart=Quellenart.CSV,
    )
zustand = st.session_state.setdefault("test_importzustand", {})
if not zustand:
    inhalt = b"wert\n1\n2\n"
    metadaten = datenimport_service.datei_pruefen("ui.csv", inhalt)
    parameter = CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.KOMMA)
    vorschau = datenimport_service.vorschau_erstellen(inhalt, parameter)
    profil = datenimport_service.profil_erstellen(vorschau.vollstaendige_tabelle)
    zustand.update(
        {
            "profil": profil,
            "datei_metadaten": metadaten,
            "datenquellen_id": str(datenquelle.datenquellen_id),
            "vorschau": vorschau,
            "vorschau_schluessel": "testprofil",
            "profil_schluessel": "testprofil",
            "dateiinhalt": inhalt,
        }
    )

try:
    _datenprofil_und_bestaetigung(
        datenimport_service=datenimport_service,
        importvorgang_service=importvorgang_service,
        projekt_id=projekt.projekt_id,
        zustand=zustand,
    )
    _gespeicherte_importe_fuer_quelle(
        importvorgang_service=importvorgang_service,
        datenimport_service=datenimport_service,
        quelle=datenquelle,
        zustand=zustand,
    )
except Importintegritaetsfehler as fehler:
    st.error(str(fehler))
