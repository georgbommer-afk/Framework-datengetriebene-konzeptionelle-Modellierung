"""Framework-Schritt 8: belegte Zuordnung zu K und offenen Bestandteilen O."""

from collections import Counter
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
import streamlit as st

from framework_mvp.application.modellableitung import MODELLBESTANDTEILE
from framework_mvp.application.modellableitung_service import (
    ModellableitungService,
    Modellableitungsvorschau,
)
from framework_mvp.application.process_mining.svg import validiere_svg_text
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Bestandteilstatus,
    Eingangsartefakt,
    ModellbestandteilId,
    Offenheitskategorie,
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


def _eingangsartefakte(basis: Any) -> None:
    st.subheader("1. Validierte Eingangsartefakte")
    st.success(
        "Die aktive, projektgebundene Lineage U, S, Q, R, T, E*, P und A_G wurde erneut "
        "vollständig validiert."
    )
    st.write(f"**Aktives Projekt:** {basis.projekt.bezeichnung} (`{basis.projekt.projekt_id}`)")
    spalten = st.columns(4)
    spalten[0].metric("Ereignisse", len(basis.event_log))
    spalten[1].metric("Fälle", basis.event_log["case_id"].nunique(dropna=True))
    spalten[2].metric("Aktivitäten", basis.event_log["activity"].nunique(dropna=True))
    spalten[3].metric("Notation P", basis.prozessnotation.bezeichnung)
    zeitraum_von = basis.event_log["timestamp"].min()
    zeitraum_bis = basis.event_log["timestamp"].max()
    st.caption(f"Zeitraum E*: {zeitraum_von} bis {zeitraum_bis}")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Artefakt": name,
                    "ID": referenz["id"],
                    "Prüfsumme": referenz["sha256"],
                    "Integrität": "gültig",
                }
                for name, referenz in basis.lineage["artefakte"].items()
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        f"A_G `{basis.aggregation.aggregations_id}` · Analyse `{basis.analyse.analyse_id}` · "
        f"Freigabe `{basis.freigabe.freigabe_id}` · E* `{basis.freigabe.event_log_id}`"
    )
    p_sha256 = basis.quellreferenzen[Eingangsartefakt.PROZESSMODELL_P]["sha256"]
    st.code(
        f"A_G: {basis.aggregation.aggregations_sha256}\n"
        f"P:   {p_sha256}\n"
        f"E*:  {basis.freigabe.event_log_sha256}",
        language=None,
    )
    svg = basis.discovery_ergebnisse.get("svg_texte", {}).get("modell_svg")
    if svg:
        try:
            st.image(
                validiere_svg_text(svg),
                caption=f"Unverändertes Prozessmodell P ({basis.prozessnotation.bezeichnung})",
                width="stretch",
            )
        except Exception as fehler:  # pragma: no cover - UI-/Rendererabhängig
            st.warning(
                "P kann nicht grafisch dargestellt werden; die strukturierte Ableitung bleibt "
                f"verfügbar: {fehler}"
            )
    else:
        st.info(
            "Für P ist keine gespeicherte SVG-Darstellung verfügbar. Das strukturierte "
            "Prozessmodell bleibt gültig und wird unverändert referenziert."
        )


def _zuordnung() -> frozenset[ModellbestandteilId]:
    st.subheader("2. Zuordnung gemäß Tabelle 3.15")
    st.caption(
        "Die Quellenmatrix ist fest. Schritt 8 erlaubt nur eine zusätzliche Kennzeichnung "
        "als fachlich unsicher, jedoch keine Ergänzung oder Änderung fachlicher Inhalte."
    )
    unsicher: set[ModellbestandteilId] = set()
    for index, definition in enumerate(MODELLBESTANDTEILE, 1):
        with st.expander(f"{index}. {definition.bezeichnung}"):
            st.write(
                "**Zulässige Quellen:** "
                + ", ".join(wert.value for wert in definition.zulaessige_quellen)
            )
            if definition.teilweise_offen:
                st.warning("Dieser Bestandteil ist gemäß Tabelle 3.15 teilweise offen.")
            if st.checkbox(
                "Vorhandene Zuordnung als fachlich unsicher kennzeichnen",
                key=f"modellableitung_unsicher_{definition.bestandteil_id.value}",
            ):
                unsicher.add(definition.bestandteil_id)
    return frozenset(unsicher)


