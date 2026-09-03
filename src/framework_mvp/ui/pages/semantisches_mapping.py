# pyright: reportArgumentType=false
"""Kompaktes semantisches Mapping des aktiven Zwischendatensatzes T."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
import streamlit as st

from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.mapping_service import MappingService
from framework_mvp.application.mappingtabelle_service import MappingtabelleService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.transformation import kombiniere_textspalten
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    Attributrolle,
    Ereignisrolle,
    Mappingeintrag,
    Mappingeintragsart,
    MappingModus,
    Mappingstatus,
    Mappingtabelle,
    Mappingtabellenstatus,
    SemantischesMapping,
    Spaltenzuordnung,
    Warnungsstufe,
    ZeitstempelZuordnung,
    ZusammengesetzteFallId,
    Zwischendatensatz,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.fortschritt import unterschritte_fuer
from framework_mvp.ui.helpers import fachliche_auswahl
from framework_mvp.ui.navigation import (
    framework_bereich_oeffnen,
    schritt_abschliessen_und_weiter,
    zeige_unterschritt_navigation,
)

MAPPING_SCHRITTE = unterschritte_fuer(3)

STANDARDROLLEN = (
    "Ressource",
    "Lifecycle",
    "Startzeitstempel",
    "Endzeitstempel",
    "Quell-Ereignis-ID",
)
ATTRIBUTGRUPPEN = {
    "ereignisattribute": (
        "Ereignisattribute",
        "Werte, die ein einzelnes Ereignis näher beschreiben und sich innerhalb "
        "eines Falls ändern können.",
        Attributrolle.EREIGNISATTRIBUT,
    ),
    "fallattribute": (
        "Fallattribute",
        "Werte, die den gesamten Auftrag oder Fall beschreiben und innerhalb "
        "eines Falls möglichst gleich bleiben.",
        Attributrolle.FALLATTRIBUT,
    ),
    "ressourcenattribute": (
        "Ressourcenattribute",
        "Zusätzliche Angaben über ausführende Personen, Maschinen oder Transporteinheiten.",
        Attributrolle.RESSOURCENATTRIBUT,
    ),
    "objektidentifikatoren": (
        "Objektidentifikatoren",
        "Weitere fachliche Objekte wie Ladeeinheit, Material oder Seriennummer.",
        Attributrolle.OBJEKTIDENTIFIKATOR,
    ),
}


def _zustand(projekt_id: UUID) -> dict[str, Any]:
    """Liefert den projektbezogenen Zustand des dreiteiligen Mapping-Ablaufs."""
    zustaende = st.session_state.setdefault("mapping_wizard_zustaende", {})
    return zustaende.setdefault(str(projekt_id), {"schritt": 1})


def _projektkontext(service: ProjektService) -> tuple[UUID, str] | None:
    """Lädt ausschließlich das zentral gewählte Projekt."""
    try:
        projekt_id = UUID(str(st.session_state.get("aktuelles_projekt_id")))
    except (TypeError, ValueError):
        st.warning("Bitte wählen oder erstellen Sie zuerst in Schritt 1 ein Projekt.")
        framework_bereich_oeffnen(schritt=1)
        return None
    projekt = service.projekt_laden(projekt_id)
    if projekt is None:
        st.warning("Das zentral gewählte Projekt ist nicht mehr vorhanden.")
        framework_bereich_oeffnen(schritt=1)
        return None
    st.write(f"**Aktuelles Projekt: {projekt.bezeichnung}**")
    return projekt_id, projekt.bezeichnung


def _aktiven_datensatz_laden(
    service: TransformationsService, projekt_id: UUID
) -> tuple[Zwischendatensatz, pd.DataFrame] | None:
    """Verwendet den Session-Datensatz oder den neuesten konsistenten Projekt-Datensatz."""
    datensaetze = service.datensaetze_fuer_projekt(projekt_id)
    nach_id = {str(wert.zwischendatensatz_id): wert for wert in datensaetze}
    kandidaten: list[Zwischendatensatz] = []
    session_id = str(st.session_state.get("aktueller_zwischendatensatz_id", ""))
    if session_id in nach_id:
        kandidaten.append(nach_id[session_id])
    kandidaten.extend(
        wert
        for wert in sorted(
            datensaetze,
            key=lambda eintrag: (eintrag.erstellt_am, str(eintrag.zwischendatensatz_id)),
            reverse=True,
        )
        if wert not in kandidaten
    )
    for datensatz in kandidaten:
        if datensatz.projekt_id != projekt_id:
            continue
        try:
            geladen, daten = service.zwischendatensatz_laden(datensatz.zwischendatensatz_id)
        except (Domaenenfehler, Importintegritaetsfehler):
            continue
        if geladen.projekt_id == projekt_id:
            st.session_state.aktueller_zwischendatensatz_id = str(geladen.zwischendatensatz_id)
            return geladen, daten
    return None


def _datensatzkontext(
    service: TransformationsService,
    datenquelle_service: DatenquelleService | None,
    datensatz: Zwischendatensatz,
) -> None:
    """Zeigt Herkunft und technische Identität des aktiven Datensatzes kompakt."""
    plan = service.plan_laden(datensatz.transformationsplan_id)
    importe = {wert.import_id: wert for wert in service.importe_fuer_projekt(datensatz.projekt_id)}
    hauptimport = importe.get(datensatz.import_ids[0])
    quelle = (
        datenquelle_service.datenquelle_laden(hauptimport.datenquellen_id)
        if datenquelle_service is not None and hauptimport is not None
        else None
    )
    bezeichnung = (
        f"{hauptimport.originaldateiname} · {hauptimport.tabellenbezeichnung}"
        if hauptimport
        else f"Zwischendatensatz vom {datensatz.erstellt_am:%d.%m.%Y}"
    )
    st.write(f"**Datengrundlage: {bezeichnung}**")
    st.caption(
        f"Datenquelle: {quelle.bezeichnung if quelle else 'nicht verfügbar'} · "
        f"Import: {hauptimport.originaldateiname if hauptimport else 'nicht verfügbar'} · "
        f"Tabelle: {hauptimport.tabellenbezeichnung if hauptimport else 'nicht verfügbar'} · "
        f"{datensatz.zeilenanzahl:,} Zeilen · {datensatz.spaltenanzahl:,} Spalten · "
        f"{sum(s.aktiviert for s in plan.schritte) if plan else 0} Transformationen · "
        f"erstellt am {datensatz.erstellt_am:%d.%m.%Y um %H:%M Uhr}"
    )
    with st.expander("Technische Details", expanded=False):
        st.write(f"Zwischendatensatz-ID: `{datensatz.zwischendatensatz_id}`")
        st.write(f"Transformationsplan-ID: `{datensatz.transformationsplan_id}`")
        st.write(f"Prüfsumme: `{datensatz.sha256}`")
        st.write(f"Schema: `{datensatz.relativer_schema_pfad}`")
    if st.button("Datengrundlage ändern", width="content"):
        framework_bereich_oeffnen(schritt=2, projekt_id=datensatz.projekt_id)


def _zeitspalten(daten: pd.DataFrame) -> list[str]:
    """Priorisiert Spalten mit überwiegend interpretierbaren Zeitwerten."""
    bewertungen = []
    for name in daten.columns:
        serie = daten[name]
        interpretierbar = pd.to_datetime(serie, errors="coerce", format="mixed").notna().mean()
        namensbonus = any(
            wort in str(name).casefold()
            for wort in ("zeit", "time", "datum", "date", "timestamp", "beginn", "ende")
        )
        bewertungen.append((str(name), float(interpretierbar), namensbonus))
    return [
        name
        for name, _, _ in sorted(
            bewertungen, key=lambda wert: (wert[2], wert[1], wert[0]), reverse=True
        )
    ]


def _struktur_vorschlagen(daten: pd.DataFrame) -> MappingModus:
    """Erzeugt einen unverbindlichen Strukturvorschlag aus Spaltennamen und Werten."""
    zeitgeeignet = sum(
        pd.to_datetime(daten[name], errors="coerce", format="mixed").notna().mean() >= 0.8
        for name in daten.columns
    )
    aktivitaet = any(
        wort in str(name).casefold()
        for name in daten.columns
        for wort in ("aktiv", "activity", "vorgang", "ereignis", "status", "transportweg")
    )
    return (
        MappingModus.BREITER_ZEITSTEMPELDATENSATZ
        if zeitgeeignet >= 2 and not aktivitaet
        else MappingModus.EREIGNISORIENTIERT
    )


def _datenstruktur(daten: pd.DataFrame, zustand: dict[str, Any]) -> None:
    """Erfasst den Mappingmodus und zeigt ausschließlich die tatsächliche Struktur."""
    st.subheader("Datenstruktur")
    st.write("**Wie sind die Ereignisse in den Daten dargestellt?**")
    vorschlag = _struktur_vorschlagen(daten)
    st.info(
        "Vorgeschlagene Datenstruktur: "
        + (
            "Eine Zeile entspricht einem Ereignis"
            if vorschlag is MappingModus.EREIGNISORIENTIERT
            else "Eine Zeile enthält mehrere Ereigniszeitpunkte"
        )
    )
    optionen = (
        MappingModus.EREIGNISORIENTIERT,
        MappingModus.BREITER_ZEITSTEMPELDATENSATZ,
    )
    vorhanden = zustand.get("modus", vorschlag)
    modus = st.radio(
        "Datenstruktur",
        optionen,
        index=optionen.index(vorhanden),
        format_func=lambda wert: (
            "Eine Zeile entspricht einem Ereignis"
            if wert is MappingModus.EREIGNISORIENTIERT
            else "Eine Zeile enthält mehrere Ereigniszeitpunkte"
        ),
    )
    zustand["modus"] = modus
    if modus is MappingModus.EREIGNISORIENTIERT:
        st.caption(
            "Jede Datenzeile beschreibt bereits eine Aktivität mit einem zugehörigen "
            "Zeitstempel (ereignisorientierter Datensatz)."
        )
    else:
        st.caption(
            "Eine Zeile enthält getrennte Zeitstempel für mehrere Aktivitäten. "
            "Daraus werden in Schritt 4 mehrere Ereignisse erzeugt "
            "(breiter Zeitstempeldatensatz)."
        )
    st.dataframe(daten.head(100), width="stretch")
    st.write("**Verfügbare Spalten:** " + ", ".join(str(wert) for wert in daten.columns))


def _fallkennzahlen(daten: pd.DataFrame, fall_id: str) -> None:
    """Zeigt Kardinalität, Leerwerte und Ereignisanzahl einer Fall-ID."""
    serie = daten[fall_id].astype("string")
    leer = serie.isna() | serie.str.strip().eq("")
    groessen = serie.loc[~leer].value_counts()
    st.caption(
        f"{serie.loc[~leer].nunique():,} unterschiedliche Fall-IDs · "
        f"{int(leer.sum()):,} leere Fall-IDs · "
        f"mindestens {int(groessen.min()) if not groessen.empty else 0:,} · "
        f"höchstens {int(groessen.max()) if not groessen.empty else 0:,} Ereignisse je Fall"
    )


def _zeitkennzahlen(daten: pd.DataFrame, spalte: str) -> None:
    """Zeigt die Interpretierbarkeit der gewählten Zeitstempelspalte."""
    original = daten[spalte]
    zeit = pd.to_datetime(original, errors="coerce", format="mixed")
    nicht_leer = original.notna()
    gueltig = zeit.notna()
    st.caption(
        f"{float(gueltig.mean()):.1%} interpretierbar · "
        f"frühester Zeitpunkt {zeit.min() if gueltig.any() else '–'} · "
        f"spätester Zeitpunkt {zeit.max() if gueltig.any() else '–'} · "
        f"{int((nicht_leer & ~gueltig).sum()):,} nicht interpretierbare Werte"
    )


def _aktivitaetskennzahlen(aktivitaeten: pd.Series) -> None:
    """Zeigt Vorschau und Kardinalität einer Aktivitätsdefinition."""
    text = aktivitaeten.astype("string")
    leer = text.isna() | text.str.strip().eq("")
    regulaer = text.loc[~leer]
    haeufig = regulaer.value_counts()
    top5 = int(haeufig.head(5).sum())
    st.dataframe(pd.DataFrame({"activity": text.head(20)}), hide_index=True)
    st.caption(
        f"{len(regulaer):,} erzeugte Aktivitäten · {regulaer.nunique():,} unterschiedliche · "
        f"{int(leer.sum()):,} leer · Anteil Top 5 "
        f"{top5 / len(regulaer) if len(regulaer) else 0:.1%} · "
        f"Eindeutigkeitsanteil "
        f"{regulaer.nunique() / len(regulaer) if len(regulaer) else 0:.1%}"
    )
    if len(regulaer) and regulaer.nunique() / len(regulaer) > 0.25:
        st.warning(
            f"Die Definition erzeugt {regulaer.nunique():,} unterschiedliche Aktivitäten "
            f"aus {len(regulaer):,} Ereignissen. Ein sehr detailliertes Aktivitätsniveau "
            "kann das spätere Prozessmodell schwer lesbar machen."
        )


def _aktivitaetsdefinition(daten: pd.DataFrame, zustand: dict[str, Any]) -> Aktivitaetsdefinition:
    """Erfasst eine vorhandene oder virtuelle zusammengesetzte Aktivität."""
    spalten = [str(wert) for wert in daten.columns]
    art = st.radio(
        "Wie wird die Aktivität gebildet?",
        ("Vorhandene Spalte verwenden", "Aus mehreren Spalten zusammensetzen"),
    )
    if art == "Vorhandene Spalte verwenden":
        priorisiert = sorted(
            spalten,
            key=lambda name: (
                not any(
                    wort in name.casefold()
                    for wort in (
                        "aktiv",
                        "activity",
                        "vorgang",
                        "ereignis",
                        "status",
                        "transportweg",
                    )
                ),
                name,
            ),
        )
        name = st.selectbox(
            "Aktivitätsspalte",
            priorisiert,
            help="Die Aktivität beschreibt, was bei einem Ereignis passiert.",
        )
        definition = Aktivitaetsdefinition(Aktivitaetsbildungsart.VORHANDENE_SPALTE, (name,))
        _aktivitaetskennzahlen(daten[name])
        return definition
    datensatz_id = zustand.get("datensatz_id", "ohne_datensatz")
    quellen = st.multiselect(
        "Quellspalten in gewünschter Reihenfolge",
        spalten,
        key=f"mapping_aktivitaetsquellen_{datensatz_id}",
    )
    trennzeichen = st.text_input("Text oder Trennzeichen", value=" → ")
    praefix = st.text_input("Präfix (optional)")
    suffix = st.text_input("Suffix (optional)")
    strategien = {
        "Aktivität leer lassen, wenn ein Bestandteil fehlt": "Ergebnis leer lassen",
        "Nur vorhandene Bestandteile verwenden": "Nur vorhandene Bestandteile kombinieren",
        "Fehlende Bestandteile durch festen Text ersetzen": "Festen Ersatztext verwenden",
    }
    auswahl = st.selectbox("Verhalten bei leeren Werten", list(strategien))
    ersatztext = (
        st.text_input("Ersatztext") if strategien[auswahl] == "Festen Ersatztext verwenden" else ""
    )
    if len(quellen) < 2:
        st.info("Wählen Sie mindestens zwei Quellspalten.")
        return Aktivitaetsdefinition(Aktivitaetsbildungsart.VORHANDENE_SPALTE, (spalten[0],))
    definition = Aktivitaetsdefinition(
        Aktivitaetsbildungsart.ZUSAMMENGESETZT,
        tuple(quellen),
        trennzeichen,
        praefix,
        suffix,
        strategien[auswahl],
        ersatztext,
    )
    aktivitaeten = kombiniere_textspalten(
        daten,
        definition.quellspalten,
        trennzeichen=definition.trennzeichen,
        praefix=definition.praefix,
        suffix=definition.suffix,
        fehlwertstrategie=definition.fehlwertstrategie,
        ersatztext=definition.ersatztext,
    )
    _aktivitaetskennzahlen(aktivitaeten)
    return definition


def _standardrollen(
    spalten: list[str], bereits_verwendet: set[str], zustand: dict[str, Any]
) -> dict[str, str]:
    """Erfasst optionale Standardrollen nur nach ausdrücklichem Hinzufügen."""
    rollen: dict[str, str] = zustand.setdefault("standardrollen", {})
    st.write("**Weitere standardisierte Rollen hinzufügen**")
    vorschlaege = _standardrollenvorschlaege(spalten)
    if vorschlaege:
        st.caption(
            "Unverbindliche Vorschläge: "
            + " · ".join(
                f"{rolle}: {', '.join(werte)}" for rolle, werte in vorschlaege.items() if werte
            )
        )
    verbleibende_rollen = [wert for wert in STANDARDROLLEN if wert not in rollen]
    if verbleibende_rollen:
        auswahl = st.selectbox("Rolle hinzufügen", verbleibende_rollen)
        if st.button("Rolle hinzufügen"):
            rollen[auswahl] = ""
            st.rerun()
    fuer_entfernung: list[str] = []
    belegt = bereits_verwendet | {wert for wert in rollen.values() if wert}
    for rolle in list(rollen):
        aktuell = rollen[rolle]
        optionen = [wert for wert in spalten if wert not in belegt or wert == aktuell]
        if optionen:
            rollen[rolle] = st.selectbox(
                f"Spalte für {rolle}",
                optionen,
                index=optionen.index(aktuell) if aktuell in optionen else 0,
                key=f"mapping_standardrolle_{rolle}",
            )
            belegt.add(rollen[rolle])
        if st.button("Rolle entfernen", key=f"mapping_rolle_entfernen_{rolle}"):
            fuer_entfernung.append(rolle)
    for rolle in fuer_entfernung:
        rollen.pop(rolle, None)
        st.rerun()
    return dict(rollen)


def _standardrollenvorschlaege(spalten: list[str]) -> dict[str, tuple[str, ...]]:
    """Leitet transparente, nicht verbindliche Vorschläge aus Spaltennamen ab."""
    muster = {
        "Ressource": ("ressource", "benutzer", "maschine", "arbeitsplatz"),
        "Lifecycle": ("status", "lifecycle", "transition"),
        "Startzeitstempel": ("start", "beginn"),
        "Endzeitstempel": ("ende", "end", "abschluss"),
        "Quell-Ereignis-ID": ("event_id", "ereignis_id"),
    }
    return {
        rolle: tuple(
            name for name in spalten if any(wert in name.casefold() for wert in suchwoerter)
        )
        for rolle, suchwoerter in muster.items()
    }


def _attribute(
    spalten: list[str], bereits_verwendet: set[str], zustand: dict[str, Any]
) -> dict[str, tuple[str, ...]]:
    """Erfasst vier disjunkte Attributgruppen aus den verbleibenden Spalten."""
    st.write("**Zusätzliche Attribute**")
    ergebnis: dict[str, tuple[str, ...]] = {}
    bisher = {
        key: tuple(zustand.get("attributgruppen", {}).get(key, ())) for key in ATTRIBUTGRUPPEN
    }
    belegt = set(bereits_verwendet)
    for key, (titel, hilfe, _) in ATTRIBUTGRUPPEN.items():
        fremde = {
            wert for anderer_key, werte in bisher.items() if anderer_key != key for wert in werte
        }
        optionen = [wert for wert in spalten if wert not in belegt and wert not in fremde]
        if not optionen:
            continue
        widget_key = f"mapping_attribute_{zustand.get('datensatz_id', 'ohne_datensatz')}_{key}"
        widget_wert = st.session_state.get(widget_key, bisher[key])
        st.session_state[widget_key] = [wert for wert in widget_wert if wert in optionen]
        auswahl = tuple(
            st.multiselect(
                titel,
                optionen,
                help=hilfe,
                key=widget_key,
            )
        )
        ergebnis[key] = auswahl
        belegt.update(auswahl)
    zustand["attributgruppen"] = ergebnis
    if not ergebnis:
        st.caption("Keine weiteren Spalten verfügbar.")
    return ergebnis


def _rollen_und_aktivitaet(
    daten: pd.DataFrame, projekt_id: UUID, datensatz_id: UUID, zustand: dict[str, Any]
) -> None:
    """Erfasst Pflichtrollen, dynamische Standardrollen und Attributgruppen."""
    st.subheader("Rollen und Aktivität")
    spalten = [str(wert) for wert in daten.columns]
    fall_id = st.selectbox(
        "Fall-ID",
        spalten,
        help="Die Fall-ID verbindet Ereignisse desselben Auftrags, Transports oder Prozessfalls.",
    )
    zustand["fall_id"] = fall_id
    _fallkennzahlen(daten, fall_id)
    modus: MappingModus = zustand["modus"]
    definition: Aktivitaetsdefinition | None = None
    zeitstempel = ""
    zeitzuordnungen: tuple[ZeitstempelZuordnung, ...] = ()
    verwendet = {fall_id}
    if modus is MappingModus.EREIGNISORIENTIERT:
        definition = _aktivitaetsdefinition(daten, zustand)
        verwendet.update(definition.quellspalten)
        zeitstempel = st.selectbox(
            "Ereigniszeitstempel",
            _zeitspalten(daten),
            help="Der Zeitstempel bestimmt, wann das Ereignis stattgefunden hat.",
        )
        verwendet.add(zeitstempel)
        _zeitkennzahlen(daten, zeitstempel)
    else:
        zeitspalten = st.multiselect(
            "Zeitstempelspalten",
            _zeitspalten(daten),
            key=f"mapping_zeitspalten_{datensatz_id}",
        )
        zuordnungen = []
        for name in zeitspalten:
            bezeichnung = st.text_input(
                f"Resultierende Aktivität für {name}",
                value=name.replace("_", " ").strip().capitalize(),
                key=f"mapping_breite_aktivitaet_{datensatz_id}_{name}",
            )
            zuordnungen.append(ZeitstempelZuordnung(name, bezeichnung))
        zeitzuordnungen = tuple(zuordnungen)
        verwendet.update(zeitspalten)
        if zeitzuordnungen:
            vorschau = []
            for zeile, datenreihe in daten.head(20).iterrows():
                for zuordnung in zeitzuordnungen:
                    wert = datenreihe[zuordnung.zeitstempelspalte]
                    if bool(pd.notna(wert)):
                        vorschau.append(
                            {
                                "Quellzeile": zeile,
                                "Fall-ID": datenreihe[fall_id],
                                "Aktivität": zuordnung.aktivitaetsbezeichnung,
                                "Zeitstempelspalte": zuordnung.zeitstempelspalte,
                                "Zeitstempelwert": wert,
                            }
                        )
            st.dataframe(pd.DataFrame(vorschau).head(100), hide_index=True)
    standardrollen = _standardrollen(spalten, verwendet, zustand)
    verwendet.update(wert for wert in standardrollen.values() if wert)
    attributgruppen = _attribute(spalten, verwendet, zustand)
    bestehend = zustand.get("mapping")
    jetzt = datetime.now(UTC)
    zuordnungen = tuple(
        Spaltenzuordnung(spalte, ATTRIBUTGRUPPEN[key][2])
        for key, werte in attributgruppen.items()
        for spalte in werte
    )
    if standardrollen.get("Quell-Ereignis-ID"):
        zuordnungen = (
            *zuordnungen,
            Spaltenzuordnung(
                standardrollen["Quell-Ereignis-ID"],
                Ereignisrolle.QUELL_EREIGNIS_ID,
            ),
        )
    mapping = SemantischesMapping(
        bestehend.mapping_id if bestehend else uuid4(),
        projekt_id,
        datensatz_id,
        modus,
        ZusammengesetzteFallId((fall_id,)),
        (
            definition.quellspalten[0]
            if definition and definition.bildungsart is Aktivitaetsbildungsart.VORHANDENE_SPALTE
            else ""
        ),
        zeitstempel,
        standardrollen.get("Startzeitstempel", ""),
        standardrollen.get("Endzeitstempel", ""),
        standardrollen.get("Lifecycle", ""),
        standardrollen.get("Ressource", ""),
        zuordnungen,
        zeitzuordnungen,
        None,
        bestehend.erstellt_am if bestehend else jetzt,
        jetzt,
        Mappingstatus.ENTWURF,
        definition,
    )
    zustand["mapping"] = mapping
    zustand.pop("mapping_ergebnis", None)
    zustand.pop("mapping_pfad", None)


def _pruefen_und_speichern(
    service: MappingService,
    projektname: str,
    datensatz: Zwischendatensatz,
    daten: pd.DataFrame,
    zustand: dict[str, Any],
) -> None:
    """Validiert, zeigt eine Vorschau und speichert idempotent vor Navigation."""
    st.subheader("Ausgabe dieses Schritts")
    st.write("### Semantisches Mapping")
    mapping: SemantischesMapping = zustand["mapping"]
    mapping, ergebnis = service.validieren(mapping, daten)
    zustand["mapping"] = mapping
    zustand["mapping_ergebnis"] = ergebnis
    fehler = [wert for wert in ergebnis.validierung.warnungen if wert.stufe is Warnungsstufe.FEHLER]
    warnungen = [
        wert for wert in ergebnis.validierung.warnungen if wert.stufe is Warnungsstufe.WARNUNG
    ]
    hinweise = [
        wert for wert in ergebnis.validierung.warnungen if wert.stufe is Warnungsstufe.HINWEIS
    ]
    for titel, werte, ausgabe in (
        ("Fehler", fehler, st.error),
        ("Warnungen", warnungen, st.warning),
        ("Hinweise", hinweise, st.info),
    ):
        if werte:
            st.write(f"**{titel}**")
            for wert in werte:
                ausgabe(f"{wert.meldung} ({wert.anzahl:,})")
    st.dataframe(ergebnis.vorschau.head(100), width="stretch")
    definition = mapping.wirksame_aktivitaetsdefinition
    gruppen = zustand.get("attributgruppen", {})
    st.write(
        f"**Projekt:** {projektname}  \n"
        f"**Datengrundlage:** {datensatz.zeilenanzahl:,} Zeilen · "
        f"{datensatz.spaltenanzahl:,} Spalten  \n"
        f"**Datenstruktur:** {mapping.mapping_modus.value}  \n"
        f"**Fall-ID:** {mapping.fall_id.spalten[0]}  \n"
        f"**Aktivität:** "
        f"{' + '.join(definition.quellspalten) if definition else 'nicht definiert'}  \n"
        f"**Zeitbezug:** "
        f"{mapping.zeitstempelspalte or f'{len(mapping.zeitstempelzuordnungen)} Zeitspalten'}  \n"
        f"**Standardisierte Rollen:** "
        f"{len(zustand.get('standardrollen', {}))}  \n"
        f"**Attribute:** Ereignis {len(gruppen.get('ereignisattribute', ()))}, "
        f"Fall {len(gruppen.get('fallattribute', ()))}, "
        f"Ressource {len(gruppen.get('ressourcenattribute', ()))}, "
        f"Objekte {len(gruppen.get('objektidentifikatoren', ()))}  \n"
        f"**Validierungsfehler:** {len(fehler)} · **Warnungen:** {len(warnungen)}"
    )
    if st.button(
        "Event-Log-Konfiguration speichern und weiter",
        type="primary",
        disabled=bool(fehler),
    ):
        erneut, erneutes_ergebnis = service.validieren(mapping, daten)
        if not erneutes_ergebnis.validierung.gueltig:
            st.error("Das Mapping enthält Validierungsfehler und wurde nicht gespeichert.")
            return
        zustand["mapping_pfad"] = service.speichern(erneut)
        st.session_state.aktuelle_mapping_id = str(erneut.mapping_id)
        st.session_state.mapping_id = erneut.mapping_id
        schritt_abschliessen_und_weiter(aktueller_schritt=3, projekt_id=mapping.projekt_id)


def _navigation(zustand: dict[str, Any]) -> None:
    """Navigiert zwischen den drei fachlichen Mappingabschnitten."""
    schritt = zustand["schritt"]
    weiter_moeglich = (
        "modus" in zustand if schritt == 1 else "mapping" in zustand if schritt == 2 else False
    )
    zeige_unterschritt_navigation(
        aktueller_unterschritt=schritt,
        anzahl_unterschritte=len(MAPPING_SCHRITTE),
        weiter_erlaubt=schritt < len(MAPPING_SCHRITTE) and weiter_moeglich,
        zurueck_callback=lambda: zustand.__setitem__("schritt", schritt - 1),
        weiter_callback=lambda: zustand.__setitem__("schritt", schritt + 1),
        schluessel="mapping_unterschritt_navigation",
    )


def zeige_event_log_konfiguration(
    projekt_service: ProjektService,
    transformations_service: TransformationsService,
    mapping_service: MappingService,
    datenquelle_service: DatenquelleService | None = None,
) -> None:
    """Erfasst in Schritt 4 die Rollen zur technischen Event-Log-Erzeugung."""
    st.subheader("Event-Log-Konfiguration")
    st.write(
        "Legen Sie erst jetzt Fall-ID, Aktivität, Zeitbezug und Event-Log-Attribute fest. "
        "Diese Funktionen gehören zur Bildung des Event Logs und nicht zu M."
    )
    try:
        projektkontext = _projektkontext(projekt_service)
        if projektkontext is None:
            return
        projekt_id, projektname = projektkontext
        geladen = _aktiven_datensatz_laden(transformations_service, projekt_id)
        if geladen is None:
            st.warning(
                "Für das aktuelle Projekt ist kein konsistenter Zwischendatensatz vorhanden."
            )
            if st.button("Zurück zu ETL", type="primary"):
                framework_bereich_oeffnen(schritt=2, projekt_id=projekt_id)
            return
        datensatz, daten = geladen
        _datensatzkontext(transformations_service, datenquelle_service, datensatz)
        zustand = _zustand(projekt_id)
        aktive_id = str(datensatz.zwischendatensatz_id)
        if zustand.get("datensatz_id") != aktive_id:
            zustand.clear()
            zustand.update({"schritt": 1, "datensatz_id": aktive_id})
        if zustand["schritt"] == 1:
            _datenstruktur(daten, zustand)
        elif zustand["schritt"] == 2:
            _rollen_und_aktivitaet(daten, projekt_id, datensatz.zwischendatensatz_id, zustand)
        else:
            _pruefen_und_speichern(mapping_service, projektname, datensatz, daten, zustand)
        _navigation(zustand)
    except (Domaenenfehler, Importintegritaetsfehler) as fehler:
        st.error(str(fehler))


def _mappingtabelle_zustand(
    projekt_id: UUID, datensatz_id: UUID, service: MappingtabelleService
) -> dict[str, Any]:
    """Bindet den UI-Entwurf strikt an das zentral aktive T und lädt vorhandenes M."""
    zustaende = st.session_state.setdefault("mappingtabelle_zustaende", {})
    schluessel = str(projekt_id)
    zustand = zustaende.setdefault(schluessel, {})
    aktuelle_id = str(datensatz_id)
    if zustand.get("datensatz_id") != aktuelle_id:
        vorhanden = service.fuer_datensatz(projekt_id, datensatz_id)
        zustand.clear()
        zustand.update(
            {
                "datensatz_id": aktuelle_id,
                "mappingtabelle": vorhanden
                if vorhanden is not None
                else Mappingtabelle.neu(projekt_id, datensatz_id),
            }
        )
    return zustand


def _mappingtabelle_anzeigen(mapping: Mappingtabelle) -> None:
    """Zeigt M mit den beiden Kernspalten und dem nötigen Wertkontext."""
    zeilen = [
        {
            "Art": eintrag.art.value,
            "Technische Bezeichnung": eintrag.technische_bezeichnung,
            "Fachliche Bezeichnung": eintrag.fachliche_bezeichnung,
            "Technische Quellspalte": eintrag.technische_quellspalte or "–",
            "Technischer Datentyp": (
                eintrag.wertreferenz.technischer_datentyp
                if eintrag.wertreferenz is not None
                else "–"
            ),
        }
        for eintrag in mapping.eintraege
    ]
    st.write("### Mappingtabelle (M)")
    if zeilen:
        st.dataframe(pd.DataFrame(zeilen), hide_index=True, width="stretch")
    else:
        st.info("M ist leer: Alle technischen Bezeichnungen werden unverändert weitergegeben.")


def _spaltenzuordnung_erfassen(daten: pd.DataFrame, mapping: Mappingtabelle) -> Mappingtabelle:
    """Erfasst eine Abbildung eines tatsächlichen Spaltennamens b_tech auf b_fach."""
    st.write("#### Spaltenbezeichnung interpretieren")
    spalten = [str(wert) for wert in daten.columns]
    spalte = fachliche_auswahl("Technische Spaltenbezeichnung", spalten)
    fachlich = st.text_input("Fachliche Spaltenbezeichnung")
    if st.button("Spaltenzuordnung hinzufügen", disabled=spalte is None):
        assert spalte is not None
        mapping = mapping.eintrag_hinzufuegen(Mappingeintrag.fuer_spalte(spalte, fachlich))
        st.success("Die Spaltenzuordnung wurde zu M hinzugefügt.")
    return mapping


def _eindeutige_werte(serie: pd.Series) -> list[object]:
    """Liefert vorhandene, nicht fehlende Werte in stabiler Reihenfolge."""
    ergebnis: list[object] = []
    schluessel: set[tuple[str, str]] = set()
    for wert in serie:
        try:
            if bool(pd.isna(wert)):
                continue
        except (TypeError, ValueError):
            pass
        referenz = Mappingeintrag.fuer_wert(str(serie.name), wert, "temporär").wertreferenz
        assert referenz is not None
        if referenz.schluessel not in schluessel:
            schluessel.add(referenz.schluessel)
            ergebnis.append(wert)
    return ergebnis


def _wertzuordnung_erfassen(daten: pd.DataFrame, mapping: Mappingtabelle) -> Mappingtabelle:
    """Erfasst paginiert einen tatsächlich vorhandenen, typisierten technischen Wert."""
    st.write("#### Enthaltenen Wert interpretieren")
    spalten = [str(wert) for wert in daten.columns]
    quellspalte = fachliche_auswahl("Technische Quellspalte für Wert", spalten)
    if quellspalte is None:
        st.info("Wählen Sie zuerst eine technische Quellspalte aus.")
        return mapping
    position = spalten.index(quellspalte)
    alle_werte = _eindeutige_werte(daten.iloc[:, position])
    suchtext = st.text_input("Technische Werte durchsuchen").casefold().strip()
    gefiltert = [wert for wert in alle_werte if suchtext in str(wert).casefold()]
    seitengroesse = 100
    seitenanzahl = max(1, (len(gefiltert) + seitengroesse - 1) // seitengroesse)
    seite = int(
        st.number_input(
            "Werteseite",
            min_value=1,
            max_value=seitenanzahl,
            value=1,
            help="Je Seite werden höchstens 100 unterschiedliche vorhandene Werte gezeigt.",
        )
    )
    start = (seite - 1) * seitengroesse
    werte = gefiltert[start : start + seitengroesse]
    st.caption(f"{len(gefiltert):,} passende unterschiedliche Werte · Seite {seite}/{seitenanzahl}")
    if not werte:
        st.info("Für den Suchtext ist kein technischer Wert vorhanden.")
        return mapping
    auswahl = fachliche_auswahl(
        "Technischer Wert",
        range(len(werte)),
        format_func=lambda index: f"{werte[index]!s}  [{type(werte[index]).__name__}]",
    )
    fachlich = st.text_input("Fachliche Wertbezeichnung")
    if st.button("Wertzuordnung hinzufügen", disabled=auswahl is None):
        assert auswahl is not None
        mapping = mapping.eintrag_hinzufuegen(
            Mappingeintrag.fuer_wert(quellspalte, werte[auswahl], fachlich)
        )
        st.success("Die Wertzuordnung wurde zu M hinzugefügt.")
    return mapping


def _mappingeintrag_bearbeiten(mapping: Mappingtabelle) -> Mappingtabelle:
    """Erlaubt Bearbeitung von b_fach und Entfernung ohne Verlust der Referenz."""
    if not mapping.eintraege:
        return mapping
    st.write("#### Vorhandene Zuordnung bearbeiten")
    nach_id = {eintrag.mappingeintrag_id: eintrag for eintrag in mapping.eintraege}
    eintrag_id = fachliche_auswahl(
        "Mappingeintrag",
        list(nach_id),
        format_func=lambda wert: (
            f"{nach_id[wert].technische_bezeichnung} → {nach_id[wert].fachliche_bezeichnung}"
        ),
    )
    if eintrag_id is None:
        st.info("Wählen Sie den zu bearbeitenden Mappingeintrag aus.")
        return mapping
    eintrag = nach_id[eintrag_id]
    fachlich = st.text_input(
        "Bearbeitete fachliche Bezeichnung",
        value=eintrag.fachliche_bezeichnung,
        key=f"mappingtabelle_bearbeiten_{eintrag_id}",
    )
    links, rechts = st.columns(2)
    if links.button("Fachliche Bezeichnung übernehmen"):
        mapping = mapping.eintrag_bearbeiten(eintrag_id, fachlich)
    if rechts.button("Zuordnung entfernen"):
        mapping = mapping.eintrag_entfernen(eintrag_id)
    return mapping


def zeige_semantisches_mapping(
    projekt_service: ProjektService,
    transformations_service: TransformationsService,
    mappingtabelle_service: MappingtabelleService,
    datenquelle_service: DatenquelleService | None = None,
) -> None:
    """Erzeugt in Schritt 3 ausschließlich die optionale Mappingtabelle M."""
    st.header("3 Semantisches Mapping")
    st.write(
        "Interpretieren Sie bei Bedarf technische Spaltenbezeichnungen oder enthaltene "
        "technische Werte. T bleibt unverändert; Fall-ID, Aktivität und Zeitbezug werden "
        "erst in Schritt 4 festgelegt."
    )
    try:
        projektkontext = _projektkontext(projekt_service)
        if projektkontext is None:
            return
        projekt_id, _ = projektkontext
        geladen = _aktiven_datensatz_laden(transformations_service, projekt_id)
        if geladen is None:
            st.warning(
                "Für das aktuelle Projekt ist kein konsistenter Zwischendatensatz vorhanden."
            )
            if st.button("Zurück zu ETL", type="primary"):
                framework_bereich_oeffnen(schritt=2, projekt_id=projekt_id)
            return
        datensatz, daten = geladen
        _datensatzkontext(transformations_service, datenquelle_service, datensatz)
        st.write("### Unveränderte Vorschau des Zwischendatensatzes T")
        st.dataframe(daten.head(100), width="stretch")
        zustand = _mappingtabelle_zustand(
            projekt_id, datensatz.zwischendatensatz_id, mappingtabelle_service
        )
        mapping: Mappingtabelle = zustand["mappingtabelle"]
        modus_key = f"mappingtabelle_modus_{datensatz.zwischendatensatz_id}"
        st.session_state.setdefault(
            modus_key,
            (
                "Kein semantisches Mapping erforderlich"
                if mapping.kein_mapping_erforderlich
                else "Semantische Zuordnungen erfassen"
            ),
        )
        modus = st.radio(
            "Ist eine Interpretation technischer Bezeichnungen erforderlich?",
            ("Semantische Zuordnungen erfassen", "Kein semantisches Mapping erforderlich"),
            key=modus_key,
        )
        if modus == "Semantische Zuordnungen erfassen":
            art = st.radio(
                "Art der technischen Bezeichnung",
                (Mappingeintragsart.SPALTENBEZEICHNUNG, Mappingeintragsart.TECHNISCHER_WERT),
                format_func=lambda wert: wert.value,
                horizontal=True,
                key=f"mappingtabelle_art_{datensatz.zwischendatensatz_id}",
            )
            mapping = (
                _spaltenzuordnung_erfassen(daten, mapping)
                if art is Mappingeintragsart.SPALTENBEZEICHNUNG
                else _wertzuordnung_erfassen(daten, mapping)
            )
            mapping = _mappingeintrag_bearbeiten(mapping)
        _mappingtabelle_anzeigen(mapping)
        zustand["mappingtabelle"] = mapping
        modus_geaendert = mapping.kein_mapping_erforderlich != (
            modus == "Kein semantisches Mapping erforderlich"
        )
        gespeichert = mapping.status is Mappingtabellenstatus.BESTAETIGT and not modus_geaendert
        links, rechts = st.columns(2)
        if links.button("Zurück", width="stretch"):
            framework_bereich_oeffnen(schritt=2, projekt_id=projekt_id)
        if not gespeichert and rechts.button(
            "Mappingtabelle speichern und weiter zu Schritt 4: Event Log aufbauen",
            type="primary",
            width="stretch",
        ):
            mapping = mapping.bestaetigen(
                kein_mapping_erforderlich=(modus == "Kein semantisches Mapping erforderlich")
            )
            zustand["mappingtabelle"] = mapping
            zustand["mapping_pfad"] = mappingtabelle_service.speichern(mapping)
            st.session_state.aktuelle_mappingtabelle_id = str(mapping.mapping_id)
            schritt_abschliessen_und_weiter(aktueller_schritt=3, projekt_id=projekt_id)
        if pfad := zustand.get("mapping_pfad"):
            st.caption(f"Gespeichertes Artefakt: `{pfad}`")
        if gespeichert and rechts.button(
            "Weiter zu Schritt 4: Event Log aufbauen", type="primary", width="stretch"
        ):
            st.session_state.aktuelle_mappingtabelle_id = str(mapping.mapping_id)
            schritt_abschliessen_und_weiter(aktueller_schritt=3, projekt_id=projekt_id)
        if not gespeichert:
            st.info("Speichern Sie die Mappingtabelle M, um mit Schritt 4 fortzufahren.")
    except (Domaenenfehler, Importintegritaetsfehler) as fehler:
        st.error(str(fehler))
