# pyright: reportArgumentType=false
"""Framework-Schritt 3 als eigenständiger Wizard für semantisches Mapping."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
import streamlit as st

from framework_mvp.application.mapping_service import MappingService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Attributrolle,
    MappingModus,
    Mappingstatus,
    SemantischesMapping,
    Spaltenzuordnung,
    ZeitstempelZuordnung,
    ZusammengesetzteFallId,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt

MAPPING_SCHRITTE = (
    "Zwischendatensatz auswählen",
    "Struktur prüfen",
    "Mappingmodus wählen",
    "Rollen zuordnen",
    "Mapping validieren",
    "Mapping speichern",
)
MAPPING_KURZNAMEN = (
    "Datensatz",
    "Struktur",
    "Modus",
    "Zuordnung",
    "Validierung",
    "Speichern",
)


def _zustand(projekt_id: UUID) -> dict[str, Any]:
    zustaende = st.session_state.setdefault("mapping_wizard_zustaende", {})
    return zustaende.setdefault(str(projekt_id), {"schritt": 1})


def _fortschritt(schritt: int) -> None:
    zeige_kompakten_fortschritt(
        schritt=schritt,
        kurze_namen=MAPPING_KURZNAMEN,
        lange_namen=MAPPING_SCHRITTE,
    )


def _projekt_auswaehlen(service: ProjektService) -> UUID | None:
    projekte = service.projekte_auflisten()
    if not projekte:
        st.warning("Für das semantische Mapping muss zuerst ein Projekt angelegt werden.")
        return None
    ids = [str(wert.projekt_id) for wert in projekte]
    namen = {str(wert.projekt_id): wert.bezeichnung for wert in projekte}
    aktuelle_id = st.session_state.get("aktuelles_projekt_id")
    index = ids.index(aktuelle_id) if aktuelle_id in ids else 0
    auswahl = st.selectbox(
        "Aktuelles Projekt",
        ids,
        index=index,
        format_func=lambda wert: namen[wert],
        key="mapping_projektauswahl",
    )
    st.session_state.aktuelles_projekt_id = auswahl
    return UUID(auswahl)


def _datensatz_auswaehlen(
    service: TransformationsService, projekt_id: UUID, zustand: dict[str, Any]
) -> None:
    datensaetze = service.datensaetze_fuer_projekt(projekt_id)
    if not datensaetze:
        st.warning("In Framework-Schritt 2 muss zuerst ein Zwischendatensatz erzeugt werden.")
        return
    ids = [str(wert.zwischendatensatz_id) for wert in datensaetze]
    auswahl = st.selectbox("Zwischendatensatz", ids)
    zustand["datensatz_id"] = auswahl
    datensatz = next(wert for wert in datensaetze if str(wert.zwischendatensatz_id) == auswahl)
    st.write(f"{datensatz.zeilenanzahl} Zeilen · {datensatz.spaltenanzahl} Spalten")


def _daten(service: MappingService, zustand: dict[str, Any]) -> pd.DataFrame:
    return service.datensatz_laden(UUID(zustand["datensatz_id"]))


def _struktur(service: MappingService, zustand: dict[str, Any]) -> None:
    daten = _daten(service, zustand)
    st.dataframe(daten.head(200), width="stretch")
    st.dataframe(
        pd.DataFrame(
            {
                "Spalte": [str(wert) for wert in daten.columns],
                "Technischer Datentyp": [str(wert) for wert in daten.dtypes],
                "Fehlende Werte": [int(daten[wert].isna().sum()) for wert in daten.columns],
            }
        ),
        hide_index=True,
    )


def _modus(zustand: dict[str, Any]) -> None:
    modus = st.radio(
        "Struktur des Zwischendatensatzes",
        list(MappingModus),
        format_func=lambda wert: (
            "Ereignisorientiert: eine Zeile entspricht einem Ereignis"
            if wert is MappingModus.EREIGNISORIENTIERT
            else "Breiter Zeitstempeldatensatz: mehrere Ereigniszeitpunkte je Zeile"
        ),
    )
    zustand["modus"] = modus


def _rollen(service: MappingService, zustand: dict[str, Any]) -> None:
    daten = _daten(service, zustand)
    spalten = [str(wert) for wert in daten.columns]
    fall_id = st.multiselect("Fall-ID-Spalte(n)", spalten)
    trennzeichen = st.text_input("Trennzeichen für zusammengesetzte Fall-ID", value="|")
    modus = zustand["modus"]
    aktivitaet = ""
    zeitstempel = ""
    startzeitstempel = ""
    endzeitstempel = ""
    lifecycle = ""
    zeitzuordnungen: tuple[ZeitstempelZuordnung, ...] = ()
    if modus is MappingModus.EREIGNISORIENTIERT:
        aktivitaet = st.selectbox("Aktivitätsspalte", ["", *spalten])
        zeitstempel = st.selectbox("Ereigniszeitstempel", ["", *spalten])
        startzeitstempel = st.selectbox("Startzeitpunkt (optional)", ["", *spalten])
        endzeitstempel = st.selectbox("Endzeitpunkt (optional)", ["", *spalten])
        lifecycle = st.selectbox("Lifecycle-Status (optional)", ["", *spalten])
    else:
        zeitspalten = st.multiselect("Zeitstempelspalten", spalten)
        zeitzuordnungen = tuple(
            ZeitstempelZuordnung(wert, wert.replace("_", " ")) for wert in zeitspalten
        )
    ressourcen = st.selectbox("Ressourcenspalte (optional)", ["", *spalten])
    standardspalten = {
        *fall_id,
        aktivitaet,
        zeitstempel,
        startzeitstempel,
        endzeitstempel,
        lifecycle,
        ressourcen,
    }
    standardspalten.update(wert.zeitstempelspalte for wert in zeitzuordnungen)
    zuordnungen = tuple(
        Spaltenzuordnung(
            wert,
            st.selectbox(
                f"Rolle für {wert}",
                list(Attributrolle),
                format_func=lambda rolle: rolle.value,
                key=f"mapping_rolle_{zustand['datensatz_id']}_{wert}",
            ),
        )
        for wert in spalten
        if wert not in standardspalten
    )
    jetzt = datetime.now(UTC)
    bestehend = zustand.get("mapping")
    mapping = SemantischesMapping(
        bestehend.mapping_id if bestehend else uuid4(),
        UUID(st.session_state.aktuelles_projekt_id),
        UUID(zustand["datensatz_id"]),
        modus,
        ZusammengesetzteFallId(tuple(fall_id), trennzeichen),
        aktivitaet,
        zeitstempel,
        startzeitstempel,
        endzeitstempel,
        lifecycle,
        ressourcen,
        zuordnungen,
        zeitzuordnungen,
        None,
        bestehend.erstellt_am if bestehend else jetzt,
        jetzt,
        Mappingstatus.ENTWURF,
    )
    zustand["mapping"] = mapping
    st.caption(
        f"{len(zuordnungen)} weitere Spalten werden zunächst als "
        f"{Attributrolle.EREIGNISATTRIBUT.value} geführt."
    )


def _validieren(service: MappingService, zustand: dict[str, Any]) -> None:
    mapping, ergebnis = service.validieren(zustand["mapping"], _daten(service, zustand))
    zustand["mapping"] = mapping
    zustand["mapping_ergebnis"] = ergebnis
    for warnung in ergebnis.validierung.warnungen:
        (st.error if warnung.stufe.value == "Fehler" else st.warning)(warnung.meldung)
    st.dataframe(ergebnis.vorschau, width="stretch")
    st.write(
        f"**Fälle:** {ergebnis.validierung.unterschiedliche_faelle} · "
        f"**Aktivitäten:** {ergebnis.validierung.unterschiedliche_aktivitaeten}"
    )


def _speichern(service: MappingService, zustand: dict[str, Any]) -> None:
    mapping = zustand["mapping"]
    if mapping.status is not Mappingstatus.VALIDIERT:
        st.error("Nur ein gültig validiertes Mapping kann gespeichert werden.")
        return
    if st.button("Semantisches Mapping speichern", type="primary"):
        zustand["mapping_pfad"] = service.speichern(mapping)
    if pfad := zustand.get("mapping_pfad"):
        st.success("Das semantische Mapping wurde gespeichert.")
        st.write(f"**Mapping-ID:** `{mapping.mapping_id}`")
        st.write(f"**Konfigurationsdatei:** `{pfad}`")


def _navigation(zustand: dict[str, Any]) -> None:
    schritt = zustand["schritt"]
    voraussetzungen = {
        1: bool(zustand.get("datensatz_id")),
        2: bool(zustand.get("datensatz_id")),
        3: "modus" in zustand,
        4: "mapping" in zustand,
        5: getattr(zustand.get("mapping"), "status", None) is Mappingstatus.VALIDIERT,
    }
    zurueck, weiter = st.columns(2)
    if zurueck.button("Zurück", disabled=schritt == 1, width="stretch"):
        zustand["schritt"] -= 1
        st.rerun()
    if weiter.button(
        "Weiter",
        disabled=schritt == len(MAPPING_SCHRITTE) or not voraussetzungen.get(schritt, False),
        type="primary",
        width="stretch",
    ):
        zustand["schritt"] += 1
        st.rerun()


def zeige_semantisches_mapping(
    projekt_service: ProjektService,
    transformations_service: TransformationsService,
    mapping_service: MappingService,
) -> None:
    """Zeigt Framework-Schritt 3 mit projektbezogenem, stabilem Wizard-Zustand."""
    st.header("3 Semantisches Mapping")
    st.write(
        "Ordnen Sie die technischen Spalten eines Zwischendatensatzes fachlichen "
        "Ereignis- und Attributrollen zu. Es wird noch kein Event Log erzeugt."
    )
    try:
        projekt_id = _projekt_auswaehlen(projekt_service)
        if projekt_id is None:
            return
        zustand = _zustand(projekt_id)
        _fortschritt(zustand["schritt"])
        aktionen = {
            1: lambda: _datensatz_auswaehlen(transformations_service, projekt_id, zustand),
            2: lambda: _struktur(mapping_service, zustand),
            3: lambda: _modus(zustand),
            4: lambda: _rollen(mapping_service, zustand),
            5: lambda: _validieren(mapping_service, zustand),
            6: lambda: _speichern(mapping_service, zustand),
        }
        aktionen[zustand["schritt"]]()
        _navigation(zustand)
    except (Domaenenfehler, Importintegritaetsfehler) as fehler:
        st.error(str(fehler))
