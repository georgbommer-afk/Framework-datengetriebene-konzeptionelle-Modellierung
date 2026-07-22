"""ETL-Hauptseite mit Datenquellenkatalog und temporärem Import-Wizard."""

import logging
from typing import Any
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.application.datenimport_service import (
    DatenimportService,
    Datenvorschau,
    Profilierungsergebnis,
    schlage_datenquellenbezeichnung_vor,
    schlage_quellenart_vor,
)
from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Datenimportfehler, Domaenenfehler
from framework_mvp.domain.models import (
    CsvImportparameter,
    Dateityp,
    Datenquelle,
    Dezimaltrennzeichen,
    ExcelImportparameter,
    Kopfzeileneinstellung,
    Kopfzeilenmodus,
    Quellenart,
    Quellsystemtyp,
    Tausendertrennzeichen,
    Trennzeichenwahl,
    Zeichenkodierung,
)
from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion
from framework_mvp.ui.components.datenprofil_visualisierung import zeige_datenprofil
from framework_mvp.ui.components.framework_navigation import zeige_framework_navigation
from framework_mvp.workspace import WorkspaceKonfiguration

LOGGER = logging.getLogger(__name__)

ETL_SCHRITTE = (
    "Datenquelle registrieren",
    "Datei hochladen",
    "Importeinstellungen",
    "Tabelle oder Tabellenblatt auswählen",
    "Datenvorschau",
    "Datenprofil und Qualitätsübersicht",
    "Import prüfen und bestätigen",
)


def _enum_text(wert: Quellsystemtyp | Quellenart) -> str:
    return wert.value.replace("_", " ").upper()


def _projekt_auswaehlen(projekt_service: ProjektService) -> UUID | None:
    projekte = projekt_service.projekte_auflisten()
    if not projekte:
        st.warning("Für den Datenimport muss zuerst ein Projekt angelegt werden.")
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


def _wizard_zustand(projekt_id: UUID) -> dict[str, Any]:
    zustaende = st.session_state.setdefault("etl_wizard_zustaende", {})
    return zustaende.setdefault(str(projekt_id), {"schritt": 1})


def _zeige_etl_fortschritt(schritt: int) -> None:
    st.subheader("ETL-Wizard")
    st.caption(f"Schritt {schritt} von 7")
    st.progress(schritt / 7)
    spalten = st.columns(7)
    for nummer, (spalte, name) in enumerate(zip(spalten, ETL_SCHRITTE, strict=True), 1):
        with spalte.container(border=True):
            st.markdown(f"**{nummer}. {name}**")
            if nummer == schritt:
                status = "Aktuell"
            elif nummer < schritt:
                status = "Erledigt"
            elif nummer <= 6:
                status = "Verfügbar"
            else:
                status = "Noch nicht verfügbar"
            st.caption(status)


def _quelle_auswaehlen(
    service: DatenquelleService, projekt_id: UUID, zustand: dict[str, Any]
) -> Datenquelle | None:
    datenquellen = service.datenquellen_fuer_projekt(projekt_id)
    optionen = ["", *(str(quelle.datenquellen_id) for quelle in datenquellen)]
    texte = {str(q.datenquellen_id): q.bezeichnung for q in datenquellen}
    gespeicherte_id = zustand.get("datenquellen_id", "")
    index = optionen.index(gespeicherte_id) if gespeicherte_id in optionen else 0
    auswahl = st.selectbox(
        "Gespeicherte Datenquelle öffnen",
        optionen,
        index=index,
        format_func=lambda wert: "Neue Datenquelle" if not wert else texte[wert],
        key=f"etl_quellenauswahl_{projekt_id}_{zustand.get('quellenauswahl_version', 0)}",
    )
    if auswahl != gespeicherte_id:
        zustand["datenquellen_id"] = auswahl
    if not auswahl:
        return None
    return next(q for q in datenquellen if str(q.datenquellen_id) == auswahl)


