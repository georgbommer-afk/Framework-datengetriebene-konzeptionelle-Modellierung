"""Fachtests für Gleichungen 3.1 bis 3.5 der Schritt-7-Performanceanalyse."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from framework_mvp.application.ergebnisaggregation.performance import (
    busy_ratio_berechnen,
    performance_zeitvergleich_berechnen,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    BusyRatioKonfiguration,
    PerformanceZeitvergleichKonfiguration,
    Vorkommensregel,
    ZwischenankunftszeitErgebnis,
)


def _performance_konfiguration(**aenderungen) -> PerformanceZeitvergleichKonfiguration:  # type: ignore[no-untyped-def]
    werte = {
        "sollquelle": "extern",
        "soll_case_id_spalte": "fall",
        "soll_activity_spalte": "schritt",
        "ist_case_id_spalte": "case_id",
        "ist_activity_spalte": "activity",
        "plan_ende_spalte": "plan_ende",
        "ist_ende_spalte": "end_timestamp",
        "plan_start_spalte": "plan_start",
        "ist_start_spalte": "start_timestamp",
        "fertigstellungsabweichung_aktiv": True,
        "bearbeitungszeitabweichung_aktiv": True,
    }
    werte.update(aenderungen)
    return PerformanceZeitvergleichKonfiguration(**werte)


def test_dt_und_db_werden_getrennt_nach_gleichung_3_1_und_3_2_berechnet() -> None:
    soll = pd.DataFrame(
        {
            "fall": ["1", "2", "3"],
            "schritt": ["A", "A", "A"],
            "plan_start": ["2026-01-01 08:00", "2026-01-01 09:00", "2026-01-01 10:00"],
            "plan_ende": ["2026-01-01 08:30", "2026-01-01 09:30", "2026-01-01 10:30"],
        }
    )
    ist = pd.DataFrame(
        {
            "case_id": ["1", "2", "3"],
            "activity": ["A", "A", "A"],
            "start_timestamp": pd.to_datetime(
                ["2026-01-01 08:05", "2026-01-01 09:00", "2026-01-01 10:00"], utc=True
            ),
            "end_timestamp": pd.to_datetime(
                ["2026-01-01 08:45", "2026-01-01 09:20", "2026-01-01 10:30"], utc=True
            ),
        }
    )

    ergebnis = performance_zeitvergleich_berechnen(
        soll_daten=soll,
        event_log=ist,
        konfiguration=_performance_konfiguration(),
    )

    assert [wert.fertigstellungsabweichung_dt_sekunden for wert in ergebnis.einzelwerte] == [
        900,
        -600,
        0,
    ]
    assert [wert.klassifikation_dt for wert in ergebnis.einzelwerte] == [
        "verspätet",
        "vorzeitig",
        "planmäßig",
    ]
    assert [wert.bearbeitungszeitabweichung_db_sekunden for wert in ergebnis.einzelwerte] == [
        600,
        -600,
        0,
    ]
    assert [wert.klassifikation_db for wert in ergebnis.einzelwerte] == [
        "länger als geplant",
        "kürzer als geplant",
        "entspricht der geplanten Bearbeitungszeit",
    ]
    assert ergebnis.dt_statistik is not None
    assert ergebnis.dt_statistik.verspaetet == 1
    assert ergebnis.dt_statistik.vorzeitig == 1
    assert ergebnis.dt_statistik.planmaessig == 1
    assert ergebnis.db_statistik is not None
    assert ergebnis.db_statistik.laenger_als_geplant == 1
    assert ergebnis.db_statistik.kuerzer_als_geplant == 1
    assert ergebnis.db_statistik.gleich_geplant == 1


def test_dt_und_db_bleiben_bei_gleicher_dauer_semantisch_getrennt() -> None:
    soll = pd.DataFrame(
        {
            "fall": ["1"],
            "schritt": ["A"],
            "plan_start": ["2026-01-01 08:00"],
            "plan_ende": ["2026-01-01 08:30"],
        }
    )
    ist = pd.DataFrame(
        {
            "case_id": ["1"],
            "activity": ["A"],
            "start_timestamp": ["2026-01-01 08:20"],
            "end_timestamp": ["2026-01-01 08:50"],
        }
    )

    ergebnis = performance_zeitvergleich_berechnen(
        soll_daten=soll,
        event_log=ist,
        konfiguration=_performance_konfiguration(),
    )

    assert ergebnis.einzelwerte[0].fertigstellungsabweichung_dt_sekunden == 1200
    assert ergebnis.einzelwerte[0].bearbeitungszeitabweichung_db_sekunden == 0
    assert "ursache" not in repr(ergebnis).lower()


def test_fehlende_zeitrollen_werden_ausgewiesen_und_nicht_erfunden() -> None:
    soll = pd.DataFrame(
        {
            "fall": ["1", "2"],
            "schritt": ["A", "A"],
            "plan_start": [None, "2026-01-01 09:00"],
            "plan_ende": ["2026-01-01 08:30", "2026-01-01 09:30"],
        }
    )
    ist = pd.DataFrame(
        {
            "case_id": ["1", "2"],
            "activity": ["A", "A"],
            "start_timestamp": ["2026-01-01 08:00", "2026-01-01 09:00"],
            "end_timestamp": ["2026-01-01 08:40", None],
        }
    )

    ergebnis = performance_zeitvergleich_berechnen(
        soll_daten=soll,
        event_log=ist,
        konfiguration=_performance_konfiguration(),
    )

    assert ergebnis.ausschlussgruende["db_zeitwert_fehlt"] == 2
    assert ergebnis.ausschlussgruende["dt_zeitwert_fehlt"] == 1
    assert ergebnis.einzelwerte[0].fertigstellungsabweichung_dt_sekunden == 600
    assert ergebnis.einzelwerte[0].bearbeitungszeitabweichung_db_sekunden is None


def test_fehlende_plan_start_spalte_blockiert_db_mit_konkretem_grund() -> None:
    soll = pd.DataFrame({"fall": ["1"], "schritt": ["A"], "plan_ende": ["2026-01-01 08:30"]})
    ist = pd.DataFrame(
        {
            "case_id": ["1"],
            "activity": ["A"],
            "start_timestamp": ["2026-01-01 08:00"],
            "end_timestamp": ["2026-01-01 08:30"],
        }
    )

    with pytest.raises(Domaenenfehler, match="plan_start"):
        performance_zeitvergleich_berechnen(
            soll_daten=soll,
            event_log=ist,
            konfiguration=_performance_konfiguration(),
        )


def test_wiederholte_aktivitaeten_benoetigen_bestaetigte_auftretensnummer() -> None:
    soll = pd.DataFrame(
        {
            "fall": ["1", "1"],
            "schritt": ["A", "A"],
            "plan_ende": ["2026-01-01 08:10", "2026-01-01 09:10"],
            "nr": [1, 2],
        }
    )
    ist = pd.DataFrame(
        {
            "case_id": ["1", "1"],
            "activity": ["A", "A"],
            "end_timestamp": ["2026-01-01 08:15", "2026-01-01 09:05"],
        }
    )
    ohne_spalte = _performance_konfiguration(
        plan_start_spalte="",
        ist_start_spalte="",
        bearbeitungszeitabweichung_aktiv=False,
        vorkommensregel=Vorkommensregel.AUFTRETENSNUMMER,
    )
    with pytest.raises(Domaenenfehler, match="Auftretensnummer"):
        performance_zeitvergleich_berechnen(
            soll_daten=soll,
            event_log=ist,
            konfiguration=ohne_spalte,
        )
    mit_spalte = _performance_konfiguration(
        plan_start_spalte="",
        ist_start_spalte="",
        bearbeitungszeitabweichung_aktiv=False,
        vorkommensregel=Vorkommensregel.AUFTRETENSNUMMER,
        soll_auftretensnummer_spalte="nr",
    )

    ergebnis = performance_zeitvergleich_berechnen(
        soll_daten=soll,
        event_log=ist,
        konfiguration=mit_spalte,
    )

    assert [wert.auftretensnummer for wert in ergebnis.einzelwerte] == [1, 2]
    assert [wert.fertigstellungsabweichung_dt_sekunden for wert in ergebnis.einzelwerte] == [
        300,
        -300,
    ]


def _busy_log() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["1", "2", "3", "4", "5", "6"],
            "activity": ["A"] * 6,
            "resource": ["M01", "M01", "M02", "M02", "M03", "M03"],
            "start_timestamp": pd.to_datetime(
                [
                    "2026-01-01 08:00",
                    "2026-01-01 08:20",
                    "2026-01-01 09:00",
                    "2026-01-01 09:10",
                    "2026-01-01 10:00",
                    "2026-01-01 10:10",
                ],
                utc=True,
            ),
            "end_timestamp": pd.to_datetime(
                [
                    "2026-01-01 08:10",
                    "2026-01-01 08:30",
                    "2026-01-01 09:15",
                    "2026-01-01 09:20",
                    "2026-01-01 10:10",
                    "2026-01-01 10:20",
                ],
                utc=True,
            ),
        }
    )


def test_busy_ratio_berechnet_gl_3_3_bis_3_5_und_markiert_potenziellen_engpass() -> None:
    ergebnis = busy_ratio_berechnen(
        event_log=_busy_log(),
        konfiguration=BusyRatioKonfiguration("resource", "start_timestamp", "end_timestamp"),
    )

    ratios = {wert.ressource: wert.busy_ratio for wert in ergebnis.einzelwerte}
    assert ratios == {"M01": pytest.approx(0.5), "M02": pytest.approx(1.5), "M03": 1.0}
    assert ergebnis.potenzieller_engpass == "M02"
    m01 = next(wert for wert in ergebnis.ressourcenstatistiken if wert.ressource == "M01")
    assert m01.mittelwert_busy_ratio == pytest.approx(0.5)
    assert m01.median_busy_ratio == pytest.approx(0.5)
    assert ergebnis.ausschlussgruende["keine_nachfolgende_ausfuehrung"] == 3
    assert "potenziellen Rückstau" in ergebnis.berechnungsregel


def test_busy_ratio_schliesst_nullteiler_fehlwerte_und_negative_dauer_aus() -> None:
    log = pd.DataFrame(
        {
            "case_id": ["1", "2", "3", "4", "5"],
            "activity": ["A"] * 5,
            "resource": ["M01", "M01", "M01", None, "M02"],
            "start_timestamp": [
                "2026-01-01 08:00",
                "2026-01-01 08:00",
                "2026-01-01 08:20",
                "2026-01-01 09:00",
                "2026-01-01 10:00",
            ],
            "end_timestamp": [
                "2026-01-01 08:10",
                "2026-01-01 08:05",
                "2026-01-01 08:30",
                "2026-01-01 09:10",
                "2026-01-01 09:50",
            ],
        }
    )

    ergebnis = busy_ratio_berechnen(
        event_log=log,
        konfiguration=BusyRatioKonfiguration("resource", "start_timestamp", "end_timestamp"),
    )

    assert ergebnis.ausschlussgruende["zwischenankunftszeit_null"] == 1
    assert ergebnis.ausschlussgruende["fehlende_ressource"] == 1
    assert ergebnis.ausschlussgruende["negative_bearbeitungszeit"] == 1
    assert all(pd.notna(wert.busy_ratio) for wert in ergebnis.einzelwerte)
    assert all(wert.busy_ratio != float("inf") for wert in ergebnis.einzelwerte)


def test_busy_ratio_ohne_ressourcenspalte_ist_nicht_berechenbar() -> None:
    log = _busy_log().drop(columns="resource")

    with pytest.raises(Domaenenfehler, match="resource"):
        busy_ratio_berechnen(
            event_log=log,
            konfiguration=BusyRatioKonfiguration("resource", "start_timestamp", "end_timestamp"),
        )


def test_eine_auswertbare_ressource_wird_gezeigt_aber_nicht_zum_engpass_erklaert() -> None:
    log = _busy_log().loc[lambda daten: daten["resource"] == "M01"].copy()

    ergebnis = busy_ratio_berechnen(
        event_log=log,
        konfiguration=BusyRatioKonfiguration("resource", "start_timestamp", "end_timestamp"),
    )

    assert ergebnis.ressourcenstatistiken[0].mittelwert_busy_ratio == pytest.approx(0.5)
    assert ergebnis.potenzieller_engpass == ""


def test_busy_ratio_beruecksichtigt_expliziten_zeitraum() -> None:
    log = _busy_log()
    voll = busy_ratio_berechnen(
        event_log=log,
        konfiguration=BusyRatioKonfiguration("resource", "start_timestamp", "end_timestamp"),
    )
    eingeschraenkt = busy_ratio_berechnen(
        event_log=log,
        konfiguration=BusyRatioKonfiguration(
            "resource",
            "start_timestamp",
            "end_timestamp",
            datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 8, 30, tzinfo=UTC),
        ),
    )

    assert len(voll.einzelwerte) == 3
    assert len(eingeschraenkt.einzelwerte) == 1
    assert eingeschraenkt.einzelwerte[0].ressource == "M01"
    assert eingeschraenkt.ausschlussgruende["ausserhalb_betrachtungszeitraum"] == 4


def test_busy_ratio_iat_ist_eigenstaendig_vom_ankunftsstrom_q() -> None:
    ergebnis = busy_ratio_berechnen(
        event_log=_busy_log(),
        konfiguration=BusyRatioKonfiguration("resource", "start_timestamp", "end_timestamp"),
    )

    assert ergebnis.einzelwerte
    assert "ressourcenbezogene_zwischenankunftszeit_sekunden" in repr(ergebnis.einzelwerte[0])
    assert not isinstance(ergebnis, ZwischenankunftszeitErgebnis)
