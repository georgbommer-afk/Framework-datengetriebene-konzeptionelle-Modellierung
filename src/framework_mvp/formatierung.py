"""Zentrale, rein darstellungsbezogene Fachformatierung für UI und Reports."""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from numbers import Real
from typing import Any


def formatiere_zahl(wert: Any, *, nachkommastellen: int = 2) -> str:
    """Formatiert endliche Zahlen ohne binäre Float-Artefakte im deutschen Dezimalformat."""
    if isinstance(wert, bool):
        return str(wert)
    if nachkommastellen < 0:
        raise ValueError("Die Anzahl der Nachkommastellen darf nicht negativ sein.")
    try:
        dezimalwert = Decimal(str(wert))
        if not dezimalwert.is_finite():
            return str(wert)
        quantum = Decimal(1).scaleb(-nachkommastellen)
        gerundet = dezimalwert.quantize(quantum, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return str(wert)
    if gerundet == 0:
        gerundet = abs(gerundet)
    text = format(gerundet, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def formatiere_messwert(wert: Any, einheit: str = "") -> str:
    """Verbindet einen fachlich formatierten Zahlenwert mit seiner Einheit."""
    if isinstance(wert, (Real, Decimal)) and not isinstance(wert, bool):
        anzeige = formatiere_zahl(wert)
    else:
        anzeige = str(wert)
    bereinigte_einheit = einheit.strip()
    return f"{anzeige} {bereinigte_einheit}" if bereinigte_einheit else anzeige


def formatiere_anteil_als_prozent(wert: Any) -> str:
    """Formatiert einen Anteil als Prozentwert, ohne den gespeicherten Rohwert zu verändern."""
    if isinstance(wert, bool) or not isinstance(wert, (Real, Decimal)):
        return str(wert)
    try:
        prozentwert = Decimal(str(wert)) * Decimal(100)
    except (InvalidOperation, ValueError):
        return str(wert)
    return formatiere_messwert(prozentwert, "%")


def formatiere_zeitstempel(wert: Any) -> str:
    """Formatiert bekannte Datums-/Zeitwerte lesbar; unbekannte Texte bleiben unverändert."""
    zeitwert: datetime | date
    if isinstance(wert, datetime | date):
        zeitwert = wert
    elif isinstance(wert, str):
        try:
            zeitwert = datetime.fromisoformat(wert.replace("Z", "+00:00"))
        except ValueError:
            return wert
    else:
        return str(wert)
    if isinstance(zeitwert, datetime):
        basis = zeitwert.strftime("%d.%m.%Y %H:%M:%S")
        offset = zeitwert.strftime("%z")
        if offset:
            basis += f" {offset[:3]}:{offset[3:]}"
        return basis
    return zeitwert.strftime("%d.%m.%Y")


def formatiere_fachwert(wert: Any) -> Any:
    """Jinja-/XLSX-Helfer für skalare Fachwerte ohne Änderung persistierter Rohwerte."""
    if isinstance(wert, bool) or wert is None:
        return wert
    if isinstance(wert, (Real, Decimal)):
        return formatiere_zahl(wert)
    if isinstance(wert, datetime | date):
        return formatiere_zeitstempel(wert)
    return wert
