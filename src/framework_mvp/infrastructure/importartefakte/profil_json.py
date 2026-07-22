"""Versionierte, strikt gültige JSON-Serialisierung technischer Datenprofile."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any
from uuid import UUID

from framework_mvp.domain.models import Datenprofil
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.persistence.sqlite_importvorgang_repository import (
    serialisiere_importparameter,
)

PROFIL_VERSION = 1

STATISTISCHE_REGELN = (
    "Echte Fehlwerte folgen der Pandas-Semantik.",
    "Textuelle Platzhalter werden nach strip exakt und ohne Beachtung der Schreibweise erkannt.",
    "Numerische Kennzahlen verwenden ausschließlich endliche Werte.",
    "Potenzielle Ausreißer liegen außerhalb der 1,5-IQR-Grenzen.",
    "Zeitspalten benötigen mindestens 90 Prozent interpretierbare reguläre Werte.",
    "Seltene Kategorien besitzen einen Anteil von weniger als einem Prozent.",
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
        "gesamtprofil": _json_wert(asdict(profil)),
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


def lade_profil_json(pfad: Path) -> ProfilArtefakt:
    """Lädt und validiert ein unterstütztes Profil-JSON."""
    try:
        struktur = json.loads(pfad.read_text(encoding="utf-8"))
        version = int(struktur["profil_version"])
        if version != PROFIL_VERSION:
            raise Importintegritaetsfehler(
                f"Die Profilversion {version} wird nicht unterstützt; "
                f"erwartet wird {PROFIL_VERSION}."
            )
        gesamtprofil = struktur["gesamtprofil"]
        if not isinstance(gesamtprofil, dict) or "spaltenprofile" not in gesamtprofil:
            raise ValueError
        return ProfilArtefakt(
            profil_version=version,
            import_id=UUID(struktur["import_id"]),
            datei_pruefsumme=str(struktur["datei_pruefsumme"]),
            importparameter=dict(struktur["importparameter"]),
            tabellenbezeichnung=str(struktur["tabellenbezeichnung"]),
            erstellt_am=datetime.fromisoformat(struktur["erstellt_am"]),
            gesamtprofil=gesamtprofil,
            statistische_regeln=tuple(struktur["statistische_regeln"]),
            warnungen=tuple(struktur["warnungen"]),
        )
    except Importintegritaetsfehler:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as fehler:
        raise Importintegritaetsfehler("Das gespeicherte Profil-JSON ist ungültig.") from fehler
