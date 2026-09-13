"""Theoriegestützte strukturierte Ergänzungen für offene Inhalte in Schritt 9."""

import copy
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import ModellbestandteilId

BEZUGSTYPEN = ("gesamtsystem", "entitaet", "aktivitaet", "warteschlange", "ressource")
KOMPONENTEN_BEZUGSTYPEN = ("entitaet", "aktivitaet", "warteschlange", "ressource")
FAKTORARTEN = ("quantitativer_parameter", "qualitative_regel")
DETAILBEHANDLUNGEN = ("beruecksichtigen", "bewusst_ausschliessen")
DATENZUSTAENDE = ("vorhanden", "angenähert_oder_geschätzt", "nicht_vorhanden")
DARSTELLUNGSFORMEN = (
    "prozessflussdiagramm",
    "ablaufdiagramm",
    "aktivitaetszyklusdiagramm",
)

_ERLAUBTE_FELDER = {
    "experimenteller_faktor": {
        "strukturtyp",
        "bezugstyp",
        "konkreter_bezug",
        "bezeichnung",
        "art",
        "unterer_wert",
        "oberer_wert",
        "einheit",
        "auspraegungen",
    },
    "ressourcenergaenzung": {
        "strukturtyp",
        "ressource",
        "rolle",
        "verfuegbare_anzahl",
        "kapazitaet",
        "schichtstart",
        "schichtende",
        "pausenzeiten",
    },
    "warteschlangenergaenzung": {
        "strukturtyp",
        "vorgaengeraktivitaet",
        "folgeaktivitaet",
        "fachlich_bestaetigt",
        "kapazitaet",
        "regel",
        "potenzieller_wartestellenhinweis",
    },
    "detaillierungsentscheidung": {
        "strukturtyp",
        "bezugstyp",
        "konkreter_bezug",
        "detailmerkmal",
        "behandlung",
    },
    "modellumfang_und_grenze": {
        "strukturtyp",
        "beschreibung",
        "einbezogen",
        "ausgeschlossen",
    },
    "entitaetsergaenzung": {
        "strukturtyp",
        "entitaetstyp",
        "objektbezug",
        "bezeichnung",
        "granularitaet",
    },
    "aktivitaetsergaenzung": {
        "strukturtyp",
        "vorhandene_aktivitaet",
        "fachliche_bezeichnung",
        "objektbezug",
        "granularitaet",
        "variantenbezug",
    },
    "problemstellung": {"strukturtyp", "beschreibung"},
    "zielsetzung": {"strukturtyp", "modellierungszweck", "angestrebter_zustand"},
    "modellausgabe": {"strukturtyp", "gewuenschte_ausgabe"},
    "annahme": {"strukturtyp", "annahme", "hintergrund"},
    "vereinfachung": {
        "strukturtyp",
        "bezugstyp",
        "konkreter_bezug",
        "beschreibung",
        "begruendung",
    },
    "datenanforderung": {
        "strukturtyp",
        "beschreibung",
        "zustand",
        "quelle",
        "naeherung",
    },
    "systemdarstellung": {"strukturtyp", "darstellungsform"},
    "fachliche_ergaenzung": {"strukturtyp", "fachliche_ergaenzung"},
}


@dataclass(frozen=True, slots=True)
class Modellbezugsoptionen:
    """Fachlich sichtbare, bereits in K belegte Modellelemente."""

    entitaeten: tuple[str, ...]
    aktivitaeten: tuple[str, ...]
    warteschlangen: tuple[str, ...]
    ressourcen: tuple[str, ...]

    def fuer(self, bezugstyp: str) -> tuple[str, ...]:
        return {
            "entitaet": self.entitaeten,
            "aktivitaet": self.aktivitaeten,
            "warteschlange": self.warteschlangen,
            "ressource": self.ressourcen,
        }.get(bezugstyp, ())


def _bestandteil(k: Mapping[str, Any], bestandteil_id: ModellbestandteilId) -> Mapping[str, Any]:
    return next(
        (
            wert
            for wert in k.get("modellbestandteile", [])
            if isinstance(wert, Mapping) and wert.get("bestandteil_id") == bestandteil_id.value
        ),
        {},
    )


def _informationen(
    k: Mapping[str, Any], bestandteil_id: ModellbestandteilId
) -> list[Mapping[str, Any]]:
    bestandteil = _bestandteil(k, bestandteil_id)
    roh = bestandteil.get("informationen", [])
    return [wert for wert in roh if isinstance(wert, Mapping)] if isinstance(roh, list) else []


