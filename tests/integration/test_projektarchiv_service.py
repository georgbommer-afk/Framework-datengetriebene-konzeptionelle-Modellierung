"""Portable ZIP-v1-Archive und ihre Sicherheitsgrenzen."""

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from framework_mvp.application.autorisierung import AutorisierungsService, geheimnis_hash
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.projektarchiv_service import ArchivGrenzen, ProjektArchivService
from framework_mvp.domain.exceptions import ArchivUngueltig, ZugriffVerweigert
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
from framework_mvp.domain.models.zugriff import (
    Projektzugehoerigkeit,
    Projektzugriffsart,
    Zugriffskontext,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
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
    zweiter_import = ziel.importieren(kontext, archiv)
    assert erster_import.projekt_id == projekt.projekt_id
    assert not erster_import.bereits_vorhanden
    assert zweiter_import.bereits_vorhanden
    assert (
        ziel_workspace.basisverzeichnis / "projects" / str(projekt.projekt_id) / "raw" / "daten.csv"
    ).read_text() == "a,b\n1,2\n"


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


def test_bekannte_uuid_allein_erlaubt_keinen_identischen_import(tmp_path: Path) -> None:
    projekt, kontext, service = _quelle(tmp_path)
    archiv = service.exportieren(kontext, projekt.projekt_id)
    with pytest.raises(ZugriffVerweigert):
        service.importieren(Zugriffskontext.gast("fremd" * 10), archiv)


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
