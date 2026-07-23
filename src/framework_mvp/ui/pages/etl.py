"""ETL-Hauptseite mit Datenquellenkatalog und temporärem Import-Wizard."""

import logging
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

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
from framework_mvp.application.importvorgang_service import ImportvorgangService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.transformation import pruefe_join
from framework_mvp.application.transformations_service import TransformationsService
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
from framework_mvp.ui.components.datenprofil_visualisierung import (
    zeige_datenprofil,
    zeige_gespeichertes_datenprofil,
)
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt
from framework_mvp.ui.components.transformation import zeige_transformationseditor
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
    "Daten transformieren",
    "Zwischendatensatz erzeugen",
)
ETL_KURZNAMEN = (
    "Quelle",
    "Upload",
    "Einstellungen",
    "Tabelle",
    "Vorschau",
    "Profil",
    "Bestätigung",
    "Transformation",
    "Datensatz",
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
    zeige_kompakten_fortschritt(
        schritt=schritt,
        kurze_namen=ETL_KURZNAMEN,
        lange_namen=ETL_SCHRITTE,
    )


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
        key=f"etl_upload_{projekt_id}_{zustand.get('durchlauf_version', 0)}",
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
            "import_id",
            "bestaetigter_import",
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
    st.dataframe(vorschau.tabelle, width="stretch")
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


def _tabellenbezeichnung(zustand: dict[str, Any]) -> str:
    metadaten = zustand["datei_metadaten"]
    if metadaten.dateityp is Dateityp.XLSX:
        return str(zustand["tabellenblatt"])
    return metadaten.sicherer_dateiname.rsplit(".", maxsplit=1)[0]


def _importpruefung(
    projekt_service: ProjektService,
    datenquelle_service: DatenquelleService,
    importvorgang_service: ImportvorgangService,
    projekt_id: UUID,
    zustand: dict[str, Any],
) -> None:
    profilierung: Profilierungsergebnis = zustand["profil"]
    profil = profilierung.profil
    metadaten = zustand["datei_metadaten"]
    datenquelle = datenquelle_service.datenquelle_laden(UUID(zustand["datenquellen_id"]))
    projekt = projekt_service.projekt_laden(projekt_id)
    if datenquelle is None or projekt is None:
        raise Domaenenfehler("Projekt oder Datenquelle des Imports wurde nicht gefunden.")
    st.subheader("Import prüfen und bestätigen")
    st.write(f"**Projekt:** {projekt.bezeichnung}")
    st.write(f"**Datenquelle:** {datenquelle.bezeichnung}")
    st.write(f"**Originaldateiname:** {metadaten.urspruenglicher_dateiname}")
    st.write(
        f"**Dateityp und Größe:** {metadaten.dateityp.value} · "
        f"{metadaten.dateigroesse_bytes:,} Bytes"
    )
    st.write(f"**Prüfsumme:** `{metadaten.sha256[:12]}…`")
    with st.expander("Vollständige SHA-256-Prüfsumme"):
        st.code(metadaten.sha256, language=None)
    st.write(f"**Importparameter:** {zustand['vorschau'].verwendete_parameter}")
    st.write(f"**Tabelle beziehungsweise Blatt:** {_tabellenbezeichnung(zustand)}")
    kennzahlen = st.columns(5)
    for spalte, (name, wert) in zip(
        kennzahlen,
        (
            ("Zeilen", profil.zeilen),
            ("Spalten", profil.spalten),
            ("Echte Fehlwerte", profil.echte_fehlwerte),
            ("Textuelle Platzhalter", profil.textuelle_platzhalter),
            ("Exakte Duplikate", profil.exakte_duplikate),
        ),
        strict=True,
    ):
        spalte.metric(name, wert)
    warnungen = importvorgang_service.import_warnings(profil)
    if warnungen:
        for warnung in warnungen:
            st.warning(warnung)
    else:
        st.success("Die technische Profilierung hat keine Qualitätswarnungen erzeugt.")
    st.info(
        "Die Originaldatei wird unverändert gespeichert. Erkannte Fehlwerte, Platzhalter, "
        "Duplikate und Ausreißer werden nicht automatisch korrigiert."
    )
    bestaetigt = zustand.get("bestaetigter_import")
    if bestaetigt is not None:
        st.success("Der Import wurde verbindlich bestätigt.")
        st.write(f"**Import-ID:** `{bestaetigt.import_id}`")
        st.write(f"**Bestätigt am:** {bestaetigt.bestaetigt_am}")
        st.write(f"**Gespeicherte Datenquelle:** {datenquelle.bezeichnung}")
        st.write(f"**Relativer Raw-Pfad:** `{bestaetigt.relativer_raw_pfad}`")
        st.write(f"**Relativer Profil-Pfad:** `{bestaetigt.relativer_profil_pfad}`")
        if st.button("Neuen Import beginnen", type="primary"):
            version = zustand.get("durchlauf_version", 0) + 1
            zustand.clear()
            zustand.update({"schritt": 1, "durchlauf_version": version})
            st.rerun()
        return
    import_id = zustand.setdefault("import_id", uuid4())
    laeuft = bool(zustand.get("bestaetigung_laeuft"))
    angefordert = st.button("Import verbindlich bestätigen", type="primary", disabled=laeuft)
    if angefordert:
        zustand["bestaetigung_laeuft"] = True
        st.rerun()
    if laeuft:
        try:
            zustand["bestaetigter_import"] = importvorgang_service.import_bestaetigen(
                import_id=import_id,
                projekt_id=projekt_id,
                datenquellen_id=datenquelle.datenquellen_id,
                datei_metadaten=metadaten,
                dateiinhalt=zustand["dateiinhalt"],
                importparameter=zustand["vorschau"].verwendete_parameter,
                tabellenbezeichnung=_tabellenbezeichnung(zustand),
                profil=profil,
            )
        finally:
            zustand["bestaetigung_laeuft"] = False
        st.rerun()


def _transformation(
    service: TransformationsService,
    projekt_id: UUID,
    zustand: dict[str, Any],
) -> None:
    """Zeigt und persistiert den Transformationsplan des bestätigten Imports."""
    importvorgang = zustand["bestaetigter_import"]
    plan = zustand.get("transformationsplan")
    globaler_plan = st.session_state.pop("etl_transformationsplan", None)
    if globaler_plan is not None and globaler_plan.projekt_id == projekt_id:
        plan = globaler_plan
    if plan is None:
        plan = Transformationsplan.neu(projekt_id, (importvorgang.import_id,))
        service.plan_speichern(plan)
    daten = service.import_dataframe_laden(importvorgang.import_id)
    ausgangsprofil = service.ausgangsprofil_laden(importvorgang.import_id)
    plan = _join_konfigurieren(service, projekt_id, plan, daten)
    zustand["transformationsplan"] = zeige_transformationseditor(
        service, plan, daten, ausgangsprofil.gesamtprofil
    )
    if ergebnis := st.session_state.pop("etl_transformationsergebnis", None):
        zustand["transformationsergebnis"] = ergebnis


def _join_konfigurieren(
    service: TransformationsService,
    projekt_id: UUID,
    plan: Transformationsplan,
    linke_daten: pd.DataFrame,
) -> Transformationsplan:
    """Prüft und ergänzt eine explizite Tabellenverknüpfung."""
    importe = [
        wert
        for wert in service.importe_fuer_projekt(projekt_id)
        if wert.import_id not in plan.import_ids
    ]
    with st.expander("Weitere bestätigte Tabelle verknüpfen"):
        if not importe:
            st.caption("Für einen Join wird ein weiterer bestätigter Import benötigt.")
            return plan
        rechte_id = st.selectbox(
            "Rechte Importtabelle",
            [wert.import_id for wert in importe],
            format_func=lambda wert: next(
                eintrag.originaldateiname for eintrag in importe if eintrag.import_id == wert
            ),
        )
        rechte_daten = service.import_dataframe_laden(rechte_id)
        linke_schluessel = st.multiselect(
            "Schlüsselspalten links", [str(wert) for wert in linke_daten.columns]
        )
        rechte_schluessel = st.multiselect(
            "Passende Schlüsselspalten rechts", [str(wert) for wert in rechte_daten.columns]
        )
        join_art = st.selectbox("Join-Art", ("INNER", "LEFT", "RIGHT", "FULL OUTER"))
        if not linke_schluessel or len(linke_schluessel) != len(rechte_schluessel):
            st.caption("Wählen Sie gleich viele linke und rechte Schlüsselspalten.")
            return plan
        pruefung = pruefe_join(
            linke_daten, rechte_daten, tuple(linke_schluessel), tuple(rechte_schluessel)
        )
        st.write(
            f"**Kardinalität:** {pruefung.kardinalitaet} · "
            f"**Erwartete INNER-Zeilen:** {pruefung.erwartete_zeilen}"
        )
        st.write(
            f"Nicht zuordenbare Schlüssel links/rechts: "
            f"{pruefung.nicht_zuordenbar_links}/{pruefung.nicht_zuordenbar_rechts}"
        )
        nm_bestaetigt = st.checkbox(
            "Ich bestätige die mögliche Zeilenvervielfachung.",
            disabled=pruefung.kardinalitaet != "n:m",
        )
        if pruefung.kardinalitaet == "n:m":
            st.warning(pruefung.warnungen[0])
        if st.button(
            "Join-Schritt hinzufügen",
            disabled=pruefung.kardinalitaet == "n:m" and not nm_bestaetigt,
        ):
            schritt = Transformationsschritt.neu(
                typ=Transformationsart.TABELLEN_JOIN,
                betroffene_spalten=tuple(linke_schluessel),
                parameter={
                    "rechte_import_id": str(rechte_id),
                    "linke_schluessel": linke_schluessel,
                    "rechte_schluessel": rechte_schluessel,
                    "join_art": join_art,
                    "suffixe": ["_links", "_rechts"],
                    "nm_bestaetigt": nm_bestaetigt,
                    "pruefung": {
                        "kardinalitaet": pruefung.kardinalitaet,
                        "erwartete_zeilen": pruefung.erwartete_zeilen,
                    },
                },
                reihenfolge=len(plan.schritte) + 1,
                beschreibung=f"{join_art}-Join",
            )
            plan = service.schritt_hinzufuegen(plan, schritt)
            plan = replace(plan, import_ids=(*plan.import_ids, rechte_id))
            service.plan_speichern(plan)
            st.session_state.etl_transformationsplan = plan
            st.rerun()
    return plan


def _zwischendatensatz(
    service: TransformationsService,
    zustand: dict[str, Any],
) -> None:
    """Zeigt die abschließende Prüfung und erzeugt die drei Interim-Artefakte."""
    st.subheader("Zwischendatensatz erzeugen")
    plan = zustand["transformationsplan"]
    ergebnis = service.vorschau(plan)
    st.write(f"**Aktive Transformationsschritte:** {sum(s.aktiviert for s in plan.schritte)}")
    st.write(
        f"**Ergebnisumfang:** {len(ergebnis.daten)} Zeilen, {len(ergebnis.daten.columns)} Spalten"
    )
    st.dataframe(ergebnis.vorschau, width="stretch")
    datensatz = zustand.get("zwischendatensatz")
    if datensatz is None:
        datensatz_id = zustand.setdefault("zwischendatensatz_id", uuid4())
        if st.button("Zwischendatensatz verbindlich erzeugen", type="primary"):
            zustand["zwischendatensatz"] = service.zwischendatensatz_erzeugen(
                plan, ergebnis, datensatz_id
            )
            st.rerun()
        return
    st.success("Der Zwischendatensatz wurde reproduzierbar gespeichert.")
    st.write(f"**Datensatz-ID:** `{datensatz.zwischendatensatz_id}`")
    st.write(f"**Daten:** `{datensatz.relativer_daten_pfad}`")
    st.write(f"**Schema:** `{datensatz.relativer_schema_pfad}`")
    st.write(f"**Transformation:** `{datensatz.relativer_transformation_pfad}`")


def _gespeicherte_importe(
    service: ImportvorgangService,
    datenquelle_service: DatenquelleService,
    projekt_id: UUID,
) -> None:
    with st.expander("Gespeicherte Importe des Projekts"):
        importe = service.importe_fuer_projekt(projekt_id)
        if not importe:
            st.caption("Für dieses Projekt wurden noch keine Importe bestätigt.")
            return
        quellen = {
            quelle.datenquellen_id: quelle.bezeichnung
            for quelle in datenquelle_service.datenquellen_fuer_projekt(projekt_id)
        }
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Zeitpunkt": wert.bestaetigt_am,
                        "Datenquelle": quellen.get(wert.datenquellen_id, "Unbekannt"),
                        "Datei": wert.originaldateiname,
                        "Tabelle/Blatt": wert.tabellenbezeichnung,
                        "Zeilen": wert.zeilenanzahl,
                        "Spalten": wert.spaltenanzahl,
                        "Status": wert.status.value,
                        "Prüfsumme": f"{wert.sha256[:12]}…",
                    }
                    for wert in importe
                ]
            ),
            hide_index=True,
        )
        optionen = ["", *(str(wert.import_id) for wert in importe)]
        auswahl = st.selectbox("Gespeicherten Import öffnen", optionen)
        if not auswahl:
            return
        geladen = service.import_laden(UUID(auswahl))
        if geladen is None:
            st.error("Der ausgewählte Import wurde nicht gefunden.")
            return
        st.success("Raw-Datei, Prüfsumme und Profil-JSON sind konsistent.")
        st.write("**Gespeicherte Importparameter:**")
        st.json(geladen.profil.importparameter)
        zeige_gespeichertes_datenprofil(geladen.profil.gesamtprofil)


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
    if schritt == 6:
        return "profil" in zustand
    if schritt == 7:
        return "bestaetigter_import" in zustand
    if schritt == 8:
        return "transformationsplan" in zustand
    return False


