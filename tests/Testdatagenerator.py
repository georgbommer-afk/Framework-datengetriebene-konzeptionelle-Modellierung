#!/usr/bin/env python3
"""
Einfacher Generator für produktionsnahe Event-Log-Testdaten.

Benutzerseitig werden nur drei Parameter eingestellt:
- Zeilenanzahl: Anzahl der Datenzeilen/Ereignisse (Header nicht mitgezählt)
- Ausreißeranteil: Anteil zeitlicher Ausreißer in Prozent
- Platzhalter gesamt: absolute Anzahl textueller Platzhalterzellen

Der erzeugte Datensatz ist bereits semantisch vorkonfiguriert und enthält die
kanonischen Mindestspalten case_id, activity und timestamp. Zusätzlich werden
Ressourcen sowie Ist-/Soll-Start- und Endzeitpunkte ausgegeben.

Beispiel:
    python testdatensatz_generator_v2.py \
        --zeilen 10000 \
        --ausreisseranteil 1.0 \
        --platzhalter 100

Ausgabe:
    Testdatensatz_Produktion.xlsx
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

# -----------------------------------------------------------------------------
# Feste interne Generatorparameter
# -----------------------------------------------------------------------------

AUSGABEDATEI = Path(
    "/Users/georgbommer/MasterarbeitGithubRepo/tests/datasets/Testdatensatz_Produktion.xlsx"
)
SEED = 20260811
STARTZEITPUNKT = datetime(2026, 7, 1, 6, 0, 0)

SPALTEN = [
    "case_id",
    "activity",
    "timestamp",
    "resource",
    "actual_start",
    "actual_end",
    "planned_start",
    "planned_end",
    "processing_time_min",
]

PLATZHALTERWERTE = ["NULL", "N/A", "-"]


@dataclass(frozen=True)
class GeneratorKonfiguration:
    zeilen: int
    ausreisseranteil: float
    platzhalter_gesamt: int


@dataclass(frozen=True)
class Aktivitaetsdefinition:
    dauer_min: int
    ressourcen: tuple[str, ...]
    plan_wartezeit_min: tuple[int, int]


AKTIVITAETEN: dict[str, Aktivitaetsdefinition] = {
    "Auftrag angelegt": Aktivitaetsdefinition(5, ("ERP",), (0, 0)),
    "Material bereitstellen": Aktivitaetsdefinition(
        25, ("Logistik_01", "Logistik_02", "Logistik_03"), (5, 20)
    ),
    "Fräsen": Aktivitaetsdefinition(
        90, ("Fräsmaschine_01", "Fräsmaschine_02", "Fräsmaschine_03"), (10, 35)
    ),
    "Qualitätsprüfung 1": Aktivitaetsdefinition(20, ("Messplatz_01", "Messplatz_02"), (5, 20)),
    "Nacharbeit mechanisch": Aktivitaetsdefinition(
        45, ("Nacharbeitsplatz_01", "Nacharbeitsplatz_02"), (10, 30)
    ),
    "Schweißen": Aktivitaetsdefinition(60, ("Schweißzelle_01", "Schweißzelle_02"), (10, 40)),
    "Schleifen": Aktivitaetsdefinition(30, ("Schleifplatz_01", "Schleifplatz_02"), (5, 20)),
    "Vormontage": Aktivitaetsdefinition(45, ("Montageplatz_01", "Montageplatz_02"), (10, 35)),
    "Baugruppenmontage": Aktivitaetsdefinition(
        75, ("Montageplatz_03", "Montageplatz_04"), (10, 35)
    ),
    "Elektrik montieren": Aktivitaetsdefinition(
        50, ("Elektromontage_01", "Elektromontage_02"), (10, 30)
    ),
    "Lackiervorbereitung": Aktivitaetsdefinition(30, ("Lackiervorbereitung_01",), (10, 25)),
    "Lackieren": Aktivitaetsdefinition(40, ("Lackierkabine_01",), (10, 30)),
    "Trocknen": Aktivitaetsdefinition(120, ("Trockenkammer_01",), (5, 15)),
    "Qualitätsprüfung 2": Aktivitaetsdefinition(25, ("Prüfplatz_Oberfläche_01",), (5, 20)),
    "Nacharbeit Lack": Aktivitaetsdefinition(35, ("Lackiernacharbeit_01",), (10, 25)),
    "Endmontage": Aktivitaetsdefinition(60, ("Endmontage_01", "Endmontage_02"), (10, 35)),
    "Verpacken": Aktivitaetsdefinition(20, ("Verpackung_01", "Verpackung_02"), (5, 20)),
    "Auftrag abgeschlossen": Aktivitaetsdefinition(5, ("ERP",), (2, 10)),
}


# -----------------------------------------------------------------------------
# Benutzerparameter
# -----------------------------------------------------------------------------


def argumente_lesen() -> GeneratorKonfiguration:
    parser = argparse.ArgumentParser(
        description=(
            "Erzeugt produktionsnahe Event-Log-Testdaten mit exakt definierter Zeilenanzahl."
        )
    )
    parser.add_argument(
        "--zeilen",
        type=int,
        default=20000,
        help="Anzahl Datenzeilen/Ereignisse, Header nicht mitgezählt (Standard: 10000).",
    )
    parser.add_argument(
        "--ausreisseranteil",
        type=float,
        default=0.0,
        help="Anteil zeitlicher Ausreißer in Prozent, z. B. 1.0 für 1 %% (Standard: 1.0).",
    )
    parser.add_argument(
        "--platzhalter",
        type=int,
        default=0,
        help="Gesamtanzahl textueller Platzhalterzellen über die Tabelle verteilt (Standard: 0).",
    )
    args = parser.parse_args()

    if args.zeilen < 15:
        parser.error("--zeilen muss mindestens 15 sein.")
    if 23 <= args.zeilen <= 29:
        parser.error(
            "Zeilenanzahlen zwischen 23 und 29 lassen sich mit vollständigen Prozessfällen "
            "nicht exakt erzeugen. Verwende 15-22 oder mindestens 30 Zeilen."
        )
    if not 0 <= args.ausreisseranteil <= 100:
        parser.error("--ausreisseranteil muss zwischen 0 und 100 Prozent liegen.")

    maximale_platzhalter = args.zeilen * len(SPALTEN)
    if not 0 <= args.platzhalter <= maximale_platzhalter:
        parser.error(f"--platzhalter muss zwischen 0 und {maximale_platzhalter} liegen.")

    return GeneratorKonfiguration(
        zeilen=args.zeilen,
        ausreisseranteil=args.ausreisseranteil,
        platzhalter_gesamt=args.platzhalter,
    )


# -----------------------------------------------------------------------------
# Prozesslogik
# -----------------------------------------------------------------------------


def trace_fuer_zusatzlaenge(zusatzlaenge: int) -> list[str]:
    """
    Erzeugt einen vollständigen Prozessfall.

    Basislänge = 15 Ereignisse.
    Die Zusatzlänge 0..7 kodiert drei unabhängige Prozesszweige:
      +1  zusätzliche Elektromontage
      +2  mechanische Nacharbeit mit Wiederholungsprüfung QP1
      +4  Lacknacharbeit mit erneutem Lackieren/Trocknen/Wiederholungsprüfung QP2

    Damit existieren vollständige Prozessvarianten mit 15 bis 22 Ereignissen.
    """
    if not 0 <= zusatzlaenge <= 7:
        raise ValueError("zusatzlaenge muss zwischen 0 und 7 liegen")

    mit_elektrik = bool(zusatzlaenge & 1)
    mit_mechanischer_nacharbeit = bool(zusatzlaenge & 2)
    mit_lacknacharbeit = bool(zusatzlaenge & 4)

    trace = [
        "Auftrag angelegt",
        "Material bereitstellen",
        "Fräsen",
        "Qualitätsprüfung 1",
    ]

    if mit_mechanischer_nacharbeit:
        trace.extend(["Nacharbeit mechanisch", "Qualitätsprüfung 1"])

    trace.extend(
        [
            "Schweißen",
            "Schleifen",
            "Vormontage",
            "Baugruppenmontage",
        ]
    )

    if mit_elektrik:
        trace.append("Elektrik montieren")

    trace.extend(
        [
            "Lackiervorbereitung",
            "Lackieren",
            "Trocknen",
            "Qualitätsprüfung 2",
        ]
    )

    if mit_lacknacharbeit:
        trace.extend(
            [
                "Nacharbeit Lack",
                "Lackieren",
                "Trocknen",
                "Qualitätsprüfung 2",
            ]
        )

    trace.extend(["Endmontage", "Verpacken", "Auftrag abgeschlossen"])

    assert len(trace) == 15 + zusatzlaenge
    return trace


def zusatzlaengen_planen(zeilenanzahl: int) -> list[int]:
    """Plant vollständige Fälle, deren Ereignisanzahl exakt zeilenanzahl ergibt."""
    if 15 <= zeilenanzahl <= 22:
        return [zeilenanzahl - 15]
    if zeilenanzahl < 30:
        raise ValueError(
            "Die gewünschte Zeilenanzahl kann nicht aus vollständigen "
            "Prozessfällen gebildet werden."
        )

    # Zielverteilung der Prozessvarianten:
    # 0 = Standard
    # 1 = zusätzliche Elektromontage
    # 2 = mechanische Nacharbeit
    # 3 = mechanische Nacharbeit + Elektromontage
    # 4 = Lacknacharbeit
    # 5 = Lacknacharbeit + Elektromontage
    # 6 = mechanische Nacharbeit + Lacknacharbeit
    # 7 = alle drei Zweige
    #
    # Daraus ergibt sich im Mittel eine Trace-Länge von ca. 15,83 Ereignissen.
    variantenwerte = [0, 1, 2, 3, 4, 5, 6, 7]
    variantengewichte = [0.60, 0.18, 0.10, 0.04, 0.04, 0.015, 0.01, 0.005]
    ziel_mittelwert = 15.83
    anzahl_faelle = max(2, round(zeilenanzahl / ziel_mittelwert))

    while 15 * anzahl_faelle > zeilenanzahl:
        anzahl_faelle -= 1
    while 22 * anzahl_faelle < zeilenanzahl:
        anzahl_faelle += 1

    if not 15 * anzahl_faelle <= zeilenanzahl <= 22 * anzahl_faelle:
        raise ValueError("Zeilenanzahl konnte nicht exakt auf vollständige Fälle verteilt werden.")

    zusatzlaengen = random.choices(
        variantenwerte,
        weights=variantengewichte,
        k=anzahl_faelle,
    )

    ziel_zusatz = zeilenanzahl - 15 * anzahl_faelle
    aktueller_zusatz = sum(zusatzlaengen)

    # Kleine Korrektur der zufällig gezogenen Varianten, damit die gewünschte
    # Zeilenanzahl exakt erreicht wird. Alle Werte 0..7 sind gültige Prozessvarianten.
    while aktueller_zusatz < ziel_zusatz:
        kandidaten = [i for i, wert in enumerate(zusatzlaengen) if wert < 7]
        index = random.choice(kandidaten)
        zusatzlaengen[index] += 1
        aktueller_zusatz += 1

    while aktueller_zusatz > ziel_zusatz:
        kandidaten = [i for i, wert in enumerate(zusatzlaengen) if wert > 0]
        index = random.choice(kandidaten)
        zusatzlaengen[index] -= 1
        aktueller_zusatz -= 1

    random.shuffle(zusatzlaengen)
    return zusatzlaengen


# -----------------------------------------------------------------------------
# Datenerzeugung
# -----------------------------------------------------------------------------


def plan_dauer(aktivitaet: str) -> int:
    basis = AKTIVITAETEN[aktivitaet].dauer_min
    return max(1, round(basis * random.uniform(0.90, 1.10)))


def ist_dauer(plan_minuten: int, ist_ausreisser: bool) -> int:
    if ist_ausreisser:
        return max(plan_minuten + 1, round(plan_minuten * random.uniform(6.0, 12.0)))
    return max(1, round(plan_minuten * random.uniform(0.85, 1.20)))


def grunddaten_erzeugen(
    konfiguration: GeneratorKonfiguration,
) -> tuple[list[list[Any]], list[int]]:
    """
    Erzeugt die vollständigen Prozessdaten.

    Rückgabe:
      - Datenzeilen ohne Header
      - Zusatzlänge je Fall zur späteren Dokumentation
    """
    zusatzlaengen = zusatzlaengen_planen(konfiguration.zeilen)
    traces = [trace_fuer_zusatzlaenge(z) for z in zusatzlaengen]

    # Ausreißer werden auf Ereignisebene festgelegt.
    ausreisser_anzahl = round(konfiguration.zeilen * konfiguration.ausreisseranteil / 100.0)
    ausreisser_indices = set(
        random.sample(range(konfiguration.zeilen), min(ausreisser_anzahl, konfiguration.zeilen))
    )

    zeilen: list[list[Any]] = []
    globaler_ereignisindex = 0

    for fall_index, trace in enumerate(traces, start=1):
        case_id = f"CASE-{fall_index:06d}"

        # Fälle überlappen bewusst zeitlich, um einen realistischen Produktionsstrom zu erzeugen.
        plan_fallstart = STARTZEITPUNKT + timedelta(
            minutes=(fall_index - 1) * 18 + random.randint(0, 8)
        )

        vorheriges_plan_ende: datetime | None = None
        vorheriges_ist_ende: datetime | None = None

        for schritt_index, aktivitaet in enumerate(trace):
            definition = AKTIVITAETEN[aktivitaet]

            if schritt_index == 0:
                planned_start = plan_fallstart
            else:
                assert vorheriges_plan_ende is not None
                planned_start = vorheriges_plan_ende + timedelta(
                    minutes=random.randint(*definition.plan_wartezeit_min)
                )

            planned_duration = plan_dauer(aktivitaet)
            planned_end = planned_start + timedelta(minutes=planned_duration)

            planabweichung = timedelta(minutes=random.randint(-10, 25))
            fruehester_start = planned_start + planabweichung

            if vorheriges_ist_ende is None:
                actual_start = fruehester_start
            else:
                queue_delay = timedelta(minutes=random.randint(2, 25))
                actual_start = max(fruehester_start, vorheriges_ist_ende + queue_delay)

            actual_duration = ist_dauer(
                planned_duration,
                globaler_ereignisindex in ausreisser_indices,
            )
            actual_end = actual_start + timedelta(minutes=actual_duration)

            resource = random.choice(definition.ressourcen)

            # timestamp ist bewusst bereits kanonisch und entspricht dem Ist-Ende der Aktivität.
            zeilen.append(
                [
                    case_id,
                    aktivitaet,
                    actual_end,
                    resource,
                    actual_start,
                    actual_end,
                    planned_start,
                    planned_end,
                    actual_duration,
                ]
            )

            vorheriges_plan_ende = planned_end
            vorheriges_ist_ende = actual_end
            globaler_ereignisindex += 1

    assert len(zeilen) == konfiguration.zeilen
    return zeilen, zusatzlaengen


# -----------------------------------------------------------------------------
# Datenqualitätsauffälligkeiten
# -----------------------------------------------------------------------------


def platzhalter_einbauen(
    zeilen: list[list[Any]],
    platzhalter_gesamt: int,
) -> int:
    """
    Verteilt exakt die gewünschte Anzahl textueller Platzhalter über die Tabelle.

    Es werden keine Zellen geleert. Die Platzhalter werden möglichst gleichmäßig
    auf alle Spalten verteilt. Jede ausgewählte Zelle wird durch NULL, N/A oder -
    ersetzt.
    """
    if platzhalter_gesamt <= 0:
        return 0

    zeilenanzahl = len(zeilen)
    spaltenanzahl = len(SPALTEN)
    maximale_anzahl = zeilenanzahl * spaltenanzahl
    anzahl = min(platzhalter_gesamt, maximale_anzahl)

    basis = anzahl // spaltenanzahl
    rest = anzahl % spaltenanzahl

    ziele_je_spalte = [basis] * spaltenanzahl
    spalten_reihenfolge = list(range(spaltenanzahl))
    random.shuffle(spalten_reihenfolge)
    for spaltenindex in spalten_reihenfolge[:rest]:
        ziele_je_spalte[spaltenindex] += 1

    # Falls sehr viele Platzhalter gewünscht werden, kann eine Spalte maximal
    # zeilenanzahl Zellen aufnehmen. Überhänge werden auf andere Spalten verteilt.
    ueberhang = 0
    for index, ziel in enumerate(ziele_je_spalte):
        if ziel > zeilenanzahl:
            ueberhang += ziel - zeilenanzahl
            ziele_je_spalte[index] = zeilenanzahl

    while ueberhang > 0:
        kandidaten = [i for i, ziel in enumerate(ziele_je_spalte) if ziel < zeilenanzahl]
        index = random.choice(kandidaten)
        ziele_je_spalte[index] += 1
        ueberhang -= 1

    gesetzt = 0
    for spaltenindex, ziel in enumerate(ziele_je_spalte):
        if ziel <= 0:
            continue
        ausgewaehlte_zeilen = random.sample(range(zeilenanzahl), ziel)
        for laufnummer, zeilenindex in enumerate(ausgewaehlte_zeilen):
            zeilen[zeilenindex][spaltenindex] = PLATZHALTERWERTE[
                (gesetzt + laufnummer) % len(PLATZHALTERWERTE)
            ]
        gesetzt += ziel

    assert gesetzt == anzahl
    return gesetzt


# -----------------------------------------------------------------------------
# Excel-Ausgabe
# -----------------------------------------------------------------------------


def tabellenstil_anwenden(tabelle: Table) -> None:
    tabelle.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )


def excel_erzeugen(
    konfiguration: GeneratorKonfiguration,
    zeilen: list[list[Any]],
    zusatzlaengen: list[int],
    platzhalter_gesetzt: int,
) -> None:
    arbeitsmappe = Workbook()
    ereignisse = arbeitsmappe.active
    assert ereignisse is not None
    ereignisse.title = "Ereignisdaten"
    hinweise = arbeitsmappe.create_sheet("Hinweise")

    kopf_fill = PatternFill("solid", fgColor="004983")
    kopf_font = Font(bold=True, color="FFFFFF")
    akzent_fill = PatternFill("solid", fgColor="EAF2F8")

    ereignisse.append(SPALTEN)
    for zeile in zeilen:
        ereignisse.append(zeile)

    for zelle in ereignisse[1]:
        zelle.fill = kopf_fill
        zelle.font = kopf_font
        zelle.alignment = Alignment(horizontal="center", vertical="center")

    ereignisse.freeze_panes = "A2"
    ereignisse.auto_filter.ref = f"A1:I{ereignisse.max_row}"

    breiten = {
        "A": 18,
        "B": 28,
        "C": 21,
        "D": 25,
        "E": 21,
        "F": 21,
        "G": 21,
        "H": 21,
        "I": 21,
    }
    for spalte, breite in breiten.items():
        ereignisse.column_dimensions[spalte].width = breite

    for spalte in ("C", "E", "F", "G", "H"):
        for zelle in ereignisse[spalte][1:]:
            if isinstance(zelle.value, datetime):
                zelle.number_format = "yyyy-mm-dd hh:mm:ss"

    ereignistabelle = Table(
        displayName="EreignisdatenTabelle",
        ref=f"A1:I{ereignisse.max_row}",
    )
    tabellenstil_anwenden(ereignistabelle)
    ereignisse.add_table(ereignistabelle)

    variantenanzahl = {
        "Standard": sum(1 for z in zusatzlaengen if z == 0),
        "mit Elektromontage": sum(1 for z in zusatzlaengen if z & 1),
        "mit mechanischer Nacharbeit": sum(1 for z in zusatzlaengen if z & 2),
        "mit Lacknacharbeit": sum(1 for z in zusatzlaengen if z & 4),
    }

    hinweise.append(["Merkmal", "Wert / Beschreibung"])
    hinweisdaten = [
        ["Zeilenanzahl", konfiguration.zeilen],
        ["Fälle", len(zusatzlaengen)],
        ["Ausreißeranteil [%]", konfiguration.ausreisseranteil],
        [
            "Zeitliche Ausreißer [Zeilen]",
            round(konfiguration.zeilen * konfiguration.ausreisseranteil / 100.0),
        ],
        ["Platzhalter gesamt", platzhalter_gesetzt],
        ["Platzhalterwerte", ", ".join(PLATZHALTERWERTE)],
        ["Semantisches Mapping", "Nicht erforderlich für case_id, activity und timestamp"],
        ["timestamp", "entspricht actual_end"],
        ["Prozess", "Fertigung einer geschweißten und lackierten Baugruppe"],
        [
            "Grundprozess",
            "Material bereitstellen → Fräsen → Qualitätsprüfung 1 → Schweißen → "
            "Schleifen → Vormontage → Baugruppenmontage → Lackiervorbereitung → "
            "Lackieren → Trocknen → Qualitätsprüfung 2 → Endmontage → Verpacken",
        ],
        [
            "Verzweigung QP1",
            "Qualitätsprüfung 1 → Nacharbeit mechanisch → Qualitätsprüfung 1",
        ],
        [
            "Verzweigung Montage",
            "Optional: Elektrik montieren nach der Baugruppenmontage",
        ],
        [
            "Verzweigung QP2",
            "Qualitätsprüfung 2 → Nacharbeit Lack → Lackieren → Trocknen → Qualitätsprüfung 2",
        ],
        ["Standardfälle", variantenanzahl["Standard"]],
        ["Fälle mit Elektromontage", variantenanzahl["mit Elektromontage"]],
        [
            "Fälle mit mechanischer Nacharbeit",
            variantenanzahl["mit mechanischer Nacharbeit"],
        ],
        ["Fälle mit Lacknacharbeit", variantenanzahl["mit Lacknacharbeit"]],
        ["Zufallsseed", SEED],
    ]
    for zeile in hinweisdaten:
        hinweise.append(zeile)

    for zelle in hinweise[1]:
        zelle.fill = kopf_fill
        zelle.font = kopf_font
        zelle.alignment = Alignment(horizontal="center", vertical="center")

    for zeile in range(2, hinweise.max_row + 1):
        hinweise.cell(zeile, 1).fill = akzent_fill
        hinweise.cell(zeile, 1).font = Font(bold=True, color="004983")
        hinweise.cell(zeile, 1).alignment = Alignment(vertical="top")
        hinweise.cell(zeile, 2).alignment = Alignment(wrap_text=True, vertical="top")

    hinweise.freeze_panes = "A2"
    hinweise.column_dimensions["A"].width = 38
    hinweise.column_dimensions["B"].width = 100

    hinweistabelle = Table(
        displayName="HinweiseTabelle",
        ref=f"A1:B{hinweise.max_row}",
    )
    tabellenstil_anwenden(hinweistabelle)
    hinweise.add_table(hinweistabelle)

    AUSGABEDATEI.parent.mkdir(parents=True, exist_ok=True)
    arbeitsmappe.save(AUSGABEDATEI)


# -----------------------------------------------------------------------------
# Einstieg
# -----------------------------------------------------------------------------


def main() -> None:
    konfiguration = argumente_lesen()
    random.seed(SEED)

    zeilen, zusatzlaengen = grunddaten_erzeugen(konfiguration)
    platzhalter_gesetzt = platzhalter_einbauen(
        zeilen,
        konfiguration.platzhalter_gesamt,
    )
    excel_erzeugen(
        konfiguration=konfiguration,
        zeilen=zeilen,
        zusatzlaengen=zusatzlaengen,
        platzhalter_gesetzt=platzhalter_gesetzt,
    )

    ausreisser_anzahl = round(konfiguration.zeilen * konfiguration.ausreisseranteil / 100.0)

    print(f"Datei erstellt: {AUSGABEDATEI.resolve()}")
    print(f"Datenzeilen: {konfiguration.zeilen:,}".replace(",", "."))
    print(f"Fälle: {len(zusatzlaengen):,}".replace(",", "."))
    print(f"Zeitliche Ausreißer: {ausreisser_anzahl:,}".replace(",", "."))
    print(f"Textuelle Platzhalter: {platzhalter_gesetzt:,}".replace(",", "."))
    print(f"Seed: {SEED}")


if __name__ == "__main__":
    main()
