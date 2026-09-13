"""Framework-Schritt 8: Modellbestandteile automatisch nach K und O ableiten."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid5

import pandas as pd
import streamlit as st

from framework_mvp.application.modellableitung import MAPPINGVERSION
from framework_mvp.application.modellableitung_service import (
    ModellableitungService,
    Modellableitungsvorschau,
)
from framework_mvp.application.process_mining.svg import validiere_svg_text
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    AnwenderhinweisFuerSchritt9,
    Bestandteilstatus,
    FachlicheUnsicherheitskennzeichnung,
    ModellbestandteilId,
)
from framework_mvp.formatierung import formatiere_fachwert
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.navigation import (
    framework_bereich_oeffnen,
    schritt_abschliessen_und_weiter,
)


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
        "vollstaendig_zugeordnet": "Vollständig zugeordnet",
        "teilweise_offen": "Teilweise offen",
        "offen": "Offen",
        "fachlich_unsicher": "Fachlich unsicher",
    }.get(roh, roh)


def _eingangsuebersicht(basis: Any) -> None:
    with st.expander("Grundlage der Modellableitung anzeigen", expanded=False):
        st.success(
            "Die aktive Lineage U, S, Q, R, T, E*, P und A_G ist validiert. Schritt 8 "
            "ordnet vorhandene Informationen zu und berechnet keine Ressourcen-, Warte- oder "
            "Zeitdaten neu."
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


def _wert_text(wert: Any) -> str:
    if isinstance(wert, str):
        return wert
    if isinstance(wert, (tuple, list)):
        if not wert:
            return "Keine Einträge"
        if all(isinstance(eintrag, (str, int, float)) for eintrag in wert):
            return ", ".join(str(formatiere_fachwert(eintrag)) for eintrag in wert)
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
                anzeige = formatiere_fachwert(wert[schluessel])
                return f"{schluessel.replace('_', ' ').capitalize()}: {anzeige}"
        return f"Strukturierte Angaben ({len(wert)} Felder)"
    return str(formatiere_fachwert(wert))


def _informationstext(informationen: Any) -> str:
    if not informationen:
        return "Keine sicher ableitbare Information"
    texte = [_wert_text(wert.wert) for wert in informationen]
    if len(texte) > 2:
        return "; ".join(texte[:2]) + f"; sowie {len(texte) - 2} weitere"
    return "; ".join(texte)


def _tabellenzeilen(vorschau: Modellableitungsvorschau) -> list[dict[str, str]]:
    offen_nach_bestandteil: dict[ModellbestandteilId, list[Any]] = {}
    for eintrag in vorschau.offene_eintraege:
        offen_nach_bestandteil.setdefault(eintrag.bestandteil_id, []).append(eintrag)
    return [
        {
            "Modellbestandteil": bestandteil.bezeichnung,
            "Zugeordnete Information": _informationstext(bestandteil.informationen),
            "Quelle": ", ".join(quelle.value for quelle in bestandteil.verwendete_quellen) or "–",
            "Status": _status_text(bestandteil.status),
            "Offene Punkte O": " · ".join(
                eintrag.begruendung
                for eintrag in offen_nach_bestandteil.get(bestandteil.bestandteil_id, [])
            )
            or "–",
        }
        for bestandteil in vorschau.bestandteile
    ]


def _tabelle_anzeigen(zeilen: list[dict[str, str]]) -> None:
    tabelle = pd.DataFrame(
        zeilen,
        columns=[
            "Modellbestandteil",
            "Zugeordnete Information",
            "Quelle",
            "Status",
            "Offene Punkte O",
        ],
    )

    def hervorheben(zeile: pd.Series) -> list[str]:
        farbe = (
            "background-color: #d1e7dd"
            if zeile["Status"] == "Vollständig zugeordnet"
            else "background-color: #fff3cd"
            if zeile["Status"] == "Teilweise offen"
            else "background-color: #f8d7da"
            if zeile["Status"] in {"Offen", "Fachlich unsicher"}
            else ""
        )
        return [farbe] * len(zeile)

    st.dataframe(tabelle.style.apply(hervorheben, axis=1), hide_index=True, width="stretch")


def _details_anzeigen(vorschau: Modellableitungsvorschau) -> None:
    with st.expander("Zugeordnete Informationen im Detail", expanded=False):
        for bestandteil in vorschau.bestandteile:
            st.markdown(f"**{bestandteil.bezeichnung}**")
            if not bestandteil.informationen:
                st.caption("Keine sicher ableitbare Information für K.")
            for information in bestandteil.informationen:
                st.write(_wert_text(information.wert))
                st.caption(f"Quelle {information.herkunftsartefakt.value}")


def _optionale_pruefung(
    vorschlag: Modellableitungsvorschau,
    fingerabdruck: str,
) -> tuple[
    tuple[AnwenderhinweisFuerSchritt9, ...],
    tuple[FachlicheUnsicherheitskennzeichnung, ...],
]:
    st.subheader("Offene Punkte für Schritt 9")
    st.caption(
        "Die systematische Begründung bleibt unverändert. Sie können optional einen Hinweis "
        "für die spätere Bearbeitung ergänzen."
    )
    hinweise: list[AnwenderhinweisFuerSchritt9] = []
    for eintrag in vorschlag.systematische_offene_eintraege:
        st.warning(
            f"{eintrag.bestandteil_id.value.replace('_', ' ').capitalize()} · "
            f"{eintrag.kategorie.value.replace('_', ' ')}: {eintrag.begruendung}"
        )
        basis_key = f"schritt8_{fingerabdruck}_{eintrag.offener_eintrag_id}"
        sichtbar_key = f"{basis_key}_hinweis_sichtbar"
        if st.session_state.get(sichtbar_key):
            hinweis = st.text_area(
                "Hinweis für die spätere fachliche Ergänzung (optional)",
                key=f"{basis_key}_anwenderhinweis",
            ).strip()
            if hinweis:
                hinweise.append(AnwenderhinweisFuerSchritt9(eintrag.offener_eintrag_id, hinweis))
        elif st.button("Hinweis für Schritt 9 hinzufügen", key=f"{basis_key}_oeffnen"):
            st.session_state[sichtbar_key] = True
            st.rerun()

    zuordenbar = tuple(wert for wert in vorschlag.vorgeschlagene_bestandteile if wert.informationen)
    unsicherheiten: list[FachlicheUnsicherheitskennzeichnung] = []
    with st.expander("Optionale fachliche Unsicherheitskennzeichnung", expanded=False):
        st.caption(
            "Eine Markierung lässt die sicher abgeleitete Information in K unverändert und "
            "erzeugt zusätzlich einen offenen Unsicherheitspunkt in O."
        )
        optionen = [wert.bestandteil_id.value for wert in zuordenbar]
        namen = {wert.bestandteil_id.value: wert.bezeichnung for wert in zuordenbar}
        ausgewaehlt = st.multiselect(
            "Als fachlich unsicher für Schritt 9 kennzeichnen",
            optionen,
            format_func=lambda wert: namen[str(wert)],
            key=f"schritt8_{fingerabdruck}_unsicher",
        )
        for bestandteil_roh in ausgewaehlt:
            bestandteil_id = ModellbestandteilId(str(bestandteil_roh))
            hinweis = st.text_area(
                f"Optionaler Hinweis zu {namen[bestandteil_id.value]}",
                key=f"schritt8_{fingerabdruck}_{bestandteil_id.value}_unsicherheitshinweis",
            ).strip()
            unsicherheiten.append(FachlicheUnsicherheitskennzeichnung(bestandteil_id, hinweis))
    return tuple(hinweise), tuple(unsicherheiten)


def _pruefwerte_aus_zustand(
    vorschlag: Modellableitungsvorschau,
    fingerabdruck: str,
) -> tuple[
    tuple[AnwenderhinweisFuerSchritt9, ...],
    tuple[FachlicheUnsicherheitskennzeichnung, ...],
]:
    """Liest optionale Werte vor der Widget-Ausgabe für die zentrale Haupttabelle."""
    hinweise = []
    for eintrag in vorschlag.systematische_offene_eintraege:
        basis_key = f"schritt8_{fingerabdruck}_{eintrag.offener_eintrag_id}"
        hinweis = str(st.session_state.get(f"{basis_key}_anwenderhinweis", "")).strip()
        if st.session_state.get(f"{basis_key}_hinweis_sichtbar") and hinweis:
            hinweise.append(AnwenderhinweisFuerSchritt9(eintrag.offener_eintrag_id, hinweis))
    ausgewaehlt = st.session_state.get(f"schritt8_{fingerabdruck}_unsicher", [])
    unsicherheiten = tuple(
        FachlicheUnsicherheitskennzeichnung(
            ModellbestandteilId(str(bestandteil_roh)),
            str(
                st.session_state.get(
                    f"schritt8_{fingerabdruck}_{bestandteil_roh}_unsicherheitshinweis", ""
                )
            ),
        )
        for bestandteil_roh in ausgewaehlt
    )
    return tuple(hinweise), unsicherheiten


def _ergebnisuebersicht(vorschau: Modellableitungsvorschau) -> None:
    zaehler = {status: 0 for status in Bestandteilstatus}
    for bestandteil in vorschau.bestandteile:
        zaehler[bestandteil.status] += 1
    spalten = st.columns(5)
    spalten[0].metric("Vollständig", zaehler[Bestandteilstatus.VOLLSTAENDIG_ZUGEORDNET])
    spalten[1].metric("Teilweise offen", zaehler[Bestandteilstatus.TEILWEISE_OFFEN])
    spalten[2].metric("Offen", zaehler[Bestandteilstatus.OFFEN])
    spalten[3].metric("Fachlich unsicher", zaehler[Bestandteilstatus.FACHLICH_UNSICHER])
    spalten[4].metric("O-Punkte gesamt", len(vorschau.offene_eintraege))
    st.caption(f"{len(vorschau.bestandteile)} Modellbestandteile werden gemeinsam gespeichert.")


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
                "prueffingerabdruck": vorschau.prueffingerabdruck,
                "mappingversion": MAPPINGVERSION,
                "artefaktlineage": vorschau.grundlage.lineage,
                "zuordnungsdetails": vorschau.bestandteile,
            },
            expanded=False,
        )


def _roh_informationstext(informationen: list[dict[str, Any]]) -> str:
    if not informationen:
        return "Keine sicher ableitbare Information"
    texte = [_wert_text(wert.get("wert")) for wert in informationen]
    if len(texte) > 2:
        return "; ".join(texte[:2]) + f"; sowie {len(texte) - 2} weitere"
    return "; ".join(texte)


def _gespeicherte_ableitung(
    service: ModellableitungService, ableitungs_id: UUID, projekt_id: UUID
) -> None:
    ableitung, k, o = service.laden(ableitungs_id)
    if ableitung.projekt_id != projekt_id:
        raise Domaenenfehler("Die aktive Modellableitung gehört nicht zum aktiven Projekt.")
    st.success("Die Zuordnungen wurden bestätigt; K und O sind gespeichert und erneut validiert.")
    offene = o.get("offene_eintraege", [])
    offene_nach_bestandteil: dict[str, list[dict[str, Any]]] = {}
    for eintrag in offene:
        offene_nach_bestandteil.setdefault(str(eintrag.get("bestandteil_id")), []).append(eintrag)
    zeilen = []
    for bestandteil in k.get("modellbestandteile", []):
        bestandteil_id = str(bestandteil.get("bestandteil_id"))
        zugehoerige_offene = offene_nach_bestandteil.get(bestandteil_id, [])
        zeilen.append(
            {
                "Modellbestandteil": str(bestandteil.get("bezeichnung", bestandteil_id)),
                "Zugeordnete Information": _roh_informationstext(
                    bestandteil.get("informationen", [])
                ),
                "Quelle": ", ".join(bestandteil.get("verwendete_quellen", [])) or "–",
                "Status": _status_text(str(bestandteil.get("status", ""))),
                "Offene Punkte O": " · ".join(
                    str(eintrag.get("begruendung", "")) for eintrag in zugehoerige_offene
                )
                or "–",
            }
        )
    _tabelle_anzeigen(zeilen)
    zaehler = {
        status: sum(zeile["Status"] == _status_text(status) for zeile in zeilen)
        for status in (
            "vollstaendig_zugeordnet",
            "teilweise_offen",
            "offen",
            "fachlich_unsicher",
        )
    }
    spalten = st.columns(5)
    spalten[0].metric("Vollständig", zaehler["vollstaendig_zugeordnet"])
    spalten[1].metric("Teilweise offen", zaehler["teilweise_offen"])
    spalten[2].metric("Offen", zaehler["offen"])
    spalten[3].metric("Fachlich unsicher", zaehler["fachlich_unsicher"])
    spalten[4].metric("O-Punkte gesamt", len(offene))
    st.caption(f"{len(zeilen)} Modellbestandteile in K")
    if offene:
        st.subheader("Gespeicherte offene Punkte für Schritt 9")
        for eintrag in offene:
            st.warning(
                f"{str(eintrag.get('bestandteil_id', '')).replace('_', ' ').capitalize()} · "
                f"{str(eintrag.get('kategorie', '')).replace('_', ' ')}: "
                f"{eintrag.get('begruendung', '')}"
            )
            if eintrag.get("anwenderhinweis"):
                st.info(f"Anwenderhinweis: {eintrag['anwenderhinweis']}")
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
    with st.expander("Technische Details", expanded=False):
        st.json(
            {
                "modellableitungs_id": str(ableitung.modellableitungs_id),
                "k_id": str(ableitung.k_id),
                "k_sha256": ableitung.k_sha256,
                "o_id": str(ableitung.o_id),
                "o_sha256": ableitung.o_sha256,
                "mappingversion": ableitung.mappingversion,
                "eingangslineage": k.get("eingangslineage"),
                "bestaetigt_am": k.get("bestaetigt_am"),
            },
            expanded=False,
        )


def zeige_modellableitung_seite(
    projekt_service: ProjektService, service: ModellableitungService
) -> None:
    """Zeigt Algorithmus 8 als prüfbare Zuordnung mit einer Gesamtbestätigung."""
    st.header("8 Modellbestandteile ableiten")
    st.write(
        "Vorhandene Informationen werden automatisch den 16 Modellbestandteilen zugeordnet. "
        "Sicher ableitbare Inhalte bilden K; fehlende, nicht ableitbare oder fachlich unsichere "
        "Punkte bleiben parallel in O und werden erst in Schritt 9 bearbeitet."
    )
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
    vorherige_hinweise: dict[str, str] = {}
    vorbefuellen = getattr(service, "vorherige_anwenderhinweise", None)
    if callable(vorbefuellen):
        try:
            vorherige_hinweise = cast(
                dict[str, str],
                vorbefuellen(projekt_id, aggregations_id, vorschlag),
            )
        except (Domaenenfehler, Importintegritaetsfehler, KeyError, TypeError, ValueError):
            vorherige_hinweise = {}
    for eintrag_id, hinweis in vorherige_hinweise.items():
        basis_key = f"schritt8_{basis.eingabefingerabdruck}_{eintrag_id}"
        st.session_state.setdefault(f"{basis_key}_hinweis_sichtbar", True)
        st.session_state.setdefault(f"{basis_key}_anwenderhinweis", hinweis)

    anwenderhinweise, unsicherheiten = _pruefwerte_aus_zustand(
        vorschlag, basis.eingabefingerabdruck
    )
    prueffingerabdruck = service.prueffingerabdruck(anwenderhinweise, unsicherheiten)
    modellableitungs_id = uuid5(
        aggregations_id, f"{basis.eingabefingerabdruck}:{prueffingerabdruck}"
    )
    try:
        vorschau = service.vorschau(
            projekt_id=projekt_id,
            aggregations_id=aggregations_id,
            modellableitungs_id=modellableitungs_id,
            k_id=uuid5(modellableitungs_id, "K"),
            o_id=uuid5(modellableitungs_id, "O"),
            anwenderhinweise=anwenderhinweise,
            unsicherheitskennzeichnungen=unsicherheiten,
        )
    except (Domaenenfehler, Importintegritaetsfehler, KeyError, TypeError) as fehler:
        st.error(f"Die K/O-Vorschau konnte nicht erzeugt werden: {fehler}")
        return
    st.subheader("Automatische Zuordnung")
    _tabelle_anzeigen(_tabellenzeilen(vorschau))
    _details_anzeigen(vorschau)
    _ergebnisuebersicht(vorschau)
    _optionale_pruefung(vorschlag, basis.eingabefingerabdruck)
    _technische_details(vorschau)
    if st.button(
        "Zuordnungen bestätigen, K und O speichern und zu Schritt 9",
        type="primary",
        width="stretch",
    ):
        try:
            bestaetigte_vorschau = service.vorschau(
                projekt_id=projekt_id,
                aggregations_id=aggregations_id,
                modellableitungs_id=modellableitungs_id,
                k_id=uuid5(modellableitungs_id, "K"),
                o_id=uuid5(modellableitungs_id, "O"),
                anwenderhinweise=anwenderhinweise,
                unsicherheitskennzeichnungen=unsicherheiten,
                bestaetigt_am=datetime.now(UTC),
            )
            ableitung = service.speichern(
                bestaetigte_vorschau,
                menschlich_bestaetigt=True,
            )
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
            schritt_abschliessen_und_weiter(aktueller_schritt=8, projekt_id=projekt_id)
        except (Domaenenfehler, Importintegritaetsfehler) as fehler:
            st.error(f"K und O konnten nicht gespeichert werden: {fehler}")
