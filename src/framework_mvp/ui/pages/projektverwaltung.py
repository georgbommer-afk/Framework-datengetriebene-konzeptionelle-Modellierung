"""Kompakter Wizard für Untersuchungsauftrag U und Datenquellenkatalog Q."""

import logging
from dataclasses import replace
from typing import Any
from uuid import UUID

import streamlit as st

from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.kataloge import (
    ZIELGROESSEN_BEZEICHNUNGEN,
    leite_kpi_kandidaten_ab,
)
from framework_mvp.domain.models import (
    Betrachtungszeitraum,
    GestaltDerGueter,
    Intralogistikklassifikation,
    LogistischeZielgroesse,
    Materialflussform,
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
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt
from framework_mvp.ui.navigation import schritt_abschliessen_und_weiter

LOGGER = logging.getLogger(__name__)

SCHRITTE = (
    "Problem und Systemgrenze",
    "Untersuchungszweck und Logistikziele",
    "Systemklassifikation",
    "Auswertungen und KPIs",
    "Untersuchungsauftrag",
)
SCHRITTE_KURZ = ("Problem", "Ziele", "System", "Auswertung", "Auftrag")
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
        "gestalt": GestaltDerGueter.MISCHFORM,
        "flussform": Materialflussform.GEMISCHT,
        "kontinuitaet": Materialflusskontinuitaet.GEMISCHT,
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
        "flussform": system.materialflussform,
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


def _projekt_nach_id(projekte: list[Projekt], projekt_id: UUID | None) -> Projekt | None:
    return next((projekt for projekt in projekte if projekt.projekt_id == projekt_id), None)


def _seitenleiste(projekte: list[Projekt]) -> Projekt | None:
    st.sidebar.header("Projekt und Untersuchungsauftrag")
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
        st.rerun()
    if st.sidebar.button("Neues Projekt", width="stretch"):
        st.session_state.ausgewaehlte_projekt_id = None
        st.session_state.wizard_entwurf = _neuer_entwurf()
        st.session_state.wizard_schritt = 1
        st.session_state.auswahl_generation += 1
        st.rerun()
    return _projekt_nach_id(projekte, neue_id)


def _kopf(schritt: int) -> None:
    zeige_kompakten_fortschritt(
        schritt=schritt,
        kurze_namen=SCHRITTE_KURZ,
        lange_namen=SCHRITTE,
    )


def _schritt_problem(daten: dict[str, Any]) -> None:
    daten["bezeichnung"] = st.text_input(
        "Projektbezeichnung", daten["bezeichnung"], help="Eindeutige Bezeichnung des Projekts."
    )
    daten["problemstellung"] = st.text_area(
        "Problemstellung",
        daten["problemstellung"],
        help=PROBLEM_HILFE,
    )
    daten["systemgrenze"] = st.text_area(
        "Systemgrenze",
        daten["systemgrenze"],
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
    daten["zwecke"] = st.multiselect(
        "Untersuchungszwecke",
        optionen,
        default=[zweck for zweck in daten["zwecke"] if zweck in optionen],
    )
    if st.checkbox(WEITERER_ZWECK):
        eingabe = st.text_input("Individueller Untersuchungszweck")
        if st.button("Untersuchungszweck hinzufügen") and _zweck_hinzufuegen(daten, eingabe):
            st.rerun()
    st.markdown("### Logistikziele")
    st.caption("Übergeordnetes Ziel: Leistungsfähigkeit des betrachteten Systems steigern")
    gewaehlt = set(daten["zielgroessen"])
    spalten = st.columns(3)
    for index, ziel in enumerate(LogistischeZielgroesse):
        if spalten[index % 3].checkbox(
            ZIELGROESSEN_BEZEICHNUNGEN[ziel],
            value=ziel in gewaehlt,
            key=f"ziel_{ziel.value}",
        ):
            gewaehlt.add(ziel)
        else:
            gewaehlt.discard(ziel)
    daten["zielgroessen"] = [ziel for ziel in LogistischeZielgroesse if ziel in gewaehlt]


def _auswahl(label: str, optionen: tuple[str, ...], wert: str) -> str:
    index = optionen.index(wert) if wert in optionen else 0
    return st.selectbox(label, optionen, index=index)


def _mehrfach(
    label: str, optionen: tuple[str, ...], wert: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    return tuple(
        st.multiselect(
            label, optionen, default=[eintrag for eintrag in wert if eintrag in optionen]
        )
    )


def _produktionsauswahl(daten: dict[str, Any]) -> None:
    produktion = daten["produktion"]
    produktion["auftragsabwicklungsstrategie"] = _auswahl(
        "Auftragsabwicklungsstrategie",
        (
            "",
            "ETO – Engineer-to-Order",
            "CTO – Configure-to-Order",
            "MTO – Make-to-Order",
            "ATO – Assemble-to-Order",
            "MTS – Make-to-Stock",
        ),
        produktion.get("auftragsabwicklungsstrategie", ""),
    )
    produktion["produktionsart"] = _auswahl(
        "Produktionsart",
        ("", "Einzelproduktion", "Serienproduktion", "Sortenproduktion", "Massenproduktion"),
        produktion.get("produktionsart", ""),
    )
    produktion["produktionsstueckzahl"] = _auswahl(
        "Produktionsstückzahl",
        ("", "gering (1–100 Stück)", "mittel (101–10.000 Stück)", "hoch (> 10.000 Stück)"),
        produktion.get("produktionsstueckzahl", ""),
    )
    produktion["produktvielfalt"] = _auswahl(
        "Produktvielfalt",
        ("", "gering (1–10 Varianten)", "mittel (11–100 Varianten)", "hoch (> 100 Varianten)"),
        produktion.get("produktvielfalt", ""),
    )
    produktion["organisationstyp"] = _auswahl(
        "Organisationstyp",
        (
            "",
            "Werkstattfertigung",
            "Gruppenfertigung",
            "Inselfertigung",
            "Reihenproduktion",
            "Fließproduktion",
            "Fließband beziehungsweise Transferstraße",
            "flexible Fertigung",
            "sonstiger Organisationstyp",
        ),
        produktion.get("organisationstyp", ""),
    )
    produktion["anzahl_arbeitsgaenge"] = _auswahl(
        "Anzahl der Arbeitsgänge",
        ("", "einstufig", "mehrstufig"),
        produktion.get("anzahl_arbeitsgaenge", ""),
    )
    produktion["produktionsfaktoren"] = _mehrfach(
        "Produktionsfaktoren",
        ("materialintensiv", "arbeitsintensiv", "informationsintensiv", "anlagenintensiv"),
        produktion.get("produktionsfaktoren", ()),
    )
    produktion["ressourcen"] = _mehrfach(
        "Eingesetzte Produktionsressourcen",
        (
            "Maschinen",
            "Anlagen",
            "Arbeitsplätze",
            "Personal",
            "Werkzeuge",
            "Fördertechnik",
            "Lager- und Pufferplätze",
            "Informationssysteme",
        ),
        produktion.get("ressourcen", ()),
    )


def _intralogistikauswahl(daten: dict[str, Any]) -> None:
    intralogistik = daten["intralogistik"]
    intralogistik["hauptfunktionen"] = _mehrfach(
        "Hauptfunktionen",
        (
            "Transport",
            "Lagerung",
            "Umschlag",
            "Kommissionierung",
            "Bereitstellung",
            "innerbetriebliche Versorgung",
        ),
        intralogistik.get("hauptfunktionen", ()),
    )
    intralogistik["transportorganisation"] = _auswahl(
        "Transportorganisation",
        (
            "",
            "Direkttransport",
            "Sammeltransport",
            "Linien- beziehungsweise Routenzugverkehr",
            "bedarfsgesteuerter Transport",
            "kontinuierliche Fördertechnik",
            "sonstige Organisation",
        ),
        intralogistik.get("transportorganisation", ""),
    )
    intralogistik["lagerprinzip"] = _auswahl(
        "Lager- beziehungsweise Bereitstellungsprinzip",
        (
            "",
            "feste Lagerplatzzuordnung",
            "chaotische Lagerung",
            "FIFO",
            "LIFO",
            "Kanban",
            "Supermarktprinzip",
            "Just-in-Time",
            "Just-in-Sequence",
            "sonstiges Prinzip",
        ),
        intralogistik.get("lagerprinzip", ""),
    )
    intralogistik["ressourcen"] = _mehrfach(
        "Eingesetzte Intralogistikressourcen",
        (
            "manuelle Transporte",
            "Stapler",
            "Routenzug",
            "Kran",
            "stationäre Fördertechnik",
            "FTS",
            "AMR",
            "Regalbediengerät",
            "Lager- und Pufferplätze",
            "Personal",
            "Informationssysteme",
        ),
        intralogistik.get("ressourcen", ()),
    )


def _schritt_system(daten: dict[str, Any]) -> None:
    altbestand_gemischt = daten["systemtyp"] is Systemtyp.KOMBINIERT
    if altbestand_gemischt:
        st.warning(
            "Dieses Altprojekt ist als Gemischt klassifiziert. Wählen Sie vor dem "
            "Speichern Produktion oder Intralogistik; eine automatische Umklassifikation "
            "findet nicht statt."
        )
    optionen: tuple[Systemtyp | None, ...] = (
        None,
        Systemtyp.PRODUKTION,
        Systemtyp.INTRALOGISTIK,
    )
    aktueller_typ = daten["systemtyp"]
    index = optionen.index(aktueller_typ) if aktueller_typ in optionen else 0
    daten["systemtyp"] = st.selectbox(
        "Systemtyp",
        optionen,
        index=index,
        format_func=lambda wert: "Bitte auswählen" if wert is None else _enum_text(wert),
    )
    system = daten["systemklassifikation"]
    daten["gestalt"] = st.selectbox(
        "Gestalt der Güter",
        list(GestaltDerGueter),
        index=list(GestaltDerGueter).index(system.gestalt_der_gueter),
        format_func=_enum_text,
    )
    daten["flussform"] = st.selectbox(
        "Art des Materialflusses",
        list(Materialflussform),
        index=list(Materialflussform).index(system.materialflussform),
        format_func=_enum_text,
    )
    daten["kontinuitaet"] = st.selectbox(
        "Kontinuität des Materialflusses",
        list(Materialflusskontinuitaet),
        index=list(Materialflusskontinuitaet).index(system.materialflusskontinuitaet),
        format_func=_enum_text,
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
    gewaehlt = set(daten["kpis"])
    for kandidat in kandidaten:
        if st.checkbox(
            kandidat.bezeichnung,
            kandidat.kpi_id in gewaehlt,
            key=f"kpi_{kandidat.kpi_id}",
        ):
            gewaehlt.add(kandidat.kpi_id)
        else:
            gewaehlt.discard(kandidat.kpi_id)
        st.caption(kandidat.beschreibung)
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
    alt = daten["systemklassifikation"]
    system = replace(
        alt,
        gestalt_der_gueter=daten["gestalt"],
        materialflussform=daten["flussform"],
        materialflusskontinuitaet=daten["kontinuitaet"],
        produktion=(
            _produktionsblock(daten["produktion"])
            if typ is Systemtyp.PRODUKTION
            else alt.produktion
        ),
        intralogistik=(
            _intralogistikblock(daten["intralogistik"])
            if typ is Systemtyp.INTRALOGISTIK
            else alt.intralogistik
        ),
    )
    zwecke = tuple(daten["zwecke"])
    return Untersuchungsauftrag(
        problemstellung=daten["problemstellung"],
        untersuchungszweck=zwecke[0] if zwecke else "",
        systemtyp=typ,
        systemgrenze=daten["systemgrenze"],
        individuelles_ziel="",
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


def _zeitraum_text(zeitraum: Betrachtungszeitraum) -> str:
    if zeitraum.beginn is None or zeitraum.ende is None:
        return "Noch nicht aus den Ereignisdaten ermittelt"
    return f"{zeitraum.beginn:%d.%m.%Y} bis {zeitraum.ende:%d.%m.%Y}"


def _schritt_auftrag(
    daten: dict[str, Any],
    projekt: Projekt | None,
    datenquelle_service: DatenquelleService,
) -> None:
    st.markdown("### Ausgaben dieses Schritts")
    st.markdown("**Untersuchungsauftrag U**")
    st.write(f"Problemstellung: {daten['problemstellung'] or '–'}")
    st.write(f"Systemgrenze: {daten['systemgrenze'] or '–'}")
    st.write("Untersuchungszwecke: " + (", ".join(daten["zwecke"]) if daten["zwecke"] else "–"))
    st.write(
        "Logistikziele: "
        + (
            ", ".join(ZIELGROESSEN_BEZEICHNUNGEN[ziel] for ziel in daten["zielgroessen"])
            if daten["zielgroessen"]
            else "–"
        )
    )
    st.write(
        "Systemklassifikation: "
        + (
            _enum_text(daten["systemtyp"])
            if daten["systemtyp"] in (Systemtyp.PRODUKTION, Systemtyp.INTRALOGISTIK)
            else "Bitte festlegen"
        )
    )
    st.write("Betrachtungszeitraum: " + _zeitraum_text(daten["betrachtungszeitraum"]))
    st.markdown("**Datenquellenkatalog Q**")
    quellen = (
        [] if projekt is None else datenquelle_service.datenquellen_fuer_projekt(projekt.projekt_id)
    )
    if not quellen:
        st.info("Datenquellenkatalog Q: Noch keine Datenquelle erfasst")
    else:
        st.dataframe(
            [
                {
                    "Bezeichnung": quelle.bezeichnung,
                    "Quellsystemtyp": quelle.quellsystemtyp.value,
                    "Quellenart": quelle.quellenart.value,
                }
                for quelle in quellen
            ],
            hide_index=True,
            width="stretch",
        )


def _speichern_und_weiter(
    service: ProjektService,
    projekt: Projekt | None,
    daten: dict[str, Any],
) -> None:
    try:
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
        return
    except Exception:
        LOGGER.exception("Unerwarteter technischer Fehler beim Speichern von Auftrag U.")
        st.error(
            "Der Untersuchungsauftrag konnte aufgrund eines technischen Fehlers "
            "nicht gespeichert werden."
        )
        return
    st.session_state.ausgewaehlte_projekt_id = gespeichert.projekt_id
    st.session_state.wizard_entwurf = _entwurf_aus_projekt(gespeichert)
    schritt_abschliessen_und_weiter(
        aktueller_schritt=1,
        projekt_id=gespeichert.projekt_id,
    )


def _navigation(
    service: ProjektService,
    projekt: Projekt | None,
    daten: dict[str, Any],
    datenquelle_service: DatenquelleService,
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
    elif rechts.button(
        "Untersuchungsauftrag speichern und mit ETL fortfahren",
        type="primary",
        width="content",
    ):
        _speichern_und_weiter(service, projekt, daten)


def zeige_projektverwaltung(
    service: ProjektService,
    datenquelle_service: DatenquelleService,
) -> None:
    """Zeigt ausschließlich die fünf methodisch erforderlichen Unterabschnitte."""
    _initialisieren()
    try:
        projekte = service.projekte_auflisten()
        projekt = _seitenleiste(projekte)
    except NichtUnterstuetzteSchemaversion as fehler:
        st.error(str(fehler))
        return
    st.header("1 Projekt und Untersuchungsauftrag")
    if meldung := st.session_state.pop("erfolgsmeldung", None):
        st.success(meldung)
    schritt = st.session_state.wizard_schritt
    _kopf(schritt)
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
        _schritt_auftrag(daten, projekt, datenquelle_service)
    _navigation(service, projekt, daten, datenquelle_service)
