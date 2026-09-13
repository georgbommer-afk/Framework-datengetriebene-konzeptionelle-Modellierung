"""Tests der gemeinsamen fachlichen Anzeigeformatierung."""

from datetime import UTC, datetime

import pytest

from framework_mvp.formatierung import (
    formatiere_fachwert,
    formatiere_messwert,
    formatiere_zahl,
    formatiere_zeitstempel,
)


@pytest.mark.parametrize(
    ("rohwert", "erwartet"),
    (
        (1850.1799999999998, "1850,18"),
        (38319.292499999996, "38319,29"),
        (360.0, "360"),
        (0.0, "0"),
        (-0.0, "0"),
        (3.333, "3,33"),
    ),
)
def test_zahlenformatierung_entfernt_floatartefakte(rohwert: float, erwartet: str) -> None:
    assert formatiere_zahl(rohwert) == erwartet


def test_messwertformatierung_verbindet_wert_und_einheit() -> None:
    assert formatiere_messwert(360.0, "s") == "360 s"
    assert formatiere_messwert(0.0333 * 100, "%") == "3,33 %"


def test_zeitstempel_werden_lesbar_und_mit_offset_formatiert() -> None:
    zeitpunkt = datetime(2026, 9, 13, 14, 5, 6, tzinfo=UTC)
    assert formatiere_zeitstempel(zeitpunkt) == "13.09.2026 14:05:06 +00:00"
    assert formatiere_zeitstempel("2026-09-13T14:05:06+02:00") == ("13.09.2026 14:05:06 +02:00")


def test_fachwert_laesst_boolesche_und_textwerte_unveraendert() -> None:
    assert formatiere_fachwert(True) is True
    assert formatiere_fachwert("1.234") == "1.234"
