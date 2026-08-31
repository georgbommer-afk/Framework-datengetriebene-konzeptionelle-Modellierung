# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""End-to-End-Vertrag von Algorithmus 8 mit aktiver A_G-Lineage."""

import copy
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from framework_mvp.application.ergebnisaggregation.sollprozess import (
    erzeuge_lineares_sollmodell,
)
from framework_mvp.application.modellableitung import MAPPINGVERSION, MODELLBESTANDTEILE
from framework_mvp.application.modellableitung_service import ModellableitungService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Aggregationsstatus,
    Datenquelle,
    Eingangsartefakt,
    Ergebnisaggregation,
    FachlicheBestandteilentscheidung,
    FachlicheEntscheidungsart,
    LogistischeZielgroesse,
    ModellbestandteilId,
    Produktionsklassifikation,
    Projekt,
    Projektstatus,
    Quellenart,
    Quellsystemtyp,
    Systemklassifikation,
    Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.workspace import WorkspaceKonfiguration


class _Repository:
    def __init__(self) -> None:
        self.werte = {}

    def speichern(self, ableitung):  # type: ignore[no-untyped-def]
        if ableitung.modellableitungs_id in self.werte:
            raise AssertionError("doppelte ID")
        self.werte[ableitung.modellableitungs_id] = ableitung

    def laden(self, modellableitungs_id):  # type: ignore[no-untyped-def]
        return self.werte.get(modellableitungs_id)

    def finde_identisch(
        self,
        projekt_id,
        aggregations_id,
        eingabefingerabdruck,
        mappingversion,
        unsicherheitsfingerabdruck,
    ):  # type: ignore[no-untyped-def]
        return next(
            (
                wert
                for wert in self.werte.values()
                if wert.projekt_id == projekt_id
                and wert.aggregations_id == aggregations_id
                and wert.eingabefingerabdruck == eingabefingerabdruck
                and wert.mappingversion == mappingversion
                and wert.unsicherheitsfingerabdruck == unsicherheitsfingerabdruck
            ),
            None,
        )


class _Aggregationen:
    def __init__(self, aggregation, a_g, basis, p):  # type: ignore[no-untyped-def]
        self.aggregation = aggregation
        self.a_g = a_g
        self.basis = basis
        self.p = p

    def laden(self, aggregations_id):  # type: ignore[no-untyped-def]
        if aggregations_id != self.aggregation.aggregations_id:
            raise Importintegritaetsfehler("A_G fehlt")
        return self.aggregation, copy.deepcopy(self.a_g)

    def uebergabe_schritt8(self, aggregations_id, projekt_id, freigabe_id, analyse_id):  # type: ignore[no-untyped-def]
        assert (
            aggregations_id,
            projekt_id,
            freigabe_id,
            analyse_id,
        ) == (
            self.aggregation.aggregations_id,
            self.aggregation.projekt_id,
            self.aggregation.freigabe_id,
            self.aggregation.analyse_id,
        )
        return bytes(self.p), copy.deepcopy(self.a_g)

    def grundlage_laden(self, projekt_id, freigabe_id, analyse_id):  # type: ignore[no-untyped-def]
        assert projekt_id == self.basis.projekt.projekt_id
        assert freigabe_id == self.basis.freigabe.freigabe_id
        assert analyse_id == self.basis.analyse.analyse_id
        return self.basis


class _Transformationen:
    def __init__(self, import_id, projekt_id, datenquellen_id):  # type: ignore[no-untyped-def]
        self.import_id = import_id
        self.projekt_id = projekt_id
        self.datenquellen_id = datenquellen_id

    def import_laden(self, import_id):  # type: ignore[no-untyped-def]
        assert import_id == self.import_id
        return SimpleNamespace(
            importvorgang=SimpleNamespace(
                projekt_id=self.projekt_id,
                datenquellen_id=self.datenquellen_id,
            )
        )


class _Datenquellen:
    def __init__(self, quelle):  # type: ignore[no-untyped-def]
        self.quelle = quelle

    def datenquelle_laden(self, datenquellen_id):  # type: ignore[no-untyped-def]
        return (
            self.quelle
            if self.quelle is not None and datenquellen_id == self.quelle.datenquellen_id
            else None
        )


