"""Vollständiger Demo-, Rehydrierungs- und Archiv-Roundtrip auf echten Services."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

import pytest

from framework_mvp.bootstrap import (
    erstelle_autorisierungs_service,
    erstelle_datenqualitaet_service,
    erstelle_demoprojekt_service,
    erstelle_ergebnisaggregation_service,
    erstelle_event_log_konfigurations_service,
    erstelle_fortschritt_service,
    erstelle_modellableitung_service,
    erstelle_modellausgabe_service,
    erstelle_modellvalidierung_service,
    erstelle_process_mining_service,
    erstelle_projekt_service,
    erstelle_projektarchiv_service,
    erstelle_projektkontext_service,
)
from framework_mvp.domain.models.zugriff import Projektaktion, Zugriffskontext
from framework_mvp.ui.projektkontext import projektkontext_setzen
from framework_mvp.workspace import WorkspaceKonfiguration


def test_vollstaendiges_demo_bleibt_nach_export_import_und_leerer_session_nutzbar(
    tmp_path: Path,
) -> None:
    quell_db = tmp_path / "quelle.sqlite"
    quell_ws = WorkspaceKonfiguration.ermitteln(tmp_path / "quell-workspace")
    quell_kontext = Zugriffskontext.gast("quelle-" + "a" * 40)
    demo_service = erstelle_demoprojekt_service(quell_db, quell_ws)
    demo = demo_service.erstellen(quell_kontext)
    projekt_id = demo.projekt.projekt_id
    wiederholt = demo_service.erstellen(quell_kontext)
    assert wiederholt.projekt.projekt_id == projekt_id
    assert wiederholt.report_html == demo.report_html

    quell_rehydriert = erstelle_projektkontext_service(quell_db, quell_ws).pruefen(projekt_id)
    assert quell_rehydriert.framework_schritt == 10
    assert {
        "aktuelle_datenquellen_id",
        "aktueller_zwischendatensatz_id",
        "aktuelle_mappingtabelle_id",
        "aktuelle_event_log_konfiguration_id",
        "aktuelles_event_log_id",
        "aktuelle_freigabe_id",
        "aktuelle_analyse_id",
        "aktuelle_aggregations_id",
        "aktuelle_modellableitungs_id",
        "aktuelle_validierungslauf_id",
        "aktuelle_k_stern_id",
    } <= set(quell_rehydriert.referenzen)
    assert demo.report_html.startswith(b"<!DOCTYPE html")
    assert demo.report_pdf.startswith(b"%PDF")

    projekt = erstelle_projekt_service(quell_db).projekt_laden(projekt_id)
    assert projekt is not None
    produktion = projekt.untersuchungsauftrag.systemklassifikation.produktion
    assert produktion is not None
    assert produktion.auftragsabwicklungsstrategie == "Make-to-Order (MTO)"
    assert produktion.auflagegroesse == "Serienproduktion"
    assert produktion.produktionsstueckzahl == "mittel (101-10 000 Stück)"
    assert produktion.produktvielfalt == "gering (1-10 Var.)"
    assert produktion.organisationstyp == "Werkstattfertigung"
    assert produktion.anzahl_arbeitsgaenge == "mehrstufig"
    assert produktion.ressourcen == (
        "Maschinen",
        "Anlagen",
        "Arbeitsplätze",
        "Werkzeuge",
        "Informationssysteme",
    )

    konfiguration = erstelle_event_log_konfigurations_service(quell_db, quell_ws).laden(
        UUID(quell_rehydriert.referenzen["aktuelle_event_log_konfiguration_id"])
    )
    assert konfiguration is not None
    assert konfiguration.fall_id.spalten == ("Produktionsauftrag",)
    assert konfiguration.aktivitaetsspalte == "Vorgang"
    assert konfiguration.zeitstempelspalte == "Buchungszeitpunkt"
    assert konfiguration.startzeitstempelspalte == "Ist_Start"
    assert konfiguration.endzeitstempelspalte == "Ist_Ende"
    assert konfiguration.ressourcen_spalte == "Ressourcenbezeichnung"

    freigabe_id = UUID(quell_rehydriert.referenzen["aktuelle_freigabe_id"])
    entscheidungen = erstelle_datenqualitaet_service(
        quell_db, quell_ws
    ).entscheidungen_der_freigabe(freigabe_id)
    assert {wert.kriterium_id for wert in entscheidungen} == {
        "q_nachvollziehbar",
        "e_interpretierbar",
    }
    assert all(not wert.ist_mangel and wert.begruendung for wert in entscheidungen)

    analyse_id = UUID(quell_rehydriert.referenzen["aktuelle_analyse_id"])
    _, a_d, prozessmodell = erstelle_process_mining_service(quell_db, quell_ws).uebergabe_laden(
        analyse_id, projekt_id, freigabe_id
    )
    assert a_d["schwellwert_k"] == 0.05
    assert a_d["prozessnotation"] == "bpmn"
    assert a_d["dfg_daten"]["kanten"]
    assert b"bpmn" in prozessmodell.lower()

    aggregations_id = UUID(quell_rehydriert.referenzen["aktuelle_aggregations_id"])
    _, a_g = erstelle_ergebnisaggregation_service(quell_db, quell_ws).laden(aggregations_id)
    assert a_g["kpi_konfigurationen"]
    assert a_g["conformance_checking"]["durchgefuehrt"] is True
    assert a_g["strukturierte_ergebnisse"]["ressourcen"]

    ableitungs_id = UUID(quell_rehydriert.referenzen["aktuelle_modellableitungs_id"])
    _, k, o = erstelle_modellableitung_service(quell_db, quell_ws).laden(ableitungs_id)
    assert len(k["modellbestandteile"]) == 16
    assert len(k["fachliche_entscheidungen"]) == 16
    assert all(wert["begruendung"] for wert in k["fachliche_entscheidungen"])
    assert "offene_eintraege" in o

    validierungslauf_id = UUID(quell_rehydriert.referenzen["aktuelle_validierungslauf_id"])
    _, k_stern = erstelle_modellvalidierung_service(quell_db, quell_ws).laden(validierungslauf_id)
    assert len(k_stern["modellbestandteile"]) == 16
    assert k_stern["gesamtvalidierung"]["menschlich_bestaetigt"] is True
    k_stern_id = UUID(quell_rehydriert.referenzen["aktuelle_k_stern_id"])
    persistierte_ausgabe = erstelle_modellausgabe_service(
        quell_db, quell_ws
    ).persistierte_ausgabe_laden(
        projekt_id=projekt_id,
        validierungslauf_id=validierungslauf_id,
        k_stern_id=k_stern_id,
    )
    assert persistierte_ausgabe is not None
    assert persistierte_ausgabe.report_html == demo.report_html
    assert persistierte_ausgabe.report_pdf == demo.report_pdf

    fremder_gast = Zugriffskontext.gast("fremd-" + "b" * 40)
    assert not erstelle_autorisierungs_service(quell_db).projekt_zugriff_erlaubt(
        fremder_gast, projekt_id, Projektaktion.ANSEHEN
    )

    archiv = erstelle_projektarchiv_service(quell_db, quell_ws).exportieren(
        quell_kontext, projekt_id
    )
    assert quell_kontext.gast_geheimnis.encode() not in archiv

    ziel_db = tmp_path / "ziel.sqlite"
    ziel_ws = WorkspaceKonfiguration.ermitteln(tmp_path / "ziel-workspace")
    ziel_kontext = Zugriffskontext.gast("ziel-" + "c" * 40)
    importiert = erstelle_projektarchiv_service(ziel_db, ziel_ws).importieren(ziel_kontext, archiv)
    assert importiert.projekt_id == projekt_id

    ziel_rehydriert = erstelle_projektkontext_service(ziel_db, ziel_ws).pruefen(projekt_id)
    assert ziel_rehydriert.framework_schritt == 10
    assert ziel_rehydriert.referenzen == quell_rehydriert.referenzen
    leere_session: dict[str, object] = {}
    projektkontext_setzen(leere_session, ziel_rehydriert)
    assert leere_session["aktuelles_projekt_id"] == str(projekt_id)
    assert (
        leere_session["aktuelle_k_stern_id"] == quell_rehydriert.referenzen["aktuelle_k_stern_id"]
    )
    assert erstelle_fortschritt_service(ziel_db).laden(ziel_kontext, projekt_id).schritt == 10
    importierte_ausgabe = erstelle_modellausgabe_service(
        ziel_db, ziel_ws
    ).persistierte_ausgabe_laden(
        projekt_id=projekt_id,
        validierungslauf_id=UUID(ziel_rehydriert.referenzen["aktuelle_validierungslauf_id"]),
        k_stern_id=UUID(ziel_rehydriert.referenzen["aktuelle_k_stern_id"]),
    )
    assert importierte_ausgabe is not None
    assert importierte_ausgabe.report_html == demo.report_html
    assert importierte_ausgabe.report_pdf == demo.report_pdf

    with sqlite3.connect(ziel_db) as verbindung:
        for tabelle in (
            "datenquellen",
            "importvorgaenge",
            "transformationsplaene",
            "zwischendatensaetze",
            "mappingtabellen",
            "semantische_mappings",
            "event_logs",
            "qualitaetspruefungen",
            "process_mining_analysen",
            "ergebnisaggregationen",
            "modellableitungen",
            "modellvalidierungen",
            "projektfortschritt",
        ):
            assert verbindung.execute(
                f"SELECT COUNT(*) FROM {tabelle} WHERE projekt_id=?",  # noqa: S608
                (str(projekt_id),),
            ).fetchone()[0]


def test_import_nachpruefung_rollt_unvollstaendiges_neuprojekt_zurueck(
    tmp_path: Path,
) -> None:
    """Die Nachprüfung ist Teil der atomaren Übernahme und lässt keinen DB-Rest zurück."""
    # Der detaillierte ZIP-Manipulationsschutz wird in test_projektarchiv_service geprüft.
    # Hier genügt ein explizit fehlschlagender Nachprüfer für den Rollbackvertrag.
    from framework_mvp.application.autorisierung import AutorisierungsService
    from framework_mvp.application.mandanten_projekt_service import MandantenProjektService
    from framework_mvp.application.projekt_service import ProjektService
    from framework_mvp.application.projektarchiv_service import ProjektArchivService
    from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
    from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
        SQLiteProjektRepository,
    )
    from framework_mvp.infrastructure.persistence.sqlite_zugriffs_repository import (
        SQLiteZugriffsRepository,
    )

    quell_db = tmp_path / "klein-quelle.sqlite"
    quell_ws = WorkspaceKonfiguration.ermitteln(tmp_path / "klein-quelle")
    kontext = Zugriffskontext.gast("rollback-" + "d" * 40)
    quell_repository = SQLiteZugriffsRepository(quell_db)
    quell_autorisierung = AutorisierungsService(quell_repository)
    projekt = MandantenProjektService(
        ProjektService(SQLiteProjektRepository(quell_db)),
        quell_repository,
        quell_autorisierung,
    ).projekt_anlegen(
        kontext,
        bezeichnung="Rollback-Projekt",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Problem", "Zweck", Systemtyp.PRODUKTION, "System"
        ),
    )
    quell_archivservice = ProjektArchivService(
        quell_db, quell_ws, quell_repository, quell_autorisierung
    )
    archiv = quell_archivservice.exportieren(kontext, projekt.projekt_id)

    ziel_db = tmp_path / "klein-ziel.sqlite"
    ziel_ws = WorkspaceKonfiguration.ermitteln(tmp_path / "klein-ziel")
    repository = SQLiteZugriffsRepository(ziel_db)
    service = ProjektArchivService(
        ziel_db,
        ziel_ws,
        repository,
        AutorisierungsService(repository),
        konsistenzpruefung=lambda _projekt_id: (_ for _ in ()).throw(ValueError("kaputt")),
    )
    with pytest.raises(ValueError, match="kaputt"):
        service.importieren(Zugriffskontext.gast("neu-" + "e" * 40), archiv)
    with sqlite3.connect(ziel_db) as verbindung:
        assert verbindung.execute("SELECT COUNT(*) FROM projekte").fetchone() == (0,)
    assert not (ziel_ws.basisverzeichnis / "projects" / str(projekt.projekt_id)).exists()
