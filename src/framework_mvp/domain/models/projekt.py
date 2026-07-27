"""Strukturierte Domänenmodelle für Projekte und Untersuchungsaufträge."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from framework_mvp.domain.exceptions import (
    Domaenenfehler,
    UngueltigeProjektbezeichnung,
    UngueltigerBetrachtungszeitraum,
    UngueltigerZeitstempel,
    UnvollstaendigerUntersuchungsauftrag,
)


class Projektstatus(StrEnum):
    """Mögliche Bearbeitungszustände eines Projekts."""

    ENTWURF = "entwurf"
    AKTIV = "aktiv"
    ABGESCHLOSSEN = "abgeschlossen"


class Systemtyp(StrEnum):
    """Vom Untersuchungsauftrag betrachteter Typ des Systems."""

    PRODUKTION = "produktion"
    INTRALOGISTIK = "intralogistik"
    KOMBINIERT = "kombiniert"


class GestaltDerGueter(StrEnum):
    """Physische Gestalt der betrachteten Güter."""

    STUECKGUT = "stueckgut"
    FLIESSGUT = "fliessgut"
    MISCHFORM = "mischform"


class Materialflussform(StrEnum):
    """Topologische Form des Materialflusses."""

    KONVERGIEREND = "konvergierend"
    DIVERGIEREND = "divergierend"
    GEMISCHT = "gemischt"


class Materialflusskontinuitaet(StrEnum):
    """Zeitliche Kontinuität des Materialflusses."""

    KONTINUIERLICH = "kontinuierlich"
    DISKONTINUIERLICH = "diskontinuierlich"
    GEMISCHT = "gemischt"


class BetrachtungszeitraumModus(StrEnum):
    """Festlegungsart des Betrachtungszeitraums."""

    AUS_DATEN = "aus_daten"
    MANUELL = "manuell"
    OFFEN = "offen"


class LogistischeZielgroesse(StrEnum):
    """Stabile technische IDs der logistischen Zielgrößen."""

    LIEFERFAEHIGKEIT = "lieferfaehigkeit_erhoehen"
    LIEFERBEREITSCHAFT = "lieferbereitschaft_erhoehen"
    LIEFERTREUE = "liefertreue_erhoehen"
    LIEFERZEIT = "lieferzeit_reduzieren"
    DURCHLAUFZEIT = "durchlaufzeit_reduzieren"
    WARTEZEIT = "wartezeit_reduzieren"
    TRANSPORTZEIT = "transportzeit_reduzieren"
    REAKTIONSZEIT = "reaktionszeit_reduzieren"
    PROZESSVARIABILITAET = "prozessvariabilitaet_reduzieren"
    PROZESSSICHERHEIT = "prozesssicherheit_erhoehen"
    QUALITAET = "qualitaet_erhoehen"
    NACHARBEIT = "nacharbeit_reduzieren"
    RESSOURCENAUSLASTUNG = "ressourcenauslastung_erhoehen"
    RUESTZEIT = "ruestzeit_reduzieren"
    BESTAENDE = "umlauf_und_lagerbestaende_reduzieren"
    KOSTEN = "prozess_und_transportkosten_reduzieren"


def _text(wert: str) -> str:
    return wert.strip()


def _texte(werte: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(text for wert in werte if (text := wert.strip()))


@dataclass(frozen=True, slots=True)
class BeteiligtePerson:
    """Eine beteiligte Person mit optionaler fachlicher Rolle."""

    vorname: str = ""
    nachname: str = ""
    rolle: str = ""

    def __post_init__(self) -> None:
        """Bereinigt die Personenangaben und sichert einen Namen."""
        object.__setattr__(self, "vorname", _text(self.vorname))
        object.__setattr__(self, "nachname", _text(self.nachname))
        object.__setattr__(self, "rolle", _text(self.rolle))
        if not self.vorname and not self.nachname:
            raise Domaenenfehler("Mindestens Vorname oder Nachname muss angegeben werden.")


@dataclass(frozen=True, slots=True)
class Betrachtungszeitraum:
    """Festlegung des fachlichen Betrachtungszeitraums."""

    modus: BetrachtungszeitraumModus = BetrachtungszeitraumModus.AUS_DATEN
    beginn: date | None = None
    ende: date | None = None
    migrationsbestand: bool = False

    def __post_init__(self) -> None:
        """Prüft die zum Modus passenden Datumswerte."""
        if self.modus is BetrachtungszeitraumModus.MANUELL:
            if (self.beginn is None or self.ende is None) and not self.migrationsbestand:
                raise UngueltigerBetrachtungszeitraum(
                    "Ein manueller Betrachtungszeitraum benötigt Beginn und Ende."
                )
            if self.beginn is not None and self.ende is not None and self.ende < self.beginn:
                raise UngueltigerBetrachtungszeitraum(
                    "Das Ende des Betrachtungszeitraums darf nicht vor dem Beginn liegen."
                )
        elif self.modus is BetrachtungszeitraumModus.AUS_DATEN:
            if (self.beginn is None) != (self.ende is None):
                raise UngueltigerBetrachtungszeitraum(
                    "Ein aus Ereignisdaten ermittelter Zeitraum benötigt Beginn und Ende."
                )
            if self.beginn is not None and self.ende is not None and self.ende < self.beginn:
                raise UngueltigerBetrachtungszeitraum(
                    "Das Ende des Betrachtungszeitraums darf nicht vor dem Beginn liegen."
                )
        elif self.beginn is not None or self.ende is not None:
            raise UngueltigerBetrachtungszeitraum(
                "Datumswerte sind nur bei einem manuellen Betrachtungszeitraum zulässig."
            )


@dataclass(frozen=True, slots=True)
class Rahmenbedingungen:
    """Strukturierte optionale Rahmenbedingungen der Untersuchung."""

    vertraulichkeit_datenschutz: str = ""
    technische_einschraenkungen: str = ""
    bekannte_annahmen: str = ""
    bekannte_ausschluesse: str = ""
    sonstige: str = ""

    def __post_init__(self) -> None:
        """Bereinigt alle Freitextangaben."""
        for feld in self.__dataclass_fields__:
            object.__setattr__(self, feld, _text(getattr(self, feld)))


@dataclass(frozen=True, slots=True)
class Produktionsklassifikation:
    """Spezifische Merkmale eines Produktionssystems."""

    auftragsabwicklungsstrategie: str = ""
    produktionsart: str = ""
    produktionsstueckzahl: str = ""
    stueckzahl_grenze_gering_mittel: int | None = None
    stueckzahl_grenze_mittel_hoch: int | None = None
    stueckzahl_einheit_zeitraum: str = ""
    produktvielfalt: str = ""
    varianten_grenze_gering_mittel: int | None = None
    varianten_grenze_mittel_hoch: int | None = None
    organisationstyp: str = ""
    anzahl_arbeitsgaenge: str = ""
    produktionsfaktoren: tuple[str, ...] = ()
    ressourcen: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Bereinigt die textuellen Produktionsmerkmale."""
        for feld in (
            "auftragsabwicklungsstrategie",
            "produktionsart",
            "produktionsstueckzahl",
            "stueckzahl_einheit_zeitraum",
            "produktvielfalt",
            "organisationstyp",
            "anzahl_arbeitsgaenge",
        ):
            object.__setattr__(self, feld, _text(getattr(self, feld)))
        object.__setattr__(self, "produktionsfaktoren", _texte(self.produktionsfaktoren))
        object.__setattr__(self, "ressourcen", _texte(self.ressourcen))


