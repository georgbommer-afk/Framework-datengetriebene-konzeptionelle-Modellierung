"""PDF-Rendering des konzeptionellen Modells."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from weasyprint import HTML

from framework_mvp.formatierung import formatiere_fachwert
from framework_mvp.reporting.report_data import REPORT_DATA_VERSION

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "conceptual_model" / "V1"

_PDF_TEMPLATE = "report_pdf.html"


class PdfRenderingFehler(RuntimeError):
    """Kennzeichnet einen Fehler beim Rendern des PDF-Reports."""


def render_report_pdf(
    report_data: Mapping[str, Any],
    zielpfad: str | Path,
) -> Path:
    """Rendert den aggregierten PDF-Report."""

    version = report_data.get("report_data_version")
    if version != REPORT_DATA_VERSION:
        raise PdfRenderingFehler(f"Nicht unterstützte Report-Datenversion: {version!r}.")

    ziel = Path(zielpfad)
    ziel.parent.mkdir(parents=True, exist_ok=True)

    try:
        environment = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
            finalize=formatiere_fachwert,
        )

        template = environment.get_template(_PDF_TEMPLATE)

        html = template.render(**report_data)

        HTML(
            string=html,
            base_url=str(_TEMPLATE_DIR),
            media_type="print",
        ).write_pdf(str(ziel))

    except Exception as fehler:
        raise PdfRenderingFehler(f"PDF-Report konnte nicht gerendert werden: {fehler}") from fehler

    return ziel
