"""Fachliche Unit-Tests der festen Zuordnung aus Tabelle 3.15."""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pm4py
import pytest
from pm4py.objects.petri_net.obj import Marking, PetriNet
from pm4py.objects.petri_net.utils import petri_utils
from pm4py.objects.process_tree.obj import Operator, ProcessTree

from framework_mvp.application.ergebnisaggregation.sollprozess import (
    erzeuge_lineares_sollmodell,
)
from framework_mvp.application.ergebnisaggregation.strukturierte_ergebnisse import (
    analysiere_ressourcen,
    analysiere_warteschlangen,
    analysiere_zeitbezogene_datenauswahl,
)
from framework_mvp.application.modellableitung import (
    MAPPINGVERSION,
    MODELLBESTANDTEILE,
    extrahiere_sichtbare_aktivitaeten,
    leite_modellbestandteile_ab,
    validiere_quellenzuordnung,
    wende_fachliche_entscheidungen_an,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Datenquelle,
    Eingangsartefakt,
    FachlicheBestandteilentscheidung,
    FachlicheEntscheidungsart,
    Intralogistikklassifikation,
    Kennzeichnungsherkunft,
    LogistischeZielgroesse,
    ModellbestandteilId,
    Offenheitskategorie,
    Produktionsklassifikation,
    Projekt,
    Projektstatus,
    Prozessnotation,
    Quellenart,
    Quellsystemtyp,
    Systemklassifikation,
    Systemtyp,
    Untersuchungsauftrag,
)


def _prozessbaum() -> ProcessTree:
    a = ProcessTree(label="A")
    b = ProcessTree(label="B")
    wurzel = ProcessTree(operator=Operator.SEQUENCE, children=[a, b])
    a.parent = wurzel
    b.parent = wurzel
    return wurzel


def _modellbytes(tmp_path: Path, notation: Prozessnotation) -> bytes:
    baum = _prozessbaum()
    pfad = tmp_path / f"modell.{notation.dateiendung}"
    if notation is Prozessnotation.PROZESSBAUM:
        pm4py.write_ptml(baum, str(pfad))
    elif notation is Prozessnotation.BPMN:
        pm4py.write_bpmn(pm4py.convert_to_bpmn(baum), str(pfad))
    else:
        netz, start, ende = pm4py.convert_to_petri_net(baum)
        stille = PetriNet.Transition("tau", None)
        netz.transitions.add(stille)
        lose_stelle = PetriNet.Place("lose")
        netz.places.add(lose_stelle)
        petri_utils.add_arc_from_to(lose_stelle, stille, netz)
        pm4py.write_pnml(netz, start, ende, str(pfad))
    return pfad.read_bytes()


@pytest.mark.parametrize("notation", tuple(Prozessnotation))
def test_aktivitaeten_werden_aus_drei_notationen_unveraendert_gelesen(
    tmp_path: Path, notation: Prozessnotation
) -> None:
    assert extrahiere_sichtbare_aktivitaeten(_modellbytes(tmp_path, notation), notation) == (
        "A",
        "B",
    )


def test_unsichtbare_petrinetztransition_ist_keine_fachliche_aktivitaet(tmp_path: Path) -> None:
    netz = PetriNet("mit-tau")
    start, ende = PetriNet.Place("start"), PetriNet.Place("ende")
    sichtbar, unsichtbar = PetriNet.Transition("A", "A"), PetriNet.Transition("tau", None)
    netz.places.update({start, ende})
    netz.transitions.update({sichtbar, unsichtbar})
    petri_utils.add_arc_from_to(start, unsichtbar, netz)
    petri_utils.add_arc_from_to(unsichtbar, start, netz)
    petri_utils.add_arc_from_to(start, sichtbar, netz)
    petri_utils.add_arc_from_to(sichtbar, ende, netz)
    pfad = tmp_path / "tau.pnml"
    pm4py.write_pnml(netz, Marking({start: 1}), Marking({ende: 1}), str(pfad))

    assert extrahiere_sichtbare_aktivitaeten(pfad.read_bytes(), Prozessnotation.PETRINETZ) == ("A",)


