"""Fachliche Formeltests der 16 KPI-Definitionen aus A.7 bis A.10."""

import math

import pandas as pd
import pytest

from framework_mvp.application.ergebnisaggregation.kpi import (
    KPI_DEFINITIONEN,
    KpiDatenbasis,
    berechne_ausgewaehlte_kpis,
    berechne_kpi_formel,
    kompatible_tabellenspalten,
    profilkennzahlen_fuer_operand,
    zulaessige_quellen_fuer_operand,
)
from framework_mvp.domain.models import (
    Datenartefakt,
    KpiKonfiguration,
    KpiOperandDefinition,
    KpiStatus,
    Operandentyp,
    OperandZuordnung,
    ProfilkennzahlReferenz,
    Profilkennzahltyp,
    Vorkommensregel,
)


def _profilkennzahl(
    kennzahltyp: Profilkennzahltyp,
    wert: float,
    *,
    referenz_id: str,
    spalte: str = "",
    operator: str = "",
    vergleichswert: str = "",
    auswertbar: int = 3,
    gesamt: int = 3,
) -> ProfilkennzahlReferenz:
    return ProfilkennzahlReferenz(
        referenz_id=referenz_id,
        import_id="import-1",
        datenquellen_id="quelle-1",
        datenquelle_bezeichnung="Produktionsdaten",
        originaldateiname="produktion.csv",
        tabellenbezeichnung="Aufträge",
        spaltenname=spalte,
        kennzahltyp=kennzahltyp,
        wert=wert,
        operator=operator,
        vergleichswert=vergleichswert,
        auswertbare_beobachtungen=auswertbar,
        grundgesamtheit=gesamt,
        profilversion=3,
        profil_sha256="c" * 64,
    )


def _basis(
    *profilkennzahlen: ProfilkennzahlReferenz,
    tabelle: pd.DataFrame | None = None,
    event_log: pd.DataFrame | None = None,
) -> KpiDatenbasis:
    return KpiDatenbasis(
        tabelle if tabelle is not None else pd.DataFrame(),
        event_log if event_log is not None else pd.DataFrame(),
        {},
        {
            Datenartefakt.DATENPROFIL_R: {"id": "R", "sha256": "c" * 64},
            Datenartefakt.ZWISCHENDATENSATZ_T: {"id": "T", "sha256": "a" * 64},
            Datenartefakt.EVENT_LOG_E_STERN: {"id": "E*", "sha256": "b" * 64},
        },
        profilkennzahlen,
    )


@pytest.mark.parametrize(
    ("kpi_id", "operanden", "erwartet"),
    (
        (
            "servicegrad",
            {"befriedigte_kundenauftragspositionen": 8, "kundenauftragspositionen": 10},
            80,
        ),
        (
            "verfuegbarkeit_planstarttermin",
            {"startbare_produktionsauftraege": 9, "produktionsauftraege": 10},
            90,
        ),
        ("liefertreue", {"liefertreue_produktionsauftraege": 7, "produktionsauftraege": 10}, 70),
        (
            "mittlere_dlz_warenausgang",
            {"summe_dlz_warenausgang": 24, "lieferscheinpositionen": 4},
            6,
        ),
        (
            "mittlere_dlz_wareneingang",
            {"summe_dlz_wareneingang": 15, "wareneingangspositionen": 3},
            5,
        ),
        (
            "tatsaechliche_wartezeit_aqt",
            {
                "auftragsausfuehrungszeit": 20,
                "belegungszeit_arbeitseinheit": 7,
                "transportzeit": 2,
                "verzoegerungszeit_arbeitseinheit": 1,
            },
            10,
        ),
        (
            "mittlere_transportzeit_je_warensendung",
            {"summe_transportzeiten": 30, "warensendungen": 5},
            6,
        ),
        ("mittlere_reaktionszeit", {"summe_reaktionszeiten": 18, "beobachtungen": 3}, 6),
        (
            "standardabweichung_dlz_warenausgang",
            {"dlz_warenausgang_werte": (2, 4, 6)},
            math.sqrt(8 / 3),
        ),
        (
            "anteil_regulaer_abgeschlossener_faelle",
            {"regulaer_abgeschlossene_faelle": 3, "betrachtete_faelle": 4},
            75,
        ),
        (
            "lieferqualitaetstreue",
            {"qualitaetsgerechte_wareneingangspositionen": 19, "wareneingangspositionen": 20},
            95,
        ),
        ("nacharbeitsquote_rr", {"nacharbeiten": 2, "verarbeitete_menge": 40}, 5),
        ("nutzungseffizienz_ue", {"produktionszeit": 8, "auslastung_der_einheit": 10}, 80),
        ("ruestzeitanteil", {"summe_ruestzeiten": 5, "summe_durchfuehrungszeiten": 100}, 5),
        (
            "bewertete_umschlagshaeufigkeit",
            {
                "abgang_untersuchungsobjekt": 120,
                "mittlerer_zugangsbestand": 20,
                "mittlerer_umlaufbestand": 10,
            },
            4,
        ),
        (
            "mittlere_kosten_produktionslogistik_pro_produktionsauftrag",
            {"kosten_produktionslogistik": 1000, "produktionsauftraege": 20},
            50,
        ),
    ),
)
def test_feste_kpi_formeln(kpi_id: str, operanden: dict[str, object], erwartet: float) -> None:
    ergebnis, _ = berechne_kpi_formel(kpi_id, operanden)
    assert ergebnis == pytest.approx(erwartet)


