"""Framework-Schritt 8: 16 Vorschläge fachlich prüfen und als K/O übernehmen."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

import pandas as pd
import streamlit as st

from framework_mvp.application.modellableitung_service import (
    ModellableitungService,
    Modellableitungsvorschau,
)
from framework_mvp.application.process_mining.svg import validiere_svg_text
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Bestandteilstatus,
    FachlicheBestandteilentscheidung,
    FachlicheEntscheidungsart,
    ModellbestandteilId,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.navigation import framework_bereich_oeffnen


def _aktive_ids() -> tuple[UUID, UUID] | None:
    try:
        return (
            UUID(str(st.session_state.get("aktuelles_projekt_id"))),
            UUID(str(st.session_state.get("aktuelle_aggregations_id"))),
        )
    except (TypeError, ValueError, AttributeError):
        return None


def _status_text(status: Bestandteilstatus | str) -> str:
    roh = status.value if isinstance(status, Bestandteilstatus) else str(status)
    return {
        "vollstaendig_zugeordnet": "vollständig zugeordnet",
        "teilweise_offen": "teilweise offen",
        "offen": "offen",
        "fachlich_unsicher": "fachlich unsicher",
    }.get(roh, roh)


def _eingangsuebersicht(basis: Any) -> None:
    st.success(
        "Die aktive Lineage U, S, Q, R, T, E*, P und A_G ist validiert. Schritt 8 "
        "berechnet keine Ressourcen-, Warte- oder Zeitdaten neu."
    )
    zeitdaten = basis.a_g.get("strukturierte_ergebnisse", {}).get("zeitbezogene_datenauswahl", {})
    umfang = zeitdaten.get("umfang_e_stern", {}) if isinstance(zeitdaten, dict) else {}
    spalten = st.columns(4)
    spalten[0].metric("Ereignisse", umfang.get("ereignisanzahl", "–"))
    spalten[1].metric("Fälle", umfang.get("fallanzahl", "–"))
    spalten[2].metric("Aktivitäten", umfang.get("aktivitaetsanzahl", "–"))
    spalten[3].metric("Notation P", basis.prozessnotation.bezeichnung)
    svg = basis.discovery_ergebnisse.get("svg_texte", {}).get("modell_svg")
    if svg:
        try:
            st.image(
                validiere_svg_text(svg),
                caption=f"Prozessmodell P ({basis.prozessnotation.bezeichnung})",
                width="stretch",
            )
        except Exception as fehler:  # pragma: no cover - UI-/Rendererabhängig
            st.warning(f"P kann nicht grafisch dargestellt werden: {fehler}")


def _wert_text(wert: Any) -> str:
    if isinstance(wert, str):
        return wert
    if isinstance(wert, (tuple, list)):
        if not wert:
            return "Keine Einträge"
        if all(isinstance(eintrag, (str, int, float)) for eintrag in wert):
            return ", ".join(str(eintrag) for eintrag in wert)
        return f"{len(wert)} strukturierte Einträge"
    if isinstance(wert, dict):
        for schluessel in (
            "beobachtete_instanzanzahl",
            "fallanzahl",
            "ereignisanzahl",
            "bezeichnung",
            "notation",
            "status",
        ):
            if wert.get(schluessel) not in (None, "", []):
                return f"{schluessel.replace('_', ' ').capitalize()}: {wert[schluessel]}"
        return f"Strukturierte Angaben ({len(wert)} Felder)"
    return str(wert)


def _ergebnistext(bestandteil: Any) -> str:
    if not bestandteil.informationen:
        return "Keine belastbare Information übernehmbar"
    texte = [_wert_text(wert.wert) for wert in bestandteil.informationen]
    if len(texte) > 2:
        return "; ".join(texte[:2]) + f"; sowie {len(texte) - 2} weitere"
    return "; ".join(texte)


def _haupttabelle(
    vorschlag: Modellableitungsvorschau,
    ergebnis: Modellableitungsvorschau,
    entscheidungen: dict[ModellbestandteilId, FachlicheBestandteilentscheidung],
) -> None:
    st.subheader("Zuordnung der Ergebnisse aus Schritt 1 bis 7")
    status_nach_id = {wert.bestandteil_id: wert.status for wert in ergebnis.bestandteile}
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Bestandteil": wert.bezeichnung,
                    "Vorgeschlagene Information": _ergebnistext(wert),
                    "Quelle/Schritt": ", ".join(quelle.value for quelle in wert.verwendete_quellen)
                    or "–",
                    "Status": _status_text(status_nach_id[wert.bestandteil_id]),
                    "Fachliche Entscheidung": (
                        entscheidungen[wert.bestandteil_id].entscheidung.value
                        if wert.bestandteil_id in entscheidungen
                        else "noch nicht entschieden"
                    ),
                }
                for wert in vorschlag.vorgeschlagene_bestandteile
            ],
            columns=[
                "Bestandteil",
                "Vorgeschlagene Information",
                "Quelle/Schritt",
                "Status",
                "Fachliche Entscheidung",
            ],
        ),
        hide_index=True,
        width="stretch",
    )


_ENTSCHEIDUNGSOPTIONEN = {
    "Noch nicht entschieden": None,
    "Vorschlag übernehmen": FachlicheEntscheidungsart.UEBERNEHMEN,
    "Offen / fachlich unsicher": FachlicheEntscheidungsart.OFFEN_UNSICHER,
    "Vorschlag nicht übernehmen": FachlicheEntscheidungsart.NICHT_UEBERNEHMEN,
}


def _fachliche_details(
    vorschau: Modellableitungsvorschau, fingerabdruck: str
) -> tuple[FachlicheBestandteilentscheidung, ...]:
    st.subheader("Fachliche Vorschläge und Übernahmeentscheidungen")
    offene_nach_bestandteil: dict[str, list[Any]] = {}
    for eintrag in vorschau.systematische_offene_eintraege:
        offene_nach_bestandteil.setdefault(eintrag.bestandteil_id.value, []).append(eintrag)
    entscheidungen: list[FachlicheBestandteilentscheidung] = []
    for index, bestandteil in enumerate(vorschau.vorgeschlagene_bestandteile, 1):
        basis_key = f"schritt8_{fingerabdruck}_{bestandteil.bestandteil_id.value}"
        with st.expander(
            f"{index}. {bestandteil.bezeichnung} · {_status_text(bestandteil.status)}"
        ):
            if not bestandteil.informationen:
                st.info("Keine fachlich belastbare Information direkt übernehmbar.")
            for information in bestandteil.informationen:
                st.markdown(f"**Vorgeschlagene Information:** {_wert_text(information.wert)}")
                st.caption(
                    f"Quelle: {information.herkunftsartefakt.value} · "
                    f"{information.strukturreferenz}"
                )
            for eintrag in offene_nach_bestandteil.get(bestandteil.bestandteil_id.value, []):
                st.warning(f"Offener Punkt ({eintrag.kategorie.value}): {eintrag.begruendung}")
            auswahl = st.radio(
                "Fachliche Entscheidung",
                tuple(_ENTSCHEIDUNGSOPTIONEN),
                key=f"{basis_key}_auswahl",
            )
            art = _ENTSCHEIDUNGSOPTIONEN[auswahl]
            begruendung = ""
            if art in {
                FachlicheEntscheidungsart.OFFEN_UNSICHER,
                FachlicheEntscheidungsart.NICHT_UEBERNEHMEN,
            }:
                begruendung = st.text_area(
                    "Begründung (erforderlich)",
                    key=f"{basis_key}_begruendung",
                    placeholder="Warum bleibt der Vorschlag offen oder wird nicht übernommen?",
                ).strip()
            if art is not None and (art is FachlicheEntscheidungsart.UEBERNEHMEN or begruendung):
                signatur = f"{art.value}:{begruendung}"
                if st.session_state.get(f"{basis_key}_signatur") != signatur:
                    st.session_state[f"{basis_key}_signatur"] = signatur
                    st.session_state[f"{basis_key}_zeitpunkt"] = datetime.now(UTC).isoformat()
                entscheidungen.append(
                    FachlicheBestandteilentscheidung(
                        bestandteil.bestandteil_id,
                        art,
                        begruendung,
                        datetime.fromisoformat(st.session_state[f"{basis_key}_zeitpunkt"]),
                    )
                )
    return tuple(entscheidungen)


def _ergebnisuebersicht(vorschau: Modellableitungsvorschau) -> None:
    st.subheader("Ergebnisübersicht vor dem Speichern")
    zaehler = {status: 0 for status in Bestandteilstatus}
    for bestandteil in vorschau.bestandteile:
        zaehler[bestandteil.status] += 1
    spalten = st.columns(4)
    spalten[0].metric("Vollständig übernommen", zaehler[Bestandteilstatus.VOLLSTAENDIG_ZUGEORDNET])
    spalten[1].metric("Teilweise offen", zaehler[Bestandteilstatus.TEILWEISE_OFFEN])
    spalten[2].metric("Offen", zaehler[Bestandteilstatus.OFFEN])
    spalten[3].metric("Fachlich unsicher", zaehler[Bestandteilstatus.FACHLICH_UNSICHER])
    st.caption(
        f"16 Modellbestandteile · {len(vorschau.offene_eintraege)} O-Einträge · "
        f"{len(vorschau.entscheidungen)} explizite Entscheidungen"
    )


def _technische_details(vorschau: Modellableitungsvorschau) -> None:
    with st.expander("Technische Details", expanded=False):
        st.json(
            {
                "modellableitungs_id": str(vorschau.modellableitungs_id),
                "k_id": str(vorschau.k_id),
                "k_sha256": vorschau.k_sha256,
                "o_id": str(vorschau.o_id),
                "o_sha256": vorschau.o_sha256,
                "eingabefingerabdruck": vorschau.grundlage.eingabefingerabdruck,
                "entscheidungsfingerabdruck": vorschau.entscheidungsfingerabdruck,
                "mappingversion": 3,
                "artefaktlineage": vorschau.grundlage.lineage,
                "vorschlaege": vorschau.vorgeschlagene_bestandteile,
            },
            expanded=False,
        )


def _gespeicherte_ableitung(
    service: ModellableitungService, ableitungs_id: UUID, projekt_id: UUID
) -> None:
    ableitung, k, o = service.laden(ableitungs_id)
    if ableitung.projekt_id != projekt_id:
        raise Domaenenfehler("Die aktive Modellableitung gehört nicht zum aktiven Projekt.")
    st.success("K und O sind gespeichert und erneut validiert.")
    entscheidungen = k.get("fachliche_entscheidungen", [])
    if entscheidungen:
        st.subheader("Gespeicherte fachliche Entscheidungen")
        st.dataframe(
            pd.DataFrame(entscheidungen).rename(
                columns={
                    "bestandteil_id": "Modellbestandteil",
                    "entscheidung": "Entscheidung",
                    "begruendung": "Begründung",
                    "entschieden_am": "Entschieden am",
                }
            ),
            hide_index=True,
            width="stretch",
        )
    st.write(f"**Modellbestandteile in K:** {len(k.get('modellbestandteile', []))}")
    st.write(f"**Offene Einträge in O:** {len(o.get('offene_eintraege', []))}")
    links, rechts = st.columns(2)
    links.download_button(
        "Vorläufiges konzeptionelles Modell K herunterladen",
        service.k_download_laden(ableitungs_id),
        f"{ableitung.k_id}.k.json",
        "application/json",
    )
    rechts.download_button(
        "Offene Bestandteile O herunterladen",
        service.o_download_laden(ableitungs_id),
        f"{ableitung.o_id}.o.json",
        "application/json",
    )


def zeige_modellableitung_seite(
    projekt_service: ProjektService, service: ModellableitungService
) -> None:
    """Lässt alle 16 Zuordnungsvorschläge prüfen und erzeugt daraus gemeinsam K und O."""
    st.header("8 Modellbestandteile ableiten")
    ids = _aktive_ids()
    if ids is None:
        st.error(
            "Schritt 8 benötigt das aktive Projekt und die aktive, gespeicherte Aggregation A_G "
            "aus Schritt 7."
        )
        if st.button("Zurück zu Schritt 7: Ergebnisse aggregieren"):
            framework_bereich_oeffnen(schritt=7)
        return
    projekt_id, aggregations_id = ids
    if projekt_service.projekt_laden(projekt_id) is None:
        st.error("Das aktive Projekt wurde nicht gefunden.")
        return
    gespeicherte_id = st.session_state.get("aktuelle_modellableitungs_id")
    if gespeicherte_id:
        try:
            _gespeicherte_ableitung(service, UUID(str(gespeicherte_id)), projekt_id)
        except (ValueError, Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            st.error(f"Die gespeicherte Modellableitung ist nicht mehr gültig: {fehler}")
        return
    try:
        basis = service.grundlage_laden(projekt_id, aggregations_id)
        vorschlags_id = uuid5(aggregations_id, basis.eingabefingerabdruck)
        vorschlag = service.vorschau(
            projekt_id=projekt_id,
            aggregations_id=aggregations_id,
            modellableitungs_id=vorschlags_id,
            k_id=uuid5(vorschlags_id, "K"),
            o_id=uuid5(vorschlags_id, "O"),
        )
    except (Domaenenfehler, Importintegritaetsfehler, KeyError, TypeError) as fehler:
        st.error(f"K und O konnten nicht automatisch abgeleitet werden: {fehler}")
        if st.button("Zurück zu Schritt 7: Ergebnisse aggregieren"):
            framework_bereich_oeffnen(schritt=7, projekt_id=projekt_id)
        return

    _eingangsuebersicht(basis)
    entscheidungen = _fachliche_details(vorschlag, basis.eingabefingerabdruck)
    entscheidungsfingerabdruck = service.entscheidungsfingerabdruck(entscheidungen)
    modellableitungs_id = uuid5(
        aggregations_id, f"{basis.eingabefingerabdruck}:{entscheidungsfingerabdruck}"
    )
    try:
        vorschau = service.vorschau(
            projekt_id=projekt_id,
            aggregations_id=aggregations_id,
            modellableitungs_id=modellableitungs_id,
            k_id=uuid5(modellableitungs_id, "K"),
            o_id=uuid5(modellableitungs_id, "O"),
            entscheidungen=entscheidungen,
        )
    except (Domaenenfehler, Importintegritaetsfehler, KeyError, TypeError) as fehler:
        st.error(f"Die entscheidungsabhängige K/O-Vorschau konnte nicht erzeugt werden: {fehler}")
        return
    entscheidungen_nach_id = {wert.bestandteil_id: wert for wert in entscheidungen}
    _haupttabelle(vorschlag, vorschau, entscheidungen_nach_id)
    _ergebnisuebersicht(vorschau)
    _technische_details(vorschau)
    fehlend = len(vorschlag.vorgeschlagene_bestandteile) - len(entscheidungen)
    if fehlend:
        st.warning(
            f"Bitte prüfen Sie noch {fehlend} Modellbestandteil"
            f"{'e' if fehlend != 1 else ''}, bevor K und O gespeichert werden können."
        )
    if st.button(
        "K und O speichern und zu Schritt 9",
        type="primary",
        disabled=fehlend > 0,
    ):
        try:
            ableitung = service.speichern(vorschau)
            st.session_state.aktuelle_modellableitungs_id = str(ableitung.modellableitungs_id)
            st.session_state.aktuelle_k_id = str(ableitung.k_id)
            st.session_state.aktuelle_o_id = str(ableitung.o_id)
            for schluessel in (
                "aktuelle_validierungslauf_id",
                "aktuelle_k_stern_id",
                "schritt10_ausgabe",
                "schritt10_ausgabe_signatur",
            ):
                st.session_state.pop(schluessel, None)
            framework_bereich_oeffnen(schritt=9, projekt_id=projekt_id)
        except (Domaenenfehler, Importintegritaetsfehler) as fehler:
            st.error(f"K und O konnten nicht gespeichert werden: {fehler}")
