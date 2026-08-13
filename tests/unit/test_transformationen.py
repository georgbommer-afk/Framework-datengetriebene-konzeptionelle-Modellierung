"""Unit-Tests der Transformationen und Verknüpfungen gemäß Tabelle 3.11."""

from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd
import pytest

from framework_mvp.application.profiling import erstelle_datenprofil
from framework_mvp.application.transformation import (
    ermittle_ersatzwert_aus_profil,
    fuehre_join_aus,
    fuehre_transformationsplan_aus,
    pruefe_join,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    FRAMEWORKKONFORME_TRANSFORMATIONSARTEN,
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


def test_frameworkkonforme_transformationsarten_sind_explizit_begrenzt() -> None:
    assert FRAMEWORKKONFORME_TRANSFORMATIONSARTEN == (
        Transformationsart.DATENTYP_KONVERTIEREN,
        Transformationsart.WERTE_ERSETZEN,
        Transformationsart.EXAKTE_TUPEL_DUPLIKATE_ENTFERNEN,
        Transformationsart.VOLLSTAENDIG_LEERE_SPALTEN_ENTFERNEN,
        Transformationsart.ZEILEN_LOESCHEN,
        Transformationsart.TEXT_BEREINIGEN,
    )


@pytest.mark.parametrize(
    "art",
    [
        Transformationsart.SPALTENAUSWAHL,
        Transformationsart.UMBENENNEN,
        Transformationsart.FEHLWERTE_BEHANDELN,
        Transformationsart.DUPLIKATE_BEHANDELN,
        Transformationsart.AUSREISSER_BEHANDELN,
        Transformationsart.ZEILEN_FILTERN,
        Transformationsart.ABGELEITETE_SPALTE,
    ],
)
def test_legacy_transformationen_werden_geladen_aber_nicht_ausgefuehrt(
    art: Transformationsart,
) -> None:
    schritt = _schritt(art, ("a",), {"strategie": "Legacy"})
    assert not schritt.frameworkkonform
    with pytest.raises(Domaenenfehler, match="Legacy-Transformationsschritt"):
        fuehre_transformationsplan_aus(pd.DataFrame({"a": [1]}), _plan(schritt))


def test_transformationsplan_veraendert_ausgangsdaten_nicht() -> None:
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


def test_konvertierungsfehler_bricht_ohne_verlust_ab() -> None:
    daten = pd.DataFrame({"a": ["1", "nicht numerisch"]})
    schritt = _schritt(
        Transformationsart.DATENTYP_KONVERTIEREN,
        ("a",),
        {"zieltyp": "Ganzzahl", "fehlerverhalten": "Vorgang abbrechen"},
    )
    with pytest.raises(Domaenenfehler, match="1 Werte können nicht konvertiert"):
        fuehre_transformationsplan_aus(daten, _plan(schritt))
    assert daten["a"].tolist() == ["1", "nicht numerisch"]


@pytest.mark.parametrize(
    ("strategie", "erwartet"),
    [
        ("Minimum", 1.0),
        ("Maximum", 100.0),
        ("Arithmetisches Mittel", 22.0),
        ("Median", 3.0),
    ],
)
def test_numerische_ersatzwerte_stammen_reproduzierbar_aus_r(
    strategie: str, erwartet: float
) -> None:
    profil = asdict(
        erstelle_datenprofil(pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 100.0]})).spaltenprofile[0]
    )
    assert ermittle_ersatzwert_aus_profil(profil, strategie) == erwartet


def test_freier_wert_und_modus_stammen_aus_der_einheitlichen_wertersetzung() -> None:
    profil = asdict(
        erstelle_datenprofil(pd.DataFrame({"status": ["A", "A", "B", "NULL"]})).spaltenprofile[0]
    )
    assert ermittle_ersatzwert_aus_profil(profil, "Frei definierter Wert", "C") == "C"
    assert ermittle_ersatzwert_aus_profil(profil, "Häufigster Wert (Modus)") == "A"


@pytest.mark.parametrize(
    ("gesuchte_werte", "ersatzwert"),
    [
        (["einzelwert"], "frei"),
        (["NULL", "N/A"], "ersetzt"),
        ([100.0], 3.0),
    ],
)
def test_werte_ersetzen_behandelt_einzelwerte_platzhalter_und_ausreisser(
    gesuchte_werte: list[object], ersatzwert: object
) -> None:
    daten = pd.DataFrame({"wert": ["einzelwert", "NULL", "N/A", 100.0, "bleibt"]})
    schritt = _schritt(
        Transformationsart.WERTE_ERSETZEN,
        ("wert",),
        {"gesuchte_werte": gesuchte_werte, "ersatzwert": ersatzwert},
    )
    ergebnis = fuehre_transformationsplan_aus(daten, _plan(schritt))
    assert ergebnis.historie[0].ergebnis_oder_warnung == (f"{len(gesuchte_werte)} Werte ersetzt")
    assert all(wert not in ergebnis.daten["wert"].tolist() for wert in gesuchte_werte)


