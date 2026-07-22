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


def test_datenprofil_schaltet_importpruefung_frei() -> None:
    """Ein berechnetes Profil macht Teilschritt sieben erreichbar."""
    assert _kann_weiter({"schritt": 6, "profil": object()})


def test_nach_schritt_sieben_gibt_es_keinen_weiteren_schritt() -> None:
    """Der vollständige Wizard endet mit der verbindlichen Bestätigung."""
    assert not _kann_weiter({"schritt": 7})
