"""End-to-End-Tests für beide Process-Discovery-Verfahren."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
import pytest

from framework_mvp.application.process_mining_service import ProcessMiningService
from framework_mvp.domain.models import (
    DiscoveryKonfiguration,
    DiscoveryVerfahren,
    ProcessMiningAnalyse,
    ProcessMiningFilter,
    ProcessMiningFiltertyp,
    ProcessMiningKonfiguration,
    QualitaetspruefungArtefakt,
)
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.workspace import WorkspaceKonfiguration


class _AnalyseRepository:
    def __init__(self) -> None:
        self.analysen: dict[UUID, ProcessMiningAnalyse] = {}

    def speichern(self, analyse: ProcessMiningAnalyse) -> None:
        self.analysen.setdefault(analyse.analyse_id, analyse)

    def laden(self, analyse_id: UUID) -> ProcessMiningAnalyse | None:
        return self.analysen.get(analyse_id)

    def fuer_projekt(self, projekt_id: UUID) -> list[ProcessMiningAnalyse]:
        return [wert for wert in self.analysen.values() if wert.projekt_id == projekt_id]


class _QualitaetService:
    def __init__(self, artefakt: QualitaetspruefungArtefakt, daten: pd.DataFrame) -> None:
        self.artefakt = artefakt
        self.daten = daten

    def laden(self, quality_run_id: UUID) -> tuple[QualitaetspruefungArtefakt, pd.DataFrame]:
        assert quality_run_id == self.artefakt.quality_run_id
        return self.artefakt, self.daten.copy(deep=True)


@pytest.mark.parametrize(
    "verfahren",
    [DiscoveryVerfahren.INDUCTIVE_MINER, DiscoveryVerfahren.HEURISTICS_MINER],
)
def test_discovery_filtern_speichern_und_erneut_oeffnen(
    tmp_path: Path, verfahren: DiscoveryVerfahren
) -> None:
    """Beide Miner erzeugen prüfbare portable Artefakte mit denselben Kennzahlen."""
    projekt_id = uuid4()
    quality_id = uuid4()
    event_log_id = uuid4()
    artefakt = QualitaetspruefungArtefakt(
        quality_id,
        projekt_id,
        event_log_id,
        "q.report.json",
        "q.measures.json",
        "q.csv.gz",
        "a" * 64,
        datetime.now(UTC),
    )
    daten = pd.DataFrame(
        {
            "case_id": ["1", "1", "2", "2", "3", "3"],
            "activity": ["A", "B", "A", "B", "A", "C"],
            "timestamp": pd.to_datetime(
                [
                    "2025-01-01",
                    "2025-01-02",
                    "2025-01-01",
                    "2025-01-03",
                    "2025-01-01",
                    "2025-01-04",
                ],
                utc=True,
            ),
        }
    )
    filter = ProcessMiningFilter(
        ProcessMiningFiltertyp.VARIANTEN_TOP_K,
        '{"k":1}',
        "{}",
        "Häufigste Variante analysieren",
        datetime.now(UTC),
    )
    konfiguration = ProcessMiningKonfiguration(DiscoveryKonfiguration(verfahren), (filter,))
    repository = _AnalyseRepository()
    workspace = WorkspaceKonfiguration.ermitteln(tmp_path / "workspace")
    service = ProcessMiningService(
        repository,  # type: ignore[arg-type]
        _QualitaetService(artefakt, daten),  # type: ignore[arg-type]
        ImportartefaktSpeicher(workspace),
    )
    vorschau = service.vorschau(quality_id, konfiguration)
    analyse = service.speichern(uuid4(), quality_id, konfiguration, vorschau)
    erneut, summary = service.laden(analyse.analyse_id)
    assert erneut == analyse
    assert summary["parameter"]["verfahren"] == verfahren.value
    assert analyse.fallanzahl_vorher == 3
    assert analyse.fallanzahl_nachher == 2
    assert service.fuer_projekt(projekt_id) == [analyse]
    assert (workspace.basisverzeichnis / analyse.relativer_modell_pfad).is_file()
    svg_artefakte = summary["visualisierungsartefakte"]
    assert svg_artefakte["dfg_svg"]
    assert svg_artefakte["modell_svg"]
    if verfahren is DiscoveryVerfahren.INDUCTIVE_MINER:
        assert svg_artefakte["process_tree_svg"]
    for pfad in (wert for wert in svg_artefakte.values() if wert):
        inhalt = (workspace.basisverzeichnis / pfad).read_bytes()
        assert b"<svg" in inhalt
        assert summary["pruefsummen"][pfad]
    erneut_ohne_discovery, summary_erneut = service.laden(analyse.analyse_id)
    assert erneut_ohne_discovery == analyse
    assert summary_erneut["svg_texte"]["dfg_svg"].lstrip().startswith("<?xml")
    assert not list(workspace.basisverzeichnis.rglob("*.pickle"))
