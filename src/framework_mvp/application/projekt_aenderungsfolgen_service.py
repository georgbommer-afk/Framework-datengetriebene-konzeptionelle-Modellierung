"""Gezielte persistierte Folgewirkungen fachlicher Änderungen am Auftrag U."""

from datetime import UTC, datetime
from uuid import UUID

from framework_mvp.application.aktive_lineage_service import (
    AktiveLineageService,
    LineageEndpunkt,
)
from framework_mvp.application.fortschritt_service import (
    FACHLICHE_UNTERSCHRITTE,
    LEERER_ABSCHLUSS,
    _normalisiere_abschluesse,
)
from framework_mvp.application.ports.zugriffs_repository import ZugriffsRepository
from framework_mvp.domain.models.zugriff import Projektfortschritt, phase_fuer_schritt


class ProjektAenderungsfolgenService:
    """Synchronisiert aktive Lineage und Fortschritt nach einer KPI-only-Änderung."""

    def __init__(
        self,
        aktive_lineage: AktiveLineageService,
        fortschritt_repository: ZugriffsRepository,
    ) -> None:
        self._aktive_lineage = aktive_lineage
        self._fortschritt = fortschritt_repository

    def kpi_auswahl_geaendert(self, projekt_id: UUID) -> None:
        """Deaktiviert A_G und Nachfolger nur bei vorhandener P-/A_D-Grundlage."""
        checkpoint = self._aktive_lineage.laden(projekt_id)
        if checkpoint is None or checkpoint.framework_schritt < 7:
            return
        gekuerzt = self._aktive_lineage.bis_endpunkt_zuruecksetzen(
            projekt_id, LineageEndpunkt.P_A_D
        )
        if gekuerzt is None or gekuerzt.endpunkt is not LineageEndpunkt.P_A_D:
            return
        alt = self._fortschritt.fortschritt_laden(projekt_id)
        abschluesse = list(
            LEERER_ABSCHLUSS
            if alt is None
            else _normalisiere_abschluesse(alt.abgeschlossene_unterschritte)
        )
        for index in range(6):
            abschluesse[index] = len(FACHLICHE_UNTERSCHRITTE[index + 1])
        abschluesse[6:] = [0] * 4
        neuer_stand = tuple(abschluesse)
        self._fortschritt.fortschritt_speichern(
            Projektfortschritt(
                projekt_id=projekt_id,
                framework_schritt=7,
                fachlicher_unterschritt=FACHLICHE_UNTERSCHRITTE[7][0],
                fortschritt_zaehler=sum(neuer_stand),
                fortschritt_nenner=sum(map(len, FACHLICHE_UNTERSCHRITTE.values())),
                phase=phase_fuer_schritt(7),
                status="in_bearbeitung",
                gespeichert_am=datetime.now(UTC),
                revision=1 if alt is None else alt.revision + 1,
                abgeschlossene_unterschritte=neuer_stand,
            )
        )
