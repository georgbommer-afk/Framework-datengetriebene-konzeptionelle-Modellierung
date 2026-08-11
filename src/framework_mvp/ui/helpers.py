"""Reine Hilfsfunktionen für Eingaben der Oberfläche."""

from collections.abc import Callable, Iterable
from typing import cast

import streamlit as st

AUSWAHL_PLATZHALTER = "Choose an option"


def fachliche_auswahl[T](
    label: str,
    optionen: Iterable[T],
    *,
    wert: T | None = None,
    format_func: Callable[[T], str] = str,
    key: str | None = None,
    help: str | None = None,
) -> T | None:
    """Zeigt eine fachliche Auswahl ohne implizit gewählten ersten Wert."""
    werte = list(optionen)
    index = werte.index(wert) if wert in werte else None
    return cast(
        T | None,
        st.selectbox(
            label,
            werte,
            index=index,
            format_func=format_func,
            key=key,
            help=help,
            placeholder=AUSWAHL_PLATZHALTER,
        ),
    )


def mehrzeiliger_text_als_liste(text: str) -> tuple[str, ...]:
    """Wandelt nicht leere, bereinigte Textzeilen in ein Tupel um."""
    return tuple(bereinigt for zeile in text.splitlines() if (bereinigt := zeile.strip()))


def liste_als_mehrzeiliger_text(werte: Iterable[str]) -> str:
    """Verbindet Listeneinträge in unveränderter Reihenfolge durch Zeilenumbrüche."""
    return "\n".join(werte)
