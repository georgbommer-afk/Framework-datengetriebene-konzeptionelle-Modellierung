"""Unit-Tests des unveränderlichen Importvorgangs."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    CsvImportparameter,
    Dateityp,
    Importstatus,
    Importvorgang,
    Profilzusammenfassung,
    Trennzeichenwahl,
)


def _importvorgang() -> Importvorgang:
    zeitpunkt = datetime.now(UTC)
    return Importvorgang(
        uuid4(),
        uuid4(),
        uuid4(),
        "daten.csv",
        "daten.csv",
        Dateityp.CSV,
        10,
        "a" * 64,
        CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.KOMMA),
        "daten",
        2,
        3,
        1,
        "projects/projekt/raw/hash/daten.csv",
        "projects/projekt/profiles/import.json",
        Profilzusammenfassung(1, 2, 0, 0),
        (" Warnung ",),
        Importstatus.BESTAETIGT,
        zeitpunkt,
        zeitpunkt,
    )


def test_gueltiger_bestaetigter_importvorgang() -> None:
    """Ein bestätigter Import normalisiert Texte und UTC-Zeitstempel."""
    importvorgang = _importvorgang()
    assert importvorgang.status is Importstatus.BESTAETIGT
    assert importvorgang.warnungen == ("Warnung",)
    assert importvorgang.bestaetigt_am is not None
    assert importvorgang.bestaetigt_am.utcoffset() == UTC.utcoffset(None)


def test_ungueltige_pruefsumme() -> None:
    """Nur eine hexadezimale SHA-256-Prüfsumme mit 64 Zeichen ist zulässig."""
    with pytest.raises(Domaenenfehler, match="Prüfsumme"):
        replace(_importvorgang(), sha256="nicht-gueltig")


def test_negative_dateigroesse() -> None:
    """Negative Dateigrößen werden abgelehnt."""
    with pytest.raises(Domaenenfehler, match="nicht negativ"):
        replace(_importvorgang(), dateigroesse_bytes=-1)


def test_ungueltiger_statuswert() -> None:
    """Das Domänenmodell akzeptiert keinen untypisierten unbekannten Status."""
    with pytest.raises(Domaenenfehler, match="Importstatus"):
        replace(_importvorgang(), status="unbekannt")  # type: ignore[arg-type]


def test_fehlende_bestaetigungsdaten() -> None:
    """Bestätigte Importe benötigen Zeitpunkt und beide Artefaktpfade."""
    with pytest.raises(Domaenenfehler, match="Bestätigungszeitpunkt"):
        replace(_importvorgang(), bestaetigt_am=None)


@pytest.mark.parametrize(
    ("feld", "pfad"),
    [
        ("relativer_raw_pfad", "../ausbruch.csv"),
        ("relativer_profil_pfad", "/tmp/profil.json"),
        ("relativer_raw_pfad", r"projects\..\ausbruch.csv"),
    ],
)
def test_artefaktpfade_bleiben_relativ(feld: str, pfad: str) -> None:
    """Absolute Pfade und Traversalsegmente verlassen das Domänenmodell nicht."""
    with pytest.raises(Domaenenfehler, match="relativ"):
        replace(_importvorgang(), **{feld: pfad})
