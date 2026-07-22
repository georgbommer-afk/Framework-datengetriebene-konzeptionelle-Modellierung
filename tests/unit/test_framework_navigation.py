"""Tests der programmatischen Framework-Navigation."""

import pytest

from framework_mvp.ui.components.framework_navigation import SCHRITTNAMEN, erstelle_framework_svg


def test_aktueller_und_abgeschlossener_schritt_sind_markiert() -> None:
    """Das SVG kennzeichnet Schritt 2 aktuell und Schritt 1 abgeschlossen."""
    svg = erstelle_framework_svg(2, {1})
    assert 'data-step="2" data-status="aktuell"' in svg
    assert 'data-step="1" data-status="abgeschlossen"' in svg
    assert svg.count('data-status="zukünftig"') == 8
    assert svg.count("<line ") == 9
    assert 'viewBox="0 0 880 320"' in svg
    assert all(f"<title>{name}</title>" in svg for name in SCHRITTNAMEN)


def test_ungueltiger_aktueller_schritt_wird_abgelehnt() -> None:
    """Nur die zehn definierten Framework-Schritte sind zulässig."""
    with pytest.raises(ValueError):
        erstelle_framework_svg(11)
