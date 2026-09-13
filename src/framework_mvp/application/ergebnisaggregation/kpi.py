# pyright: reportAttributeAccessIssue=false
"""Feste KPI-Gleichungen und explizite Operandenzuordnung gemäß A.7 bis A.10."""
# ruff: noqa: E501 -- Die zentralen LaTeX-Formeln bleiben jeweils atomar lesbar.

from dataclasses import asdict, dataclass
from math import isfinite, sqrt
from typing import Any, cast

import pandas as pd

from framework_mvp.domain.models import (
    Datenartefakt,
    KpiDefinition,
    KpiErgebnis,
    KpiKonfiguration,
    KpiOperandDefinition,
    KpiStatus,
    Operandentyp,
    OperandZuordnung,
    ProfilkennzahlReferenz,
    Profilkennzahltyp,
    Vorkommensregel,
)

_ALLE_QUELLEN = (
    Datenartefakt.DATENPROFIL_R,
    Datenartefakt.ZWISCHENDATENSATZ_T,
    Datenartefakt.EVENT_LOG_E_STERN,
)
_TABELLEN_QUELLEN = (
    Datenartefakt.ZWISCHENDATENSATZ_T,
    Datenartefakt.EVENT_LOG_E_STERN,
)


def _operand(
    operand_id: str,
    bezeichnung: str,
    typ: Operandentyp,
    *,
    quellen: tuple[Datenartefakt, ...] = _ALLE_QUELLEN,
    datentyp: str = "numerisch",
) -> KpiOperandDefinition:
    return KpiOperandDefinition(operand_id, bezeichnung, typ, quellen, datentyp)


KPI_FORMELN_LATEX = {
    "einhaltung_lagerbandbreite": r"\frac{n_{\mathrm{Tage\ innerhalb\ Bestandsgrenzen}}}{t_{\mathrm{Betrachtungszeitraum}}}\cdot 100",
    "servicegrad": r"\frac{n_{\mathrm{befriedigte\ Kundenauftragspositionen}}}{n_{\mathrm{Kundenauftragspositionen}}}\cdot 100",
    "verfuegbarkeit_planstarttermin": r"\frac{n_{\mathrm{startbare\ Produktionsauftraege}}}{n_{\mathrm{Produktionsauftraege}}}\cdot 100",
    "bestaetigungsquote_kundenwunschtermin": r"\frac{n_{\mathrm{zum\ Kundenwunschtermin\ bestaetigte\ Kundenauftragspositionen}}}{n_{\mathrm{Kundenauftragspositionen}}}\cdot 100",
    "liefertreue": r"\frac{n_{\mathrm{liefertreue\ Produktionsauftraege}}}{n_{\mathrm{Produktionsauftraege}}}\cdot 100",
    "liefertreue_intralogistik": r"\frac{n_{\mathrm{befriedigte\ Kundenauftragspositionen}}}{n_{\mathrm{Kundenauftragspositionen}}}\cdot 100",
    "mittlere_durchfuehrungszeit": r"\frac{\sum_{i=1}^{n}t_{\mathrm{Durchfuehrung},i}}{n}",
    "mittlere_dlz_warenausgang": r"\frac{\sum_i DLZ_{\mathrm{Warenausgang},i}}{n_{\mathrm{Lieferscheinpositionen}}}",
    "mittlerer_durchfuehrungszeitanteil": r"\frac{\sum_{i=1}^{n}t_{\mathrm{Durchfuehrung},i}}{\sum_{i=1}^{n}t_{\mathrm{Durchlauf},i}}\cdot 100",
    "mittlere_dlz_wareneingang": r"\frac{\sum_i DLZ_{\mathrm{Wareneingang},i}}{n_{\mathrm{Wareneingangspositionen}}}",
    "tatsaechliche_wartezeit_aqt": r"t_{\mathrm{Auftragsausfuehrung}}-t_{\mathrm{Belegung}}-t_{\mathrm{Transport}}-t_{\mathrm{Verzoegerung}}",
    "mittlere_wartezeit_je_foerdereinheit": r"\overline{t}_{W}=\frac{\sum_{i=1}^{n}t_{W,i}}{n}",
    "tatsaechliche_transportzeit_att": r"t_{\mathrm{Auftragsausfuehrung}}-t_{\mathrm{Belegung}}-t_{\mathrm{Wartezeit}}-t_{\mathrm{Verzoegerung}}",
    "mittlere_transportzeit_je_warensendung": r"\frac{\sum_i t_{\mathrm{Transport},i}}{n_{\mathrm{Warensendungen}}}",
    "mittlere_reaktionszeit": r"\frac{\sum_i(t_{\mathrm{erste\ Reaktion},i}-t_{\mathrm{Ausloesung},i})}{n}",
    "standardabweichung_bearbeitungszeit": r"\sqrt{\frac{\sum_{i=1}^{n}(t_i-\overline{t})^2}{n}}",
    "standardabweichung_dlz_warenausgang": r"\frac{\sum_{i=1}^{n}(DLZ_i-\overline{DLZ})^2}{n_{\mathrm{Lieferscheinpositionen}}}",
    "anteil_regulaer_abgeschlossener_faelle": r"\frac{n_{\mathrm{regulaer\ abgeschlossen}}}{n_{\mathrm{betrachtete\ Faelle}}}\cdot 100",
    "first_time_quality_ftq": r"\frac{GQ}{PQF}\cdot 100",
    "lieferqualitaetstreue": r"\frac{n_{\mathrm{qualitaetsgerechte\ Wareneingangspositionen}}}{n_{\mathrm{Wareneingangspositionen}}}\cdot 100",
    "nacharbeitsquote_rr": r"\frac{RQ}{PQ}\cdot 100",
    "reklamationsquote": r"\frac{n_{\mathrm{berechtigte\ Kundenreklamationen}}}{n_{\mathrm{Lieferscheinpositionen}}}\cdot 100",
    "nutzungseffizienz_ue": r"\frac{t_{\mathrm{Produktionszeit}}}{t_{\mathrm{Auslastung\ der\ Einheit}}}\cdot 100",
    "kommissionierauftragspositionen_pro_mitarbeiterstunde": r"\frac{n_{\mathrm{Kommissionierauftragspositionen}}}{t_{\mathrm{Mitarbeiterstunden\ Distribution}}}",
    "ruestzeitanteil": r"\frac{\sum_i t_{\mathrm{Ruest},i}}{\sum_i t_{\mathrm{Durchfuehrung},i}}\cdot 100",
    "setupzeit_je_kommissionierliste": r"t_{Sep}=t_{Se}\quad\forall p=1,\ldots,P",
    "bewertete_umschlagshaeufigkeit": r"\frac{A_{\mathrm{Untersuchungsobjekt}}}{\overline{B}_{\mathrm{Zugang}}+\overline{B}_{\mathrm{Umlauf}}}",
    "mittlere_kosten_produktionslogistik_pro_produktionsauftrag": r"\frac{K_{\mathrm{Produktionslogistik}}}{n_{\mathrm{Produktionsauftraege}}}",
    "mittlere_kosten_distributionstaetigkeiten_je_kommissionierauftragsposition": r"\frac{K_{\mathrm{Distributionstaetigkeiten}}}{n_{\mathrm{Kommissionierauftragspositionen}}}",
}


