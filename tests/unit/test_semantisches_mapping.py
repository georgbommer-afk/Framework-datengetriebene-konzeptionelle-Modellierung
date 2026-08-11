"""Schritt-4-Tests für Event-Log-Struktur und Rollenvalidierung."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd

from framework_mvp.application.mapping import validiere_mapping
from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    Attributrolle,
    MappingModus,
    Mappingstatus,
    SemantischesMapping,
    Spaltenzuordnung,
    ZeitstempelZuordnung,
    ZusammengesetzteFallId,
)


def _mapping(
    modus: MappingModus,
    *,
    aktivitaet: str = "activity",
    zeitstempel: str = "time",
    zeitzuordnungen: tuple[ZeitstempelZuordnung, ...] = (),
) -> SemantischesMapping:
    jetzt = datetime.now(UTC)
    return SemantischesMapping(
        uuid4(),
        uuid4(),
        uuid4(),
        modus,
        ZusammengesetzteFallId(("order", "item"), "/"),
        aktivitaet,
        zeitstempel,
        "",
        "",
        "",
        "",
        (),
        zeitzuordnungen,
        None,
        jetzt,
        jetzt,
        Mappingstatus.ENTWURF,
    )


def test_ereignisorientiertes_mapping_bildet_zusammengesetzte_fall_id() -> None:
    """Mehrere technische Schlüssel werden mit dem konfigurierten Separator verbunden."""
    daten = pd.DataFrame(
        {
            "order": ["A", "A"],
            "item": [1, 1],
            "activity": ["Start", "Ende"],
            "time": ["2025-01-01", "2025-01-02"],
        }
    )
    ergebnis = validiere_mapping(daten, _mapping(MappingModus.EREIGNISORIENTIERT))
    assert ergebnis.validierung.gueltig
    assert ergebnis.vollstaendige_ereignisse["case_id"].tolist() == ["A/1", "A/1"]
    assert ergebnis.validierung.unterschiedliche_aktivitaeten == 2


def test_breites_mapping_erzeugt_eine_ereigniszeile_je_zeitstempel() -> None:
    """Breite Daten werden nur für die Vorschau kontrolliert in Ereignisse umgeformt."""
    daten = pd.DataFrame(
        {
            "order": ["A"],
            "item": [1],
            "created": ["2025-01-01"],
            "finished": ["2025-01-03"],
        }
    )
    mapping = _mapping(
        MappingModus.BREITER_ZEITSTEMPELDATENSATZ,
        aktivitaet="",
        zeitstempel="",
        zeitzuordnungen=(
            ZeitstempelZuordnung("created", "Erstellt"),
            ZeitstempelZuordnung("finished", "Abgeschlossen"),
        ),
    )
    ergebnis = validiere_mapping(daten, mapping)
    assert ergebnis.validierung.gueltig
    assert ergebnis.vollstaendige_ereignisse["activity"].tolist() == [
        "Erstellt",
        "Abgeschlossen",
    ]


def test_mapping_meldet_fehlende_rollenwerte_als_fehler() -> None:
    """Fehlende Fall-ID, Aktivität und ungültige Zeit verhindern einen gültigen Status."""
    daten = pd.DataFrame({"order": [None], "item": [1], "activity": [""], "time": ["kein Datum"]})
    ergebnis = validiere_mapping(daten, _mapping(MappingModus.EREIGNISORIENTIERT))
    assert not ergebnis.validierung.gueltig
    assert {warnung.code for warnung in ergebnis.validierung.warnungen} >= {
        "FEHLENDE_FALL_ID",
        "FEHLENDE_AKTIVITAET",
        "UNGUELTIGE_ZEIT",
    }


def test_zusammengesetzte_aktivitaet_wird_in_der_vorschau_berechnet() -> None:
    """Mehrere Spalten bilden eine virtuelle Aktivität, ohne die Daten zu verändern."""
    daten = pd.DataFrame(
        {
            "order": ["A", "A"],
            "item": [1, 1],
            "von": ["C01", None],
            "zu": ["MAS", "Z02"],
            "time": ["2025-01-01", "2025-01-02"],
        }
    )
    original = daten.copy(deep=True)
    mapping = _mapping(MappingModus.EREIGNISORIENTIERT, aktivitaet="")
    mapping = replace(
        mapping,
        aktivitaetsdefinition=Aktivitaetsdefinition(
            Aktivitaetsbildungsart.ZUSAMMENGESETZT,
            ("von", "zu"),
            " → ",
            "von ",
            "",
            "Nur vorhandene Bestandteile kombinieren",
        ),
    )
    ergebnis = validiere_mapping(daten, mapping)
    assert ergebnis.vollstaendige_ereignisse["activity"].tolist() == [
        "von C01 → MAS",
        "von Z02",
    ]
    pd.testing.assert_frame_equal(daten, original)


def test_breite_doppelte_aktivitaetsbezeichnungen_sind_ungueltig() -> None:
    """Mehrere Zeitstempelspalten benötigen eindeutige Aktivitätsbezeichnungen."""
    daten = pd.DataFrame(
        {
            "order": ["A"],
            "item": [1],
            "start": ["2025-01-01"],
            "ende": ["2025-01-02"],
        }
    )
    mapping = _mapping(
        MappingModus.BREITER_ZEITSTEMPELDATENSATZ,
        aktivitaet="",
        zeitstempel="",
        zeitzuordnungen=(
            ZeitstempelZuordnung("start", "Bearbeitung"),
            ZeitstempelZuordnung("ende", "Bearbeitung"),
        ),
    )
    ergebnis = validiere_mapping(daten, mapping)
    assert not ergebnis.validierung.gueltig
    assert "DOPPELTE_AKTIVITAETSBEZEICHNUNG" in {
        wert.code for wert in ergebnis.validierung.warnungen
    }


def test_wechselndes_fallattribut_wird_als_warnung_gemeldet() -> None:
    """Ein innerhalb des Falls wechselnder Wert verhindert Speichern nicht automatisch."""
    daten = pd.DataFrame(
        {
            "order": ["A", "A"],
            "item": [1, 1],
            "activity": ["Start", "Ende"],
            "time": ["2025-01-01", "2025-01-02"],
            "menge": [10, 20],
        }
    )
    mapping = replace(
        _mapping(MappingModus.EREIGNISORIENTIERT),
        spaltenzuordnungen=(Spaltenzuordnung("menge", Attributrolle.FALLATTRIBUT),),
    )
    ergebnis = validiere_mapping(daten, mapping)
    assert ergebnis.validierung.gueltig
    assert "WECHSELNDES_FALLATTRIBUT" in {wert.code for wert in ergebnis.validierung.warnungen}
