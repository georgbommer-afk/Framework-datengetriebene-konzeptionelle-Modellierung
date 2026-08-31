"""Versionierte, strikt gültige JSON-Serialisierung technischer Datenprofile."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any
from uuid import UUID

from framework_mvp.domain.models import (
    Datenprofil,
    Indikatorbedingung,
    Indikatoroperator,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.persistence.sqlite_importvorgang_repository import (
    serialisiere_importparameter,
)

PROFIL_VERSION = 3
UNTERSTUETZTE_PROFIL_VERSIONEN = {1, 2, PROFIL_VERSION}

STATISTISCHE_REGELN = (
    "Echte Fehlwerte folgen der Pandas-Semantik.",
    "Textuelle Platzhalter werden nach strip exakt und ohne Beachtung der Schreibweise erkannt.",
    "Numerische Kennzahlen verwenden ausschließlich endliche Werte und Gleichung 3.10.",
    "Potenzielle Ausreißer liegen außerhalb der 1,5-IQR-Grenzen.",
    "Indikatorhäufigkeiten verwenden nur reguläre, typgerecht auswertbare Beobachtungen.",
)


@dataclass(frozen=True, slots=True)
class ProfilArtefakt:
    """Validierter Inhalt eines gespeicherten Profil-JSONs."""

    profil_version: int
    import_id: UUID
    datei_pruefsumme: str
    importparameter: dict[str, Any]
    tabellenbezeichnung: str
    erstellt_am: datetime
    gesamtprofil: dict[str, Any]
    statistische_regeln: tuple[str, ...]
    warnungen: tuple[str, ...]
    indikatorbedingungen: tuple[Indikatorbedingung, ...] = ()


def _json_wert(wert: Any) -> Any:
    if isinstance(wert, float) and not isfinite(wert):
        return None
    if isinstance(wert, datetime):
        return wert.isoformat()
    if isinstance(wert, UUID):
        return str(wert)
    if isinstance(wert, Enum):
        return wert.value
    if isinstance(wert, dict):
        return {str(name): _json_wert(inhalt) for name, inhalt in wert.items()}
    if isinstance(wert, (list, tuple)):
        return [_json_wert(inhalt) for inhalt in wert]
    return wert


def _fachliches_gesamtprofil(profil: Datenprofil) -> dict[str, Any]:
    """Projiziert das persistierte R auf Tabellen 3.7 bis 3.10."""
    roh = _json_wert(asdict(profil))
    spaltenprofile = []
    numerische_felder = (
        "gueltige_werte",
        "minimum",
        "maximum",
        "mittelwert",
        "median",
        "q1",
        "q3",
        "interquartilsabstand",
        "untere_ausreissergrenze",
        "obere_ausreissergrenze",
        "potenzielle_ausreisser",
    )
    for spalte in roh["spaltenprofile"]:
        eintrag = {
            "spaltenname": spalte["spaltenname"],
            "originaldatentyp": spalte["originaldatentyp"],
            "technischer_datentyp": spalte["technischer_datentyp"],
            "profiltyp": spalte["profiltyp"],
            "fehlwerte": spalte["fehlwerte"],
            "indikatorauswertungen": spalte["indikatorauswertungen"],
        }
        numerisch = spalte.get("numerisch")
        if numerisch is not None:
            eintrag["numerisch"] = {name: numerisch[name] for name in numerische_felder}
        kategorial = spalte.get("kategorial")
        if kategorial is not None:
            eintrag["kategorial"] = {
                "eindeutige_auspraegungen": kategorial["eindeutige_auspraegungen"],
                "haeufigster_wert": kategorial["haeufigster_wert"],
            }
        spaltenprofile.append(eintrag)
    return {
        "zeilen": roh["zeilen"],
        "spalten": roh["spalten"],
        "exakte_duplikate": roh["exakte_duplikate"],
        "vollstaendig_leere_spalten": roh["vollstaendig_leere_spalten"],
        "echte_fehlwerte": roh["echte_fehlwerte"],
        "textuelle_platzhalter": roh["textuelle_platzhalter"],
        "spaltenprofile": spaltenprofile,
        "bestaetigte_zusaetzliche_platzhalter": roh["bestaetigte_zusaetzliche_platzhalter"],
    }


def erstelle_profil_json(
    *,
    import_id: UUID,
    datei_pruefsumme: str,
    importparameter: Any,
    tabellenbezeichnung: str,
    erstellt_am: datetime,
    profil: Datenprofil,
    warnungen: tuple[str, ...],
) -> bytes:
    """Serialisiert ein vollständiges Profil reproduzierbar als UTF-8-JSON."""
    struktur = {
        "profil_version": PROFIL_VERSION,
        "import_id": str(import_id),
        "datei_pruefsumme": datei_pruefsumme,
        "importparameter": serialisiere_importparameter(importparameter),
        "tabellenbezeichnung": tabellenbezeichnung,
        "erstellt_am": erstellt_am.isoformat(),
        "gesamtprofil": _fachliches_gesamtprofil(profil),
        "statistische_regeln": list(STATISTISCHE_REGELN),
        "warnungen": list(warnungen),
    }
    return json.dumps(
        struktur,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")


def _migriere_gesamtprofil(gesamtprofil: dict[str, Any]) -> dict[str, Any]:
    """Ergänzt fachliche Profilfelder beim kontrollierten Laden von Version 1."""
    gesamtprofil.setdefault("bestaetigte_zusaetzliche_platzhalter", [])
    for spalte in gesamtprofil.get("spaltenprofile", []):
        if not isinstance(spalte, dict):
            continue
        spalte.setdefault("indikatorauswertungen", [])
        original = str(spalte.get("originaldatentyp", "")).lower()
        profiltyp = spalte.get("profiltyp")
        if "bool" in original:
            fachtyp = "Boolean"
        elif profiltyp == "zeitbezogen":
            fachtyp = "Datum und Uhrzeit"
        elif profiltyp == "numerisch":
            fachtyp = "Ganzzahl" if "int" in original else "Fließkommazahl"
        else:
            fachtyp = "Text"
        spalte.setdefault("technischer_datentyp", fachtyp)
        numerisch = spalte.get("numerisch")
        if isinstance(numerisch, dict):
            numerisch.pop("standardabweichung", None)
        kategorial = spalte.get("kategorial")
        if isinstance(kategorial, dict):
            haeufigkeiten = kategorial.get("haeufigste_werte", [])
            modus = (
                haeufigkeiten[0].get("bezeichnung")
                if haeufigkeiten and isinstance(haeufigkeiten[0], dict)
                else None
            )
            kategorial.setdefault("haeufigster_wert", modus)
            spalte["kategorial"] = {
                "eindeutige_auspraegungen": kategorial.get("eindeutige_auspraegungen", 0),
                "haeufigster_wert": kategorial.get("haeufigster_wert"),
            }
        spalte.pop("zeitbezogen", None)
        spalte.pop("eindeutige_werte", None)
        if isinstance(numerisch, dict):
            erlaubte_numerische_felder = {
                "gueltige_werte",
                "minimum",
                "maximum",
                "mittelwert",
                "median",
                "q1",
                "q3",
                "interquartilsabstand",
                "untere_ausreissergrenze",
                "obere_ausreissergrenze",
                "potenzielle_ausreisser",
            }
            spalte["numerisch"] = {
                name: wert for name, wert in numerisch.items() if name in erlaubte_numerische_felder
            }
    for name in (
        "speicherbedarf_bytes",
        "numerische_spalten",
        "kategoriale_spalten",
        "zeitbezogene_spalten",
        "sonstige_spalten",
    ):
        gesamtprofil.pop(name, None)
    return gesamtprofil


def _indikatorbedingungen_laden(
    gesamtprofil: dict[str, Any],
) -> tuple[Indikatorbedingung, ...]:
    bedingungen: list[Indikatorbedingung] = []
    for spalte in gesamtprofil.get("spaltenprofile", []):
        if not isinstance(spalte, dict):
            raise ValueError
        for auswertung in spalte.get("indikatorauswertungen", []):
            if not isinstance(auswertung, dict):
                raise ValueError
            spaltenname = str(auswertung["spaltenname"])
            if spaltenname != str(spalte.get("spaltenname", "")):
                raise ValueError
            absolute_haeufigkeit = int(auswertung["absolute_haeufigkeit"])
            auswertbare_beobachtungen = int(auswertung["auswertbare_beobachtungen"])
            if (
                absolute_haeufigkeit < 0
                or auswertbare_beobachtungen < 0
                or absolute_haeufigkeit > auswertbare_beobachtungen
            ):
                raise ValueError
            bedingungen.append(
                Indikatorbedingung(
                    spaltenname=spaltenname,
                    operator=Indikatoroperator(str(auswertung["operator"])),
                    vergleichswert=str(auswertung["vergleichswert"]),
                )
            )
    return tuple(bedingungen)


def lade_profil_json(pfad: Path) -> ProfilArtefakt:
    """Lädt und validiert ein unterstütztes Profil-JSON."""
    try:
        struktur = json.loads(pfad.read_text(encoding="utf-8"))
        version = int(struktur["profil_version"])
        if version not in UNTERSTUETZTE_PROFIL_VERSIONEN:
            raise Importintegritaetsfehler(
                f"Die Profilversion {version} wird nicht unterstützt; "
                f"erwartet wird {PROFIL_VERSION}."
            )
        gesamtprofil = struktur["gesamtprofil"]
        if not isinstance(gesamtprofil, dict) or "spaltenprofile" not in gesamtprofil:
            raise ValueError
        gesamtprofil = _migriere_gesamtprofil(gesamtprofil)
        return ProfilArtefakt(
            profil_version=version,
            import_id=UUID(struktur["import_id"]),
            datei_pruefsumme=str(struktur["datei_pruefsumme"]),
            importparameter=dict(struktur["importparameter"]),
            tabellenbezeichnung=str(struktur["tabellenbezeichnung"]),
            erstellt_am=datetime.fromisoformat(struktur["erstellt_am"]),
            gesamtprofil=gesamtprofil,
            indikatorbedingungen=_indikatorbedingungen_laden(gesamtprofil),
            statistische_regeln=tuple(struktur["statistische_regeln"]),
            warnungen=tuple(struktur["warnungen"]),
        )
    except Importintegritaetsfehler:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as fehler:
        raise Importintegritaetsfehler("Das gespeicherte Profil-JSON ist ungültig.") from fehler
