"""Framework-Schritt 9: ausschließlich O ergänzen und das Gesamtmodell validieren."""

import json
from collections import Counter, defaultdict
from typing import Any
from uuid import UUID, uuid4

import streamlit as st

from framework_mvp.application.modellvalidierung_service import (
    ModellvalidierungService,
    Validierungsarbeitsfassung,
)
from framework_mvp.application.modellvalidierung_struktur import (
    DARSTELLUNGSFORMEN,
    DATENZUSTAENDE,
    DETAILBEHANDLUNGEN,
    modellbezugsoptionen,
    validiere_strukturierten_inhalt,
    wartestellenhinweise,
)
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    BehandlungOffenerEintrag,
    Gesamtvalidierungsstatus,
    ModellbestandteilId,
    Offenheitsentscheidung,
    Offenheitskategorie,
)
from framework_mvp.formatierung import formatiere_fachwert
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.navigation import (
    framework_bereich_oeffnen,
    schritt_abschliessen_und_weiter,
)

_NICHT_BEHANDELT = "noch_nicht_behandelt"
_ENTSCHEIDUNGSTEXTE = {
    _NICHT_BEHANDELT: "Noch nicht behandelt",
    Offenheitsentscheidung.BESTAETIGT.value: "Vorhandene Information bestätigen",
    Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST.value: "Ergänzen / konkretisieren",
    Offenheitsentscheidung.NICHT_BEKANNT_ODER_BESTIMMBAR.value: (
        "Nicht bekannt / nicht bestimmbar"
    ),
    Offenheitsentscheidung.NICHT_ANWENDBAR.value: "Nicht anwendbar",
}
_BEZUGSTEXTE = {
    "gesamtsystem": "Gesamtsystem",
    "entitaet": "Entität",
    "aktivitaet": "Aktivität",
    "warteschlange": "Warteschlange",
    "ressource": "Ressource",
}


def _aktive_ids() -> tuple[UUID, UUID, UUID, UUID] | None:
    try:
        return (
            UUID(str(st.session_state.get("aktuelles_projekt_id"))),
            UUID(str(st.session_state.get("aktuelle_modellableitungs_id"))),
            UUID(str(st.session_state.get("aktuelle_k_id"))),
            UUID(str(st.session_state.get("aktuelle_o_id"))),
        )
    except (TypeError, ValueError, AttributeError):
        return None


def _fachwert(wert: Any) -> str:
    if isinstance(wert, str):
        return wert
    if isinstance(wert, (list, tuple)) and all(
        isinstance(eintrag, (str, int, float)) for eintrag in wert
    ):
        return ", ".join(str(formatiere_fachwert(eintrag)) for eintrag in wert)
    return json.dumps(wert, ensure_ascii=False, default=str)


def _bestandteile_anzeigen(k: dict[str, Any], o: dict[str, Any], *, projekt_id: UUID) -> None:
    st.subheader("1. Vorläufiges Modell K")
    st.caption(
        "K bleibt schreibgeschützt. In Schritt 9 werden nur die in O referenzierten "
        "Einzelpunkte ergänzt oder überprüft."
    )
    offene_anzahl: dict[str, int] = defaultdict(int)
    for offen in o.get("offene_eintraege", []):
        offene_anzahl[str(offen["bestandteil_id"])] += 1
    st.dataframe(
        [
            {
                "Modellbestandteil": wert["bezeichnung"],
                "Status in K": str(wert["status"]).replace("_", " ").capitalize(),
                "Sichere Informationen": len(wert.get("informationen", [])),
                "Offene Punkte in O": offene_anzahl[wert["bestandteil_id"]],
            }
            for wert in k["modellbestandteile"]
        ],
        hide_index=True,
        width="stretch",
    )
    with st.expander("Bereits zugeordnete Modellbestandteile anzeigen", expanded=False):
        bezeichnungen = {wert["bestandteil_id"]: wert for wert in k["modellbestandteile"]}
        auswahl = st.selectbox(
            "Modellbestandteil anzeigen",
            list(bezeichnungen),
            format_func=lambda wert: bezeichnungen[wert]["bezeichnung"],
            key="schritt9_k_detailauswahl",
        )
        bestandteil = bezeichnungen[auswahl]
        for information in bestandteil.get("informationen", []):
            st.write(_fachwert(information.get("wert")))
            st.caption(
                f"Quelle {information.get('herkunftsartefakt', '–')} · "
                f"{information.get('strukturreferenz', '–')}"
            )
        if not bestandteil.get("informationen"):
            st.info("Keine sicher abgeleitete Information in K.")
    if st.button("Zurück zu Schritt 8 und als fachlich unsicher kennzeichnen"):
        framework_bereich_oeffnen(schritt=8, projekt_id=projekt_id)


