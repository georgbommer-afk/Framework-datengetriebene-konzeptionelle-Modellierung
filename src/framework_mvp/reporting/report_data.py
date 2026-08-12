"""Formatneutrale Aufbereitung eines validierten K* für Report- und Excel-Layouts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID


REPORT_DATA_VERSION = 1

ERWARTETE_BESTANDTEIL_IDS = (
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
    "qualitaet_erhoehen": "Qualität erhöhen",
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
    if isinstance(wert, (UUID, datetime, date, Enum)):
        return str(wert.value if isinstance(wert, Enum) else wert)
    if is_dataclass(wert):
        return _normalisieren(asdict(cast(Any, wert)))
    if isinstance(wert, Mapping):
        return {str(name): _normalisieren(inhalt) for name, inhalt in wert.items()}
    if isinstance(wert, (tuple, list, set, frozenset)):
        return [_normalisieren(inhalt) for inhalt in wert]
    return wert


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
    """Indiziert die elf Bestandteile unabhängig von ihrer späteren Darstellung."""
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
            raise ReportDataFehler(
                f"Der Modellbestandteil '{bestandteil_id}' kommt mehrfach vor."
            )
        ergebnis[bestandteil_id] = bestandteil

    erwartet = set(ERWARTETE_BESTANDTEIL_IDS)
    vorhanden = set(ergebnis)
    if vorhanden != erwartet:
        fehlend = sorted(erwartet - vorhanden)
        unerwartet = sorted(vorhanden - erwartet)
        raise ReportDataFehler(
            "Die K*-Struktur passt nicht zur Report-Datenversion. "
            f"Fehlend: {fehlend or 'keine'}; "
            f"unerwartet: {unerwartet or 'keine'}."
        )

    return ergebnis


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
        raise ReportDataFehler(
            f"Die Strukturreferenz '{strukturreferenz}' ist nicht eindeutig."
        )
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
        if isinstance(wert, Mapping)
        and str(wert.get("bestandteil_id", "")) == bestandteil_id
    ]


def _fachliche_anpassungen(
    bestandteil: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Liefert nur echte zusätzliche Modellinhalte aus Schritt 9."""
    roh = bestandteil.get("menschliche_eintraege", [])
    if not isinstance(roh, list):
        return []

    ergebnis: list[dict[str, Any]] = []
    for eintrag in roh:
        if not isinstance(eintrag, Mapping):
            continue
        if eintrag.get("eintragstyp") != "zusaetzliche_anpassung":
            continue
        ergebnis.append(
            {
                "anpassungsnummer": eintrag.get("anpassungsnummer"),
                "fachlicher_inhalt": str(eintrag.get("fachlicher_inhalt", "")),
                "begruendung": str(eintrag.get("begruendung", "")),
                "menschliche_entscheidung": bool(
                    eintrag.get("menschliche_entscheidung")
                ),
            }
        )
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
        ergebnis_anzeige = str(ergebnis)
        if einheit:
            ergebnis_anzeige = f"{ergebnis_anzeige} {einheit}"

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
        "fehlende_voraussetzungen": _listenwert(
            wert.get("fehlende_voraussetzungen")
        ),
        "wertebedingungen": _normalisieren(wert.get("wertebedingungen", [])),
        "zugeordnete_operanden": _normalisieren(
            wert.get("zugeordnete_operanden", [])
        ),
        "zwischensummen": _normalisieren(wert.get("zwischensummen", {})),
        "ausgeschlossene_werte": _normalisieren(
            wert.get("ausgeschlossene_werte")
        ),
        "quellenreferenzen": _normalisieren(
            wert.get("quellenreferenzen", [])
        ),
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
    """Verdichtet R zu einer für Report und Excel unmittelbar nutzbaren Struktur."""
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
        "profil_version": _normalisieren(wert.get("profil_version")),
        "profil_sha256": _normalisieren(wert.get("profil_sha256")),
        "raw_sha256": _normalisieren(wert.get("raw_sha256")),
        "datei_pruefsumme": _normalisieren(wert.get("datei_pruefsumme")),
        "zeilenanzahl": _normalisieren(gesamt.get("zeilen")),
        "spaltenanzahl": _normalisieren(
            gesamt.get("spalten", len(spaltenprofile))
        ),
        "echte_fehlwerte": _normalisieren(gesamt.get("echte_fehlwerte")),
        "textuelle_platzhalter": _normalisieren(
            gesamt.get("textuelle_platzhalter")
        ),
        "exakte_duplikate": _normalisieren(gesamt.get("exakte_duplikate")),
        "vollstaendig_leere_spalten": _normalisieren(
            gesamt.get("vollstaendig_leere_spalten")
        ),
        "spaltenprofile": _normalisieren(spaltenprofile),
    }