def _umgebung(tmp_path):  # type: ignore[no-untyped-def]
    jetzt = datetime.now(UTC)
    projekt_id, aggregations_id, freigabe_id, analyse_id, event_log_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    import_id, t_id = uuid4(), uuid4()
    auftrag = Untersuchungsauftrag(
        "Problem bleibt unverändert",
        "Leistung bewerten",
        Systemtyp.PRODUKTION,
        "Werk A",
        logistische_zielgroessen=(LogistischeZielgroesse.LIEFERFAEHIGKEIT,),
        ausgewaehlte_kpi_ids=("servicegrad",),
        systemklassifikation=Systemklassifikation(
            objekte_gueter="Produktionsauftrag",
            produktion=Produktionsklassifikation(ressourcen=("Maschinen",)),
        ),
    )
    projekt = Projekt(
        projekt_id,
        "Ableitung",
        (),
        Projektstatus.AKTIV,
        jetzt,
        jetzt,
        auftrag,
    )
    quelle = Datenquelle.neu(
        projekt_id=projekt_id,
        bezeichnung="ERP",
        quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
        quellenart=Quellenart.CSV,
    )
    p = erzeuge_lineares_sollmodell(
        projekt_id=projekt_id,
        aktivitaeten=("A", "B"),
        bezeichnung="P",
        fachliche_grundlage="Test",
        modellversion="1",
        person="Test",
        freigabedatum=date.today(),
        menschlich_bestaetigt=True,
    ).original_pnml
    p_sha = __import__("hashlib").sha256(p).hexdigest()
    tabelle = pd.DataFrame({"auftrag": [1, 2], "wert": [3.0, 4.0]})
    event_log = pd.DataFrame(
        {
            "case_id": ["1", "1", "2", "2"],
            "activity": ["A", "B", "A", "B"],
            "timestamp": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-01", "2026-01-03"], utc=True
            ),
        }
    )
    datensatz = SimpleNamespace(
        zwischendatensatz_id=t_id,
        projekt_id=projekt_id,
        import_ids=(import_id,),
        sha256="b" * 64,
        zeilenanzahl=2,
        spaltenanzahl=2,
        relativer_daten_pfad="projects/p/interim/t.csv.gz",
        relativer_schema_pfad="projects/p/interim/t.schema.json",
    )
    freigabe = SimpleNamespace(
        freigabe_id=freigabe_id,
        event_log_id=event_log_id,
        event_log_sha256="c" * 64,
    )
    analyse = SimpleNamespace(
        analyse_id=analyse_id,
        relativer_modell_pfad="projects/p/process_mining/p.pnml",
    )
    discovery = {
        "schwellwert_k": 0.0,
        "miner_variante": "inductive_miner",
        "prozessnotation": "petrinetz",
        "warnungen": [],
        "dfg_daten": {
            "startaktivitaeten": [["A", 2]],
            "endaktivitaeten": [["B", 2]],
        },
    }
    basis = SimpleNamespace(
        projekt=projekt,
        zwischendatensatz=datensatz,
        zwischendaten=tabelle,
        event_log=event_log,
        freigabe=freigabe,
        analyse=analyse,
        discovery_ergebnisse=discovery,
        prozessmodell_sha256=p_sha,
        datenprofil_sha256="d" * 64,
        profilreferenzen=(
            {
                "import_id": str(import_id),
                "profil_sha256": "e" * 64,
                "gesamtprofil": {"zeilen": 2},
            },
        ),
    )
    a_g = {
        "artefaktversion": 1,
        "aggregations_id": str(aggregations_id),
        "projekt_id": str(projekt_id),
        "spezifikations_id": str(projekt_id),
        "freigabe_id": str(freigabe_id),
        "event_log_id": str(event_log_id),
        "process_mining_analyse_id": str(analyse_id),
        "prozessmodell_p": {
            "sha256": p_sha,
            "prozessnotation": "petrinetz",
            "relativer_pfad": analyse.relativer_modell_pfad,
        },
        "kpi_ergebnisse": [
            {
                "kpi_id": "servicegrad",
                "status": "nicht_berechenbar",
                "ergebnis": None,
                "fehlende_voraussetzungen": ["Operand fehlt"],
            }
        ],
        "optionale_artefakte": {
            "prozessmodell_p_soll": {"sha256": "f" * 64},
        },
    }
    aggregation = Ergebnisaggregation(
        aggregations_id,
        projekt_id,
        projekt_id,
        freigabe_id,
        event_log_id,
        analyse_id,
        "1" * 64,
        "2" * 64,
        "projects/p/aggregation/ag.json",
        "3" * 64,
        Aggregationsstatus.GESPEICHERT,
        jetzt,
    )
    repository = _Repository()
    service = ModellableitungService(
        repository,
        _Aggregationen(aggregation, a_g, basis, p),
        _Transformationen(import_id, projekt_id, quelle.datenquellen_id),
        _Datenquellen(quelle),
        ImportartefaktSpeicher(WorkspaceKonfiguration(tmp_path / "workspace")),
    )
    return service, repository, basis, aggregation, a_g, p, quelle