def test_katalog_besitzt_genau_16_versionierte_definitionen() -> None:
    assert len(KPI_DEFINITIONEN) == 16
    assert all(wert.definitionsversion == 1 for wert in KPI_DEFINITIONEN.values())
    assert all(
        wert.formel and wert.operanden and wert.bezugsmenge for wert in KPI_DEFINITIONEN.values()
    )


def test_nullnenner_ist_kontrolliert_nicht_berechenbar() -> None:
    with pytest.raises(ZeroDivisionError, match="Nenner ist null"):
        berechne_kpi_formel(
            "servicegrad",
            {"befriedigte_kundenauftragspositionen": 0, "kundenauftragspositionen": 0},
        )


def test_nur_ausgewaehlte_kpis_werden_berechnet_und_fehler_bleiben_isoliert() -> None:
    tabelle = pd.DataFrame({"status": ["ja", "ja", "nein"], "menge": [1, 1, 1]})
    basis = KpiDatenbasis(
        tabelle.copy(deep=True),
        pd.DataFrame({"case_id": [], "activity": [], "timestamp": []}),
        {},
        {
            Datenartefakt.ZWISCHENDATENSATZ_T: {"id": "T", "sha256": "a" * 64},
        },
    )
    servicegrad = KpiKonfiguration(
        "servicegrad",
        (
            OperandZuordnung(
                "befriedigte_kundenauftragspositionen",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="status",
                bedingungsoperator="gleich",
                bedingungswert="ja",
            ),
            OperandZuordnung(
                "kundenauftragspositionen",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="status",
            ),
        ),
        "%",
        "Kundenauftragspositionen",
    )
    ergebnisse = berechne_ausgewaehlte_kpis(("servicegrad", "liefertreue"), (servicegrad,), basis)
    assert [wert.kpi_id for wert in ergebnisse] == ["servicegrad", "liefertreue"]
    assert ergebnisse[0].status is KpiStatus.BERECHNET
    assert ergebnisse[0].ergebnis == pytest.approx(200 / 3)
    assert ergebnisse[1].status is KpiStatus.NICHT_BERECHENBAR
    assert "keine Operanden" in ergebnisse[1].fehlende_voraussetzungen[0]


def test_bestaetigter_arithmetischer_mittelwert_wird_direkt_aus_r_uebernommen() -> None:
    referenz = "profil:lieferzeit:mittelwert"
    basis = KpiDatenbasis(
        pd.DataFrame(),
        pd.DataFrame(),
        {referenz: 7.5},
        {Datenartefakt.DATENPROFIL_R: {"id": "R", "sha256": "b" * 64}},
    )
    konfiguration = KpiKonfiguration(
        "mittlere_dlz_warenausgang",
        (),
        "Tage",
        "Lieferscheinpositionen",
        referenz,
    )

    (ergebnis,) = berechne_ausgewaehlte_kpis(
        ("mittlere_dlz_warenausgang",), (konfiguration,), basis
    )

    assert ergebnis.status is KpiStatus.BERECHNET
    assert ergebnis.ergebnis == pytest.approx(7.5)
    assert ergebnis.quellenreferenzen[0]["profilreferenz"] == referenz
    assert "direkt übernommen" in ergebnis.rechenweg