def _definition(
    kpi_id: str,
    bezeichnung: str,
    formel: str,
    operanden: tuple[KpiOperandDefinition, ...],
    einheit: str,
    bezugsmenge: str,
    *,
    einheit_eingeben: bool = False,
    definitionsversion: int = 1,
) -> KpiDefinition:
    return KpiDefinition(
        kpi_id,
        bezeichnung,
        formel,
        operanden,
        "Fließkommazahl",
        einheit,
        einheit_eingeben,
        bezugsmenge,
        definitionsversion=definitionsversion,
        formel_latex=KPI_FORMELN_LATEX[kpi_id],
    )


KPI_DEFINITIONEN: dict[str, KpiDefinition] = {
    "einhaltung_lagerbandbreite": _definition(
        "einhaltung_lagerbandbreite",
        "Einhaltung Lagerbandbreite",
        "Anzahl Tage innerhalb Bestandsgrenzen / Betrachtungszeitraum · 100",
        (
            _operand(
                "tage_innerhalb_bestandsgrenzen",
                "Tage innerhalb der Bestandsgrenzen",
                Operandentyp.ANZAHL,
            ),
            _operand(
                "betrachtungszeitraum_tage",
                "Tage im Betrachtungszeitraum",
                Operandentyp.ANZAHL,
            ),
        ),
        "%",
        "Betrachtungszeitraum in Tagen",
    ),
    "servicegrad": _definition(
        "servicegrad",
        "Servicegrad",
        "Anzahl befriedigter Kundenauftragspositionen / Anzahl Kundenauftragspositionen · 100",
        (
            _operand(
                "befriedigte_kundenauftragspositionen",
                "befriedigte Kundenauftragspositionen",
                Operandentyp.ANZAHL,
            ),
            _operand("kundenauftragspositionen", "Kundenauftragspositionen", Operandentyp.ANZAHL),
        ),
        "%",
        "Kundenauftragspositionen",
    ),
    "verfuegbarkeit_planstarttermin": _definition(
        "verfuegbarkeit_planstarttermin",
        "Verfügbarkeit zum Planstarttermin",
        "Anzahl startbarer Produktionsaufträge / Anzahl Produktionsaufträge · 100",
        (
            _operand(
                "startbare_produktionsauftraege",
                "startbare Produktionsaufträge",
                Operandentyp.ANZAHL,
            ),
            _operand("produktionsauftraege", "Produktionsaufträge", Operandentyp.ANZAHL),
        ),
        "%",
        "Produktionsaufträge",
    ),
    "bestaetigungsquote_kundenwunschtermin": _definition(
        "bestaetigungsquote_kundenwunschtermin",
        "Bestätigungsquote Kundenwunschtermin",
        "Anzahl zum Kundenwunschtermin bestätigter Kundenauftragspositionen / "
        "Anzahl Kundenauftragspositionen · 100",
        (
            _operand(
                "bestaetigte_kundenauftragspositionen",
                "zum Kundenwunschtermin bestätigte Kundenauftragspositionen",
                Operandentyp.ANZAHL,
            ),
            _operand("kundenauftragspositionen", "Kundenauftragspositionen", Operandentyp.ANZAHL),
        ),
        "%",
        "Kundenauftragspositionen",
    ),
    "liefertreue": _definition(
        "liefertreue",
        "Liefertreue",
        "Anzahl liefertreuer Produktionsaufträge / Anzahl Produktionsaufträge · 100",
        (
            _operand(
                "liefertreue_produktionsauftraege",
                "liefertreue Produktionsaufträge",
                Operandentyp.ANZAHL,
            ),
            _operand("produktionsauftraege", "Produktionsaufträge", Operandentyp.ANZAHL),
        ),
        "%",
        "Produktionsaufträge",
    ),
    "liefertreue_intralogistik": _definition(
        "liefertreue_intralogistik",
        "Liefertreue",
        "Anzahl befriedigter Kundenauftragspositionen / Anzahl Kundenauftragspositionen · 100",
        (
            _operand(
                "befriedigte_kundenauftragspositionen",
                "befriedigte Kundenauftragspositionen",
                Operandentyp.ANZAHL,
            ),
            _operand("kundenauftragspositionen", "Kundenauftragspositionen", Operandentyp.ANZAHL),
        ),
        "%",
        "Kundenauftragspositionen",
    ),
    "mittlere_durchfuehrungszeit": _definition(
        "mittlere_durchfuehrungszeit",
        "Mittlere Durchführungszeit",
        "Σ Durchführungszeit_i / n",
        (
            _operand(
                "summe_durchfuehrungszeiten",
                "Summe der Durchführungszeiten",
                Operandentyp.SUMME,
            ),
            _operand("produktionsauftraege", "Produktionsaufträge n", Operandentyp.ANZAHL),
        ),
        "fachlich festzulegen",
        "Produktionsaufträge n",
        einheit_eingeben=True,
    ),
    "mittlere_dlz_warenausgang": _definition(
        "mittlere_dlz_warenausgang",
        "Mittlere DLZ Warenausgang",
        "Σ DLZ_i / Anzahl Lieferscheinpositionen",
        (
            _operand("summe_dlz_warenausgang", "Summe DLZ Warenausgang", Operandentyp.SUMME),
            _operand("lieferscheinpositionen", "Lieferscheinpositionen", Operandentyp.ANZAHL),
        ),
        "fachlich festzulegen",
        "Lieferscheinpositionen",
        einheit_eingeben=True,
    ),
    "mittlerer_durchfuehrungszeitanteil": _definition(
        "mittlerer_durchfuehrungszeitanteil",
        "Mittlerer Durchführungszeitanteil",
        "Σ Durchführungszeit_i / Σ Durchlaufzeit_i · 100",
        (
            _operand(
                "summe_durchfuehrungszeiten",
                "Summe der Durchführungszeiten",
                Operandentyp.SUMME,
            ),
            _operand(
                "summe_durchlaufzeiten",
                "Summe der Durchlaufzeiten",
                Operandentyp.SUMME,
            ),
        ),
        "%",
        "Produktionsaufträge n",
    ),
    "mittlere_dlz_wareneingang": _definition(
        "mittlere_dlz_wareneingang",
        "Mittlere DLZ Wareneingang",
        "Σ DLZ_i / Anzahl Wareneingangspositionen",
        (
            _operand("summe_dlz_wareneingang", "Summe DLZ Wareneingang", Operandentyp.SUMME),
            _operand("wareneingangspositionen", "Wareneingangspositionen", Operandentyp.ANZAHL),
        ),
        "fachlich festzulegen",
        "Wareneingangspositionen",
        einheit_eingeben=True,
    ),
    "tatsaechliche_wartezeit_aqt": _definition(
        "tatsaechliche_wartezeit_aqt",
        "Tatsächliche (tats.) Wartezeit (AQT)",
        "tatsächliche Auftragsausführungszeit − tatsächliche Belegungszeit der "
        "Arbeitseinheit − tatsächliche Transportzeit − tatsächliche Verzögerungszeit "
        "der Arbeitseinheit",
        (
            _operand(
                "auftragsausfuehrungszeit",
                "tatsächliche Auftragsausführungszeit",
                Operandentyp.MITTELWERT,
            ),
            _operand(
                "belegungszeit_arbeitseinheit",
                "tatsächliche Belegungszeit der Arbeitseinheit",
                Operandentyp.MITTELWERT,
            ),
            _operand("transportzeit", "tatsächliche Transportzeit", Operandentyp.MITTELWERT),
            _operand(
                "verzoegerungszeit_arbeitseinheit",
                "tatsächliche Verzögerungszeit der Arbeitseinheit",
                Operandentyp.MITTELWERT,
            ),
        ),
        "fachlich festzulegen",
        "betrachtete Auftragsausführungen",
        einheit_eingeben=True,
    ),
    "mittlere_wartezeit_je_foerdereinheit": _definition(
        "mittlere_wartezeit_je_foerdereinheit",
        "Mittlere Wartezeit je Fördereinheit",
        "Σ Wartezeit_i / Anzahl Fördereinheiten n",
        (
            _operand("summe_wartezeiten", "Summe der Wartezeiten", Operandentyp.SUMME),
            _operand("foerdereinheiten", "Fördereinheiten n", Operandentyp.ANZAHL),
        ),
        "fachlich festzulegen",
        "Fördereinheiten n",
        einheit_eingeben=True,
    ),
    "tatsaechliche_transportzeit_att": _definition(
        "tatsaechliche_transportzeit_att",
        "Tatsächliche (tats.) Transportzeit (ATT)",
        "tatsächliche Auftragsausführungszeit − tatsächliche Belegungszeit der "
        "Arbeitseinheit − tatsächliche Wartezeit − tatsächliche Verzögerungszeit "
        "der Arbeitseinheit",
        (
            _operand(
                "auftragsausfuehrungszeit",
                "tatsächliche Auftragsausführungszeit",
                Operandentyp.MITTELWERT,
            ),
            _operand(
                "belegungszeit_arbeitseinheit",
                "tatsächliche Belegungszeit der Arbeitseinheit",
                Operandentyp.MITTELWERT,
            ),
            _operand("wartezeit", "tatsächliche Wartezeit", Operandentyp.MITTELWERT),
            _operand(
                "verzoegerungszeit_arbeitseinheit",
                "tatsächliche Verzögerungszeit der Arbeitseinheit",
                Operandentyp.MITTELWERT,
            ),
        ),
        "fachlich festzulegen",
        "betrachtete Auftragsausführungen",
        einheit_eingeben=True,
    ),
    "mittlere_transportzeit_je_warensendung": _definition(
        "mittlere_transportzeit_je_warensendung",
        "Mittlere Transportzeit je Warensendung",
        "Σ Transportzeit_i / Anzahl Warensendungen",
        (
            _operand("summe_transportzeiten", "Summe Transportzeiten", Operandentyp.SUMME),
            _operand("warensendungen", "Warensendungen", Operandentyp.ANZAHL),
        ),
        "fachlich festzulegen",
        "Warensendungen",
        einheit_eingeben=True,
    ),
    "mittlere_reaktionszeit": _definition(
        "mittlere_reaktionszeit",
        "Mittlere Reaktionszeit",
        "Σ (t_erste Reaktion,i − t_Auslösung,i) / n",
        (
            _operand(
                "summe_reaktionszeiten",
                "Summe der Zeitdifferenzen zwischen Auslösung und erster Reaktion",
                Operandentyp.ZEITDIFFERENZ_SUMME,
                quellen=_TABELLEN_QUELLEN,
                datentyp="Zeitstempel",
            ),
            _operand("beobachtungen", "Beobachtungen n", Operandentyp.ANZAHL),
        ),
        "fachlich festzulegen",
        "Beobachtungen n",
        einheit_eingeben=True,
    ),
    "standardabweichung_dlz_warenausgang": _definition(
        "standardabweichung_dlz_warenausgang",
        "Standardabweichung DLZ Warenausgang",
        "Σ (DLZ_i − Mittlere DLZ)² / Anzahl Lieferscheinpositionen",
        (
            _operand(
                "dlz_warenausgang_werte",
                "DLZ-Werte Warenausgang",
                Operandentyp.MESSWERTE,
                quellen=_TABELLEN_QUELLEN,
            ),
        ),
        "fachlich festzulegen",
        "Lieferscheinpositionen",
        einheit_eingeben=True,
        definitionsversion=2,
    ),
    "standardabweichung_bearbeitungszeit": _definition(
        "standardabweichung_bearbeitungszeit",
        "Standardabweichung der Bearbeitungszeit",
        "√(Σ (Bearbeitungszeit_i − mittlere Bearbeitungszeit)² / n)",
        (
            _operand(
                "bearbeitungszeit_werte",
                "Bearbeitungszeiten t_i",
                Operandentyp.MESSWERTE,
                quellen=_TABELLEN_QUELLEN,
            ),
        ),
        "fachlich festzulegen",
        "Bearbeitungszeiten n",
        einheit_eingeben=True,
    ),
    "anteil_regulaer_abgeschlossener_faelle": _definition(
        "anteil_regulaer_abgeschlossener_faelle",
        "Anteil regulär abgeschlossener Fälle",
        "n_regulär abgeschlossene Fälle / n_betrachtete Fälle · 100",
        (
            _operand(
                "regulaer_abgeschlossene_faelle",
                "regulär abgeschlossene Fälle",
                Operandentyp.ANZAHL,
            ),
            _operand("betrachtete_faelle", "betrachtete Fälle", Operandentyp.ANZAHL),
        ),
        "%",
        "betrachtete Fälle",
    ),
    "lieferqualitaetstreue": _definition(
        "lieferqualitaetstreue",
        "Lieferqualitätstreue",
        "Anzahl qualitätsgerechter Wareneingangspositionen / Anzahl Wareneingangspositionen · 100",
        (
            _operand(
                "qualitaetsgerechte_wareneingangspositionen",
                "qualitätsgerechte Wareneingangspositionen",
                Operandentyp.ANZAHL,
            ),
            _operand("wareneingangspositionen", "Wareneingangspositionen", Operandentyp.ANZAHL),
        ),
        "%",
        "Wareneingangspositionen",
    ),
    "first_time_quality_ftq": _definition(
        "first_time_quality_ftq",
        "First Time Quality (FTQ)",
        "Gutmenge GQ / produzierte Fertigungsmenge PQF · 100",
        (
            _operand("gutmenge_gq", "Gutmenge (GQ)", Operandentyp.SUMME),
            _operand(
                "produzierte_fertigungsmenge_pqf",
                "produzierte Fertigungsmenge (PQF)",
                Operandentyp.SUMME,
            ),
        ),
        "%",
        "produzierte Fertigungsmenge (PQF)",
    ),
    "nacharbeitsquote_rr": _definition(
        "nacharbeitsquote_rr",
        "Nacharbeitsquote (RR)",
        "Nacharbeitsmenge RQ / Produktionsmenge PQ · 100",
        (
            _operand("nacharbeiten", "Nacharbeitsmenge (RQ)", Operandentyp.SUMME),
            _operand("verarbeitete_menge", "Produktionsmenge (PQ)", Operandentyp.SUMME),
        ),
        "%",
        "Produktionsmenge (PQ)",
        definitionsversion=2,
    ),
    "reklamationsquote": _definition(
        "reklamationsquote",
        "Reklamationsquote",
        "Anzahl berechtigter Kundenreklamationen / Anzahl Lieferscheinpositionen · 100",
        (
            _operand(
                "berechtigte_kundenreklamationen",
                "berechtigte Kundenreklamationen",
                Operandentyp.ANZAHL,
            ),
            _operand("lieferscheinpositionen", "Lieferscheinpositionen", Operandentyp.ANZAHL),
        ),
        "%",
        "Lieferscheinpositionen",
    ),
    "nutzungseffizienz_ue": _definition(
        "nutzungseffizienz_ue",
        "Nutzungseffizienz (UE)",
        "tatsächliche Produktionszeit / tatsächliche Auslastung der Einheit · 100",
        (
            _operand("produktionszeit", "tatsächliche Produktionszeit", Operandentyp.SUMME),
            _operand(
                "auslastung_der_einheit", "tatsächliche Auslastung der Einheit", Operandentyp.SUMME
            ),
        ),
        "%",
        "betrachtete Einheit",
    ),
    "kommissionierauftragspositionen_pro_mitarbeiterstunde": _definition(
        "kommissionierauftragspositionen_pro_mitarbeiterstunde",
        "Kommissionierauftragspositionen pro Mitarbeiterstunde",
        "Anzahl Kommissionierauftragspositionen / Mitarbeiterstunden Distribution",
        (
            _operand(
                "kommissionierauftragspositionen",
                "Kommissionierauftragspositionen",
                Operandentyp.ANZAHL,
            ),
            _operand(
                "mitarbeiterstunden_distribution",
                "Mitarbeiterstunden Distribution",
                Operandentyp.SUMME,
            ),
        ),
        "1/h",
        "Mitarbeiterstunden Distribution",
    ),
    "ruestzeitanteil": _definition(
        "ruestzeitanteil",
        "Rüstzeitanteil",
        "Σ Rüstzeit_i / Σ Durchführungszeit_i · 100",
        (
            _operand("summe_ruestzeiten", "Summe Rüstzeiten", Operandentyp.SUMME),
            _operand("summe_durchfuehrungszeiten", "Summe Durchführungszeiten", Operandentyp.SUMME),
        ),
        "%",
        "Produktionsaufträge n",
    ),
    "setupzeit_je_kommissionierliste": _definition(
        "setupzeit_je_kommissionierliste",
        "Setupzeit je Kommissionierliste",
        "Setupzeit t_Se für jede Kommissionierliste p = 1, …, P",
        (
            _operand(
                "setupzeit_kommissionierliste",
                "für alle Kommissionierlisten gleiche Setupzeit t_Se",
                Operandentyp.EINDEUTIGER_WERT,
                quellen=_TABELLEN_QUELLEN,
            ),
        ),
        "fachlich festzulegen",
        "Kommissionierliste p",
        einheit_eingeben=True,
    ),
    "bewertete_umschlagshaeufigkeit": _definition(
        "bewertete_umschlagshaeufigkeit",
        "Bewertete Umschlagshäufigkeit",
        "Abgang Untersuchungsobjekt / (Mittlerer Zugangsbestand + Mittlerer Umlaufbestand)",
        (
            _operand(
                "abgang_untersuchungsobjekt", "Abgang Untersuchungsobjekt", Operandentyp.SUMME
            ),
            _operand(
                "mittlerer_zugangsbestand", "Mittlerer Zugangsbestand", Operandentyp.MITTELWERT
            ),
            _operand("mittlerer_umlaufbestand", "Mittlerer Umlaufbestand", Operandentyp.MITTELWERT),
        ),
        "1/Jahr",
        "Gesamtbestand",
    ),
    "mittlere_kosten_produktionslogistik_pro_produktionsauftrag": _definition(
        "mittlere_kosten_produktionslogistik_pro_produktionsauftrag",
        "Mittlere Kosten der Produktionslogistik pro Produktionsauftrag",
        "Kosten Produktionslogistik / Anzahl Produktionsaufträge",
        (
            _operand(
                "kosten_produktionslogistik", "Kosten Produktionslogistik", Operandentyp.SUMME
            ),
            _operand("produktionsauftraege", "Produktionsaufträge", Operandentyp.ANZAHL),
        ),
        "EUR",
        "Produktionsaufträge",
    ),
    "mittlere_kosten_distributionstaetigkeiten_je_kommissionierauftragsposition": _definition(
        "mittlere_kosten_distributionstaetigkeiten_je_kommissionierauftragsposition",
        "Mittlere Kosten Distributionstätigkeiten je Kommissionierauftragsposition",
        "Kosten Distributionstätigkeiten / Anzahl Kommissionierauftragspositionen",
        (
            _operand(
                "kosten_distributionstaetigkeiten",
                "Kosten Distributionstätigkeiten",
                Operandentyp.SUMME,
            ),
            _operand(
                "kommissionierauftragspositionen",
                "Kommissionierauftragspositionen",
                Operandentyp.ANZAHL,
            ),
        ),
        "EUR",
        "Kommissionierauftragspositionen",
    ),
}

