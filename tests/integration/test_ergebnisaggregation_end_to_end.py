"""End-to-End-Vertrag von Algorithmus 7 mit unveränderter Eingabekette."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pandas as pd
import pytest

from framework_mvp.application.ergebnisaggregation.sollprozess import (
    erstelle_aktivitaetsmapping,
    erzeuge_lineares_sollmodell,
)
from framework_mvp.application.ergebnisaggregation.zeitvergleich import (
    lese_externe_sollzeitdaten,
)
from framework_mvp.application.ergebnisaggregation_service import ErgebnisaggregationService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    AnkunftsstromDefinition,
    Attributzuordnung,
    BestaetigteWarteschlangeninformation,
    BusyRatioKonfiguration,
    Datenartefakt,
    DiscoveryVerfahren,
    Freigabestatus,
    KpiBehandlungsart,
    KpiKonfiguration,
    KpiStatus,
    LogistischeZielgroesse,
    Mappingzustand,
    OperandZuordnung,
    PerformanceZeitvergleichKonfiguration,
    ProcessMiningAnalyse,
    ProcessMiningStatus,
    Profilkennzahltyp,
    Projekt,
    Projektstatus,
    Qualitaetsfreigabe,
    Systemtyp,
    Untersuchungsauftrag,
    Vergleichsebene,
    Vorkommensregel,
    ZeitvergleichKonfiguration,
    Zwischendatensatz,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.infrastructure.importartefakte.profil_json import ProfilArtefakt
from framework_mvp.workspace import WorkspaceKonfiguration


class _AggregationRepository:
    def __init__(self) -> None:
        self.werte = {}

    def speichern(self, aggregation):  # type: ignore[no-untyped-def]
        self.werte.setdefault(aggregation.aggregations_id, aggregation)

    def laden(self, aggregations_id):  # type: ignore[no-untyped-def]
        return self.werte.get(aggregations_id)

    def fuer_analyse(self, projekt_id, analyse_id):  # type: ignore[no-untyped-def]
        return [
            wert
            for wert in self.werte.values()
            if wert.projekt_id == projekt_id and wert.analyse_id == analyse_id
        ]


class _Projekte:
    def __init__(self, projekt: Projekt) -> None:
        self.projekt = projekt

    def projekt_laden(self, projekt_id: UUID):  # type: ignore[no-untyped-def]
        return self.projekt if self.projekt.projekt_id == projekt_id else None


class _Qualitaet:
    def __init__(self, freigabe: Qualitaetsfreigabe, event_log: pd.DataFrame) -> None:
        self.freigabe = freigabe
        self.event_log = event_log

    def freigabe_laden(self, freigabe_id: UUID):  # type: ignore[no-untyped-def]
        if freigabe_id != self.freigabe.freigabe_id:
            raise Importintegritaetsfehler("Freigabe fehlt")
        return self.freigabe, self.event_log.copy(deep=True)


class _Transformationen:
    def __init__(
        self,
        datensatz: Zwischendatensatz,
        tabelle: pd.DataFrame,
        profil: ProfilArtefakt,
        raw_sha256: str,
    ) -> None:
        self.datensatz = datensatz
        self.tabelle = tabelle
        self.profil = profil
        self.raw_sha256 = raw_sha256
        self.abstraktionen: tuple[dict[str, object], ...] = ()
        self.fachhistorie: tuple[dict[str, object], ...] = ()

    def zwischendatensatz_laden(self, datensatz_id: UUID):  # type: ignore[no-untyped-def]
        assert datensatz_id == self.datensatz.zwischendatensatz_id
        return self.datensatz, self.tabelle.copy(deep=True)

    def import_laden(self, import_id: UUID):  # type: ignore[no-untyped-def]
        assert import_id == self.profil.import_id
        return SimpleNamespace(
            importvorgang=SimpleNamespace(
                projekt_id=self.datensatz.projekt_id,
                sha256=self.raw_sha256,
            ),
            profil=self.profil,
        )

    def regelbasierte_abstraktionen_laden(self, datensatz):  # type: ignore[no-untyped-def]
        assert datensatz == self.datensatz
        return self.abstraktionen

    def fachliche_transformationshistorie_laden(self, datensatz):  # type: ignore[no-untyped-def]
        assert datensatz == self.datensatz
        return self.fachhistorie


class _ProcessMining:
    def __init__(self, analyse: ProcessMiningAnalyse, a_d: dict, modell: bytes) -> None:
        self.analyse = analyse
        self.a_d = a_d
        self.modell = modell

    def uebergabe_laden(self, analyse_id, projekt_id, freigabe_id):  # type: ignore[no-untyped-def]
        if (
            analyse_id != self.analyse.analyse_id
            or projekt_id != self.analyse.projekt_id
            or freigabe_id != self.analyse.qualitaetspruefung_id
        ):
            raise Domaenenfehler("Fremde Analyse")
        return self.analyse, dict(self.a_d), bytes(self.modell)


def _umgebung(
    tmp_path,  # type: ignore[no-untyped-def]
    *,
    ausgewaehlte_kpi_ids: tuple[str, ...] = ("servicegrad",),
):  # type: ignore[no-untyped-def]
    jetzt = datetime.now(UTC)
    projekt_id, freigabe_id, event_log_id, t_id, import_id, analyse_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    auftrag = Untersuchungsauftrag(
        "Lieferfähigkeit ist zu untersuchen",
        "Leistung bewerten",
        Systemtyp.KOMBINIERT,
        "Werk",
        logistische_zielgroessen=(
            LogistischeZielgroesse.LIEFERFAEHIGKEIT,
            LogistischeZielgroesse.NACHARBEIT,
        ),
        ausgewaehlte_kpi_ids=ausgewaehlte_kpi_ids,
    )
    projekt = Projekt(
        projekt_id,
        "Aggregation",
        (),
        Projektstatus.AKTIV,
        jetzt,
        jetzt,
        auftrag,
    )
    tabelle = pd.DataFrame(
        {
            "position": ["P1", "P2", "P3"],
            "befriedigt": ["ja", "ja", "nein"],
            "wert": [1.0, 2.0, 3.0],
        }
    )
    event_log = pd.DataFrame(
        {
            "case_id": ["1", "1", "2", "2"],
            "activity": ["A", "B", "A", "B"],
            "timestamp": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-01", "2026-01-03"], utc=True
            ),
        }
    )
    datensatz = Zwischendatensatz(
        t_id,
        projekt_id,
        uuid4(),
        (import_id,),
        "t.csv.gz",
        "t.schema.json",
        "t.lineage.json",
        "b" * 64,
        len(tabelle),
        len(tabelle.columns),
        jetzt,
    )
    profil = ProfilArtefakt(
        3,
        import_id,
        "1" * 64,
        {},
        "Tabelle",
        jetzt,
        {
            "zeilen": 3,
            "spaltenprofile": [
                {
                    "spaltenname": "befriedigt",
                    "indikatorauswertungen": [
                        {
                            "spaltenname": "befriedigt",
                            "operator": "gleich",
                            "vergleichswert": "ja",
                            "absolute_haeufigkeit": 2,
                            "auswertbare_beobachtungen": 3,
                        },
                        {
                            "spaltenname": "befriedigt",
                            "operator": "ungleich",
                            "vergleichswert": "ja",
                            "absolute_haeufigkeit": 1,
                            "auswertbare_beobachtungen": 3,
                        },
                    ],
                },
                {
                    "spaltenname": "wert",
                    "numerisch": {"mittelwert": 2.0, "gueltige_werte": 3},
                    "indikatorauswertungen": [],
                },
            ],
        },
        (),
        (),
    )
    freigabe = Qualitaetsfreigabe(
        freigabe_id,
        projekt_id,
        event_log_id,
        "a" * 64,
        t_id,
        datensatz.sha256,
        uuid4(),
        None,
        "",
        Mappingzustand.NICHT_VORHANDEN,
        (),
        "c" * 64,
        "d" * 64,
        "e" * 64,
        "release.json",
        "f" * 64,
        Freigabestatus.FREIGEGEBEN,
        jetzt,
    )
    modell = b"<?xml version='1.0'?><ptml/>"
    p_sha = hashlib.sha256(modell).hexdigest()
    a_d_bytes = b'{"a_d":true}'
    a_d_sha = hashlib.sha256(a_d_bytes).hexdigest()
    analyse = ProcessMiningAnalyse(
        analyse_id,
        projekt_id,
        freigabe_id,
        event_log_id,
        "{}",
        "[]",
        DiscoveryVerfahren.INDUCTIVE_MINER,
        json.dumps({"a_d_sha256": a_d_sha}),
        4,
        2,
        2,
        1,
        4,
        2,
        2,
        1,
        "{}",
        "[]",
        "2.7.23.3",
        "analysis.discovery.json",
        "",
        "analysis.dfg.json",
        "analysis.model.ptml",
        "",
        ProcessMiningStatus.AUSGEFUEHRT,
        jetzt,
        jetzt,
    )
    a_d = {
        "prozessnotation": "prozessbaum",
        "prozessmodell_p": {
            "relativer_pfad": analyse.relativer_modell_pfad,
            "sha256": p_sha,
        },
    }
    workspace = WorkspaceKonfiguration.ermitteln(tmp_path / "workspace")
    speicher = ImportartefaktSpeicher(workspace)
    repository = _AggregationRepository()
    projekte = _Projekte(projekt)
    transformationen = _Transformationen(datensatz, tabelle, profil, "1" * 64)
    qualitaet = _Qualitaet(freigabe, event_log)
    process = _ProcessMining(analyse, a_d, modell)
    service = ErgebnisaggregationService(
        repository,  # type: ignore[arg-type]
        projekte,  # type: ignore[arg-type]
        transformationen,  # type: ignore[arg-type]
        qualitaet,  # type: ignore[arg-type]
        process,  # type: ignore[arg-type]
        speicher,
    )
    return (
        service,
        repository,
        projekte,
        speicher,
        projekt,
        freigabe,
        analyse,
        tabelle,
        event_log,
        modell,
    )


def test_a_g_ohne_optionale_bestandteile_ist_idempotent_und_uebergabefaehig(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, _, _, projekt, freigabe, analyse, tabelle, event_log, modell = _umgebung(tmp_path)
    service._transformationen.abstraktionen = (  # type: ignore[attr-defined]
        {
            "quellspalte": "Von",
            "vergleichsart": "Beginnt mit",
            "suchwert_muster": "HRL-04-",
            "vorher_muster": "HRL-04-*",
            "abstraktionswert": "HRL-04",
            "zielspalte": "Von_aggregiert",
            "betroffene_beobachtungen": 185,
            "originalwerte_erhalten": True,
        },
    )
    service._transformationen.fachhistorie = (  # type: ignore[attr-defined]
        {
            "reihenfolge": 1,
            "transformationsart": "Werte regelbasiert abstrahieren",
            "betroffene_spalten": ["Von"],
            "regel": {"vergleichsart": "Beginnt mit", "suchwert": "HRL-04"},
            "ersatz_oder_abstraktionswert": "HRL-04",
            "eingang": "ursprüngliche Datenquelle D",
            "ergebnis": "aktiver Zwischendatensatz T",
            "wirkung": "185 Werte regelbasiert abstrahiert",
        },
    )
    t_vorher, e_vorher = tabelle.copy(deep=True), event_log.copy(deep=True)
    config = KpiKonfiguration(
        "servicegrad",
        (
            OperandZuordnung(
                "befriedigte_kundenauftragspositionen",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="befriedigt",
                bedingungsoperator="gleich",
                bedingungswert="ja",
            ),
            OperandZuordnung(
                "kundenauftragspositionen",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="position",
            ),
        ),
        "%",
        "Kundenauftragspositionen",
    )
    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
        kpi_konfigurationen=(config,),
    )
    assert vorschau.kpi_ergebnisse[0].status is KpiStatus.BERECHNET
    assert vorschau.kpi_ergebnisse[0].ergebnis == pytest.approx(200 / 3)
    assert vorschau.conformance_ergebnis is None
    assert vorschau.zeitvergleich_ergebnis is None
    aggregation_id = uuid4()
    gespeichert = service.speichern(aggregation_id, vorschau, menschlich_bestaetigt=True)
    assert service.speichern(aggregation_id, vorschau, menschlich_bestaetigt=True) == gespeichert
    erneut, a_g = service.laden(aggregation_id)
    p_uebergabe, a_g_uebergabe = service.uebergabe_schritt8(
        aggregation_id, projekt.projekt_id, freigabe.freigabe_id, analyse.analyse_id
    )
    assert erneut == gespeichert
    assert a_g["discovery_ergebnisse_a_d"]["sha256"]
    assert "schwellwert_k" in a_g["discovery_ergebnisse_a_d"]
    assert "miner_variante" in a_g["discovery_ergebnisse_a_d"]
    assert a_g["artefaktversion"] == 7
    assert a_g["kpi_konfigurationsversion"] == 3
    assert a_g["konfiguration"]["version"] == 2
    assert a_g["strukturierte_ergebnisse"]["ergebnisversion"] == 4
    assert a_g["strukturierte_ergebnisse"]["vereinfachungen"]["etl_abstraktionen"] == [
        {
            "quellspalte": "Von",
            "vergleichsart": "Beginnt mit",
            "suchwert_muster": "HRL-04-",
            "vorher_muster": "HRL-04-*",
            "abstraktionswert": "HRL-04",
            "zielspalte": "Von_aggregiert",
            "betroffene_beobachtungen": 185,
            "originalwerte_erhalten": True,
        }
    ]
    assert a_g["strukturierte_ergebnisse"]["datenaufbereitung"]["transformationshistorie"] == list(
        cast(Any, service._transformationen).fachhistorie
    )
    assert a_g["conformance_checking"] == {
        "sollprozess_vorhanden": False,
        "durchgefuehrt": False,
        "status": "Kein Sollprozess vorhanden; Conformance Checking entfällt ohne Fehler.",
        "a_c_referenz": None,
        "ergebnis": None,
    }
    assert "entitaetsinstanzen_und_attribute" in a_g["strukturierte_ergebnisse"]
    assert a_g["optionale_artefakte"] == {}
    assert p_uebergabe == modell
    assert a_g_uebergabe == a_g
    pd.testing.assert_frame_equal(tabelle, t_vorher)
    pd.testing.assert_frame_equal(event_log, e_vorher)


def test_r_indikator_wird_als_strukturierte_kpi_rechengroesse_persistiert(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, _, _, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    basis = service.grundlage_laden(
        projekt.projekt_id,
        freigabe.freigabe_id,
        analyse.analyse_id,
    )
    indikator = next(
        wert
        for wert in basis.profilkennzahlen
        if wert.kennzahltyp is Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR
        and wert.spaltenname == "befriedigt"
        and wert.operator == "gleich"
    )
    config = KpiKonfiguration(
        "servicegrad",
        (
            OperandZuordnung(
                "befriedigte_kundenauftragspositionen",
                Datenartefakt.DATENPROFIL_R,
                profilkennzahl=indikator,
            ),
            OperandZuordnung(
                "kundenauftragspositionen",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="position",
            ),
        ),
        "%",
        "Kundenauftragspositionen",
    )

    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
        kpi_konfigurationen=(config,),
    )
    ergebnis = vorschau.kpi_ergebnisse[0]
    assert ergebnis.status is KpiStatus.BERECHNET
    assert ergebnis.ergebnis == pytest.approx(200 / 3)
    assert ergebnis.zwischensummen["befriedigte_kundenauftragspositionen"] == 2
    assert ergebnis.wertebedingungen[0]["in_schritt_7_ausgewertet"] is False
    assert ergebnis.quellenreferenzen[0]["profilkennzahl"]["profil_sha256"]

    aggregation = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    _, a_g = service.laden(aggregation.aggregations_id)
    gespeichert = a_g["kpi_konfigurationen"][0]["zuordnungen"][0]["profilkennzahl"]
    assert gespeichert["kennzahltyp"] == "absolute_haeufigkeit_indikator"
    assert gespeichert["spaltenname"] == "befriedigt"
    assert gespeichert["operator"] == "gleich"
    assert gespeichert["vergleichswert"] == "ja"
    assert gespeichert["wert"] == 2
    assert a_g["kpi_ergebnisse"][0]["definitionsversion"] == 1
    assert a_g["kpi_ergebnisse"][0]["zwischensummen"] == {
        "befriedigte_kundenauftragspositionen": 2.0,
        "kundenauftragspositionen": 3.0,
    }


def test_r_indikator_wird_auch_als_summe_operand_e2e_persistiert(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, _, _, projekt, freigabe, analyse, _, _, _ = _umgebung(
        tmp_path,
        ausgewaehlte_kpi_ids=("nacharbeitsquote_rr",),
    )
    basis = service.grundlage_laden(
        projekt.projekt_id,
        freigabe.freigabe_id,
        analyse.analyse_id,
    )
    indikator = next(
        wert
        for wert in basis.profilkennzahlen
        if wert.kennzahltyp is Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR
        and wert.spaltenname == "befriedigt"
        and wert.operator == "gleich"
    )
    config = KpiKonfiguration(
        "nacharbeitsquote_rr",
        (
            OperandZuordnung(
                "nacharbeiten",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="wert",
            ),
            OperandZuordnung(
                "verarbeitete_menge",
                Datenartefakt.DATENPROFIL_R,
                profilkennzahl=indikator,
            ),
        ),
        "%",
        "verarbeitete Menge",
    )

    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
        kpi_konfigurationen=(config,),
    )
    ergebnis = vorschau.kpi_ergebnisse[0]
    assert ergebnis.status is KpiStatus.BERECHNET
    assert ergebnis.zwischensummen == {"nacharbeiten": 6.0, "verarbeitete_menge": 2.0}
    assert ergebnis.ergebnis == pytest.approx(300)
    assert ergebnis.zugeordnete_operanden[1]["wert_aus_gespeichertem_r_uebernommen"] is True

    aggregation = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    _, a_g = service.laden(aggregation.aggregations_id)
    gespeichert = a_g["kpi_konfigurationen"][0]["zuordnungen"][1]["profilkennzahl"]
    assert gespeichert["kennzahltyp"] == "absolute_haeufigkeit_indikator"
    assert gespeichert["wert"] == 2


def test_veralteter_r_indikator_wird_beim_summe_operand_e2e_abgelehnt(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, _, _, projekt, freigabe, analyse, _, _, _ = _umgebung(
        tmp_path,
        ausgewaehlte_kpi_ids=("nacharbeitsquote_rr",),
    )
    basis = service.grundlage_laden(
        projekt.projekt_id,
        freigabe.freigabe_id,
        analyse.analyse_id,
    )
    indikator = next(
        wert
        for wert in basis.profilkennzahlen
        if wert.kennzahltyp is Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR
        and wert.operator == "gleich"
    )
    config = KpiKonfiguration(
        "nacharbeitsquote_rr",
        (
            OperandZuordnung(
                "nacharbeiten",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="position",
            ),
            OperandZuordnung(
                "verarbeitete_menge",
                Datenartefakt.DATENPROFIL_R,
                profilkennzahl=indikator,
            ),
        ),
        "%",
        "verarbeitete Menge",
    )
    transformationen = cast(Any, service._transformationen)
    gesamtprofil = json.loads(json.dumps(transformationen.profil.gesamtprofil))
    gesamtprofil["spaltenprofile"][0]["indikatorauswertungen"][0]["absolute_haeufigkeit"] = 1
    transformationen.profil = replace(
        transformationen.profil,
        gesamtprofil=gesamtprofil,
    )

    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
        kpi_konfigurationen=(config,),
    )

    ergebnis = vorschau.kpi_ergebnisse[0]
    assert ergebnis.status is KpiStatus.NICHT_BERECHENBAR
    assert any(
        "nicht mehr mit dem aktuellen R" in wert for wert in ergebnis.fehlende_voraussetzungen
    )


def test_indikatoraenderung_aendert_r_pruefsumme_und_eingabefingerabdruck(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, _, _, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    vorher = service.grundlage_laden(
        projekt.projekt_id,
        freigabe.freigabe_id,
        analyse.analyse_id,
    )
    transformationen = cast(Any, service._transformationen)
    profil = transformationen.profil
    gesamtprofil = json.loads(json.dumps(profil.gesamtprofil))
    gesamtprofil["spaltenprofile"][0]["indikatorauswertungen"][0]["absolute_haeufigkeit"] = 1
    transformationen.profil = replace(profil, gesamtprofil=gesamtprofil)

    nachher = service.grundlage_laden(
        projekt.projekt_id,
        freigabe.freigabe_id,
        analyse.analyse_id,
    )

    assert nachher.datenprofil_sha256 != vorher.datenprofil_sha256
    assert nachher.eingabefingerabdruck != vorher.eingabefingerabdruck
    geaendert = next(
        wert
        for wert in nachher.profilkennzahlen
        if wert.kennzahltyp is Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR
        and wert.operator == "gleich"
    )
    assert geaendert.wert == 1
    assert geaendert.profil_sha256 != indikator_sha(vorher)


def indikator_sha(basis) -> str:  # type: ignore[no-untyped-def]
    return next(
        wert.profil_sha256
        for wert in basis.profilkennzahlen
        if wert.kennzahltyp is Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR
        and wert.operator == "gleich"
    )


def test_dt_db_busy_ratio_und_a_v_werden_vollstaendig_in_a_g_persistiert(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, _, speicher, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    qualitaet = cast(Any, service._qualitaet)
    event_log = qualitaet.event_log.copy(deep=True)
    event_log["resource"] = ["M01", "M01", "M02", "M02"]
    event_log["start_timestamp"] = pd.to_datetime(
        [
            "2026-01-01 08:00",
            "2026-01-01 08:20",
            "2026-01-01 09:00",
            "2026-01-01 09:10",
        ],
        utc=True,
    )
    event_log["end_timestamp"] = pd.to_datetime(
        [
            "2026-01-01 08:10",
            "2026-01-01 08:30",
            "2026-01-01 09:15",
            "2026-01-01 09:20",
        ],
        utc=True,
    )
    qualitaet.event_log = event_log
    soll_csv = (
        b"fall,schritt,plan_start,plan_ende\n"
        b"1,A,2026-01-01 07:50,2026-01-01 08:05\n"
        b"1,B,2026-01-01 08:10,2026-01-01 08:30\n"
        b"2,A,2026-01-01 08:50,2026-01-01 09:10\n"
        b"2,B,2026-01-01 09:00,2026-01-01 09:20\n"
    )
    sollzeitdaten, solltabelle = lese_externe_sollzeitdaten(
        projekt_id=projekt.projekt_id,
        dateiname="performance-soll.csv",
        originalbytes=soll_csv,
    )
    performance_config = PerformanceZeitvergleichKonfiguration(
        "extern",
        "fall",
        "schritt",
        "case_id",
        "activity",
        "plan_ende",
        "end_timestamp",
        "plan_start",
        "start_timestamp",
        vorkommensregel=Vorkommensregel.ERSTES,
        fertigstellungsabweichung_aktiv=True,
        bearbeitungszeitabweichung_aktiv=True,
    )
    busy_config = BusyRatioKonfiguration(
        "resource",
        "start_timestamp",
        "end_timestamp",
        datetime(2026, 1, 1, 7, 0, tzinfo=UTC),
        datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
    )

    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
        sollzeitdaten=sollzeitdaten,
        sollzeit_tabelle=solltabelle,
        performance_zeitvergleich_konfiguration=performance_config,
        performance_zeitvergleich_ausfuehren=True,
        busy_ratio_konfiguration=busy_config,
        busy_ratio_ausfuehren=True,
    )

    assert vorschau.performance_zeitvergleich_ergebnis is not None
    assert vorschau.performance_zeitvergleich_ergebnis.dt_statistik is not None
    assert vorschau.performance_zeitvergleich_ergebnis.db_statistik is not None
    assert vorschau.busy_ratio_ergebnis is not None
    assert vorschau.busy_ratio_ergebnis.potenzieller_engpass == "M02"
    aggregation = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    _, a_g = service.laden(aggregation.aggregations_id)

    performance = a_g["strukturierte_ergebnisse"]["performance_und_engpassanalyse"]
    assert performance["dt_db_konfiguration"]["plan_start_spalte"] == "plan_start"
    assert len(performance["dt_db_ergebnis"]["einzelwerte"]) == 4
    assert performance["busy_ratio_konfiguration"]["ressourcenspalte"] == "resource"
    assert performance["busy_ratio_ergebnis"]["potenzieller_engpass"] == "M02"
    av_referenz = a_g["optionale_artefakte"]["potenzielle_verbesserungspotenziale_a_v"]
    assert av_referenz["artefaktversion"] == 2
    assert av_referenz["dt_db_csv_pfad_sha256"]
    assert av_referenz["busy_ratio_csv_pfad_sha256"]
    a_v = json.loads(speicher.lesen(av_referenz["relativer_pfad"]))
    assert a_v["artefaktversion"] == 2
    assert a_v["fertigstellungs_und_bearbeitungszeitabweichungen"]["einzelwerte"]
    assert a_v["ressourcenbezogene_busy_ratio"]["ressourcenstatistiken"]
    details = service.gespeicherte_ergebnisdetails_laden(aggregation.aggregations_id)
    assert details["performance"] == a_v


def test_a_g_v1_bleibt_lesbar_waehrend_neue_speicherungen_v7_schreiben(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, repository, _, speicher, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
    )
    aggregation = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    struktur = json.loads(speicher.lesen(aggregation.relativer_aggregations_pfad))
    struktur.pop("gesamtpruefsumme")
    struktur["artefaktversion"] = 1
    struktur.pop("strukturierte_ergebnisse")
    struktur.pop("prozessbelege")
    struktur["gesamtpruefsumme"] = hashlib.sha256(
        json.dumps(
            struktur,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    v1_bytes = json.dumps(
        struktur,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")
    speicher.artefakt_ersetzen(aggregation.relativer_aggregations_pfad, v1_bytes)
    repository.werte[aggregation.aggregations_id] = replace(
        aggregation,
        aggregations_sha256=hashlib.sha256(v1_bytes).hexdigest(),
    )

    _, geladen = service.laden(aggregation.aggregations_id)

    assert geladen["artefaktversion"] == 1
    assert "strukturierte_ergebnisse" not in geladen


def test_a_g_v2_bleibt_ohne_umdeutung_alter_uebergangswartezeiten_lesbar(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, repository, _, speicher, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
    )
    aggregation = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    struktur = json.loads(speicher.lesen(aggregation.relativer_aggregations_pfad))
    struktur.pop("gesamtpruefsumme")
    struktur["artefaktversion"] = 2
    struktur["strukturierte_ergebnisse"] = {
        "ergebnisversion": 1,
        "warteschlangen_und_wartezeiten": {
            "uebergaenge": [{"von_aktivitaet": "A", "zu_aktivitaet": "B"}]
        },
    }
    struktur["gesamtpruefsumme"] = hashlib.sha256(
        json.dumps(
            struktur,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    v2_bytes = json.dumps(
        struktur, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8")
    speicher.artefakt_ersetzen(aggregation.relativer_aggregations_pfad, v2_bytes)
    repository.werte[aggregation.aggregations_id] = replace(
        aggregation, aggregations_sha256=hashlib.sha256(v2_bytes).hexdigest()
    )

    _, geladen = service.laden(aggregation.aggregations_id)

    alt = geladen["strukturierte_ergebnisse"]["warteschlangen_und_wartezeiten"]
    assert "uebergaenge" in alt
    assert "bestaetigte_warteschlangen" not in alt


@pytest.mark.parametrize("alte_version", (3, 4, 5, 6))
def test_a_g_v3_bis_v6_bleiben_ohne_umdeutung_lesbar(tmp_path, alte_version: int) -> None:  # type: ignore[no-untyped-def]
    service, repository, _, speicher, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
    )
    aggregation = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    struktur = json.loads(speicher.lesen(aggregation.relativer_aggregations_pfad))
    struktur.pop("gesamtpruefsumme")
    struktur["artefaktversion"] = alte_version
    struktur.pop("conformance_checking")
    struktur["strukturierte_ergebnisse"].pop("performance_und_engpassanalyse")
    struktur["strukturierte_ergebnisse"]["ergebnisversion"] = 2
    if alte_version == 3:
        struktur.pop("kpi_konfigurationsversion")
    struktur["gesamtpruefsumme"] = hashlib.sha256(
        json.dumps(
            struktur,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    alte_bytes = json.dumps(
        struktur, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8")
    speicher.artefakt_ersetzen(aggregation.relativer_aggregations_pfad, alte_bytes)
    repository.werte[aggregation.aggregations_id] = replace(
        aggregation,
        aggregations_sha256=hashlib.sha256(alte_bytes).hexdigest(),
    )

    _, geladen = service.laden(aggregation.aggregations_id)

    assert geladen["artefaktversion"] == alte_version
    assert "performance_und_engpassanalyse" not in geladen["strukturierte_ergebnisse"]
    if alte_version == 3:
        assert "kpi_konfigurationsversion" not in geladen


def test_mehrere_ankunftsstroeme_werden_getrennt_in_a_g_gespeichert(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, _, _, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    stroeme = (
        AnkunftsstromDefinition(
            "Systemeintritt",
            Datenartefakt.EVENT_LOG_E_STERN,
            "case_id",
            "timestamp",
            aktivitaet="A",
        ),
        AnkunftsstromDefinition(
            "Ankunft B",
            Datenartefakt.EVENT_LOG_E_STERN,
            "case_id",
            "timestamp",
            aktivitaet="B",
        ),
    )
    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
        ankunftsstroeme=stroeme,
    )
    aggregation = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    _, a_g = service.laden(aggregation.aggregations_id)

    iat = a_g["strukturierte_ergebnisse"]["zeitbezogene_datenauswahl"]["zwischenankunftszeiten"]
    assert [wert["definition"]["bezeichnung"] for wert in iat] == [
        "Systemeintritt",
        "Ankunft B",
    ]


def test_a_g_integritaet_und_vorschauinvalidierung(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, projekte, speicher, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
    )
    aggregation = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    original = speicher.lesen(aggregation.relativer_aggregations_pfad)
    speicher.artefakt_ersetzen(aggregation.relativer_aggregations_pfad, original + b" ")
    with pytest.raises(Importintegritaetsfehler, match="Dateiprüfsumme"):
        service.laden(aggregation.aggregations_id)
    speicher.artefakt_ersetzen(aggregation.relativer_aggregations_pfad, original)
    projekte.projekt = projekt.aktualisiert(
        bezeichnung=projekt.bezeichnung,
        untersuchungsauftrag=Untersuchungsauftrag(
            "Geänderte Problemstellung",
            "Leistung bewerten",
            Systemtyp.KOMBINIERT,
            "Werk",
            logistische_zielgroessen=(LogistischeZielgroesse.LIEFERFAEHIGKEIT,),
            ausgewaehlte_kpi_ids=("servicegrad",),
        ),
        status=Projektstatus.AKTIV,
    )
    with pytest.raises(Domaenenfehler, match="Neuberechnung"):
        service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)


def test_a_c_p_soll_mapping_sollzeitdaten_und_a_v_werden_reproduzierbar_referenziert(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    service, _, _, speicher, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    sollmodell = erzeuge_lineares_sollmodell(
        projekt_id=projekt.projekt_id,
        aktivitaeten=("A", "B"),
        bezeichnung="Soll A-B",
        fachliche_grundlage="Freigegebene Arbeitsanweisung",
        modellversion="1",
        person="Prüfperson",
        freigabedatum=date.today(),
        menschlich_bestaetigt=True,
    )
    mapping = erstelle_aktivitaetsmapping(
        projekt_id=projekt.projekt_id,
        sollmodell_id=sollmodell.metadaten.sollmodell_id,
        event_aktivitaeten=("A", "B"),
        modell_transitionen=sollmodell.sichtbare_transitionen,
        manuelle_zuordnungen={},
        menschlich_bestaetigt=True,
    )
    sollzeit_bytes = b"fall,plan\n1,2026-01-02\n2,2026-01-02\n"
    sollzeit, sollzeit_tabelle = lese_externe_sollzeitdaten(
        projekt_id=projekt.projekt_id,
        dateiname="soll.csv",
        originalbytes=sollzeit_bytes,
    )
    zeitkonfiguration = ZeitvergleichKonfiguration(
        Vergleichsebene.FALL,
        "extern",
        "fall",
        "plan",
        "case_id",
        "timestamp",
        ist_activity_spalte="activity",
        ausgewaehlte_ist_aktivitaet="B",
        vorkommensregel=Vorkommensregel.ERSTES,
    )
    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
        sollmodell=sollmodell,
        aktivitaetsmapping=mapping,
        conformance_ausfuehren=True,
        sollzeitdaten=sollzeit,
        sollzeit_tabelle=sollzeit_tabelle,
        zeitvergleich_konfiguration=zeitkonfiguration,
        zeitvergleich_ausfuehren=True,
    )
    assert vorschau.conformance_ergebnis is not None
    assert vorschau.conformance_ergebnis.fitness == pytest.approx(1.0)
    assert vorschau.zeitvergleich_ergebnis is not None
    assert vorschau.zeitvergleich_ergebnis.aggregierte_anzahlen == {
        "eindeutig_vergleichbar": 2,
        "fehlender_sollwert": 0,
        "fehlender_istwert": 0,
        "nicht_eindeutig_zuordenbar": 0,
        "verfrüht": 0,
        "termingerecht": 1,
        "verspätet": 1,
    }
    aggregation = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    _, a_g = service.laden(aggregation.aggregations_id)
    optionen = a_g["optionale_artefakte"]
    assert a_g["conformance_checking"]["ergebnis"] == {
        "fitness": pytest.approx(1.0),
        "produzierte_tokens": 6,
        "konsumierte_tokens": 6,
        "fehlende_tokens": 0,
        "verbleibende_tokens": 0,
        "ausgewertete_faelle": 2,
        "konforme_faelle": 2,
        "abweichende_faelle": 0,
        "ausgeschlossene_faelle": 0,
        "artefaktversion": 1,
    }
    assert optionen["prozessmodell_p_soll"]["original_sha256"] == sollmodell.metadaten.sha256
    assert optionen["aktivitaetsmapping"]["sha256"]
    assert optionen["conformance_ergebnisse_a_c"]["sha256"]
    assert optionen["conformance_ergebnisse_a_c"]["detail_csv_sha256"]
    a_c = json.loads(speicher.lesen(optionen["conformance_ergebnisse_a_c"]["relativer_pfad"]))
    assert a_c["sollmodell_referenz"]["sollmodell_id"] == str(sollmodell.metadaten.sollmodell_id)
    assert a_c["aktivitaetsmapping_referenz"]["mapping_id"] == str(mapping.mapping_id)
    assert a_c["ergebnis"]["produzierte_tokens"] == 6
    assert a_c["ergebnis"]["konsumierte_tokens"] == 6
    assert a_c["ergebnis"]["fehlende_tokens"] == 0
    assert a_c["ergebnis"]["verbleibende_tokens"] == 0
    assert a_c["ergebnis"]["fitness"] == pytest.approx(1.0)
    assert a_c["ergebnis"]["fitness_plausibilisierung_pm4py"] == pytest.approx(1.0)
    assert len(a_c["ergebnis"]["fallbezogene_diagnosen"]) == 2
    assert a_c["ergebnis"]["pm4py_version"]
    assert a_c["ergebnis"]["erstellt_am"]
    details = service.gespeicherte_ergebnisdetails_laden(aggregation.aggregations_id)
    assert details["conformance"] == a_c
    assert optionen["sollzeitdaten"]["sha256"] == sollzeit.sha256
    assert optionen["potenzielle_verbesserungspotenziale_a_v"]["sha256"]


def test_projektzeitstempel_und_bezeichnung_sind_keine_fachliche_a_g_eingabe(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, projekte, _, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
    )
    aggregation = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    vorher = vorschau.grundlage.eingabefingerabdruck
    projekte.projekt = replace(
        projekt,
        bezeichnung="Nur neue Anzeige",
        geaendert_am=projekt.geaendert_am + timedelta(minutes=5),
    )

    nachher = service.grundlage_laden(
        projekt.projekt_id,
        freigabe.freigabe_id,
        analyse.analyse_id,
    )

    assert nachher.eingabefingerabdruck == vorher
    assert service.laden(aggregation.aggregations_id)[0] == aggregation


def test_kpi_only_laed_historisches_a_g_selektiv_als_vollstaendige_vorlage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, repository, projekte, _, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    kpi = KpiKonfiguration(
        "servicegrad",
        (
            OperandZuordnung(
                "befriedigte_kundenauftragspositionen",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="befriedigt",
                bedingungsoperator="gleich",
                bedingungswert="ja",
            ),
            OperandZuordnung(
                "kundenauftragspositionen",
                Datenartefakt.ZWISCHENDATENSATZ_T,
                spalte="position",
            ),
        ),
        "%",
        "Kundenauftragspositionen",
    )
    sollmodell = erzeuge_lineares_sollmodell(
        projekt_id=projekt.projekt_id,
        aktivitaeten=("A", "B"),
        bezeichnung="Soll A-B",
        fachliche_grundlage="Arbeitsanweisung",
        modellversion="2",
        person="Prüfperson",
        freigabedatum=date(2026, 1, 1),
        menschlich_bestaetigt=True,
    )
    mapping = erstelle_aktivitaetsmapping(
        projekt_id=projekt.projekt_id,
        sollmodell_id=sollmodell.metadaten.sollmodell_id,
        event_aktivitaeten=("A", "B"),
        modell_transitionen=sollmodell.sichtbare_transitionen,
        manuelle_zuordnungen={},
        menschlich_bestaetigt=True,
    )
    ressourcenattribute = (
        Attributzuordnung(Datenartefakt.ZWISCHENDATENSATZ_T, "wert", "position"),
    )
    entitaetsattribute = (
        Attributzuordnung(Datenartefakt.ZWISCHENDATENSATZ_T, "befriedigt", "position"),
    )
    warteschlangen = (
        BestaetigteWarteschlangeninformation(
            "Puffer A/B", "A", "B", Datenartefakt.EVENT_LOG_E_STERN, "activity", "B"
        ),
    )
    ankunftsstroeme = (
        AnkunftsstromDefinition(
            "Aufträge",
            Datenartefakt.EVENT_LOG_E_STERN,
            "case_id",
            "timestamp",
            aktivitaet="A",
            vorkommensregel=Vorkommensregel.ERSTES,
        ),
    )
    sollzeitdaten, sollzeit_tabelle = lese_externe_sollzeitdaten(
        projekt_id=projekt.projekt_id,
        dateiname="wiederverwendbare-sollzeiten.csv",
        originalbytes=(
            b"position;befriedigt;plan_ende\n1;ja;2026-01-01 08:00:00\n2;nein;2026-01-01 09:00:00\n"
        ),
        trennzeichen=";",
    )
    performance = PerformanceZeitvergleichKonfiguration(
        "extern",
        "position",
        "befriedigt",
        "case_id",
        "activity",
        "plan_ende",
        "timestamp",
        fertigstellungsabweichung_aktiv=False,
        bearbeitungszeitabweichung_aktiv=False,
    )
    busy = BusyRatioKonfiguration(
        "resource",
        "start_timestamp",
        "end_timestamp",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )
    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
        kpi_konfigurationen=(kpi,),
        sollmodell=sollmodell,
        aktivitaetsmapping=mapping,
        conformance_ausfuehren=False,
        sollzeitdaten=sollzeitdaten,
        sollzeit_tabelle=sollzeit_tabelle,
        ressourcenattributzuordnungen=ressourcenattribute,
        entitaetsattributzuordnungen=entitaetsattribute,
        entitaetstyp="Kundenauftrag",
        bestaetigte_warteschlangen=warteschlangen,
        ankunftsstroeme=ankunftsstroeme,
        performance_zeitvergleich_konfiguration=performance,
        performance_zeitvergleich_ausfuehren=False,
        busy_ratio_konfiguration=busy,
        busy_ratio_ausfuehren=False,
    )
    alt = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    projekte.projekt = replace(
        projekt,
        untersuchungsauftrag=replace(
            projekt.untersuchungsauftrag,
            ausgewaehlte_kpi_ids=("servicegrad", "nacharbeitsquote_rr"),
        ),
        geaendert_am=projekt.geaendert_am + timedelta(minutes=1),
    )

    with pytest.raises(Importintegritaetsfehler):
        service.laden(alt.aggregations_id)
    assert service.historisch_laden(alt.aggregations_id)[0] == alt
    vorlage = service.kompatible_konfigurationsvorlage_laden(
        projekt.projekt_id,
        freigabe.freigabe_id,
        analyse.analyse_id,
    )

    assert vorlage is not None
    assert vorlage.aggregations_id == alt.aggregations_id
    assert vorlage.kpi_konfigurationen == (kpi,)
    assert vorlage.sollmodell == sollmodell
    assert vorlage.aktivitaetsmapping == mapping
    assert vorlage.ressourcenattributzuordnungen == ressourcenattribute
    assert vorlage.entitaetsattributzuordnungen == entitaetsattribute
    assert vorlage.entitaetstyp == "Kundenauftrag"
    assert vorlage.bestaetigte_warteschlangen == warteschlangen
    assert vorlage.ankunftsstroeme == ankunftsstroeme
    assert vorlage.performance_zeitvergleich_konfiguration == performance
    assert vorlage.busy_ratio_konfiguration == busy
    assert vorlage.sollzeitdaten is not None
    assert vorlage.sollzeitdaten.originalbytes == sollzeitdaten.originalbytes
    assert vorlage.sollzeit_tabelle is not None
    pd.testing.assert_frame_equal(vorlage.sollzeit_tabelle, sollzeit_tabelle)
    assert {wert.kpi_id for wert in vorlage.kpi_konfigurationen} == {"servicegrad"}

    neu_vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
        kpi_konfigurationen=vorlage.kpi_konfigurationen,
        sollmodell=vorlage.sollmodell,
        aktivitaetsmapping=vorlage.aktivitaetsmapping,
        conformance_ausfuehren=vorlage.conformance_ausfuehren,
        sollzeitdaten=vorlage.sollzeitdaten,
        sollzeit_tabelle=vorlage.sollzeit_tabelle,
        ressourcenanalyse=vorlage.ressourcenanalyse,
        ressourcenattributzuordnungen=vorlage.ressourcenattributzuordnungen,
        entitaetsattributzuordnungen=vorlage.entitaetsattributzuordnungen,
        entitaetstyp=vorlage.entitaetstyp,
        bestaetigte_warteschlangen=vorlage.bestaetigte_warteschlangen,
        ankunftsstroeme=vorlage.ankunftsstroeme,
        performance_zeitvergleich_konfiguration=(vorlage.performance_zeitvergleich_konfiguration),
        performance_zeitvergleich_ausfuehren=vorlage.performance_zeitvergleich_ausfuehren,
        busy_ratio_konfiguration=vorlage.busy_ratio_konfiguration,
        busy_ratio_ausfuehren=vorlage.busy_ratio_ausfuehren,
    )
    assert [wert.kpi_id for wert in neu_vorschau.kpi_ergebnisse] == [
        "servicegrad",
        "nacharbeitsquote_rr",
    ]
    assert neu_vorschau.kpi_ergebnisse[0].status is KpiStatus.BERECHNET
    assert neu_vorschau.kpi_ergebnisse[1].status is KpiStatus.NICHT_BERECHENBAR
    neu = service.speichern(uuid4(), neu_vorschau, menschlich_bestaetigt=True)
    assert len(repository.werte) == 2
    assert service.laden(neu.aggregations_id)[0] == neu
    assert service.historisch_laden(alt.aggregations_id)[0] == alt

    projekte.projekt = replace(
        projekte.projekt,
        untersuchungsauftrag=replace(
            projekte.projekt.untersuchungsauftrag,
            ausgewaehlte_kpi_ids=("nacharbeitsquote_rr",),
        ),
        geaendert_am=projekte.projekt.geaendert_am + timedelta(minutes=1),
    )
    ohne_entfernte = service.kompatible_konfigurationsvorlage_laden(
        projekt.projekt_id,
        freigabe.freigabe_id,
        analyse.analyse_id,
    )
    assert ohne_entfernte is not None
    assert ohne_entfernte.kpi_konfigurationen == ()


def test_vorlage_ohne_kpis_bleibt_nutzbar_aber_nicht_nach_neuer_p_grundlage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, projekte, _, projekt, freigabe, analyse, _, _, _ = _umgebung(
        tmp_path, ausgewaehlte_kpi_ids=()
    )
    ankunft = AnkunftsstromDefinition(
        "Erste Ankunft",
        Datenartefakt.EVENT_LOG_E_STERN,
        "case_id",
        "timestamp",
        aktivitaet="A",
    )
    alt = service.speichern(
        uuid4(),
        service.vorschau(
            projekt_id=projekt.projekt_id,
            freigabe_id=freigabe.freigabe_id,
            analyse_id=analyse.analyse_id,
            entitaetstyp="Auftrag",
            ankunftsstroeme=(ankunft,),
        ),
        menschlich_bestaetigt=True,
    )
    projekte.projekt = replace(
        projekt,
        untersuchungsauftrag=replace(
            projekt.untersuchungsauftrag,
            ausgewaehlte_kpi_ids=("servicegrad",),
        ),
        geaendert_am=projekt.geaendert_am + timedelta(minutes=1),
    )

    vorlage = service.kompatible_konfigurationsvorlage_laden(
        projekt.projekt_id, freigabe.freigabe_id, analyse.analyse_id
    )
    assert vorlage is not None
    assert vorlage.aggregations_id == alt.aggregations_id
    assert vorlage.kpi_konfigurationen == ()
    assert vorlage.entitaetstyp == "Auftrag"
    assert vorlage.ankunftsstroeme == (ankunft,)

    process = cast(Any, service._process_mining)
    process.modell = b"<?xml version='1.0'?><ptml><changed/></ptml>"
    process.a_d["prozessmodell_p"]["sha256"] = hashlib.sha256(process.modell).hexdigest()
    assert (
        service.kompatible_konfigurationsvorlage_laden(
            projekt.projekt_id, freigabe.freigabe_id, analyse.analyse_id
        )
        is None
    )


def test_manuelle_kpi_und_globale_zeitvereinfachung_werden_persistiert_und_restauriert(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    service, _, projekte, _, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
    manuell = KpiKonfiguration(
        "servicegrad",
        (),
        "%",
        "Kundenauftragspositionen",
        behandlungsart=KpiBehandlungsart.SPAETER_MANUELL_BERECHNEN,
    )
    ohne_vereinfachung = service.konfigurationsfingerabdruck(
        kpi_konfigurationen=(manuell,),
        sollmodell=None,
        aktivitaetsmapping=None,
        conformance_ausfuehren=False,
        sollzeitdaten=None,
        zeitvergleich_konfiguration=None,
        zeitvergleich_ausfuehren=False,
        vereinfachte_zeitspannen_bestaetigt=False,
    )
    vorschau = service.vorschau(
        projekt_id=projekt.projekt_id,
        freigabe_id=freigabe.freigabe_id,
        analyse_id=analyse.analyse_id,
        kpi_konfigurationen=(manuell,),
        vereinfachte_zeitspannen_bestaetigt=True,
    )

    assert vorschau.konfigurationsfingerabdruck != ohne_vereinfachung
    assert vorschau.kpi_ergebnisse[0].status is KpiStatus.FUER_SPAETERE_MANUELLE_BERECHNUNG
    assert vorschau.kpi_ergebnisse[0].ergebnis is None
    gespeichert = service.speichern(uuid4(), vorschau, menschlich_bestaetigt=True)
    _, a_g = service.laden(gespeichert.aggregations_id)
    assert a_g["kpi_konfigurationen"][0]["behandlungsart"] == "spaeter_manuell_berechnen"
    assert a_g["kpi_ergebnisse"][0]["status"] == ("fuer_spaetere_manuelle_berechnung_vorgesehen")
    assert a_g["kpi_ergebnisse"][0]["ergebnis"] is None
    assert a_g["kpi_ergebnisse"][0]["formel"]
    assert a_g["konfiguration"]["vereinfachte_zeitspannen_bestaetigt"] is True

    projekte.projekt = replace(
        projekt,
        untersuchungsauftrag=replace(
            projekt.untersuchungsauftrag,
            ausgewaehlte_kpi_ids=("servicegrad", "nacharbeitsquote_rr"),
        ),
        geaendert_am=projekt.geaendert_am + timedelta(minutes=1),
    )
    vorlage = service.kompatible_konfigurationsvorlage_laden(
        projekt.projekt_id, freigabe.freigabe_id, analyse.analyse_id
    )

    assert vorlage is not None
    assert vorlage.kpi_konfigurationen == (manuell,)
    assert (
        vorlage.kpi_konfigurationen[0].behandlungsart is KpiBehandlungsart.SPAETER_MANUELL_BERECHNEN
    )
    assert vorlage.vereinfachte_zeitspannen_bestaetigt is True
