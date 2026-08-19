"""Sofortige Gastlöschung und opportunistische TTL-Bereinigung."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from framework_mvp.application.autorisierung import AutorisierungsService, geheimnis_hash
from framework_mvp.application.gast_service import BereinigungsService
from framework_mvp.application.loesch_service import LoeschService
from framework_mvp.application.mandanten_projekt_service import AutorisierterLoeschService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
from framework_mvp.domain.models.zugriff import (
    Projektzugehoerigkeit,
    Projektzugriffsart,
    Zugriffskontext,
)
from framework_mvp.infrastructure.persistence.sqlite_loesch_repository import (
    SQLiteLoeschRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_zugriffs_repository import (
    SQLiteZugriffsRepository,
)
from framework_mvp.workspace import WorkspaceKonfiguration


def _gastprojekt(db: Path, workspace: WorkspaceKonfiguration, geheimnis: str, ablauf: datetime):
    projekt = ProjektService(SQLiteProjektRepository(db)).projekt_anlegen(
        bezeichnung="Gast",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Problem", "Zweck", Systemtyp.PRODUKTION, "Grenze"
        ),
    )
    workspace.fuer_projekt_anlegen(projekt.projekt_id)
    jetzt = datetime.now(UTC)
    repository = SQLiteZugriffsRepository(db)
    repository.projektzugehoerigkeit_speichern(
        Projektzugehoerigkeit(
            projekt.projekt_id,
            Projektzugriffsart.GAST,
            None,
            geheimnis_hash(geheimnis),
            ablauf,
            jetzt,
            1,
            jetzt,
        )
    )
    return projekt


def test_demo_beenden_loescht_nur_eigenes_projekt(tmp_path: Path) -> None:
    db = tmp_path / "gaeste.sqlite"
    workspace = WorkspaceKonfiguration(tmp_path / "workspace")
    jetzt = datetime.now(UTC)
    eigenes = _gastprojekt(db, workspace, "a" * 40, jetzt + timedelta(hours=1))
    fremdes = _gastprojekt(db, workspace, "b" * 40, jetzt + timedelta(hours=1))
    repository = SQLiteZugriffsRepository(db)
    service = AutorisierterLoeschService(
        LoeschService(SQLiteLoeschRepository(db), workspace),
        AutorisierungsService(repository),
    )
    service.projekt_loeschen(Zugriffskontext.gast("a" * 40), eigenes.projekt_id)
    projekt_repository = SQLiteProjektRepository(db)
    assert projekt_repository.laden(eigenes.projekt_id) is None
    assert projekt_repository.laden(fremdes.projekt_id) is not None


def test_opportunistische_bereinigung_entfernt_nur_abgelaufene_gaeste(
    tmp_path: Path,
) -> None:
    db = tmp_path / "ttl.sqlite"
    workspace = WorkspaceKonfiguration(tmp_path / "workspace")
    jetzt = datetime.now(UTC)
    abgelaufen = _gastprojekt(db, workspace, "a" * 40, jetzt - timedelta(seconds=1))
    aktiv = _gastprojekt(db, workspace, "b" * 40, jetzt + timedelta(hours=1))
    geloescht = BereinigungsService(
        SQLiteZugriffsRepository(db),
        LoeschService(SQLiteLoeschRepository(db), workspace),
        workspace,
    ).opportunistisch(zeitpunkt=jetzt)
    repository = SQLiteProjektRepository(db)
    assert geloescht == 1
    assert repository.laden(abgelaufen.projekt_id) is None
    assert repository.laden(aktiv.projekt_id) is not None