def _technische_details(basis: Any, arbeitsfassung: Validierungsarbeitsfassung | None) -> None:
    with st.expander("Technische Details", expanded=False):
        details = {
            "modellableitungs_id": str(basis.ableitung.modellableitungs_id),
            "projekt_id": str(basis.ableitung.projekt_id),
            "k_id": str(basis.ableitung.k_id),
            "k_sha256": basis.ableitung.k_sha256,
            "o_id": str(basis.ableitung.o_id),
            "o_sha256": basis.ableitung.o_sha256,
            "eingabefingerabdruck": basis.eingabefingerabdruck,
        }
        if arbeitsfassung is not None:
            details["entscheidungsfingerabdruck"] = arbeitsfassung.entscheidungsfingerabdruck
        st.json(details, expanded=False)


def _entscheidungsoptionen(kategorie: Offenheitskategorie) -> list[str]:
    optionen = [
        _NICHT_BEHANDELT,
        Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST.value,
        Offenheitsentscheidung.NICHT_BEKANNT_ODER_BESTIMMBAR.value,
        Offenheitsentscheidung.NICHT_ANWENDBAR.value,
    ]
    if kategorie is Offenheitskategorie.FACHLICH_UNSICHER:
        optionen.insert(1, Offenheitsentscheidung.BESTAETIGT.value)
    return optionen


def _zeilen(text: str) -> list[str]:
    return list(dict.fromkeys(zeile.strip() for zeile in text.splitlines() if zeile.strip()))


def _bezug_editor(k: dict[str, Any], *, key: str, gesamtsystem: bool) -> dict[str, str]:
    optionen = modellbezugsoptionen(k)
    typen = [
        wert
        for wert in _BEZUGSTEXTE
        if (wert == "gesamtsystem" and gesamtsystem) or optionen.fuer(wert)
    ]
    if not typen:
        st.warning("K enthält kein geeignetes vorhandenes Modellelement für diesen Bezug.")
        return {"bezugstyp": "", "konkreter_bezug": ""}
    bezugstyp = st.selectbox(
        "Bezugstyp",
        typen,
        format_func=lambda wert: _BEZUGSTEXTE[str(wert)],
        key=f"{key}_bezugstyp",
    )
    konkreter_bezug = ""
    if bezugstyp != "gesamtsystem":
        konkreter_bezug = st.selectbox(
            "Konkreter Bezug",
            optionen.fuer(str(bezugstyp)),
            key=f"{key}_konkreter_bezug",
        )
    return {"bezugstyp": str(bezugstyp), "konkreter_bezug": str(konkreter_bezug)}


def _eingaben_editor(k: dict[str, Any], key: str) -> dict[str, Any]:
    inhalt: dict[str, Any] = {
        "strukturtyp": "experimenteller_faktor",
        **_bezug_editor(k, key=key, gesamtsystem=True),
        "bezeichnung": st.text_input(
            "Bezeichnung des experimentellen Faktors", key=f"{key}_bezeichnung"
        ).strip(),
    }
    art = st.selectbox(
        "Art des Faktors",
        ["quantitativer_parameter", "qualitative_regel"],
        format_func=lambda wert: {
            "quantitativer_parameter": "Quantitativer Parameter",
            "qualitative_regel": "Qualitative Regel",
        }[str(wert)],
        key=f"{key}_art",
    )
    inhalt["art"] = art
    if art == "quantitativer_parameter":
        links, rechts = st.columns(2)
        inhalt["unterer_wert"] = links.number_input(
            "Unterer Wert", value=0.0, key=f"{key}_unterer_wert"
        )
        inhalt["oberer_wert"] = rechts.number_input(
            "Oberer Wert", value=1.0, key=f"{key}_oberer_wert"
        )
        inhalt["einheit"] = st.text_input("Einheit", key=f"{key}_einheit").strip()
    else:
        inhalt["auspraegungen"] = _zeilen(
            st.text_area("Mögliche Ausprägungen (eine pro Zeile)", key=f"{key}_auspraegungen")
        )
    return inhalt