def _navigation(zustand: dict[str, Any]) -> None:
    zurueck, weiter = st.columns(2)
    if zurueck.button("Zurück", disabled=zustand["schritt"] == 1, width="stretch"):
        zustand["schritt"] -= 1
        st.rerun()
    if weiter.button(
        "Weiter",
        disabled=zustand["schritt"] >= len(ETL_SCHRITTE) or not _kann_weiter(zustand),
        type="primary",
        width="stretch",
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
    """Zeigt Framework-Schritt 2 und den vollständigen neunstufigen ETL-Wizard."""
    st.header("2 ETL durchführen")
    if meldung := st.session_state.pop("etl_erfolgsmeldung", None):
        st.success(meldung)
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
        elif zustand["schritt"] == 6:
            _datenprofil(datenimport_service, projekt_id, zustand)
        elif zustand["schritt"] == 7:
            _importpruefung(
                projekt_service,
                datenquelle_service,
                importvorgang_service,
                projekt_id,
                zustand,
            )
        elif zustand["schritt"] == 8:
            _transformation(transformations_service, projekt_id, zustand)
        else:
            _zwischendatensatz(transformations_service, zustand)
        _navigation(zustand)
        _gespeicherte_importe(importvorgang_service, datenquelle_service, projekt_id)
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
