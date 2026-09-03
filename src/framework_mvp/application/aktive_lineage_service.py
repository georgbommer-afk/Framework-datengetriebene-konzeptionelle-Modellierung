"""Persistierter fachlicher Endpunkt der genau einen aktiven Projektlineage."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class LineageEndpunkt(StrEnum):
    """Speicherbare Endpunkte in fachlicher Abhängigkeitsreihenfolge."""

    PROJEKT = "PROJEKT"
    T = "T"
    M = "M"
    EVENT_LOG_KONFIGURATION = "EVENT_LOG_KONFIGURATION"
    E = "E"
    E_STERN = "E_STERN"
    P_A_D = "P_A_D"
    A_G = "A_G"
    K_O = "K_O"
    K_STERN = "K_STERN"


ENDPUNKT_SCHRITT = {
    LineageEndpunkt.PROJEKT: 1,
    LineageEndpunkt.T: 2,
    LineageEndpunkt.M: 3,
    LineageEndpunkt.EVENT_LOG_KONFIGURATION: 4,
    LineageEndpunkt.E: 5,
    LineageEndpunkt.E_STERN: 6,
    LineageEndpunkt.P_A_D: 7,
    LineageEndpunkt.A_G: 8,
    LineageEndpunkt.K_O: 9,
    LineageEndpunkt.K_STERN: 10,
}

REFERENZEN_JE_ENDPUNKT: dict[LineageEndpunkt, frozenset[str]] = {
    LineageEndpunkt.PROJEKT: frozenset(),
    LineageEndpunkt.T: frozenset({"aktuelle_datenquellen_id", "aktueller_zwischendatensatz_id"}),
    LineageEndpunkt.M: frozenset({"aktuelle_mappingtabelle_id"}),
    LineageEndpunkt.EVENT_LOG_KONFIGURATION: frozenset(
        {"aktuelle_mapping_id", "mapping_id", "aktuelle_event_log_konfiguration_id"}
    ),
    LineageEndpunkt.E: frozenset({"aktuelles_event_log_id", "event_log_id"}),
    LineageEndpunkt.E_STERN: frozenset({"aktuelle_freigabe_id", "freigegebenes_event_log_id"}),
    LineageEndpunkt.P_A_D: frozenset(
        {
            "aktuelle_analyse_id",
            "aktuelles_prozessmodell_id",
            "aktuelle_discovery_ergebnisse_id",
        }
    ),
    LineageEndpunkt.A_G: frozenset({"aktuelle_aggregations_id"}),
    LineageEndpunkt.K_O: frozenset(
        {"aktuelle_modellableitungs_id", "aktuelle_k_id", "aktuelle_o_id"}
    ),
    LineageEndpunkt.K_STERN: frozenset({"aktuelle_validierungslauf_id", "aktuelle_k_stern_id"}),
}

REIHENFOLGE = tuple(LineageEndpunkt)


@dataclass(frozen=True, slots=True)
class AktiveProjektlineage:
    projekt_id: UUID
    endpunkt: LineageEndpunkt
    referenzen: dict[str, str]
    revision: int
    aktualisiert_am: datetime

    @property
    def framework_schritt(self) -> int:
        return ENDPUNKT_SCHRITT[self.endpunkt]


def kanonische_projekt_id(wert: UUID | str) -> str:
    """Normalisiert Projekt-IDs für Session, Persistenz und Vergleiche."""
    return str(UUID(str(wert)))


class AktiveLineageService:
    """Schreibt Checkpoints additiv und löst nur aktive Folgebezüge."""

    def __init__(self, datenbankpfad: Path | str) -> None:
        self._datenbankpfad = Path(datenbankpfad)

    def laden(self, projekt_id: UUID | str) -> AktiveProjektlineage | None:
        projekt = kanonische_projekt_id(projekt_id)
        verbindung = sqlite3.connect(self._datenbankpfad)
        verbindung.row_factory = sqlite3.Row
        try:
            initialisiere_schema(verbindung)
            zeile = verbindung.execute(
                "SELECT * FROM aktive_projektlineage WHERE projekt_id=?", (projekt,)
            ).fetchone()
        finally:
            verbindung.close()
        if zeile is None:
            return None
        return AktiveProjektlineage(
            UUID(zeile["projekt_id"]),
            LineageEndpunkt(zeile["endpunkt"]),
            {str(k): str(v) for k, v in json.loads(zeile["referenzen_json"]).items()},
            int(zeile["revision"]),
            datetime.fromisoformat(zeile["aktualisiert_am_utc"]),
        )

    def aktivieren(
        self,
        projekt_id: UUID | str,
        endpunkt: LineageEndpunkt,
        referenzen: dict[str, UUID | str],
    ) -> AktiveProjektlineage:
        """Aktiviert eine Generation und entfernt nur nachgelagerte aktive Referenzen."""
        projekt = kanonische_projekt_id(projekt_id)
        aktuell = self.laden(projekt)
        behalten: dict[str, str] = dict(aktuell.referenzen) if aktuell else {}
        grenze = REIHENFOLGE.index(endpunkt)
        for spaeter in REIHENFOLGE[grenze:]:
            for schluessel in REFERENZEN_JE_ENDPUNKT[spaeter]:
                behalten.pop(schluessel, None)
        erlaubte = set().union(
            *(REFERENZEN_JE_ENDPUNKT[wert] for wert in REIHENFOLGE[: grenze + 1])
        )
        for schluessel, wert in referenzen.items():
            if schluessel in erlaubte and wert not in (None, ""):
                behalten[schluessel] = str(wert)
        revision = 1 if aktuell is None else aktuell.revision + 1
        zeitpunkt = datetime.now(UTC)
        verbindung = sqlite3.connect(self._datenbankpfad)
        try:
            initialisiere_schema(verbindung)
            with verbindung:
                verbindung.execute(
                    """
                    INSERT INTO aktive_projektlineage (
                        projekt_id, endpunkt, referenzen_json, revision, aktualisiert_am_utc
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(projekt_id) DO UPDATE SET
                        endpunkt=excluded.endpunkt,
                        referenzen_json=excluded.referenzen_json,
                        revision=excluded.revision,
                        aktualisiert_am_utc=excluded.aktualisiert_am_utc
                    """,
                    (
                        projekt,
                        endpunkt.value,
                        json.dumps(behalten, ensure_ascii=False, sort_keys=True),
                        revision,
                        zeitpunkt.isoformat(),
                    ),
                )
        finally:
            verbindung.close()
        return AktiveProjektlineage(UUID(projekt), endpunkt, behalten, revision, zeitpunkt)

    def legacy_uebernehmen(
        self,
        projekt_id: UUID | str,
        endpunkt: LineageEndpunkt,
        referenzen: dict[str, str],
    ) -> AktiveProjektlineage:
        """Persistiert genau einmal den rekonstruierten Ausgangspunkt eines Altprojekts."""
        vorhanden = self.laden(projekt_id)
        return vorhanden or self.aktivieren(projekt_id, endpunkt, referenzen)

    def entfernen(self, projekt_id: UUID | str) -> None:
        """Löst ausschließlich den aktiven Checkpoint; Fachhistorie bleibt erhalten."""
        projekt = kanonische_projekt_id(projekt_id)
        verbindung = sqlite3.connect(self._datenbankpfad)
        try:
            initialisiere_schema(verbindung)
            with verbindung:
                verbindung.execute(
                    "DELETE FROM aktive_projektlineage WHERE projekt_id=?", (projekt,)
                )
        finally:
            verbindung.close()
