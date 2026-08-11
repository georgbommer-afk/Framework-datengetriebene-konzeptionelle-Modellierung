"""Fachliche Unit-Tests der optionalen Mappingtabelle M aus Schritt 3."""

from uuid import uuid4

import pytest

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Mappingeintrag,
    Mappingeintragsart,
    Mappingtabelle,
    Mappingtabellenstatus,
)


def _mapping() -> Mappingtabelle:
    return Mappingtabelle.neu(uuid4(), uuid4())


def test_spalten_und_wertbezeichnungen_werden_als_kern_von_m_abgebildet() -> None:
    """M bildet sowohl Spaltennamen als auch enthaltene Werte von b_tech auf b_fach ab."""
    mapping = _mapping()
    mapping = mapping.eintrag_hinzufuegen(
        Mappingeintrag.fuer_spalte("t_pdno", "Produktionsauftrag")
    )
    mapping = mapping.eintrag_hinzufuegen(
        Mappingeintrag.fuer_wert("transaction", "ticst0201m000", "Produktionsauftrag abschließen")
    )
    assert [wert.art for wert in mapping.eintraege] == [
        Mappingeintragsart.SPALTENBEZEICHNUNG,
        Mappingeintragsart.TECHNISCHER_WERT,
    ]
    assert mapping.fachliche_spaltenbezeichnung("t_pdno") == "Produktionsauftrag"
    assert (
        mapping.fachliche_wertbezeichnung("transaction", "ticst0201m000")
        == "Produktionsauftrag abschließen"
    )
    assert mapping.fachliche_spaltenbezeichnung("unbekannt") == "unbekannt"


def test_wertmapping_bleibt_an_quellspalte_und_technischen_typ_gebunden() -> None:
    """Gleich angezeigte Werte verschiedener Spalten oder Typen bleiben unterscheidbar."""
    mapping = _mapping()
    mapping = mapping.eintrag_hinzufuegen(Mappingeintrag.fuer_wert("status", "1", "Freigegeben"))
    mapping = mapping.eintrag_hinzufuegen(Mappingeintrag.fuer_wert("prioritaet", "1", "Hoch"))
    mapping = mapping.eintrag_hinzufuegen(
        Mappingeintrag.fuer_wert("status", 1, "Technischer Status 1")
    )
    assert mapping.fachliche_wertbezeichnung("status", "1") == "Freigegeben"
    assert mapping.fachliche_wertbezeichnung("prioritaet", "1") == "Hoch"
    assert mapping.fachliche_wertbezeichnung("status", 1) == "Technischer Status 1"


def test_mehrere_technische_bezeichnungen_duerfen_dasselbe_b_fach_besitzen() -> None:
    """Die in Abschnitt 3.6.7 erlaubte n:1-Zuordnung wird nicht künstlich eingeschränkt."""
    mapping = _mapping()
    mapping = mapping.eintrag_hinzufuegen(
        Mappingeintrag.fuer_spalte("t_pdno", "Produktionsauftrag")
    )
    mapping = mapping.eintrag_hinzufuegen(
        Mappingeintrag.fuer_spalte("order_no", "Produktionsauftrag")
    )
    assert len(mapping.eintraege) == 2


def test_identische_zuordnung_ist_idempotent_aber_widerspruch_wird_abgelehnt() -> None:
    """Eine technische Referenz besitzt höchstens eine fachliche Bedeutung."""
    mapping = _mapping()
    mapping = mapping.eintrag_hinzufuegen(
        Mappingeintrag.fuer_spalte("t_pdno", "Produktionsauftrag")
    )
    unveraendert = mapping.eintrag_hinzufuegen(
        Mappingeintrag.fuer_spalte("t_pdno", "Produktionsauftrag")
    )
    assert unveraendert == mapping
    with pytest.raises(Domaenenfehler, match="andere fachliche Bezeichnung"):
        mapping.eintrag_hinzufuegen(Mappingeintrag.fuer_spalte("t_pdno", "Kundenauftrag"))


def test_eintraege_koennen_bearbeitet_und_entfernt_werden() -> None:
    eintrag = Mappingeintrag.fuer_spalte("t_pdno", "Auftrag")
    mapping = _mapping().eintrag_hinzufuegen(eintrag)
    mapping = mapping.eintrag_bearbeiten(eintrag.mappingeintrag_id, "Produktionsauftrag")
    assert mapping.eintraege[0].fachliche_bezeichnung == "Produktionsauftrag"
    assert mapping.eintraege[0].technische_bezeichnung == "t_pdno"
    assert mapping.eintrag_entfernen(eintrag.mappingeintrag_id).eintraege == ()


def test_leere_fachliche_bezeichnung_und_unbestimmtes_leeres_m_sind_ungueltig() -> None:
    mapping = _mapping()
    with pytest.raises(Domaenenfehler, match="darf nicht leer"):
        Mappingeintrag.fuer_spalte("t_pdno", "   ")
    with pytest.raises(Domaenenfehler, match="ausdrücklich"):
        mapping.bestaetigen()


def test_leeres_m_kann_ausdruecklich_bestaetigt_und_weitergegeben_werden() -> None:
    mapping = _mapping().bestaetigen(kein_mapping_erforderlich=True)
    assert mapping.status is Mappingtabellenstatus.BESTAETIGT
    assert mapping.kein_mapping_erforderlich
    assert mapping.eintraege == ()
    assert mapping.fachliche_spaltenbezeichnung("t_pdno") == "t_pdno"
