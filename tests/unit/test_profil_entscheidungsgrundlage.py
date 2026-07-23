"""Tests der profilgestützten Transformationsentscheidung."""

from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd

from framework_mvp.application.datenimport_service import DatenimportService
from framework_mvp.application.profiling.entscheidungsgrundlage import (
    bereite_gemischte_anzeigetabelle,
    ermittle_auffaelligkeiten,
    fachlich_zulaessige_fehlwertstrategien,
    filtere_auffaelligkeiten,
    transformationsart_fuer_auffaelligkeit,
    vergleiche_profile,
)
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.models import Transformationsart, Transformationsplan


def _profil(daten: pd.DataFrame) -> dict[str, object]:
    return asdict(DatenimportService().profil_erstellen(daten).profil)


def test_auffaelligkeiten_werden_korrekten_spalten_zugeordnet() -> None:
    """Fehlwerte, Platzhalter und Ausreißer bleiben spaltenbezogen unterscheidbar."""
    daten = pd.DataFrame(
        {
            "wert": [1.0, 2.0, 3.0, 100.0, None],
            "text": ["ok", "NULL", "N/A", "ok", "ok"],
        }
    )
    auffaelligkeiten = ermittle_auffaelligkeiten(_profil(daten), daten)
    paare = {(wert.spaltenname, wert.art) for wert in auffaelligkeiten if wert.anzahl}
    assert ("wert", "Fehlwerte") in paare
    assert ("wert", "Ausreißer") in paare
    assert ("text", "Platzhalter") in paare
    platzhalter = next(wert for wert in auffaelligkeiten if wert.art == "Platzhalter")
    assert "NULL: 1" in platzhalter.detailwerte
    assert "N/A: 1" in platzhalter.detailwerte


def test_filter_nur_spalten_mit_auffaelligkeiten() -> None:
    """Der Filter entfernt reine Datentyphinweise ohne positiven Befund."""
    daten = pd.DataFrame({"a": [1, None], "b": ["x", "y"]})
    alle = ermittle_auffaelligkeiten(_profil(daten), daten)
    gefiltert = filtere_auffaelligkeiten(alle, nur_mit_befund=True, arten=("Fehlwerte",))
    assert [(wert.spaltenname, wert.art) for wert in gefiltert] == [("a", "Fehlwerte")]


def test_median_wird_nur_fuer_numerische_spalten_angeboten() -> None:
    """Statistische Ersetzungen sind für kategoriale Spalten ausgeschlossen."""
    profil = _profil(pd.DataFrame({"zahl": [1, None], "text": ["a", None]}))
    assert "Median einsetzen" in fachlich_zulaessige_fehlwertstrategien(profil, ("zahl",))
    assert "Median einsetzen" not in fachlich_zulaessige_fehlwertstrategien(profil, ("text",))


def test_vorher_nachher_vergleich_zeigt_korrekte_veraenderung_ohne_mutation() -> None:
    """Profilvergleich verändert das bestätigte Ausgangsprofil nicht."""
    vorher = _profil(pd.DataFrame({"a": [1, None, None]}))
    kopie = dict(vorher)
    nachher = _profil(pd.DataFrame({"a": [1, 0, 0]}))
    vergleich = {wert["Kennzahl"]: wert for wert in vergleiche_profile(vorher, nachher)}
    assert vergleich["Echte Fehlwerte"]["Absolute Veränderung"] == -2
    assert vorher == kopie


def test_geaenderter_transformationsplan_invalidiert_cache_schluessel() -> None:
    """Der vollständige Plan einschließlich Änderungszeitpunkt bestimmt den Schlüssel."""
    jetzt = datetime.now(UTC)
    plan = Transformationsplan(uuid4(), uuid4(), (uuid4(),), (), jetzt, jetzt)
    geaendert = Transformationsplan(
        plan.transformationsplan_id,
        plan.projekt_id,
        plan.import_ids,
        (),
        plan.erstellt_am,
        datetime.now(UTC),
    )
    assert TransformationsService.profil_cache_schluessel(
        plan
    ) != TransformationsService.profil_cache_schluessel(geaendert)


def test_direkte_aktion_liefert_nur_formularvorauswahl() -> None:
    """Die Befundaktion erzeugt keinen Schritt und verändert keinen Transformationsplan."""
    jetzt = datetime.now(UTC)
    plan = Transformationsplan(uuid4(), uuid4(), (uuid4(),), (), jetzt, jetzt)
    art = transformationsart_fuer_auffaelligkeit("Ausreißer")
    assert art is Transformationsart.AUSREISSER_BEHANDELN
    assert plan.schritte == ()


def test_gemischte_anzeigewerte_sind_arrow_kompatible_texte() -> None:
    """Ganzzahl, Dezimalzahl, Text und None werden ohne fachliche Rundung vereinheitlicht."""
    tabelle = bereite_gemischte_anzeigetabelle(
        (
            ("Ganzzahl", 12, 10),
            ("Fließkommazahl", 1.23456789, 2.5),
            ("Text", "int64", "string"),
            ("Leer", None, None),
        )
    )
    assert all(str(typ) == "string" for typ in tabelle.dtypes)
    assert tabelle["Vorher"].tolist() == ["12", "1.23456789", "int64", "–"]