def _ressourcen_editor(k: dict[str, Any], key: str) -> dict[str, Any]:
    ressourcen = modellbezugsoptionen(k).ressourcen
    if not ressourcen:
        st.warning(
            "K enthält keine vorhandene Ressource. Bitte den Punkt als nicht bekannt oder "
            "nicht anwendbar behandeln beziehungsweise Schritt 8 prüfen."
        )
        return {}
    inhalt: dict[str, Any] = {
        "strukturtyp": "ressourcenergaenzung",
        "ressource": st.selectbox("Vorhandene Ressource", ressourcen, key=f"{key}_ressource"),
        "rolle": st.text_input("Rolle / fachliche Funktion", key=f"{key}_rolle").strip(),
        "kapazitaet": st.text_input("Kapazität", key=f"{key}_kapazitaet").strip(),
        "schichtstart": st.text_input("Schichtstart", key=f"{key}_schichtstart").strip(),
        "schichtende": st.text_input("Schichtende", key=f"{key}_schichtende").strip(),
        "pausenzeiten": st.text_input("Pausenzeiten", key=f"{key}_pausenzeiten").strip(),
    }
    if st.checkbox("Verfügbare Anzahl ergänzen", key=f"{key}_anzahl_aktiv"):
        inhalt["verfuegbare_anzahl"] = int(
            st.number_input("Verfügbare Anzahl", min_value=0, step=1, value=1, key=f"{key}_anzahl")
        )
    return inhalt


def _warteschlangen_editor(k: dict[str, Any], key: str) -> dict[str, Any]:
    aktivitaeten = modellbezugsoptionen(k).aktivitaeten
    hinweise = wartestellenhinweise(k)
    if hinweise:
        st.markdown("**Vorhandener potenzieller Wartestellenhinweis aus K/A_G:**")
        for hinweis in hinweise:
            st.write(
                f"{hinweis.get('von_aktivitaet', '–')} → "
                f"{hinweis.get('zu_aktivitaet', '–')} · {_fachwert(hinweis.get('statistik', {}))}"
            )
        st.caption("Potenzielle Wartezeit ist noch keine bestätigte Warteschlange.")
    if len(aktivitaeten) < 2:
        st.warning("K enthält nicht zwei auswählbare Aktivitäten für eine Warteschlange.")
        return {}
    von = st.selectbox("Vorgängeraktivität", aktivitaeten, key=f"{key}_vorgaengeraktivitaet")
    folgeoptionen = tuple(wert for wert in aktivitaeten if wert != von)
    zu = st.selectbox("Folgeaktivität", folgeoptionen, key=f"{key}_folgeaktivitaet")
    return {
        "strukturtyp": "warteschlangenergaenzung",
        "vorgaengeraktivitaet": von,
        "folgeaktivitaet": zu,
        "fachlich_bestaetigt": st.checkbox(
            "Diese Warteschlange fachlich bestätigen", key=f"{key}_fachlich_bestaetigt"
        ),
        "kapazitaet": st.text_input(
            "Verfügbare Kapazität (optional)", key=f"{key}_kapazitaet"
        ).strip(),
        "regel": st.text_input("Fachlich relevante Regel (optional)", key=f"{key}_regel").strip(),
        "potenzieller_wartestellenhinweis": list(hinweise),
    }


