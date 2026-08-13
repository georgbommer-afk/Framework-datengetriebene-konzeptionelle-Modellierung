"""Portables Kursarchiv aus validierten, einzeln autorisierten Projektarchiven."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from framework_mvp.application.autorisierung import NICHT_VERFUEGBAR, AutorisierungsService
from framework_mvp.application.loesch_service import LoeschService
from framework_mvp.application.ports.zugriffs_repository import ZugriffsRepository
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.projektarchiv_service import ProjektArchivService, hmac_compare
from framework_mvp.domain.exceptions import ArchivKonflikt, ArchivUngueltig, ZugriffVerweigert
from framework_mvp.domain.models.zugriff import (
    GlobaleRolle,
    Gruppenaktion,
    Gruppenmitgliedschaft,
    Gruppenrolle,
    Gruppenstatus,
    Kursgruppe,
    Mitgliedschaftsstatus,
    Zugriffskontext,
)

KURSARCHIVVERSION = 1
MAXIMALE_KURSARCHIVGROESSE = 2 * 1024 * 1024 * 1024


class KursarchivService:
    """Exportiert keine Rechte und importiert nur mit verifizierter Leitungsidentität."""

    def __init__(
        self,
        zugriffs_repository: ZugriffsRepository,
        autorisierung: AutorisierungsService,
        projektarchive: ProjektArchivService,
        projekt_service: ProjektService,
        loesch_service: LoeschService,
    ) -> None:
        self._zugriff = zugriffs_repository
        self._autorisierung = autorisierung
        self._projektarchive = projektarchive
        self._projekte = projekt_service
        self._loeschen = loesch_service

    def exportieren(self, kontext: Zugriffskontext, gruppen_id: UUID) -> bytes:
        self._autorisierung.gruppen_zugriff_pruefen(kontext, gruppen_id, Gruppenaktion.ARCHIVIEREN)
        gruppe = self._zugriff.kursgruppe_laden(gruppen_id)
        if gruppe is None:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        leitung = self._zugriff.benutzer_laden(gruppe.gruppenleitung_benutzer_id)
        if leitung is None:
            raise ArchivUngueltig("Die verantwortliche Gruppenleitung fehlt.")
        payload: dict[str, bytes] = {}
        gruppe_json = self._gruppe_als_dict(gruppe)
        payload["group/group.json"] = self._json(gruppe_json)
        projekt_hinweise: list[dict[str, Any]] = []
        for projekt_id in self._zugriff.projekt_ids_fuer_gruppe(gruppen_id):
            projekt = self._projekte.projekt_laden(projekt_id)
            if projekt is None:
                continue
            projektarchiv = self._projektarchive.exportieren(kontext, projekt_id)
            payload[f"projects/{projekt_id}.zip"] = projektarchiv
            fortschritt = self._zugriff.fortschritt_laden(projekt_id)
            team_labels: list[str] = []
            for mitglied in self._zugriff.projektmitglieder_auflisten(projekt_id):
                benutzer = self._zugriff.benutzer_laden(mitglied.benutzer_id)
                if benutzer is not None:
                    team_labels.append(benutzer.anzeigename or benutzer.email or "Mitglied")
            projekt_hinweise.append(
                {
                    "original_project_id": str(projekt_id),
                    "project_name": projekt.bezeichnung,
                    "last_framework_step": (
                        fortschritt.framework_schritt if fortschritt is not None else 1
                    ),
                    "team_labels": sorted(team_labels),
                }
            )
        payload["group/project-team-hints.json"] = self._json(projekt_hinweise)
        payload["README.txt"] = (
            b"Portables Kursgruppenarchiv v1. Es kann Projektdateien und "
            b"personenbezogene Zuordnungshinweise enthalten. Einladungen und Rechte "
            b"werden nicht exportiert.\n"
        )
        dateien = [
            {
                "path": pfad,
                "size_bytes": len(daten),
                "sha256": hashlib.sha256(daten).hexdigest(),
            }
            for pfad, daten in sorted(payload.items())
        ]
        manifest = {
            "course_archive_version": KURSARCHIVVERSION,
            "original_group_id": str(gruppen_id),
            "group_name": gruppe.bezeichnung,
            "exported_at_utc": datetime.now(UTC).isoformat(),
            "original_leader": {
                "oidc_issuer": leitung.oidc_issuer,
                "oidc_subject": leitung.oidc_subject,
            },
            "files": dateien,
            "contains_active_invitations": False,
            "contains_access_rights": False,
        }
        ausgabe = io.BytesIO()
        with zipfile.ZipFile(ausgabe, "w", zipfile.ZIP_DEFLATED) as archiv:
            for pfad, daten in sorted(payload.items()):
                archiv.writestr(pfad, daten)
            archiv.writestr("course-manifest.json", self._json(manifest))
        ergebnis = ausgabe.getvalue()
        if len(ergebnis) > MAXIMALE_KURSARCHIVGROESSE:
            raise ArchivUngueltig("Das Kursarchiv überschreitet die zulässige Größe.")
        self._validieren(ergebnis)
        self._zugriff.archiv_metadaten_speichern(
            archiv_id=uuid4(),
            projekt_id=None,
            gruppen_id=gruppen_id,
            archivtyp="kurs_export",
            archivversion=KURSARCHIVVERSION,
            sha256=hashlib.sha256(ergebnis).hexdigest(),
            groesse_bytes=len(ergebnis),
            benutzer_id=kontext.benutzer_id,
            status="erfolgreich",
            details={"projektanzahl": len(projekt_hinweise)},
            zeitpunkt=datetime.now(UTC),
        )
        return ergebnis

    def importieren(
        self,
        kontext: Zugriffskontext,
        archiv: bytes,
        *,
        systemadmin_wiederherstellung: bool = False,
    ) -> Kursgruppe:
        if kontext.benutzer_id is None:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        payload, manifest = self._validieren(archiv)
        benutzer = self._zugriff.benutzer_laden(kontext.benutzer_id)
        if benutzer is None:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        leitung = manifest.get("original_leader", {})
        identisch = (
            isinstance(leitung, dict)
            and leitung.get("oidc_issuer") == benutzer.oidc_issuer
            and leitung.get("oidc_subject") == benutzer.oidc_subject
        )
        rollen = self._zugriff.globale_rollen_laden(benutzer.benutzer_id)
        if not identisch:
            if not systemadmin_wiederherstellung:
                raise ZugriffVerweigert(NICHT_VERFUEGBAR)
            self._autorisierung.systemadmin_pruefen(kontext)
        elif not rollen.intersection({GlobaleRolle.GRUPPENLEITUNG, GlobaleRolle.SYSTEMADMIN}):
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        try:
            gruppen_id = UUID(str(manifest["original_group_id"]))
        except (KeyError, TypeError, ValueError) as fehler:
            raise ArchivUngueltig("Die Gruppen-ID ist ungültig.") from fehler
        if self._zugriff.kursgruppe_laden(gruppen_id) is not None:
            raise ArchivKonflikt("Die Kursgruppe ist bereits vorhanden.")
        gruppe_daten = json.loads(payload["group/group.json"])
        team_hinweise = json.loads(payload["group/project-team-hints.json"])
        if not isinstance(team_hinweise, list):
            raise ArchivUngueltig("Die Projekt-/Teamhinweise sind ungültig.")
        gruppe = self._gruppe_aus_dict(gruppe_daten, benutzer.benutzer_id)
        if gruppe.gruppen_id != gruppen_id:
            raise ArchivUngueltig("Manifest und Gruppenkonfiguration widersprechen sich.")
        jetzt = datetime.now(UTC)
        self._zugriff.kursgruppe_speichern(gruppe)
        self._zugriff.gruppenmitgliedschaft_speichern(
            Gruppenmitgliedschaft(
                gruppen_id,
                benutzer.benutzer_id,
                Gruppenrolle.GRUPPENLEITUNG,
                Mitgliedschaftsstatus.AKTIV,
                frozenset(),
                jetzt,
                jetzt,
            )
        )
        importiert: list[UUID] = []
        try:
            for pfad, daten in sorted(payload.items()):
                if not pfad.startswith("projects/"):
                    continue
                ergebnis = self._projektarchive.importieren(
                    kontext, daten, ziel_gruppen_id=gruppen_id
                )
                if not ergebnis.bereits_vorhanden:
                    importiert.append(ergebnis.projekt_id)
        except Exception:
            for projekt_id in reversed(importiert):
                self._loeschen.projekt_loeschen(projekt_id)
            self._zugriff.kursgruppe_status_setzen(
                gruppen_id, status="geloescht", zeitpunkt=datetime.now(UTC)
            )
            raise
        self._zugriff.archiv_metadaten_speichern(
            archiv_id=uuid4(),
            projekt_id=None,
            gruppen_id=gruppen_id,
            archivtyp="kurs_import",
            archivversion=KURSARCHIVVERSION,
            sha256=hashlib.sha256(archiv).hexdigest(),
            groesse_bytes=len(archiv),
            benutzer_id=kontext.benutzer_id,
            status="erfolgreich",
            details={
                "projektanzahl": len(importiert),
                "projekt_team_hinweise": team_hinweise,
                "erteilt_zugriffsrechte": False,
            },
            zeitpunkt=datetime.now(UTC),
        )
        return gruppe

    def _validieren(self, archiv: bytes) -> tuple[dict[str, bytes], dict[str, Any]]:
        if len(archiv) > MAXIMALE_KURSARCHIVGROESSE:
            raise ArchivUngueltig("Das Kursarchiv überschreitet die zulässige Größe.")
        try:
            zip_archiv = zipfile.ZipFile(io.BytesIO(archiv))
        except zipfile.BadZipFile as fehler:
            raise ArchivUngueltig("Die Datei ist kein gültiges Kurs-ZIP.") from fehler
        payload: dict[str, bytes] = {}
        with zip_archiv:
            namen: set[str] = set()
            for info in zip_archiv.infolist():
                if info.is_dir():
                    continue
                pfad = PurePosixPath(info.filename)
                if (
                    pfad.is_absolute()
                    or "\\" in info.filename
                    or any(teil in {"", ".", ".."} for teil in pfad.parts)
                    or info.filename.casefold() in namen
                    or info.flag_bits & 1
                ):
                    raise ArchivUngueltig("Das Kursarchiv enthält einen unsicheren Pfad.")
                namen.add(info.filename.casefold())
                erlaubt = info.filename in {
                    "course-manifest.json",
                    "group/group.json",
                    "group/project-team-hints.json",
                    "README.txt",
                } or (
                    len(pfad.parts) == 2 and pfad.parts[0] == "projects" and pfad.suffix == ".zip"
                )
                if not erlaubt:
                    raise ArchivUngueltig("Das Kursarchiv enthält eine unerlaubte Datei.")
                payload[info.filename] = zip_archiv.read(info)
        try:
            manifest = json.loads(payload.pop("course-manifest.json"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as fehler:
            raise ArchivUngueltig("Das Kursmanifest fehlt oder ist ungültig.") from fehler
        if manifest.get("course_archive_version") != KURSARCHIVVERSION:
            raise ArchivUngueltig("Die Kursarchivversion wird nicht unterstützt.")
        if manifest.get("contains_active_invitations") is not False:
            raise ArchivUngueltig("Ein Kursarchiv darf keine aktiven Einladungen enthalten.")
        dateien = manifest.get("files")
        if not isinstance(dateien, list):
            raise ArchivUngueltig("Die Kursdateiliste fehlt.")
        erwartet = {
            eintrag.get("path"): eintrag for eintrag in dateien if isinstance(eintrag, dict)
        }
        if set(erwartet) != set(payload):
            raise ArchivUngueltig("Kursmanifest und Archivinhalt unterscheiden sich.")
        for pfad, daten in payload.items():
            eintrag = erwartet[pfad]
            if eintrag.get("size_bytes") != len(daten) or not hmac_compare(
                str(eintrag.get("sha256", "")), hashlib.sha256(daten).hexdigest()
            ):
                raise ArchivUngueltig("Eine Kursarchiv-Prüfsumme ist ungültig.")
            if pfad.startswith("projects/"):
                self._projektarchive.validieren(daten)
        if not {"group/group.json", "group/project-team-hints.json", "README.txt"} <= set(payload):
            raise ArchivUngueltig("Das Kursarchiv ist unvollständig.")
        return payload, manifest

    @staticmethod
    def _gruppe_als_dict(gruppe: Kursgruppe) -> dict[str, Any]:
        return {
            "gruppen_id": str(gruppe.gruppen_id),
            "bezeichnung": gruppe.bezeichnung,
            "beschreibung": gruppe.beschreibung,
            "beginn_am": None if gruppe.beginn_am is None else gruppe.beginn_am.isoformat(),
            "ende_am": None if gruppe.ende_am is None else gruppe.ende_am.isoformat(),
            "aufbewahrung_bis_utc": (
                None if gruppe.aufbewahrung_bis is None else gruppe.aufbewahrung_bis.isoformat()
            ),
            "maximale_teilnehmende": gruppe.maximale_teilnehmende,
            "maximale_projekte": gruppe.maximale_projekte,
            "speicherlimit_pro_projekt_bytes": gruppe.speicherlimit_pro_projekt_bytes,
            "status": gruppe.status.value,
            "erstellt_am_utc": gruppe.erstellt_am.isoformat(),
            "geaendert_am_utc": gruppe.geaendert_am.isoformat(),
        }

    @staticmethod
    def _gruppe_aus_dict(daten: dict[str, Any], leitung_id: UUID) -> Kursgruppe:
        return Kursgruppe(
            gruppen_id=UUID(daten["gruppen_id"]),
            bezeichnung=str(daten["bezeichnung"]),
            beschreibung=str(daten.get("beschreibung", "")),
            gruppenleitung_benutzer_id=leitung_id,
            beginn_am=None
            if daten.get("beginn_am") is None
            else date.fromisoformat(daten["beginn_am"]),
            ende_am=None if daten.get("ende_am") is None else date.fromisoformat(daten["ende_am"]),
            maximale_teilnehmende=int(daten["maximale_teilnehmende"]),
            maximale_projekte=int(daten["maximale_projekte"]),
            speicherlimit_pro_projekt_bytes=int(daten["speicherlimit_pro_projekt_bytes"]),
            aufbewahrung_bis=(
                None
                if daten.get("aufbewahrung_bis_utc") is None
                else datetime.fromisoformat(daten["aufbewahrung_bis_utc"]).astimezone(UTC)
            ),
            status=Gruppenstatus(daten["status"]),
            erstellt_am=datetime.fromisoformat(daten["erstellt_am_utc"]).astimezone(UTC),
            geaendert_am=datetime.fromisoformat(daten["geaendert_am_utc"]).astimezone(UTC),
        )

    @staticmethod
    def _json(wert: Any) -> bytes:
        return json.dumps(wert, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
