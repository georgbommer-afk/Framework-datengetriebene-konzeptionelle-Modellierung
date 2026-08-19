"""Portable ZIP-v1-Archive und ihre Sicherheitsgrenzen."""

import hashlib
import io
import json
import os
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from framework_mvp.application.autorisierung import AutorisierungsService, geheimnis_hash
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.projektarchiv_service import ArchivGrenzen, ProjektArchivService
from framework_mvp.domain.exceptions import ArchivKonflikt, ArchivUngueltig, ZugriffVerweigert
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
from framework_mvp.domain.models.zugriff import (
    Projektaktion,
    Projektzugehoerigkeit,
    Projektzugriffsart,
    Zugriffskontext,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema
from framework_mvp.infrastructure.persistence.sqlite_zugriffs_repository import (
    SQLiteZugriffsRepository,
)
from framework_mvp.workspace import WorkspaceKonfiguration


def _quelle(tmp_path: Path):
    db = tmp_path / "quelle.sqlite"
    workspace = WorkspaceKonfiguration(tmp_path / "quelle-workspace")
    projekt = ProjektService(SQLiteProjektRepository(db)).projekt_anlegen(
        bezeichnung="Übungsprojekt",
        untersuchungsauftrag=Untersuchungsauftrag(
            problemstellung="Problem",
            untersuchungszweck="Zweck",
            systemtyp=Systemtyp.PRODUKTION,
            systemgrenze="Grenze",
        ),
    )
    datei = workspace.fuer_projekt_anlegen(projekt.projekt_id).raw / "daten.csv"
    datei.write_text("a,b\n1,2\n", encoding="utf-8")
    repository = SQLiteZugriffsRepository(db)
    jetzt = datetime.now(UTC)
    geheimnis = "q" * 40
    repository.projektzugehoerigkeit_speichern(
        Projektzugehoerigkeit(
            projekt.projekt_id,
            Projektzugriffsart.GAST,
            None,
            geheimnis_hash(geheimnis),
            jetzt + timedelta(hours=1),
            jetzt,
            1,
            jetzt,
        )
    )
    service = ProjektArchivService(db, workspace, repository, AutorisierungsService(repository))
    return projekt, Zugriffskontext.gast(geheimnis), service


def test_export_ist_selbstvalidierend_und_enthaelt_keine_rechte(tmp_path: Path) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    archiv = service.exportieren(kontext, projekt.projekt_id)
    with zipfile.ZipFile(io.BytesIO(archiv)) as zip_archiv:
        namen = set(zip_archiv.namelist())
        manifest = json.loads(zip_archiv.read("manifest.json"))
    assert {"manifest.json", "project/project.json", "README.txt"} <= namen
    assert "artifacts/raw/daten.csv" in namen
    assert manifest["archive_version"] == 1
    assert manifest["original_project_id"] == str(projekt.projekt_id)
    assert manifest["project_name"] == "Übungsprojekt"
    assert not any(
        begriff in name
        for name in namen
        for begriff in ("benutzer", "rolle", "einladung", "session", "secret")
    )


def test_gast_importiert_in_eigenen_neuen_mandanten_und_kann_wiederoeffnen(
    tmp_path: Path,
) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    archiv = service.exportieren(kontext, projekt.projekt_id)
    ziel_db = tmp_path / "ziel.sqlite"
    ziel_workspace = WorkspaceKonfiguration(tmp_path / "ziel-workspace")
    ziel_repository = SQLiteZugriffsRepository(ziel_db)
    ziel = ProjektArchivService(
        ziel_db,
        ziel_workspace,
        ziel_repository,
        AutorisierungsService(ziel_repository),
    )
    erster_import = ziel.importieren(kontext, archiv)
    pruefung = ziel.import_pruefen(kontext, archiv)
    assert pruefung.bereits_vorhanden
    with pytest.raises(ArchivKonflikt, match="ausdrücklich"):
        ziel.importieren(kontext, archiv)
    zweiter_import = ziel.importieren(kontext, archiv, vorhandenes_projekt_ersetzen=True)
    assert erster_import.projekt_id == projekt.projekt_id
    assert not erster_import.bereits_vorhanden
    assert zweiter_import.bereits_vorhanden
    assert zweiter_import.ersetzt
    assert (
        ziel_workspace.basisverzeichnis / "projects" / str(projekt.projekt_id) / "raw" / "daten.csv"
    ).read_text() == "a,b\n1,2\n"


def test_exportiertes_gastprojekt_wird_nach_verlust_des_gastkontexts_wiederhergestellt(
    tmp_path: Path,
) -> None:
    projekt, gast_a, service_a = _quelle(tmp_path)
    archiv = service_a.exportieren(gast_a, projekt.projekt_id)
    db = tmp_path / "quelle.sqlite"
    workspace = WorkspaceKonfiguration(tmp_path / "quelle-workspace")
    raw = workspace.basisverzeichnis / "projects" / str(projekt.projekt_id) / "raw" / "daten.csv"
    raw.write_text("zwischenzeitlich verändert", encoding="utf-8")
    with sqlite3.connect(db) as verbindung:
        verbindung.execute(
            "UPDATE projekte SET bezeichnung='Zwischenstand' WHERE projekt_id=?",
            (str(projekt.projekt_id),),
        )
        verbindung.commit()

    repository = SQLiteZugriffsRepository(db)
    service_b = ProjektArchivService(db, workspace, repository, AutorisierungsService(repository))
    gast_b = Zugriffskontext.gast("n" * 40)
    pruefung = service_b.import_pruefen(gast_b, archiv)
    ergebnis = service_b.importieren(
        gast_b, archiv, vorhandenes_projekt_ersetzen=pruefung.bereits_vorhanden
    )

    assert ergebnis.projekt_id == projekt.projekt_id
    assert ergebnis.ersetzt
    assert raw.read_text(encoding="utf-8") == "a,b\n1,2\n"
    geladen = SQLiteProjektRepository(db).laden(projekt.projekt_id)
    assert geladen is not None
    assert geladen.bezeichnung == "Übungsprojekt"
    AutorisierungsService(repository).projekt_zugriff_pruefen(
        gast_b, projekt.projekt_id, Projektaktion.ANSEHEN
    )


def test_vorhandenes_projekt_wird_nach_rueckfrage_vollstaendig_ersetzt(
    tmp_path: Path,
) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    archiv = service.exportieren(kontext, projekt.projekt_id)
    db = tmp_path / "ziel-erfolg.sqlite"
    workspace = WorkspaceKonfiguration(tmp_path / "ziel-erfolg-workspace")
    repository = SQLiteZugriffsRepository(db)
    ziel = ProjektArchivService(db, workspace, repository, AutorisierungsService(repository))
    ziel.importieren(kontext, archiv)
    raw = workspace.basisverzeichnis / "projects" / str(projekt.projekt_id) / "raw" / "daten.csv"
    raw.write_text("veraendert", encoding="utf-8")
    with sqlite3.connect(db) as verbindung:
        verbindung.execute(
            "UPDATE projekte SET bezeichnung='Verändert' WHERE projekt_id=?",
            (str(projekt.projekt_id),),
        )

    ergebnis = ziel.importieren(kontext, archiv, vorhandenes_projekt_ersetzen=True)

    assert ergebnis.ersetzt
    assert raw.read_text(encoding="utf-8") == "a,b\n1,2\n"
    geladen = SQLiteProjektRepository(db).laden(projekt.projekt_id)
    assert geladen is not None
    assert geladen.bezeichnung == "Übungsprojekt"


def test_fehler_beim_dateitausch_rollt_ersetzen_vollstaendig_zurueck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    archiv = service.exportieren(kontext, projekt.projekt_id)
    db = tmp_path / "ziel-rollback.sqlite"
    workspace = WorkspaceKonfiguration(tmp_path / "ziel-rollback-workspace")
    repository = SQLiteZugriffsRepository(db)
    ziel = ProjektArchivService(db, workspace, repository, AutorisierungsService(repository))
    ziel.importieren(kontext, archiv)
    raw = workspace.basisverzeichnis / "projects" / str(projekt.projekt_id) / "raw" / "daten.csv"
    raw.write_text("bisheriger Stand", encoding="utf-8")
    original_replace = os.replace
    aufrufe = 0

    def zweiter_tausch_schlaegt_fehl(quelle, senke):  # type: ignore[no-untyped-def]
        nonlocal aufrufe
        aufrufe += 1
        if aufrufe == 2:
            raise OSError("simulierter Dateitauschfehler")
        return original_replace(quelle, senke)

    monkeypatch.setattr(
        "framework_mvp.application.projektarchiv_service.os.replace",
        zweiter_tausch_schlaegt_fehl,
    )

    with pytest.raises(OSError, match="simulierter Dateitauschfehler"):
        ziel.importieren(kontext, archiv, vorhandenes_projekt_ersetzen=True)

    assert raw.read_text(encoding="utf-8") == "bisheriger Stand"
    assert SQLiteProjektRepository(db).laden(projekt.projekt_id) is not None


def test_import_verweigert_zip_slip_vor_jedem_schreibzugriff(tmp_path: Path) -> None:
    db = tmp_path / "ziel.sqlite"
    workspace = WorkspaceKonfiguration(tmp_path / "ziel-workspace")
    repository = SQLiteZugriffsRepository(db)
    service = ProjektArchivService(db, workspace, repository, AutorisierungsService(repository))
    boese = io.BytesIO()
    with zipfile.ZipFile(boese, "w") as archiv:
        archiv.writestr("../ausbruch.txt", b"nicht schreiben")
        archiv.writestr("manifest.json", b"{}")
    with pytest.raises(ArchivUngueltig, match="verlässt"):
        service.importieren(Zugriffskontext.gast("x" * 40), boese.getvalue())
    assert not (tmp_path / "ausbruch.txt").exists()


def test_import_verweigert_nicht_gelistete_und_manipulierte_datei(tmp_path: Path) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    original = service.exportieren(kontext, projekt.projekt_id)
    mit_manipulation = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(original)) as quelle,
        zipfile.ZipFile(mit_manipulation, "w", zipfile.ZIP_DEFLATED) as ziel,
    ):
        for info in quelle.infolist():
            daten = quelle.read(info.filename)
            if info.filename == "project/project.json":
                daten += b" "
            ziel.writestr(info.filename, daten)
    with pytest.raises(ArchivUngueltig, match="Dateigröße|SHA-256"):
        service.importieren(kontext, mit_manipulation.getvalue())