def _strukturierter_editor(
    bestandteil_id: ModellbestandteilId, k: dict[str, Any], *, key: str
) -> dict[str, Any]:
    if bestandteil_id is ModellbestandteilId.EINGABEN:
        return _eingaben_editor(k, key)
    if bestandteil_id is ModellbestandteilId.RESSOURCEN:
        return _ressourcen_editor(k, key)
    if bestandteil_id is ModellbestandteilId.WARTESCHLANGEN:
        return _warteschlangen_editor(k, key)
    if bestandteil_id in {ModellbestandteilId.MODELLUMFANG, ModellbestandteilId.MODELLGRENZEN}:
        return {
            "strukturtyp": "modellumfang_und_grenze",
            "beschreibung": st.text_area(
                "Beschreibung der Systemgrenze beziehungsweise des Umfangs",
                key=f"{key}_beschreibung",
            ).strip(),
            "einbezogen": _zeilen(
                st.text_area("Einbezogene Bereiche (optional)", key=f"{key}_einbezogen")
            ),
            "ausgeschlossen": _zeilen(
                st.text_area("Ausgeschlossene Bereiche (optional)", key=f"{key}_ausgeschlossen")
            ),
        }
    if bestandteil_id is ModellbestandteilId.DETAILLIERUNGSGRAD:
        return {
            "strukturtyp": "detaillierungsentscheidung",
            **_bezug_editor(k, key=key, gesamtsystem=False),
            "detailmerkmal": st.text_input("Detailmerkmal", key=f"{key}_detailmerkmal").strip(),
            "behandlung": st.selectbox(
                "Behandlung des Detailmerkmals",
                DETAILBEHANDLUNGEN,
                format_func=lambda wert: {
                    "beruecksichtigen": "Berücksichtigen",
                    "bewusst_ausschliessen": "Bewusst ausschließen",
                }[str(wert)],
                key=f"{key}_behandlung",
            ),
        }
    if bestandteil_id is ModellbestandteilId.ENTITAETEN:
        return {
            "strukturtyp": "entitaetsergaenzung",
            "entitaetstyp": st.text_input(
                "Fachlicher Entitätstyp", key=f"{key}_entitaetstyp"
            ).strip(),
            "objektbezug": st.text_input("Objektbezug", key=f"{key}_objektbezug").strip(),
            "bezeichnung": st.text_input("Bezeichnung", key=f"{key}_bezeichnung").strip(),
            "granularitaet": st.text_input("Granularität", key=f"{key}_granularitaet").strip(),
        }
    if bestandteil_id is ModellbestandteilId.AKTIVITAETEN:
        aktivitaeten = modellbezugsoptionen(k).aktivitaeten
        vorhandene = (
            st.selectbox(
                "Vorhandene Aktivität (optional)",
                ("", *aktivitaeten),
                format_func=lambda wert: "Keine Auswahl" if not wert else str(wert),
                key=f"{key}_vorhandene_aktivitaet",
            )
            if aktivitaeten
            else ""
        )
        return {
            "strukturtyp": "aktivitaetsergaenzung",
            "vorhandene_aktivitaet": vorhandene,
            "fachliche_bezeichnung": st.text_input(
                "Fachliche Bezeichnung", key=f"{key}_fachliche_bezeichnung"
            ).strip(),
            "objektbezug": st.text_input("Objektbezug", key=f"{key}_objektbezug").strip(),
            "granularitaet": st.text_input("Granularität", key=f"{key}_granularitaet").strip(),
            "variantenbezug": st.text_input(
                "Variantenbezug (optional)", key=f"{key}_variantenbezug"
            ).strip(),
        }
    if bestandteil_id is ModellbestandteilId.PROBLEMSTELLUNG:
        return {
            "strukturtyp": "problemstellung",
            "beschreibung": st.text_area(
                "Fachliche Beschreibung der Problemstellung", key=f"{key}_beschreibung"
            ).strip(),
        }
    if bestandteil_id is ModellbestandteilId.ZIELSETZUNG:
        return {
            "strukturtyp": "zielsetzung",
            "modellierungszweck": st.text_area(
                "Modellierungszweck beziehungsweise Ziel", key=f"{key}_modellierungszweck"
            ).strip(),
            "angestrebter_zustand": st.text_area(
                "Angestrebter Zustand / untersuchter Zweck",
                key=f"{key}_angestrebter_zustand",
            ).strip(),
        }
    if bestandteil_id is ModellbestandteilId.AUSGABEN:
        return {
            "strukturtyp": "modellausgabe",
            "gewuenschte_ausgabe": st.text_area(
                "Tatsächlich gewünschte Modellausgabe", key=f"{key}_gewuenschte_ausgabe"
            ).strip(),
        }
    if bestandteil_id is ModellbestandteilId.ANNAHMEN:
        return {
            "strukturtyp": "annahme",
            "annahme": st.text_area("Annahme", key=f"{key}_annahme").strip(),
            "hintergrund": st.text_area(
                "Kurze Begründung / Hintergrund (optional)", key=f"{key}_hintergrund"
            ).strip(),
        }
    if bestandteil_id is ModellbestandteilId.VEREINFACHUNGEN:
        return {
            "strukturtyp": "vereinfachung",
            **_bezug_editor(k, key=key, gesamtsystem=True),
            "beschreibung": st.text_area(
                "Beschreibung der bewussten Vereinfachung", key=f"{key}_beschreibung"
            ).strip(),
            "begruendung": st.text_area("Begründung", key=f"{key}_begruendung").strip(),
        }
    if bestandteil_id in {ModellbestandteilId.DATENAUSWAHL, ModellbestandteilId.DATEN}:
        return {
            "strukturtyp": "datenanforderung",
            "beschreibung": st.text_area(
                "Benötigte Information", key=f"{key}_beschreibung"
            ).strip(),
            "zustand": st.selectbox(
                "Fachlicher Datenzustand",
                DATENZUSTAENDE,
                format_func=lambda wert: {
                    "vorhanden": "Vorhanden",
                    "angenähert_oder_geschätzt": "Angenähert / geschätzt",
                    "nicht_vorhanden": "Nicht vorhanden",
                }[str(wert)],
                key=f"{key}_zustand",
            ),
            "quelle": st.text_input("Quelle / Bezug (optional)", key=f"{key}_quelle").strip(),
            "naeherung": st.text_area(
                "Verwendete Näherung (optional)", key=f"{key}_naeherung"
            ).strip(),
        }
    if bestandteil_id is ModellbestandteilId.DARSTELLUNG_DER_VORGAENGE:
        return {
            "strukturtyp": "systemdarstellung",
            "darstellungsform": st.selectbox(
                "Fachlich gewünschte / verwendete Darstellungsform",
                DARSTELLUNGSFORMEN,
                format_func=lambda wert: {
                    "prozessflussdiagramm": "Prozessflussdiagramm",
                    "ablaufdiagramm": "Ablaufdiagramm",
                    "aktivitaetszyklusdiagramm": "Aktivitätszyklusdiagramm",
                }[str(wert)],
                key=f"{key}_darstellungsform",
            ),
        }
    return {
        "strukturtyp": "fachliche_ergaenzung",
        "fachliche_ergaenzung": st.text_area(
            "Fachliche Ergänzung", key=f"{key}_fachliche_ergaenzung"
        ).strip(),
    }


