"""Eigenständiges Domänenmodell der Mappingtabelle M aus Schritt 3."""

import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from enum import StrEnum
from math import isfinite
from typing import Any, Self
from uuid import UUID, uuid4

from framework_mvp.domain.exceptions import Domaenenfehler


class Mappingeintragsart(StrEnum):
    """Fachlich zulässige Arten technischer Bezeichnungen in M."""

    SPALTENBEZEICHNUNG = "Spaltenbezeichnung"
    TECHNISCHER_WERT = "Technischer Wert"


class Mappingtabellenstatus(StrEnum):
    """Lebenszyklus einer datensatzbezogenen Mappingtabelle."""

    ENTWURF = "entwurf"
    BESTAETIGT = "bestaetigt"


def _wert_payload(wert: object) -> object:
    """Erzeugt eine JSON-fähige, typstabile Darstellung üblicher Tabellenskalare."""
    if isinstance(wert, datetime | date | time):
        return {"isoformat": wert.isoformat()}
    if isinstance(wert, float) and not isfinite(wert):
        return {"nicht_endliche_zahl": repr(wert)}
    if isinstance(wert, str | int | float | bool) or wert is None:
        return wert
    item = getattr(wert, "item", None)
    if callable(item):
        skalar = item()
        if skalar is not wert:
            return _wert_payload(skalar)
    isoformat = getattr(wert, "isoformat", None)
    if callable(isoformat):
        return {"isoformat": str(isoformat())}
    return {"repr": repr(wert)}