_DIREKT_AUS_R_UEBERNEHMBARE_MITTELWERTE = {
    "mittlere_durchfuehrungszeit",
    "mittlere_dlz_warenausgang",
    "mittlere_dlz_wareneingang",
    "mittlere_wartezeit_je_foerdereinheit",
    "mittlere_transportzeit_je_warensendung",
    "mittlere_reaktionszeit",
    "mittlere_kosten_produktionslogistik_pro_produktionsauftrag",
    "mittlere_kosten_distributionstaetigkeiten_je_kommissionierauftragsposition",
}


def kpi_erlaubt_direkten_profilmittelwert(kpi_id: str) -> bool:
    """Kennzeichnet Formeln, deren Ergebnis exakt ein bestätigter Mittelwert aus R sein kann."""
    return kpi_id in _DIREKT_AUS_R_UEBERNEHMBARE_MITTELWERTE


@dataclass(frozen=True, slots=True)
class KpiDatenbasis:
    """Tiefe Arbeitskopien und exakt bezeichnete Werte aus R."""

    zwischendatensatz: pd.DataFrame
    event_log: pd.DataFrame
    profilwerte: dict[str, float]
    referenzen: dict[Datenartefakt, dict[str, Any]]
    profilkennzahlen: tuple[ProfilkennzahlReferenz, ...] = ()


