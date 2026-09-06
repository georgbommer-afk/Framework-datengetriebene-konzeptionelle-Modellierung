"""Grundlegende Tests der Paketkonfiguration."""

import tomllib
from pathlib import Path

from framework_mvp import __version__
from framework_mvp.application.projektarchiv_service import ProjektArchivService


def test_version_ist_definiert() -> None:
    """Die Anwendung muss eine nicht leere Versionsnummer bereitstellen."""
    assert __version__


def test_pyproject_ist_einzige_versionsquelle_fuer_app_reports_und_archiv() -> None:
    with Path("pyproject.toml").open("rb") as datei:
        pyproject_version = tomllib.load(datei)["project"]["version"]

    assert __version__ == pyproject_version
    assert ProjektArchivService._app_version() == pyproject_version
