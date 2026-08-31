"""Framework-Schritt 9: K mit Domänenwissen ergänzen und fachlich validieren."""

from collections import defaultdict
from typing import Any
from uuid import UUID, uuid4

import streamlit as st

from framework_mvp.application.modellvalidierung_service import (
    ModellvalidierungService,
    Validierungsarbeitsfassung,
)
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    BehandlungOffenerEintrag,
    Gesamtvalidierungsstatus,
    ModellbestandteilId,
    Offenheitsentscheidung,
    Offenheitskategorie,
    ZusaetzlicheModellanpassung,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.navigation import framework_bereich_oeffnen


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


def _bestandteile_anzeigen(k: dict[str, Any], o: dict[str, Any]) -> None:
    st.subheader("2. Übersicht der 16 Modellbestandteile")
    st.markdown("**Vorläufiges Modell K**")
    st.caption(
        "K ist schreibgeschützt. Die Detailbearbeitung konzentriert sich anschließend auf O."
    )
    offene_anzahl: dict[str, int] = defaultdict(int)
    for offen in o.get("offene_eintraege", []):
        offene_anzahl[str(offen["bestandteil_id"])] += 1
    st.dataframe(
        [
            {
                "Modellbestandteil": wert["bezeichnung"],
                "Status in K": wert["status"],
                "Informationen": len(wert.get("informationen", [])),
                "Offene Punkte in O": offene_anzahl[wert["bestandteil_id"]],
            }
            for wert in k["modellbestandteile"]
        ],
        hide_index=True,
        width="stretch",
    )
    with st.expander("Schreibgeschützte Details aus K", expanded=False):
        bezeichnungen = {wert["bestandteil_id"]: wert for wert in k["modellbestandteile"]}
        auswahl = st.selectbox(
            "Modellbestandteil anzeigen",
            list(bezeichnungen),
            format_func=lambda wert: bezeichnungen[wert]["bezeichnung"],
            key="schritt9_k_detailauswahl",
        )
        bestandteil = bezeichnungen[auswahl]
        st.write(f"Status in K: {bestandteil['status']}")
        for information in bestandteil.get("informationen", []):
            st.write(
                f"{information['herkunftsartefakt']} · {information['strukturreferenz']}: "
                f"{information['wert']}"
            )
        if not bestandteil.get("informationen"):
            st.info("Keine direkt aus den Eingangsartefakten übernommene Information.")


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
        "noch_nicht_behandelt",
        Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST.value,
        Offenheitsentscheidung.NICHT_ANWENDBAR.value,
    ]
    if kategorie is Offenheitskategorie.FACHLICH_UNSICHER:
        optionen.insert(1, Offenheitsentscheidung.BESTAETIGT.value)
    return optionen


