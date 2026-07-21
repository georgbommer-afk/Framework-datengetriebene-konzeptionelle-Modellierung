"""Unit-Tests für die Zusammensetzung der Anwendung."""

from pathlib import Path

import pytest

from framework_mvp.bootstrap import DATENBANKPFAD_UMGEBUNGSVARIABLE, erstelle_projekt_service


def test_standardpfad_wird_verwendet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ohne Konfiguration wird die Datenbank im lokalen workspace angelegt."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, raising=False)

    erstelle_projekt_service().projekte_auflisten()

    assert (tmp_path / "workspace" / "framework_mvp.sqlite").is_file()


def test_pfad_aus_umgebungsvariable_wird_verwendet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die Umgebungsvariable bestimmt den Datenbankpfad."""
    datenbankpfad = tmp_path / "konfiguriert" / "projekte.sqlite"
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(datenbankpfad))

    erstelle_projekt_service().projekte_auflisten()

    assert datenbankpfad.is_file()


def test_expliziter_pfad_hat_vorrang(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ein Funktionsargument überschreibt den Pfad aus der Umgebung."""
    umgebungspfad = tmp_path / "umgebung.sqlite"
    expliziter_pfad = tmp_path / "explizit.sqlite"
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(umgebungspfad))

    erstelle_projekt_service(expliziter_pfad).projekte_auflisten()

    assert expliziter_pfad.is_file()
    assert not umgebungspfad.exists()
