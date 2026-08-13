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

    def importieren(
        self,
        kontext: Zugriffskontext,
        archiv: bytes,
        *,
        ziel_gruppen_id: UUID | None = None,
    ) -> ImportErgebnis:
        """Validiert vollständig, staged einzeln und übernimmt DB/Dateien gemeinsam."""
        inhalt, manifest = self._archiv_pruefen(archiv)
        try:
            projekt_id = UUID(str(manifest["original_project_id"]))
        except (KeyError, TypeError, ValueError) as fehler:
            raise ArchivUngueltig("Die ursprüngliche Projekt-ID ist ungültig.") from fehler
        projektname = str(manifest.get("project_name", "")).strip()
        if not projektname:
            raise ArchivUngueltig("Der Projektname fehlt im Manifest.")
        with self._sperren.sperren(projekt_id):
            vorhandener_fingerabdruck = self._vorhandener_fingerabdruck(projekt_id)
            if vorhandener_fingerabdruck is not None:
                if not self._autorisierung.projekt_zugriff_erlaubt(
                    kontext, projekt_id, Projektaktion.ANSEHEN
                ):
                    raise ZugriffVerweigert(NICHT_VERFUEGBAR)
                if vorhandener_fingerabdruck != manifest["project_fingerprint"]:
                    raise ArchivKonflikt(
                        "Die Projekt-ID ist bereits mit abweichendem Inhalt vorhanden."
                    )
                return ImportErgebnis(projekt_id, True, projektname)
            self._importziel_pruefen(kontext, ziel_gruppen_id, manifest=manifest)
            self._atomar_uebernehmen(kontext, projekt_id, ziel_gruppen_id, inhalt, manifest)
            self._zugriff.archiv_metadaten_speichern(
                archiv_id=uuid4(),
                projekt_id=projekt_id,
                gruppen_id=ziel_gruppen_id,
                archivtyp="projekt_import",
                archivversion=ARCHIVVERSION,
                sha256=hashlib.sha256(archiv).hexdigest(),
                groesse_bytes=len(archiv),
                benutzer_id=kontext.benutzer_id,
                status="erfolgreich",
                details={"project_fingerprint": manifest["project_fingerprint"]},
                zeitpunkt=datetime.now(UTC),
            )
        return ImportErgebnis(projekt_id, False, projektname)

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
    ) -> None:
        basis = self._workspace.basisverzeichnis.resolve()
        basis.mkdir(parents=True, exist_ok=True)
        staging_basis = basis / ".import-staging"
        staging_basis.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="project-", dir=staging_basis))
        staged_project = staging / str(projekt_id)
        staged_project.mkdir()
        ziel = basis / "projects" / str(projekt_id)
        if ziel.exists():
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
                if verbindung.execute(
                    "SELECT 1 FROM projekte WHERE projekt_id = ?", (str(projekt_id),)
                ).fetchone():
                    raise ArchivKonflikt("Das Projekt wurde parallel importiert.")
                for tabelle in _TABELLEN_REIHENFOLGE:
                    for zeile in tabellendaten[tabelle]:
                        spalten = list(zeile)
                        platzhalter = ",".join("?" for _ in spalten)
                        spalten_sql = ",".join(spalten)
                        verbindung.execute(
                            f"INSERT INTO {tabelle} ({spalten_sql}) VALUES ({platzhalter})",
                            [zeile[spalte] for spalte in spalten],
                        )
                jetzt = datetime.now(UTC)
                if kontext.gast_geheimnis is not None:
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
                else:
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
                ziel.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_project, ziel)
                verbindung.commit()
            except Exception:
                verbindung.rollback()
                if ziel.exists():
                    shutil.rmtree(ziel, ignore_errors=True)
                raise
            finally:
                verbindung.close()
        finally:
            shutil.rmtree(staging, ignore_errors=True)

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
