"""Mandanten-, Rollen- und Zugriffstypen der Community-Cloud-Anwendung."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID

from framework_mvp.domain.exceptions import Domaenenfehler


class GlobaleRolle(StrEnum):
    """Sparsam vergebene anwendungsweite Rollen."""

    GRUPPENLEITUNG = "gruppenleitung"
    SYSTEMADMIN = "systemadmin"


class Gruppenrolle(StrEnum):
    """Rolle einer angemeldeten Person innerhalb einer privaten Kursgruppe."""

    TEILNEHMER = "teilnehmer"
    GRUPPENLEITUNG = "gruppenleitung"
    GRUPPENASSISTENZ = "gruppenassistenz"


class Gruppenstatus(StrEnum):
    """Lebenszyklus einer privaten Kursgruppe."""

    AKTIV = "aktiv"
    ABGELAUFEN = "abgelaufen"
    GESPERRT = "gesperrt"
    GELOESCHT = "geloescht"


class Mitgliedschaftsstatus(StrEnum):
    """Serverseitig geprüfter Zustand einer Mitgliedschaft."""

    AKTIV = "aktiv"
    ENTFERNT = "entfernt"
    GESPERRT = "gesperrt"


class Projektzugriffsart(StrEnum):
    """Exklusive Mandantenzuordnung eines Projekts."""

    GAST = "gast"
    KURSGRUPPE = "kursgruppe"
    LEGACY_UNASSIGNED = "legacy_unassigned"


class Projektaktion(StrEnum):
    """Explizit autorisierbare Projektoperationen."""

    ANSEHEN = "ansehen"
    BEARBEITEN = "bearbeiten"
    EXPORTIEREN = "exportieren"
    IMPORTIEREN = "importieren"
    LOESCHEN = "loeschen"
    FORTSCHRITT_ANSEHEN = "fortschritt_ansehen"
    BERICHT_ANSEHEN = "bericht_ansehen"


class Gruppenaktion(StrEnum):
    """Explizit autorisierbare Gruppenoperationen."""

    ANSEHEN = "ansehen"
    BEARBEITEN = "bearbeiten"
    MITGLIEDER_VERWALTEN = "mitglieder_verwalten"
    EINLADUNGEN_VERWALTEN = "einladungen_verwalten"
    ARCHIVIEREN = "archivieren"
    LOESCHEN = "loeschen"


@dataclass(frozen=True, slots=True)
class Zugriffskontext:
    """Explizite Identität; enthält bei Gästen nur den flüchtigen Besitznachweis."""

    benutzer_id: UUID | None = None
    gast_geheimnis: str | None = None

    def __post_init__(self) -> None:
        if (self.benutzer_id is None) == (self.gast_geheimnis is None):
            raise Domaenenfehler(
                "Ein Zugriffskontext muss genau eine angemeldete oder eine Gastidentität enthalten."
            )
        if self.gast_geheimnis is not None and len(self.gast_geheimnis) < 32:
            raise Domaenenfehler("Der Gast-Besitznachweis ist zu kurz.")

    @classmethod
    def angemeldet(cls, benutzer_id: UUID) -> Zugriffskontext:
        return cls(benutzer_id=benutzer_id)

    @classmethod
    def gast(cls, geheimnis: str) -> Zugriffskontext:
        return cls(gast_geheimnis=geheimnis)


@dataclass(frozen=True, slots=True)
class Benutzer:
    """Persistierte, providergebundene OIDC-Identität ohne Tokenmaterial."""

    benutzer_id: UUID
    oidc_issuer: str
    oidc_subject: str
    email: str
    anzeigename: str
    aktiv: bool
    erstellt_am: datetime
    zuletzt_angemeldet_am: datetime


@dataclass(frozen=True, slots=True)
class Kursgruppe:
    """Private Lehrveranstaltungs- oder Arbeitsgruppe."""

    gruppen_id: UUID
    bezeichnung: str
    beschreibung: str
    gruppenleitung_benutzer_id: UUID
    beginn_am: date | None
    ende_am: date | None
    maximale_teilnehmende: int
    maximale_projekte: int
    speicherlimit_pro_projekt_bytes: int
    aufbewahrung_bis: datetime | None
    status: Gruppenstatus
    erstellt_am: datetime
    geaendert_am: datetime

    def __post_init__(self) -> None:
        if not self.bezeichnung.strip():
            raise Domaenenfehler("Die Gruppenbezeichnung darf nicht leer sein.")
        if not 1 <= self.maximale_teilnehmende <= 10_000:
            raise Domaenenfehler("Die Teilnehmendenzahl muss zwischen 1 und 10.000 liegen.")
        if not 1 <= self.maximale_projekte <= 10_000:
            raise Domaenenfehler("Die Projektanzahl muss zwischen 1 und 10.000 liegen.")
        if self.speicherlimit_pro_projekt_bytes <= 0:
            raise Domaenenfehler("Das Speicherlimit muss positiv sein.")
        if self.beginn_am and self.ende_am and self.ende_am < self.beginn_am:
            raise Domaenenfehler("Das Gruppenende darf nicht vor dem Beginn liegen.")


@dataclass(frozen=True, slots=True)
class Gruppenmitgliedschaft:
    """Rolle und fein granulare Assistenzrechte in genau einer Gruppe."""

    gruppen_id: UUID
    benutzer_id: UUID
    rolle: Gruppenrolle
    status: Mitgliedschaftsstatus
    berechtigungen: frozenset[str]
    beigetreten_am: datetime
    geaendert_am: datetime


@dataclass(frozen=True, slots=True)
class Projektzugehoerigkeit:
    """Mandantenbindung und Gastablauf eines Projekts."""

    projekt_id: UUID
    zugriffsart: Projektzugriffsart
    gruppen_id: UUID | None
    gast_geheimnis_sha256: str | None
    gast_ablauf_am: datetime | None
    zuletzt_aktiv_am: datetime
    revision: int
    erstellt_am: datetime


@dataclass(frozen=True, slots=True)
class Projektmitglied:
    """Explizite Teamzuordnung eines angemeldeten Benutzers."""

    projekt_id: UUID
    benutzer_id: UUID
    darf_bearbeiten: bool
    aktiv: bool


@dataclass(frozen=True, slots=True)
class Gruppeneinladung:
    """Persistierte Einladung; der Klartext-Token ist absichtlich nicht enthalten."""

    einladungs_id: UUID
    gruppen_id: UUID
    token_sha256: str
    laeuft_ab_am: datetime
    maximale_nutzungen: int
    anzahl_nutzungen: int
    erlaubte_email_domain: str
    erlaubte_emails: tuple[str, ...]
    widerrufen_am: datetime | None
    erstellt_von_benutzer_id: UUID
    erstellt_am: datetime


@dataclass(frozen=True, slots=True)
class Projektfortschritt:
    """Persistierter, zwischen Projekt- und Dashboardansicht geteilter Fortschritt."""

    projekt_id: UUID
    framework_schritt: int
    fachlicher_unterschritt: str
    fortschritt_zaehler: int
    fortschritt_nenner: int
    phase: int
    status: str
    gespeichert_am: datetime
    revision: int

    def __post_init__(self) -> None:
        if not 1 <= self.framework_schritt <= 10:
            raise Domaenenfehler("Der Framework-Schritt muss zwischen 1 und 10 liegen.")
        if self.phase != phase_fuer_schritt(self.framework_schritt):
            raise Domaenenfehler("Die Phase passt nicht zum Framework-Schritt.")
        if not 0 <= self.fortschritt_zaehler <= self.fortschritt_nenner:
            raise Domaenenfehler("Der Fortschrittsbruch ist ungültig.")
        if self.status not in {"in_bearbeitung", "abgeschlossen", "blockiert"}:
            raise Domaenenfehler("Der Fortschrittsstatus ist ungültig.")


def phase_fuer_schritt(schritt: int) -> int:
    """Liefert die stabilen Phasengrenzen 1–5, 6–7 und 8–10."""
    if not 1 <= schritt <= 10:
        raise Domaenenfehler("Der Framework-Schritt muss zwischen 1 und 10 liegen.")
    if schritt <= 5:
        return 1
    if schritt <= 7:
        return 2
    return 3


def utc_jetzt() -> datetime:
    """Zentrale, zeitzonenbewusste Uhr für die Zugriffsschicht."""
    return datetime.now(UTC)