def test_import_verweigert_im_archiv_fehlende_manifestdatei(tmp_path: Path) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    original = service.exportieren(kontext, projekt.projekt_id)
    unvollstaendig = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(original)) as quelle,
        zipfile.ZipFile(unvollstaendig, "w", zipfile.ZIP_DEFLATED) as ziel,
    ):
        for info in quelle.infolist():
            if info.filename != "README.txt":
                ziel.writestr(info.filename, quelle.read(info.filename))

    with pytest.raises(ArchivUngueltig, match="unterschiedliche Dateien"):
        service.importieren(kontext, unvollstaendig.getvalue())


def test_bekannte_uuid_allein_erlaubt_keinen_identischen_import(tmp_path: Path) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    archiv = service.exportieren(kontext, projekt.projekt_id)
    with sqlite3.connect(tmp_path / "quelle.sqlite") as verbindung:
        verbindung.execute(
            "DELETE FROM archivmetadaten WHERE projekt_id=? AND archivtyp='projekt_export'",
            (str(projekt.projekt_id),),
        )
        verbindung.commit()
    fremder_kontext = Zugriffskontext.gast("fremd" * 10)
    with pytest.raises(ZugriffVerweigert):
        service.import_pruefen(fremder_kontext, archiv)
    with pytest.raises(ZugriffVerweigert):
        service.importieren(fremder_kontext, archiv, vorhandenes_projekt_ersetzen=True)


