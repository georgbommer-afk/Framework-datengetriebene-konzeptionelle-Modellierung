"""Unit-Tests reproduzierbarer Transformationen und Tabellenverknüpfungen."""

from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd
import pytest

from framework_mvp.application.transformation import (
    fuehre_join_aus,
    fuehre_transformationsplan_aus,
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
