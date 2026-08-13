"""Unveränderliche Modelle des semantischen Mappings."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from framework_mvp.domain.exceptions import Domaenenfehler

AKTUELLE_EVENT_LOG_KONFIGURATIONSVERSION = 3
UNTERSTUETZTE_EVENT_LOG_KONFIGURATIONSVERSIONEN = frozenset({1, 2, 3})


class MappingModus(StrEnum):
    """Unterstützte strukturelle Ausgangsformen."""

    EREIGNISORIENTIERT = "ereignisorientiert"
    BREITER_ZEITSTEMPELDATENSATZ = "breiter_zeitstempeldatensatz"


class Mappingstatus(StrEnum):
    """Validierungsstatus eines semantischen Mappings."""

    ENTWURF = "entwurf"
    VALIDIERT = "validiert"
    UNGUELTIG = "ungueltig"


class Ereignisrolle(StrEnum):
    """Standardisierte Rollen eines möglichen Ereignisses."""

    FALL_ID = "Fall-ID"
    AKTIVITAET = "Aktivität"
    EREIGNISZEITPUNKT = "Ereigniszeitpunkt"
    STARTZEITPUNKT = "Startzeitpunkt"
    ENDZEITPUNKT = "Endzeitpunkt"
    LIFECYCLE = "Lifecycle-Status"
    RESSOURCE = "Ressource"
    MENGE = "Menge"
    KOSTEN = "Kosten"
    STANDORT = "Standort"
    AUFTRAGSART = "Auftragsart"
    PRODUKT = "Produkt"
    MATERIAL = "Material"
    MASCHINE = "Maschine"
    TRANSPORTMITTEL = "Transportmittel"
    QUELL_EREIGNIS_ID = "Quell-Ereignis-ID"


class Attributrolle(StrEnum):
    """Rolle weiterer nicht standardisierter Spalten."""

    EREIGNISATTRIBUT = "Ereignisattribut"
    FALLATTRIBUT = "Fallattribut"
    RESSOURCENATTRIBUT = "Ressourcenattribut"
    OBJEKTIDENTIFIKATOR = "Objektidentifikator"
    IGNORIERT = "Ignorierte Spalte"


class Aktivitaetsbildungsart(StrEnum):
    """Unterstützte Definitionen einer fachlichen Aktivität."""

    VORHANDENE_SPALTE = "vorhandene_spalte"
    ZUSAMMENGESETZT = "zusammengesetzt"


@dataclass(frozen=True, slots=True)
class Aktivitaetsdefinition:
    """Reproduzierbare Aktivität aus einer Spalte oder mehreren Textbestandteilen."""

    bildungsart: Aktivitaetsbildungsart
    quellspalten: tuple[str, ...]
    trennzeichen: str = ""
    praefix: str = ""
    suffix: str = ""
    fehlwertstrategie: str = "Nur vorhandene Bestandteile kombinieren"
    ersatztext: str = ""

    def __post_init__(self) -> None:
        """Bereinigt Namen und prüft die zur Bildungsart passende Spaltenanzahl."""
        spalten = tuple(wert.strip() for wert in self.quellspalten if wert.strip())
        object.__setattr__(self, "quellspalten", spalten)
        if self.bildungsart is Aktivitaetsbildungsart.VORHANDENE_SPALTE and len(spalten) != 1:
            raise Domaenenfehler("Eine vorhandene Aktivität benötigt genau eine Spalte.")
        if self.bildungsart is Aktivitaetsbildungsart.ZUSAMMENGESETZT and len(spalten) < 2:
            raise Domaenenfehler(
                "Eine zusammengesetzte Aktivität benötigt mindestens zwei Spalten."
            )
        if self.fehlwertstrategie not in {
            "Ergebnis leer lassen",
            "Nur vorhandene Bestandteile kombinieren",
            "Festen Ersatztext verwenden",
        }:
            raise Domaenenfehler("Die Fehlwertstrategie der Aktivität ist ungültig.")


class Warnungsstufe(StrEnum):
    """Schweregrad einer Mappingwarnung."""

    FEHLER = "Fehler"
    WARNUNG = "Warnung"
    HINWEIS = "Hinweis"


@dataclass(frozen=True, slots=True)
class Spaltenzuordnung:
    """Semantische oder attributbezogene Rolle einer technischen Spalte."""

    spaltenname: str
    rolle: Ereignisrolle | Attributrolle

    def __post_init__(self) -> None:
        """Bereinigt den technischen Spaltennamen."""
        object.__setattr__(self, "spaltenname", self.spaltenname.strip())


@dataclass(frozen=True, slots=True)
class ZusammengesetzteFallId:
    """Geordnete Fall-ID-Spalten und ihr explizites Trennzeichen."""

    spalten: tuple[str, ...]
    trennzeichen: str = "|"

    def __post_init__(self) -> None:
        """Bereinigt Fall-ID-Spalten und verlangt ein sichtbares Trennzeichen."""
        object.__setattr__(
            self, "spalten", tuple(wert.strip() for wert in self.spalten if wert.strip())
        )
        if not self.trennzeichen:
            raise Domaenenfehler(
                "Das Trennzeichen einer zusammengesetzten Fall-ID darf nicht leer sein."
            )


@dataclass(frozen=True, slots=True)
class ZeitstempelZuordnung:
    """Aktivität und optionale Zusatzspalten einer breiten Zeitstempelspalte."""

    zeitstempelspalte: str
    aktivitaetsbezeichnung: str
    ressourcenspalte: str = ""
    statusspalte: str = ""

    def __post_init__(self) -> None:
        """Bereinigt alle Namen einer breiten Zeitstempelzuordnung."""
        for feld in (
            "zeitstempelspalte",
            "aktivitaetsbezeichnung",
            "ressourcenspalte",
            "statusspalte",
        ):
            object.__setattr__(self, feld, getattr(self, feld).strip())


@dataclass(frozen=True, slots=True)
class MappingWarnung:
    """Standardisierte Feststellung einer Mappingvalidierung."""

    stufe: Warnungsstufe
    code: str
    meldung: str
    anzahl: int = 0


@dataclass(frozen=True, slots=True)
class MappingValidierung:
    """Kennzahlen, Warnungen und Gültigkeit der standardisierten Vorschau."""

    gueltig: bool
    fehlende_fall_ids: int
    fehlende_aktivitaeten: int
    nicht_interpretierbare_zeitwerte: int
    start_nach_ende: int
    identische_ereigniszeilen: int
    moegliche_doppelte_ereignisse: int
    faelle_mit_einem_ereignis: int
    faelle_mit_vielen_ereignissen: int
    unterschiedliche_aktivitaeten: int
    unterschiedliche_faelle: int
    warnungen: tuple[MappingWarnung, ...]


@dataclass(frozen=True, slots=True)
class SemantischesMapping:
    """Historische Event-Log-Konfiguration; ausdrücklich nicht Mappingtabelle M."""

    mapping_id: UUID
    projekt_id: UUID
    zwischendatensatz_id: UUID
    mapping_modus: MappingModus
    fall_id: ZusammengesetzteFallId
    aktivitaetsspalte: str
    zeitstempelspalte: str
    startzeitstempelspalte: str
    endzeitstempelspalte: str
    lifecycle_spalte: str
    ressourcen_spalte: str
    spaltenzuordnungen: tuple[Spaltenzuordnung, ...]
    zeitstempelzuordnungen: tuple[ZeitstempelZuordnung, ...]
    validierung: MappingValidierung | None
    erstellt_am: datetime
    geaendert_am: datetime
    status: Mappingstatus
    aktivitaetsdefinition: Aktivitaetsdefinition | None = None
    mappingtabelle_id: UUID | None = None
    konfigurationsversion: int = 1

    def __post_init__(self) -> None:
        """Bereinigt Namen und normalisiert Zeitstempel nach UTC."""
        for feld in (
            "aktivitaetsspalte",
            "zeitstempelspalte",
            "startzeitstempelspalte",
            "endzeitstempelspalte",
            "lifecycle_spalte",
            "ressourcen_spalte",
        ):
            object.__setattr__(self, feld, getattr(self, feld).strip())
        if self.erstellt_am.utcoffset() is None or self.geaendert_am.utcoffset() is None:
            raise Domaenenfehler("Zeitstempel eines Mappings müssen zeitzonenbewusst sein.")
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))
        object.__setattr__(self, "geaendert_am", self.geaendert_am.astimezone(UTC))
        if self.konfigurationsversion not in UNTERSTUETZTE_EVENT_LOG_KONFIGURATIONSVERSIONEN:
            raise Domaenenfehler("Die Event-Log-Konfigurationsversion ist ungültig.")
        if self.konfigurationsversion >= 2:
            self._aktuelle_fachregeln_pruefen()

    def _aktuelle_fachregeln_pruefen(self) -> None:
        """Begrenzt neue Konfigurationen auf Abschnitt 3.6.8."""
        if len(self.fall_id.spalten) != 1:
            raise Domaenenfehler(
                "Neue Event-Log-Konfigurationen benötigen genau eine Fallidentifikationsspalte."
            )
        if self.konfigurationsversion == 2 and any(
            (
                self.startzeitstempelspalte,
                self.endzeitstempelspalte,
                self.lifecycle_spalte,
                self.ressourcen_spalte,
            )
        ):
            raise Domaenenfehler(
                "Start, Ende, Lifecycle und Ressource sind keine besonderen Rollen der "
                "aktuellen Schritt-4-Konfiguration."
            )
        if len({wert.spaltenname for wert in self.spaltenzuordnungen}) != len(
            self.spaltenzuordnungen
        ):
            raise Domaenenfehler("Ein zusätzliches Attribut darf nur einmal ausgewählt werden.")
        if any(
            wert.rolle is not Attributrolle.EREIGNISATTRIBUT for wert in self.spaltenzuordnungen
        ):
            raise Domaenenfehler(
                "Neue Konfigurationen behandeln weitere Spalten nur als ausgewählte Attribute."
            )
        definition = self.wirksame_aktivitaetsdefinition
        if self.mapping_modus is MappingModus.EREIGNISORIENTIERT:
            if definition is None or not self.zeitstempelspalte:
                raise Domaenenfehler(
                    "Aktivitätsbeschreibung und Ereigniszeitstempel müssen festgelegt sein."
                )
            if self.zeitstempelzuordnungen:
                raise Domaenenfehler(
                    "Ein ereignisorientierter Datensatz besitzt keine breiten "
                    "Zeitstempelzuordnungen."
                )
            if definition.bildungsart is Aktivitaetsbildungsart.ZUSAMMENGESETZT and (
                definition.praefix
                or definition.suffix
                or definition.ersatztext
                or definition.fehlwertstrategie != "Ergebnis leer lassen"
            ):
                raise Domaenenfehler(
                    "Neue zusammengesetzte Aktivitäten erlauben nur Reihenfolge und "
                    "Verknüpfungselement."
                )
        else:
            if self.zeitstempelspalte or definition is not None:
                raise Domaenenfehler(
                    "Ein breiter Datensatz verwendet ausschließlich seine Zeitstempelzuordnungen."
                )
            if not self.zeitstempelzuordnungen:
                raise Domaenenfehler("Wählen Sie mindestens eine relevante Zeitstempelspalte aus.")
            if any(
                not wert.zeitstempelspalte or not wert.aktivitaetsbezeichnung
                for wert in self.zeitstempelzuordnungen
            ):
                raise Domaenenfehler(
                    "Jede Zeitstempelspalte benötigt genau eine Aktivitätsbeschreibung."
                )
            if self.konfigurationsversion == 2 and any(
                wert.ressourcenspalte or wert.statusspalte for wert in self.zeitstempelzuordnungen
            ):
                raise Domaenenfehler(
                    "Version 2 erlaubt in breiten Daten keine besonderen Ressourcen- oder "
                    "Statusrollen."
                )
            zeitspalten = [wert.zeitstempelspalte for wert in self.zeitstempelzuordnungen]
            if len(zeitspalten) != len(set(zeitspalten)):
                raise Domaenenfehler("Eine Zeitstempelspalte darf nur einmal ausgewählt werden.")
        if self.konfigurationsversion == 3:
            self._rollen_der_version_drei_pruefen()

    def _rollen_der_version_drei_pruefen(self) -> None:
        """Stellt die eindeutige technische Belegung der Rollen von Version 3 sicher."""
        rollen_nach_spalte: dict[str, str] = {}

        def belegen(spalte: str, rolle: str, *, wiederholbar: bool = False) -> None:
            if not spalte:
                return
            vorhandene_rolle = rollen_nach_spalte.get(spalte)
            if vorhandene_rolle is not None and not (wiederholbar and vorhandene_rolle == rolle):
                raise Domaenenfehler(
                    "Eine technische Quellspalte darf nicht mehreren Standardrollen oder "
                    "zusätzlich als allgemeines Attribut zugeordnet sein: "
                    f"{spalte}."
                )
            rollen_nach_spalte[spalte] = rolle

        for spalte in self.fall_id.spalten:
            belegen(spalte, "case_id")
        definition = self.wirksame_aktivitaetsdefinition
        if definition is not None:
            for spalte in definition.quellspalten:
                belegen(spalte, "activity")
        if self.mapping_modus is MappingModus.EREIGNISORIENTIERT:
            belegen(self.zeitstempelspalte, "timestamp")
            belegen(self.startzeitstempelspalte, "start_timestamp")
            belegen(self.endzeitstempelspalte, "end_timestamp")
            belegen(self.lifecycle_spalte, "lifecycle")
            belegen(self.ressourcen_spalte, "resource")
        else:
            if any(
                (
                    self.startzeitstempelspalte,
                    self.endzeitstempelspalte,
                    self.lifecycle_spalte,
                    self.ressourcen_spalte,
                )
            ):
                raise Domaenenfehler(
                    "Ein breiter Datensatz ordnet Ressource und Lifecycle je "
                    "Zeitstempelzuordnung zu; Start und Ende werden nicht abgeleitet."
                )
            for zuordnung in self.zeitstempelzuordnungen:
                belegen(zuordnung.zeitstempelspalte, "timestamp")
                belegen(zuordnung.ressourcenspalte, "resource", wiederholbar=True)
                belegen(zuordnung.statusspalte, "lifecycle", wiederholbar=True)
        for zuordnung in self.spaltenzuordnungen:
            if zuordnung.rolle is not Attributrolle.IGNORIERT:
                belegen(zuordnung.spaltenname, "allgemeines Attribut")

    @property
    def wirksame_aktivitaetsdefinition(self) -> Aktivitaetsdefinition | None:
        """Liefert die neue Definition oder interpretiert ein altes Mapping kompatibel."""
        if self.aktivitaetsdefinition is not None:
            return self.aktivitaetsdefinition
        if self.aktivitaetsspalte:
            return Aktivitaetsdefinition(
                Aktivitaetsbildungsart.VORHANDENE_SPALTE,
                (self.aktivitaetsspalte,),
            )
        return None

    @property
    def zusaetzliche_attribute(self) -> tuple[str, ...]:
        """Liefert für neue Konfigurationen die ausdrücklich ausgewählten Spalten."""
        return tuple(
            wert.spaltenname
            for wert in self.spaltenzuordnungen
            if wert.rolle is not Attributrolle.IGNORIERT
        )


# Fachlich korrekter Name für neue Schritt-4-Verwendungen bei kompatiblem Altformat.
EventLogKonfiguration = SemantischesMapping
