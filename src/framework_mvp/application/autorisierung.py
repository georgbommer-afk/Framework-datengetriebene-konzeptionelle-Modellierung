"""Zentrale, standardmäßig verweigernde Autorisierung aller Cloud-Zugriffe."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID

from framework_mvp.application.ports.zugriffs_repository import ZugriffsRepository
from framework_mvp.domain.exceptions import ZugriffVerweigert
from framework_mvp.domain.models.zugriff import (
    GlobaleRolle,
    Gruppenaktion,
    Gruppenrolle,
    Gruppenstatus,
    Mitgliedschaftsstatus,
    Projektaktion,
    Projektzugriffsart,
    Zugriffskontext,
)

NICHT_VERFUEGBAR = "Die angeforderte Ressource ist nicht verfügbar."

_SCHREIBENDE_PROJEKTAKTIONEN = {
    Projektaktion.BEARBEITEN,
    Projektaktion.IMPORTIEREN,
    Projektaktion.LOESCHEN,
}

_ASSISTENZ_PROJEKTRECHTE = {
    Projektaktion.ANSEHEN: "projekte_lesen",
    Projektaktion.BEARBEITEN: "projekte_bearbeiten",
    Projektaktion.EXPORTIEREN: "projekte_exportieren",
    Projektaktion.IMPORTIEREN: "projekte_importieren",
    Projektaktion.LOESCHEN: "projekte_loeschen",
    Projektaktion.FORTSCHRITT_ANSEHEN: "fortschritt_lesen",
    Projektaktion.BERICHT_ANSEHEN: "berichte_lesen",
}

_ASSISTENZ_GRUPPENRECHTE = {
    Gruppenaktion.ANSEHEN: "gruppe_lesen",
    Gruppenaktion.BEARBEITEN: "gruppe_bearbeiten",
    Gruppenaktion.MITGLIEDER_VERWALTEN: "mitglieder_verwalten",
    Gruppenaktion.EINLADUNGEN_VERWALTEN: "einladungen_verwalten",
    Gruppenaktion.ARCHIVIEREN: "archive_verwalten",
    Gruppenaktion.LOESCHEN: "gruppe_loeschen",
}


def geheimnis_hash(geheimnis: str) -> str:
    """Hasht einen kryptografisch zufälligen Besitznachweis für die Persistenz."""
    return hashlib.sha256(geheimnis.encode("utf-8")).hexdigest()


class AutorisierungsService:
    """Prüft jede Aktion gegen den aktuellen persistenten Zustand (deny by default)."""

    def __init__(self, repository: ZugriffsRepository) -> None:
        self._repository = repository

    def projekt_zugriff_pruefen(
        self,
        kontext: Zugriffskontext,
        projekt_id: UUID,
        aktion: Projektaktion,
        *,
        zeitpunkt: datetime | None = None,
    ) -> None:
        """Erlaubt eine konkrete Aktion oder meldet bewusst keinen Existenzgrund."""
        if not self.projekt_zugriff_erlaubt(
            kontext, projekt_id, aktion, zeitpunkt=zeitpunkt
        ):
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)

    def projekt_zugriff_erlaubt(
        self,
        kontext: Zugriffskontext,
        projekt_id: UUID,
        aktion: Projektaktion,
        *,
        zeitpunkt: datetime | None = None,
    ) -> bool:
        """Berechnet eine Projektentscheidung ohne Ausnahmen oder Existenzleck."""
        zuordnung = self._repository.projektzugehoerigkeit_laden(projekt_id)
        if zuordnung is None:
            return False
        jetzt = (zeitpunkt or datetime.now(UTC)).astimezone(UTC)
        if zuordnung.zugriffsart is Projektzugriffsart.GAST:
            if kontext.gast_geheimnis is None or zuordnung.gast_ablauf_am is None:
                return False
            if zuordnung.gast_ablauf_am <= jetzt or zuordnung.gast_geheimnis_sha256 is None:
                return False
            return hmac.compare_digest(
                geheimnis_hash(kontext.gast_geheimnis), zuordnung.gast_geheimnis_sha256
            )
        if kontext.benutzer_id is None:
            return False
        benutzer = self._repository.benutzer_laden(kontext.benutzer_id)
        if benutzer is None or not benutzer.aktiv:
            return False
        globale_rollen = self._repository.globale_rollen_laden(kontext.benutzer_id)
        if zuordnung.zugriffsart is Projektzugriffsart.LEGACY_UNASSIGNED:
            return GlobaleRolle.SYSTEMADMIN in globale_rollen
        if zuordnung.zugriffsart is not Projektzugriffsart.KURSGRUPPE:
            return False
        if zuordnung.gruppen_id is None:
            return False
        gruppe = self._repository.kursgruppe_laden(zuordnung.gruppen_id)
        mitgliedschaft = self._repository.gruppenmitgliedschaft_laden(
            zuordnung.gruppen_id, kontext.benutzer_id
        )
        if (
            gruppe is None
            or mitgliedschaft is None
            or mitgliedschaft.status is not Mitgliedschaftsstatus.AKTIV
            or gruppe.status is Gruppenstatus.GELOESCHT
        ):
            return False
        if gruppe.status in {Gruppenstatus.SCHREIBGESCHUETZT, Gruppenstatus.ARCHIVIERT}:
            if aktion in _SCHREIBENDE_PROJEKTAKTIONEN:
                return False
        team = self._repository.projektmitglied_laden(projekt_id, kontext.benutzer_id)
        ist_teammitglied = team is not None and team.aktiv
        ist_leitung = (
            mitgliedschaft.rolle is Gruppenrolle.GRUPPENLEITUNG
            or gruppe.gruppenleitung_benutzer_id == kontext.benutzer_id
        )
        if ist_leitung:
            if aktion is Projektaktion.BEARBEITEN:
                return bool(ist_teammitglied and team and team.darf_bearbeiten)
            return True
        if mitgliedschaft.rolle is Gruppenrolle.GRUPPENASSISTENZ:
            recht = _ASSISTENZ_PROJEKTRECHTE[aktion]
            if recht not in mitgliedschaft.berechtigungen:
                return False
            if aktion is Projektaktion.BEARBEITEN:
                return bool(ist_teammitglied and team and team.darf_bearbeiten)
            return True
        if mitgliedschaft.rolle is not Gruppenrolle.TEILNEHMER or not ist_teammitglied:
            return False
        if aktion in {Projektaktion.LOESCHEN, Projektaktion.FORTSCHRITT_ANSEHEN}:
            return False
        if aktion is Projektaktion.BEARBEITEN:
            return bool(team and team.darf_bearbeiten)
        return aktion in {
            Projektaktion.ANSEHEN,
            Projektaktion.EXPORTIEREN,
            Projektaktion.IMPORTIEREN,
            Projektaktion.BERICHT_ANSEHEN,
        }

    def gruppen_zugriff_pruefen(
        self, kontext: Zugriffskontext, gruppen_id: UUID, aktion: Gruppenaktion
    ) -> None:
        if not self.gruppen_zugriff_erlaubt(kontext, gruppen_id, aktion):
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)

    def gruppen_zugriff_erlaubt(
        self, kontext: Zugriffskontext, gruppen_id: UUID, aktion: Gruppenaktion
    ) -> bool:
        if kontext.benutzer_id is None:
            return False
        benutzer = self._repository.benutzer_laden(kontext.benutzer_id)
        gruppe = self._repository.kursgruppe_laden(gruppen_id)
        mitgliedschaft = self._repository.gruppenmitgliedschaft_laden(
            gruppen_id, kontext.benutzer_id
        )
        if (
            benutzer is None
            or not benutzer.aktiv
            or gruppe is None
            or gruppe.status is Gruppenstatus.GELOESCHT
            or mitgliedschaft is None
            or mitgliedschaft.status is not Mitgliedschaftsstatus.AKTIV
        ):
            return False
        if (
            mitgliedschaft.rolle is Gruppenrolle.GRUPPENLEITUNG
            or gruppe.gruppenleitung_benutzer_id == kontext.benutzer_id
        ):
            return True
        if mitgliedschaft.rolle is Gruppenrolle.GRUPPENASSISTENZ:
            return _ASSISTENZ_GRUPPENRECHTE[aktion] in mitgliedschaft.berechtigungen
        return aktion is Gruppenaktion.ANSEHEN

    def systemadmin_pruefen(self, kontext: Zugriffskontext) -> None:
        """Prüft Adminrechte frisch; OIDC-Anmeldung allein reicht nie aus."""
        if kontext.benutzer_id is None:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        benutzer = self._repository.benutzer_laden(kontext.benutzer_id)
        rollen = self._repository.globale_rollen_laden(kontext.benutzer_id)
        if benutzer is None or not benutzer.aktiv or GlobaleRolle.SYSTEMADMIN not in rollen:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)

    def sichtbare_projekt_ids(self, kontext: Zugriffskontext) -> list[UUID]:
        """Liefert nur Kandidaten, die anschließend nochmals einzeln geprüft werden."""
        if kontext.benutzer_id is None:
            return []
        kandidaten = set(self._repository.projekt_ids_fuer_benutzer(kontext.benutzer_id))
        for gruppe in self._repository.gruppen_fuer_benutzer(kontext.benutzer_id):
            mitgliedschaft = self._repository.gruppenmitgliedschaft_laden(
                gruppe.gruppen_id, kontext.benutzer_id
            )
            if mitgliedschaft is None:
                continue
            if (
                mitgliedschaft.rolle is Gruppenrolle.GRUPPENLEITUNG
                or gruppe.gruppenleitung_benutzer_id == kontext.benutzer_id
                or mitgliedschaft.rolle is Gruppenrolle.GRUPPENASSISTENZ
                and "projekte_lesen" in mitgliedschaft.berechtigungen
            ):
                kandidaten.update(self._repository.projekt_ids_fuer_gruppe(gruppe.gruppen_id))
        if GlobaleRolle.SYSTEMADMIN in self._repository.globale_rollen_laden(
            kontext.benutzer_id
        ):
            kandidaten.update(self._repository.legacy_projekt_ids())
        return sorted(
            projekt_id
            for projekt_id in kandidaten
            if self.projekt_zugriff_erlaubt(kontext, projekt_id, Projektaktion.ANSEHEN)
        )
