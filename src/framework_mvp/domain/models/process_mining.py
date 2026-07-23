"""Unveränderliche Domänenmodelle für Process Discovery."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from framework_mvp.domain.exceptions import Domaenenfehler


class ProcessMiningStatus(StrEnum):
    """Status einer Process-Mining-Analyse."""

    ENTWURF = "entwurf"
    AUSGEFUEHRT = "ausgefuehrt"
    FEHLGESCHLAGEN = "fehlgeschlagen"


class DiscoveryVerfahren(StrEnum):
    """Im MVP unterstützte Discovery-Verfahren."""

    INDUCTIVE_MINER = "inductive_miner"
    HEURISTICS_MINER = "heuristics_miner"


class ProcessMiningFiltertyp(StrEnum):
    """Unterstützte Filter einer Analysesicht."""

    KEIN_FILTER = "kein_filter"
    VARIANTEN_TOP_K = "varianten_top_k"
    VARIANTEN_ABDECKUNG = "varianten_abdeckung"
    AKTIVITAETEN = "aktivitaeten"
    DFG_DARSTELLUNG = "dfg_darstellung"


@dataclass(frozen=True, slots=True)
class ProcessMiningFilter:
    """Dokumentierte Filterentscheidung und deren Wirkung."""

    filtertyp: ProcessMiningFiltertyp
    parameter_json: str
    wirkung_json: str
    fachliche_begruendung: str
    erstellt_am: datetime

    def __post_init__(self) -> None:
        if self.erstellt_am.utcoffset() is None:
            raise Domaenenfehler("Der Filterzeitpunkt muss zeitzonenbewusst sein.")
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class ProzessVariante:
    """Zusammengefasste identische Aktivitätsfolge."""

    rang: int
    aktivitaetsfolge: tuple[str, ...]
    fallanzahl: int
    anteil: float
    kumulierter_anteil: float

    @property
    def aktivitaetsanzahl(self) -> int:
        """Liefert die Länge der Aktivitätsfolge."""
        return len(self.aktivitaetsfolge)


@dataclass(frozen=True, slots=True)
class VariantenErgebnis:
    """Kennzahlen und Varianten des analysierten Event Logs."""

    ereignisanzahl: int
    fallanzahl: int
    aktivitaetsanzahl: int
    variantenanzahl: int
    durchschnittliche_ereignisse_je_fall: float
    minimale_ereignisse_je_fall: int
    maximale_ereignisse_je_fall: int
    aktivitaetshaeufigkeiten: tuple[tuple[str, int], ...]
    startaktivitaeten: tuple[tuple[str, int], ...]
    endaktivitaeten: tuple[tuple[str, int], ...]
    varianten: tuple[ProzessVariante, ...]


@dataclass(frozen=True, slots=True)
class DfgKante:
    """Gerichtete Kante eines frequenzbasierten DFG."""

    quelle: str
    ziel: str
    haeufigkeit: int
    anteil: float


@dataclass(frozen=True, slots=True)
class DfgErgebnis:
    """Vollständiger frequenzbasierter Directly-Follows-Graph."""

    aktivitaeten: tuple[str, ...]
    aktivitaetshaeufigkeiten: tuple[tuple[str, int], ...]
    kanten: tuple[DfgKante, ...]
    startaktivitaeten: tuple[tuple[str, int], ...]
    endaktivitaeten: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DiscoveryKonfiguration:
    """Typisierte Parameter genau eines Discovery-Verfahrens."""

    verfahren: DiscoveryVerfahren
    noise_threshold: float = 0.0
    dependency_threshold: float = 0.5
    and_threshold: float = 0.65
    loop_two_threshold: float = 0.5

    def __post_init__(self) -> None:
        for name, wert in (
            ("Noise Threshold", self.noise_threshold),
            ("Dependency Threshold", self.dependency_threshold),
            ("AND Threshold", self.and_threshold),
            ("Loop-two Threshold", self.loop_two_threshold),
        ):
            if not 0.0 <= wert <= 1.0:
                raise Domaenenfehler(f"{name} muss zwischen 0,0 und 1,0 liegen.")


@dataclass(frozen=True, slots=True)
class ProcessMiningKonfiguration:
    """Gesamte reproduzierbare Konfiguration einer Analyse."""

    discovery: DiscoveryKonfiguration
    filter: tuple[ProcessMiningFilter, ...]


@dataclass(frozen=True, slots=True)
class ModellStatistik:
    """Strukturelle Kennzahlen eines Petri-Netzes."""

    sichtbare_transitionen: int
    stille_transitionen: int
    stellen: int
    kanten: int


@dataclass(frozen=True, slots=True)
class ProcessMiningWarnung:
    """Nicht blockierende verständliche Analysewarnung."""

    code: str
    meldung: str


@dataclass(frozen=True, slots=True)
class DiscoveryErgebnisse:
    """In-Memory-Ergebnis eines Discovery-Laufs."""

    statistik: ModellStatistik
    pnml: bytes
    process_tree_ptml: bytes | None
    modell_svg: bytes | None
    process_tree_svg: bytes | None
    warnungen: tuple[ProcessMiningWarnung, ...]


@dataclass(frozen=True, slots=True)
class ProzessModellArtefakt:
    """Relative Pfade des gespeicherten Prozessmodells."""

    relativer_modell_pfad: str
    relativer_process_tree_pfad: str
    relativer_visualisierung_pfad: str


@dataclass(frozen=True, slots=True)
class ProcessMiningAnalyse:
    """Persistierte Metadaten und Ergebnisreferenzen einer Analyse."""

    analyse_id: UUID
    projekt_id: UUID
    qualitaetspruefung_id: UUID
    event_log_id: UUID
    konfiguration_json: str
    filter_json: str
    discovery_verfahren: DiscoveryVerfahren
    parameter_json: str
    ereignisanzahl_vorher: int
    fallanzahl_vorher: int
    aktivitaetsanzahl_vorher: int
    variantenanzahl_vorher: int
    ereignisanzahl_nachher: int
    fallanzahl_nachher: int
    aktivitaetsanzahl_nachher: int
    variantenanzahl_nachher: int
    modellstatistik_json: str
    warnungen_json: str
    pm4py_version: str
    relativer_ergebnis_pfad: str
    relativer_varianten_pfad: str
    relativer_dfg_pfad: str
    relativer_modell_pfad: str
    relativer_visualisierung_pfad: str
    status: ProcessMiningStatus
    erstellt_am: datetime
    geaendert_am: datetime

    def __post_init__(self) -> None:
        if self.erstellt_am.utcoffset() is None or self.geaendert_am.utcoffset() is None:
            raise Domaenenfehler("Analysezeitstempel müssen zeitzonenbewusst sein.")
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))
        object.__setattr__(self, "geaendert_am", self.geaendert_am.astimezone(UTC))
