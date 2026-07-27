"""Tests der Logik des fünfstufigen ETL-Ablaufs."""

from datetime import UTC, datetime
from uuid import uuid4

from framework_mvp.domain.models import (
    CsvImportparameter,
    Dateityp,
    Dezimaltrennzeichen,
    Importstatus,
    Importvorgang,
    Profilzusammenfassung,
    Trennzeichenwahl,
    Zeichenkodierung,
)
from framework_mvp.ui.pages.etl import (
    _erkenne_csv_kodierung,
    _erkenne_csv_struktur,
    _importbezeichnung,
    _kann_weiter,
)


def test_vorschau_schaltet_datenprofil_frei() -> None:
    """Eine vorhandene vollständige Vorschau macht den Profilabschnitt erreichbar."""
    assert _kann_weiter({"schritt": 2, "vorschau": object()})


def test_bestaetigter_import_schaltet_transformation_frei() -> None:
    """Nur ein bestätigter Import macht den Transformationsabschnitt erreichbar."""
    assert _kann_weiter({"schritt": 3, "bestaetigter_import": object()})


def test_transformationsplan_schaltet_ergebnis_frei() -> None:
    """Ein reproduzierbarer Plan macht den Ergebnisabschnitt erreichbar."""
    assert _kann_weiter({"schritt": 4, "transformationsplan": object()})


def test_nach_schritt_fuenf_gibt_es_keinen_weiteren_etl_abschnitt() -> None:
    """Der ETL-Wizard endet mit dem Zwischendatensatz T."""
    assert not _kann_weiter({"schritt": 5})


def test_csv_kodierung_erkennt_utf8_bom_und_unsicheren_fallback() -> None:
    """BOM und verlustfreies UTF-8 werden sicher, ein Fallback als unsicher markiert."""
    assert _erkenne_csv_kodierung(b"\xef\xbb\xbfa,b\n") == (
        Zeichenkodierung.UTF_8_BOM,
        True,
    )
    assert _erkenne_csv_kodierung("ä;ö".encode("cp1252")) == (
        Zeichenkodierung.WINDOWS_1252,
        False,
    )


def test_csv_struktur_erkennt_zeilenumbruch_und_dezimaltrennzeichen() -> None:
    """Die technische Vorprüfung erkennt eindeutige CRLF- und Dezimalmuster."""
    assert _erkenne_csv_struktur(b"id;wert\r\n1;12,5\r\n", Zeichenkodierung.UTF_8, ";") == (
        "Windows (CRLF)",
        Dezimaltrennzeichen.KOMMA,
    )


def test_importbezeichnung_verwendet_fachliche_angaben_statt_uuid() -> None:
    """Datei, Quelle, Tabelle, Umfang und Status bilden die primäre Auswahlbezeichnung."""
    import_id = uuid4()
    importvorgang = Importvorgang(
        import_id,
        uuid4(),
        uuid4(),
        "ereignisse.csv",
        "ereignisse.csv",
        Dateityp.CSV,
        10,
        "a" * 64,
        CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.SEMIKOLON),
        "Ereignisdaten",
        14350,
        9,
        1,
        "projects/projekt/raw/datei.csv",
        "projects/projekt/profiles/profil.json",
        Profilzusammenfassung(0, 0, 0, 0),
        (),
        Importstatus.BESTAETIGT,
        datetime.now(UTC),
        datetime.now(UTC),
    )
    text = _importbezeichnung(importvorgang, "ERP Export")
    assert "ereignisse.csv" in text
    assert "ERP Export" in text
    assert "Ereignisdaten" in text
    assert "14,350 Zeilen" in text
    assert str(import_id) not in text
