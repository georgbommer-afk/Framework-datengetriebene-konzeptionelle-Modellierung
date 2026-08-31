"""Reine Schritt-7-Analysen für Ressourcen, Entitäten und Zeitgrößen."""

import pandas as pd
import pytest

from framework_mvp.application.ergebnisaggregation.strukturierte_ergebnisse import (
    analysiere_entitaeten,
    analysiere_ressourcen,
    analysiere_warteschlangen,
    analysiere_zeitbezogene_datenauswahl,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    AnkunftsstromDefinition,
    Attributstatus,
    Attributzuordnung,
    BestaetigteWarteschlangeninformation,
    Datenartefakt,
    Ressourcenzuordnungsmodus,
    StrukturiertesErgebnisStatus,
    Vorkommensregel,
)


def test_beobachtete_ressourcen_sind_vollstaendig_und_mehrfach_moeglich() -> None:
    event_log = pd.DataFrame({"activity": ["A", "A", "B"], "resource": [" M1 ", "M2", "M2"]})

    ergebnis = analysiere_ressourcen(event_log)

    assert ergebnis.modus is Ressourcenzuordnungsmodus.AUTOMATISCH
    assert [(wert.aktivitaet, wert.ressourcen) for wert in ergebnis.zuordnungen] == [
        ("A", ("M1", "M2")),
        ("B", ("M2",)),
    ]
    assert ergebnis.zuordnungen[0].automatisch_beobachtete_ressourcen == ("M1", "M2")


def test_teilbeobachtungen_bleiben_erhalten_und_nur_luecken_werden_entschieden() -> None:
    event_log = pd.DataFrame(
        {"activity": ["Fräsen", "Lackieren", "Prüfung"], "resource": ["M01", "LKK2", None]}
    )

    offen = analysiere_ressourcen(event_log)
    assert offen.modus is Ressourcenzuordnungsmodus.GEMISCHT
    assert offen.zuordnungen[0].ressourcen == ("M01",)
    assert next(wert for wert in offen.zuordnungen if wert.aktivitaet == "Prüfung").offen

    gemischt = analysiere_ressourcen(
        event_log,
        manuelle_zuordnungen={"Prüfung": ("MA03",)},
    )
    pruefung = next(wert for wert in gemischt.zuordnungen if wert.aktivitaet == "Prüfung")
    assert pruefung.manuell_bestaetigte_ressourcen == ("MA03",)
    assert not pruefung.offen

    with pytest.raises(Domaenenfehler, match="Es fehlen: Prüfung"):
        analysiere_ressourcen(event_log, manuelle_zuordnungen={})


def test_vollstaendig_manuelle_ressourcen_und_explizit_offene_luecke() -> None:
    event_log = pd.DataFrame({"activity": ["A", "B"]})
    manuell = analysiere_ressourcen(
        event_log,
        manuelle_zuordnungen={"A": ("AP01",), "B": ("MA01", "MA02")},
    )
    assert manuell.modus is Ressourcenzuordnungsmodus.MANUELL

    teilweise_offen = analysiere_ressourcen(
        event_log,
        manuelle_zuordnungen={"A": ("AP01",)},
        offene_aktivitaeten=("B",),
    )
    assert teilweise_offen.modus is Ressourcenzuordnungsmodus.GEMISCHT
    assert teilweise_offen.zuordnungen[1].offen