@dataclass(frozen=True, slots=True)
class _OperandWert:
    wert: float | tuple[float, ...]
    ausgeschlossen: int
    dokumentation: dict[str, Any]


_KOMPATIBLE_PROFILKENNZAHLEN: dict[Operandentyp, frozenset[Profilkennzahltyp]] = {
    Operandentyp.ANZAHL: frozenset(
        {
            Profilkennzahltyp.ZEILENANZAHL,
            Profilkennzahltyp.GUELTIGE_BEOBACHTUNGEN,
            Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR,
        }
    ),
    Operandentyp.SUMME: frozenset(
        {
            Profilkennzahltyp.SUMME,
            Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR,
        }
    ),
    Operandentyp.MITTELWERT: frozenset({Profilkennzahltyp.ARITHMETISCHES_MITTEL}),
    Operandentyp.MESSWERTE: frozenset(),
    Operandentyp.ZEITDIFFERENZ_SUMME: frozenset({Profilkennzahltyp.ZEITDIFFERENZ_SUMME}),
    Operandentyp.EINDEUTIGER_WERT: frozenset(),
}


def profilkennzahlen_fuer_operand(
    definition: KpiOperandDefinition,
    basis: KpiDatenbasis,
) -> tuple[ProfilkennzahlReferenz, ...]:
    """Liefert nur mathematisch passende, tatsächlich in R gespeicherte Kennzahlen."""
    if Datenartefakt.DATENPROFIL_R not in definition.zulaessige_quellen:
        return ()
    typen = _KOMPATIBLE_PROFILKENNZAHLEN[definition.operandentyp]
    return tuple(wert for wert in basis.profilkennzahlen if wert.kennzahltyp in typen)


