"""Anwendungsservices für private Kursgruppen, Rollen und Einladungen."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from framework_mvp.application.autorisierung import NICHT_VERFUEGBAR, AutorisierungsService
from framework_mvp.application.loesch_service import LoeschService
from framework_mvp.application.ports.zugriffs_repository import ZugriffsRepository
from framework_mvp.domain.exceptions import Domaenenfehler, ZugriffVerweigert
from framework_mvp.domain.models.zugriff import (
    GlobaleRolle,
    Gruppenaktion,
    Gruppeneinladung,
    Gruppenmitgliedschaft,
    Gruppenrolle,
    Gruppenstatus,
    Kursgruppe,
    Mitgliedschaftsstatus,
    Projektmitglied,
    Zugriffskontext,
)


class KursgruppenService:
    """Schützt Gruppenoperationen serverseitig und hält Rollen gruppenspezifisch."""

    def __init__(
        self, repository: ZugriffsRepository, autorisierung: AutorisierungsService
    ) -> None:
        self._repository = repository
        self._autorisierung = autorisierung

    def gruppe_anlegen(
        self,
        kontext: Zugriffskontext,
        *,
        bezeichnung: str,
        beschreibung: str = "",
        beginn_am: date | None = None,
        ende_am: date | None = None,
        maximale_teilnehmende: int = 100,
        maximale_projekte: int = 15,
        speicherlimit_pro_projekt_bytes: int = 200 * 1024 * 1024,
        aufbewahrung_bis: datetime | None = None,
    ) -> Kursgruppe:
        if kontext.benutzer_id is None:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        benutzer = self._repository.benutzer_laden(kontext.benutzer_id)
        rollen = self._repository.globale_rollen_laden(kontext.benutzer_id)
        if (
            benutzer is None
            or not benutzer.aktiv
            or not rollen.intersection({GlobaleRolle.GRUPPENLEITUNG, GlobaleRolle.SYSTEMADMIN})
        ):
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        jetzt = datetime.now(UTC)
        gruppe = Kursgruppe(
            gruppen_id=uuid4(),
            bezeichnung=bezeichnung.strip(),
            beschreibung=beschreibung.strip(),
            gruppenleitung_benutzer_id=kontext.benutzer_id,
            beginn_am=beginn_am,
            ende_am=ende_am,
            maximale_teilnehmende=maximale_teilnehmende,
            maximale_projekte=maximale_projekte,
            speicherlimit_pro_projekt_bytes=speicherlimit_pro_projekt_bytes,
            aufbewahrung_bis=aufbewahrung_bis,
            status=Gruppenstatus.AKTIV,
            erstellt_am=jetzt,
            geaendert_am=jetzt,
        )
        self._repository.kursgruppe_speichern(gruppe)
        self._repository.gruppenmitgliedschaft_speichern(
            Gruppenmitgliedschaft(
                gruppen_id=gruppe.gruppen_id,
                benutzer_id=kontext.benutzer_id,
                rolle=Gruppenrolle.GRUPPENLEITUNG,
                status=Mitgliedschaftsstatus.AKTIV,
                berechtigungen=frozenset(),
                beigetreten_am=jetzt,
                geaendert_am=jetzt,
            )
        )
        return gruppe

    def gruppen_auflisten(self, kontext: Zugriffskontext) -> list[Kursgruppe]:
        if kontext.benutzer_id is None:
            return []
        return self._repository.gruppen_fuer_benutzer(kontext.benutzer_id)

    def mitgliedschaft_setzen(
        self,
        kontext: Zugriffskontext,
        gruppen_id: UUID,
        benutzer_id: UUID,
        *,
        rolle: Gruppenrolle,
        status: Mitgliedschaftsstatus = Mitgliedschaftsstatus.AKTIV,
        berechtigungen: frozenset[str] = frozenset(),
    ) -> Gruppenmitgliedschaft:
        self._autorisierung.gruppen_zugriff_pruefen(
            kontext, gruppen_id, Gruppenaktion.MITGLIEDER_VERWALTEN
        )
        if rolle is not Gruppenrolle.GRUPPENASSISTENZ and berechtigungen:
            raise Domaenenfehler("Feinrechte sind nur für Gruppenassistenzen zulässig.")
        jetzt = datetime.now(UTC)
        vorhanden = self._repository.gruppenmitgliedschaft_laden(gruppen_id, benutzer_id)
        mitgliedschaft = Gruppenmitgliedschaft(
            gruppen_id=gruppen_id,
            benutzer_id=benutzer_id,
            rolle=rolle,
            status=status,
            berechtigungen=berechtigungen,
            beigetreten_am=jetzt if vorhanden is None else vorhanden.beigetreten_am,
            geaendert_am=jetzt,
        )
        self._repository.gruppenmitgliedschaft_speichern(mitgliedschaft)
        return mitgliedschaft

    def projekt_zuweisen(
        self,
        kontext: Zugriffskontext,
        gruppen_id: UUID,
        projekt_id: UUID,
        benutzer_id: UUID,
        *,
        darf_bearbeiten: bool = True,
    ) -> Projektmitglied:
        self._autorisierung.gruppen_zugriff_pruefen(
            kontext, gruppen_id, Gruppenaktion.MITGLIEDER_VERWALTEN
        )
        zuordnung = self._repository.projektzugehoerigkeit_laden(projekt_id)
        if zuordnung is None or zuordnung.gruppen_id != gruppen_id:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        mitgliedschaft = self._repository.gruppenmitgliedschaft_laden(gruppen_id, benutzer_id)
        if mitgliedschaft is None or mitgliedschaft.status is not Mitgliedschaftsstatus.AKTIV:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        projektmitglied = Projektmitglied(
            projekt_id=projekt_id,
            benutzer_id=benutzer_id,
            darf_bearbeiten=darf_bearbeiten,
            aktiv=True,
        )
        self._repository.projektmitglied_speichern(projektmitglied, zeitpunkt=datetime.now(UTC))
        return projektmitglied


class EinladungsService:
    """Erzeugt mindestens 256-Bit-Tokens und persistiert ausschließlich deren Hash."""

    def __init__(
        self, repository: ZugriffsRepository, autorisierung: AutorisierungsService
    ) -> None:
        self._repository = repository
        self._autorisierung = autorisierung

    def erstellen(
        self,
        kontext: Zugriffskontext,
        gruppen_id: UUID,
        *,
        gueltig_fuer: timedelta = timedelta(days=7),
        maximale_nutzungen: int = 1,
        erlaubte_email_domain: str = "",
        erlaubte_emails: tuple[str, ...] = (),
    ) -> tuple[Gruppeneinladung, str]:
        self._autorisierung.gruppen_zugriff_pruefen(
            kontext, gruppen_id, Gruppenaktion.EINLADUNGEN_VERWALTEN
        )
        if kontext.benutzer_id is None:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        if gueltig_fuer <= timedelta(0) or maximale_nutzungen < 1:
            raise Domaenenfehler("Einladungsdauer und Nutzungszahl müssen positiv sein.")
        jetzt = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        einladung = Gruppeneinladung(
            einladungs_id=uuid4(),
            gruppen_id=gruppen_id,
            token_sha256=hashlib.sha256(token.encode()).hexdigest(),
            laeuft_ab_am=jetzt + gueltig_fuer,
            maximale_nutzungen=maximale_nutzungen,
            anzahl_nutzungen=0,
            erlaubte_email_domain=erlaubte_email_domain.strip().casefold().lstrip("@"),
            erlaubte_emails=tuple(
                sorted({email.strip().casefold() for email in erlaubte_emails if email.strip()})
            ),
            widerrufen_am=None,
            erstellt_von_benutzer_id=kontext.benutzer_id,
            erstellt_am=jetzt,
        )
        self._repository.einladung_speichern(einladung)
        return einladung, token

    def einloesen(self, kontext: Zugriffskontext, token: str) -> Gruppenmitgliedschaft:
        if kontext.benutzer_id is None:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        benutzer = self._repository.benutzer_laden(kontext.benutzer_id)
        if benutzer is None or not benutzer.aktiv:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return self._repository.einladung_atomar_einloesen(
            token_sha256=token_hash, benutzer=benutzer, zeitpunkt=datetime.now(UTC)
        )

    def auflisten(self, kontext: Zugriffskontext, gruppen_id: UUID) -> list[Gruppeneinladung]:
        self._autorisierung.gruppen_zugriff_pruefen(
            kontext, gruppen_id, Gruppenaktion.EINLADUNGEN_VERWALTEN
        )
        return self._repository.einladungen_fuer_gruppe(gruppen_id)

    def widerrufen(self, kontext: Zugriffskontext, gruppen_id: UUID, einladungs_id: UUID) -> None:
        self._autorisierung.gruppen_zugriff_pruefen(
            kontext, gruppen_id, Gruppenaktion.EINLADUNGEN_VERWALTEN
        )
        if not self._repository.einladung_widerrufen(
            gruppen_id, einladungs_id, zeitpunkt=datetime.now(UTC)
        ):
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)


class KursgruppenLoeschService:
    """Löscht genau eine autorisierte Gruppe und ihre lokalen Projekte."""

    def __init__(
        self,
        repository: ZugriffsRepository,
        autorisierung: AutorisierungsService,
        loesch_service: LoeschService,
    ) -> None:
        self._repository = repository
        self._autorisierung = autorisierung
        self._loeschen = loesch_service

    def gruppe_loeschen(self, kontext: Zugriffskontext, gruppen_id: UUID) -> int:
        self._autorisierung.gruppen_zugriff_pruefen(kontext, gruppen_id, Gruppenaktion.LOESCHEN)
        projekt_ids = self._repository.projekt_ids_fuer_gruppe(gruppen_id)
        for projekt_id in projekt_ids:
            self._loeschen.projekt_loeschen(projekt_id)
        jetzt = datetime.now(UTC)
        self._repository.kursgruppe_status_setzen(gruppen_id, status="geloescht", zeitpunkt=jetzt)
        self._repository.bereinigung_protokollieren(
            projekt_id=None,
            gruppen_id=gruppen_id,
            aktion="kursgruppe_manuell_loeschen",
            ergebnis="erfolgreich",
            details={"projektanzahl": len(projekt_ids)},
            zeitpunkt=jetzt,
        )
        return len(projekt_ids)