def test_manifest_hashes_stimmen_mit_payload_ueberein(tmp_path: Path) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    archiv = service.exportieren(kontext, projekt.projekt_id)
    with zipfile.ZipFile(io.BytesIO(archiv)) as zip_archiv:
        manifest = json.loads(zip_archiv.read("manifest.json"))
        for eintrag in manifest["files"]:
            assert hashlib.sha256(zip_archiv.read(eintrag["path"])).hexdigest() == eintrag["sha256"]


@pytest.mark.parametrize("pfad", ["/absolut.txt", "C:/absolut.txt", "artifacts/../../x.txt"])
def test_unsichere_absolute_und_traversierende_pfade_werden_abgelehnt(
    tmp_path: Path, pfad: str
) -> None:
    _, kontext, service = _quelle(tmp_path)
    boese = io.BytesIO()
    with zipfile.ZipFile(boese, "w") as archiv:
        archiv.writestr(pfad, b"x")
        archiv.writestr("manifest.json", b"{}")
    with pytest.raises(ArchivUngueltig):
        service.importieren(kontext, boese.getvalue())


def test_symbolischer_link_und_doppelter_name_werden_abgelehnt(tmp_path: Path) -> None:
    _, kontext, service = _quelle(tmp_path)
    link_archiv = io.BytesIO()
    with zipfile.ZipFile(link_archiv, "w") as archiv:
        link = zipfile.ZipInfo("artifacts/link.txt")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        archiv.writestr(link, b"ziel")
        archiv.writestr("manifest.json", b"{}")
    with pytest.raises(ArchivUngueltig, match="Symbolische Links"):
        service.importieren(kontext, link_archiv.getvalue())

    doppelt = io.BytesIO()
    with pytest.warns(UserWarning), zipfile.ZipFile(doppelt, "w") as archiv:
        archiv.writestr("README.txt", b"eins")
        archiv.writestr("README.txt", b"zwei")
        archiv.writestr("manifest.json", b"{}")
    with pytest.raises(ArchivUngueltig, match="doppelte"):
        service.importieren(kontext, doppelt.getvalue())


