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
from framework_mvp.domain.models import (
    CsvImportparameter,
    Indikatorbedingung,
    Indikatoroperator,
    Trennzeichenwahl,
)
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


def test_persistiertes_r_enthaelt_nur_fachliche_profilwerte_und_keine_zeitaggregation(
    tmp_path: Path,
) -> None:
    profil = erstelle_datenprofil(
        pd.DataFrame(
            {
                "kategorie": ["A", "A", "B"],
                "zahl": [1.0, 2.0, 100.0],
                "zeit": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            }
        )
    )
    inhalt = erstelle_profil_json(
        import_id=uuid4(),
        datei_pruefsumme="b" * 64,
        importparameter=CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.KOMMA),
        tabellenbezeichnung="daten",
        erstellt_am=datetime.now(UTC),
        profil=profil,
        warnungen=(),
    )
    struktur = json.loads(inhalt)["gesamtprofil"]
    assert set(struktur) == {
        "zeilen",
        "spalten",
        "exakte_duplikate",
        "vollstaendig_leere_spalten",
        "echte_fehlwerte",
        "textuelle_platzhalter",
        "spaltenprofile",
        "bestaetigte_zusaetzliche_platzhalter",
    }
    kategorie = next(
        wert for wert in struktur["spaltenprofile"] if wert["spaltenname"] == "kategorie"
    )
    assert kategorie["kategorial"] == {
        "eindeutige_auspraegungen": 2,
        "haeufigster_wert": "A",
    }
    zahl = next(wert for wert in struktur["spaltenprofile"] if wert["spaltenname"] == "zahl")
    assert "standardabweichung" not in zahl["numerisch"]
    assert "unendliche_werte" not in zahl["numerisch"]
    assert all("zeitbezogen" not in wert for wert in struktur["spaltenprofile"])


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


def test_indikatorauswertung_wird_in_r_persistiert_und_wiederhergestellt(
    tmp_path: Path,
) -> None:
    bedingung = Indikatorbedingung("Status", Indikatoroperator.GLEICH, "A")
    profil = erstelle_datenprofil(
        pd.DataFrame({"Status": ["A", "B", "A"]}),
        indikatorbedingungen=(bedingung,),
    )
    inhalt = erstelle_profil_json(
        import_id=uuid4(),
        datei_pruefsumme="c" * 64,
        importparameter=CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.KOMMA),
        tabellenbezeichnung="daten",
        erstellt_am=datetime.now(UTC),
        profil=profil,
        warnungen=(),
    )
    struktur = json.loads(inhalt)
    auswertung = struktur["gesamtprofil"]["spaltenprofile"][0]["indikatorauswertungen"][0]
    assert auswertung == {
        "absolute_haeufigkeit": 2,
        "auswertbare_beobachtungen": 3,
        "operator": "gleich",
        "spaltenname": "Status",
        "vergleichswert": "A",
    }
    pfad = tmp_path / "profil-mit-indikator.json"
    pfad.write_bytes(inhalt)
    assert lade_profil_json(pfad).indikatorbedingungen == (bedingung,)


def test_aelteres_profil_ohne_indikatorfeld_bleibt_ladbar(tmp_path: Path) -> None:
    inhalt, _, _ = _profil_json()
    struktur = json.loads(inhalt)
    struktur["profil_version"] = 2
    for spalte in struktur["gesamtprofil"]["spaltenprofile"]:
        spalte.pop("indikatorauswertungen", None)
    pfad = tmp_path / "profil-version-2.json"
    pfad.write_text(json.dumps(struktur), encoding="utf-8")
    geladen = lade_profil_json(pfad)
    assert geladen.profil_version == 2
    assert geladen.indikatorbedingungen == ()
    assert geladen.gesamtprofil["spaltenprofile"][0]["indikatorauswertungen"] == []
