"""Tests für Event-Log-Zeitraum und zentrale Framework-Navigation."""

from datetime import UTC, datetime

from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.models import (
    BetrachtungszeitraumModus,
    Projektstatus,
    Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.ui.navigation import naechster_framework_bereich
from tests.unit.test_projekt_service import InMemoryProjektRepository


def test_event_log_zeitraum_wird_kontrolliert_aktualisiert() -> None:
    """Schritt 4 kann den Zeitraum ergänzen, ohne Status oder Altwerte zu verändern."""
    service = ProjektService(InMemoryProjektRepository())
    projekt = service.projekt_anlegen(
        bezeichnung="Zeitraum",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Problem",
            "Analyse",
            Systemtyp.PRODUKTION,
            "Grenze",
            anmerkungen="Altwert",
        ),
    )
    aktualisiert = service.betrachtungszeitraum_aus_event_log_aktualisieren(
        projekt.projekt_id,
        fruehester_ereigniszeitpunkt=datetime(2025, 1, 2, 8, tzinfo=UTC),
        spaetester_ereigniszeitpunkt=datetime(2025, 3, 4, 17, tzinfo=UTC),
    )
    zeitraum = aktualisiert.untersuchungsauftrag.betrachtungszeitraum
    assert zeitraum.modus is BetrachtungszeitraumModus.AUS_DATEN
    assert zeitraum.beginn.isoformat() == "2025-01-02"  # type: ignore[union-attr]
    assert zeitraum.ende.isoformat() == "2025-03-04"  # type: ignore[union-attr]
    assert aktualisiert.status is Projektstatus.ENTWURF
    assert aktualisiert.untersuchungsauftrag.anmerkungen == "Altwert"


def test_zentrale_navigation_bestimmt_schritt_zwei() -> None:
    """Die wiederverwendbare Navigation bildet Schritt 1 eindeutig auf ETL ab."""
    assert naechster_framework_bereich(1) == "2 ETL durchführen"