@dataclass(frozen=True)
class _Datensatz:
    zwischendatensatz_id: object
    zeilenanzahl: int
    spaltenanzahl: int
    relativer_daten_pfad: str
    relativer_schema_pfad: str


def _basis(tmp_path: Path):  # type: ignore[no-untyped-def]
    projekt_id = uuid4()
    auftrag = Untersuchungsauftrag(
        "Unveränderte Problemstellung",
        "Leistung bewerten",
        Systemtyp.KOMBINIERT,
        "Werk A",
        logistische_zielgroessen=(LogistischeZielgroesse.WARTEZEIT,),
        ausgewaehlte_kpi_ids=("tatsaechliche_wartezeit_aqt", "servicegrad"),
        systemklassifikation=Systemklassifikation(
            objekte_gueter="Produktionsauftrag",
            produktion=Produktionsklassifikation(ressourcen=("Maschinen",)),
            intralogistik=Intralogistikklassifikation(ressourcen=("Personal",)),
        ),
        untersuchungszwecke=("Leistung bewerten",),
    )
    projekt = Projekt(
        projekt_id,
        "Ableitung",
        (),
        Projektstatus.AKTIV,
        datetime.now(UTC),
        datetime.now(UTC),
        auftrag,
    )
    quelle = Datenquelle.neu(
        projekt_id=projekt_id,
        bezeichnung="ERP Export",
        quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
        quellenart=Quellenart.CSV,
    )
    modell = erzeuge_lineares_sollmodell(
        projekt_id=projekt_id,
        aktivitaeten=("A", "B"),
        bezeichnung="Technisches Testmodell",
        fachliche_grundlage="Test",
        modellversion="1",
        person="Test",
        freigabedatum=date.today(),
        menschlich_bestaetigt=True,
    ).original_pnml
    referenzen = {
        quelle: {"id": f"id-{quelle.value}", "sha256": "a" * 64} for quelle in Eingangsartefakt
    }
    zwischendaten = pd.DataFrame({"auftrag": [1, 2], "wert": [3.0, 4.0]})
    event_log = pd.DataFrame(
        {
            "case_id": ["1", "1"],
            "activity": ["A", "B"],
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
            "resource": ["M1", "M1"],
        }
    )
    strukturiert = {
        "ergebnisversion": 1,
        "ressourcen": _json_dict(analysiere_ressourcen(event_log)),
        "warteschlangen_und_wartezeiten": _json_dict(analysiere_warteschlangen(event_log)),
        "zeitbezogene_datenauswahl": _json_dict(
            analysiere_zeitbezogene_datenauswahl(zwischendaten, event_log)
        ),
    }
    return SimpleNamespace(
        projekt=projekt,
        datenquellen=(quelle,),
        profilreferenzen=(
            {"import_id": str(uuid4()), "profil_sha256": "b" * 64, "gesamtprofil": {}},
        ),
        zwischendatensatz=_Datensatz(uuid4(), 2, 2, "t.csv.gz", "t.schema.json"),
        zwischendaten=zwischendaten,
        event_log=event_log,
        freigabe=SimpleNamespace(event_log_id=uuid4()),
        analyse=SimpleNamespace(analyse_id=uuid4(), relativer_modell_pfad="p.pnml"),
        discovery_ergebnisse={
            "schwellwert_k": 0.2,
            "miner_variante": "inductive_miner_infrequent",
            "prozessnotation": "petrinetz",
            "warnungen": [],
            "dfg_daten": {
                "startaktivitaeten": [["A", 1]],
                "endaktivitaeten": [["B", 1]],
            },
        },
        prozessmodell=modell,
        prozessnotation=Prozessnotation.PETRINETZ,
        a_g={
            "discovery_ergebnisse_a_d": {"schwellwert_k": 0.2},
            "kpi_ergebnisse": [
                {
                    "kpi_id": "tatsaechliche_wartezeit_aqt",
                    "status": "berechnet",
                    "ergebnis": 4.0,
                },
                {"kpi_id": "servicegrad", "status": "nicht_berechenbar", "ergebnis": None},
            ],
            "optionale_artefakte": {
                "prozessmodell_p_soll": {"sha256": "c" * 64},
                "conformance_ergebnisse_a_c": {"sha256": "d" * 64},
            },
            "strukturierte_ergebnisse": strukturiert,
        },
        quellreferenzen=referenzen,
    )


