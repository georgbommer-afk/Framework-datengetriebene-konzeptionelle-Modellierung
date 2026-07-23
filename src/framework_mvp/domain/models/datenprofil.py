"""Unveränderliche Modelle der technischen Datenprofilierung."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Profiltyp(StrEnum):
    """Technisch erkannter Profiltyp einer Spalte."""

    NUMERISCH = "numerisch"
    KATEGORIAL = "kategorial"
    ZEITBEZOGEN = "zeitbezogen"
    SONSTIG = "sonstig"


class Zeitgranularitaet(StrEnum):
    """Deterministische Granularität einer zeitlichen Aggregation."""

    STUNDE = "Stunde"
    TAG = "Tag"
    WOCHE = "Woche"
    MONAT = "Monat"


@dataclass(frozen=True, slots=True)
class PlatzhalterAnzahl:
    """Anzahl einer normalisierten textuellen Platzhalterklasse."""

    bezeichnung: str
    anzahl: int


@dataclass(frozen=True, slots=True)
class Fehlwertprofil:
    """Getrennte Kennzahlen echter Fehlwerte und textueller Platzhalter."""

    echte_fehlwerte: int
    anteil_echter_fehlwerte: float
    platzhalter: int
    anteil_platzhalter: float
    platzhalterklassen: tuple[PlatzhalterAnzahl, ...]
    gueltige_regulaere_werte: int


@dataclass(frozen=True, slots=True)
class NumerischesSpaltenprofil:
    """Statistische Kennzahlen der endlichen Werte einer numerischen Spalte."""

    gueltige_werte: int
    unendliche_werte: int
    minimum: float | None
    maximum: float | None
    mittelwert: float | None
    median: float | None
    standardabweichung: float | None
    q1: float | None
    q3: float | None
    interquartilsabstand: float | None
    untere_ausreissergrenze: float | None
    obere_ausreissergrenze: float | None
    potenzielle_ausreisser: int


@dataclass(frozen=True, slots=True)
class KategorieHaeufigkeit:
    """Absolute und relative Häufigkeit einer regulären Ausprägung."""

    bezeichnung: str
    anzahl: int
    anteil: float


@dataclass(frozen=True, slots=True)
class KategorialesSpaltenprofil:
    """Kennzahlen und sortierte Häufigkeiten einer kategorialen Spalte."""

    gueltige_werte: int
    eindeutige_auspraegungen: int
    haeufigste_werte: tuple[KategorieHaeufigkeit, ...]
    seltene_werte: int


@dataclass(frozen=True, slots=True)
class ZeitintervallAggregation:
    """Anzahl interpretierbarer Zeitwerte in einem Intervall."""

    intervallbeginn: datetime
    anzahl: int


@dataclass(frozen=True, slots=True)
class ZeitbezogenesSpaltenprofil:
    """Kennzahlen einer bestehenden oder erkannten Zeitspalte."""

    fruehester_zeitpunkt: datetime | None
    spaetester_zeitpunkt: datetime | None
    interpretierbare_werte: int
    nicht_interpretierbare_werte: int
    erfolgsquote: float
    granularitaet: Zeitgranularitaet | None
    aggregation: tuple[ZeitintervallAggregation, ...]


@dataclass(frozen=True, slots=True)
class Spaltenprofil:
    """Vollständiges technisches Profil genau einer Originalspalte."""

    spaltenname: str
    originaldatentyp: str
    profiltyp: Profiltyp
    fehlwerte: Fehlwertprofil
    eindeutige_werte: int
    numerisch: NumerischesSpaltenprofil | None = None
    kategorial: KategorialesSpaltenprofil | None = None
    zeitbezogen: ZeitbezogenesSpaltenprofil | None = None


@dataclass(frozen=True, slots=True)
class Datenprofil:
    """Gesamtprofil einer vollständig eingelesenen Tabelle."""

    zeilen: int
    spalten: int
    speicherbedarf_bytes: int
    exakte_duplikate: int
    vollstaendig_leere_spalten: int
    numerische_spalten: int
    kategoriale_spalten: int
    zeitbezogene_spalten: int
    sonstige_spalten: int
    echte_fehlwerte: int
    textuelle_platzhalter: int
    spaltenprofile: tuple[Spaltenprofil, ...]


@dataclass(frozen=True, slots=True)
class HistogrammKlasse:
    """Aggregierte Klasse eines Histogramms."""

    untergrenze: float
    obergrenze: float
    anzahl: int


@dataclass(frozen=True, slots=True)
class HistogrammDaten:
    """Histogrammklassen und separat darzustellender Median."""

    klassen: tuple[HistogrammKlasse, ...]
    median: float | None
    verwendete_endliche_werte: int


@dataclass(frozen=True, slots=True)
class BoxplotDaten:
    """Aggregierte Boxplot-Kennzahlen ohne einzelne Ausreißerpunkte."""

    unterer_whisker: float | None
    q1: float | None
    median: float | None
    q3: float | None
    oberer_whisker: float | None
    ausreisser: int


@dataclass(frozen=True, slots=True)
class FehlwertDiagrammEintrag:
    """Getrennte Fehlwertanteile einer Spalte für Diagramme."""

    spaltenname: str
    art: str
    anzahl: int
    anteil: float


@dataclass(frozen=True, slots=True)
class NumerischeDiagrammdaten:
    """Vollständig aggregierte Diagrammdaten einer numerischen Spalte."""

    histogramm: HistogrammDaten
    boxplot: BoxplotDaten


@dataclass(frozen=True, slots=True)
class SpaltenDiagrammdaten:
    """Diagrammdaten für genau eine Detailspalte."""

    spaltenname: str
    numerisch: NumerischeDiagrammdaten | None = None
    kategorien: tuple[KategorieHaeufigkeit, ...] = ()
    zeitintervalle: tuple[ZeitintervallAggregation, ...] = ()


@dataclass(frozen=True, slots=True)
class DatenprofilDiagramme:
    """Von Profilkennzahlen getrennte Diagrammdaten des Gesamtprofils."""

    fehlwerte: tuple[FehlwertDiagrammEintrag, ...]
    spalten: tuple[SpaltenDiagrammdaten, ...]