def test_dateianzahl_einzelgroesse_gesamtgroesse_und_ratio_sind_begrenzt(
    tmp_path: Path,
) -> None:
    db = tmp_path / "limits.sqlite"
    workspace = WorkspaceKonfiguration(tmp_path / "limits-workspace")
    repository = SQLiteZugriffsRepository(db)
    kontext = Zugriffskontext.gast("l" * 40)

    def service(grenzen: ArchivGrenzen) -> ProjektArchivService:
        return ProjektArchivService(
            db, workspace, repository, AutorisierungsService(repository), grenzen=grenzen
        )

    zwei_dateien = io.BytesIO()
    with zipfile.ZipFile(zwei_dateien, "w") as archiv:
        archiv.writestr("manifest.json", b"{}")
        archiv.writestr("README.txt", b"x")
    with pytest.raises(ArchivUngueltig, match="zu viele"):
        service(ArchivGrenzen(maximale_dateien=1)).importieren(kontext, zwei_dateien.getvalue())

    grosse_datei = io.BytesIO()
    with zipfile.ZipFile(grosse_datei, "w") as archiv:
        archiv.writestr("README.txt", b"12345")
        archiv.writestr("manifest.json", b"{}")
    with pytest.raises(ArchivUngueltig, match="Einzelgrenze"):
        service(ArchivGrenzen(maximale_einzeldatei_bytes=4)).importieren(
            kontext, grosse_datei.getvalue()
        )
    with pytest.raises(ArchivUngueltig, match="Gesamtgrenze"):
        service(ArchivGrenzen(maximale_entpackte_groesse_bytes=6)).importieren(
            kontext, grosse_datei.getvalue()
        )

    zip_bombe = io.BytesIO()
    with zipfile.ZipFile(zip_bombe, "w", zipfile.ZIP_DEFLATED) as archiv:
        archiv.writestr("artifacts/nullen.txt", b"0" * 20_000)
        archiv.writestr("manifest.json", b"{}")
    with pytest.raises(ArchivUngueltig, match="Kompressionsverhältnis"):
        service(ArchivGrenzen(maximales_kompressionsverhaeltnis=2)).importieren(
            kontext, zip_bombe.getvalue()
        )