def _json_dict(wert):  # type: ignore[no-untyped-def]
    return json.loads(json.dumps(asdict(wert), ensure_ascii=False, default=str))


def test_sechzehn_bestandteile_und_quellenmatrix_sind_exakt_und_stabil() -> None:
    assert MAPPINGVERSION == 3
    assert [wert.bezeichnung for wert in MODELLBESTANDTEILE] == [
        "Problemstellung",
        "Zielsetzung",
        "Ausgaben",
        "Eingaben",
        "Modellumfang",
        "Modellgrenzen",
        "Detaillierungsgrad",
        "Entitäten",
        "Aktivitäten",
        "Warteschlangen",
        "Ressourcen",
        "Annahmen",
        "Vereinfachungen",
        "Datenauswahl",
        "Daten",
        "Darstellung der Vorgänge des Systems",
    ]
    assert [wert.bestandteil_id for wert in MODELLBESTANDTEILE] == list(ModellbestandteilId)
    assert {wert.bestandteil_id for wert in MODELLBESTANDTEILE if wert.teilweise_offen} == {
        ModellbestandteilId.EINGABEN,
        ModellbestandteilId.DETAILLIERUNGSGRAD,
        ModellbestandteilId.WARTESCHLANGEN,
        ModellbestandteilId.RESSOURCEN,
        ModellbestandteilId.ANNAHMEN,
        ModellbestandteilId.VEREINFACHUNGEN,
    }


def test_quellenmatrix_akzeptiert_und_verwirft_jede_kombination_exakt() -> None:
    for definition in MODELLBESTANDTEILE:
        for quelle in Eingangsartefakt:
            if quelle in definition.zulaessige_quellen:
                validiere_quellenzuordnung(definition.bestandteil_id, quelle)
            else:
                with pytest.raises(Domaenenfehler, match="Tabelle 3.15"):
                    validiere_quellenzuordnung(definition.bestandteil_id, quelle)
    assert {
        wert.bestandteil_id: tuple(quelle.value for quelle in wert.zulaessige_quellen)
        for wert in MODELLBESTANDTEILE
    } == {
        ModellbestandteilId.PROBLEMSTELLUNG: ("U",),
        ModellbestandteilId.ZIELSETZUNG: ("U",),
        ModellbestandteilId.AUSGABEN: ("U", "A_G"),
        ModellbestandteilId.EINGABEN: ("U",),
        ModellbestandteilId.MODELLUMFANG: ("U", "S", "P", "A_G"),
        ModellbestandteilId.MODELLGRENZEN: ("U",),
        ModellbestandteilId.DETAILLIERUNGSGRAD: ("U", "S", "P", "A_G"),
        ModellbestandteilId.ENTITAETEN: ("S", "E*", "A_G"),
        ModellbestandteilId.AKTIVITAETEN: ("P", "A_G"),
        ModellbestandteilId.WARTESCHLANGEN: ("A_G",),
        ModellbestandteilId.RESSOURCEN: ("S", "A_G"),
        ModellbestandteilId.ANNAHMEN: ("U", "S", "P", "A_G"),
        ModellbestandteilId.VEREINFACHUNGEN: ("P", "A_G"),
        ModellbestandteilId.DATENAUSWAHL: ("Q", "R", "T", "E*", "A_G"),
        ModellbestandteilId.DATEN: ("Q", "R", "T", "E*", "A_G"),
        ModellbestandteilId.DARSTELLUNG_DER_VORGAENGE: ("P",),
    }