def test_alte_technische_operandreferenzen_bleiben_kontrolliert_lesbar() -> None:
    zaehler = "import-1:status:gueltige_werte"
    nenner = "import-1:__gesamt__:zeilen"
    basis = KpiDatenbasis(
        pd.DataFrame(),
        pd.DataFrame(),
        {zaehler: 8.0, nenner: 10.0},
        {Datenartefakt.DATENPROFIL_R: {"id": "R", "sha256": "b" * 64}},
    )
    konfiguration = KpiKonfiguration(
        "servicegrad",
        (
            OperandZuordnung(
                "befriedigte_kundenauftragspositionen",
                Datenartefakt.DATENPROFIL_R,
                profilreferenz=zaehler,
            ),
            OperandZuordnung(
                "kundenauftragspositionen",
                Datenartefakt.DATENPROFIL_R,
                profilreferenz=nenner,
            ),
        ),
        "%",
        "Kundenauftragspositionen",
    )

    (ergebnis,) = berechne_ausgewaehlte_kpis(("servicegrad",), (konfiguration,), basis)

    assert ergebnis.status is KpiStatus.BERECHNET
    assert ergebnis.ergebnis == pytest.approx(80)
    assert all(
        operand["legacy_profilreferenz"] is True for operand in ergebnis.zugeordnete_operanden
    )


def test_strukturierte_profilkennzahl_wird_fachlich_lesbar_angezeigt() -> None:
    referenz = _profilkennzahl(
        Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR,
        73,
        referenz_id="indikator-ja",
        spalte="Nacharbeit",
        operator="gleich",
        vergleichswert="Ja",
        auswertbar=100,
        gesamt=102,
    )

    assert "Datensatz: Produktionsdaten" in referenz.anzeigetext
    assert "Spalte: Nacharbeit" in referenz.anzeigetext
    assert "Absolute Häufigkeit eines Indikators" in referenz.anzeigetext
    assert "Nacharbeit = Ja" in referenz.anzeigetext
    assert "Wert: 73" in referenz.anzeigetext
    assert "indikator-ja" not in referenz.anzeigetext


def test_strukturierter_mittelwert_ist_fuer_mittelwert_nutzbar_indikator_aber_nicht() -> None:
    mittelwert = _profilkennzahl(
        Profilkennzahltyp.ARITHMETISCHES_MITTEL,
        14.7,
        referenz_id="mittelwert",
        spalte="Bearbeitungszeit",
    )
    indikator = _profilkennzahl(
        Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR,
        2,
        referenz_id="indikator",
        spalte="Nacharbeit",
        operator="gleich",
        vergleichswert="Ja",
    )
    definition = KpiOperandDefinition(
        "zeit",
        "Bearbeitungszeit",
        Operandentyp.MITTELWERT,
        (Datenartefakt.DATENPROFIL_R,),
        "numerisch",
    )
    basis = _basis(mittelwert, indikator)

    assert profilkennzahlen_fuer_operand(definition, basis) == (mittelwert,)


def test_strukturierter_mittelwert_kann_nach_bestaetigung_direkt_uebernommen_werden() -> None:
    mittelwert = _profilkennzahl(
        Profilkennzahltyp.ARITHMETISCHES_MITTEL,
        7.5,
        referenz_id="mittelwert-dlz",
        spalte="Lieferzeit",
    )
    konfiguration = KpiKonfiguration(
        "mittlere_dlz_warenausgang",
        (),
        "Tage",
        "Lieferscheinpositionen",
        direkte_profilkennzahl=mittelwert,
    )

    (ergebnis,) = berechne_ausgewaehlte_kpis(
        ("mittlere_dlz_warenausgang",),
        (konfiguration,),
        _basis(mittelwert),
    )

    assert ergebnis.status is KpiStatus.BERECHNET
    assert ergebnis.ergebnis == pytest.approx(7.5)
    assert ergebnis.quellenreferenzen[0]["profilkennzahl"]["spaltenname"] == "Lieferzeit"


