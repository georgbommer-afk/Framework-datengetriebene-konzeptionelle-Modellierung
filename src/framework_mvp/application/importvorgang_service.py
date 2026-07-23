"""Bestätigungsablauf und Integritätsprüfung persistierter Importvorgänge."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

from framework_mvp.application.ports.datenquelle_repository import DatenquelleRepository
from framework_mvp.application.ports.importvorgang_repository import ImportvorgangRepository
from framework_mvp.application.ports.projekt_repository import ProjektRepository
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    DateiMetadaten,
    Datenprofil,
    Importstatus,
    Importvorgang,
    Profilzusammenfassung,
)
from framework_mvp.domain.models.importvorgang import Importparameter
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte.artefakt_speicher import (
    GespeichertesArtefakt,
    ImportartefaktSpeicher,
)
from framework_mvp.infrastructure.importartefakte.profil_json import (
    PROFIL_VERSION,
    ProfilArtefakt,
    erstelle_profil_json,
    lade_profil_json,
)


@dataclass(frozen=True, slots=True)
class GeladenerImport:
    """Integritätsgeprüfte Metadaten und Profilstruktur eines Imports."""

    importvorgang: Importvorgang
    profil: ProfilArtefakt


def ermittle_profilzusammenfassung(profil: Datenprofil) -> Profilzusammenfassung:
    """Verdichtet zentrale Qualitätskennzahlen für SQLite."""
    return Profilzusammenfassung(
        echte_fehlwerte=profil.echte_fehlwerte,
        textuelle_platzhalter=profil.textuelle_platzhalter,
        exakte_duplikate=profil.exakte_duplikate,
        potenzielle_ausreisser=sum(
            spalte.numerisch.potenzielle_ausreisser
            for spalte in profil.spaltenprofile
            if spalte.numerisch is not None
        ),
    )


def ermittle_warnungen(profil: Datenprofil) -> tuple[str, ...]:
    """Leitet reproduzierbare technische Qualitätswarnungen ab."""
    warnungen: list[str] = []
    if profil.echte_fehlwerte:
        warnungen.append(f"Die Tabelle enthält {profil.echte_fehlwerte} echte Fehlwerte.")
    if profil.textuelle_platzhalter:
        warnungen.append(
            f"Die Tabelle enthält {profil.textuelle_platzhalter} textuelle Fehlwertplatzhalter."
        )
    if profil.exakte_duplikate:
        warnungen.append(f"Die Tabelle enthält {profil.exakte_duplikate} exakte Duplikate.")
    ausreisser = ermittle_profilzusammenfassung(profil).potenzielle_ausreisser
    if ausreisser:
        warnungen.append(f"Es wurden {ausreisser} potenzielle numerische Ausreißer erkannt.")
    return tuple(warnungen)


class ImportvorgangService:
    """Koordiniert Dateisystemartefakte und transaktionale SQLite-Metadaten."""

    def __init__(
        self,
        repository: ImportvorgangRepository,
        projekt_repository: ProjektRepository,
        datenquelle_repository: DatenquelleRepository,
        artefakte: ImportartefaktSpeicher,
    ) -> None:
        """Übernimmt explizite Ports und den Artefaktspeicher ohne globalen Zustand."""
        self._repository = repository
        self._projekt_repository = projekt_repository
        self._datenquelle_repository = datenquelle_repository
        self._artefakte = artefakte

    def import_bestaetigen(
        self,
        *,
        import_id: UUID,
        projekt_id: UUID,
        datenquellen_id: UUID,
        datei_metadaten: DateiMetadaten,
        dateiinhalt: bytes,
        importparameter: Importparameter,
        tabellenbezeichnung: str,
        profil: Datenprofil,
    ) -> Importvorgang:
        """Bestätigt einen Import idempotent mit kontrollierter Kompensation."""
        vorhanden = self._repository.laden(import_id)
        if vorhanden is not None:
            return vorhanden
        projekt = self._projekt_repository.laden(projekt_id)
        datenquelle = self._datenquelle_repository.laden(datenquellen_id)
        if projekt is None:
            raise Domaenenfehler("Das zugehörige Projekt wurde nicht gefunden.")
        if datenquelle is None or datenquelle.projekt_id != projekt_id:
            raise Domaenenfehler("Projekt und Datenquelle des Imports gehören nicht zusammen.")
        if hashlib.sha256(dateiinhalt).hexdigest() != datei_metadaten.sha256:
            raise Importintegritaetsfehler(
                "Die Uploadbytes stimmen nicht mit ihrer Prüfsumme überein."
            )
        warnungen = ermittle_warnungen(profil)
        zusammenfassung = ermittle_profilzusammenfassung(profil)
        raw: GespeichertesArtefakt | None = None
        profilartefakt: GespeichertesArtefakt | None = None
        try:
            raw = self._artefakte.raw_speichern(
                projekt_id,
                datei_metadaten.sha256,
                datei_metadaten.sicherer_dateiname,
                dateiinhalt,
            )
            relativer_profil_pfad = (
                PurePosixPath("projects") / str(projekt_id) / "profiles" / f"{import_id}.json"
            ).as_posix()
            zeitpunkt = datetime.now(UTC)
            importvorgang = Importvorgang(
                import_id=import_id,
                projekt_id=projekt_id,
                datenquellen_id=datenquellen_id,
                originaldateiname=datei_metadaten.urspruenglicher_dateiname,
                sicherer_dateiname=datei_metadaten.sicherer_dateiname,
                dateityp=datei_metadaten.dateityp,
                dateigroesse_bytes=datei_metadaten.dateigroesse_bytes,
                sha256=datei_metadaten.sha256,
                importparameter=importparameter,
                tabellenbezeichnung=tabellenbezeichnung,
                zeilenanzahl=profil.zeilen,
                spaltenanzahl=profil.spalten,
                profil_version=PROFIL_VERSION,
                relativer_raw_pfad=raw.relativer_pfad,
                relativer_profil_pfad=relativer_profil_pfad,
                profilzusammenfassung=zusammenfassung,
                warnungen=warnungen,
                status=Importstatus.BESTAETIGT,
                erstellt_am=zeitpunkt,
                bestaetigt_am=zeitpunkt,
            )
            profil_json = erstelle_profil_json(
                import_id=import_id,
                datei_pruefsumme=datei_metadaten.sha256,
                importparameter=importparameter,
                tabellenbezeichnung=tabellenbezeichnung,
                erstellt_am=zeitpunkt,
                profil=profil,
                warnungen=warnungen,
            )
            profilartefakt = self._artefakte.profil_speichern(projekt_id, import_id, profil_json)
            lade_profil_json(self._artefakte.pfad(profilartefakt.relativer_pfad))
            self._repository.speichern(importvorgang)
            return importvorgang
        except Exception:
            if profilartefakt is not None:
                self._artefakte.neu_erstelltes_artefakt_entfernen(profilartefakt)
            if raw is not None:
                self._artefakte.neu_erstelltes_artefakt_entfernen(raw)
            raise

    @staticmethod
    def import_warnings(profil: Datenprofil) -> tuple[str, ...]:
        """Liefert die vor einer Bestätigung anzuzeigenden Qualitätswarnungen."""
        return ermittle_warnungen(profil)

    def import_laden(self, import_id: UUID) -> GeladenerImport | None:
        """Lädt einen Import und prüft Referenzen, Raw-Prüfsumme und Profil-JSON."""
        importvorgang = self._repository.laden(import_id)
        if importvorgang is None:
            return None
        projekt = self._projekt_repository.laden(importvorgang.projekt_id)
        datenquelle = self._datenquelle_repository.laden(importvorgang.datenquellen_id)
        erwarteter_praefix = f"projects/{importvorgang.projekt_id}/"
        if (
            projekt is None
            or datenquelle is None
            or datenquelle.projekt_id != importvorgang.projekt_id
            or not importvorgang.relativer_raw_pfad.startswith(erwarteter_praefix)
            or not importvorgang.relativer_profil_pfad.startswith(erwarteter_praefix)
        ):
            raise Importintegritaetsfehler(
                "Projekt- und Datenquellenbezug des gespeicherten Imports sind inkonsistent."
            )
        raw = self._artefakte.lesen(importvorgang.relativer_raw_pfad)
        if hashlib.sha256(raw).hexdigest() != importvorgang.sha256:
            raise Importintegritaetsfehler(
                "Die Prüfsumme der gespeicherten Originaldatei stimmt nicht überein."
            )
        profilpfad = self._artefakte.pfad(importvorgang.relativer_profil_pfad)
        if not profilpfad.is_file():
            raise Importintegritaetsfehler("Die gespeicherte Profil-Datei ist nicht vorhanden.")
        profil = lade_profil_json(profilpfad)
        if (
            profil.import_id != importvorgang.import_id
            or profil.datei_pruefsumme != importvorgang.sha256
            or profil.profil_version != importvorgang.profil_version
        ):
            raise Importintegritaetsfehler(
                "Profil-JSON und Importmetadaten gehören nicht zum selben Import."
            )
        return GeladenerImport(importvorgang, profil)

    def importe_fuer_projekt(self, projekt_id: UUID) -> list[Importvorgang]:
        """Listet die Importe eines Projekts stabil auf."""
        return self._repository.fuer_projekt_auflisten(projekt_id)

    def importe_fuer_datenquelle(self, datenquellen_id: UUID) -> list[Importvorgang]:
        """Listet die Importe einer Datenquelle stabil auf."""
        return self._repository.fuer_datenquelle_auflisten(datenquellen_id)

    def originaldatei_laden(self, import_id: UUID) -> tuple[Importvorgang, bytes]:
        """Lädt einen integritätsgeprüften Import und seine unveränderten Originalbytes."""
        geladen = self.import_laden(import_id)
        if geladen is None:
            raise Domaenenfehler("Der angeforderte Import wurde nicht gefunden.")
        return geladen.importvorgang, self._artefakte.lesen(
            geladen.importvorgang.relativer_raw_pfad
        )