def _texte(wert: Any, schluessel: frozenset[str]) -> list[str]:
    ergebnis: list[str] = []
    if isinstance(wert, Mapping):
        for name, inhalt in wert.items():
            if name in schluessel:
                if isinstance(inhalt, str) and inhalt.strip():
                    ergebnis.append(inhalt.strip())
                elif isinstance(inhalt, (list, tuple)):
                    ergebnis.extend(
                        str(eintrag).strip()
                        for eintrag in inhalt
                        if isinstance(eintrag, (str, int, float)) and str(eintrag).strip()
                    )
            ergebnis.extend(_texte(inhalt, schluessel))
    elif isinstance(wert, (list, tuple)):
        for eintrag in wert:
            ergebnis.extend(_texte(eintrag, schluessel))
    return ergebnis


def _direkte_texte(informationen: list[Mapping[str, Any]], referenzteil: str) -> list[str]:
    ergebnis: list[str] = []
    for information in informationen:
        if referenzteil not in str(information.get("strukturreferenz", "")):
            continue
        wert = information.get("wert")
        if isinstance(wert, str) and wert.strip():
            ergebnis.append(wert.strip())
        elif isinstance(wert, (list, tuple)):
            ergebnis.extend(
                str(eintrag).strip()
                for eintrag in wert
                if isinstance(eintrag, (str, int, float)) and str(eintrag).strip()
            )
    return ergebnis


def _alle_skalartexte(wert: Any) -> list[str]:
    if isinstance(wert, str) and wert.strip():
        return [wert.strip()]
    if isinstance(wert, Mapping):
        return [text for inhalt in wert.values() for text in _alle_skalartexte(inhalt)]
    if isinstance(wert, (list, tuple)):
        return [text for eintrag in wert for text in _alle_skalartexte(eintrag)]
    return []


def _eindeutig(werte: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(wert for wert in werte if wert))