def test_ableitung_bleibt_belegt_offen_und_schliesst_p_soll_aus(tmp_path: Path) -> None:
    basis = _basis(tmp_path)
    bestandteile, offen = leite_modellbestandteile_ab(basis)
    definitionen = {wert.bestandteil_id: wert for wert in MODELLBESTANDTEILE}

    assert len(bestandteile) == 16
    assert [wert.bestandteil_id for wert in bestandteile] == list(ModellbestandteilId)
    for bestandteil in bestandteile:
        assert set(bestandteil.verwendete_quellen) <= set(
            definitionen[bestandteil.bestandteil_id].zulaessige_quellen
        )
    problem = bestandteile[0]
    assert [wert.wert for wert in problem.informationen] == ["Unveränderte Problemstellung"]
    ausgaben = bestandteile[2]
    kpi_ergebnis = next(
        wert
        for wert in ausgaben.informationen
        if isinstance(wert.wert, dict) and wert.wert.get("kpi_id") == "tatsaechliche_wartezeit_aqt"
    )
    assert kpi_ergebnis.wert["status"] == "berechnet"
    assert not any(
        isinstance(wert.wert, dict) and wert.wert.get("kpi_id") == "servicegrad"
        for wert in ausgaben.informationen
    )
    assert "prozessmodell_p_soll" not in repr(bestandteile)
    vereinfachungen = next(
        wert for wert in bestandteile if wert.bestandteil_id is ModellbestandteilId.VEREINFACHUNGEN
    )
    schwellwert = next(
        wert
        for wert in vereinfachungen.informationen
        if wert.strukturreferenz == "discovery_ergebnisse_a_d.schwellwert_k.auswirkung"
    )
    assert "seltenes Verhalten" in schwellwert.wert["beobachtbare_tatsache"]
    detail = next(
        wert
        for wert in bestandteile
        if wert.bestandteil_id is ModellbestandteilId.DETAILLIERUNGSGRAD
    )
    assert any("nicht den Detaillierungsgrad" in str(info.wert) for info in detail.informationen)
    assert any(wert.bestandteil_id is ModellbestandteilId.EINGABEN for wert in offen)


def test_menschliche_entscheidungen_steuern_k_und_o(tmp_path: Path) -> None:
    vorschlaege, systematisch_offen = leite_modellbestandteile_ab(_basis(tmp_path))
    jetzt = datetime.now(UTC)
    entscheidungen = tuple(
        FachlicheBestandteilentscheidung(
            wert.bestandteil_id,
            (
                FachlicheEntscheidungsart.OFFEN_UNSICHER
                if wert.bestandteil_id is ModellbestandteilId.AKTIVITAETEN
                else FachlicheEntscheidungsart.UEBERNEHMEN
            ),
            "Aktivitäten müssen fachlich geprüft werden."
            if wert.bestandteil_id is ModellbestandteilId.AKTIVITAETEN
            else "",
            jetzt,
        )
        for wert in vorschlaege
    )
    bestandteile, offen = wende_fachliche_entscheidungen_an(
        vorschlaege, systematisch_offen, entscheidungen
    )
    aktivitaeten = next(
        wert for wert in bestandteile if wert.bestandteil_id is ModellbestandteilId.AKTIVITAETEN
    )
    markierung = next(
        wert
        for wert in offen
        if wert.bestandteil_id is ModellbestandteilId.AKTIVITAETEN
        and wert.kennzeichnungsherkunft is Kennzeichnungsherkunft.MENSCHLICH_MARKIERT
    )
    assert not aktivitaeten.informationen
    assert markierung.status == "offen"
    problem = bestandteile[0]
    assert problem.informationen[0].fachliche_entscheidung is FachlicheEntscheidungsart.UEBERNEHMEN
    assert problem.informationen[0].bestaetigt_am == jetzt
    detaillierung = next(
        wert
        for wert in bestandteile
        if wert.bestandteil_id is ModellbestandteilId.DETAILLIERUNGSGRAD
    )
    assert detaillierung.informationen and detaillierung.offene_eintrag_ids
    assert detaillierung.status.value == "teilweise_offen"


def test_nicht_uebernehmen_benoetigt_begruendung() -> None:
    with pytest.raises(Domaenenfehler, match="Begründung"):
        FachlicheBestandteilentscheidung(
            ModellbestandteilId.AKTIVITAETEN,
            FachlicheEntscheidungsart.NICHT_UEBERNEHMEN,
            "",
            datetime.now(UTC),
        )


