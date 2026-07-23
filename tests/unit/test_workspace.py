"""Tests der zentralen Workspace-Konfiguration."""

from pathlib import Path
from uuid import uuid4

import pytest

from framework_mvp.workspace import (
    STANDARD_WORKSPACE_PFAD,
    WORKSPACE_UMGEBUNGSVARIABLE,
    WorkspaceKonfiguration,
)


def test_standardpfad_ist_vom_arbeitsverzeichnis_unabhaengig(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein Verzeichniswechsel beeinflusst den Standardpfad nicht."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(WORKSPACE_UMGEBUNGSVARIABLE, raising=False)
    assert WorkspaceKonfiguration.ermitteln().basisverzeichnis == STANDARD_WORKSPACE_PFAD


def test_umgebungsvariable_und_expliziter_pfad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein expliziter Pfad besitzt Vorrang vor der Umgebungsvariable."""
    umgebung = tmp_path / "umgebung"
    explizit = tmp_path / "explizit"
    monkeypatch.setenv(WORKSPACE_UMGEBUNGSVARIABLE, str(umgebung))
    assert WorkspaceKonfiguration.ermitteln().basisverzeichnis == umgebung
    assert WorkspaceKonfiguration.ermitteln(explizit).basisverzeichnis == explizit


def test_projektverzeichnisse_werden_beim_ersten_bedarf_angelegt(tmp_path: Path) -> None:
    """Alle Artefaktverzeichnisse werden projektbezogen erzeugt."""
    projekt_id = uuid4()
    pfade = WorkspaceKonfiguration.ermitteln(tmp_path).fuer_projekt_anlegen(projekt_id)
    assert pfade.projekt == tmp_path / "projects" / str(projekt_id)
    assert all(
        pfad.is_dir()
        for pfad in (
            pfade.raw,
            pfade.profiles,
            pfade.interim,
            pfade.mappings,
            pfade.event_logs,
            pfade.quality,
        )
    )