def test_unerlaubter_dateityp_und_neuere_archivversion_werden_abgelehnt(
    tmp_path: Path,
) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    original = service.exportieren(kontext, projekt.projekt_id)
    unerlaubt = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as quelle, zipfile.ZipFile(unerlaubt, "w") as ziel:
        for info in quelle.infolist():
            ziel.writestr(info.filename, quelle.read(info.filename))
        ziel.writestr("artifacts/programm.exe", b"MZ")
    with pytest.raises(ArchivUngueltig, match="Artefakttyp"):
        service.importieren(kontext, unerlaubt.getvalue())

    neuer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as quelle, zipfile.ZipFile(neuer, "w") as ziel:
        for info in quelle.infolist():
            daten = quelle.read(info.filename)
            if info.filename == "manifest.json":
                manifest = json.loads(daten)
                manifest["archive_version"] = 999
                daten = json.dumps(manifest).encode()
            ziel.writestr(info.filename, daten)
    with pytest.raises(ArchivUngueltig, match="Archivversion"):
        service.importieren(kontext, neuer.getvalue())


def _upload_staging_pfad(workspace: WorkspaceKonfiguration, staging_id) -> Path:  # type: ignore[no-untyped-def]
    return workspace.basisverzeichnis / ".import-staging" / f"upload-{staging_id}"


def test_upload_staging_ueberlebt_service_rerun_und_wird_beim_abbruch_entfernt(
    tmp_path: Path,
) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    archiv = service.exportieren(kontext, projekt.projekt_id)
    staging = service.archiv_stagen(kontext, archiv)
    workspace = WorkspaceKonfiguration(tmp_path / "quelle-workspace")
    staging_pfad = _upload_staging_pfad(workspace, staging.staging_id)
    assert staging_pfad.is_dir()

    neuer_service = ProjektArchivService(
        tmp_path / "quelle.sqlite",
        workspace,
        (repository := SQLiteZugriffsRepository(tmp_path / "quelle.sqlite")),
        AutorisierungsService(repository),
    )
    pruefung = neuer_service.gestagten_import_pruefen(
        kontext, staging.staging_id, staging.archiv_sha256
    )

    assert pruefung.projekt_id == projekt.projekt_id
    assert pruefung.bereits_vorhanden
    assert staging_pfad.is_dir()
    neuer_service.archiv_staging_verwerfen(kontext, staging.staging_id, staging.archiv_sha256)
    assert not staging_pfad.exists()


