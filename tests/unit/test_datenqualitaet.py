"""Unit-Tests verpflichtender Qualitätsregeln und Maßnahmen."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd

from framework_mvp.application.datenqualitaet import (
    filtere_befunde,
    pruefe_event_log,
    standardregeln,
    wende_massnahmen_an,
)
from framework_mvp.domain.models import (
    Massnahmenaktion,
    Qualitaetsmassnahme,
    Qualitaetsmassnahmenplan,
    Schweregrad,
)


def _daten() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["A", "A", "A", "B", ""],
            "activity": ["Start", "Start", "Ende", "Solo", ""],
            "timestamp": pd.to_datetime(
                ["2025-01-02", "2025-01-01", "2025-01-01", "2025-01-01", None]
            ),
            "start_timestamp": pd.to_datetime(
                ["2025-01-02", "2025-01-03", "2025-01-01", "2025-01-01", None]
            ),
            "end_timestamp": pd.to_datetime(
                ["2025-01-02", "2025-01-02", "2025-01-01", "2025-01-01", None]
            ),
            "event_id": ["1", "1", "3", "4", "5"],
            "_source_row": [0, 1, 2, 3, 4],
            "lifecycle": ["start", "complete", "complete", "complete", "unbekannt"],
            "case_variant": ["x", "y", "x", "z", "q"],
        }
    )


def test_pflicht_duplikat_zeit_lifecycle_und_fallregeln() -> None:
    """Die verpflichtenden Regelgruppen erzeugen typisierte Befunde."""
    ergebnis = pruefe_event_log(_daten(), standardregeln())
    ids = {wert.regel_id for wert in ergebnis.befunde}
    assert {
        "fehlende_fall_id",
        "fehlende_aktivitaet",
        "fehlender_zeitstempel",
        "doppelte_event_id",
        "start_nach_ende",
        "negative_dauer",
        "ruecklaeufige_zeit",
        "identische_zeit",
        "einzelereignis",
        "wechselndes_fallattribut",
        "lifecycle_paarung",
    } <= ids
    assert (
        next(wert for wert in ergebnis.befunde if wert.regel_id == "doppelte_event_id").schweregrad
        is Schweregrad.BLOCKIEREND
    )


def test_massnahmenplan_veraendert_nur_arbeitskopie_und_prueft_erneut() -> None:
    """Explizites Ausschließen erhält das Original und reduziert die Arbeitskopie."""
    original = _daten()
    vorher = original.copy(deep=True)
    massnahme = Qualitaetsmassnahme(
        uuid4(),
        "fehlende_fall_id",
        Massnahmenaktion.EREIGNISSE_AUSSCHLIESSEN,
        json.dumps({}),
        "Leere Zeile ausschließen",
        1,
        datetime.now(UTC),
        1,
    )
    ergebnis = wende_massnahmen_an(
        original, Qualitaetsmassnahmenplan((massnahme,)), standardregeln()
    )
    pd.testing.assert_frame_equal(original, vorher)
    assert len(ergebnis.daten) == 4
    assert "fehlende_fall_id" not in {wert.regel_id for wert in ergebnis.pruefung.befunde}


def test_identische_ereignisse_extreme_zeiten_seltene_aktivitaet_und_filter() -> None:
    """Duplikat-, IQR- und Seltenheitsregeln sind gemeinsam filterbar."""
    zeit = pd.to_datetime(
        [
            "2025-01-01",
            "2025-01-01 00:01",
            "2025-01-01 00:02",
            "2025-01-01 00:03",
            "2025-03-01",
        ],
        format="mixed",
    )
    daten = pd.DataFrame(
        {
            "case_id": ["A"] * 5,
            "activity": ["Regel", "Regel", "Regel", "Regel", "Selten"],
            "timestamp": zeit,
            "start_timestamp": zeit,
            "end_timestamp": zeit + pd.to_timedelta([1, 1, 1, 1, 10000], unit="s"),
            "event_id": ["1", "2", "3", "4", "5"],
            "_source_row": [0, 1, 2, 3, 4],
        }
    )
    regeln = tuple(
        replace(
            wert,
            parameter_json=json.dumps({"anteil": 0.3}),
        )
        if wert.regel_id == "seltene_aktivitaet"
        else wert
        for wert in standardregeln()
    )
    ergebnis = pruefe_event_log(daten, regeln)
    ids = {wert.regel_id for wert in ergebnis.befunde}
    assert {"extreme_wartezeit", "extreme_dauer", "seltene_aktivitaet"} <= ids
    gefiltert = filtere_befunde(
        ergebnis.befunde,
        dimensionen=("Zeitliche Plausibilität",),
        schweregrade=("Warnung",),
        spalten=("timestamp",),
    )
    assert {wert.regel_id for wert in gefiltert} == {"extreme_wartezeit"}

    doppelt = pd.concat([daten.iloc[[0]], daten.iloc[[0]]], ignore_index=True)
    doppelergebnis = pruefe_event_log(doppelt, standardregeln())
    assert "identische_ereignisse" in {wert.regel_id for wert in doppelergebnis.befunde}