def kompatible_tabellenspalten(
    operandentyp: Operandentyp,
    daten: pd.DataFrame,
) -> tuple[str, ...]:
    """Filtert T/E*-Spalten kontrolliert nach der benötigten mathematischen Operation."""
    if operandentyp is Operandentyp.ANZAHL:
        return tuple(str(wert) for wert in daten.columns)
    kandidaten: list[str] = []
    for name in daten.columns:
        serie = cast("pd.Series", daten[name])
        if operandentyp is Operandentyp.ZEITDIFFERENZ_SUMME:
            if pd.api.types.is_datetime64_any_dtype(serie.dtype):
                kandidaten.append(str(name))
                continue
            if pd.api.types.is_numeric_dtype(serie.dtype):
                continue
            regulaer = serie.dropna()
            if (
                not regulaer.empty
                and pd.to_datetime(regulaer, errors="coerce", utc=True, format="mixed")
                .notna()
                .all()
            ):
                kandidaten.append(str(name))
            continue
        if pd.api.types.is_datetime64_any_dtype(serie.dtype):
            continue
        if pd.api.types.is_numeric_dtype(serie.dtype):
            kandidaten.append(str(name))
            continue
        regulaer = serie.dropna()
        if not regulaer.empty and pd.to_numeric(regulaer, errors="coerce").notna().all():
            kandidaten.append(str(name))
    return tuple(kandidaten)


def zulaessige_quellen_fuer_operand(
    definition: KpiOperandDefinition,
    basis: KpiDatenbasis,
) -> tuple[Datenartefakt, ...]:
    """Schränkt formale Quellen auf die mit den aktuellen Daten tatsächlich nutzbaren ein."""
    ergebnis: list[Datenartefakt] = []
    for quelle in definition.zulaessige_quellen:
        if quelle is Datenartefakt.DATENPROFIL_R:
            if profilkennzahlen_fuer_operand(definition, basis):
                ergebnis.append(quelle)
            continue
        tabelle = (
            basis.zwischendatensatz
            if quelle is Datenartefakt.ZWISCHENDATENSATZ_T
            else basis.event_log
        )
        if kompatible_tabellenspalten(definition.operandentyp, tabelle):
            ergebnis.append(quelle)
        elif (
            definition.operandentyp is Operandentyp.ZEITDIFFERENZ_SUMME
            and quelle is Datenartefakt.EVENT_LOG_E_STERN
            and {"case_id", "activity", "timestamp"} <= set(tabelle.columns)
        ):
            ergebnis.append(quelle)
    return tuple(ergebnis)


def kpi_definition(kpi_id: str) -> KpiDefinition:
    """Liefert ausschließlich eine Definition der systemspezifischen KPI-Matrix."""
    if kpi_id not in KPI_DEFINITIONEN:
        raise KeyError(f"Die KPI-ID {kpi_id} ist nicht in A.7 bis A.10 definiert.")
    return KPI_DEFINITIONEN[kpi_id]


def _dividiere(zaehler: float, nenner: float, faktor: float = 1.0) -> float:
    if not isfinite(zaehler) or not isfinite(nenner):
        raise ValueError("Die fachlichen Rechengrößen müssen endliche Zahlen sein.")
    if nenner == 0:
        raise ZeroDivisionError("Die fachliche Bezugsmenge im Nenner ist null.")
    return zaehler / nenner * faktor