def test_nicht_uebernehmen_entfernt_vorschlag_aus_k_und_dokumentiert_o(
    tmp_path: Path,
) -> None:
    vorschlaege, systematisch_offen = leite_modellbestandteile_ab(_basis(tmp_path))
    entscheidung = FachlicheBestandteilentscheidung(
        ModellbestandteilId.PROBLEMSTELLUNG,
        FachlicheEntscheidungsart.NICHT_UEBERNEHMEN,
        "Die Problemstellung ist fachlich nicht mehr aktuell.",
        datetime.now(UTC),
    )

    bestandteile, offen = wende_fachliche_entscheidungen_an(
        vorschlaege, systematisch_offen, (entscheidung,)
    )

    problem = bestandteile[0]
    assert not problem.informationen
    menschlicher_o_eintrag = next(
        wert
        for wert in offen
        if wert.bestandteil_id is ModellbestandteilId.PROBLEMSTELLUNG
        and wert.kennzeichnungsherkunft is Kennzeichnungsherkunft.MENSCHLICH_MARKIERT
    )
    assert menschlicher_o_eintrag.fachliche_entscheidung is (
        FachlicheEntscheidungsart.NICHT_UEBERNEHMEN
    )
    assert menschlicher_o_eintrag.belegreferenzen[0]["wert"] == "Unveränderte Problemstellung"


def test_ressourcen_werden_nur_aus_strukturiertem_a_g_uebernommen(tmp_path: Path) -> None:
    basis = _basis(tmp_path)
    schritt7_log = pd.DataFrame(
        {
            "case_id": ["1"] * 6,
            "activity": ["A", "A", "A", "B", "B", "B"],
            "timestamp": pd.date_range("2026-01-01", periods=6, tz="UTC"),
            "resource": [" M1 ", "M1", "M2", "M2", "", None],
        }
    )
    basis.a_g["strukturierte_ergebnisse"]["ressourcen"] = _json_dict(
        analysiere_ressourcen(schritt7_log)
    )
    basis.event_log = schritt7_log.assign(resource="DARF_NICHT_NEU_BERECHNET_WERDEN")

    bestandteile, _ = leite_modellbestandteile_ab(basis)

    ressourcen = next(
        wert for wert in bestandteile if wert.bestandteil_id is ModellbestandteilId.RESSOURCEN
    )
    information = next(
        wert
        for wert in ressourcen.informationen
        if wert.strukturreferenz == "strukturierte_ergebnisse.ressourcen"
    )
    assert information.wert["modus"] == "automatisch"
    assert [wert["ressourcen"] for wert in information.wert["zuordnungen"]] == [
        ["M1", "M2"],
        ["M2"],
    ]
    assert information.wert["zuordnungen"][0]["automatisch_beobachtete_ressourcen"] == [
        "M1",
        "M2",
    ]
    assert "DARF_NICHT_NEU_BERECHNET_WERDEN" not in repr(information.wert)


def test_entitaet_und_ressource_bleiben_getrennt_und_attribute_erhalten(tmp_path: Path) -> None:
    basis = _basis(tmp_path)
    basis.a_g["strukturierte_ergebnisse"]["entitaetsinstanzen_und_attribute"] = {
        "entitaetstyp": "Produktionsauftrag",
        "instanzen": [{"instanz_id": "PA4711"}],
        "attribute": [{"attribut": "Priorität", "stabiler_wert": "hoch"}],
    }
    basis.a_g["strukturierte_ergebnisse"]["ressourcen"] = {
        "modus": "automatisch",
        "zuordnungen": [{"aktivitaet": "A", "ressourcen": ["M01"], "offen": False}],
        "attribute": [{"instanz_id": "M01", "attribut": "OEE", "stabiler_wert": "0.82"}],
    }

    bestandteile, _ = leite_modellbestandteile_ab(basis)

    entitaeten = next(
        wert for wert in bestandteile if wert.bestandteil_id is ModellbestandteilId.ENTITAETEN
    )
    ressourcen = next(
        wert for wert in bestandteile if wert.bestandteil_id is ModellbestandteilId.RESSOURCEN
    )
    assert "Produktionsauftrag" in repr(entitaeten)
    assert "PA4711" in repr(entitaeten)
    assert "M01" not in repr(entitaeten)
    assert "M01" in repr(ressourcen)
    assert "OEE" in repr(ressourcen)


