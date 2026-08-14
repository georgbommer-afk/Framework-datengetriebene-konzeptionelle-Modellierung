"""Wizard für Schritt 1: Projektrahmen definieren mit den Ausgaben U und S."""

import logging
from collections.abc import Callable, MutableMapping
from dataclasses import replace
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import streamlit as st

from framework_mvp.application.ergebnisaggregation import KPI_DEFINITIONEN
from framework_mvp.application.loesch_service import LoeschService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.kataloge import (
    ERZEUGNISSTRUKTURTYP_BEZEICHNUNGEN,
    GESTALT_DER_GUETER_BEZEICHNUNGEN,
    INTRALOGISTIKSPEZIFISCHE_MERKMALE,
    MATERIALFLUSSKONTINUITAET_BEZEICHNUNGEN,
    PRODUKTIONSSPEZIFISCHE_MERKMALE,
    SYSTEMTYP_BEZEICHNUNGEN,
    ZIELGROESSEN_BEZEICHNUNGEN,
    ZIELGRUPPEN,
    leite_kpi_kandidaten_ab,
)
from framework_mvp.domain.models import (
    Betrachtungszeitraum,
    Erzeugnisstrukturtyp,
    GestaltDerGueter,
    Intralogistikklassifikation,
    LogistischeZielgroesse,
    Materialflusskontinuitaet,
    Produktionsklassifikation,
    Projekt,
    Projektstatus,
    Rahmenbedingungen,
    Systemklassifikation,
    Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion
from framework_mvp.ui.fortschritt import unterschritte_fuer
from framework_mvp.ui.helpers import fachliche_auswahl
from framework_mvp.ui.navigation import schritt_abschliessen_und_weiter
from framework_mvp.ui.session_cleanup import (
    projekt_zustand_bereinigen,
    zwischendatensatz_zustand_bereinigen,
)

LOGGER = logging.getLogger(__name__)
LOKALE_ZEITZONE = ZoneInfo("Europe/Vienna")

SCHRITTE = unterschritte_fuer(1)
VORDEFINIERTE_UNTERSUCHUNGSZWECKE = (
    "System verstehen und transparent beschreiben",
    "System analysieren",
    "System evaluieren",
    "Varianten oder Bereiche vergleichen",
    "zukünftiges Verhalten prognostizieren",
)
WEITERER_ZWECK = "Weiteren Untersuchungszweck hinzufügen …"
PROBLEM_HILFE = (
    "Beschreiben Sie kurz, welches betriebliche Problem oder welche Fragestellung "
    "mit der Untersuchung analysiert werden soll."
)
SYSTEMGRENZE_HILFE = (
    "Beschreiben Sie, welche Prozesse, Bereiche oder Objekte betrachtet werden und "
    "was ausdrücklich außerhalb der Untersuchung liegt."
)


def _enum_text(wert: Any) -> str:
    return str(wert.value).replace("_", " ").capitalize()


def _neuer_entwurf() -> dict[str, Any]:
    return {
        "bezeichnung": "",
        "status": Projektstatus.ENTWURF,
        "personen": (),
        "problemstellung": "",
        "systemgrenze": "",
        "zwecke": [],
        "individuelle_zwecke": [],
        "zielgroessen": [],
        "systemtyp": None,
        "systemklassifikation": Systemklassifikation(),
        "gestalt": None,
        "erzeugnisstrukturtyp": None,
        "kontinuitaet": None,
        "produktion": {},
        "intralogistik": {},
        "kpis": [],
        "detaillierung": "",
        "rahmenbedingungen": Rahmenbedingungen(),
        "betrachtungszeitraum": Betrachtungszeitraum(),
        "anmerkungen": "",
        "legacy_kpis": [],
        "migrationsbestand": False,
    }


def _entwurf_aus_projekt(projekt: Projekt) -> dict[str, Any]:
    auftrag = projekt.untersuchungsauftrag
    system = auftrag.systemklassifikation
    zwecke = list(auftrag.untersuchungszwecke)
    individuelle = [zweck for zweck in zwecke if zweck not in VORDEFINIERTE_UNTERSUCHUNGSZWECKE]
    if auftrag.individuelles_ziel and all(
        auftrag.individuelles_ziel.casefold() != zweck.casefold() for zweck in zwecke
    ):
        zwecke.append(auftrag.individuelles_ziel)
        individuelle.append(auftrag.individuelles_ziel)
    return {
        "bezeichnung": projekt.bezeichnung,
        "status": projekt.status,
        "personen": projekt.beteiligte_personen,
        "problemstellung": auftrag.problemstellung,
        "systemgrenze": auftrag.systemgrenze,
        "zwecke": zwecke,
        "individuelle_zwecke": individuelle,
        "zielgroessen": list(auftrag.logistische_zielgroessen),
        "systemtyp": auftrag.systemtyp,
        "systemklassifikation": system,
        "gestalt": system.gestalt_der_gueter,
        "erzeugnisstrukturtyp": system.erzeugnisstrukturtyp,
        "kontinuitaet": system.materialflusskontinuitaet,
        "produktion": (
            {}
            if system.produktion is None
            else {
                name: getattr(system.produktion, name)
                for name in system.produktion.__dataclass_fields__
            }
        ),
        "intralogistik": (
            {}
            if system.intralogistik is None
            else {
                name: getattr(system.intralogistik, name)
                for name in system.intralogistik.__dataclass_fields__
            }
        ),
        "kpis": list(auftrag.ausgewaehlte_kpi_ids),
        "detaillierung": auftrag.detaillierungsgrad,
        "rahmenbedingungen": auftrag.rahmenbedingungen,
        "betrachtungszeitraum": auftrag.betrachtungszeitraum,
        "anmerkungen": auftrag.anmerkungen,
        "legacy_kpis": list(auftrag.legacy_leistungskennzahlen),
        "migrationsbestand": auftrag.migrationsbestand,
    }


def _initialisieren() -> None:
    for schluessel, wert in (
        ("ausgewaehlte_projekt_id", None),
        ("auswahl_generation", 0),
        ("wizard_schritt", 1),
        ("wizard_entwurf", _neuer_entwurf()),
    ):
        if schluessel not in st.session_state:
            st.session_state[schluessel] = wert


def _widget_key(feld: str) -> str:
    """Bindet einen Widgetzustand an Projekt beziehungsweise Entwurfsgeneration."""
    projekt_id = st.session_state.ausgewaehlte_projekt_id
    kontext = str(projekt_id) if projekt_id is not None else "neu"
    return f"projektrahmen_{kontext}_{st.session_state.auswahl_generation}_{feld}"


def _widget_initialisieren(feld: str, wert: Any) -> str:
    """Initialisiert einen fachlichen Widgetwert genau einmal je Projektkontext."""
    key = _widget_key(feld)
    if key not in st.session_state:
        st.session_state[key] = wert
    return key


def _projekt_nach_id(projekte: list[Projekt], projekt_id: UUID | None) -> Projekt | None:
    return next((projekt for projekt in projekte if projekt.projekt_id == projekt_id), None)


@st.dialog("Projekt löschen")
def _projekt_loeschen_dialog(
    projekt: Projekt,
    service: LoeschService,
    nachbereitung: Callable[[], None] | None = None,
) -> None:
    st.warning(
        f"Das Projekt **{projekt.bezeichnung}** und alle zugehörigen Artefakte werden "
        "dauerhaft gelöscht. Andere Projekte bleiben unverändert."
    )
    loeschen, abbrechen = st.columns(2)
    if loeschen.button(
        "Endgültig löschen",
        type="primary",
        width="stretch",
        key=f"projekt_dialog_loeschen_{projekt.projekt_id}",
    ):
        try:
            _projektloeschung_ausfuehren(
                projekt,
                service,
                cast("MutableMapping[str, Any]", st.session_state),
            )
            if nachbereitung is not None:
                nachbereitung()
        except Domaenenfehler as fehler:
            st.error(str(fehler))
            return
        except Exception:
            LOGGER.exception("Unerwarteter Fehler beim Löschen eines Projekts.")
            st.error("Das Projekt konnte nicht vollständig gelöscht werden.")
            return
        st.rerun(scope="app")
    if abbrechen.button(
        "Abbrechen", width="stretch", key=f"projekt_dialog_abbrechen_{projekt.projekt_id}"
    ):
        st.rerun(scope="app")


def _datensatzbezeichnung(datensatz: Any) -> str:
    zeitpunkt = datensatz.erstellt_am.astimezone(LOKALE_ZEITZONE)
    return (
        f"Zwischendatensatz vom {zeitpunkt:%d.%m.%Y, %H:%M Uhr} · "
        f"{datensatz.zeilenanzahl:,} Zeilen · {datensatz.spaltenanzahl:,} Spalten"
    )


def _projektloeschung_ausfuehren(
    projekt: Projekt,
    service: LoeschService,
    zustand: MutableMapping[str, Any],
) -> None:
    """Löscht exakt das bestätigte Projekt und bereitet die Navigation vor."""
    service.projekt_loeschen(projekt.projekt_id)
    projekt_zustand_bereinigen(zustand, projekt.projekt_id)
    zustand["erfolgsmeldung"] = f"Projekt „{projekt.bezeichnung}“ wurde vollständig gelöscht."


def _datensatzloeschung_ausfuehren(
    projekt: Projekt,
    datensatz: Any,
    service: LoeschService,
    zustand: MutableMapping[str, Any],
) -> None:
    """Löscht exakt das bestätigte T und bereitet die Navigation vor."""
    service.zwischendatensatz_loeschen(projekt.projekt_id, datensatz.zwischendatensatz_id)
    zwischendatensatz_zustand_bereinigen(
        zustand,
        projekt.projekt_id,
        datensatz.zwischendatensatz_id,
    )
    zustand["etl_erfolgsmeldung"] = (
        f"{_datensatzbezeichnung(datensatz)} wurde vollständig gelöscht."
    )


@st.dialog("Datensatz löschen")
def _datensatz_loeschen_dialog(
    projekt: Projekt,
    datensaetze: list[Any],
    service: LoeschService,
) -> None:
    aktueller_wert = st.session_state.get("aktueller_zwischendatensatz_id")
    ids = [wert.zwischendatensatz_id for wert in datensaetze]
    vorauswahl = next(
        (index for index, wert in enumerate(ids) if str(wert) == str(aktueller_wert)),
        0,
    )
    datensatz_id = st.selectbox(
        "Zwischendatensatz",
        ids,
        index=vorauswahl,
        format_func=lambda wert: next(
            _datensatzbezeichnung(eintrag)
            for eintrag in datensaetze
            if eintrag.zwischendatensatz_id == wert
        ),
    )
    if datensatz_id is None:  # pragma: no cover - die Optionsliste ist fachlich nicht leer
        return
    ziel = next(wert for wert in datensaetze if wert.zwischendatensatz_id == datensatz_id)
    st.warning(
        f"**{_datensatzbezeichnung(ziel)}** aus Projekt **{projekt.bezeichnung}** und "
        "alle ausschließlich davon abhängigen Artefakte werden gelöscht. Rohimporte, "
        "Datenquellen und andere Datensätze bleiben erhalten."
    )
    loeschen, abbrechen = st.columns(2)
    if loeschen.button(
        "Endgültig löschen",
        type="primary",
        width="stretch",
        key=f"datensatz_dialog_loeschen_{datensatz_id}",
    ):
        try:
            _datensatzloeschung_ausfuehren(
                projekt,
                ziel,
                service,
                cast("MutableMapping[str, Any]", st.session_state),
            )
        except Domaenenfehler as fehler:
            st.error(str(fehler))
            return
        except Exception:
            LOGGER.exception("Unerwarteter Fehler beim Löschen eines Zwischendatensatzes.")
            st.error("Der Zwischendatensatz konnte nicht vollständig gelöscht werden.")
            return
        st.rerun(scope="app")
    if abbrechen.button(
        "Abbrechen", width="stretch", key=f"datensatz_dialog_abbrechen_{datensatz_id}"
    ):
        st.rerun(scope="app")


def zeige_loeschaktionen(
    projekt: Projekt,
    transformations_service: TransformationsService | None,
    loesch_service: LoeschService,
    *,
    projekt_loesch_label: str = "Projekt löschen",
    projektloeschung_nachbereiten: Callable[[], None] | None = None,
    projekt_loeschen_erlaubt: bool = True,
    datensatz_loeschen_erlaubt: bool = True,
) -> None:
    """Rendert autorisierte Löschaktionen im dauerhaft sichtbaren Projektrahmen."""
    datensaetze = (
        transformations_service.datensaetze_fuer_projekt(projekt.projekt_id)
        if transformations_service is not None and datensatz_loeschen_erlaubt
        else []
    )
    if not projekt_loeschen_erlaubt and not datensaetze:
        return
    st.sidebar.divider()
    links, rechts = st.sidebar.columns(2)
    if projekt_loeschen_erlaubt and links.button(projekt_loesch_label, width="stretch"):
        _projekt_loeschen_dialog(
            projekt,
            loesch_service,
            projektloeschung_nachbereiten,
        )
    if datensaetze and rechts.button("Datensatz löschen", width="stretch"):
        _datensatz_loeschen_dialog(projekt, datensaetze, loesch_service)


def _seitenleiste(
    projekte: list[Projekt],
    transformations_service: TransformationsService | None = None,
    loesch_service: LoeschService | None = None,
    *,
    titel_anzeigen: bool = True,
    projekt_loesch_label: str = "Projekt löschen",
    projektloeschung_nachbereiten: Callable[[], None] | None = None,
) -> Projekt | None:
    if titel_anzeigen:
        st.sidebar.header("Projektrahmen")
    aktuelle_id = st.session_state.ausgewaehlte_projekt_id
    if aktuelle_id not in {projekt.projekt_id for projekt in projekte}:
        aktuelle_id = None
    optionen = ["", *(str(projekt.projekt_id) for projekt in projekte)]
    texte = {str(projekt.projekt_id): projekt.bezeichnung for projekt in projekte}
    auswahl = st.sidebar.selectbox(
        "Vorhandenes Projekt auswählen",
        optionen,
        index=optionen.index("" if aktuelle_id is None else str(aktuelle_id)),
        format_func=lambda wert: "Neues Projekt" if not wert else texte[wert],
        key=f"projektauswahl_{st.session_state.auswahl_generation}",
    )
    neue_id = UUID(auswahl) if auswahl else None
    if neue_id != aktuelle_id:
        projekt = _projekt_nach_id(projekte, neue_id)
        st.session_state.ausgewaehlte_projekt_id = neue_id
        st.session_state.wizard_entwurf = (
            _neuer_entwurf() if projekt is None else _entwurf_aus_projekt(projekt)
        )
        st.session_state.wizard_schritt = 1
        st.session_state.auswahl_generation += 1
        st.rerun()
    if st.sidebar.button("Neues Projekt", width="stretch"):
        st.session_state.ausgewaehlte_projekt_id = None
        st.session_state.wizard_entwurf = _neuer_entwurf()
        st.session_state.wizard_schritt = 1
        st.session_state.auswahl_generation += 1
        st.rerun()
    projekt = _projekt_nach_id(projekte, neue_id)
    if projekt is not None and loesch_service is not None:
        zeige_loeschaktionen(
            projekt,
            transformations_service,
            loesch_service,
            projekt_loesch_label=projekt_loesch_label,
            projektloeschung_nachbereiten=projektloeschung_nachbereiten,
        )
    return projekt


def _schritt_problem(daten: dict[str, Any]) -> None:
    daten["bezeichnung"] = st.text_input(
        "Projektbezeichnung",
        key=_widget_initialisieren("bezeichnung", daten["bezeichnung"]),
        help="Eindeutige Bezeichnung des Projekts.",
    )
    daten["problemstellung"] = st.text_area(
        "Problemstellung",
        key=_widget_initialisieren("problemstellung", daten["problemstellung"]),
        help=PROBLEM_HILFE,
    )
    daten["systemgrenze"] = st.text_area(
        "Systemgrenze",
        key=_widget_initialisieren("systemgrenze", daten["systemgrenze"]),
        help=SYSTEMGRENZE_HILFE,
    )


def _zweck_hinzufuegen(daten: dict[str, Any], eingabe: str) -> bool:
    zweck = eingabe.strip()
    if not zweck:
        st.error("Der individuelle Untersuchungszweck darf nicht leer sein.")
        return False
    vorhandene = {
        wert.casefold()
        for wert in (*VORDEFINIERTE_UNTERSUCHUNGSZWECKE, *daten["individuelle_zwecke"])
    }
    if zweck.casefold() in vorhandene:
        st.error("Dieser Untersuchungszweck ist bereits vorhanden.")
        return False
    daten["individuelle_zwecke"].append(zweck)
    daten["zwecke"].append(zweck)
    return True


def _schritt_ziele(daten: dict[str, Any]) -> None:
    optionen = (*VORDEFINIERTE_UNTERSUCHUNGSZWECKE, *daten["individuelle_zwecke"])
    zwecke_key = _widget_initialisieren(
        "untersuchungszwecke", [zweck for zweck in daten["zwecke"] if zweck in optionen]
    )
    if (ausstehend := st.session_state.pop(f"{zwecke_key}_synchronisieren", None)) is not None:
        st.session_state[zwecke_key] = ausstehend
    daten["zwecke"] = st.multiselect(
        "Untersuchungszwecke",
        optionen,
        key=zwecke_key,
    )
    if st.checkbox(
        WEITERER_ZWECK,
        key=_widget_initialisieren("weiterer_untersuchungszweck", False),
    ):
        eingabe = st.text_input(
            "Individueller Untersuchungszweck",
            key=_widget_initialisieren("individueller_untersuchungszweck", ""),
        )
        if st.button("Untersuchungszweck hinzufügen") and _zweck_hinzufuegen(daten, eingabe):
            st.session_state[f"{zwecke_key}_synchronisieren"] = list(daten["zwecke"])
            st.rerun()
    st.markdown("### Logistische Zielgrößen")
    st.caption("Übergeordnetes Ziel: Leistungsfähigkeit des betrachteten Systems steigern")
    gewaehlt = set(daten["zielgroessen"])
    gruppenspalten = st.columns(2)
    for index, gruppe in enumerate(ZIELGRUPPEN):
        with gruppenspalten[index % 2]:
            st.markdown(f"#### {gruppe.titel}")
            for ziel in gruppe.zielgroessen:
                if st.checkbox(
                    ZIELGROESSEN_BEZEICHNUNGEN[ziel],
                    key=_widget_initialisieren(f"ziel_{ziel.value}", ziel in gewaehlt),
                ):
                    gewaehlt.add(ziel)
                else:
                    gewaehlt.discard(ziel)
    daten["zielgroessen"] = [ziel for ziel in LogistischeZielgroesse if ziel in gewaehlt]


def _auswahl(feld: str, label: str, optionen: tuple[str, ...], wert: str) -> str:
    key = _widget_initialisieren(feld, wert if wert in optionen else None)
    return fachliche_auswahl(label, optionen, key=key) or ""


def _mehrfach(
    feld: str,
    label: str,
    optionen: tuple[str, ...],
    wert: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    key = _widget_initialisieren(feld, [eintrag for eintrag in wert if eintrag in optionen])
    return tuple(st.multiselect(label, optionen, key=key))


def _produktionsauswahl(daten: dict[str, Any]) -> None:
    produktion = daten["produktion"]
    for merkmal in PRODUKTIONSSPEZIFISCHE_MERKMALE:
        aktueller_wert = produktion.get(merkmal.feldname, () if merkmal.mehrfachauswahl else "")
        produktion[merkmal.feldname] = (
            _mehrfach(
                f"produktion_{merkmal.feldname}",
                merkmal.bezeichnung,
                merkmal.auspraegungen,
                aktueller_wert,
            )
            if merkmal.mehrfachauswahl
            else _auswahl(
                f"produktion_{merkmal.feldname}",
                merkmal.bezeichnung,
                merkmal.auspraegungen,
                aktueller_wert,
            )
        )


def _intralogistikauswahl(daten: dict[str, Any]) -> None:
    intralogistik = daten["intralogistik"]
    for merkmal in INTRALOGISTIKSPEZIFISCHE_MERKMALE:
        aktueller_wert = intralogistik.get(merkmal.feldname, () if merkmal.mehrfachauswahl else "")
        intralogistik[merkmal.feldname] = (
            _mehrfach(
                f"intralogistik_{merkmal.feldname}",
                merkmal.bezeichnung,
                merkmal.auspraegungen,
                aktueller_wert,
            )
            if merkmal.mehrfachauswahl
            else _auswahl(
                f"intralogistik_{merkmal.feldname}",
                merkmal.bezeichnung,
                merkmal.auspraegungen,
                aktueller_wert,
            )
        )


def _schritt_system(daten: dict[str, Any]) -> None:
    altbestand_gemischt = daten["systemtyp"] is Systemtyp.KOMBINIERT
    if altbestand_gemischt:
        st.warning(
            "Dieses Altprojekt ist als Gemischt klassifiziert. Wählen Sie vor dem "
            "Speichern Produktion oder Intralogistik; eine automatische Umklassifikation "
            "findet nicht statt."
        )
    optionen: tuple[Systemtyp, ...] = (
        Systemtyp.PRODUKTION,
        Systemtyp.INTRALOGISTIK,
    )
    aktueller_typ = daten["systemtyp"]
    systemtyp_key = _widget_initialisieren(
        "systemtyp", aktueller_typ if aktueller_typ in optionen else None
    )
    daten["systemtyp"] = fachliche_auswahl(
        "Systemtyp",
        optionen,
        format_func=_enum_text,
        key=systemtyp_key,
    )
    gestalt_optionen = list(GestaltDerGueter)
    daten["gestalt"] = fachliche_auswahl(
        "Gestalt der Güter",
        gestalt_optionen,
        format_func=GESTALT_DER_GUETER_BEZEICHNUNGEN.__getitem__,
        key=_widget_initialisieren(
            "gestalt", daten["gestalt"] if daten["gestalt"] in gestalt_optionen else None
        ),
    )
    erzeugnis_optionen = list(Erzeugnisstrukturtyp)
    daten["erzeugnisstrukturtyp"] = fachliche_auswahl(
        "Erzeugnisstrukturtyp",
        erzeugnis_optionen,
        format_func=ERZEUGNISSTRUKTURTYP_BEZEICHNUNGEN.__getitem__,
        key=_widget_initialisieren(
            "erzeugnisstrukturtyp",
            (
                daten["erzeugnisstrukturtyp"]
                if daten["erzeugnisstrukturtyp"] in erzeugnis_optionen
                else None
            ),
        ),
    )
    kontinuitaet_optionen = list(Materialflusskontinuitaet)
    daten["kontinuitaet"] = fachliche_auswahl(
        "Kontinuität des Materialflusses",
        kontinuitaet_optionen,
        format_func=MATERIALFLUSSKONTINUITAET_BEZEICHNUNGEN.__getitem__,
        key=_widget_initialisieren(
            "kontinuitaet",
            daten["kontinuitaet"] if daten["kontinuitaet"] in kontinuitaet_optionen else None,
        ),
    )
    if daten["systemtyp"] is Systemtyp.PRODUKTION:
        _produktionsauswahl(daten)
    elif daten["systemtyp"] is Systemtyp.INTRALOGISTIK:
        _intralogistikauswahl(daten)


def _schritt_auswertungen(daten: dict[str, Any]) -> None:
    st.info(
        "Die Auswahl beschreibt den Analysebedarf. Ob eine Kennzahl berechnet werden "
        "kann, wird später anhand der verfügbaren Ereignisdaten geprüft."
    )
    kandidaten = leite_kpi_kandidaten_ab(tuple(daten["zielgroessen"]))
    gueltige_ids = {kandidat.kpi_id for kandidat in kandidaten}
    gewaehlt = set(daten["kpis"]) & gueltige_ids
    kopf = st.columns((3, 3, 3, 1))
    for spalte, titel in zip(
        kopf,
        (
            "Logistische Zielgröße",
            "Vorgeschlagene Kennzahl",
            "Gleichung",
            "Berücksichtigen",
        ),
        strict=True,
    ):
        spalte.markdown(f"**{titel}**")
    for kandidat in kandidaten:
        definition = KPI_DEFINITIONEN[kandidat.kpi_id]
        st.caption(
            "Sie haben als logistische Zielgröße "
            f"„{ZIELGROESSEN_BEZEICHNUNGEN[kandidat.zielgroesse]}“ ausgewählt. "
            f"Auf dieser Grundlage wird Ihnen die Kennzahl „{kandidat.bezeichnung}“ "
            "zur späteren manuellen Berechnung vorgeschlagen. Möchten Sie diese "
            "berücksichtigen?"
        )
        ziel, kpi, formel, auswahl = st.columns((3, 3, 3, 1))
        ziel.write(ZIELGROESSEN_BEZEICHNUNGEN[kandidat.zielgroesse])
        kpi.write(kandidat.bezeichnung)
        formel.write(definition.formel)
        if auswahl.checkbox(
            "Auswählen",
            key=_widget_initialisieren(f"kpi_{kandidat.kpi_id}", kandidat.kpi_id in gewaehlt),
            label_visibility="collapsed",
        ):
            gewaehlt.add(kandidat.kpi_id)
        else:
            gewaehlt.discard(kandidat.kpi_id)
    daten["kpis"] = [kandidat.kpi_id for kandidat in kandidaten if kandidat.kpi_id in gewaehlt]
    if daten["legacy_kpis"]:
        st.caption("Relevante Kennzahlen aus dem Altprojekt: " + ", ".join(daten["legacy_kpis"]))


def _produktionsblock(daten: dict[str, Any]) -> Produktionsklassifikation:
    erlaubte = {feld.name for feld in Produktionsklassifikation.__dataclass_fields__.values()}
    return Produktionsklassifikation(
        **{name: wert for name, wert in daten.items() if name in erlaubte}
    )


def _intralogistikblock(daten: dict[str, Any]) -> Intralogistikklassifikation:
    erlaubte = {feld.name for feld in Intralogistikklassifikation.__dataclass_fields__.values()}
    return Intralogistikklassifikation(
        **{name: wert for name, wert in daten.items() if name in erlaubte}
    )


def _auftrag(daten: dict[str, Any]) -> Untersuchungsauftrag:
    typ = daten["systemtyp"]
    if typ not in (Systemtyp.PRODUKTION, Systemtyp.INTRALOGISTIK):
        raise Domaenenfehler(
            "Wählen Sie für die Systemklassifikation Produktion oder Intralogistik."
        )
    fehlende_allgemeine = [
        label
        for label, wert in (
            ("Gestalt der Güter", daten["gestalt"]),
            ("Erzeugnisstrukturtyp", daten["erzeugnisstrukturtyp"]),
            ("Kontinuität des Materialflusses", daten["kontinuitaet"]),
        )
        if wert is None
    ]
    spezifische_merkmale = (
        PRODUKTIONSSPEZIFISCHE_MERKMALE
        if typ is Systemtyp.PRODUKTION
        else INTRALOGISTIKSPEZIFISCHE_MERKMALE
    )
    spezifische_daten = daten["produktion" if typ is Systemtyp.PRODUKTION else "intralogistik"]
    fehlende_spezifische = [
        merkmal.bezeichnung
        for merkmal in spezifische_merkmale
        if not merkmal.mehrfachauswahl and not spezifische_daten.get(merkmal.feldname)
    ]
    if fehlende_allgemeine or fehlende_spezifische:
        raise Domaenenfehler(
            "Treffen Sie eine Auswahl für: "
            + ", ".join((*fehlende_allgemeine, *fehlende_spezifische))
            + "."
        )
    alt = daten["systemklassifikation"]
    system = replace(
        alt,
        gestalt_der_gueter=daten["gestalt"],
        erzeugnisstrukturtyp=daten["erzeugnisstrukturtyp"],
        materialflusskontinuitaet=daten["kontinuitaet"],
        produktion=(
            _produktionsblock(daten["produktion"]) if typ is Systemtyp.PRODUKTION else None
        ),
        intralogistik=(
            _intralogistikblock(daten["intralogistik"]) if typ is Systemtyp.INTRALOGISTIK else None
        ),
    )
    zwecke = tuple(daten["zwecke"])
    individuelle_auswahl = tuple(
        zweck for zweck in zwecke if zweck not in VORDEFINIERTE_UNTERSUCHUNGSZWECKE
    )
    return Untersuchungsauftrag(
        problemstellung=daten["problemstellung"],
        untersuchungszweck=zwecke[0] if zwecke else "",
        systemtyp=typ,
        systemgrenze=daten["systemgrenze"],
        individuelles_ziel=individuelle_auswahl[0] if individuelle_auswahl else "",
        logistische_zielgroessen=tuple(daten["zielgroessen"]),
        ausgewaehlte_kpi_ids=tuple(daten["kpis"]),
        systemklassifikation=system,
        detaillierungsgrad=daten["detaillierung"],
        rahmenbedingungen=daten["rahmenbedingungen"],
        betrachtungszeitraum=daten["betrachtungszeitraum"],
        anmerkungen=daten["anmerkungen"],
        legacy_leistungskennzahlen=tuple(daten["legacy_kpis"]),
        migrationsbestand=daten["migrationsbestand"],
        untersuchungszwecke=zwecke,
    )


def _zusammenfassungswert(wert: str | tuple[str, ...] | list[str]) -> str:
    """Formatiert eine einzelne oder mehrfache Merkmalsausprägung."""
    if isinstance(wert, str):
        return wert or "–"
    return ", ".join(wert) if wert else "–"


def _schritt_auftrag(daten: dict[str, Any]) -> None:
    st.markdown("### Ausgaben dieses Schritts")
    st.markdown("**Untersuchungsauftrag (U)**")
    st.markdown(f"**Projektbezeichnung:** {daten['bezeichnung'] or '–'}")
    st.markdown(f"**Problemstellung:** {daten['problemstellung'] or '–'}")
    st.markdown(f"**Systemgrenzen:** {daten['systemgrenze'] or '–'}")
    vordefinierte_zwecke = [
        zweck for zweck in daten["zwecke"] if zweck in VORDEFINIERTE_UNTERSUCHUNGSZWECKE
    ]
    st.markdown("**Untersuchungszwecke:** " + _zusammenfassungswert(vordefinierte_zwecke))
    individuelle_zwecke = [
        zweck for zweck in daten["zwecke"] if zweck not in VORDEFINIERTE_UNTERSUCHUNGSZWECKE
    ]
    if individuelle_zwecke:
        st.markdown("**Individueller Untersuchungszweck:** " + ", ".join(individuelle_zwecke))
    kandidaten = {k.zielgroesse: k for k in leite_kpi_kandidaten_ab(tuple(daten["zielgroessen"]))}
    ausgewaehlte_kpis = set(daten["kpis"])
    if daten["zielgroessen"]:
        st.markdown("**Ausgewählte logistische Zielgrößen und KPI-Kandidaten:**")
        st.dataframe(
            [
                {
                    "Logistische Zielgröße": ZIELGROESSEN_BEZEICHNUNGEN[ziel],
                    "KPI-Kandidat": (
                        kandidaten[ziel].bezeichnung
                        if kandidaten[ziel].kpi_id in ausgewaehlte_kpis
                        else "–"
                    ),
                }
                for ziel in daten["zielgroessen"]
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.markdown("**Ausgewählte logistische Zielgrößen und KPI-Kandidaten:** –")

    st.markdown("**Systemprofil (S)**")
    systemtyp = daten["systemtyp"]
    st.markdown(
        "**Systemtyp:** "
        + (SYSTEMTYP_BEZEICHNUNGEN[systemtyp] if systemtyp in SYSTEMTYP_BEZEICHNUNGEN else "–")
    )
    st.markdown(
        "**Gestalt der Güter:** "
        + (GESTALT_DER_GUETER_BEZEICHNUNGEN[daten["gestalt"]] if daten["gestalt"] else "–")
    )
    st.markdown(
        "**Erzeugnisstrukturtyp:** "
        + (
            ERZEUGNISSTRUKTURTYP_BEZEICHNUNGEN[daten["erzeugnisstrukturtyp"]]
            if daten["erzeugnisstrukturtyp"]
            else "–"
        )
    )
    st.markdown(
        "**Kontinuität des Materialflusses:** "
        + (
            MATERIALFLUSSKONTINUITAET_BEZEICHNUNGEN[daten["kontinuitaet"]]
            if daten["kontinuitaet"]
            else "–"
        )
    )
    if systemtyp is Systemtyp.PRODUKTION:
        st.markdown("**Produktionsspezifische Merkmale:**")
        for merkmal in PRODUKTIONSSPEZIFISCHE_MERKMALE:
            st.markdown(
                f"**{merkmal.bezeichnung}:** "
                + _zusammenfassungswert(daten["produktion"].get(merkmal.feldname, ""))
            )
    elif systemtyp is Systemtyp.INTRALOGISTIK:
        st.markdown("**Intralogistikspezifische Merkmale:**")
        for merkmal in INTRALOGISTIKSPEZIFISCHE_MERKMALE:
            st.markdown(
                f"**{merkmal.bezeichnung}:** "
                + _zusammenfassungswert(daten["intralogistik"].get(merkmal.feldname, ""))
            )


def _speichern(
    service: ProjektService,
    projekt: Projekt | None,
    daten: dict[str, Any],
) -> Projekt | None:
    try:
        fehlende_pflichtangaben = [
            label
            for label, wert in (
                ("Projektbezeichnung", daten["bezeichnung"]),
                ("Problemstellung", daten["problemstellung"]),
                ("Systemgrenze", daten["systemgrenze"]),
                ("Untersuchungszweck", daten["zwecke"]),
            )
            if not wert
        ]
        if fehlende_pflichtangaben:
            raise Domaenenfehler(
                "Folgende Pflichtangaben müssen ausgefüllt sein: "
                + ", ".join(fehlende_pflichtangaben)
                + "."
            )
        auftrag = _auftrag(daten)
        if not auftrag.ist_vollstaendig():
            raise Domaenenfehler(
                "Problemstellung, Systemgrenze und mindestens ein "
                "Untersuchungszweck müssen ausgefüllt sein."
            )
        if projekt is None:
            gespeichert = service.projekt_anlegen(
                bezeichnung=daten["bezeichnung"],
                untersuchungsauftrag=auftrag,
            )
        else:
            gespeichert = service.projekt_aktualisieren(
                projekt.projekt_id,
                bezeichnung=daten["bezeichnung"],
                untersuchungsauftrag=auftrag,
                status=projekt.status,
                beteiligte_personen=projekt.beteiligte_personen,
            )
    except (Domaenenfehler, NichtUnterstuetzteSchemaversion) as fehler:
        st.error(str(fehler))
        return None
    except Exception:
        LOGGER.exception("Unerwarteter technischer Fehler beim Speichern von Auftrag U.")
        st.error(
            "Der Untersuchungsauftrag konnte aufgrund eines technischen Fehlers "
            "nicht gespeichert werden."
        )
        return None
    st.session_state.ausgewaehlte_projekt_id = gespeichert.projekt_id
    st.session_state.auswahl_generation += 1
    st.session_state.wizard_entwurf = _entwurf_aus_projekt(gespeichert)
    st.session_state.aktuelles_projekt_id = str(gespeichert.projekt_id)
    return gespeichert


def _navigation(
    service: ProjektService,
    projekt: Projekt | None,
    daten: dict[str, Any],
) -> None:
    schritt = st.session_state.wizard_schritt
    links, rechts = st.columns(2)
    if links.button("Zurück", disabled=schritt == 1, width="content"):
        st.session_state.wizard_schritt = schritt - 1
        st.rerun()
    if schritt < len(SCHRITTE):
        if rechts.button("Weiter", width="content"):
            st.session_state.wizard_schritt = schritt + 1
            st.rerun()
    else:
        if rechts.button(
            "Projektrahmen speichern und zu Schritt 2",
            type="primary",
            width="content",
        ):
            gespeichert = _speichern(service, projekt, daten)
            if gespeichert is not None:
                schritt_abschliessen_und_weiter(
                    aktueller_schritt=1, projekt_id=gespeichert.projekt_id
                )


def zeige_projektverwaltung(
    service: ProjektService,
    transformations_service: TransformationsService | None = None,
    loesch_service: LoeschService | None = None,
    *,
    sidebar_titel_anzeigen: bool = True,
    projekt_loesch_label: str = "Projekt löschen",
    projektloeschung_nachbereiten: Callable[[], None] | None = None,
) -> None:
    """Zeigt ausschließlich die fünf methodisch erforderlichen Unterabschnitte."""
    _initialisieren()
    try:
        projekte = service.projekte_auflisten()
        projekt = _seitenleiste(
            projekte,
            transformations_service,
            loesch_service,
            titel_anzeigen=sidebar_titel_anzeigen,
            projekt_loesch_label=projekt_loesch_label,
            projektloeschung_nachbereiten=projektloeschung_nachbereiten,
        )
    except NichtUnterstuetzteSchemaversion as fehler:
        st.error(str(fehler))
        return
    st.header("Schritt 1: Projektrahmen definieren")
    if meldung := st.session_state.pop("erfolgsmeldung", None):
        st.success(meldung)
    schritt = st.session_state.wizard_schritt
    daten = st.session_state.wizard_entwurf
    if schritt == 1:
        _schritt_problem(daten)
    elif schritt == 2:
        _schritt_ziele(daten)
    elif schritt == 3:
        _schritt_system(daten)
    elif schritt == 4:
        _schritt_auswertungen(daten)
    else:
        _schritt_auftrag(daten)
    _navigation(service, projekt, daten)
