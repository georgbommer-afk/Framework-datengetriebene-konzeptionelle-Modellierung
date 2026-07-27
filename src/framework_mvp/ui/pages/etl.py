"""Fünfstufige ETL-Oberfläche für den reproduzierbaren Zwischendatensatz T."""

import logging
import re
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from framework_mvp.application.datenimport_service import (
    DatenimportService,
    Datenvorschau,
    Profilierungsergebnis,
    schlage_quellenart_vor,
)
from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.importvorgang_service import (
    GeladenerImport,
    ImportvorgangService,
)
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.transformation import pruefe_join
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Datenimportfehler, Domaenenfehler
from framework_mvp.domain.models import (
    CsvImportparameter,
    DateiMetadaten,
    Dateityp,
    Datenquelle,
    Dezimaltrennzeichen,
    ExcelImportparameter,
    Importvorgang,
    Kopfzeileneinstellung,
    Kopfzeilenmodus,
    Quellenart,
    Quellsystemtyp,
    Tausendertrennzeichen,
    Transformationsart,
    Transformationsplan,
    Transformationsschritt,
    Trennzeichenwahl,
    Zeichenkodierung,
)
from framework_mvp.infrastructure.exceptions import (
    Importintegritaetsfehler,
    NichtUnterstuetzteSchemaversion,
)
from framework_mvp.ui.components.datenprofil_visualisierung import zeige_datenprofil
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt
from framework_mvp.ui.components.transformation import zeige_transformationseditor
from framework_mvp.ui.navigation import (
    framework_bereich_oeffnen,
    schritt_abschliessen_und_weiter,
)
from framework_mvp.workspace import WorkspaceKonfiguration

LOGGER = logging.getLogger(__name__)
LOKALE_ZEITZONE = ZoneInfo("Europe/Vienna")

ETL_SCHRITTE = (
    "Datenquelle und Datei",
    "Tabelle und Vorschau",
    "Datenprofil",
    "Transformieren und verknüpfen",
    "Zwischendatensatz",
)
ETL_KURZNAMEN = ("Quelle", "Vorschau", "Profil", "Transformation", "Ergebnis")


def _enum_text(wert: Quellsystemtyp) -> str:
    """Formatiert einen Systemtyp als verständlichen Auswahltext."""
    return wert.value.replace("_", " ").upper()


def _projektkontext(projekt_service: ProjektService) -> tuple[UUID, str] | None:
    """Lädt ausschließlich das zentral gewählte Projekt und zeigt es schreibgeschützt."""
    rohwert = st.session_state.get("aktuelles_projekt_id")
    try:
        projekt_id = UUID(str(rohwert))
    except (TypeError, ValueError):
        st.warning("Bitte wählen oder erstellen Sie zuerst in Schritt 1 ein Projekt.")
        framework_bereich_oeffnen(schritt=1)
        return None
    projekt = projekt_service.projekt_laden(projekt_id)
    if projekt is None:
        st.warning("Das zentral gewählte Projekt ist nicht mehr vorhanden.")
        framework_bereich_oeffnen(schritt=1)
        return None
    links, rechts = st.columns((5, 1))
    links.write(f"**Aktuelles Projekt: {projekt.bezeichnung}**")
    if rechts.button("Projekt wechseln", width="stretch"):
        framework_bereich_oeffnen(schritt=1, projekt_id=projekt_id)
    return projekt_id, projekt.bezeichnung


def _wizard_zustand(projekt_id: UUID) -> dict[str, Any]:
    """Liefert den projektbezogenen, rerun-stabilen ETL-Zustand."""
    zustaende = st.session_state.setdefault("etl_wizard_zustaende", {})
    return zustaende.setdefault(str(projekt_id), {"schritt": 1})


def _zeige_etl_fortschritt(schritt: int) -> None:
    """Zeigt den kompakten Fortschritt des fünfteiligen ETL-Ablaufs."""
    zeige_kompakten_fortschritt(
        schritt=schritt,
        kurze_namen=ETL_KURZNAMEN,
        lange_namen=ETL_SCHRITTE,
    )


def _importbezeichnung(importvorgang: Importvorgang, datenquellenbezeichnung: str) -> str:
    """Erzeugt eine lesbare Importbezeichnung ohne primäre UUID."""
    zeitpunkt = (importvorgang.bestaetigt_am or importvorgang.erstellt_am).astimezone(
        LOKALE_ZEITZONE
    )
    tabelle = importvorgang.tabellenbezeichnung or "ohne Tabellenbezeichnung"
    return (
        f"{importvorgang.originaldateiname} · {datenquellenbezeichnung} · "
        f"{zeitpunkt:%d.%m.%Y, %H:%M Uhr} · {tabelle} · "
        f"{importvorgang.zeilenanzahl:,} Zeilen · "
        f"{importvorgang.spaltenanzahl:,} Spalten · {importvorgang.status.value.capitalize()}"
    )


def _neuester_konsistenter_import(
    service: ImportvorgangService, importe: list[Importvorgang]
) -> GeladenerImport | None:
    """Wählt den neuesten vollständig integritätsgeprüften Import."""
    sortiert = sorted(
        importe,
        key=lambda wert: (
            wert.bestaetigt_am or wert.erstellt_am,
            str(wert.import_id),
        ),
        reverse=True,
    )
    for importvorgang in sortiert:
        try:
            geladen = service.import_laden(importvorgang.import_id)
        except Importintegritaetsfehler:
            continue
        if geladen is not None:
            return geladen
    return None