def test_staging_wird_nach_erfolg_und_validierungsfehler_entfernt(tmp_path: Path) -> None:
    projekt, quellkontext, quelle = _quelle(tmp_path)
    archiv = quelle.exportieren(quellkontext, projekt.projekt_id)
    ziel_db = tmp_path / "staging-ziel.sqlite"
    ziel_workspace = WorkspaceKonfiguration(tmp_path / "staging-ziel-workspace")
    ziel_repository = SQLiteZugriffsRepository(ziel_db)
    ziel = ProjektArchivService(
        ziel_db,
        ziel_workspace,
        ziel_repository,
        AutorisierungsService(ziel_repository),
    )
    neuer_gast = Zugriffskontext.gast("n" * 40)
    staging = ziel.archiv_stagen(neuer_gast, archiv)
    staging_pfad = _upload_staging_pfad(ziel_workspace, staging.staging_id)
    pruefung = ziel.gestagten_import_pruefen(neuer_gast, staging.staging_id, staging.archiv_sha256)

    ergebnis = ziel.gestagten_importieren(
        neuer_gast,
        staging.staging_id,
        staging.archiv_sha256,
        erwartete_projekt_id=pruefung.projekt_id,
    )

    assert ergebnis.projekt_id == projekt.projekt_id
    assert not staging_pfad.exists()
    zuordnung = ziel_repository.projektzugehoerigkeit_laden(projekt.projekt_id)
    assert zuordnung is not None
    assert zuordnung.gast_geheimnis_sha256 == geheimnis_hash("n" * 40)

    ungueltig = ziel.archiv_stagen(neuer_gast, b"kein ZIP")
    ungueltig_pfad = _upload_staging_pfad(ziel_workspace, ungueltig.staging_id)
    with pytest.raises(ArchivUngueltig, match="ZIP"):
        ziel.gestagten_import_pruefen(
            neuer_gast,
            ungueltig.staging_id,
            ungueltig.archiv_sha256,
        )
    assert not ungueltig_pfad.exists()


def test_staging_ist_an_kontext_gebunden_und_fehler_entfernt_es_sicher(
    tmp_path: Path,
) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    archiv = service.exportieren(kontext, projekt.projekt_id)
    staging = service.archiv_stagen(kontext, archiv)
    workspace = WorkspaceKonfiguration(tmp_path / "quelle-workspace")
    staging_pfad = _upload_staging_pfad(workspace, staging.staging_id)

    with pytest.raises(ZugriffVerweigert):
        service.gestagten_import_pruefen(
            Zugriffskontext.gast("f" * 40),
            staging.staging_id,
            staging.archiv_sha256,
        )
    assert staging_pfad.is_dir()

    pruefung = service.gestagten_import_pruefen(kontext, staging.staging_id, staging.archiv_sha256)
    (staging_pfad / "projektarchiv.zip").write_bytes(b"manipuliert")
    with pytest.raises(ArchivUngueltig, match="verändert"):
        service.gestagten_importieren(
            kontext,
            staging.staging_id,
            staging.archiv_sha256,
            erwartete_projekt_id=pruefung.projekt_id,
            vorhandenes_projekt_ersetzen=True,
        )
    assert not staging_pfad.exists()
    assert SQLiteProjektRepository(tmp_path / "quelle.sqlite").laden(projekt.projekt_id) is not None


_FACHLICHE_TABELLEN = (
    "projekte",
    "datenquellen",
    "importvorgaenge",
    "transformationsplaene",
    "zwischendatensaetze",
    "semantische_mappings",
    "mappingtabellen",
    "event_logs",
    "qualitaetspruefungen",
    "qualitaetsregeln",
    "qualitaetsmassnahmen",
    "process_mining_analysen",
    "ergebnisaggregationen",
    "modellableitungen",
    "modellvalidierungen",
    "projektfortschritt",
)


