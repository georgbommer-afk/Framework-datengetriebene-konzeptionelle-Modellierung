"""Unit-Tests reproduzierbarer Transformationen und Tabellenverknüpfungen."""

from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd
import pytest

from framework_mvp.application.transformation import (
    fuehre_join_aus,
    fuehre_transformationsplan_aus,
    kombiniere_textspalten,
    pruefe_join,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Transformationsart,
    Transformationsplan,
    Transformationsschritt,
)


def _schritt(
    art: Transformationsart,
    spalten: tuple[str, ...],
    parameter: dict[str, object],
    reihenfolge: int = 1,
) -> Transformationsschritt:
    return Transformationsschritt.neu(
        typ=art,
        betroffene_spalten=spalten,
        parameter=parameter,
        reihenfolge=reihenfolge,
        beschreibung=art.value,
    )


def _plan(*schritte: Transformationsschritt) -> Transformationsplan:
    jetzt = datetime.now(UTC)
    return Transformationsplan(uuid4(), uuid4(), (uuid4(),), schritte, jetzt, jetzt)


def test_transformationsplan_veraendert_ausgangsdaten_nicht() -> None:
    """Ausführung arbeitet auf einer tiefen Kopie und protokolliert die Wirkung."""
    daten = pd.DataFrame({"a": ["1", "2"], "b": ["x", "y"]})
    original = daten.copy(deep=True)
    schritt = _schritt(
        Transformationsart.DATENTYP_KONVERTIEREN,
        ("a",),
        {"zieltyp": "Ganzzahl", "fehlerverhalten": "Vorgang abbrechen"},
    )
    ergebnis = fuehre_transformationsplan_aus(daten, _plan(schritt))
    pd.testing.assert_frame_equal(daten, original)
    assert str(ergebnis.daten["a"].dtype) == "Int64"
    assert ergebnis.historie[0].zeilen_vorher == 2


def test_fehlwerte_duplikate_filter_und_abgeleitete_spalte() -> None:
    """Geordnete Schritte wirken nachvollziehbar auf das vollständige Ergebnis."""
    daten = pd.DataFrame({"id": [1, 1, 2], "wert": [None, None, 4]})
    schritte = (
        _schritt(
            Transformationsart.FEHLWERTE_BEHANDELN,
            ("wert",),
            {"strategie": "Festen Wert einsetzen", "wert": 2},
            1,
        ),
        _schritt(
            Transformationsart.DUPLIKATE_BEHANDELN,
            ("id", "wert"),
            {"strategie": "Entfernen", "behalten": "Erstes Vorkommen"},
            2,
        ),
        _schritt(
            Transformationsart.ZEILEN_FILTERN,
            ("wert",),
            {"operator": "größer oder gleich", "wert": 2},
            3,
        ),
        _schritt(
            Transformationsart.ABGELEITETE_SPALTE,
            (),
            {"zielspalte": "quelle", "art": "Konstante", "wert": "Test"},
            4,
        ),
    )
    ergebnis = fuehre_transformationsplan_aus(daten, _plan(*schritte))
    assert ergebnis.daten.to_dict("records") == [
        {"id": 1, "wert": 2.0, "quelle": "Test"},
        {"id": 2, "wert": 4.0, "quelle": "Test"},
    ]


def test_join_prueft_kardinalitaet_und_verhindert_unbestaetigtes_n_zu_m() -> None:
    """n:m-Verknüpfungen benötigen vor der Ausführung eine ausdrückliche Bestätigung."""
    links = pd.DataFrame({"id": [1, 1], "links": ["a", "b"]})
    rechts = pd.DataFrame({"id": [1, 1], "rechts": ["c", "d"]})
    pruefung = pruefe_join(links, rechts, ("id",), ("id",))
    assert pruefung.kardinalitaet == "n:m"
    assert pruefung.erwartete_zeilen == 4
    with pytest.raises(Domaenenfehler):
        fuehre_join_aus(
            links,
            rechts,
            join_art="INNER",
            linke_schluessel=("id",),
            rechte_schluessel=("id",),
        )
    ergebnis, _ = fuehre_join_aus(
        links,
        rechts,
        join_art="INNER",
        linke_schluessel=("id",),
        rechte_schluessel=("id",),
        nm_bestaetigt=True,
    )
    assert len(ergebnis) == 4


def test_textspalten_werden_ohne_technische_fehlwerttexte_kombiniert() -> None:
    """None, NaN und Platzhalter gelangen nicht als technische Texte ins Ergebnis."""
    daten = pd.DataFrame(
        {
            "von": ["C01", None, "NULL"],
            "zu": ["MAS", "Z02", pd.NA],
            "bereich": ["A", "B", "C"],
        }
    )
    kombiniert = kombiniere_textspalten(
        daten,
        ("von", "zu", "bereich"),
        trennzeichen=" → ",
        praefix="von ",
        suffix="",
        fehlwertstrategie="Nur vorhandene Bestandteile kombinieren",
    )
    assert kombiniert.tolist() == [
        "von C01 → MAS → A",
        "von Z02 → B",
        "von C",
    ]
    assert all("None" not in wert and "nan" not in wert for wert in kombiniert)


def test_textspaltenkombination_kann_bei_fehlwert_leer_bleiben() -> None:
    """Die strenge Strategie erzeugt bei einem fehlenden Bestandteil einen Fehlwert."""
    daten = pd.DataFrame({"von": ["A", None], "zu": ["B", "C"]})
    kombiniert = kombiniere_textspalten(
        daten,
        ("von", "zu"),
        trennzeichen=" - ",
        fehlwertstrategie="Ergebnis leer lassen",
    )
    assert kombiniert.iloc[0] == "A - B"
    assert pd.isna(kombiniert.iloc[1])


def test_textspaltenkombination_ist_reproduzierbar_im_plan() -> None:
    """Die UI-Parameter werden durch die bestehende Planstruktur vollständig ausgeführt."""
    daten = pd.DataFrame({"von": ["A"], "zu": ["B"]})
    schritt = _schritt(
        Transformationsart.ABGELEITETE_SPALTE,
        ("von", "zu"),
        {
            "zielspalte": "Transportweg",
            "art": "Textspalten kombinieren",
            "quellspalten": ["von", "zu"],
            "trennzeichen": " → ",
            "praefix": "",
            "suffix": "",
            "fehlwertstrategie": "Nur vorhandene Bestandteile kombinieren",
            "ersatztext": "",
            "originalspalten_behalten": False,
        },
    )
    ergebnis = fuehre_transformationsplan_aus(daten, _plan(schritt))
    assert ergebnis.daten.to_dict("records") == [{"Transportweg": "A → B"}]


def test_werte_koennen_exakt_oder_normalisiert_ersetzt_werden() -> None:
    """Die typisierte Wertersetzung unterscheidet exakte und normalisierte Treffer."""
    daten = pd.DataFrame({"status": [" offen ", "OFFEN", "geschlossen"]})
    schritt = _schritt(
        Transformationsart.WERTE_ERSETZEN,
        ("status",),
        {
            "gesuchter_wert": "offen",
            "ersatzwert": "in Arbeit",
            "normalisierte_uebereinstimmung": True,
        },
    )
    ergebnis = fuehre_transformationsplan_aus(daten, _plan(schritt))
    assert ergebnis.daten["status"].tolist() == [
        "in Arbeit",
        "in Arbeit",
        "geschlossen",
    ]