def _registrierung(
    service: DatenquelleService,
    workspace: WorkspaceKonfiguration,
    projekt_id: UUID,
    zustand: dict[str, Any],
) -> None:
    quelle = _quelle_auswaehlen(service, projekt_id, zustand)
    with st.form(f"datenquelle_formular_{projekt_id}"):
        bezeichnung = st.text_input(
            "Bezeichnung der Datenquelle", quelle.bezeichnung if quelle else ""
        )
        systemtypen = list(Quellsystemtyp)
        quellsystemtyp = st.selectbox(
            "Quellsystemtyp",
            systemtypen,
            index=systemtypen.index(quelle.quellsystemtyp) if quelle else 0,
            format_func=_enum_text,
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
        with st.expander("Weitere Metadaten"):
            konkretes_system = st.text_input(
                "Konkretes Quellsystem (optional)", quelle.konkretes_quellsystem if quelle else ""
            )
            beschreibung = st.text_area(
                "Fachliche Beschreibung", quelle.fachliche_beschreibung if quelle else ""
            )
            herkunft = st.text_input(
                "Herkunft beziehungsweise Verantwortungsbereich",
                quelle.herkunft_oder_verantwortungsbereich if quelle else "",
            )
        speichern = st.form_submit_button("Datenquelle speichern", type="primary")
    if not speichern:
        return
    argumente = {
        "bezeichnung": bezeichnung,
        "quellsystemtyp": quellsystemtyp,
        "quellenart": quellenart,
        "konkretes_quellsystem": konkretes_system,
        "fachliche_beschreibung": beschreibung,
        "herkunft_oder_verantwortungsbereich": herkunft,
        "erwartete_tabellen_oder_blaetter": (
            quelle.erwartete_tabellen_oder_blaetter if quelle else ()
        ),
        "bekannte_schluesselattribute": quelle.bekannte_schluesselattribute if quelle else (),
    }
    if quelle is None:
        gespeichert = service.datenquelle_anlegen(projekt_id=projekt_id, **argumente)
    else:
        gespeichert = service.datenquelle_aktualisieren(quelle.datenquellen_id, **argumente)
    workspace.fuer_projekt_anlegen(projekt_id)
    zustand["datenquellen_id"] = str(gespeichert.datenquellen_id)
    zustand["quellenauswahl_version"] = zustand.get("quellenauswahl_version", 0) + 1
    st.session_state.etl_erfolgsmeldung = "Die Datenquelle wurde erfolgreich gespeichert."
    st.rerun()


def _upload(import_service: DatenimportService, projekt_id: UUID, zustand: dict[str, Any]) -> None:
    upload = st.file_uploader(
        "CSV- oder XLSX-Datei",
        type=["csv", "xlsx"],
        accept_multiple_files=False,
        key=f"etl_upload_{projekt_id}",
    )
    if upload is None:
        st.info("Wählen Sie genau eine CSV- oder XLSX-Datei aus.")
        return
    dateiinhalt = upload.getvalue()
    metadaten = import_service.datei_pruefen(upload.name, dateiinhalt)
    vorherige_pruefsumme = getattr(zustand.get("datei_metadaten"), "sha256", None)
    if vorherige_pruefsumme != metadaten.sha256:
        for schluessel in (
            "csv_parameter",
            "csv_erkennungen",
            "excel_kopfzeile",
            "tabellenblaetter",
            "tabellenblatt",
            "vorschau",
            "vorschau_schluessel",
            "profil",
            "profil_schluessel",
        ):
            zustand.pop(schluessel, None)
        zustand["dateiinhalt"] = dateiinhalt
        zustand["datei_metadaten"] = metadaten
    st.write(f"**Ursprünglicher Dateiname:** {metadaten.urspruenglicher_dateiname}")
    st.write(f"**Dateigröße:** {metadaten.dateigroesse_bytes:,} Bytes")
    st.write(f"**Erkannter Dateityp:** {metadaten.dateityp.value}")
    bezeichnungsvorschlag = schlage_datenquellenbezeichnung_vor(metadaten.sicherer_dateiname, "")
    quellenartvorschlag = schlage_quellenart_vor(metadaten.dateityp)
    zustand["bezeichnungsvorschlag"] = bezeichnungsvorschlag
    zustand["quellenartvorschlag"] = quellenartvorschlag
    st.caption(
        f"Automatische Vorschläge: Bezeichnung „{bezeichnungsvorschlag}“, "
        f"Quellenart {_enum_text(quellenartvorschlag)}. Manuelle Angaben bleiben unverändert."
    )
    st.code(metadaten.sha256, language=None)
    st.caption("Die Datei wird nur temporär verarbeitet und noch nicht im Workspace gespeichert.")


def _kopfzeile(schluessel: str) -> Kopfzeileneinstellung:
    beschriftungen = {
        "Erste Zeile": Kopfzeilenmodus.ERSTE_ZEILE,
        "Benutzerdefinierte Zeilennummer": Kopfzeilenmodus.BENUTZERDEFINIERT,
        "Keine Kopfzeile": Kopfzeilenmodus.KEINE,
    }
    auswahl = st.selectbox("Kopfzeile", list(beschriftungen), key=f"{schluessel}_modus")
    modus = beschriftungen[auswahl]
    zeilennummer = None
    if modus is Kopfzeilenmodus.BENUTZERDEFINIERT:
        st.caption("Die erste Datenzeile entspricht Zeile 1.")
        zeilennummer = int(
            st.number_input("Zeilennummer der Kopfzeile", min_value=1, value=1, key=schluessel)
        )
    return Kopfzeileneinstellung(modus, zeilennummer)


def _csv_einstellungen(
    import_service: DatenimportService, projekt_id: UUID, zustand: dict[str, Any]
) -> None:
    dateiinhalt: bytes = zustand["dateiinhalt"]
    kodierungen = {
        "UTF-8": Zeichenkodierung.UTF_8,
        "UTF-8 mit BOM": Zeichenkodierung.UTF_8_BOM,
        "ISO-8859-1": Zeichenkodierung.ISO_8859_1,
        "Windows-1252": Zeichenkodierung.WINDOWS_1252,
    }
    kodierung = kodierungen[
        st.selectbox("Zeichenkodierung", list(kodierungen), key=f"etl_encoding_{projekt_id}")
    ]
    erkennungen = zustand.setdefault("csv_erkennungen", {})
    erkennungsschluessel = (zustand["datei_metadaten"].sha256, kodierung)
    if erkennungsschluessel not in erkennungen:
        try:
            erkennungen[erkennungsschluessel] = import_service.csv_trennzeichen_erkennen(
                dateiinhalt, kodierung
            )
        except Datenimportfehler:
            erkennungen[erkennungsschluessel] = ""
    erkannt = erkennungen[erkennungsschluessel]
    if erkannt:
        st.info(f"Automatisch erkanntes Trennzeichen: `{erkannt.replace(chr(9), 'Tabulator')}`")
    else:
        st.warning(
            "Das Trennzeichen konnte nicht automatisch erkannt werden. Bitte wählen Sie es manuell."
        )
    trennzeichen = {
        "Automatisch erkennen": Trennzeichenwahl.AUTOMATISCH,
        "Komma": Trennzeichenwahl.KOMMA,
        "Semikolon": Trennzeichenwahl.SEMIKOLON,
        "Tabulator": Trennzeichenwahl.TABULATOR,
        "Benutzerdefiniert": Trennzeichenwahl.BENUTZERDEFINIERT,
    }
    wahl = trennzeichen[
        st.selectbox("Trennzeichen", list(trennzeichen), key=f"etl_separator_{projekt_id}")
    ]
    eigenes = ""
    if wahl is Trennzeichenwahl.BENUTZERDEFINIERT:
        eigenes = st.text_input(
            "Benutzerdefiniertes Trennzeichen", max_chars=1, key=f"etl_custom_sep_{projekt_id}"
        )
    dezimal = st.selectbox("Dezimaltrennzeichen", ["Punkt", "Komma"])
    tausender = st.selectbox("Tausendertrennzeichen", ["Keines", "Punkt", "Komma", "Leerzeichen"])
    parameter = CsvImportparameter(
        trennzeichenwahl=wahl,
        benutzerdefiniertes_trennzeichen=eigenes,
        erkanntes_trennzeichen=erkannt,
        zeichenkodierung=kodierung,
        dezimaltrennzeichen={
            "Punkt": Dezimaltrennzeichen.PUNKT,
            "Komma": Dezimaltrennzeichen.KOMMA,
        }[dezimal],
        tausendertrennzeichen={
            "Keines": Tausendertrennzeichen.KEINES,
            "Punkt": Tausendertrennzeichen.PUNKT,
            "Komma": Tausendertrennzeichen.KOMMA,
            "Leerzeichen": Tausendertrennzeichen.LEERZEICHEN,
        }[tausender],
        kopfzeile=_kopfzeile(f"etl_csv_header_{projekt_id}"),
    )
    if zustand.get("csv_parameter") != parameter:
        zustand.pop("vorschau", None)
        zustand.pop("vorschau_schluessel", None)
        zustand.pop("profil", None)
        zustand.pop("profil_schluessel", None)
        zustand["csv_parameter"] = parameter


def _excel_einstellungen(projekt_id: UUID, zustand: dict[str, Any]) -> None:
    kopfzeile = _kopfzeile(f"etl_excel_header_{projekt_id}")
    if zustand.get("excel_kopfzeile") != kopfzeile:
        zustand.pop("vorschau", None)
        zustand.pop("vorschau_schluessel", None)
        zustand.pop("profil", None)
        zustand.pop("profil_schluessel", None)
        zustand["excel_kopfzeile"] = kopfzeile


def _importeinstellungen(
    import_service: DatenimportService, projekt_id: UUID, zustand: dict[str, Any]
) -> None:
    metadaten = zustand["datei_metadaten"]
    if metadaten.dateityp is Dateityp.CSV:
        _csv_einstellungen(import_service, projekt_id, zustand)
    else:
        _excel_einstellungen(projekt_id, zustand)


def _tabellenauswahl(
    import_service: DatenimportService, projekt_id: UUID, zustand: dict[str, Any]
) -> None:
    metadaten = zustand["datei_metadaten"]
    if metadaten.dateityp is Dateityp.CSV:
        st.info("CSV-Dateien enthalten keine Tabellenblätter. Es ist keine Auswahl erforderlich.")
        return
    if "tabellenblaetter" not in zustand:
        zustand["tabellenblaetter"] = import_service.excel_tabellenblaetter(zustand["dateiinhalt"])
    blaetter = zustand["tabellenblaetter"]
    st.dataframe(
        pd.DataFrame(
            {
                "Tabellenblatt": [blatt.name for blatt in blaetter],
                "Ungefähre Zeilen": [blatt.ungefaehre_zeilenanzahl for blatt in blaetter],
                "Ungefähre Spalten": [blatt.ungefaehre_spaltenanzahl for blatt in blaetter],
            }
        ),
        hide_index=True,
    )
    namen = [blatt.name for blatt in blaetter]
    auswahl = st.selectbox("Tabellenblatt auswählen", namen, key=f"etl_sheet_{projekt_id}")
    if zustand.get("tabellenblatt") != auswahl:
        zustand["tabellenblatt"] = auswahl
        zustand.pop("vorschau", None)
        zustand.pop("vorschau_schluessel", None)
        zustand.pop("profil", None)
        zustand.pop("profil_schluessel", None)


def _parameter(zustand: dict[str, Any]) -> CsvImportparameter | ExcelImportparameter:
    if zustand["datei_metadaten"].dateityp is Dateityp.CSV:
        return zustand["csv_parameter"]
    return ExcelImportparameter(zustand["tabellenblatt"], zustand["excel_kopfzeile"])


def _vorschau(import_service: DatenimportService, zustand: dict[str, Any]) -> None:
    parameter = _parameter(zustand)
    schluessel = import_service.cache_schluessel(zustand["datei_metadaten"], parameter)
    if zustand.get("vorschau_schluessel") != schluessel:
        zustand["vorschau"] = import_service.vorschau_erstellen(zustand["dateiinhalt"], parameter)
        zustand["vorschau_schluessel"] = schluessel
    vorschau: Datenvorschau = zustand["vorschau"]
    links, rechts = st.columns(2)
    links.metric("Gesamtzahl Zeilen", vorschau.gesamtzeilen)
    rechts.metric("Gesamtzahl Spalten", vorschau.gesamtspalten)
    st.caption("Die Tabelle zeigt eine unveränderte Vorschau der ersten maximal 200 Zeilen.")
    st.dataframe(vorschau.tabelle, use_container_width=True)
    st.write("**Ursprüngliche Spaltennamen:**", list(vorschau.spaltennamen))
    st.write("**Von Pandas erkannte Datentypen:**", list(vorschau.pandas_datentypen))
    st.write("**Verwendete Importparameter:**", str(vorschau.verwendete_parameter))
    st.subheader("Spaltenübersicht")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Spaltenname": wert.spaltenname,
                    "Pandas-Datentyp": wert.pandas_datentyp,
                    "Nicht leere Werte": wert.nicht_leere_werte,
                    "Leere Werte": wert.leere_werte,
                    "Anteil leerer Werte": wert.anteil_leerer_werte,
                }
                for wert in vorschau.spaltenuebersicht
            ]
        ),
        hide_index=True,
        column_config={"Anteil leerer Werte": st.column_config.NumberColumn(format="%.1%%")},
    )


