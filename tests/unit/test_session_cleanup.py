"""Session-State-Verträge nach kontrollierten Löschaktionen."""

from uuid import uuid4

from framework_mvp.ui.session_cleanup import (
    folgeartefakte_zustand_invalidieren,
    projekt_zustand_bereinigen,
    zwischendatensatz_zustand_bereinigen,
)


def test_neue_datenbasis_bewahrt_etl_und_invalidiert_alle_folgeartefakte() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    zustand = {
        "aktuelles_event_log_id": "alt",
        "aktuelle_analyse_id": "alt",
        "schritt10_ausgabe": b"alt",
        "etl_wizard_zustaende": {str(projekt_id): {"schritt": 4, "plan": "bleibt"}},
        "mapping_wizard_zustaende": {str(projekt_id): {"schritt": 3}},
    }

    folgeartefakte_zustand_invalidieren(zustand, projekt_id, datensatz_id)

    assert zustand["etl_wizard_zustaende"][str(projekt_id)]["plan"] == "bleibt"
    assert str(projekt_id) not in zustand["mapping_wizard_zustaende"]
    assert "aktuelles_event_log_id" not in zustand
    assert "aktuelle_analyse_id" not in zustand
    assert "schritt10_ausgabe" not in zustand
    assert zustand["aktueller_zwischendatensatz_id"] == str(datensatz_id)
    assert zustand["folgeartefakte_veraltet"] == str(projekt_id)


def test_t_loeschung_bereinigt_alle_abhaengigen_ids_und_projektzustaende() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    zustand = {
        "aktuelles_projekt_id": str(projekt_id),
        "aktueller_zwischendatensatz_id": str(datensatz_id),
        "aktuelles_event_log_id": "e",
        "aktuelle_freigabe_id": "q",
        "aktuelle_analyse_id": "p",
        "aktuelle_aggregations_id": "a",
        "aktuelle_modellableitungs_id": "k-o",
        "aktuelle_validierungslauf_id": "k-star",
        "schritt9_arbeitsfassung": {"veraltet": True},
        "etl_wizard_zustaende": {str(projekt_id): {"schritt": 5}, "fremd": {"schritt": 2}},
        f"widget_{datensatz_id}": "veraltet",
        "framework_bereich": "1 Projektrahmen definieren",
    }

    zwischendatensatz_zustand_bereinigen(zustand, projekt_id, datensatz_id)

    assert zustand["aktuelles_projekt_id"] == str(projekt_id)
    assert "aktueller_zwischendatensatz_id" not in zustand
    assert "aktuelles_event_log_id" not in zustand
    assert "aktuelle_validierungslauf_id" not in zustand
    assert str(projekt_id) not in zustand["etl_wizard_zustaende"]
    assert zustand["etl_wizard_zustaende"]["fremd"] == {"schritt": 2}
    assert "schritt9_arbeitsfassung" not in zustand
    assert zustand["framework_bereich"] == "1 Projektrahmen definieren"
    assert zustand["naechster_framework_bereich"] == "2 ETL durchführen"


def test_projektloeschung_entfernt_projektkontext_und_oeffnet_schritt_eins() -> None:
    projekt_id = uuid4()
    zustand = {
        "aktuelles_projekt_id": str(projekt_id),
        "ausgewaehlte_projekt_id": projekt_id,
        "wizard_entwurf": {"bezeichnung": "Alt"},
        "wizard_schritt": 5,
        f"projektrahmen_{projekt_id}_feld": "Alt",
        "unabhaengig": "bleibt",
        "framework_bereich": "7 Ergebnisse aggregieren",
    }

    projekt_zustand_bereinigen(zustand, projekt_id)

    assert "aktuelles_projekt_id" not in zustand
    assert "ausgewaehlte_projekt_id" not in zustand
    assert "wizard_entwurf" not in zustand
    assert zustand["unabhaengig"] == "bleibt"
    assert zustand["framework_bereich"] == "7 Ergebnisse aggregieren"
    assert zustand["naechster_framework_bereich"] == "1 Projektrahmen definieren"
