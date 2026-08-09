"""Tests der getrennten PM4Py-Integrationsschicht."""

import pandas as pd
import pm4py
import pytest

from framework_mvp.application.process_mining import Pm4pyAdapter
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    DiscoveryKonfiguration,
    MinerVariante,
    Prozessnotation,
)


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


@pytest.mark.parametrize("k", [-0.01, 1.01])
def test_schwellwert_k_ist_auf_null_bis_eins_begrenzt(k: float) -> None:
    with pytest.raises(Domaenenfehler, match="zwischen 0 und 1"):
        DiscoveryKonfiguration(k, Prozessnotation.PROZESSBAUM)


@pytest.mark.parametrize(
    "konfiguration",
    [
        DiscoveryKonfiguration(0.0, Prozessnotation.PROZESSBAUM),
        DiscoveryKonfiguration(0.2, Prozessnotation.PETRINETZ),
        DiscoveryKonfiguration(0.4, Prozessnotation.BPMN),
    ],
)
def test_discovery_erzeugt_alle_drei_notationen_aus_einem_prozessbaum(
    konfiguration: DiscoveryKonfiguration,
) -> None:
    """PTML, PNML und BPMN-XML entstehen reproduzierbar aus derselben PT-Grundlage."""
    ergebnis = Pm4pyAdapter().entdecken(_log(), konfiguration)
    assert ergebnis.prozessbaum is not None
    assert ergebnis.prozessmodell is not None
    assert ergebnis.ergebnisse.prozessmodell.startswith(b"<?xml")
    assert ergebnis.ergebnisse.prozessbaum_ptml.startswith(b"<?xml")
    assert ergebnis.ergebnisse.statistik.stellen > 0
    assert ergebnis.ergebnisse.statistik.kanten > 0
    assert ergebnis.ergebnisse.prozessnotation is konfiguration.prozessnotation
    assert ergebnis.ergebnisse.miner_variante is konfiguration.miner_variante
    assert ergebnis.ergebnisse.prozessbaum_svg is not None
    assert ergebnis.ergebnisse.modell_svg is not None


@pytest.mark.parametrize(
    ("k", "variante"),
    (
        (0.0, MinerVariante.INDUCTIVE_MINER),
        (0.01, MinerVariante.INDUCTIVE_MINER_INFREQUENT),
        (1.0, MinerVariante.INDUCTIVE_MINER_INFREQUENT),
    ),
)
def test_k_bestimmt_miner_variante_und_prozessbaum_wird_genau_einmal_erzeugt(
    monkeypatch: pytest.MonkeyPatch,
    k: float,
    variante: MinerVariante,
) -> None:
    original = pm4py.discover_process_tree_inductive
    aufrufe: list[float] = []

    def entdecken(log: pd.DataFrame, *, noise_threshold: float):  # type: ignore[no-untyped-def]
        aufrufe.append(noise_threshold)
        return original(log, noise_threshold=noise_threshold)

    monkeypatch.setattr(pm4py, "discover_process_tree_inductive", entdecken)
    konfiguration = DiscoveryKonfiguration(k, Prozessnotation.PROZESSBAUM)
    ergebnis = Pm4pyAdapter().entdecken(_log(), konfiguration)
    assert aufrufe == [k]
    assert ergebnis.ergebnisse.miner_variante is variante


def test_visualisierungsfehler_verwirft_discovery_nicht(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BPMN und Modellstatistik bleiben bei isolierten SVG-Fehlern erhalten."""
    adapter = Pm4pyAdapter()

    def fehlerhafte_svg_ausgabe(_graph: object) -> bytes:
        raise OSError("Graphviz absichtlich nicht verfügbar")

    monkeypatch.setattr(adapter, "_graph_svg", fehlerhafte_svg_ausgabe)
    ergebnis = adapter.entdecken(_log(), DiscoveryKonfiguration(0.2, Prozessnotation.BPMN))
    assert ergebnis.ergebnisse.prozessmodell.startswith(b"<?xml")
    assert ergebnis.ergebnisse.modell_svg is None
    assert ergebnis.ergebnisse.prozessbaum_svg is None
    assert len(ergebnis.ergebnisse.warnungen) == 2
