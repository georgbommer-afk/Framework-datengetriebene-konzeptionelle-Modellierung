"""Tests für P_Soll, Aktivitätsmapping und Token-Based Replay."""

import re
from datetime import date
from uuid import uuid4

import pandas as pd
import pytest

from framework_mvp.application.ergebnisaggregation.sollprozess import (
    erstelle_aktivitaetsmapping,
    erzeuge_lineares_sollmodell,
    fitness_gleichung_3_13,
    token_replay,
    validiere_pnml_sollmodell,
)
from framework_mvp.domain.exceptions import Domaenenfehler


def _linear(projekt_id=None):  # type: ignore[no-untyped-def]
    return erzeuge_lineares_sollmodell(
        projekt_id=projekt_id or uuid4(),
        aktivitaeten=("A", "B"),
        bezeichnung="Soll A-B",
        fachliche_grundlage="Freigegebene Arbeitsanweisung 7",
        modellversion="1.0",
        person="Fachverantwortliche Person",
        freigabedatum=date(2026, 8, 9),
        menschlich_bestaetigt=True,
    )


def test_linearer_assistent_erzeugt_gueltiges_workflow_netz_und_bewahrt_reihenfolge() -> None:
    modell = _linear()
    assert modell.workflow_netz and modell.sound
    assert modell.sichtbare_transitionen == ("A", "B")
    assert modell.original_pnml == modell.replay_pnml
    assert modell.original_pnml.startswith(b"<?xml")
    assert _linear().original_pnml == modell.original_pnml


@pytest.mark.parametrize("aktivitaeten", [(), ("",), ("A", "A")])
def test_linearer_assistent_blockiert_leere_und_wiederholte_aktivitaeten(
    aktivitaeten: tuple[str, ...],
) -> None:
    with pytest.raises(Domaenenfehler):
        erzeuge_lineares_sollmodell(
            projekt_id=uuid4(),
            aktivitaeten=aktivitaeten,
            bezeichnung="Soll",
            fachliche_grundlage="Quelle",
            modellversion="1",
            person="Person",
            freigabedatum=date.today(),
            menschlich_bestaetigt=True,
        )


def test_pnml_upload_bleibt_unveraendert_und_wird_vollstaendig_validiert() -> None:
    projekt_id = uuid4()
    original = _linear(projekt_id).original_pnml
    geladen = validiere_pnml_sollmodell(
        projekt_id=projekt_id,
        dateiname="woped-export.pnml",
        originalbytes=original,
        bezeichnung="WoPeD Soll",
        fachliche_grundlage="Freigegebene Prozessdokumentation",
        modellversion="2",
        person="Prüfperson",
        freigabedatum=date.today(),
        menschlich_bestaetigt=True,
        markierungsableitung_bestaetigt=False,
    )
    assert geladen.original_pnml == original
    assert geladen.metadaten.sha256
    assert geladen.sichtbare_transitionen == ("A", "B")


def test_pnml_mit_woped_werkzeugerweiterung_wird_importiert() -> None:
    projekt_id = uuid4()
    original = _linear(projekt_id).original_pnml.replace(
        b"</net>",
        b'<toolspecific tool="WoPeD" version="1.0">'
        b'<bounds x="0" y="0" width="900" height="600" />'
        b"</toolspecific></net>",
    )

    geladen = validiere_pnml_sollmodell(
        projekt_id=projekt_id,
        dateiname="woped-next-export.pnml",
        originalbytes=original,
        bezeichnung="WoPeD Soll mit Erweiterung",
        fachliche_grundlage="Freigegebene Prozessdokumentation",
        modellversion="2",
        person="Prüfperson",
        freigabedatum=date.today(),
        menschlich_bestaetigt=True,
        markierungsableitung_bestaetigt=False,
    )

    assert geladen.original_pnml == original
    assert geladen.sichtbare_transitionen == ("A", "B")


