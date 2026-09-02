"""Persistenz und Integritätsprüfung der Mappingtabelle M aus Schritt 3."""

import hashlib
import json
from dataclasses import asdict
from pathlib import PurePosixPath
from uuid import UUID

import pandas as pd

from framework_mvp.application.aktive_lineage_service import AktiveLineageService, LineageEndpunkt
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Mappingeintragsart,
    Mappingtabelle,
    Mappingtabellenstatus,
    TechnischeWertreferenz,
    Zwischendatensatz,
    mappingtabelle_aus_dict,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte.artefakt_speicher import (
    GespeichertesArtefakt,
    ImportartefaktSpeicher,
)
from framework_mvp.infrastructure.persistence.sqlite_mappingtabelle_repository import (
    SQLiteMappingtabelleRepository,
)

MAPPINGTABELLE_ARTEFAKTVERSION = 1


def _ist_fehlend(wert: object) -> bool:
    try:
        return bool(pd.isna(wert))
    except (TypeError, ValueError):
        return False


class MappingtabelleService:
    """Speichert M getrennt von der Event-Log-Konfiguration des Schritts 4."""

    def __init__(
        self,
        repository: SQLiteMappingtabelleRepository,
        transformations_service: TransformationsService,
        artefakte: ImportartefaktSpeicher,
        aktive_lineage: AktiveLineageService | None = None,
    ) -> None:
        self._repository = repository
        self._transformations_service = transformations_service
        self._artefakte = artefakte
        self._aktive_lineage = aktive_lineage

    def datensatz_laden(self, datensatz_id: UUID) -> tuple[Zwischendatensatz, pd.DataFrame]:
        """Lädt T ausschließlich über dessen bestehende Integritätsprüfung."""
        return self._transformations_service.zwischendatensatz_laden(datensatz_id)

    def _referenzen_pruefen(self, mapping: Mappingtabelle, daten: pd.DataFrame) -> None:
        """Prüft jede technische Spalten- und Wertreferenz gegen unverändertes T."""
        spalten = [str(wert) for wert in daten.columns]
        for eintrag in mapping.eintraege:
            if eintrag.art is Mappingeintragsart.SPALTENBEZEICHNUNG:
                if eintrag.technische_bezeichnung not in spalten:
                    raise Domaenenfehler(
                        "Die technische Spaltenbezeichnung ist in T nicht vorhanden: "
                        f"{eintrag.technische_bezeichnung}"
                    )
                continue
            if eintrag.technische_quellspalte not in spalten:
                raise Domaenenfehler(
                    "Die Quellspalte eines technischen Wertmappings ist in T nicht vorhanden: "
                    f"{eintrag.technische_quellspalte}"
                )
            assert eintrag.wertreferenz is not None
            position = spalten.index(eintrag.technische_quellspalte)
            vorhandene_referenzen = {
                TechnischeWertreferenz.aus_wert(wert).schluessel
                for wert in daten.iloc[:, position].drop_duplicates()
                if not _ist_fehlend(wert)
            }
            if eintrag.wertreferenz.schluessel not in vorhandene_referenzen:
                raise Domaenenfehler(
                    "Der typisierte technische Wert ist in der angegebenen Quellspalte "
                    "von T nicht vorhanden."
                )

    def _kontext_pruefen(self, mapping: Mappingtabelle) -> tuple[Zwischendatensatz, pd.DataFrame]:
        datensatz, daten = self.datensatz_laden(mapping.zwischendatensatz_id)
        if datensatz.projekt_id != mapping.projekt_id:
            raise Domaenenfehler(
                "Mappingtabelle und Zwischendatensatz gehören nicht zum selben Projekt."
            )
        self._referenzen_pruefen(mapping, daten)
        return datensatz, daten

    def speichern(self, mapping: Mappingtabelle) -> str:
        """Speichert ein bestätigtes M atomar, idempotent und datensatzgebunden."""
        if mapping.status is not Mappingtabellenstatus.BESTAETIGT:
            raise Domaenenfehler("Die Mappingtabelle muss vor dem Speichern bestätigt werden.")
        self._kontext_pruefen(mapping)
        vorhanden = self._repository.fuer_datensatz(
            mapping.projekt_id, mapping.zwischendatensatz_id
        )
        if vorhanden is not None and vorhanden[0].mapping_id != mapping.mapping_id:
            raise Domaenenfehler(
                "Für diesen Zwischendatensatz existiert bereits eine andere Mappingtabelle."
            )
        relativer_pfad = (
            PurePosixPath("projects")
            / str(mapping.projekt_id)
            / "mapping_tables"
            / f"{mapping.mapping_id}.json"
        ).as_posix()
        struktur = {
            "artefaktversion": MAPPINGTABELLE_ARTEFAKTVERSION,
            "artefaktart": "Mappingtabelle M",
            "mappingtabelle": asdict(mapping),
        }
        inhalt = json.dumps(
            struktur,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        ).encode("utf-8")
        sha256 = hashlib.sha256(inhalt).hexdigest()
        vorher = self._artefakte.artefakt_ersetzen(relativer_pfad, inhalt)
        try:
            self._repository.speichern(mapping, relativer_pfad, sha256)
            if self._aktive_lineage is not None:
                self._aktive_lineage.aktivieren(
                    mapping.projekt_id,
                    LineageEndpunkt.M,
                    {
                        "aktueller_zwischendatensatz_id": mapping.zwischendatensatz_id,
                        "aktuelle_mappingtabelle_id": mapping.mapping_id,
                    },
                )
        except Exception:
            if vorher is None:
                self._artefakte.neu_erstelltes_artefakt_entfernen(
                    GespeichertesArtefakt(relativer_pfad, True)
                )
            else:
                self._artefakte.artefakt_ersetzen(relativer_pfad, vorher)
            raise
        return relativer_pfad

    def _geladenes_pruefen(self, geladen: tuple[Mappingtabelle, str, str]) -> Mappingtabelle:
        mapping, pfad, erwartete_pruefsumme = geladen
        erwarteter_ordner = f"projects/{mapping.projekt_id}/mapping_tables/"
        if not pfad.startswith(erwarteter_ordner):
            raise Importintegritaetsfehler(
                "Der Mappingtabellenpfad passt nicht zum zugeordneten Projekt."
            )
        inhalt = self._artefakte.lesen(pfad)
        if hashlib.sha256(inhalt).hexdigest() != erwartete_pruefsumme:
            raise Importintegritaetsfehler(
                "Die Prüfsumme des Mappingtabellen-Artefakts stimmt nicht überein."
            )
        try:
            struktur = json.loads(inhalt)
            if struktur.get("artefaktversion") != MAPPINGTABELLE_ARTEFAKTVERSION:
                raise Importintegritaetsfehler(
                    "Die Mappingtabellen-Artefaktversion wird nicht unterstützt."
                )
            if struktur.get("artefaktart") != "Mappingtabelle M":
                raise Importintegritaetsfehler(
                    "Das referenzierte Artefakt ist keine Mappingtabelle M."
                )
            artefakt_mapping = mappingtabelle_aus_dict(struktur["mappingtabelle"])
        except Importintegritaetsfehler:
            raise
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as fehler:
            raise Importintegritaetsfehler("Das Mappingtabellen-Artefakt ist ungültig.") from fehler
        if artefakt_mapping != mapping:
            raise Importintegritaetsfehler(
                "Mappingtabellen-Artefakt und SQLite-Metadaten sind inkonsistent."
            )
        self._kontext_pruefen(mapping)
        return mapping

    def laden(self, mapping_id: UUID) -> Mappingtabelle | None:
        """Lädt M mit Versions-, Artefakt-, Projekt-, T- und Referenzprüfung."""
        geladen = self._repository.laden(mapping_id)
        return None if geladen is None else self._geladenes_pruefen(geladen)

    def pruefsumme(self, mapping_id: UUID) -> str:
        """Liefert die Prüfsumme ausschließlich nach vollständiger Integritätsprüfung."""
        geladen = self._repository.laden(mapping_id)
        if geladen is None:
            raise Domaenenfehler("Die Mappingtabelle wurde nicht gefunden.")
        self._geladenes_pruefen(geladen)
        return geladen[2]

    def fuer_datensatz(self, projekt_id: UUID, zwischendatensatz_id: UUID) -> Mappingtabelle | None:
        """Verhindert die stillschweigende Wiederverwendung von M eines anderen T."""
        geladen = self._repository.fuer_datensatz(projekt_id, zwischendatensatz_id)
        return None if geladen is None else self._geladenes_pruefen(geladen)

    def fuer_projekt(self, projekt_id: UUID) -> list[Mappingtabelle]:
        """Listet ausschließlich gültige Mappingtabellen M eines Projekts."""
        return [self._geladenes_pruefen(wert) for wert in self._repository.fuer_projekt(projekt_id)]
