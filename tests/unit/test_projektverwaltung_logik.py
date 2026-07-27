"""Unit-Tests der reduzierten Untersuchungszweck-Logik."""

import pytest

from framework_mvp.ui.pages import projektverwaltung


@pytest.mark.parametrize("eingabe", ["", "   "])
def test_leerer_individueller_untersuchungszweck_wird_abgelehnt(
    monkeypatch: pytest.MonkeyPatch, eingabe: str
) -> None:
    """Leere und ausschließlich aus Leerzeichen bestehende Zwecke sind ungültig."""
    fehler: list[str] = []
    monkeypatch.setattr(projektverwaltung.st, "error", fehler.append)
    daten = {"zwecke": [], "individuelle_zwecke": []}
    assert not projektverwaltung._zweck_hinzufuegen(daten, eingabe)
    assert fehler
    assert daten["zwecke"] == []


def test_mehrere_zwecke_und_casefold_duplikaterkennung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mehrere Zwecke sind möglich, ein Duplikat mit anderer Schreibung nicht."""
    fehler: list[str] = []
    monkeypatch.setattr(projektverwaltung.st, "error", fehler.append)
    daten = {"zwecke": [], "individuelle_zwecke": []}
    assert projektverwaltung._zweck_hinzufuegen(daten, "  Materialfluss erklären ")
    assert projektverwaltung._zweck_hinzufuegen(daten, "Bestände verstehen")
    assert not projektverwaltung._zweck_hinzufuegen(daten, "materialfluss ERKLÄREN")
    assert daten["zwecke"] == ["Materialfluss erklären", "Bestände verstehen"]
    assert "bereits vorhanden" in fehler[-1]
