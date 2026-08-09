"""Wizard für Schritt 1: Projektrahmen definieren mit den Ausgaben U und S."""

import logging
from dataclasses import replace
from typing import Any
from uuid import UUID

import streamlit as st

from framework_mvp.application.projekt_service import ProjektService
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
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt
from framework_mvp.ui.navigation import schritt_abschliessen_und_weiter

LOGGER = logging.getLogger(__name__)

SCHRITTE = (
    "Problem und Systemgrenze",
    "Untersuchungszweck und Logistikziele",
    "Systemklassifikation",
    "Auswertungen und KPIs",
    "Untersuchungsauftrag und Systemprofil",
)
SCHRITTE_KURZ = ("Problem", "Ziele", "System", "KPIs", "U und S")
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
        "erzeugnisstrukturtyp": Erzeugnisstrukturtyp.GENERELL,
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


def _projekt_nach_id(projekte: list[Projekt], projekt_id: UUID | None) -> Projekt | None:
    return next((projekt for projekt in projekte if projekt.projekt_id == projekt_id), None)


def _seitenleiste(projekte: list[Projekt]) -> Projekt | None:
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
    for merkmal in PRODUKTIONSSPEZIFISCHE_MERKMALE:
        aktueller_wert = produktion.get(merkmal.feldname, () if merkmal.mehrfachauswahl else "")
        produktion[merkmal.feldname] = (
            _mehrfach(merkmal.bezeichnung, merkmal.auspraegungen, aktueller_wert)
            if merkmal.mehrfachauswahl
            else _auswahl(merkmal.bezeichnung, ("", *merkmal.auspraegungen), aktueller_wert)
        )


def _intralogistikauswahl(daten: dict[str, Any]) -> None:
    intralogistik = daten["intralogistik"]
    for merkmal in INTRALOGISTIKSPEZIFISCHE_MERKMALE:
        aktueller_wert = intralogistik.get(merkmal.feldname, () if merkmal.mehrfachauswahl else "")
        intralogistik[merkmal.feldname] = (
            _mehrfach(merkmal.bezeichnung, merkmal.auspraegungen, aktueller_wert)
            if merkmal.mehrfachauswahl
            else _auswahl(merkmal.bezeichnung, ("", *merkmal.auspraegungen), aktueller_wert)
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
    daten["gestalt"] = st.selectbox(
        "Gestalt der Güter",
        list(GestaltDerGueter),
        index=list(GestaltDerGueter).index(daten["gestalt"]),
        format_func=GESTALT_DER_GUETER_BEZEICHNUNGEN.__getitem__,
    )
    daten["erzeugnisstrukturtyp"] = st.selectbox(
        "Erzeugnisstrukturtyp",
        list(Erzeugnisstrukturtyp),
        index=list(Erzeugnisstrukturtyp).index(daten["erzeugnisstrukturtyp"]),
        format_func=ERZEUGNISSTRUKTURTYP_BEZEICHNUNGEN.__getitem__,
    )
    daten["kontinuitaet"] = st.selectbox(
        "Kontinuität des Materialflusses",
        list(Materialflusskontinuitaet),
        index=list(Materialflusskontinuitaet).index(daten["kontinuitaet"]),
        format_func=MATERIALFLUSSKONTINUITAET_BEZEICHNUNGEN.__getitem__,
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
        st.caption("Logistische Zielgröße: " + ZIELGROESSEN_BEZEICHNUNGEN[kandidat.zielgroesse])
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
    st.write(f"Projektbezeichnung: {daten['bezeichnung'] or '–'}")
    st.write(f"Problemstellung: {daten['problemstellung'] or '–'}")
    st.write(f"Systemgrenzen: {daten['systemgrenze'] or '–'}")
    vordefinierte_zwecke = [
        zweck for zweck in daten["zwecke"] if zweck in VORDEFINIERTE_UNTERSUCHUNGSZWECKE
    ]
    st.write("Untersuchungszwecke: " + _zusammenfassungswert(vordefinierte_zwecke))
    individuelle_zwecke = [
        zweck for zweck in daten["zwecke"] if zweck not in VORDEFINIERTE_UNTERSUCHUNGSZWECKE
    ]
    if individuelle_zwecke:
        st.write("Individueller Untersuchungszweck: " + ", ".join(individuelle_zwecke))
    kandidaten = {k.zielgroesse: k for k in leite_kpi_kandidaten_ab(tuple(daten["zielgroessen"]))}
    ausgewaehlte_kpis = set(daten["kpis"])
    if daten["zielgroessen"]:
        st.write("Ausgewählte logistische Zielgrößen und KPI-Kandidaten:")
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
        st.write("Ausgewählte logistische Zielgrößen und KPI-Kandidaten: –")

    st.markdown("**Systemprofil (S)**")
    systemtyp = daten["systemtyp"]
    st.write(
        "Systemtyp: "
        + (SYSTEMTYP_BEZEICHNUNGEN[systemtyp] if systemtyp in SYSTEMTYP_BEZEICHNUNGEN else "–")
    )
    st.write("Gestalt der Güter: " + GESTALT_DER_GUETER_BEZEICHNUNGEN[daten["gestalt"]])
    st.write(
        "Erzeugnisstrukturtyp: " + ERZEUGNISSTRUKTURTYP_BEZEICHNUNGEN[daten["erzeugnisstrukturtyp"]]
    )
    st.write(
        "Kontinuität des Materialflusses: "
        + MATERIALFLUSSKONTINUITAET_BEZEICHNUNGEN[daten["kontinuitaet"]]
    )
    if systemtyp is Systemtyp.PRODUKTION:
        st.write("Produktionsspezifische Merkmale:")
        for merkmal in PRODUKTIONSSPEZIFISCHE_MERKMALE:
            st.write(
                f"{merkmal.bezeichnung}: "
                + _zusammenfassungswert(daten["produktion"].get(merkmal.feldname, ""))
            )
    elif systemtyp is Systemtyp.INTRALOGISTIK:
        st.write("Intralogistikspezifische Merkmale:")
        for merkmal in INTRALOGISTIKSPEZIFISCHE_MERKMALE:
            st.write(
                f"{merkmal.bezeichnung}: "
                + _zusammenfassungswert(daten["intralogistik"].get(merkmal.feldname, ""))
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
        "Projektrahmen speichern und mit ETL fortfahren",
        type="primary",
        width="content",
    ):
        _speichern_und_weiter(service, projekt, daten)


def zeige_projektverwaltung(
    service: ProjektService,
) -> None:
    """Zeigt ausschließlich die fünf methodisch erforderlichen Unterabschnitte."""
    _initialisieren()
    try:
        projekte = service.projekte_auflisten()
        projekt = _seitenleiste(projekte)
    except NichtUnterstuetzteSchemaversion as fehler:
        st.error(str(fehler))
        return
    st.header("Schritt 1: Projektrahmen definieren")
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
        _schritt_auftrag(daten)
    _navigation(service, projekt, daten)
