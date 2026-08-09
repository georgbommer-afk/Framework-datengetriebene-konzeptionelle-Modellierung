"""Port für persistierte Qualitätsprüfungen."""

from typing import Protocol
from uuid import UUID

from framework_mvp.domain.models import (
    Qualitaetsfreigabe,
    Qualitaetsmassnahmenplan,
    QualitaetspruefungArtefakt,
    Qualitaetsregel,
)


class QualitaetRepository(Protocol):
    """Abstrakter Speichervertrag für Qualitätsergebnisse."""

    def speichern(
        self,
        artefakt: QualitaetspruefungArtefakt,
        regeln: tuple[Qualitaetsregel, ...],
        plan: Qualitaetsmassnahmenplan,
        report: dict[str, object],
        vergleich: dict[str, object],
    ) -> None:
        """Speichert Prüfung, Regeln und Maßnahmen."""
        ...

    def laden(self, quality_run_id: UUID) -> QualitaetspruefungArtefakt | None:
        """Lädt eine Qualitätsprüfung."""
        ...

    def fuer_projekt(self, projekt_id: UUID) -> list[QualitaetspruefungArtefakt]:
        """Listet Qualitätsprüfungen eines Projekts."""
        ...

    def freigabe_speichern(
        self,
        freigabe: Qualitaetsfreigabe,
        report: dict[str, object],
        report_sha256: str,
    ) -> None:
        """Speichert eine unveränderte E*-Referenz im kompatiblen Qualitätsspeicher."""
        ...

    def freigabe_laden(self, freigabe_id: UUID) -> Qualitaetsfreigabe | None:
        """Lädt ausschließlich eine neue Quality-Gate-Freigabe."""
        ...

    def freigaben_fuer_projekt(self, projekt_id: UUID) -> list[Qualitaetsfreigabe]:
        """Listet ausschließlich neue E*-Freigaben eines Projekts."""
        ...