@dataclass(frozen=True, slots=True)
class Intralogistikklassifikation:
    """Spezifische Merkmale eines Intralogistiksystems."""

    hauptfunktionen: tuple[str, ...] = ()
    ladungstraeger: tuple[str, ...] = ()
    quellen_und_senken: str = ""
    transportorganisation: str = ""
    lagerprinzip: str = ""
    ressourcen: tuple[str, ...] = ()
    puffer_und_lagerbereiche: str = ""
    bekannte_kapazitaetsgrenzen: str = ""

    def __post_init__(self) -> None:
        """Bereinigt die textuellen Intralogistikmerkmale."""
        object.__setattr__(self, "hauptfunktionen", _texte(self.hauptfunktionen))
        object.__setattr__(self, "ladungstraeger", _texte(self.ladungstraeger))
        object.__setattr__(self, "ressourcen", _texte(self.ressourcen))
        for feld in (
            "quellen_und_senken",
            "transportorganisation",
            "lagerprinzip",
            "puffer_und_lagerbereiche",
            "bekannte_kapazitaetsgrenzen",
        ):
            object.__setattr__(self, feld, _text(getattr(self, feld)))


@dataclass(frozen=True, slots=True)
class Systemklassifikation:
    """Gemeinsame und systemtypspezifische Klassifikationsmerkmale."""

    bereich: str = ""
    objekte_gueter: str = ""
    gestalt_der_gueter: GestaltDerGueter = GestaltDerGueter.MISCHFORM
    materialflussform: Materialflussform = Materialflussform.GEMISCHT
    materialflusskontinuitaet: Materialflusskontinuitaet = Materialflusskontinuitaet.GEMISCHT
    kapazitaetsgrenzen: str = ""
    input_beschreibung: str = ""
    transformation_beschreibung: str = ""
    output_beschreibung: str = ""
    produktion: Produktionsklassifikation | None = None
    intralogistik: Intralogistikklassifikation | None = None

    def __post_init__(self) -> None:
        """Bereinigt die gemeinsamen Freitextangaben."""
        for feld in (
            "bereich",
            "objekte_gueter",
            "kapazitaetsgrenzen",
            "input_beschreibung",
            "transformation_beschreibung",
            "output_beschreibung",
        ):
            object.__setattr__(self, feld, _text(getattr(self, feld)))


