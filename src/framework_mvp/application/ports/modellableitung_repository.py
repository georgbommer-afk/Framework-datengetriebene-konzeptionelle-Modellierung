"""Port für atomar persistierte Modellableitungen K und O."""

from typing import Protocol
from uuid import UUID

from framework_mvp.domain.models import Modellableitung


class ModellableitungRepository(Protocol):
    """Metadatenzugriff ohne fachliche Ableitungslogik."""

    def speichern(self, ableitung: Modellableitung) -> None: ...

    def laden(self, modellableitungs_id: UUID) -> Modellableitung | None: ...

    def finde_identisch(
        self,
        projekt_id: UUID,
        aggregations_id: UUID,
        eingabefingerabdruck: str,
        mappingversion: int,
        unsicherheitsfingerabdruck: str,
    ) -> Modellableitung | None: ...
