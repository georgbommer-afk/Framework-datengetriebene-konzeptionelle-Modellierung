"""Port für atomar persistierte Validierungsläufe und K*."""

from typing import Protocol
from uuid import UUID

from framework_mvp.domain.models import Modellvalidierung


class ModellvalidierungRepository(Protocol):
    """Metadatenzugriff ohne fachliche Validierungs- oder Exportlogik."""

    def speichern(self, validierung: Modellvalidierung) -> None: ...

    def laden(self, validierungslauf_id: UUID) -> Modellvalidierung | None: ...

    def finde_identisch(
        self,
        projekt_id: UUID,
        modellableitungs_id: UUID,
        eingabefingerabdruck: str,
        entscheidungsfingerabdruck: str,
    ) -> Modellvalidierung | None: ...
