"""Tests für sichere Uploadmetadaten und automatische Vorschläge."""

import hashlib

import pytest

from framework_mvp.application.datenimport_service import (
    schlage_datenquellenbezeichnung_vor,
    schlage_quellenart_vor,
)
from framework_mvp.domain.exceptions import Datenimportfehler
from framework_mvp.domain.models import Dateityp, Quellenart
from framework_mvp.infrastructure.dateiimport.datei_metadaten import (
    MAX_UPLOAD_MB_UMGEBUNGSVARIABLE,
    bereinige_dateiname,
    ermittle_dateimetadaten,
    ermittle_max_upload_mb,
)


def test_dateiname_wird_sicher_bereinigt() -> None:
    """Sonderzeichen werden nicht unverändert übernommen."""
    assert bereinige_dateiname("umsatz<script>.csv") == "umsatz_script_.csv"


@pytest.mark.parametrize("name", ["../../daten.csv", r"C:\temp\daten.csv"])
def test_pfadbestandteile_werden_entfernt(name: str) -> None:
    """Unix- und Windows-Pfadbestandteile gelangen nicht in den sicheren Namen."""
    assert bereinige_dateiname(name) == "daten.csv"


def test_pruefsumme_und_dateigroesse_sind_korrekt() -> None:
    """Die Metadaten beziehen sich exakt auf die unveränderten Bytes."""
    inhalt = b"a,b\n1,2\n"
    metadaten = ermittle_dateimetadaten("daten.csv", inhalt)
    assert metadaten.dateigroesse_bytes == len(inhalt)
    assert metadaten.sha256 == hashlib.sha256(inhalt).hexdigest()


def test_groessenbegrenzung_wird_eingehalten(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ein Upload oberhalb der konfigurierten Grenze wird abgelehnt."""
    monkeypatch.setenv(MAX_UPLOAD_MB_UMGEBUNGSVARIABLE, "1")
    with pytest.raises(Datenimportfehler, match="maximal erlaubte Größe"):
        ermittle_dateimetadaten("gross.csv", b"x" * (1024 * 1024 + 1))


@pytest.mark.parametrize("wert", ["0", "-2", "eins"])
def test_ungueltige_umgebungsvariable_wird_kontrolliert_behandelt(
    wert: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nur positive Ganzzahlen sind als Megabyte-Grenze zulässig."""
    monkeypatch.setenv(MAX_UPLOAD_MB_UMGEBUNGSVARIABLE, wert)
    with pytest.raises(Datenimportfehler, match="positive Ganzzahl"):
        ermittle_max_upload_mb()


def test_bezeichnung_wird_ohne_dateiendung_vorgeschlagen() -> None:
    """Der Vorschlag entfernt Endung und lesetrennt einfache Dateinamen."""
    assert schlage_datenquellenbezeichnung_vor("tages_export.csv", "") == "tages export"


def test_manuelle_bezeichnung_wird_nicht_ueberschrieben() -> None:
    """Bereits erfasste Angaben haben Vorrang vor dem Dateivorschlag."""
    assert schlage_datenquellenbezeichnung_vor("neu.csv", "Manuell") == "Manuell"


@pytest.mark.parametrize(
    ("dateityp", "quellenart"),
    [(Dateityp.CSV, Quellenart.CSV), (Dateityp.XLSX, Quellenart.EXCEL)],
)
def test_quellenart_wird_passend_vorgeschlagen(dateityp: Dateityp, quellenart: Quellenart) -> None:
    """CSV und XLSX werden ihren fachlichen Quellenarten zugeordnet."""
    assert schlage_quellenart_vor(dateityp) is quellenart


@pytest.mark.parametrize("name", ["daten.txt", "daten.xls", "daten"])
def test_ungueltige_dateiendung_wird_abgelehnt(name: str) -> None:
    """Nur CSV und XLSX sind in diesem Inkrement zulässig."""
    with pytest.raises(Datenimportfehler, match="CSV- und XLSX"):
        ermittle_dateimetadaten(name, b"inhalt")


def test_leere_datei_wird_abgelehnt() -> None:
    """Ein Upload ohne Bytes wird verständlich abgelehnt."""
    with pytest.raises(Datenimportfehler, match="leer"):
        ermittle_dateimetadaten("leer.csv", b"")