def _entscheidungen(
    *, unsicher: frozenset[ModellbestandteilId] = frozenset()
) -> tuple[FachlicheBestandteilentscheidung, ...]:
    jetzt = datetime(2026, 8, 31, tzinfo=UTC)
    return tuple(
        FachlicheBestandteilentscheidung(
            definition.bestandteil_id,
            FachlicheEntscheidungsart.OFFEN_UNSICHER
            if definition.bestandteil_id in unsicher
            else FachlicheEntscheidungsart.UEBERNEHMEN,
            "Fachliche Prüfung in Schritt 9 erforderlich."
            if definition.bestandteil_id in unsicher
            else "",
            jetzt,
        )
        for definition in MODELLBESTANDTEILE
    )


def test_k_und_o_werden_atomar_idempotent_gespeichert_und_validiert(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, repository, basis, aggregation, a_g, p, quelle = _umgebung(tmp_path)
    projekt_vorher = copy.deepcopy(basis.projekt)
    profil_vorher = copy.deepcopy(basis.profilreferenzen)
    quelle_vorher = copy.deepcopy(quelle)
    t_vorher = basis.zwischendaten.copy(deep=True)
    e_vorher = basis.event_log.copy(deep=True)
    ag_vorher = copy.deepcopy(a_g)
    vorschau = service.vorschau(
        projekt_id=basis.projekt.projekt_id,
        aggregations_id=aggregation.aggregations_id,
        modellableitungs_id=uuid4(),
        k_id=uuid4(),
        o_id=uuid4(),
        entscheidungen=_entscheidungen(unsicher=frozenset({ModellbestandteilId.AKTIVITAETEN})),
    )
    gespeichert = service.speichern(vorschau)
    erneut, k, o = service.laden(gespeichert.modellableitungs_id)
    assert erneut == gespeichert
    assert len(k["modellbestandteile"]) == 16
    assert k["mappingversion"] == MAPPINGVERSION == 3
    assert k["menschlich_bestaetigt"] is True
    assert all(wert["status"] == "offen" for wert in o["offene_eintraege"])
    assert o["k_referenz"]["datei_sha256"] == gespeichert.k_sha256
    assert "prozessmodell_p_soll" not in str(k)
    assert service.uebergabe_schritt9(
        gespeichert.modellableitungs_id, basis.projekt.projekt_id
    ) == (k, o)
    zweite_vorschau = service.vorschau(
        projekt_id=basis.projekt.projekt_id,
        aggregations_id=aggregation.aggregations_id,
        modellableitungs_id=uuid4(),
        k_id=uuid4(),
        o_id=uuid4(),
        entscheidungen=_entscheidungen(unsicher=frozenset({ModellbestandteilId.AKTIVITAETEN})),
    )
    assert service.speichern(zweite_vorschau) == gespeichert
    assert len(repository.werte) == 1
    pd.testing.assert_frame_equal(basis.zwischendaten, t_vorher, check_dtype=True)
    pd.testing.assert_frame_equal(basis.event_log, e_vorher, check_dtype=True)
    assert a_g == ag_vorher
    assert basis.prozessmodell_sha256 == __import__("hashlib").sha256(p).hexdigest()
    assert basis.projekt == projekt_vorher
    assert basis.profilreferenzen == profil_vorher
    assert quelle == quelle_vorher


def test_speicherung_benoetigt_bestaetigung_und_invalide_lineage_blockiert(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, basis, aggregation, _, _, _ = _umgebung(tmp_path)
    vorschau = service.vorschau(
        projekt_id=basis.projekt.projekt_id,
        aggregations_id=aggregation.aggregations_id,
        modellableitungs_id=uuid4(),
        k_id=uuid4(),
        o_id=uuid4(),
    )
    with pytest.raises(Domaenenfehler, match="alle 16"):
        service.speichern(vorschau)
    fast_vollstaendig = service.vorschau(
        projekt_id=basis.projekt.projekt_id,
        aggregations_id=aggregation.aggregations_id,
        modellableitungs_id=uuid4(),
        k_id=uuid4(),
        o_id=uuid4(),
        entscheidungen=_entscheidungen()[:-1],
    )
    with pytest.raises(Domaenenfehler, match="alle 16"):
        service.speichern(fast_vollstaendig, menschlich_bestaetigt=True)
    vorschau = service.vorschau(
        projekt_id=basis.projekt.projekt_id,
        aggregations_id=aggregation.aggregations_id,
        modellableitungs_id=uuid4(),
        k_id=uuid4(),
        o_id=uuid4(),
        entscheidungen=_entscheidungen(),
    )
    basis.projekt = basis.projekt.aktualisiert(
        bezeichnung=basis.projekt.bezeichnung,
        untersuchungsauftrag=Untersuchungsauftrag(
            "Geändertes Problem",
            "Leistung bewerten",
            Systemtyp.PRODUKTION,
            "Werk A",
        ),
        status=Projektstatus.AKTIV,
    )
    with pytest.raises(Domaenenfehler, match="Neuberechnung"):
        service.speichern(vorschau)


def test_manipuliertes_k_wird_beim_laden_abgewiesen(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, basis, aggregation, _, _, _ = _umgebung(tmp_path)
    vorschau = service.vorschau(
        projekt_id=basis.projekt.projekt_id,
        aggregations_id=aggregation.aggregations_id,
        modellableitungs_id=uuid4(),
        k_id=uuid4(),
        o_id=uuid4(),
        entscheidungen=_entscheidungen(),
    )
    gespeichert = service.speichern(vorschau)
    service._artefakte.artefakt_ersetzen(  # noqa: SLF001
        gespeichert.relativer_k_pfad,
        service._artefakte.lesen(gespeichert.relativer_k_pfad) + b" ",  # noqa: SLF001
    )
    with pytest.raises(Importintegritaetsfehler, match="Dateiprüfsumme"):
        service.laden(gespeichert.modellableitungs_id)


def test_q_wird_nur_ueber_import_ids_der_aktiven_t_lineage_geladen(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, basis, aggregation, _, _, quelle = _umgebung(tmp_path)
    grundlage = service.grundlage_laden(basis.projekt.projekt_id, aggregation.aggregations_id)
    assert grundlage.datenquellen == (quelle,)
    assert grundlage.quellreferenzen[Eingangsartefakt.DATENQUELLENKATALOG_Q][
        "datenquellen_ids"
    ] == [str(quelle.datenquellen_id)]


def test_abweichende_p_referenz_in_a_g_blockiert_schritt_acht(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, basis, aggregation, _, _, _ = _umgebung(tmp_path)
    service._aggregationen.a_g["prozessmodell_p"]["sha256"] = "0" * 64  # noqa: SLF001

    with pytest.raises(Importintegritaetsfehler, match=r"P, E\*, Process-Mining-Analyse"):
        service.grundlage_laden(basis.projekt.projekt_id, aggregation.aggregations_id)


def test_fehlende_q_referenz_der_aktiven_t_lineage_blockiert(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, basis, aggregation, _, _, _ = _umgebung(tmp_path)
    service._datenquellen.quelle = None  # noqa: SLF001

    with pytest.raises(Importintegritaetsfehler, match="Datenquelle aus Q fehlt"):
        service.grundlage_laden(basis.projekt.projekt_id, aggregation.aggregations_id)


def test_entscheidung_und_begruendung_aendern_den_fingerabdruck(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, basis, aggregation, _, _, _ = _umgebung(tmp_path)
    akzeptiert = service.vorschau(
        projekt_id=basis.projekt.projekt_id,
        aggregations_id=aggregation.aggregations_id,
        modellableitungs_id=uuid4(),
        k_id=uuid4(),
        o_id=uuid4(),
        entscheidungen=_entscheidungen(),
    )
    unsicher = service.vorschau(
        projekt_id=basis.projekt.projekt_id,
        aggregations_id=aggregation.aggregations_id,
        modellableitungs_id=uuid4(),
        k_id=uuid4(),
        o_id=uuid4(),
        entscheidungen=_entscheidungen(unsicher=frozenset({ModellbestandteilId.RESSOURCEN})),
    )

    assert akzeptiert.entscheidungsfingerabdruck != unsicher.entscheidungsfingerabdruck
    ressourcen = next(
        wert
        for wert in unsicher.bestandteile
        if wert.bestandteil_id is ModellbestandteilId.RESSOURCEN
    )
    assert not ressourcen.informationen
    assert any(
        wert.bestandteil_id is ModellbestandteilId.RESSOURCEN
        and wert.kennzeichnungsherkunft.value == "menschlich_markiert"
        for wert in unsicher.offene_eintraege
    )


def test_historische_elfteilige_ableitung_bleibt_kontrolliert_lesbar() -> None:
    alte_ids = [
        "problemstellung",
        "zielsetzung",
        "ausgaben_und_eingaben",
        "modellumfang_grenzen_detaillierungsgrad",
        "entitaeten",
        "aktivitaeten",
        "warteschlangen",
        "ressourcen",
        "annahmen_und_vereinfachungen",
        "datenauswahl_und_daten",
        "darstellung_der_vorgaenge_des_systems",
    ]
    ableitung = SimpleNamespace(mappingversion=2)
    k = {
        "mappingversion": 2,
        "modellbestandteile": [{"bestandteil_id": wert} for wert in alte_ids],
    }
    o: dict[str, object] = {}

    _, gelesenes_k, gelesenes_o = ModellableitungService._historische_ableitung_pruefen(  # noqa: SLF001
        ableitung, k, o
    )

    assert gelesenes_k["historische_darstellung"] is True
    assert gelesenes_o["historische_darstellung"] is True
    assert [wert["bestandteil_id"] for wert in gelesenes_k["modellbestandteile"]] == alte_ids
