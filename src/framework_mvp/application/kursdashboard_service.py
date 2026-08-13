"""Autorisierte, technisch bereinigte Lesesicht für Lehrende."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from framework_mvp.application.autorisierung import AutorisierungsService
from framework_mvp.application.fortschritt_service import FortschrittService
from framework_mvp.application.ports.zugriffs_repository import ZugriffsRepository
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.models.zugriff import Gruppenaktion, Zugriffskontext
from framework_mvp.workspace import WorkspaceKonfiguration


@dataclass(frozen=True, slots=True)
class Dashboardzeile:
    projektname: str
    mitglieder: tuple[str, ...]
    phase: str
    schritt: int
    fortschritt_prozent: int
    letzte_aktivitaet: datetime
    ablaufdatum: datetime | None
    speicherverbrauch_bytes: int


class KursdashboardService:
    def __init__(
        self,
        zugriffs_repository: ZugriffsRepository,
        projekt_service: ProjektService,
        fortschritt_service: FortschrittService,
        autorisierung: AutorisierungsService,
        workspace: WorkspaceKonfiguration,
    ) -> None:
        self._zugriff = zugriffs_repository
        self._projekte = projekt_service
        self._fortschritt = fortschritt_service
        self._autorisierung = autorisierung
        self._workspace = workspace

    def laden(self, kontext: Zugriffskontext, gruppen_id: UUID) -> list[Dashboardzeile]:
        self._autorisierung.gruppen_zugriff_pruefen(kontext, gruppen_id, Gruppenaktion.ANSEHEN)
        gruppe = self._zugriff.kursgruppe_laden(gruppen_id)
        if gruppe is None:
            return []
        zeilen: list[Dashboardzeile] = []
        for projekt_id in self._zugriff.projekt_ids_fuer_gruppe(gruppen_id):
            projekt = self._projekte.projekt_laden(projekt_id)
            if projekt is None:
                continue
            fortschritt = self._fortschritt.laden(kontext, projekt_id, dashboard=True)
            namen = []
            for mitglied in self._zugriff.projektmitglieder_auflisten(projekt_id):
                benutzer = self._zugriff.benutzer_laden(mitglied.benutzer_id)
                if benutzer is not None:
                    namen.append(benutzer.anzeigename or benutzer.email or "Mitglied")
            zeilen.append(
                Dashboardzeile(
                    projektname=projekt.bezeichnung,
                    mitglieder=tuple(sorted(namen)),
                    phase=fortschritt.phasenname,
                    schritt=fortschritt.schritt,
                    fortschritt_prozent=fortschritt.prozent,
                    letzte_aktivitaet=fortschritt.letzte_aktivitaet,
                    ablaufdatum=gruppe.aufbewahrung_bis,
                    speicherverbrauch_bytes=self._verzeichnisgroesse(projekt_id),
                )
            )
        return zeilen

    def _verzeichnisgroesse(self, projekt_id: UUID) -> int:
        projektpfad = (self._workspace.basisverzeichnis / "projects" / str(projekt_id)).resolve()
        basis = self._workspace.basisverzeichnis.resolve()
        try:
            projektpfad.relative_to(basis)
        except ValueError:
            return 0
        if not projektpfad.exists():
            return 0
        return sum(
            datei.stat().st_size
            for datei in projektpfad.rglob("*")
            if datei.is_file() and not datei.is_symlink()
        )
