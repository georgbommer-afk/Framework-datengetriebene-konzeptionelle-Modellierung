"""Reine, quellengebundene Ableitung gemäß Tabelle 3.15 und Algorithmus 8."""

import tempfile
from collections.abc import Hashable, Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pm4py
from pm4py.objects.bpmn.obj import BPMN

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    AbgeleiteterModellbestandteil,
    Bestandteilstatus,
    Eingangsartefakt,
    Informationseintrag,
    Kennzeichnungsherkunft,
    ModellbestandteilDefinition,
    ModellbestandteilId,
    OffenerEintrag,
    Offenheitskategorie,
    Prozessnotation,
    Uebernahmeart,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler

MAPPINGVERSION = 1

MODELLBESTANDTEILE = (
    ModellbestandteilDefinition(
        ModellbestandteilId.PROBLEMSTELLUNG,
        "Problemstellung",
        (Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.ZIELSETZUNG,
        "Zielsetzung",
        (Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.AUSGABEN_UND_EINGABEN,
        "Ausgaben und Eingaben",
        (
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
        True,
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.MODELLUMFANG_GRENZEN_DETAILLIERUNG,
        "Modellumfang, Modellgrenzen und Detaillierungsgrad",
        (
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            Eingangsartefakt.SYSTEMPROFIL_S,
            Eingangsartefakt.PROZESSMODELL_P,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.ENTITAETEN,
        "Entitäten",
        (Eingangsartefakt.SYSTEMPROFIL_S, Eingangsartefakt.EVENT_LOG_E_STERN),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.AKTIVITAETEN,
        "Aktivitäten",
        (
            Eingangsartefakt.PROZESSMODELL_P,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.WARTESCHLANGEN,
        "Warteschlangen",
        (
            Eingangsartefakt.EVENT_LOG_E_STERN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
        True,
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.RESSOURCEN,
        "Ressourcen",
        (
            Eingangsartefakt.SYSTEMPROFIL_S,
            Eingangsartefakt.EVENT_LOG_E_STERN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.ANNAHMEN_UND_VEREINFACHUNGEN,
        "Annahmen und Vereinfachungen",
        (
            Eingangsartefakt.PROZESSMODELL_P,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
        True,
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.DATENAUSWAHL_UND_DATEN,
        "Datenauswahl und Daten",
        (
            Eingangsartefakt.DATENQUELLENKATALOG_Q,
            Eingangsartefakt.DATENPROFIL_R,
            Eingangsartefakt.ZWISCHENDATENSATZ_T,
            Eingangsartefakt.EVENT_LOG_E_STERN,
        ),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.DARSTELLUNG_DER_VORGAENGE,
        "Darstellung der Vorgänge des Systems",
        (Eingangsartefakt.PROZESSMODELL_P,),
    ),
)

_DEFINITIONEN = {wert.bestandteil_id: wert for wert in MODELLBESTANDTEILE}


def _eindeutig[T: Hashable](werte: Iterable[T]) -> tuple[T, ...]:
    gesehen: set[T] = set()
    ergebnis: list[T] = []
    for wert in werte:
        if wert and wert not in gesehen:
            gesehen.add(wert)
            ergebnis.append(wert)
    return tuple(ergebnis)


def extrahiere_sichtbare_aktivitaeten(
    prozessmodell: bytes, notation: Prozessnotation
) -> tuple[str, ...]:
    """Liest sichtbare Aktivitäten aus P; stille Petrinetztransitionen bleiben ausgeschlossen."""
    suffix = f".{notation.dateiendung}"
    temporaerer_pfad = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as datei:
            datei.write(prozessmodell)
            temporaerer_pfad = datei.name
        if notation is Prozessnotation.PROZESSBAUM:
            wurzel = pm4py.read_ptml(temporaerer_pfad)
            stapel = [wurzel]
            aktivitaeten: list[str] = []
            while stapel:
                knoten = stapel.pop()
                label = getattr(knoten, "label", None)
                if isinstance(label, str) and label:
                    aktivitaeten.append(label)
                stapel.extend(reversed(tuple(getattr(knoten, "children", ()))))
            return tuple(sorted(_eindeutig(aktivitaeten)))
        if notation is Prozessnotation.PETRINETZ:
            netz, _, _ = pm4py.read_pnml(temporaerer_pfad)
            return tuple(
                sorted(
                    _eindeutig(
                        transition.label
                        for transition in sorted(netz.transitions, key=lambda wert: str(wert.name))
                        if isinstance(transition.label, str) and transition.label
                    )
                )
            )
        bpmn = pm4py.read_bpmn(temporaerer_pfad)
        return tuple(
            sorted(
                _eindeutig(
                    knoten.get_name()
                    for knoten in sorted(bpmn.get_nodes(), key=lambda wert: str(wert.get_id()))
                    if isinstance(knoten, BPMN.Activity) and knoten.get_name()
                )
            )
        )
    except Exception as fehler:
        raise Importintegritaetsfehler(
            f"Die sichtbaren Aktivitäten können nicht aus P ({notation.value}) gelesen werden."
        ) from fehler
    finally:
        if temporaerer_pfad:
            Path(temporaerer_pfad).unlink(missing_ok=True)


class _Sammlung:
    def __init__(self, basis: Any) -> None:
        self.basis = basis
        self.informationen: dict[ModellbestandteilId, list[Informationseintrag]] = {
            wert.bestandteil_id: [] for wert in MODELLBESTANDTEILE
        }
        self.offen: dict[ModellbestandteilId, list[OffenerEintrag]] = {
            wert.bestandteil_id: [] for wert in MODELLBESTANDTEILE
        }

    def info(
        self,
        bestandteil: ModellbestandteilId,
        quelle: Eingangsartefakt,
        pfad: str,
        wert: Any,
        art: Uebernahmeart = Uebernahmeart.DIREKTE_UEBERNAHME,
        *,
        artefakt_id: str | None = None,
        sha256: str | None = None,
    ) -> None:
        definition = _DEFINITIONEN[bestandteil]
        if quelle not in definition.zulaessige_quellen:
            raise Domaenenfehler(
                f"{quelle.value} ist für '{definition.bezeichnung}' gemäß Tabelle 3.15 unzulässig."
            )
        referenz = self.basis.quellreferenzen[quelle]
        liste = self.informationen[bestandteil]
        liste.append(
            Informationseintrag(
                f"{bestandteil.value}:information:{len(liste) + 1}",
                bestandteil,
                quelle,
                artefakt_id or str(referenz["id"]),
                sha256 or str(referenz["sha256"]),
                pfad,
                wert,
                art,
            )
        )

    def oeffnen(
        self,
        bestandteil: ModellbestandteilId,
        kategorie: Offenheitskategorie,
        begruendung: str,
        belege: tuple[dict[str, Any], ...] = (),
        herkunft: Kennzeichnungsherkunft = Kennzeichnungsherkunft.SYSTEMATISCH_ERKANNT,
    ) -> None:
        liste = self.offen[bestandteil]
        liste.append(
            OffenerEintrag(
                f"{bestandteil.value}:offen:{len(liste) + 1}",
                bestandteil,
                kategorie,
                begruendung,
                belege,
                herkunft,
            )
        )


def _problem_und_ziele(sammlung: _Sammlung) -> None:
    u = sammlung.basis.projekt.untersuchungsauftrag
    if u.problemstellung:
        sammlung.info(
            ModellbestandteilId.PROBLEMSTELLUNG,
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            "untersuchungsauftrag.problemstellung",
            u.problemstellung,
        )
    else:
        sammlung.oeffnen(
            ModellbestandteilId.PROBLEMSTELLUNG,
            Offenheitskategorie.FEHLEND,
            "In U ist keine Problemstellung dokumentiert.",
        )
    zwecke = u.untersuchungszwecke or ((u.untersuchungszweck,) if u.untersuchungszweck else ())
    for pfad, wert in (
        ("untersuchungsauftrag.untersuchungszwecke", zwecke),
        ("untersuchungsauftrag.individuelles_ziel", u.individuelles_ziel),
        (
            "untersuchungsauftrag.logistische_zielgroessen",
            tuple(ziel.value for ziel in u.logistische_zielgroessen),
        ),
        ("untersuchungsauftrag.ausgewaehlte_kpi_ids", u.ausgewaehlte_kpi_ids),
    ):
        if wert:
            sammlung.info(
                ModellbestandteilId.ZIELSETZUNG,
                Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
                pfad,
                wert,
            )
    if not sammlung.informationen[ModellbestandteilId.ZIELSETZUNG]:
        sammlung.oeffnen(
            ModellbestandteilId.ZIELSETZUNG,
            Offenheitskategorie.FEHLEND,
            "In U ist keine Zielsetzung dokumentiert.",
        )


def _ausgaben_eingaben(sammlung: _Sammlung) -> None:
    u = sammlung.basis.projekt.untersuchungsauftrag
    if u.ausgewaehlte_kpi_ids:
        sammlung.info(
            ModellbestandteilId.AUSGABEN_UND_EINGABEN,
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            "untersuchungsauftrag.ausgewaehlte_kpi_ids",
            u.ausgewaehlte_kpi_ids,
        )
    ergebnisse = sammlung.basis.a_g.get("kpi_ergebnisse", [])
    for index, ergebnis in enumerate(ergebnisse):
        sammlung.info(
            ModellbestandteilId.AUSGABEN_UND_EINGABEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            f"kpi_ergebnisse[{index}]",
            ergebnis,
        )
    sammlung.oeffnen(
        ModellbestandteilId.AUSGABEN_UND_EINGABEN,
        Offenheitskategorie.NICHT_ABLEITBAR,
        "Experimentelle Faktoren, steuerbare Modelleingaben und ihre Wertebereiche sind in "
        "U beziehungsweise A_G fachlich zu ergänzen, sofern sie dort nicht ausdrücklich "
        "dokumentiert sind. Nicht berechenbare KPI werden nicht geschätzt.",
    )


def _umfang(sammlung: _Sammlung, aktivitaeten: tuple[str, ...]) -> None:
    u = sammlung.basis.projekt.untersuchungsauftrag
    if u.systemgrenze:
        sammlung.info(
            ModellbestandteilId.MODELLUMFANG_GRENZEN_DETAILLIERUNG,
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            "untersuchungsauftrag.systemgrenze",
            u.systemgrenze,
        )
    else:
        sammlung.oeffnen(
            ModellbestandteilId.MODELLUMFANG_GRENZEN_DETAILLIERUNG,
            Offenheitskategorie.FEHLEND,
            "In U sind keine Systemgrenzen dokumentiert.",
        )
    if u.detaillierungsgrad:
        sammlung.info(
            ModellbestandteilId.MODELLUMFANG_GRENZEN_DETAILLIERUNG,
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            "untersuchungsauftrag.detaillierungsgrad",
            u.detaillierungsgrad,
        )
    else:
        sammlung.oeffnen(
            ModellbestandteilId.MODELLUMFANG_GRENZEN_DETAILLIERUNG,
            Offenheitskategorie.NICHT_ABLEITBAR,
            "Ein fachlicher Detaillierungsgrad ist nicht ausdrücklich dokumentiert und wird "
            "nicht aus der Aktivitäts- oder Variantenanzahl abgeleitet.",
        )
    sammlung.info(
        ModellbestandteilId.MODELLUMFANG_GRENZEN_DETAILLIERUNG,
        Eingangsartefakt.SYSTEMPROFIL_S,
        "systemprofil",
        {
            "systemtyp": u.systemtyp.value,
            "systemklassifikation": asdict(u.systemklassifikation),
        },
        Uebernahmeart.METADATENZUSAMMENFASSUNG,
    )
    sammlung.info(
        ModellbestandteilId.MODELLUMFANG_GRENZEN_DETAILLIERUNG,
        Eingangsartefakt.PROZESSMODELL_P,
        "sichtbare_aktivitaeten",
        aktivitaeten,
        Uebernahmeart.METADATENZUSAMMENFASSUNG,
    )
    dfg = sammlung.basis.discovery_ergebnisse.get("dfg_daten", {})
    sammlung.info(
        ModellbestandteilId.MODELLUMFANG_GRENZEN_DETAILLIERUNG,
        Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        "discovery_ergebnisse_a_d.dfg.start_und_endaktivitaeten",
        {
            "startaktivitaeten": dfg.get("startaktivitaeten", []),
            "endaktivitaeten": dfg.get("endaktivitaeten", []),
        },
        Uebernahmeart.METADATENZUSAMMENFASSUNG,
    )
    bereich = u.systemklassifikation.bereich
    if bereich and u.systemgrenze and bereich != u.systemgrenze:
        sammlung.info(
            ModellbestandteilId.MODELLUMFANG_GRENZEN_DETAILLIERUNG,
            Eingangsartefakt.SYSTEMPROFIL_S,
            "systemprofil.bereich",
            bereich,
        )
        sammlung.oeffnen(
            ModellbestandteilId.MODELLUMFANG_GRENZEN_DETAILLIERUNG,
            Offenheitskategorie.FACHLICH_UNSICHER,
            "U.systemgrenze und S.bereich enthalten unterschiedliche Belege. Keine Quelle "
            "wurde automatisch bevorzugt.",
            (
                {"artefakt": "U", "pfad": "untersuchungsauftrag.systemgrenze"},
                {"artefakt": "S", "pfad": "systemprofil.bereich"},
            ),
        )
    sammlung.oeffnen(
        ModellbestandteilId.MODELLUMFANG_GRENZEN_DETAILLIERUNG,
        Offenheitskategorie.NICHT_ABLEITBAR,
        "Die beobachtbaren Grenzen und Start-/Endbereiche von P werden nicht automatisch "
        "mit den fachlichen Systemgrenzen aus U gleichgesetzt.",
    )


def _entitaeten_aktivitaeten(sammlung: _Sammlung, aktivitaeten: tuple[str, ...]) -> None:
    objekte = sammlung.basis.projekt.untersuchungsauftrag.systemklassifikation.objekte_gueter
    if objekte:
        sammlung.info(
            ModellbestandteilId.ENTITAETEN,
            Eingangsartefakt.SYSTEMPROFIL_S,
            "systemprofil.objekte_gueter",
            objekte,
        )
    sammlung.info(
        ModellbestandteilId.ENTITAETEN,
        Eingangsartefakt.EVENT_LOG_E_STERN,
        "schema.case_id",
        {
            "kanonisches_attribut": "case_id",
            "fallanzahl": len(
                cast("pd.Series", sammlung.basis.event_log["case_id"]).dropna().unique()
            ),
        },
        Uebernahmeart.METADATENZUSAMMENFASSUNG,
    )
    if not objekte:
        sammlung.oeffnen(
            ModellbestandteilId.ENTITAETEN,
            Offenheitskategorie.NICHT_ABLEITBAR,
            "E* belegt eine fallbezogene Identifikation über case_id, aber keinen fachlichen "
            "Entitätstyp. Dieser darf nicht aus Attributnamen oder -werten erraten werden.",
        )
    if aktivitaeten:
        sammlung.info(
            ModellbestandteilId.AKTIVITAETEN,
            Eingangsartefakt.PROZESSMODELL_P,
            "sichtbare_aktivitaeten",
            aktivitaeten,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    else:
        sammlung.oeffnen(
            ModellbestandteilId.AKTIVITAETEN,
            Offenheitskategorie.NICHT_ABLEITBAR,
            "P enthält keine sichtbaren fachlichen Aktivitäten.",
        )
    optionen = sammlung.basis.a_g.get("optionale_artefakte", {})
    analysebezogen = {
        name: optionen[name]
        for name in (
            "conformance_ergebnisse_a_c",
            "potenzielle_verbesserungspotenziale_a_v",
        )
        if name in optionen
    }
    if analysebezogen:
        sammlung.info(
            ModellbestandteilId.AKTIVITAETEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "optionale_artefakte",
            analysebezogen,
            Uebernahmeart.ARTEFAKTREFERENZ,
        )


def _warteschlangen_ressourcen(sammlung: _Sammlung) -> None:
    kpis = sammlung.basis.a_g.get("kpi_ergebnisse", [])
    warte_kpis = [wert for wert in kpis if wert.get("kpi_id") == "tatsaechliche_wartezeit_aqt"]
    for index, wert in enumerate(warte_kpis):
        sammlung.info(
            ModellbestandteilId.WARTESCHLANGEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            f"kpi_ergebnisse.wartezeit[{index}]",
            wert,
        )
    e_stern = sammlung.basis.event_log
    wartehinweise: list[dict[str, Any]] = []
    if {"case_id", "activity", "start_timestamp", "end_timestamp"} <= set(e_stern.columns):
        arbeitskopie = e_stern.copy(deep=True)
        arbeitskopie["start_timestamp"] = pd.to_datetime(
            arbeitskopie["start_timestamp"], errors="coerce", utc=True
        )
        arbeitskopie["end_timestamp"] = pd.to_datetime(
            arbeitskopie["end_timestamp"], errors="coerce", utc=True
        )
        arbeitskopie = arbeitskopie.dropna(subset=["case_id"])
        arbeitskopie["_reihenfolge"] = range(len(arbeitskopie))
        differenzen: list[dict[str, Any]] = []
        for _, fall in arbeitskopie.groupby("case_id", sort=False, dropna=False):
            sortiert = fall.sort_values(
                ["start_timestamp", "_reihenfolge"], kind="stable", na_position="last"
            )
            for position in range(len(sortiert) - 1):
                aktuell = sortiert.iloc[position]
                folgend = sortiert.iloc[position + 1]
                if (
                    pd.isna(aktuell["activity"])
                    or pd.isna(folgend["activity"])
                    or not str(aktuell["activity"]).strip()
                    or not str(folgend["activity"]).strip()
                    or pd.isna(aktuell["end_timestamp"])
                    or pd.isna(folgend["start_timestamp"])
                ):
                    continue
                delta = folgend["start_timestamp"] - aktuell["end_timestamp"]
                sekunden = float(delta.total_seconds())
                if sekunden <= 0:
                    continue
                differenzen.append(
                    {
                        "von_aktivitaet": str(aktuell["activity"]),
                        "zu_aktivitaet": str(folgend["activity"]),
                        "wartezeit_sekunden": sekunden,
                    }
                )
        if differenzen:
            differenz_tabelle = pd.DataFrame(differenzen)
            for schluessel, gruppe in differenz_tabelle.groupby(
                ["von_aktivitaet", "zu_aktivitaet"], sort=True
            ):
                von, zu = cast(tuple[Hashable, Hashable], schluessel)
                wartezeiten = cast(pd.Series, gruppe["wartezeit_sekunden"])
                wartehinweise.append(
                    {
                        "uebergang": {"von": von, "zu": zu},
                        "positive_hinweise": len(gruppe),
                        "mittlere_wartezeit_sekunden": float(wartezeiten.mean()),
                        "mediane_wartezeit_sekunden": float(wartezeiten.median()),
                    }
                )
            sammlung.info(
                ModellbestandteilId.WARTESCHLANGEN,
                Eingangsartefakt.EVENT_LOG_E_STERN,
                "start_timestamp_end_timestamp.positive_uebergangsdifferenzen",
                tuple(wartehinweise),
                Uebernahmeart.METADATENZUSAMMENFASSUNG,
            )
    if not warte_kpis and not wartehinweise:
        sammlung.oeffnen(
            ModellbestandteilId.WARTESCHLANGEN,
            Offenheitskategorie.NICHT_ABLEITBAR,
            "E* enthält keine ableitbaren positiven Übergangsdifferenzen aus ausdrücklich "
            "vorhandenen Start-/Endzeitstempeln und A_G keine ausdrücklich dokumentierte "
            "Warteinformation. Andere Spalten werden nicht als Warteschlange interpretiert.",
        )
    sammlung.oeffnen(
        ModellbestandteilId.WARTESCHLANGEN,
        Offenheitskategorie.NICHT_ABLEITBAR,
        "Warteschlangendisziplinen, Kapazitäten, Priorisierungsregeln und Wartezustände "
        "erfordern eine fachliche Ergänzung in Schritt 9.",
    )

    profil = sammlung.basis.projekt.untersuchungsauftrag.systemklassifikation
    ressourcen = {
        "produktion": profil.produktion.ressourcen if profil.produktion else (),
        "intralogistik": profil.intralogistik.ressourcen if profil.intralogistik else (),
    }
    if any(ressourcen.values()):
        sammlung.info(
            ModellbestandteilId.RESSOURCEN,
            Eingangsartefakt.SYSTEMPROFIL_S,
            "systemprofil.ressourcen",
            ressourcen,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    if "resource" in sammlung.basis.event_log.columns:
        ressourcendaten = sammlung.basis.event_log.loc[:, ["activity", "resource"]].copy()
        ressourcendaten["activity"] = ressourcendaten["activity"].astype("string").str.strip()
        ressourcendaten["resource"] = ressourcendaten["resource"].astype("string").str.strip()
        ressourcendaten = (
            ressourcendaten.dropna()
            .loc[lambda tabelle: tabelle["activity"].ne("") & tabelle["resource"].ne("")]
            .drop_duplicates()
        )
        gruppiert = tuple(
            {
                "aktivitaet": str(aktivitaet),
                "ressourcen": tuple(sorted(gruppe["resource"].astype(str).unique())),
            }
            for aktivitaet, gruppe in ressourcendaten.groupby("activity", sort=True)
        )
        sammlung.info(
            ModellbestandteilId.RESSOURCEN,
            Eingangsartefakt.EVENT_LOG_E_STERN,
            "schema.resource",
            {
                "attribut": "resource",
                "eindeutige_werte": tuple(sorted(ressourcendaten["resource"].astype(str).unique())),
                "aktivitaet_ressourcen": gruppiert,
            },
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    ressourcen_kpis = [
        wert for wert in kpis if wert.get("kpi_id") in {"nutzungseffizienz_ue", "ruestzeitanteil"}
    ]
    if ressourcen_kpis:
        sammlung.info(
            ModellbestandteilId.RESSOURCEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "kpi_ergebnisse.ressourcenbezogen",
            ressourcen_kpis,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    if "resource" not in sammlung.basis.event_log.columns:
        sammlung.oeffnen(
            ModellbestandteilId.RESSOURCEN,
            Offenheitskategorie.NICHT_ABLEITBAR,
            "E* enthält kein kanonisches Ressourcenattribut resource. Die Zuordnung jeder "
            "Aktivität zu einer oder mehreren Ressourcen muss in Schritt 9 manuell dokumentiert "
            "oder bewusst offen gelassen werden.",
        )
    else:
        sammlung.oeffnen(
            ModellbestandteilId.RESSOURCEN,
            Offenheitskategorie.NICHT_ABLEITBAR,
            "Rollen, Kapazitäten, Verfügbarkeiten und Zuordnungsregeln sind nicht vollständig "
            "aus den ausdrücklich dokumentierten Ressourcenangaben ableitbar.",
        )


def _annahmen(sammlung: _Sammlung) -> None:
    discovery = sammlung.basis.discovery_ergebnisse
    entscheidungen = {
        "schwellwert_k": discovery.get("schwellwert_k"),
        "miner_variante": discovery.get("miner_variante"),
        "prozessnotation": discovery.get("prozessnotation"),
        "discovery_warnungen": discovery.get("warnungen", []),
        "aggregationswarnungen": sammlung.basis.a_g.get("warnungen", []),
    }
    sammlung.info(
        ModellbestandteilId.ANNAHMEN_UND_VEREINFACHUNGEN,
        Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        "discovery_ergebnisse_a_d.modellierungsentscheidungen",
        entscheidungen,
        Uebernahmeart.METADATENZUSAMMENFASSUNG,
    )
    sammlung.info(
        ModellbestandteilId.ANNAHMEN_UND_VEREINFACHUNGEN,
        Eingangsartefakt.PROZESSMODELL_P,
        "prozessnotation",
        sammlung.basis.prozessnotation.value,
    )
    if float(discovery.get("schwellwert_k", 0) or 0) > 0:
        sammlung.info(
            ModellbestandteilId.ANNAHMEN_UND_VEREINFACHUNGEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "discovery_ergebnisse_a_d.schwellwert_k.auswirkung",
            {
                "moegliche_abstraktion": (
                    "Seltenes Verhalten ist möglicherweise nicht in P enthalten."
                ),
                "unveraendert": ("vollständiger DFG", "E*"),
            },
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
        sammlung.oeffnen(
            ModellbestandteilId.ANNAHMEN_UND_VEREINFACHUNGEN,
            Offenheitskategorie.FACHLICH_UNSICHER,
            "Bei k > 0 kann seltenes Verhalten in P abstrahiert sein. Der vollständige DFG und "
            "E* bleiben unberührt; die fachliche Auswirkung ist in Schritt 9 zu prüfen.",
            ({"artefakt": "A_G", "pfad": "discovery_ergebnisse_a_d.schwellwert_k"},),
        )
    sammlung.oeffnen(
        ModellbestandteilId.ANNAHMEN_UND_VEREINFACHUNGEN,
        Offenheitskategorie.NICHT_ABLEITBAR,
        "Fachliche Annahmen und bewusste Vereinfachungen des realen Systems sind aus P und A_G "
        "nicht vollständig ableitbar und müssen in Schritt 9 begründet werden.",
    )


def _daten_und_darstellung(sammlung: _Sammlung) -> None:
    for quelle in sammlung.basis.datenquellen:
        sammlung.info(
            ModellbestandteilId.DATENAUSWAHL_UND_DATEN,
            Eingangsartefakt.DATENQUELLENKATALOG_Q,
            f"datenquellen[{quelle.datenquellen_id}]",
            asdict(quelle),
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
            artefakt_id=str(quelle.datenquellen_id),
        )
    for index, profil in enumerate(sammlung.basis.profilreferenzen):
        sammlung.info(
            ModellbestandteilId.DATENAUSWAHL_UND_DATEN,
            Eingangsartefakt.DATENPROFIL_R,
            f"profile[{index}]",
            profil,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
            artefakt_id=str(profil["import_id"]),
            sha256=str(profil["profil_sha256"]),
        )
    t = sammlung.basis.zwischendatensatz
    sammlung.info(
        ModellbestandteilId.DATENAUSWAHL_UND_DATEN,
        Eingangsartefakt.ZWISCHENDATENSATZ_T,
        "schema_und_referenz",
        {
            "zwischendatensatz_id": str(t.zwischendatensatz_id),
            "zeilenanzahl": t.zeilenanzahl,
            "spaltenanzahl": t.spaltenanzahl,
            "schema": [
                {"name": str(name), "datentyp": str(typ)}
                for name, typ in sammlung.basis.zwischendaten.dtypes.items()
            ],
            "relativer_daten_pfad": t.relativer_daten_pfad,
            "relativer_schema_pfad": t.relativer_schema_pfad,
        },
        Uebernahmeart.METADATENZUSAMMENFASSUNG,
    )
    e = sammlung.basis.event_log
    sammlung.info(
        ModellbestandteilId.DATENAUSWAHL_UND_DATEN,
        Eingangsartefakt.EVENT_LOG_E_STERN,
        "schema_umfang_zeitraum_und_referenz",
        {
            "event_log_id": str(sammlung.basis.freigabe.event_log_id),
            "ereignisanzahl": len(e),
            "fallanzahl": len(cast("pd.Series", e["case_id"]).dropna().unique()),
            "aktivitaetsanzahl": len(cast("pd.Series", e["activity"]).dropna().unique()),
            "zeitraum_von": e["timestamp"].min(),
            "zeitraum_bis": e["timestamp"].max(),
            "schema": [{"name": str(name), "datentyp": str(typ)} for name, typ in e.dtypes.items()],
        },
        Uebernahmeart.METADATENZUSAMMENFASSUNG,
    )
    sammlung.oeffnen(
        ModellbestandteilId.DATENAUSWAHL_UND_DATEN,
        Offenheitskategorie.NICHT_ABLEITBAR,
        "Die Rollen als Kontext-, Modell- oder Validierungsdaten sind nicht ausdrücklich "
        "festgelegt und werden nicht automatisch zugeordnet.",
    )
    sammlung.info(
        ModellbestandteilId.DARSTELLUNG_DER_VORGAENGE,
        Eingangsartefakt.PROZESSMODELL_P,
        "prozessmodell_referenz",
        {
            "prozessmodell_id": str(sammlung.basis.analyse.analyse_id),
            "process_mining_analyse_id": str(sammlung.basis.analyse.analyse_id),
            "notation": sammlung.basis.prozessnotation.value,
            "relativer_pfad": sammlung.basis.analyse.relativer_modell_pfad,
        },
        Uebernahmeart.ARTEFAKTREFERENZ,
    )


def leite_modellbestandteile_ab(
    basis: Any,
    *,
    fachlich_unsichere_bestandteile: frozenset[ModellbestandteilId] = frozenset(),
) -> tuple[tuple[AbgeleiteterModellbestandteil, ...], tuple[OffenerEintrag, ...]]:
    """Ordnet nur belegte Informationen zu und hält jeden Ergänzungsbedarf in O."""
    unbekannt = fachlich_unsichere_bestandteile - set(_DEFINITIONEN)
    if unbekannt:
        raise Domaenenfehler("Mindestens eine menschliche Unsicherheitsmarkierung ist ungültig.")
    aktivitaeten = extrahiere_sichtbare_aktivitaeten(basis.prozessmodell, basis.prozessnotation)
    sammlung = _Sammlung(basis)
    _problem_und_ziele(sammlung)
    _ausgaben_eingaben(sammlung)
    _umfang(sammlung, aktivitaeten)
    _entitaeten_aktivitaeten(sammlung, aktivitaeten)
    _warteschlangen_ressourcen(sammlung)
    _annahmen(sammlung)
    _daten_und_darstellung(sammlung)
    for bestandteil in fachlich_unsichere_bestandteile:
        infos = sammlung.informationen[bestandteil]
        sammlung.oeffnen(
            bestandteil,
            Offenheitskategorie.FACHLICH_UNSICHER,
            "Die anwendende Person hat die vorhandene Zuordnung als fachlich unsicher "
            "gekennzeichnet. Eine Auflösung erfolgt erst in Schritt 9.",
            tuple(
                {
                    "informations_id": info.informations_id,
                    "artefakt": info.herkunftsartefakt.value,
                    "strukturreferenz": info.strukturreferenz,
                }
                for info in infos
            ),
            Kennzeichnungsherkunft.MENSCHLICH_MARKIERT,
        )
    bestandteile: list[AbgeleiteterModellbestandteil] = []
    alle_offenen: list[OffenerEintrag] = []
    for definition in MODELLBESTANDTEILE:
        infos = tuple(sammlung.informationen[definition.bestandteil_id])
        offene = tuple(sammlung.offen[definition.bestandteil_id])
        alle_offenen.extend(offene)
        if any(wert.kategorie is Offenheitskategorie.FACHLICH_UNSICHER for wert in offene):
            status = Bestandteilstatus.FACHLICH_UNSICHER
        elif infos and offene:
            status = Bestandteilstatus.TEILWEISE_OFFEN
        elif infos:
            status = Bestandteilstatus.VOLLSTAENDIG_ZUGEORDNET
        else:
            status = Bestandteilstatus.OFFEN
        bestandteile.append(
            AbgeleiteterModellbestandteil(
                definition.bestandteil_id,
                definition.bezeichnung,
                status,
                _eindeutig(wert.herkunftsartefakt for wert in infos),
                infos,
                tuple(wert.offener_eintrag_id for wert in offene),
            )
        )
    return tuple(bestandteile), tuple(alle_offenen)
