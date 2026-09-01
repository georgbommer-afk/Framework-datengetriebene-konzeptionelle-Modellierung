"""Algorithmus 10: HTML- und PDF-Ausgabe eines validierten K*."""

import hashlib
import json
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
    """Reproduzierbare Dateien aus genau einem K*."""

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
        ausgabe = StrukturierteModellausgabe(
            html_bytes,
            sicherer_dateiname(basis, "html") if html else None,
            pdf_bytes,
            sicherer_dateiname(basis, "pdf") if pdf else None,
        )
        self._persistieren(projekt_id, validierungslauf_id, k_stern_id, ausgabe)
        return ausgabe

    def _reportverzeichnis(
        self, projekt_id: UUID, validierungslauf_id: UUID, k_stern_id: UUID
    ) -> Path:
        return (
            self._workspace.basisverzeichnis
            / "projects"
            / str(projekt_id)
            / "reports"
            / f"{validierungslauf_id}_{k_stern_id}"
        )

    def _persistieren(
        self,
        projekt_id: UUID,
        validierungslauf_id: UUID,
        k_stern_id: UUID,
        ausgabe: StrukturierteModellausgabe,
    ) -> None:
        verzeichnis = self._reportverzeichnis(projekt_id, validierungslauf_id, k_stern_id)
        verzeichnis.mkdir(parents=True, exist_ok=True)
        dateien: dict[str, dict[str, str]] = {}
        for formatname, inhalt, dateiname in (
            ("html", ausgabe.report_html, ausgabe.html_dateiname),
            ("pdf", ausgabe.report_pdf, ausgabe.pdf_dateiname),
        ):
            if inhalt is None or dateiname is None:
                continue
            artefaktname = f"report.{formatname}"
            (verzeichnis / artefaktname).write_bytes(inhalt)
            dateien[formatname] = {
                "artefaktname": artefaktname,
                "dateiname": dateiname,
                "sha256": hashlib.sha256(inhalt).hexdigest(),
            }
        manifest = {
            "artefaktart": "konzeptionelle_modellausgabe",
            "artefaktversion": 1,
            "projekt_id": str(projekt_id),
            "validierungslauf_id": str(validierungslauf_id),
            "k_stern_id": str(k_stern_id),
            "dateien": dateien,
        }
        (verzeichnis / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )

    def persistierte_ausgabe_laden(
        self, *, projekt_id: UUID, validierungslauf_id: UUID, k_stern_id: UUID
    ) -> StrukturierteModellausgabe | None:
        """Lädt eine gespeicherte Ausgabe erst nach Lineage- und Hashprüfung."""
        self._validierungen.uebergabe_schritt10(validierungslauf_id, projekt_id, k_stern_id)
        verzeichnis = self._reportverzeichnis(projekt_id, validierungslauf_id, k_stern_id)
        manifestpfad = verzeichnis / "manifest.json"
        if not manifestpfad.is_file():
            return None
        try:
            manifest = json.loads(manifestpfad.read_text(encoding="utf-8"))
            if (
                manifest.get("artefaktart") != "konzeptionelle_modellausgabe"
                or manifest.get("artefaktversion") != 1
                or manifest.get("projekt_id") != str(projekt_id)
                or manifest.get("validierungslauf_id") != str(validierungslauf_id)
                or manifest.get("k_stern_id") != str(k_stern_id)
            ):
                raise Importintegritaetsfehler("Das Reportmanifest ist inkonsistent.")
            geladen: dict[str, tuple[bytes | None, str | None]] = {}
            for formatname in ("html", "pdf"):
                eintrag = manifest.get("dateien", {}).get(formatname)
                if eintrag is None:
                    geladen[formatname] = (None, None)
                    continue
                artefaktname = str(eintrag["artefaktname"])
                if artefaktname != f"report.{formatname}":
                    raise Importintegritaetsfehler("Das Reportmanifest enthält einen Fremdpfad.")
                inhalt = (verzeichnis / artefaktname).read_bytes()
                if hashlib.sha256(inhalt).hexdigest() != eintrag["sha256"]:
                    raise Importintegritaetsfehler("Die Prüfsumme einer Reportdatei ist ungültig.")
                geladen[formatname] = (inhalt, str(eintrag["dateiname"]))
        except Importintegritaetsfehler:
            raise
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as fehler:
            raise Importintegritaetsfehler(
                "Die persistierte Modellausgabe ist ungültig."
            ) from fehler
        html_inhalt, html_name = geladen["html"]
        pdf_inhalt, pdf_name = geladen["pdf"]
        return StrukturierteModellausgabe(html_inhalt, html_name, pdf_inhalt, pdf_name)
