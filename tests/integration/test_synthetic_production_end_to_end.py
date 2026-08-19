"""Ende-zu-Ende-Nachweis der synthetischen Rohdaten gegen aktuelle MVP-Verträge."""

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from framework_mvp.application.datenqualitaet import pruefe_event_log, standardregeln
from framework_mvp.application.ergebnisaggregation.sollprozess import (
    erstelle_aktivitaetsmapping,
    token_replay,
    validiere_pnml_sollmodell,
)
from framework_mvp.application.ergebnisaggregation.strukturierte_ergebnisse import (
    analysiere_ressourcen,
    analysiere_warteschlangen,
    analysiere_zeitbezogene_datenauswahl,
)
from framework_mvp.application.event_log import erzeuge_event_log
from framework_mvp.application.process_mining import Pm4pyAdapter, berechne_dfg
from framework_mvp.application.transformation import (
    fuehre_join_aus,
    fuehre_transformationsplan_aus,
)
from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    Attributrolle,
    DiscoveryKonfiguration,
    ExcelImportparameter,
    MappingModus,
    Mappingstatus,
    Prozessnotation,
    Ressourcenzuordnungsmodus,
    SemantischesMapping,
    Spaltenzuordnung,
    StrukturiertesErgebnisStatus,
    Transformationsart,
    Transformationsplan,
    Transformationsschritt,
    ZusammengesetzteFallId,
)
from framework_mvp.infrastructure.dateiimport.excel_importer import (
    ermittle_tabellenblaetter,
    lese_excel,
)
from tests.Testdatagenerator import (
    KONFIGURATION,
    excel_erzeugen,
    generiere_daten,
    pnml_erzeugen,
)


def _mapping(projekt_id, datensatz_id):  # type: ignore[no-untyped-def]
    jetzt = datetime.now(UTC)
    return SemantischesMapping(
        mapping_id=uuid4(),
        projekt_id=projekt_id,
        zwischendatensatz_id=datensatz_id,
        mapping_modus=MappingModus.EREIGNISORIENTIERT,
        fall_id=ZusammengesetzteFallId(("Produktionsauftrag",)),
        aktivitaetsspalte="Vorgang",
        zeitstempelspalte="Buchungszeitpunkt",
        startzeitstempelspalte="Ist_Start",
        endzeitstempelspalte="Ist_Ende",
        lifecycle_spalte="",
        ressourcen_spalte="Ressourcenbezeichnung",
        spaltenzuordnungen=tuple(
            Spaltenzuordnung(name, Attributrolle.EREIGNISATTRIBUT)
            for name in (
                "Quellereignis_ID",
                "Soll_Start",
                "Soll_Ende",
                "Zwischenlagerplatz",
                "Auftragsmenge",
                "Gutmenge",
                "Ausschussmenge",
                "Kosten_EUR",
                "Prozessvariante",
            )
        ),
        zeitstempelzuordnungen=(),
        validierung=None,
        erstellt_am=jetzt,
        geaendert_am=jetzt,
        status=Mappingstatus.VALIDIERT,
        aktivitaetsdefinition=Aktivitaetsdefinition(
            Aktivitaetsbildungsart.VORHANDENE_SPALTE, ("Vorgang",)
        ),
        konfigurationsversion=3,
    )


