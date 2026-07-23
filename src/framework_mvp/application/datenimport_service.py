"""Anwendungslogik für temporären Dateiimport und unveränderte Vorschauen."""

from dataclasses import dataclass
from pathlib import PurePosixPath

import pandas as pd

from framework_mvp.application.profiling import erstelle_datenprofil, erstelle_diagrammdaten
from framework_mvp.domain.models import (
    CsvImportparameter,
    DateiMetadaten,
    Dateityp,
    Datenprofil,
    DatenprofilDiagramme,
    ExcelImportparameter,
    Quellenart,
    TabellenblattInfo,
    Zeichenkodierung,
)
from framework_mvp.infrastructure.dateiimport.csv_importer import (
    erkenne_trennzeichen,
    lese_csv,
)
from framework_mvp.infrastructure.dateiimport.datei_metadaten import ermittle_dateimetadaten
from framework_mvp.infrastructure.dateiimport.excel_importer import (
    ermittle_tabellenblaetter,
    lese_excel,
)

MAXIMALE_VORSCHAUZEILEN = 200
Importparameter = CsvImportparameter | ExcelImportparameter
VorschauCacheSchluessel = tuple[str, Importparameter]


@dataclass(frozen=True, slots=True)
class Spaltenuebersicht:
    """Kompakte, auf dem vollständigen DataFrame berechnete Spaltenstatistik."""

    spaltenname: object
    pandas_datentyp: str
    nicht_leere_werte: int
    leere_werte: int
    anteil_leerer_werte: float


@dataclass(frozen=True, slots=True)
class Datenvorschau:
    """Aufbereitete Vorschau samt Gesamtmaßen und Importparametern."""

    tabelle: pd.DataFrame
    gesamtzeilen: int
    gesamtspalten: int
    spaltennamen: tuple[object, ...]
    pandas_datentypen: tuple[str, ...]
    spaltenuebersicht: tuple[Spaltenuebersicht, ...]
    verwendete_parameter: Importparameter
    vollstaendige_tabelle: pd.DataFrame


@dataclass(frozen=True, slots=True)
class Profilierungsergebnis:
    """Temporäres Gesamtprofil mit davon getrennten Diagrammdaten."""

    profil: Datenprofil
    diagramme: DatenprofilDiagramme


def schlage_datenquellenbezeichnung_vor(dateiname: str, vorhandene_bezeichnung: str) -> str:
    """Leitet nur bei leerem Eingabefeld eine Bezeichnung ohne Dateiendung ab."""
    if vorhandene_bezeichnung.strip():
        return vorhandene_bezeichnung
    basisname = PurePosixPath(dateiname.replace("\\", "/")).name
    return PurePosixPath(basisname).stem.replace("_", " ").replace("-", " ").strip()


def schlage_quellenart_vor(dateityp: Dateityp) -> Quellenart:
    """Ordnet eine unterstützte Dateiendung der fachlichen Quellenart zu."""
    return Quellenart.CSV if dateityp is Dateityp.CSV else Quellenart.EXCEL


def bereite_vorschau_auf(daten: pd.DataFrame, parameter: Importparameter) -> Datenvorschau:
    """Erzeugt ohne Mutation der Quelldaten eine auf 200 Zeilen begrenzte Vorschau."""
    zeilenanzahl = len(daten)
    uebersichten: list[Spaltenuebersicht] = []
    for position, spaltenname in enumerate(daten.columns):
        spalte = daten.iloc[:, position]
        leer = int(spalte.isna().sum())
        uebersichten.append(
            Spaltenuebersicht(
                spaltenname=spaltenname,
                pandas_datentyp=str(spalte.dtype),
                nicht_leere_werte=zeilenanzahl - leer,
                leere_werte=leer,
                anteil_leerer_werte=leer / zeilenanzahl if zeilenanzahl else 0.0,
            )
        )
    return Datenvorschau(
        tabelle=daten.head(MAXIMALE_VORSCHAUZEILEN).copy(deep=True),
        gesamtzeilen=zeilenanzahl,
        gesamtspalten=len(daten.columns),
        spaltennamen=tuple(daten.columns),
        pandas_datentypen=tuple(str(typ) for typ in daten.dtypes),
        spaltenuebersicht=tuple(uebersichten),
        verwendete_parameter=parameter,
        vollstaendige_tabelle=daten.copy(deep=True),
    )


class DatenimportService:
    """Koordiniert Dateiüberprüfung, Erkennung, Import und Vorschau."""

    def datei_pruefen(self, dateiname: str, dateiinhalt: bytes) -> DateiMetadaten:
        """Prüft einen Upload und gibt seine Metadaten zurück."""
        return ermittle_dateimetadaten(dateiname, dateiinhalt)

    def csv_trennzeichen_erkennen(self, dateiinhalt: bytes, kodierung: Zeichenkodierung) -> str:
        """Erkennt ein CSV-Trennzeichen mit der gewählten Kodierung."""
        return erkenne_trennzeichen(dateiinhalt, kodierung)

    def excel_tabellenblaetter(self, dateiinhalt: bytes) -> tuple[TabellenblattInfo, ...]:
        """Ermittelt die verfügbaren Excel-Tabellenblätter."""
        return ermittle_tabellenblaetter(dateiinhalt)

    def vorschau_erstellen(self, dateiinhalt: bytes, parameter: Importparameter) -> Datenvorschau:
        """Liest eine Datei vollständig und erzeugt ihre begrenzte Vorschau."""
        if isinstance(parameter, CsvImportparameter):
            daten = lese_csv(dateiinhalt, parameter)
        else:
            daten = lese_excel(dateiinhalt, parameter)
        return bereite_vorschau_auf(daten, parameter)

    def cache_schluessel(
        self, datei_metadaten: DateiMetadaten, parameter: Importparameter
    ) -> VorschauCacheSchluessel:
        """Verknüpft Prüfsumme und unveränderliche Importparameter."""
        return (datei_metadaten.sha256, parameter)

    def profil_erstellen(self, daten: pd.DataFrame) -> Profilierungsergebnis:
        """Berechnet Profilkennzahlen und getrennte aggregierte Diagrammdaten."""
        profil = erstelle_datenprofil(daten)
        return Profilierungsergebnis(profil, erstelle_diagrammdaten(daten, profil))