def _sichere_informationen(bestandteil: dict[str, Any]) -> None:
    informationen = bestandteil.get("informationen", [])
    if not informationen:
        return
    st.markdown("**Bestehende sichere Information in K:**")
    for information in informationen:
        st.write(f"- {_fachwert(information.get('wert'))}")


def _offene_punkte_bearbeiten(
    k: dict[str, Any], o: dict[str, Any], *, widget_praefix: str
) -> tuple[tuple[BehandlungOffenerEintrag, ...], list[dict[str, Any]]]:
    st.subheader("2. Offene Inhalte aus O ergänzen")
    st.caption(
        "Nur diese O-Punkte sind editierbar. Die systematische Begründung und ein optionaler "
        "Hinweis aus Schritt 8 bleiben getrennte Kontexte."
    )
    behandlungen: list[BehandlungOffenerEintrag] = []
    roh: list[dict[str, Any]] = []
    offene_nach_bestandteil: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for offen in o.get("offene_eintraege", []):
        offene_nach_bestandteil[str(offen["bestandteil_id"])].append(offen)
    bestandteile = {wert["bestandteil_id"]: wert for wert in k["modellbestandteile"]}
    nummer = 0
    for bestandteil_id, bestandteil in bestandteile.items():
        offene = offene_nach_bestandteil.get(bestandteil_id, [])
        if not offene:
            continue
        with st.expander(
            f"{bestandteil['bezeichnung']} · {len(offene)} offene Punkte", expanded=False
        ):
            _sichere_informationen(bestandteil)
            for offen in offene:
                nummer += 1
                kategorie = Offenheitskategorie(offen["kategorie"])
                st.markdown(f"**Offener Punkt {nummer} · {kategorie.value.replace('_', ' ')}**")
                st.markdown("**Warum offen:**")
                st.write(offen["begruendung"])
                if str(offen.get("anwenderhinweis", "")).strip():
                    st.markdown("**Hinweis aus Schritt 8:**")
                    st.info(str(offen["anwenderhinweis"]))
                key = f"{widget_praefix}_{offen['offener_eintrag_id']}"
                entscheidung = st.selectbox(
                    "Behandlung",
                    _entscheidungsoptionen(kategorie),
                    key=f"{key}_entscheidung",
                    format_func=lambda wert: _ENTSCHEIDUNGSTEXTE[str(wert)],
                )
                strukturierter_inhalt: dict[str, Any] = {}
                validierungsfehler = ""
                if entscheidung == Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST.value:
                    strukturierter_inhalt = _strukturierter_editor(
                        ModellbestandteilId(bestandteil_id), k, key=key
                    )
                    try:
                        strukturierter_inhalt = validiere_strukturierten_inhalt(
                            ModellbestandteilId(bestandteil_id), strukturierter_inhalt, k
                        )
                    except Domaenenfehler as fehler:
                        validierungsfehler = str(fehler)
                kommentar = ""
                if entscheidung != _NICHT_BEHANDELT:
                    kommentar = st.text_area("Optionaler Kommentar", key=f"{key}_kommentar").strip()
                roh.append(
                    {
                        "offener_eintrag_id": offen["offener_eintrag_id"],
                        "bestandteil_id": bestandteil_id,
                        "entscheidung": entscheidung,
                        "strukturierter_inhalt": strukturierter_inhalt,
                        "kommentar": kommentar,
                        "validierungsfehler": validierungsfehler,
                    }
                )
                if entscheidung != _NICHT_BEHANDELT and not validierungsfehler:
                    behandlungen.append(
                        BehandlungOffenerEintrag(
                            offen["offener_eintrag_id"],
                            ModellbestandteilId(bestandteil_id),
                            kategorie,
                            offen["begruendung"],
                            Offenheitsentscheidung(str(entscheidung)),
                            begruendung=kommentar,
                            strukturierter_inhalt=strukturierter_inhalt,
                        )
                    )
    if not o.get("offene_eintraege"):
        st.success("O enthält keine offenen Einträge; eine Einzelbehandlung ist nicht nötig.")
    return tuple(behandlungen), roh


