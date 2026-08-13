"""Framework-Schritt 8: Ergebnisse aus Schritt 1 bis 7 den elf Bestandteilen zuordnen."""

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
from framework_mvp.domain.models import Bestandteilstatus
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
    zeitdaten = basis.a_g.get("strukturierte_ergebnisse", {}).get(
        "zeitbezogene_datenauswahl", {}
    )
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


def _ergebnistext(bestandteil: Any) -> str:
    if not bestandteil.informationen:
        return "Keine belastbare Information übernehmbar"
    referenzen = [str(wert.strukturreferenz) for wert in bestandteil.informationen]
    if len(referenzen) > 3:
        return ", ".join(referenzen[:3]) + f" sowie {len(referenzen) - 3} weitere"
    return ", ".join(referenzen)


def _haupttabelle(vorschau: Modellableitungsvorschau) -> None:
    st.subheader("Zuordnung der Ergebnisse aus Schritt 1 bis 7")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Bestandteil": wert.bezeichnung,
                    "Übernommene Ergebnisse": _ergebnistext(wert),
                    "Quelle/Schritt": ", ".join(
                        quelle.value for quelle in wert.verwendete_quellen
                    )
                    or "–",
                    "Status": _status_text(wert.status),
                }
                for wert in vorschau.bestandteile
            ],
            columns=[
                "Bestandteil",
                "Übernommene Ergebnisse",
                "Quelle/Schritt",
                "Status",
            ],
        ),
        hide_index=True,
        width="stretch",
    )


def _fachliche_details(vorschau: Modellableitungsvorschau) -> None:
    st.subheader("Fachliche Details")
    offene_nach_bestandteil: dict[str, list[Any]] = {}
    for eintrag in vorschau.offene_eintraege:
        offene_nach_bestandteil.setdefault(eintrag.bestandteil_id.value, []).append(eintrag)
    for index, bestandteil in enumerate(vorschau.bestandteile, 1):
        with st.expander(
            f"{index}. {bestandteil.bezeichnung} · {_status_text(bestandteil.status)}"
        ):
            if not bestandteil.informationen:
                st.info("Keine fachlich belastbare Information direkt übernehmbar.")
            for information in bestandteil.informationen:
                st.markdown(
                    f"**{information.herkunftsartefakt.value} · "
                    f"{information.strukturreferenz}**"
                )
                st.json(information.wert, expanded=False)
            for eintrag in offene_nach_bestandteil.get(bestandteil.bestandteil_id.value, []):
                st.warning(f"{eintrag.kategorie.value}: {eintrag.begruendung}")


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
                "artefaktlineage": vorschau.grundlage.lineage,
            },
            expanded=False,
        )


def _gespeicherte_ableitung(
    service: ModellableitungService, ableitungs_id: UUID, projekt_id: UUID
) -> None:
    ableitung, _, _ = service.laden(ableitungs_id)
    if ableitung.projekt_id != projekt_id:
        raise Domaenenfehler("Die aktive Modellableitung gehört nicht zum aktiven Projekt.")
    st.success("K und O sind gespeichert und erneut validiert.")
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
    """Ordnet die validierten Ergebnisse automatisch und ohne fachliche Eingabefelder zu."""
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
        modellableitungs_id = uuid5(aggregations_id, basis.eingabefingerabdruck)
        vorschau = service.vorschau(
            projekt_id=projekt_id,
            aggregations_id=aggregations_id,
            modellableitungs_id=modellableitungs_id,
            k_id=uuid5(modellableitungs_id, "K"),
            o_id=uuid5(modellableitungs_id, "O"),
            fachlich_unsichere_bestandteile=frozenset(),
        )
    except (Domaenenfehler, Importintegritaetsfehler, KeyError, TypeError) as fehler:
        st.error(f"K und O konnten nicht automatisch abgeleitet werden: {fehler}")
        if st.button("Zurück zu Schritt 7: Ergebnisse aggregieren"):
            framework_bereich_oeffnen(schritt=7, projekt_id=projekt_id)
        return

    _eingangsuebersicht(basis)
    _haupttabelle(vorschau)
    _fachliche_details(vorschau)
    _technische_details(vorschau)
    if st.button("K und O speichern und zu Schritt 9", type="primary"):
        try:
            ableitung = service.speichern(vorschau, menschlich_bestaetigt=True)
            st.session_state.aktuelle_modellableitungs_id = str(
                ableitung.modellableitungs_id
            )
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