def _abhaengige_zustaende_verwerfen(zustand: dict[str, Any]) -> None:
    """Invalidiert Vorschau, Profil, Plan und Ergebnis nach einer Importänderung."""
    for schluessel in (
        "vorschau",
        "vorschau_schluessel",
        "profil",
        "profil_schluessel",
        "bestaetigter_import",
        "transformationsplan",
        "transformationsergebnis",
        "zwischendatensatz",
        "zwischendatensatz_id",
    ):
        zustand.pop(schluessel, None)


def _gespeicherten_import_wiederherstellen(
    *,
    importvorgang_service: ImportvorgangService,
    datenimport_service: DatenimportService,
    import_id: UUID,
    zustand: dict[str, Any],
) -> Importvorgang:
    """Stellt Raw-Datei, Parameter, Tabelle, Vorschau und Profil eines Imports wieder her."""
    geladen = importvorgang_service.import_laden(import_id)
    if geladen is None:
        raise Domaenenfehler("Der ausgewählte gespeicherte Import wurde nicht gefunden.")
    importvorgang, dateiinhalt = importvorgang_service.originaldatei_laden(import_id)
    metadaten = DateiMetadaten(
        importvorgang.originaldateiname,
        importvorgang.sicherer_dateiname,
        importvorgang.dateigroesse_bytes,
        importvorgang.dateityp,
        importvorgang.sha256,
    )
    vorschau = datenimport_service.vorschau_erstellen(dateiinhalt, importvorgang.importparameter)
    profil = datenimport_service.profil_erstellen(vorschau.vollstaendige_tabelle)
    _abhaengige_zustaende_verwerfen(zustand)
    zustand.update(
        {
            "datenquellen_id": str(importvorgang.datenquellen_id),
            "dateiinhalt": dateiinhalt,
            "datei_metadaten": metadaten,
            "vorschau": vorschau,
            "vorschau_schluessel": datenimport_service.cache_schluessel(
                metadaten, importvorgang.importparameter
            ),
            "profil": profil,
            "profil_schluessel": datenimport_service.cache_schluessel(
                metadaten, importvorgang.importparameter
            ),
            "import_id": importvorgang.import_id,
            "bestaetigter_import": importvorgang,
            "gespeichertes_profil": geladen.profil,
        }
    )
    if isinstance(importvorgang.importparameter, CsvImportparameter):
        zustand["csv_parameter"] = importvorgang.importparameter
    else:
        zustand["excel_kopfzeile"] = importvorgang.importparameter.kopfzeile
        zustand["tabellenblatt"] = importvorgang.importparameter.tabellenblatt
    return importvorgang


def _quelle_auswaehlen(
    service: DatenquelleService, projekt_id: UUID, zustand: dict[str, Any]
) -> Datenquelle | None:
    """Wählt eine Katalogquelle oder den Eintrag für eine neue Quelle."""
    datenquellen = service.datenquellen_fuer_projekt(projekt_id)
    optionen = ["", *(str(quelle.datenquellen_id) for quelle in datenquellen)]
    texte = {str(q.datenquellen_id): q.bezeichnung for q in datenquellen}
    gespeichert = str(zustand.get("datenquellen_id", ""))
    index = optionen.index(gespeichert) if gespeichert in optionen else 0
    auswahl = st.selectbox(
        "Datenquelle",
        optionen,
        index=index,
        format_func=lambda wert: "Neue Datenquelle anlegen" if not wert else texte[wert],
        key=f"etl_quellenauswahl_{projekt_id}",
    )
    if auswahl != gespeichert:
        zustand["datenquellen_id"] = auswahl
        _abhaengige_zustaende_verwerfen(zustand)
    return next(
        (quelle for quelle in datenquellen if str(quelle.datenquellen_id) == auswahl),
        None,
    )


def _kopfzeile(
    schluessel: str, vorhanden: Kopfzeileneinstellung | None = None
) -> Kopfzeileneinstellung:
    """Erfasst eine Kopfzeile ohne technischen Nullwert."""
    beschriftungen = {
        "Erste Zeile": Kopfzeilenmodus.ERSTE_ZEILE,
        "Andere Zeile": Kopfzeilenmodus.BENUTZERDEFINIERT,
        "Keine Kopfzeile": Kopfzeilenmodus.KEINE,
    }
    aktueller_modus = vorhanden.modus if vorhanden else Kopfzeilenmodus.ERSTE_ZEILE
    namen = list(beschriftungen)
    index = list(beschriftungen.values()).index(aktueller_modus)
    modus = beschriftungen[st.selectbox("Kopfzeile", namen, index=index, key=f"{schluessel}_modus")]
    zeilennummer = None
    if modus is Kopfzeilenmodus.BENUTZERDEFINIERT:
        zeilennummer = int(
            st.number_input(
                "Zeilennummer der Kopfzeile",
                min_value=1,
                value=vorhanden.zeilennummer if vorhanden and vorhanden.zeilennummer else 1,
                key=schluessel,
            )
        )
    return Kopfzeileneinstellung(modus, zeilennummer)