def test_summe_wird_nicht_aus_mittelwert_und_anzahl_rekonstruiert() -> None:
    mittelwert = _profilkennzahl(
        Profilkennzahltyp.ARITHMETISCHES_MITTEL,
        10,
        referenz_id="mittelwert",
        spalte="Menge",
    )
    anzahl = _profilkennzahl(
        Profilkennzahltyp.GUELTIGE_BEOBACHTUNGEN,
        4,
        referenz_id="anzahl",
        spalte="Menge",
    )
    definition = KpiOperandDefinition(
        "menge",
        "verarbeitete Menge",
        Operandentyp.SUMME,
        (Datenartefakt.DATENPROFIL_R,),
        "numerisch",
    )

    assert profilkennzahlen_fuer_operand(definition, _basis(mittelwert, anzahl)) == ()
    assert zulaessige_quellen_fuer_operand(definition, _basis(mittelwert, anzahl)) == ()


@pytest.mark.parametrize(
    ("operator", "vergleichswert", "anzeigeoperator"),
    (
        ("gleich", "Ja", "="),
        ("ungleich", "Freigegeben", "!="),
        (">", "10", ">"),
        (">=", "20", ">="),
        ("<", "80", "<"),
        ("<=", "5", "<="),
    ),
)
def test_gespeicherte_indikatoroperatoren_werden_ohne_neuberechnung_uebernommen(
    operator: str,
    vergleichswert: str,
    anzeigeoperator: str,
) -> None:
    indikator = _profilkennzahl(
        Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR,
        73,
        referenz_id=f"indikator-{operator}",
        spalte="Nacharbeit",
        operator=operator,
        vergleichswert=vergleichswert,
        auswertbar=100,
        gesamt=102,
    )
    zeilen = _profilkennzahl(
        Profilkennzahltyp.ZEILENANZAHL,
        100,
        referenz_id="zeilen",
        auswertbar=100,
        gesamt=100,
    )
    konfiguration = KpiKonfiguration(
        "servicegrad",
        (
            OperandZuordnung(
                "befriedigte_kundenauftragspositionen",
                Datenartefakt.DATENPROFIL_R,
                profilkennzahl=indikator,
            ),
            OperandZuordnung(
                "kundenauftragspositionen",
                Datenartefakt.DATENPROFIL_R,
                profilkennzahl=zeilen,
            ),
        ),
        "%",
        "Kundenauftragspositionen",
    )
    basis = _basis(
        indikator,
        zeilen,
        tabelle=pd.DataFrame({"Nacharbeit": ["Nein"] * 100}),
    )

    (ergebnis,) = berechne_ausgewaehlte_kpis(("servicegrad",), (konfiguration,), basis)

    assert ergebnis.status is KpiStatus.BERECHNET
    assert ergebnis.ergebnis == pytest.approx(73)
    assert ergebnis.zwischensummen["befriedigte_kundenauftragspositionen"] == 73
    assert ergebnis.wertebedingungen[0] == {
        "operand_id": "befriedigte_kundenauftragspositionen",
        "quelle": "R",
        "spalte": "Nacharbeit",
        "operator": operator,
        "wert": vergleichswert,
        "in_schritt_7_ausgewertet": False,
        "bedeutung": "Gespeicherte Indikatorbedingung aus R",
    }
    assert f"Nacharbeit {anzeigeoperator} {vergleichswert}" in indikator.anzeigetext
    assert ergebnis.ausgeschlossene_werte == 2


def test_mehrere_indikatorbedingungen_einer_spalte_bleiben_getrennt_auswaehlbar() -> None:
    gleich = _profilkennzahl(
        Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR,
        73,
        referenz_id="nacharbeit-gleich-ja",
        spalte="Nacharbeit",
        operator="gleich",
        vergleichswert="Ja",
    )
    ungleich = _profilkennzahl(
        Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR,
        27,
        referenz_id="nacharbeit-ungleich-ja",
        spalte="Nacharbeit",
        operator="ungleich",
        vergleichswert="Ja",
    )
    definition = KPI_DEFINITIONEN["servicegrad"].operanden[0]

    auswahl = profilkennzahlen_fuer_operand(definition, _basis(gleich, ungleich))

    assert [wert.referenz_id for wert in auswahl] == [
        "nacharbeit-gleich-ja",
        "nacharbeit-ungleich-ja",
    ]
    assert auswahl[0].anzeigetext != auswahl[1].anzeigetext


