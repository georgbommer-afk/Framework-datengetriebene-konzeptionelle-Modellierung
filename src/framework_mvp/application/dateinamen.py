"""Zentrale, Unicode-erhaltende Dateinamensregeln für Benutzerausgaben."""

import re
import unicodedata

_UNZULAESSIG = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_LEERRAUM = re.compile(r"\s+")


def sicherer_dateinamenbestandteil(
    wert: str, *, fallback: str = "Unbenanntes Projekt"
) -> str:
    """Entfernt unzulässige Dateisystemzeichen und bewahrt lesbares Unicode."""
    normalisiert = unicodedata.normalize("NFC", str(wert))
    bereinigt = _UNZULAESSIG.sub(" ", normalisiert)
    bereinigt = _LEERRAUM.sub(" ", bereinigt).strip(" .")
    return bereinigt or fallback


def sicherer_dateiname(stamm: str, endung: str) -> str:
    """Erzeugt aus einem sichtbaren Stamm und einer Endung einen sicheren Dateinamen."""
    suffix = str(endung).strip().lstrip(".").lower()
    if not suffix or not suffix.isalnum():
        raise ValueError("Die Dateiendung ist ungültig.")
    return f"{sicherer_dateinamenbestandteil(stamm)}.{suffix}"
