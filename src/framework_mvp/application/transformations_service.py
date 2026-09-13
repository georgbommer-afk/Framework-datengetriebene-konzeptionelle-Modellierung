# pyright: reportAttributeAccessIssue=false
"""Planverwaltung, Vorschau und Erzeugung reproduzierbarer Zwischendatensätze."""

import gzip
import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import pandas as pd

from framework_mvp.application.aktive_lineage_service import AktiveLineageService, LineageEndpunkt
from framework_mvp.application.datenimport_service import (
    DatenimportService,
    Profilierungsergebnis,
)
from framework_mvp.application.importvorgang_service import GeladenerImport, ImportvorgangService
from framework_mvp.application.loesch_service import LoeschService
from framework_mvp.application.profiling.entscheidungsgrundlage import (
    ermittle_auffaelligkeiten,
)
from framework_mvp.application.transformation import (
    Transformationsergebnis,
    fuehre_join_aus,
    fuehre_transformationsplan_aus,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    TRANSFORMATIONSART_BEZEICHNUNGEN,
    DateiMetadaten,
    Dateityp,
    ExcelImportparameter,
    Importvorgang,
    Transformationsart,
    Transformationshistorie,
    Transformationsplan,
    Transformationsschritt,
    Zwischendatensatz,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte.artefakt_speicher import (
    GespeichertesArtefakt,
    ImportartefaktSpeicher,
)
from framework_mvp.infrastructure.importartefakte.profil_json import ProfilArtefakt
from framework_mvp.infrastructure.persistence.sqlite_etl_repository import SQLiteETLRepository

TRANSFORMATIONS_ARTEFAKT_VERSION = 2


@dataclass(frozen=True, slots=True)
class Transformationsabschluss:
    """Ergebnis der einzigen physischen Persistenzgrenze von Schritt 2."""

    datensatz: Zwischendatensatz
    ergebnis: Transformationsergebnis
    daten_geaendert: bool
    datensatz_wiederverwendet: bool


class TransformationsService:
    """Orchestriert unveränderliche Pläne, Vorschauen und Interim-Artefakte."""

    def __init__(
        self,
        repository: SQLiteETLRepository,
        import_service: ImportvorgangService,
        datenimport_service: DatenimportService,
        artefakte: ImportartefaktSpeicher,
        aktive_lineage: AktiveLineageService | None = None,
        loesch_service: LoeschService | None = None,
    ) -> None:
        self._repository = repository
        self._import_service = import_service
        self._datenimport_service = datenimport_service
        self._artefakte = artefakte
        self._aktive_lineage = aktive_lineage
        self._loesch_service = loesch_service

    @staticmethod
    def schritt_hinzufuegen(
        plan: Transformationsplan, schritt: Transformationsschritt
    ) -> Transformationsplan:
        """Fügt einen Schritt kontrolliert am Planende an."""
        neu = replace(schritt, reihenfolge=len(plan.schritte) + 1)
        return replace(plan, schritte=(*plan.schritte, neu), geaendert_am=datetime.now(UTC))

    @staticmethod
    def schritt_entfernen(plan: Transformationsplan, schritt_id: UUID) -> Transformationsplan:
        """Entfernt einen Schritt und nummeriert die verbleibenden Schritte neu."""
        verbleibend = [
            wert for wert in plan.schritte if wert.transformationsschritt_id != schritt_id
        ]
        schritte = tuple(
            replace(wert, reihenfolge=index) for index, wert in enumerate(verbleibend, 1)
        )
        return replace(plan, schritte=schritte, geaendert_am=datetime.now(UTC))

    @staticmethod
    def schritt_verschieben(
        plan: Transformationsplan, schritt_id: UUID, neue_position: int
    ) -> Transformationsplan:
        """Verschiebt einen Schritt an eine gültige einsbasierte Position."""
        if neue_position < 1 or neue_position > len(plan.schritte):
            raise Domaenenfehler("Die neue Schrittposition liegt außerhalb des Plans.")
        liste = list(sorted(plan.schritte, key=lambda wert: wert.reihenfolge))
        index = next(
            (
                position
                for position, wert in enumerate(liste)
                if wert.transformationsschritt_id == schritt_id
            ),
            None,
        )
        if index is None:
            raise Domaenenfehler("Der Transformationsschritt wurde nicht gefunden.")
        schritt = liste.pop(index)
        liste.insert(neue_position - 1, schritt)
        return replace(
            plan,
            schritte=tuple(
                replace(wert, reihenfolge=position) for position, wert in enumerate(liste, 1)
            ),
            geaendert_am=datetime.now(UTC),
        )

    @staticmethod
    def schritt_aktivieren(
        plan: Transformationsplan, schritt_id: UUID, aktiviert: bool
    ) -> Transformationsplan:
        """Ersetzt genau einen Schritt mit geändertem Aktivierungszustand."""
        schritte = tuple(
            replace(wert, aktiviert=aktiviert)
            if wert.transformationsschritt_id == schritt_id
            else wert
            for wert in plan.schritte
        )
        return replace(plan, schritte=schritte, geaendert_am=datetime.now(UTC))

    def plan_speichern(self, plan: Transformationsplan) -> None:
        """Persistiert die aktuelle Plankonfiguration."""
        self._repository.plan_speichern(plan)

    def _plan_fuer_bearbeitung(self, plan: Transformationsplan) -> Transformationsplan:
        """Forkt einen bereits finalisierten Plan, damit die aktive T-Lineage unverändert bleibt."""
        if not self._repository.datensaetze_fuer_plan(plan.transformationsplan_id):
            return plan
        jetzt = datetime.now(UTC)
        return Transformationsplan(
            uuid4(),
            plan.projekt_id,
            plan.import_ids,
            plan.schritte,
            jetzt,
            jetzt,
        )

    def schritt_entfernen_und_vorschau(
        self, plan: Transformationsplan, schritt_id: UUID
    ) -> tuple[Transformationsplan, Transformationsergebnis]:
        """Entfernt einen Planschritt, persistiert nur den Plan und berechnet die Vorschau neu."""
        bearbeitbar = self._plan_fuer_bearbeitung(plan)
        aktualisiert = self.schritt_entfernen(bearbeitbar, schritt_id)
        if len(aktualisiert.schritte) == len(bearbeitbar.schritte):
            raise Domaenenfehler("Der Transformationsschritt wurde nicht gefunden.")
        ergebnis = self.vorschau(aktualisiert)
        self._repository.plan_speichern(aktualisiert)
        return aktualisiert, ergebnis

    def plan_laden(self, plan_id: UUID) -> Transformationsplan | None:
        """Lädt einen persistierten Transformationsplan."""
        return self._repository.plan_laden(plan_id)

    def neuester_plan_fuer_import(
        self, projekt_id: UUID, import_id: UUID
    ) -> Transformationsplan | None:
        """Lädt die zuletzt geänderte, persistierte Kette eines Ausgangsimports."""
        kandidaten = [
            plan
            for plan in self._repository.plaene_fuer_projekt(projekt_id)
            if import_id in plan.import_ids
        ]
        return max(kandidaten, key=lambda wert: wert.geaendert_am, default=None)

    def import_dataframe_laden(self, import_id: UUID) -> pd.DataFrame:
        """Rekonstruiert die importierte Tabelle aus Raw-Datei und Importparametern."""
        importvorgang, inhalt = self._import_service.originaldatei_laden(import_id)
        return self._datenimport_service.vorschau_erstellen(
            inhalt, importvorgang.importparameter
        ).vollstaendige_tabelle

    def importe_fuer_projekt(self, projekt_id: UUID) -> list[Importvorgang]:
        """Listet die bestätigten Importquellen für Transformation und Join."""
        return self._import_service.importe_fuer_projekt(projekt_id)

    def import_laden(self, import_id: UUID) -> GeladenerImport | None:
        """Lädt einen Ausgangsimport über dessen vollständige Integritätsprüfung."""
        return self._import_service.import_laden(import_id)

    def excel_tabellenblaetter(self, import_id: UUID) -> tuple[str, ...]:
        """Listet weitere Blätter derselben unveränderten XLSX-Importdatei."""
        vorgang, inhalt = self._import_service.originaldatei_laden(import_id)
        if vorgang.dateityp is not Dateityp.XLSX:
            return ()
        return tuple(wert.name for wert in self._datenimport_service.excel_tabellenblaetter(inhalt))

    def excel_arbeitsblatt_vorschau(
        self, basis_import_id: UUID, tabellenblatt: str
    ) -> tuple[pd.DataFrame, Profilierungsergebnis]:
        """Liest und profiliert ein vorhandenes Blatt, ohne es bereits zu bestätigen."""
        vorgang, inhalt = self._import_service.originaldatei_laden(basis_import_id)
        if not isinstance(vorgang.importparameter, ExcelImportparameter):
            raise Domaenenfehler("Die Ausgangsdatei ist keine XLSX-Arbeitsmappe.")
        parameter = ExcelImportparameter(tabellenblatt, vorgang.importparameter.kopfzeile)
        vorschau = self._datenimport_service.vorschau_erstellen(inhalt, parameter)
        profil = self._datenimport_service.profil_erstellen(vorschau.vollstaendige_tabelle)
        return vorschau.vollstaendige_tabelle, profil

    def excel_arbeitsblatt_aufbereiten(
        self,
        basis_import_id: UUID,
        tabellenblatt: str,
        *,
        import_id: UUID | None = None,
        plan_id: UUID | None = None,
        datensatz_id: UUID | None = None,
    ) -> tuple[Importvorgang, Transformationsplan, None, pd.DataFrame]:
        """Bestätigt ein zweites Blatt samt Plan, ohne dafür ein Hilfs-T zu materialisieren."""
        vorgang, inhalt = self._import_service.originaldatei_laden(basis_import_id)
        if vorgang.dateityp is not Dateityp.XLSX or not isinstance(
            vorgang.importparameter, ExcelImportparameter
        ):
            raise Domaenenfehler("Weitere Tabellenblätter sind nur für XLSX verfügbar.")
        blaetter = self.excel_tabellenblaetter(basis_import_id)
        if tabellenblatt not in blaetter or tabellenblatt == vorgang.importparameter.tabellenblatt:
            raise Domaenenfehler("Wählen Sie ein anderes vorhandenes Tabellenblatt aus.")
        parameter = ExcelImportparameter(tabellenblatt, vorgang.importparameter.kopfzeile)
        vorschau = self._datenimport_service.vorschau_erstellen(inhalt, parameter)
        metadaten = DateiMetadaten(
            vorgang.originaldateiname,
            vorgang.sicherer_dateiname,
            vorgang.dateigroesse_bytes,
            vorgang.dateityp,
            vorgang.sha256,
        )
        bestaetigt = self._import_service.import_bestaetigen(
            import_id=import_id or uuid4(),
            projekt_id=vorgang.projekt_id,
            datenquellen_id=vorgang.datenquellen_id,
            datei_metadaten=metadaten,
            dateiinhalt=inhalt,
            importparameter=parameter,
            tabellenbezeichnung=tabellenblatt,
            profil=self._datenimport_service.profil_erstellen(
                vorschau.vollstaendige_tabelle
            ).profil,
        )
        plan = Transformationsplan.neu(vorgang.projekt_id, (bestaetigt.import_id,))
        if plan_id is not None:
            plan = replace(plan, transformationsplan_id=plan_id)
        ergebnis = self.vorschau(plan)
        del datensatz_id
        self._repository.plan_speichern(plan)
        return bestaetigt, plan, None, ergebnis.daten

    def _importe_des_plans(self, plan: Transformationsplan) -> list[Importvorgang]:
        """Validiert den Projektbezug und liefert die Importe in Planreihenfolge."""
        nach_id = {
            importvorgang.import_id: importvorgang
            for importvorgang in self.importe_fuer_projekt(plan.projekt_id)
        }
        fehlend = [import_id for import_id in plan.import_ids if import_id not in nach_id]
        if fehlend:
            raise Domaenenfehler(
                "Mindestens ein Ausgangsimport fehlt oder gehört nicht zum Projekt des Plans."
            )
        return [nach_id[import_id] for import_id in plan.import_ids]

    def ausgangsprofil_laden(self, import_id: UUID) -> ProfilArtefakt:
        """Lädt das unveränderte, bestätigte technische Ausgangsprofil."""
        geladen = self._import_service.import_laden(import_id)
        if geladen is None:
            raise Domaenenfehler("Das Ausgangsprofil des Imports wurde nicht gefunden.")
        return geladen.profil

    @staticmethod
    def profil_cache_schluessel(plan: Transformationsplan) -> str:
        """Bildet einen stabilen Schlüssel aus Quellen und vollständigem Transformationsplan."""
        struktur = json.dumps(asdict(plan), ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(struktur.encode("utf-8")).hexdigest()

    def vorschauprofil_erstellen(self, ergebnis: Transformationsergebnis) -> Profilierungsergebnis:
        """Berechnet ein separates, nicht persistiertes Profil des vollständigen Ergebnisses."""
        return self._datenimport_service.profil_erstellen(ergebnis.daten)

    def arbeitsprofil_erstellen(self, daten: pd.DataFrame) -> Profilierungsergebnis:
        """Berechnet das aktuelle Profil für die Konfiguration des nächsten Kettenschritts."""
        return self._datenimport_service.profil_erstellen(daten)

    def vorschau(self, plan: Transformationsplan) -> Transformationsergebnis:
        """Wendet alle Schritte streng geordnet neu auf unveränderte Raw-Daten an."""
        self._importe_des_plans(plan)
        daten = self.import_dataframe_laden(plan.import_ids[0])
        historie: list[Transformationshistorie] = []
        warnungen: list[str] = []
        for schritt in sorted(plan.schritte, key=lambda wert: wert.reihenfolge):
            if not schritt.aktiviert:
                continue
            ergebnis = self._schritt_ausfuehren(plan, schritt, daten)
            daten = ergebnis.daten
            historie.extend(ergebnis.historie)
            warnungen.extend(ergebnis.warnungen)
        return Transformationsergebnis(
            daten,
            daten.head(200).copy(deep=True),
            tuple(historie),
            tuple(warnungen),
        )

    def _schritt_ausfuehren(
        self,
        plan: Transformationsplan,
        schritt: Transformationsschritt,
        daten: pd.DataFrame,
    ) -> Transformationsergebnis:
        """Validiert und berechnet genau einen Schritt auf einem vorhandenen Arbeitsstand."""
        if not schritt.frameworkkonform:
            raise Domaenenfehler(
                f"Der Legacy-Schritt '{schritt.typ.value}' ist nicht mehr "
                "frameworkkonform und wird nicht ausgeführt."
            )
        if schritt.typ.value != "tabellen_join":
            einzelplan = replace(plan, schritte=(replace(schritt, reihenfolge=1),))
            ergebnis = fuehre_transformationsplan_aus(daten, einzelplan)
            return replace(
                ergebnis,
                historie=tuple(
                    replace(wert, schritt=schritt.reihenfolge) for wert in ergebnis.historie
                ),
            )
        parameter = schritt.parameter
        rechter_plan_id = parameter.get("rechter_transformationsplan_id")
        rechte_datensatz_id = parameter.get("rechter_zwischendatensatz_id")
        if not rechter_plan_id and not rechte_datensatz_id:
            raise Domaenenfehler(
                "Eine Verknüpfung benötigt einen rechten Transformationsplan oder "
                "Zwischendatensatz."
            )
        if rechter_plan_id:
            rechter_plan = self.plan_laden(UUID(str(rechter_plan_id)))
            if rechter_plan is None or rechter_plan.projekt_id != plan.projekt_id:
                raise Domaenenfehler("Der rechte Transformationsplan gehört nicht zum Projekt.")
            if rechter_plan.transformationsplan_id == plan.transformationsplan_id:
                raise Domaenenfehler("Ein Transformationsplan kann nicht mit sich selbst joinen.")
            rechte_daten = self.vorschau(rechter_plan).daten
        else:
            rechter_datensatz, rechte_daten = self.zwischendatensatz_laden(
                UUID(str(rechte_datensatz_id))
            )
            if rechter_datensatz.projekt_id != plan.projekt_id:
                raise Domaenenfehler("Die Join-Datensätze gehören nicht zum selben Projekt.")
        suffixe_roh = parameter.get("suffixe", ["_links", "_rechts"])
        suffixe = (str(suffixe_roh[0]), str(suffixe_roh[1]))
        zeilen_vorher, spalten_vorher = daten.shape
        ergebnisdaten, pruefung = fuehre_join_aus(
            daten,
            rechte_daten,
            linke_schluessel=tuple(parameter["linke_schluessel"]),
            rechte_schluessel=tuple(parameter["rechte_schluessel"]),
            join_art=str(parameter["join_art"]),
            suffixe=suffixe,
            nm_bestaetigt=bool(parameter.get("nm_bestaetigt", False)),
        )
        historie = Transformationshistorie(
            schritt.reihenfolge,
            schritt.beschreibung,
            schritt.betroffene_spalten,
            zeilen_vorher,
            len(ergebnisdaten),
            spalten_vorher,
            len(ergebnisdaten.columns),
            f"Kardinalität {pruefung.kardinalitaet}; {len(ergebnisdaten)} Ergebniszeilen",
        )
        return Transformationsergebnis(
            ergebnisdaten,
            ergebnisdaten.head(200).copy(deep=True),
            (historie,),
            tuple(pruefung.warnungen),
        )

    def _transformationsartefakt(self, datensatz: Zwischendatensatz) -> dict[str, object]:
        try:
            struktur = json.loads(self._artefakte.lesen(datensatz.relativer_transformation_pfad))
        except (json.JSONDecodeError, UnicodeDecodeError) as fehler:
            raise Importintegritaetsfehler(
                "Die Transformations-Lineage ist kein gültiges JSON."
            ) from fehler
        if not isinstance(struktur, dict):
            raise Importintegritaetsfehler("Die Transformations-Lineage ist ungültig.")
        return struktur

    def regelbasierte_abstraktionen_laden(
        self, datensatz: Zwischendatensatz
    ) -> tuple[dict[str, object], ...]:
        """Liest tatsächlich ausgeführte regelbasierte Abstraktionen aus T."""
        artefakt = self._transformationsartefakt(datensatz)
        plan = artefakt.get("transformationsplan", {})
        schritte = plan.get("schritte", []) if isinstance(plan, dict) else []
        historie = artefakt.get("transformationshistorie", [])
        if not isinstance(schritte, list) or not isinstance(historie, list):
            return ()
        wirkung_nach_schritt = {
            int(wert["schritt"]): str(wert.get("ergebnis_oder_warnung", ""))
            for wert in historie
            if isinstance(wert, dict) and isinstance(wert.get("schritt"), int)
        }
        ergebnis: list[dict[str, object]] = []
        regelarten = {
            "Beginnt mit",
            "Enthält",
            "Regulärer Ausdruck",
        }
        for schritt in schritte:
            if not isinstance(schritt, dict) or not bool(schritt.get("aktiviert", True)):
                continue
            typ = str(schritt.get("typ", ""))
            try:
                parameter = json.loads(str(schritt.get("parameter_json", "{}")))
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(parameter, dict):
                continue
            vergleichsart = str(parameter.get("vergleichsart", ""))
            ist_neuer_typ = typ == Transformationsart.WERTE_REGELBASIERT_ABSTRAHIEREN.value
            ist_legacy = (
                typ == Transformationsart.WERTE_ERSETZEN.value and vergleichsart in regelarten
            )
            if not (ist_neuer_typ or ist_legacy) or vergleichsart not in regelarten:
                continue
            try:
                reihenfolge = int(schritt["reihenfolge"])
            except (KeyError, TypeError, ValueError):
                continue
            wirkung = wirkung_nach_schritt.get(reihenfolge)
            if wirkung is None:
                continue
            treffer = re.match(r"^(\d+) Werte (?:regelbasiert abstrahiert|ersetzt)", wirkung)
            if treffer is None or int(treffer.group(1)) == 0:
                continue
            spalten = schritt.get("betroffene_spalten", [])
            if not isinstance(spalten, list) or not spalten:
                continue
            quellspalten = [str(spalte) for spalte in spalten]
            quellspalte = quellspalten[0]
            zielmodus = str(parameter.get("zielmodus", "Bestehende Spalte überschreiben"))
            suchwert = str(parameter.get("suchwert", parameter.get("gesuchter_wert", "")))
            vorher_muster = (
                f"{suchwert}*"
                if vergleichsart == "Beginnt mit"
                else f"*{suchwert}*"
                if vergleichsart == "Enthält"
                else suchwert
            )
            dokumentation: dict[str, object] = {
                "quellspalte": quellspalte,
                "vergleichsart": vergleichsart,
                "suchwert_muster": suchwert,
                "vorher_muster": vorher_muster,
                "abstraktionswert": parameter.get("ersatzwert"),
                "zielspalte": (
                    str(parameter.get("zielspalte", "")).strip()
                    if zielmodus == "Neue Spalte erstellen"
                    else quellspalte
                ),
                "betroffene_beobachtungen": int(treffer.group(1)),
                "originalwerte_erhalten": zielmodus == "Neue Spalte erstellen",
            }
            if len(quellspalten) > 1:
                treffer_nach_spalte = {
                    name.strip(): int(anzahl)
                    for name, anzahl in re.findall(r"([^;():]+): (\d+) Treffer", wirkung)
                }
                dokumentation.update(
                    {
                        "quellspalten": quellspalten,
                        "zielspalten": quellspalten,
                        "treffer_nach_spalte": treffer_nach_spalte,
                    }
                )
            ergebnis.append(dokumentation)
        return tuple(ergebnis)

    def fachliche_transformationshistorie_laden(
        self, datensatz: Zwischendatensatz
    ) -> tuple[dict[str, object], ...]:
        """Projiziert die persistierte Lineage einmalig auf fachliche Schritte innerhalb T."""
        artefakt = self._transformationsartefakt(datensatz)
        plan = artefakt.get("transformationsplan", {})
        schritte = plan.get("schritte", []) if isinstance(plan, dict) else []
        historie = artefakt.get("transformationshistorie", [])
        if not isinstance(schritte, list) or not isinstance(historie, list):
            return ()
        wirkung_nach_schritt = {
            int(wert["schritt"]): wert
            for wert in historie
            if isinstance(wert, dict) and isinstance(wert.get("schritt"), int)
        }
        aktive_schritte = [
            wert
            for wert in schritte
            if isinstance(wert, dict) and bool(wert.get("aktiviert", True))
        ]
        ergebnis: list[dict[str, object]] = []
        for schritt in aktive_schritte:
            try:
                reihenfolge = int(schritt["reihenfolge"])
                transformationsart = Transformationsart(str(schritt["typ"]))
                parameter = json.loads(str(schritt.get("parameter_json", "{}")))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            wirkung = wirkung_nach_schritt.get(reihenfolge)
            if not isinstance(wirkung, dict) or not isinstance(parameter, dict):
                continue
            regel = {
                name: parameter[name]
                for name in (
                    "vergleichsart",
                    "suchwert",
                    "gesuchte_werte",
                    "operator",
                    "wert",
                    "format",
                    "datentyp",
                )
                if name in parameter
            }
            ergebnis.append(
                {
                    "reihenfolge": reihenfolge,
                    "betroffener_datensatz": "Zwischendatensatz T",
                    "transformationsart": TRANSFORMATIONSART_BEZEICHNUNGEN.get(
                        transformationsart, transformationsart.value
                    ),
                    "betroffene_spalten": [
                        str(wert) for wert in schritt.get("betroffene_spalten", [])
                    ],
                    "regel": regel,
                    "ersatz_oder_abstraktionswert": parameter.get("ersatzwert", ""),
                    "zielspalte_oder_modus": parameter.get(
                        "zielspalte", parameter.get("zielmodus", "")
                    ),
                    "beschreibung": str(schritt.get("beschreibung", "")),
                    "fachliche_begruendung": str(schritt.get("fachliche_begruendung", "")),
                    "eingang": (
                        "ursprüngliche Datenquelle D"
                        if not ergebnis
                        else "vorheriger Arbeitsstand innerhalb T"
                    ),
                    "ergebnis": (
                        "aktiver Zwischendatensatz T"
                        if len(ergebnis) + 1 == len(aktive_schritte)
                        else "nächster Arbeitsstand innerhalb T"
                    ),
                    "wirkung": str(wirkung.get("ergebnis_oder_warnung", "")),
                    "zeilen_vorher": int(wirkung.get("zeilen_vorher", 0)),
                    "zeilen_nachher": int(wirkung.get("zeilen_nachher", 0)),
                    "spalten_vorher": int(wirkung.get("spalten_vorher", 0)),
                    "spalten_nachher": int(wirkung.get("spalten_nachher", 0)),
                }
            )
        return tuple(ergebnis)

    def _letzter_ausgefuehrter_stand(
        self, plan: Transformationsplan
    ) -> tuple[Zwischendatensatz | None, pd.DataFrame, tuple[Transformationshistorie, ...]]:
        """Lädt den letzten zur aktuellen Plankette passenden Zwischenstand."""
        schritt_ids = [str(wert.transformationsschritt_id) for wert in plan.schritte]
        for datensatz in reversed(
            self._repository.datensaetze_fuer_plan(plan.transformationsplan_id)
        ):
            artefakt = self._transformationsartefakt(datensatz)
            artefakt_plan = artefakt.get("transformationsplan")
            artefakt_schritte = (
                artefakt_plan.get("schritte", []) if isinstance(artefakt_plan, dict) else []
            )
            ids = [
                str(wert.get("transformationsschritt_id"))
                for wert in artefakt_schritte
                if isinstance(wert, dict)
            ]
            if ids != schritt_ids:
                continue
            _, daten = self.zwischendatensatz_laden(datensatz.zwischendatensatz_id)
            historie_roh = artefakt.get("transformationshistorie", [])
            if not isinstance(historie_roh, list):
                historie_roh = []
            historie = tuple(
                Transformationshistorie(
                    int(wert["schritt"]),
                    str(wert["aktion"]),
                    tuple(str(spalte) for spalte in wert.get("betroffene_spalten", [])),
                    int(wert["zeilen_vorher"]),
                    int(wert["zeilen_nachher"]),
                    int(wert["spalten_vorher"]),
                    int(wert["spalten_nachher"]),
                    str(wert["ergebnis_oder_warnung"]),
                )
                for wert in historie_roh
                if isinstance(wert, dict)
            )
            return datensatz, daten, historie
        ergebnis = self.vorschau(plan)
        return None, ergebnis.daten, ergebnis.historie

    def arbeitsstand_laden(
        self, plan: Transformationsplan
    ) -> tuple[Zwischendatensatz | None, pd.DataFrame]:
        """Liefert den letzten persistierten Zwischenstand oder den kontrollierten Planstand."""
        datensatz, daten, _ = self._letzter_ausgefuehrter_stand(plan)
        return datensatz, daten

    def transformation_anwenden(
        self,
        plan: Transformationsplan,
        schritt: Transformationsschritt,
        datensatz_id: UUID | None = None,
        *,
        zusaetzliche_import_ids: tuple[UUID, ...] = (),
    ) -> tuple[Transformationsplan, Transformationsergebnis, None]:
        """Persistiert einen Planschritt und seine Vorschau, aber ausdrücklich noch kein T."""
        del datensatz_id  # Kompatibler Parameter; T entsteht ausschließlich beim Abschluss.
        bearbeitbar = self._plan_fuer_bearbeitung(plan)
        aktualisiert = self.schritt_hinzufuegen(bearbeitbar, schritt)
        if zusaetzliche_import_ids:
            aktualisiert = replace(
                aktualisiert,
                import_ids=tuple(
                    dict.fromkeys((*aktualisiert.import_ids, *zusaetzliche_import_ids))
                ),
            )
        ergebnis = self.vorschau(aktualisiert)
        self._repository.plan_speichern(aktualisiert)
        return aktualisiert, ergebnis, None

    def zwischendatensatz_erzeugen(
        self,
        plan: Transformationsplan,
        ergebnis: Transformationsergebnis,
        datensatz_id: UUID,
        *,
        vorgaenger: Zwischendatensatz | None = None,
        angewendeter_schritt: Transformationsschritt | None = None,
        aktivieren: bool = True,
    ) -> Zwischendatensatz:
        """Speichert CSV.GZ, Schema und Transformation mit Kompensation."""
        vorhanden = self._repository.datensatz_laden(datensatz_id)
        if vorhanden is not None:
            if vorhanden.transformationsplan_id != plan.transformationsplan_id:
                raise Domaenenfehler(
                    "Die Zwischendatensatz-ID gehört bereits zu einem anderen Transformationsplan."
                )
            dateninhalt = self._artefakte.lesen(vorhanden.relativer_daten_pfad)
            if hashlib.sha256(dateninhalt).hexdigest() != vorhanden.sha256:
                raise Importintegritaetsfehler(
                    "Der vorhandene Zwischendatensatz besitzt eine abweichende Prüfsumme."
                )
            try:
                gzip.decompress(dateninhalt)
                json.loads(self._artefakte.lesen(vorhanden.relativer_schema_pfad))
                json.loads(self._artefakte.lesen(vorhanden.relativer_transformation_pfad))
            except (gzip.BadGzipFile, json.JSONDecodeError, UnicodeDecodeError) as fehler:
                raise Importintegritaetsfehler(
                    "Die vorhandenen Zwischendatensatz-Artefakte sind inkonsistent."
                ) from fehler
            return vorhanden
        self._repository.plan_speichern(plan)
        jetzt = datetime.now(UTC)
        csv_bytes = self._daten_komprimieren(ergebnis.daten)
        pruefsumme = hashlib.sha256(csv_bytes).hexdigest()
        basis = PurePosixPath("projects") / str(plan.projekt_id) / "interim"
        daten_pfad = (basis / f"{datensatz_id}.csv.gz").as_posix()
        schema_pfad = (basis / f"{datensatz_id}.schema.json").as_posix()
        transformation_pfad = (basis / f"{datensatz_id}.transformation.json").as_posix()
        ausgangsimporte = self._importe_des_plans(plan)
        ausgangsprofile = [self.ausgangsprofil_laden(wert.import_id) for wert in ausgangsimporte]
        vorherige_lineage = self._transformationsartefakt(vorgaenger) if vorgaenger else None
        vorheriges_schema = (
            json.loads(self._artefakte.lesen(vorgaenger.relativer_schema_pfad))
            if vorgaenger is not None
            else None
        )
        ursprungsspalten = dict(
            vorheriges_schema.get("urspruengliche_quellspalten_nach_import", {})
            if isinstance(vorheriges_schema, dict)
            else {}
        )
        for importvorgang in ausgangsimporte:
            import_schluessel = str(importvorgang.import_id)
            if import_schluessel not in ursprungsspalten:
                ursprungsspalten[import_schluessel] = [
                    str(name)
                    for name in self.import_dataframe_laden(importvorgang.import_id).columns
                ]
        schema = {
            "artefakt_version": 1,
            "spalten": [
                {"name": str(name), "technischer_datentyp": str(ergebnis.daten[name].dtype)}
                for name in ergebnis.daten.columns
            ],
            "urspruengliche_quellspalten_nach_import": ursprungsspalten,
            "datumsformat": "ISO-8601",
            "fehlwertdarstellung": "leeres CSV-Feld",
            "zeilenanzahl": len(ergebnis.daten),
            "spaltenanzahl": len(ergebnis.daten.columns),
            "sha256": pruefsumme,
            "import_ids": [str(wert) for wert in plan.import_ids],
            "erstellt_am": jetzt.isoformat(),
        }
        ergebnisprofil = self._datenimport_service.profil_erstellen(ergebnis.daten).profil
        transformation = {
            "artefakt_version": TRANSFORMATIONS_ARTEFAKT_VERSION,
            "software_schema_version": 4,
            "ausgangsprofil_version": ausgangsprofile[0].profil_version,
            "ausgangsimport_id": str(plan.import_ids[0]),
            "ausgangsimporte": [
                {
                    "import_id": str(importvorgang.import_id),
                    "datenquellen_id": str(importvorgang.datenquellen_id),
                    "originaldateiname": importvorgang.originaldateiname,
                    "tabellenbezeichnung": importvorgang.tabellenbezeichnung,
                    "dateiformat": importvorgang.dateityp.value,
                    "datei_pruefsumme": importvorgang.sha256,
                    "profil_version": profil.profil_version,
                    "profil_pfad": importvorgang.relativer_profil_pfad,
                }
                for importvorgang, profil in zip(ausgangsimporte, ausgangsprofile, strict=True)
            ],
            "relevante_auffaelligkeiten": (
                vorherige_lineage.get("relevante_auffaelligkeiten", [])
                if isinstance(vorherige_lineage, dict)
                else [
                    asdict(wert)
                    for wert in ermittle_auffaelligkeiten(
                        self.ausgangsprofil_laden(plan.import_ids[0]).gesamtprofil,
                        self.import_dataframe_laden(plan.import_ids[0]),
                    )
                    if wert.anzahl > 0
                ]
            ),
            "transformationsplan": asdict(plan),
            "transformationshistorie": [asdict(wert) for wert in ergebnis.historie],
            "inkrementelle_lineage": {
                "eingabedatensatz": (
                    "Raw + vollständiger Transformationsplan"
                    if vorgaenger is None
                    else f"Zwischendatensatz {max(1, len(ergebnis.historie) - 1)}"
                ),
                "eingabe_zwischendatensatz_id": (
                    None if vorgaenger is None else str(vorgaenger.zwischendatensatz_id)
                ),
                "ausgabe_zwischendatensatz_id": str(datensatz_id),
                "angewendeter_transformationsschritt_id": (
                    None
                    if angewendeter_schritt is None
                    else str(angewendeter_schritt.transformationsschritt_id)
                ),
                "folgeartefakte_neu_zu_erzeugen": vorgaenger is not None,
            },
            "ergebnisprofil": asdict(ergebnisprofil),
            "ergebniskennzahlen": {
                "zeilen": len(ergebnis.daten),
                "spalten": len(ergebnis.daten.columns),
            },
            "warnungen": list(ergebnis.warnungen),
        }
        if angewendeter_schritt is not None and ergebnis.historie:
            wirkung = ergebnis.historie[-1]
            transformation["inkrementelle_ausfuehrung"] = {
                "reihenfolge": angewendeter_schritt.reihenfolge,
                "transformationsart": TRANSFORMATIONSART_BEZEICHNUNGEN.get(
                    angewendeter_schritt.typ, angewendeter_schritt.typ.value
                ),
                "betroffene_spalte_oder_bedingung": (
                    angewendeter_schritt.beschreibung
                    or ", ".join(angewendeter_schritt.betroffene_spalten)
                    or "gesamter Datensatz"
                ),
                "eingabedatensatz": (
                    "Rohimport"
                    if vorgaenger is None
                    else f"Zwischendatensatz {angewendeter_schritt.reihenfolge - 1}"
                ),
                "erzeugter_zwischendatensatz": (
                    f"Zwischendatensatz {angewendeter_schritt.reihenfolge}"
                ),
                "zeilen_vorher": wirkung.zeilen_vorher,
                "zeilen_nachher": wirkung.zeilen_nachher,
                "status": "Erfolgreich",
            }
        schema_bytes = json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2).encode()
        transformation_bytes = json.dumps(
            transformation, ensure_ascii=False, sort_keys=True, indent=2, default=str
        ).encode()
        erzeugt: list[GespeichertesArtefakt] = []
        try:
            erzeugt.append(self._artefakte.artefakt_speichern(daten_pfad, csv_bytes))
            erzeugt.append(self._artefakte.artefakt_speichern(schema_pfad, schema_bytes))
            erzeugt.append(
                self._artefakte.artefakt_speichern(transformation_pfad, transformation_bytes)
            )
            datensatz = Zwischendatensatz(
                datensatz_id,
                plan.projekt_id,
                plan.transformationsplan_id,
                plan.import_ids,
                daten_pfad,
                schema_pfad,
                transformation_pfad,
                pruefsumme,
                len(ergebnis.daten),
                len(ergebnis.daten.columns),
                jetzt,
            )
            self._repository.datensatz_speichern(datensatz)
            if aktivieren and self._aktive_lineage is not None:
                self._aktive_lineage.aktivieren(
                    plan.projekt_id,
                    LineageEndpunkt.T,
                    {"aktueller_zwischendatensatz_id": datensatz.zwischendatensatz_id},
                )
            return datensatz
        except Exception:
            for artefakt in reversed(erzeugt):
                self._artefakte.neu_erstelltes_artefakt_entfernen(artefakt)
            raise

    @staticmethod
    def _daten_komprimieren(daten: pd.DataFrame) -> bytes:
        """Serialisiert Ergebnisdaten deterministisch für Vergleich und Persistenz."""
        csv_text = daten.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%S.%f%z", na_rep="")
        return gzip.compress(csv_text.encode("utf-8"), mtime=0)

    def _aktiven_datensatz_laden(
        self,
        projekt_id: UUID,
        explizite_id: UUID | None,
    ) -> Zwischendatensatz | None:
        datensatz_id = explizite_id
        if datensatz_id is None and self._aktive_lineage is not None:
            checkpoint = self._aktive_lineage.laden(projekt_id)
            referenz = (
                checkpoint.referenzen.get("aktueller_zwischendatensatz_id") if checkpoint else None
            )
            if referenz:
                datensatz_id = UUID(referenz)
        if datensatz_id is None:
            return None
        datensatz = self._repository.datensatz_laden(datensatz_id)
        if datensatz is None or datensatz.projekt_id != projekt_id:
            raise Domaenenfehler("Der bisher aktive Zwischendatensatz wurde nicht gefunden.")
        return datensatz

    def _identischen_datensatz_auf_plan_umstellen(
        self,
        datensatz: Zwischendatensatz,
        plan: Transformationsplan,
        ergebnis: Transformationsergebnis,
    ) -> Zwischendatensatz:
        """Aktualisiert nur Plan-, Schema- und Lineage-Metadaten eines unveränderten T."""
        self._repository.plan_speichern(plan)
        schema = json.loads(self._artefakte.lesen(datensatz.relativer_schema_pfad))
        transformation = self._transformationsartefakt(datensatz)
        ausgangsimporte = self._importe_des_plans(plan)
        ausgangsprofile = [self.ausgangsprofil_laden(wert.import_id) for wert in ausgangsimporte]
        ursprungsspalten = dict(schema.get("urspruengliche_quellspalten_nach_import", {}))
        for importvorgang in ausgangsimporte:
            ursprungsspalten.setdefault(
                str(importvorgang.import_id),
                [
                    str(name)
                    for name in self.import_dataframe_laden(importvorgang.import_id).columns
                ],
            )
        schema.update(
            {
                "spalten": [
                    {"name": str(name), "technischer_datentyp": str(ergebnis.daten[name].dtype)}
                    for name in ergebnis.daten.columns
                ],
                "urspruengliche_quellspalten_nach_import": ursprungsspalten,
                "zeilenanzahl": len(ergebnis.daten),
                "spaltenanzahl": len(ergebnis.daten.columns),
                "import_ids": [str(wert) for wert in plan.import_ids],
            }
        )
        ergebnisprofil = self._datenimport_service.profil_erstellen(ergebnis.daten).profil
        transformation.update(
            {
                "artefakt_version": TRANSFORMATIONS_ARTEFAKT_VERSION,
                "ausgangsprofil_version": ausgangsprofile[0].profil_version,
                "ausgangsimport_id": str(plan.import_ids[0]),
                "ausgangsimporte": [
                    {
                        "import_id": str(importvorgang.import_id),
                        "datenquellen_id": str(importvorgang.datenquellen_id),
                        "originaldateiname": importvorgang.originaldateiname,
                        "tabellenbezeichnung": importvorgang.tabellenbezeichnung,
                        "dateiformat": importvorgang.dateityp.value,
                        "datei_pruefsumme": importvorgang.sha256,
                        "profil_version": profil.profil_version,
                        "profil_pfad": importvorgang.relativer_profil_pfad,
                    }
                    for importvorgang, profil in zip(ausgangsimporte, ausgangsprofile, strict=True)
                ],
                "transformationsplan": asdict(plan),
                "transformationshistorie": [asdict(wert) for wert in ergebnis.historie],
                "inkrementelle_lineage": {
                    "eingabedatensatz": "Raw + vollständiger Transformationsplan",
                    "eingabe_zwischendatensatz_id": None,
                    "ausgabe_zwischendatensatz_id": str(datensatz.zwischendatensatz_id),
                    "angewendeter_transformationsschritt_id": None,
                    "folgeartefakte_neu_zu_erzeugen": False,
                },
                "ergebnisprofil": asdict(ergebnisprofil),
                "ergebniskennzahlen": {
                    "zeilen": len(ergebnis.daten),
                    "spalten": len(ergebnis.daten.columns),
                },
                "warnungen": list(ergebnis.warnungen),
            }
        )
        transformation.pop("inkrementelle_ausfuehrung", None)
        schema_bytes = json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2).encode()
        transformation_bytes = json.dumps(
            transformation, ensure_ascii=False, sort_keys=True, indent=2, default=str
        ).encode()
        altes_schema = self._artefakte.artefakt_ersetzen(
            datensatz.relativer_schema_pfad, schema_bytes
        )
        alte_transformation: bytes | None = None
        aktualisiert = replace(
            datensatz,
            transformationsplan_id=plan.transformationsplan_id,
            import_ids=plan.import_ids,
            zeilenanzahl=len(ergebnis.daten),
            spaltenanzahl=len(ergebnis.daten.columns),
        )
        try:
            alte_transformation = self._artefakte.artefakt_ersetzen(
                datensatz.relativer_transformation_pfad, transformation_bytes
            )
            self._repository.datensatz_aktualisieren(aktualisiert)
        except Exception:
            if altes_schema is not None:
                self._artefakte.artefakt_ersetzen(datensatz.relativer_schema_pfad, altes_schema)
            if alte_transformation is not None:
                self._artefakte.artefakt_ersetzen(
                    datensatz.relativer_transformation_pfad, alte_transformation
                )
            raise
        if datensatz.transformationsplan_id != plan.transformationsplan_id:
            self._repository.plan_loeschen_wenn_ungenutzt(datensatz.transformationsplan_id)
        return aktualisiert

    def _referenzierte_hilfsdatensaetze(
        self,
        plan: Transformationsplan,
        besuchte_plaene: set[UUID] | None = None,
    ) -> set[UUID]:
        """Schützt ausschließlich T-Artefakte, die alte Join-Pläne noch reproduzierbar machen."""
        besucht = set() if besuchte_plaene is None else besuchte_plaene
        if plan.transformationsplan_id in besucht:
            return set()
        besucht.add(plan.transformationsplan_id)
        referenzen: set[UUID] = set()
        for schritt in plan.schritte:
            if not schritt.aktiviert or schritt.typ is not Transformationsart.TABELLEN_JOIN:
                continue
            datensatz_id = schritt.parameter.get("rechter_zwischendatensatz_id")
            if datensatz_id:
                referenzen.add(UUID(str(datensatz_id)))
            rechter_plan_id = schritt.parameter.get("rechter_transformationsplan_id")
            if not rechter_plan_id:
                continue
            rechter_plan = self.plan_laden(UUID(str(rechter_plan_id)))
            if rechter_plan is not None:
                referenzen.update(self._referenzierte_hilfsdatensaetze(rechter_plan, besucht))
        return referenzen

    def _veraltete_datensaetze_bereinigen(
        self,
        plan: Transformationsplan,
        aktiver_datensatz_id: UUID,
    ) -> None:
        """Entfernt projektweit überholte T-Generationen, nicht aber nötige Legacy-Join-Eingaben."""
        if self._loesch_service is None:
            return
        geschuetzt = {
            aktiver_datensatz_id,
            *self._referenzierte_hilfsdatensaetze(plan),
        }
        for datensatz in self._repository.datensaetze_fuer_projekt(plan.projekt_id):
            if datensatz.zwischendatensatz_id not in geschuetzt:
                self._loesch_service.zwischendatensatz_loeschen(
                    plan.projekt_id,
                    datensatz.zwischendatensatz_id,
                )

    def zwischendatensatz_abschliessen(
        self,
        plan: Transformationsplan,
        *,
        bisheriger_datensatz_id: UUID | None = None,
        datensatz_id: UUID | None = None,
    ) -> Transformationsabschluss:
        """Persistiert am Schritt-2-Abschluss genau ein finales T oder verwendet es wieder."""
        ergebnis = self.vorschau(plan)
        kandidat_sha256 = hashlib.sha256(self._daten_komprimieren(ergebnis.daten)).hexdigest()
        bisheriger = self._aktiven_datensatz_laden(plan.projekt_id, bisheriger_datensatz_id)
        if bisheriger is not None and bisheriger.sha256 == kandidat_sha256:
            aktualisiert = self._identischen_datensatz_auf_plan_umstellen(
                bisheriger, plan, ergebnis
            )
            self._veraltete_datensaetze_bereinigen(
                plan,
                aktualisiert.zwischendatensatz_id,
            )
            return Transformationsabschluss(aktualisiert, ergebnis, False, True)

        neuer_datensatz = self.zwischendatensatz_erzeugen(
            plan,
            ergebnis,
            datensatz_id or uuid4(),
            aktivieren=False,
        )
        if self._aktive_lineage is not None:
            self._aktive_lineage.aktivieren(
                plan.projekt_id,
                LineageEndpunkt.T,
                {"aktueller_zwischendatensatz_id": neuer_datensatz.zwischendatensatz_id},
            )
        self._veraltete_datensaetze_bereinigen(
            plan,
            neuer_datensatz.zwischendatensatz_id,
        )
        return Transformationsabschluss(neuer_datensatz, ergebnis, True, False)

    def join_schritt_ersetzen(
        self,
        plan: Transformationsplan,
        bisheriger_schritt_id: UUID,
        neuer_schritt: Transformationsschritt,
        datensatz_id: UUID | None = None,
        *,
        zusaetzliche_import_ids: tuple[UUID, ...] = (),
    ) -> tuple[Transformationsplan, Transformationsergebnis, None]:
        """Ersetzt einen Join im Plan und berechnet ausschließlich die neue Vorschau."""
        del datensatz_id
        if not any(
            wert.transformationsschritt_id == bisheriger_schritt_id
            and wert.typ is Transformationsart.TABELLEN_JOIN
            for wert in plan.schritte
        ):
            raise Domaenenfehler("Der zu ersetzende Join-Schritt wurde nicht gefunden.")
        bearbeitbar = self._plan_fuer_bearbeitung(plan)
        jetzt = datetime.now(UTC)
        schritte = tuple(
            replace(neuer_schritt, reihenfolge=wert.reihenfolge)
            if wert.transformationsschritt_id == bisheriger_schritt_id
            else wert
            for wert in bearbeitbar.schritte
        )
        neuer_plan = replace(
            bearbeitbar,
            import_ids=tuple(dict.fromkeys((*bearbeitbar.import_ids, *zusaetzliche_import_ids))),
            schritte=schritte,
            geaendert_am=jetzt,
        )
        ergebnis = self.vorschau(neuer_plan)
        self._repository.plan_speichern(neuer_plan)
        return neuer_plan, ergebnis, None

    def zwischendatensatz_laden(self, datensatz_id: UUID) -> tuple[Zwischendatensatz, pd.DataFrame]:
        """Lädt CSV.GZ nach Prüfsummenprüfung und stellt technische Typen wieder her."""
        datensatz = self._repository.datensatz_laden(datensatz_id)
        if datensatz is None:
            raise Domaenenfehler("Der Zwischendatensatz wurde nicht gefunden.")
        inhalt = self._artefakte.lesen(datensatz.relativer_daten_pfad)
        if hashlib.sha256(inhalt).hexdigest() != datensatz.sha256:
            raise Domaenenfehler("Die Prüfsumme des Zwischendatensatzes stimmt nicht überein.")
        schema = json.loads(self._artefakte.lesen(datensatz.relativer_schema_pfad))
        transformation = json.loads(self._artefakte.lesen(datensatz.relativer_transformation_pfad))
        daten = pd.read_csv(BytesIO(gzip.decompress(inhalt)), keep_default_na=False, na_values=[""])
        schema_spalten = [str(spalte["name"]) for spalte in schema["spalten"]]
        if (
            len(schema_spalten) != len(set(schema_spalten))
            or schema_spalten != [str(wert) for wert in daten.columns]
            or int(schema.get("zeilenanzahl", -1)) != len(daten)
            or int(schema.get("spaltenanzahl", -1)) != len(daten.columns)
            or schema.get("sha256") != datensatz.sha256
            or schema.get("import_ids") != [str(wert) for wert in datensatz.import_ids]
        ):
            raise Importintegritaetsfehler(
                "Schema-JSON und CSV.GZ des Zwischendatensatzes sind inkonsistent."
            )
        plan_roh = transformation.get("transformationsplan", {})
        ausgangsimporte = transformation.get("ausgangsimporte", [])
        if (
            plan_roh.get("transformationsplan_id") != str(datensatz.transformationsplan_id)
            or plan_roh.get("projekt_id") != str(datensatz.projekt_id)
            or [wert.get("import_id") for wert in ausgangsimporte]
            != [str(wert) for wert in datensatz.import_ids]
        ):
            raise Importintegritaetsfehler(
                "Transformations-Lineage und Zwischendatensatz sind inkonsistent."
            )
        for spalte in schema["spalten"]:
            name, typ = spalte["name"], spalte["technischer_datentyp"]
            if typ.startswith("datetime"):
                daten[name] = pd.to_datetime(daten[name], errors="coerce")
            elif typ == "Int64":
                daten[name] = pd.to_numeric(daten[name], errors="coerce").astype("Int64")
            elif typ == "boolean":
                daten[name] = daten[name].astype("boolean")
            elif typ.startswith(("int", "float")):
                daten[name] = pd.to_numeric(daten[name], errors="coerce")
        return datensatz, daten

    def datensaetze_fuer_projekt(self, projekt_id: UUID) -> list[Zwischendatensatz]:
        """Listet gespeicherte Zwischendatensätze eines Projekts."""
        return self._repository.datensaetze_fuer_projekt(projekt_id)

    def transformationshistorie(self, plan: Transformationsplan) -> list[dict[str, object]]:
        """Liefert die aktuelle In-Memory-Historie aus Raw-Daten und vollständigem Plan."""
        historie = self.vorschau(plan).historie
        schritte = {wert.reihenfolge: wert for wert in plan.schritte}
        zeilen: list[dict[str, object]] = []
        for wirkung in historie:
            nummer = wirkung.schritt
            schritt = schritte.get(nummer)
            zeilen.append(
                {
                    "reihenfolge": nummer,
                    "transformationsart": (
                        TRANSFORMATIONSART_BEZEICHNUNGEN.get(schritt.typ, schritt.typ.value)
                        if schritt is not None
                        else wirkung.aktion
                    ),
                    "betroffene_spalte_oder_bedingung": wirkung.aktion,
                    "eingabedatensatz": "Raw + bisheriger Transformationsplan",
                    "erzeugter_zwischendatensatz": "Vorschau (nicht persistiert)",
                    "zeilen_vorher": wirkung.zeilen_vorher,
                    "zeilen_nachher": wirkung.zeilen_nachher,
                    "status": "Vorschau erfolgreich",
                }
            )
        return zeilen