def test_nacharbeitsquote_verwendet_r_indikator_als_zaehler_und_t_summe_als_nenner() -> None:
    indikator = _profilkennzahl(
        Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR,
        3,
        referenz_id="nacharbeit-ja",
        spalte="Nacharbeit",
        operator="gleich",
        vergleichswert="Ja",
        auswertbar=100,
        gesamt=100,
    )
    konfiguration = KpiKonfiguration(
        "nacharbeitsquote_rr",
        (
            OperandZuordnung(
                "nacharbeiten",
                Datenartefakt.DATENPROFIL_R,
                profilkennzahl=indikator,
            ),
            OperandZuordnung(
                "verarbeitete_menge",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="Menge",
            ),
        ),
        "%",
        "verarbeitete Menge",
    )
    basis = _basis(
        indikator,
        tabelle=pd.DataFrame(
            {
                "Nacharbeit": ["Nein", "Nein", "Nein"],
                "Menge": [10, 20, 30],
            }
        ),
    )

    (ergebnis,) = berechne_ausgewaehlte_kpis(
        ("nacharbeitsquote_rr",),
        (konfiguration,),
        basis,
    )

    assert ergebnis.status is KpiStatus.BERECHNET
    assert ergebnis.zwischensummen == {"nacharbeiten": 3.0, "verarbeitete_menge": 60.0}
    assert ergebnis.ergebnis == pytest.approx(5)
    assert ergebnis.formel == KPI_DEFINITIONEN["nacharbeitsquote_rr"].formel
    assert ergebnis.quellenreferenzen[0]["artefakt"] == "R"
    assert ergebnis.wertebedingungen[0]["in_schritt_7_ausgewertet"] is False


def test_ungleich_zaehlt_fehlwert_in_t_nicht_als_treffer() -> None:
    tabelle = pd.DataFrame({"status": ["Ja", "Nein", None]})
    konfiguration = KpiKonfiguration(
        "servicegrad",
        (
            OperandZuordnung(
                "befriedigte_kundenauftragspositionen",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="status",
                bedingungsoperator="ungleich",
                bedingungswert="Ja",
            ),
            OperandZuordnung(
                "kundenauftragspositionen",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="status",
            ),
        ),
        "%",
        "Kundenauftragspositionen",
    )

    (ergebnis,) = berechne_ausgewaehlte_kpis(
        ("servicegrad",),
        (konfiguration,),
        _basis(tabelle=tabelle),
    )

    assert ergebnis.status is KpiStatus.BERECHNET
    assert ergebnis.zwischensummen == {
        "befriedigte_kundenauftragspositionen": 1.0,
        "kundenauftragspositionen": 2.0,
    }
    assert ergebnis.ergebnis == pytest.approx(50)


def test_quellkompatibilitaet_beruecksichtigt_operandentyp_und_vorhandene_daten() -> None:
    kennzahlen = (
        _profilkennzahl(Profilkennzahltyp.ZEILENANZAHL, 3, referenz_id="zeilen"),
        _profilkennzahl(
            Profilkennzahltyp.ARITHMETISCHES_MITTEL,
            2,
            referenz_id="mittelwert",
            spalte="zahl",
        ),
    )
    tabelle = pd.DataFrame(
        {
            "text": ["a", "b"],
            "zahl": [1.0, 2.0],
            "start": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
            "ende": pd.to_datetime(["2026-01-02", "2026-01-03"], utc=True),
        }
    )
    event_log = pd.DataFrame(
        {
            "case_id": ["1", "1"],
            "activity": ["A", "B"],
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
            "zahl": [1, 2],
        }
    )
    basis = _basis(*kennzahlen, tabelle=tabelle, event_log=event_log)
    alle = (
        Datenartefakt.DATENPROFIL_R,
        Datenartefakt.ZWISCHENDATENSATZ_T,
        Datenartefakt.EVENT_LOG_E_STERN,
    )

    def quellen(typ: Operandentyp) -> tuple[Datenartefakt, ...]:
        return zulaessige_quellen_fuer_operand(
            KpiOperandDefinition("x", "x", typ, alle, "fachlich"),
            basis,
        )

    assert quellen(Operandentyp.ANZAHL) == alle
    assert quellen(Operandentyp.MITTELWERT) == alle
    assert quellen(Operandentyp.SUMME) == (
        Datenartefakt.ZWISCHENDATENSATZ_T,
        Datenartefakt.EVENT_LOG_E_STERN,
    )
    assert quellen(Operandentyp.MESSWERTE) == (
        Datenartefakt.ZWISCHENDATENSATZ_T,
        Datenartefakt.EVENT_LOG_E_STERN,
    )
    assert quellen(Operandentyp.ZEITDIFFERENZ_SUMME) == (
        Datenartefakt.ZWISCHENDATENSATZ_T,
        Datenartefakt.EVENT_LOG_E_STERN,
    )
    assert kompatible_tabellenspalten(Operandentyp.MITTELWERT, tabelle) == ("zahl",)
    assert kompatible_tabellenspalten(Operandentyp.ZEITDIFFERENZ_SUMME, tabelle) == (
        "start",
        "ende",
    )