def _offene_punkte_bearbeiten(
    k: dict[str, Any], o: dict[str, Any], *, widget_praefix: str
) -> tuple[tuple[BehandlungOffenerEintrag, ...], list[dict[str, str]]]:
    st.subheader("3. Offene und fachlich unsichere Punkte bearbeiten")
    st.caption(
        "O bleibt unverändert. Jede Behandlung wird separat als menschliche Entscheidung geführt."
    )
    behandlungen: list[BehandlungOffenerEintrag] = []
    roh: list[dict[str, str]] = []
    offene_nach_bestandteil: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for offen in o.get("offene_eintraege", []):
        offene_nach_bestandteil[str(offen["bestandteil_id"])].append(offen)
    bezeichnungen = {
        wert["bestandteil_id"]: wert["bezeichnung"] for wert in k["modellbestandteile"]
    }
    nummer = 0
    for bestandteil_id, bezeichnung in bezeichnungen.items():
        offene = offene_nach_bestandteil.get(bestandteil_id, [])
        if not offene:
            continue
        with st.expander(f"{bezeichnung} · {len(offene)} offene Punkte", expanded=False):
            for offen in offene:
                nummer += 1
                kategorie = Offenheitskategorie(offen["kategorie"])
                st.markdown(f"**Offener Punkt {nummer} · {kategorie.value}**")
                st.write(offen["begruendung"])
                belege = offen.get("belegreferenzen", [])
                st.caption(
                    f"Herkunft: {offen.get('kennzeichnungsherkunft', 'nicht angegeben')} · "
                    f"Belege: {', '.join(map(str, belege)) if belege else 'keine'}"
                )
                entscheidung = st.selectbox(
                    "Fachliche Entscheidung",
                    _entscheidungsoptionen(kategorie),
                    key=f"{widget_praefix}_entscheidung_{offen['offener_eintrag_id']}",
                    format_func=lambda wert: {
                        "noch_nicht_behandelt": "Noch nicht behandelt",
                        "bestätigt": "bestätigt",
                        "ergänzt_oder_angepasst": "ergänzt oder angepasst",
                        "nicht_anwendbar": "nicht anwendbar",
                    }[wert],
                )
                inhalt = ""
                if entscheidung == Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST.value:
                    inhalt = st.text_area(
                        "Fachlicher Inhalt für K*",
                        key=f"{widget_praefix}_inhalt_{offen['offener_eintrag_id']}",
                    ).strip()
                begruendung = ""
                if entscheidung != "noch_nicht_behandelt":
                    begruendung = st.text_area(
                        "Begründung der fachlichen Entscheidung",
                        key=f"{widget_praefix}_begruendung_{offen['offener_eintrag_id']}",
                    ).strip()
                roh.append(
                    {
                        "offener_eintrag_id": offen["offener_eintrag_id"],
                        "bestandteil_id": bestandteil_id,
                        "entscheidung": entscheidung,
                        "fachlicher_inhalt": inhalt,
                        "begruendung": begruendung,
                    }
                )
                vollstaendig = bool(begruendung) and (
                    entscheidung != Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST.value
                    or bool(inhalt)
                )
                if entscheidung != "noch_nicht_behandelt" and vollstaendig:
                    behandlungen.append(
                        BehandlungOffenerEintrag(
                            offen["offener_eintrag_id"],
                            ModellbestandteilId(bestandteil_id),
                            kategorie,
                            offen["begruendung"],
                            Offenheitsentscheidung(entscheidung),
                            inhalt,
                            begruendung,
                        )
                    )
    if not o.get("offene_eintraege"):
        st.success(
            "O enthält keine offenen Einträge; eine Einzelbehandlung ist nicht erforderlich."
        )
    return tuple(behandlungen), roh


def _gesamtvalidierung(
    k: dict[str, Any], *, widget_praefix: str
) -> tuple[
    tuple[ZusaetzlicheModellanpassung, ...],
    list[dict[str, str]],
    Gesamtvalidierungsstatus,
    str,
    bool,
]:
    st.subheader("4. Fachliche Gesamtvalidierung")
    st.markdown("**Weitere fachliche Anpassung (optional)**")
    anzahl = int(
        st.number_input(
            "Anzahl zusätzlicher Modellanpassungen",
            min_value=0,
            max_value=50,
            value=0,
            step=1,
            key=f"{widget_praefix}_anpassungsanzahl",
            help="Mehrere Einträge je Modellbestandteil sind möglich.",
        )
    )
    bezeichnungen = {
        wert["bestandteil_id"]: wert["bezeichnung"] for wert in k["modellbestandteile"]
    }
    anpassungen: list[ZusaetzlicheModellanpassung] = []
    roh: list[dict[str, str]] = []
    for index in range(anzahl):
        with st.expander(f"Zusätzliche Anpassung {index + 1}", expanded=True):
            bestandteil_id = st.selectbox(
                "Modellbestandteil",
                list(bezeichnungen),
                format_func=lambda wert: bezeichnungen[wert],
                key=f"{widget_praefix}_anpassung_{index}_bestandteil",
            )
            assert bestandteil_id is not None
            inhalt = st.text_area(
                "Fachlicher Inhalt", key=f"{widget_praefix}_anpassung_{index}_inhalt"
            ).strip()
            begruendung = st.text_area(
                "Begründung", key=f"{widget_praefix}_anpassung_{index}_begruendung"
            ).strip()
            roh.append(
                {
                    "bestandteil_id": bestandteil_id,
                    "fachlicher_inhalt": inhalt,
                    "begruendung": begruendung,
                }
            )
            if inhalt and begruendung:
                anpassungen.append(
                    ZusaetzlicheModellanpassung(
                        ModellbestandteilId(bestandteil_id), inhalt, begruendung
                    )
                )
    status = Gesamtvalidierungsstatus(
        st.radio(
            "Status der fachlichen Gesamtvalidierung",
            [
                Gesamtvalidierungsstatus.ANPASSUNGSBEDARF.value,
                Gesamtvalidierungsstatus.FACHLICH_VALIDIERT.value,
            ],
            format_func=lambda wert: {
                "anpassungsbedarf": "Anpassungsbedarf – Arbeitsstand fortsetzen",
                "fachlich_validiert": "fachlich validiert",
            }[wert],
            key=f"{widget_praefix}_gesamtstatus",
        )
    )
    vermerk = st.text_area(
        "Optionaler Validierungsvermerk", key=f"{widget_praefix}_validierungsvermerk"
    ).strip()
    bestaetigt = st.checkbox(
        "Ich habe das vollständige konzeptionelle Modell einschließlich der ergänzten "
        "und angepassten Inhalte fachlich geprüft.",
        key=f"{widget_praefix}_gesamtbestaetigung",
    )
    return tuple(anpassungen), roh, status, vermerk, bestaetigt


