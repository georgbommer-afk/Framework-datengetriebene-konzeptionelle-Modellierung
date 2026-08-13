"""Session-State-Verträge nach kontrollierten Löschaktionen."""

from uuid import uuid4

from framework_mvp.ui.session_cleanup import (
    projekt_zustand_bereinigen,
    zwischendatensatz_zustand_bereinigen,
)


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
        "etl_wizard_zustaende": {str(projekt_id): {"schritt": 5}, "fremd": {"schritt": 2}},
        f"widget_{datensatz_id}": "veraltet",
    }

    zwischendatensatz_zustand_bereinigen(zustand, projekt_id, datensatz_id)

    assert zustand["aktuelles_projekt_id"] == str(projekt_id)
    assert "aktueller_zwischendatensatz_id" not in zustand
    assert "aktuelles_event_log_id" not in zustand
    assert "aktuelle_validierungslauf_id" not in zustand
    assert str(projekt_id) not in zustand["etl_wizard_zustaende"]
    assert zustand["etl_wizard_zustaende"]["fremd"] == {"schritt": 2}
    assert zustand["framework_bereich"] == "2 ETL durchführen"


def test_projektloeschung_entfernt_projektkontext_und_oeffnet_schritt_eins() -> None:
    projekt_id = uuid4()
    zustand = {
        "aktuelles_projekt_id": str(projekt_id),
        "ausgewaehlte_projekt_id": projekt_id,
        "wizard_entwurf": {"bezeichnung": "Alt"},
        "wizard_schritt": 5,
        f"projektrahmen_{projekt_id}_feld": "Alt",
        "unabhaengig": "bleibt",
    }

    projekt_zustand_bereinigen(zustand, projekt_id)

    assert "aktuelles_projekt_id" not in zustand
    assert "ausgewaehlte_projekt_id" not in zustand
    assert "wizard_entwurf" not in zustand
    assert zustand["unabhaengig"] == "bleibt"
    assert zustand["framework_bereich"] == "Schritt 1: Projektrahmen definieren"
