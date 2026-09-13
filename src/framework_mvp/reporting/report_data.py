"""Formatneutrale Aufbereitung eines validierten K* für alle Reportlayouts."""

import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID

from framework_mvp.formatierung import (
    formatiere_anteil_als_prozent,
    formatiere_messwert,
    formatiere_zeitstempel,
)

REPORT_DATA_VERSION = 2

ERWARTETE_BESTANDTEIL_IDS = (
    "problemstellung",
    "zielsetzung",
    "ausgaben",
    "eingaben",
    "modellumfang",
    "modellgrenzen",
    "detaillierungsgrad",
    "entitaeten",
    "aktivitaeten",
    "warteschlangen",
    "ressourcen",
    "annahmen",
    "vereinfachungen",
    "datenauswahl",
    "daten",
    "darstellung_der_vorgaenge_des_systems",
)

_HISTORISCHE_BESTANDTEIL_IDS = (
    "problemstellung",
    "zielsetzung",
    "ausgaben_und_eingaben",
    "modellumfang_grenzen_detaillierungsgrad",
    "entitaeten",
    "aktivitaeten",
    "warteschlangen",
    "ressourcen",
    "annahmen_und_vereinfachungen",
    "datenauswahl_und_daten",
    "darstellung_der_vorgaenge_des_systems",
)

_ANZEIGETEXTE = {
    "fachlich_validiert": "Fachlich validiert",
    "vollstaendig_zugeordnet": "Vollständig zugeordnet",
    "teilweise_offen": "Teilweise offen",
    "fachlich_unsicher": "Fachlich unsicher",
    "offen": "Offen",
    "nicht_berechenbar": "Nicht berechenbar",
    "berechnet": "Berechnet",
    "fuer_spaetere_manuelle_berechnung_vorgesehen": ("Für spätere manuelle Berechnung vorgesehen"),
    "automatisch_berechnen": "Aus den Daten berechnen",
    "spaeter_manuell_berechnen": "Später manuell berechnen",
    "qualitaet_erhoehen": "Qualität erhöhen",
    "liefertreue_erhoehen": "Liefertreue erhöhen",
    "erp_system": "ERP-System",
    "me_system": "MES",
    "wm_system": "Lagerverwaltungssystem",
    "datei_export": "Dateiexport",
    "sonstiges_system": "Sonstiges System",
    "excel": "XLSX",
    "csv": "CSV",
    "datenbank": "Datenbank",
    "gesamtsystem": "Gesamtsystem",
    "entitaet": "Entität",
    "aktivitaet": "Aktivität",
    "warteschlange": "Warteschlange",
    "ressource": "Ressource",
    "petrinetz": "Petrinetz",
    "prozessbaum": "Prozessbaum",
    "bpmn": "BPMN",
    "direkte_uebernahme": "Direkte Übernahme",
    "metadatenzusammenfassung": "Metadatenzusammenfassung",
    "artefaktreferenz": "Artefaktreferenz",
}


class ReportDataFehler(ValueError):
    """Kennzeichnet eine mit der Report-Datenstruktur inkompatible K*-Struktur."""


def _normalisieren(wert: Any) -> Any:
    """Überführt Werte in ausschließlich Jinja-/JSON-freundliche Python-Typen."""
    if isinstance(wert, datetime | date):
        return formatiere_zeitstempel(wert)
    if isinstance(wert, str):
        return formatiere_zeitstempel(wert)
    if isinstance(wert, (UUID, Enum)):
        return str(wert.value if isinstance(wert, Enum) else wert)
    if is_dataclass(wert):
        return _normalisieren(asdict(cast(Any, wert)))
    if isinstance(wert, Mapping):
        return {str(name): _normalisieren(inhalt) for name, inhalt in wert.items()}
    if isinstance(wert, (tuple, list, set, frozenset)):
        return [_normalisieren(inhalt) for inhalt in wert]
    return wert


def _conformance_aufbereiten(wert: Mapping[str, Any]) -> dict[str, Any]:
    """Ergänzt reine Anzeigewerte, während Fitness als Rohanteil erhalten bleibt."""
    ergebnis = _normalisieren(wert)
    if not isinstance(ergebnis, dict):
        return {}
    details = ergebnis.get("ergebnis")
    if isinstance(details, dict) and details.get("fitness") is not None:
        details["fitness_anzeige"] = formatiere_anteil_als_prozent(details["fitness"])
    return ergebnis


REPORT_LIST_LIMIT = 20
REPORT_RESSOURCEN_JE_AKTIVITAET_LIMIT = 10


def _reportwert_begrenzen(wert: Any) -> Any:
    """Begrenzt große Listen ausschließlich für die Reportdarstellung."""
    if isinstance(wert, Mapping):
        return {str(name): _reportwert_begrenzen(inhalt) for name, inhalt in wert.items()}

    if isinstance(wert, (list, tuple, set, frozenset)):
        return [_reportwert_begrenzen(inhalt) for inhalt in list(wert)[:REPORT_LIST_LIMIT]]

    return _normalisieren(wert)


def _anzeigetext(wert: Any) -> str:
    """Liefert nur für ausdrücklich bekannte Codes eine lesbare Bezeichnung."""
    if wert is None:
        return ""
    text = str(wert)
    return _ANZEIGETEXTE.get(text, text)


def _listenwert(wert: Any) -> list[Any]:
    """Normalisiert einen optionalen Einzel- oder Listenwert zu einer Liste."""
    normalisiert = _normalisieren(wert)
    if normalisiert is None or normalisiert == "":
        return []
    if isinstance(normalisiert, list):
        return normalisiert
    return [normalisiert]


def _code_liste(wert: Any) -> list[dict[str, str]]:
    """Bewahrt technische IDs und ergänzt optional einen lesbaren Anzeigetext."""
    return [
        {
            "id": str(eintrag),
            "bezeichnung": _anzeigetext(eintrag),
        }
        for eintrag in _listenwert(wert)
    ]


