"""Professionelle XLSX-Ausgabe aus den gemeinsamen Reportdaten von Schritt 10."""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from framework_mvp.reporting.report_data import REPORT_DATA_VERSION

LOGGER = logging.getLogger(__name__)

SHEET_NAMES = (
    "Übersicht",
    "Problemstellung & Systemgrenze",
    "Zielsetzung & KPIs",
    "Prozessmodell",
    "Systemelemente & Merkmale",
    "Annahmen & offene Punkte",
    "Daten & Datenauswahl",
    "Analyseergebnisse",
    "Validierung",
    "Nachvollziehbarkeit",
)

NAVY = "17365D"
BLUE = "D9EAF7"
LIGHT_BLUE = "EEF5FA"
LIGHT_GRAY = "F2F2F2"
MID_GRAY = "A6A6A6"
WHITE = "FFFFFF"
GREEN = "E2F0D9"
YELLOW = "FFF2CC"
RED = "FCE4D6"
THIN_GRAY = Side(style="thin", color="D9E1F2")
FONT_FAMILY = "Calibri"


class XlsxRenderingFehler(RuntimeError):
    """Kennzeichnet eine nicht erzeugbare XLSX-Reportdatei."""


def _mapping(wert: Any) -> Mapping[str, Any]:
    return wert if isinstance(wert, Mapping) else {}


def _liste(wert: Any) -> list[Any]:
    if wert is None or wert == "":
        return []
    if isinstance(wert, list):
        return wert
    if isinstance(wert, tuple):
        return list(wert)
    return [wert]


def _label(name: Any) -> str:
    return str(name).replace("_", " ").strip().capitalize()


def _anzeige(wert: Any) -> str:
    """Formatiert strukturierte Werte lesbar, ohne JSON-Rohdump."""
    if wert is None or wert == "":
        return "Nicht im finalen Modell ausgewiesen"
    if isinstance(wert, bool):
        return "Ja" if wert else "Nein"
    if isinstance(wert, Mapping):
        if not wert:
            return "Nicht im finalen Modell ausgewiesen"
        return "\n".join(f"{_label(name)}: {_anzeige(inhalt)}" for name, inhalt in wert.items())
    if isinstance(wert, (list, tuple)):
        if not wert:
            return "Nicht im finalen Modell ausgewiesen"
        return "\n".join(f"• {_anzeige(inhalt)}" for inhalt in wert)
    return str(wert)


def _kurz(wert: Any, laenge: int = 240) -> str:
    text = _anzeige(wert).replace("\n", " ")
    return text if len(text) <= laenge else f"{text[: laenge - 1].rstrip()}…"


def _sheet_start(ws: Worksheet, titel: str, untertitel: str) -> int:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A5"
    ws.merge_cells("A1:H1")
    ws["A1"] = titel
    ws["A1"].font = Font(name=FONT_FAMILY, size=20, bold=True, color=NAVY)
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 30
    ws.merge_cells("A2:H2")
    ws["A2"] = untertitel
    ws["A2"].font = Font(name=FONT_FAMILY, size=12, color="666666")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 26
    for spalte in range(1, 9):
        ws.cell(3, spalte).border = Border(bottom=Side(style="medium", color=NAVY))
    if ws.sheet_properties.pageSetUpPr is not None:
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    if ws.sheet_properties.outlinePr is not None:
        ws.sheet_properties.outlinePr.summaryBelow = True
    return 5


def _abschnitt(ws: Worksheet, zeile: int, titel: str, breite: int = 8) -> int:
    ws.merge_cells(start_row=zeile, start_column=1, end_row=zeile, end_column=breite)
    zelle = ws.cell(zeile, 1, titel)
    zelle.fill = PatternFill("solid", fgColor=BLUE)
    zelle.font = Font(name=FONT_FAMILY, size=14, bold=True, color=NAVY)
    zelle.alignment = Alignment(vertical="center")
    ws.row_dimensions[zeile].height = 22
    return zeile + 1


def _paare(ws: Worksheet, zeile: int, paare: Iterable[tuple[str, Any]]) -> int:
    for bezeichnung, wert in paare:
        ws.cell(zeile, 1, bezeichnung)
        ws.cell(zeile, 1).font = Font(name=FONT_FAMILY, size=12, bold=True, color=NAVY)
        ws.merge_cells(start_row=zeile, start_column=2, end_row=zeile, end_column=8)
        ws.cell(zeile, 2, _anzeige(wert))
        for spalte in range(1, 9):
            zelle = ws.cell(zeile, spalte)
            zelle.alignment = Alignment(wrap_text=True, vertical="top")
            zelle.border = Border(bottom=THIN_GRAY)
        ws.row_dimensions[zeile].height = max(20, min(90, 15 * (_anzeige(wert).count("\n") + 1)))
        zeile += 1
    return zeile


def _status_fill(wert: Any) -> PatternFill | None:
    text = str(wert).casefold()
    if any(teil in text for teil in ("validiert", "berechnet", "übernommen", "bestaetigt")):
        return PatternFill("solid", fgColor=GREEN)
    if any(teil in text for teil in ("offen", "unsicher", "nicht berechenbar")):
        return PatternFill("solid", fgColor=YELLOW)
    if any(teil in text for teil in ("fehler", "ungültig", "abgelehnt")):
        return PatternFill("solid", fgColor=RED)
    return None


