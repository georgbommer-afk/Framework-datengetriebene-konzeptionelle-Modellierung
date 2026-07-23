"""Unit-Tests des Datenquellen-Domänenmodells."""

from datetime import UTC
from uuid import uuid4

import pytest

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import Datenquelle, Quellenart, Quellsystemtyp


def test_bezeichnung_darf_nicht_leer_sein() -> None:
    """Eine leere Datenquellenbezeichnung wird fachlich abgelehnt."""
    with pytest.raises(Domaenenfehler):
        Datenquelle.neu(
            projekt_id=uuid4(),
            bezeichnung="   ",
            quellsystemtyp=Quellsystemtyp.DATEI_EXPORT,
            quellenart=Quellenart.CSV,
        )


def test_texte_und_listeneintraege_werden_normalisiert() -> None:
    """Rand-Leerzeichen und leere Listeneinträge werden entfernt."""
    datenquelle = Datenquelle.neu(
        projekt_id=uuid4(),
        bezeichnung=" Export ",
        quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
        quellenart=Quellenart.EXCEL,
        konkretes_quellsystem=" SAP S/4HANA ",
        erwartete_tabellen_oder_blaetter=(" Aufträge ", "", " Material "),
        bekannte_schluesselattribute=(" ID ", " "),
    )
    assert datenquelle.bezeichnung == "Export"
    assert datenquelle.konkretes_quellsystem == "SAP S/4HANA"
    assert datenquelle.erwartete_tabellen_oder_blaetter == ("Aufträge", "Material")
    assert datenquelle.bekannte_schluesselattribute == ("ID",)


def test_id_und_utc_zeitstempel_werden_automatisch_erzeugt() -> None:
    """Eine neue Datenquelle besitzt UUID und zeitzonenbewusste UTC-Zeitstempel."""
    datenquelle = Datenquelle.neu(
        projekt_id=uuid4(),
        bezeichnung="Export",
        quellsystemtyp=Quellsystemtyp.DATEI_EXPORT,
        quellenart=Quellenart.CSV,
    )
    assert datenquelle.datenquellen_id.version == 4
    assert datenquelle.erstellt_am.tzinfo is UTC
    assert datenquelle.geaendert_am.tzinfo is UTC