def _gesamtuebersicht(o: dict[str, Any], behandlungen: tuple[BehandlungOffenerEintrag, ...]) -> int:
    st.subheader("3. Gesamtübersicht")
    zaehler = Counter(wert.entscheidung for wert in behandlungen)
    unbehandelt = len(o.get("offene_eintraege", [])) - len(behandlungen)
    spalten = st.columns(6)
    werte = (
        ("Ursprünglich offen", len(o.get("offene_eintraege", []))),
        ("Ergänzt", zaehler[Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST]),
        ("Bestätigt", zaehler[Offenheitsentscheidung.BESTAETIGT]),
        (
            "Nicht bekannt",
            zaehler[Offenheitsentscheidung.NICHT_BEKANNT_ODER_BESTIMMBAR],
        ),
        ("Nicht anwendbar", zaehler[Offenheitsentscheidung.NICHT_ANWENDBAR]),
        ("Unbehandelt", unbehandelt),
    )
    for spalte, (titel, wert) in zip(spalten, werte, strict=True):
        spalte.metric(titel, wert)
    if unbehandelt:
        st.info("Alle O-Punkte müssen bewusst behandelt sein, bevor K* erzeugt werden kann.")
    else:
        st.success("Alle O-Punkte sind behandelt. Die Gesamtvalidierung ist verfügbar.")
    return unbehandelt


def _gesamtvalidierung(*, widget_praefix: str, unbehandelt: int) -> tuple[str, bool]:
    st.subheader("4. Fachliche Gesamtvalidierung")
    st.caption(
        "Prüfen Sie K als Ganzes einschließlich Ergänzungen und dokumentierter Einschränkungen. "
        "O-Behandlungen können bis zum finalen Klick oberhalb geändert werden."
    )
    vermerk = st.text_area(
        "Validierungsvermerk (optional)",
        key=f"{widget_praefix}_validierungsvermerk",
        disabled=bool(unbehandelt),
    ).strip()
    bestaetigt = st.checkbox(
        "Ich habe das vollständige konzeptionelle Modell einschließlich der ergänzten "
        "Informationen und dokumentierten Einschränkungen fachlich geprüft.",
        key=f"{widget_praefix}_gesamtbestaetigung",
        disabled=bool(unbehandelt),
    )
    if unbehandelt:
        st.caption("Die Gesamtbestätigung wird nach Behandlung aller O-Punkte freigeschaltet.")
    return vermerk, bestaetigt


def _fehlende_pflichtentscheidungen(
    o: dict[str, Any], roh_behandlungen: list[dict[str, Any]], bestaetigt: bool
) -> list[str]:
    fehlend: list[str] = []
    for index, (offen, behandlung) in enumerate(
        zip(o.get("offene_eintraege", []), roh_behandlungen, strict=True), 1
    ):
        bezug = f"Offener Punkt {index} ({offen['bestandteil_id']})"
        if behandlung["entscheidung"] == _NICHT_BEHANDELT:
            fehlend.append(f"{bezug}: Behandlung auswählen")
        elif behandlung["validierungsfehler"]:
            fehlend.append(f"{bezug}: {behandlung['validierungsfehler']}")
    if not bestaetigt:
        fehlend.append("Fachliche Gesamtbestätigung")
    return fehlend