def _bestandteile_nach_id(k_stern: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Indiziert aktuelle 16er- sowie historische 11er-Bestandteile."""
    roh = k_stern.get("modellbestandteile")
    if not isinstance(roh, list):
        raise ReportDataFehler("K* enthält keine gültige Liste der Modellbestandteile.")

    ergebnis: dict[str, Mapping[str, Any]] = {}
    for bestandteil in roh:
        if not isinstance(bestandteil, Mapping):
            raise ReportDataFehler("Ein Modellbestandteil besitzt keine gültige Struktur.")
        bestandteil_id = str(bestandteil.get("bestandteil_id", ""))
        if not bestandteil_id:
            raise ReportDataFehler("Ein Modellbestandteil besitzt keine Bestandteil-ID.")
        if bestandteil_id in ergebnis:
            raise ReportDataFehler(f"Der Modellbestandteil '{bestandteil_id}' kommt mehrfach vor.")
        ergebnis[bestandteil_id] = bestandteil

    vorhanden = set(ergebnis)
    aktuell = set(ERWARTETE_BESTANDTEIL_IDS)
    historisch = set(_HISTORISCHE_BESTANDTEIL_IDS)
    if vorhanden not in (aktuell, historisch):
        erwartet = aktuell
        fehlend = sorted(erwartet - vorhanden)
        unerwartet = sorted(vorhanden - erwartet)
        raise ReportDataFehler(
            "Die K*-Struktur passt nicht zur Report-Datenversion. "
            f"Fehlend: {fehlend or 'keine'}; "
            f"unerwartet: {unerwartet or 'keine'}."
        )

    return ergebnis


def _kombiniere_bestandteile(
    *bestandteile: Mapping[str, Any],
) -> dict[str, Any]:
    """Projiziert getrennte V3-Bestandteile verlustfrei auf das bestehende Reportlayout."""
    erster = bestandteile[0]
    informationen: list[Any] = []
    bekannte_referenzen: dict[str, Any] = {}
    menschliche_eintraege: list[Any] = []
    for bestandteil in bestandteile:
        original = bestandteil.get("urspruenglicher_bestandteil", {})
        if isinstance(original, Mapping) and isinstance(original.get("informationen"), list):
            for eintrag in original["informationen"]:
                if not isinstance(eintrag, Mapping):
                    informationen.append(eintrag)
                    continue
                referenz = str(eintrag.get("strukturreferenz", ""))
                wert = _normalisieren(eintrag.get("wert"))
                if referenz in bekannte_referenzen and bekannte_referenzen[referenz] == wert:
                    continue
                if referenz and referenz not in bekannte_referenzen:
                    bekannte_referenzen[referenz] = wert
                informationen.append(eintrag)
        eintraege = bestandteil.get("menschliche_eintraege", [])
        if isinstance(eintraege, list):
            menschliche_eintraege.extend(eintraege)
    original_erster = erster.get("urspruenglicher_bestandteil", {})
    original = dict(original_erster) if isinstance(original_erster, Mapping) else {}
    original["informationen"] = informationen
    return {
        **dict(erster),
        "urspruenglicher_bestandteil": original,
        "menschliche_eintraege": menschliche_eintraege,
    }


def _informationen(bestandteil: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    original = bestandteil.get("urspruenglicher_bestandteil", {})
    if not isinstance(original, Mapping):
        return []
    roh = original.get("informationen", [])
    if not isinstance(roh, list):
        return []
    return [wert for wert in roh if isinstance(wert, Mapping)]


def _info_wert(
    bestandteil: Mapping[str, Any],
    strukturreferenz: str,
    standard: Any = None,
) -> Any:
    """Liest genau eine bekannte Strukturreferenz aus einem Modellbestandteil."""
    treffer = [
        information
        for information in _informationen(bestandteil)
        if information.get("strukturreferenz") == strukturreferenz
    ]
    if not treffer:
        return _normalisieren(standard)
    if len(treffer) > 1:
        raise ReportDataFehler(f"Die Strukturreferenz '{strukturreferenz}' ist nicht eindeutig.")
    return _normalisieren(treffer[0].get("wert"))


def _info_werte_mit_praefix(
    bestandteil: Mapping[str, Any],
    praefix: str,
) -> list[Any]:
    """Liest dynamisch indizierte Referenzen wie kpi_ergebnisse[n] oder profile[n]."""
    return [
        _normalisieren(information.get("wert"))
        for information in _informationen(bestandteil)
        if str(information.get("strukturreferenz", "")).startswith(praefix)
    ]


def _wartestellenhinweise(quelle: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Projiziert potenzielle Wartezeiten aus A_G in die gemeinsame Reportstruktur."""
    ergebnis: list[dict[str, Any]] = []
    for uebergang in _listenwert(
        quelle.get("potenzielle_wartezeiten", quelle.get("uebergaenge", []))
    ):
        if not isinstance(uebergang, Mapping):
            continue
        statistik = uebergang.get("statistik", {})
        if not isinstance(statistik, Mapping):
            statistik = {}
        ergebnis.append(
            {
                "uebergang": {
                    "von": uebergang.get("von_aktivitaet"),
                    "zu": uebergang.get("zu_aktivitaet"),
                },
                "anzahl": statistik.get("anzahl"),
                "mittlere_wartezeit_sekunden": statistik.get("mittelwert_sekunden"),
                "mediane_wartezeit_sekunden": statistik.get("median_sekunden"),
            }
        )
    return ergebnis


def _fachliche_entscheidungen(
    k_stern: Mapping[str, Any],
    bestandteil_id: str,
) -> list[dict[str, Any]]:
    """Liefert Behandlungen offener Einträge als Validierungsinformation."""
    roh = k_stern.get("behandlungen_offener_eintraege", [])
    if not isinstance(roh, list):
        return []
    return [
        cast(dict[str, Any], _normalisieren(wert))
        for wert in roh
        if isinstance(wert, Mapping) and str(wert.get("bestandteil_id", "")) == bestandteil_id
    ]


def _fachliche_anpassungen(
    bestandteil: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Liefert nur echte Modellinhalte; unbekannt/nicht anwendbar bleiben Entscheidungen."""
    roh = bestandteil.get("menschliche_eintraege", [])
    if not isinstance(roh, list):
        return []

    ergebnis: list[dict[str, Any]] = []
    for eintrag in roh:
        if not isinstance(eintrag, Mapping):
            continue
        if eintrag.get("eintragstyp") == "zusaetzliche_anpassung":
            ergebnis.append(
                {
                    "anpassungsnummer": eintrag.get("anpassungsnummer"),
                    "fachlicher_inhalt": str(eintrag.get("fachlicher_inhalt", "")),
                    "begruendung": str(eintrag.get("begruendung", "")),
                    "menschliche_entscheidung": bool(eintrag.get("menschliche_entscheidung")),
                }
            )
            continue
        struktur = eintrag.get("strukturierter_inhalt")
        if (
            eintrag.get("eintragstyp") == "behandlung_offener_eintrag"
            and eintrag.get("modellinhalt_erzeugt") is True
            and isinstance(struktur, Mapping)
            and struktur
        ):
            ergebnis.append(
                {
                    "offener_eintrag_id": eintrag.get("offener_eintrag_id"),
                    "fachlicher_inhalt": json.dumps(
                        _normalisieren(struktur), ensure_ascii=False, sort_keys=True
                    ),
                    "strukturierter_inhalt": _normalisieren(struktur),
                    "begruendung": str(eintrag.get("kommentar", eintrag.get("begruendung", ""))),
                    "menschliche_entscheidung": bool(eintrag.get("menschliche_entscheidung")),
                }
            )
    return ergebnis


def _strukturierte_menschliche_inhalte(
    bestandteil: Mapping[str, Any],
    strukturtyp: str,
) -> list[dict[str, Any]]:
    """Liest ausschließlich explizit in K* gespeicherte strukturierte Modellinhalte."""
    roh = bestandteil.get("menschliche_eintraege", [])
    if not isinstance(roh, list):
        return []
    ergebnis: list[dict[str, Any]] = []
    for eintrag in roh:
        if not isinstance(eintrag, Mapping) or eintrag.get("modellinhalt_erzeugt") is not True:
            continue
        inhalt = eintrag.get("strukturierter_inhalt")
        if isinstance(inhalt, Mapping) and inhalt.get("strukturtyp") == strukturtyp:
            ergebnis.append(cast(dict[str, Any], _normalisieren(inhalt)))
    return ergebnis


def _experimentelle_faktoren(bestandteil: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Bereitet nur in Schritt 9 ausdrücklich festgelegte experimentelle Faktoren auf."""
    ergebnis: list[dict[str, Any]] = []
    for faktor in _strukturierte_menschliche_inhalte(bestandteil, "experimenteller_faktor"):
        art = str(faktor.get("art", ""))
        auspraegungen = _listenwert(faktor.get("auspraegungen", []))
        if art == "quantitativer_parameter":
            unterer_wert = faktor.get("unterer_wert")
            oberer_wert = faktor.get("oberer_wert")
            einheit = str(faktor.get("einheit", "") or "")
            wertebereich = (
                f"{formatiere_messwert(unterer_wert)} bis "
                f"{formatiere_messwert(oberer_wert)}"
                f"{f' {einheit}' if einheit else ''}"
            )
        else:
            unterer_wert = oberer_wert = None
            einheit = ""
            wertebereich = ", ".join(str(wert) for wert in auspraegungen)
        ergebnis.append(
            {
                **faktor,
                "bezugstyp_anzeige": _anzeigetext(faktor.get("bezugstyp")),
                "art_anzeige": {
                    "quantitativer_parameter": "Quantitativer Parameter",
                    "qualitative_regel": "Qualitative Regel",
                }.get(art, _anzeigetext(art)),
                "unterer_wert": unterer_wert,
                "oberer_wert": oberer_wert,
                "einheit": einheit,
                "auspraegungen": auspraegungen,
                "wertebereich_anzeige": wertebereich,
            }
        )
    return ergebnis


def _bestaetigte_warteschlangen(
    bestandteil: Mapping[str, Any],
    automatisch: Any,
) -> list[dict[str, Any]]:
    """Vereinigt bestätigte K-Inhalte und menschliche Schritt-9-Ergänzungen."""
    kandidaten: list[dict[str, Any]] = []
    for eintrag in _listenwert(automatisch):
        if isinstance(eintrag, Mapping):
            kandidaten.append(cast(dict[str, Any], _normalisieren(eintrag)))
    kandidaten.extend(
        eintrag
        for eintrag in _strukturierte_menschliche_inhalte(bestandteil, "warteschlangenergaenzung")
        if eintrag.get("fachlich_bestaetigt") is True
    )
    ergebnis: list[dict[str, Any]] = []
    bekannte: set[tuple[str, str, str]] = set()
    for eintrag in kandidaten:
        von = str(eintrag.get("vorgaengeraktivitaet", eintrag.get("von_aktivitaet", "")) or "")
        zu = str(eintrag.get("folgeaktivitaet", eintrag.get("zu_aktivitaet", "")) or "")
        bezeichnung = str(eintrag.get("bezeichnung", "") or "")
        schluessel = (von, zu, bezeichnung)
        if not von or not zu or schluessel in bekannte:
            continue
        bekannte.add(schluessel)
        ergebnis.append(
            {
                **eintrag,
                "bezeichnung": bezeichnung or f"Warteschlange {von} → {zu}",
                "vorgaengeraktivitaet": von,
                "folgeaktivitaet": zu,
            }
        )
    return ergebnis


def _datenquellen_aufbereiten(werte: list[Any]) -> list[dict[str, Any]]:
    """Dedupliziert Q-Einträge über ihre stabile Identität und übersetzt bekannte Codes."""
    zusammengefuehrt: dict[tuple[str, ...], dict[str, Any]] = {}
    reihenfolge: list[tuple[str, ...]] = []
    for wert in werte:
        if not isinstance(wert, Mapping):
            continue
        normalisiert = cast(dict[str, Any], _normalisieren(wert))
        identitaet = str(normalisiert.get("datenquellen_id", "") or "")
        schluessel = (
            ("id", identitaet)
            if identitaet
            else (
                "fachlich",
                str(normalisiert.get("bezeichnung", "")),
                str(normalisiert.get("konkretes_quellsystem", "")),
                str(normalisiert.get("quellenart", "")),
            )
        )
        if schluessel not in zusammengefuehrt:
            zusammengefuehrt[schluessel] = {}
            reihenfolge.append(schluessel)
        ziel = zusammengefuehrt[schluessel]
        for name, inhalt in normalisiert.items():
            if inhalt not in (None, "", [], {}) or name not in ziel:
                ziel[name] = inhalt

    ergebnis: list[dict[str, Any]] = []
    for schluessel in reihenfolge:
        quelle = zusammengefuehrt[schluessel]
        konkretes_system = str(quelle.get("konkretes_quellsystem", "") or "")
        ergebnis.append(
            {
                **quelle,
                "quellsystem_anzeige": konkretes_system
                or _anzeigetext(quelle.get("quellsystemtyp")),
                "format_anzeige": _anzeigetext(quelle.get("quellenart")),
                "verwendung": str(quelle.get("fachliche_beschreibung", "") or ""),
            }
        )
    return ergebnis


def _manuelle_ressourcenzuordnungen(
    bestandteil: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Liest ausschließlich bereits in K* dokumentierte menschliche Zuordnungen."""
    roh = bestandteil.get("menschliche_eintraege", [])
    if not isinstance(roh, list):
        return []
    ergebnis: list[dict[str, Any]] = []
    for eintrag in roh:
        if not isinstance(eintrag, Mapping):
            continue
        dokumentation = eintrag.get("fachliche_ergaenzung_oder_begruendung")
        if isinstance(dokumentation, str):
            try:
                dokumentation = json.loads(dokumentation)
            except json.JSONDecodeError:
                continue
        if not isinstance(dokumentation, Mapping):
            continue
        zuordnungen = dokumentation.get("aktivitaet_ressourcen", [])
        if not isinstance(zuordnungen, list):
            continue
        ergebnis.extend(
            cast(dict[str, Any], _normalisieren(zuordnung))
            for zuordnung in zuordnungen
            if isinstance(zuordnung, Mapping)
        )
    return ergebnis


def _ressourcenzuordnungen_fuer_anzeige(wert: Any) -> list[dict[str, Any]]:
    """Verdichtet nur die Reportdarstellung, ohne die A_G-Zuordnung zu verändern."""
    ergebnis: list[dict[str, Any]] = []
    for zuordnung in _listenwert(wert):
        if not isinstance(zuordnung, Mapping):
            continue
        normalisiert = cast(dict[str, Any], _normalisieren(zuordnung))
        ressourcen = _listenwert(zuordnung.get("ressourcen", []))
        normalisiert["ressourcen"] = ressourcen[:REPORT_RESSOURCEN_JE_AKTIVITAET_LIMIT]
        normalisiert["weitere_ressourcen"] = max(
            len(ressourcen) - REPORT_RESSOURCEN_JE_AKTIVITAET_LIMIT,
            0,
        )
        ergebnis.append(normalisiert)
    return ergebnis


def _abschnitt_metadaten(
    k_stern: Mapping[str, Any],
    bestandteil: Mapping[str, Any],
) -> dict[str, Any]:
    """Erzeugt gemeinsame Metadaten jedes fachlichen Reportabschnitts."""
    bestandteil_id = str(bestandteil["bestandteil_id"])
    original = bestandteil.get("urspruenglicher_bestandteil", {})
    if not isinstance(original, Mapping):
        original = {}

    validierungsstatus = bestandteil.get("validierungsstatus")
    ableitungsstatus = original.get("status")

    anpassungen = _fachliche_anpassungen(bestandteil)
    entscheidungen = _fachliche_entscheidungen(k_stern, bestandteil_id)

    return {
        "bestandteil_id": bestandteil_id,
        "bezeichnung": str(bestandteil.get("bezeichnung", bestandteil_id)),
        "validierungsstatus": _normalisieren(validierungsstatus),
        "validierungsstatus_anzeige": _anzeigetext(validierungsstatus),
        "ableitungsstatus": _normalisieren(ableitungsstatus),
        "ableitungsstatus_anzeige": _anzeigetext(ableitungsstatus),
        "verwendete_quellen": _listenwert(original.get("verwendete_quellen")),
        "fachliche_entscheidungen": entscheidungen,
        "fachliche_anpassungen": anpassungen,
        "hat_fachliche_anpassungen": bool(anpassungen),
    }


def _kpi_aufbereiten(wert: Any) -> dict[str, Any]:
    """Bereitet ein A_G-KPI-Ergebnis ohne fachliche Neuinterpretation auf."""
    if not isinstance(wert, Mapping):
        return {"wert": _normalisieren(wert)}

    status = wert.get("status")
    ergebnis = _normalisieren(wert.get("ergebnis"))
    einheit = str(wert.get("einheit", "") or "")

    if ergebnis is None:
        ergebnis_anzeige = _anzeigetext(status)
    else:
        ergebnis_anzeige = formatiere_messwert(ergebnis, einheit)

    return {
        "kpi_id": str(wert.get("kpi_id", "")),
        "bezeichnung": str(wert.get("bezeichnung", "")),
        "status": _normalisieren(status),
        "status_anzeige": _anzeigetext(status),
        "ergebnis": ergebnis,
        "ergebnis_anzeige": ergebnis_anzeige,
        "einheit": einheit,
        "bezugsmenge": _normalisieren(wert.get("bezugsmenge")),
        "formel": _normalisieren(wert.get("formel")),
        "rechenweg": _normalisieren(wert.get("rechenweg")),
        "fehlende_voraussetzungen": _listenwert(wert.get("fehlende_voraussetzungen")),
        "wertebedingungen": _normalisieren(wert.get("wertebedingungen", [])),
        "zugeordnete_operanden": _normalisieren(wert.get("zugeordnete_operanden", [])),
        "zwischensummen": _normalisieren(wert.get("zwischensummen", {})),
        "ausgeschlossene_werte": _normalisieren(wert.get("ausgeschlossene_werte")),
        "quellenreferenzen": _normalisieren(wert.get("quellenreferenzen", [])),
        "definitionsversion": _normalisieren(wert.get("definitionsversion")),
        "behandlungsart": _normalisieren(wert.get("behandlungsart")),
        "behandlungsart_anzeige": _anzeigetext(wert.get("behandlungsart")),
    }


def _aktivitaetsfrequenzen(wert: Any) -> list[dict[str, Any]]:
    """Formt DFG-Start-/Endaktivitäten zu einer layoutfreundlichen Liste."""
    if isinstance(wert, Mapping):
        return [
            {
                "aktivitaet": str(name),
                "haeufigkeit": _normalisieren(haeufigkeit),
            }
            for name, haeufigkeit in wert.items()
        ]

    ergebnis: list[dict[str, Any]] = []
    for eintrag in _listenwert(wert):
        if isinstance(eintrag, list) and len(eintrag) >= 2:
            ergebnis.append(
                {
                    "aktivitaet": str(eintrag[0]),
                    "haeufigkeit": _normalisieren(eintrag[1]),
                }
            )
        else:
            ergebnis.append(
                {
                    "aktivitaet": str(eintrag),
                    "haeufigkeit": None,
                }
            )
    return ergebnis


def _profil_aufbereiten(wert: Any) -> dict[str, Any]:
    """Verdichtet R zu einer für beide Reportlayouts unmittelbar nutzbaren Struktur."""
    if not isinstance(wert, Mapping):
        return {"wert": _normalisieren(wert)}

    gesamt = wert.get("gesamtprofil", {})
    if not isinstance(gesamt, Mapping):
        gesamt = {}

    spaltenprofile = gesamt.get("spaltenprofile", [])
    if not isinstance(spaltenprofile, list):
        spaltenprofile = []

    return {
        "import_id": _normalisieren(wert.get("import_id")),
        "datenquellen_id": _normalisieren(wert.get("datenquellen_id")),
        "datenquelle_bezeichnung": _normalisieren(wert.get("datenquelle_bezeichnung")),
        "originaldateiname": _normalisieren(wert.get("originaldateiname")),
        "tabellenbezeichnung": _normalisieren(wert.get("tabellenbezeichnung")),
        "profil_version": _normalisieren(wert.get("profil_version")),
        "profil_sha256": _normalisieren(wert.get("profil_sha256")),
        "raw_sha256": _normalisieren(wert.get("raw_sha256")),
        "datei_pruefsumme": _normalisieren(wert.get("datei_pruefsumme")),
        "zeilenanzahl": _normalisieren(gesamt.get("zeilen")),
        "spaltenanzahl": _normalisieren(gesamt.get("spalten", len(spaltenprofile))),
        "echte_fehlwerte": _normalisieren(gesamt.get("echte_fehlwerte")),
        "textuelle_platzhalter": _normalisieren(gesamt.get("textuelle_platzhalter")),
        "exakte_duplikate": _normalisieren(gesamt.get("exakte_duplikate")),
        "vollstaendig_leere_spalten": _normalisieren(gesamt.get("vollstaendig_leere_spalten")),
        "spaltenprofile": _normalisieren(spaltenprofile),
    }


def _profile_aufbereiten(
    werte: list[Any], datenquellen: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Ordnet jedes Profil über die gespeicherte Datenquellen-ID fachlich sichtbar zu."""
    quellen_nach_id = {
        str(wert.get("datenquellen_id")): str(wert.get("bezeichnung", ""))
        for wert in datenquellen
        if wert.get("datenquellen_id")
    }
    ergebnis: list[dict[str, Any]] = []
    bekannte: set[tuple[str, str]] = set()
    for index, wert in enumerate(werte, 1):
        profil = _profil_aufbereiten(wert)
        import_id = str(profil.get("import_id", "") or "")
        profil_sha256 = str(profil.get("profil_sha256", "") or "")
        schluessel = (
            import_id or f"legacy-{index}",
            profil_sha256 or str(profil.get("originaldateiname", "") or index),
        )
        if schluessel in bekannte:
            continue
        bekannte.add(schluessel)
        bezeichnung = str(profil.get("datenquelle_bezeichnung", "") or "")
        if not bezeichnung:
            bezeichnung = quellen_nach_id.get(str(profil.get("datenquellen_id", "")), "")
        if not bezeichnung:
            bezeichnung = str(profil.get("originaldateiname", "") or f"Datenprofil {index}")
        profil["anzeigebezeichnung"] = bezeichnung
        ergebnis.append(profil)
    return ergebnis


def _fachlicher_zeitstempel(wert: Any) -> str:
    """Formatiert den Berichtszeitraum kompakt; K* und technische Rohwerte bleiben unverändert."""
    formatiert = formatiere_zeitstempel(wert)
    return formatiert.removesuffix(" +00:00")


def _zeitstatistikzeile(wert: Mapping[str, Any]) -> dict[str, Any]:
    statistik = wert.get("statistik", {})
    if not isinstance(statistik, Mapping):
        statistik = {}
    return {
        "anzahl": statistik.get("anzahl"),
        "mittelwert_sekunden": statistik.get("mittelwert_sekunden"),
        "median_sekunden": statistik.get("median_sekunden"),
    }


def _zeitbezogene_datenauswahl_aufbereiten(
    wert: Mapping[str, Any],
    bestaetigte_warteschlangen: list[dict[str, Any]],
) -> dict[str, Any]:
    """Erzeugt gemeinsame Tabellenzeilen ohne neue zeitbezogene Berechnungen."""
    ergebnis = cast(dict[str, Any], _normalisieren(wert))

    bearbeitungszeiten: list[dict[str, Any]] = []
    bekannte_bearbeitungszeiten: set[tuple[str, str, str]] = set()
    for schluessel in ("bearbeitungszeiten", "ressourcenbezogene_bearbeitungszeiten"):
        for eintrag in _listenwert(wert.get(schluessel)):
            if not isinstance(eintrag, Mapping):
                continue
            aktivitaet = str(eintrag.get("aktivitaet", "") or "")
            ressource = str(eintrag.get("ressource", "") or "")
            statistik = eintrag.get("statistik", eintrag)
            identitaet = (
                aktivitaet,
                ressource,
                json.dumps(_normalisieren(statistik), sort_keys=True),
            )
            if identitaet in bekannte_bearbeitungszeiten:
                continue
            bekannte_bearbeitungszeiten.add(identitaet)
            bearbeitungszeiten.append(
                {
                    "aktivitaet": aktivitaet,
                    "ressource": ressource,
                    **_zeitstatistikzeile({"statistik": statistik}),
                }
            )

    bestaetigte_uebergaenge = {
        (
            str(eintrag.get("vorgaengeraktivitaet", "")),
            str(eintrag.get("folgeaktivitaet", "")),
        )
        for eintrag in bestaetigte_warteschlangen
    }
    potenzielle_wartezeiten: list[dict[str, Any]] = []
    for eintrag in _listenwert(wert.get("potenzielle_wartezeiten")):
        if not isinstance(eintrag, Mapping):
            continue
        von = str(eintrag.get("von_aktivitaet", "") or "")
        zu = str(eintrag.get("zu_aktivitaet", "") or "")
        potenzielle_wartezeiten.append(
            {
                "uebergang": f"{von} → {zu}",
                "von_aktivitaet": von,
                "zu_aktivitaet": zu,
                **_zeitstatistikzeile(eintrag),
                "status": "Bestätigt" if (von, zu) in bestaetigte_uebergaenge else "Hinweis",
            }
        )

    vereinfachte_zeitspannen = [
        {
            "uebergang": (
                f"{eintrag.get('von_aktivitaet', '')} → {eintrag.get('zu_aktivitaet', '')}"
            ),
            "von_aktivitaet": eintrag.get("von_aktivitaet"),
            "zu_aktivitaet": eintrag.get("zu_aktivitaet"),
            **_zeitstatistikzeile(eintrag),
        }
        for eintrag in _listenwert(wert.get("vereinfachte_zeitspannen"))
        if isinstance(eintrag, Mapping)
    ]
    ergebnis.update(
        {
            "bearbeitungszeiten_tabelle": bearbeitungszeiten,
            "potenzielle_wartezeiten_tabelle": potenzielle_wartezeiten,
            "vereinfachte_zeitspannen_tabelle": vereinfachte_zeitspannen,
        }
    )
    return ergebnis


def _lineage_informationen(
    bestandteile: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Hält technische Rückverfolgbarkeit getrennt vom sichtbaren Modellinhalt."""
    ergebnis: list[dict[str, Any]] = []
    for bestandteil_id in bestandteile:
        for information in _informationen(bestandteile[bestandteil_id]):
            ergebnis.append(
                {
                    "bestandteil_id": bestandteil_id,
                    "informations_id": _normalisieren(information.get("informations_id")),
                    "strukturreferenz": _normalisieren(information.get("strukturreferenz")),
                    "herkunftsartefakt": _normalisieren(information.get("herkunftsartefakt")),
                    "herkunftsartefakt_id": _normalisieren(information.get("herkunftsartefakt_id")),
                    "herkunftsartefakt_sha256": _normalisieren(
                        information.get("herkunftsartefakt_sha256")
                    ),
                    "uebernahmeart": _normalisieren(information.get("uebernahmeart")),
                    "uebernahmeart_anzeige": _anzeigetext(information.get("uebernahmeart")),
                }
            )
    return ergebnis


def _vollstaendige_modellbestandteile(
    k_stern: Mapping[str, Any],
    bestandteile: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Bewahrt jeden finalen K*-Bestandteil für formatübergreifende Detailausgaben."""
    ergebnis: list[dict[str, Any]] = []
    for bestandteil in bestandteile.values():
        original = bestandteil.get("urspruenglicher_bestandteil", {})
        if not isinstance(original, Mapping):
            original = {}
        ergebnis.append(
            {
                **_abschnitt_metadaten(k_stern, bestandteil),
                "informationen": _reportwert_begrenzen(_informationen(bestandteil)),
                "menschliche_eintraege": _normalisieren(
                    bestandteil.get("menschliche_eintraege", [])
                ),
            }
        )
    return ergebnis


def build_report_data(
    k_stern: Mapping[str, Any],
    *,
    projektbezeichnung: str | None = None,
    softwareversion: str | None = None,
) -> dict[str, Any]:
    """Projiziert ein bereits validiertes K* auf eine formatneutrale Reportstruktur.

    Die Funktion verändert K* nicht, lädt keine weiteren Artefakte und führt
    keine fachliche Modellbildung oder Validierung durch.
    """
    bestandteile = _bestandteile_nach_id(k_stern)

    problemstellung = bestandteile["problemstellung"]
    zielsetzung = bestandteile["zielsetzung"]
    ist_v3 = "ausgaben" in bestandteile
    ausgaben = bestandteile["ausgaben"] if ist_v3 else bestandteile["ausgaben_und_eingaben"]
    eingaben = bestandteile["eingaben"] if ist_v3 else bestandteile["ausgaben_und_eingaben"]
    ausgaben_eingaben = (
        _kombiniere_bestandteile(ausgaben, eingaben)
        if ist_v3
        else bestandteile["ausgaben_und_eingaben"]
    )
    umfang = (
        _kombiniere_bestandteile(
            bestandteile["modellumfang"],
            bestandteile["modellgrenzen"],
            bestandteile["detaillierungsgrad"],
        )
        if ist_v3
        else bestandteile["modellumfang_grenzen_detaillierungsgrad"]
    )
    entitaeten = bestandteile["entitaeten"]
    aktivitaeten = bestandteile["aktivitaeten"]
    warteschlangen = bestandteile["warteschlangen"]
    ressourcen = bestandteile["ressourcen"]
    annahmen = (
        _kombiniere_bestandteile(bestandteile["annahmen"], bestandteile["vereinfachungen"])
        if ist_v3
        else bestandteile["annahmen_und_vereinfachungen"]
    )
    daten = (
        _kombiniere_bestandteile(bestandteile["datenauswahl"], bestandteile["daten"])
        if ist_v3
        else bestandteile["datenauswahl_und_daten"]
    )
    darstellung = bestandteile["darstellung_der_vorgaenge_des_systems"]

    systemprofil = _info_wert(umfang, "systemprofil", {})
    if not isinstance(systemprofil, Mapping):
        systemprofil = {}

    systemklassifikation = systemprofil.get("systemklassifikation", {})
    if not isinstance(systemklassifikation, Mapping):
        systemklassifikation = {}

    start_und_ende = _info_wert(
        umfang,
        "prozessbelege.start_und_endaktivitaeten",
        _info_wert(
            umfang,
            "discovery_ergebnisse_a_d.dfg.start_und_endaktivitaeten",
            {},
        ),
    )
    if not isinstance(start_und_ende, Mapping):
        start_und_ende = {}

    case_id = _info_wert(entitaeten, "schema.case_id", {})
    if not isinstance(case_id, Mapping):
        case_id = {}

    optionale_artefakte = _info_wert(aktivitaeten, "optionale_artefakte", {})
    if not isinstance(optionale_artefakte, Mapping):
        optionale_artefakte = {}

    systemressourcen = _info_wert(ressourcen, "systemprofil.ressourcen", {})
    if not isinstance(systemressourcen, Mapping):
        systemressourcen = {}

    event_log_ressourcen = _info_wert(ressourcen, "schema.resource", {})
    if not isinstance(event_log_ressourcen, Mapping):
        event_log_ressourcen = {}

    ressourcenanalyse = _info_wert(
        ressourcen,
        "strukturierte_ergebnisse.ressourcen",
        {},
    )
    if not isinstance(ressourcenanalyse, Mapping):
        ressourcenanalyse = {}
    zugeordnete_ressourcen = sorted(
        {
            str(ressource)
            for zuordnung in _listenwert(ressourcenanalyse.get("zuordnungen", []))
            if isinstance(zuordnung, Mapping)
            for ressource in _listenwert(zuordnung.get("ressourcen", []))
            if str(ressource)
        }
    )

    warteschlangenanalyse = _info_wert(
        warteschlangen,
        "strukturierte_ergebnisse.warteschlangen_und_wartezeiten",
        {},
    )
    if not isinstance(warteschlangenanalyse, Mapping):
        warteschlangenanalyse = {}
    wartestellenhinweise = _wartestellenhinweise(warteschlangenanalyse)
    if not wartestellenhinweise:
        wartestellenhinweise = _listenwert(
            _info_wert(
                warteschlangen,
                "start_timestamp_end_timestamp.positive_uebergangsdifferenzen",
                [],
            )
        )

    modellierungsentscheidungen = _info_wert(
        annahmen,
        "discovery_ergebnisse_a_d.modellierungsentscheidungen",
        {},
    )
    if not isinstance(modellierungsentscheidungen, Mapping):
        modellierungsentscheidungen = {}

    schwellwert_auswirkung = _info_wert(
        annahmen,
        "discovery_ergebnisse_a_d.schwellwert_k.auswirkung",
        {},
    )
    if not isinstance(schwellwert_auswirkung, Mapping):
        schwellwert_auswirkung = {}

    etl_abstraktionen = _info_wert(
        annahmen,
        "strukturierte_ergebnisse.vereinfachungen.etl_abstraktionen",
        [],
    )
    if not isinstance(etl_abstraktionen, list):
        etl_abstraktionen = []
    etl_abstraktionen = [
        _normalisieren(wert) for wert in etl_abstraktionen if isinstance(wert, Mapping)
    ]

    datenquellen = _datenquellen_aufbereiten(_info_werte_mit_praefix(daten, "datenquellen["))
    profile = _profile_aufbereiten(_info_werte_mit_praefix(daten, "profile["), datenquellen)

    zwischendatensatz = _info_wert(daten, "schema_und_referenz", {})
    if not isinstance(zwischendatensatz, Mapping):
        zwischendatensatz = {}

    event_log = _info_wert(
        daten,
        "schema_umfang_zeitraum_und_referenz",
        {},
    )
    if not isinstance(event_log, Mapping):
        event_log = {}

    zeitbezogene_datenauswahl = _info_wert(
        daten,
        "strukturierte_ergebnisse.zeitbezogene_datenauswahl",
        {},
    )
    if not isinstance(zeitbezogene_datenauswahl, Mapping):
        zeitbezogene_datenauswahl = {}
    conformance_ausgabe = _info_wert(ausgaben_eingaben, "conformance_checking", {})
    if not isinstance(conformance_ausgabe, Mapping):
        conformance_ausgabe = {}
    performance_ausgabe = _info_wert(
        ausgaben_eingaben,
        "strukturierte_ergebnisse.performance_und_engpassanalyse",
        {},
    )
    if not isinstance(performance_ausgabe, Mapping):
        performance_ausgabe = {}
    automatisch_bestaetigte_warteschlangen = _info_wert(
        warteschlangen,
        "strukturierte_ergebnisse.warteschlangen_und_wartezeiten.bestaetigte_warteschlangen",
        warteschlangenanalyse.get("bestaetigte_warteschlangen", []),
    )
    bestaetigte_warteschlangen = _bestaetigte_warteschlangen(
        warteschlangen, automatisch_bestaetigte_warteschlangen
    )
    zeitbezogene_datenauswahl = _zeitbezogene_datenauswahl_aufbereiten(
        zeitbezogene_datenauswahl,
        bestaetigte_warteschlangen,
    )
    vereinfachte_zeitspannen = _listenwert(
        zeitbezogene_datenauswahl.get("vereinfachte_zeitspannen")
    )
    zeitvereinfachung: dict[str, Any] = {}
    if (
        zeitbezogene_datenauswahl.get("vereinfachte_zeitspannen_bestaetigt")
        or vereinfachte_zeitspannen
    ):
        zeitvereinfachung = {
            "status": "Menschlich bestätigt",
            "entscheidung": zeitbezogene_datenauswahl.get("vereinfachungsentscheidung"),
            "betroffene_uebergaenge": len(vereinfachte_zeitspannen),
            "fachliche_grenze": (
                "Gemeinsame Zeitspanne aus Bearbeitung, Transport, Warten und sonstigen "
                "Zwischenzeiten; keine zusätzliche Bearbeitungs- oder Wartezeit für "
                "denselben Abschnitt."
            ),
        }
    datenaufbereitung = _info_wert(
        daten,
        "strukturierte_ergebnisse.datenaufbereitung",
        {},
    )
    if not isinstance(datenaufbereitung, Mapping):
        datenaufbereitung = {}
    if not wartestellenhinweise:
        # Potenzielle Wartezeiten sind auch dann berichtsfähige Messwerte, wenn sie
        # fachlich noch keine explizit bestätigte Warteschlange in K* begründen.
        wartestellenhinweise = _wartestellenhinweise(zeitbezogene_datenauswahl)

    prozessmodell_referenz = _info_wert(
        darstellung,
        "prozessmodell_referenz",
        {},
    )
    if not isinstance(prozessmodell_referenz, Mapping):
        prozessmodell_referenz = {}

    gesamtvalidierung = k_stern.get("gesamtvalidierung", {})
    if not isinstance(gesamtvalidierung, Mapping):
        gesamtvalidierung = {}

    status = gesamtvalidierung.get("status")
    aktivitaet_ressourcen = _listenwert(
        ressourcenanalyse.get(
            "zuordnungen",
            event_log_ressourcen.get("aktivitaet_ressourcen", []),
        )
    )[:REPORT_LIST_LIMIT]
    manuelle_aktivitaet_ressourcen = _manuelle_ressourcenzuordnungen(ressourcen)
    experimentelle_faktoren = _experimentelle_faktoren(eingaben)
    event_log_anzeige = cast(dict[str, Any], _normalisieren(event_log))
    if event_log.get("zeitraum_von"):
        event_log_anzeige["zeitraum_von_anzeige"] = _fachlicher_zeitstempel(
            event_log.get("zeitraum_von")
        )
    if event_log.get("zeitraum_bis"):
        event_log_anzeige["zeitraum_bis_anzeige"] = _fachlicher_zeitstempel(
            event_log.get("zeitraum_bis")
        )
    fallidentifikation = next(
        (
            str(wert)
            for wert in _listenwert(_info_wert(entitaeten, "systemprofil.objekte_gueter"))
            if str(wert).strip()
        ),
        "",
    )

    return {
        "report_data_version": REPORT_DATA_VERSION,
        "dokument": {
            "titel": "Konzeptionelles Modell",
            "untertitel": "Validiertes konzeptionelles Modell K*",
            "softwareversion": softwareversion,
        },
        "projekt": {
            "projekt_id": _normalisieren(k_stern.get("projekt_id")),
            "bezeichnung": projektbezeichnung,
        },
        "modell": {
            "k_stern_id": _normalisieren(k_stern.get("k_stern_id")),
            "validierungslauf_id": _normalisieren(k_stern.get("validierungslauf_id")),
            "artefaktart": _normalisieren(k_stern.get("artefaktart")),
            "artefaktversion": _normalisieren(k_stern.get("artefaktversion")),
            "erstellt_am": formatiere_zeitstempel(k_stern.get("erstellt_am")),
        },
        "validierung": {
            "status": _normalisieren(status),
            "status_anzeige": _anzeigetext(status),
            "validierungsvermerk": _normalisieren(gesamtvalidierung.get("validierungsvermerk")),
            "menschlich_bestaetigt": bool(gesamtvalidierung.get("menschlich_bestaetigt")),
            "entscheidungen": _normalisieren(k_stern.get("behandlungen_offener_eintraege", [])),
        },
        "problemstellung": {
            **_abschnitt_metadaten(k_stern, problemstellung),
            "text": _info_wert(
                problemstellung,
                "untersuchungsauftrag.problemstellung",
            ),
        },
        "zielsetzung": {
            **_abschnitt_metadaten(k_stern, zielsetzung),
            "untersuchungszwecke": _listenwert(
                _info_wert(
                    zielsetzung,
                    "untersuchungsauftrag.untersuchungszwecke",
                )
            ),
            "individuelles_ziel": _info_wert(
                zielsetzung,
                "untersuchungsauftrag.individuelles_ziel",
            ),
            "logistische_zielgroessen": _code_liste(
                _info_wert(
                    zielsetzung,
                    "untersuchungsauftrag.logistische_zielgroessen",
                )
            ),
            "ausgewaehlte_kpis": _code_liste(
                _info_wert(
                    zielsetzung,
                    "untersuchungsauftrag.ausgewaehlte_kpi_ids",
                )
            ),
        },
        "ausgaben": {
            **_abschnitt_metadaten(k_stern, ausgaben),
            "ausgewaehlte_kpis": _code_liste(
                _info_wert(
                    ausgaben,
                    "untersuchungsauftrag.ausgewaehlte_kpi_ids",
                )
            ),
            "kpi_ergebnisse": [
                _kpi_aufbereiten(wert)
                for wert in _info_werte_mit_praefix(
                    ausgaben,
                    "kpi_ergebnisse[",
                )
            ],
            "conformance_checking": _conformance_aufbereiten(conformance_ausgabe),
            "performance_und_engpassanalyse": _normalisieren(performance_ausgabe),
        },
        "eingaben": {
            **_abschnitt_metadaten(k_stern, eingaben),
            "experimentelle_faktoren": experimentelle_faktoren,
        },
        # Kompatibler Sammelzugriff für bestehende Integrationen; neue Renderer verwenden
        # die fachlich getrennten Abschnitte ``ausgaben`` und ``eingaben``.
        "ausgaben_und_eingaben": {
            **_abschnitt_metadaten(k_stern, ausgaben_eingaben),
            "ausgewaehlte_kpis": _code_liste(
                _info_wert(ausgaben, "untersuchungsauftrag.ausgewaehlte_kpi_ids")
            ),
            "kpi_ergebnisse": [
                _kpi_aufbereiten(wert)
                for wert in _info_werte_mit_praefix(ausgaben, "kpi_ergebnisse[")
            ],
            "conformance_checking": _conformance_aufbereiten(conformance_ausgabe),
            "performance_und_engpassanalyse": _normalisieren(performance_ausgabe),
            "experimentelle_faktoren": experimentelle_faktoren,
        },
        "modellumfang": {
            **_abschnitt_metadaten(k_stern, umfang),
            "systemgrenze": _info_wert(
                umfang,
                "untersuchungsauftrag.systemgrenze",
            ),
            "detaillierungsgrad": _info_wert(
                umfang,
                "untersuchungsauftrag.detaillierungsgrad",
            ),
            "systemtyp": _normalisieren(systemprofil.get("systemtyp")),
            "systemtyp_anzeige": _anzeigetext(systemprofil.get("systemtyp")),
            "systemklassifikation": _normalisieren(systemklassifikation),
            "bereich_aus_systemprofil": _info_wert(
                umfang,
                "systemprofil.bereich",
            ),
            "sichtbare_aktivitaeten": _listenwert(_info_wert(umfang, "sichtbare_aktivitaeten")),
            "startaktivitaeten": _aktivitaetsfrequenzen(
                start_und_ende.get("startaktivitaeten", [])
            ),
            "endaktivitaeten": _aktivitaetsfrequenzen(start_und_ende.get("endaktivitaeten", [])),
        },
        "entitaeten": {
            **_abschnitt_metadaten(k_stern, entitaeten),
            "objekte_gueter": _listenwert(_info_wert(entitaeten, "systemprofil.objekte_gueter")),
            "kanonisches_fallattribut": _normalisieren(case_id.get("kanonisches_attribut")),
            "fallidentifikation": fallidentifikation,
            "fallanzahl": _normalisieren(case_id.get("fallanzahl")),
        },
        "aktivitaeten": {
            **_abschnitt_metadaten(k_stern, aktivitaeten),
            "sichtbare_aktivitaeten": _listenwert(
                _info_wert(aktivitaeten, "sichtbare_aktivitaeten")
            )[:REPORT_LIST_LIMIT],
            "optionale_artefakte": _normalisieren(optionale_artefakte),
        },
        "warteschlangen": {
            **_abschnitt_metadaten(k_stern, warteschlangen),
            "wartezeit_kpis": [
                _kpi_aufbereiten(wert)
                for wert in _info_werte_mit_praefix(
                    warteschlangen,
                    "kpi_ergebnisse.wartezeit[",
                )
            ],
            "wartestellenhinweise": wartestellenhinweise,
            "bestaetigte_warteschlangen": bestaetigte_warteschlangen,
            "berechnungsregel": _normalisieren(warteschlangenanalyse.get("berechnungsregel")),
            "ausgeschlossene_negative_werte": _normalisieren(
                warteschlangenanalyse.get(
                    "anzahl_ueberlappungen",
                    warteschlangenanalyse.get("ausgeschlossene_negative_werte"),
                )
            ),
            "ausgeschlossene_nicht_auswertbare_werte": _normalisieren(
                warteschlangenanalyse.get("ausgeschlossene_nicht_auswertbare_werte")
            ),
        },
        "ressourcen": {
            **_abschnitt_metadaten(k_stern, ressourcen),
            "systemressourcen": _normalisieren(systemressourcen),
            "event_log_ressourcen": _listenwert(
                zugeordnete_ressourcen or event_log_ressourcen.get("eindeutige_werte", [])
            )[:REPORT_LIST_LIMIT],
            "ressourcenattribut": _normalisieren(
                ressourcenanalyse.get("quellspalte") or event_log_ressourcen.get("attribut")
            ),
            "aktivitaet_ressourcen": aktivitaet_ressourcen,
            "aktivitaet_ressourcen_anzeige": _ressourcenzuordnungen_fuer_anzeige(
                aktivitaet_ressourcen
            ),
            "zuordnungsmodus": _normalisieren(ressourcenanalyse.get("modus")),
            "zuordnungsherkunft": _normalisieren(ressourcenanalyse.get("herkunft")),
            "zuordnungsbegruendung": _normalisieren(ressourcenanalyse.get("begruendung")),
            "manuelle_aktivitaet_ressourcen": manuelle_aktivitaet_ressourcen,
            "manuelle_aktivitaet_ressourcen_anzeige": (
                _ressourcenzuordnungen_fuer_anzeige(manuelle_aktivitaet_ressourcen)
            ),
            "fachliche_ressourcenergaenzungen": _strukturierte_menschliche_inhalte(
                ressourcen, "ressourcenergaenzung"
            ),
            "ressourcenbezogene_kpis": [
                _kpi_aufbereiten(wert)
                for wert in _listenwert(
                    _info_wert(
                        ressourcen,
                        "kpi_ergebnisse.ressourcenbezogen",
                        [],
                    )
                )
            ],
        },
        "annahmen": {
            **_abschnitt_metadaten(k_stern, annahmen),
            "modellierungsentscheidungen": _normalisieren(modellierungsentscheidungen),
            "prozessnotation": _info_wert(
                annahmen,
                "prozessnotation",
            ),
            "prozessnotation_anzeige": _anzeigetext(_info_wert(annahmen, "prozessnotation")),
            "schwellwert_auswirkung": _normalisieren(schwellwert_auswirkung),
            "explizite_annahmen": _strukturierte_menschliche_inhalte(annahmen, "annahme"),
        },
        "vereinfachungen": {
            "etl_abstraktionen": etl_abstraktionen,
            "vereinfachte_zeitspannen": _normalisieren(zeitvereinfachung),
            "explizite_vereinfachungen": _strukturierte_menschliche_inhalte(
                annahmen, "vereinfachung"
            ),
        },
        "daten": {
            **_abschnitt_metadaten(k_stern, daten),
            "datenquellen": _normalisieren(datenquellen),
            "profile": profile,
            "zwischendatensatz": _normalisieren(zwischendatensatz),
            "event_log": event_log_anzeige,
            "zeitbezogene_datenauswahl": zeitbezogene_datenauswahl,
            "datenaufbereitung": _normalisieren(datenaufbereitung),
            "fachliche_datenanforderungen": [
                *_strukturierte_menschliche_inhalte(
                    bestandteile["datenauswahl"] if ist_v3 else daten,
                    "datenanforderung",
                ),
                *_strukturierte_menschliche_inhalte(
                    bestandteile["daten"] if ist_v3 else daten,
                    "datenanforderung",
                ),
            ],
        },
        "prozessdarstellung": {
            **_abschnitt_metadaten(k_stern, darstellung),
            "prozessmodell_id": _normalisieren(prozessmodell_referenz.get("prozessmodell_id")),
            "process_mining_analyse_id": _normalisieren(
                prozessmodell_referenz.get("process_mining_analyse_id")
            ),
            "notation": _normalisieren(prozessmodell_referenz.get("notation")),
            "notation_anzeige": _anzeigetext(prozessmodell_referenz.get("notation")),
            "relativer_pfad": _normalisieren(prozessmodell_referenz.get("relativer_pfad")),
        },
        "modellbestandteile": _vollstaendige_modellbestandteile(k_stern, bestandteile),
        "lineage": {
            "k_referenz": _normalisieren(k_stern.get("k_referenz")),
            "o_referenz": _normalisieren(k_stern.get("o_referenz")),
            "eingabefingerabdruck": _normalisieren(k_stern.get("eingabefingerabdruck")),
            "entscheidungsfingerabdruck": _normalisieren(k_stern.get("entscheidungsfingerabdruck")),
            "gesamtpruefsumme": _normalisieren(k_stern.get("gesamtpruefsumme")),
            "informationen": _lineage_informationen(bestandteile),
        },
    }