def _bestandteile(vorschau: Modellableitungsvorschau) -> None:
    st.subheader("3. Vorschau des vorläufigen konzeptionellen Modells (K)")
    for index, bestandteil in enumerate(vorschau.bestandteile, 1):
        with st.expander(
            f"{index}. {bestandteil.bezeichnung} · {_status_text(bestandteil.status)}"
        ):
            st.write(
                "**Verwendete Quellen:** "
                + (", ".join(wert.value for wert in bestandteil.verwendete_quellen) or "keine")
            )
            if not bestandteil.informationen:
                st.info("Keine fachlich belastbare Information direkt ableitbar.")
            for information in bestandteil.informationen:
                st.markdown(
                    f"**{information.herkunftsartefakt.value} · "
                    f"`{information.strukturreferenz}`**  \n"
                    f"Übernahmeart: `{information.uebernahmeart.value}` · "
                    f"Artefakt-ID: `{information.herkunftsartefakt_id}`"
                )
                st.json(information.wert, expanded=False)
                st.caption(f"Quellprüfsumme: {information.herkunftsartefakt_sha256}")


def _offene(vorschau: Modellableitungsvorschau) -> None:
    st.subheader("4. Offene Bestandteile (O)")
    if not vorschau.offene_eintraege:
        st.success("Es wurden keine offenen Einträge erkannt.")
        return
    for eintrag in vorschau.offene_eintraege:
        st.warning(
            f"**{eintrag.bestandteil_id.value} · {eintrag.kategorie.value}:** {eintrag.begruendung}"
        )
        st.caption(
            f"Kennzeichnung: {eintrag.kennzeichnungsherkunft.value} · Status: {eintrag.status}"
        )
        if eintrag.belegreferenzen:
            st.json(eintrag.belegreferenzen, expanded=False)


def _zusammenfassung(vorschau: Modellableitungsvorschau) -> None:
    st.subheader("5. Bestätigung, Speicherung und Übergabe an Schritt 9")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Bestandteil": wert.bezeichnung,
                    "Status": _status_text(wert.status),
                    "Informationen": len(wert.informationen),
                    "Offene Einträge": len(wert.offene_eintrag_ids),
                }
                for wert in vorschau.bestandteile
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    kategorien = Counter(wert.kategorie.value for wert in vorschau.offene_eintraege)
    informationsanzahl = sum(len(wert.informationen) for wert in vorschau.bestandteile)
    st.write(f"Direkt zugeordnete Informationen: **{informationsanzahl}**")
    st.write(
        "Offene Einträge: "
        + ", ".join(
            f"{kategorie.value} **{kategorien.get(kategorie.value, 0)}**"
            for kategorie in Offenheitskategorie
        )
    )
    st.caption(
        f"Vorschau K `{vorschau.k_id}` · SHA-256 `{vorschau.k_sha256}`  \n"
        f"Vorschau O `{vorschau.o_id}` · SHA-256 `{vorschau.o_sha256}`"
    )
    warnungen = vorschau.grundlage.a_g.get("warnungen", [])
    if warnungen:
        st.warning("Warnungen aus A_G: " + " · ".join(str(wert) for wert in warnungen))
    else:
        st.caption("Vorhandene Warnungen: keine zusätzlichen Warnungen aus A_G.")
    with st.expander("Vollständige Eingangslineage"):
        st.json(vorschau.grundlage.lineage)


