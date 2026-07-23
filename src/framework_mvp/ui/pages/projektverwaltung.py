"""Geführter Streamlit-Wizard für den Untersuchungsauftrag."""

import logging
from datetime import date
from typing import Any
from uuid import UUID

import streamlit as st

from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.kataloge import (
    ZIELGROESSEN_BEZEICHNUNGEN,
    ZIELGRUPPEN,
    leite_kpi_kandidaten_ab,
)
from framework_mvp.domain.models import (
    BeteiligtePerson,
    Betrachtungszeitraum,
    BetrachtungszeitraumModus,
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
from framework_mvp.ui.helpers import liste_als_mehrzeiliger_text, mehrzeiliger_text_als_liste

LOGGER = logging.getLogger(__name__)

SCHRITTE = (
    "Projekt und beteiligte Personen",
    "Problemstellung und Systemgrenze",
    "Untersuchungszweck und logistische Zielgrößen",
    "Systemklassifikation",
    "Gewünschte Auswertungen und Rahmenbedingungen",
    "Betrachtungszeitraum",
    "Zusammenfassung und Speicherung",
)
SCHRITTE_KURZ = (
    "Projekt",
    "Problem",
    "Ziele",
    "System",
    "Auswertung",
    "Zeitraum",
    "Speichern",
)
ROLLEN = (
    "Auftraggeber:in",
    "Bearbeiter:in",
    "Fachexpert:in",
    "Datenverantwortliche:r",
    "Prozessverantwortliche:r",
    "Betreuer:in",
    "Sonstige",
    "Weitere Rolle hinzufügen …",
)
UNTERSUCHUNGSZWECKE = (
    "System verstehen und transparent beschreiben",
    "System analysieren",
    "System evaluieren",
    "Varianten oder Bereiche vergleichen",
    "zukünftiges Verhalten prognostizieren",
    "Weiteren Untersuchungszweck hinzufügen …",
)


def _status_text(status: Projektstatus) -> str:
    return status.value.capitalize()


def _enum_text(wert: Any) -> str:
    return str(wert.value).replace("_", " ").capitalize()


def _neuer_entwurf() -> dict[str, Any]:
    return {
        "bezeichnung": "",
        "status": Projektstatus.ENTWURF,
        "personen": [],
        "problemstellung": "",
        "systemgrenze": "",
        "untersuchungszweck": "",
        "individuelles_ziel": "",
        "zielgroessen": [],
        "systemtyp": Systemtyp.KOMBINIERT,
        "bereich": "",
        "objekte": "",
        "gestalt": GestaltDerGueter.MISCHFORM,
        "flussform": Materialflussform.GEMISCHT,
        "kontinuitaet": Materialflusskontinuitaet.GEMISCHT,
        "kapazitaet": "",
        "input": "",
        "transformation": "",
        "output": "",
        "detaillierung": "",
        "produktion": {},
        "intralogistik": {},
        "kpis": [],
        "vertraulichkeit": "",
        "technik": "",
        "annahmen": "",
        "ausschluesse": "",
        "sonstige_rahmenbedingungen": "",
        "zeitraum_modus": BetrachtungszeitraumModus.AUS_DATEN,
        "beginn": date.today(),
        "ende": date.today(),
        "anmerkungen": "",
        "legacy_kpis": [],
    }


def _entwurf_aus_projekt(projekt: Projekt) -> dict[str, Any]:
    a = projekt.untersuchungsauftrag
    s = a.systemklassifikation
    daten = _neuer_entwurf()
    daten.update(
        {
            "bezeichnung": projekt.bezeichnung,
            "status": projekt.status,
            "personen": [
                {"vorname": p.vorname, "nachname": p.nachname, "rolle": p.rolle}
                for p in projekt.beteiligte_personen
            ],
            "problemstellung": a.problemstellung,
            "systemgrenze": a.systemgrenze,
            "untersuchungszweck": a.untersuchungszweck,
            "individuelles_ziel": a.individuelles_ziel,
            "zielgroessen": list(a.logistische_zielgroessen),
            "systemtyp": a.systemtyp,
            "bereich": s.bereich,
            "objekte": s.objekte_gueter,
            "gestalt": s.gestalt_der_gueter,
            "flussform": s.materialflussform,
            "kontinuitaet": s.materialflusskontinuitaet,
            "kapazitaet": s.kapazitaetsgrenzen,
            "input": s.input_beschreibung,
            "transformation": s.transformation_beschreibung,
            "output": s.output_beschreibung,
            "detaillierung": a.detaillierungsgrad,
            "kpis": list(a.ausgewaehlte_kpi_ids),
            "vertraulichkeit": a.rahmenbedingungen.vertraulichkeit_datenschutz,
            "technik": a.rahmenbedingungen.technische_einschraenkungen,
            "annahmen": a.rahmenbedingungen.bekannte_annahmen,
            "ausschluesse": a.rahmenbedingungen.bekannte_ausschluesse,
            "sonstige_rahmenbedingungen": a.rahmenbedingungen.sonstige,
            "zeitraum_modus": a.betrachtungszeitraum.modus,
            "beginn": a.betrachtungszeitraum.beginn or date.today(),
            "ende": a.betrachtungszeitraum.ende or date.today(),
            "anmerkungen": a.anmerkungen,
            "legacy_kpis": list(a.legacy_leistungskennzahlen),
        }
    )
    if s.produktion is not None:
        daten["produktion"] = {
            feld: getattr(s.produktion, feld) for feld in s.produktion.__dataclass_fields__
        }
    if s.intralogistik is not None:
        daten["intralogistik"] = {
            feld: getattr(s.intralogistik, feld) for feld in s.intralogistik.__dataclass_fields__
        }
    return daten


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
    return next((p for p in projekte if p.projekt_id == projekt_id), None)


def _seitenleiste(projekte: list[Projekt]) -> Projekt | None:
    st.sidebar.header("Projektverwaltung")
    aktuelle_id = st.session_state.ausgewaehlte_projekt_id
    if aktuelle_id not in {p.projekt_id for p in projekte}:
        aktuelle_id = None
    optionen = ["", *(str(p.projekt_id) for p in projekte)]
    projekttexte = {
        str(p.projekt_id): f"{p.bezeichnung} · {_status_text(p.status)}" for p in projekte
    }
    auswahl = st.sidebar.selectbox(
        "Vorhandenes Projekt auswählen",
        optionen,
        index=optionen.index("" if aktuelle_id is None else str(aktuelle_id)),
        format_func=lambda wert: "Neues Projekt" if not wert else projekttexte[wert],
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
    projekt = _projekt_nach_id(projekte, neue_id)
    if projekt:
        st.sidebar.caption(
            f"Zuletzt geändert: {projekt.geaendert_am.astimezone():%d.%m.%Y, %H:%M %Z}"
        )
    elif not projekte:
        st.sidebar.info("Noch keine Projekte vorhanden.")
    return projekt


def _kopf(schritt: int) -> None:
    zeige_kompakten_fortschritt(
        schritt=schritt,
        kurze_namen=SCHRITTE_KURZ,
        lange_namen=SCHRITTE,
    )
    st.subheader(SCHRITTE[schritt - 1])


def _schritt_1(d: dict[str, Any]) -> None:
    d["bezeichnung"] = st.text_input("Projektbezeichnung", d["bezeichnung"])
    status_als_text = st.selectbox(
        "Projektstatus",
        [status.value for status in Projektstatus],
        index=list(Projektstatus).index(d["status"]),
        format_func=lambda wert: _status_text(Projektstatus(wert)),
    )
    d["status"] = Projektstatus(status_als_text)
    st.markdown("#### Beteiligte Personen")
    entfernen: int | None = None
    for index, person in enumerate(d["personen"]):
        spalten = st.columns((2, 2, 2, 1))
        person["vorname"] = spalten[0].text_input(
            "Vorname", person["vorname"], key=f"person_v_{index}"
        )
        person["nachname"] = spalten[1].text_input(
            "Nachname", person["nachname"], key=f"person_n_{index}"
        )
        aktuelle_rolle = person["rolle"] if person["rolle"] in ROLLEN[:-1] else ROLLEN[-1]
        rolle = spalten[2].selectbox(
            "Rolle", ROLLEN, index=ROLLEN.index(aktuelle_rolle), key=f"person_r_{index}"
        )
        if rolle == ROLLEN[-1]:
            person["rolle"] = spalten[2].text_input(
                "Individuelle Rolle",
                person["rolle"] if aktuelle_rolle == ROLLEN[-1] else "",
                key=f"person_rx_{index}",
            )
        else:
            person["rolle"] = rolle
        if spalten[3].button("Entfernen", key=f"person_entfernen_{index}"):
            entfernen = index
    if entfernen is not None:
        d["personen"].pop(entfernen)
        st.rerun()
    if st.button("Person hinzufügen"):
        d["personen"].append({"vorname": "", "nachname": "", "rolle": "Sonstige"})
        st.rerun()


def _schritt_2(d: dict[str, Any]) -> None:
    d["problemstellung"] = st.text_area("Problemstellung", d["problemstellung"])
    d["systemgrenze"] = st.text_area("Systemgrenze", d["systemgrenze"])


def _schritt_3(d: dict[str, Any]) -> None:
    vorhandener = d["untersuchungszweck"]
    standard = vorhandener if vorhandener in UNTERSUCHUNGSZWECKE[:-1] else UNTERSUCHUNGSZWECKE[-1]
    zweck = st.selectbox(
        "Untersuchungszweck", UNTERSUCHUNGSZWECKE, index=UNTERSUCHUNGSZWECKE.index(standard)
    )
    d["untersuchungszweck"] = (
        st.text_input(
            "Individueller Untersuchungszweck",
            vorhandener if standard == UNTERSUCHUNGSZWECKE[-1] else "",
        )
        if zweck == UNTERSUCHUNGSZWECKE[-1]
        else zweck
    )
    d["individuelles_ziel"] = st.text_area("Weiteres individuelles Ziel", d["individuelles_ziel"])
    st.markdown("**Oberziel: Leistungsfähigkeit des betrachteten Systems steigern**")
    gewaehlt = set(d["zielgroessen"])
    for gruppe in ZIELGRUPPEN:
        with st.expander(gruppe.titel, expanded=True):
            st.caption(gruppe.beschreibung)
            for ziel in gruppe.zielgroessen:
                if st.checkbox(
                    ZIELGROESSEN_BEZEICHNUNGEN[ziel],
                    value=ziel in gewaehlt,
                    key=f"ziel_{ziel.value}",
                ):
                    gewaehlt.add(ziel)
                else:
                    gewaehlt.discard(ziel)
    d["zielgroessen"] = [ziel for ziel in LogistischeZielgroesse if ziel in gewaehlt]
    st.info(
        "Gewählt: "
        + (", ".join(ZIELGROESSEN_BEZEICHNUNGEN[z] for z in d["zielgroessen"]) or "Keine Zielgröße")
    )


def _mehrfach(
    label: str, optionen: tuple[str, ...], wert: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    return tuple(st.multiselect(label, optionen, default=[x for x in wert if x in optionen]))


def _auswahl(label: str, optionen: tuple[str, ...], wert: str) -> str:
    """Zeigt eine Textauswahl mit einem vorhandenen Wert als Standard."""
    index = optionen.index(wert) if wert in optionen else 0
    return st.selectbox(label, optionen, index=index)


def _schritt_4(d: dict[str, Any]) -> None:
    systemtyp_als_text = st.selectbox(
        "Systemtyp",
        [wert.value for wert in Systemtyp],
        index=list(Systemtyp).index(d["systemtyp"]),
        format_func=lambda wert: _enum_text(Systemtyp(wert)),
    )
    d["systemtyp"] = Systemtyp(systemtyp_als_text)
    d["bereich"] = st.text_input(
        "Betrachteter Bereich beziehungsweise Systemausschnitt", d["bereich"]
    )
    d["objekte"] = st.text_input("Betrachtete Produkte, Objekte oder Güter", d["objekte"])
    gestalt_als_text = st.selectbox(
        "Gestalt der Güter",
        [wert.value for wert in GestaltDerGueter],
        index=list(GestaltDerGueter).index(d["gestalt"]),
        format_func=lambda wert: _enum_text(GestaltDerGueter(wert)),
    )
    d["gestalt"] = GestaltDerGueter(gestalt_als_text)
    flussform_als_text = st.selectbox(
        "Form des Materialflusses",
        [wert.value for wert in Materialflussform],
        index=list(Materialflussform).index(d["flussform"]),
        format_func=lambda wert: _enum_text(Materialflussform(wert)),
    )
    d["flussform"] = Materialflussform(flussform_als_text)
    kontinuitaet_als_text = st.selectbox(
        "Kontinuität des Materialflusses",
        [wert.value for wert in Materialflusskontinuitaet],
        index=list(Materialflusskontinuitaet).index(d["kontinuitaet"]),
        format_func=lambda wert: _enum_text(Materialflusskontinuitaet(wert)),
    )
    d["kontinuitaet"] = Materialflusskontinuitaet(kontinuitaet_als_text)
    d["kapazitaet"] = st.text_area("Kapazitätsgrenzen", d["kapazitaet"])
    d["input"] = st.text_area("Beschreibung des Inputs", d["input"])
    d["transformation"] = st.text_area("Beschreibung der Transformation", d["transformation"])
    d["output"] = st.text_area("Beschreibung des Outputs", d["output"])
    d["detaillierung"] = st.text_input("Gewünschter Detaillierungsgrad", d["detaillierung"])
    if d["systemtyp"] in (Systemtyp.PRODUKTION, Systemtyp.KOMBINIERT):
        with st.expander("Produktionssystem", expanded=True):
            p = d["produktion"]
            p["auftragsabwicklungsstrategie"] = _auswahl(
                "Auftragsabwicklungsstrategie",
                (
                    "",
                    "ETO – Engineer-to-Order",
                    "CTO – Configure-to-Order",
                    "MTO – Make-to-Order",
                    "ATO – Assemble-to-Order",
                    "MTS – Make-to-Stock",
                ),
                p.get("auftragsabwicklungsstrategie", ""),
            )
            p["produktionsart"] = _auswahl(
                "Produktionsart",
                (
                    "",
                    "Einzelproduktion",
                    "Serienproduktion",
                    "Sortenproduktion",
                    "Massenproduktion",
                ),
                p.get("produktionsart", ""),
            )
            p["produktionsstueckzahl"] = _auswahl(
                "Produktionsstückzahl (Orientierungswert je Produktvariante "
                "und Betrachtungszeitraum)",
                ("", "gering (1–100 Stück)", "mittel (101–10.000 Stück)", "hoch (> 10.000 Stück)"),
                p.get("produktionsstueckzahl", ""),
            )
            if st.checkbox(
                "Abweichende Stückzahlgrenzen verwenden",
                value=p.get("stueckzahl_grenze_gering_mittel") is not None,
            ):
                grenzspalten = st.columns(2)
                p["stueckzahl_grenze_gering_mittel"] = int(
                    grenzspalten[0].number_input(
                        "Grenze gering bis mittel",
                        min_value=1,
                        value=p.get("stueckzahl_grenze_gering_mittel") or 100,
                    )
                )
                p["stueckzahl_grenze_mittel_hoch"] = int(
                    grenzspalten[1].number_input(
                        "Grenze mittel bis hoch",
                        min_value=2,
                        value=p.get("stueckzahl_grenze_mittel_hoch") or 10_000,
                    )
                )
                p["stueckzahl_einheit_zeitraum"] = st.text_input(
                    "Einheit beziehungsweise Bezugszeitraum",
                    p.get("stueckzahl_einheit_zeitraum", ""),
                )
            else:
                p["stueckzahl_grenze_gering_mittel"] = None
                p["stueckzahl_grenze_mittel_hoch"] = None
            p["produktvielfalt"] = _auswahl(
                "Produktvielfalt (Orientierungswert)",
                (
                    "",
                    "gering (1–10 Varianten)",
                    "mittel (11–100 Varianten)",
                    "hoch (> 100 Varianten)",
                ),
                p.get("produktvielfalt", ""),
            )
            if st.checkbox(
                "Abweichende Variantengrenzen verwenden",
                value=p.get("varianten_grenze_gering_mittel") is not None,
            ):
                variantenspalten = st.columns(2)
                p["varianten_grenze_gering_mittel"] = int(
                    variantenspalten[0].number_input(
                        "Variantengrenze gering bis mittel",
                        min_value=1,
                        value=p.get("varianten_grenze_gering_mittel") or 10,
                    )
                )
                p["varianten_grenze_mittel_hoch"] = int(
                    variantenspalten[1].number_input(
                        "Variantengrenze mittel bis hoch",
                        min_value=2,
                        value=p.get("varianten_grenze_mittel_hoch") or 100,
                    )
                )
            else:
                p["varianten_grenze_gering_mittel"] = None
                p["varianten_grenze_mittel_hoch"] = None
            p["organisationstyp"] = _auswahl(
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
                p.get("organisationstyp", ""),
            )
            p["anzahl_arbeitsgaenge"] = st.radio(
                "Anzahl der Arbeitsgänge", ("einstufig", "mehrstufig")
            )
            p["produktionsfaktoren"] = _mehrfach(
                "Produktionsfaktoren",
                ("materialintensiv", "arbeitsintensiv", "informationsintensiv", "anlagenintensiv"),
                p.get("produktionsfaktoren", ()),
            )
            basis = (
                "Maschinen",
                "Anlagen",
                "Arbeitsplätze",
                "Personal",
                "Werkzeuge",
                "Fördertechnik",
                "Lager- und Pufferplätze",
                "Informationssysteme",
            )
            p["ressourcen"] = (
                *_mehrfach("Eingesetzte Produktionsressourcen", basis, p.get("ressourcen", ())),
                *mehrzeiliger_text_als_liste(
                    st.text_area("Weitere Produktionsressourcen (eine pro Zeile)")
                ),
            )
            st.caption(
                "Die Grenzen sind Orientierungswerte je Produktvariante und Betrachtungszeitraum."
            )
    if d["systemtyp"] in (Systemtyp.INTRALOGISTIK, Systemtyp.KOMBINIERT):
        with st.expander("Intralogistiksystem", expanded=True):
            i = d["intralogistik"]
            i["hauptfunktionen"] = _mehrfach(
                "Hauptfunktionen",
                (
                    "Transport",
                    "Lagerung",
                    "Umschlag",
                    "Kommissionierung",
                    "Bereitstellung",
                    "innerbetriebliche Versorgung",
                ),
                i.get("hauptfunktionen", ()),
            )
            i["ladungstraeger"] = mehrzeiliger_text_als_liste(
                st.text_area(
                    "Material- oder Ladungsträger (eine Angabe pro Zeile)",
                    liste_als_mehrzeiliger_text(i.get("ladungstraeger", ())),
                )
            )
            i["quellen_und_senken"] = st.text_area(
                "Quellen und Senken des Materialflusses", i.get("quellen_und_senken", "")
            )
            i["transportorganisation"] = st.selectbox(
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
            )
            i["lagerprinzip"] = st.selectbox(
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
            )
            basis = (
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
            )
            i["ressourcen"] = (
                *_mehrfach("Eingesetzte Intralogistikressourcen", basis, i.get("ressourcen", ())),
                *mehrzeiliger_text_als_liste(
                    st.text_area("Weitere Intralogistikressourcen (eine pro Zeile)")
                ),
            )
            i["puffer_und_lagerbereiche"] = st.text_area(
                "Puffer- und Lagerbereiche", i.get("puffer_und_lagerbereiche", "")
            )
            i["bekannte_kapazitaetsgrenzen"] = st.text_area(
                "Bekannte Kapazitätsgrenzen der Intralogistik",
                i.get("bekannte_kapazitaetsgrenzen", ""),
            )


def _schritt_5(d: dict[str, Any]) -> None:
    kandidaten = leite_kpi_kandidaten_ab(tuple(d["zielgroessen"]))
    erlaubte = {k.kpi_id for k in kandidaten}
    gewaehlt = {k for k in d["kpis"] if k in erlaubte}
    st.markdown("#### KPI-Kandidaten")
    for kandidat in kandidaten:
        if st.checkbox(
            kandidat.bezeichnung, kandidat.kpi_id in gewaehlt, key=f"kpi_{kandidat.kpi_id}"
        ):
            gewaehlt.add(kandidat.kpi_id)
        else:
            gewaehlt.discard(kandidat.kpi_id)
        st.caption(f"Benötigte Daten: {kandidat.voraussetzungen}")
    d["kpis"] = [k.kpi_id for k in kandidaten if k.kpi_id in gewaehlt]
    st.info("Die tatsächliche Ableitbarkeit wird nach dem Datenimport geprüft.")
    d["vertraulichkeit"] = st.text_area("Vertraulichkeit und Datenschutz", d["vertraulichkeit"])
    d["technik"] = st.text_area("Technische Einschränkungen", d["technik"])
    d["annahmen"] = st.text_area("Bekannte Annahmen", d["annahmen"])
    d["ausschluesse"] = st.text_area("Bekannte Ausschlüsse", d["ausschluesse"])
    d["sonstige_rahmenbedingungen"] = st.text_area(
        "Sonstige fachliche Rahmenbedingungen", d["sonstige_rahmenbedingungen"]
    )


def _schritt_6(d: dict[str, Any]) -> None:
    modus_als_text = st.radio(
        "Modus des Betrachtungszeitraums",
        [wert.value for wert in BetrachtungszeitraumModus],
        index=list(BetrachtungszeitraumModus).index(d["zeitraum_modus"]),
        format_func=lambda wert: _enum_text(BetrachtungszeitraumModus(wert)),
    )
    d["zeitraum_modus"] = BetrachtungszeitraumModus(modus_als_text)
    if d["zeitraum_modus"] is BetrachtungszeitraumModus.AUS_DATEN:
        st.info(
            "Der Betrachtungszeitraum wird nach dem Datenimport aus dem frühesten und "
            "spätesten relevanten Zeitstempel bestimmt."
        )
    elif d["zeitraum_modus"] is BetrachtungszeitraumModus.MANUELL:
        d["beginn"] = st.date_input("Beginn", d["beginn"])
        d["ende"] = st.date_input("Ende", d["ende"])
    else:
        st.info("Der Betrachtungszeitraum wird zu einem späteren Zeitpunkt festgelegt.")


def _schritt_7(d: dict[str, Any]) -> None:
    st.markdown(f"**Projekt:** {d['bezeichnung'] or '–'}")
    st.markdown(f"**Problemstellung:** {d['problemstellung'] or '–'}")
    st.markdown(f"**Systemgrenze:** {d['systemgrenze'] or '–'}")
    st.markdown(f"**Untersuchungszweck:** {d['untersuchungszweck'] or '–'}")
    st.markdown(
        "**Zielgrößen:** "
        + (", ".join(ZIELGROESSEN_BEZEICHNUNGEN[z] for z in d["zielgroessen"]) or "–")
    )
    st.markdown(f"**Systemtyp:** {_enum_text(d['systemtyp'])}")
    st.markdown(f"**Ausgewählte KPI-Kandidaten:** {len(d['kpis'])}")
    d["anmerkungen"] = st.text_area("Anmerkungen", d["anmerkungen"])
    vorschau = _auftrag(d)
    if vorschau.ist_vollstaendig():
        st.success("Untersuchungsauftrag vollständig")
    else:
        st.warning(
            "Untersuchungsauftrag unvollständig. Erforderlich sind Problemstellung, "
            "Systemgrenze und Untersuchungszweck."
        )


def _produktionsblock(daten: dict[str, Any]) -> Produktionsklassifikation:
    erlaubte = {f.name for f in Produktionsklassifikation.__dataclass_fields__.values()}
    return Produktionsklassifikation(**{k: v for k, v in daten.items() if k in erlaubte})


def _intralogistikblock(daten: dict[str, Any]) -> Intralogistikklassifikation:
    erlaubte = {f.name for f in Intralogistikklassifikation.__dataclass_fields__.values()}
    return Intralogistikklassifikation(**{k: v for k, v in daten.items() if k in erlaubte})


def _auftrag(d: dict[str, Any]) -> Untersuchungsauftrag:
    typ = d["systemtyp"]
    system = Systemklassifikation(
        d["bereich"],
        d["objekte"],
        d["gestalt"],
        d["flussform"],
        d["kontinuitaet"],
        d["kapazitaet"],
        d["input"],
        d["transformation"],
        d["output"],
        _produktionsblock(d["produktion"])
        if typ in (Systemtyp.PRODUKTION, Systemtyp.KOMBINIERT)
        else None,
        _intralogistikblock(d["intralogistik"])
        if typ in (Systemtyp.INTRALOGISTIK, Systemtyp.KOMBINIERT)
        else None,
    )
    modus = d["zeitraum_modus"]
    zeitraum = Betrachtungszeitraum(
        modus,
        d["beginn"] if modus is BetrachtungszeitraumModus.MANUELL else None,
        d["ende"] if modus is BetrachtungszeitraumModus.MANUELL else None,
    )
    return Untersuchungsauftrag(
        d["problemstellung"],
        d["untersuchungszweck"],
        typ,
        d["systemgrenze"],
        d["individuelles_ziel"],
        tuple(d["zielgroessen"]),
        tuple(d["kpis"]),
        system,
        d["detaillierung"],
        Rahmenbedingungen(
            d["vertraulichkeit"],
            d["technik"],
            d["annahmen"],
            d["ausschluesse"],
            d["sonstige_rahmenbedingungen"],
        ),
        zeitraum,
        d["anmerkungen"],
        tuple(d["legacy_kpis"]),
    )


def _speichern(
    service: ProjektService, projekt: Projekt | None, d: dict[str, Any], als_entwurf: bool
) -> None:
    try:
        personen = tuple(BeteiligtePerson(**person) for person in d["personen"])
        status = Projektstatus.ENTWURF if als_entwurf else d["status"]
        if projekt is None:
            gespeichert = service.projekt_anlegen(
                bezeichnung=d["bezeichnung"],
                untersuchungsauftrag=_auftrag(d),
                status=status,
                beteiligte_personen=personen,
            )
        else:
            gespeichert = service.projekt_aktualisieren(
                projekt.projekt_id,
                bezeichnung=d["bezeichnung"],
                untersuchungsauftrag=_auftrag(d),
                status=status,
                beteiligte_personen=personen,
            )
    except Domaenenfehler as fehler:
        st.error(str(fehler))
        return
    except NichtUnterstuetzteSchemaversion as fehler:
        st.error(str(fehler))
        return
    except Exception:
        LOGGER.exception("Unerwarteter technischer Fehler beim Speichern des Projekts.")
        st.error("Das Projekt konnte aufgrund eines technischen Fehlers nicht gespeichert werden.")
        return
    st.session_state.ausgewaehlte_projekt_id = gespeichert.projekt_id
    st.session_state.erfolgsmeldung = (
        "Der Entwurf wurde gespeichert."
        if als_entwurf
        else "Das Projekt wurde erfolgreich gespeichert."
    )
    st.session_state.auswahl_generation += 1
    st.rerun()


def _navigation(
    service: ProjektService, projekt: Projekt | None, d: dict[str, Any], schritt: int
) -> None:
    links, mitte, rechts = st.columns(3)
    if links.button("Zurück", disabled=schritt == 1, width="stretch"):
        st.session_state.wizard_schritt = schritt - 1
        st.rerun()
    if mitte.button("Entwurf speichern", width="stretch"):
        _speichern(service, projekt, d, True)
    if schritt < 7:
        if rechts.button("Weiter", width="stretch"):
            st.session_state.wizard_schritt = schritt + 1
            st.rerun()
    elif rechts.button("Projekt speichern", type="primary", width="stretch"):
        _speichern(service, projekt, d, False)


def zeige_projektverwaltung(service: ProjektService) -> None:
    """Zeigt Projektwahl, Fortschritt und den aktuellen Wizard-Schritt."""
    _initialisieren()
    if meldung := st.session_state.pop("erfolgsmeldung", None):
        st.success(meldung)
    try:
        projekte = service.projekte_auflisten()
    except NichtUnterstuetzteSchemaversion as fehler:
        st.error(str(fehler))
        return
    except Exception:
        LOGGER.exception("Unerwarteter technischer Fehler beim Laden der Projekte.")
        st.error("Die Projekte konnten aufgrund eines technischen Fehlers nicht geladen werden.")
        return
    projekt = _seitenleiste(projekte)
    d = st.session_state.wizard_entwurf
    schritt = st.session_state.wizard_schritt
    _kopf(schritt)
    (_schritt_1, _schritt_2, _schritt_3, _schritt_4, _schritt_5, _schritt_6, _schritt_7)[
        schritt - 1
    ](d)
    _navigation(service, projekt, d, schritt)