def test_import_join_mapping_discovery_ressourcen_zeiten_und_conformance(
    tmp_path: Path,
) -> None:
    """Durchläuft Rohimport bis Replay einschließlich kontrollierter Abweichungen."""
    konfiguration = replace(
        KONFIGURATION,
        anzahl_faelle=80,
        fehlwerte_prozent=0,
        platzhalter_prozent=0,
        ausreisser_prozent=0,
        duplikate_prozent=0,
        unbekannte_ressourcen_prozent=0,
        nichtkonforme_faelle_prozent=10,
    )
    erzeugt = generiere_daten(konfiguration)
    excel_pfad = excel_erzeugen(konfiguration, erzeugt, tmp_path / "Testdatensatz_Produktion.xlsx")
    pnml_pfad = tmp_path / "Sollprozess_Produktion.pnml"
    pnml_erzeugen(pnml_pfad)

    inhalt = excel_pfad.read_bytes()
    blaetter = ermittle_tabellenblaetter(inhalt)
    assert [wert.name for wert in blaetter][:2] == [
        "Ereignisdaten",
        "Ressourcenstamm",
    ]
    ereignisse = lese_excel(inhalt, ExcelImportparameter("Ereignisdaten"))
    ressourcen = lese_excel(inhalt, ExcelImportparameter("Ressourcenstamm"))
    assert "Ressourcenbezeichnung" not in ereignisse

    verbunden, join_pruefung = fuehre_join_aus(
        ereignisse,
        ressourcen,
        join_art="LEFT",
        linke_schluessel=("Ressourcen_ID",),
        rechte_schluessel=("Ressourcen_ID",),
        nm_bestaetigt=True,
    )
    assert join_pruefung.kardinalitaet == "n:1"
    assert join_pruefung.nicht_zuordenbar_links == 0
    assert len(verbunden) == len(ereignisse)
    assert bool(verbunden["Ressourcenbezeichnung"].notna().all())

    projekt_id, import_id, datensatz_id = uuid4(), uuid4(), uuid4()
    schritt = Transformationsschritt.neu(
        typ=Transformationsart.DATENTYP_KONVERTIEREN,
        betroffene_spalten=("Produktionsauftrag",),
        parameter={"zieltyp": "Text", "fehlerverhalten": "Vorgang abbrechen"},
        reihenfolge=1,
        beschreibung="Numerische Produktionsaufträge kontrolliert in Text überführen",
    )
    plan = replace(Transformationsplan.neu(projekt_id, (import_id,)), schritte=(schritt,))
    transformiert = fuehre_transformationsplan_aus(verbunden, plan).daten
    assert str(transformiert["Produktionsauftrag"].dtype) == "string"

    event_log_ergebnis = erzeuge_event_log(
        transformiert, _mapping(projekt_id, datensatz_id), datensatz_id
    )
    event_log = event_log_ergebnis.ereignisse
    assert event_log_ergebnis.fallanzahl == konfiguration.anzahl_faelle
    assert event_log_ergebnis.aktivitaetsanzahl == 20
    assert {
        "case_id",
        "activity",
        "timestamp",
        "resource",
        "start_timestamp",
        "end_timestamp",
        "Soll_Start",
        "Soll_Ende",
    } <= set(event_log)

    qualitaet = pruefe_event_log(event_log, standardregeln())
    assert qualitaet.ereignisanzahl == len(event_log)
    assert qualitaet.fallanzahl == konfiguration.anzahl_faelle
    assert not {
        "fehlende_fall_id",
        "fehlende_aktivitaet",
        "fehlender_zeitstempel",
        "start_nach_ende",
    } & {wert.regel_id for wert in qualitaet.befunde}

    dfg = berechne_dfg(event_log)
    assert len(dfg.aktivitaeten) == 20
    discovery = Pm4pyAdapter().entdecken(
        event_log, DiscoveryKonfiguration(0.05, Prozessnotation.PROZESSBAUM)
    )
    assert discovery.ergebnisse.prozessmodell

    ressourcenanalyse = analysiere_ressourcen(event_log)
    assert ressourcenanalyse.modus is Ressourcenzuordnungsmodus.AUTOMATISCH
    assert len(ressourcenanalyse.zuordnungen) == 20
    warteschlangen = analysiere_warteschlangen(event_log)
    assert warteschlangen.status is StrukturiertesErgebnisStatus.ABLEITBAR
    assert warteschlangen.uebergaenge
    zeitanalyse = analysiere_zeitbezogene_datenauswahl(transformiert, event_log)
    assert zeitanalyse.status is StrukturiertesErgebnisStatus.ABLEITBAR
    assert zeitanalyse.bearbeitungszeiten

    sollmodell = validiere_pnml_sollmodell(
        projekt_id=projekt_id,
        dateiname=pnml_pfad.name,
        originalbytes=pnml_pfad.read_bytes(),
        bezeichnung="Synthetischer Sollprozess Produktion",
        fachliche_grundlage="Statischer Demonstrationsprozess",
        modellversion="1.0",
        person="Synthetische Testfreigabe",
        freigabedatum=date(2026, 8, 19),
        menschlich_bestaetigt=True,
        markierungsableitung_bestaetigt=False,
    )
    aktivitaetsmapping = erstelle_aktivitaetsmapping(
        projekt_id=projekt_id,
        sollmodell_id=sollmodell.metadaten.sollmodell_id,
        event_aktivitaeten=event_log["activity"].astype("string").unique(),
        modell_transitionen=sollmodell.sichtbare_transitionen,
        manuelle_zuordnungen={},
        menschlich_bestaetigt=True,
    )
    replay = token_replay(
        event_log=event_log,
        sollmodell=sollmodell,
        mapping=aktivitaetsmapping,
    )
    nichtkonforme = set(erzeugt.nichtkonforme_faelle)
    diagnosen = {int(wert.fall_id): wert.konform for wert in replay.fallbezogene_diagnosen}
    assert all(not diagnosen[fall_id] for fall_id in nichtkonforme)
    assert all(konform for fall_id, konform in diagnosen.items() if fall_id not in nichtkonforme)
    assert replay.abweichende_faelle == len(nichtkonforme)
    assert replay.konforme_faelle == konfiguration.anzahl_faelle - len(nichtkonforme)