def berechne_kpi_formel(kpi_id: str, operanden: dict[str, Any]) -> tuple[float, str]:
    """Berechnet die mathematische Bedeutung der festen Tabellenformel unverändert."""
    if kpi_id in {
        "einhaltung_lagerbandbreite",
        "servicegrad",
        "verfuegbarkeit_planstarttermin",
        "bestaetigungsquote_kundenwunschtermin",
        "liefertreue",
        "liefertreue_intralogistik",
        "mittlerer_durchfuehrungszeitanteil",
        "anteil_regulaer_abgeschlossener_faelle",
        "first_time_quality_ftq",
        "lieferqualitaetstreue",
        "nacharbeitsquote_rr",
        "reklamationsquote",
        "nutzungseffizienz_ue",
        "ruestzeitanteil",
    }:
        definition = kpi_definition(kpi_id)
        ids = [operand.operand_id for operand in definition.operanden]
        ergebnis = _dividiere(float(operanden[ids[0]]), float(operanden[ids[1]]), 100.0)
    elif kpi_id in {
        "mittlere_durchfuehrungszeit",
        "mittlere_dlz_warenausgang",
        "mittlere_dlz_wareneingang",
        "mittlere_wartezeit_je_foerdereinheit",
        "mittlere_transportzeit_je_warensendung",
        "mittlere_reaktionszeit",
        "kommissionierauftragspositionen_pro_mitarbeiterstunde",
        "mittlere_kosten_produktionslogistik_pro_produktionsauftrag",
        "mittlere_kosten_distributionstaetigkeiten_je_kommissionierauftragsposition",
    }:
        definition = kpi_definition(kpi_id)
        ids = [operand.operand_id for operand in definition.operanden]
        ergebnis = _dividiere(float(operanden[ids[0]]), float(operanden[ids[1]]))
    elif kpi_id == "tatsaechliche_wartezeit_aqt":
        ergebnis = (
            float(operanden["auftragsausfuehrungszeit"])
            - float(operanden["belegungszeit_arbeitseinheit"])
            - float(operanden["transportzeit"])
            - float(operanden["verzoegerungszeit_arbeitseinheit"])
        )
    elif kpi_id == "tatsaechliche_transportzeit_att":
        ergebnis = (
            float(operanden["auftragsausfuehrungszeit"])
            - float(operanden["belegungszeit_arbeitseinheit"])
            - float(operanden["wartezeit"])
            - float(operanden["verzoegerungszeit_arbeitseinheit"])
        )
    elif kpi_id in {
        "standardabweichung_bearbeitungszeit",
        "standardabweichung_dlz_warenausgang",
    }:
        operand_id = (
            "bearbeitungszeit_werte"
            if kpi_id == "standardabweichung_bearbeitungszeit"
            else "dlz_warenausgang_werte"
        )
        werte = tuple(float(wert) for wert in operanden[operand_id])
        if not werte:
            raise ZeroDivisionError("Es liegen keine gültigen Messwerte vor.")
        if not all(isfinite(wert) for wert in werte):
            raise ValueError("Die fachlichen Messwerte müssen endliche Zahlen sein.")
        mittelwert = sum(werte) / len(werte)
        mittlere_quadratische_abweichung = sum((wert - mittelwert) ** 2 for wert in werte) / len(
            werte
        )
        ergebnis = (
            sqrt(mittlere_quadratische_abweichung)
            if kpi_id == "standardabweichung_bearbeitungszeit"
            else mittlere_quadratische_abweichung
        )
    elif kpi_id == "setupzeit_je_kommissionierliste":
        ergebnis = float(operanden["setupzeit_kommissionierliste"])
    elif kpi_id == "bewertete_umschlagshaeufigkeit":
        ergebnis = _dividiere(
            float(operanden["abgang_untersuchungsobjekt"]),
            float(operanden["mittlerer_zugangsbestand"])
            + float(operanden["mittlerer_umlaufbestand"]),
        )
    else:
        kpi_definition(kpi_id)
        raise AssertionError("Für die definierte KPI-ID fehlt die feste Rechenregel.")
    if not isfinite(ergebnis):
        raise ValueError("Das KPI-Ergebnis ist keine endliche Zahl.")
    return ergebnis, kpi_definition(kpi_id).formel


def _tabelle(zuordnung: OperandZuordnung, basis: KpiDatenbasis) -> pd.DataFrame:
    return (
        basis.zwischendatensatz.copy(deep=True)
        if zuordnung.quelle is Datenartefakt.ZWISCHENDATENSATZ_T
        else basis.event_log.copy(deep=True)
    )


def _numerische_serie(daten: pd.DataFrame, spalte: str) -> tuple[pd.Series, int]:
    if not spalte or spalte not in daten.columns:
        raise ValueError(f"Die zugeordnete Spalte '{spalte}' ist nicht vorhanden.")
    original = cast("pd.Series", daten[spalte])
    numerisch = cast("pd.Series", pd.to_numeric(original, errors="coerce"))
    endlich = cast(
        "pd.Series", numerisch.map(lambda wert: pd.notna(wert) and isfinite(float(wert)))
    )
    gueltig = cast("pd.Series", numerisch.where(endlich).dropna())
    return gueltig, int(len(original) - len(gueltig))


def _zeitdifferenzen(daten: pd.DataFrame, zuordnung: OperandZuordnung) -> tuple[pd.Series, int]:
    if zuordnung.startaktivitaet or zuordnung.endaktivitaet:
        if not zuordnung.startaktivitaet or not zuordnung.endaktivitaet:
            raise ValueError("Start- und Endaktivität müssen gemeinsam festgelegt werden.")
        if not {"case_id", "activity", "timestamp"}.issubset(daten.columns):
            raise ValueError("Die Aktivitätsauswahl benötigt case_id, activity und timestamp.")
        kopie = daten.copy(deep=True)
        kopie["timestamp"] = pd.to_datetime(kopie["timestamp"], errors="coerce", utc=True)
        starts = kopie[kopie["activity"].astype("string") == zuordnung.startaktivitaet]
        ends = kopie[kopie["activity"].astype("string") == zuordnung.endaktivitaet]
        startwerte = starts.groupby("case_id", sort=False)["timestamp"].first()
        endwerte = (
            ends.groupby("case_id", sort=False)["timestamp"].last()
            if zuordnung.vorkommensregel is Vorkommensregel.LETZTES
            else ends.groupby("case_id", sort=False)["timestamp"].first()
        )
        gemeinsam = startwerte.to_frame("start").join(endwerte.to_frame("ende"), how="outer")
        differenzen = (gemeinsam["ende"] - gemeinsam["start"]).dt.total_seconds()
        return differenzen.dropna(), int(differenzen.isna().sum())
    if not zuordnung.spalte or not zuordnung.zweite_spalte:
        raise ValueError("Die Zeitdifferenz benötigt zwei ausdrücklich gewählte Zeitspalten.")
    if zuordnung.spalte not in daten or zuordnung.zweite_spalte not in daten:
        raise ValueError("Mindestens eine zugeordnete Zeitspalte ist nicht vorhanden.")
    start = pd.to_datetime(daten[zuordnung.spalte], errors="coerce", utc=True)
    ende = pd.to_datetime(daten[zuordnung.zweite_spalte], errors="coerce", utc=True)
    differenzen = (ende - start).dt.total_seconds()
    return differenzen.dropna(), int(differenzen.isna().sum())


