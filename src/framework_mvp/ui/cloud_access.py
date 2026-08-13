"""Kontextgebundene Adapter für die unveränderten Framework-Seiten 1–10."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from framework_mvp.application.autorisierung import AutorisierungsService
from framework_mvp.application.loesch_service import LoeschService
from framework_mvp.application.mandanten_projekt_service import MandantenProjektService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import ZugriffVerweigert
from framework_mvp.domain.models import (
    BeteiligtePerson,
    Projekt,
    Projektstatus,
    Untersuchungsauftrag,
)
from framework_mvp.domain.models.zugriff import (
    GlobaleRolle,
    Projektaktion,
    Zugriffskontext,
)


class GebundenerProjektService(ProjektService):
    """Bietet der Bestands-UI ihre Signaturen, prüft aber jede Projektoperation."""

    def __init__(
        self,
        kontext: Zugriffskontext,
        rohservice: ProjektService,
        mandantenservice: MandantenProjektService,
        autorisierung: AutorisierungsService,
        *,
        ziel_gruppen_id: UUID | None,
        gast_projekt_id: UUID | None,
        globale_rollen: frozenset[GlobaleRolle] = frozenset(),
    ) -> None:
        self._kontext = kontext
        self._roh = rohservice
        self._mandanten = mandantenservice
        self._autorisierung = autorisierung
        self._ziel_gruppen_id = ziel_gruppen_id
        self._gast_projekt_id = gast_projekt_id
        self._globale_rollen = globale_rollen

    def projekte_auflisten(self) -> list[Projekt]:
        if self._kontext.gast_geheimnis is not None:
            if self._gast_projekt_id is None:
                return []
            try:
                return [self._mandanten.projekt_laden(self._kontext, self._gast_projekt_id)]
            except ZugriffVerweigert:
                return []
        return self._mandanten.projekte_auflisten(self._kontext)

    def projekt_laden(self, projekt_id: UUID) -> Projekt | None:
        try:
            return self._mandanten.projekt_laden(self._kontext, projekt_id)
        except ZugriffVerweigert:
            return None

    def projekt_anlegen(
        self,
        *,
        bezeichnung: str,
        untersuchungsauftrag: Untersuchungsauftrag,
        beteiligte_personen: tuple[BeteiligtePerson, ...] = (),
    ) -> Projekt:
        if (
            GlobaleRolle.SYSTEMADMIN in self._globale_rollen
            and self._ziel_gruppen_id is None
            and self._kontext.gast_geheimnis is None
        ):
            return self._roh.projekt_anlegen(
                bezeichnung=bezeichnung,
                untersuchungsauftrag=untersuchungsauftrag,
                beteiligte_personen=beteiligte_personen,
            )
        return self._mandanten.projekt_anlegen(
            self._kontext,
            bezeichnung=bezeichnung,
            untersuchungsauftrag=untersuchungsauftrag,
            gruppen_id=self._ziel_gruppen_id,
            beteiligte_personen=beteiligte_personen,
        )

    def projekt_aktualisieren(
        self,
        projekt_id: UUID,
        *,
        bezeichnung: str,
        untersuchungsauftrag: Untersuchungsauftrag,
        status: Projektstatus,
        beteiligte_personen: tuple[BeteiligtePerson, ...] = (),
    ) -> Projekt:
        return self._mandanten.projekt_aktualisieren(
            self._kontext,
            projekt_id,
            bezeichnung=bezeichnung,
            untersuchungsauftrag=untersuchungsauftrag,
            status=status,
            beteiligte_personen=beteiligte_personen,
        )

    def betrachtungszeitraum_aus_event_log_aktualisieren(
        self,
        projekt_id: UUID,
        *,
        fruehester_ereigniszeitpunkt: datetime,
        spaetester_ereigniszeitpunkt: datetime,
    ) -> Projekt:
        self._autorisierung.projekt_zugriff_pruefen(
            self._kontext, projekt_id, Projektaktion.BEARBEITEN
        )
        return self._roh.betrachtungszeitraum_aus_event_log_aktualisieren(
            projekt_id,
            fruehester_ereigniszeitpunkt=fruehester_ereigniszeitpunkt,
            spaetester_ereigniszeitpunkt=spaetester_ereigniszeitpunkt,
        )


class GebundenerLoeschService(LoeschService):
    """Signaturkompatible Löschfassade für Bestandsseiten."""

    def __init__(
        self,
        kontext: Zugriffskontext,
        rohservice: LoeschService,
        autorisierung: AutorisierungsService,
    ) -> None:
        self._kontext = kontext
        self._roh = rohservice
        self._autorisierung = autorisierung

    def projekt_loeschen(self, projekt_id: UUID) -> None:
        self._autorisierung.projekt_zugriff_pruefen(
            self._kontext, projekt_id, Projektaktion.LOESCHEN
        )
        self._roh.projekt_loeschen(projekt_id)

    def zwischendatensatz_loeschen(self, projekt_id: UUID, zwischendatensatz_id: UUID) -> None:
        self._autorisierung.projekt_zugriff_pruefen(
            self._kontext, projekt_id, Projektaktion.BEARBEITEN
        )
        self._roh.zwischendatensatz_loeschen(projekt_id, zwischendatensatz_id)
