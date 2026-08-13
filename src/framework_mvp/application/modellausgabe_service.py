"""Algorithmus 10: HTML- und PDF-Ausgabe eines validierten K*."""

import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from framework_mvp.application.dateinamen import (
    sicherer_dateiname,
    sicherer_dateinamenbestandteil,
)
from framework_mvp.application.modellvalidierung_service import ModellvalidierungService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.reporting.asset_resolver import ReportAssetFehler, resolve_report_assets
from framework_mvp.reporting.html_renderer import HtmlRenderingFehler, render_report_html
from framework_mvp.reporting.pdf_renderer import PdfRenderingFehler, render_report_pdf
from framework_mvp.reporting.report_data import ReportDataFehler, build_report_data
from framework_mvp.workspace import WorkspaceKonfiguration


@dataclass(frozen=True, slots=True)
class StrukturierteModellausgabe:
    """Reproduzierbare, nicht persistierte Dateien aus genau einem K*."""

    report_html: bytes | None
    html_dateiname: str | None
    report_pdf: bytes | None
    pdf_dateiname: str | None


class ModellausgabeService:
    """Rendert HTML und PDF aus derselben einmalig aufgebauten Reportdatenstruktur."""

    def __init__(
        self,
        validierungen: ModellvalidierungService,
        projekte: ProjektService,
        workspace: WorkspaceKonfiguration,
    ) -> None:
        self._validierungen = validierungen
        self._projekte = projekte
        self._workspace = workspace

    def erzeugen(
        self,
        *,
        validierungslauf_id: UUID,
        projekt_id: UUID,
        k_stern_id: UUID,
        html: bool,
        pdf: bool,
    ) -> StrukturierteModellausgabe:
        if not html and not pdf:
            raise Importintegritaetsfehler("Mindestens HTML oder PDF muss gewählt werden.")
        k_stern = self._validierungen.uebergabe_schritt10(
            validierungslauf_id, projekt_id, k_stern_id
        )
        projekt = self._projekte.projekt_laden(projekt_id)
        if projekt is None or str(k_stern.get("projekt_id")) != str(projekt.projekt_id):
            raise Importintegritaetsfehler(
                "Projektbezeichnung und validiertes Modell gehören nicht zur "
                "angeforderten Projekt-ID."
            )
        try:
            report_data = build_report_data(k_stern)
            aufgeloeste_reportdaten = resolve_report_assets(
                report_data,
                workspace_root=self._workspace.basisverzeichnis,
            )
            html_bytes = (
                render_report_html(aufgeloeste_reportdaten).encode("utf-8") if html else None
            )
            pdf_bytes: bytes | None = None
            if pdf:
                with tempfile.TemporaryDirectory(prefix="framework-mvp-report-") as temp:
                    ziel = Path(temp) / "report.pdf"
                    render_report_pdf(aufgeloeste_reportdaten, ziel)
                    pdf_bytes = ziel.read_bytes()
        except (
            ReportDataFehler,
            ReportAssetFehler,
            HtmlRenderingFehler,
            PdfRenderingFehler,
        ) as fehler:
            raise Importintegritaetsfehler(
                f"Der Report aus K* konnte nicht erzeugt werden: {fehler}"
            ) from fehler
        except OSError as fehler:
            raise Importintegritaetsfehler(
                f"Die temporäre Reportdatei konnte nicht verarbeitet werden: {fehler}"
            ) from fehler

        projektname = sicherer_dateinamenbestandteil(projekt.bezeichnung)
        basis = f"Konzeptionelles Modell {projektname}"
        return StrukturierteModellausgabe(
            html_bytes,
            sicherer_dateiname(basis, "html") if html else None,
            pdf_bytes,
            sicherer_dateiname(basis, "pdf") if pdf else None,
        )