def _gespeicherte_ableitung(
    service: ModellableitungService, ableitungs_id: UUID, projekt_id: UUID
) -> None:
    ableitung, k, o = service.laden(ableitungs_id)
    if ableitung.projekt_id != projekt_id:
        raise Domaenenfehler("Die aktive Modellableitung gehört nicht zum aktiven Projekt.")
    st.success(f"K und O sind gespeichert und erneut validiert: Modellableitung {ableitungs_id}.")
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
    st.caption(
        f"K `{k['k_id']}` · `{ableitung.k_sha256}`  \nO `{o['o_id']}` · `{ableitung.o_sha256}`"
    )
    if st.button("Weiter zu Schritt 9: Modell ergänzen und validieren", type="primary"):
        framework_bereich_oeffnen(schritt=9, projekt_id=projekt_id)


def zeige_modellableitung_seite(
    projekt_service: ProjektService, service: ModellableitungService
) -> None:
    """Setzt Algorithmus 8 ohne lokale Artefaktauswahl oder fachliche Ergänzung um."""
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
    try:
        basis = service.grundlage_laden(projekt_id, aggregations_id)
    except (Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
        st.error(f"Die Eingangslineage von Schritt 8 ist ungültig: {fehler}")
        if st.button("Zurück zu Schritt 7: Ergebnisse aggregieren"):
            framework_bereich_oeffnen(schritt=7, projekt_id=projekt_id)
        return
    _eingangsartefakte(basis)
    unsicher = _zuordnung()
    if st.button("Vorschau von K und O erzeugen", type="primary"):
        try:
            st.session_state.modellableitung_vorschau = service.vorschau(
                projekt_id=projekt_id,
                aggregations_id=aggregations_id,
                modellableitungs_id=uuid4(),
                k_id=uuid4(),
                o_id=uuid4(),
                fachlich_unsichere_bestandteile=unsicher,
            )
        except (Domaenenfehler, Importintegritaetsfehler) as fehler:
            st.error(f"K und O konnten nicht abgeleitet werden: {fehler}")
    vorschau = st.session_state.get("modellableitung_vorschau")
    if isinstance(vorschau, Modellableitungsvorschau):
        veraltet = (
            vorschau.grundlage.projekt.projekt_id != projekt_id
            or vorschau.grundlage.aggregation.aggregations_id != aggregations_id
            or vorschau.grundlage.eingabefingerabdruck != basis.eingabefingerabdruck
            or vorschau.unsicherheitsfingerabdruck != service.unsicherheitsfingerabdruck(unsicher)
        )
        if veraltet:
            st.warning(
                "Projekt, Eingangsartefakte oder Unsicherheitskennzeichnungen haben sich "
                "geändert. Die Vorschau ist ungültig und muss neu berechnet werden."
            )
        _bestandteile(vorschau)
        _offene(vorschau)
        _zusammenfassung(vorschau)
        bestaetigt = st.checkbox(
            "Ich bestätige ausschließlich die nachvollziehbare Zuordnung und Speicherung; "
            "dies ist keine fachliche Validierung von K.",
            key="modellableitung_speichern_bestaetigt",
        )
        if st.button(
            "K und O speichern und zu Schritt 9",
            disabled=veraltet or not bestaetigt,
        ):
            try:
                ableitung = service.speichern(vorschau, menschlich_bestaetigt=bestaetigt)
                st.session_state.aktuelle_modellableitungs_id = str(ableitung.modellableitungs_id)
                st.session_state.aktuelle_k_id = str(ableitung.k_id)
                st.session_state.aktuelle_o_id = str(ableitung.o_id)
                framework_bereich_oeffnen(schritt=9, projekt_id=projekt_id)
            except (Domaenenfehler, Importintegritaetsfehler) as fehler:
                st.error(f"K und O konnten nicht gespeichert werden: {fehler}")
    gespeicherte_id = st.session_state.get("aktuelle_modellableitungs_id")
    if gespeicherte_id:
        try:
            _gespeicherte_ableitung(service, UUID(str(gespeicherte_id)), projekt_id)
        except (ValueError, Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            st.error(f"Die gespeicherte Modellableitung ist nicht mehr gültig: {fehler}")