def _lineage_informationen(
    bestandteile: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Hält technische Rückverfolgbarkeit getrennt vom sichtbaren Modellinhalt."""
    ergebnis: list[dict[str, Any]] = []
    for bestandteil_id in ERWARTETE_BESTANDTEIL_IDS:
        for information in _informationen(bestandteile[bestandteil_id]):
            ergebnis.append(
                {
                    "bestandteil_id": bestandteil_id,
                    "informations_id": _normalisieren(
                        information.get("informations_id")
                    ),
                    "strukturreferenz": _normalisieren(
                        information.get("strukturreferenz")
                    ),
                    "herkunftsartefakt": _normalisieren(
                        information.get("herkunftsartefakt")
                    ),
                    "herkunftsartefakt_id": _normalisieren(
                        information.get("herkunftsartefakt_id")
                    ),
                    "herkunftsartefakt_sha256": _normalisieren(
                        information.get("herkunftsartefakt_sha256")
                    ),
                    "uebernahmeart": _normalisieren(
                        information.get("uebernahmeart")
                    ),
                }
            )
    return ergebnis


def build_report_data(k_stern: Mapping[str, Any]) -> dict[str, Any]:
    """Projiziert ein bereits validiertes K* auf eine formatneutrale Reportstruktur.

    Die Funktion verändert K* nicht, lädt keine weiteren Artefakte und führt
    keine fachliche Modellbildung oder Validierung durch.
    """
    bestandteile = _bestandteile_nach_id(k_stern)

    problemstellung = bestandteile["problemstellung"]
    zielsetzung = bestandteile["zielsetzung"]
    ausgaben_eingaben = bestandteile["ausgaben_und_eingaben"]
    umfang = bestandteile["modellumfang_grenzen_detaillierungsgrad"]
    entitaeten = bestandteile["entitaeten"]
    aktivitaeten = bestandteile["aktivitaeten"]
    warteschlangen = bestandteile["warteschlangen"]
    ressourcen = bestandteile["ressourcen"]
    annahmen = bestandteile["annahmen_und_vereinfachungen"]
    daten = bestandteile["datenauswahl_und_daten"]
    darstellung = bestandteile["darstellung_der_vorgaenge_des_systems"]

    systemprofil = _info_wert(umfang, "systemprofil", {})
    if not isinstance(systemprofil, Mapping):
        systemprofil = {}

    systemklassifikation = systemprofil.get("systemklassifikation", {})
    if not isinstance(systemklassifikation, Mapping):
        systemklassifikation = {}

    start_und_ende = _info_wert(
        umfang,
        "discovery_ergebnisse_a_d.dfg.start_und_endaktivitaeten",
        {},
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

    datenquellen = _info_werte_mit_praefix(daten, "datenquellen[")
    profile = [
        _profil_aufbereiten(wert)
        for wert in _info_werte_mit_praefix(daten, "profile[")
    ]

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

    return {
        "report_data_version": REPORT_DATA_VERSION,
        "dokument": {
            "titel": "Konzeptionelles Modell",
            "untertitel": "Validiertes konzeptionelles Modell K*",
        },
        "projekt": {
            "projekt_id": _normalisieren(k_stern.get("projekt_id")),
            # K* v1 enthält die Projektbezeichnung nicht. Sie wird hier bewusst
            # nicht live aus dem Projektservice nachgeladen, damit dieselbe
            # K*-Version reproduzierbar dieselben Reportdaten erzeugt.
            "bezeichnung": None,
        },
        "modell": {
            "k_stern_id": _normalisieren(k_stern.get("k_stern_id")),
            "validierungslauf_id": _normalisieren(
                k_stern.get("validierungslauf_id")
            ),
            "artefaktart": _normalisieren(k_stern.get("artefaktart")),
            "artefaktversion": _normalisieren(k_stern.get("artefaktversion")),
            "erstellt_am": _normalisieren(k_stern.get("erstellt_am")),
        },
        "validierung": {
            "status": _normalisieren(status),
            "status_anzeige": _anzeigetext(status),
            "validierungsvermerk": _normalisieren(
                gesamtvalidierung.get("validierungsvermerk")
            ),
            "menschlich_bestaetigt": bool(
                gesamtvalidierung.get("menschlich_bestaetigt")
            ),
            "entscheidungen": _normalisieren(
                k_stern.get("behandlungen_offener_eintraege", [])
            ),
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
        "ausgaben_und_eingaben": {
            **_abschnitt_metadaten(k_stern, ausgaben_eingaben),
            "ausgewaehlte_kpis": _code_liste(
                _info_wert(
                    ausgaben_eingaben,
                    "untersuchungsauftrag.ausgewaehlte_kpi_ids",
                )
            ),
            "kpi_ergebnisse": [
                _kpi_aufbereiten(wert)
                for wert in _info_werte_mit_praefix(
                    ausgaben_eingaben,
                    "kpi_ergebnisse[",
                )
            ],
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
            "sichtbare_aktivitaeten": _listenwert(
                _info_wert(umfang, "sichtbare_aktivitaeten")
            ),
            "startaktivitaeten": _aktivitaetsfrequenzen(
                start_und_ende.get("startaktivitaeten", [])
            ),
            "endaktivitaeten": _aktivitaetsfrequenzen(
                start_und_ende.get("endaktivitaeten", [])
            ),
        },
        "entitaeten": {
            **_abschnitt_metadaten(k_stern, entitaeten),
            "objekte_gueter": _listenwert(
                _info_wert(entitaeten, "systemprofil.objekte_gueter")
            ),
            "kanonisches_fallattribut": _normalisieren(
                case_id.get("kanonisches_attribut")
            ),
            "fallanzahl": _normalisieren(case_id.get("fallanzahl")),
        },
        "aktivitaeten": {
            **_abschnitt_metadaten(k_stern, aktivitaeten),
            "sichtbare_aktivitaeten": _listenwert(
                _info_wert(aktivitaeten, "sichtbare_aktivitaeten")
            ),
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
        },
        "ressourcen": {
            **_abschnitt_metadaten(k_stern, ressourcen),
            "systemressourcen": _normalisieren(systemressourcen),
            "event_log_ressourcen": _normalisieren(
                event_log_ressourcen.get("eindeutige_werte", [])
            ),
            "ressourcenattribut": _normalisieren(
                event_log_ressourcen.get("attribut")
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
            "modellierungsentscheidungen": _normalisieren(
                modellierungsentscheidungen
            ),
            "prozessnotation": _info_wert(
                annahmen,
                "prozessnotation",
            ),
            "prozessnotation_anzeige": _anzeigetext(
                _info_wert(annahmen, "prozessnotation")
            ),
            "schwellwert_auswirkung": _normalisieren(
                schwellwert_auswirkung
            ),
        },
        "daten": {
            **_abschnitt_metadaten(k_stern, daten),
            "datenquellen": _normalisieren(datenquellen),
            "profile": profile,
            "zwischendatensatz": _normalisieren(zwischendatensatz),
            "event_log": _normalisieren(event_log),
        },
        "prozessdarstellung": {
            **_abschnitt_metadaten(k_stern, darstellung),
            "prozessmodell_id": _normalisieren(
                prozessmodell_referenz.get("prozessmodell_id")
            ),
            "process_mining_analyse_id": _normalisieren(
                prozessmodell_referenz.get("process_mining_analyse_id")
            ),
            "notation": _normalisieren(
                prozessmodell_referenz.get("notation")
            ),
            "notation_anzeige": _anzeigetext(
                prozessmodell_referenz.get("notation")
            ),
            "relativer_pfad": _normalisieren(
                prozessmodell_referenz.get("relativer_pfad")
            ),
        },
        "lineage": {
            "k_referenz": _normalisieren(k_stern.get("k_referenz")),
            "o_referenz": _normalisieren(k_stern.get("o_referenz")),
            "eingabefingerabdruck": _normalisieren(
                k_stern.get("eingabefingerabdruck")
            ),
            "entscheidungsfingerabdruck": _normalisieren(
                k_stern.get("entscheidungsfingerabdruck")
            ),
            "gesamtpruefsumme": _normalisieren(
                k_stern.get("gesamtpruefsumme")
            ),
            "informationen": _lineage_informationen(bestandteile),
        },
    }