def _tabelle(
    ws: Worksheet,
    zeile: int,
    spalten: Sequence[tuple[str, str]],
    daten: Iterable[Mapping[str, Any]],
    *,
    autofilter: bool = False,
    zahlenformate: Mapping[str, str] | None = None,
) -> int:
    datenzeilen = list(daten)
    zahlenformate = zahlenformate or {}
    for index, (titel, _) in enumerate(spalten, 1):
        zelle = ws.cell(zeile, index, titel)
        zelle.fill = PatternFill("solid", fgColor=NAVY)
        zelle.font = Font(name=FONT_FAMILY, size=12, bold=True, color=WHITE)
        zelle.alignment = Alignment(wrap_text=True, vertical="center")
    kopfzeile = zeile
    zeile += 1
    if not datenzeilen:
        ws.merge_cells(start_row=zeile, start_column=1, end_row=zeile, end_column=len(spalten))
        ws.cell(zeile, 1, "Für dieses Projekt sind im finalen Modell keine Einträge vorhanden.")
        ws.cell(zeile, 1).font = Font(
            name=FONT_FAMILY, size=12, italic=True, color="666666"
        )
        zeile += 1
    else:
        for datensatz in datenzeilen:
            maximale_zeilen = 1
            for index, (_, schluessel) in enumerate(spalten, 1):
                rohwert = datensatz.get(schluessel)
                text = _anzeige(rohwert)
                zellenwert = (
                    rohwert
                    if schluessel in zahlenformate
                    and isinstance(rohwert, (int, float))
                    and not isinstance(rohwert, bool)
                    else text
                )
                zelle = ws.cell(zeile, index, zellenwert)
                zelle.font = Font(name=FONT_FAMILY, size=12)
                if schluessel in zahlenformate and isinstance(zellenwert, (int, float)):
                    zelle.number_format = zahlenformate[schluessel]
                zelle.alignment = Alignment(wrap_text=True, vertical="top")
                zelle.border = Border(bottom=THIN_GRAY)
                zeichen_pro_zeile = 24 if index == 1 else 30
                benoetigte_zeilen = sum(
                    max(1, math.ceil(len(abschnitt) / zeichen_pro_zeile))
                    for abschnitt in text.splitlines()
                )
                maximale_zeilen = max(maximale_zeilen, benoetigte_zeilen)
                if index == len(spalten):
                    fuellung = _status_fill(zelle.value)
                    if fuellung is not None:
                        zelle.fill = fuellung
            ws.row_dimensions[zeile].height = min(405, max(24, 14 * maximale_zeilen + 4))
            zeile += 1
    if autofilter and datenzeilen:
        ws.auto_filter.ref = f"A{kopfzeile}:{get_column_letter(len(spalten))}{zeile - 1}"
    return zeile


def _informationen(report: Mapping[str, Any], ids: set[str]) -> list[dict[str, Any]]:
    ergebnis: list[dict[str, Any]] = []
    for bestandteil in _liste(report.get("modellbestandteile")):
        if not isinstance(bestandteil, Mapping) or bestandteil.get("bestandteil_id") not in ids:
            continue
        for information in _liste(bestandteil.get("informationen")):
            if isinstance(information, Mapping):
                ergebnis.append(
                    {
                        "bestandteil": bestandteil.get("bezeichnung"),
                        "referenz": information.get("strukturreferenz"),
                        "wert": information.get("wert"),
                        "quelle": information.get("herkunftsartefakt"),
                        "status": bestandteil.get("validierungsstatus_anzeige"),
                    }
                )
    return ergebnis


