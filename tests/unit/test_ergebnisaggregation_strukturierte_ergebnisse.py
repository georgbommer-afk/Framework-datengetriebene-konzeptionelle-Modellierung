"""Reine Schritt-7-Analysen für Ressourcen, Warte- und Zeitdaten."""

import pandas as pd
import pytest

from framework_mvp.application.ergebnisaggregation.strukturierte_ergebnisse import (
    analysiere_ressourcen,
    analysiere_warteschlangen,
    analysiere_zeitbezogene_datenauswahl,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Ressourcenzuordnungsmodus,
    StrukturiertesErgebnisStatus,
)


def test_vollstaendige_kanonische_ressourcen_werden_automatisch_gruppiert() -> None:
    event_log = pd.DataFrame(
        {
            "activity": ["A", "A", "B", "B"],
            "resource": [" M1 ", "M2", "M2", "M2"],
        }
    )

    ergebnis = analysiere_ressourcen(event_log)

    assert ergebnis.modus is Ressourcenzuordnungsmodus.AUTOMATISCH
    assert ergebnis.quellspalte == "resource"
    assert [(wert.aktivitaet, wert.ressourcen) for wert in ergebnis.zuordnungen] == [
        ("A", ("M1", "M2")),
        ("B", ("M2",)),
    ]


def test_unvollstaendige_ressourcen_erfordern_vollstaendige_manuelle_entscheidung() -> None:
    event_log = pd.DataFrame(
        {"activity": ["A", "B"], "resource": ["M1", None]}
    )
    with pytest.raises(Domaenenfehler, match="Es fehlen: B"):
        analysiere_ressourcen(event_log, manuelle_zuordnungen={"A": ["M1"]})

    manuell = analysiere_ressourcen(
        event_log,
        manuelle_zuordnungen={"A": ["M1"], "B": ["Personal"]},
    )
    assert manuell.modus is Ressourcenzuordnungsmodus.MANUELL
    nicht_moeglich = analysiere_ressourcen(
        event_log,
        nicht_moeglich_begruendung="Keine fachlich belastbare Zuordnung vorhanden.",
    )
    assert nicht_moeglich.modus is Ressourcenzuordnungsmodus.NICHT_MOEGLICH
    assert "belastbare" in nicht_moeglich.begruendung


def test_uebergangswartezeiten_sind_start_b_minus_ende_a_mit_ausschluessen() -> None:
    event_log = pd.DataFrame(
        {
            "case_id": ["1", "1", "2", "2", "3", "3", "4", "4"],
            "activity": ["A", "B"] * 4,
            "start_timestamp": pd.to_datetime(
                [
                    "2026-01-01 10:00",
                    "2026-01-01 10:03",
                    "2026-01-01 11:00",
                    "2026-01-01 11:05",
                    "2026-01-01 12:00",
                    "2026-01-01 12:01",
                    "2026-01-01 13:00",
                    None,
                ],
                utc=True,
            ),
            "end_timestamp": pd.to_datetime(
                [
                    "2026-01-01 10:01",
                    "2026-01-01 10:04",
                    "2026-01-01 11:01",
                    "2026-01-01 11:06",
                    "2026-01-01 12:02",
                    "2026-01-01 12:03",
                    "2026-01-01 13:01",
                    "2026-01-01 13:02",
                ],
                utc=True,
            ),
        }
    )

    ergebnis = analysiere_warteschlangen(event_log)

    assert ergebnis.status is StrukturiertesErgebnisStatus.ABLEITBAR
    assert ergebnis.ausgeschlossene_negative_werte == 1
    assert ergebnis.ausgeschlossene_nicht_auswertbare_werte == 1
    statistik = ergebnis.uebergaenge[0].statistik
    assert statistik.anzahl == 2
    assert statistik.mittelwert_sekunden == 180.0
    assert statistik.median_sekunden == 180.0
    assert "Start(B) − Ende(A)" in ergebnis.berechnungsregel


def test_bearbeitungs_und_zwischenankunftszeit_bleiben_getrennt_benannt() -> None:
    event_log = pd.DataFrame(
        {
            "case_id": ["1", "1", "2", "2", "3", "3"],
            "activity": ["A", "B"] * 3,
            "timestamp": pd.to_datetime(
                [
                    "2026-01-01 08:00",
                    "2026-01-01 08:10",
                    "2026-01-01 09:00",
                    "2026-01-01 09:10",
                    "2026-01-01 11:00",
                    "2026-01-01 11:10",
                ],
                utc=True,
            ),
            "start_timestamp": pd.to_datetime(
                [
                    "2026-01-01 08:00",
                    "2026-01-01 08:05",
                    "2026-01-01 09:00",
                    "2026-01-01 09:05",
                    "2026-01-01 11:00",
                    "2026-01-01 11:05",
                ],
                utc=True,
            ),
            "end_timestamp": pd.to_datetime(
                [
                    "2026-01-01 08:02",
                    "2026-01-01 08:07",
                    "2026-01-01 09:02",
                    "2026-01-01 09:07",
                    "2026-01-01 11:02",
                    "2026-01-01 11:07",
                ],
                utc=True,
            ),
        }
    )

    ergebnis = analysiere_zeitbezogene_datenauswahl(
        pd.DataFrame({"rohwert": [1]}), event_log
    )

    assert ergebnis.bestaetigte_datenbasis == ("Q", "R", "T", "E*")
    assert ergebnis.ankunftsregel == (
        "Erster gültiger kanonischer Ereigniszeitstempel E*.timestamp je Fall."
    )
    assert ergebnis.zwischenankunftszeit is not None
    assert ergebnis.zwischenankunftszeit.anzahl == 2
    assert ergebnis.zwischenankunftszeit.median_sekunden == 5400.0
    assert ergebnis.bearbeitungszeiten[0].statistik.median_sekunden == 120.0
    assert ergebnis.uebergangswartezeiten[0].statistik.median_sekunden == 180.0