def test_duplikate_werden_nur_als_vollstaendige_tupel_entfernt() -> None:
    daten = pd.DataFrame({"id": [1, 1, 1], "wert": ["A", "A", "B"]})
    schritt = _schritt(
        Transformationsart.EXAKTE_TUPEL_DUPLIKATE_ENTFERNEN,
        (),
        {"betroffene_tupel": 1},
    )
    ergebnis = fuehre_transformationsplan_aus(daten, _plan(schritt))
    assert ergebnis.daten.to_dict("records") == [
        {"id": 1, "wert": "A"},
        {"id": 1, "wert": "B"},
    ]
    assert "1 zusätzliche Tupel" in ergebnis.historie[0].ergebnis_oder_warnung


def test_nur_tatsaechlich_vollstaendig_leere_spalten_werden_entfernt() -> None:
    daten = pd.DataFrame({"leer": [None, None], "platzhalter": ["NULL", "-"]})
    schritt = _schritt(
        Transformationsart.VOLLSTAENDIG_LEERE_SPALTEN_ENTFERNEN,
        ("leer",),
        {"vollstaendig_leere_spalten": ["leer"]},
    )
    ergebnis = fuehre_transformationsplan_aus(daten, _plan(schritt))
    assert list(ergebnis.daten.columns) == ["platzhalter"]


def test_durchlauf_ohne_transformation_ist_zulaessig() -> None:
    daten = pd.DataFrame({"a": [1, 2]})
    ergebnis = fuehre_transformationsplan_aus(daten, _plan())
    pd.testing.assert_frame_equal(ergebnis.daten, daten)
    assert ergebnis.historie == ()


@pytest.mark.parametrize(
    ("werte", "operator", "parameter", "verbleibend"),
    [
        (["A", "B"], "gleich", {"wert": "A"}, ["B"]),
        (["A", "B"], "ungleich", {"wert": "A"}, ["A"]),
        (["abc", "xyz"], "enthält", {"wert": "b"}, ["xyz"]),
        (["abc", "xbc"], "beginnt mit", {"wert": "a"}, ["xbc"]),
        (["abc", "abx"], "endet mit", {"wert": "c"}, ["abx"]),
        ([None, "A"], "ist leer", {}, ["A"]),
        ([None, "A"], "ist nicht leer", {}, [None]),
        ([1, 2], "kleiner", {"wert": 2}, [2]),
        ([1, 2], "kleiner oder gleich", {"wert": 1}, [2]),
        ([1, 2], "größer", {"wert": 1}, [1]),
        ([1, 2], "größer oder gleich", {"wert": 2}, [1]),
        ([1, 2, 3], "zwischen", {"von": 1, "bis": 2}, [3]),
        (["2025-01-01", "2025-01-03"], "vor", {"wert": "2025-01-02"}, ["2025-01-03"]),
        (["2025-01-01", "2025-01-03"], "nach", {"wert": "2025-01-02"}, ["2025-01-01"]),
        (
            ["2025-01-01", "2025-01-03", "2025-01-05"],
            "zeitlich zwischen",
            {"von": "2025-01-02", "bis": "2025-01-04"},
            ["2025-01-01", "2025-01-05"],
        ),
        (["A", "B", "C"], "enthalten in", {"werte": ["A", "C"]}, ["B"]),
        (["A", "B", "C"], "nicht enthalten in", {"werte": ["A", "C"]}, ["A", "C"]),
    ],
)
def test_zeilen_loeschen_deckt_operatorgruppen_ab(
    werte: list[object], operator: str, parameter: dict[str, object], verbleibend: list[object]
) -> None:
    daten = pd.DataFrame({"wert": werte, "beleg": range(len(werte))})
    original = daten.copy(deep=True)
    schritt = _schritt(
        Transformationsart.ZEILEN_LOESCHEN,
        ("wert",),
        {"operator": operator, **parameter},
    )

    ergebnis = fuehre_transformationsplan_aus(daten, _plan(schritt))

    tatsaechlich = ergebnis.daten["wert"].tolist()
    assert len(tatsaechlich) == len(verbleibend)
    assert all(
        pd.isna(ist) if soll is None else ist == soll
        for ist, soll in zip(tatsaechlich, verbleibend, strict=True)
    )
    assert ergebnis.historie[0].zeilen_vorher == len(werte)
    assert ergebnis.historie[0].zeilen_nachher == len(verbleibend)
    assert "Zeilen gelöscht" in ergebnis.historie[0].ergebnis_oder_warnung
    pd.testing.assert_frame_equal(daten, original)


