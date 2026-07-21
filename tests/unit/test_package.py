"""Grundlegende Tests der Paketkonfiguration."""

from framework_mvp import __version__


def test_version_ist_definiert() -> None:
    """Die Anwendung muss eine nicht leere Versionsnummer bereitstellen."""
    assert __version__
