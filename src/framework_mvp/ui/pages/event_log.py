"""Framework-Schritt 4: fallbezogenen Event Log E aufbauen."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
import streamlit as st

from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.event_log import EventLogErgebnis, erzeuge_event_log
from framework_mvp.application.event_log_service import EventLogService
from framework_mvp.application.mapping_service import EventLogKonfigurationService
from framework_mvp.application.mappingtabelle_service import MappingtabelleService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    Attributrolle,
    MappingModus,
    Mappingstatus,
    Mappingtabelle,
    SemantischesMapping,
    Spaltenzuordnung,
    ZeitstempelZuordnung,
    ZusammengesetzteFallId,
    Zwischendatensatz,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt
from framework_mvp.ui.navigation import framework_bereich_oeffnen, schritt_abschliessen_und_weiter
from framework_mvp.ui.pages.semantisches_mapping import (
    _aktiven_datensatz_laden,
    _datensatzkontext,
    _projektkontext,
)

SCHRITTE = (
    "Strukturart festlegen",
    "Mindestbestandteile konfigurieren",
    "Zusätzliche Attribute auswählen",
    "Event Log erzeugen und prüfen",
    "Event Log ausgeben und speichern",
)
KURZ = ("Struktur", "Mindestbestandteile", "Attribute", "Erzeugen", "Ausgabe E")


def _folgeergebnisse_verwerfen(zustand: dict[str, Any]) -> None:
    """Verwirft bei geänderter Eingabe ausschließlich daraus abgeleitete Ergebnisse."""
    for schluessel in ("konfiguration", "ergebnis", "artefakt", "event_log_id"):
        zustand.pop(schluessel, None)


def _zustand(projekt_id: UUID, datensatz_id: UUID) -> dict[str, Any]:
    zustaende = st.session_state.setdefault("event_log_zustaende", {})
    zustand = zustaende.setdefault(str(projekt_id), {})
    if zustand.get("datensatz_id") != str(datensatz_id):
        zustand.clear()
        zustand.update(
            {
                "schritt": 1,
                "datensatz_id": str(datensatz_id),
                "konfigurations_id": uuid4(),
                "erstellt_am": datetime.now(UTC),
                "zusaetzliche_attribute": (),
            }
        )
    return zustand


def _spaltenlabel(mapping: Mappingtabelle | None, spalte: str) -> str:
    if mapping is None:
        return spalte
    fachlich = mapping.fachliche_spaltenbezeichnung(spalte)
    return spalte if fachlich == spalte else f"{fachlich} ({spalte})"


def _mapping_anzeigen(mapping: Mappingtabelle | None) -> None:
    st.write("### Semantische Sicht aus Schritt 3")
    if mapping is None:
        st.info("Es ist kein M vorhanden; technische Bezeichnungen werden direkt verwendet.")
    elif mapping.kein_mapping_erforderlich:
        st.info("M ist bestätigt leer; technische Bezeichnungen bleiben unverändert.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Art": e.art.value,
                        "Technische Bezeichnung": e.technische_bezeichnung,
                        "Fachliche Bezeichnung": e.fachliche_bezeichnung,
                        "Technische Quellspalte": e.technische_quellspalte or "–",
                    }
                    for e in mapping.eintraege
                ]
            ),
            hide_index=True,
            width="stretch",
        )


def _struktur(
    zustand: dict[str, Any],
    projekt_id: UUID,
    datensatz_id: UUID,
    service: EventLogKonfigurationService,
) -> bool:
    _folgeergebnisse_verwerfen(zustand)
    optionen = (MappingModus.EREIGNISORIENTIERT, MappingModus.BREITER_ZEITSTEMPELDATENSATZ)
    zustand["mapping_modus"] = st.radio(
        "Wie sind die Ereignisse in T dargestellt?",
        optionen,
        index=optionen.index(zustand.get("mapping_modus", optionen[0])),
        format_func=lambda w: (
            "Eine Zeile beschreibt genau ein Ereignis"
            if w is MappingModus.EREIGNISORIENTIERT
            else "Eine Zeile enthält mehrere Ereigniszeitpunkte"
        ),
        key=f"event_struktur_{datensatz_id}",
    )
    bestehende = [
        w for w in service.fuer_projekt(projekt_id) if w.zwischendatensatz_id == datensatz_id
    ]
    if bestehende:
        with st.expander("Gespeicherte Konfiguration für exakt dieses T wiederaufnehmen"):
            auswahl = st.selectbox(
                "Event-Log-Konfiguration wiederaufnehmen",
                [w.mapping_id for w in bestehende],
            )
            if st.button("Gespeicherte Konfiguration verwenden"):
                zustand["konfiguration"] = next(w for w in bestehende if w.mapping_id == auswahl)
                zustand["konfigurations_id"] = auswahl
                zustand["schritt"] = 4
                st.rerun()
    return True


def _aktivitaetsquellen(
    spalten: list[str], mapping: Mappingtabelle | None, zustand: dict[str, Any]
) -> tuple[str, ...]:
    if len(spalten) < 2:
        st.error(
            "Für eine zusammengesetzte Aktivität benötigt T mindestens zwei auswählbare Spalten."
        )
        zustand["aktivitaetsquellen"] = ()
        return ()
    anzahl = int(
        st.number_input(
            "Anzahl der Aktivitätsbestandteile",
            min_value=2,
            max_value=max(2, min(10, len(spalten))),
            value=2,
            key=f"event_aktivitaetsanzahl_{zustand['datensatz_id']}",
        )
    )
    auswahl: list[str] = []
    for position in range(anzahl):
        optionen = [w for w in spalten if w not in auswahl]
        if not optionen:
            break
        auswahl.append(
            st.selectbox(
                f"{position + 1}. Bestandteil",
                optionen,
                format_func=lambda w: _spaltenlabel(mapping, w),
                key=(f"event_aktivitaetsbestandteil_{zustand['datensatz_id']}_{position}"),
            )
        )
    zustand["aktivitaetsquellen"] = tuple(auswahl)
    return tuple(auswahl)


def _mindestbestandteile(
    daten: pd.DataFrame, mapping: Mappingtabelle | None, zustand: dict[str, Any]
) -> bool:
    _folgeergebnisse_verwerfen(zustand)
    spalten = [str(w) for w in daten.columns]
    datensatz_id = zustand["datensatz_id"]

    def label(wert: str) -> str:
        return _spaltenlabel(mapping, wert)

    zustand["fall_id"] = st.selectbox(
        "Fallidentifikation",
        spalten,
        format_func=label,
        key=f"event_fall_id_{datensatz_id}",
    )
    modus: MappingModus = zustand["mapping_modus"]
    if modus is MappingModus.EREIGNISORIENTIERT:
        art = st.radio(
            "Aktivitätsbeschreibung",
            ("Vorhandene Spalte", "Aus mehreren Attributen zusammensetzen"),
            key=f"event_aktivitaetsart_{datensatz_id}",
        )
        if art == "Vorhandene Spalte":
            zustand["aktivitaetsquellen"] = (
                st.selectbox(
                    "Aktivitätsspalte",
                    spalten,
                    format_func=label,
                    key=f"event_aktivitaetsspalte_{datensatz_id}",
                ),
            )
            zustand["verknuepfungselement"] = ""
        else:
            if len(_aktivitaetsquellen(spalten, mapping, zustand)) < 2:
                return False
            zustand["verknuepfungselement"] = st.text_input(
                "Verknüpfungselement (optional)",
                value=" → ",
                key=f"event_verknuepfung_{datensatz_id}",
            )
        zustand["zeitstempelspalte"] = st.selectbox(
            "Ereigniszeitstempel",
            spalten,
            format_func=label,
            key=f"event_zeitstempel_{datensatz_id}",
        )
        zustand["zeitstempelzuordnungen"] = ()
        return True
    zeitspalten = tuple(
        st.multiselect(
            "Relevante Zeitstempelspalten",
            spalten,
            format_func=label,
            key=f"event_breite_zeitspalten_{datensatz_id}",
        )
    )
    zuordnungen = tuple(
        ZeitstempelZuordnung(
            spalte,
            st.text_input(
                f"Aktivitätsbeschreibung für {label(spalte)}",
                key=f"event_breite_aktivitaet_{datensatz_id}_{position}_{spalte}",
            ),
        )
        for position, spalte in enumerate(zeitspalten)
    )
    zustand["zeitstempelzuordnungen"] = zuordnungen
    zustand["zeitstempelspalte"] = ""
    zustand["aktivitaetsquellen"] = ()
    if not zeitspalten:
        st.info("Wählen Sie mindestens eine relevante Zeitstempelspalte.")
        return False
    if any(not w.aktivitaetsbezeichnung for w in zuordnungen):
        st.info("Jede Zeitstempelspalte benötigt eine Aktivitätsbeschreibung.")
        return False
    return True


def _attribute(
    daten: pd.DataFrame, mapping: Mappingtabelle | None, zustand: dict[str, Any]
) -> bool:
    _folgeergebnisse_verwerfen(zustand)
    kern = {
        zustand["fall_id"],
        zustand.get("zeitstempelspalte", ""),
        *zustand.get("aktivitaetsquellen", ()),
        *(w.zeitstempelspalte for w in zustand.get("zeitstempelzuordnungen", ())),
    }
    optionen = [str(w) for w in daten.columns if str(w) not in kern]
    zustand["zusaetzliche_attribute"] = tuple(
        st.multiselect(
            "Weitere Attribute in E übernehmen",
            optionen,
            default=[w for w in zustand.get("zusaetzliche_attribute", ()) if w in optionen],
            format_func=lambda w: _spaltenlabel(mapping, w),
            key=f"event_zusatzattribute_{zustand['datensatz_id']}",
        )
    )
    if not zustand["zusaetzliche_attribute"]:
        st.info("Es werden keine zusätzlichen Attribute übernommen.")
    return True


def _konfiguration(
    projekt_id: UUID,
    datensatz_id: UUID,
    mapping: Mappingtabelle | None,
    zustand: dict[str, Any],
) -> SemantischesMapping:
    modus: MappingModus = zustand["mapping_modus"]
    definition = None
    aktivitaetsspalte = ""
    if modus is MappingModus.EREIGNISORIENTIERT:
        quellen = tuple(zustand["aktivitaetsquellen"])
        if len(quellen) == 1:
            aktivitaetsspalte = quellen[0]
            definition = Aktivitaetsdefinition(Aktivitaetsbildungsart.VORHANDENE_SPALTE, quellen)
        else:
            definition = Aktivitaetsdefinition(
                Aktivitaetsbildungsart.ZUSAMMENGESETZT,
                quellen,
                zustand.get("verknuepfungselement", ""),
                fehlwertstrategie="Ergebnis leer lassen",
            )
    jetzt = datetime.now(UTC)
    return SemantischesMapping(
        zustand["konfigurations_id"],
        projekt_id,
        datensatz_id,
        modus,
        ZusammengesetzteFallId((zustand["fall_id"],)),
        aktivitaetsspalte,
        zustand.get("zeitstempelspalte", ""),
        "",
        "",
        "",
        "",
        tuple(
            Spaltenzuordnung(w, Attributrolle.EREIGNISATTRIBUT)
            for w in zustand.get("zusaetzliche_attribute", ())
        ),
        tuple(zustand.get("zeitstempelzuordnungen", ())),
        None,
        zustand["erstellt_am"],
        jetzt,
        Mappingstatus.ENTWURF,
        definition,
        mapping.mapping_id if mapping is not None else None,
        2,
    )


def _fachspalten(ergebnis: EventLogErgebnis) -> list[str]:
    return [
        w
        for w in ergebnis.ereignisse.columns
        if w in {"case_id", "activity", "timestamp"} or w in ergebnis.attributherkunft
    ]


def _ergebnis(
    ergebnis: EventLogErgebnis,
    konfiguration: SemantischesMapping,
    projektname: str,
    datensatz: Zwischendatensatz,
    mapping: Mappingtabelle | None,
) -> None:
    definition = konfiguration.wirksame_aktivitaetsdefinition
    if definition is None:
        aktivitaetstext = "je Zeitstempelspalte"
    elif definition.bildungsart is Aktivitaetsbildungsart.VORHANDENE_SPALTE:
        aktivitaetstext = _spaltenlabel(mapping, definition.quellspalten[0])
    else:
        quellen = " · ".join(_spaltenlabel(mapping, wert) for wert in definition.quellspalten)
        aktivitaetstext = f"{quellen} (Verknüpfungselement: {definition.trennzeichen!r})"
    zeitquellen = (
        _spaltenlabel(mapping, konfiguration.zeitstempelspalte)
        if konfiguration.mapping_modus is MappingModus.EREIGNISORIENTIERT
        else ", ".join(
            _spaltenlabel(mapping, wert.zeitstempelspalte)
            for wert in konfiguration.zeitstempelzuordnungen
        )
    )
    mappingtext = (
        "nicht vorhanden"
        if mapping is None
        else "bestätigt leer"
        if mapping.kein_mapping_erforderlich
        else str(mapping.mapping_id)
    )
    st.write("### Fallbezogener Event Log (E)")
    st.write(
        f"**Projekt:** {projektname}  \n"
        f"**Zwischendatensatz T:** {datensatz.zwischendatensatz_id}  \n"
        f"**Mappingtabelle M:** {mappingtext}  \n"
        f"**Strukturart:** {konfiguration.mapping_modus.value}  \n"
        f"**Fallidentifikation:** "
        f"{_spaltenlabel(mapping, konfiguration.fall_id.spalten[0])}  \n"
        f"**Aktivitätsbeschreibung:** {aktivitaetstext}  \n"
        f"**Zeitstempelquelle(n):** {zeitquellen}  \n"
        f"**Zusätzliche Attribute:** "
        f"{', '.join(ergebnis.attributherkunft) or 'keine'}"
    )
    st.dataframe(
        pd.DataFrame(
            [
                ("Ereignisse", ergebnis.ereignisanzahl),
                ("Fälle", ergebnis.fallanzahl),
                ("Unterschiedliche Aktivitäten", ergebnis.aktivitaetsanzahl),
                ("Frühester Zeitpunkt", ergebnis.fruehester_zeitpunkt),
                ("Spätester Zeitpunkt", ergebnis.spaetester_zeitpunkt),
            ],
            columns=["Kennzahl", "Wert"],
        ).astype("string"),
        hide_index=True,
        width="stretch",
    )
    st.dataframe(ergebnis.ereignisse.loc[:, _fachspalten(ergebnis)].head(200), width="stretch")
    with st.expander("Technische Herkunft und Lineage"):
        st.json(ergebnis.herkunft_standardspalten)
        st.json(ergebnis.attributherkunft)
        technische = [
            w for w in ergebnis.ereignisse.columns if str(w).startswith("_") or w == "event_id"
        ]
        st.dataframe(ergebnis.ereignisse.loc[:, technische].head(200), width="stretch")
    for warnung in ergebnis.warnungen:
        st.warning(warnung)
    st.info("Die abschließende Qualitätsprüfung und Freigabe erfolgt erst in Schritt 5.")


def _erzeugen(
    service: EventLogKonfigurationService,
    projekt_id: UUID,
    projektname: str,
    datensatz: Zwischendatensatz,
    daten: pd.DataFrame,
    mapping: Mappingtabelle | None,
    zustand: dict[str, Any],
) -> bool:
    konfiguration = zustand.get("konfiguration")
    if konfiguration is None:
        konfiguration = _konfiguration(projekt_id, datensatz.zwischendatensatz_id, mapping, zustand)
        konfiguration, pruefung = service.validieren(konfiguration, daten.copy(deep=True))
        if not pruefung.validierung.gueltig:
            for warnung in pruefung.validierung.warnungen:
                if warnung.stufe.value == "Fehler":
                    st.error(warnung.meldung)
            return False
        service.speichern(konfiguration)
        zustand["konfiguration"] = konfiguration
        st.session_state.aktuelle_event_log_konfiguration_id = str(konfiguration.mapping_id)
    ergebnis = erzeuge_event_log(
        daten.copy(deep=True),
        konfiguration,
        datensatz.zwischendatensatz_id,
        mapping,
    )
    zustand["ergebnis"] = ergebnis
    _ergebnis(ergebnis, konfiguration, projektname, datensatz, mapping)
    return True


def _speichern(
    service: EventLogService,
    projekt_id: UUID,
    projektname: str,
    datensatz: Zwischendatensatz,
    mapping: Mappingtabelle | None,
    zustand: dict[str, Any],
) -> None:
    konfiguration = zustand["konfiguration"]
    _ergebnis(zustand["ergebnis"], konfiguration, projektname, datensatz, mapping)
    event_log_id = zustand.setdefault("event_log_id", uuid4())
    artefakt = zustand.get("artefakt")
    if artefakt is None and st.button("Event Log E reproduzierbar speichern", type="primary"):
        zustand["artefakt"] = service.speichern(event_log_id, konfiguration.mapping_id)
        st.session_state.aktuelles_event_log_id = str(event_log_id)
        st.session_state.event_log_id = event_log_id
        st.rerun()
    elif artefakt is not None:
        st.success("Der fallbezogene Event Log (E) wurde gespeichert.")
        st.write(f"**CSV.GZ:** {artefakt.relativer_csv_pfad}")
        st.write(f"**Schema:** {artefakt.relativer_schema_pfad}")
        st.write(f"**Lineage:** {artefakt.relativer_lineage_pfad}")
        if st.button("Weiter zu Schritt 5: Datenqualität prüfen"):
            schritt_abschliessen_und_weiter(aktueller_schritt=4, projekt_id=projekt_id)


def _navigation(zustand: dict[str, Any], weiter: bool) -> None:
    links, rechts = st.columns(2)
    if links.button("Zurück", disabled=zustand["schritt"] == 1, width="stretch"):
        zustand["schritt"] -= 1
        st.rerun()
    if rechts.button(
        "Weiter",
        disabled=zustand["schritt"] == len(SCHRITTE) or not weiter,
        type="primary",
        width="stretch",
    ):
        zustand["schritt"] += 1
        st.rerun()


def zeige_event_log_seite(
    projekt_service: ProjektService,
    konfigurations_service: EventLogKonfigurationService,
    mappingtabelle_service: MappingtabelleService,
    transformations_service: TransformationsService,
    event_log_service: EventLogService,
    datenquelle_service: DatenquelleService | None = None,
) -> None:
    """Setzt Pseudocode 4 für den zentralen Projekt- und T-Kontext um."""
    st.header("4 Event Log aufbauen")
    try:
        projektkontext = _projektkontext(projekt_service)
        if projektkontext is None:
            return
        projekt_id, projektname = projektkontext
        geladen = _aktiven_datensatz_laden(transformations_service, projekt_id)
        if geladen is None:
            st.warning("Für das aktuelle Projekt ist kein konsistenter T vorhanden.")
            if st.button("Zurück zu ETL", type="primary"):
                framework_bereich_oeffnen(schritt=2, projekt_id=projekt_id)
            return
        datensatz, daten = geladen
        _datensatzkontext(transformations_service, datenquelle_service, datensatz)
        zustand = _zustand(projekt_id, datensatz.zwischendatensatz_id)
        mapping = mappingtabelle_service.fuer_datensatz(projekt_id, datensatz.zwischendatensatz_id)
        gespeicherte_konfiguration = zustand.get("konfiguration")
        if gespeicherte_konfiguration is not None:
            if gespeicherte_konfiguration.konfigurationsversion < 2:
                # Altbestände entstanden vor der getrennten Mappingtabelle M.
                mapping = None
            else:
                gespeicherte_mapping_id = gespeicherte_konfiguration.mappingtabelle_id
                if gespeicherte_mapping_id is None:
                    mapping = None
                elif mapping is None or mapping.mapping_id != gespeicherte_mapping_id:
                    mapping = mappingtabelle_service.laden(gespeicherte_mapping_id)
                    if mapping is None:
                        raise Importintegritaetsfehler(
                            "Die von der Event-Log-Konfiguration referenzierte Mappingtabelle M "
                            "wurde nicht gefunden."
                        )
        _mapping_anzeigen(mapping)
        st.write("### Unveränderte Vorschau des Zwischendatensatzes T")
        st.dataframe(daten.head(100), width="stretch")
        zeige_kompakten_fortschritt(
            schritt=zustand["schritt"], kurze_namen=KURZ, lange_namen=SCHRITTE
        )
        weiter = False
        if zustand["schritt"] == 1:
            weiter = _struktur(
                zustand,
                projekt_id,
                datensatz.zwischendatensatz_id,
                konfigurations_service,
            )
        elif zustand["schritt"] == 2:
            weiter = _mindestbestandteile(daten, mapping, zustand)
        elif zustand["schritt"] == 3:
            weiter = _attribute(daten, mapping, zustand)
        elif zustand["schritt"] == 4:
            weiter = _erzeugen(
                konfigurations_service,
                projekt_id,
                projektname,
                datensatz,
                daten,
                mapping,
                zustand,
            )
        else:
            _speichern(
                event_log_service,
                projekt_id,
                projektname,
                datensatz,
                mapping,
                zustand,
            )
        _navigation(zustand, weiter)
    except (Domaenenfehler, Importintegritaetsfehler) as fehler:
        st.error(str(fehler))