def test_ressourcenattribute_werden_nur_stabil_verdichtet() -> None:
    event_log = pd.DataFrame(
        {
            "activity": ["A", "A", "A", "A"],
            "resource": ["M01", "M01", "M02", "M02"],
            "timestamp": pd.to_datetime(
                ["2026-01-01 08:00", "2026-01-01 12:00", "2026-01-01 08:00", "2026-01-01 12:00"],
                utc=True,
            ),
            "typ": ["Fräsmaschine", "Fräsmaschine", "Presse", "Presse"],
            "verfuegbar": ["1", "0", "1", "1"],
        }
    )
    zwischendaten = pd.DataFrame(
        {"maschinen_id": ["M01", "M01", "M02"], "kapazitaet": ["5", "5", "8"]}
    )
    ergebnis = analysiere_ressourcen(
        event_log,
        zwischendaten=zwischendaten,
        attributzuordnungen=(
            Attributzuordnung(Datenartefakt.EVENT_LOG_E_STERN, "typ", "resource"),
            Attributzuordnung(
                Datenartefakt.EVENT_LOG_E_STERN, "verfuegbar", "resource", "timestamp"
            ),
            Attributzuordnung(Datenartefakt.ZWISCHENDATENSATZ_T, "kapazitaet", "maschinen_id"),
        ),
    )

    typ_m01 = next(
        wert for wert in ergebnis.attribute if wert.instanz_id == "M01" and wert.attribut == "typ"
    )
    verfuegbar_m01 = next(
        wert
        for wert in ergebnis.attribute
        if wert.instanz_id == "M01" and wert.attribut == "verfuegbar"
    )
    assert typ_m01.status is Attributstatus.STABIL
    assert typ_m01.stabiler_wert == "Fräsmaschine"
    assert verfuegbar_m01.status is Attributstatus.ZEITABHAENGIG_NICHT_EINDEUTIG
    assert verfuegbar_m01.stabiler_wert == ""
    assert [wert.wert for wert in verfuegbar_m01.beobachtungen] == ["1", "0"]
    kapazitaet_m01 = next(
        wert
        for wert in ergebnis.attribute
        if wert.instanz_id == "M01" and wert.attribut == "kapazitaet"
    )
    assert kapazitaet_m01.stabiler_wert == "5"
    assert kapazitaet_m01.schluesselspalte == "maschinen_id"


def test_case_id_bleibt_entitaetsinstanz_und_attribute_bleiben_bei_wechsel_erhalten() -> None:
    event_log = pd.DataFrame(
        {
            "case_id": ["PA4711", "PA4711", "PA4712"],
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-01"], utc=True),
            "produkt": ["P100", "P100", "P200"],
            "qualitaet": ["offen", "freigegeben", "offen"],
        }
    )
    ergebnis = analysiere_entitaeten(
        pd.DataFrame(),
        event_log,
        attributzuordnungen=(
            Attributzuordnung(Datenartefakt.EVENT_LOG_E_STERN, "produkt", "case_id"),
            Attributzuordnung(Datenartefakt.EVENT_LOG_E_STERN, "qualitaet", "case_id", "timestamp"),
        ),
    )

    assert [wert.instanz_id for wert in ergebnis.instanzen] == ["PA4711", "PA4712"]
    assert ergebnis.entitaetstyp == ""
    produkt = next(
        wert
        for wert in ergebnis.attribute
        if wert.instanz_id == "PA4711" and wert.attribut == "produkt"
    )
    qualitaet = next(
        wert
        for wert in ergebnis.attribute
        if wert.instanz_id == "PA4711" and wert.attribut == "qualitaet"
    )
    assert produkt.stabiler_wert == "P100"
    assert qualitaet.status is Attributstatus.ZEITABHAENGIG_NICHT_EINDEUTIG
    assert qualitaet.stabiler_wert == ""


def test_potenzielle_wartezeit_nutzt_timestamp_reihenfolge_und_zaehlt_ueberlappung() -> None:
    event_log = pd.DataFrame(
        {
            "case_id": ["1", "1", "2", "2", "3", "3"],
            "activity": ["A", "B", "A", "B", "A", "B"],
            "timestamp": pd.to_datetime(
                [
                    "2026-01-01 08:00",
                    "2026-01-01 08:30",
                    "2026-01-01 09:00",
                    "2026-01-01 09:30",
                    "2026-01-01 10:00",
                    "2026-01-01 10:30",
                ],
                utc=True,
            ),
            # In Fall 1 würde eine Sortierung nach Start fälschlich B -> A ergeben.
            "start_timestamp": pd.to_datetime(
                [
                    "2026-01-01 08:20",
                    "2026-01-01 08:10",
                    "2026-01-01 09:00",
                    "2026-01-01 09:10",
                    "2026-01-01 10:00",
                    "2026-01-01 10:05",
                ],
                utc=True,
            ),
            "end_timestamp": pd.to_datetime(
                [
                    "2026-01-01 07:50",
                    "2026-01-01 08:40",
                    "2026-01-01 09:10",
                    "2026-01-01 09:20",
                    "2026-01-01 10:10",
                    "2026-01-01 10:20",
                ],
                utc=True,
            ),
        }
    )
    ergebnis = analysiere_warteschlangen(event_log)

    assert ergebnis.status is StrukturiertesErgebnisStatus.ABLEITBAR
    assert not ergebnis.bestaetigte_warteschlangen
    assert ergebnis.anzahl_ueberlappungen == 1
    assert len(ergebnis.potenzielle_wartezeiten) == 1
    statistik = ergebnis.potenzielle_wartezeiten[0].statistik
    assert statistik.anzahl == 2
    assert statistik.median_sekunden == 600.0
    assert "Potenzielle Wartezeit" in ergebnis.berechnungsregel
    assert "E*.timestamp" in ergebnis.berechnungsregel


