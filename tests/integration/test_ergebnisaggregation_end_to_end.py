"""End-to-End-Vertrag von Algorithmus 7 mit unveränderter Eingabekette."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
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
    Datenartefakt,
    DiscoveryVerfahren,
    Freigabestatus,
    KpiKonfiguration,
    KpiStatus,
    LogistischeZielgroesse,
    Mappingzustand,
    OperandZuordnung,
    ProcessMiningAnalyse,
    ProcessMiningStatus,
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


def _umgebung(tmp_path):  # type: ignore[no-untyped-def]
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
        logistische_zielgroessen=(LogistischeZielgroesse.LIEFERFAEHIGKEIT,),
        ausgewaehlte_kpi_ids=("servicegrad",),
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
        2,
        import_id,
        "1" * 64,
        {},
        "Tabelle",
        jetzt,
        {
            "zeilen": 3,
            "spaltenprofile": [
                {
                    "spaltenname": "wert",
                    "numerisch": {"mittelwert": 2.0, "gueltige_werte": 3},
                }
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
    assert a_g["artefaktversion"] == 2
    assert a_g["strukturierte_ergebnisse"]["ergebnisversion"] == 1
    assert a_g["optionale_artefakte"] == {}
    assert p_uebergabe == modell
    assert a_g_uebergabe == a_g
    pd.testing.assert_frame_equal(tabelle, t_vorher)
    pd.testing.assert_frame_equal(event_log, e_vorher)


def test_a_g_v1_bleibt_lesbar_waehrend_neue_speicherungen_v2_schreiben(tmp_path) -> None:  # type: ignore[no-untyped-def]
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
    service, _, _, _, projekt, freigabe, analyse, _, _, _ = _umgebung(tmp_path)
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
    assert optionen["prozessmodell_p_soll"]["original_sha256"] == sollmodell.metadaten.sha256
    assert optionen["aktivitaetsmapping"]["sha256"]
    assert optionen["conformance_ergebnisse_a_c"]["sha256"]
    assert optionen["conformance_ergebnisse_a_c"]["detail_csv_sha256"]
    assert optionen["sollzeitdaten"]["sha256"] == sollzeit.sha256
    assert optionen["potenzielle_verbesserungspotenziale_a_v"]["sha256"]
