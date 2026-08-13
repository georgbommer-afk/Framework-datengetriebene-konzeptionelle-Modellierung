"""Port für Identitäten, Kursmandanten, Einladungen und Projektzuordnungen."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from framework_mvp.domain.models.zugriff import (
    Benutzer,
    GlobaleRolle,
    Gruppeneinladung,
    Gruppenmitgliedschaft,
    Kursgruppe,
    Projektfortschritt,
    Projektmitglied,
    Projektzugehoerigkeit,
)


class ZugriffsRepository(Protocol):
    """Dauerhafte Schnittstelle der serverseitigen Zugriffsschicht."""

    def oidc_benutzer_speichern(
        self, *, issuer: str, subject: str, email: str, anzeigename: str
    ) -> Benutzer: ...

    def benutzer_laden(self, benutzer_id: UUID) -> Benutzer | None: ...

    def globale_rollen_laden(self, benutzer_id: UUID) -> frozenset[GlobaleRolle]: ...

    def globale_rolle_setzen(
        self,
        benutzer_id: UUID,
        rolle: GlobaleRolle,
        *,
        vergeben_von: UUID | None,
    ) -> None: ...

    def globale_rolle_entfernen(self, benutzer_id: UUID, rolle: GlobaleRolle) -> None: ...

    def kursgruppe_speichern(self, gruppe: Kursgruppe) -> None: ...

    def kursgruppe_laden(self, gruppen_id: UUID) -> Kursgruppe | None: ...

    def gruppenmitgliedschaft_speichern(self, mitgliedschaft: Gruppenmitgliedschaft) -> None: ...

    def gruppenmitgliedschaft_laden(
        self, gruppen_id: UUID, benutzer_id: UUID
    ) -> Gruppenmitgliedschaft | None: ...

    def gruppen_fuer_benutzer(self, benutzer_id: UUID) -> list[Kursgruppe]: ...

    def projektzugehoerigkeit_speichern(self, zugehoerigkeit: Projektzugehoerigkeit) -> None: ...

    def projektzugehoerigkeit_laden(
        self, projekt_id: UUID
    ) -> Projektzugehoerigkeit | None: ...

    def projektmitglied_speichern(self, mitglied: Projektmitglied, *, zeitpunkt: datetime) -> None: ...

    def projektmitglied_laden(
        self, projekt_id: UUID, benutzer_id: UUID
    ) -> Projektmitglied | None: ...

    def projekt_ids_fuer_benutzer(self, benutzer_id: UUID) -> list[UUID]: ...

    def projekt_ids_fuer_gruppe(self, gruppen_id: UUID) -> list[UUID]: ...

    def legacy_projekt_ids(self) -> list[UUID]: ...

    def abgelaufene_gastprojekt_ids(self, *, zeitpunkt: datetime, limit: int) -> list[UUID]: ...

    def projekt_aktivitaet_beruehren(
        self, projekt_id: UUID, *, zeitpunkt: datetime, neue_ablaufzeit: datetime | None = None
    ) -> None: ...

    def fortschritt_speichern(self, fortschritt: Projektfortschritt) -> None: ...

    def fortschritt_laden(self, projekt_id: UUID) -> Projektfortschritt | None: ...

    def einladung_speichern(self, einladung: Gruppeneinladung) -> None: ...

    def einladung_laden_per_hash(self, token_sha256: str) -> Gruppeneinladung | None: ...

    def einladung_widerrufen(self, einladungs_id: UUID, *, zeitpunkt: datetime) -> None: ...

    def einladung_atomar_einloesen(
        self, *, token_sha256: str, benutzer: Benutzer, zeitpunkt: datetime
    ) -> Gruppenmitgliedschaft: ...