@dataclass(frozen=True, slots=True)
class Untersuchungsauftrag:
    """Strukturierter Auftrag zur Steuerung der weiteren Frameworkschritte."""

    problemstellung: str
    untersuchungszweck: str
    systemtyp: Systemtyp
    systemgrenze: str
    individuelles_ziel: str = ""
    logistische_zielgroessen: tuple[LogistischeZielgroesse, ...] = ()
    ausgewaehlte_kpi_ids: tuple[str, ...] = ()
    systemklassifikation: Systemklassifikation = Systemklassifikation()
    detaillierungsgrad: str = ""
    rahmenbedingungen: Rahmenbedingungen = Rahmenbedingungen()
    betrachtungszeitraum: Betrachtungszeitraum = Betrachtungszeitraum()
    anmerkungen: str = ""
    legacy_leistungskennzahlen: tuple[str, ...] = ()
    migrationsbestand: bool = False
    untersuchungszwecke: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Bereinigt Freitexte und entfernt nicht mehr ableitbare KPI-Auswahlen."""
        for feld in (
            "problemstellung",
            "untersuchungszweck",
            "systemgrenze",
            "individuelles_ziel",
            "detaillierungsgrad",
            "anmerkungen",
        ):
            object.__setattr__(self, feld, _text(getattr(self, feld)))
        object.__setattr__(self, "ausgewaehlte_kpi_ids", _texte(self.ausgewaehlte_kpi_ids))
        object.__setattr__(
            self, "legacy_leistungskennzahlen", _texte(self.legacy_leistungskennzahlen)
        )
        zwecke = _texte(self.untersuchungszwecke)
        if not zwecke and self.untersuchungszweck:
            zwecke = (self.untersuchungszweck,)
        eindeutig: list[str] = []
        bekannte: set[str] = set()
        for zweck in zwecke:
            normalisiert = zweck.casefold()
            if normalisiert not in bekannte:
                bekannte.add(normalisiert)
                eindeutig.append(zweck)
        object.__setattr__(self, "untersuchungszwecke", tuple(eindeutig))
        if eindeutig:
            object.__setattr__(self, "untersuchungszweck", eindeutig[0])
        from framework_mvp.domain.kataloge import bereinige_kpi_auswahl

        object.__setattr__(
            self,
            "ausgewaehlte_kpi_ids",
            bereinige_kpi_auswahl(self.logistische_zielgroessen, self.ausgewaehlte_kpi_ids),
        )

    def ist_vollstaendig(self) -> bool:
        """Prüft Problem, Systemgrenze und Untersuchungszweck."""
        return bool(self.problemstellung and self.systemgrenze and self.untersuchungszwecke)


def _utc_jetzt() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Projekt:
    """Unveränderliches Projekt mit seinem Untersuchungsauftrag."""

    projekt_id: UUID
    bezeichnung: str
    beteiligte_personen: tuple[BeteiligtePerson, ...]
    status: Projektstatus
    erstellt_am: datetime
    geaendert_am: datetime
    untersuchungsauftrag: Untersuchungsauftrag

    def __post_init__(self) -> None:
        """Bereinigt Projektangaben und sichert die fachlichen Invarianten."""
        object.__setattr__(self, "bezeichnung", _text(self.bezeichnung))
        if not self.bezeichnung:
            raise UngueltigeProjektbezeichnung("Die Projektbezeichnung darf nicht leer sein.")
        if self.erstellt_am.utcoffset() is None or self.geaendert_am.utcoffset() is None:
            raise UngueltigerZeitstempel("Projektzeitstempel müssen zeitzonenbewusst sein.")
        erstellt_utc = self.erstellt_am.astimezone(UTC)
        geaendert_utc = self.geaendert_am.astimezone(UTC)
        if geaendert_utc < erstellt_utc:
            raise UngueltigerZeitstempel(
                "Der Änderungszeitpunkt darf nicht vor dem Erstellungszeitpunkt liegen."
            )
        object.__setattr__(self, "erstellt_am", erstellt_utc)
        object.__setattr__(self, "geaendert_am", geaendert_utc)
        if (
            self.status is not Projektstatus.ENTWURF
            and not self.untersuchungsauftrag.ist_vollstaendig()
            and not self.untersuchungsauftrag.migrationsbestand
        ):
            raise UnvollstaendigerUntersuchungsauftrag(
                "Ein unvollständiger Untersuchungsauftrag darf nur als Entwurf gespeichert werden."
            )

    @classmethod
    def neu(
        cls,
        bezeichnung: str,
        untersuchungsauftrag: Untersuchungsauftrag,
        status: Projektstatus = Projektstatus.ENTWURF,
        beteiligte_personen: tuple[BeteiligtePerson, ...] = (),
    ) -> Self:
        """Erzeugt ein neues Projekt mit UUID und UTC-Zeitstempeln."""
        zeitpunkt = _utc_jetzt()
        return cls(
            projekt_id=uuid4(),
            bezeichnung=bezeichnung,
            beteiligte_personen=beteiligte_personen,
            status=status,
            erstellt_am=zeitpunkt,
            geaendert_am=zeitpunkt,
            untersuchungsauftrag=untersuchungsauftrag,
        )

    def aktualisiert(
        self,
        *,
        bezeichnung: str,
        untersuchungsauftrag: Untersuchungsauftrag,
        status: Projektstatus,
        beteiligte_personen: tuple[BeteiligtePerson, ...] = (),
    ) -> Self:
        """Gibt eine fachlich validierte, aktualisierte Projektkopie zurück."""
        return replace(
            self,
            bezeichnung=bezeichnung,
            beteiligte_personen=beteiligte_personen,
            status=status,
            geaendert_am=_utc_jetzt(),
            untersuchungsauftrag=untersuchungsauftrag,
        )