def _erkenne_csv_kodierung(dateiinhalt: bytes) -> tuple[Zeichenkodierung, bool]:
    """Erkennt BOM oder eine verlustfrei decodierbare Standardkodierung."""
    if dateiinhalt.startswith(b"\xef\xbb\xbf"):
        return Zeichenkodierung.UTF_8_BOM, True
    try:
        dateiinhalt.decode("utf-8")
    except UnicodeDecodeError:
        return Zeichenkodierung.WINDOWS_1252, False
    return Zeichenkodierung.UTF_8, True


def _erkenne_csv_struktur(
    dateiinhalt: bytes, kodierung: Zeichenkodierung, trennzeichen: str
) -> tuple[str, Dezimaltrennzeichen | None]:
    """Erkennt Zeilenumbruch und ein eindeutiges Dezimaltrennzeichen heuristisch."""
    codec = {
        Zeichenkodierung.UTF_8: "utf-8",
        Zeichenkodierung.UTF_8_BOM: "utf-8-sig",
        Zeichenkodierung.ISO_8859_1: "iso-8859-1",
        Zeichenkodierung.WINDOWS_1252: "cp1252",
    }[kodierung]
    text = dateiinhalt[:65536].decode(codec, errors="replace")
    zeilenumbruch = (
        "Windows (CRLF)"
        if "\r\n" in text
        else "Unix (LF)"
        if "\n" in text
        else "Klassisch (CR)"
        if "\r" in text
        else "nicht sicher erkannt"
    )
    komma = 0 if trennzeichen == "," else len(re.findall(r"\b\d+,\d+\b", text))
    punkt = len(re.findall(r"\b\d+\.\d+\b", text))
    dezimal = (
        Dezimaltrennzeichen.KOMMA
        if komma > punkt and komma > 0
        else Dezimaltrennzeichen.PUNKT
        if punkt > komma and punkt > 0
        else None
    )
    return zeilenumbruch, dezimal


def _csv_einstellungen(
    import_service: DatenimportService, projekt_id: UUID, zustand: dict[str, Any]
) -> None:
    """Erkennt CSV-Grundparameter und erlaubt Korrekturen im Expander."""
    dateiinhalt: bytes = zustand["dateiinhalt"]
    vorhanden = zustand.get("csv_parameter")
    erkannt_kodierung, sicher = _erkenne_csv_kodierung(dateiinhalt)
    start_kodierung = vorhanden.zeichenkodierung if vorhanden else erkannt_kodierung
    try:
        erkanntes_trennzeichen = import_service.csv_trennzeichen_erkennen(
            dateiinhalt, start_kodierung
        )
    except Datenimportfehler:
        erkanntes_trennzeichen = ""
    zeilenumbruch, erkanntes_dezimal = _erkenne_csv_struktur(
        dateiinhalt, start_kodierung, erkanntes_trennzeichen
    )
    st.caption(
        "Automatisch erkannt: "
        f"{start_kodierung.value}, "
        f"Trennzeichen {repr(erkanntes_trennzeichen) if erkanntes_trennzeichen else 'unsicher'}, "
        f"Zeilenumbruch {zeilenumbruch}, Kopfzeile erste Zeile, "
        f"Dezimaltrennzeichen "
        f"{erkanntes_dezimal.value if erkanntes_dezimal else 'unsicher'}."
    )
    if not sicher or not erkanntes_trennzeichen:
        st.warning("Mindestens eine automatische CSV-Erkennung ist unsicher.")
    with st.expander("Erweiterte Importeinstellungen"):
        kodierungen = list(Zeichenkodierung)
        kodierung = st.selectbox(
            "Zeichenkodierung",
            kodierungen,
            index=kodierungen.index(start_kodierung),
            format_func=lambda wert: wert.value,
            key=f"etl_encoding_{projekt_id}",
        )
        trennzeichen = {
            "Automatisch erkannt": Trennzeichenwahl.AUTOMATISCH,
            "Komma": Trennzeichenwahl.KOMMA,
            "Semikolon": Trennzeichenwahl.SEMIKOLON,
            "Tabulator": Trennzeichenwahl.TABULATOR,
            "Benutzerdefiniert": Trennzeichenwahl.BENUTZERDEFINIERT,
        }
        vorhandene_wahl = vorhanden.trennzeichenwahl if vorhanden else Trennzeichenwahl.AUTOMATISCH
        namen = list(trennzeichen)
        wahl = trennzeichen[
            st.selectbox(
                "Trennzeichen",
                namen,
                index=list(trennzeichen.values()).index(vorhandene_wahl),
                key=f"etl_separator_{projekt_id}",
            )
        ]
        eigenes = ""
        if wahl is Trennzeichenwahl.BENUTZERDEFINIERT:
            eigenes = st.text_input(
                "Benutzerdefiniertes Trennzeichen",
                value=vorhanden.benutzerdefiniertes_trennzeichen if vorhanden else "",
                max_chars=1,
            )
        dezimal = st.selectbox(
            "Dezimaltrennzeichen",
            list(Dezimaltrennzeichen),
            index=list(Dezimaltrennzeichen).index(
                vorhanden.dezimaltrennzeichen
                if vorhanden
                else erkanntes_dezimal or Dezimaltrennzeichen.PUNKT
            ),
            format_func=lambda wert: wert.value,
        )
        kopfzeile = _kopfzeile(
            f"etl_csv_header_{projekt_id}", vorhanden.kopfzeile if vorhanden else None
        )
    parameter = CsvImportparameter(
        trennzeichenwahl=wahl,
        benutzerdefiniertes_trennzeichen=eigenes,
        erkanntes_trennzeichen=erkanntes_trennzeichen,
        zeichenkodierung=kodierung,
        dezimaltrennzeichen=dezimal,
        tausendertrennzeichen=Tausendertrennzeichen.KEINES,
        kopfzeile=kopfzeile,
    )
    if vorhanden != parameter:
        _abhaengige_zustaende_verwerfen(zustand)
        zustand["csv_parameter"] = parameter