def _datenprofil(
    import_service: DatenimportService, projekt_id: UUID, zustand: dict[str, Any]
) -> None:
    vorschau: Datenvorschau = zustand["vorschau"]
    profilschluessel = zustand["vorschau_schluessel"]
    if zustand.get("profil_schluessel") != profilschluessel:
        zustand["profil"] = import_service.profil_erstellen(vorschau.vollstaendige_tabelle)
        zustand["profil_schluessel"] = profilschluessel
    ergebnis: Profilierungsergebnis = zustand["profil"]
    metadaten = zustand["datei_metadaten"]
    zeige_datenprofil(
        ergebnis,
        session_key=f"etl_profildetail_{projekt_id}_{metadaten.sha256}",
    )


def _kann_weiter(zustand: dict[str, Any]) -> bool:
    schritt = zustand["schritt"]
    if schritt == 1:
        return bool(zustand.get("datenquellen_id"))
    if schritt == 2:
        return "datei_metadaten" in zustand
    if schritt == 3:
        metadaten = zustand.get("datei_metadaten")
        return bool(
            metadaten
            and (
                (metadaten.dateityp is Dateityp.CSV and "csv_parameter" in zustand)
                or (metadaten.dateityp is Dateityp.XLSX and "excel_kopfzeile" in zustand)
            )
        )
    if schritt == 4:
        metadaten = zustand["datei_metadaten"]
        return metadaten.dateityp is Dateityp.CSV or bool(zustand.get("tabellenblatt"))
    if schritt == 5:
        return "vorschau" in zustand
    return False


