"""OIDC-Claim-Mapping und explizites Bootstrap der globalen Administration."""

from collections.abc import Mapping

from framework_mvp.application.ports.zugriffs_repository import ZugriffsRepository
from framework_mvp.domain.exceptions import ZugriffVerweigert
from framework_mvp.domain.models.zugriff import Benutzer, GlobaleRolle, Zugriffskontext


class IdentitaetsService:
    """Persistiert nur stabile Claims und niemals OIDC-Token oder Passwörter."""

    def __init__(self, repository: ZugriffsRepository) -> None:
        self._repository = repository

    def aus_oidc_claims(
        self,
        claims: Mapping[str, object],
        *,
        systemadmin_identitaeten: frozenset[tuple[str, str]] = frozenset(),
    ) -> tuple[Zugriffskontext, Benutzer]:
        issuer = str(claims.get("iss", "")).strip()
        subject = str(claims.get("sub", "")).strip()
        if not issuer or not subject:
            raise ZugriffVerweigert("Die Anmeldung enthält keine stabile OIDC-Identität.")
        benutzer = self._repository.oidc_benutzer_speichern(
            issuer=issuer,
            subject=subject,
            email=str(claims.get("email", "")),
            anzeigename=str(claims.get("name", claims.get("preferred_username", ""))),
        )
        if (issuer, subject) in systemadmin_identitaeten:
            self._repository.globale_rolle_setzen(
                benutzer.benutzer_id, GlobaleRolle.SYSTEMADMIN, vergeben_von=None
            )
        return Zugriffskontext.angemeldet(benutzer.benutzer_id), benutzer
