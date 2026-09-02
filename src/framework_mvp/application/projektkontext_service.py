"""Rekonstruktion des aktiven Projektkontexts aus persistierter Artefaktlineage."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from framework_mvp.application.aktive_lineage_service import (
    AktiveLineageService,
    LineageEndpunkt,
    kanonische_projekt_id,
)


@dataclass(frozen=True, slots=True)
class Projektkontext:
    """Die tiefste vollständig validierte, zusammengehörige Projektgeneration."""

    projekt_id: UUID
    framework_schritt: int
    referenzen: dict[str, str]


class ProjektkontextService:
    """Stellt UI-Referenzen ohne Neuberechnung aus Fachpersistenz wieder her.

    Kandidaten werden vom tiefsten Artefakt aus geprüft. Schlägt die
    Integritätsprüfung eines Kandidaten fehl, wird die nächstältere Generation
    derselben Tiefe versucht; Artefakte verschiedener Generationen werden nie
    anhand bloß maximaler UUIDs kombiniert.
    """

    def __init__(
        self,
        datenbankpfad: Path | str,
        *,
        transformationen: Any,
        event_log_konfiguration: Any,
        mappingtabelle: Any,
        event_log: Any,
        datenqualitaet: Any,
        process_mining: Any,
        ergebnisaggregation: Any,
        modellableitung: Any,
        modellvalidierung: Any,
        aktive_lineage: AktiveLineageService | None = None,
    ) -> None:
        self._datenbankpfad = Path(datenbankpfad)
        self._transformationen = transformationen
        self._event_log_konfiguration = event_log_konfiguration
        self._mappingtabelle = mappingtabelle
        self._event_log = event_log
        self._datenqualitaet = datenqualitaet
        self._process_mining = process_mining
        self._ergebnisaggregation = ergebnisaggregation
        self._modellableitung = modellableitung
        self._modellvalidierung = modellvalidierung
        self._aktive_lineage = aktive_lineage or AktiveLineageService(self._datenbankpfad)

    def wiederherstellen(self, projekt_id: UUID | str) -> Projektkontext:
        """Liefert primär die persistierte aktive, andernfalls einmalig die Legacy-Lineage."""
        projekt_id = UUID(kanonische_projekt_id(projekt_id))
        checkpoint = self._aktive_lineage.laden(projekt_id)
        if checkpoint is not None:
            referenzen = self._checkpoint_aufloesen(
                projekt_id, checkpoint.endpunkt, checkpoint.referenzen
            )
            return Projektkontext(projekt_id, checkpoint.framework_schritt, referenzen)
        stufen: tuple[tuple[str, str, int, Callable[[UUID, UUID], dict[str, str]]], ...] = (
            ("modellvalidierungen", "validierungslauf_id", 10, self._aus_validierung),
            ("modellableitungen", "modellableitungs_id", 9, self._aus_modellableitung),
            ("ergebnisaggregationen", "aggregations_id", 8, self._aus_aggregation),
            ("process_mining_analysen", "analyse_id", 7, self._aus_analyse),
            ("qualitaetspruefungen", "quality_run_id", 6, self._aus_freigabe),
            ("event_logs", "event_log_id", 5, self._aus_event_log),
            ("semantische_mappings", "mapping_id", 4, self._aus_konfiguration),
            ("mappingtabellen", "mapping_id", 3, self._aus_mappingtabelle),
            ("zwischendatensaetze", "zwischendatensatz_id", 2, self._aus_datensatz),
        )
        for tabelle, id_spalte, schritt, aufloesen in stufen:
            for kandidat in self._kandidaten(tabelle, id_spalte, projekt_id):
                try:
                    referenzen = aufloesen(projekt_id, kandidat)
                except Exception:
                    continue
                self._aktive_lineage.legacy_uebernehmen(
                    projekt_id, self._endpunkt_fuer_schritt(schritt), referenzen
                )
                return Projektkontext(projekt_id, schritt, referenzen)
        return Projektkontext(projekt_id, 1, {})

    @staticmethod
    def _endpunkt_fuer_schritt(schritt: int) -> LineageEndpunkt:
        return {
            2: LineageEndpunkt.T,
            3: LineageEndpunkt.M,
            4: LineageEndpunkt.EVENT_LOG_KONFIGURATION,
            5: LineageEndpunkt.E,
            6: LineageEndpunkt.E_STERN,
            7: LineageEndpunkt.P_A_D,
            8: LineageEndpunkt.A_G,
            9: LineageEndpunkt.K_O,
            10: LineageEndpunkt.K_STERN,
        }[schritt]

    def _checkpoint_aufloesen(
        self,
        projekt_id: UUID,
        endpunkt: LineageEndpunkt,
        gespeichert: dict[str, str],
    ) -> dict[str, str]:
        """Prüft den aktiven Endpunkt und sämtliche darin gespeicherten Referenzen."""
        schluessel, aufloesen = {
            LineageEndpunkt.T: ("aktueller_zwischendatensatz_id", self._aus_datensatz),
            LineageEndpunkt.M: ("aktuelle_mappingtabelle_id", self._aus_mappingtabelle),
            LineageEndpunkt.EVENT_LOG_KONFIGURATION: (
                "aktuelle_event_log_konfiguration_id",
                self._aus_konfiguration,
            ),
            LineageEndpunkt.E: ("aktuelles_event_log_id", self._aus_event_log),
            LineageEndpunkt.E_STERN: ("aktuelle_freigabe_id", self._aus_freigabe),
            LineageEndpunkt.P_A_D: ("aktuelle_analyse_id", self._aus_analyse),
            LineageEndpunkt.A_G: ("aktuelle_aggregations_id", self._aus_aggregation),
            LineageEndpunkt.K_O: ("aktuelle_modellableitungs_id", self._aus_modellableitung),
            LineageEndpunkt.K_STERN: (
                "aktuelle_validierungslauf_id",
                self._aus_validierung,
            ),
        }[endpunkt]
        try:
            artefakt_id = UUID(gespeichert[schluessel])
        except (KeyError, TypeError, ValueError) as fehler:
            raise ValueError(
                "Der aktive Lineage-Checkpoint besitzt keinen gültigen Endpunkt."
            ) from fehler
        rekonstruiert = aufloesen(projekt_id, artefakt_id)
        for name, wert in gespeichert.items():
            if name in rekonstruiert and rekonstruiert[name] != wert:
                raise ValueError(
                    f"Die aktive Lineage-Referenz {name} stimmt nicht mit dem Artefakt überein."
                )
        return rekonstruiert

    def pruefen(self, projekt_id: UUID | str) -> Projektkontext:
        """Prüft vor Importaktivierung jede persistierte Projektlineage vollständig."""
        projekt_id = UUID(kanonische_projekt_id(projekt_id))
        kontext = self.wiederherstellen(projekt_id)
        for tabelle, id_spalte, aufloesen in (
            ("modellvalidierungen", "validierungslauf_id", self._aus_validierung),
            ("modellableitungen", "modellableitungs_id", self._aus_modellableitung),
            ("ergebnisaggregationen", "aggregations_id", self._aus_aggregation),
            ("process_mining_analysen", "analyse_id", self._aus_analyse),
            ("qualitaetspruefungen", "quality_run_id", self._aus_freigabe),
            ("event_logs", "event_log_id", self._aus_event_log),
            ("semantische_mappings", "mapping_id", self._aus_konfiguration),
            ("mappingtabellen", "mapping_id", self._aus_mappingtabelle),
            ("zwischendatensaetze", "zwischendatensatz_id", self._aus_datensatz),
        ):
            for kandidat in self._kandidaten(tabelle, id_spalte, projekt_id):
                try:
                    aufloesen(projekt_id, kandidat)
                except Exception as fehler:
                    raise ValueError(
                        f"Die Projektlineage in {tabelle} ist nicht vollständig integer."
                    ) from fehler
        return kontext

    def _kandidaten(self, tabelle: str, id_spalte: str, projekt_id: UUID) -> list[UUID]:
        verbindung = sqlite3.connect(self._datenbankpfad)
        try:
            zeilen = verbindung.execute(
                f"SELECT {id_spalte} FROM {tabelle} WHERE projekt_id=? "  # noqa: S608
                "ORDER BY erstellt_am_utc DESC, rowid DESC",
                (str(projekt_id),),
            ).fetchall()
        finally:
            verbindung.close()
        return [UUID(str(zeile[0])) for zeile in zeilen]

    def _hoechste_persistierte_stufe(self, projekt_id: UUID) -> int:
        for tabelle, schritt in (
            ("modellvalidierungen", 10),
            ("modellableitungen", 9),
            ("ergebnisaggregationen", 8),
            ("process_mining_analysen", 7),
            ("qualitaetspruefungen", 6),
            ("event_logs", 5),
            ("semantische_mappings", 4),
            ("mappingtabellen", 3),
            ("zwischendatensaetze", 2),
        ):
            verbindung = sqlite3.connect(self._datenbankpfad)
            try:
                vorhanden = verbindung.execute(
                    f"SELECT 1 FROM {tabelle} WHERE projekt_id=? LIMIT 1",  # noqa: S608
                    (str(projekt_id),),
                ).fetchone()
            finally:
                verbindung.close()
            if vorhanden:
                return schritt
        return 1

    def _aus_datensatz_id(self, projekt_id: UUID, datensatz_id: UUID) -> dict[str, str]:
        datensatz, _ = self._transformationen.zwischendatensatz_laden(datensatz_id)
        if datensatz.projekt_id != projekt_id:
            raise ValueError("Der Zwischendatensatz gehört nicht zum Projekt.")
        referenzen: dict[str, str] = {
            "aktueller_zwischendatensatz_id": str(datensatz.zwischendatensatz_id)
        }
        erste_quelle: UUID | None = None
        for import_id in datensatz.import_ids:
            geladen = self._transformationen.import_laden(import_id)
            if geladen is None or geladen.importvorgang.projekt_id != projekt_id:
                raise ValueError("Ein Ausgangsimport der Lineage fehlt.")
            if erste_quelle is None:
                erste_quelle = geladen.importvorgang.datenquellen_id
        if erste_quelle is not None:
            referenzen["aktuelle_datenquellen_id"] = str(erste_quelle)
        return referenzen

    def _aus_datensatz(self, projekt_id: UUID, datensatz_id: UUID) -> dict[str, str]:
        return self._aus_datensatz_id(projekt_id, datensatz_id)

    def _aus_mappingtabelle(self, projekt_id: UUID, mapping_id: UUID) -> dict[str, str]:
        mapping = self._mappingtabelle.laden(mapping_id)
        if mapping is None or mapping.projekt_id != projekt_id:
            raise ValueError("Die Mappingtabelle gehört nicht zum Projekt.")
        referenzen = self._aus_datensatz_id(projekt_id, mapping.zwischendatensatz_id)
        referenzen["aktuelle_mappingtabelle_id"] = str(mapping.mapping_id)
        return referenzen

    def _aus_konfiguration(self, projekt_id: UUID, mapping_id: UUID) -> dict[str, str]:
        konfiguration = self._event_log_konfiguration.laden(mapping_id)
        if konfiguration is None or konfiguration.projekt_id != projekt_id:
            raise ValueError("Die Event-Log-Konfiguration gehört nicht zum Projekt.")
        referenzen = self._aus_datensatz_id(projekt_id, konfiguration.zwischendatensatz_id)
        referenzen["aktuelle_mapping_id"] = str(konfiguration.mapping_id)
        referenzen["mapping_id"] = str(konfiguration.mapping_id)
        referenzen["aktuelle_event_log_konfiguration_id"] = str(konfiguration.mapping_id)
        if konfiguration.mappingtabelle_id is not None:
            mapping = self._mappingtabelle.laden(konfiguration.mappingtabelle_id)
            if (
                mapping is None
                or mapping.zwischendatensatz_id != konfiguration.zwischendatensatz_id
            ):
                raise ValueError("Die referenzierte Mappingtabelle ist inkonsistent.")
            referenzen["aktuelle_mappingtabelle_id"] = str(mapping.mapping_id)
        return referenzen

    def _aus_event_log(self, projekt_id: UUID, event_log_id: UUID) -> dict[str, str]:
        kontext = self._event_log.kontext_laden(event_log_id)
        if kontext.artefakt.projekt_id != projekt_id:
            raise ValueError("Das Event Log gehört nicht zum Projekt.")
        referenzen = self._aus_konfiguration(projekt_id, kontext.konfiguration.mapping_id)
        referenzen["aktuelles_event_log_id"] = str(kontext.artefakt.event_log_id)
        referenzen["event_log_id"] = str(kontext.artefakt.event_log_id)
        return referenzen

    def _aus_freigabe(self, projekt_id: UUID, freigabe_id: UUID) -> dict[str, str]:
        freigabe, _ = self._datenqualitaet.freigabe_laden(freigabe_id)
        if freigabe.projekt_id != projekt_id:
            raise ValueError("Die Freigabe gehört nicht zum Projekt.")
        referenzen = self._aus_event_log(projekt_id, freigabe.event_log_id)
        referenzen["aktuelle_freigabe_id"] = str(freigabe.freigabe_id)
        referenzen["freigegebenes_event_log_id"] = str(freigabe.event_log_id)
        return referenzen

    def _aus_analyse(self, projekt_id: UUID, analyse_id: UUID) -> dict[str, str]:
        analyse, _ = self._process_mining.laden(analyse_id)
        if analyse.projekt_id != projekt_id:
            raise ValueError("Die Analyse gehört nicht zum Projekt.")
        referenzen = self._aus_freigabe(projekt_id, analyse.qualitaetspruefung_id)
        if referenzen["aktuelles_event_log_id"] != str(analyse.event_log_id):
            raise ValueError("Analyse und freigegebenes Event Log sind inkonsistent.")
        for schluessel in (
            "aktuelle_analyse_id",
            "aktuelles_prozessmodell_id",
            "aktuelle_discovery_ergebnisse_id",
        ):
            referenzen[schluessel] = str(analyse.analyse_id)
        return referenzen

    def _aus_aggregation(self, projekt_id: UUID, aggregations_id: UUID) -> dict[str, str]:
        aggregation, _ = self._ergebnisaggregation.laden(aggregations_id)
        if aggregation.projekt_id != projekt_id:
            raise ValueError("Die Aggregation gehört nicht zum Projekt.")
        referenzen = self._aus_analyse(projekt_id, aggregation.analyse_id)
        if referenzen["aktuelle_freigabe_id"] != str(aggregation.freigabe_id) or referenzen[
            "aktuelles_event_log_id"
        ] != str(aggregation.event_log_id):
            raise ValueError("Aggregation und Eingangslineage sind inkonsistent.")
        referenzen["aktuelle_aggregations_id"] = str(aggregation.aggregations_id)
        return referenzen

    def _aus_modellableitung(self, projekt_id: UUID, ableitungs_id: UUID) -> dict[str, str]:
        ableitung, _, _ = self._modellableitung.laden(ableitungs_id)
        if ableitung.projekt_id != projekt_id:
            raise ValueError("Die Modellableitung gehört nicht zum Projekt.")
        referenzen = self._aus_aggregation(projekt_id, ableitung.aggregations_id)
        if referenzen["aktuelle_analyse_id"] != str(ableitung.analyse_id) or referenzen[
            "aktuelles_event_log_id"
        ] != str(ableitung.event_log_id):
            raise ValueError("Modellableitung und Eingangslineage sind inkonsistent.")
        referenzen.update(
            {
                "aktuelle_modellableitungs_id": str(ableitung.modellableitungs_id),
                "aktuelle_k_id": str(ableitung.k_id),
                "aktuelle_o_id": str(ableitung.o_id),
            }
        )
        return referenzen

    def _aus_validierung(self, projekt_id: UUID, validierung_id: UUID) -> dict[str, str]:
        validierung, _ = self._modellvalidierung.laden(validierung_id)
        if validierung.projekt_id != projekt_id:
            raise ValueError("Die Modellvalidierung gehört nicht zum Projekt.")
        referenzen = self._aus_modellableitung(projekt_id, validierung.modellableitungs_id)
        if referenzen["aktuelle_k_id"] != str(validierung.k_id) or referenzen[
            "aktuelle_o_id"
        ] != str(validierung.o_id):
            raise ValueError("K* und das K/O-Paar sind inkonsistent.")
        referenzen.update(
            {
                "aktuelle_validierungslauf_id": str(validierung.validierungslauf_id),
                "aktuelle_k_stern_id": str(validierung.k_stern_id),
            }
        )
        return referenzen