def _excel_einstellungen(projekt_id: UUID, zustand: dict[str, Any]) -> None:
    """Erfasst ausschließlich die bei Excel nötige Kopfzeile."""
    with st.expander("Erweiterte Importeinstellungen"):
        kopfzeile = _kopfzeile(f"etl_excel_header_{projekt_id}", zustand.get("excel_kopfzeile"))
    if zustand.get("excel_kopfzeile") != kopfzeile:
        _abhaengige_zustaende_verwerfen(zustand)
        zustand["excel_kopfzeile"] = kopfzeile


def _gespeicherte_importe_fuer_quelle(
    *,
    importvorgang_service: ImportvorgangService,
    datenimport_service: DatenimportService,
    quelle: Datenquelle,
    zustand: dict[str, Any],
) -> None:
    """Bietet bestätigte Importe einer Quelle lesbar und ohne erneuten Upload an."""
    importe = importvorgang_service.importe_fuer_datenquelle(quelle.datenquellen_id)
    if not importe:
        return
    st.write("**Gespeicherte Importe dieser Datenquelle**")
    neuester = _neuester_konsistenter_import(importvorgang_service, importe)
    optionen = [wert.import_id for wert in importe]
    standard = (
        optionen.index(neuester.importvorgang.import_id)
        if neuester is not None
        else len(optionen) - 1
    )
    auswahl = st.selectbox(
        "Gespeicherten Import verwenden",
        optionen,
        index=standard,
        format_func=lambda wert: _importbezeichnung(
            next(eintrag for eintrag in importe if eintrag.import_id == wert),
            quelle.bezeichnung,
        ),
    )
    gewaehlt = next(wert for wert in importe if wert.import_id == auswahl)
    with st.expander("Technische Importinformationen"):
        st.write(f"Import-ID: `{gewaehlt.import_id}`")
        st.write(f"Prüfsumme: `{gewaehlt.sha256}`")
        st.write(f"Raw-Pfad: `{gewaehlt.relativer_raw_pfad}`")
        st.json(gewaehlt.importparameter)
    if st.button("Gespeicherten Import ohne erneuten Upload öffnen", type="primary"):
        _gespeicherten_import_wiederherstellen(
            importvorgang_service=importvorgang_service,
            datenimport_service=datenimport_service,
            import_id=auswahl,
            zustand=zustand,
        )
        zustand["schritt"] = 2
        st.rerun()