def _navigation(zustand: dict[str, Any]) -> None:
    zurueck, weiter = st.columns(2)
    if zurueck.button("Zurück", disabled=zustand["schritt"] == 1, use_container_width=True):
        zustand["schritt"] -= 1
        st.rerun()
    if weiter.button(
        "Weiter",
        disabled=zustand["schritt"] >= 6 or not _kann_weiter(zustand),
        type="primary",
        use_container_width=True,
    ):
        zustand["schritt"] += 1
        st.rerun()


def zeige_etl_seite(
    projekt_service: ProjektService,
    datenquelle_service: DatenquelleService,
    datenimport_service: DatenimportService,
    workspace: WorkspaceKonfiguration,
) -> None:
    """Zeigt Framework-Schritt 2 und die aktiven ETL-Teilschritte eins bis sechs."""
    st.header("2 ETL durchführen")
    if meldung := st.session_state.pop("etl_erfolgsmeldung", None):
        st.success(meldung)
    zeige_framework_navigation(current_step=2, completed_steps={1})
    st.write(
        "Eingaben sind die Rohdaten D und der Datenquellenkatalog Q. Spätere Ausgaben sind "
        "Zwischendatensätze T und das Datenprofil R."
    )
    try:
        projekt_id = _projekt_auswaehlen(projekt_service)
        if projekt_id is None:
            return
        zustand = _wizard_zustand(projekt_id)
        _zeige_etl_fortschritt(zustand["schritt"])
        if zustand["schritt"] == 1:
            _registrierung(datenquelle_service, workspace, projekt_id, zustand)
        elif zustand["schritt"] == 2:
            _upload(datenimport_service, projekt_id, zustand)
        elif zustand["schritt"] == 3:
            _importeinstellungen(datenimport_service, projekt_id, zustand)
        elif zustand["schritt"] == 4:
            _tabellenauswahl(datenimport_service, projekt_id, zustand)
        elif zustand["schritt"] == 5:
            _vorschau(datenimport_service, zustand)
        else:
            _datenprofil(datenimport_service, projekt_id, zustand)
        _navigation(zustand)
    except (Domaenenfehler, Datenimportfehler) as fehler:
        st.error(str(fehler))
    except NichtUnterstuetzteSchemaversion as fehler:
        st.error(str(fehler))
    except Exception:
        LOGGER.exception("Unerwarteter Fehler auf der ETL-Seite.")
        st.error(
            "Der ETL-Schritt konnte aufgrund eines technischen Fehlers nicht ausgeführt werden."
        )
