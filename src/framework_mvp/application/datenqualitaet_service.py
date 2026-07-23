"""Orchestrierung regelbasierter Qualitätsprüfung und bestätigter Maßnahmen."""

import gzip
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from uuid import UUID

import pandas as pd

from framework_mvp.application.datenqualitaet import (
    Massnahmenergebnis,
    QualitaetspruefungErgebnis,
    pruefe_event_log,
    wende_massnahmen_an,
)
from framework_mvp.application.event_log_service import EventLogService
from framework_mvp.application.ports.qualitaet_repository import QualitaetRepository
from framework_mvp.domain.models import (
    Qualitaetsmassnahmenplan,
    QualitaetspruefungArtefakt,
    Qualitaetsregel,
    Schweregrad,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher

QUALITAETS_ARTEFAKTVERSION = 1


class DatenqualitaetService:
    """Prüft Event Logs und speichert ausschließlich bestätigte Maßnahmen."""

    def __init__(
        self,
        repository: QualitaetRepository,
        event_log_service: EventLogService,
        artefakte: ImportartefaktSpeicher,
    ) -> None:
        self._repository = repository
        self._event_log_service = event_log_service
        self._artefakte = artefakte

    def pruefen(
        self, event_log_id: UUID, regeln: tuple[Qualitaetsregel, ...]
    ) -> QualitaetspruefungErgebnis:
        """Prüft das unveränderte kanonische Event Log."""
        _, daten = self._event_log_service.laden(event_log_id)
        return pruefe_event_log(daten, regeln)

    def massnahmen_vorschau(
        self,
        event_log_id: UUID,
        regeln: tuple[Qualitaetsregel, ...],
        plan: Qualitaetsmassnahmenplan,
    ) -> Massnahmenergebnis:
        """Wendet den Maßnahmenplan nur auf einer Arbeitskopie an."""
        _, daten = self._event_log_service.laden(event_log_id)
        return wende_massnahmen_an(daten, plan, regeln)

    def speichern(
        self,
        quality_run_id: UUID,
        event_log_id: UUID,
        regeln: tuple[Qualitaetsregel, ...],
        plan: Qualitaetsmassnahmenplan,
    ) -> QualitaetspruefungArtefakt:
        """Speichert Bericht, Maßnahmen und qualitätsgeprüfte CSV.GZ."""
        vorhanden = self._repository.laden(quality_run_id)
        if vorhanden is not None:
            self.laden(quality_run_id)
            return vorhanden
        event_log, original = self._event_log_service.laden(event_log_id)
        vorher = pruefe_event_log(original, regeln)
        nachher = wende_massnahmen_an(original, plan, regeln)
        jetzt = datetime.now(UTC)
        basis = PurePosixPath("projects") / str(event_log.projekt_id) / "quality"
        report_pfad = (basis / f"{quality_run_id}.report.json").as_posix()
        massnahmen_pfad = (basis / f"{quality_run_id}.measures.json").as_posix()
        csv_pfad = (basis / f"{quality_run_id}.csv.gz").as_posix()
        csv_bytes = gzip.compress(
            nachher.daten.to_csv(
                index=False, date_format="%Y-%m-%dT%H:%M:%S.%f%z", na_rep=""
            ).encode(),
            mtime=0,
        )
        sha256 = hashlib.sha256(csv_bytes).hexdigest()
        vergleich = self._vergleich(vorher, nachher.pruefung)
        report = {
            "artefaktversion": QUALITAETS_ARTEFAKTVERSION,
            "original_event_log_id": str(event_log_id),
            "regelkonfiguration": [asdict(wert) for wert in regeln],
            "ergebnis_vorher": asdict(vorher),
            "ergebnis_nachher": asdict(nachher.pruefung),
            "vergleich": vergleich,
            "original_sha256": event_log.sha256,
            "quality_sha256": sha256,
            "erstellt_am": jetzt.isoformat(),
        }
        massnahmen = {
            "artefaktversion": QUALITAETS_ARTEFAKTVERSION,
            "massnahmenplan": asdict(plan),
        }
        erzeugt = []
        try:
            erzeugt.append(self._artefakte.artefakt_speichern(csv_pfad, csv_bytes))
            erzeugt.append(
                self._artefakte.artefakt_speichern(
                    report_pfad,
                    json.dumps(
                        report, ensure_ascii=False, sort_keys=True, indent=2, default=str
                    ).encode(),
                )
            )
            erzeugt.append(
                self._artefakte.artefakt_speichern(
                    massnahmen_pfad,
                    json.dumps(
                        massnahmen,
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                        default=str,
                    ).encode(),
                )
            )
            artefakt = QualitaetspruefungArtefakt(
                quality_run_id,
                event_log.projekt_id,
                event_log_id,
                report_pfad,
                massnahmen_pfad,
                csv_pfad,
                sha256,
                jetzt,
            )
            self._repository.speichern(artefakt, regeln, plan, report, vergleich)
            return artefakt
        except Exception:
            for wert in reversed(erzeugt):
                self._artefakte.neu_erstelltes_artefakt_entfernen(wert)
            raise

    def laden(self, quality_run_id: UUID) -> tuple[QualitaetspruefungArtefakt, pd.DataFrame]:
        """Lädt die qualitätsgeprüfte Arbeitskopie nach Integritätsprüfung."""
        artefakt = self._repository.laden(quality_run_id)
        if artefakt is None:
            raise Importintegritaetsfehler("Die Qualitätsprüfung wurde nicht gefunden.")
        inhalt = self._artefakte.lesen(artefakt.relativer_csv_pfad)
        if hashlib.sha256(inhalt).hexdigest() != artefakt.sha256:
            raise Importintegritaetsfehler(
                "Die Prüfsumme der qualitätsgeprüften Arbeitskopie ist ungültig."
            )
        json.loads(self._artefakte.lesen(artefakt.relativer_report_pfad))
        json.loads(self._artefakte.lesen(artefakt.relativer_massnahmen_pfad))
        return artefakt, pd.read_csv(BytesIO(gzip.decompress(inhalt)))

    def fuer_projekt(self, projekt_id: UUID) -> list[QualitaetspruefungArtefakt]:
        """Listet ausschließlich gespeicherte Qualitätsartefakte eines Projekts."""
        return self._repository.fuer_projekt(projekt_id)

    @staticmethod
    def _vergleich(
        vorher: QualitaetspruefungErgebnis, nachher: QualitaetspruefungErgebnis
    ) -> dict[str, object]:
        def anzahl(ergebnis: QualitaetspruefungErgebnis, schwere: Schweregrad | None = None) -> int:
            return sum(
                wert.betroffene_ereignisse
                for wert in ergebnis.befunde
                if schwere is None or wert.schweregrad is schwere
            )

        return {
            "ereignisse": [vorher.ereignisanzahl, nachher.ereignisanzahl],
            "faelle": [vorher.fallanzahl, nachher.fallanzahl],
            "pflichtfeldfehler": [
                sum(
                    wert.betroffene_ereignisse
                    for wert in vorher.befunde
                    if wert.regel_id.startswith("fehlend")
                ),
                sum(
                    wert.betroffene_ereignisse
                    for wert in nachher.befunde
                    if wert.regel_id.startswith("fehlend")
                ),
            ],
            "duplikate": [
                sum(
                    wert.betroffene_ereignisse
                    for wert in ergebnis.befunde
                    if wert.regel_id
                    in {
                        "identische_ereignisse",
                        "fachlich_doppelt",
                        "doppelte_event_id",
                        "doppelte_quellzeile",
                    }
                )
                for ergebnis in (vorher, nachher)
            ],
            "zeitfehler": [
                sum(
                    wert.betroffene_ereignisse
                    for wert in ergebnis.befunde
                    if wert.dimension.value == "Zeitliche Plausibilität"
                )
                for ergebnis in (vorher, nachher)
            ],
            "lifecycle_fehler": [
                sum(
                    wert.betroffene_ereignisse
                    for wert in ergebnis.befunde
                    if wert.regel_id == "lifecycle_paarung"
                )
                for ergebnis in (vorher, nachher)
            ],
            "warnungen": [
                anzahl(vorher, Schweregrad.WARNUNG),
                anzahl(nachher, Schweregrad.WARNUNG),
            ],
            "blockierend": [
                anzahl(vorher, Schweregrad.BLOCKIEREND),
                anzahl(nachher, Schweregrad.BLOCKIEREND),
            ],
        }