def test_nur_explizit_bestaetigte_warteschlange_ist_uebernehmbar(tmp_path: Path) -> None:
    basis = _basis(tmp_path)
    wartedaten = basis.a_g["strukturierte_ergebnisse"]["warteschlangen_und_wartezeiten"]
    wartedaten["bestaetigte_warteschlangen"] = [
        {
            "bezeichnung": "Puffer vor B",
            "von_aktivitaet": "A",
            "zu_aktivitaet": "B",
            "herkunft": "manuell_bestaetigt",
        }
    ]

    bestandteile, offen = leite_modellbestandteile_ab(basis)

    warteschlangen = next(
        wert for wert in bestandteile if wert.bestandteil_id is ModellbestandteilId.WARTESCHLANGEN
    )
    assert "Puffer vor B" in repr(warteschlangen.informationen)
    assert "potenzielle_wartezeiten" not in repr(warteschlangen.informationen)
    assert not any(wert.bestandteil_id is ModellbestandteilId.WARTESCHLANGEN for wert in offen)


def test_potenzielle_wartezeiten_werden_aus_a_g_uebernommen_ohne_neuberechnung(
    tmp_path: Path,
) -> None:
    basis = _basis(tmp_path)
    basis.a_g["kpi_ergebnisse"] = []
    basis.event_log = pd.DataFrame(
        {
            "case_id": ["1", "1", "2", "2", "3", "3"],
            "activity": ["A", "B", "A", "B", "A", "B"],
            "timestamp": pd.to_datetime(["2026-01-01"] * 6, utc=True),
            "start_timestamp": pd.to_datetime(
                [
                    "2026-01-01 10:00",
                    "2026-01-01 10:03",
                    "2026-01-01 11:00",
                    "2026-01-01 11:05",
                    "2026-01-01 12:00",
                    "2026-01-01 12:01",
                ],
                utc=True,
            ),
            "end_timestamp": pd.to_datetime(
                [
                    "2026-01-01 10:01",
                    "2026-01-01 10:04",
                    "2026-01-01 11:01",
                    "2026-01-01 11:06",
                    "2026-01-01 12:02",
                    "2026-01-01 12:03",
                ],
                utc=True,
            ),
        }
    )
    basis.a_g["strukturierte_ergebnisse"]["warteschlangen_und_wartezeiten"] = _json_dict(
        analysiere_warteschlangen(basis.event_log)
    )
    basis.a_g["strukturierte_ergebnisse"]["zeitbezogene_datenauswahl"] = _json_dict(
        analysiere_zeitbezogene_datenauswahl(basis.zwischendaten, basis.event_log)
    )
    vorher = basis.event_log.copy(deep=True)
    basis.event_log["start_timestamp"] = basis.event_log["start_timestamp"].iloc[::-1].to_numpy()

    bestandteile, offen = leite_modellbestandteile_ab(basis)

    assert not basis.event_log.equals(vorher)
    warteschlangen = next(
        wert for wert in bestandteile if wert.bestandteil_id is ModellbestandteilId.WARTESCHLANGEN
    )
    assert not warteschlangen.informationen
    datenauswahl = next(
        wert for wert in bestandteile if wert.bestandteil_id is ModellbestandteilId.DATENAUSWAHL
    )
    hinweis = next(
        wert
        for wert in datenauswahl.informationen
        if wert.strukturreferenz == "strukturierte_ergebnisse.zeitbezogene_datenauswahl"
    )
    assert hinweis.wert["potenzielle_wartezeiten"] == [
        {
            "von_aktivitaet": "A",
            "zu_aktivitaet": "B",
            "statistik": {
                "anzahl": 2,
                "mittelwert_sekunden": 180.0,
                "median_sekunden": 180.0,
            },
        }
    ]
    assert any(
        wert.bestandteil_id is ModellbestandteilId.WARTESCHLANGEN
        and "keine explizit bestätigte Warteschlange" in wert.begruendung
        for wert in offen
    )


