"""Sichere Ermittlung von Metadaten hochgeladener Dateien."""

import hashlib
import os
import re
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from framework_mvp.domain.exceptions import Datenimportfehler
from framework_mvp.domain.models import DateiMetadaten, Dateityp

MAX_UPLOAD_MB_STANDARD = 50
MAX_UPLOAD_MB_UMGEBUNGSVARIABLE = "FRAMEWORK_MVP_MAX_UPLOAD_MB"


def ermittle_max_upload_mb() -> int:
    """Liest und validiert die zentrale maximale Uploadgröße in Megabyte."""
    rohwert = os.getenv(MAX_UPLOAD_MB_UMGEBUNGSVARIABLE)
    if rohwert is None:
        return MAX_UPLOAD_MB_STANDARD
    try:
        wert = int(rohwert)
    except ValueError as fehler:
        raise Datenimportfehler(
            f"{MAX_UPLOAD_MB_UMGEBUNGSVARIABLE} muss eine positive Ganzzahl sein."
        ) from fehler
    if wert <= 0:
        raise Datenimportfehler(
            f"{MAX_UPLOAD_MB_UMGEBUNGSVARIABLE} muss eine positive Ganzzahl sein."
        )
    return wert


def bereinige_dateiname(dateiname: str) -> str:
    """Entfernt Pfadbestandteile und sicherheitskritische Zeichen aus einem Dateinamen."""
    basisname = PurePosixPath(dateiname.replace("\\", "/")).name.strip().lstrip(".")
    sicher = re.sub(r"[^\w. -]", "_", basisname, flags=re.UNICODE)
    sicher = re.sub(r"\s+", " ", sicher).strip()
    if not sicher:
        raise Datenimportfehler("Der Dateiname enthält keinen verwendbaren Namen.")
    return sicher


def ermittle_dateimetadaten(dateiname: str, dateiinhalt: bytes) -> DateiMetadaten:
    """Validiert einen Upload und ermittelt dessen unveränderliche Metadaten."""
    sicherer_name = bereinige_dateiname(dateiname)
    endung = PurePosixPath(sicherer_name).suffix.lower()
    typen = {".csv": Dateityp.CSV, ".xlsx": Dateityp.XLSX}
    if endung not in typen:
        raise Datenimportfehler("Es werden ausschließlich CSV- und XLSX-Dateien unterstützt.")
    if not dateiinhalt:
        raise Datenimportfehler("Die hochgeladene Datei ist leer.")
    maximum_mb = ermittle_max_upload_mb()
    if len(dateiinhalt) > maximum_mb * 1024 * 1024:
        raise Datenimportfehler(
            f"Die Datei überschreitet die maximal erlaubte Größe von {maximum_mb} MB."
        )
    dateityp = typen[endung]
    if dateityp is Dateityp.XLSX:
        try:
            with ZipFile(BytesIO(dateiinhalt)) as archiv:
                ist_arbeitsmappe = "xl/workbook.xml" in archiv.namelist()
        except BadZipFile:
            ist_arbeitsmappe = False
        if not ist_arbeitsmappe:
            raise Datenimportfehler(
                "Die Datei besitzt die Endung XLSX, enthält aber keine gültige Excel-Arbeitsmappe."
            )
    elif dateiinhalt.startswith(b"PK\x03\x04") or b"\x00" in dateiinhalt[:4096]:
        raise Datenimportfehler(
            "Die Datei besitzt die Endung CSV, ihr Inhalt ist jedoch keine Textdatei."
        )
    return DateiMetadaten(
        urspruenglicher_dateiname=dateiname,
        sicherer_dateiname=sicherer_name,
        dateigroesse_bytes=len(dateiinhalt),
        dateityp=dateityp,
        sha256=hashlib.sha256(dateiinhalt).hexdigest(),
    )