def test_explizite_warteschlange_bleibt_von_potenzieller_wartezeit_getrennt() -> None:
    event_log = pd.DataFrame(
        {
            "case_id": ["1", "1"],
            "activity": ["Fräsen", "Lackieren"],
            "timestamp": pd.to_datetime(["2026-01-01 08:00", "2026-01-01 08:30"], utc=True),
            "start_timestamp": pd.to_datetime(["2026-01-01 08:00", "2026-01-01 08:30"], utc=True),
            "end_timestamp": pd.to_datetime(["2026-01-01 08:10", "2026-01-01 08:50"], utc=True),
            "puffer": ["", "Zwischenlager"],
        }
    )
    bestaetigt = BestaetigteWarteschlangeninformation(
        "Zwischenlager vor Lackierung",
        "Fräsen",
        "Lackieren",
        Datenartefakt.EVENT_LOG_E_STERN,
        "puffer",
        "Zwischenlager",
    )

    ergebnis = analysiere_warteschlangen(event_log, bestaetigte_warteschlangen=(bestaetigt,))

    assert ergebnis.bestaetigte_warteschlangen == (bestaetigt,)
    assert ergebnis.potenzielle_wartezeiten[0].statistik.median_sekunden == 1200.0


def test_bearbeitungszeit_nach_ressource_und_ungueltige_getrennt_gezaehlt() -> None:
    event_log = pd.DataFrame(
        {
            "case_id": ["1", "2", "3", "4", "5", "6"],
            "activity": ["A"] * 6,
            "timestamp": pd.to_datetime(["2026-01-01"] * 6, utc=True),
            "resource": ["M01", "M02", None, "M01", "M01", "M02"],
            "start_timestamp": pd.to_datetime(
                [
                    "2026-01-01 08:00",
                    "2026-01-01 08:00",
                    "2026-01-01 08:00",
                    None,
                    "2026-01-01 09:10",
                    "2026-01-01 10:00",
                ],
                utc=True,
            ),
            "end_timestamp": pd.to_datetime(
                [
                    "2026-01-01 08:10",
                    "2026-01-01 08:20",
                    "2026-01-01 08:30",
                    "2026-01-01 09:00",
                    None,
                    "2026-01-01 09:00",
                ],
                utc=True,
            ),
        }
    )
    ergebnis = analysiere_zeitbezogene_datenauswahl(pd.DataFrame(), event_log)

    assert {(wert.aktivitaet, wert.ressource) for wert in ergebnis.bearbeitungszeiten} == {
        ("A", ""),
        ("A", "M01"),
        ("A", "M02"),
    }
    ohne = next(wert for wert in ergebnis.bearbeitungszeiten if not wert.ressource)
    assert not ohne.ressourcenbezug
    assert "kein Ressourcenbezug verfügbar" in ohne.gruppierungsbezeichnung
    assert ergebnis.ausgeschlossene_negative_bearbeitungszeiten == 1
    assert ergebnis.ausgeschlossene_nicht_auswertbare_bearbeitungszeiten == 2


def _iat_event_log() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["C1", "C1", "C2", "C2", "C3", "C3"],
            "activity": ["Start", "Lack", "Start", "Lack", "Start", "Lack"],
            "timestamp": pd.to_datetime(
                [
                    "2026-01-01 08:00",
                    "2026-01-01 09:00",
                    "2026-01-01 08:10",
                    "2026-01-01 09:20",
                    "2026-01-01 08:25",
                    "2026-01-01 09:50",
                ],
                utc=True,
            ),
        }
    )


