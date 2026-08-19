"""Sicherer Export und Import vollständiger, portabler Projektarchive (ZIP v1)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from framework_mvp.application.autorisierung import (
    NICHT_VERFUEGBAR,
    AutorisierungsService,
    geheimnis_hash,
)
from framework_mvp.application.ports.zugriffs_repository import ZugriffsRepository
from framework_mvp.domain.exceptions import ArchivKonflikt, ArchivUngueltig, ZugriffVerweigert
from framework_mvp.domain.models.zugriff import (
    Gruppenaktion,
    Gruppenrolle,
    Projektaktion,
    Projektzugriffsart,
    Zugriffskontext,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import (
    SCHEMAVERSION,
    initialisiere_schema,
)
from framework_mvp.workspace import WorkspaceKonfiguration

ARCHIVVERSION = 1

_TABELLEN_REIHENFOLGE = (
    "projekte",
    "datenquellen",
    "importvorgaenge",
    "transformationsplaene",
    "zwischendatensaetze",
    "semantische_mappings",
    "mappingtabellen",
    "event_logs",
    "qualitaetspruefungen",
    "qualitaetsregeln",
    "qualitaetsmassnahmen",
    "process_mining_analysen",
    "ergebnisaggregationen",
    "modellableitungen",
    "modellvalidierungen",
    "projektfortschritt",
)

_ARTEFAKT_ENDUNGEN = {
    ".json",
    ".txt",
    ".csv",
    ".gz",
    ".parquet",
    ".xlsx",
    ".xls",
    ".pnml",
    ".ptml",
    ".bpmn",
    ".svg",
    ".xes",
    ".pdf",
    ".html",
}


@dataclass(frozen=True, slots=True)
class ArchivGrenzen:
    """Harte Ressourcenlimits gegen ZIP-Bomben und Speicherüberlastung."""

    maximale_archivgroesse_bytes: int = 250 * 1024 * 1024
    maximale_dateien: int = 5_000
    maximale_einzeldatei_bytes: int = 250 * 1024 * 1024
    maximale_entpackte_groesse_bytes: int = 1024 * 1024 * 1024
    maximales_kompressionsverhaeltnis: float = 100.0
    maximale_pfadlaenge: int = 512


@dataclass(frozen=True, slots=True)
class ImportErgebnis:
    """Ergebnis eines erfolgreichen Imports oder identischen Wiederöffnens."""

    projekt_id: UUID
    bereits_vorhanden: bool
    projektname: str
    ersetzt: bool = False


@dataclass(frozen=True, slots=True)
class ArchivImportPruefung:
    """Verständliche Metadaten eines vollständig validierten Importarchivs."""

    projekt_id: UUID
    projektname: str
    exportiert_am: str
    bereits_vorhanden: bool


@dataclass(frozen=True, slots=True)
class ArchivStaging:
    """Kleine, rerun-stabile Referenz auf ein noch ungeprüftes Uploadarchiv."""

    staging_id: UUID
    archiv_sha256: str
    zielkontext: str
    ziel_gruppen_id: UUID | None


@dataclass(frozen=True, slots=True)
class GestagterProjektimport:
    """Vollständig geprüftes Archiv samt konflikt- und kontextgebundener Metadaten."""

    staging_id: UUID
    archiv_sha256: str
    archivversion: int
    projekt_id: UUID
    projektname: str
    exportiert_am: str
    bereits_vorhanden: bool
    zielkontext: str
    ziel_gruppen_id: UUID | None


class ProjektSperren:
    """Prozesslokale Projektsperren; SQLite ergänzt sie prozessübergreifend."""

    def __init__(self) -> None:
        self._global = threading.Lock()
        self._sperren: dict[UUID, threading.RLock] = {}

    @contextmanager
    def sperren(self, projekt_id: UUID):
        with self._global:
            sperre = self._sperren.setdefault(projekt_id, threading.RLock())
        with sperre:
            yield


class ProjektArchivService:
    """Erzeugt selbstvalidierende Archive und importiert ohne ``extractall``."""

    def __init__(
        self,
        datenbankpfad: Path | str,
        workspace: WorkspaceKonfiguration,
        zugriffs_repository: ZugriffsRepository,
        autorisierung: AutorisierungsService,
        *,
        grenzen: ArchivGrenzen | None = None,
        sperren: ProjektSperren | None = None,
        gast_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self._datenbankpfad = Path(datenbankpfad)
        self._workspace = workspace
        self._zugriff = zugriffs_repository
        self._autorisierung = autorisierung
        self._grenzen = grenzen or ArchivGrenzen()
        self._sperren = sperren or ProjektSperren()
        self._gast_ttl = gast_ttl

    def exportieren(self, kontext: Zugriffskontext, projekt_id: UUID) -> bytes:
        """Exportiert einen autorisierten, konsistenten Projektsnapshot als ZIP v1."""
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, Projektaktion.EXPORTIEREN)
        with self._sperren.sperren(projekt_id):
            zuordnung_vorher = self._zugriff.projektzugehoerigkeit_laden(projekt_id)
            if zuordnung_vorher is None:
                raise ZugriffVerweigert(NICHT_VERFUEGBAR)
            datenbankdaten = self._datenbank_snapshot(projekt_id)
            projektzeilen = datenbankdaten.get("projekte", [])
            if len(projektzeilen) != 1:
                raise ZugriffVerweigert(NICHT_VERFUEGBAR)
            projektzeile = projektzeilen[0]
            payload = self._payload_erstellen(projekt_id, datenbankdaten, projektzeile)
            zuordnung_nachher = self._zugriff.projektzugehoerigkeit_laden(projekt_id)
            if zuordnung_nachher is None or zuordnung_nachher.revision != zuordnung_vorher.revision:
                raise ArchivKonflikt("Das Projekt wurde während des Exports verändert.")
            erster_fingerabdruck = self._payload_fingerabdruck(payload)
            if self._vorhandener_fingerabdruck(projekt_id) != erster_fingerabdruck:
                raise ArchivKonflikt("Das Projekt wurde während des Exports verändert.")
            archiv = self._zip_erstellen(projekt_id, projektzeile, payload, datenbankdaten)
            _, manifest = self._archiv_pruefen(archiv)
            self._zugriff.archiv_metadaten_speichern(
                archiv_id=uuid4(),
                projekt_id=projekt_id,
                gruppen_id=zuordnung_vorher.gruppen_id,
                archivtyp="projekt_export",
                archivversion=ARCHIVVERSION,
                sha256=hashlib.sha256(archiv).hexdigest(),
                groesse_bytes=len(archiv),
                benutzer_id=kontext.benutzer_id,
                status="erfolgreich",
                details={"project_fingerprint": manifest["project_fingerprint"]},
                zeitpunkt=datetime.now(UTC),
            )
            return archiv

    def validieren(self, archiv: bytes) -> dict[str, Any]:
        """Validiert ein Projektarchiv ohne Schreibzugriff und liefert sein Manifest."""
        _, manifest = self._archiv_pruefen(archiv)
        return manifest

    def import_pruefen(
        self,
        kontext: Zugriffskontext,
        archiv: bytes,
        *,
        ziel_gruppen_id: UUID | None = None,
    ) -> ArchivImportPruefung:
        """Validiert ohne Mutation und prüft Ziel beziehungsweise Ersetzungsberechtigung."""
        _, manifest = self._archiv_pruefen(archiv)
        return self._import_pruefung_aus_manifest(
            kontext,
            manifest,
            archiv_sha256=hashlib.sha256(archiv).hexdigest(),
            ziel_gruppen_id=ziel_gruppen_id,
        )

    def archiv_stagen(
        self,
        kontext: Zugriffskontext,
        archiv: bytes,
        *,
        ziel_gruppen_id: UUID | None = None,
    ) -> ArchivStaging:
        """Übernimmt einen begrenzten Upload ohne Dateinamen in kontrolliertes Staging."""
        if len(archiv) > self._grenzen.maximale_archivgroesse_bytes:
            raise ArchivUngueltig("Das Archiv überschreitet die zulässige Größe.")
        staging_id = uuid4()
        staging = self._upload_staging_pfad(staging_id)
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.mkdir()
        archiv_sha256 = hashlib.sha256(archiv).hexdigest()
        zielkontext = self._zielkontext(kontext, ziel_gruppen_id)
        try:
            (staging / "projektarchiv.zip").write_bytes(archiv)
            (staging / "staging.json").write_bytes(
                self._json_bytes(
                    {
                        "staging_id": str(staging_id),
                        "archiv_sha256": archiv_sha256,
                        "kontextbindung": self._kontextbindung(kontext, ziel_gruppen_id),
                        "zielkontext": zielkontext,
                    }
                )
            )
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return ArchivStaging(staging_id, archiv_sha256, zielkontext, ziel_gruppen_id)

    def gestagten_import_pruefen(
        self,
        kontext: Zugriffskontext,
        staging_id: UUID,
        archiv_sha256: str,
        *,
        ziel_gruppen_id: UUID | None = None,
    ) -> GestagterProjektimport:
        """Validiert das über einen Rerun erhaltene Archiv und bindet den Konfliktstatus."""
        try:
            archiv, zielkontext = self._gestagtes_archiv_laden(
                kontext,
                staging_id,
                archiv_sha256,
                ziel_gruppen_id=ziel_gruppen_id,
            )
            _, manifest = self._archiv_pruefen(archiv)
            pruefung = self._import_pruefung_aus_manifest(
                kontext,
                manifest,
                archiv_sha256=hashlib.sha256(archiv).hexdigest(),
                ziel_gruppen_id=ziel_gruppen_id,
            )
            return GestagterProjektimport(
                staging_id=staging_id,
                archiv_sha256=archiv_sha256,
                archivversion=int(manifest["archive_version"]),
                projekt_id=pruefung.projekt_id,
                projektname=pruefung.projektname,
                exportiert_am=pruefung.exportiert_am,
                bereits_vorhanden=pruefung.bereits_vorhanden,
                zielkontext=zielkontext,
                ziel_gruppen_id=ziel_gruppen_id,
            )
        except ZugriffVerweigert:
            raise
        except Exception:
            self._upload_staging_verwerfen(staging_id)
            raise

    def gestagten_importieren(
        self,
        kontext: Zugriffskontext,
        staging_id: UUID,
        archiv_sha256: str,
        *,
        erwartete_projekt_id: UUID,
        ziel_gruppen_id: UUID | None = None,
        vorhandenes_projekt_ersetzen: bool = False,
    ) -> ImportErgebnis:
        """Importiert nur den zuvor geprüften Stagingstand und räumt ihn stets auf."""
        try:
            archiv, _ = self._gestagtes_archiv_laden(
                kontext,
                staging_id,
                archiv_sha256,
                ziel_gruppen_id=ziel_gruppen_id,
            )
        except ZugriffVerweigert:
            raise
        except Exception:
            self._upload_staging_verwerfen(staging_id)
            raise
        try:
            pruefung = self.import_pruefen(
                kontext,
                archiv,
                ziel_gruppen_id=ziel_gruppen_id,
            )
            if (
                pruefung.projekt_id != erwartete_projekt_id
                or pruefung.bereits_vorhanden != vorhandenes_projekt_ersetzen
            ):
                raise ArchivKonflikt(
                    "Das Importziel wurde parallel verändert. Bitte erneut prüfen."
                )
            return self.importieren(
                kontext,
                archiv,
                ziel_gruppen_id=ziel_gruppen_id,
                vorhandenes_projekt_ersetzen=vorhandenes_projekt_ersetzen,
            )
        finally:
            self._upload_staging_verwerfen(staging_id)

    def archiv_staging_verwerfen(
        self,
        kontext: Zugriffskontext,
        staging_id: UUID,
        archiv_sha256: str,
        *,
        ziel_gruppen_id: UUID | None = None,
    ) -> None:
        """Verwirft ausschließlich ein nach Prüfsumme und Kontext gebundenes Uploadstaging."""
        try:
            self._gestagtes_archiv_laden(
                kontext,
                staging_id,
                archiv_sha256,
                ziel_gruppen_id=ziel_gruppen_id,
            )
        except ZugriffVerweigert:
            raise
        except Exception:
            self._upload_staging_verwerfen(staging_id)
            raise
        self._upload_staging_verwerfen(staging_id)

    def _import_pruefung_aus_manifest(
        self,
        kontext: Zugriffskontext,
        manifest: dict[str, Any],
        *,
        archiv_sha256: str,
        ziel_gruppen_id: UUID | None,
    ) -> ArchivImportPruefung:
        try:
            projekt_id = UUID(str(manifest["original_project_id"]))
        except (KeyError, TypeError, ValueError) as fehler:
            raise ArchivUngueltig("Die ursprüngliche Projekt-ID ist ungültig.") from fehler
        projektname = str(manifest.get("project_name", "")).strip()
        if not projektname:
            raise ArchivUngueltig("Der Projektname fehlt im Manifest.")
        vorhanden = self._vorhandener_fingerabdruck(projekt_id) is not None
        if vorhanden:
            self._ersetzungszugriff_pruefen(kontext, projekt_id, archiv_sha256)
        else:
            self._importziel_pruefen(kontext, ziel_gruppen_id, manifest=manifest)
        return ArchivImportPruefung(
            projekt_id,
            projektname,
            str(manifest.get("exported_at_utc", "")),
            vorhanden,
        )

    def _ersetzungszugriff_pruefen(
        self, kontext: Zugriffskontext, projekt_id: UUID, archiv_sha256: str
    ) -> bool:
        """Erlaubt alternativ nur den exakt dokumentierten Gast-Export als Besitznachweis."""
        try:
            self._autorisierung.projekt_zugriff_pruefen(
                kontext, projekt_id, Projektaktion.IMPORTIEREN
            )
            self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, Projektaktion.LOESCHEN)
            return False
        except ZugriffVerweigert:
            if self._passender_gast_exportnachweis(kontext, projekt_id, archiv_sha256):
                return True
            raise ZugriffVerweigert(NICHT_VERFUEGBAR) from None

    def _passender_gast_exportnachweis(
        self, kontext: Zugriffskontext, projekt_id: UUID, archiv_sha256: str
    ) -> bool:
        if kontext.gast_geheimnis is None:
            return False
        zuordnung = self._zugriff.projektzugehoerigkeit_laden(projekt_id)
        if zuordnung is None or zuordnung.zugriffsart is not Projektzugriffsart.GAST:
            return False
        verbindung = sqlite3.connect(self._datenbankpfad, timeout=5.0)
        try:
            return (
                verbindung.execute(
                    """
                    SELECT 1 FROM archivmetadaten
                    WHERE projekt_id = ? AND gruppen_id IS NULL
                      AND archivtyp = 'projekt_export' AND status = 'erfolgreich'
                      AND sha256 = ?
                    LIMIT 1
                    """,
                    (str(projekt_id), archiv_sha256),
                ).fetchone()
                is not None
            )
        finally:
            verbindung.close()

    def _upload_staging_pfad(self, staging_id: UUID) -> Path:
        basis = self._workspace.basisverzeichnis.resolve()
        wurzel = (basis / ".import-staging").resolve()
        pfad = (wurzel / f"upload-{staging_id}").resolve()
        if pfad.parent != wurzel:
            raise ArchivUngueltig("Die Import-Stagingkennung ist ungültig.")
        return pfad

    def _gestagtes_archiv_laden(
        self,
        kontext: Zugriffskontext,
        staging_id: UUID,
        archiv_sha256: str,
        *,
        ziel_gruppen_id: UUID | None,
    ) -> tuple[bytes, str]:
        staging = self._upload_staging_pfad(staging_id)
        try:
            metadaten = json.loads((staging / "staging.json").read_bytes())
            archivpfad = staging / "projektarchiv.zip"
            if archivpfad.stat().st_size > self._grenzen.maximale_archivgroesse_bytes:
                raise ArchivUngueltig("Das gestagte Archiv überschreitet die zulässige Größe.")
            archiv = archivpfad.read_bytes()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as fehler:
            raise ArchivUngueltig("Der gestagte Import ist nicht mehr verfügbar.") from fehler
        if not isinstance(metadaten, dict):
            raise ArchivUngueltig("Die Import-Stagingmetadaten sind ungültig.")
        erwartete_bindung = self._kontextbindung(kontext, ziel_gruppen_id)
        if (
            metadaten.get("staging_id") != str(staging_id)
            or not hmac_compare(str(metadaten.get("archiv_sha256", "")), archiv_sha256)
            or not hmac_compare(str(metadaten.get("kontextbindung", "")), erwartete_bindung)
        ):
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        if not hmac_compare(hashlib.sha256(archiv).hexdigest(), archiv_sha256):
            raise ArchivUngueltig("Das gestagte Projektarchiv wurde verändert.")
        return archiv, str(metadaten.get("zielkontext", ""))

    def _upload_staging_verwerfen(self, staging_id: UUID) -> None:
        shutil.rmtree(self._upload_staging_pfad(staging_id), ignore_errors=True)

    @staticmethod
    def _kontextbindung(kontext: Zugriffskontext, ziel_gruppen_id: UUID | None) -> str:
        if kontext.gast_geheimnis is not None:
            identitaet = f"gast:{geheimnis_hash(kontext.gast_geheimnis)}"
        else:
            identitaet = f"benutzer:{kontext.benutzer_id}"
        return hashlib.sha256(f"{identitaet}:gruppe:{ziel_gruppen_id}".encode()).hexdigest()

    @staticmethod
    def _zielkontext(kontext: Zugriffskontext, ziel_gruppen_id: UUID | None) -> str:
        if kontext.gast_geheimnis is not None:
            return "aktuelle Gastsitzung"
        return f"Kursgruppe {ziel_gruppen_id}"

    def importieren(
        self,
        kontext: Zugriffskontext,
        archiv: bytes,
        *,
        ziel_gruppen_id: UUID | None = None,
        vorhandenes_projekt_ersetzen: bool = False,
    ) -> ImportErgebnis:
        """Validiert vollständig, staged einzeln und übernimmt DB/Dateien gemeinsam."""
        inhalt, manifest = self._archiv_pruefen(archiv)
        archiv_sha256 = hashlib.sha256(archiv).hexdigest()
        try:
            projekt_id = UUID(str(manifest["original_project_id"]))
        except (KeyError, TypeError, ValueError) as fehler:
            raise ArchivUngueltig("Die ursprüngliche Projekt-ID ist ungültig.") from fehler
        projektname = str(manifest.get("project_name", "")).strip()
        if not projektname:
            raise ArchivUngueltig("Der Projektname fehlt im Manifest.")
        with self._sperren.sperren(projekt_id):
            vorhandener_fingerabdruck = self._vorhandener_fingerabdruck(projekt_id)
            gast_neu_binden = False
            if vorhandener_fingerabdruck is not None:
                gast_neu_binden = self._ersetzungszugriff_pruefen(
                    kontext, projekt_id, archiv_sha256
                )
                if not vorhandenes_projekt_ersetzen:
                    raise ArchivKonflikt(
                        "Die Projekt-ID ist bereits vorhanden. Bestätigen Sie ausdrücklich, "
                        "dass das vorhandene Projekt ersetzt werden soll."
                    )
                zuordnung = self._zugriff.projektzugehoerigkeit_laden(projekt_id)
                if zuordnung is None:
                    raise ZugriffVerweigert(NICHT_VERFUEGBAR)
                self._atomar_uebernehmen(
                    kontext,
                    projekt_id,
                    zuordnung.gruppen_id,
                    inhalt,
                    manifest,
                    archiv_sha256=archiv_sha256,
                    archivgroesse_bytes=len(archiv),
                    gast_neu_binden=gast_neu_binden,
                    ersetzen=True,
                )
            else:
                self._importziel_pruefen(kontext, ziel_gruppen_id, manifest=manifest)
                self._atomar_uebernehmen(
                    kontext,
                    projekt_id,
                    ziel_gruppen_id,
                    inhalt,
                    manifest,
                    archiv_sha256=archiv_sha256,
                    archivgroesse_bytes=len(archiv),
                    gast_neu_binden=False,
                    ersetzen=False,
                )
        return ImportErgebnis(
            projekt_id,
            bereits_vorhanden=vorhandener_fingerabdruck is not None,
            projektname=projektname,
            ersetzt=vorhandener_fingerabdruck is not None,
        )

    def _datenbank_snapshot(self, projekt_id: UUID) -> dict[str, list[dict[str, Any]]]:
        verbindung = sqlite3.connect(self._datenbankpfad, timeout=5.0)
        verbindung.row_factory = sqlite3.Row
        try:
            initialisiere_schema(verbindung)
            verbindung.execute("BEGIN IMMEDIATE")
            ergebnis: dict[str, list[dict[str, Any]]] = {}
            quality_ids = [
                zeile[0]
                for zeile in verbindung.execute(
                    "SELECT quality_run_id FROM qualitaetspruefungen WHERE projekt_id = ?",
                    (str(projekt_id),),
                ).fetchall()
            ]
            for tabelle in _TABELLEN_REIHENFOLGE:
                if tabelle in {"qualitaetsregeln", "qualitaetsmassnahmen"}:
                    if not quality_ids:
                        zeilen: list[sqlite3.Row] = []
                    else:
                        platzhalter = ",".join("?" for _ in quality_ids)
                        zeilen = verbindung.execute(
                            f"SELECT * FROM {tabelle} WHERE quality_run_id IN ({platzhalter})",
                            quality_ids,
                        ).fetchall()
                else:
                    zeilen = verbindung.execute(
                        f"SELECT * FROM {tabelle} WHERE projekt_id = ?", (str(projekt_id),)
                    ).fetchall()
                ergebnis[tabelle] = [dict(zeile) for zeile in zeilen]
            verbindung.commit()
            return ergebnis
        except Exception:
            verbindung.rollback()
            raise
        finally:
            verbindung.close()

    def _payload_erstellen(
        self,
        projekt_id: UUID,
        datenbankdaten: dict[str, list[dict[str, Any]]],
        projektzeile: dict[str, Any],
    ) -> dict[str, bytes]:
        payload: dict[str, bytes] = {
            "project/project.json": self._json_bytes(projektzeile),
            "README.txt": (
                "Portables Framework-MVP-Projektarchiv, Formatversion 1.\n"
                "Es enthält Projektdaten und Artefakte, aber keine Benutzer-, "
                "Rollen-, Einladungs-, Sitzungs- oder Geheimnisdaten.\n"
            ).encode(),
        }
        for tabelle, zeilen in datenbankdaten.items():
            payload[f"database/{tabelle}.json"] = self._json_bytes(zeilen)
        projektwurzel = (self._workspace.basisverzeichnis / "projects" / str(projekt_id)).resolve()
        basis = self._workspace.basisverzeichnis.resolve()
        if projektwurzel.exists():
            try:
                projektwurzel.relative_to(basis)
            except ValueError as fehler:
                raise ArchivUngueltig("Der Projektpfad verlässt den Workspace.") from fehler
            for datei in sorted(projektwurzel.rglob("*")):
                if datei.is_symlink():
                    raise ArchivUngueltig("Symbolische Links werden nicht exportiert.")
                if not datei.is_file():
                    continue
                relativ = datei.relative_to(projektwurzel)
                zielwurzel = (
                    "reports" if datei.suffix.casefold() in {".pdf", ".html"} else "artifacts"
                )
                payload[f"{zielwurzel}/{relativ.as_posix()}"] = datei.read_bytes()
        self._payload_limits_pruefen(payload)
        return payload

    def _zip_erstellen(
        self,
        projekt_id: UUID,
        projektzeile: dict[str, Any],
        payload: dict[str, bytes],
        datenbankdaten: dict[str, list[dict[str, Any]]],
    ) -> bytes:
        dateiliste = [
            {
                "path": pfad,
                "size_bytes": len(daten),
                "sha256": hashlib.sha256(daten).hexdigest(),
            }
            for pfad, daten in sorted(payload.items())
        ]
        probe = self._zip_schreiben(payload, None)
        with zipfile.ZipFile(io.BytesIO(probe)) as zip_probe:
            komprimiert = sum(info.compress_size for info in zip_probe.infolist())
        fingerabdruck = self._payload_fingerabdruck(payload)
        fortschritt = datenbankdaten.get("projektfortschritt", [])
        letzter_schritt = fortschritt[0]["framework_schritt"] if fortschritt else 1
        manifest = {
            "archive_version": ARCHIVVERSION,
            "app_version": self._app_version(),
            "database_schema_version": SCHEMAVERSION,
            "original_project_id": str(projekt_id),
            "project_name": projektzeile["bezeichnung"],
            "exported_at_utc": datetime.now(UTC).isoformat(),
            "last_framework_step": letzter_schritt,
            "files": dateiliste,
            "compressed_payload_size_bytes": komprimiert,
            "uncompressed_payload_size_bytes": sum(len(daten) for daten in payload.values()),
            "project_fingerprint": fingerabdruck,
            "artifact_types": sorted(
                {Path(pfad).suffix.casefold().lstrip(".") for pfad in payload if Path(pfad).suffix}
            ),
        }
        return self._zip_schreiben(payload, self._json_bytes(manifest))

    @staticmethod
    def _zip_schreiben(payload: dict[str, bytes], manifest: bytes | None) -> bytes:
        ausgabe = io.BytesIO()
        with zipfile.ZipFile(
            ausgabe, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archiv:
            for pfad, daten in sorted(payload.items()):
                archiv.writestr(pfad, daten)
            if manifest is not None:
                archiv.writestr("manifest.json", manifest)
        return ausgabe.getvalue()

    def _archiv_pruefen(self, archiv: bytes) -> tuple[dict[str, bytes], dict[str, Any]]:
        if len(archiv) > self._grenzen.maximale_archivgroesse_bytes:
            raise ArchivUngueltig("Das Archiv überschreitet die zulässige Größe.")
        try:
            zip_archiv = zipfile.ZipFile(io.BytesIO(archiv))
        except zipfile.BadZipFile as fehler:
            raise ArchivUngueltig("Die Datei ist kein gültiges ZIP-Archiv.") from fehler
        with zip_archiv:
            infos = [info for info in zip_archiv.infolist() if not info.is_dir()]
            if len(infos) > self._grenzen.maximale_dateien:
                raise ArchivUngueltig("Das Archiv enthält zu viele Dateien.")
            normalisierte: dict[str, zipfile.ZipInfo] = {}
            gesamt = 0
            komprimiert = 0
            for info in infos:
                pfad = self._sicherer_archivpfad(info.filename)
                if len(pfad.encode("utf-8")) > self._grenzen.maximale_pfadlaenge:
                    raise ArchivUngueltig("Ein Archivpfad ist zu lang.")
                schluessel = pfad.casefold()
                if schluessel in normalisierte:
                    raise ArchivUngueltig("Das Archiv enthält doppelte Dateipfade.")
                normalisierte[schluessel] = info
                modus = (info.external_attr >> 16) & 0o170000
                if modus == stat.S_IFLNK:
                    raise ArchivUngueltig("Symbolische Links sind im Archiv nicht zulässig.")
                if info.flag_bits & 0x1:
                    raise ArchivUngueltig("Verschlüsselte ZIP-Einträge sind nicht zulässig.")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ArchivUngueltig("Die ZIP-Kompressionsmethode wird nicht unterstützt.")
                if info.file_size > self._grenzen.maximale_einzeldatei_bytes:
                    raise ArchivUngueltig("Eine Archivdatei überschreitet die Einzelgrenze.")
                if info.compress_size == 0 and info.file_size > 0:
                    raise ArchivUngueltig("Ein ZIP-Eintrag besitzt eine ungültige Kompression.")
                if info.compress_size and (
                    info.file_size / info.compress_size
                    > self._grenzen.maximales_kompressionsverhaeltnis
                ):
                    raise ArchivUngueltig("Das Kompressionsverhältnis ist nicht zulässig.")
                gesamt += info.file_size
                komprimiert += info.compress_size
            if gesamt > self._grenzen.maximale_entpackte_groesse_bytes:
                raise ArchivUngueltig("Der entpackte Inhalt überschreitet die Gesamtgrenze.")
            if (
                komprimiert
                and gesamt / komprimiert > self._grenzen.maximales_kompressionsverhaeltnis
            ):
                raise ArchivUngueltig("Das gesamte Kompressionsverhältnis ist nicht zulässig.")
            if "manifest.json" not in normalisierte:
                raise ArchivUngueltig("manifest.json fehlt.")
            inhalt: dict[str, bytes] = {}
            try:
                for info in infos:
                    pfad = self._sicherer_archivpfad(info.filename)
                    self._dateityp_pruefen(pfad)
                    with zip_archiv.open(info, "r") as quelle:
                        daten = quelle.read(self._grenzen.maximale_einzeldatei_bytes + 1)
                    if len(daten) != info.file_size:
                        raise ArchivUngueltig("Ein ZIP-Eintrag ist unvollständig.")
                    inhalt[pfad] = daten
            except (zipfile.BadZipFile, RuntimeError, OSError) as fehler:
                raise ArchivUngueltig("CRC- oder ZIP-Strukturprüfung fehlgeschlagen.") from fehler
        try:
            manifest = json.loads(inhalt.pop("manifest.json"))
        except (UnicodeDecodeError, json.JSONDecodeError) as fehler:
            raise ArchivUngueltig("Das Manifest ist kein gültiges JSON.") from fehler
        self._manifest_pruefen(manifest, inhalt)
        return inhalt, manifest

    def _manifest_pruefen(self, manifest: Any, inhalt: dict[str, bytes]) -> None:
        if not isinstance(manifest, dict) or manifest.get("archive_version") != ARCHIVVERSION:
            raise ArchivUngueltig("Die Archivversion wird nicht unterstützt.")
        schema_version = manifest.get("database_schema_version")
        if not isinstance(schema_version, int) or schema_version > SCHEMAVERSION:
            raise ArchivUngueltig("Die Datenbankschemaversion wird nicht unterstützt.")
        dateiliste = manifest.get("files")
        if not isinstance(dateiliste, list):
            raise ArchivUngueltig("Die Dateiliste im Manifest fehlt.")
        erwartet: dict[str, dict[str, Any]] = {}
        for eintrag in dateiliste:
            if not isinstance(eintrag, dict) or not isinstance(eintrag.get("path"), str):
                raise ArchivUngueltig("Die Dateiliste im Manifest ist ungültig.")
            pfad = self._sicherer_archivpfad(eintrag["path"])
            if pfad in erwartet:
                raise ArchivUngueltig("Das Manifest enthält doppelte Dateipfade.")
            erwartet[pfad] = eintrag
        if set(erwartet) != set(inhalt):
            raise ArchivUngueltig("Archiv und Manifest enthalten unterschiedliche Dateien.")
        for pfad, daten in inhalt.items():
            eintrag = erwartet[pfad]
            if eintrag.get("size_bytes") != len(daten) or not isinstance(
                eintrag.get("sha256"), str
            ):
                raise ArchivUngueltig("Eine Dateigröße stimmt nicht mit dem Manifest überein.")
            if not hmac_compare(eintrag["sha256"], hashlib.sha256(daten).hexdigest()):
                raise ArchivUngueltig(
                    "Eine Datei stimmt nicht mit ihrer SHA-256-Prüfsumme überein."
                )
        pflicht = {"project/project.json", "README.txt"} | {
            f"database/{tabelle}.json" for tabelle in _TABELLEN_REIHENFOLGE
        }
        if not pflicht.issubset(inhalt):
            raise ArchivUngueltig("Das Archiv ist unvollständig.")
        fingerprint_payload = {
            pfad: hashlib.sha256(daten).hexdigest()
            for pfad, daten in sorted(inhalt.items())
            if pfad != "README.txt"
        }
        erwartet_fingerprint = hashlib.sha256(self._json_bytes(fingerprint_payload)).hexdigest()
        if not hmac_compare(str(manifest.get("project_fingerprint", "")), erwartet_fingerprint):
            raise ArchivUngueltig("Der Projektfingerabdruck ist ungültig.")

    def _atomar_uebernehmen(
        self,
        kontext: Zugriffskontext,
        projekt_id: UUID,
        ziel_gruppen_id: UUID | None,
        inhalt: dict[str, bytes],
        manifest: dict[str, Any],
        *,
        archiv_sha256: str,
        archivgroesse_bytes: int,
        gast_neu_binden: bool,
        ersetzen: bool,
    ) -> None:
        basis = self._workspace.basisverzeichnis.resolve()
        basis.mkdir(parents=True, exist_ok=True)
        staging_basis = basis / ".import-staging"
        staging_basis.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="project-", dir=staging_basis))
        staged_project = staging / str(projekt_id)
        staged_project.mkdir()
        ziel = basis / "projects" / str(projekt_id)
        if ziel.exists() and not ersetzen:
            shutil.rmtree(staging, ignore_errors=True)
            raise ArchivKonflikt("Zum Projekt existiert bereits ein abweichender Dateibestand.")
        try:
            for pfad, daten in inhalt.items():
                if not (pfad.startswith("artifacts/") or pfad.startswith("reports/")):
                    continue
                relativ = PurePosixPath(pfad).relative_to(PurePosixPath(pfad).parts[0])
                datei = staged_project.joinpath(*relativ.parts)
                datei.parent.mkdir(parents=True, exist_ok=True)
                datei.write_bytes(daten)
            tabellendaten = self._tabellendaten_laden(inhalt, projekt_id)
            verbindung = sqlite3.connect(self._datenbankpfad, timeout=5.0)
            backup_project = staging / "bisheriger-dateibestand"
            dateien_ausgetauscht = False
            try:
                initialisiere_schema(verbindung)
                verbindung.execute("BEGIN IMMEDIATE")
                for tabelle, zeilen in tabellendaten.items():
                    erwartete_spalten = {
                        zeile[1]
                        for zeile in verbindung.execute(f"PRAGMA table_info({tabelle})").fetchall()
                    }
                    if any(set(zeile) != erwartete_spalten for zeile in zeilen):
                        raise ArchivUngueltig(
                            f"Die Spaltenstruktur der Tabelle {tabelle} ist ungültig."
                        )
                projekt_vorhanden = (
                    verbindung.execute(
                        "SELECT 1 FROM projekte WHERE projekt_id = ?", (str(projekt_id),)
                    ).fetchone()
                    is not None
                )
                if projekt_vorhanden != ersetzen:
                    raise ArchivKonflikt("Das Projekt wurde parallel verändert.")
                jetzt = datetime.now(UTC)
                if gast_neu_binden:
                    if kontext.gast_geheimnis is None:
                        raise ZugriffVerweigert(NICHT_VERFUEGBAR)
                    aktualisiert = verbindung.execute(
                        """
                        UPDATE projektzugehoerigkeiten SET
                            gast_geheimnis_sha256 = ?, gast_ablauf_am_utc = ?,
                            zuletzt_aktiv_am_utc = ?, revision = revision + 1
                        WHERE projekt_id = ? AND zugriffsart = 'gast'
                        """,
                        (
                            geheimnis_hash(kontext.gast_geheimnis),
                            (jetzt + self._gast_ttl).isoformat(),
                            jetzt.isoformat(),
                            str(projekt_id),
                        ),
                    )
                    if aktualisiert.rowcount != 1:
                        raise ZugriffVerweigert(NICHT_VERFUEGBAR)
                if ersetzen:
                    self._projektinhalt_aus_verbindung_loeschen(verbindung, projekt_id)
                    projektzeile = tabellendaten["projekte"][0]
                    spalten = [name for name in projektzeile if name != "projekt_id"]
                    set_sql = ",".join(f"{name}=?" for name in spalten)
                    verbindung.execute(
                        f"UPDATE projekte SET {set_sql} WHERE projekt_id=?",  # noqa: S608
                        [projektzeile[name] for name in spalten] + [str(projekt_id)],
                    )
                for tabelle in _TABELLEN_REIHENFOLGE:
                    if ersetzen and tabelle == "projekte":
                        continue
                    for zeile in tabellendaten[tabelle]:
                        spalten = list(zeile)
                        platzhalter = ",".join("?" for _ in spalten)
                        spalten_sql = ",".join(spalten)
                        verbindung.execute(
                            f"INSERT INTO {tabelle} ({spalten_sql}) VALUES ({platzhalter})",
                            [zeile[spalte] for spalte in spalten],
                        )
                if not ersetzen and kontext.gast_geheimnis is not None:
                    verbindung.execute(
                        """
                        INSERT INTO projektzugehoerigkeiten (
                            projekt_id, zugriffsart, gruppen_id, gast_geheimnis_sha256,
                            gast_ablauf_am_utc, zuletzt_aktiv_am_utc, revision, erstellt_am_utc
                        ) VALUES (?, 'gast', NULL, ?, ?, ?, 1, ?)
                        """,
                        (
                            str(projekt_id),
                            geheimnis_hash(kontext.gast_geheimnis),
                            (jetzt + self._gast_ttl).isoformat(),
                            jetzt.isoformat(),
                            jetzt.isoformat(),
                        ),
                    )
                elif not ersetzen:
                    if kontext.benutzer_id is None or ziel_gruppen_id is None:
                        raise ZugriffVerweigert(NICHT_VERFUEGBAR)
                    verbindung.execute(
                        """
                        INSERT INTO projektzugehoerigkeiten (
                            projekt_id, zugriffsart, gruppen_id, gast_geheimnis_sha256,
                            gast_ablauf_am_utc, zuletzt_aktiv_am_utc, revision, erstellt_am_utc
                        ) VALUES (?, 'kursgruppe', ?, NULL, NULL, ?, 1, ?)
                        """,
                        (
                            str(projekt_id),
                            str(ziel_gruppen_id),
                            jetzt.isoformat(),
                            jetzt.isoformat(),
                        ),
                    )
                    verbindung.execute(
                        """
                        INSERT INTO projektmitglieder (
                            projekt_id, benutzer_id, darf_bearbeiten, status, zugewiesen_am_utc
                        ) VALUES (?, ?, 1, 'aktiv', ?)
                        """,
                        (str(projekt_id), str(kontext.benutzer_id), jetzt.isoformat()),
                    )
                verbindung.execute(
                    """
                    INSERT INTO archivmetadaten (
                        archiv_id, projekt_id, gruppen_id, archivtyp, archivversion,
                        sha256, groesse_bytes, erstellt_von_benutzer_id,
                        erstellt_am_utc, status, details_json
                    ) VALUES (?, ?, ?, 'projekt_import', ?, ?, ?, ?, ?, 'erfolgreich', ?)
                    """,
                    (
                        str(uuid4()),
                        str(projekt_id),
                        None if ziel_gruppen_id is None else str(ziel_gruppen_id),
                        ARCHIVVERSION,
                        archiv_sha256,
                        archivgroesse_bytes,
                        None if kontext.benutzer_id is None else str(kontext.benutzer_id),
                        jetzt.isoformat(),
                        json.dumps(
                            {"project_fingerprint": manifest["project_fingerprint"]},
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    ),
                )
                ziel.parent.mkdir(parents=True, exist_ok=True)
                if ziel.exists():
                    os.replace(ziel, backup_project)
                os.replace(staged_project, ziel)
                dateien_ausgetauscht = True
                verbindung.commit()
            except Exception:
                verbindung.rollback()
                if dateien_ausgetauscht and ziel.exists():
                    shutil.rmtree(ziel, ignore_errors=True)
                if backup_project.exists():
                    os.replace(backup_project, ziel)
                raise
            finally:
                verbindung.close()
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _projektinhalt_aus_verbindung_loeschen(
        verbindung: sqlite3.Connection, projekt_id: UUID
    ) -> None:
        """Entfernt Projektinhalte in FK-Reihenfolge, bewahrt aber Mandant und Team."""
        projekt = str(projekt_id)
        quality_ids = [
            str(zeile[0])
            for zeile in verbindung.execute(
                "SELECT quality_run_id FROM qualitaetspruefungen WHERE projekt_id=?",
                (projekt,),
            )
        ]
        if quality_ids:
            platzhalter = ",".join("?" for _ in quality_ids)
            for tabelle in ("qualitaetsregeln", "qualitaetsmassnahmen"):
                verbindung.execute(
                    f"DELETE FROM {tabelle} WHERE quality_run_id IN ({platzhalter})",  # noqa: S608
                    quality_ids,
                )
        for tabelle in reversed(_TABELLEN_REIHENFOLGE):
            if tabelle in {"projekte", "qualitaetsregeln", "qualitaetsmassnahmen"}:
                continue
            verbindung.execute(
                f"DELETE FROM {tabelle} WHERE projekt_id=?",  # noqa: S608
                (projekt,),
            )

    def _tabellendaten_laden(
        self, inhalt: dict[str, bytes], projekt_id: UUID
    ) -> dict[str, list[dict[str, Any]]]:
        ergebnis: dict[str, list[dict[str, Any]]] = {}
        for tabelle in _TABELLEN_REIHENFOLGE:
            try:
                daten = json.loads(inhalt[f"database/{tabelle}.json"])
            except (UnicodeDecodeError, json.JSONDecodeError) as fehler:
                raise ArchivUngueltig(f"Die Tabelle {tabelle} enthält ungültiges JSON.") from fehler
            if not isinstance(daten, list) or not all(isinstance(zeile, dict) for zeile in daten):
                raise ArchivUngueltig(f"Die Tabelle {tabelle} besitzt ein ungültiges Format.")
            if tabelle not in {"qualitaetsregeln", "qualitaetsmassnahmen"}:
                if any(zeile.get("projekt_id") != str(projekt_id) for zeile in daten):
                    raise ArchivUngueltig("Das Archiv mischt Daten mehrerer Projekte.")
            ergebnis[tabelle] = daten
        if len(ergebnis["projekte"]) != 1:
            raise ArchivUngueltig("Das Archiv muss genau ein Projekt enthalten.")
        projekt_json = json.loads(inhalt["project/project.json"])
        if not isinstance(projekt_json, dict) or projekt_json != ergebnis["projekte"][0]:
            raise ArchivUngueltig("project.json stimmt nicht mit den Datenbankdaten überein.")
        self._lineage_dateien_pruefen(ergebnis, inhalt, projekt_id)
        return ergebnis

    @staticmethod
    def _lineage_dateien_pruefen(
        tabellen: dict[str, list[dict[str, Any]]],
        inhalt: dict[str, bytes],
        projekt_id: UUID,
    ) -> None:
        prefix = f"projects/{projekt_id}/"
        for zeilen in tabellen.values():
            for zeile in zeilen:
                for spalte, wert in zeile.items():
                    if not spalte.startswith("relativer_") or not spalte.endswith("_pfad"):
                        continue
                    if not isinstance(wert, str) or not wert:
                        continue
                    normalisiert = wert.replace("\\", "/")
                    if not normalisiert.startswith(prefix):
                        raise ArchivUngueltig("Eine Lineage-Dateireferenz verlässt das Projekt.")
                    relativ = normalisiert.removeprefix(prefix)
                    wurzel = (
                        "reports"
                        if Path(relativ).suffix.casefold() in {".pdf", ".html"}
                        else "artifacts"
                    )
                    if f"{wurzel}/{relativ}" not in inhalt:
                        raise ArchivUngueltig(
                            "Eine in der Lineage referenzierte Projektdatei fehlt."
                        )

    def _vorhandener_fingerabdruck(self, projekt_id: UUID) -> str | None:
        verbindung = sqlite3.connect(self._datenbankpfad)
        try:
            initialisiere_schema(verbindung)
            vorhanden = verbindung.execute(
                "SELECT 1 FROM projekte WHERE projekt_id = ?", (str(projekt_id),)
            ).fetchone()
        finally:
            verbindung.close()
        if vorhanden is None:
            return None
        daten = self._datenbank_snapshot(projekt_id)
        payload = self._payload_erstellen(projekt_id, daten, daten["projekte"][0])
        return self._payload_fingerabdruck(payload)

    def _importziel_pruefen(
        self,
        kontext: Zugriffskontext,
        ziel_gruppen_id: UUID | None,
        *,
        manifest: dict[str, Any],
    ) -> None:
        if kontext.gast_geheimnis is not None:
            if ziel_gruppen_id is not None:
                raise ZugriffVerweigert(NICHT_VERFUEGBAR)
            return
        if ziel_gruppen_id is None:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        self._autorisierung.gruppen_zugriff_pruefen(
            kontext, ziel_gruppen_id, Gruppenaktion.ARCHIVIEREN
        )
        if kontext.benutzer_id is None:
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        gruppe = self._zugriff.kursgruppe_laden(ziel_gruppen_id)
        mitgliedschaft = self._zugriff.gruppenmitgliedschaft_laden(
            ziel_gruppen_id, kontext.benutzer_id
        )
        if (
            gruppe is None
            or mitgliedschaft is None
            or mitgliedschaft.rolle is not Gruppenrolle.GRUPPENLEITUNG
            and gruppe.gruppenleitung_benutzer_id != kontext.benutzer_id
        ):
            raise ZugriffVerweigert(NICHT_VERFUEGBAR)
        if len(self._zugriff.projekt_ids_fuer_gruppe(ziel_gruppen_id)) >= gruppe.maximale_projekte:
            raise ArchivUngueltig("Die Kursgruppe hat ihre maximale Projektanzahl erreicht.")
        unkomprimiert = manifest.get("uncompressed_payload_size_bytes")
        if (
            not isinstance(unkomprimiert, int)
            or unkomprimiert > gruppe.speicherlimit_pro_projekt_bytes
        ):
            raise ArchivUngueltig("Das Projekt überschreitet das Speicherlimit der Kursgruppe.")

    def _payload_limits_pruefen(self, payload: dict[str, bytes]) -> None:
        if len(payload) > self._grenzen.maximale_dateien:
            raise ArchivUngueltig("Das Projekt enthält zu viele Dateien.")
        if any(len(daten) > self._grenzen.maximale_einzeldatei_bytes for daten in payload.values()):
            raise ArchivUngueltig("Eine Projektdatei überschreitet die Einzelgrenze.")
        if sum(map(len, payload.values())) > self._grenzen.maximale_entpackte_groesse_bytes:
            raise ArchivUngueltig("Das Projekt überschreitet die Exportgrenze.")

    @staticmethod
    def _sicherer_archivpfad(roh: str) -> str:
        if not roh or "\\" in roh or "\x00" in roh:
            raise ArchivUngueltig("Ein Archivpfad ist ungültig.")
        pfad = PurePosixPath(roh)
        if pfad.is_absolute() or any(teil in {"", ".", ".."} for teil in pfad.parts):
            raise ArchivUngueltig("Ein Archivpfad verlässt das Archiv.")
        normalisiert = pfad.as_posix()
        if normalisiert != roh:
            raise ArchivUngueltig("Ein Archivpfad ist nicht kanonisch.")
        return normalisiert

    @staticmethod
    def _dateityp_pruefen(pfad: str) -> None:
        if pfad in {"manifest.json", "README.txt", "project/project.json"}:
            return
        if pfad.startswith("database/"):
            name = PurePosixPath(pfad).name
            if name not in {f"{tabelle}.json" for tabelle in _TABELLEN_REIHENFOLGE}:
                raise ArchivUngueltig("Das Archiv enthält eine unbekannte Datenbanktabelle.")
            return
        if pfad.startswith(("artifacts/", "reports/")):
            if PurePosixPath(pfad).suffix.casefold() not in _ARTEFAKT_ENDUNGEN:
                raise ArchivUngueltig("Das Archiv enthält einen unzulässigen Artefakttyp.")
            return
        raise ArchivUngueltig("Das Archiv enthält einen unzulässigen Pfad.")

    @staticmethod
    def _json_bytes(wert: Any) -> bytes:
        return json.dumps(wert, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

    @classmethod
    def _payload_fingerabdruck(cls, payload: dict[str, bytes]) -> str:
        fingerprint_payload = {
            pfad: hashlib.sha256(inhalt).hexdigest()
            for pfad, inhalt in sorted(payload.items())
            if pfad != "README.txt"
        }
        return hashlib.sha256(cls._json_bytes(fingerprint_payload)).hexdigest()

    @staticmethod
    def _app_version() -> str:
        try:
            return version("framework-mvp")
        except PackageNotFoundError:
            return "0.1.0.dev0"


def hmac_compare(links: str, rechts: str) -> bool:
    """Konstanter Vergleich auch für manifeste Hashwerte."""
    import hmac

    return hmac.compare_digest(links, rechts)
