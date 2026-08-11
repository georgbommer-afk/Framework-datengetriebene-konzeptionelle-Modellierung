"""Tests der direkten fall- und ereignisbezogenen Soll-Ist-Abweichungen."""

from io import BytesIO
from uuid import uuid4

import pandas as pd
import pytest

from framework_mvp.application.ergebnisaggregation.zeitvergleich import (
    lese_externe_sollzeitdaten,
    zeitvergleich_berechnen,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Vergleichsebene,
    Vorkommensregel,
    ZeitvergleichKonfiguration,
)


def _event_log() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": ["1", "1", "2", "2"],
            "activity": ["A", "Ende", "A", "Ende"],
            "timestamp": pd.to_datetime(
                ["2026-01-01", "2026-01-03", "2026-01-01", "2026-01-02"], utc=True
            ),
        }
    )


def test_fallbezogener_vergleich_klassifiziert_direkte_abweichungen() -> None:
    soll = pd.DataFrame(
        {"fall": ["1", "2", "3"], "plan": ["2026-01-02", "2026-01-02", "2026-01-04"]}
    )
    config = ZeitvergleichKonfiguration(
        Vergleichsebene.FALL,
        "extern",
        "fall",
        "plan",
        "case_id",
        "timestamp",
        ist_activity_spalte="activity",
        ausgewaehlte_ist_aktivitaet="Ende",
        vorkommensregel=Vorkommensregel.ERSTES,
    )
    ergebnis = zeitvergleich_berechnen(
        soll_daten=soll, event_log=_event_log(), konfiguration=config
    )
    assert [wert.klassifikation for wert in ergebnis.abweichungen] == ["verspätet", "termingerecht"]
    assert ergebnis.fehlende_istwerte == 1
    assert ergebnis.aggregierte_anzahlen["eindeutig_vergleichbar"] == 2


def test_ereignisvergleich_mit_auftretensnummer_und_mehrdeutigkeit_blockiert() -> None:
    ist = pd.DataFrame(
        {
            "case_id": ["1", "1"],
            "activity": ["A", "A"],
            "timestamp": pd.to_datetime(["2026-01-02", "2026-01-04"], utc=True),
        }
    )
    soll = pd.DataFrame(
        {
            "fall": ["1", "1"],
            "schritt": ["A", "A"],
            "plan": ["2026-01-01", "2026-01-05"],
            "nr": [1, 2],
        }
    )
    ohne_nummer = ZeitvergleichKonfiguration(
        Vergleichsebene.EREIGNIS,
        "extern",
        "fall",
        "plan",
        "case_id",
        "timestamp",
        "schritt",
        "activity",
    )
    with pytest.raises(Domaenenfehler, match="Auftretensnummer"):
        zeitvergleich_berechnen(soll_daten=soll, event_log=ist, konfiguration=ohne_nummer)
    mit_nummer = ZeitvergleichKonfiguration(
        Vergleichsebene.EREIGNIS,
        "extern",
        "fall",
        "plan",
        "case_id",
        "timestamp",
        "schritt",
        "activity",
        soll_auftretensnummer_spalte="nr",
        vorkommensregel=Vorkommensregel.AUFTRETENSNUMMER,
    )
    ergebnis = zeitvergleich_berechnen(soll_daten=soll, event_log=ist, konfiguration=mit_nummer)
    assert [wert.abweichung_sekunden for wert in ergebnis.abweichungen] == [86400, -86400]


def test_externe_csv_bleibt_unveraendert_und_xlsx_oder_unsicherer_typ_wird_kontrolliert() -> None:
    original = b"case_id,plan\n1,2026-01-01\n"
    artefakt, daten = lese_externe_sollzeitdaten(
        projekt_id=uuid4(), dateiname="soll.csv", originalbytes=original
    )
    assert artefakt.originalbytes == original
    assert list(daten.columns) == ["case_id", "plan"]
    with pytest.raises(Domaenenfehler):
        lese_externe_sollzeitdaten(projekt_id=uuid4(), dateiname="soll.exe", originalbytes=original)


def test_externe_xlsx_wird_getrennt_und_unveraendert_gelesen() -> None:
    puffer = BytesIO()
    pd.DataFrame({"case_id": ["1"], "plan": ["2026-01-01"]}).to_excel(
        puffer, index=False, sheet_name="Soll"
    )
    original = puffer.getvalue()
    artefakt, daten = lese_externe_sollzeitdaten(
        projekt_id=uuid4(),
        dateiname="soll.xlsx",
        originalbytes=original,
        tabellenblatt="Soll",
    )
    assert artefakt.originalbytes == original
    assert daten.to_dict(orient="records") == [{"case_id": 1, "plan": "2026-01-01"}]


def test_leere_zuordnungsschluessel_werden_separat_ausgewiesen() -> None:
    soll = pd.DataFrame({"fall": ["1", ""], "plan": ["2026-01-03", "2026-01-04"]})
    config = ZeitvergleichKonfiguration(
        Vergleichsebene.FALL,
        "extern",
        "fall",
        "plan",
        "case_id",
        "timestamp",
        ist_activity_spalte="activity",
        ausgewaehlte_ist_aktivitaet="Ende",
    )

    ergebnis = zeitvergleich_berechnen(
        soll_daten=soll, event_log=_event_log(), konfiguration=config
    )

    assert ergebnis.nicht_zuordenbare_datensaetze == 1
    assert ergebnis.aggregierte_anzahlen["eindeutig_vergleichbar"] == 1
    assert ergebnis.fehlende_sollwerte == 1