def _quelle_und_datei(
    *,
    datenquelle_service: DatenquelleService,
    datenimport_service: DatenimportService,
    importvorgang_service: ImportvorgangService,
    workspace: WorkspaceKonfiguration,
    projekt_id: UUID,
    zustand: dict[str, Any],
) -> None:
    """Verbindet Datenquellenkatalog, Upload, Erkennung und Grundeinstellungen."""
    st.subheader("Datenquelle und Datei")
    quelle = _quelle_auswaehlen(datenquelle_service, projekt_id, zustand)
    if quelle is not None:
        _gespeicherte_importe_fuer_quelle(
            importvorgang_service=importvorgang_service,
            datenimport_service=datenimport_service,
            quelle=quelle,
            zustand=zustand,
        )
    upload = st.file_uploader(
        "Rohdatei auswählen",
        type=["csv", "xlsx"],
        accept_multiple_files=False,
        key=f"etl_upload_{projekt_id}_{zustand.get('durchlauf_version', 0)}",
    )
    if upload is not None:
        inhalt = upload.getvalue()
        metadaten = datenimport_service.datei_pruefen(upload.name, inhalt)
        vorherige = getattr(zustand.get("datei_metadaten"), "sha256", None)
        if vorherige != metadaten.sha256:
            _abhaengige_zustaende_verwerfen(zustand)
            zustand["dateiinhalt"] = inhalt
            zustand["datei_metadaten"] = metadaten
        formattext = "Excel-Arbeitsmappe" if metadaten.dateityp is Dateityp.XLSX else "CSV-Datei"
        st.success(f"Erkanntes Dateiformat: {formattext}")
    metadaten = zustand.get("datei_metadaten")
    with st.form(f"datenquelle_formular_{projekt_id}"):
        bezeichnung = st.text_input(
            "Bezeichnung der Datenquelle", quelle.bezeichnung if quelle else ""
        )
        systemtypen = list(Quellsystemtyp)
        systemtyp = st.selectbox(
            "Quellsystemtyp",
            systemtypen,
            index=systemtypen.index(quelle.quellsystemtyp) if quelle else 0,
            format_func=_enum_text,
        )
        konkretes_system = st.text_input(
            "Konkretes Quellsystem (optional)",
            quelle.konkretes_quellsystem if quelle else "",
        )
        speichern = st.form_submit_button("Datenquelle speichern")
    if speichern:
        quellenart = (
            schlage_quellenart_vor(metadaten.dateityp)
            if metadaten is not None
            else quelle.quellenart
            if quelle is not None and quelle.quellenart is not Quellenart.DATENBANK
            else Quellenart.CSV
        )
        argumente = {
            "bezeichnung": bezeichnung,
            "quellsystemtyp": systemtyp,
            "quellenart": quellenart,
            "konkretes_quellsystem": konkretes_system,
            "fachliche_beschreibung": quelle.fachliche_beschreibung if quelle else "",
            "herkunft_oder_verantwortungsbereich": (
                quelle.herkunft_oder_verantwortungsbereich if quelle else ""
            ),
            "erwartete_tabellen_oder_blaetter": (
                quelle.erwartete_tabellen_oder_blaetter if quelle else ()
            ),
            "bekannte_schluesselattribute": (quelle.bekannte_schluesselattribute if quelle else ()),
        }
        gespeichert = (
            datenquelle_service.datenquelle_anlegen(projekt_id=projekt_id, **argumente)
            if quelle is None
            else datenquelle_service.datenquelle_aktualisieren(quelle.datenquellen_id, **argumente)
        )
        workspace.fuer_projekt_anlegen(projekt_id)
        zustand["datenquellen_id"] = str(gespeichert.datenquellen_id)
        st.session_state.etl_erfolgsmeldung = "Die Datenquelle wurde erfolgreich gespeichert."
        st.rerun()
    if metadaten is None:
        st.info("Laden Sie eine CSV- oder XLSX-Datei hoch oder öffnen Sie einen Import.")
        return
    if metadaten.dateityp is Dateityp.CSV:
        _csv_einstellungen(datenimport_service, projekt_id, zustand)
    else:
        _excel_einstellungen(projekt_id, zustand)


def _parameter(zustand: dict[str, Any]) -> CsvImportparameter | ExcelImportparameter:
    """Liefert die vollständigen Importparameter des aktuellen Zustands."""
    if zustand["datei_metadaten"].dateityp is Dateityp.CSV:
        return zustand["csv_parameter"]
    return ExcelImportparameter(zustand["tabellenblatt"], zustand["excel_kopfzeile"])


def _vorschau_berechnen(
    import_service: DatenimportService, zustand: dict[str, Any]
) -> Datenvorschau:
    """Berechnet oder verwendet eine parametergebundene Vorschau."""
    parameter = _parameter(zustand)
    schluessel = import_service.cache_schluessel(zustand["datei_metadaten"], parameter)
    if zustand.get("vorschau_schluessel") != schluessel:
        zustand["vorschau"] = import_service.vorschau_erstellen(zustand["dateiinhalt"], parameter)
        zustand["vorschau_schluessel"] = schluessel
        zustand.pop("profil", None)
        zustand.pop("profil_schluessel", None)
    return zustand["vorschau"]


def _tabelle_und_vorschau(
    import_service: DatenimportService, projekt_id: UUID, zustand: dict[str, Any]
) -> None:
    """Verbindet Tabellenblattauswahl und unveränderte Datenvorschau."""
    st.subheader("Tabelle und Vorschau")
    metadaten: DateiMetadaten = zustand["datei_metadaten"]
    if metadaten.dateityp is Dateityp.XLSX:
        if "tabellenblaetter" not in zustand:
            zustand["tabellenblaetter"] = import_service.excel_tabellenblaetter(
                zustand["dateiinhalt"]
            )
        namen = [blatt.name for blatt in zustand["tabellenblaetter"]]
        vorhanden = zustand.get("tabellenblatt")
        index = namen.index(vorhanden) if vorhanden in namen else 0
        auswahl = st.selectbox("Tabellenblatt", namen, index=index, key=f"etl_sheet_{projekt_id}")
        if vorhanden != auswahl:
            zustand["tabellenblatt"] = auswahl
            zustand.pop("vorschau_schluessel", None)
    else:
        st.caption("CSV-Datei · keine Tabellenblattauswahl erforderlich")
    vorschau = _vorschau_berechnen(import_service, zustand)
    st.write(
        f"**{vorschau.gesamtzeilen:,} Zeilen · "
        f"{vorschau.gesamtspalten:,} Spalten · "
        f"Kopfzeile: {_kopfzeilenbeschreibung(vorschau.verwendete_parameter)}**"
    )
    st.caption("Unveränderte Vorschau der ersten maximal 200 Zeilen.")
    st.dataframe(vorschau.tabelle, width="stretch")
    with st.expander("Technische Importinformationen"):
        st.write("Ursprüngliche Spaltennamen:", list(vorschau.spaltennamen))
        st.write("Erkannte technische Datentypen:", list(vorschau.pandas_datentypen))
        st.json(vorschau.verwendete_parameter)


