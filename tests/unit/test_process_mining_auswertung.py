"""Tests für Varianten, DFG und nicht mutierende Analysesichten."""

import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from framework_mvp.application.process_mining import (
    berechne_dfg,
    berechne_varianten,
    filtere_analysesicht,
    filtere_dfg_darstellung,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import ProcessMiningFilter, ProcessMiningFiltertyp


def _log() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["2", "1", "3", "1", "2", "3", "3"],
            "activity": ["A", "A", "A", "B", "B", "C", "B"],
            "timestamp": [
                "2025-01-01T00:00:00Z",
                "2025-01-01T00:00:00Z",
                "2025-01-01T00:00:00Z",
                "2025-01-02T00:00:00Z",
                "2025-01-02T00:00:00Z",
                "2025-01-02T00:00:00Z",
                "2025-01-03T00:00:00Z",
            ],
            "zusatz": list("abcdefg"),
        }
    )


def _filter(typ: ProcessMiningFiltertyp, parameter: dict[str, object]) -> ProcessMiningFilter:
    return ProcessMiningFilter(typ, json.dumps(parameter), "{}", "", datetime.now(UTC))


def test_grundauswertung_und_stabile_varianten() -> None:
    """Alle geforderten Häufigkeiten und kumulierten Anteile sind reproduzierbar."""
    ergebnis = berechne_varianten(_log())
    assert (ergebnis.ereignisanzahl, ergebnis.fallanzahl) == (7, 3)
    assert (ergebnis.aktivitaetsanzahl, ergebnis.variantenanzahl) == (3, 2)
    assert ergebnis.minimale_ereignisse_je_fall == 2
    assert ergebnis.maximale_ereignisse_je_fall == 3
    assert ergebnis.aktivitaetshaeufigkeiten == (("A", 3), ("B", 3), ("C", 1))
    assert ergebnis.startaktivitaeten == (("A", 3),)
    assert ergebnis.endaktivitaeten == (("B", 3),)
    assert ergebnis.varianten[0].aktivitaetsfolge == ("A", "B")
    assert ergebnis.varianten[0].fallanzahl == 2
    assert ergebnis.varianten[-1].kumulierter_anteil == pytest.approx(1.0)


def test_dfg_und_reiner_darstellungsfilter() -> None:
    """DFG-Häufigkeiten stimmen; sein Darstellungsfilter verändert keine Daten."""
    original = _log()
    vorher = original.copy(deep=True)
    dfg = berechne_dfg(original)
    assert [(k.quelle, k.ziel, k.haeufigkeit) for k in dfg.kanten] == [
        ("A", "B", 2),
        ("A", "C", 1),
        ("C", "B", 1),
    ]
    reduziert = filtere_dfg_darstellung(dfg, mindesthaeufigkeit=2)
    assert len(reduziert.kanten) == 1
    pd.testing.assert_frame_equal(original, vorher)


def test_top_k_abdeckung_und_aktivitaetsfilter_arbeiten_auf_kopie() -> None:
    """Filter dokumentieren ihre Wirkung und lassen den Ursprung unverändert."""
    original = _log()
    vorher = original.copy(deep=True)
    top = filtere_analysesicht(
        original, (_filter(ProcessMiningFiltertyp.VARIANTEN_TOP_K, {"k": 1}),)
    )
    assert top.nachher.fallanzahl == 2
    assert top.fallabdeckung == pytest.approx(2 / 3)
    abdeckung = filtere_analysesicht(
        original,
        (
            _filter(
                ProcessMiningFiltertyp.VARIANTEN_ABDECKUNG,
                {"abdeckung": 0.8},
            ),
        ),
    )
    assert abdeckung.nachher.fallanzahl == 3
    aktivitaet = filtere_analysesicht(
        original,
        (_filter(ProcessMiningFiltertyp.AKTIVITAETEN, {"aktivitaeten": ["A"]}),),
    )
    assert aktivitaet.nachher.ereignisanzahl == 3
    pd.testing.assert_frame_equal(original, vorher)


def test_vollstaendige_entfernung_wird_abgelehnt() -> None:
    """Eine leere Analysesicht kann nicht entdeckt werden."""
    with pytest.raises(Domaenenfehler, match="keine analysierbaren Fälle"):
        filtere_analysesicht(
            _log(),
            (_filter(ProcessMiningFiltertyp.AKTIVITAETEN, {"aktivitaeten": []}),),
        )