def test_eindeutig_ableitbare_markierungen_erfordern_menschliche_bestaetigung() -> None:
    projekt_id = uuid4()
    original = _linear(projekt_id).original_pnml
    ohne_markierungen = re.sub(
        rb"<initialMarking>.*?</initialMarking>", b"", original, flags=re.DOTALL
    )
    ohne_markierungen = re.sub(
        rb"<finalmarkings>.*?</finalmarkings>", b"", ohne_markierungen, flags=re.DOTALL
    )
    parameter = {
        "projekt_id": projekt_id,
        "dateiname": "ohne-markierungen.pnml",
        "originalbytes": ohne_markierungen,
        "bezeichnung": "Soll",
        "fachliche_grundlage": "Quelle",
        "modellversion": "1",
        "person": "Person",
        "freigabedatum": date.today(),
        "menschlich_bestaetigt": True,
    }
    with pytest.raises(Domaenenfehler, match="menschlich bestätigt"):
        validiere_pnml_sollmodell(
            **parameter,
            markierungsableitung_bestaetigt=False,
        )
    modell = validiere_pnml_sollmodell(
        **parameter,
        markierungsableitung_bestaetigt=True,
    )
    assert modell.markierungen_abgeleitet
    assert modell.original_pnml == ohne_markierungen
    assert modell.replay_pnml != ohne_markierungen


@pytest.mark.parametrize(
    "inhalt",
    (
        b"",
        b"<!DOCTYPE pnml [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><pnml>&x;</pnml>",
        b"<not-pnml/>",
    ),
)
def test_ungueltige_oder_unsichere_pnml_wird_abgewiesen(inhalt: bytes) -> None:
    with pytest.raises(Domaenenfehler):
        validiere_pnml_sollmodell(
            projekt_id=uuid4(),
            dateiname="modell.pnml",
            originalbytes=inhalt,
            bezeichnung="Soll",
            fachliche_grundlage="Quelle",
            modellversion="1",
            person="Person",
            freigabedatum=date.today(),
            menschlich_bestaetigt=True,
            markierungsableitung_bestaetigt=False,
        )


def test_uebergrosse_pnml_wird_vor_xml_import_abgewiesen() -> None:
    with pytest.raises(Domaenenfehler, match="10 MB"):
        validiere_pnml_sollmodell(
            projekt_id=uuid4(),
            dateiname="zu-gross.pnml",
            originalbytes=b"<pnml>" + b" " * (10 * 1024 * 1024) + b"</pnml>",
            bezeichnung="Soll",
            fachliche_grundlage="Quelle",
            modellversion="1",
            person="Person",
            freigabedatum=date.today(),
            menschlich_bestaetigt=True,
            markierungsableitung_bestaetigt=False,
        )


def test_mapping_ist_exakt_oder_menschlich_und_replay_verwendet_vollstaendiges_log() -> None:
    projekt_id = uuid4()
    modell = _linear(projekt_id)
    mapping = erstelle_aktivitaetsmapping(
        projekt_id=projekt_id,
        sollmodell_id=modell.metadaten.sollmodell_id,
        event_aktivitaeten=("Anfang", "B"),
        modell_transitionen=("A", "B"),
        manuelle_zuordnungen={"Anfang": "A"},
        menschlich_bestaetigt=True,
    )
    log = pd.DataFrame(
        {
            "case_id": ["1", "1", "2"],
            "activity": ["Anfang", "B", "Anfang"],
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-01"], utc=True),
        }
    )
    vorher = log.copy(deep=True)
    ergebnis = token_replay(event_log=log, sollmodell=modell, mapping=mapping)
    assert len(ergebnis.fallbezogene_diagnosen) == 2
    assert ergebnis.produzierte_tokens == 5
    assert ergebnis.konsumierte_tokens == 5
    assert ergebnis.fehlende_tokens == 1
    assert ergebnis.verbleibende_tokens == 1
    assert ergebnis.fitness == pytest.approx(0.8)
    assert ergebnis.fitness_plausibilisierung_pm4py is not None
    pd.testing.assert_frame_equal(log, vorher)