def _operand_ermitteln(
    definition: KpiOperandDefinition,
    zuordnung: OperandZuordnung,
    basis: KpiDatenbasis,
) -> _OperandWert:
    if zuordnung.quelle not in definition.zulaessige_quellen:
        raise ValueError(
            f"{zuordnung.quelle.value} ist für die Rechengröße "
            f"{definition.bezeichnung} nicht zulässig."
        )
    if zuordnung.quelle is Datenartefakt.DATENPROFIL_R:
        aktuelle_nach_id = {wert.referenz_id: wert for wert in basis.profilkennzahlen}
        strukturierte_referenz = zuordnung.profilkennzahl
        if strukturierte_referenz is None and zuordnung.profilreferenz in aktuelle_nach_id:
            strukturierte_referenz = aktuelle_nach_id[zuordnung.profilreferenz]
        if strukturierte_referenz is not None:
            aktuell = aktuelle_nach_id.get(strukturierte_referenz.referenz_id)
            if aktuell is None:
                raise ValueError(
                    "Die strukturierte Profilkennzahl ist im aktuellen R nicht vorhanden."
                )
            if aktuell != strukturierte_referenz:
                raise ValueError(
                    "Die strukturierte Profilkennzahl stimmt nicht mehr mit dem aktuellen "
                    "R überein."
                )
            if aktuell.kennzahltyp not in _KOMPATIBLE_PROFILKENNZAHLEN[definition.operandentyp]:
                raise ValueError(
                    "Die gespeicherte Profilkennzahl entspricht nicht exakt der benötigten "
                    f"Rechengröße {definition.operandentyp.value}."
                )
            ausgeschlossen = max(
                aktuell.grundgesamtheit - aktuell.auswertbare_beobachtungen,
                0,
            )
            return _OperandWert(
                float(aktuell.wert),
                ausgeschlossen,
                {
                    "profilkennzahl": asdict(aktuell),
                    "profilreferenz": aktuell.referenz_id,
                    "ermittelter_wert": float(aktuell.wert),
                    "wert_aus_gespeichertem_r_uebernommen": True,
                },
            )
        if not zuordnung.profilreferenz or zuordnung.profilreferenz not in basis.profilwerte:
            raise ValueError("Die exakt benötigte Profilkennzahl aus R wurde nicht zugeordnet.")
        profilkennzahl = zuordnung.profilreferenz.rsplit(":", 1)[-1]
        erwartete_profilkennzahlen = {
            Operandentyp.ANZAHL: {"gueltige_werte", "zeilen"},
            Operandentyp.SUMME: {"summe"},
            Operandentyp.MITTELWERT: {"mittelwert"},
        }.get(definition.operandentyp, set())
        if profilkennzahl not in erwartete_profilkennzahlen:
            raise ValueError(
                "Die gespeicherte Profilkennzahl entspricht nicht exakt der benötigten "
                f"Rechengröße {definition.operandentyp.value}."
            )
        wert = float(basis.profilwerte[zuordnung.profilreferenz])
        return _OperandWert(
            wert,
            0,
            {
                "profilreferenz": zuordnung.profilreferenz,
                "ermittelter_wert": wert,
                "legacy_profilreferenz": True,
            },
        )

    daten = _tabelle(zuordnung, basis)
    if definition.operandentyp is Operandentyp.ANZAHL:
        if not zuordnung.spalte or zuordnung.spalte not in daten:
            raise ValueError("Für die Zählmenge muss eine vorhandene Spalte gewählt werden.")
        serie = cast("pd.Series", daten[zuordnung.spalte])
        gueltig = serie.notna() & serie.astype("string").str.strip().ne("")
        ausgeschlossen = int((~gueltig).sum())
        if zuordnung.bedingungsoperator:
            vergleich = serie.astype("string") == zuordnung.bedingungswert
            if zuordnung.bedingungsoperator == "ungleich":
                vergleich = ~vergleich
            gueltig &= vergleich
        wert = float(gueltig.sum())
    elif definition.operandentyp in {
        Operandentyp.SUMME,
        Operandentyp.MITTELWERT,
        Operandentyp.EINDEUTIGER_WERT,
    }:
        serie, ausgeschlossen = _numerische_serie(daten, zuordnung.spalte)
        if serie.empty:
            raise ValueError("Die zugeordnete Spalte enthält keine gültigen numerischen Werte.")
        if definition.operandentyp is Operandentyp.SUMME:
            wert = float(serie.sum())
        elif definition.operandentyp is Operandentyp.MITTELWERT:
            wert = float(serie.mean())
        else:
            eindeutige_werte = tuple(float(eintrag) for eintrag in serie.unique())
            if len(eindeutige_werte) != 1:
                raise ValueError(
                    "Die Setupzeit ist nicht für alle betrachteten Kommissionierlisten gleich."
                )
            wert = eindeutige_werte[0]
    elif definition.operandentyp is Operandentyp.MESSWERTE:
        serie, ausgeschlossen = _numerische_serie(daten, zuordnung.spalte)
        if serie.empty:
            raise ValueError("Die zugeordnete Spalte enthält keine gültigen Messwerte.")
        wert = tuple(float(wert) for wert in serie)
    else:
        serie, ausgeschlossen = _zeitdifferenzen(daten, zuordnung)
        if serie.empty:
            raise ValueError("Aus den gewählten Zeitbezügen entsteht keine gültige Zeitdifferenz.")
        wert = float(serie.sum())
    return _OperandWert(
        wert,
        ausgeschlossen,
        {
            "spalte": zuordnung.spalte,
            "zweite_spalte": zuordnung.zweite_spalte,
            "startaktivitaet": zuordnung.startaktivitaet,
            "endaktivitaet": zuordnung.endaktivitaet,
            "bedingungsoperator": zuordnung.bedingungsoperator,
            "bedingungswert": zuordnung.bedingungswert,
            "ermittelter_wert": wert,
        },
    )


def _nicht_berechenbar(
    definition: KpiDefinition,
    konfiguration: KpiKonfiguration | None,
    gruende: list[str],
) -> KpiErgebnis:
    zuordnungen = konfiguration.zuordnungen if konfiguration else ()
    return KpiErgebnis(
        definition.kpi_id,
        definition.bezeichnung,
        KpiStatus.NICHT_BERECHENBAR,
        definition.formel,
        tuple(asdict(wert) for wert in zuordnungen),
        tuple(
            {
                "artefakt": wert.quelle.value,
                "spalte": wert.spalte,
                "profilreferenz": (
                    wert.profilkennzahl.referenz_id
                    if wert.profilkennzahl is not None
                    else wert.profilreferenz
                ),
                "profilkennzahl": (
                    asdict(wert.profilkennzahl) if wert.profilkennzahl is not None else None
                ),
            }
            for wert in zuordnungen
        ),
        tuple(
            {
                "operand_id": wert.operand_id,
                "operator": wert.bedingungsoperator,
                "wert": wert.bedingungswert,
            }
            for wert in zuordnungen
            if wert.bedingungsoperator
        ),
        konfiguration.bezugsmenge if konfiguration else definition.bezugsmenge,
        konfiguration.einheit if konfiguration else definition.einheit,
        0,
        "Keine Berechnung durchgeführt.",
        {},
        None,
        tuple(gruende),
        definitionsversion=definition.definitionsversion,
    )


