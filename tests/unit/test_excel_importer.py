"""Tests der Excel-Metadaten- und -Leselogik."""

from pathlib import Path

import pandas as pd
import pytest

from framework_mvp.domain.exceptions import Datenimportfehler
from framework_mvp.domain.models import (
    ExcelImportparameter,
    Kopfzeileneinstellung,
    Kopfzeilenmodus,
)
from framework_mvp.infrastructure.dateiimport.excel_importer import (
    ermittle_tabellenblaetter,
    lese_excel,
)


def _xlsx(tmp_path: Path, blaetter: dict[str, pd.DataFrame]) -> bytes:
    pfad = tmp_path / "test.xlsx"
    with pd.ExcelWriter(pfad, engine="openpyxl") as writer:
        for name, daten in blaetter.items():
            daten.to_excel(writer, sheet_name=name, index=False)
    return pfad.read_bytes()


def test_datei_mit_einem_blatt(tmp_path: Path) -> None:
    """Ein einzelnes Blatt wird mit seinen ungefähren Dimensionen erkannt."""
    blaetter = ermittle_tabellenblaetter(_xlsx(tmp_path, {"Daten": pd.DataFrame({"a": [1]})}))
    assert [(b.name, b.ungefaehre_zeilenanzahl, b.ungefaehre_spaltenanzahl) for b in blaetter] == [
        ("Daten", 2, 1)
    ]


def test_datei_mit_mehreren_blaettern(tmp_path: Path) -> None:
    """Alle Blattnamen bleiben in Arbeitsmappenreihenfolge verfügbar."""
    inhalt = _xlsx(
        tmp_path,
        {"Eins": pd.DataFrame({"a": [1]}), "Zwei": pd.DataFrame({"b": [2]})},
    )
    assert [blatt.name for blatt in ermittle_tabellenblaetter(inhalt)] == ["Eins", "Zwei"]


def test_blatt_kann_ausgewaehlt_werden(tmp_path: Path) -> None:
    """Nur das gewählte Tabellenblatt wird in das DataFrame übernommen."""
    inhalt = _xlsx(
        tmp_path,
        {"Eins": pd.DataFrame({"wert": [1]}), "Zwei": pd.DataFrame({"wert": [9]})},
    )
    assert lese_excel(inhalt, ExcelImportparameter("Zwei")).iloc[0, 0] == 9


def test_benutzerdefinierte_kopfzeile(tmp_path: Path) -> None:
    """Eine benutzerdefinierte Kopfzeilennummer wird einsbasiert ausgewertet."""
    pfad = tmp_path / "kopf.xlsx"
    pd.DataFrame([["Hinweis", None], ["a", "b"], [1, 2]]).to_excel(pfad, index=False, header=False)
    parameter = ExcelImportparameter(
        "Sheet1", Kopfzeileneinstellung(Kopfzeilenmodus.BENUTZERDEFINIERT, 2)
    )
    assert list(lese_excel(pfad.read_bytes(), parameter).columns) == ["a", "b"]


def test_ohne_kopfzeile(tmp_path: Path) -> None:
    """Ohne Kopfzeile bleibt die erste Tabellenzeile erhalten."""
    inhalt = _xlsx(tmp_path, {"Daten": pd.DataFrame({"a": [1]})})
    parameter = ExcelImportparameter("Daten", Kopfzeileneinstellung(Kopfzeilenmodus.KEINE))
    assert lese_excel(inhalt, parameter).shape == (2, 1)


def test_nicht_vorhandenes_blatt(tmp_path: Path) -> None:
    """Ein unbekannter Blattname wird als erwartbarer Importfehler gemeldet."""
    inhalt = _xlsx(tmp_path, {"Daten": pd.DataFrame({"a": [1]})})
    with pytest.raises(Datenimportfehler, match="nicht vorhanden"):
        lese_excel(inhalt, ExcelImportparameter("Fehlt"))


@pytest.mark.parametrize(
    "funktion", [ermittle_tabellenblaetter, lambda b: lese_excel(b, ExcelImportparameter("A"))]
)
def test_beschaedigte_xlsx(funktion: object) -> None:
    """Beschädigte Arbeitsmappen liefern keine technischen Tracebacks nach außen."""
    with pytest.raises(Datenimportfehler, match="beschädigt|gelesen"):
        funktion(b"keine XLSX-Datei")  # type: ignore[operator]
