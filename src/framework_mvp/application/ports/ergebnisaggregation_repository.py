"""Port für persistierte aggregierte Analyseergebnisse A_G."""

from typing import Protocol
from uuid import UUID

from framework_mvp.domain.models import Ergebnisaggregation


class ErgebnisaggregationRepository(Protocol):
    """Abstrakter, transaktionaler Metadatenspeicher."""

    def speichern(self, aggregation: Ergebnisaggregation) -> None: ...

    def laden(self, aggregations_id: UUID) -> Ergebnisaggregation | None: ...

    def fuer_analyse(self, projekt_id: UUID, analyse_id: UUID) -> list[Ergebnisaggregation]: ...