def _vollstaendigen_fachstand_anlegen(
    db: Path, workspace: WorkspaceKonfiguration, projekt_id
) -> dict[str, str]:  # type: ignore[no-untyped-def]
    ids = {
        "datenquellen_id": str(uuid4()),
        "import_id": str(uuid4()),
        "transformationsplan_id": str(uuid4()),
        "zwischendatensatz_id": str(uuid4()),
        "semantische_mapping_id": str(uuid4()),
        "mappingtabelle_id": str(uuid4()),
        "event_log_id": str(uuid4()),
        "quality_run_id": str(uuid4()),
        "regel_id": str(uuid4()),
        "massnahme_id": str(uuid4()),
        "analyse_id": str(uuid4()),
        "aggregations_id": str(uuid4()),
        "modellableitungs_id": str(uuid4()),
        "k_id": str(uuid4()),
        "o_id": str(uuid4()),
        "validierungslauf_id": str(uuid4()),
        "k_stern_id": str(uuid4()),
        "spezifikations_id": str(uuid4()),
    }
    status = {
        "importvorgaenge": "bestaetigt",
        "semantische_mappings": "validiert",
        "mappingtabellen": "bestaetigt",
        "event_logs": "erzeugt",
        "process_mining_analysen": "ausgefuehrt",
        "ergebnisaggregationen": "gespeichert",
        "modellableitungen": "gespeichert",
        "modellvalidierungen": "fachlich_validiert",
        "projektfortschritt": "in_bearbeitung",
    }
    projektwurzel = workspace.fuer_projekt_anlegen(projekt_id).projekt
    zeitpunkt = "2026-08-19T10:00:00+00:00"

    def wert_fuer(tabelle: str, spalte: str, typ: str):  # type: ignore[no-untyped-def]
        if spalte == "projekt_id":
            return str(projekt_id)
        if spalte == "mapping_id":
            return (
                ids["mappingtabelle_id"]
                if tabelle == "mappingtabellen"
                else ids["semantische_mapping_id"]
            )
        if spalte in ids:
            return ids[spalte]
        if spalte in {"freigabe_id", "qualitaetspruefung_id"}:
            return ids["quality_run_id"]
        if spalte.startswith("relativer_") and spalte.endswith("_pfad"):
            endung = next(
                (
                    suffix
                    for kennung, suffix in (
                        ("csv", ".csv"),
                        ("xes", ".xes"),
                        ("visualisierung", ".svg"),
                        ("modell", ".pnml"),
                        ("daten", ".parquet"),
                    )
                    if kennung in spalte
                ),
                ".json",
            )
            relativ = f"roundtrip/{tabelle}-{spalte}{endung}"
            datei = projektwurzel / relativ
            datei.parent.mkdir(parents=True, exist_ok=True)
            datei.write_bytes(f"{tabelle}:{spalte}".encode())
            return f"projects/{projekt_id}/{relativ}"
        if spalte == "dateityp":
            return "CSV"
        if spalte == "quellenart":
            return "csv"
        if spalte == "discovery_verfahren":
            return "inductive_miner"
        if spalte == "phase":
            return 3
        if spalte == "framework_schritt":
            return 9
        if spalte == "fachlicher_unterschritt":
            return "Modell ergänzen und validieren"
        if spalte == "status":
            return status[tabelle]
        if spalte.endswith("_json"):
            return "{}"
        if "sha256" in spalte or "fingerabdruck" in spalte:
            return hashlib.sha256(f"{tabelle}:{spalte}".encode()).hexdigest()
        if spalte.endswith("_am_utc") or spalte in {"zeitraum_von", "zeitraum_bis"}:
            return zeitpunkt
        if typ.upper() == "INTEGER":
            return 1
        return f"{tabelle}-{spalte}"

    with sqlite3.connect(db) as verbindung:
        initialisiere_schema(verbindung)
        verbindung.execute("PRAGMA foreign_keys = ON")
        for tabelle in _FACHLICHE_TABELLEN[1:]:
            spalteninformationen = verbindung.execute(f"PRAGMA table_info({tabelle})").fetchall()
            spalten = [zeile[1] for zeile in spalteninformationen]
            werte = [wert_fuer(tabelle, zeile[1], zeile[2]) for zeile in spalteninformationen]
            verbindung.execute(
                f"INSERT INTO {tabelle} ({','.join(spalten)}) "  # noqa: S608
                f"VALUES ({','.join('?' for _ in spalten)})",
                werte,
            )
        verbindung.commit()
    for name, daten in {
        "berichte/abschlussbericht.pdf": b"%PDF-1.7 roundtrip",
        "berichte/dashboard.html": b"<html>Roundtrip</html>",
        "modelle/sollmodell.bpmn": b"<definitions />",
        "modelle/sollmodell.ptml": b"<ptml />",
        "modelle/sollmodell.pnml": b"<pnml />",
        "modelle/sollmodell.svg": b"<svg />",
    }.items():
        datei = projektwurzel / name
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_bytes(daten)
    return ids


