"""Tests der CSV-Erkennung und -Leselogik."""

import pytest

from framework_mvp.domain.exceptions import Datenimportfehler, Domaenenfehler
from framework_mvp.domain.models import (
    CsvImportparameter,
    Dezimaltrennzeichen,
    Kopfzeileneinstellung,
    Kopfzeilenmodus,
    Trennzeichenwahl,
    Zeichenkodierung,
)
from framework_mvp.infrastructure.dateiimport.csv_importer import (
    erkenne_trennzeichen,
    lese_csv,
)


def _parameter(
    trennzeichen: Trennzeichenwahl,
    *,
    kodierung: Zeichenkodierung = Zeichenkodierung.UTF_8,
    erkannt: str = "",
    kopfzeile: Kopfzeileneinstellung | None = None,
    dezimal: Dezimaltrennzeichen = Dezimaltrennzeichen.PUNKT,
) -> CsvImportparameter:
    return CsvImportparameter(
        trennzeichenwahl=trennzeichen,
        erkanntes_trennzeichen=erkannt,
        zeichenkodierung=kodierung,
        kopfzeile=kopfzeile or Kopfzeileneinstellung(),
        dezimaltrennzeichen=dezimal,
    )


@pytest.mark.parametrize(
    ("inhalt", "wahl"),
    [
        (b"a,b\n1,2", Trennzeichenwahl.KOMMA),
        (b"a;b\n1;2", Trennzeichenwahl.SEMIKOLON),
        (b"a\tb\n1\t2", Trennzeichenwahl.TABULATOR),
    ],
)
def test_csv_trennzeichen(inhalt: bytes, wahl: Trennzeichenwahl) -> None:
    """Komma, Semikolon und Tabulator werden korrekt verwendet."""
    assert lese_csv(inhalt, _parameter(wahl)).shape == (1, 2)


@pytest.mark.parametrize(
    ("text", "kodierung"),
    [
        ("name\nGröße", Zeichenkodierung.UTF_8),
        ("name\nGröße", Zeichenkodierung.UTF_8_BOM),
        ("name\nGröße", Zeichenkodierung.ISO_8859_1),
        ("name\nGröße", Zeichenkodierung.WINDOWS_1252),
    ],
)
def test_csv_zeichenkodierungen(text: str, kodierung: Zeichenkodierung) -> None:
    """Alle geforderten repräsentativen Kodierungen werden gelesen."""
    inhalt = text.encode(kodierung.value)
    daten = lese_csv(inhalt, _parameter(Trennzeichenwahl.KOMMA, kodierung=kodierung))
    assert daten.iloc[0, 0] == "Größe"


def test_dezimalkomma() -> None:
    """Dezimalkommas werden bei einem anderen Feldtrenner numerisch interpretiert."""
    daten = lese_csv(
        b"wert\n1,5",
        _parameter(Trennzeichenwahl.SEMIKOLON, dezimal=Dezimaltrennzeichen.KOMMA),
    )
    assert daten.iloc[0, 0] == 1.5


def test_benutzerdefinierte_kopfzeile() -> None:
    """Die einsbasierte zweite Dateizeile kann als Kopfzeile dienen."""
    kopf = Kopfzeileneinstellung(Kopfzeilenmodus.BENUTZERDEFINIERT, 2)
    daten = lese_csv(b"Hinweis\na,b\n1,2", _parameter(Trennzeichenwahl.KOMMA, kopfzeile=kopf))
    assert list(daten.columns) == ["a", "b"]


def test_ohne_kopfzeile() -> None:
    """Ohne Kopfzeile bleibt die erste Zeile ein Datensatz."""
    kopf = Kopfzeileneinstellung(Kopfzeilenmodus.KEINE)
    daten = lese_csv(b"1,2\n3,4", _parameter(Trennzeichenwahl.KOMMA, kopfzeile=kopf))
    assert daten.shape == (2, 2)


def test_leere_csv() -> None:
    """Eine inhaltlich leere CSV wird kontrolliert abgelehnt."""
    with pytest.raises(Datenimportfehler, match="keine tabellarischen Daten"):
        lese_csv(b"   ", _parameter(Trennzeichenwahl.KOMMA))


def test_falsche_zeichenkodierung() -> None:
    """Nicht dekodierbare Bytes führen zu einer verständlichen Meldung."""
    with pytest.raises(Datenimportfehler, match="Zeichenkodierung"):
        lese_csv(b"name\n\xff", _parameter(Trennzeichenwahl.KOMMA))


def test_automatische_erkennung() -> None:
    """Ein Semikolon wird aus einer repräsentativen Probe erkannt."""
    assert erkenne_trennzeichen(b"a;b\n1;2", Zeichenkodierung.UTF_8) == ";"


def test_ungueltiges_trennzeichen() -> None:
    """Mehrere Zeichen werden bereits im Parametermodell abgelehnt."""
    with pytest.raises(Domaenenfehler, match="genau ein"):
        CsvImportparameter(
            trennzeichenwahl=Trennzeichenwahl.BENUTZERDEFINIERT,
            benutzerdefiniertes_trennzeichen="::",
        )


def test_ungueltige_kopfzeilennummer() -> None:
    """Eine benutzerdefinierte Kopfzeile beginnt bei eins."""
    with pytest.raises(Domaenenfehler, match="positive Ganzzahl"):
        Kopfzeileneinstellung(Kopfzeilenmodus.BENUTZERDEFINIERT, 0)
