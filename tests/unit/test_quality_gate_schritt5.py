"""Fachliche Unit-Tests von Tabelle 3.14 und Pseudocode 5."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd
import pytest

from framework_mvp.application.datenqualitaet import QualityGateKontext, pruefe_quality_gate
from framework_mvp.application.event_log_service import EventLogKontext
from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    CsvImportparameter,
    Dateityp,
    Datenquelle,
    EventLogArtefakt,
    EventLogStatus,
    FachlicheEntscheidung,
    Importvorgang,
    Mappingeintrag,
    MappingModus,
    Mappingstatus,
    Mappingtabelle,
    Mappingzustand,
    Profilzusammenfassung,
    QualityGateBereich,
    QualityGateStatus,
    Quellenart,
    Quellsystemtyp,
    SemantischesMapping,
    ZeitstempelZuordnung,
    ZusammengesetzteFallId,
    Zwischendatensatz,
)


def _kontext(
    *,
    t_daten: pd.DataFrame | None = None,
    e_daten: pd.DataFrame | None = None,
) -> QualityGateKontext:
    projekt_id, t_id, config_id, event_id, import_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    jetzt = datetime.now(UTC)
    t_daten = (
        t_daten
        if t_daten is not None
        else pd.DataFrame(
            {
                "fall": ["A", "A"],
                "aktion": ["Start", "Ende"],
                "zeit": ["2025-01-01", "2025-01-02"],
                "unbenutzt": [None, None],
            }
        )
    )
    e_daten = (
        e_daten
        if e_daten is not None
        else pd.DataFrame(
            {
                "case_id": ["A", "A"],
                "activity": ["Start", "Ende"],
                "timestamp": pd.to_datetime(["2025-01-01", "2025-01-02"]),
                "event_id": ["e1", "e2"],
                "_source_row": [0, 1],
                "_source_case_id_raw": ["A", "A"],
                "_source_activity_raw": ["Start", "Ende"],
                "_source_timestamp_raw": ["2025-01-01", "2025-01-02"],
                "_source_timestamp_column": ["zeit", "zeit"],
            }
        )
    )
    datensatz = Zwischendatensatz(
        t_id,
        projekt_id,
        uuid4(),
        (import_id,),
        "projects/p/interim/t.csv.gz",
        "projects/p/interim/t.schema.json",
        "projects/p/interim/t.transformation.json",
        "a" * 64,
        len(t_daten),
        len(t_daten.columns),
        jetzt,
    )
    config = SemantischesMapping(
        config_id,
        projekt_id,
        t_id,
        MappingModus.EREIGNISORIENTIERT,
        ZusammengesetzteFallId(("fall",)),
        "aktion",
        "zeit",
        "",
        "",
        "",
        "",
        (),
        (),
        None,
        jetzt,
        jetzt,
        Mappingstatus.VALIDIERT,
        Aktivitaetsdefinition(Aktivitaetsbildungsart.VORHANDENE_SPALTE, ("aktion",)),
        None,
        2,
    )
    artefakt = EventLogArtefakt(
        event_id,
        projekt_id,
        t_id,
        config_id,
        EventLogStatus.ERZEUGT,
        len(e_daten),
        len(set(e_daten["case_id"].dropna().astype(str))) if "case_id" in e_daten else 0,
        len(set(e_daten["activity"].dropna().astype(str))) if "activity" in e_daten else 0,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 2, tzinfo=UTC),
        "projects/p/event_logs/e.csv.gz",
        "projects/p/event_logs/e.schema.json",
        "projects/p/event_logs/e.lineage.json",
        "",
        "b" * 64,
        jetzt,
    )
    lineage = {
        "projekt_id": str(projekt_id),
        "zwischendatensatz_id": str(t_id),
        "mapping_id": str(config_id),
        "mappingtabelle_id": None,
        "herkunft_standardspalten": {
            "case_id": "fall",
            "activity": "aktion",
            "timestamp": "zeit",
        },
        "angewandte_fachliche_zuordnungen": [],
    }
    quelle = Datenquelle.neu(
        projekt_id=projekt_id,
        bezeichnung="ERP-Export",
        quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
        quellenart=Quellenart.CSV,
        konkretes_quellsystem="ERP Produktivsystem",
        fachliche_beschreibung="Produktionsaufträge",
        herkunft_oder_verantwortungsbereich="Produktionsplanung",
    )
    importvorgang = Importvorgang.bestaetigt(
        projekt_id=projekt_id,
        datenquellen_id=quelle.datenquellen_id,
        originaldateiname="auftrag.csv",
        sicherer_dateiname="auftrag.csv",
        dateityp=Dateityp.CSV,
        dateigroesse_bytes=10,
        sha256="c" * 64,
        importparameter=CsvImportparameter(erkanntes_trennzeichen=","),
        tabellenbezeichnung="auftrag.csv",
        zeilenanzahl=len(t_daten),
        spaltenanzahl=len(t_daten.columns),
        profil_version=1,
        relativer_raw_pfad="projects/p/raw/c/auftrag.csv",
        relativer_profil_pfad="projects/p/profiles/i.json",
        profilzusammenfassung=Profilzusammenfassung(0, 0, 0, 0),
        import_id=import_id,
    )
    event_kontext = EventLogKontext(
        artefakt,
        e_daten,
        config,
        datensatz,
        t_daten,
        None,
        {"sha256": artefakt.sha256},
        lineage,
    )
    return QualityGateKontext(event_kontext, (quelle,), (importvorgang,))


def _bestaetigungen() -> tuple[FachlicheEntscheidung, ...]:
    return (
        FachlicheEntscheidung("q_nachvollziehbar", False, "Herkunft ist nachvollziehbar."),
        FachlicheEntscheidung("e_interpretierbar", False, "Mindestbestandteile sind eindeutig."),
    )


def _mit_mapping(kontext: QualityGateKontext, mapping: Mappingtabelle) -> QualityGateKontext:
    """Verknüpft ein bestätigtes M genauso, wie Schritt 4 es in der Lineage speichert."""
    config = replace(kontext.event_log.konfiguration, mappingtabelle_id=mapping.mapping_id)
    lineage = dict(kontext.event_log.lineage)
    lineage["mappingtabelle_id"] = str(mapping.mapping_id)
    lineage["angewandte_fachliche_zuordnungen"] = [
        {
            "mappingeintrag_id": str(eintrag.mappingeintrag_id),
            "art": eintrag.art.value,
            "technische_bezeichnung": eintrag.technische_bezeichnung,
            "fachliche_bezeichnung": eintrag.fachliche_bezeichnung,
            "technische_quellspalte": eintrag.technische_quellspalte,
            "technischer_datentyp": (
                eintrag.wertreferenz.technischer_datentyp
                if eintrag.wertreferenz is not None
                else ""
            ),
            "technischer_wert_json": (
                eintrag.wertreferenz.wert_json if eintrag.wertreferenz is not None else ""
            ),
        }
        for eintrag in mapping.eintraege
    ]
    event = replace(
        kontext.event_log,
        konfiguration=config,
        mappingtabelle=mapping,
        lineage=lineage,
    )
    return replace(kontext, event_log=event, mappingtabelle_sha256="d" * 64)


def test_vollstaendige_kette_wird_ohne_score_und_ohne_mutation_freigabefaehig() -> None:
    kontext = _kontext()
    t_vorher = kontext.event_log.zwischendaten.copy(deep=True)
    e_vorher = kontext.event_log.ereignisse.copy(deep=True)
    q_vorher = deepcopy(kontext.datenquellen)

    ergebnis, _ = pruefe_quality_gate(kontext, _bestaetigungen())

    assert ergebnis.freigabe_moeglich
    assert {wert.bereich for wert in ergebnis.befunde} == set(QualityGateBereich)
    assert not ergebnis.rueckspruenge
    assert not hasattr(ergebnis, "score")
    pd.testing.assert_frame_equal(kontext.event_log.zwischendaten, t_vorher)
    pd.testing.assert_frame_equal(kontext.event_log.ereignisse, e_vorher)
    assert kontext.datenquellen == q_vorher
    assert {wert.technische_bezeichnung for wert in ergebnis.spaltenpruefungen} == {
        "fall",
        "aktion",
        "zeit",
    }


def test_fehlende_und_uninterpretierbare_e_werte_bleiben_getrennt_und_blockieren() -> None:
    ereignisse = pd.DataFrame(
        {
            "case_id": ["A", " "],
            "activity": ["Start", None],
            "timestamp": [pd.NaT, pd.NaT],
            "event_id": ["e1", "e2"],
            "_source_row": [0, 1],
            "_source_case_id_raw": ["A", " "],
            "_source_activity_raw": ["Start", None],
            "_source_timestamp_raw": ["", "keine Zeit"],
            "_source_timestamp_column": ["zeit", "zeit"],
        }
    )
    ergebnis, _ = pruefe_quality_gate(_kontext(e_daten=ereignisse), _bestaetigungen())
    nach_id = {wert.kriterium_id: wert for wert in ergebnis.befunde}

    assert not ergebnis.freigabe_moeglich
    assert nach_id["e_zeit_fehlt"].betroffene_ereignisse == 1
    assert nach_id["e_zeit_uninterpretierbar"].betroffene_ereignisse == 1
    assert nach_id["e_wert_fehlt:case_id"].nicht_uebersteuerbar
    assert 2 in ergebnis.rueckspruenge


def test_unbewertete_oder_als_mangel_bewertete_fachfrage_verhindert_freigabe() -> None:
    offen, _ = pruefe_quality_gate(_kontext())
    assert not offen.freigabe_moeglich
    assert any(
        wert.status is QualityGateStatus.FACHLICHE_BESTAETIGUNG_ERFORDERLICH
        for wert in offen.befunde
    )
    mangel, _ = pruefe_quality_gate(
        _kontext(),
        (
            FachlicheEntscheidung("q_nachvollziehbar", True, "Herkunft ist nicht eindeutig."),
            FachlicheEntscheidung("e_interpretierbar", False, "E ist fachlich interpretierbar."),
        ),
    )
    assert not mangel.freigabe_moeglich
    assert mangel.rueckspruenge == (1,)


def test_fachlich_nicht_interpretierbares_e_verwendet_begruendete_ursachenauswahl() -> None:
    ergebnis, _ = pruefe_quality_gate(
        _kontext(),
        (
            FachlicheEntscheidung("q_nachvollziehbar", False, "Q ist nachvollziehbar."),
            FachlicheEntscheidung(
                "e_interpretierbar",
                True,
                "Die Aktivitätswerte benötigen eine fachliche Zuordnung in M.",
                3,
            ),
        ),
    )
    assert ergebnis.rueckspruenge == (3,)
    assert (
        next(
            wert for wert in ergebnis.befunde if wert.kriterium_id == "e_interpretierbar"
        ).begruendung
        == "Die Aktivitätswerte benötigen eine fachliche Zuordnung in M."
    )


def test_unbenutzte_t_spalte_wird_nicht_pauschal_als_pflichtfeld_geprueft() -> None:
    ergebnis, _ = pruefe_quality_gate(_kontext(), _bestaetigungen())
    assert "unbenutzt" not in {wert.technische_bezeichnung for wert in ergebnis.spaltenpruefungen}


def test_q_prueft_nur_verwendete_quellen_und_fehlender_eintrag_fuehrt_zu_schritt_eins() -> None:
    kontext = _kontext()
    unbenutzte_quelle = replace(kontext.datenquellen[0], datenquellen_id=uuid4())
    mit_unbenutzter = replace(kontext, datenquellen=(*kontext.datenquellen, unbenutzte_quelle))
    ergebnis, snapshot = pruefe_quality_gate(mit_unbenutzter, _bestaetigungen())
    assert ergebnis.freigabe_moeglich
    assert len(snapshot) == 1
    assert unbenutzte_quelle.datenquellen_id not in ergebnis.datenquellen_ids

    ohne_q = replace(kontext, datenquellen=())
    mangel, _ = pruefe_quality_gate(
        ohne_q,
        (FachlicheEntscheidung("e_interpretierbar", False, "E ist interpretierbar."),),
    )
    assert 1 in mangel.rueckspruenge
    assert any(wert.kriterium_id.startswith("q_quelle_fehlt:") for wert in mangel.befunde)


def test_optionale_legacy_quellenfelder_blockieren_die_freigabe_nicht() -> None:
    """Leere, im aktuellen Vertrag optionale Q-Felder sind kein technischer Mangel."""
    kontext = _kontext()
    quelle = replace(
        kontext.datenquellen[0],
        konkretes_quellsystem="",
        fachliche_beschreibung="",
        herkunft_oder_verantwortungsbereich="",
    )

    ergebnis, _ = pruefe_quality_gate(replace(kontext, datenquellen=(quelle,)), _bestaetigungen())

    assert ergebnis.freigabe_moeglich
    assert not any(wert.kriterium_id.startswith("q_angaben_fehlen:") for wert in ergebnis.befunde)


def test_t_fehlende_erforderliche_spalte_und_ungueltige_zeit_fuehren_zu_schritt_zwei() -> None:
    t_daten = pd.DataFrame(
        {
            "fall": ["A", "A"],
            "zeit": ["keine Zeit", "2025-01-02"],
            "unbenutzt": [None, None],
        }
    )
    ergebnis, _ = pruefe_quality_gate(_kontext(t_daten=t_daten), _bestaetigungen())
    ids = {wert.kriterium_id for wert in ergebnis.befunde}
    assert "t_spalte_fehlt:aktion" in ids
    assert "t_zeit_uninterpretierbar:zeit" in ids
    assert ergebnis.rueckspruenge == (2,)


def test_leerer_breiter_zeitstempel_wird_transparent_fachlich_und_nicht_pauschal_blockiert() -> (
    None
):
    kontext = _kontext(
        t_daten=pd.DataFrame(
            {
                "fall": ["A", "B"],
                "start": ["2025-01-01", ""],
                "ende": ["2025-01-02", "2025-01-03"],
            }
        )
    )
    config = replace(
        kontext.event_log.konfiguration,
        mapping_modus=MappingModus.BREITER_ZEITSTEMPELDATENSATZ,
        aktivitaetsspalte="",
        zeitstempelspalte="",
        aktivitaetsdefinition=None,
        zeitstempelzuordnungen=(
            ZeitstempelZuordnung("start", "Start"),
            ZeitstempelZuordnung("ende", "Ende"),
        ),
    )
    kontext = replace(kontext, event_log=replace(kontext.event_log, konfiguration=config))
    offen, _ = pruefe_quality_gate(kontext, _bestaetigungen())
    assert any(
        wert.kriterium_id == "t_breiter_zeitstempel:start"
        and wert.status is QualityGateStatus.FACHLICHE_BESTAETIGUNG_ERFORDERLICH
        for wert in offen.befunde
    )
    entschieden, _ = pruefe_quality_gate(
        kontext,
        (
            *_bestaetigungen(),
            FachlicheEntscheidung(
                "t_breiter_zeitstempel:start",
                False,
                "In Fall B hat die Aktivität Start fachlich nicht stattgefunden.",
            ),
        ),
    )
    assert entschieden.freigabe_moeglich


def test_m_unterscheidet_fehlend_bestaetigt_leer_und_befuellt_mit_zulaessigem_n_zu_eins() -> None:
    basis = _kontext()
    ohne_m, _ = pruefe_quality_gate(basis, _bestaetigungen())
    assert ohne_m.mappingzustand is Mappingzustand.NICHT_VORHANDEN
    assert any(wert.kriterium_id == "m_nicht_vorhanden" for wert in ohne_m.befunde)

    leer = Mappingtabelle.neu(
        basis.event_log.artefakt.projekt_id,
        basis.event_log.zwischendatensatz.zwischendatensatz_id,
    ).bestaetigen(kein_mapping_erforderlich=True)
    leer_ergebnis, _ = pruefe_quality_gate(_mit_mapping(basis, leer), _bestaetigungen())
    assert leer_ergebnis.mappingzustand is Mappingzustand.BESTAETIGT_LEER
    assert leer_ergebnis.freigabe_moeglich

    gefuellt = Mappingtabelle.neu(
        basis.event_log.artefakt.projekt_id,
        basis.event_log.zwischendatensatz.zwischendatensatz_id,
    )
    gefuellt = gefuellt.eintrag_hinzufuegen(Mappingeintrag.fuer_spalte("fall", "Identifikation"))
    gefuellt = gefuellt.eintrag_hinzufuegen(
        Mappingeintrag.fuer_spalte("aktion", "Identifikation")
    ).bestaetigen()
    m_kontext = _mit_mapping(basis, gefuellt)
    entscheidungen = (
        *_bestaetigungen(),
        FachlicheEntscheidung(
            "m_verstaendlich", False, "Beide technischen Referenzen sind eindeutig erläutert."
        ),
    )
    m_ergebnis, _ = pruefe_quality_gate(m_kontext, entscheidungen)
    assert m_ergebnis.mappingzustand is Mappingzustand.BEFUELLT
    assert m_ergebnis.freigabe_moeglich
    assert not any(wert.kriterium_id == "m_referenzen_ungueltig" for wert in m_ergebnis.befunde)


@pytest.mark.parametrize("spalte", ["case_id", "activity", "timestamp"])
def test_fehlender_mindestbestandteil_in_e_ist_nicht_uebersteuerbar(spalte: str) -> None:
    kontext = _kontext()
    ereignisse = kontext.event_log.ereignisse.drop(columns=spalte)
    ergebnis, _ = pruefe_quality_gate(
        replace(kontext, event_log=replace(kontext.event_log, ereignisse=ereignisse)),
        _bestaetigungen(),
    )
    befund = next(
        wert for wert in ergebnis.befunde if wert.kriterium_id == f"e_spalte_fehlt:{spalte}"
    )
    assert befund.nicht_uebersteuerbar
    assert befund.ruecksprung_schritt == 4
    assert not ergebnis.freigabe_moeglich


def test_mehrere_ursachen_erzeugen_getrennte_rueckspruenge() -> None:
    kontext = _kontext(t_daten=pd.DataFrame({"fall": ["A"], "zeit": ["2025-01-01"]}))
    event = replace(
        kontext.event_log,
        ereignisse=kontext.event_log.ereignisse.drop(columns="activity"),
    )
    ergebnis, _ = pruefe_quality_gate(
        replace(kontext, event_log=event, datenquellen=()),
        (FachlicheEntscheidung("e_interpretierbar", False, "E bleibt lesbar."),),
    )
    assert ergebnis.rueckspruenge == (1, 2, 4)