def _fehlende_pflichtentscheidungen(
    o: dict[str, Any],
    roh_behandlungen: list[dict[str, str]],
    roh_anpassungen: list[dict[str, str]],
    status: Gesamtvalidierungsstatus,
    bestaetigt: bool,
) -> list[str]:
    fehlend: list[str] = []
    for index, (offen, behandlung) in enumerate(
        zip(o.get("offene_eintraege", []), roh_behandlungen, strict=True), 1
    ):
        bezug = f"Offener Punkt {index} ({offen['bestandteil_id']})"
        if behandlung["entscheidung"] == "noch_nicht_behandelt":
            fehlend.append(f"{bezug}: Fachliche Entscheidung")
            continue
        if (
            behandlung["entscheidung"] == Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST.value
            and not behandlung["fachlicher_inhalt"]
        ):
            fehlend.append(f"{bezug}: Fachlicher Inhalt für K*")
        if not behandlung["begruendung"]:
            fehlend.append(f"{bezug}: Begründung der fachlichen Entscheidung")
    for index, anpassung in enumerate(roh_anpassungen, 1):
        if not anpassung["fachlicher_inhalt"]:
            fehlend.append(f"Zusätzliche Anpassung {index}: Fachlicher Inhalt")
        if not anpassung["begruendung"]:
            fehlend.append(f"Zusätzliche Anpassung {index}: Begründung")
    if status is not Gesamtvalidierungsstatus.FACHLICH_VALIDIERT:
        fehlend.append("Status der fachlichen Gesamtvalidierung: fachlich validiert")
    if not bestaetigt:
        fehlend.append("Ausdrückliche fachliche Gesamtbestätigung")
    return fehlend


def _bereitschaft_und_vorschau(
    k: dict[str, Any],
    o: dict[str, Any],
    behandlungen: tuple[BehandlungOffenerEintrag, ...],
    anpassungen: tuple[ZusaetzlicheModellanpassung, ...],
    fehlend: list[str],
) -> None:
    offene_insgesamt = len(o.get("offene_eintraege", []))
    st.write(
        f"Bereitschaft: Offene Punkte insgesamt: {offene_insgesamt} · "
        f"vollständig behandelt: {len(behandlungen)} · "
        f"noch zu behandeln: {offene_insgesamt - len(behandlungen)} · "
        f"zusätzliche Anpassungen: {len(anpassungen)}"
    )
    if fehlend:
        st.info("Status: Noch nicht finalisierbar.")
        with st.expander("Noch offene Pflichtangaben", expanded=False):
            for feld in fehlend:
                st.write(f"- {feld}")
    else:
        st.success(
            "Alle offenen Punkte sind behandelt. Die fachliche Gesamtvalidierung kann "
            "abgeschlossen werden."
        )
    st.caption("K*-Vorschau: ursprüngliches K plus separat ausgewiesene menschliche Einträge")
    behandlungen_nach_id: dict[ModellbestandteilId, list[BehandlungOffenerEintrag]] = defaultdict(
        list
    )
    anpassungen_nach_id: dict[ModellbestandteilId, list[ZusaetzlicheModellanpassung]] = defaultdict(
        list
    )
    for wert in behandlungen:
        behandlungen_nach_id[wert.bestandteil_id].append(wert)
    for wert in anpassungen:
        anpassungen_nach_id[wert.bestandteil_id].append(wert)

    def menschliche_vorschau(bestandteil_id: ModellbestandteilId) -> str:
        texte = [
            (f"{wert.entscheidung.value}: {wert.fachlicher_inhalt or wert.begruendung}")
            for wert in behandlungen_nach_id[bestandteil_id]
        ]
        texte.extend(
            f"weitere Anpassung: {wert.fachlicher_inhalt}"
            for wert in anpassungen_nach_id[bestandteil_id]
        )
        return " · ".join(texte) or "keine"

    st.dataframe(
        [
            {
                "Modellbestandteil": wert["bezeichnung"],
                "Original K": f"{len(wert.get('informationen', []))} Informationen",
                "O-Behandlungen": len(
                    behandlungen_nach_id[ModellbestandteilId(wert["bestandteil_id"])]
                ),
                "Weitere Anpassungen": len(
                    anpassungen_nach_id[ModellbestandteilId(wert["bestandteil_id"])]
                ),
                "Menschlicher Inhalt / Entscheidung": menschliche_vorschau(
                    ModellbestandteilId(wert["bestandteil_id"])
                ),
            }
            for wert in k["modellbestandteile"]
        ],
        hide_index=True,
        width="stretch",
    )


