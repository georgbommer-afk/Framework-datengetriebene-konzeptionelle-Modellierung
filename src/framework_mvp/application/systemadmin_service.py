"""Eng begrenzte Systemadministration ohne impliziten Projektzugriff."""

from datetime import UTC, datetime
from uuid import UUID

from framework_mvp.application.autorisierung import AutorisierungsService
from framework_mvp.application.gast_service import BereinigungsService
from framework_mvp.application.ports.zugriffs_repository import ZugriffsRepository
from framework_mvp.domain.models.zugriff import GlobaleRolle, Zugriffskontext


class SystemadminService:
    def __init__(
        self,
        repository: ZugriffsRepository,
        autorisierung: AutorisierungsService,
        bereinigung: BereinigungsService | None = None,
    ) -> None:
        self._repository = repository
        self._autorisierung = autorisierung
        self._bereinigung = bereinigung

    def gruppenleitung_freischalten(self, kontext: Zugriffskontext, benutzer_id: UUID) -> None:
        self._autorisierung.systemadmin_pruefen(kontext)
        self._repository.globale_rolle_setzen(
            benutzer_id, GlobaleRolle.GRUPPENLEITUNG, vergeben_von=kontext.benutzer_id
        )

    def gruppenleitung_entziehen(self, kontext: Zugriffskontext, benutzer_id: UUID) -> None:
        self._autorisierung.systemadmin_pruefen(kontext)
        self._repository.globale_rolle_entfernen(benutzer_id, GlobaleRolle.GRUPPENLEITUNG)

    def gruppe_sperren(self, kontext: Zugriffskontext, gruppen_id: UUID) -> None:
        self._autorisierung.systemadmin_pruefen(kontext)
        self._repository.kursgruppe_status_setzen(
            gruppen_id, status="gesperrt", zeitpunkt=datetime.now(UTC)
        )

    def bereinigung_ausloesen(self, kontext: Zugriffskontext) -> int:
        self._autorisierung.systemadmin_pruefen(kontext)
        return 0 if self._bereinigung is None else self._bereinigung.opportunistisch(limit=1000)