def test_nullwartezeit_bleibt_gueltig_negative_und_fehlende_werden_ausgeschlossen(
    tmp_path: Path,
) -> None:
    basis = _basis(tmp_path)
    basis.a_g["kpi_ergebnisse"] = []
    basis.event_log = pd.DataFrame(
        {
            "case_id": ["null", "null", "negativ", "negativ", "fehlend", "fehlend"],
            "activity": ["A", "B"] * 3,
            "timestamp": pd.to_datetime(["2026-01-01"] * 6, utc=True),
            "start_timestamp": pd.to_datetime(
                [
                    "2026-01-01 10:00",
                    "2026-01-01 10:01",
                    "2026-01-01 11:00",
                    "2026-01-01 11:01",
                    "2026-01-01 12:00",
                    None,
                ],
                utc=True,
            ),
            "end_timestamp": pd.to_datetime(
                [
                    "2026-01-01 10:01",
                    "2026-01-01 10:02",
                    "2026-01-01 11:02",
                    "2026-01-01 11:03",
                    "2026-01-01 12:01",
                    "2026-01-01 12:02",
                ],
                utc=True,
            ),
        }
    )
    basis.a_g["strukturierte_ergebnisse"]["warteschlangen_und_wartezeiten"] = _json_dict(
        analysiere_warteschlangen(basis.event_log)
    )
    basis.a_g["strukturierte_ergebnisse"]["zeitbezogene_datenauswahl"] = _json_dict(
        analysiere_zeitbezogene_datenauswahl(basis.zwischendaten, basis.event_log)
    )

    bestandteile, offen = leite_modellbestandteile_ab(basis)

    datenauswahl = next(
        wert for wert in bestandteile if wert.bestandteil_id is ModellbestandteilId.DATENAUSWAHL
    )
    analyse = next(
        wert.wert
        for wert in datenauswahl.informationen
        if wert.strukturreferenz == "strukturierte_ergebnisse.zeitbezogene_datenauswahl"
    )
    assert analyse["potenzielle_wartezeiten"][0]["statistik"]["median_sekunden"] == 0.0
    assert any(
        wert.bestandteil_id is ModellbestandteilId.WARTESCHLANGEN
        and "keine explizit bestätigte Warteschlange" in wert.begruendung
        for wert in offen
    )


def test_fehlende_zeitspalten_und_warteinformation_erzeugen_offenen_eintrag(
    tmp_path: Path,
) -> None:
    basis = _basis(tmp_path)
    basis.a_g["kpi_ergebnisse"] = []
    basis.a_g.pop("strukturierte_ergebnisse")

    _, offen = leite_modellbestandteile_ab(basis)

    assert any(
        wert.bestandteil_id is ModellbestandteilId.WARTESCHLANGEN
        and wert.kategorie is Offenheitskategorie.NICHT_ABLEITBAR
        and "keine explizit bestätigte Warteschlange" in wert.begruendung
        for wert in offen
    )


def test_fehlende_problemstellung_und_widerspruechliche_grenzen_bleiben_offen(
    tmp_path: Path,
) -> None:
    basis = _basis(tmp_path)
    basis.projekt = Projekt(
        basis.projekt.projekt_id,
        basis.projekt.bezeichnung,
        (),
        Projektstatus.ENTWURF,
        basis.projekt.erstellt_am,
        basis.projekt.geaendert_am,
        Untersuchungsauftrag(
            "",
            "Leistung bewerten",
            Systemtyp.PRODUKTION,
            "Fachliche Grenze",
            systemklassifikation=Systemklassifikation(bereich="Abweichender Datenbereich"),
        ),
    )

    bestandteile, offen = leite_modellbestandteile_ab(basis)

    problem = next(
        wert for wert in bestandteile if wert.bestandteil_id is ModellbestandteilId.PROBLEMSTELLUNG
    )
    assert problem.status.value == "offen"
    assert any(
        wert.bestandteil_id is ModellbestandteilId.PROBLEMSTELLUNG
        and wert.kategorie is Offenheitskategorie.FEHLEND
        for wert in offen
    )
    grenzen = next(
        wert for wert in bestandteile if wert.bestandteil_id is ModellbestandteilId.MODELLGRENZEN
    )
    assert [info.herkunftsartefakt for info in grenzen.informationen] == [
        Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U
    ]
    assert "Abweichender Datenbereich" not in repr(grenzen)