def _behandlungstext(wert: dict[str, Any]) -> str:
    entscheidung = _ENTSCHEIDUNGSTEXTE.get(str(wert.get("entscheidung")), "–")
    struktur = wert.get("strukturierter_inhalt")
    if isinstance(struktur, dict) and struktur:
        return f"{entscheidung}: {_fachwert(struktur)}"
    kommentar = str(wert.get("kommentar") or wert.get("begruendung") or "")
    return f"{entscheidung}{f': {kommentar}' if kommentar else ''}"


def _zustand_vorbelegen(praefix: str, behandlungen: list[dict[str, Any]]) -> None:
    for behandlung in behandlungen:
        eintrag_id = str(behandlung.get("offener_eintrag_id", ""))
        if not eintrag_id:
            continue
        key = f"{praefix}_{eintrag_id}"
        st.session_state[f"{key}_entscheidung"] = str(behandlung.get("entscheidung", ""))
        st.session_state[f"{key}_kommentar"] = str(
            behandlung.get("kommentar", behandlung.get("begruendung", ""))
        )
        struktur = behandlung.get("strukturierter_inhalt", {})
        if not isinstance(struktur, dict):
            continue
        for name, wert in struktur.items():
            if name == "strukturtyp" or isinstance(wert, dict):
                continue
            if isinstance(wert, list):
                if name == "potenzieller_wartestellenhinweis":
                    continue
                wert = "\n".join(str(eintrag) for eintrag in wert)
            st.session_state[f"{key}_{name}"] = wert
        if "verfuegbare_anzahl" in struktur:
            st.session_state[f"{key}_anzahl_aktiv"] = True
            st.session_state[f"{key}_anzahl"] = struktur["verfuegbare_anzahl"]


