"""Explizite lokale Authentifizierung für die bestehende UI-Testsuite."""

import pytest

from framework_mvp.ui.oidc import (
    LOKALER_TESTADMIN_UMGEBUNGSVARIABLE,
    LOKALER_TESTMODUS_UMGEBUNGSVARIABLE,
)


@pytest.fixture(autouse=True)
def _lokale_testidentitaet(monkeypatch: pytest.MonkeyPatch):
    """Tests aktivieren bewusst den in Produktion standardmäßig abgeschalteten Modus."""
    monkeypatch.setenv(LOKALER_TESTMODUS_UMGEBUNGSVARIABLE, "true")
    monkeypatch.setenv(LOKALER_TESTADMIN_UMGEBUNGSVARIABLE, "true")
