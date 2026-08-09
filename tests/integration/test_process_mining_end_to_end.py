"""End-to-End-Tests von Algorithmus 6 für alle drei Prozessnotationen."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
import pytest

from framework_mvp.application.process_mining_service import ProcessMiningService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    DiscoveryKonfiguration,
    DiscoveryVerfahren,
    Freigabestatus,
    Mappingzustand,
    MinerVariante,
    ProcessMiningAnalyse,
    ProcessMiningStatus,
    Prozessnotation,
    Qualitaetsfreigabe,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
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
    def __init__(self, artefakt: Qualitaetsfreigabe, daten: pd.DataFrame) -> None:
        self.artefakt = artefakt
        self.daten = daten

    def freigabe_laden(self, freigabe_id: UUID) -> tuple[Qualitaetsfreigabe, pd.DataFrame]:
        if freigabe_id != self.artefakt.freigabe_id:
            raise Importintegritaetsfehler("Dies ist keine gültige E*-Freigabe.")
        return self.artefakt, self.daten.copy(deep=True)


def _umgebung(
    tmp_path: Path,
) -> tuple[
    ProcessMiningService,
    Qualitaetsfreigabe,
    pd.DataFrame,
    WorkspaceKonfiguration,
    ImportartefaktSpeicher,
    _QualitaetService,
]:
    projekt_id, freigabe_id, event_log_id = uuid4(), uuid4(), uuid4()
    freigabe = Qualitaetsfreigabe(
        freigabe_id,
        projekt_id,
        event_log_id,
        "a" * 64,
        uuid4(),
        "b" * 64,
        uuid4(),
        None,
        "",
        Mappingzustand.NICHT_VORHANDEN,
        (),
        "c" * 64,
        "d" * 64,
        "e" * 64,
        "q.release.json",
        "f" * 64,
        Freigabestatus.FREIGEGEBEN,
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
            "zusatz": [1, 2, 3, 4, 5, 6],
        }
    )
    workspace = WorkspaceKonfiguration.ermitteln(tmp_path / "workspace")
    speicher = ImportartefaktSpeicher(workspace)
    qualitaet = _QualitaetService(freigabe, daten)
    service = ProcessMiningService(
        _AnalyseRepository(),  # type: ignore[arg-type]
        qualitaet,  # type: ignore[arg-type]
        speicher,
    )
    return service, freigabe, daten, workspace, speicher, qualitaet


@pytest.mark.parametrize(
    ("notation", "k", "endung", "variante"),
    (
        (Prozessnotation.PROZESSBAUM, 0.0, ".ptml", MinerVariante.INDUCTIVE_MINER),
        (
            Prozessnotation.PETRINETZ,
            0.15,
            ".pnml",
            MinerVariante.INDUCTIVE_MINER_INFREQUENT,
        ),
        (
            Prozessnotation.BPMN,
            0.4,
            ".bpmn",
            MinerVariante.INDUCTIVE_MINER_INFREQUENT,
        ),
    ),
)
def test_p_und_a_d_speichern_idempotent_laden_und_an_schritt_sieben_uebergeben(
    tmp_path: Path,
    notation: Prozessnotation,
    k: float,
    endung: str,
    variante: MinerVariante,
) -> None:
    service, freigabe, daten, workspace, _, _ = _umgebung(tmp_path)
    vorher = daten.copy(deep=True)
    konfiguration = DiscoveryKonfiguration(k, notation)
    vorschau = service.vorschau(freigabe.freigabe_id, konfiguration)
    analyse_id = uuid4()
    analyse = service.speichern(analyse_id, freigabe.freigabe_id, konfiguration, vorschau)
    assert service.speichern(analyse_id, freigabe.freigabe_id, konfiguration, vorschau) == analyse
    erneut, a_d = service.laden(analyse_id)
    uebergabe, a_d_uebergabe, modell = service.uebergabe_laden(
        analyse_id, freigabe.projekt_id, freigabe.freigabe_id
    )

    assert erneut == analyse == uebergabe
    assert a_d["legacy"] is False
    assert a_d["schwellwert_k"] == k
    assert a_d["miner_variante"] == variante.value
    assert a_d["prozessnotation"] == notation.value
    assert analyse.relativer_modell_pfad.endswith(endung)
    assert modell == a_d["prozessmodell_bytes"] == a_d_uebergabe["prozessmodell_bytes"]
    assert modell.startswith(b"<?xml")
    assert a_d["prozessbaum_bytes"].startswith(b"<?xml")
    assert a_d["event_log_id"] == str(freigabe.event_log_id)
    assert a_d["event_log_sha256"] == freigabe.event_log_sha256
    assert analyse.filter_json == "[]"
    assert analyse.relativer_varianten_pfad == ""
    assert analyse.ereignisanzahl_vorher == analyse.ereignisanzahl_nachher == len(daten)
    assert service.analysen_fuer_freigabe(freigabe.projekt_id, freigabe.freigabe_id) == [analyse]
    assert (workspace.basisverzeichnis / analyse.relativer_ergebnis_pfad).is_file()
    assert (workspace.basisverzeichnis / analyse.relativer_modell_pfad).is_file()
    assert not list(workspace.basisverzeichnis.rglob("*.variants.csv.gz"))
    assert not list(workspace.basisverzeichnis.rglob("*.pickle"))
    pd.testing.assert_frame_equal(daten, vorher, check_dtype=True)


def test_dfg_ist_unabhaengig_von_k_und_beruht_immer_auf_vollstaendigem_e_stern(
    tmp_path: Path,
) -> None:
    service, freigabe, daten, _, _, _ = _umgebung(tmp_path)
    vorher = daten.copy(deep=True)
    ohne_filter = service.vorschau(
        freigabe.freigabe_id,
        DiscoveryKonfiguration(0.0, Prozessnotation.PROZESSBAUM),
    )
    abstrahiert = service.vorschau(
        freigabe.freigabe_id,
        DiscoveryKonfiguration(0.8, Prozessnotation.BPMN),
    )

    assert ohne_filter.dfg == abstrahiert.dfg
    assert [(wert.quelle, wert.ziel, wert.haeufigkeit) for wert in ohne_filter.dfg.kanten] == [
        ("A", "B", 2),
        ("A", "C", 1),
    ]
    pd.testing.assert_frame_equal(daten, vorher, check_dtype=True)


def test_nur_gueltige_projektgebundene_freigabe_ist_zulaessig_und_manipuliertes_p_blockiert(
    tmp_path: Path,
) -> None:
    service, freigabe, _, _, speicher, _ = _umgebung(tmp_path)
    with pytest.raises(Importintegritaetsfehler, match=r"keine gültige E\*-Freigabe"):
        service.grundlage_laden(uuid4())
    with pytest.raises(Domaenenfehler, match="aktuellen Projekt"):
        service.grundlage_laden(freigabe.freigabe_id, uuid4())

    konfiguration = DiscoveryKonfiguration(0.0, Prozessnotation.PETRINETZ)
    vorschau = service.vorschau(freigabe.freigabe_id, konfiguration)
    analyse = service.speichern(uuid4(), freigabe.freigabe_id, konfiguration, vorschau)
    modell_bytes = speicher.lesen(analyse.relativer_modell_pfad)
    speicher.artefakt_ersetzen(analyse.relativer_modell_pfad, b"manipuliert")
    with pytest.raises(Importintegritaetsfehler, match="Prüfsumme"):
        service.laden(analyse.analyse_id)
    speicher.artefakt_ersetzen(analyse.relativer_modell_pfad, modell_bytes)
    a_d_bytes = speicher.lesen(analyse.relativer_ergebnis_pfad)
    speicher.artefakt_ersetzen(analyse.relativer_ergebnis_pfad, a_d_bytes + b" ")
    with pytest.raises(Importintegritaetsfehler, match="A_D"):
        service.laden(analyse.analyse_id)


def test_vorschau_einer_geaenderten_e_stern_kette_wird_vor_speicherung_verworfen(
    tmp_path: Path,
) -> None:
    service, freigabe, _, _, _, qualitaet = _umgebung(tmp_path)
    konfiguration = DiscoveryKonfiguration(0.1, Prozessnotation.PROZESSBAUM)
    vorschau = service.vorschau(freigabe.freigabe_id, konfiguration)
    qualitaet.artefakt = replace(qualitaet.artefakt, event_log_sha256="9" * 64)
    with pytest.raises(Domaenenfehler, match="Vorschau gehört nicht mehr"):
        service.speichern(uuid4(), freigabe.freigabe_id, konfiguration, vorschau)


def test_legacy_analyse_bleibt_lesbar_aber_wird_nicht_als_neues_p_und_a_d_angeboten(
    tmp_path: Path,
) -> None:
    _, freigabe, daten, workspace, speicher, qualitaet = _umgebung(tmp_path)
    repository = _AnalyseRepository()
    analyse_id = uuid4()
    summary_pfad = f"projects/{freigabe.projekt_id}/process_mining/{analyse_id}.summary.json"
    summary = {
        "artefaktversion": 1,
        "analyse_id": str(analyse_id),
        "pruefsummen": {},
        "visualisierungsartefakte": {},
    }
    speicher.artefakt_speichern(summary_pfad, json.dumps(summary).encode())
    jetzt = datetime.now(UTC)
    legacy = ProcessMiningAnalyse(
        analyse_id,
        freigabe.projekt_id,
        freigabe.freigabe_id,
        freigabe.event_log_id,
        '{"legacy":true}',
        '[{"filter":"varianten_top_k"}]',
        DiscoveryVerfahren.HEURISTICS_MINER,
        '{"dependency_threshold":0.5}',
        len(daten),
        3,
        3,
        2,
        4,
        2,
        2,
        1,
        "{}",
        "[]",
        "2.7.23.3",
        summary_pfad,
        "",
        "",
        "legacy.model.pnml",
        "",
        ProcessMiningStatus.AUSGEFUEHRT,
        jetzt,
        jetzt,
    )
    repository.speichern(legacy)
    service = ProcessMiningService(
        repository,  # type: ignore[arg-type]
        qualitaet,  # type: ignore[arg-type]
        ImportartefaktSpeicher(workspace),
    )
    geladen, struktur = service.laden(analyse_id)
    assert geladen == legacy
    assert struktur["legacy"] is True
    assert service.analysen_fuer_freigabe(freigabe.projekt_id, freigabe.freigabe_id) == []
