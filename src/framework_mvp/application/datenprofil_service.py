"""Unveränderliche fachliche Profilgenerationen auf derselben Importbasis."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from framework_mvp.application.datenimport_service import DatenimportService
from framework_mvp.application.importvorgang_service import ImportvorgangService, ermittle_warnungen
from framework_mvp.domain.models import Indikatorbedingung
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.infrastructure.importartefakte.profil_json import (
    ProfilArtefakt,
    erstelle_profil_json,
    lade_profil_json,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


@dataclass(frozen=True, slots=True)
class Profilgeneration:
    profil_id: UUID
    projekt_id: UUID
    import_id: UUID
    vorgaenger_profil_id: UUID | None
    fachversion: int
    relativer_profil_pfad: str
    sha256: str
    erstellt_am: datetime
    profil: ProfilArtefakt


class DatenprofilService:
    """Erzeugt neue R-Versionen, ohne Import, T oder die aktive Lineage zu verändern."""

    def __init__(
        self,
        datenbankpfad: Path | str,
        importe: ImportvorgangService,
        datenimport: DatenimportService,
        artefakte: ImportartefaktSpeicher,
    ) -> None:
        self._datenbankpfad = Path(datenbankpfad)
        self._importe = importe
        self._datenimport = datenimport
        self._artefakte = artefakte

    def _zeilen(self, import_id: UUID) -> list[sqlite3.Row]:
        verbindung = sqlite3.connect(self._datenbankpfad)
        verbindung.row_factory = sqlite3.Row
        try:
            initialisiere_schema(verbindung)
            return verbindung.execute(
                "SELECT * FROM datenprofil_generationen WHERE import_id=? "
                "ORDER BY fachversion, erstellt_am_utc, profil_id",
                (str(import_id),),
            ).fetchall()
        finally:
            verbindung.close()

    def _legacy(self, import_id: UUID) -> Profilgeneration:
        geladen = self._importe.import_laden(import_id)
        if geladen is None:
            raise Importintegritaetsfehler("Der Import des Datenprofils wurde nicht gefunden.")
        vorgang = geladen.importvorgang
        inhalt = self._artefakte.lesen(vorgang.relativer_profil_pfad)
        return Profilgeneration(
            profil_id=import_id,
            projekt_id=vorgang.projekt_id,
            import_id=import_id,
            vorgaenger_profil_id=None,
            fachversion=1,
            relativer_profil_pfad=vorgang.relativer_profil_pfad,
            sha256=hashlib.sha256(inhalt).hexdigest(),
            erstellt_am=geladen.profil.erstellt_am,
            profil=geladen.profil,
        )

    def _aus_zeile(self, zeile: sqlite3.Row) -> Profilgeneration:
        pfad = str(zeile["relativer_profil_pfad"])
        inhalt = self._artefakte.lesen(pfad)
        if hashlib.sha256(inhalt).hexdigest() != zeile["sha256"]:
            raise Importintegritaetsfehler("Die Prüfsumme der Profilgeneration ist ungültig.")
        profil = lade_profil_json(self._artefakte.pfad(pfad))
        if profil.import_id != UUID(zeile["import_id"]):
            raise Importintegritaetsfehler("Profilgeneration und Importbasis sind inkonsistent.")
        return Profilgeneration(
            UUID(zeile["profil_id"]),
            UUID(zeile["projekt_id"]),
            UUID(zeile["import_id"]),
            UUID(zeile["vorgaenger_profil_id"]),
            int(zeile["fachversion"]),
            pfad,
            str(zeile["sha256"]),
            datetime.fromisoformat(zeile["erstellt_am_utc"]),
            profil,
        )

    def fuer_import(self, import_id: UUID) -> tuple[Profilgeneration, ...]:
        return (
            self._legacy(import_id),
            *(self._aus_zeile(wert) for wert in self._zeilen(import_id)),
        )

    def aktuellste(self, import_id: UUID) -> Profilgeneration:
        return self.fuer_import(import_id)[-1]

    def erweitern(
        self,
        import_id: UUID,
        indikatorbedingungen: tuple[Indikatorbedingung, ...],
        *,
        vorgaenger_profil_id: UUID | None = None,
        profil_id: UUID | None = None,
    ) -> Profilgeneration:
        """Bestätigt einen Profilentwurf als neue R-Version auf unveränderten Raw-Bytes."""
        generationen = self.fuer_import(import_id)
        vorgaenger = generationen[-1]
        if vorgaenger_profil_id is not None:
            vorgaenger = next(
                (wert for wert in generationen if wert.profil_id == vorgaenger_profil_id),
                None,
            )
            if vorgaenger is None:
                raise Importintegritaetsfehler("Die gewählte Vorgänger-Profilgeneration fehlt.")
        vorgang, raw = self._importe.originaldatei_laden(import_id)
        vorschau = self._datenimport.vorschau_erstellen(raw, vorgang.importparameter)
        platzhalter = tuple(
            vorgaenger.profil.gesamtprofil.get("bestaetigte_zusaetzliche_platzhalter", ())
        )
        profil = self._datenimport.profil_erstellen(
            vorschau.vollstaendige_tabelle,
            platzhalter,
            indikatorbedingungen,
        ).profil
        jetzt = datetime.now(UTC)
        neue_id = profil_id or uuid4()
        fachversion = max(wert.fachversion for wert in generationen) + 1
        inhalt = erstelle_profil_json(
            import_id=import_id,
            datei_pruefsumme=vorgang.sha256,
            importparameter=vorgang.importparameter,
            tabellenbezeichnung=vorgang.tabellenbezeichnung,
            erstellt_am=jetzt,
            profil=profil,
            warnungen=ermittle_warnungen(profil),
        )
        sha256 = hashlib.sha256(inhalt).hexdigest()
        pfad = (
            PurePosixPath("projects")
            / str(vorgang.projekt_id)
            / "profile_generations"
            / f"{neue_id}.json"
        ).as_posix()
        gespeichert = self._artefakte.artefakt_speichern(pfad, inhalt)
        verbindung = sqlite3.connect(self._datenbankpfad)
        try:
            initialisiere_schema(verbindung)
            with verbindung:
                verbindung.execute(
                    "INSERT INTO datenprofil_generationen VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(neue_id),
                        str(vorgang.projekt_id),
                        str(import_id),
                        str(vorgaenger.profil_id),
                        fachversion,
                        pfad,
                        sha256,
                        jetzt.isoformat(),
                    ),
                )
        except Exception:
            self._artefakte.neu_erstelltes_artefakt_entfernen(gespeichert)
            raise
        finally:
            verbindung.close()
        return self.aktuellste(import_id)
