"""Domänenmodelle für Projekte und Untersuchungsaufträge."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from framework_mvp.domain.exceptions import (
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


def _bereinigter_text(wert: str) -> str:
    return wert.strip()


def _bereinigte_liste(werte: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(bereinigt for wert in werte if (bereinigt := wert.strip()))


def _utc_jetzt() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Untersuchungsauftrag:
    """Beschreibt Ziel, Grenze und fachlichen Rahmen einer Untersuchung."""

    problemstellung: str
    zielsetzung: str
    systemtyp: Systemtyp
    systemgrenze: str
    input_beschreibung: str = ""
    transformation_beschreibung: str = ""
    output_beschreibung: str = ""
    detaillierungsgrad: str = ""
    leistungskennzahlen: tuple[str, ...] = ()
    rahmenbedingungen: str = ""
    betrachtungszeitraum_beginn: date | None = None
    betrachtungszeitraum_ende: date | None = None
    anmerkungen: str = ""

    def __post_init__(self) -> None:
        """Bereinigt Eingaben und prüft den Betrachtungszeitraum."""
        textfelder = (
            "problemstellung",
            "zielsetzung",
            "systemgrenze",
            "input_beschreibung",
            "transformation_beschreibung",
            "output_beschreibung",
            "detaillierungsgrad",
            "rahmenbedingungen",
            "anmerkungen",
        )
        for feldname in textfelder:
            object.__setattr__(self, feldname, _bereinigter_text(getattr(self, feldname)))
        object.__setattr__(self, "leistungskennzahlen", _bereinigte_liste(self.leistungskennzahlen))
        if (
            self.betrachtungszeitraum_beginn is not None
            and self.betrachtungszeitraum_ende is not None
            and self.betrachtungszeitraum_ende < self.betrachtungszeitraum_beginn
        ):
            raise UngueltigerBetrachtungszeitraum(
                "Das Ende des Betrachtungszeitraums darf nicht vor dem Beginn liegen."
            )

    def ist_vollstaendig(self) -> bool:
        """Prüft die drei Mindestangaben des Untersuchungsauftrags."""
        return bool(self.problemstellung and self.zielsetzung and self.systemgrenze)


@dataclass(frozen=True, slots=True)
class Projekt:
    """Unveränderliches Projekt mit seinem Untersuchungsauftrag."""

    projekt_id: UUID
    bezeichnung: str
    beteiligte_personen: tuple[str, ...]
    status: Projektstatus
    erstellt_am: datetime
    geaendert_am: datetime
    untersuchungsauftrag: Untersuchungsauftrag

    def __post_init__(self) -> None:
        """Bereinigt Projektangaben und sichert die fachlichen Invarianten."""
        object.__setattr__(self, "bezeichnung", _bereinigter_text(self.bezeichnung))
        object.__setattr__(self, "beteiligte_personen", _bereinigte_liste(self.beteiligte_personen))
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
        beteiligte_personen: tuple[str, ...] = (),
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
        beteiligte_personen: tuple[str, ...] = (),
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
