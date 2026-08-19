"""Verträge der zentralen sicheren Dateinamensfunktion."""

import pytest

from framework_mvp.application.dateinamen import (
    sicherer_dateiname,
    sicherer_dateinamenbestandteil,
)


def test_unzulaessige_zeichen_entfallen_und_umlaute_bleiben_erhalten() -> None:
    assert sicherer_dateiname("Konzeptionelles Modell Förderanlage / Süd: ÄÖÜ", "PDF") == (
        "Konzeptionelles Modell Förderanlage Süd ÄÖÜ.pdf"
    )


def test_leerer_name_erhaelt_nachvollziehbaren_fallback() -> None:
    assert sicherer_dateinamenbestandteil(" /:*?<>|. ") == "Unbenanntes Projekt"


def test_ungueltige_endung_wird_abgewiesen() -> None:
    with pytest.raises(ValueError, match="Dateiendung"):
        sicherer_dateiname("Modell", "pdf/zip")
