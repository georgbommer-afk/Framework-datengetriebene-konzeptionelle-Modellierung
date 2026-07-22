"""Domänenmodell eines reproduzierbar bestätigten Dateiimports."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Self
from uuid import UUID, uuid4

from framework_mvp.domain.exceptions import Domaenenfehler, UngueltigerZeitstempel
from framework_mvp.domain.models.importauftrag import (
    CsvImportparameter,
    Dateityp,
    ExcelImportparameter,
)

Importparameter = CsvImportparameter | ExcelImportparameter


class Importstatus(StrEnum):
    """Lebenszyklusstatus eines Importvorgangs."""

    ENTWURF = "entwurf"
    BESTAETIGT = "bestaetigt"
    FEHLGESCHLAGEN = "fehlgeschlagen"


@dataclass(frozen=True, slots=True)
class Profilzusammenfassung:
    """In SQLite gespeicherte zentrale Qualitätskennzahlen."""

    echte_fehlwerte: int
    textuelle_platzhalter: int
    exakte_duplikate: int
    potenzielle_ausreisser: int


def _relativer_artefaktpfad(pfad: str) -> str:
    bereinigt = pfad.strip().replace("\\", "/")
    relativ = PurePosixPath(bereinigt)
    if not bereinigt or relativ.is_absolute() or ".." in relativ.parts:
        raise Domaenenfehler("Ein Artefaktpfad muss sicher und relativ zum Workspace sein.")
    return relativ.as_posix()


@dataclass(frozen=True, slots=True)
class Importvorgang:
    """Unveränderlicher Metadatensatz eines temporären oder bestätigten Imports."""

    import_id: UUID
    projekt_id: UUID
    datenquellen_id: UUID
    originaldateiname: str
    sicherer_dateiname: str
    dateityp: Dateityp
    dateigroesse_bytes: int
    sha256: str
    importparameter: Importparameter
    tabellenbezeichnung: str
    zeilenanzahl: int
    spaltenanzahl: int
    profil_version: int
    relativer_raw_pfad: str
    relativer_profil_pfad: str
    profilzusammenfassung: Profilzusammenfassung
    warnungen: tuple[str, ...]
    status: Importstatus
    erstellt_am: datetime
    bestaetigt_am: datetime | None

    def __post_init__(self) -> None:
        """Bereinigt Metadaten und prüft Identität, Integrität und Lebenszyklus."""
        for feld in ("originaldateiname", "sicherer_dateiname", "tabellenbezeichnung"):
            object.__setattr__(self, feld, getattr(self, feld).strip())
        object.__setattr__(self, "sha256", self.sha256.lower())
        object.__setattr__(self, "warnungen", tuple(w.strip() for w in self.warnungen if w.strip()))
        if not isinstance(self.status, Importstatus):
            raise Domaenenfehler("Der Importstatus ist ungültig.")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise Domaenenfehler("Die SHA-256-Prüfsumme ist formal ungültig.")
        if self.dateigroesse_bytes < 0:
            raise Domaenenfehler("Die Dateigröße darf nicht negativ sein.")
        if self.zeilenanzahl < 0 or self.spaltenanzahl < 0:
            raise Domaenenfehler("Zeilen- und Spaltenanzahl dürfen nicht negativ sein.")
        if self.profil_version < 1:
            raise Domaenenfehler("Die Profilversion muss eine positive Ganzzahl sein.")
        if self.erstellt_am.utcoffset() is None:
            raise UngueltigerZeitstempel("Der Erstellungszeitpunkt muss zeitzonenbewusst sein.")
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))
        if self.bestaetigt_am is not None:
            if self.bestaetigt_am.utcoffset() is None:
                raise UngueltigerZeitstempel(
                    "Der Bestätigungszeitpunkt muss zeitzonenbewusst sein."
                )
            object.__setattr__(self, "bestaetigt_am", self.bestaetigt_am.astimezone(UTC))
        if self.relativer_raw_pfad:
            object.__setattr__(
                self, "relativer_raw_pfad", _relativer_artefaktpfad(self.relativer_raw_pfad)
            )
        if self.relativer_profil_pfad:
            object.__setattr__(
                self,
                "relativer_profil_pfad",
                _relativer_artefaktpfad(self.relativer_profil_pfad),
            )
        if self.status is Importstatus.BESTAETIGT and (
            self.bestaetigt_am is None
            or not self.relativer_raw_pfad
            or not self.relativer_profil_pfad
        ):
            raise Domaenenfehler(
                "Ein bestätigter Import benötigt Bestätigungszeitpunkt und Artefaktpfade."
            )

    @classmethod
    def bestaetigt(
        cls,
        *,
        projekt_id: UUID,
        datenquellen_id: UUID,
        originaldateiname: str,
        sicherer_dateiname: str,
        dateityp: Dateityp,
        dateigroesse_bytes: int,
        sha256: str,
        importparameter: Importparameter,
        tabellenbezeichnung: str,
        zeilenanzahl: int,
        spaltenanzahl: int,
        profil_version: int,
        relativer_raw_pfad: str,
        relativer_profil_pfad: str,
        profilzusammenfassung: Profilzusammenfassung,
        warnungen: tuple[str, ...] = (),
        import_id: UUID | None = None,
    ) -> Self:
        """Erzeugt einen bestätigten Import mit stabiler ID und UTC-Zeitpunkten."""
        zeitpunkt = datetime.now(UTC)
        return cls(
            import_id or uuid4(),
            projekt_id,
            datenquellen_id,
            originaldateiname,
            sicherer_dateiname,
            dateityp,
            dateigroesse_bytes,
            sha256,
            importparameter,
            tabellenbezeichnung,
            zeilenanzahl,
            spaltenanzahl,
            profil_version,
            relativer_raw_pfad,
            relativer_profil_pfad,
            profilzusammenfassung,
            warnungen,
            Importstatus.BESTAETIGT,
            zeitpunkt,
            zeitpunkt,
        )
