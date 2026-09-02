"""Vollständiges, reproduzierbares Produktions-Demoprojekt über die Fachservices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from framework_mvp.application.ergebnisaggregation.sollprozess import (
    erstelle_aktivitaetsmapping,
    validiere_pnml_sollmodell,
)
from framework_mvp.application.fortschritt_service import FACHLICHE_UNTERSCHRITTE
from framework_mvp.application.mandanten_projekt_service import (
    AutorisierterLoeschService,
    MandantenProjektService,
)
from framework_mvp.application.modellableitung import MODELLBESTANDTEILE
from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    Attributrolle,
    BehandlungOffenerEintrag,
    BusyRatioKonfiguration,
    Datenartefakt,
    DiscoveryKonfiguration,
    Erzeugnisstrukturtyp,
    ExcelImportparameter,
    FachlicheBestandteilentscheidung,
    FachlicheEntscheidung,
    FachlicheEntscheidungsart,
    Gesamtvalidierungsstatus,
    GestaltDerGueter,
    KpiKonfiguration,
    LogistischeZielgroesse,
    MappingModus,
    Mappingstatus,
    Mappingtabelle,
    Materialflusskontinuitaet,
    Offenheitsentscheidung,
    Offenheitskategorie,
    OperandZuordnung,
    PerformanceZeitvergleichKonfiguration,
    Produktionsklassifikation,
    Projekt,
    Projektstatus,
    Prozessnotation,
    QualityGateStatus,
    Quellenart,
    Quellsystemtyp,
    SemantischesMapping,
    Spaltenzuordnung,
    Systemklassifikation,
    Systemtyp,
    Transformationsart,
    Transformationsplan,
    Transformationsschritt,
    Untersuchungsauftrag,
    Vorkommensregel,
    ZusammengesetzteFallId,
)
from framework_mvp.domain.models.zugriff import Zugriffskontext
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher


@dataclass(frozen=True, slots=True)
class DemoprojektErgebnis:
    projekt: Projekt
    report_html: bytes
    report_pdf: bytes


class DemoProjektService:
    """Orchestriert einmalig die regulären Algorithmen 1 bis 10."""

    PROJEKTNAME = "Demoprojekt Produktion – vollständiger Framework-Durchlauf"

    def __init__(
        self,
        *,
        projekte: MandantenProjektService,
        loeschen: AutorisierterLoeschService,
        datenquellen: Any,
        datenimport: Any,
        importvorgaenge: Any,
        transformationen: Any,
        mappingtabellen: Any,
        event_log_konfiguration: Any,
        event_logs: Any,
        datenqualitaet: Any,
        process_mining: Any,
        aggregationen: Any,
        modellableitungen: Any,
        modellvalidierungen: Any,
        modellausgabe: Any,
        fortschritt: Any,
        artefakte: ImportartefaktSpeicher,
        produktionsdaten: Path,
        sollprozess: Path,
    ) -> None:
        self._projekte = projekte
        self._loeschen = loeschen
        self._datenquellen = datenquellen
        self._datenimport = datenimport
        self._importvorgaenge = importvorgaenge
        self._transformationen = transformationen
        self._mappingtabellen = mappingtabellen
        self._event_log_konfiguration = event_log_konfiguration
        self._event_logs = event_logs
        self._datenqualitaet = datenqualitaet
        self._process_mining = process_mining
        self._aggregationen = aggregationen
        self._modellableitungen = modellableitungen
        self._modellvalidierungen = modellvalidierungen
        self._modellausgabe = modellausgabe
        self._fortschritt = fortschritt
        self._artefakte = artefakte
        self._produktionsdaten = produktionsdaten
        self._sollprozess = sollprozess

    def erstellen(self, kontext: Zugriffskontext) -> DemoprojektErgebnis:
        """Erzeugt ein isoliertes Vollprojekt; Teilstände werden kompensiert."""
        if kontext.gast_geheimnis is None:
            raise ValueError("Das öffentliche Demoprojekt benötigt einen Gastkontext.")
        if not self._produktionsdaten.is_file() or not self._sollprozess.is_file():
            raise FileNotFoundError("Die versionierten Produktions-Demodaten fehlen.")
        vorhandene = [
            projekt
            for projekt in self._projekte.projekte_auflisten(kontext)
            if projekt.bezeichnung == self.PROJEKTNAME
        ]
        if vorhandene:
            projekt = vorhandene[0]
            report_basis = f"projects/{projekt.projekt_id}/reports"
            try:
                html = self._artefakte.lesen(f"{report_basis}/demoprojekt-modell.html")
                pdf = self._artefakte.lesen(f"{report_basis}/demoprojekt-modell.pdf")
            except Exception:
                self._loeschen.projekt_loeschen(kontext, projekt.projekt_id)
            else:
                return DemoprojektErgebnis(projekt, html, pdf)

        projekt = self._projekt_anlegen(kontext)
        try:
            ergebnis = self._fachkette_erzeugen(kontext, projekt)
        except Exception:
            self._loeschen.projekt_loeschen(kontext, projekt.projekt_id)
            raise
        return ergebnis

    def _projekt_anlegen(self, kontext: Zugriffskontext) -> Projekt:
        auftrag = Untersuchungsauftrag(
            problemstellung=(
                "Durchlaufzeiten, Termintreue, Qualität und Ressourcennutzung einer "
                "synthetischen variantenreichen Produktion sollen transparent bewertet werden."
            ),
            untersuchungszweck="Produktionsprozess datenbasiert analysieren und modellieren",
            untersuchungszwecke=(
                "Produktionsprozess datenbasiert analysieren und modellieren",
                "Abweichungen zum freigegebenen Sollprozess nachvollziehbar bewerten",
            ),
            systemtyp=Systemtyp.PRODUKTION,
            systemgrenze="Auftragsfreigabe bis Abschluss einschließlich Arbeitsplätze und Anlagen",
            individuelles_ziel=(
                "Belastbare konzeptionelle Grundlage für Verbesserungsentscheidungen"
            ),
            logistische_zielgroessen=(
                LogistischeZielgroesse.LIEFERFAEHIGKEIT,
                LogistischeZielgroesse.LIEFERTREUE,
            ),
            ausgewaehlte_kpi_ids=("servicegrad", "liefertreue"),
            systemklassifikation=Systemklassifikation(
                bereich="Synthetische variantenreiche Auftragsfertigung",
                objekte_gueter="Produktionsaufträge und diskrete Stückgüter",
                gestalt_der_gueter=GestaltDerGueter.STUECKGUT,
                erzeugnisstrukturtyp=Erzeugnisstrukturtyp.KONVERGIEREND,
                materialflusskontinuitaet=Materialflusskontinuitaet.DISKONTINUIERLICH,
                kapazitaetsgrenzen=(
                    "Kapazitäten der Maschinen, Anlagen, Arbeitsplätze und Prüfmittel "
                    "gemäß Ressourcenstamm"
                ),
                input_beschreibung="Freigegebene Produktionsaufträge mit drei Produktvarianten",
                transformation_beschreibung=(
                    "Mehrstufige Bearbeitung, Montage, Prüfung und gegebenenfalls Nacharbeit"
                ),
                output_beschreibung="Fertiggestellte und qualitätsgeprüfte Produktionsaufträge",
                produktion=Produktionsklassifikation(
                    auftragsabwicklungsstrategie="Make-to-Order (MTO)",
                    auflagegroesse="Serienproduktion",
                    produktionsstueckzahl="mittel (101-10 000 Stück)",
                    produktvielfalt="gering (1-10 Var.)",
                    organisationstyp="Werkstattfertigung",
                    anzahl_arbeitsgaenge="mehrstufig",
                    ressourcen=(
                        "Maschinen",
                        "Anlagen",
                        "Arbeitsplätze",
                        "Werkzeuge",
                        "Informationssysteme",
                    ),
                ),
            ),
            detaillierungsgrad="Aktivitäten, Ressourcen, Aufträge, Zeit- und Qualitätsmerkmale",
            anmerkungen="Vollständig synthetische Demonstrationsdaten; keine Echtdaten.",
        )
        projekt = self._projekte.projekt_anlegen(
            kontext,
            bezeichnung=self.PROJEKTNAME,
            untersuchungsauftrag=auftrag,
        )
        return self._projekte.projekt_aktualisieren(
            kontext,
            projekt.projekt_id,
            bezeichnung=projekt.bezeichnung,
            untersuchungsauftrag=auftrag,
            status=Projektstatus.AKTIV,
            beteiligte_personen=projekt.beteiligte_personen,
        )

    def _importieren(self, projekt: Projekt, quelle: Any, blatt: str, inhalt: bytes) -> Any:
        parameter = ExcelImportparameter(blatt)
        metadaten = self._datenimport.datei_pruefen(self._produktionsdaten.name, inhalt)
        vorschau = self._datenimport.vorschau_erstellen(inhalt, parameter)
        profil = self._datenimport.profil_erstellen(vorschau.vollstaendige_tabelle).profil
        return self._importvorgaenge.import_bestaetigen(
            import_id=uuid4(),
            projekt_id=projekt.projekt_id,
            datenquellen_id=quelle.datenquellen_id,
            datei_metadaten=metadaten,
            dateiinhalt=inhalt,
            importparameter=parameter,
            tabellenbezeichnung=blatt,
            profil=profil,
        )

    def _fachkette_erzeugen(
        self, kontext: Zugriffskontext, projekt: Projekt
    ) -> DemoprojektErgebnis:
        inhalt = self._produktionsdaten.read_bytes()
        ereignisquelle = self._datenquellen.datenquelle_anlegen(
            projekt_id=projekt.projekt_id,
            bezeichnung="ERP/MES-Ereignisdaten",
            quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
            quellenart=Quellenart.EXCEL,
            konkretes_quellsystem="Synthetisches ERP/MES",
            fachliche_beschreibung="Produktionsaufträge und Arbeitsgangereignisse",
            herkunft_oder_verantwortungsbereich="Produktionsplanung und -steuerung",
            erwartete_tabellen_oder_blaetter=("Ereignisdaten",),
            bekannte_schluesselattribute=("Quellereignis_ID", "Produktionsauftrag"),
        )
        ressourcenquelle = self._datenquellen.datenquelle_anlegen(
            projekt_id=projekt.projekt_id,
            bezeichnung="Ressourcenstamm",
            quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
            quellenart=Quellenart.EXCEL,
            konkretes_quellsystem="Synthetischer Ressourcenstamm",
            fachliche_beschreibung="Arbeitsplätze, Anlagen und Informationssysteme",
            herkunft_oder_verantwortungsbereich="Produktion",
            erwartete_tabellen_oder_blaetter=("Ressourcenstamm",),
            bekannte_schluesselattribute=("Ressourcen_ID",),
        )
        ereignisimport = self._importieren(projekt, ereignisquelle, "Ereignisdaten", inhalt)
        ressourcenimport = self._importieren(projekt, ressourcenquelle, "Ressourcenstamm", inhalt)

        ressourcenplan = Transformationsplan.neu(projekt.projekt_id, (ressourcenimport.import_id,))
        ressourcen_t = self._transformationen.zwischendatensatz_erzeugen(
            ressourcenplan, self._transformationen.vorschau(ressourcenplan), uuid4()
        )
        plan = Transformationsplan.neu(
            projekt.projekt_id, (ereignisimport.import_id, ressourcenimport.import_id)
        )
        plan = self._transformationen.schritt_hinzufuegen(
            plan,
            Transformationsschritt.neu(
                typ=Transformationsart.TABELLEN_JOIN,
                betroffene_spalten=("Ressourcen_ID",),
                parameter={
                    "rechter_zwischendatensatz_id": str(ressourcen_t.zwischendatensatz_id),
                    "linke_schluessel": ["Ressourcen_ID"],
                    "rechte_schluessel": ["Ressourcen_ID"],
                    "join_art": "LEFT",
                    "suffixe": ["_ereignis", "_ressource"],
                    "nm_bestaetigt": True,
                },
                reihenfolge=1,
                beschreibung="Ereignisse n:1 mit dem Ressourcenstamm verknüpfen",
                fachliche_begruendung="Ressourcenbezeichnungen werden für die Analyse benötigt.",
            ),
        )
        plan = self._transformationen.schritt_hinzufuegen(
            plan,
            Transformationsschritt.neu(
                typ=Transformationsart.DATENTYP_KONVERTIEREN,
                betroffene_spalten=("Produktionsauftrag",),
                parameter={"zieltyp": "Text", "fehlerverhalten": "Vorgang abbrechen"},
                reihenfolge=2,
                beschreibung="Produktionsauftrag kontrolliert als Text behandeln",
                fachliche_begruendung="Die Auftragsnummer ist eine Fall-ID und keine Messzahl.",
            ),
        )
        t = self._transformationen.zwischendatensatz_erzeugen(
            plan, self._transformationen.vorschau(plan), uuid4()
        )

        mappingtabelle = Mappingtabelle.neu(projekt.projekt_id, t.zwischendatensatz_id).bestaetigen(
            kein_mapping_erforderlich=True
        )
        self._mappingtabellen.speichern(mappingtabelle)
        _, t_daten = self._transformationen.zwischendatensatz_laden(t.zwischendatensatz_id)
        jetzt = datetime.now(UTC)
        zusaetze = tuple(
            Spaltenzuordnung(name, Attributrolle.EREIGNISATTRIBUT)
            for name in (
                "Quellereignis_ID",
                "Artikelnummer",
                "Produktvariante",
                "Prozessvariante",
                "Auftragsmenge",
                "Gutmenge",
                "Ausschussmenge",
                "Liefertermin",
                "Tatsaechlicher_Fertigstellungstermin",
                "Zwischenlagerplatz",
                "Qualitaetsstatus",
                "Nacharbeitsgrund",
                "Ruestzeit_Min",
                "Kosten_EUR",
            )
        )
        konfiguration = SemantischesMapping(
            uuid4(),
            projekt.projekt_id,
            t.zwischendatensatz_id,
            MappingModus.EREIGNISORIENTIERT,
            ZusammengesetzteFallId(("Produktionsauftrag",)),
            "Vorgang",
            "Buchungszeitpunkt",
            "Ist_Start",
            "Ist_Ende",
            "",
            "Ressourcenbezeichnung",
            zusaetze,
            (),
            None,
            jetzt,
            jetzt,
            Mappingstatus.ENTWURF,
            Aktivitaetsdefinition(Aktivitaetsbildungsart.VORHANDENE_SPALTE, ("Vorgang",)),
            mappingtabelle.mapping_id,
            5,
            "Soll_Start",
            "Soll_Ende",
        )
        konfiguration, validierung = self._event_log_konfiguration.validieren(
            konfiguration, t_daten
        )
        if not validierung.validierung.gueltig:
            raise ValueError("Die Demo-Event-Log-Konfiguration ist nicht gültig.")
        self._event_log_konfiguration.speichern(konfiguration)
        event_log = self._event_logs.speichern(uuid4(), konfiguration.mapping_id)

        gate = self._datenqualitaet.quality_gate_pruefen(projekt.projekt_id, event_log.event_log_id)
        begruendungen = {
            "q_nachvollziehbar": (
                "Datenherkunft, Arbeitsblätter und Verantwortungsbereiche sind im "
                "Demoprojekt vollständig dokumentiert."
            ),
            "m_verstaendlich": (
                "Die bestätigte leere Mappingtabelle ist fachlich plausibel, weil die "
                "technischen Spaltenbezeichnungen bereits eindeutig verständlich sind."
            ),
            "e_interpretierbar": (
                "Produktionsauftrag, Vorgang und Buchungszeitpunkt sind als Fall, "
                "Aktivität und Ereigniszeit eindeutig interpretierbar."
            ),
        }
        entscheidungen = tuple(
            FachlicheEntscheidung(
                befund.kriterium_id,
                False,
                begruendungen.get(
                    befund.kriterium_id,
                    "Der fachliche Befund wurde für das synthetische Demoprojekt geprüft.",
                ),
            )
            for befund in gate.befunde
            if befund.status is QualityGateStatus.FACHLICHE_BESTAETIGUNG_ERFORDERLICH
        )
        freigabe = self._datenqualitaet.freigeben(
            uuid4(), projekt.projekt_id, event_log.event_log_id, entscheidungen
        )
        discovery_konfiguration = DiscoveryKonfiguration(0.05, Prozessnotation.BPMN)
        discovery_vorschau = self._process_mining.vorschau(
            freigabe.freigabe_id, discovery_konfiguration
        )
        analyse = self._process_mining.speichern(
            uuid4(), freigabe.freigabe_id, discovery_konfiguration, discovery_vorschau
        )

        sollmodell = validiere_pnml_sollmodell(
            projekt_id=projekt.projekt_id,
            dateiname=self._sollprozess.name,
            originalbytes=self._sollprozess.read_bytes(),
            bezeichnung="Freigegebener Sollprozess Produktion",
            fachliche_grundlage="Versioniertes synthetisches Sollmodell",
            modellversion="1.0",
            person="Demoprojekt-Service",
            freigabedatum=date.today(),
            menschlich_bestaetigt=True,
            markierungsableitung_bestaetigt=True,
        )
        aktivitaeten = tuple(sorted(t_daten["Vorgang"].astype("string").unique()))
        aktivitaetsmapping = erstelle_aktivitaetsmapping(
            projekt_id=projekt.projekt_id,
            sollmodell_id=sollmodell.metadaten.sollmodell_id,
            event_aktivitaeten=aktivitaeten,
            modell_transitionen=sollmodell.sichtbare_transitionen,
            manuelle_zuordnungen={},
            menschlich_bestaetigt=True,
        )
        kpis = (
            KpiKonfiguration(
                "servicegrad",
                (
                    OperandZuordnung(
                        "befriedigte_kundenauftragspositionen",
                        Datenartefakt.ZWISCHENDATENSATZ_T,
                        spalte="Qualitaetsstatus",
                        bedingungsoperator="gleich",
                        bedingungswert="FREIGEGEBEN",
                    ),
                    OperandZuordnung(
                        "kundenauftragspositionen",
                        Datenartefakt.ZWISCHENDATENSATZ_T,
                        spalte="Produktionsauftrag",
                    ),
                ),
                "%",
                "Produktionsereignisse",
            ),
            KpiKonfiguration(
                "liefertreue",
                (
                    OperandZuordnung(
                        "liefertreue_produktionsauftraege",
                        Datenartefakt.ZWISCHENDATENSATZ_T,
                        spalte="Qualitaetsstatus",
                        bedingungsoperator="gleich",
                        bedingungswert="FREIGEGEBEN",
                    ),
                    OperandZuordnung(
                        "produktionsauftraege",
                        Datenartefakt.ZWISCHENDATENSATZ_T,
                        spalte="Produktionsauftrag",
                    ),
                ),
                "%",
                "Produktionsereignisse",
            ),
        )
        performance = PerformanceZeitvergleichKonfiguration(
            "T",
            "Produktionsauftrag",
            "Vorgang",
            "case_id",
            "activity",
            "Soll_Ende",
            "end_timestamp",
            "Soll_Start",
            "start_timestamp",
            vorkommensregel=Vorkommensregel.ERSTES,
            fertigstellungsabweichung_aktiv=True,
            bearbeitungszeitabweichung_aktiv=True,
        )
        event_kontext = self._event_logs.kontext_laden(event_log.event_log_id)
        zeitraum_von = event_kontext.artefakt.zeitraum_von
        zeitraum_bis = event_kontext.artefakt.zeitraum_bis
        if zeitraum_von is not None and zeitraum_von.utcoffset() is None:
            zeitraum_von = zeitraum_von.replace(tzinfo=UTC)
        if zeitraum_bis is not None and zeitraum_bis.utcoffset() is None:
            zeitraum_bis = zeitraum_bis.replace(tzinfo=UTC)
        busy = BusyRatioKonfiguration(
            "resource",
            "start_timestamp",
            "end_timestamp",
            zeitraum_von,
            zeitraum_bis,
        )
        aggregationsvorschau = self._aggregationen.vorschau(
            projekt_id=projekt.projekt_id,
            freigabe_id=freigabe.freigabe_id,
            analyse_id=analyse.analyse_id,
            kpi_konfigurationen=kpis,
            sollmodell=sollmodell,
            aktivitaetsmapping=aktivitaetsmapping,
            conformance_ausfuehren=True,
            performance_zeitvergleich_konfiguration=performance,
            performance_zeitvergleich_ausfuehren=True,
            busy_ratio_konfiguration=busy,
            busy_ratio_ausfuehren=True,
        )
        aggregation = self._aggregationen.speichern(
            uuid4(), aggregationsvorschau, menschlich_bestaetigt=True
        )

        entscheidungszeitpunkt = datetime.now(UTC)
        bestandteilentscheidungen = tuple(
            FachlicheBestandteilentscheidung(
                definition.bestandteil_id,
                FachlicheEntscheidungsart.UEBERNEHMEN,
                "Der Vorschlag wird für das fachlich geprüfte Demomodell übernommen.",
                entscheidungszeitpunkt,
            )
            for definition in MODELLBESTANDTEILE
        )
        ableitungsvorschau = self._modellableitungen.vorschau(
            projekt_id=projekt.projekt_id,
            aggregations_id=aggregation.aggregations_id,
            modellableitungs_id=uuid4(),
            k_id=uuid4(),
            o_id=uuid4(),
            entscheidungen=bestandteilentscheidungen,
        )
        ableitung = self._modellableitungen.speichern(
            ableitungsvorschau, menschlich_bestaetigt=True
        )
        _, _, o = self._modellableitungen.laden(ableitung.modellableitungs_id)
        behandlungen = tuple(self._behandlung(wert) for wert in o["offene_eintraege"])
        arbeitsfassung = self._modellvalidierungen.arbeitsfassung_erstellen(
            projekt_id=projekt.projekt_id,
            modellableitungs_id=ableitung.modellableitungs_id,
            erwartete_k_id=ableitung.k_id,
            erwartete_o_id=ableitung.o_id,
            behandlungen=behandlungen,
            gesamtvalidierungsstatus=Gesamtvalidierungsstatus.FACHLICH_VALIDIERT,
            validierungsvermerk=(
                "Alle offenen Punkte des synthetischen Demoprojekts wurden fachlich behandelt."
            ),
            gesamtpruefung_bestaetigt=True,
        )
        validierung = self._modellvalidierungen.speichern(
            arbeitsfassung, validierungslauf_id=uuid4(), k_stern_id=uuid4()
        )
        ausgabe = self._modellausgabe.erzeugen(
            validierungslauf_id=validierung.validierungslauf_id,
            projekt_id=projekt.projekt_id,
            k_stern_id=validierung.k_stern_id,
            html=True,
            pdf=True,
        )
        if ausgabe.report_html is None or ausgabe.report_pdf is None:
            raise ValueError("Die Demoausgabe wurde nicht vollständig erzeugt.")
        report_basis = f"projects/{projekt.projekt_id}/reports"
        self._artefakte.artefakt_speichern(
            f"{report_basis}/demoprojekt-modell.html", ausgabe.report_html
        )
        self._artefakte.artefakt_speichern(
            f"{report_basis}/demoprojekt-modell.pdf", ausgabe.report_pdf
        )
        self._fortschritt.aktualisieren(
            kontext,
            projekt.projekt_id,
            schritt=10,
            unterschritt=FACHLICHE_UNTERSCHRITTE[10][-1],
            status="abgeschlossen",
        )
        return DemoprojektErgebnis(projekt, ausgabe.report_html, ausgabe.report_pdf)

    @staticmethod
    def _behandlung(eintrag: dict[str, Any]) -> BehandlungOffenerEintrag:
        kategorie = Offenheitskategorie(eintrag["kategorie"])
        ist_unsicher = kategorie is Offenheitskategorie.FACHLICH_UNSICHER
        return BehandlungOffenerEintrag(
            eintrag["offener_eintrag_id"],
            next(
                definition.bestandteil_id
                for definition in MODELLBESTANDTEILE
                if definition.bestandteil_id.value == eintrag["bestandteil_id"]
            ),
            kategorie,
            eintrag["begruendung"],
            (
                Offenheitsentscheidung.BESTAETIGT
                if ist_unsicher
                else Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST
            ),
            "" if ist_unsicher else "Für das Demomodell fachlich plausibilisiert und ergänzt.",
            "Im Rahmen des synthetischen Demonstrationsfalls bewusst entschieden.",
        )