def wartestellenhinweise(k: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Liest potenzielle Wartehinweise aus K, ohne sie als Warteschlangen zu bestätigen."""
    ergebnis: list[dict[str, Any]] = []

    def besuchen(wert: Any, *, in_potenzialliste: bool = False) -> None:
        if isinstance(wert, Mapping):
            von = wert.get("von_aktivitaet")
            zu = wert.get("zu_aktivitaet")
            if in_potenzialliste and isinstance(von, str) and isinstance(zu, str):
                ergebnis.append(copy.deepcopy(dict(wert)))
            for name, inhalt in wert.items():
                besuchen(inhalt, in_potenzialliste=name == "potenzielle_wartezeiten")
        elif isinstance(wert, (list, tuple)):
            for eintrag in wert:
                besuchen(eintrag, in_potenzialliste=in_potenzialliste)

    for bestandteil in k.get("modellbestandteile", []):
        if isinstance(bestandteil, Mapping):
            besuchen(bestandteil.get("informationen", []))
    return tuple(ergebnis)


def modellbezugsoptionen(k: Mapping[str, Any]) -> Modellbezugsoptionen:
    """Ermittelt ausschließlich in K vorhandene fachliche Auswahlwerte."""
    aktivitaetsinfos = _informationen(k, ModellbestandteilId.AKTIVITAETEN)
    aktivitaeten = _direkte_texte(aktivitaetsinfos, "sichtbare_aktivitaeten")
    aktivitaeten += _texte(
        [wert.get("wert") for wert in aktivitaetsinfos],
        frozenset({"aktivitaet", "von_aktivitaet", "zu_aktivitaet"}),
    )

    ressourceninfos = _informationen(k, ModellbestandteilId.RESSOURCEN)
    ressourcen = _texte(
        [wert.get("wert") for wert in ressourceninfos],
        frozenset({"ressource", "ressourcen", "instanz_id", "bezeichnung"}),
    )
    ressourcen += _direkte_texte(ressourceninfos, "systemprofil.ressourcen")
    ressourcen += [
        text
        for information in ressourceninfos
        if "systemprofil.ressourcen" in str(information.get("strukturreferenz", ""))
        for text in _alle_skalartexte(information.get("wert"))
    ]

    entitaetsinfos = _informationen(k, ModellbestandteilId.ENTITAETEN)
    entitaeten = _texte(
        [wert.get("wert") for wert in entitaetsinfos],
        frozenset({"entitaetstyp", "bezeichnung"}),
    )
    entitaeten += _direkte_texte(entitaetsinfos, "objekte_gueter")
    entitaeten += [
        text
        for information in entitaetsinfos
        if "objekte_gueter" in str(information.get("strukturreferenz", ""))
        for text in _alle_skalartexte(information.get("wert"))
    ]

    warteschlangeninfos = _informationen(k, ModellbestandteilId.WARTESCHLANGEN)
    warteschlangen = _texte(
        [wert.get("wert") for wert in warteschlangeninfos], frozenset({"bezeichnung"})
    )
    bestaetigte_uebergaenge = _texte(
        [wert.get("wert") for wert in warteschlangeninfos],
        frozenset({"von_aktivitaet", "zu_aktivitaet"}),
    )
    aktivitaeten.extend(bestaetigte_uebergaenge)
    for wert in wartestellenhinweise(k):
        von, zu = str(wert.get("von_aktivitaet", "")), str(wert.get("zu_aktivitaet", ""))
        if von and zu:
            warteschlangen.append(f"Wartestelle {von} → {zu}")
            aktivitaeten.extend((von, zu))

    return Modellbezugsoptionen(
        _eindeutig(entitaeten),
        _eindeutig(aktivitaeten),
        _eindeutig(warteschlangen),
        _eindeutig(ressourcen),
    )


def _text(inhalt: Mapping[str, Any], name: str, *, pflicht: bool = True) -> str:
    wert = inhalt.get(name, "")
    if not isinstance(wert, str):
        raise Domaenenfehler(f"'{name}' muss Text sein.")
    wert = wert.strip()
    if pflicht and not wert:
        raise Domaenenfehler(f"'{name}' darf nicht leer sein.")
    return wert


def _textliste(inhalt: Mapping[str, Any], name: str, *, minimum: int = 0) -> list[str]:
    wert = inhalt.get(name, [])
    if not isinstance(wert, list):
        raise Domaenenfehler(f"'{name}' muss eine Liste sein.")
    liste = [eintrag.strip() for eintrag in wert if isinstance(eintrag, str) and eintrag.strip()]
    if len(liste) != len(wert) or len(set(liste)) != len(liste) or len(liste) < minimum:
        raise Domaenenfehler(f"'{name}' enthält zu wenige, leere oder doppelte Ausprägungen.")
    return liste


def _zahl(inhalt: Mapping[str, Any], name: str) -> float:
    wert = inhalt.get(name)
    if isinstance(wert, bool) or not isinstance(wert, (int, float)) or not math.isfinite(wert):
        raise Domaenenfehler(f"'{name}' muss eine endliche Zahl sein.")
    return float(wert)


def _bezug_pruefen(
    inhalt: Mapping[str, Any], optionen: Modellbezugsoptionen, *, gesamtsystem: bool
) -> None:
    erlaubte = BEZUGSTYPEN if gesamtsystem else KOMPONENTEN_BEZUGSTYPEN
    bezugstyp = _text(inhalt, "bezugstyp")
    if bezugstyp not in erlaubte:
        raise Domaenenfehler("Der Bezugstyp ist für diese Ergänzung nicht zulässig.")
    konkreter_bezug = _text(inhalt, "konkreter_bezug", pflicht=bezugstyp != "gesamtsystem")
    if bezugstyp != "gesamtsystem" and konkreter_bezug not in optionen.fuer(bezugstyp):
        raise Domaenenfehler("Der konkrete Bezug ist nicht als Modellelement in K vorhanden.")


def _mindestens_ein_text(inhalt: Mapping[str, Any], namen: tuple[str, ...]) -> None:
    if not any(_text(inhalt, name, pflicht=False) for name in namen):
        raise Domaenenfehler("Mindestens eine fachliche Ergänzung muss angegeben werden.")


def validiere_strukturierten_inhalt(
    bestandteil_id: ModellbestandteilId,
    inhalt: Mapping[str, Any],
    k: Mapping[str, Any],
) -> dict[str, Any]:
    """Validiert einen strukturierten O-Zusatz und seine Referenzen gegen K."""
    if not isinstance(inhalt, Mapping) or not inhalt:
        raise Domaenenfehler("Die fachliche Ergänzung muss strukturiert vorliegen.")
    strukturtyp = _text(inhalt, "strukturtyp")
    unerwartet = set(inhalt) - _ERLAUBTE_FELDER.get(strukturtyp, set())
    if strukturtyp not in _ERLAUBTE_FELDER or unerwartet:
        raise Domaenenfehler(
            "Die strukturierte Ergänzung enthält einen unbekannten Typ oder fachfremde Felder."
        )
    optionen = modellbezugsoptionen(k)

    if bestandteil_id is ModellbestandteilId.EINGABEN:
        if strukturtyp != "experimenteller_faktor":
            raise Domaenenfehler("Eingaben müssen als experimenteller Faktor erfasst werden.")
        _bezug_pruefen(inhalt, optionen, gesamtsystem=True)
        _text(inhalt, "bezeichnung")
        art = _text(inhalt, "art")
        if art not in FAKTORARTEN:
            raise Domaenenfehler("Die Faktorart ist ungültig.")
        if art == "quantitativer_parameter":
            if "auspraegungen" in inhalt:
                raise Domaenenfehler("Ein quantitativer Faktor darf keine Ausprägungsliste haben.")
            unterer_wert, oberer_wert = _zahl(inhalt, "unterer_wert"), _zahl(inhalt, "oberer_wert")
            if unterer_wert > oberer_wert:
                raise Domaenenfehler("Der untere Faktorwert darf nicht über dem oberen liegen.")
            _text(inhalt, "einheit")
        else:
            if {"unterer_wert", "oberer_wert", "einheit"} & set(inhalt):
                raise Domaenenfehler("Eine qualitative Regel darf keinen Zahlenbereich haben.")
            _textliste(inhalt, "auspraegungen", minimum=2)
    elif bestandteil_id is ModellbestandteilId.RESSOURCEN:
        if strukturtyp != "ressourcenergaenzung":
            raise Domaenenfehler("Ressourcen benötigen eine Ressourcenergänzung.")
        ressource = _text(inhalt, "ressource")
        if ressource not in optionen.ressourcen:
            raise Domaenenfehler("Die Ressource ist nicht in K vorhanden.")
        textfelder = ("rolle", "kapazitaet", "schichtstart", "schichtende", "pausenzeiten")
        for name in textfelder:
            _text(inhalt, name, pflicht=False)
        anzahl = inhalt.get("verfuegbare_anzahl")
        if anzahl not in (None, "") and (
            isinstance(anzahl, bool) or not isinstance(anzahl, int) or anzahl < 0
        ):
            raise Domaenenfehler("Die verfügbare Anzahl muss eine nichtnegative Ganzzahl sein.")
        if anzahl in (None, "") and not any(
            _text(inhalt, name, pflicht=False) for name in textfelder
        ):
            raise Domaenenfehler("Mindestens eine Ressourceninformation muss ergänzt werden.")
    elif bestandteil_id is ModellbestandteilId.WARTESCHLANGEN:
        if strukturtyp != "warteschlangenergaenzung":
            raise Domaenenfehler("Warteschlangen benötigen eine Warteschlangenergänzung.")
        von, zu = _text(inhalt, "vorgaengeraktivitaet"), _text(inhalt, "folgeaktivitaet")
        if von not in optionen.aktivitaeten or zu not in optionen.aktivitaeten or von == zu:
            raise Domaenenfehler("Die Warteschlange muss zwei vorhandene Aktivitäten verbinden.")
        if inhalt.get("fachlich_bestaetigt") is not True:
            raise Domaenenfehler("Eine potenzielle Wartestelle muss fachlich bestätigt werden.")
        _text(inhalt, "kapazitaet", pflicht=False)
        _text(inhalt, "regel", pflicht=False)
        hinweise = inhalt.get("potenzieller_wartestellenhinweis", [])
        if not isinstance(hinweise, list) or hinweise != list(wartestellenhinweise(k)):
            raise Domaenenfehler(
                "Der potenzielle Wartestellenhinweis muss unverändert aus K übernommen werden."
            )
    elif bestandteil_id is ModellbestandteilId.DETAILLIERUNGSGRAD:
        if strukturtyp != "detaillierungsentscheidung":
            raise Domaenenfehler("Der Detaillierungsgrad benötigt eine Detailentscheidung.")
        _bezug_pruefen(inhalt, optionen, gesamtsystem=False)
        _text(inhalt, "detailmerkmal")
        if _text(inhalt, "behandlung") not in DETAILBEHANDLUNGEN:
            raise Domaenenfehler("Die Behandlung des Detailmerkmals ist ungültig.")
    elif bestandteil_id in {ModellbestandteilId.MODELLUMFANG, ModellbestandteilId.MODELLGRENZEN}:
        if strukturtyp != "modellumfang_und_grenze":
            raise Domaenenfehler("Modellumfang und -grenzen benötigen eine Systembeschreibung.")
        _text(inhalt, "beschreibung")
        _textliste(inhalt, "einbezogen")
        _textliste(inhalt, "ausgeschlossen")
    elif bestandteil_id is ModellbestandteilId.ENTITAETEN:
        if strukturtyp != "entitaetsergaenzung":
            raise Domaenenfehler("Entitäten benötigen eine Entitätsergänzung.")
        _mindestens_ein_text(
            inhalt, ("entitaetstyp", "objektbezug", "bezeichnung", "granularitaet")
        )
    elif bestandteil_id is ModellbestandteilId.AKTIVITAETEN:
        if strukturtyp != "aktivitaetsergaenzung":
            raise Domaenenfehler("Aktivitäten benötigen eine Aktivitätsergänzung.")
        vorhandene = _text(inhalt, "vorhandene_aktivitaet", pflicht=False)
        if vorhandene and vorhandene not in optionen.aktivitaeten:
            raise Domaenenfehler("Die ausgewählte Aktivität ist nicht in K vorhanden.")
        _mindestens_ein_text(
            inhalt, ("fachliche_bezeichnung", "objektbezug", "granularitaet", "variantenbezug")
        )
    elif bestandteil_id is ModellbestandteilId.PROBLEMSTELLUNG:
        if strukturtyp != "problemstellung":
            raise Domaenenfehler("Die Problemstellung benötigt eine fachliche Beschreibung.")
        _text(inhalt, "beschreibung")
    elif bestandteil_id is ModellbestandteilId.ZIELSETZUNG:
        if strukturtyp != "zielsetzung":
            raise Domaenenfehler("Die Zielsetzung benötigt eine strukturierte Ergänzung.")
        _mindestens_ein_text(inhalt, ("modellierungszweck", "angestrebter_zustand"))
    elif bestandteil_id is ModellbestandteilId.AUSGABEN:
        if strukturtyp != "modellausgabe":
            raise Domaenenfehler("Ausgaben benötigen eine gewünschte Modellausgabe.")
        _text(inhalt, "gewuenschte_ausgabe")
    elif bestandteil_id is ModellbestandteilId.ANNAHMEN:
        if strukturtyp != "annahme":
            raise Domaenenfehler("Annahmen benötigen eine explizite Annahme.")
        _text(inhalt, "annahme")
        _text(inhalt, "hintergrund", pflicht=False)
    elif bestandteil_id is ModellbestandteilId.VEREINFACHUNGEN:
        if strukturtyp != "vereinfachung":
            raise Domaenenfehler("Vereinfachungen benötigen eine bewusste Reduktion.")
        _bezug_pruefen(inhalt, optionen, gesamtsystem=True)
        _text(inhalt, "beschreibung")
        _text(inhalt, "begruendung")
    elif bestandteil_id in {ModellbestandteilId.DATENAUSWAHL, ModellbestandteilId.DATEN}:
        if strukturtyp != "datenanforderung":
            raise Domaenenfehler("Daten benötigen eine strukturierte Datenanforderung.")
        _text(inhalt, "beschreibung")
        if _text(inhalt, "zustand") not in DATENZUSTAENDE:
            raise Domaenenfehler("Der fachliche Datenzustand ist ungültig.")
        _text(inhalt, "quelle", pflicht=False)
        _text(inhalt, "naeherung", pflicht=False)
    elif bestandteil_id is ModellbestandteilId.DARSTELLUNG_DER_VORGAENGE:
        if strukturtyp != "systemdarstellung":
            raise Domaenenfehler("Die Systemdarstellung benötigt eine Darstellungsform.")
        if _text(inhalt, "darstellungsform") not in DARSTELLUNGSFORMEN:
            raise Domaenenfehler(
                "Die Darstellungsform ist nicht in der fachlichen Referenz enthalten."
            )
    else:
        if strukturtyp != "fachliche_ergaenzung":
            raise Domaenenfehler(
                "Für diesen offenen Aspekt ist nur die begrenzte Ergänzung erlaubt."
            )
        _text(inhalt, "fachliche_ergaenzung")
    return copy.deepcopy(dict(inhalt))
