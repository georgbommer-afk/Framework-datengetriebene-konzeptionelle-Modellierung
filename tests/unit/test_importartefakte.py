"""Tests der sicheren und atomaren Ablage von Importartefakten."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from framework_mvp.application.profiling import erstelle_datenprofil
from framework_mvp.domain.models import CsvImportparameter, Trennzeichenwahl
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte.artefakt_speicher import ImportartefaktSpeicher
from framework_mvp.infrastructure.importartefakte.profil_json import (
    PROFIL_VERSION,
    erstelle_profil_json,
    lade_profil_json,
)
from framework_mvp.workspace import WorkspaceKonfiguration


def test_raw_bytes_pruefsumme_und_wiederverwendung(tmp_path: Path) -> None:
    """Identische Uploadbytes werden unverändert gespeichert und anschließend wiederverwendet."""
    speicher = ImportartefaktSpeicher(WorkspaceKonfiguration.ermitteln(tmp_path))
    inhalt = b"a,b\n1,2\n"
    pruefsumme = hashlib.sha256(inhalt).hexdigest()
    projekt_id = uuid4()
    erster = speicher.raw_speichern(projekt_id, pruefsumme, "daten.csv", inhalt)
    zweiter = speicher.raw_speichern(projekt_id, pruefsumme, "daten.csv", inhalt)
    assert speicher.lesen(erster.relativer_pfad) == inhalt
    assert hashlib.sha256(speicher.lesen(erster.relativer_pfad)).hexdigest() == pruefsumme
    assert erster.neu_erstellt
    assert not zweiter.neu_erstellt
    assert not list(tmp_path.rglob(".import-*"))


def test_namensgleiche_unterschiedliche_dateien_ueberschreiben_sich_nicht(tmp_path: Path) -> None:
    """Der Prüfsummenordner trennt unterschiedliche Inhalte mit gleichem Namen."""
    speicher = ImportartefaktSpeicher(WorkspaceKonfiguration.ermitteln(tmp_path))
    projekt_id = uuid4()
    erste_bytes = b"eins"
    zweite_bytes = b"zwei"
    erster = speicher.raw_speichern(
        projekt_id, hashlib.sha256(erste_bytes).hexdigest(), "daten.csv", erste_bytes
    )
    zweiter = speicher.raw_speichern(
        projekt_id, hashlib.sha256(zweite_bytes).hexdigest(), "daten.csv", zweite_bytes
    )
    assert erster.relativer_pfad != zweiter.relativer_pfad
    assert speicher.lesen(erster.relativer_pfad) == erste_bytes


@pytest.mark.parametrize("pfad", ["../datei", "/tmp/datei", r"projects\..\datei"])
def test_pfad_traversal_wird_verhindert(tmp_path: Path, pfad: str) -> None:
    """Auch beim Lesen können relative Pfade den Workspace nicht verlassen."""
    speicher = ImportartefaktSpeicher(WorkspaceKonfiguration.ermitteln(tmp_path))
    with pytest.raises(Importintegritaetsfehler, match="Workspace"):
        speicher.lesen(pfad)


def _profil_json() -> tuple[bytes, object, str]:
    import_id = uuid4()
    checksum = "a" * 64
    profil = erstelle_datenprofil(pd.DataFrame({"Wert": [1.0, np.inf, np.nan]}))
    inhalt = erstelle_profil_json(
        import_id=import_id,
        datei_pruefsumme=checksum,
        importparameter=CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.KOMMA),
        tabellenbezeichnung="daten",
        erstellt_am=datetime.now(UTC),
        profil=profil,
        warnungen=("Prüfung nötig",),
    )
    return inhalt, import_id, checksum


def test_profil_json_utf8_iso_version_und_endliche_jsonwerte(tmp_path: Path) -> None:
    """Das JSON ist UTF-8, versioniert, ISO-datiert und enthält weder NaN noch Infinity."""
    inhalt, import_id, checksum = _profil_json()
    struktur = json.loads(inhalt.decode("utf-8"))
    assert struktur["profil_version"] == PROFIL_VERSION
    assert struktur["import_id"] == str(import_id)
    assert struktur["datei_pruefsumme"] == checksum
    datetime.fromisoformat(struktur["erstellt_am"])
    assert "Infinity" not in inhalt.decode("utf-8")
    assert "NaN" not in inhalt.decode("utf-8")
    pfad = tmp_path / "profil.json"
    pfad.write_bytes(inhalt)
    assert lade_profil_json(pfad).import_id == import_id


def test_ungueltiges_profil_json_wird_abgelehnt(tmp_path: Path) -> None:
    """Beschädigtes oder unvollständiges Profil-JSON gilt als Integritätsfehler."""
    pfad = tmp_path / "profil.json"
    pfad.write_text('{"profil_version": 1}', encoding="utf-8")
    with pytest.raises(Importintegritaetsfehler, match="ungültig"):
        lade_profil_json(pfad)


def test_unterstuetzte_profilversion_wird_geprueft(tmp_path: Path) -> None:
    """Eine neuere Profilversion wird nicht irrtümlich als gültig geladen."""
    inhalt, _, _ = _profil_json()
    struktur = json.loads(inhalt)
    struktur["profil_version"] = PROFIL_VERSION + 1
    pfad = tmp_path / "profil.json"
    pfad.write_text(json.dumps(struktur), encoding="utf-8")
    with pytest.raises(Importintegritaetsfehler, match="nicht unterstützt"):
        lade_profil_json(pfad)
