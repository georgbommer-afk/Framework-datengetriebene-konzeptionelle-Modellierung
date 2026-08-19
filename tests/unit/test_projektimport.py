"""Deterministische Session- und Widget-Identitäten des Projektimports."""

from uuid import uuid4

from framework_mvp.application.projektarchiv_service import (
    ArchivStaging,
    GestagterProjektimport,
)
from framework_mvp.ui.projektimport import (
    PROJEKTIMPORT_ZUSTAND,
    ProjektImportPhase,
    ProjektImportZustand,
    projektimport_session_zuruecksetzen,
    projektimport_widget_key,
)


def test_importbutton_keys_sind_eindeutig_und_ueber_reruns_stabil() -> None:
    projekt_id = uuid4()
    archiv_hash = "a" * 64
    aktionen = ("pruefen", "abbrechen", "ausfuehren", "ersetzen")

    erster_run = [projektimport_widget_key(aktion, projekt_id, archiv_hash) for aktion in aktionen]
    zweiter_run = [projektimport_widget_key(aktion, projekt_id, archiv_hash) for aktion in aktionen]

    assert erster_run == zweiter_run
    assert len(set(erster_run)) == len(aktionen)
    assert all(str(projekt_id) in key and archiv_hash[:16] in key for key in erster_run)
    assert projektimport_widget_key("oeffnen", projekt_id).startswith("projektimport_oeffnen_")


def test_importzustand_bewahrt_staging_pruefung_und_konflikt() -> None:
    staging_id = uuid4()
    projekt_id = uuid4()
    zustand = ProjektImportZustand.aus_staging(
        ArchivStaging(staging_id, "b" * 64, "aktuelle Gastsitzung", None)
    )
    pruefung = GestagterProjektimport(
        staging_id,
        "b" * 64,
        1,
        projekt_id,
        "Portables Projekt",
        "2026-08-19T10:00:00+00:00",
        True,
        "aktuelle Gastsitzung",
        None,
    )

    validiert = zustand.mit_pruefung(pruefung)

    assert validiert.phase is ProjektImportPhase.KONFLIKT
    assert validiert.projekt_id == projekt_id
    assert validiert.archivversion == 1
    assert validiert.bereits_vorhanden is True


def test_import_session_cleanup_entfernt_keinen_fremden_sessionzustand() -> None:
    zustand = {
        PROJEKTIMPORT_ZUSTAND: object(),
        "projektimport_offen": True,
        "projektimport_generation": 4,
        "aktuelles_projekt_id": "bleibt",
        "gast_geheimnis": "bleibt-geheim",
    }

    projektimport_session_zuruecksetzen(zustand)

    assert PROJEKTIMPORT_ZUSTAND not in zustand
    assert zustand["projektimport_offen"] is False
    assert zustand["projektimport_generation"] == 5
    assert zustand["aktuelles_projekt_id"] == "bleibt"
    assert zustand["gast_geheimnis"] == "bleibt-geheim"