@pytest.mark.parametrize(
    ("art", "parameter", "werte", "erwartet"),
    [
        ("Festen Präfix entfernen", {"praefix": "RS "}, ["RS TX", "AX"], ["TX", "AX"]),
        ("Festen Suffix entfernen", {"suffix": ".csv"}, ["a.csv", "b"], ["a", "b"]),
        (
            "Zwischen Begrenzern extrahieren",
            {"startbegrenzer": "(", "endbegrenzer": ")"},
            ["RS TX (abc)", "ohne Treffer"],
            ["abc", "ohne Treffer"],
        ),
    ],
)
def test_allgemeine_texttransformation_bewahrt_nichttreffer_und_eingangsdaten(
    art: str, parameter: dict[str, object], werte: list[str], erwartet: list[str]
) -> None:
    daten = pd.DataFrame({"text": werte})
    original = daten.copy(deep=True)
    schritt = _schritt(
        Transformationsart.TEXT_BEREINIGEN,
        ("text",),
        {"art": art, "nichttreffer": "Originalwert beibehalten", **parameter},
    )

    ergebnis = fuehre_transformationsplan_aus(daten, _plan(schritt))

    assert ergebnis.daten["text"].tolist() == erwartet
    pd.testing.assert_frame_equal(daten, original)


@pytest.mark.parametrize(
    ("join_art", "erwartete_zeilen", "datenverlust"),
    [
        ("INNER", 1, True),
        ("LEFT", 2, True),
        ("RIGHT", 2, True),
        ("OUTER", 3, False),
    ],
)
def test_alle_join_arten_pruefen_ihre_tatsaechliche_wirkung(
    join_art: str, erwartete_zeilen: int, datenverlust: bool
) -> None:
    links = pd.DataFrame({"id": [1, 2], "links": ["a", "b"]})
    rechts = pd.DataFrame({"id": [2, 3], "rechts": ["c", "d"]})
    pruefung = pruefe_join(links, rechts, ("id",), ("id",), join_art)
    assert pruefung.erwartete_zeilen == erwartete_zeilen
    assert pruefung.moeglicher_datenverlust is datenverlust
    ergebnis, ausgefuehrte_pruefung = fuehre_join_aus(
        links,
        rechts,
        join_art=join_art,
        linke_schluessel=("id",),
        rechte_schluessel=("id",),
    )
    assert len(ergebnis) == erwartete_zeilen
    assert ausgefuehrte_pruefung.join_art == join_art


@pytest.mark.parametrize(
    ("linke_ids", "rechte_ids", "kardinalitaet"),
    [
        ([1, 2], [1, 2], "1:1"),
        ([1, 2], [1, 1], "1:n"),
        ([1, 1], [1, 2], "n:1"),
        ([1, 1], [1, 1], "n:m"),
    ],
)
def test_join_kardinalitaeten(
    linke_ids: list[int], rechte_ids: list[int], kardinalitaet: str
) -> None:
    links = pd.DataFrame({"id": linke_ids})
    rechts = pd.DataFrame({"id": rechte_ids})
    assert pruefe_join(links, rechts, ("id",), ("id",)).kardinalitaet == kardinalitaet


def test_join_verhindert_unbestaetigte_zeilenvervielfachung() -> None:
    links = pd.DataFrame({"id": [1, 1], "links": ["a", "b"]})
    rechts = pd.DataFrame({"id": [1, 1], "rechts": ["c", "d"]})
    pruefung = pruefe_join(links, rechts, ("id",), ("id",))
    assert pruefung.moegliche_zeilenvervielfachung
    with pytest.raises(Domaenenfehler, match="ausdrücklich bestätigt"):
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


def test_join_prueft_schluesselanzahl_vorhandensein_typen_und_fehlwerte() -> None:
    links = pd.DataFrame({"id": pd.Series([1, None], dtype="Int64")})
    rechts = pd.DataFrame({"id": pd.Series([1, 2], dtype="Int64")})
    pruefung = pruefe_join(links, rechts, ("id",), ("id",))
    assert pruefung.fehlende_schluessel_links == 1
    assert pruefung.nicht_zuordenbar_rechts == 1
    with pytest.raises(Domaenenfehler, match="gleich viele"):
        pruefe_join(links, rechts, ("id",), ())
    with pytest.raises(Domaenenfehler, match="fehlt"):
        pruefe_join(links, rechts, ("unbekannt",), ("id",))
    with pytest.raises(Domaenenfehler, match="Datentypen"):
        pruefe_join(links, pd.DataFrame({"id": ["1", "2"]}), ("id",), ("id",))