def berechne_ausgewaehlte_kpis(
    ausgewaehlte_kpi_ids: tuple[str, ...],
    konfigurationen: tuple[KpiKonfiguration, ...],
    basis: KpiDatenbasis,
) -> tuple[KpiErgebnis, ...]:
    """Berechnet nur U-Auswahl; jeder Fehler bleibt auf genau diese KPI begrenzt."""
    nach_id = {wert.kpi_id: wert for wert in konfigurationen}
    ergebnisse: list[KpiErgebnis] = []
    for kpi_id in ausgewaehlte_kpi_ids:
        definition = kpi_definition(kpi_id)
        konfiguration = nach_id.get(kpi_id)
        if konfiguration is None:
            ergebnisse.append(
                _nicht_berechenbar(
                    definition,
                    None,
                    ["Für die ausgewählte Kennzahl wurden keine Operanden zugeordnet."],
                )
            )
            continue
        if definition.einheiteneingabe_erforderlich and not konfiguration.einheit.strip():
            ergebnisse.append(
                _nicht_berechenbar(
                    definition,
                    konfiguration,
                    ["Die fachlich erforderliche Einheit wurde nicht angegeben."],
                )
            )
            continue
        if konfiguration.direkte_profilreferenz or konfiguration.direkte_profilkennzahl:
            referenz = konfiguration.direkte_profilreferenz
            strukturierte_referenz = konfiguration.direkte_profilkennzahl
            aktuelle_nach_id = {wert.referenz_id: wert for wert in basis.profilkennzahlen}
            if strukturierte_referenz is None and referenz in aktuelle_nach_id:
                strukturierte_referenz = aktuelle_nach_id[referenz]
            struktur_gueltig = (
                strukturierte_referenz is not None
                and aktuelle_nach_id.get(strukturierte_referenz.referenz_id)
                == strukturierte_referenz
                and strukturierte_referenz.kennzahltyp is Profilkennzahltyp.ARITHMETISCHES_MITTEL
            )
            legacy_gueltig = (
                bool(referenz)
                and referenz.endswith(":mittelwert")
                and referenz in basis.profilwerte
            )
            if kpi_id not in _DIREKT_AUS_R_UEBERNEHMBARE_MITTELWERTE or not (
                struktur_gueltig or legacy_gueltig
            ):
                ergebnisse.append(
                    _nicht_berechenbar(
                        definition,
                        konfiguration,
                        [
                            "Die direkt gewählte Profilkennzahl entspricht nicht exakt einer "
                            "für diese KPI übernehmbaren arithmetischen Mittelwertgröße."
                        ],
                    )
                )
                continue
            wert = float(
                strukturierte_referenz.wert
                if strukturierte_referenz is not None
                else basis.profilwerte[referenz]
            )
            if not isfinite(wert):
                ergebnisse.append(
                    _nicht_berechenbar(
                        definition,
                        konfiguration,
                        ["Die direkt gewählte Profilkennzahl ist keine endliche Zahl."],
                    )
                )
                continue
            profilreferenz = (
                strukturierte_referenz.referenz_id
                if strukturierte_referenz is not None
                else referenz
            )
            profildokumentation = (
                asdict(strukturierte_referenz)
                if strukturierte_referenz is not None
                else {"profilreferenz": referenz, "legacy_profilreferenz": True}
            )
            ergebnisse.append(
                KpiErgebnis(
                    kpi_id,
                    definition.bezeichnung,
                    KpiStatus.BERECHNET,
                    definition.formel,
                    (
                        {
                            "direkte_profilreferenz": profilreferenz,
                            "profilkennzahl": profildokumentation,
                            "menschlich_bestaetigte_bedeutung": definition.bezeichnung,
                            "ermittelter_wert": wert,
                        },
                    ),
                    (
                        {
                            "artefakt": Datenartefakt.DATENPROFIL_R.value,
                            **basis.referenzen.get(Datenartefakt.DATENPROFIL_R, {}),
                            "profilreferenz": profilreferenz,
                            "profilkennzahl": profildokumentation,
                        },
                    ),
                    (),
                    konfiguration.bezugsmenge or definition.bezugsmenge,
                    konfiguration.einheit or definition.einheit,
                    (
                        max(
                            strukturierte_referenz.grundgesamtheit
                            - strukturierte_referenz.auswertbare_beobachtungen,
                            0,
                        )
                        if strukturierte_referenz is not None
                        else 0
                    ),
                    "Die in R gespeicherte arithmetische Mittelwertgröße wurde nach "
                    "ausdrücklicher fachlicher Bestätigung direkt übernommen.",
                    {"profilmittelwert": wert},
                    wert,
                    definitionsversion=definition.definitionsversion,
                )
            )
            continue
        zuordnungen = {wert.operand_id: wert for wert in konfiguration.zuordnungen}
        fehlend = [
            f"Rechengröße '{operand.bezeichnung}' ist nicht zugeordnet."
            for operand in definition.operanden
            if operand.operand_id not in zuordnungen
        ]
        if fehlend:
            ergebnisse.append(_nicht_berechenbar(definition, konfiguration, fehlend))
            continue
        werte: dict[str, Any] = {}
        dokumentation: list[dict[str, Any]] = []
        ausgeschlossen = 0
        fehler: list[str] = []
        for operand in definition.operanden:
            zuordnung = zuordnungen[operand.operand_id]
            try:
                ermittelt = _operand_ermitteln(operand, zuordnung, basis)
                werte[operand.operand_id] = ermittelt.wert
                ausgeschlossen += ermittelt.ausgeschlossen
                dokumentation.append(
                    {
                        "operand_id": operand.operand_id,
                        "bezeichnung": operand.bezeichnung,
                        "quelle": zuordnung.quelle.value,
                        **ermittelt.dokumentation,
                    }
                )
            except (TypeError, ValueError) as ursache:
                fehler.append(f"{operand.bezeichnung}: {ursache}")
        if fehler:
            ergebnisse.append(_nicht_berechenbar(definition, konfiguration, fehler))
            continue
        try:
            ergebnis, formel = berechne_kpi_formel(kpi_id, werte)
        except (TypeError, ValueError, ZeroDivisionError) as ursache:
            ergebnisse.append(_nicht_berechenbar(definition, konfiguration, [str(ursache)]))
            continue
        quellen = tuple(
            {
                "artefakt": wert.quelle.value,
                **basis.referenzen.get(wert.quelle, {}),
                "spalte": wert.spalte,
                "profilreferenz": (
                    wert.profilkennzahl.referenz_id
                    if wert.profilkennzahl is not None
                    else wert.profilreferenz
                ),
                "profilkennzahl": (
                    asdict(wert.profilkennzahl) if wert.profilkennzahl is not None else None
                ),
            }
            for wert in konfiguration.zuordnungen
        )
        tabellenbedingungen = tuple(
            {
                "operand_id": wert.operand_id,
                "quelle": wert.quelle.value,
                "operator": wert.bedingungsoperator,
                "wert": wert.bedingungswert,
                "in_schritt_7_ausgewertet": True,
            }
            for wert in konfiguration.zuordnungen
            if wert.bedingungsoperator
        )
        profilbedingungen = tuple(
            {
                "operand_id": wert.operand_id,
                "quelle": Datenartefakt.DATENPROFIL_R.value,
                "spalte": wert.profilkennzahl.spaltenname,
                "operator": wert.profilkennzahl.operator,
                "wert": wert.profilkennzahl.vergleichswert,
                "in_schritt_7_ausgewertet": False,
                "bedeutung": "Gespeicherte Indikatorbedingung aus R",
            }
            for wert in konfiguration.zuordnungen
            if wert.profilkennzahl is not None
            and wert.profilkennzahl.kennzahltyp is Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR
        )
        ergebnisse.append(
            KpiErgebnis(
                kpi_id,
                definition.bezeichnung,
                KpiStatus.BERECHNET,
                formel,
                tuple(dokumentation),
                quellen,
                (*tabellenbedingungen, *profilbedingungen),
                konfiguration.bezugsmenge or definition.bezugsmenge,
                konfiguration.einheit or definition.einheit,
                ausgeschlossen,
                f"Feste Formel angewandt: {formel}",
                werte,
                ergebnis,
                definitionsversion=definition.definitionsversion,
            )
        )
    return tuple(ergebnisse)