def _kopfzeilenbeschreibung(
    parameter: CsvImportparameter | ExcelImportparameter,
) -> str:
    """Beschreibt die gewählte Kopfzeile ohne Python-Repräsentationen."""
    kopfzeile = parameter.kopfzeile
    if kopfzeile.modus is Kopfzeilenmodus.ERSTE_ZEILE:
        return "erste Zeile"
    if kopfzeile.modus is Kopfzeilenmodus.KEINE:
        return "keine"
    return f"Zeile {kopfzeile.zeilennummer}"


def _tabellenbezeichnung(zustand: dict[str, Any]) -> str:
    """Liefert Blatt- oder CSV-Tabellenname für die Herkunftsdokumentation."""
    metadaten: DateiMetadaten = zustand["datei_metadaten"]
    if metadaten.dateityp is Dateityp.XLSX:
        return str(zustand["tabellenblatt"])
    return metadaten.sicherer_dateiname.rsplit(".", maxsplit=1)[0]


def _datenprofil_und_bestaetigung(
    *,
    datenimport_service: DatenimportService,
    importvorgang_service: ImportvorgangService,
    projekt_id: UUID,
    zustand: dict[str, Any],
) -> None:
    """Zeigt das Profil und integriert die idempotente Importbestätigung."""
    st.subheader("Datenprofil")
    vorschau: Datenvorschau = zustand["vorschau"]
    profilschluessel = zustand["vorschau_schluessel"]
    if zustand.get("profil_schluessel") != profilschluessel:
        zustand["profil"] = datenimport_service.profil_erstellen(vorschau.vollstaendige_tabelle)
        zustand["profil_schluessel"] = profilschluessel
    ergebnis: Profilierungsergebnis = zustand["profil"]
    zeige_datenprofil(
        ergebnis,
        session_key=f"etl_profildetail_{projekt_id}_{zustand['datei_metadaten'].sha256}",
        daten=vorschau.vollstaendige_tabelle,
    )
    if zustand.get("bestaetigter_import") is not None:
        st.success("Diese Tabelle ist als Ausgangsdaten bestätigt.")
        return
    if st.button("Diese Tabelle als Ausgangsdaten verwenden", type="primary"):
        import_id = zustand.setdefault("import_id", uuid4())
        zustand["bestaetigter_import"] = importvorgang_service.import_bestaetigen(
            import_id=import_id,
            projekt_id=projekt_id,
            datenquellen_id=UUID(zustand["datenquellen_id"]),
            datei_metadaten=zustand["datei_metadaten"],
            dateiinhalt=zustand["dateiinhalt"],
            importparameter=vorschau.verwendete_parameter,
            tabellenbezeichnung=_tabellenbezeichnung(zustand),
            profil=ergebnis.profil,
        )
        zustand["schritt"] = 4
        st.rerun()


def _transformation(
    service: TransformationsService, projekt_id: UUID, zustand: dict[str, Any]
) -> None:
    """Zeigt und persistiert den Transformationsplan des bestätigten Imports."""
    importvorgang: Importvorgang = zustand["bestaetigter_import"]
    plan = zustand.get("transformationsplan")
    globaler_plan = st.session_state.pop("etl_transformationsplan", None)
    if globaler_plan is not None and globaler_plan.projekt_id == projekt_id:
        plan = globaler_plan
    if plan is None:
        plan = Transformationsplan.neu(projekt_id, (importvorgang.import_id,))
        service.plan_speichern(plan)
    daten = service.import_dataframe_laden(importvorgang.import_id)
    ausgangsprofil = service.ausgangsprofil_laden(importvorgang.import_id)
    zustand["transformationsplan"] = zeige_transformationseditor(
        service, plan, daten, ausgangsprofil.gesamtprofil
    )
    zustand["transformationsplan"] = _join_konfigurieren(
        service, projekt_id, zustand["transformationsplan"], daten
    )
    if ergebnis := st.session_state.pop("etl_transformationsergebnis", None):
        zustand["transformationsergebnis"] = ergebnis


