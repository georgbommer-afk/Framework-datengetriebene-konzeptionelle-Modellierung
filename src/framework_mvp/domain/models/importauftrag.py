"""Unveränderliche Modelle für den temporären tabellarischen Datenimport."""

from dataclasses import dataclass
from enum import StrEnum

from framework_mvp.domain.exceptions import Domaenenfehler


class Dateityp(StrEnum):
    """Unterstützte Typen hochgeladener Dateien."""

    CSV = "CSV"
    XLSX = "XLSX"


class Trennzeichenwahl(StrEnum):
    """Auswahlmöglichkeiten für CSV-Trennzeichen."""

    AUTOMATISCH = "automatisch"
    KOMMA = ","
    SEMIKOLON = ";"
    TABULATOR = "\t"
    BENUTZERDEFINIERT = "benutzerdefiniert"


class Zeichenkodierung(StrEnum):
    """Unterstützte Zeichenkodierungen für CSV-Dateien."""

    UTF_8 = "utf-8"
    UTF_8_BOM = "utf-8-sig"
    ISO_8859_1 = "iso-8859-1"
    WINDOWS_1252 = "cp1252"


class Dezimaltrennzeichen(StrEnum):
    """Unterstützte Dezimaltrennzeichen."""

    PUNKT = "."
    KOMMA = ","


class Tausendertrennzeichen(StrEnum):
    """Unterstützte Tausendertrennzeichen."""

    KEINES = ""
    PUNKT = "."
    KOMMA = ","
    LEERZEICHEN = " "


class Kopfzeilenmodus(StrEnum):
    """Art der Kopfzeile einer Tabelle."""

    ERSTE_ZEILE = "erste_zeile"
    BENUTZERDEFINIERT = "benutzerdefiniert"
    KEINE = "keine"


@dataclass(frozen=True, slots=True)
class Kopfzeileneinstellung:
    """Validierte Kopfzeilenauswahl mit einsbasierter Zeilennummer."""

    modus: Kopfzeilenmodus = Kopfzeilenmodus.ERSTE_ZEILE
    zeilennummer: int | None = None

    def __post_init__(self) -> None:
        """Prüft eine benutzerdefinierte Zeilennummer."""
        if self.modus is Kopfzeilenmodus.BENUTZERDEFINIERT and (
            self.zeilennummer is None or self.zeilennummer < 1
        ):
            raise Domaenenfehler("Die Kopfzeilennummer muss eine positive Ganzzahl sein.")

    @property
    def pandas_header(self) -> int | None:
        """Liefert die nullbasierte Kopfzeile für Pandas."""
        if self.modus is Kopfzeilenmodus.KEINE:
            return None
        if self.modus is Kopfzeilenmodus.ERSTE_ZEILE:
            return 0
        assert self.zeilennummer is not None
        return self.zeilennummer - 1


@dataclass(frozen=True, slots=True)
class CsvImportparameter:
    """Vollständige, unveränderliche Einstellungen für einen CSV-Import."""

    trennzeichenwahl: Trennzeichenwahl = Trennzeichenwahl.AUTOMATISCH
    benutzerdefiniertes_trennzeichen: str = ""
    erkanntes_trennzeichen: str = ""
    zeichenkodierung: Zeichenkodierung = Zeichenkodierung.UTF_8
    dezimaltrennzeichen: Dezimaltrennzeichen = Dezimaltrennzeichen.PUNKT
    tausendertrennzeichen: Tausendertrennzeichen = Tausendertrennzeichen.KEINES
    kopfzeile: Kopfzeileneinstellung = Kopfzeileneinstellung()

    def __post_init__(self) -> None:
        """Prüft das manuelle oder automatisch erkannte Trennzeichen."""
        if self.trennzeichenwahl is Trennzeichenwahl.BENUTZERDEFINIERT:
            trennzeichen = self.benutzerdefiniertes_trennzeichen
        elif self.trennzeichenwahl is Trennzeichenwahl.AUTOMATISCH:
            trennzeichen = self.erkanntes_trennzeichen
        else:
            trennzeichen = self.trennzeichenwahl.value
        if len(trennzeichen) != 1 or trennzeichen in {"\r", "\n"}:
            raise Domaenenfehler("Das CSV-Trennzeichen muss genau ein gültiges Zeichen sein.")

    @property
    def trennzeichen(self) -> str:
        """Liefert das wirksame CSV-Trennzeichen."""
        if self.trennzeichenwahl is Trennzeichenwahl.BENUTZERDEFINIERT:
            return self.benutzerdefiniertes_trennzeichen
        if self.trennzeichenwahl is Trennzeichenwahl.AUTOMATISCH:
            return self.erkanntes_trennzeichen
        return self.trennzeichenwahl.value


@dataclass(frozen=True, slots=True)
class ExcelImportparameter:
    """Unveränderliche Einstellungen für einen Excel-Import."""

    tabellenblatt: str
    kopfzeile: Kopfzeileneinstellung = Kopfzeileneinstellung()

    def __post_init__(self) -> None:
        """Bereinigt und prüft den Namen des Tabellenblatts."""
        object.__setattr__(self, "tabellenblatt", self.tabellenblatt.strip())
        if not self.tabellenblatt:
            raise Domaenenfehler("Es muss genau ein Tabellenblatt ausgewählt werden.")


@dataclass(frozen=True, slots=True)
class DateiMetadaten:
    """Metadaten einer unverändert im Arbeitsspeicher gehaltenen Datei."""

    urspruenglicher_dateiname: str
    sicherer_dateiname: str
    dateigroesse_bytes: int
    dateityp: Dateityp
    sha256: str


@dataclass(frozen=True, slots=True)
class TabellenblattInfo:
    """Leichtgewichtig ermittelte Metadaten eines Excel-Tabellenblatts."""

    name: str
    ungefaehre_zeilenanzahl: int
    ungefaehre_spaltenanzahl: int