def _gespeichertes_k_stern(
    service: ModellvalidierungService, validierungslauf_id: UUID, projekt_id: UUID
) -> None:
    validierung, k_stern = service.laden(validierungslauf_id)
    if validierung.projekt_id != projekt_id:
        raise Domaenenfehler("Der aktive Validierungslauf gehört nicht zum aktiven Projekt.")
    historisch = bool(k_stern.get("historischer_lesemodus"))
    if historisch:
        st.warning("Dieses historische K* ist lesbar, aber keine aktuelle Schritt-10-Grundlage.")
    else:
        st.success("K* ist mit einer fachlichen Gesamtvalidierung gespeichert.")
    behandlungen = k_stern.get("behandlungen_offener_eintraege", [])
    st.subheader("Gespeicherter fachlicher Ergänzungsstatus")
    if isinstance(behandlungen, list) and behandlungen:
        st.dataframe(
            [
                {
                    "Modellbestandteil": wert.get("bestandteil_id", "–"),
                    "Behandlung": _ENTSCHEIDUNGSTEXTE.get(str(wert.get("entscheidung")), "–"),
                    "Dokumentation": _behandlungstext(wert),
                    "Entschieden am": wert.get("entschieden_am", "–"),
                }
                for wert in behandlungen
                if isinstance(wert, dict)
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("O enthielt keine offenen Einträge.")
    gesamt = k_stern.get("gesamtvalidierung", {})
    if isinstance(gesamt, dict):
        st.write(f"**Validierungsvermerk:** {gesamt.get('validierungsvermerk') or '–'}")
        st.write(
            "**Fachliche Gesamtbestätigung:** "
            + ("Ja" if gesamt.get("menschlich_bestaetigt") else "Nein")
        )
    st.download_button(
        "Validiertes konzeptionelles Modell K* herunterladen",
        service.k_stern_download_laden(validierungslauf_id),
        "validiertes-konzeptionelles-modell-k-stern.json",
        "application/json",
    )
    if not historisch and isinstance(behandlungen, list):
        if st.button("O-Behandlungen vor erneuter Gesamtvalidierung bearbeiten"):
            praefix = f"schritt9_{projekt_id}_{validierung.modellableitungs_id}"
            _zustand_vorbelegen(praefix, [wert for wert in behandlungen if isinstance(wert, dict)])
            st.session_state[f"{praefix}_validierungsvermerk"] = str(
                gesamt.get("validierungsvermerk", "") if isinstance(gesamt, dict) else ""
            )
            st.session_state[f"{praefix}_gesamtbestaetigung"] = False
            st.session_state.pop("aktuelle_validierungslauf_id", None)
            st.session_state.pop("aktuelle_k_stern_id", None)
            st.rerun()
    links, rechts = st.columns(2)
    if links.button("Zurück zu Schritt 8 und als fachlich unsicher kennzeichnen", width="stretch"):
        framework_bereich_oeffnen(schritt=8, projekt_id=projekt_id)
    if rechts.button(
        "Weiter zu Schritt 10: Konzeptionelles Modell ausgeben",
        type="primary",
        width="stretch",
        disabled=historisch,
    ):
        schritt_abschliessen_und_weiter(aktueller_schritt=9, projekt_id=projekt_id)


def zeige_modellvalidierung_seite(
    projekt_service: ProjektService, service: ModellvalidierungService
) -> None:
    """Setzt Algorithmus 9 als O-Behandlung plus eine fachliche Gesamtvalidierung um."""
    st.header("9 Modell ergänzen und validieren")
    ids = _aktive_ids()
    if ids is None:
        if st.session_state.get("aktuelle_aggregations_id"):
            st.warning(
                "Schritt 8 ist für die aktuelle Ergebnisaggregation A_G noch nicht "
                "abgeschlossen. Speichern Sie zunächst K und O."
            )
        else:
            st.error(
                "Schritt 9 benötigt eine aktive Ergebnisaggregation A_G und das dazu "
                "gespeicherte K/O-Paar aus Schritt 8."
            )
        if st.button("Zurück zu Schritt 8: Modellbestandteile ableiten"):
            framework_bereich_oeffnen(schritt=8)
        return
    projekt_id, modellableitungs_id, k_id, o_id = ids
    if projekt_service.projekt_laden(projekt_id) is None:
        st.error("Das aktive Projekt wurde nicht gefunden.")
        return
    gespeicherte_id = st.session_state.get("aktuelle_validierungslauf_id")
    if gespeicherte_id:
        try:
            _gespeichertes_k_stern(service, UUID(str(gespeicherte_id)), projekt_id)
        except (ValueError, Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            st.error(f"Das gespeicherte K* ist nicht mehr gültig: {fehler}")
        return
    try:
        basis = service.grundlage_laden(
            projekt_id,
            modellableitungs_id,
            erwartete_k_id=k_id,
            erwartete_o_id=o_id,
        )
    except (Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
        st.error(f"K und O sind nicht mehr gültig: {fehler}")
        if st.button("Zurück zu Schritt 8: Modellbestandteile ableiten"):
            framework_bereich_oeffnen(schritt=8, projekt_id=projekt_id)
        return

    _bestandteile_anzeigen(basis.k, basis.o, projekt_id=projekt_id)
    praefix = f"schritt9_{projekt_id}_{modellableitungs_id}"
    behandlungen, roh_behandlungen = _offene_punkte_bearbeiten(
        basis.k, basis.o, widget_praefix=praefix
    )
    unbehandelt = _gesamtuebersicht(basis.o, behandlungen)
    vermerk, bestaetigt = _gesamtvalidierung(widget_praefix=praefix, unbehandelt=unbehandelt)
    fehlend = _fehlende_pflichtentscheidungen(basis.o, roh_behandlungen, bestaetigt)
    arbeitsfassung: Validierungsarbeitsfassung | None = None
    if not fehlend:
        try:
            arbeitsfassung = service.arbeitsfassung_aus_grundlage(
                basis,
                behandlungen=behandlungen,
                zusaetzliche_anpassungen=(),
                gesamtvalidierungsstatus=Gesamtvalidierungsstatus.FACHLICH_VALIDIERT,
                validierungsvermerk=vermerk,
                gesamtpruefung_bestaetigt=bestaetigt,
            )
        except (ValueError, Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            fehlend.append(str(fehler))
    if fehlend:
        with st.expander("Noch offene Angaben", expanded=False):
            for feld in fehlend:
                st.write(f"- {feld}")
    _technische_details(basis, arbeitsfassung)
    if st.button(
        "Gesamtmodell fachlich validieren und K* erzeugen",
        type="primary",
        disabled=bool(fehlend) or arbeitsfassung is None,
        width="stretch",
    ):
        assert arbeitsfassung is not None
        try:
            validierung = service.speichern(
                arbeitsfassung, validierungslauf_id=uuid4(), k_stern_id=uuid4()
            )
            st.session_state.aktuelle_validierungslauf_id = str(validierung.validierungslauf_id)
            st.session_state.aktuelle_k_stern_id = str(validierung.k_stern_id)
            for schluessel in (
                "schritt10_ausgabe",
                "schritt10_ausgabe_signatur",
                "schritt10_html_medienreferenz",
            ):
                st.session_state.pop(schluessel, None)
            schritt_abschliessen_und_weiter(aktueller_schritt=9, projekt_id=projekt_id)
        except (ValueError, Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            st.error(f"K* konnte nicht gespeichert werden: {fehler}")
