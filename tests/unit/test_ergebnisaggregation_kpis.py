"""Fachliche Formeltests der 16 KPI-Definitionen aus A.7 bis A.10."""

import math

import pandas as pd
import pytest

from framework_mvp.application.ergebnisaggregation.kpi import (
    KPI_DEFINITIONEN,
    KpiDatenbasis,
    berechne_ausgewaehlte_kpis,
    berechne_kpi_formel,
)
from framework_mvp.domain.models import (
    Datenartefakt,
    KpiKonfiguration,
    KpiStatus,
    OperandZuordnung,
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