def _join_konfigurieren(
    service: TransformationsService,
    projekt_id: UUID,
    plan: Transformationsplan,
    linke_daten: pd.DataFrame,
) -> Transformationsplan:
    """Prüft und ergänzt eine fachlich geführte Tabellenverknüpfung."""
    importe = [
        wert
        for wert in service.importe_fuer_projekt(projekt_id)
        if wert.import_id not in plan.import_ids
    ]
    with st.expander("Weitere Tabelle verknüpfen (optional)"):
        st.caption(
            "Ergänzen Sie den Hauptdatensatz um passende Informationen aus einer zweiten Tabelle."
        )
        with st.expander("Was bedeuten die Verknüpfungsarten?"):
            st.write("Haupttabelle: A, B, C · Zusatztabelle: B, C, D")
            st.write("Alle Hauptzeilen behalten: A, B, C (LEFT JOIN)")
            st.write("Nur passende Zeilen: B, C (INNER JOIN)")
            st.write("Alle Zeilen beider Tabellen: A, B, C, D (FULL OUTER JOIN)")
        if not importe:
            st.caption("Es ist keine weitere bestätigte Tabelle verfügbar.")
            return plan
        rechte_id = st.selectbox(
            "Zusätzliche bestätigte Tabelle",
            [wert.import_id for wert in importe],
            format_func=lambda wert: next(
                eintrag.originaldateiname for eintrag in importe if eintrag.import_id == wert
            ),
        )
        rechte_daten = service.import_dataframe_laden(rechte_id)
        linke_schluessel = st.multiselect(
            "Schlüsselspalte im Hauptdatensatz", [str(wert) for wert in linke_daten.columns]
        )
        rechte_schluessel = st.multiselect(
            "Schlüsselspalte in der zusätzlichen Tabelle",
            [str(wert) for wert in rechte_daten.columns],
        )
        join_texte = {
            "Alle Zeilen der Haupttabelle behalten (LEFT JOIN)": "LEFT",
            "Nur passende Zeilen beider Tabellen behalten (INNER JOIN)": "INNER",
            "Alle Zeilen beider Tabellen behalten (FULL OUTER JOIN)": "FULL OUTER",
        }
        join_art = join_texte[st.selectbox("Art der Verknüpfung", list(join_texte))]
        if not linke_schluessel or len(linke_schluessel) != len(rechte_schluessel):
            st.caption("Wählen Sie gleich viele Schlüsselspalten auf beiden Seiten.")
            return plan
        pruefung = pruefe_join(
            linke_daten, rechte_daten, tuple(linke_schluessel), tuple(rechte_schluessel)
        )
        passende_hauptzeilen = max(len(linke_daten) - pruefung.nicht_zuordenbar_links, 0)
        trefferquote = passende_hauptzeilen / len(linke_daten) if len(linke_daten) else 0.0
        st.write(
            f"**Hauptzeilen:** {len(linke_daten):,} · "
            f"**Zusatzzeilen:** {len(rechte_daten):,} · "
            f"**Trefferquote:** {trefferquote:.1%} · "
            f"**Ohne Treffer:** {pruefung.nicht_zuordenbar_links:,}/"
            f"{pruefung.nicht_zuordenbar_rechts:,} · "
            f"**Erwartete INNER-Zeilen:** {pruefung.erwartete_zeilen:,}"
        )
        nm_bestaetigt = st.checkbox(
            "Ich bestätige die mögliche Zeilenvervielfachung.",
            disabled=pruefung.kardinalitaet != "n:m",
        )
        if pruefung.kardinalitaet == "n:m":
            st.warning("Viele-zu-viele-Verknüpfung: Das Ergebnis kann Zeilen vervielfachen.")
        parameter = {
            "rechte_import_id": str(rechte_id),
            "linke_schluessel": linke_schluessel,
            "rechte_schluessel": rechte_schluessel,
            "join_art": join_art,
            "suffixe": ["_haupt", "_zusatz"],
            "nm_bestaetigt": nm_bestaetigt,
            "pruefung": {
                "kardinalitaet": pruefung.kardinalitaet,
                "erwartete_zeilen": pruefung.erwartete_zeilen,
            },
        }
        with st.expander("Technische Transformationsdefinition"):
            st.json(parameter)
        if st.button(
            "Verknüpfung anwenden",
            disabled=pruefung.kardinalitaet == "n:m" and not nm_bestaetigt,
        ):
            schritt = Transformationsschritt.neu(
                typ=Transformationsart.TABELLEN_JOIN,
                betroffene_spalten=tuple(linke_schluessel),
                parameter=parameter,
                reihenfolge=len(plan.schritte) + 1,
                beschreibung=f"{join_art}-Verknüpfung",
            )
            plan = service.schritt_hinzufuegen(plan, schritt)
            plan = replace(plan, import_ids=(*plan.import_ids, rechte_id))
            service.plan_speichern(plan)
            st.session_state.etl_transformationsplan = plan
            st.rerun()
    return plan


def _zwischendatensatz(
    service: TransformationsService,
    datenquelle_service: DatenquelleService,
    projekt_id: UUID,
    zustand: dict[str, Any],
) -> None:
    """Fasst Ausgabe und Artefakte zusammen und navigiert nach Erfolg zu Schritt 3."""
    st.subheader("Ausgabe dieses Schritts")
    st.write("### Zwischendatensatz T")
    plan: Transformationsplan = zustand["transformationsplan"]
    ergebnis = service.vorschau(plan)
    importvorgang: Importvorgang = zustand["bestaetigter_import"]
    quelle = datenquelle_service.datenquelle_laden(importvorgang.datenquellen_id)
    join_anzahl = sum(
        schritt.typ is Transformationsart.TABELLEN_JOIN and schritt.aktiviert
        for schritt in plan.schritte
    )
    st.write(
        f"**Datenquelle:** {quelle.bezeichnung if quelle else 'Unbekannt'}  \n"
        f"**Import:** {importvorgang.originaldateiname}  \n"
        f"**Tabelle:** {importvorgang.tabellenbezeichnung}  \n"
        f"**Umfang:** {len(ergebnis.daten):,} Zeilen · "
        f"{len(ergebnis.daten.columns):,} Spalten  \n"
        f"**Transformationen:** {sum(s.aktiviert for s in plan.schritte):,} · "
        f"davon {join_anzahl:,} Tabellenverknüpfungen  \n"
        f"**Warnungen:** {len(ergebnis.warnungen):,}"
    )
    st.caption(
        "Vorgesehene Artefakte: CSV.GZ, Schema-JSON und reproduzierbarer Transformationsplan."
    )
    datensatz = zustand.get("zwischendatensatz")
    if datensatz is None:
        datensatz_id = zustand.setdefault("zwischendatensatz_id", uuid4())
        if st.button(
            "Zwischendatensatz erstellen und mit dem semantischen Mapping fortfahren",
            type="primary",
        ):
            datensatz = service.zwischendatensatz_erzeugen(plan, ergebnis, datensatz_id)
            zustand["zwischendatensatz"] = datensatz
            st.session_state.aktueller_zwischendatensatz_id = str(datensatz.zwischendatensatz_id)
            schritt_abschliessen_und_weiter(aktueller_schritt=2, projekt_id=projekt_id)
        return
    st.success("Der Zwischendatensatz wurde reproduzierbar gespeichert.")
    st.write(f"**Daten:** `{datensatz.relativer_daten_pfad}`")
    st.write(f"**Schema:** `{datensatz.relativer_schema_pfad}`")
    st.write(f"**Transformation:** `{datensatz.relativer_transformation_pfad}`")


