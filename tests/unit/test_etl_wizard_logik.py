"""Tests der Mindestvoraussetzungen der aktivierten ETL-Wizardschritte."""

from framework_mvp.domain.models import DateiMetadaten, Dateityp
from framework_mvp.ui.pages.etl import _kann_weiter


def test_csv_benoetigt_keine_echte_tabellenauswahl() -> None:
    """Eine CSV darf Teilschritt vier ohne Tabellenblatt verlassen."""
    metadaten = DateiMetadaten("a.csv", "a.csv", 1, Dateityp.CSV, "checksum")
    assert _kann_weiter({"schritt": 4, "datei_metadaten": metadaten})


def test_vorschau_schaltet_datenprofil_frei() -> None:
    """Eine vorhandene vollständige Vorschau macht Teilschritt sechs erreichbar."""
    assert _kann_weiter({"schritt": 5, "vorschau": object()})


def test_schritt_sieben_bleibt_gesperrt() -> None:
    """Nach dem Datenprofil gibt es noch keine Importbestätigung."""
    assert not _kann_weiter({"schritt": 6})