def _gespeichertes_k_stern(
    service: ModellvalidierungService, validierungslauf_id: UUID, projekt_id: UUID
) -> None:
    validierung, k_stern = service.laden(validierungslauf_id)
    if validierung.projekt_id != projekt_id:
        raise Domaenenfehler("Der aktive Validierungslauf gehört nicht zum aktiven Projekt.")
    if k_stern.get("historischer_lesemodus"):
        st.warning("Dieses historische K* ist nur lesbar und keine aktuelle Schritt-10-Grundlage.")
    else:
        st.success("K* ist fachlich validiert und gespeichert.")
    st.download_button(
        "Validiertes konzeptionelles Modell K* herunterladen",
        service.k_stern_download_laden(validierungslauf_id),
        "validiertes-konzeptionelles-modell-k-stern.json",
        "application/json",
    )


def zeige_modellvalidierung_seite(
    projekt_service: ProjektService, service: ModellvalidierungService
) -> None:
    """Setzt Algorithmus 9 ausschließlich mit K, O und menschlichem Domänenwissen um."""
    st.header("9 Modell ergänzen und validieren")
    ids = _aktive_ids()
    if ids is None:
        st.error("Schritt 9 benötigt die aktiven IDs des gespeicherten K/O-Paars aus Schritt 8.")
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
    st.subheader("1. Validierte Eingaben K und O")
    st.success(
        "K und O wurden einschließlich Projektbindung, Versionen, Prüfsummen und "
        "gegenseitiger Referenz erneut validiert."
    )
    _bestandteile_anzeigen(basis.k, basis.o)
    praefix = f"schritt9_{projekt_id}_{modellableitungs_id}"
    behandlungen, roh_behandlungen = _offene_punkte_bearbeiten(
        basis.k, basis.o, widget_praefix=praefix
    )
    anpassungen, roh_anpassungen, status, vermerk, bestaetigt = _gesamtvalidierung(
        basis.k, widget_praefix=praefix
    )
    fehlend = _fehlende_pflichtentscheidungen(
        basis.o, roh_behandlungen, roh_anpassungen, status, bestaetigt
    )
    arbeitsfassung: Validierungsarbeitsfassung | None = None
    if not fehlend:
        try:
            arbeitsfassung = service.arbeitsfassung_aus_grundlage(
                basis,
                behandlungen=behandlungen,
                zusaetzliche_anpassungen=anpassungen,
                gesamtvalidierungsstatus=status,
                validierungsvermerk=vermerk,
                gesamtpruefung_bestaetigt=bestaetigt,
            )
        except (ValueError, Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            fehlend.append(str(fehler))
    _bereitschaft_und_vorschau(basis.k, basis.o, behandlungen, anpassungen, fehlend)
    _technische_details(basis, arbeitsfassung)
    st.subheader("5. K* speichern und zu Schritt 10")
    if st.button(
        "K* fachlich validieren und zu Schritt 10",
        type="primary",
        disabled=bool(fehlend) or arbeitsfassung is None,
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
            framework_bereich_oeffnen(schritt=10, projekt_id=projekt_id)
        except (ValueError, Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            st.error(f"K* konnte nicht gespeichert werden: {fehler}")