def test_ohne_bestaetigten_ankunftsstrom_entsteht_keine_automatische_iat() -> None:
    event_log = _iat_event_log()
    event_log["start_timestamp"] = event_log["timestamp"]
    ergebnis = analysiere_zeitbezogene_datenauswahl(pd.DataFrame(), event_log)
    assert ergebnis.zwischenankunftszeiten == ()
    assert ergebnis.zwischenankunftszeit is None
    assert "T" not in ergebnis.bestaetigte_datenbasis


def test_zwei_ankunftsstroeme_werden_getrennt_und_explizit_berechnet() -> None:
    definitionen = (
        AnkunftsstromDefinition(
            "Systemeintritt",
            Datenartefakt.EVENT_LOG_E_STERN,
            "case_id",
            "timestamp",
            aktivitaet="Start",
        ),
        AnkunftsstromDefinition(
            "Ankunft Lackierung",
            Datenartefakt.EVENT_LOG_E_STERN,
            "case_id",
            "timestamp",
            aktivitaet="Lack",
        ),
    )
    ergebnis = analysiere_zeitbezogene_datenauswahl(
        pd.DataFrame(), _iat_event_log(), ankunftsstroeme=definitionen
    )

    assert [wert.definition.bezeichnung for wert in ergebnis.zwischenankunftszeiten] == [
        "Systemeintritt",
        "Ankunft Lackierung",
    ]
    assert ergebnis.zwischenankunftszeiten[0].statistik is not None
    assert ergebnis.zwischenankunftszeiten[0].statistik.median_sekunden == 750.0
    assert ergebnis.zwischenankunftszeiten[1].statistik is not None
    assert ergebnis.zwischenankunftszeiten[1].statistik.median_sekunden == 1500.0


def test_mehrdeutige_ankunft_ohne_regel_wird_ausgeschlossen_mit_erstes_deterministisch() -> None:
    event_log = pd.concat([_iat_event_log(), _iat_event_log().iloc[[0]]], ignore_index=True)
    ohne_regel = AnkunftsstromDefinition(
        "Systemeintritt",
        Datenartefakt.EVENT_LOG_E_STERN,
        "case_id",
        "timestamp",
        aktivitaet="Start",
    )
    mit_regel = AnkunftsstromDefinition(
        "Systemeintritt",
        Datenartefakt.EVENT_LOG_E_STERN,
        "case_id",
        "timestamp",
        aktivitaet="Start",
        vorkommensregel=Vorkommensregel.ERSTES,
    )

    mehrdeutig = analysiere_zeitbezogene_datenauswahl(
        pd.DataFrame(), event_log, ankunftsstroeme=(ohne_regel,)
    )
    eindeutig = analysiere_zeitbezogene_datenauswahl(
        pd.DataFrame(), event_log, ankunftsstroeme=(mit_regel,)
    )

    assert mehrdeutig.zwischenankunftszeiten[0].ausschlussgruende == {
        "mehrdeutig_ohne_vorkommensregel": 1
    }
    assert eindeutig.zwischenankunftszeiten[0].statistik is not None
    assert "Vorkommensregel: erstes" in eindeutig.zwischenankunftszeiten[0].berechnungsregel


def test_ankunft_aus_t_verwendet_nur_explizite_id_zeit_und_lineage() -> None:
    tabelle = pd.DataFrame(
        {
            "auftrag": ["C1", "C2", "C3"],
            "ankunft": ["2026-01-01 08:00", "2026-01-01 08:10", "2026-01-01 08:25"],
        }
    )
    definition = AnkunftsstromDefinition(
        "Puffer Montage", Datenartefakt.ZWISCHENDATENSATZ_T, "auftrag", "ankunft"
    )
    ergebnis = analysiere_zeitbezogene_datenauswahl(
        tabelle,
        _iat_event_log(),
        ankunftsstroeme=(definition,),
        datenbasis_referenzen={"T": {"sha256": "a" * 64}, "E*": {"sha256": "b" * 64}},
    )
    iat = ergebnis.zwischenankunftszeiten[0]
    assert iat.statistik is not None and iat.statistik.anzahl == 2
    assert iat.lineage["entitaetsspalte"] == "auftrag"
    assert iat.lineage["zeitspalte"] == "ankunft"
    assert iat.lineage["quellenreferenz"] == {"sha256": "a" * 64}
    assert ergebnis.bestaetigte_datenbasis == ("T",)
