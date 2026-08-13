"""Autorisierte Fassade für Projektanlage, -zugriff und -löschung."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from framework_mvp.application.autorisierung import (
    NICHT_VERFUEGBAR,
    AutorisierungsService,
    geheimnis_hash,
)
from framework_mvp.application.loesch_service import LoeschService
from framework_mvp.application.ports.zugriffs_repository import ZugriffsRepository
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import ZugriffVerweigert
from framework_mvp.domain.models import (
    BeteiligtePerson,
    Projekt,
    Projektstatus,
    Untersuchungsauftrag,
)
from framework_mvp.domain.models.zugriff import (
    Gruppenaktion,
    Projektaktion,
    Projektmitglied,
    Projektzugehoerigkeit,
    Projektzugriffsart,
    Zugriffskontext,
)


class MandantenProjektService:
    """Stellt sicher, dass jede nach außen erreichbare Projektoperation autorisiert wird."""

    def __init__(
        self,
        projekt_service: ProjektService,
        zugriffs_repository: ZugriffsRepository,
        autorisierung: AutorisierungsService,
        *,
        gast_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self._projekte = projekt_service
        self._zugriff = zugriffs_repository
        self._autorisierung = autorisierung
        self._gast_ttl = gast_ttl

    def projekt_anlegen(
        self,
        kontext: Zugriffskontext,
        *,
        bezeichnung: str,
        untersuchungsauftrag: Untersuchungsauftrag,
        gruppen_id: UUID | None = None,
        beteiligte_personen: tuple[BeteiligtePerson, ...] = (),
    ) -> Projekt:
        """Legt ein Projekt an und bindet es unmittelbar exklusiv an Gast oder Kursgruppe."""
        jetzt = datetime.now(UTC)
        if kontext.gast_geheimnis is not None:
            if gruppen_id is not None:
                raise ZugriffVerweigert(NICHT_VERFUEGBAR)
            zugriffsart = Projektzugriffsart.GAST
        else:
            if kontext.benutzer_id is None or gruppen_id is None:
                raise ZugriffVerweigert(NICHT_VERFUEGBAR)
            self._autorisierung.gruppen_zugriff_pruefen(kontext, gruppen_id, Gruppenaktion.ANSEHEN)
            gruppe = self._zugriff.kursgruppe_laden(gruppen_id)
            if (
                gruppe is None
                or len(self._zugriff.projekt_ids_fuer_gruppe(gruppen_id))
                >= gruppe.maximale_projekte
            ):
                raise ZugriffVerweigert(NICHT_VERFUEGBAR)
            zugriffsart = Projektzugriffsart.KURSGRUPPE
        projekt = self._projekte.projekt_anlegen(
            bezeichnung=bezeichnung,
            untersuchungsauftrag=untersuchungsauftrag,
            beteiligte_personen=beteiligte_personen,
        )
        self._zugriff.projektzugehoerigkeit_speichern(
            Projektzugehoerigkeit(
                projekt_id=projekt.projekt_id,
                zugriffsart=zugriffsart,
                gruppen_id=gruppen_id,
                gast_geheimnis_sha256=(
                    geheimnis_hash(kontext.gast_geheimnis)
                    if kontext.gast_geheimnis is not None
                    else None
                ),
                gast_ablauf_am=jetzt + self._gast_ttl
                if zugriffsart is Projektzugriffsart.GAST
                else None,
                zuletzt_aktiv_am=jetzt,
                revision=1,
                erstellt_am=jetzt,
            )
        )
        if kontext.benutzer_id is not None:
            self._zugriff.projektmitglied_speichern(
                Projektmitglied(
                    projekt_id=projekt.projekt_id,
                    benutzer_id=kontext.benutzer_id,
                    darf_bearbeiten=True,
                    aktiv=True,
                ),
                zeitpunkt=jetzt,
            )
        return projekt

    def projekt_laden(self, kontext: Zugriffskontext, projekt_id: UUID) -> Projekt:
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, Projektaktion.ANSEHEN)
        projekt = self._projekte.projekt_laden(projekt_id)
        if projekt is None:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        self._aktivitaet_beruehren(kontext, projekt_id)
        return projekt

    def projekte_auflisten(self, kontext: Zugriffskontext) -> list[Projekt]:
        projekte: list[Projekt] = []
        for projekt_id in self._autorisierung.sichtbare_projekt_ids(kontext):
            projekt = self._projekte.projekt_laden(projekt_id)
            if projekt is not None:
                projekte.append(projekt)
        return projekte

    def projekt_aktualisieren(
        self,
        kontext: Zugriffskontext,
        projekt_id: UUID,
        *,
        bezeichnung: str,
        untersuchungsauftrag: Untersuchungsauftrag,
        status: Projektstatus,
        beteiligte_personen: tuple[BeteiligtePerson, ...] = (),
    ) -> Projekt:
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, Projektaktion.BEARBEITEN)
        projekt = self._projekte.projekt_aktualisieren(
            projekt_id,
            bezeichnung=bezeichnung,
            untersuchungsauftrag=untersuchungsauftrag,
            status=status,
            beteiligte_personen=beteiligte_personen,
        )
        self._aktivitaet_beruehren(kontext, projekt_id)
        return projekt

    def _aktivitaet_beruehren(self, kontext: Zugriffskontext, projekt_id: UUID) -> None:
        jetzt = datetime.now(UTC)
        self._zugriff.projekt_aktivitaet_beruehren(
            projekt_id,
            zeitpunkt=jetzt,
            neue_ablaufzeit=(
                jetzt + self._gast_ttl if kontext.gast_geheimnis is not None else None
            ),
        )


class AutorisierterLoeschService:
    """Verhindert Löschungen allein aufgrund einer bekannten UUID."""

    def __init__(self, loesch_service: LoeschService, autorisierung: AutorisierungsService) -> None:
        self._loeschen = loesch_service
        self._autorisierung = autorisierung

    def projekt_loeschen(self, kontext: Zugriffskontext, projekt_id: UUID) -> None:
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, Projektaktion.LOESCHEN)
        self._loeschen.projekt_loeschen(projekt_id)

    def zwischendatensatz_loeschen(
        self, kontext: Zugriffskontext, projekt_id: UUID, zwischendatensatz_id: UUID
    ) -> None:
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, Projektaktion.BEARBEITEN)
        self._loeschen.zwischendatensatz_loeschen(projekt_id, zwischendatensatz_id)
