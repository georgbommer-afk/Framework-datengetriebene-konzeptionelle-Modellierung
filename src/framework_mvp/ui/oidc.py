"""Kleine, testbare Konfigurationsschicht um Streamlits native OIDC-Funktionen."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

LOKALER_TESTMODUS_UMGEBUNGSVARIABLE = "FRAMEWORK_MVP_LOCAL_AUTH_TEST_MODE"
LOKALER_TESTADMIN_UMGEBUNGSVARIABLE = "FRAMEWORK_MVP_LOCAL_AUTH_TEST_ADMIN"


@dataclass(frozen=True, slots=True)
class OidcKonfiguration:
    konfiguriert: bool
    systemadmin_identitaeten: frozenset[tuple[str, str]]
    lokaler_testmodus: bool
    lokaler_testadmin: bool


def oidc_konfiguration_ermitteln(
    secrets: Mapping[str, object] | None,
) -> OidcKonfiguration:
    """Interpretiert nur explizite Konfiguration; fehlende Werte vergeben keine Rechte."""
    daten = secrets or {}
    auth = daten.get("auth")
    konfiguriert = isinstance(auth, Mapping) and all(
        str(auth.get(name, "")).strip()
        for name in (
            "redirect_uri",
            "cookie_secret",
            "client_id",
            "client_secret",
            "server_metadata_url",
        )
    )
    admin_roh = daten.get("systemadmin")
    identitaeten: set[tuple[str, str]] = set()
    if isinstance(admin_roh, Mapping):
        for eintrag in admin_roh.get("identities", []):
            if isinstance(eintrag, Mapping):
                issuer = str(eintrag.get("issuer", "")).strip()
                subject = str(eintrag.get("subject", "")).strip()
                if issuer and subject:
                    identitaeten.add((issuer, subject))
    testmodus = os.getenv(LOKALER_TESTMODUS_UMGEBUNGSVARIABLE, "").casefold() in {
        "1",
        "true",
        "yes",
    }
    testadmin = testmodus and os.getenv(LOKALER_TESTADMIN_UMGEBUNGSVARIABLE, "").casefold() in {
        "1",
        "true",
        "yes",
    }
    return OidcKonfiguration(
        konfiguriert=konfiguriert,
        systemadmin_identitaeten=frozenset(identitaeten),
        lokaler_testmodus=testmodus,
        lokaler_testadmin=testadmin,
    )


def lokaler_test_claims() -> dict[str, str]:
    """Feste lokale Identität; wird ausschließlich bei explizitem Testmodus verwendet."""
    return {
        "iss": "urn:framework-mvp:local-test",
        "sub": "local-test-user",
        "email": "local-test@example.invalid",
        "name": "Lokaler Testbenutzer",
    }
