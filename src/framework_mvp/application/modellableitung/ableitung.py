"""Reine, quellengebundene Ableitung gemäß Tabelle 3.15 und Algorithmus 8."""

import tempfile
from collections.abc import Hashable, Iterable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pm4py
from pm4py.objects.bpmn.obj import BPMN

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    AbgeleiteterModellbestandteil,
    Bestandteilstatus,
    Eingangsartefakt,
    FachlicheBestandteilentscheidung,
    FachlicheEntscheidungsart,
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

MAPPINGVERSION = 3

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
        ModellbestandteilId.AUSGABEN,
        "Ausgaben",
        (
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.EINGABEN,
        "Eingaben",
        (Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,),
        True,
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.MODELLUMFANG,
        "Modellumfang",
        (
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            Eingangsartefakt.SYSTEMPROFIL_S,
            Eingangsartefakt.PROZESSMODELL_P,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.MODELLGRENZEN,
        "Modellgrenzen",
        (Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.DETAILLIERUNGSGRAD,
        "Detaillierungsgrad",
        (
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            Eingangsartefakt.SYSTEMPROFIL_S,
            Eingangsartefakt.PROZESSMODELL_P,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
        True,
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.ENTITAETEN,
        "Entitäten",
        (
            Eingangsartefakt.SYSTEMPROFIL_S,
            Eingangsartefakt.EVENT_LOG_E_STERN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
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
        (Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,),
        True,
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.RESSOURCEN,
        "Ressourcen",
        (
            Eingangsartefakt.SYSTEMPROFIL_S,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
        True,
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.ANNAHMEN,
        "Annahmen",
        (
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            Eingangsartefakt.SYSTEMPROFIL_S,
            Eingangsartefakt.PROZESSMODELL_P,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
        True,
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.VEREINFACHUNGEN,
        "Vereinfachungen",
        (
            Eingangsartefakt.PROZESSMODELL_P,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
        True,
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.DATENAUSWAHL,
        "Datenauswahl",
        (
            Eingangsartefakt.DATENQUELLENKATALOG_Q,
            Eingangsartefakt.DATENPROFIL_R,
            Eingangsartefakt.ZWISCHENDATENSATZ_T,
            Eingangsartefakt.EVENT_LOG_E_STERN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.DATEN,
        "Daten",
        (
            Eingangsartefakt.DATENQUELLENKATALOG_Q,
            Eingangsartefakt.DATENPROFIL_R,
            Eingangsartefakt.ZWISCHENDATENSATZ_T,
            Eingangsartefakt.EVENT_LOG_E_STERN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        ),
    ),
    ModellbestandteilDefinition(
        ModellbestandteilId.DARSTELLUNG_DER_VORGAENGE,
        "Darstellung der Vorgänge des Systems",
        (Eingangsartefakt.PROZESSMODELL_P,),
    ),
)

_DEFINITIONEN = {wert.bestandteil_id: wert for wert in MODELLBESTANDTEILE}


def validiere_quellenzuordnung(bestandteil: ModellbestandteilId, quelle: Eingangsartefakt) -> None:
    """Weist jede Quellenkombination außerhalb der aktuellen Tabelle 3.15 zurück."""
    definition = _DEFINITIONEN[bestandteil]
    if quelle not in definition.zulaessige_quellen:
        raise Domaenenfehler(
            f"{quelle.value} ist für '{definition.bezeichnung}' gemäß Tabelle 3.15 unzulässig."
        )


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
        validiere_quellenzuordnung(bestandteil, quelle)
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


def _problem_ziele_ausgaben(sammlung: _Sammlung) -> None:
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
    zielwerte = (
        ("untersuchungsauftrag.untersuchungszwecke", zwecke),
        ("untersuchungsauftrag.individuelles_ziel", u.individuelles_ziel),
        (
            "untersuchungsauftrag.logistische_zielgroessen",
            tuple(ziel.value for ziel in u.logistische_zielgroessen),
        ),
        ("untersuchungsauftrag.ausgewaehlte_kpi_ids", u.ausgewaehlte_kpi_ids),
    )
    for pfad, wert in zielwerte:
        if wert:
            sammlung.info(
                ModellbestandteilId.ZIELSETZUNG,
                Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
                pfad,
                wert,
            )
            sammlung.info(
                ModellbestandteilId.AUSGABEN,
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

    ausgewaehlt = set(u.ausgewaehlte_kpi_ids)
    for index, ergebnis in enumerate(sammlung.basis.a_g.get("kpi_ergebnisse", [])):
        if isinstance(ergebnis, dict) and ergebnis.get("kpi_id") in ausgewaehlt:
            sammlung.info(
                ModellbestandteilId.AUSGABEN,
                Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
                f"kpi_ergebnisse[{index}]",
                ergebnis,
            )
    zieltext = " ".join((*zwecke, u.individuelles_ziel)).casefold()
    conformance = sammlung.basis.a_g.get("conformance_checking", {})
    if (
        isinstance(conformance, dict)
        and conformance.get("durchgefuehrt")
        and any(wort in zieltext for wort in ("konform", "abweich", "sollprozess"))
    ):
        sammlung.info(
            ModellbestandteilId.AUSGABEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "conformance_checking",
            conformance,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    performance = _strukturierte_ergebnisse(sammlung).get("performance_und_engpassanalyse", {})
    if (
        isinstance(performance, dict)
        and performance
        and any(
            wort in zieltext
            for wort in ("leistung", "engpass", "termin", "bearbeitung", "warte", "zeit", "auslast")
        )
    ):
        sammlung.info(
            ModellbestandteilId.AUSGABEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "strukturierte_ergebnisse.performance_und_engpassanalyse",
            performance,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    if not sammlung.informationen[ModellbestandteilId.AUSGABEN]:
        sammlung.oeffnen(
            ModellbestandteilId.AUSGABEN,
            Offenheitskategorie.FEHLEND,
            "U und A_G enthalten keine zum Untersuchungszweck belegte Ausgabe.",
        )


def _eingaben_umfang_grenzen_detail(sammlung: _Sammlung, aktivitaeten: tuple[str, ...]) -> None:
    u = sammlung.basis.projekt.untersuchungsauftrag
    sammlung.oeffnen(
        ModellbestandteilId.EINGABEN,
        Offenheitskategorie.FEHLEND,
        "U dokumentiert keine konkreten experimentellen Faktoren mit möglichen Wertebereichen. "
        "Zeitgrößen und Ressourcenkapazitäten aus A_G werden nicht automatisch zu Eingaben.",
    )
    sammlung.info(
        ModellbestandteilId.MODELLUMFANG,
        Eingangsartefakt.SYSTEMPROFIL_S,
        "systemprofil",
        {"systemtyp": u.systemtyp.value, "systemklassifikation": asdict(u.systemklassifikation)},
        Uebernahmeart.METADATENZUSAMMENFASSUNG,
    )
    if aktivitaeten:
        sammlung.info(
            ModellbestandteilId.MODELLUMFANG,
            Eingangsartefakt.PROZESSMODELL_P,
            "sichtbare_aktivitaeten",
            aktivitaeten,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    dfg = sammlung.basis.a_g.get("prozessbelege", {}).get("start_und_endaktivitaeten", {})
    if isinstance(dfg, dict) and dfg:
        sammlung.info(
            ModellbestandteilId.MODELLUMFANG,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "prozessbelege.start_und_endaktivitaeten",
            dfg,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )

    if u.systemgrenze:
        sammlung.info(
            ModellbestandteilId.MODELLGRENZEN,
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            "untersuchungsauftrag.systemgrenze",
            u.systemgrenze,
        )
    ausschluesse = u.rahmenbedingungen.bekannte_ausschluesse
    if ausschluesse:
        sammlung.info(
            ModellbestandteilId.MODELLGRENZEN,
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            "untersuchungsauftrag.rahmenbedingungen.bekannte_ausschluesse",
            ausschluesse,
        )
    if not sammlung.informationen[ModellbestandteilId.MODELLGRENZEN]:
        sammlung.oeffnen(
            ModellbestandteilId.MODELLGRENZEN,
            Offenheitskategorie.FEHLEND,
            "In U sind keine Modell- oder Systemgrenzen dokumentiert.",
        )

    if u.detaillierungsgrad:
        sammlung.info(
            ModellbestandteilId.DETAILLIERUNGSGRAD,
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            "untersuchungsauftrag.detaillierungsgrad",
            u.detaillierungsgrad,
        )
    else:
        sammlung.oeffnen(
            ModellbestandteilId.DETAILLIERUNGSGRAD,
            Offenheitskategorie.FEHLEND,
            "Ein fachlich bestätigter Detaillierungsgrad ist nicht in U dokumentiert.",
        )
    sammlung.info(
        ModellbestandteilId.DETAILLIERUNGSGRAD,
        Eingangsartefakt.PROZESSMODELL_P,
        "prozessmodell_abstraktion",
        {
            "notation": sammlung.basis.prozessnotation.value,
            "sichtbare_aktivitaeten": len(aktivitaeten),
        },
        Uebernahmeart.METADATENZUSAMMENFASSUNG,
    )
    discovery_referenz = sammlung.basis.a_g.get("discovery_ergebnisse_a_d", {})
    k_roh = (
        discovery_referenz.get("schwellwert_k") if isinstance(discovery_referenz, dict) else None
    )
    if isinstance(k_roh, (int, float)) and not isinstance(k_roh, bool) and float(k_roh) > 0:
        k = float(k_roh)
        sammlung.info(
            ModellbestandteilId.DETAILLIERUNGSGRAD,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "discovery_ergebnisse_a_d.schwellwert_k",
            {
                "filterparameter_k": k,
                "bedeutung": (
                    "Seltenes Verhalten wurde im datengetrieben entdeckten Prozessmodell P "
                    "teilweise ausgefiltert; dies legt nicht den Detaillierungsgrad des "
                    "gesamten konzeptionellen Modells fest."
                ),
            },
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )


def _strukturierte_ergebnisse(sammlung: _Sammlung) -> dict[str, Any]:
    wert = sammlung.basis.a_g.get("strukturierte_ergebnisse", {})
    return wert if isinstance(wert, dict) else {}


def _entitaeten_aktivitaeten(sammlung: _Sammlung, aktivitaeten: tuple[str, ...]) -> None:
    u = sammlung.basis.projekt.untersuchungsauftrag
    entitaetstyp = u.systemklassifikation.objekte_gueter
    strukturiert = _strukturierte_ergebnisse(sammlung)
    entitaeten = strukturiert.get("entitaetsinstanzen_und_attribute", {})
    zeitdaten = strukturiert.get("zeitbezogene_datenauswahl", {})
    umfang = zeitdaten.get("umfang_e_stern", {}) if isinstance(zeitdaten, dict) else {}
    if entitaetstyp:
        sammlung.info(
            ModellbestandteilId.ENTITAETEN,
            Eingangsartefakt.SYSTEMPROFIL_S,
            "systemprofil.objekte_gueter",
            entitaetstyp,
        )
    sammlung.info(
        ModellbestandteilId.ENTITAETEN,
        Eingangsartefakt.EVENT_LOG_E_STERN,
        "schema.case_id",
        {"instanzidentifikation": "case_id", "beobachtete_instanzanzahl": umfang.get("fallanzahl")},
        Uebernahmeart.METADATENZUSAMMENFASSUNG,
    )
    if isinstance(entitaeten, dict) and entitaeten:
        sammlung.info(
            ModellbestandteilId.ENTITAETEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "strukturierte_ergebnisse.entitaetsinstanzen_und_attribute",
            entitaeten,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    if not entitaetstyp and not (isinstance(entitaeten, dict) and entitaeten.get("entitaetstyp")):
        sammlung.oeffnen(
            ModellbestandteilId.ENTITAETEN,
            Offenheitskategorie.NICHT_ABLEITBAR,
            "E*.case_id belegt Entitätsinstanzen, aber keinen fachlichen Entitätstyp. "
            "Maschinen werden nicht als Entitäten interpretiert.",
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
    prozessbelege = sammlung.basis.a_g.get("prozessbelege", {})
    if isinstance(prozessbelege, dict) and prozessbelege:
        sammlung.info(
            ModellbestandteilId.AKTIVITAETEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "prozessbelege",
            prozessbelege,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )


def _warteschlangen_ressourcen(sammlung: _Sammlung) -> None:
    strukturiert = _strukturierte_ergebnisse(sammlung)
    wartedaten = strukturiert.get("warteschlangen_und_wartezeiten", {})
    bestaetigt = (
        wartedaten.get("bestaetigte_warteschlangen", []) if isinstance(wartedaten, dict) else []
    )
    if bestaetigt:
        sammlung.info(
            ModellbestandteilId.WARTESCHLANGEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "strukturierte_ergebnisse.warteschlangen_und_wartezeiten.bestaetigte_warteschlangen",
            bestaetigt,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    else:
        sammlung.oeffnen(
            ModellbestandteilId.WARTESCHLANGEN,
            Offenheitskategorie.NICHT_ABLEITBAR,
            "A_G enthält keine explizit bestätigte Warteschlange. Potenzielle Wartezeiten "
            "belegen allein keine Warteschlange.",
            (
                {
                    "artefakt": "A_G",
                    "pfad": "strukturierte_ergebnisse.warteschlangen_und_wartezeiten",
                },
            ),
        )

    profil = sammlung.basis.projekt.untersuchungsauftrag.systemklassifikation
    ressourcentypen = {
        "produktion": profil.produktion.ressourcen if profil.produktion else (),
        "intralogistik": profil.intralogistik.ressourcen if profil.intralogistik else (),
    }
    if any(ressourcentypen.values()):
        sammlung.info(
            ModellbestandteilId.RESSOURCEN,
            Eingangsartefakt.SYSTEMPROFIL_S,
            "systemprofil.ressourcen",
            ressourcentypen,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    ressourcen = strukturiert.get("ressourcen", {})
    if isinstance(ressourcen, dict) and ressourcen:
        sammlung.info(
            ModellbestandteilId.RESSOURCEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "strukturierte_ergebnisse.ressourcen",
            ressourcen,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    zuordnungen = ressourcen.get("zuordnungen", []) if isinstance(ressourcen, dict) else []
    ist_offen = any(wert.get("offen") for wert in zuordnungen if isinstance(wert, dict))
    if not ressourcen or ressourcen.get("modus") == "nicht_moeglich" or ist_offen:
        sammlung.oeffnen(
            ModellbestandteilId.RESSOURCEN,
            Offenheitskategorie.NICHT_ABLEITBAR,
            str(ressourcen.get("begruendung"))
            if isinstance(ressourcen, dict) and ressourcen.get("begruendung")
            else (
                "Mindestens eine Ressourcenbeziehung oder Ressourceneigenschaft ist fachlich offen."
            ),
        )


def _annahmen_vereinfachungen(sammlung: _Sammlung) -> None:
    annahmen = sammlung.basis.projekt.untersuchungsauftrag.rahmenbedingungen.bekannte_annahmen
    if annahmen:
        sammlung.info(
            ModellbestandteilId.ANNAHMEN,
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
            "untersuchungsauftrag.rahmenbedingungen.bekannte_annahmen",
            annahmen,
        )
    else:
        sammlung.oeffnen(
            ModellbestandteilId.ANNAHMEN,
            Offenheitskategorie.FEHLEND,
            "Es sind keine expliziten fachlichen Annahmen dokumentiert. Technische Parameter "
            "werden nicht automatisch als Annahmen ausgelegt.",
        )
    discovery_referenz = sammlung.basis.a_g.get("discovery_ergebnisse_a_d", {})
    k_roh = (
        discovery_referenz.get("schwellwert_k") if isinstance(discovery_referenz, dict) else None
    )
    if isinstance(k_roh, (int, float)) and not isinstance(k_roh, bool) and float(k_roh) > 0:
        k = float(k_roh)
        sammlung.info(
            ModellbestandteilId.VEREINFACHUNGEN,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "discovery_ergebnisse_a_d.schwellwert_k.auswirkung",
            {
                "filterparameter_k": k,
                "beobachtbare_tatsache": (
                    "Bei der Process Discovery wurde ein Filterparameter verwendet, durch den "
                    "seltenes Verhalten gegenüber dem vollständigen Event Log abstrahiert wurde."
                ),
            },
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    else:
        sammlung.oeffnen(
            ModellbestandteilId.VEREINFACHUNGEN,
            Offenheitskategorie.NICHT_ABLEITBAR,
            "A_G belegt keine Filterabstraktion k > 0. Daraus folgt nicht, dass keine weiteren "
            "Vereinfachungen vorliegen; weitere bewusste Abstraktionen sind nicht dokumentiert.",
        )


def _daten(sammlung: _Sammlung) -> None:
    strukturierte = _strukturierte_ergebnisse(sammlung)
    zeitdaten = strukturierte.get("zeitbezogene_datenauswahl", {})
    for quelle in sammlung.basis.datenquellen:
        auswahlwert = {
            "datenquellen_id": str(quelle.datenquellen_id),
            "bezeichnung": quelle.bezeichnung,
            "quellsystemtyp": quelle.quellsystemtyp.value,
            "quellenart": quelle.quellenart.value,
        }
        for bestandteil in (ModellbestandteilId.DATENAUSWAHL, ModellbestandteilId.DATEN):
            sammlung.info(
                bestandteil,
                Eingangsartefakt.DATENQUELLENKATALOG_Q,
                f"datenquellen[{quelle.datenquellen_id}]",
                auswahlwert if bestandteil is ModellbestandteilId.DATENAUSWAHL else asdict(quelle),
                Uebernahmeart.METADATENZUSAMMENFASSUNG,
                artefakt_id=str(quelle.datenquellen_id),
            )
    for index, profil in enumerate(sammlung.basis.profilreferenzen):
        for bestandteil in (ModellbestandteilId.DATENAUSWAHL, ModellbestandteilId.DATEN):
            sammlung.info(
                bestandteil,
                Eingangsartefakt.DATENPROFIL_R,
                f"profile[{index}]",
                profil,
                Uebernahmeart.METADATENZUSAMMENFASSUNG,
                artefakt_id=str(profil["import_id"]),
                sha256=str(profil["profil_sha256"]),
            )
    t = sammlung.basis.zwischendatensatz
    t_wert = {
        "zwischendatensatz_id": str(t.zwischendatensatz_id),
        "zeilenanzahl": t.zeilenanzahl,
        "spaltenanzahl": t.spaltenanzahl,
        "schema": zeitdaten.get("schema_t", []) if isinstance(zeitdaten, dict) else [],
        "relativer_daten_pfad": t.relativer_daten_pfad,
        "relativer_schema_pfad": t.relativer_schema_pfad,
    }
    umfang = zeitdaten.get("umfang_e_stern", {}) if isinstance(zeitdaten, dict) else {}
    e_wert = {
        "event_log_id": str(sammlung.basis.freigabe.event_log_id),
        **umfang,
        "schema": zeitdaten.get("schema_e_stern", []) if isinstance(zeitdaten, dict) else [],
    }
    for bestandteil in (ModellbestandteilId.DATENAUSWAHL, ModellbestandteilId.DATEN):
        sammlung.info(
            bestandteil,
            Eingangsartefakt.ZWISCHENDATENSATZ_T,
            "schema_und_referenz",
            t_wert,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
        sammlung.info(
            bestandteil,
            Eingangsartefakt.EVENT_LOG_E_STERN,
            "schema_umfang_zeitraum_und_referenz",
            e_wert,
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    if isinstance(zeitdaten, dict) and zeitdaten:
        sammlung.info(
            ModellbestandteilId.DATENAUSWAHL,
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
            "strukturierte_ergebnisse.zeitbezogene_datenauswahl",
            {
                "bestaetigte_datenbasis": zeitdaten.get("bestaetigte_datenbasis", []),
                "datenbasis_referenzen": zeitdaten.get("datenbasis_referenzen", {}),
                "bearbeitungszeiten": zeitdaten.get("bearbeitungszeiten", []),
                "zwischenankunftszeiten": zeitdaten.get("zwischenankunftszeiten", []),
                "potenzielle_wartezeiten": zeitdaten.get(
                    "potenzielle_wartezeiten", zeitdaten.get("uebergangswartezeiten", [])
                ),
            },
            Uebernahmeart.METADATENZUSAMMENFASSUNG,
        )
    else:
        sammlung.oeffnen(
            ModellbestandteilId.DATENAUSWAHL,
            Offenheitskategorie.NICHT_ABLEITBAR,
            "A_G enthält keine strukturierte Datenauswahl; Schritt 8 berechnet sie nicht neu.",
        )
    sammlung.info(
        ModellbestandteilId.DATEN,
        Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G,
        "strukturierte_ergebnisse.metadaten",
        {
            "ergebnisversion": strukturierte.get("ergebnisversion"),
            "enthaltene_bereiche": sorted(strukturierte),
            "artefaktversion_a_g": sammlung.basis.a_g.get("artefaktversion"),
            "artefakt_pruefsummen": sammlung.basis.a_g.get("artefakt_pruefsummen", {}),
        },
        Uebernahmeart.METADATENZUSAMMENFASSUNG,
    )
    sammlung.info(
        ModellbestandteilId.DARSTELLUNG_DER_VORGAENGE,
        Eingangsartefakt.PROZESSMODELL_P,
        "prozessmodell_referenz",
        {
            "prozessmodell_id": str(sammlung.basis.analyse.analyse_id),
            "notation": sammlung.basis.prozessnotation.value,
            "relativer_pfad": sammlung.basis.analyse.relativer_modell_pfad,
            "sha256": sammlung.basis.quellreferenzen[Eingangsartefakt.PROZESSMODELL_P]["sha256"],
        },
        Uebernahmeart.ARTEFAKTREFERENZ,
    )


def _status(
    infos: tuple[Informationseintrag, ...], offene: tuple[OffenerEintrag, ...]
) -> Bestandteilstatus:
    if any(wert.kategorie is Offenheitskategorie.FACHLICH_UNSICHER for wert in offene):
        return Bestandteilstatus.FACHLICH_UNSICHER
    if infos and offene:
        return Bestandteilstatus.TEILWEISE_OFFEN
    if infos:
        return Bestandteilstatus.VOLLSTAENDIG_ZUGEORDNET
    return Bestandteilstatus.OFFEN


def leite_modellbestandteile_ab(
    basis: Any,
) -> tuple[tuple[AbgeleiteterModellbestandteil, ...], tuple[OffenerEintrag, ...]]:
    """Erzeugt unverbindliche, quellengebundene Vorschläge und systematische offene Punkte."""
    aktivitaeten = extrahiere_sichtbare_aktivitaeten(basis.prozessmodell, basis.prozessnotation)
    sammlung = _Sammlung(basis)
    _problem_ziele_ausgaben(sammlung)
    _eingaben_umfang_grenzen_detail(sammlung, aktivitaeten)
    _entitaeten_aktivitaeten(sammlung, aktivitaeten)
    _warteschlangen_ressourcen(sammlung)
    _annahmen_vereinfachungen(sammlung)
    _daten(sammlung)
    bestandteile: list[AbgeleiteterModellbestandteil] = []
    alle_offenen: list[OffenerEintrag] = []
    for definition in MODELLBESTANDTEILE:
        infos = tuple(sammlung.informationen[definition.bestandteil_id])
        offene = tuple(sammlung.offen[definition.bestandteil_id])
        alle_offenen.extend(offene)
        bestandteile.append(
            AbgeleiteterModellbestandteil(
                definition.bestandteil_id,
                definition.bezeichnung,
                _status(infos, offene),
                _eindeutig(wert.herkunftsartefakt for wert in infos),
                infos,
                tuple(wert.offener_eintrag_id for wert in offene),
            )
        )
    return tuple(bestandteile), tuple(alle_offenen)


def wende_fachliche_entscheidungen_an(
    vorschlaege: tuple[AbgeleiteterModellbestandteil, ...],
    systematische_offene: tuple[OffenerEintrag, ...],
    entscheidungen: tuple[FachlicheBestandteilentscheidung, ...],
) -> tuple[tuple[AbgeleiteterModellbestandteil, ...], tuple[OffenerEintrag, ...]]:
    """Überführt ausschließlich explizit bestätigte Vorschläge nach K und den Rest nach O."""
    nach_id = {wert.bestandteil_id: wert for wert in entscheidungen}
    if len(nach_id) != len(entscheidungen) or set(nach_id) - set(_DEFINITIONEN):
        raise Domaenenfehler("Die fachlichen Entscheidungen sind nicht eindeutig oder ungültig.")
    offene_nach_id: dict[ModellbestandteilId, list[OffenerEintrag]] = {
        definition.bestandteil_id: [] for definition in MODELLBESTANDTEILE
    }
    for eintrag in systematische_offene:
        offene_nach_id[eintrag.bestandteil_id].append(eintrag)
    ergebnis: list[AbgeleiteterModellbestandteil] = []
    for vorschlag in vorschlaege:
        entscheidung = nach_id.get(vorschlag.bestandteil_id)
        infos: tuple[Informationseintrag, ...] = ()
        if (
            entscheidung is not None
            and entscheidung.entscheidung is FachlicheEntscheidungsart.UEBERNEHMEN
        ):
            infos = tuple(
                replace(
                    info,
                    fachliche_entscheidung=entscheidung.entscheidung,
                    bestaetigt_am=entscheidung.entschieden_am,
                )
                for info in vorschlag.informationen
            )
        elif entscheidung is not None:
            offene = offene_nach_id[vorschlag.bestandteil_id]
            offene.append(
                OffenerEintrag(
                    f"{vorschlag.bestandteil_id.value}:offen:{len(offene) + 1}",
                    vorschlag.bestandteil_id,
                    Offenheitskategorie.FACHLICH_UNSICHER,
                    entscheidung.begruendung,
                    tuple(
                        {
                            "informations_id": info.informations_id,
                            "artefakt": info.herkunftsartefakt.value,
                            "herkunftsartefakt_id": info.herkunftsartefakt_id,
                            "herkunftsartefakt_sha256": info.herkunftsartefakt_sha256,
                            "strukturreferenz": info.strukturreferenz,
                            "wert": info.wert,
                            "uebernahmeart": info.uebernahmeart.value,
                        }
                        for info in vorschlag.informationen
                    ),
                    Kennzeichnungsherkunft.MENSCHLICH_MARKIERT,
                    "offen",
                    entscheidung.entscheidung,
                    entscheidung.entschieden_am,
                )
            )
        offene = tuple(offene_nach_id[vorschlag.bestandteil_id])
        ergebnis.append(
            AbgeleiteterModellbestandteil(
                vorschlag.bestandteil_id,
                vorschlag.bezeichnung,
                _status(infos, offene),
                _eindeutig(wert.herkunftsartefakt for wert in infos),
                infos,
                tuple(wert.offener_eintrag_id for wert in offene),
                entscheidung,
            )
        )
    alle_offenen = tuple(
        eintrag
        for definition in MODELLBESTANDTEILE
        for eintrag in offene_nach_id[definition.bestandteil_id]
    )
    return tuple(ergebnis), alle_offenen
