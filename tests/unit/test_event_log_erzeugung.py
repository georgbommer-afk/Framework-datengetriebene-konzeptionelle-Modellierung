"""Unit-Tests des kanonischen Event-Log-Aufbaus."""

from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd

from framework_mvp.application.event_log import erzeuge_event_log
from framework_mvp.domain.models import (
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
    zeitzuordnungen: tuple[ZeitstempelZuordnung, ...] = (),
) -> SemantischesMapping:
    jetzt = datetime.now(UTC)
    return SemantischesMapping(
        uuid4(),
        uuid4(),
        uuid4(),
        modus,
        ZusammengesetzteFallId(("auftrag", "position"), "/"),
        "aktivitaet" if modus is MappingModus.EREIGNISORIENTIERT else "",
        "zeit" if modus is MappingModus.EREIGNISORIENTIERT else "",
        "",
        "",
        "",
        "ressource",
        (Spaltenzuordnung("produkt", Attributrolle.FALLATTRIBUT),),
        zeitzuordnungen,
        None,
        jetzt,
        jetzt,
        Mappingstatus.VALIDIERT,
    )


def test_ereignisorientiertes_mapping_event_id_attribute_und_sortierung() -> None:
    """Quellzeilen werden stabil standardisiert, sortiert und nicht mutiert."""
    daten = pd.DataFrame(
        {
            "auftrag": ["A", "A"],
            "position": [1, 1],
            "aktivitaet": ["Ende", "Start"],
            "zeit": ["2025-01-01 10:00", "2025-01-01 10:00"],
            "ressource": ["R2", "R1"],
            "produkt": ["P", "P"],
        }
    )
    original = daten.copy(deep=True)
    mapping = _mapping(MappingModus.EREIGNISORIENTIERT)
    datensatz_id = uuid4()
    eins = erzeuge_event_log(daten, mapping, datensatz_id)
    zwei = erzeuge_event_log(daten, mapping, datensatz_id)
    pd.testing.assert_frame_equal(daten, original)
    assert eins.ereignisse["case_id"].tolist() == ["A/1", "A/1"]
    assert eins.ereignisse["_source_row"].tolist() == [0, 1]
    assert eins.ereignisse["event_id"].tolist() == zwei.ereignisse["event_id"].tolist()
    assert eins.ereignisanzahl == 2
    assert eins.fallanzahl == 1
    assert eins.aktivitaetsanzahl == 2
    assert eins.attributrollen["produkt"] == Attributrolle.FALLATTRIBUT.value


def test_breiter_datensatz_wird_unpivotiert_und_leere_zeit_uebersprungen() -> None:
    """Nur vorhandene konfigurierte Zeitstempel erzeugen Ereignisse mit Herkunft."""
    daten = pd.DataFrame(
        {
            "auftrag": ["A"],
            "position": [1],
            "erstellt": ["2025-01-01"],
            "beendet": [None],
            "ressource": ["R"],
            "produkt": ["P"],
        }
    )
    mapping = _mapping(
        MappingModus.BREITER_ZEITSTEMPELDATENSATZ,
        zeitzuordnungen=(
            ZeitstempelZuordnung("erstellt", "Erstellt", "ressource"),
            ZeitstempelZuordnung("beendet", "Beendet", "ressource"),
        ),
    )
    ergebnis = erzeuge_event_log(daten, mapping, uuid4())
    assert ergebnis.ereignisanzahl == 1
    assert ergebnis.ereignisse["activity"].tolist() == ["Erstellt"]
    assert ergebnis.ereignisse["_source_timestamp_column"].tolist() == ["erstellt"]
    assert ergebnis.ereignisse["produkt"].tolist() == ["P"]
