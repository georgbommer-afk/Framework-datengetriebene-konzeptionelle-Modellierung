"""Quality-Gate und E*-Freigabe mit getrennten Legacy-Qualitätskopien."""

import gzip
import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from uuid import UUID

import pandas as pd

from framework_mvp.application.aktive_lineage_service import AktiveLineageService, LineageEndpunkt
from framework_mvp.application.datenqualitaet import (
    Massnahmenergebnis,
    QualitaetspruefungErgebnis,
    QualityGateKontext,
    pruefe_event_log,
    pruefe_quality_gate,
    wende_massnahmen_an,
)
from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.event_log_service import EventLogService
from framework_mvp.application.mappingtabelle_service import MappingtabelleService
from framework_mvp.application.ports.qualitaet_repository import QualitaetRepository
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    FachlicheEntscheidung,
    Freigabestatus,
    Qualitaetsfreigabe,
    Qualitaetsmassnahmenplan,
    QualitaetspruefungArtefakt,
    Qualitaetsregel,
    QualityGateErgebnis,
    Schweregrad,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher

QUALITAETS_ARTEFAKTVERSION = 1
QUALITY_GATE_ARTEFAKTVERSION = 2


class DatenqualitaetService:
    """Prüft die Artefaktkette; alte Maßnahmen bleiben ausschließlich Legacy-API."""

    def __init__(
        self,
        repository: QualitaetRepository,
        event_log_service: EventLogService,
        artefakte: ImportartefaktSpeicher,
        transformations_service: TransformationsService | None = None,
        datenquelle_service: DatenquelleService | None = None,
        mappingtabelle_service: MappingtabelleService | None = None,
        aktive_lineage: AktiveLineageService | None = None,
    ) -> None:
        self._repository = repository
        self._event_log_service = event_log_service
        self._artefakte = artefakte
        self._transformations_service = transformations_service
        self._datenquelle_service = datenquelle_service
        self._mappingtabelle_service = mappingtabelle_service
        self._aktive_lineage = aktive_lineage

    def _quality_gate_kontext(self, projekt_id: UUID, event_log_id: UUID) -> QualityGateKontext:
        """Leitet Q, T, optional M und Konfiguration ausschließlich aus E ab."""
        if self._transformations_service is None or self._datenquelle_service is None:
            raise Domaenenfehler(
                "Die Services für Q und T sind für das Quality-Gate nicht konfiguriert."
            )
        event = self._event_log_service.kontext_laden(event_log_id)
        if event.artefakt.projekt_id != projekt_id:
            raise Domaenenfehler("Der aktive Event Log gehört nicht zum aktuellen Projekt.")
        importe = []
        datenquellen = {}
        for import_id in event.zwischendatensatz.import_ids:
            geladen = self._transformations_service.import_laden(import_id)
            if geladen is None:
                raise Importintegritaetsfehler(
                    f"Der in T referenzierte Import {import_id} wurde nicht gefunden."
                )
            importvorgang = geladen.importvorgang
            if importvorgang.projekt_id != projekt_id:
                raise Importintegritaetsfehler(
                    "Ein Ausgangsimport von T gehört nicht zum aktuellen Projekt."
                )
            importe.append(importvorgang)
            quelle = self._datenquelle_service.datenquelle_laden(importvorgang.datenquellen_id)
            if quelle is not None:
                datenquellen[quelle.datenquellen_id] = quelle
        mapping_sha256 = ""
        if event.mappingtabelle is not None:
            if self._mappingtabelle_service is None:
                raise Domaenenfehler(
                    "Die referenzierte Mappingtabelle kann im Quality-Gate nicht geprüft werden."
                )
            mapping_sha256 = self._mappingtabelle_service.pruefsumme(
                event.mappingtabelle.mapping_id
            )
        return QualityGateKontext(
            event,
            tuple(datenquellen.values()),
            tuple(importe),
            mapping_sha256,
        )

    def quality_gate_pruefen(
        self,
        projekt_id: UUID,
        event_log_id: UUID,
        entscheidungen: tuple[FachlicheEntscheidung, ...] = (),
    ) -> QualityGateErgebnis:
        """Prüft die unveränderte Artefaktkette nach Tabelle 3.14 und Pseudocode 5."""
        return pruefe_quality_gate(
            self._quality_gate_kontext(projekt_id, event_log_id), entscheidungen
        )[0]

    def freigeben(
        self,
        freigabe_id: UUID,
        projekt_id: UUID,
        event_log_id: UUID,
        entscheidungen: tuple[FachlicheEntscheidung, ...],
    ) -> Qualitaetsfreigabe:
        """Speichert E* als Freigabereferenz auf exakt dasselbe E, niemals als neue CSV."""
        vorhanden = self._repository.freigabe_laden(freigabe_id)
        if vorhanden is not None:
            if vorhanden.projekt_id != projekt_id or vorhanden.event_log_id != event_log_id:
                raise Domaenenfehler(
                    "Die Freigabe-ID gehört bereits zu einer anderen Artefaktkette."
                )
            return self.freigabe_laden(freigabe_id)[0]
        kontext = self._quality_gate_kontext(projekt_id, event_log_id)
        ergebnis, q_snapshot = pruefe_quality_gate(kontext, entscheidungen)
        if not ergebnis.freigabe_moeglich:
            raise Domaenenfehler(
                "E kann erst freigegeben werden, wenn alle Pflichtprüfungen bestanden und "
                "alle fachlichen Bewertungen abgeschlossen sind."
            )
        jetzt = datetime.now(UTC)
        report_pfad = (
            PurePosixPath("projects") / str(projekt_id) / "quality" / f"{freigabe_id}.release.json"
        ).as_posix()
        vorlaeufig = Qualitaetsfreigabe(
            freigabe_id,
            projekt_id,
            event_log_id,
            ergebnis.event_log_sha256,
            ergebnis.zwischendatensatz_id,
            ergebnis.zwischendatensatz_sha256,
            ergebnis.mapping_id,
            ergebnis.mappingtabelle_id,
            ergebnis.mappingtabelle_sha256,
            ergebnis.mappingzustand,
            ergebnis.datenquellen_ids,
            ergebnis.datenquellen_snapshot_sha256,
            ergebnis.konfiguration_sha256,
            ergebnis.kettenfingerabdruck,
            report_pfad,
            "0" * 64,
            Freigabestatus.FREIGEGEBEN,
            jetzt,
        )
        freigabe_roh = asdict(vorlaeufig)
        freigabe_roh.pop("report_sha256")
        report = {
            "artefaktversion": QUALITY_GATE_ARTEFAKTVERSION,
            "artefaktart": "quality_gate_freigabe_e_stern",
            "freigabe": freigabe_roh,
            "quality_gate_ergebnis": asdict(ergebnis),
            "datenquellen_snapshot": q_snapshot,
            "event_log_konfiguration": asdict(kontext.event_log.konfiguration),
            "bedeutung": "E* verweist unverändert auf E; es wurde keine Qualitäts-CSV erzeugt.",
            "software_schemaversion": 7,
        }
        report_bytes = json.dumps(
            report, ensure_ascii=False, sort_keys=True, indent=2, default=str
        ).encode("utf-8")
        report_sha256 = hashlib.sha256(report_bytes).hexdigest()
        freigabe = replace(vorlaeufig, report_sha256=report_sha256)
        gespeichert = self._artefakte.artefakt_speichern(report_pfad, report_bytes)
        try:
            self._repository.freigabe_speichern(freigabe, report, report_sha256)
            if self._aktive_lineage is not None:
                self._aktive_lineage.aktivieren(
                    projekt_id,
                    LineageEndpunkt.E_STERN,
                    {
                        "aktuelles_event_log_id": event_log_id,
                        "event_log_id": event_log_id,
                        "aktuelle_freigabe_id": freigabe_id,
                        "freigegebenes_event_log_id": event_log_id,
                    },
                )
        except Exception:
            self._artefakte.neu_erstelltes_artefakt_entfernen(gespeichert)
            raise
        return freigabe

    def freigabe_laden(self, freigabe_id: UUID) -> tuple[Qualitaetsfreigabe, pd.DataFrame]:
        """Validiert Bericht und aktuelle Artefaktkette erneut und lädt dasselbe E."""
        freigabe = self._repository.freigabe_laden(freigabe_id)
        if freigabe is None:
            raise Importintegritaetsfehler(
                "Die E*-Freigabe wurde nicht gefunden oder ist ein Legacy-Qualitätsartefakt."
            )
        report_bytes = self._artefakte.lesen(freigabe.relativer_report_pfad)
        if hashlib.sha256(report_bytes).hexdigest() != freigabe.report_sha256:
            raise Importintegritaetsfehler("Die Prüfsumme des Freigabeberichts ist ungültig.")
        try:
            report = json.loads(report_bytes)
            if (
                report.get("artefaktversion") != QUALITY_GATE_ARTEFAKTVERSION
                or report.get("artefaktart") != "quality_gate_freigabe_e_stern"
                or report["freigabe"]["freigabe_id"] != str(freigabe.freigabe_id)
            ):
                raise Importintegritaetsfehler("Der Freigabebericht ist inkonsistent.")
            entscheidungen = tuple(
                FachlicheEntscheidung(
                    wert["kriterium_id"],
                    bool(wert["ist_mangel"]),
                    wert["begruendung"],
                    wert.get("ruecksprung_schritt"),
                )
                for wert in report["quality_gate_ergebnis"]["entscheidungen"]
            )
        except Importintegritaetsfehler:
            raise
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as fehler:
            raise Importintegritaetsfehler("Der Freigabebericht ist ungültig.") from fehler
        kontext = self._quality_gate_kontext(freigabe.projekt_id, freigabe.event_log_id)
        aktuell, _ = pruefe_quality_gate(kontext, entscheidungen)
        if (
            not aktuell.freigabe_moeglich
            or aktuell.kettenfingerabdruck != freigabe.kettenfingerabdruck
            or aktuell.event_log_sha256 != freigabe.event_log_sha256
            or aktuell.zwischendatensatz_sha256 != freigabe.zwischendatensatz_sha256
            or aktuell.mappingtabelle_sha256 != freigabe.mappingtabelle_sha256
            or aktuell.datenquellen_snapshot_sha256 != freigabe.datenquellen_snapshot_sha256
        ):
            raise Importintegritaetsfehler(
                "Die Artefaktkette wurde seit der Freigabe verändert oder besteht das "
                "Quality-Gate nicht mehr."
            )
        return freigabe, kontext.event_log.ereignisse.copy(deep=True)

    def freigaben_fuer_projekt(self, projekt_id: UUID) -> list[Qualitaetsfreigabe]:
        """Listet ausschließlich aktuell gültige neue E*-Freigaben, niemals Legacy-Kopien."""
        ergebnis = []
        for wert in self._repository.freigaben_fuer_projekt(projekt_id):
            try:
                geladen, _ = self.freigabe_laden(wert.freigabe_id)
            except (Domaenenfehler, Importintegritaetsfehler):
                continue
            ergebnis.append(geladen)
        return ergebnis

    def entscheidungen_der_freigabe(self, freigabe_id: UUID) -> tuple[FachlicheEntscheidung, ...]:
        """Lädt die begründeten Bewertungen einer zuvor erneut validierten Freigabe."""
        freigabe, _ = self.freigabe_laden(freigabe_id)
        report = json.loads(self._artefakte.lesen(freigabe.relativer_report_pfad))
        return tuple(
            FachlicheEntscheidung(
                wert["kriterium_id"],
                bool(wert["ist_mangel"]),
                wert["begruendung"],
                wert.get("ruecksprung_schritt"),
            )
            for wert in report["quality_gate_ergebnis"]["entscheidungen"]
        )

    def freigaben_fuer_event_log(
        self, projekt_id: UUID, event_log_id: UUID
    ) -> list[Qualitaetsfreigabe]:
        """Bietet Wiederaufnahme nur für dasselbe Projekt und exakt dasselbe E an."""
        return [
            wert
            for wert in self.freigaben_fuer_projekt(projekt_id)
            if wert.event_log_id == event_log_id
        ]

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
        """Listet kontrolliert lesbare Legacy-Qualitätskopien, nicht neue E*-Freigaben."""
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