@dataclass(frozen=True, slots=True)
class TechnischeWertreferenz:
    """Typisierte Referenz auf genau einen in einer T-Spalte enthaltenen Wert."""

    anzeigewert: str
    technischer_datentyp: str
    wert_json: str

    def __post_init__(self) -> None:
        """Prüft die kanonische JSON-Repräsentation der technischen Referenz."""
        object.__setattr__(self, "technischer_datentyp", self.technischer_datentyp.strip())
        if not self.technischer_datentyp:
            raise Domaenenfehler("Eine technische Wertreferenz benötigt ihren Datentyp.")
        try:
            json.loads(self.wert_json)
        except (json.JSONDecodeError, TypeError) as fehler:
            raise Domaenenfehler(
                "Die technische Wertreferenz ist nicht gültig serialisiert."
            ) from fehler

    @classmethod
    def aus_wert(cls, wert: object) -> Self:
        """Bewahrt Anzeige, Python-/Pandas-Typ und Wert kanonisch und reproduzierbar."""
        typ = type(wert)
        datentyp = f"{typ.__module__}.{typ.__qualname__}"
        wert_json = json.dumps(
            _wert_payload(wert),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return cls(str(wert), datentyp, wert_json)

    @property
    def schluessel(self) -> tuple[str, str]:
        """Unterscheidet gleich dargestellte Werte verschiedener technischer Typen."""
        return self.technischer_datentyp, self.wert_json


@dataclass(frozen=True, slots=True)
class Mappingeintrag:
    """Eine Zuordnung von b_tech zu b_fach mit eindeutiger technischer Referenz."""

    mappingeintrag_id: UUID
    art: Mappingeintragsart
    technische_bezeichnung: str
    fachliche_bezeichnung: str
    technische_quellspalte: str = ""
    wertreferenz: TechnischeWertreferenz | None = None

    def __post_init__(self) -> None:
        """Bereinigt Fachtext und erzwingt den zur Eintragsart passenden Kontext."""
        object.__setattr__(self, "technische_bezeichnung", self.technische_bezeichnung.strip())
        object.__setattr__(self, "fachliche_bezeichnung", self.fachliche_bezeichnung.strip())
        object.__setattr__(self, "technische_quellspalte", self.technische_quellspalte.strip())
        if not self.fachliche_bezeichnung:
            raise Domaenenfehler("Die fachliche Bezeichnung darf nicht leer sein.")
        if self.art is Mappingeintragsart.SPALTENBEZEICHNUNG:
            if not self.technische_bezeichnung:
                raise Domaenenfehler("Eine Spaltenzuordnung benötigt einen technischen Namen.")
            if self.technische_quellspalte or self.wertreferenz is not None:
                raise Domaenenfehler(
                    "Eine Spaltenzuordnung darf keinen technischen Wertkontext enthalten."
                )
        elif self.art is Mappingeintragsart.TECHNISCHER_WERT:
            if not self.technische_quellspalte or self.wertreferenz is None:
                raise Domaenenfehler(
                    "Eine Wertzuordnung benötigt Quellspalte, Wert und technischen Datentyp."
                )
            object.__setattr__(self, "technische_bezeichnung", self.wertreferenz.anzeigewert)
        else:
            raise Domaenenfehler("Die Art des Mappingeintrags ist ungültig.")

    @classmethod
    def fuer_spalte(cls, spaltenname: str, fachliche_bezeichnung: str) -> Self:
        """Erzeugt eine Zuordnung einer tatsächlich vorhandenen Spaltenbezeichnung."""
        return cls(
            uuid4(),
            Mappingeintragsart.SPALTENBEZEICHNUNG,
            spaltenname,
            fachliche_bezeichnung,
        )

    @classmethod
    def fuer_wert(
        cls, quellspalte: str, technischer_wert: object, fachliche_bezeichnung: str
    ) -> Self:
        """Erzeugt eine spalten- und datentypgebundene technische Wertzuordnung."""
        referenz = TechnischeWertreferenz.aus_wert(technischer_wert)
        return cls(
            uuid4(),
            Mappingeintragsart.TECHNISCHER_WERT,
            referenz.anzeigewert,
            fachliche_bezeichnung,
            quellspalte,
            referenz,
        )

    @property
    def technischer_referenzschluessel(self) -> tuple[str, ...]:
        """Identifiziert eine technische Spalte oder einen typisierten Wert widerspruchsfrei."""
        if self.art is Mappingeintragsart.SPALTENBEZEICHNUNG:
            return self.art.value, self.technische_bezeichnung
        assert self.wertreferenz is not None
        return (
            self.art.value,
            self.technische_quellspalte,
            *self.wertreferenz.schluessel,
        )


@dataclass(frozen=True, slots=True)
class Mappingtabelle:
    """Versionierbare zentrale Ausgabe M für genau einen Zwischendatensatz T."""

    mapping_id: UUID
    projekt_id: UUID
    zwischendatensatz_id: UUID
    eintraege: tuple[Mappingeintrag, ...]
    kein_mapping_erforderlich: bool
    status: Mappingtabellenstatus
    erstellt_am: datetime
    geaendert_am: datetime

    def __post_init__(self) -> None:
        """Prüft Zeitstempel, leere Bestätigung und widerspruchsfreie Referenzen."""
        if self.erstellt_am.utcoffset() is None or self.geaendert_am.utcoffset() is None:
            raise Domaenenfehler("Zeitstempel einer Mappingtabelle müssen zeitzonenbewusst sein.")
        erstellt = self.erstellt_am.astimezone(UTC)
        geaendert = self.geaendert_am.astimezone(UTC)
        if geaendert < erstellt:
            raise Domaenenfehler(
                "Eine Mappingtabelle darf nicht vor ihrer Erstellung geändert sein."
            )
        object.__setattr__(self, "erstellt_am", erstellt)
        object.__setattr__(self, "geaendert_am", geaendert)
        if self.kein_mapping_erforderlich and self.eintraege:
            raise Domaenenfehler("Ein bestätigtes leeres Mapping darf keine Zuordnungen enthalten.")
        if (
            self.status is Mappingtabellenstatus.BESTAETIGT
            and not self.eintraege
            and not self.kein_mapping_erforderlich
        ):
            raise Domaenenfehler(
                "Eine leere Mappingtabelle muss ausdrücklich als nicht erforderlich bestätigt sein."
            )
        referenzen: dict[tuple[str, ...], Mappingeintrag] = {}
        for eintrag in self.eintraege:
            schluessel = eintrag.technischer_referenzschluessel
            vorhanden = referenzen.get(schluessel)
            if vorhanden is not None:
                art = (
                    "widersprüchlich"
                    if (vorhanden.fachliche_bezeichnung != eintrag.fachliche_bezeichnung)
                    else "doppelt"
                )
                raise Domaenenfehler(f"Dieselbe technische Referenz ist {art} mehrfach zugeordnet.")
            referenzen[schluessel] = eintrag

    @classmethod
    def neu(cls, projekt_id: UUID, zwischendatensatz_id: UUID) -> Self:
        """Erzeugt M entsprechend Pseudocode 3 zunächst als leere Menge."""
        jetzt = datetime.now(UTC)
        return cls(
            uuid4(),
            projekt_id,
            zwischendatensatz_id,
            (),
            False,
            Mappingtabellenstatus.ENTWURF,
            jetzt,
            jetzt,
        )

    def eintrag_hinzufuegen(self, eintrag: Mappingeintrag) -> Self:
        """Fügt idempotent hinzu und weist widersprüchliche Referenzen verständlich ab."""
        for vorhanden in self.eintraege:
            if vorhanden.technischer_referenzschluessel != (eintrag.technischer_referenzschluessel):
                continue
            if vorhanden.fachliche_bezeichnung == eintrag.fachliche_bezeichnung:
                return self
            raise Domaenenfehler(
                "Diese technische Referenz besitzt bereits eine andere fachliche Bezeichnung."
            )
        return replace(
            self,
            eintraege=(*self.eintraege, eintrag),
            kein_mapping_erforderlich=False,
            status=Mappingtabellenstatus.ENTWURF,
            geaendert_am=datetime.now(UTC),
        )

    def eintrag_bearbeiten(self, eintrag_id: UUID, fachliche_bezeichnung: str) -> Self:
        """Ändert ausschließlich b_fach und erhält die technische Referenz exakt."""
        if not fachliche_bezeichnung.strip():
            raise Domaenenfehler("Die fachliche Bezeichnung darf nicht leer sein.")
        gefunden = False
        eintraege = []
        for eintrag in self.eintraege:
            if eintrag.mappingeintrag_id == eintrag_id:
                eintraege.append(replace(eintrag, fachliche_bezeichnung=fachliche_bezeichnung))
                gefunden = True
            else:
                eintraege.append(eintrag)
        if not gefunden:
            raise Domaenenfehler("Der zu bearbeitende Mappingeintrag wurde nicht gefunden.")
        return replace(
            self,
            eintraege=tuple(eintraege),
            status=Mappingtabellenstatus.ENTWURF,
            geaendert_am=datetime.now(UTC),
        )

    def eintrag_entfernen(self, eintrag_id: UUID) -> Self:
        """Entfernt genau eine Zuordnung aus M."""
        eintraege = tuple(
            eintrag for eintrag in self.eintraege if eintrag.mappingeintrag_id != eintrag_id
        )
        if len(eintraege) == len(self.eintraege):
            raise Domaenenfehler("Der zu entfernende Mappingeintrag wurde nicht gefunden.")
        return replace(
            self,
            eintraege=eintraege,
            status=Mappingtabellenstatus.ENTWURF,
            geaendert_am=datetime.now(UTC),
        )

    def bestaetigen(self, *, kein_mapping_erforderlich: bool = False) -> Self:
        """Bestätigt ein befülltes M oder ausdrücklich die leere Menge."""
        if self.eintraege and kein_mapping_erforderlich:
            raise Domaenenfehler(
                "Eine Mappingtabelle mit Zuordnungen kann nicht als leer bestätigt werden."
            )
        if not self.eintraege and not kein_mapping_erforderlich:
            raise Domaenenfehler(
                "Bestätigen Sie ausdrücklich, dass kein semantisches Mapping erforderlich ist."
            )
        return replace(
            self,
            kein_mapping_erforderlich=kein_mapping_erforderlich,
            status=Mappingtabellenstatus.BESTAETIGT,
            geaendert_am=datetime.now(UTC),
        )

    def fachliche_spaltenbezeichnung(self, technischer_name: str) -> str:
        """Liefert b_fach oder bei leerem M unverändert b_tech für Schritt 4."""
        for eintrag in self.eintraege:
            if (
                eintrag.art is Mappingeintragsart.SPALTENBEZEICHNUNG
                and eintrag.technische_bezeichnung == technischer_name
            ):
                return eintrag.fachliche_bezeichnung
        return technischer_name

    def fachliche_wertbezeichnung(self, quellspalte: str, wert: object) -> str:
        """Liefert eine Wertinterpretation unter Erhalt von Spalte und technischem Typ."""
        referenz = TechnischeWertreferenz.aus_wert(wert)
        for eintrag in self.eintraege:
            if (
                eintrag.art is Mappingeintragsart.TECHNISCHER_WERT
                and eintrag.technische_quellspalte == quellspalte
                and eintrag.wertreferenz is not None
                and eintrag.wertreferenz.schluessel == referenz.schluessel
            ):
                return eintrag.fachliche_bezeichnung
        return str(wert)


def mappingtabelle_aus_dict(struktur: dict[str, Any]) -> Mappingtabelle:
    """Rekonstruiert M aus der versionierten JSON-/SQLite-Struktur."""
    eintraege = []
    for wert in struktur["eintraege"]:
        referenz_roh = wert.get("wertreferenz")
        referenz = TechnischeWertreferenz(**referenz_roh) if referenz_roh else None
        eintraege.append(
            Mappingeintrag(
                UUID(wert["mappingeintrag_id"]),
                Mappingeintragsart(wert["art"]),
                wert["technische_bezeichnung"],
                wert["fachliche_bezeichnung"],
                wert.get("technische_quellspalte", ""),
                referenz,
            )
        )
    return Mappingtabelle(
        UUID(struktur["mapping_id"]),
        UUID(struktur["projekt_id"]),
        UUID(struktur["zwischendatensatz_id"]),
        tuple(eintraege),
        bool(struktur["kein_mapping_erforderlich"]),
        Mappingtabellenstatus(struktur["status"]),
        datetime.fromisoformat(struktur["erstellt_am"]),
        datetime.fromisoformat(struktur["geaendert_am"]),
    )