def _statistikzeilen(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    daten = _mapping(report.get("daten"))
    zeitwahl = _mapping(daten.get("zeitbezogene_datenauswahl"))
    ergebnis: list[dict[str, Any]] = []

    def aufnehmen(art: str, bezug: str, statistik: Any) -> None:
        stats = _mapping(statistik)
        ergebnis.append(
            {
                "art": art,
                "bezug": bezug,
                "anzahl": stats.get("anzahl"),
                "mittelwert": stats.get("mittelwert_sekunden", stats.get("mittelwert")),
                "median": stats.get("median_sekunden", stats.get("median")),
                "minimum": stats.get("minimum_sekunden", stats.get("minimum")),
                "maximum": stats.get("maximum_sekunden", stats.get("maximum")),
                "einheit": stats.get("einheit", "Sekunden"),
            }
        )

    einzelwert = zeitwahl.get("zwischenankunftszeit")
    if isinstance(einzelwert, Mapping) and einzelwert:
        aufnehmen("Zwischenankunftszeit", "Gesamt", einzelwert.get("statistik", einzelwert))
    for eintrag in _liste(zeitwahl.get("zwischenankunftszeiten")):
        mapping = _mapping(eintrag)
        if not mapping:
            continue
        definition = _mapping(mapping.get("definition"))
        bezug = str(definition.get("bezeichnung") or mapping.get("bezeichnung") or "Gesamt")
        statistik = mapping.get("statistik")
        if isinstance(statistik, Mapping) and statistik:
            aufnehmen("Zwischenankunftszeit", bezug, statistik)
    for schluessel, titel in (
        ("bearbeitungszeiten", "Bearbeitungszeit"),
        ("ressourcenbezogene_bearbeitungszeiten", "Ressourcenbezogene Bearbeitungszeit"),
    ):
        for eintrag in _liste(zeitwahl.get(schluessel)):
            mapping = _mapping(eintrag)
            bezug = (
                " / ".join(
                    str(mapping.get(name))
                    for name in ("aktivitaet", "ressource")
                    if mapping.get(name) not in (None, "")
                )
                or "Gesamt"
            )
            aufnehmen(titel, bezug, mapping.get("statistik", mapping))
    for hinweis in _liste(_mapping(report.get("warteschlangen")).get("wartestellenhinweise")):
        mapping = _mapping(hinweis)
        uebergang = _mapping(mapping.get("uebergang"))
        ergebnis.append(
            {
                "art": "Wartezeit",
                "bezug": f"{uebergang.get('von', '')} → {uebergang.get('zu', '')}",
                "anzahl": mapping.get("anzahl"),
                "mittelwert": mapping.get("mittlere_wartezeit_sekunden"),
                "median": mapping.get("mediane_wartezeit_sekunden"),
                "minimum": None,
                "maximum": None,
                "einheit": "Sekunden",
            }
        )
    return ergebnis


def _svg_zu_png(svg: str) -> bytes | None:
    """Konvertiert SVG bevorzugt in-process, optional über vorhandenes rsvg-convert."""
    try:
        from cairosvg import svg2png  # type: ignore[import-not-found]

        return bytes(svg2png(bytestring=svg.encode("utf-8"), output_width=1800))
    except (ImportError, OSError, ValueError):
        programm = shutil.which("rsvg-convert")
        if programm is None:
            return None
        try:
            prozess = subprocess.run(
                [programm, "--format=png", "--width=1800"],
                input=svg.encode("utf-8"),
                capture_output=True,
                check=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return prozess.stdout or None


def _prozessbild(ws: Worksheet, zeile: int, report: Mapping[str, Any]) -> int:
    prozess = _mapping(report.get("prozessdarstellung"))
    svg = next(
        (
            wert
            for wert in (
                prozess.get("svg_inline"),
                prozess.get("dfg_svg_inline"),
                prozess.get("process_tree_svg_inline"),
            )
            if isinstance(wert, str) and wert.strip()
        ),
        None,
    )
    if svg is None:
        return _paare(ws, zeile, [("Visualisierung", "Keine Prozessgrafik im K*-Asset verfügbar.")])
    png = _svg_zu_png(svg)
    if png is None:
        LOGGER.warning(
            "Die Prozessgrafik konnte für die XLSX-Ausgabe nicht in PNG umgewandelt werden."
        )
        return _paare(
            ws,
            zeile,
            [("Visualisierung", "Die Prozessgrafik konnte nicht in Excel eingebettet werden.")],
        )
    try:
        bild = Image(BytesIO(png))
        verfuegbare_breite = sum(
            float(ws.column_dimensions[get_column_letter(index)].width or 13.0) * 7.0
            for index in range(1, 9)
        ) - 24.0
        faktor = min(1.0, verfuegbare_breite / bild.width, 720 / bild.height)
        bild.width = int(bild.width * faktor)
        bild.height = int(bild.height * faktor)
        ws.add_image(bild, f"A{zeile}")
        belegte_zeilen = max(10, int(bild.height / 20) + 2)
        for index in range(zeile, zeile + belegte_zeilen):
            ws.row_dimensions[index].height = 20
        return zeile + belegte_zeilen
    except (OSError, ValueError) as fehler:
        LOGGER.warning("Die PNG-Prozessgrafik konnte nicht eingebettet werden: %s", fehler)
        return _paare(
            ws,
            zeile,
            [("Visualisierung", "Die Prozessgrafik konnte nicht in Excel eingebettet werden.")],
        )


def _uebersicht(ws: Worksheet, report: Mapping[str, Any]) -> None:
    projekt = _mapping(report.get("projekt"))
    modell = _mapping(report.get("modell"))
    umfang = _mapping(report.get("modellumfang"))
    ziel = _mapping(report.get("zielsetzung"))
    validierung = _mapping(report.get("validierung"))
    dokument = _mapping(report.get("dokument"))
    zeile = _sheet_start(ws, SHEET_NAMES[0], "Management Summary des finalen K*")
    zeile = _abschnitt(ws, zeile, "Projekt und Modell")
    zeile = _paare(
        ws,
        zeile,
        (
            ("Projekt", projekt.get("bezeichnung") or dokument.get("titel")),
            ("Projekt-ID", projekt.get("projekt_id")),
            ("Systemtyp", umfang.get("systemtyp_anzeige") or umfang.get("systemtyp")),
            (
                "Systemgegenstand",
                umfang.get("bereich_aus_systemprofil")
                or _mapping(umfang.get("systemklassifikation")).get("bereich"),
            ),
            ("Problemstellung", _kurz(_mapping(report.get("problemstellung")).get("text"), 400)),
            ("Zielsetzung", ziel.get("individuelles_ziel") or ziel.get("untersuchungszwecke")),
            ("Validierungsstatus", validierung.get("status_anzeige")),
            ("Modellstand", modell.get("erstellt_am")),
            ("Framework-Version", dokument.get("softwareversion")),
        ),
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Wichtigste Modellbestandteile")
    ressourcen = _mapping(report.get("ressourcen"))
    zusammenfassung = [
        {
            "kategorie": "Entitäten/Objekte",
            "inhalt": _mapping(report.get("entitaeten")).get("objekte_gueter"),
        },
        {
            "kategorie": "Ressourcen",
            "inhalt": ressourcen.get("event_log_ressourcen") or ressourcen.get("systemressourcen"),
        },
        {
            "kategorie": "Aktivitäten",
            "inhalt": _mapping(report.get("aktivitaeten")).get("sichtbare_aktivitaeten"),
        },
        {
            "kategorie": "Warteschlangen",
            "inhalt": _mapping(report.get("warteschlangen")).get("wartestellenhinweise"),
        },
        {
            "kategorie": "Zustände",
            "inhalt": [
                wert.get("wert")
                for wert in _informationen(report, {"entitaeten", "aktivitaeten"})
                if "zustand" in str(wert.get("referenz", "")).casefold()
            ],
        },
        {
            "kategorie": "Attribute/Variablen",
            "inhalt": {
                "Fallattribut": _mapping(report.get("entitaeten")).get("kanonisches_fallattribut"),
                "Ressourcenattribut": ressourcen.get("ressourcenattribut"),
            },
        },
        {
            "kategorie": "Prozesssteuerung/Logik",
            "inhalt": _mapping(report.get("annahmen")).get("modellierungsentscheidungen"),
        },
        {
            "kategorie": "Eingaben",
            "inhalt": [wert.get("wert") for wert in _informationen(report, {"eingaben"})],
        },
        {
            "kategorie": "Ausgaben",
            "inhalt": _mapping(report.get("ausgaben_und_eingaben")).get("ausgewaehlte_kpis"),
        },
        {
            "kategorie": "Annahmen",
            "inhalt": _mapping(report.get("annahmen")).get("schwellwert_auswirkung"),
        },
    ]
    zeile = _tabelle(
        ws,
        zeile,
        (("Kategorie", "kategorie"), ("Finaler Inhalt", "inhalt")),
        zusammenfassung,
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Navigation")
    for ziel in SHEET_NAMES[1:]:
        ws.merge_cells(start_row=zeile, start_column=1, end_row=zeile, end_column=3)
        zelle = ws.cell(zeile, 1, ziel)
        zelle.hyperlink = f"#'{ziel}'!A1"
        zelle.style = "Hyperlink"
        zeile += 1
    ws.column_dimensions["A"].width = 28
    for spalte in range(2, 9):
        ws.column_dimensions[get_column_letter(spalte)].width = 16


def _problem_und_grenze(ws: Worksheet, report: Mapping[str, Any]) -> None:
    problem = _mapping(report.get("problemstellung"))
    umfang = _mapping(report.get("modellumfang"))
    zeile = _sheet_start(ws, SHEET_NAMES[1], "Fachlicher Auftrag und Abgrenzung")
    zeile = _abschnitt(ws, zeile, "Problemstellung")
    zeile = _paare(ws, zeile, (("Problem", problem.get("text")),))
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Systemgrenze und Umfang")
    zeile = _paare(
        ws,
        zeile,
        (
            ("Systemgrenze", umfang.get("systemgrenze")),
            ("Modellumfang", umfang.get("sichtbare_aktivitaeten")),
            ("Detaillierungsgrad", umfang.get("detaillierungsgrad")),
            ("Einbezogener Bereich", umfang.get("bereich_aus_systemprofil")),
            ("Systemklassifikation", umfang.get("systemklassifikation")),
        ),
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Start- und Endaktivitäten")
    _tabelle(
        ws,
        zeile,
        (("Typ", "typ"), ("Aktivität", "aktivitaet"), ("Häufigkeit", "haeufigkeit")),
        [
            {"typ": typ, **dict(eintrag)}
            for typ, schluessel in (("Start", "startaktivitaeten"), ("Ende", "endaktivitaeten"))
            for eintrag in _liste(umfang.get(schluessel))
            if isinstance(eintrag, Mapping)
        ],
        zahlenformate={"haeufigkeit": "#,##0"},
    )


def _ziele(ws: Worksheet, report: Mapping[str, Any]) -> None:
    ziel = _mapping(report.get("zielsetzung"))
    ausgaben = _mapping(report.get("ausgaben_und_eingaben"))
    zeile = _sheet_start(ws, SHEET_NAMES[2], "Ziele, Zielgrößen und Kennzahlen")
    zeile = _abschnitt(ws, zeile, "Zielbild")
    zeile = _paare(
        ws,
        zeile,
        (
            ("Untersuchungszwecke", ziel.get("untersuchungszwecke")),
            ("Individuelles Ziel", ziel.get("individuelles_ziel")),
            ("Logistische Zielgrößen", ziel.get("logistische_zielgroessen")),
        ),
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Ausgewählte KPIs und Ergebnisse")
    kpis = [
        dict(wert) for wert in _liste(ausgaben.get("kpi_ergebnisse")) if isinstance(wert, Mapping)
    ]
    vorhandene = {str(wert.get("kpi_id")) for wert in kpis}
    kpis.extend(
        {
            "kpi_id": wert.get("id"),
            "bezeichnung": wert.get("bezeichnung"),
            "status_anzeige": "Ausgewählt",
            "ergebnis": None,
            "einheit": None,
            "formel": None,
            "bezugsmenge": None,
        }
        for wert in _liste(ausgaben.get("ausgewaehlte_kpis"))
        if isinstance(wert, Mapping) and str(wert.get("id")) not in vorhandene
    )
    for kpi in kpis:
        if not isinstance(kpi.get("ergebnis"), (int, float)):
            kpi["ergebnis"] = kpi.get("ergebnis_anzeige")
    _tabelle(
        ws,
        zeile,
        (
            ("KPI-ID", "kpi_id"),
            ("Bezeichnung", "bezeichnung"),
            ("Ergebnis", "ergebnis"),
            ("Einheit", "einheit"),
            ("Bezugsmenge", "bezugsmenge"),
            ("Berechnungslogik", "formel"),
            ("Status", "status_anzeige"),
        ),
        kpis,
        autofilter=True,
        zahlenformate={"ergebnis": "0.00"},
    )


def _prozess(ws: Worksheet, report: Mapping[str, Any]) -> None:
    prozess = _mapping(report.get("prozessdarstellung"))
    annahmen = _mapping(report.get("annahmen"))
    zeile = _sheet_start(
        ws, SHEET_NAMES[3], "Eingebettete Visualisierung des finalen Prozessmodells"
    )
    zeile = _abschnitt(ws, zeile, "Modell und Mining-Parameter")
    zeile = _paare(
        ws,
        zeile,
        (
            (
                "Notation",
                prozess.get("notation_anzeige") or annahmen.get("prozessnotation_anzeige"),
            ),
            ("Prozessmodell-ID", prozess.get("prozessmodell_id")),
            ("Process-Mining-Analyse-ID", prozess.get("process_mining_analyse_id")),
            ("Modellierungsentscheidungen", annahmen.get("modellierungsentscheidungen")),
            ("Schwellwert-Auswirkung", annahmen.get("schwellwert_auswirkung")),
        ),
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Prozessvisualisierung")
    ws.column_dimensions["A"].width = 30
    for spalte in range(2, 9):
        ws.column_dimensions[get_column_letter(spalte)].width = 24
    _prozessbild(ws, zeile, report)
    ws.sheet_view.zoomScale = 80


def _systemelemente(ws: Worksheet, report: Mapping[str, Any]) -> None:
    zeile = _sheet_start(
        ws, SHEET_NAMES[4], "Finale Entitäten, Aktivitäten, Ressourcen und Merkmale"
    )
    zeile = _abschnitt(ws, zeile, "Strukturierte Modellinhalte")
    entitaeten = _mapping(report.get("entitaeten"))
    aktivitaeten = _mapping(report.get("aktivitaeten"))
    ressourcen = _mapping(report.get("ressourcen"))
    warteschlangen = _mapping(report.get("warteschlangen"))
    daten: list[dict[str, Any]] = []

    def ergaenzen(kategorie: str, werte: Any, *, ursprung: str) -> None:
        for wert in _liste(werte):
            daten.append(
                {
                    "kategorie": kategorie,
                    "element": _kurz(wert, 500),
                    "typ": kategorie,
                    "beschreibung": _kurz(wert, 500),
                    "ursprung": ursprung,
                    "eigenschaften": None,
                    "status": "Fachlich validiert",
                }
            )

    ergaenzen("Entität/Objekt", entitaeten.get("objekte_gueter"), ursprung="Systemprofil")
    ergaenzen(
        "Aktivität",
        aktivitaeten.get("sichtbare_aktivitaeten"),
        ursprung="Finales Prozessmodell",
    )
    ergaenzen(
        "Ressource",
        ressourcen.get("event_log_ressourcen") or ressourcen.get("systemressourcen"),
        ursprung=ressourcen.get("zuordnungsherkunft") or "Ressourcenanalyse",
    )
    ergaenzen(
        "Warteschlange/Wartepunkt",
        warteschlangen.get("wartestellenhinweise"),
        ursprung="Zeitbezogene Analyse",
    )
    for bezeichnung, wert, ursprung in (
        ("Fallattribut", entitaeten.get("kanonisches_fallattribut"), "Event-Log-Schema"),
        ("Ressourcenattribut", ressourcen.get("ressourcenattribut"), "Event-Log-Schema"),
    ):
        if wert not in (None, ""):
            daten.append(
                {
                    "kategorie": "Attribut/Variable",
                    "element": bezeichnung,
                    "typ": "Attribut",
                    "beschreibung": wert,
                    "ursprung": ursprung,
                    "eigenschaften": None,
                    "status": "Fachlich validiert",
                }
            )
    for eintrag in _informationen(report, {"eingaben"}):
        daten.append(
            {
                "kategorie": "Eingabe",
                "element": eintrag.get("referenz"),
                "typ": "Eingabe",
                "beschreibung": _kurz(eintrag.get("wert"), 300),
                "ursprung": eintrag.get("quelle"),
                "eigenschaften": None,
                "status": eintrag.get("status"),
            }
        )
    ausgaben = _mapping(report.get("ausgaben_und_eingaben"))
    for kpi in _liste(ausgaben.get("kpi_ergebnisse")):
        mapping = _mapping(kpi)
        daten.append(
            {
                "kategorie": "Ausgabe/KPI",
                "element": mapping.get("bezeichnung") or mapping.get("kpi_id"),
                "typ": "Kennzahl",
                "beschreibung": mapping.get("ergebnis_anzeige"),
                "ursprung": "Ergebnisaggregation",
                "eigenschaften": {
                    "Formel": mapping.get("formel"),
                    "Bezugsmenge": mapping.get("bezugsmenge"),
                },
                "status": mapping.get("status_anzeige"),
            }
        )
    _tabelle(
        ws,
        zeile,
        (
            ("Kategorie", "kategorie"),
            ("Element/Merkmal", "element"),
            ("Typ", "typ"),
            ("Beschreibung", "beschreibung"),
            ("Ursprung", "ursprung"),
            ("Eigenschaften", "eigenschaften"),
            ("Status", "status"),
        ),
        daten,
        autofilter=True,
    )


def _annahmen(ws: Worksheet, report: Mapping[str, Any]) -> None:
    annahmen = _mapping(report.get("annahmen"))
    zeile = _sheet_start(ws, SHEET_NAMES[5], "Annahmen, Vereinfachungen und fachliche Restpunkte")
    zeile = _abschnitt(ws, zeile, "Modellierungsannahmen")
    zeile = _paare(
        ws,
        zeile,
        (
            ("Modellierungsentscheidungen", annahmen.get("modellierungsentscheidungen")),
            ("Prozessnotation", annahmen.get("prozessnotation_anzeige")),
            ("Schwellwert-Auswirkung", annahmen.get("schwellwert_auswirkung")),
        ),
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Fachliche Entscheidungen, Anpassungen und offene Punkte")
    entscheidungen: list[dict[str, Any]] = []
    for bestandteil in _liste(report.get("modellbestandteile")):
        if not isinstance(bestandteil, Mapping):
            continue
        for typ, schluessel in (
            ("Entscheidung", "fachliche_entscheidungen"),
            ("Anpassung", "fachliche_anpassungen"),
        ):
            for eintrag in _liste(bestandteil.get(schluessel)):
                mapping = _mapping(eintrag)
                entscheidungen.append(
                    {
                        "bestandteil": bestandteil.get("bezeichnung"),
                        "typ": typ,
                        "inhalt": mapping.get("fachlicher_inhalt")
                        or mapping.get("entscheidung")
                        or mapping,
                        "begruendung": mapping.get("begruendung"),
                        "status": bestandteil.get("validierungsstatus_anzeige"),
                    }
                )
    _tabelle(
        ws,
        zeile,
        (
            ("Bestandteil", "bestandteil"),
            ("Typ", "typ"),
            ("Inhalt", "inhalt"),
            ("Begründung", "begruendung"),
            ("Status", "status"),
        ),
        entscheidungen,
        autofilter=True,
    )


def _daten(ws: Worksheet, report: Mapping[str, Any]) -> None:
    daten = _mapping(report.get("daten"))
    zeile = _sheet_start(ws, SHEET_NAMES[6], "Datenbasis und zeitbezogene Datenauswahl")
    zeile = _abschnitt(ws, zeile, "Datenquellen und Datenartefakte")
    zeile = _paare(
        ws,
        zeile,
        (
            ("Datenquellen", daten.get("datenquellen")),
            ("Zwischendatensatz", daten.get("zwischendatensatz")),
            ("Event Log", daten.get("event_log")),
        ),
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Datenprofile")
    zeile = _tabelle(
        ws,
        zeile,
        (
            ("Import-ID", "import_id"),
            ("Zeilen", "zeilenanzahl"),
            ("Spalten", "spaltenanzahl"),
            ("Fehlwerte", "echte_fehlwerte"),
            ("Platzhalter", "textuelle_platzhalter"),
            ("Duplikate", "exakte_duplikate"),
            ("Profil-Prüfsumme", "profil_sha256"),
        ),
        [dict(wert) for wert in _liste(daten.get("profile")) if isinstance(wert, Mapping)],
        zahlenformate={
            "zeilenanzahl": "#,##0",
            "spaltenanzahl": "#,##0",
            "echte_fehlwerte": "#,##0",
            "textuelle_platzhalter": "#,##0",
            "exakte_duplikate": "#,##0",
        },
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Zeitbezogene Kennwerte")
    statistikzeilen = _statistikzeilen(report)
    statistikspalten: list[tuple[str, str]] = [
        ("Kennwert", "art"),
        ("Bezug", "bezug"),
        ("Anzahl", "anzahl"),
        ("Mittelwert", "mittelwert"),
        ("Median", "median"),
    ]
    if any(wert.get("minimum") not in (None, "") for wert in statistikzeilen):
        statistikspalten.append(("Minimum", "minimum"))
    if any(wert.get("maximum") not in (None, "") for wert in statistikzeilen):
        statistikspalten.append(("Maximum", "maximum"))
    statistikspalten.append(("Einheit", "einheit"))
    _tabelle(
        ws,
        zeile,
        tuple(statistikspalten),
        statistikzeilen,
        autofilter=True,
        zahlenformate={
            "anzahl": "#,##0",
            "mittelwert": "0.00",
            "median": "0.00",
            "minimum": "0.00",
            "maximum": "0.00",
        },
    )


def _analyse(ws: Worksheet, report: Mapping[str, Any]) -> None:
    prozess = _mapping(report.get("prozessdarstellung"))
    ausgaben = _mapping(report.get("ausgaben_und_eingaben"))
    ressourcen = _mapping(report.get("ressourcen"))
    warteschlangen = _mapping(report.get("warteschlangen"))
    zeile = _sheet_start(
        ws, SHEET_NAMES[7], "Process Mining, Conformance, Zeit- und Ressourcenbefunde"
    )
    zeile = _abschnitt(ws, zeile, "Process Discovery und Conformance")
    zeile = _paare(
        ws,
        zeile,
        (
            ("Analyse-ID", prozess.get("process_mining_analyse_id")),
            ("Notation", prozess.get("notation_anzeige")),
            ("Verfügbare Visualisierungen", prozess.get("assets")),
            (
                "Relevante Analysebefunde",
                [
                    wert.get("wert")
                    for wert in _informationen(
                        report, {"annahmen", "darstellung_der_vorgaenge_des_systems"}
                    )
                ],
            ),
        ),
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Kennzahlen- und Ressourcenbefunde")
    kpi_zeilen = [
        dict(wert)
        for wert in (
            _liste(ausgaben.get("kpi_ergebnisse"))
            + _liste(warteschlangen.get("wartezeit_kpis"))
            + _liste(ressourcen.get("ressourcenbezogene_kpis"))
        )
        if isinstance(wert, Mapping)
    ]
    for kpi in kpi_zeilen:
        if not isinstance(kpi.get("ergebnis"), (int, float)):
            kpi["ergebnis"] = kpi.get("ergebnis_anzeige")
    zeile = _tabelle(
        ws,
        zeile,
        (
            ("KPI", "bezeichnung"),
            ("Ergebnis", "ergebnis"),
            ("Formel", "formel"),
            ("Bezugsmenge", "bezugsmenge"),
            ("Status", "status_anzeige"),
        ),
        kpi_zeilen,
        autofilter=True,
        zahlenformate={"ergebnis": "0.00"},
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Aktivitäts-/Ressourcenzuordnung")
    _tabelle(
        ws,
        zeile,
        (
            ("Aktivität", "aktivitaet"),
            ("Ressourcen", "ressourcen"),
            ("Modus", "modus"),
            ("Herkunft", "herkunft"),
        ),
        [
            dict(wert)
            for wert in _liste(ressourcen.get("aktivitaet_ressourcen"))
            if isinstance(wert, Mapping)
        ],
    )


def _validierung(ws: Worksheet, report: Mapping[str, Any]) -> None:
    validierung = _mapping(report.get("validierung"))
    zeile = _sheet_start(
        ws, SHEET_NAMES[8], "Vorschlag, finale Fassung und Validierungsentscheidung"
    )
    zeile = _abschnitt(ws, zeile, "Gesamtvalidierung")
    zeile = _paare(
        ws,
        zeile,
        (
            ("Status", validierung.get("status_anzeige")),
            ("Validierungsvermerk", validierung.get("validierungsvermerk")),
            ("Menschlich bestätigt", validierung.get("menschlich_bestaetigt")),
        ),
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Bestandteile im Vorher-/Nachher-Vergleich")
    vergleich = []
    for bestandteil in _liste(report.get("modellbestandteile")):
        if not isinstance(bestandteil, Mapping):
            continue
        original = [
            wert.get("wert")
            for wert in _liste(bestandteil.get("informationen"))
            if isinstance(wert, Mapping)
        ]
        anpassungen = bestandteil.get("fachliche_anpassungen")
        vergleich.append(
            {
                "bestandteil": bestandteil.get("bezeichnung"),
                "vorschlag": _kurz(original, 800),
                "final": _kurz([*original, *_liste(anpassungen)], 800),
                "entscheidung": _kurz(bestandteil.get("fachliche_entscheidungen"), 500),
                "geaendert": bool(_liste(anpassungen)),
                "status": bestandteil.get("validierungsstatus_anzeige"),
            }
        )
    _tabelle(
        ws,
        zeile,
        (
            ("Bestandteil", "bestandteil"),
            ("Vorgeschlagener Inhalt", "vorschlag"),
            ("Finaler Inhalt", "final"),
            ("Entscheidung/Begründung", "entscheidung"),
            ("Geändert", "geaendert"),
            ("Status", "status"),
        ),
        vergleich,
        autofilter=True,
    )


def _lineage(ws: Worksheet, report: Mapping[str, Any]) -> None:
    projekt = _mapping(report.get("projekt"))
    modell = _mapping(report.get("modell"))
    prozess = _mapping(report.get("prozessdarstellung"))
    lineage = _mapping(report.get("lineage"))
    dokument = _mapping(report.get("dokument"))
    zeile = _sheet_start(ws, SHEET_NAMES[9], "IDs, Referenzen, Prüfsummen und Artefaktherkunft")
    zeile = _abschnitt(ws, zeile, "Modellreferenzen")
    zeile = _paare(
        ws,
        zeile,
        (
            ("Projekt-ID", projekt.get("projekt_id")),
            ("K*-ID", modell.get("k_stern_id")),
            ("Validierungslauf-ID", modell.get("validierungslauf_id")),
            ("Prozessmodell-ID", prozess.get("prozessmodell_id")),
            ("Analyse-ID", prozess.get("process_mining_analyse_id")),
            ("K-Referenz", lineage.get("k_referenz")),
            ("O-Referenz", lineage.get("o_referenz")),
            ("Eingabefingerabdruck", lineage.get("eingabefingerabdruck")),
            ("Entscheidungsfingerabdruck", lineage.get("entscheidungsfingerabdruck")),
            ("Gesamtprüfsumme", lineage.get("gesamtpruefsumme")),
            ("Framework-Version", dokument.get("softwareversion")),
        ),
    )
    zeile += 1
    zeile = _abschnitt(ws, zeile, "Informationsherkunft")
    _tabelle(
        ws,
        zeile,
        (
            ("Bestandteil", "bestandteil_id"),
            ("Informations-ID", "informations_id"),
            ("Strukturreferenz", "strukturreferenz"),
            ("Herkunftsartefakt", "herkunftsartefakt"),
            ("Artefakt-ID", "herkunftsartefakt_id"),
            ("Prüfsumme", "herkunftsartefakt_sha256"),
            ("Übernahmeart", "uebernahmeart"),
        ),
        [dict(wert) for wert in _liste(lineage.get("informationen")) if isinstance(wert, Mapping)],
        autofilter=True,
    )


def _arbeitsmappe_finalisieren(arbeitsmappe: Workbook) -> None:
    breite_grenzen: dict[str, dict[str, float]] = {
        SHEET_NAMES[0]: {"B": 72},
        SHEET_NAMES[1]: {"B": 82, "D": 48},
        SHEET_NAMES[2]: {"B": 48, "E": 34, "F": 62},
        SHEET_NAMES[4]: {"B": 42, "D": 62, "E": 42, "F": 54},
        SHEET_NAMES[5]: {"C": 62, "D": 62},
        SHEET_NAMES[6]: {"A": 32, "B": 48, "G": 45},
        SHEET_NAMES[7]: {"A": 38, "C": 55, "D": 42},
        SHEET_NAMES[8]: {"B": 62, "C": 62, "D": 54},
        SHEET_NAMES[9]: {"C": 54, "D": 38, "E": 42, "F": 45},
    }
    for ws in arbeitsmappe.worksheets:
        if ws.sheet_properties.pageSetUpPr is not None:
            ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_margins.left = 0.25
        ws.page_margins.right = 0.25
        ws.page_margins.top = 0.5
        ws.page_margins.bottom = 0.5
        ws.print_options.horizontalCentered = False
        if ws.max_column > 5:
            ws.page_setup.orientation = "landscape"
        for spalte in range(1, max(8, ws.max_column) + 1):
            buchstabe = get_column_letter(spalte)
            if ws.title == SHEET_NAMES[3]:
                continue
            inhaltslaengen = []
            for zelle in (ws.cell(zeile, spalte) for zeile in range(4, ws.max_row + 1)):
                if zelle.value is None or zelle.coordinate in ws.merged_cells:
                    continue
                inhaltslaengen.extend(len(teil) for teil in str(zelle.value).splitlines())
            minimum = 14.0 if spalte > 1 else 20.0
            maximum = breite_grenzen.get(ws.title, {}).get(buchstabe, 36.0)
            passend = max(inhaltslaengen, default=int(minimum)) + 2
            ws.column_dimensions[buchstabe].width = min(maximum, max(minimum, passend))
        for zeile in ws.iter_rows():
            for zelle in zeile:
                if zelle.value is not None:
                    bestehend = zelle.font
                    zelle.font = Font(
                        name=FONT_FAMILY,
                        size=bestehend.sz or 12,
                        bold=bestehend.bold,
                        italic=bestehend.italic,
                        color=bestehend.color,
                        underline=bestehend.underline,
                    )
                if zelle.value is not None and zelle.alignment == Alignment():
                    zelle.alignment = Alignment(wrap_text=True, vertical="top")


def render_report_xlsx(report_data: Mapping[str, Any]) -> bytes:
    """Rendert die gemeinsamen, bereits aufgelösten Reportdaten als XLSX-Bytes."""
    if report_data.get("report_data_version") != REPORT_DATA_VERSION:
        raise XlsxRenderingFehler(
            f"Nicht unterstützte Report-Datenversion: {report_data.get('report_data_version')!r}."
        )
    try:
        arbeitsmappe = Workbook()
        standardblatt = arbeitsmappe.active
        if standardblatt is not None:
            arbeitsmappe.remove(standardblatt)
        funktionen = (
            _uebersicht,
            _problem_und_grenze,
            _ziele,
            _prozess,
            _systemelemente,
            _annahmen,
            _daten,
            _analyse,
            _validierung,
            _lineage,
        )
        for name, funktion in zip(SHEET_NAMES, funktionen, strict=True):
            funktion(arbeitsmappe.create_sheet(name), report_data)
        _arbeitsmappe_finalisieren(arbeitsmappe)
        ziel = BytesIO()
        arbeitsmappe.save(ziel)
        return ziel.getvalue()
    except XlsxRenderingFehler:
        raise
    except (OSError, TypeError, ValueError, KeyError) as fehler:
        raise XlsxRenderingFehler(
            f"Die XLSX-Arbeitsmappe konnte nicht erzeugt werden: {fehler}"
        ) from fehler
