"""Auflösung optionaler Report-Assets aus persistierten Frameworkartefakten."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID


class ReportAssetFehler(RuntimeError):
    """Kennzeichnet ungültige oder nicht lesbare Report-Assets."""


def _uuid_text(wert: Any, feld: str) -> str | None:
    """Validiert technische IDs, bevor daraus Dateipfade gebildet werden."""
    if wert is None or wert == "":
        return None

    try:
        return str(UUID(str(wert)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ReportAssetFehler(
            f"Ungültige UUID in '{feld}': {wert!r}."
        ) from exc


def _svg_fragment(pfad: Path) -> str | None:
    """Liest ein vorhandenes SVG und liefert nur das eigentliche <svg>-Element."""
    if not pfad.is_file():
        return None

    try:
        text = pfad.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReportAssetFehler(
            f"SVG konnte nicht gelesen werden: {pfad}"
        ) from exc

    start = text.find("<svg")
    ende = text.rfind("</svg>")

    if start < 0 or ende < 0:
        raise ReportAssetFehler(
            f"Datei enthält kein gültiges SVG-Element: {pfad}"
        )

    ende += len("</svg>")
    return text[start:ende]


def resolve_report_assets(
    report_data: Mapping[str, Any],
    *,
    workspace_root: str | Path = "workspace",
) -> dict[str, Any]:
    """Ergänzt Reportdaten um vorhandene SVG-Visualisierungen.

    Fehlende optionale SVGs führen nicht zum Abbruch. Vorhandene, aber
    ungültige SVG-Dateien werden dagegen als Fehler behandelt.
    """
    ergebnis = copy.deepcopy(dict(report_data))

    projekt = ergebnis.get("projekt")
    prozess = ergebnis.get("prozessdarstellung")

    if not isinstance(projekt, dict):
        raise ReportAssetFehler(
            "Reportdaten enthalten keinen gültigen Projektbereich."
        )

    if not isinstance(prozess, dict):
        raise ReportAssetFehler(
            "Reportdaten enthalten keine gültige Prozessdarstellung."
        )

    # Schlüssel werden immer bereitgestellt, damit das Template stabil bleibt.
    prozess["svg_inline"] = None
    prozess["dfg_svg_inline"] = None
    prozess["process_tree_svg_inline"] = None

    projekt_id = _uuid_text(
        projekt.get("projekt_id"),
        "projekt.projekt_id",
    )
    analyse_id = _uuid_text(
        prozess.get("process_mining_analyse_id"),
        "prozessdarstellung.process_mining_analyse_id",
    )

    if projekt_id is None or analyse_id is None:
        prozess["assets"] = {
            "modell_svg": False,
            "dfg_svg": False,
            "process_tree_svg": False,
        }
        return ergebnis

    wurzel = Path(workspace_root).resolve()

    analyseordner = (
        wurzel
        / "projects"
        / projekt_id
        / "process_mining"
    )

    modell_svg = analyseordner / f"{analyse_id}.model.svg"
    dfg_svg = analyseordner / f"{analyse_id}.dfg.svg"
    process_tree_svg = analyseordner / f"{analyse_id}.process-tree.svg"

    prozess["svg_inline"] = _svg_fragment(modell_svg)
    prozess["dfg_svg_inline"] = _svg_fragment(dfg_svg)
    prozess["process_tree_svg_inline"] = _svg_fragment(process_tree_svg)

    prozess["assets"] = {
        "modell_svg": modell_svg.is_file(),
        "dfg_svg": dfg_svg.is_file(),
        "process_tree_svg": process_tree_svg.is_file(),
    }

    return ergebnis