"""Unit-Tests für Mappingmodi und Validierungswarnungen."""

from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd

from framework_mvp.application.mapping import validiere_mapping
from framework_mvp.domain.models import (
    MappingModus,
    Mappingstatus,
    SemantischesMapping,
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