def _zip_dateien(archiv: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(archiv)) as zip_archiv:
        return {name: zip_archiv.read(name) for name in zip_archiv.namelist()}


def test_vollstaendiger_roundtrip_erhaelt_alle_fachdaten_ids_dateien_und_manifest(
    tmp_path: Path,
) -> None:
    projekt, quellkontext, quelle = _quelle(tmp_path)
    quelle_workspace = WorkspaceKonfiguration(tmp_path / "quelle-workspace")
    ids = _vollstaendigen_fachstand_anlegen(
        tmp_path / "quelle.sqlite", quelle_workspace, projekt.projekt_id
    )
    quellarchiv = quelle.exportieren(quellkontext, projekt.projekt_id)
    quelldateien = _zip_dateien(quellarchiv)
    quellmanifest = json.loads(quelldateien["manifest.json"])
    exportierte_tabellen = {
        Path(name).stem for name in quelldateien if name.startswith("database/")
    }

    with sqlite3.connect(tmp_path / "quelle.sqlite") as verbindung:
        tabellen_mit_projektbezug = {
            name
            for (name,) in verbindung.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            if "projekt_id"
            in {zeile[1] for zeile in verbindung.execute(f"PRAGMA table_info({name})")}
        }
    bewusst_global = {
        "projektzugehoerigkeiten",
        "projektmitglieder",
        "archivmetadaten",
        "bereinigungsprotokoll",
    }
    erwartet = (tabellen_mit_projektbezug - bewusst_global) | {
        "qualitaetsregeln",
        "qualitaetsmassnahmen",
    }
    assert exportierte_tabellen == erwartet == set(_FACHLICHE_TABELLEN)

    ziel_db = tmp_path / "vollstaendig-ziel.sqlite"
    ziel_workspace = WorkspaceKonfiguration(tmp_path / "vollstaendig-ziel-workspace")
    ziel_repository = SQLiteZugriffsRepository(ziel_db)
    ziel = ProjektArchivService(
        ziel_db,
        ziel_workspace,
        ziel_repository,
        AutorisierungsService(ziel_repository),
    )
    zielkontext = Zugriffskontext.gast("r" * 40)
    ergebnis = ziel.importieren(zielkontext, quellarchiv)
    zielarchiv = ziel.exportieren(zielkontext, ergebnis.projekt_id)
    zieldateien = _zip_dateien(zielarchiv)
    zielmanifest = json.loads(zieldateien["manifest.json"])

    assert ergebnis.projekt_id == projekt.projekt_id
    for tabelle in _FACHLICHE_TABELLEN:
        assert zieldateien[f"database/{tabelle}.json"] == quelldateien[f"database/{tabelle}.json"]
    for identitaet in ids.values():
        assert any(
            identitaet in zieldateien[f"database/{tabelle}.json"].decode()
            for tabelle in _FACHLICHE_TABELLEN
        )
    quell_payload = {
        name: daten
        for name, daten in quelldateien.items()
        if name.startswith(("artifacts/", "reports/"))
    }
    ziel_payload = {
        name: daten
        for name, daten in zieldateien.items()
        if name.startswith(("artifacts/", "reports/"))
    }
    assert ziel_payload == quell_payload
    assert zielmanifest["original_project_id"] == quellmanifest["original_project_id"]
    assert zielmanifest["project_name"] == quellmanifest["project_name"]
    assert zielmanifest["last_framework_step"] == quellmanifest["last_framework_step"] == 9
    assert zielmanifest["project_fingerprint"] == quellmanifest["project_fingerprint"]
    assert zielmanifest["artifact_types"] == quellmanifest["artifact_types"]
