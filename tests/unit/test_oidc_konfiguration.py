"""OIDC-Konfiguration vergibt ohne expliziten Bootstrap niemals Adminrechte."""

import pytest

from framework_mvp.ui.oidc import (
    LOKALER_TESTADMIN_UMGEBUNGSVARIABLE,
    LOKALER_TESTMODUS_UMGEBUNGSVARIABLE,
    oidc_konfiguration_ermitteln,
)


def test_fehlende_oidc_konfiguration_bleibt_oeffentlich_aber_nicht_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(LOKALER_TESTMODUS_UMGEBUNGSVARIABLE, raising=False)
    monkeypatch.delenv(LOKALER_TESTADMIN_UMGEBUNGSVARIABLE, raising=False)
    konfiguration = oidc_konfiguration_ermitteln({})
    assert not konfiguration.konfiguriert
    assert not konfiguration.lokaler_testmodus
    assert not konfiguration.lokaler_testadmin
    assert not konfiguration.systemadmin_identitaeten


def test_admin_bootstrap_verwendet_issuer_und_subject_nicht_email() -> None:
    konfiguration = oidc_konfiguration_ermitteln(
        {
            "systemadmin": {
                "identities": [
                    {
                        "issuer": "https://idp.example",
                        "subject": "stabil-123",
                        "email": "wird-nicht-verwendet@example.org",
                    }
                ]
            }
        }
    )
    assert konfiguration.systemadmin_identitaeten == frozenset(
        {("https://idp.example", "stabil-123")}
    )
