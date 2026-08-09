"""Domänenmodell des Datenquellenkatalogs Q."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from framework_mvp.domain.exceptions import Domaenenfehler, UngueltigerZeitstempel


class Quellsystemtyp(StrEnum):
    """Fachlicher Typ des erzeugenden Quellsystems."""

    ERP_SYSTEM = "erp_system"
    ME_SYSTEM = "me_system"
    WM_SYSTEM = "wm_system"
    DATENBANK = "datenbank"
    DATEI_EXPORT = "datei_export"
    SONSTIGES_SYSTEM = "sonstiges_system"


class Quellenart(StrEnum):
    """Technische Art einer registrierten Datenquelle."""

    CSV = "csv"
    EXCEL = "excel"
    DATENBANK = "datenbank"


AUSWAEHLBARE_QUELLSYSTEMTYPEN = (
    Quellsystemtyp.ERP_SYSTEM,
    Quellsystemtyp.ME_SYSTEM,
    Quellsystemtyp.WM_SYSTEM,
    Quellsystemtyp.SONSTIGES_SYSTEM,
)

AUSWAEHLBARE_QUELLENARTEN = (Quellenart.CSV, Quellenart.EXCEL)


def _text(wert: str) -> str:
    return wert.strip()


def _liste(werte: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(text for wert in werte if (text := wert.strip()))


def _utc_jetzt() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Datenquelle:
    """Unveränderlicher Eintrag im projektbezogenen Datenquellenkatalog Q."""

    datenquellen_id: UUID
    projekt_id: UUID
    bezeichnung: str
    quellsystemtyp: Quellsystemtyp
    konkretes_quellsystem: str
    fachliche_beschreibung: str
    herkunft_oder_verantwortungsbereich: str
    quellenart: Quellenart
    erwartete_tabellen_oder_blaetter: tuple[str, ...]
    bekannte_schluesselattribute: tuple[str, ...]
    erstellt_am: datetime
    geaendert_am: datetime

    def __post_init__(self) -> None:
        """Bereinigt Eingaben und prüft Identität sowie UTC-Zeitstempel."""
        if not isinstance(self.projekt_id, UUID):
            raise Domaenenfehler("Die Projekt-ID der Datenquelle ist ungültig.")
        for feld in (
            "bezeichnung",
            "konkretes_quellsystem",
            "fachliche_beschreibung",
            "herkunft_oder_verantwortungsbereich",
        ):
            object.__setattr__(self, feld, _text(getattr(self, feld)))
        object.__setattr__(
            self,
            "erwartete_tabellen_oder_blaetter",
            _liste(self.erwartete_tabellen_oder_blaetter),
        )
        object.__setattr__(
            self,
            "bekannte_schluesselattribute",
            _liste(self.bekannte_schluesselattribute),
        )
        if not self.bezeichnung:
            raise Domaenenfehler("Die Bezeichnung der Datenquelle darf nicht leer sein.")
        if self.erstellt_am.utcoffset() is None or self.geaendert_am.utcoffset() is None:
            raise UngueltigerZeitstempel(
                "Zeitstempel einer Datenquelle müssen zeitzonenbewusst sein."
            )
        erstellt_utc = self.erstellt_am.astimezone(UTC)
        geaendert_utc = self.geaendert_am.astimezone(UTC)
        if geaendert_utc < erstellt_utc:
            raise UngueltigerZeitstempel(
                "Der Änderungszeitpunkt darf nicht vor dem Erstellungszeitpunkt liegen."
            )
        object.__setattr__(self, "erstellt_am", erstellt_utc)
        object.__setattr__(self, "geaendert_am", geaendert_utc)

    @classmethod
    def neu(
        cls,
        *,
        projekt_id: UUID,
        bezeichnung: str,
        quellsystemtyp: Quellsystemtyp,
        quellenart: Quellenart,
        konkretes_quellsystem: str = "",
        fachliche_beschreibung: str = "",
        herkunft_oder_verantwortungsbereich: str = "",
        erwartete_tabellen_oder_blaetter: tuple[str, ...] = (),
        bekannte_schluesselattribute: tuple[str, ...] = (),
    ) -> Self:
        """Erzeugt eine Datenquelle mit UUID und reproduzierbaren UTC-Zeitstempeln."""
        zeitpunkt = _utc_jetzt()
        return cls(
            uuid4(),
            projekt_id,
            bezeichnung,
            quellsystemtyp,
            konkretes_quellsystem,
            fachliche_beschreibung,
            herkunft_oder_verantwortungsbereich,
            quellenart,
            erwartete_tabellen_oder_blaetter,
            bekannte_schluesselattribute,
            zeitpunkt,
            zeitpunkt,
        )

    def aktualisiert(
        self,
        *,
        bezeichnung: str,
        quellsystemtyp: Quellsystemtyp,
        quellenart: Quellenart,
        konkretes_quellsystem: str = "",
        fachliche_beschreibung: str = "",
        herkunft_oder_verantwortungsbereich: str = "",
        erwartete_tabellen_oder_blaetter: tuple[str, ...] = (),
        bekannte_schluesselattribute: tuple[str, ...] = (),
    ) -> Self:
        """Erzeugt eine validierte Kopie mit neuem Änderungszeitpunkt."""
        return replace(
            self,
            bezeichnung=bezeichnung,
            quellsystemtyp=quellsystemtyp,
            quellenart=quellenart,
            konkretes_quellsystem=konkretes_quellsystem,
            fachliche_beschreibung=fachliche_beschreibung,
            herkunft_oder_verantwortungsbereich=herkunft_oder_verantwortungsbereich,
            erwartete_tabellen_oder_blaetter=erwartete_tabellen_oder_blaetter,
            bekannte_schluesselattribute=bekannte_schluesselattribute,
            geaendert_am=_utc_jetzt(),
        )
