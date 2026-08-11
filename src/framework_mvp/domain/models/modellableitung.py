"""Domänenvertrag für Algorithmus 8: vorläufiges Modell K und offene Inhalte O."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from framework_mvp.domain.exceptions import Domaenenfehler


class Eingangsartefakt(StrEnum):
    """Die einzigen nach Tabelle 3.15 zulässigen Quellen von Schritt 8."""

    UNTERSUCHUNGSAUFTRAG_U = "U"
    SYSTEMPROFIL_S = "S"
    DATENQUELLENKATALOG_Q = "Q"
    DATENPROFIL_R = "R"
    ZWISCHENDATENSATZ_T = "T"
    EVENT_LOG_E_STERN = "E*"
    PROZESSMODELL_P = "P"
    AGGREGIERTE_ANALYSEERGEBNISSE_A_G = "A_G"


class ModellbestandteilId(StrEnum):
    """Stabile Reihenfolge der elf Bestandteile aus Abschnitt 2.3.1."""

    PROBLEMSTELLUNG = "problemstellung"
    ZIELSETZUNG = "zielsetzung"
    AUSGABEN_UND_EINGABEN = "ausgaben_und_eingaben"
    MODELLUMFANG_GRENZEN_DETAILLIERUNG = "modellumfang_grenzen_detaillierungsgrad"
    ENTITAETEN = "entitaeten"
    AKTIVITAETEN = "aktivitaeten"
    WARTESCHLANGEN = "warteschlangen"
    RESSOURCEN = "ressourcen"
    ANNAHMEN_UND_VEREINFACHUNGEN = "annahmen_und_vereinfachungen"
    DATENAUSWAHL_UND_DATEN = "datenauswahl_und_daten"
    DARSTELLUNG_DER_VORGAENGE = "darstellung_der_vorgaenge_des_systems"


class Bestandteilstatus(StrEnum):
    """Nachvollziehbarer Zuordnungsstatus eines Modellbestandteils."""

    VOLLSTAENDIG_ZUGEORDNET = "vollstaendig_zugeordnet"
    TEILWEISE_OFFEN = "teilweise_offen"
    OFFEN = "offen"
    FACHLICH_UNSICHER = "fachlich_unsicher"


class Offenheitskategorie(StrEnum):
    """Die drei Kategorien aus Algorithmus 8."""

    FEHLEND = "fehlend"
    NICHT_ABLEITBAR = "nicht_ableitbar"
    FACHLICH_UNSICHER = "fachlich_unsicher"


class Kennzeichnungsherkunft(StrEnum):
    """Ursprung eines offenen Eintrags."""

    SYSTEMATISCH_ERKANNT = "systematisch_erkannt"
    MENSCHLICH_MARKIERT = "menschlich_markiert"


class Uebernahmeart(StrEnum):
    """Zulässige, nicht interpretierende Übernahmeformen nach Algorithmus 8."""

    DIREKTE_UEBERNAHME = "direkte_uebernahme"
    METADATENZUSAMMENFASSUNG = "metadatenzusammenfassung"
    ARTEFAKTREFERENZ = "artefaktreferenz"


class Modellableitungsstatus(StrEnum):
    """Persistenzstatus eines gemeinsam gespeicherten K/O-Paars."""

    GESPEICHERT = "gespeichert"


@dataclass(frozen=True, slots=True)
class ModellbestandteilDefinition:
    """Versionierte Quellenzuordnung eines Bestandteils gemäß Tabelle 3.15."""

    bestandteil_id: ModellbestandteilId
    bezeichnung: str
    zulaessige_quellen: tuple[Eingangsartefakt, ...]
    teilweise_offen: bool = False


@dataclass(frozen=True, slots=True)
class Informationseintrag:
    """Belegte Information mit exakter Herkunft, ohne fachliche Neuschöpfung."""

    informations_id: str
    bestandteil_id: ModellbestandteilId
    herkunftsartefakt: Eingangsartefakt
    herkunftsartefakt_id: str
    herkunftsartefakt_sha256: str
    strukturreferenz: str
    wert: Any
    uebernahmeart: Uebernahmeart


@dataclass(frozen=True, slots=True)
class OffenerEintrag:
    """Unaufgelöster Ergänzungs- oder Validierungsbedarf für Schritt 9."""

    offener_eintrag_id: str
    bestandteil_id: ModellbestandteilId
    kategorie: Offenheitskategorie
    begruendung: str
    belegreferenzen: tuple[dict[str, Any], ...]
    kennzeichnungsherkunft: Kennzeichnungsherkunft
    status: str = "offen"

    def __post_init__(self) -> None:
        if self.status != "offen":
            raise Domaenenfehler("Ein Eintrag in O muss in Schritt 8 offen bleiben.")
        if not self.begruendung.strip():
            raise Domaenenfehler("Ein offener Eintrag benötigt eine konkrete Begründung.")


@dataclass(frozen=True, slots=True)
class AbgeleiteterModellbestandteil:
    """Ein Bestandteil von K mit Informationen, Status und O-Referenzen."""

    bestandteil_id: ModellbestandteilId
    bezeichnung: str
    status: Bestandteilstatus
    verwendete_quellen: tuple[Eingangsartefakt, ...]
    informationen: tuple[Informationseintrag, ...]
    offene_eintrag_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Modellableitung:
    """Persistierte Metadaten eines atomar erzeugten Paars aus K und O."""

    modellableitungs_id: UUID
    k_id: UUID
    o_id: UUID
    projekt_id: UUID
    aggregations_id: UUID
    analyse_id: UUID
    event_log_id: UUID
    eingabefingerabdruck: str
    mappingversion: int
    unsicherheitsfingerabdruck: str
    relativer_k_pfad: str
    k_sha256: str
    relativer_o_pfad: str
    o_sha256: str
    status: Modellableitungsstatus
    erstellt_am: datetime

    def __post_init__(self) -> None:
        for wert in (
            self.eingabefingerabdruck,
            self.unsicherheitsfingerabdruck,
            self.k_sha256,
            self.o_sha256,
        ):
            if len(wert) != 64 or any(zeichen not in "0123456789abcdef" for zeichen in wert):
                raise Domaenenfehler("Eine Prüfsumme der Modellableitung ist ungültig.")
        if self.mappingversion < 1:
            raise Domaenenfehler("Die Mappingversion der Modellableitung ist ungültig.")
        if self.erstellt_am.utcoffset() is None:
            raise Domaenenfehler("Der Erstellungszeitpunkt muss zeitzonenbewusst sein.")
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))