def test_exakte_zuordnung_ist_automatisch_und_unbeobachtete_solltransition_bleibt() -> None:
    projekt_id = uuid4()
    modell = _linear(projekt_id)

    mapping = erstelle_aktivitaetsmapping(
        projekt_id=projekt_id,
        sollmodell_id=modell.metadaten.sollmodell_id,
        event_aktivitaeten=("A",),
        modell_transitionen=("A", "B"),
        manuelle_zuordnungen={},
        menschlich_bestaetigt=True,
    )

    assert mapping.exakte_zuordnungen == (("A", "A"),)
    assert mapping.nur_event_log == ()
    assert mapping.nur_sollmodell == ("B",)


def test_abweichender_name_bleibt_bis_zur_manuellen_zuordnung_offen() -> None:
    projekt_id = uuid4()
    modell = _linear(projekt_id)

    offen = erstelle_aktivitaetsmapping(
        projekt_id=projekt_id,
        sollmodell_id=modell.metadaten.sollmodell_id,
        event_aktivitaeten=("QG", "B"),
        modell_transitionen=("Qualitätsprüfung", "B"),
        manuelle_zuordnungen={},
        menschlich_bestaetigt=True,
    )
    bestaetigt = erstelle_aktivitaetsmapping(
        projekt_id=projekt_id,
        sollmodell_id=modell.metadaten.sollmodell_id,
        event_aktivitaeten=("QG", "B"),
        modell_transitionen=("Qualitätsprüfung", "B"),
        manuelle_zuordnungen={"QG": "Qualitätsprüfung"},
        menschlich_bestaetigt=True,
    )

    assert offen.nur_event_log == ("QG",)
    assert offen.nur_sollmodell == ("Qualitätsprüfung",)
    assert bestaetigt.manuelle_zuordnungen == (("QG", "Qualitätsprüfung"),)
    assert bestaetigt.nur_event_log == ()


def test_fehlende_menschliche_mappingbestaetigung_blockiert_replay() -> None:
    projekt_id = uuid4()
    modell = _linear(projekt_id)
    mapping = erstelle_aktivitaetsmapping(
        projekt_id=projekt_id,
        sollmodell_id=modell.metadaten.sollmodell_id,
        event_aktivitaeten=("A", "B"),
        modell_transitionen=("A", "B"),
        manuelle_zuordnungen={},
        menschlich_bestaetigt=False,
    )
    log = pd.DataFrame(
        {
            "case_id": ["1", "1"],
            "activity": ["A", "B"],
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
        }
    )

    with pytest.raises(Domaenenfehler, match="menschlich bestätigt"):
        token_replay(event_log=log, sollmodell=modell, mapping=mapping)


def test_nicht_zugeordnete_aktivitaet_blockiert_replay_ohne_filterung() -> None:
    projekt_id = uuid4()
    modell = _linear(projekt_id)
    mapping = erstelle_aktivitaetsmapping(
        projekt_id=projekt_id,
        sollmodell_id=modell.metadaten.sollmodell_id,
        event_aktivitaeten=("A", "X"),
        modell_transitionen=("A", "B"),
        manuelle_zuordnungen={},
        menschlich_bestaetigt=True,
    )
    log = pd.DataFrame(
        {
            "case_id": ["1", "1"],
            "activity": ["A", "X"],
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
        }
    )
    with pytest.raises(Domaenenfehler, match="Nicht zugeordnete"):
        token_replay(event_log=log, sollmodell=modell, mapping=mapping)


def test_fitness_gleichung_3_13_und_undefinierte_nenner() -> None:
    assert fitness_gleichung_3_13(
        produzierte_tokens=10,
        konsumierte_tokens=10,
        fehlende_tokens=2,
        verbleibende_tokens=4,
    ) == pytest.approx(0.7)
    assert (
        fitness_gleichung_3_13(
            produzierte_tokens=0,
            konsumierte_tokens=0,
            fehlende_tokens=0,
            verbleibende_tokens=0,
        )
        is None
    )
