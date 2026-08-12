"""Jinja-Rendering des konzeptionellen Modells als HTML."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateError,
    select_autoescape,
)


_TEMPLATE_VERSION = "V1"
_TEMPLATE_ROOT = (
    Path(__file__).resolve().parent
    / "templates"
    / "conceptual_model"
    / _TEMPLATE_VERSION
)
_TEMPLATE_NAME = "report_html.html"


class HtmlRenderingFehler(RuntimeError):
    """Kennzeichnet einen Fehler beim Rendern des HTML-Reports."""

def _hat_inhalt(wert: Any) -> bool:
    """Prüft, ob ein Wert für die fachliche Reportdarstellung Inhalt besitzt."""
    if wert is None:
        return False

    if isinstance(wert, str):
        return wert.strip() not in {"", "-", "–"}

    if isinstance(wert, Mapping):
        return any(_hat_inhalt(eintrag) for eintrag in wert.values())

    if isinstance(wert, (list, tuple, set, frozenset)):
        return any(_hat_inhalt(eintrag) for eintrag in wert)

    return True

def template_verzeichnis() -> Path:
    """Liefert das Verzeichnis des aktuell verwendeten Report-Templates."""
    return _TEMPLATE_ROOT


def _umgebung() -> Environment:
    if not _TEMPLATE_ROOT.is_dir():
        raise HtmlRenderingFehler(
            f"Template-Verzeichnis nicht gefunden: {_TEMPLATE_ROOT}"
        )

    umgebung = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_ROOT)),
        autoescape=select_autoescape(
            enabled_extensions=("html", "xml"),
            default_for_string=True,
        ),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    umgebung.globals["hat_inhalt"] = _hat_inhalt

    return umgebung


def render_report_html(report_data: Mapping[str, Any]) -> str:
    """Rendert formatneutrale Reportdaten in ein vollständiges HTML-Dokument."""
    version = report_data.get("report_data_version")
    if version != 1:
        raise HtmlRenderingFehler(
            f"Nicht unterstützte Report-Datenversion: {version!r}."
        )

    try:
        template = _umgebung().get_template(_TEMPLATE_NAME)
        return template.render(**dict(report_data))
    except TemplateError as exc:
        raise HtmlRenderingFehler(
            f"HTML-Report konnte nicht gerendert werden: {exc}"
        ) from exc


def render_report_html_datei(
    report_data: Mapping[str, Any],
    zielpfad: str | Path,
) -> Path:
    """Rendert den HTML-Report und schreibt ihn für Vorschau oder Tests."""
    ziel = Path(zielpfad)
    ziel.parent.mkdir(parents=True, exist_ok=True)

    html = render_report_html(report_data)
    ziel.write_text(html, encoding="utf-8")

    return ziel