def _kann_weiter(zustand: dict[str, Any]) -> bool:
    """Prüft ausschließlich die Voraussetzung des aktuellen ETL-Abschnitts."""
    schritt = zustand["schritt"]
    if schritt == 1:
        metadaten = zustand.get("datei_metadaten")
        return bool(
            zustand.get("datenquellen_id")
            and metadaten
            and (
                (metadaten.dateityp is Dateityp.CSV and "csv_parameter" in zustand)
                or (metadaten.dateityp is Dateityp.XLSX and "excel_kopfzeile" in zustand)
            )
        )
    if schritt == 2:
        return "vorschau" in zustand
    if schritt == 3:
        return "bestaetigter_import" in zustand
    if schritt == 4:
        return "transformationsplan" in zustand
    return False


def _navigation(zustand: dict[str, Any]) -> None:
    """Navigiert kompakt zwischen den fünf ETL-Abschnitten."""
    zurueck, weiter = st.columns(2)
    if zurueck.button("Zurück", disabled=zustand["schritt"] == 1, width="content"):
        zustand["schritt"] -= 1
        st.rerun()
    if weiter.button(
        "Weiter",
        disabled=zustand["schritt"] >= len(ETL_SCHRITTE) or not _kann_weiter(zustand),
        type="primary",
        width="content",
    ):
        zustand["schritt"] += 1
        st.rerun()


def zeige_etl_seite(
    projekt_service: ProjektService,
    datenquelle_service: DatenquelleService,
    datenimport_service: DatenimportService,
    importvorgang_service: ImportvorgangService,
    transformations_service: TransformationsService,
    workspace: WorkspaceKonfiguration,
) -> None:
    """Zeigt Framework-Schritt 2 als fokussierten fünfstufigen ETL-Ablauf."""
    st.header("2 ETL durchführen")
    st.write(
        "Eingaben sind der Untersuchungsauftrag U, der Datenquellenkatalog Q und "
        "ausgewählte Rohdateien. Ausgabe ist der aufbereitete Zwischendatensatz T "
        "mit reproduzierbarem Transformationsplan und dokumentierter Herkunft."
    )
    try:
        projektkontext = _projektkontext(projekt_service)
        if projektkontext is None:
            return
        projekt_id, _ = projektkontext
        if meldung := st.session_state.pop("etl_erfolgsmeldung", None):
            st.success(meldung)
        zustand = _wizard_zustand(projekt_id)
        _zeige_etl_fortschritt(zustand["schritt"])
        if zustand["schritt"] == 1:
            _quelle_und_datei(
                datenquelle_service=datenquelle_service,
                datenimport_service=datenimport_service,
                importvorgang_service=importvorgang_service,
                workspace=workspace,
                projekt_id=projekt_id,
                zustand=zustand,
            )
        elif zustand["schritt"] == 2:
            _tabelle_und_vorschau(datenimport_service, projekt_id, zustand)
        elif zustand["schritt"] == 3:
            _datenprofil_und_bestaetigung(
                datenimport_service=datenimport_service,
                importvorgang_service=importvorgang_service,
                projekt_id=projekt_id,
                zustand=zustand,
            )
        elif zustand["schritt"] == 4:
            _transformation(transformations_service, projekt_id, zustand)
        else:
            _zwischendatensatz(
                transformations_service,
                datenquelle_service,
                projekt_id,
                zustand,
            )
        _navigation(zustand)
    except (Domaenenfehler, Datenimportfehler) as fehler:
        st.error(str(fehler))
    except NichtUnterstuetzteSchemaversion as fehler:
        st.error(str(fehler))
    except Importintegritaetsfehler as fehler:
        LOGGER.exception("Integritätsfehler beim Laden oder Speichern eines Imports.")
        st.error(str(fehler))
    except Exception:
        LOGGER.exception("Unerwarteter Fehler auf der ETL-Seite.")
        st.error(
            "Der ETL-Schritt konnte aufgrund eines technischen Fehlers nicht ausgeführt werden."
        )
