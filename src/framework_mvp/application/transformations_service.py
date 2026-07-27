# pyright: reportAttributeAccessIssue=false
"""Planverwaltung, Vorschau und Erzeugung reproduzierbarer Zwischendatensätze."""

import gzip
import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from uuid import UUID

import pandas as pd

from framework_mvp.application.datenimport_service import (
    DatenimportService,
    Profilierungsergebnis,
)
from framework_mvp.application.importvorgang_service import ImportvorgangService
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
    Importvorgang,
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

TRANSFORMATIONS_ARTEFAKT_VERSION = 1


class TransformationsService:
    """Orchestriert unveränderliche Pläne, Vorschauen und Interim-Artefakte."""

    def __init__(
        self,
        repository: SQLiteETLRepository,
        import_service: ImportvorgangService,
        datenimport_service: DatenimportService,
        artefakte: ImportartefaktSpeicher,
    ) -> None:
        self._repository = repository
        self._import_service = import_service
        self._datenimport_service = datenimport_service
        self._artefakte = artefakte

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

    def plan_laden(self, plan_id: UUID) -> Transformationsplan | None:
        """Lädt einen persistierten Transformationsplan."""
        return self._repository.plan_laden(plan_id)

    def import_dataframe_laden(self, import_id: UUID) -> pd.DataFrame:
        """Rekonstruiert die importierte Tabelle aus Raw-Datei und Importparametern."""
        importvorgang, inhalt = self._import_service.originaldatei_laden(import_id)
        return self._datenimport_service.vorschau_erstellen(
            inhalt, importvorgang.importparameter
        ).vollstaendige_tabelle

    def importe_fuer_projekt(self, projekt_id: UUID) -> list[Importvorgang]:
        """Listet die bestätigten Importquellen für Transformation und Join."""
        return self._import_service.importe_fuer_projekt(projekt_id)

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

    def vorschau(self, plan: Transformationsplan) -> Transformationsergebnis:
        """Wendet alle Schritte streng geordnet neu auf unveränderte Raw-Daten an."""
        daten = self.import_dataframe_laden(plan.import_ids[0])
        historie: list[Transformationshistorie] = []
        warnungen: list[str] = []
        for schritt in sorted(plan.schritte, key=lambda wert: wert.reihenfolge):
            if not schritt.aktiviert:
                continue
            if schritt.typ.value != "tabellen_join":
                einzelplan = replace(plan, schritte=(replace(schritt, reihenfolge=1),))
                ergebnis = fuehre_transformationsplan_aus(daten, einzelplan)
                daten = ergebnis.daten
                historie.extend(
                    replace(wert, schritt=schritt.reihenfolge) for wert in ergebnis.historie
                )
                warnungen.extend(ergebnis.warnungen)
                continue
            parameter = schritt.parameter
            rechte_import_id = UUID(str(parameter["rechte_import_id"]))
            rechte_daten = self.import_dataframe_laden(rechte_import_id)
            suffixe_roh = parameter.get("suffixe", ["_links", "_rechts"])
            suffixe = (str(suffixe_roh[0]), str(suffixe_roh[1]))
            zeilen_vorher, spalten_vorher = daten.shape
            daten, pruefung = fuehre_join_aus(
                daten,
                rechte_daten,
                linke_schluessel=tuple(parameter["linke_schluessel"]),
                rechte_schluessel=tuple(parameter["rechte_schluessel"]),
                join_art=str(parameter["join_art"]),
                suffixe=suffixe,
                nm_bestaetigt=bool(parameter.get("nm_bestaetigt", False)),
            )
            historie.append(
                Transformationshistorie(
                    schritt.reihenfolge,
                    schritt.beschreibung,
                    schritt.betroffene_spalten,
                    zeilen_vorher,
                    len(daten),
                    spalten_vorher,
                    len(daten.columns),
                    f"Kardinalität {pruefung.kardinalitaet}; {len(daten)} Ergebniszeilen",
                )
            )
            warnungen.extend(pruefung.warnungen)
        return Transformationsergebnis(
            daten,
            daten.head(200).copy(deep=True),
            tuple(historie),
            tuple(warnungen),
        )

    def zwischendatensatz_erzeugen(
        self, plan: Transformationsplan, ergebnis: Transformationsergebnis, datensatz_id: UUID
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
        csv_text = ergebnis.daten.to_csv(
            index=False, date_format="%Y-%m-%dT%H:%M:%S.%f%z", na_rep=""
        )
        csv_bytes = gzip.compress(csv_text.encode("utf-8"), mtime=0)
        pruefsumme = hashlib.sha256(csv_bytes).hexdigest()
        basis = PurePosixPath("projects") / str(plan.projekt_id) / "interim"
        daten_pfad = (basis / f"{datensatz_id}.csv.gz").as_posix()
        schema_pfad = (basis / f"{datensatz_id}.schema.json").as_posix()
        transformation_pfad = (basis / f"{datensatz_id}.transformation.json").as_posix()
        schema = {
            "artefakt_version": 1,
            "spalten": [
                {"name": str(name), "technischer_datentyp": str(ergebnis.daten[name].dtype)}
                for name in ergebnis.daten.columns
            ],
            "urspruengliche_quellspalten": [str(name) for name in ergebnis.daten.columns],
            "datumsformat": "ISO-8601",
            "fehlwertdarstellung": "leeres CSV-Feld",
            "zeilenanzahl": len(ergebnis.daten),
            "spaltenanzahl": len(ergebnis.daten.columns),
            "sha256": pruefsumme,
            "import_ids": [str(wert) for wert in plan.import_ids],
            "erstellt_am": jetzt.isoformat(),
        }
        transformation = {
            "artefakt_version": TRANSFORMATIONS_ARTEFAKT_VERSION,
            "software_schema_version": 4,
            "ausgangsprofil_version": self.ausgangsprofil_laden(plan.import_ids[0]).profil_version,
            "ausgangsimport_id": str(plan.import_ids[0]),
            "relevante_auffaelligkeiten": [
                asdict(wert)
                for wert in ermittle_auffaelligkeiten(
                    self.ausgangsprofil_laden(plan.import_ids[0]).gesamtprofil,
                    self.import_dataframe_laden(plan.import_ids[0]),
                )
                if wert.anzahl > 0
            ],
            "transformationsplan": asdict(plan),
            "ergebniskennzahlen": {
                "zeilen": len(ergebnis.daten),
                "spalten": len(ergebnis.daten.columns),
            },
            "warnungen": list(ergebnis.warnungen),
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
            return datensatz
        except Exception:
            for artefakt in reversed(erzeugt):
                self._artefakte.neu_erstelltes_artefakt_entfernen(artefakt)
            raise

    def zwischendatensatz_laden(self, datensatz_id: UUID) -> tuple[Zwischendatensatz, pd.DataFrame]:
        """Lädt CSV.GZ nach Prüfsummenprüfung und stellt technische Typen wieder her."""
        datensatz = self._repository.datensatz_laden(datensatz_id)
        if datensatz is None:
            raise Domaenenfehler("Der Zwischendatensatz wurde nicht gefunden.")
        inhalt = self._artefakte.lesen(datensatz.relativer_daten_pfad)
        if hashlib.sha256(inhalt).hexdigest() != datensatz.sha256:
            raise Domaenenfehler("Die Prüfsumme des Zwischendatensatzes stimmt nicht überein.")
        schema = json.loads(self._artefakte.lesen(datensatz.relativer_schema_pfad))
        daten = pd.read_csv(BytesIO(gzip.decompress(inhalt)), keep_default_na=False, na_values=[""])
        schema_spalten = [str(spalte["name"]) for spalte in schema["spalten"]]
        if (
            len(schema_spalten) != len(set(schema_spalten))
            or schema_spalten != [str(wert) for wert in daten.columns]
            or int(schema.get("zeilenanzahl", -1)) != len(daten)
            or int(schema.get("spaltenanzahl", -1)) != len(daten.columns)
        ):
            raise Importintegritaetsfehler(
                "Schema-JSON und CSV.GZ des Zwischendatensatzes sind inkonsistent."
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
