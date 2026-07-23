"""Reine Hilfsfunktionen für Eingaben der Oberfläche."""

from collections.abc import Iterable


def mehrzeiliger_text_als_liste(text: str) -> tuple[str, ...]:
    """Wandelt nicht leere, bereinigte Textzeilen in ein Tupel um."""
    return tuple(bereinigt for zeile in text.splitlines() if (bereinigt := zeile.strip()))


def liste_als_mehrzeiliger_text(werte: Iterable[str]) -> str:
    """Verbindet Listeneinträge in unveränderter Reihenfolge durch Zeilenumbrüche."""
    return "\n".join(werte)
