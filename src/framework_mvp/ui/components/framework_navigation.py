"""Programmatisch erzeugte SVG-Navigation des zehnstufigen Frameworks."""

from collections.abc import Collection
from html import escape

import streamlit as st

SCHRITTNAMEN = (
    "Datenquelle identifizieren",
    "ETL durchführen",
    "Semantisches Mapping",
    "Event Log aufbauen",
    "Datenqualität prüfen",
    "Process Mining durchführen",
    "Ergebnisse aggregieren",
    "Modellbestandteile ableiten",
    "Modell ergänzen und validieren",
    "Konzeptionelles Modell ausgeben",
)

_TEXTZEILEN = (
    ("Datenquelle identifizieren",),
    ("ETL durchführen",),
    ("Semantisches Mapping",),
    ("Event Log aufbauen",),
    ("Datenqualität prüfen",),
    ("Process Mining durchführen",),
    ("Ergebnisse aggregieren",),
    ("Modellbestandteile ableiten",),
    ("Modell ergänzen", "und validieren"),
    ("Konzeptionelles Modell", "ausgeben"),
)

_POSITIONEN = {
    1: (10, 15),
    2: (230, 15),
    3: (450, 15),
    4: (670, 15),
    5: (670, 125),
    6: (450, 125),
    7: (230, 125),
    8: (10, 125),
    9: (10, 235),
    10: (230, 235),
}

_PFEILE = (
    (210, 50, 220, 50),
    (430, 50, 440, 50),
    (650, 50, 660, 50),
    (770, 85, 770, 115),
    (670, 160, 660, 160),
    (450, 160, 440, 160),
    (230, 160, 220, 160),
    (110, 195, 110, 225),
    (210, 270, 220, 270),
)


def erstelle_framework_svg(current_step: int, completed_steps: Collection[int] = ()) -> str:
    """Erzeugt ein vollständiges responsives SVG der zehn Framework-Schritte."""
    if current_step not in range(1, 11):
        raise ValueError("Der aktuelle Framework-Schritt muss zwischen 1 und 10 liegen.")
    abgeschlossene = set(completed_steps)
    if not abgeschlossene.issubset(range(1, 11)):
        raise ValueError("Abgeschlossene Framework-Schritte müssen zwischen 1 und 10 liegen.")

    teile = [
        '<svg viewBox="0 0 880 320" width="100%" role="img" '
        'aria-label="Zehnstufiges Framework" preserveAspectRatio="xMinYMin meet">',
        '<defs><marker id="framework-pfeil" markerWidth="7" markerHeight="7" '
        'refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" '
        'fill="#64748b"/></marker></defs>',
    ]
    for x1, y1, x2, y2 in _PFEILE:
        teile.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            'stroke="#64748b" stroke-width="3" marker-end="url(#framework-pfeil)"/>'
        )
    for schritt, (name, zeilen) in enumerate(zip(SCHRITTNAMEN, _TEXTZEILEN, strict=True), 1):
        x, y = _POSITIONEN[schritt]
        if schritt == current_step:
            fuellung, rand, textfarbe, status = "#2563eb", "#1d4ed8", "#ffffff", "aktuell"
        elif schritt in abgeschlossene:
            fuellung, rand, textfarbe, status = "#dcfce7", "#16a34a", "#166534", "abgeschlossen"
        else:
            fuellung, rand, textfarbe, status = "#f1f5f9", "#cbd5e1", "#475569", "zukünftig"
        teile.extend(
            (
                f'<g data-step="{schritt}" data-status="{status}"><title>{escape(name)}</title>',
                f'<rect x="{x}" y="{y}" width="200" height="70" rx="9" '
                f'fill="{fuellung}" stroke="{rand}" stroke-width="3"/>',
                f'<text x="{x + 10}" y="{y + 23}" fill="{textfarbe}" '
                f'font-size="14" font-weight="700">{schritt}</text>',
                f'<text x="{x + 32}" y="{y + 23}" fill="{textfarbe}" font-size="12">',
            )
        )
        for index, zeile in enumerate(zeilen):
            dy = "0" if index == 0 else "18"
            x_wert = x + 32 if index == 0 else x + 32
            teile.append(f'<tspan x="{x_wert}" dy="{dy}">{escape(zeile)}</tspan>')
        teile.extend(("</text>", "</g>"))
    teile.append("</svg>")
    return "".join(teile)


def zeige_framework_navigation(
    current_step: int,
    completed_steps: Collection[int] = (),
    *,
    mit_grosser_ansicht: bool = True,
) -> None:
    """Zeigt die kompakte und optional eine größere Framework-Grafik."""
    svg = erstelle_framework_svg(current_step, completed_steps)
    st.markdown(svg, unsafe_allow_html=True)
    if mit_grosser_ansicht:
        with st.expander("Framework-Grafik größer anzeigen"):
            st.markdown(svg, unsafe_allow_html=True)
