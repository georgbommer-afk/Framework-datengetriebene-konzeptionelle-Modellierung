from unittest.mock import MagicMock
from uuid import uuid4

from framework_mvp.application.autorisierung import AutorisierungsService
from framework_mvp.application.mandanten_projekt_service import MandantenProjektService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.models import Untersuchungsauftrag
from framework_mvp.domain.models.zugriff import GlobaleRolle, Zugriffskontext
from framework_mvp.ui.cloud_access import GebundenerProjektService


def _service(
    *, legacy_erstellung_erlaubt: bool
) -> tuple[GebundenerProjektService, MagicMock, MagicMock, Zugriffskontext]:
    kontext = Zugriffskontext.angemeldet(uuid4())
    rohservice = MagicMock(spec=ProjektService)
    mandantenservice = MagicMock(spec=MandantenProjektService)
    service = GebundenerProjektService(
        kontext,
        rohservice,
        mandantenservice,
        MagicMock(spec=AutorisierungsService),
        ziel_gruppen_id=None,
        gast_projekt_id=None,
        globale_rollen=frozenset({GlobaleRolle.SYSTEMADMIN}),
        legacy_erstellung_erlaubt=legacy_erstellung_erlaubt,
    )
    return service, rohservice, mandantenservice, kontext


def test_systemadmin_umgeht_mandantenservice_im_produktionsmodus_nicht() -> None:
    service, rohservice, mandantenservice, kontext = _service(legacy_erstellung_erlaubt=False)
    auftrag = MagicMock(spec=Untersuchungsauftrag)

    service.projekt_anlegen(bezeichnung="Projekt", untersuchungsauftrag=auftrag)

    rohservice.projekt_anlegen.assert_not_called()
    mandantenservice.projekt_anlegen.assert_called_once_with(
        kontext,
        bezeichnung="Projekt",
        untersuchungsauftrag=auftrag,
        gruppen_id=None,
        beteiligte_personen=(),
    )


def test_legacy_erstellung_bleibt_explizitem_testmodus_vorbehalten() -> None:
    service, rohservice, mandantenservice, _ = _service(legacy_erstellung_erlaubt=True)
    auftrag = MagicMock(spec=Untersuchungsauftrag)

    service.projekt_anlegen(bezeichnung="Projekt", untersuchungsauftrag=auftrag)

    mandantenservice.projekt_anlegen.assert_not_called()
    rohservice.projekt_anlegen.assert_called_once_with(
        bezeichnung="Projekt",
        untersuchungsauftrag=auftrag,
        beteiligte_personen=(),
    )
