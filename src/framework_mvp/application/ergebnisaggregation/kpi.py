# pyright: reportAttributeAccessIssue=false
"""Feste KPI-Gleichungen und explizite Operandenzuordnung gemäß A.7 bis A.10."""

from dataclasses import asdict, dataclass
from math import sqrt
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


def _definition(
    kpi_id: str,
    bezeichnung: str,
    formel: str,
    operanden: tuple[KpiOperandDefinition, ...],
    einheit: str,
    bezugsmenge: str,
    *,
    einheit_eingeben: bool = False,
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
    )


KPI_DEFINITIONEN: dict[str, KpiDefinition] = {
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
        "√(Σ (DLZ_i − Mittlere DLZ)² / Anzahl Lieferscheinpositionen)",
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
    "nacharbeitsquote_rr": _definition(
        "nacharbeitsquote_rr",
        "Nacharbeitsquote (RR)",
        "Anzahl Nacharbeiten / Anzahl verarbeitete Menge · 100",
        (
            _operand("nacharbeiten", "Nacharbeiten", Operandentyp.ANZAHL),
            _operand("verarbeitete_menge", "verarbeitete Menge", Operandentyp.SUMME),
        ),
        "%",
        "verarbeitete Menge",
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
}

_DIREKT_AUS_R_UEBERNEHMBARE_MITTELWERTE = {
    "mittlere_dlz_warenausgang",
    "mittlere_dlz_wareneingang",
    "mittlere_transportzeit_je_warensendung",
    "mittlere_reaktionszeit",
    "mittlere_kosten_produktionslogistik_pro_produktionsauftrag",
}


@dataclass(frozen=True, slots=True)
class KpiDatenbasis:
    """Tiefe Arbeitskopien und exakt bezeichnete Werte aus R."""

    zwischendatensatz: pd.DataFrame
    event_log: pd.DataFrame
    profilwerte: dict[str, float]
    referenzen: dict[Datenartefakt, dict[str, str]]


@dataclass(frozen=True, slots=True)
class _OperandWert:
    wert: float | tuple[float, ...]
    ausgeschlossen: int
    dokumentation: dict[str, Any]


def kpi_definition(kpi_id: str) -> KpiDefinition:
    """Liefert ausschließlich eine der 16 festen Definitionen."""
    if kpi_id not in KPI_DEFINITIONEN:
        raise KeyError(f"Die KPI-ID {kpi_id} ist nicht in A.7 bis A.10 definiert.")
    return KPI_DEFINITIONEN[kpi_id]


def _dividiere(zaehler: float, nenner: float, faktor: float = 1.0) -> float:
    if nenner == 0:
        raise ZeroDivisionError("Die fachliche Bezugsmenge im Nenner ist null.")
    return zaehler / nenner * faktor


def berechne_kpi_formel(kpi_id: str, operanden: dict[str, Any]) -> tuple[float, str]:
    """Berechnet die mathematische Bedeutung der festen Tabellenformel unverändert."""
    if kpi_id in {
        "servicegrad",
        "verfuegbarkeit_planstarttermin",
        "liefertreue",
        "anteil_regulaer_abgeschlossener_faelle",
        "lieferqualitaetstreue",
        "nacharbeitsquote_rr",
        "nutzungseffizienz_ue",
        "ruestzeitanteil",
    }:
        definition = kpi_definition(kpi_id)
        ids = [operand.operand_id for operand in definition.operanden]
        ergebnis = _dividiere(float(operanden[ids[0]]), float(operanden[ids[1]]), 100.0)
    elif kpi_id in {
        "mittlere_dlz_warenausgang",
        "mittlere_dlz_wareneingang",
        "mittlere_transportzeit_je_warensendung",
        "mittlere_reaktionszeit",
        "mittlere_kosten_produktionslogistik_pro_produktionsauftrag",
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
    elif kpi_id == "standardabweichung_dlz_warenausgang":
        werte = tuple(float(wert) for wert in operanden["dlz_warenausgang_werte"])
        if not werte:
            raise ZeroDivisionError("Es liegen keine gültigen DLZ-Werte vor.")
        mittelwert = sum(werte) / len(werte)
        ergebnis = sqrt(sum((wert - mittelwert) ** 2 for wert in werte) / len(werte))
    elif kpi_id == "bewertete_umschlagshaeufigkeit":
        ergebnis = _dividiere(
            float(operanden["abgang_untersuchungsobjekt"]),
            float(operanden["mittlerer_zugangsbestand"])
            + float(operanden["mittlerer_umlaufbestand"]),
        )
    else:
        kpi_definition(kpi_id)
        raise AssertionError("Für die definierte KPI-ID fehlt die feste Rechenregel.")
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
    numerisch = pd.to_numeric(original, errors="coerce")
    gueltig = cast("pd.Series", numerisch.dropna())
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
        if not zuordnung.profilreferenz or zuordnung.profilreferenz not in basis.profilwerte:
            raise ValueError("Die exakt benötigte Profilkennzahl aus R wurde nicht zugeordnet.")
        if definition.operandentyp is Operandentyp.MESSWERTE:
            raise ValueError("R enthält keine Einzelwerte für diese weiterführende Berechnung.")
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
            {"profilreferenz": zuordnung.profilreferenz, "wert": wert},
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
    elif definition.operandentyp in {Operandentyp.SUMME, Operandentyp.MITTELWERT}:
        serie, ausgeschlossen = _numerische_serie(daten, zuordnung.spalte)
        if serie.empty:
            raise ValueError("Die zugeordnete Spalte enthält keine gültigen numerischen Werte.")
        wert = float(serie.sum() if definition.operandentyp is Operandentyp.SUMME else serie.mean())
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
                "profilreferenz": wert.profilreferenz,
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
                    ["Die fachlich erforderliche Zeiteinheit wurde nicht angegeben."],
                )
            )
            continue
        if konfiguration.direkte_profilreferenz:
            referenz = konfiguration.direkte_profilreferenz
            if (
                kpi_id not in _DIREKT_AUS_R_UEBERNEHMBARE_MITTELWERTE
                or not referenz.endswith(":mittelwert")
                or referenz not in basis.profilwerte
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
            wert = float(basis.profilwerte[referenz])
            ergebnisse.append(
                KpiErgebnis(
                    kpi_id,
                    definition.bezeichnung,
                    KpiStatus.BERECHNET,
                    definition.formel,
                    (
                        {
                            "direkte_profilreferenz": referenz,
                            "menschlich_bestaetigte_bedeutung": definition.bezeichnung,
                        },
                    ),
                    (
                        {
                            "artefakt": Datenartefakt.DATENPROFIL_R.value,
                            **basis.referenzen.get(Datenartefakt.DATENPROFIL_R, {}),
                            "profilreferenz": referenz,
                        },
                    ),
                    (),
                    konfiguration.bezugsmenge or definition.bezugsmenge,
                    konfiguration.einheit or definition.einheit,
                    0,
                    "Die in R gespeicherte arithmetische Mittelwertgröße wurde nach "
                    "ausdrücklicher fachlicher Bestätigung direkt übernommen.",
                    {"profilmittelwert": wert},
                    wert,
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
                "profilreferenz": wert.profilreferenz,
            }
            for wert in konfiguration.zuordnungen
        )
        bedingungen = tuple(
            {
                "operand_id": wert.operand_id,
                "operator": wert.bedingungsoperator,
                "wert": wert.bedingungswert,
            }
            for wert in konfiguration.zuordnungen
            if wert.bedingungsoperator
        )
        ergebnisse.append(
            KpiErgebnis(
                kpi_id,
                definition.bezeichnung,
                KpiStatus.BERECHNET,
                formel,
                tuple(dokumentation),
                quellen,
                bedingungen,
                konfiguration.bezugsmenge or definition.bezugsmenge,
                konfiguration.einheit or definition.einheit,
                ausgeschlossen,
                f"Feste Formel angewandt: {formel}",
                werte,
                ergebnis,
            )
        )
    return tuple(ergebnisse)
