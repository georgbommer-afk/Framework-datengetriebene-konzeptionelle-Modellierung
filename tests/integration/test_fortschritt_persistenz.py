"""Persistierter Fortschritt bleibt über Servicesitzungen hinweg identisch."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from framework_mvp.application.autorisierung import AutorisierungsService, geheimnis_hash
from framework_mvp.application.fortschritt_service import FortschrittService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
from framework_mvp.domain.models.zugriff import (
    Projektzugehoerigkeit,
    Projektzugriffsart,
    Zugriffskontext,
)
from framework_mvp.infrastructure.persistence.sqlite_fortschritt_repository import (
    SQLiteFortschrittRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_zugriffs_repository import (
    SQLiteZugriffsRepository,
)


def test_fortschritt_kommt_nicht_aus_session_state(tmp_path: Path) -> None:
    db = tmp_path / "fortschritt.sqlite"
    projekt = ProjektService(SQLiteProjektRepository(db)).projekt_anlegen(
        bezeichnung="Fortschritt",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Problem", "Zweck", Systemtyp.PRODUKTION, "Grenze"
        ),
    )
    geheimnis = "g" * 40
    jetzt = datetime.now(UTC)
    repository = SQLiteZugriffsRepository(db)
    repository.projektzugehoerigkeit_speichern(
        Projektzugehoerigkeit(
            projekt.projekt_id,
            Projektzugriffsart.GAST,
            None,
            geheimnis_hash(geheimnis),
            jetzt + timedelta(hours=2),
            jetzt,
            1,
            jetzt,
        )
    )
    kontext = Zugriffskontext.gast(geheimnis)
    service = FortschrittService(
        repository, SQLiteFortschrittRepository(db), AutorisierungsService(repository)
    )
    gespeichert = service.aktualisieren(
        kontext,
        projekt.projekt_id,
        schritt=4,
        unterschritt="Semantische Rollen",
    )
    neues_repository = SQLiteZugriffsRepository(db)
    neue_sitzung = FortschrittService(
        neues_repository,
        SQLiteFortschrittRepository(db),
        AutorisierungsService(neues_repository),
    ).laden(kontext, projekt.projekt_id)
    assert neue_sitzung.prozent == gespeichert.prozent
    assert neue_sitzung.schritt == 4
    assert neue_sitzung.unterschritt == "Semantische Rollen"
