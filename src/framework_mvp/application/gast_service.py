"""Temporäre Gastsitzungen und opportunistische TTL-Bereinigung."""

from __future__ import annotations

import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from framework_mvp.application.loesch_service import LoeschService
from framework_mvp.application.mandanten_projekt_service import (
    AutorisierterLoeschService,
    MandantenProjektService,
)
from framework_mvp.application.ports.zugriffs_repository import ZugriffsRepository
from framework_mvp.domain.models import Projekt, Systemtyp, Untersuchungsauftrag
from framework_mvp.domain.models.zugriff import Zugriffskontext
from framework_mvp.workspace import WorkspaceKonfiguration

GAST_HINWEIS = (
    "Dieses Projekt wird nur temporär gespeichert. Exportieren Sie es, "
    "wenn Sie später weiterarbeiten möchten."
)


@dataclass(frozen=True, slots=True)
class Gastdemo:
    kontext: Zugriffskontext
    projekt: Projekt


class GastService:
    """Erzeugt einen zufälligen Besitznachweis und genau ein isoliertes Demoprojekt."""

    def __init__(
        self,
        projekt_service: MandantenProjektService,
        loesch_service: AutorisierterLoeschService,
    ) -> None:
        self._projekte = projekt_service
        self._loeschen = loesch_service

    def demo_starten(self) -> Gastdemo:
        geheimnis = secrets.token_urlsafe(32)
        kontext = Zugriffskontext.gast(geheimnis)
        projekt = self._projekte.projekt_anlegen(
            kontext,
            bezeichnung="Temporäres Demoprojekt",
            untersuchungsauftrag=Untersuchungsauftrag(
                problemstellung="Demonstration des Framework-Ablaufs",
                untersuchungszweck="Framework unverbindlich testen",
                systemtyp=Systemtyp.PRODUKTION,
                systemgrenze="Noch festzulegen",
            ),
        )
        return Gastdemo(kontext, projekt)

    def demo_beenden(self, demo: Gastdemo) -> None:
        self._loeschen.projekt_loeschen(demo.kontext, demo.projekt.projekt_id)


class BereinigungsService:
    """Bereinigt begrenzt und opportunistisch statt einen Scheduler vorauszusetzen."""

    def __init__(
        self,
        zugriffs_repository: ZugriffsRepository,
        loesch_service: LoeschService,
        workspace: WorkspaceKonfiguration,
        *,
        staging_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self._zugriff = zugriffs_repository
        self._loeschen = loesch_service
        self._workspace = workspace
        self._staging_ttl = staging_ttl

    def opportunistisch(self, *, limit: int = 20, zeitpunkt: datetime | None = None) -> int:
        jetzt = (zeitpunkt or datetime.now(UTC)).astimezone(UTC)
        geloescht = 0
        for projekt_id in self._zugriff.abgelaufene_gastprojekt_ids(zeitpunkt=jetzt, limit=limit):
            try:
                self._loeschen.projekt_loeschen(projekt_id)
            except Exception as fehler:
                self._zugriff.bereinigung_protokollieren(
                    projekt_id=projekt_id,
                    gruppen_id=None,
                    aktion="gast_ttl_loeschung",
                    ergebnis="fehlgeschlagen",
                    details={"fehlertyp": type(fehler).__name__},
                    zeitpunkt=jetzt,
                )
            else:
                geloescht += 1
                self._zugriff.bereinigung_protokollieren(
                    projekt_id=projekt_id,
                    gruppen_id=None,
                    aktion="gast_ttl_loeschung",
                    ergebnis="erfolgreich",
                    details={},
                    zeitpunkt=jetzt,
                )
        for gruppe in self._zugriff.kursgruppen_mit_abgelaufenem_kursende(datum=jetzt, limit=limit):
            self._zugriff.kursgruppe_status_setzen(
                gruppe.gruppen_id, status="abgelaufen", zeitpunkt=jetzt
            )
        for gruppe in self._zugriff.kursgruppen_mit_abgelaufener_aufbewahrung(
            zeitpunkt=jetzt, limit=limit
        ):
            self.kursgruppe_bereinigen(gruppe.gruppen_id, zeitpunkt=jetzt)
        self._verwaiste_stagingverzeichnisse_bereinigen(jetzt, limit=limit)
        return geloescht

    def kursgruppe_bereinigen(self, gruppen_id: UUID, *, zeitpunkt: datetime | None = None) -> int:
        jetzt = (zeitpunkt or datetime.now(UTC)).astimezone(UTC)
        gruppe = self._zugriff.kursgruppe_laden(gruppen_id)
        if gruppe is None or gruppe.aufbewahrung_bis is None or gruppe.aufbewahrung_bis > jetzt:
            return 0
        projekt_ids = self._zugriff.projekt_ids_fuer_gruppe(gruppen_id)
        geloescht = 0
        for projekt_id in projekt_ids:
            self._loeschen.projekt_loeschen(projekt_id)
            geloescht += 1
            self._zugriff.bereinigung_protokollieren(
                projekt_id=projekt_id,
                gruppen_id=gruppen_id,
                aktion="kurs_aufbewahrung_loeschung",
                ergebnis="erfolgreich",
                details={},
                zeitpunkt=jetzt,
            )
        self._zugriff.kursgruppe_status_setzen(gruppen_id, status="geloescht", zeitpunkt=jetzt)
        return geloescht

    def _verwaiste_stagingverzeichnisse_bereinigen(
        self, zeitpunkt: datetime, *, limit: int
    ) -> None:
        grenze = zeitpunkt.timestamp() - self._staging_ttl.total_seconds()
        basis = self._workspace.basisverzeichnis.resolve()
        kandidaten: list[Path] = []
        for name in (".import-staging", ".deletion-staging"):
            wurzel = (basis / name).resolve()
            if wurzel.parent != basis or not wurzel.exists():
                continue
            kandidaten.extend(pfad for pfad in wurzel.iterdir() if pfad.is_dir())
        for pfad in sorted(kandidaten, key=lambda wert: wert.stat().st_mtime)[:limit]:
            if pfad.resolve().parent.parent != basis:
                continue
            if pfad.stat().st_mtime <= grenze:
                shutil.rmtree(pfad, ignore_errors=True)
