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
    """Stabile Reihenfolge der 16 Bestandteile aus der aktuellen Tabelle 3.15."""

    PROBLEMSTELLUNG = "problemstellung"
    ZIELSETZUNG = "zielsetzung"
    AUSGABEN = "ausgaben"
    EINGABEN = "eingaben"
    MODELLUMFANG = "modellumfang"
    MODELLGRENZEN = "modellgrenzen"
    DETAILLIERUNGSGRAD = "detaillierungsgrad"
    ENTITAETEN = "entitaeten"
    AKTIVITAETEN = "aktivitaeten"
    WARTESCHLANGEN = "warteschlangen"
    RESSOURCEN = "ressourcen"
    ANNAHMEN = "annahmen"
    VEREINFACHUNGEN = "vereinfachungen"
    DATENAUSWAHL = "datenauswahl"
    DATEN = "daten"
    DARSTELLUNG_DER_VORGAENGE = "darstellung_der_vorgaenge_des_systems"


class FachlicheEntscheidungsart(StrEnum):
    """Explizite Human-in-the-Loop-Entscheidung zu genau einem Vorschlag."""

    UEBERNEHMEN = "vorschlag_uebernehmen"
    OFFEN_UNSICHER = "offen_fachlich_unsicher"
    NICHT_UEBERNEHMEN = "vorschlag_nicht_uebernehmen"


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
    fachliche_entscheidung: FachlicheEntscheidungsart | None = None
    bestaetigt_am: datetime | None = None

    def __post_init__(self) -> None:
        if (self.fachliche_entscheidung is None) != (self.bestaetigt_am is None):
            raise Domaenenfehler(
                "Entscheidung und Bestätigungszeitpunkt eines K-Eintrags müssen gemeinsam "
                "vorliegen."
            )
        if self.bestaetigt_am is not None:
            if self.bestaetigt_am.utcoffset() is None:
                raise Domaenenfehler("Ein Bestätigungszeitpunkt muss zeitzonenbewusst sein.")
            object.__setattr__(self, "bestaetigt_am", self.bestaetigt_am.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class FachlicheBestandteilentscheidung:
    """Geprüfte Entscheidung der anwendenden Person ohne erfundene Benutzeridentität."""

    bestandteil_id: ModellbestandteilId
    entscheidung: FachlicheEntscheidungsart
    begruendung: str
    entschieden_am: datetime

    def __post_init__(self) -> None:
        begruendung = self.begruendung.strip()
        object.__setattr__(self, "begruendung", begruendung)
        if self.entscheidung is not FachlicheEntscheidungsart.UEBERNEHMEN and not begruendung:
            raise Domaenenfehler(
                "Offene, unsichere oder nicht übernommene Vorschläge benötigen eine Begründung."
            )
        if self.entschieden_am.utcoffset() is None:
            raise Domaenenfehler("Der Entscheidungszeitpunkt muss zeitzonenbewusst sein.")
        object.__setattr__(self, "entschieden_am", self.entschieden_am.astimezone(UTC))


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
    fachliche_entscheidung: FachlicheEntscheidungsart | None = None
    entschieden_am: datetime | None = None

    def __post_init__(self) -> None:
        if self.status != "offen":
            raise Domaenenfehler("Ein Eintrag in O muss in Schritt 8 offen bleiben.")
        if not self.begruendung.strip():
            raise Domaenenfehler("Ein offener Eintrag benötigt eine konkrete Begründung.")
        if (self.fachliche_entscheidung is None) != (self.entschieden_am is None):
            raise Domaenenfehler(
                "Menschliche Entscheidung und Zeitpunkt eines O-Eintrags müssen gemeinsam "
                "vorliegen."
            )
        if self.entschieden_am is not None:
            if self.entschieden_am.utcoffset() is None:
                raise Domaenenfehler("Ein Entscheidungszeitpunkt muss zeitzonenbewusst sein.")
            object.__setattr__(self, "entschieden_am", self.entschieden_am.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class AbgeleiteterModellbestandteil:
    """Ein Bestandteil von K mit Informationen, Status und O-Referenzen."""

    bestandteil_id: ModellbestandteilId
    bezeichnung: str
    status: Bestandteilstatus
    verwendete_quellen: tuple[Eingangsartefakt, ...]
    informationen: tuple[Informationseintrag, ...]
    offene_eintrag_ids: tuple[str, ...]
    fachliche_entscheidung: FachlicheBestandteilentscheidung | None = None


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

    @property
    def entscheidungsfingerabdruck(self) -> str:
        """Fachlich aktuelle Bezeichnung der aus Kompatibilitätsgründen erhaltenen Spalte."""
        return self.unsicherheitsfingerabdruck
