"""Separat testbare CSV-Erkennung und CSV-Leselogik."""

import csv
from io import BytesIO

import pandas as pd

from framework_mvp.domain.exceptions import Datenimportfehler
from framework_mvp.domain.models import CsvImportparameter, Zeichenkodierung


def erkenne_trennzeichen(dateiinhalt: bytes, kodierung: Zeichenkodierung) -> str:
    """Erkennt ein übliches CSV-Trennzeichen anhand einer begrenzten Textprobe."""
    try:
        textprobe = dateiinhalt[:65536].decode(kodierung.value)
    except UnicodeDecodeError as fehler:
        raise Datenimportfehler(
            "Die CSV-Datei kann mit der gewählten Zeichenkodierung nicht gelesen werden."
        ) from fehler
    if not textprobe.strip():
        raise Datenimportfehler("Die CSV-Datei enthält keine lesbaren Daten.")
    try:
        return csv.Sniffer().sniff(textprobe, delimiters=",;\t|").delimiter
    except csv.Error as fehler:
        raise Datenimportfehler(
            "Das CSV-Trennzeichen konnte nicht automatisch erkannt werden. "
            "Bitte wählen Sie es manuell."
        ) from fehler


def lese_csv(dateiinhalt: bytes, parameter: CsvImportparameter) -> pd.DataFrame:
    """Liest eine vollständige CSV-Datei mit validierten Parametern ein."""
    try:
        daten = pd.read_csv(
            BytesIO(dateiinhalt),
            sep=parameter.trennzeichen,
            encoding=parameter.zeichenkodierung.value,
            decimal=parameter.dezimaltrennzeichen.value,
            thousands=parameter.tausendertrennzeichen.value or None,
            header=parameter.kopfzeile.pandas_header,
        )
    except UnicodeDecodeError as fehler:
        raise Datenimportfehler(
            "Die CSV-Datei kann mit der gewählten Zeichenkodierung nicht gelesen werden."
        ) from fehler
    except pd.errors.EmptyDataError as fehler:
        raise Datenimportfehler("Die CSV-Datei enthält keine tabellarischen Daten.") from fehler
    except (pd.errors.ParserError, ValueError) as fehler:
        raise Datenimportfehler(
            "Die CSV-Datei kann mit den gewählten Importeinstellungen nicht gelesen werden."
        ) from fehler
    if daten.empty and len(daten.columns) == 0:
        raise Datenimportfehler("Die CSV-Datei enthält keine tabellarischen Daten.")
    return daten