def test_alle_16_definitionen_bieten_nur_tatsaechlich_bestimmbare_quellen_an() -> None:
    basis = _basis(
        _profilkennzahl(Profilkennzahltyp.ZEILENANZAHL, 2, referenz_id="zeilen"),
        _profilkennzahl(
            Profilkennzahltyp.ARITHMETISCHES_MITTEL,
            1.5,
            referenz_id="mittel",
            spalte="zahl",
        ),
        tabelle=pd.DataFrame(
            {
                "text": ["a", "b"],
                "zahl": [1.0, 2.0],
                "start": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
                "ende": pd.to_datetime(["2026-01-02", "2026-01-03"], utc=True),
            }
        ),
        event_log=pd.DataFrame(
            {
                "case_id": ["1", "1"],
                "activity": ["A", "B"],
                "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
                "zahl": [1.0, 2.0],
            }
        ),
    )

    assert len(KPI_DEFINITIONEN) == 16
    for definition in KPI_DEFINITIONEN.values():
        for operand in definition.operanden:
            quellen = zulaessige_quellen_fuer_operand(operand, basis)
            assert set(quellen) <= set(operand.zulaessige_quellen)
            if operand.operandentyp in {
                Operandentyp.SUMME,
                Operandentyp.MESSWERTE,
                Operandentyp.ZEITDIFFERENZ_SUMME,
            }:
                assert Datenartefakt.DATENPROFIL_R not in quellen
            if Datenartefakt.DATENPROFIL_R in quellen:
                assert operand.operandentyp in {Operandentyp.ANZAHL, Operandentyp.MITTELWERT}


def test_zeitbezogene_kpi_verwendet_explizite_aktivitaeten_und_vorkommensregel() -> None:
    event_log = pd.DataFrame(
        {
            "case_id": ["1", "1", "1", "2", "2"],
            "activity": ["A", "B", "B", "A", "B"],
            "timestamp": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-01",
                    "2026-01-04",
                ],
                utc=True,
            ),
        }
    )
    konfiguration = KpiKonfiguration(
        "mittlere_reaktionszeit",
        (
            OperandZuordnung(
                "summe_reaktionszeiten",
                Datenartefakt.EVENT_LOG_E_STERN,
                startaktivitaet="A",
                endaktivitaet="B",
                vorkommensregel=Vorkommensregel.LETZTES,
            ),
            OperandZuordnung(
                "beobachtungen",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="fall",
            ),
        ),
        "Sekunden",
        "Beobachtungen n",
    )

    (ergebnis,) = berechne_ausgewaehlte_kpis(
        ("mittlere_reaktionszeit",),
        (konfiguration,),
        _basis(tabelle=pd.DataFrame({"fall": ["1", "2"]}), event_log=event_log),
    )

    assert ergebnis.status is KpiStatus.BERECHNET
    assert ergebnis.zwischensummen["summe_reaktionszeiten"] == 5 * 24 * 60 * 60
    assert ergebnis.ergebnis == pytest.approx(2.5 * 24 * 60 * 60)
    assert ergebnis.einheit == "Sekunden"
    assert ergebnis.zugeordnete_operanden[0]["startaktivitaet"] == "A"
    assert ergebnis.zugeordnete_operanden[0]["endaktivitaet"] == "B"
