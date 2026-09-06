"""Softwaretechnische Instanziierung des entwickelten Frameworks."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _paketversion() -> str:
    """Liest die einzige Versionsangabe aus Paketmetadaten oder dem Quellprojekt."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.is_file():
        try:
            with pyproject.open("rb") as datei:
                projekt = tomllib.load(datei).get("project", {})
            wert = str(projekt.get("version", "")).strip()
        except (OSError, tomllib.TOMLDecodeError, AttributeError):
            wert = ""
        if wert:
            return wert
    try:
        return version("framework-mvp")
    except PackageNotFoundError:
        return "0+unknown"


__version__ = _paketversion()
