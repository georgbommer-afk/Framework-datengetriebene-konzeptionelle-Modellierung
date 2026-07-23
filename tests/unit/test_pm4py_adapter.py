"""Tests der getrennten PM4Py-Integrationsschicht."""

import pandas as pd
import pytest

from framework_mvp.application.process_mining import Pm4pyAdapter
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import DiscoveryKonfiguration, DiscoveryVerfahren


def _log() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["1", "1", "2", "2"],
            "activity": ["A", "B", "A", "C"],
            "timestamp": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-01", "2025-01-03"], utc=True
            ),
            "resource": ["R1", "R2", "R1", "R3"],
        }
    )


def test_pm4py_arbeitskopie_version_und_attribute() -> None:
    """Kanonische Namen werden nur in einer attributtreuen Kopie übersetzt."""
    adapter = Pm4pyAdapter()
    original = _log()
    vorher = original.copy(deep=True)
    kopie = adapter.arbeitskopie(original)
    assert adapter.version
    assert {"case:concept:name", "concept:name", "time:timestamp", "resource"} <= set(kopie)
    assert "case_id" not in kopie
    pd.testing.assert_frame_equal(original, vorher)


def test_ungueltige_pflichtspalten_werden_abgelehnt() -> None:
    """PM4Py erhält niemals ein technisch ungültiges Log."""
    with pytest.raises(Domaenenfehler, match="Pflichtspalten"):
        Pm4pyAdapter().arbeitskopie(_log().drop(columns="case_id"))


@pytest.mark.parametrize(
    "konfiguration",
    [
        DiscoveryKonfiguration(DiscoveryVerfahren.INDUCTIVE_MINER, noise_threshold=0.2),
        DiscoveryKonfiguration(
            DiscoveryVerfahren.HEURISTICS_MINER,
            dependency_threshold=0.5,
            and_threshold=0.65,
            loop_two_threshold=0.5,
        ),
    ],
)
def test_discovery_erzeugt_petri_netz_markierungen_statistik_und_pnml(
    konfiguration: DiscoveryKonfiguration,
) -> None:
    """Beide freigegebenen Verfahren liefern ein portables PNML-Artefakt."""
    ergebnis = Pm4pyAdapter().entdecken(_log(), konfiguration)
    assert ergebnis.netz is not None
    assert ergebnis.initial_marking is not None
    assert ergebnis.final_marking is not None
    assert ergebnis.ergebnisse.pnml.startswith(b"<?xml")
    assert ergebnis.ergebnisse.statistik.stellen > 0
    assert ergebnis.ergebnisse.statistik.kanten > 0
    if konfiguration.verfahren is DiscoveryVerfahren.INDUCTIVE_MINER:
        assert ergebnis.ergebnisse.process_tree_ptml is not None
        assert ergebnis.ergebnisse.process_tree_svg is not None
    assert ergebnis.ergebnisse.modell_svg is not None


def test_visualisierungsfehler_verwirft_discovery_nicht(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PNML und Modellstatistik bleiben bei einem isolierten SVG-Fehler erhalten."""
    adapter = Pm4pyAdapter()

    def fehlerhafte_svg_ausgabe(_graph: object) -> bytes:
        raise OSError("Graphviz absichtlich nicht verfügbar")

    monkeypatch.setattr(adapter, "_graph_svg", fehlerhafte_svg_ausgabe)
    ergebnis = adapter.entdecken(_log(), DiscoveryKonfiguration(DiscoveryVerfahren.INDUCTIVE_MINER))
    assert ergebnis.ergebnisse.pnml.startswith(b"<?xml")
    assert ergebnis.ergebnisse.modell_svg is None
    assert ergebnis.ergebnisse.process_tree_svg is None
    assert len(ergebnis.ergebnisse.warnungen) == 2
