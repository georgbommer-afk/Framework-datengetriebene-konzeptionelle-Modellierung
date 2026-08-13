"""Port für kontrollierte, projektgebundene Löschtransaktionen."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ZwischendatensatzLoeschplan:
    """Vorab ermittelte, unveränderliche Abhängigkeiten eines T."""

    transformationsplan_id: UUID
    relative_artefaktpfade: tuple[str, ...]


class LoeschRepository(Protocol):
    """Grenze zwischen Löschkoordination und SQLite-Transaktion."""

    def zwischendatensatz_loeschplan(
        self, projekt_id: UUID, zwischendatensatz_id: UUID
    ) -> ZwischendatensatzLoeschplan | None: ...

    def zwischendatensatz_loeschen(
        self, projekt_id: UUID, zwischendatensatz_id: UUID, transformationsplan_id: UUID
    ) -> None: ...

    def projekt_loeschen(self, projekt_id: UUID) -> bool: ...
