"""Algorithmus 8: quellengebundene Ableitung und Persistenz von K und O."""

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, cast
from uuid import UUID

import pandas as pd

from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.ergebnisaggregation_service import ErgebnisaggregationService
from framework_mvp.application.modellableitung import (
    MAPPINGVERSION,
    MODELLBESTANDTEILE,
    leite_modellbestandteile_ab,
    wende_fachliche_entscheidungen_an,
)
from framework_mvp.application.ports.modellableitung_repository import (
    ModellableitungRepository,
)
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    AbgeleiteterModellbestandteil,
    Datenquelle,
    Eingangsartefakt,
    Ergebnisaggregation,
    FachlicheBestandteilentscheidung,
    Modellableitung,
    Modellableitungsstatus,
    OffenerEintrag,
    Projekt,
    Prozessnotation,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher

K_ARTEFAKTVERSION = 1
O_ARTEFAKTVERSION = 1
K_ARTEFAKTART = "vorlaeufiges_konzeptionelles_modell_k"
O_ARTEFAKTART = "offene_modellbestandteile_o"


def _normalisieren(wert: Any) -> Any:
    if isinstance(wert, bytes):
        return {"sha256": hashlib.sha256(wert).hexdigest(), "bytes": len(wert)}
    if isinstance(wert, (UUID, datetime, date, Enum)):
        return str(wert.value if isinstance(wert, Enum) else wert)
    if is_dataclass(wert):
        return _normalisieren(asdict(cast(Any, wert)))
    if isinstance(wert, dict):
        return {str(name): _normalisieren(inhalt) for name, inhalt in wert.items()}
    if isinstance(wert, (tuple, list, set, frozenset)):
        return [_normalisieren(inhalt) for inhalt in wert]
    return wert


def _json_bytes(wert: Any, *, eingerueckt: bool = True) -> bytes:
    return json.dumps(
        _normalisieren(wert),
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if eingerueckt else None,
        separators=None if eingerueckt else (",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(wert: Any) -> str:
    return hashlib.sha256(_json_bytes(wert, eingerueckt=False)).hexdigest()


def _u_snapshot(projekt: Projekt) -> dict[str, Any]:
    u = projekt.untersuchungsauftrag
    return {
        "projektbezeichnung": projekt.bezeichnung,
        "problemstellung": u.problemstellung,
        "untersuchungszweck": u.untersuchungszweck,
        "untersuchungszwecke": u.untersuchungszwecke,
        "individuelles_ziel": u.individuelles_ziel,
        "systemgrenze": u.systemgrenze,
        "logistische_zielgroessen": u.logistische_zielgroessen,
        "ausgewaehlte_kpi_ids": u.ausgewaehlte_kpi_ids,
        "detaillierungsgrad": u.detaillierungsgrad,
        "rahmenbedingungen": u.rahmenbedingungen,
        "betrachtungszeitraum": u.betrachtungszeitraum,
        "anmerkungen": u.anmerkungen,
    }


def _s_snapshot(projekt: Projekt) -> dict[str, Any]:
    u = projekt.untersuchungsauftrag
    return {"systemtyp": u.systemtyp, "systemklassifikation": u.systemklassifikation}


@dataclass(frozen=True, slots=True)
class Modellableitungsgrundlage:
    """Vollständig validierte und tief kopierte Eingangsartefakte von Algorithmus 8."""

    projekt: Projekt
    aggregation: Ergebnisaggregation
    datenquellen: tuple[Datenquelle, ...]
    profilreferenzen: tuple[dict[str, Any], ...]
    zwischendatensatz: Any
    zwischendaten: pd.DataFrame
    event_log: pd.DataFrame
    freigabe: Any
    analyse: Any
    discovery_ergebnisse: dict[str, Any]
    prozessmodell: bytes
    prozessnotation: Prozessnotation
    a_g: dict[str, Any]
    quellreferenzen: dict[Eingangsartefakt, dict[str, Any]]
    lineage: dict[str, Any]
    eingabefingerabdruck: str


@dataclass(frozen=True, slots=True)
class Modellableitungsvorschau:
    """Ungespeichertes, an Lineage und fachliche Einzelentscheidungen gebundenes K/O-Paar."""

    grundlage: Modellableitungsgrundlage
    modellableitungs_id: UUID
    k_id: UUID
    o_id: UUID
    vorgeschlagene_bestandteile: tuple[AbgeleiteterModellbestandteil, ...]
    systematische_offene_eintraege: tuple[OffenerEintrag, ...]
    entscheidungen: tuple[FachlicheBestandteilentscheidung, ...]
    bestandteile: tuple[AbgeleiteterModellbestandteil, ...]
    offene_eintraege: tuple[OffenerEintrag, ...]
    entscheidungsfingerabdruck: str
    k: dict[str, Any]
    o: dict[str, Any]
    k_bytes: bytes
    o_bytes: bytes
    k_sha256: str
    o_sha256: str


class ModellableitungService:
    """Ordnet ausschließlich die aktive, erneut validierte Artefaktkette K und O zu."""

    def __init__(
        self,
        repository: ModellableitungRepository,
        aggregationen: ErgebnisaggregationService,
        transformationen: TransformationsService,
        datenquellen: DatenquelleService,
        artefakte: ImportartefaktSpeicher,
    ) -> None:
        self._repository = repository
        self._aggregationen = aggregationen
        self._transformationen = transformationen
        self._datenquellen = datenquellen
        self._artefakte = artefakte

    def grundlage_laden(self, projekt_id: UUID, aggregations_id: UUID) -> Modellableitungsgrundlage:
        """Löst U,S,Q,R,T,E*,P,A_G ausschließlich über die aktive A_G-Lineage auf."""
        aggregation, a_g = self._aggregationen.laden(aggregations_id)
        if aggregation.projekt_id != projekt_id:
            raise Domaenenfehler("Das aktive A_G gehört nicht zum aktiven Projekt.")
        prozessmodell, uebergabe_a_g = self._aggregationen.uebergabe_schritt8(
            aggregations_id,
            projekt_id,
            aggregation.freigabe_id,
            aggregation.analyse_id,
        )
        if uebergabe_a_g != a_g:
            raise Importintegritaetsfehler(
                "Die erneut validierten A_G-Repräsentationen weichen ab."
            )
        basis = self._aggregationen.grundlage_laden(
            projekt_id, aggregation.freigabe_id, aggregation.analyse_id
        )
        if (
            str(basis.analyse.analyse_id) != str(a_g.get("process_mining_analyse_id"))
            or str(basis.freigabe.event_log_id) != str(a_g.get("event_log_id"))
            or basis.prozessmodell_sha256 != a_g.get("prozessmodell_p", {}).get("sha256")
            or hashlib.sha256(prozessmodell).hexdigest() != basis.prozessmodell_sha256
        ):
            raise Importintegritaetsfehler(
                "P, E*, Process-Mining-Analyse und A_G besitzen keine identische Lineage."
            )
        q_nach_id: dict[UUID, Datenquelle] = {}
        for import_id in basis.zwischendatensatz.import_ids:
            geladen = self._transformationen.import_laden(import_id)
            if geladen is None or geladen.importvorgang.projekt_id != projekt_id:
                raise Importintegritaetsfehler("Ein über T referenzierter Import fehlt.")
            quelle = self._datenquellen.datenquelle_laden(geladen.importvorgang.datenquellen_id)
            if quelle is None or quelle.projekt_id != projekt_id:
                raise Importintegritaetsfehler(
                    "Eine über die T-Lineage referenzierte Datenquelle aus Q fehlt."
                )
            q_nach_id[quelle.datenquellen_id] = quelle
        q = tuple(q_nach_id[wert] for wert in sorted(q_nach_id, key=str))
        u_sha = _sha(_u_snapshot(basis.projekt))
        s_sha = _sha(_s_snapshot(basis.projekt))
        q_sha = _sha(q)
        notation = Prozessnotation(str(a_g["prozessmodell_p"]["prozessnotation"]))
        referenzen: dict[Eingangsartefakt, dict[str, Any]] = {
            Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U: {
                "id": str(projekt_id),
                "sha256": u_sha,
            },
            Eingangsartefakt.SYSTEMPROFIL_S: {"id": str(projekt_id), "sha256": s_sha},
            Eingangsartefakt.DATENQUELLENKATALOG_Q: {
                "id": f"datenquellenkatalog:{projekt_id}",
                "sha256": q_sha,
                "datenquellen_ids": [str(wert.datenquellen_id) for wert in q],
            },
            Eingangsartefakt.DATENPROFIL_R: {
                "id": f"datenprofilverbund:{basis.zwischendatensatz.zwischendatensatz_id}",
                "sha256": basis.datenprofil_sha256,
                "import_ids": [str(wert) for wert in basis.zwischendatensatz.import_ids],
            },
            Eingangsartefakt.ZWISCHENDATENSATZ_T: {
                "id": str(basis.zwischendatensatz.zwischendatensatz_id),
                "sha256": basis.zwischendatensatz.sha256,
            },
            Eingangsartefakt.EVENT_LOG_E_STERN: {
                "id": str(basis.freigabe.event_log_id),
                "sha256": basis.freigabe.event_log_sha256,
                "freigabe_id": str(basis.freigabe.freigabe_id),
            },
            Eingangsartefakt.PROZESSMODELL_P: {
                "id": str(basis.analyse.analyse_id),
                "sha256": basis.prozessmodell_sha256,
                "relativer_pfad": basis.analyse.relativer_modell_pfad,
                "notation": notation.value,
            },
            Eingangsartefakt.AGGREGIERTE_ANALYSEERGEBNISSE_A_G: {
                "id": str(aggregation.aggregations_id),
                "sha256": aggregation.aggregations_sha256,
                "relativer_pfad": aggregation.relativer_aggregations_pfad,
                "artefaktversion": a_g["artefaktversion"],
            },
        }
        lineage = {
            "projekt_id": str(projekt_id),
            "spezifikations_id": str(a_g["spezifikations_id"]),
            "freigabe_id": str(aggregation.freigabe_id),
            "process_mining_analyse_id": str(aggregation.analyse_id),
            "aggregations_id": str(aggregation.aggregations_id),
            "artefakte": {
                quelle.value: _normalisieren(referenz) for quelle, referenz in referenzen.items()
            },
        }
        fingerabdruck = _sha({"lineage": lineage, "mappingversion": MAPPINGVERSION})
        return Modellableitungsgrundlage(
            copy.deepcopy(basis.projekt),
            aggregation,
            copy.deepcopy(q),
            copy.deepcopy(basis.profilreferenzen),
            copy.deepcopy(basis.zwischendatensatz),
            basis.zwischendaten.copy(deep=True),
            basis.event_log.copy(deep=True),
            copy.deepcopy(basis.freigabe),
            copy.deepcopy(basis.analyse),
            copy.deepcopy(basis.discovery_ergebnisse),
            bytes(prozessmodell),
            notation,
            copy.deepcopy(a_g),
            referenzen,
            lineage,
            fingerabdruck,
        )

    @staticmethod
    def entscheidungsfingerabdruck(
        entscheidungen: tuple[FachlicheBestandteilentscheidung, ...],
    ) -> str:
        """Bindet die Vorschau an Entscheidung, Begründung und Zeitpunkt je Bestandteil."""
        return _sha(
            sorted(
                (
                    wert.bestandteil_id.value,
                    wert.entscheidung.value,
                    wert.begruendung,
                    wert.entschieden_am,
                )
                for wert in entscheidungen
            )
        )

    def vorschau(
        self,
        *,
        projekt_id: UUID,
        aggregations_id: UUID,
        modellableitungs_id: UUID,
        k_id: UUID,
        o_id: UUID,
        entscheidungen: tuple[FachlicheBestandteilentscheidung, ...] = (),
    ) -> Modellableitungsvorschau:
        """Erzeugt Vorschläge und eine entscheidungsabhängige K/O-Vorschau ohne Ergänzungen."""
        basis = self.grundlage_laden(projekt_id, aggregations_id)
        t_vorher = basis.zwischendaten.copy(deep=True)
        e_vorher = basis.event_log.copy(deep=True)
        p_vorher = bytes(basis.prozessmodell)
        ag_vorher = copy.deepcopy(basis.a_g)
        vorgeschlagene_bestandteile, systematische_offene = leite_modellbestandteile_ab(basis)
        bestandteile, offene_eintraege = wende_fachliche_entscheidungen_an(
            vorgeschlagene_bestandteile,
            systematische_offene,
            entscheidungen,
        )
        entscheidungsfingerabdruck = self.entscheidungsfingerabdruck(entscheidungen)
        vollstaendig_geprueft = len(entscheidungen) == len(MODELLBESTANDTEILE)
        zeitpunkt = datetime.now(UTC)
        k: dict[str, Any] = {
            "artefaktart": K_ARTEFAKTART,
            "artefaktversion": K_ARTEFAKTVERSION,
            "mappingversion": MAPPINGVERSION,
            "k_id": str(k_id),
            "modellableitungs_id": str(modellableitungs_id),
            "projekt_id": str(projekt_id),
            "eingangslineage": basis.lineage,
            "modellbestandteile": bestandteile,
            "fachliche_entscheidungen": entscheidungen,
            "entscheidungsfingerabdruck": entscheidungsfingerabdruck,
            "menschlich_bestaetigt": vollstaendig_geprueft,
            "erstellt_am": zeitpunkt,
            "hinweis": (
                "Vorläufiges konzeptionelles Modell; fachliche Ergänzung und Validierung "
                "erfolgen ausschließlich in Schritt 9."
            ),
        }
        k["gesamtpruefsumme"] = _sha(k)
        k_bytes = _json_bytes(k)
        k_sha = hashlib.sha256(k_bytes).hexdigest()
        o: dict[str, Any] = {
            "artefaktart": O_ARTEFAKTART,
            "artefaktversion": O_ARTEFAKTVERSION,
            "o_id": str(o_id),
            "modellableitungs_id": str(modellableitungs_id),
            "projekt_id": str(projekt_id),
            "mappingversion": MAPPINGVERSION,
            "fachliche_entscheidungen": entscheidungen,
            "entscheidungsfingerabdruck": entscheidungsfingerabdruck,
            "menschlich_bestaetigt": vollstaendig_geprueft,
            "k_referenz": {
                "k_id": str(k_id),
                "gesamtpruefsumme": k["gesamtpruefsumme"],
                "datei_sha256": k_sha,
            },
            "offene_eintraege": offene_eintraege,
            "erstellt_am": zeitpunkt,
            "hinweis": (
                "Alle Einträge bleiben offen. Lösungen, Ergänzungen und Validierungsentscheidungen "
                "gehören ausschließlich zu Schritt 9."
            ),
        }
        o["gesamtpruefsumme"] = _sha(o)
        o_bytes = _json_bytes(o)
        o_sha = hashlib.sha256(o_bytes).hexdigest()
        pd.testing.assert_frame_equal(basis.zwischendaten, t_vorher, check_dtype=True)
        pd.testing.assert_frame_equal(basis.event_log, e_vorher, check_dtype=True)
        if basis.prozessmodell != p_vorher or basis.a_g != ag_vorher:
            raise Importintegritaetsfehler(
                "P oder A_G wurde während der Modellableitung verändert."
            )
        return Modellableitungsvorschau(
            basis,
            modellableitungs_id,
            k_id,
            o_id,
            vorgeschlagene_bestandteile,
            systematische_offene,
            entscheidungen,
            bestandteile,
            offene_eintraege,
            entscheidungsfingerabdruck,
            k,
            o,
            k_bytes,
            o_bytes,
            k_sha,
            o_sha,
        )

    def speichern(
        self,
        vorschau: Modellableitungsvorschau,
        *,
        menschlich_bestaetigt: bool | None = None,
    ) -> Modellableitung:
        """Persistiert K/O erst nach einer expliziten Entscheidung zu allen 16 Vorschlägen."""
        entschiedene_ids = {wert.bestandteil_id for wert in vorschau.entscheidungen}
        erwartete_ids = {wert.bestandteil_id for wert in MODELLBESTANDTEILE}
        if entschiedene_ids != erwartete_ids or len(vorschau.entscheidungen) != len(erwartete_ids):
            raise Domaenenfehler(
                "K und O dürfen erst gespeichert werden, nachdem alle 16 Modellbestandteile "
                "explizit fachlich geprüft wurden."
            )
        if menschlich_bestaetigt is False:
            raise Domaenenfehler("Die fachliche Prüfung wurde nicht bestätigt.")
        basis = self.grundlage_laden(
            vorschau.grundlage.projekt.projekt_id,
            vorschau.grundlage.aggregation.aggregations_id,
        )
        if basis.eingabefingerabdruck != vorschau.grundlage.eingabefingerabdruck:
            raise Domaenenfehler(
                "U, S, Q, R, T, E*, P oder A_G wurde seit der Vorschau verändert; "
                "eine Neuberechnung ist erforderlich."
            )
        if (
            self.entscheidungsfingerabdruck(vorschau.entscheidungen)
            != vorschau.entscheidungsfingerabdruck
        ):
            raise Domaenenfehler(
                "Die fachlichen Entscheidungen wurden verändert; eine neue Vorschau ist nötig."
            )
        if (
            vorschau.k.get("menschlich_bestaetigt") is not True
            or vorschau.o.get("menschlich_bestaetigt") is not True
        ):
            raise Domaenenfehler("Die K/O-Vorschau enthält keine vollständige fachliche Prüfung.")
        identisch = self._repository.finde_identisch(
            basis.projekt.projekt_id,
            basis.aggregation.aggregations_id,
            basis.eingabefingerabdruck,
            MAPPINGVERSION,
            vorschau.entscheidungsfingerabdruck,
        )
        if identisch is not None:
            return self.laden(identisch.modellableitungs_id)[0]
        vorhanden = self._repository.laden(vorschau.modellableitungs_id)
        if vorhanden is not None:
            raise Domaenenfehler("Die Modellableitungs-ID gehört bereits zu einem anderen Lauf.")
        basis_pfad = (
            PurePosixPath("projects")
            / str(basis.projekt.projekt_id)
            / "model_derivations"
            / str(vorschau.modellableitungs_id)
        )
        k_pfad = (basis_pfad / "preliminary-conceptual-model-k.json").as_posix()
        o_pfad = (basis_pfad / "open-components-o.json").as_posix()
        ableitung = Modellableitung(
            vorschau.modellableitungs_id,
            vorschau.k_id,
            vorschau.o_id,
            basis.projekt.projekt_id,
            basis.aggregation.aggregations_id,
            basis.analyse.analyse_id,
            basis.freigabe.event_log_id,
            basis.eingabefingerabdruck,
            MAPPINGVERSION,
            vorschau.entscheidungsfingerabdruck,
            k_pfad,
            vorschau.k_sha256,
            o_pfad,
            vorschau.o_sha256,
            Modellableitungsstatus.GESPEICHERT,
            datetime.now(UTC),
        )
        erzeugt = []
        try:
            erzeugt.append(self._artefakte.artefakt_speichern(k_pfad, vorschau.k_bytes))
            erzeugt.append(self._artefakte.artefakt_speichern(o_pfad, vorschau.o_bytes))
            self._repository.speichern(ableitung)
        except Exception:
            for artefakt in reversed(erzeugt):
                self._artefakte.neu_erstelltes_artefakt_entfernen(artefakt)
            raise
        return self.laden(ableitung.modellableitungs_id)[0]

    @staticmethod
    def _json_pruefen(inhalt: bytes, artefaktart: str, artefaktversion: int) -> dict[str, Any]:
        try:
            struktur = json.loads(inhalt)
            pruefsumme = struktur.pop("gesamtpruefsumme")
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as fehler:
            raise Importintegritaetsfehler("K oder O ist kein gültiges JSON-Artefakt.") from fehler
        if (
            struktur.get("artefaktart") != artefaktart
            or struktur.get("artefaktversion") != artefaktversion
            or _sha(struktur) != pruefsumme
        ):
            raise Importintegritaetsfehler(
                "Artefaktart, Version oder Gesamtprüfsumme von K beziehungsweise O ist ungültig."
            )
        struktur["gesamtpruefsumme"] = pruefsumme
        return struktur

    def laden(
        self, modellableitungs_id: UUID
    ) -> tuple[Modellableitung, dict[str, Any], dict[str, Any]]:
        """Lädt K und O erst nach erneuter Prüfung der vollständigen Eingangslineage."""
        ableitung = self._repository.laden(modellableitungs_id)
        if ableitung is None:
            raise Importintegritaetsfehler("Die Modellableitung wurde nicht gefunden.")
        k_bytes = self._artefakte.lesen(ableitung.relativer_k_pfad)
        o_bytes = self._artefakte.lesen(ableitung.relativer_o_pfad)
        if (
            hashlib.sha256(k_bytes).hexdigest() != ableitung.k_sha256
            or hashlib.sha256(o_bytes).hexdigest() != ableitung.o_sha256
        ):
            raise Importintegritaetsfehler("Die Dateiprüfsumme von K oder O ist ungültig.")
        k = self._json_pruefen(k_bytes, K_ARTEFAKTART, K_ARTEFAKTVERSION)
        o = self._json_pruefen(o_bytes, O_ARTEFAKTART, O_ARTEFAKTVERSION)
        if (
            k.get("k_id") != str(ableitung.k_id)
            or o.get("o_id") != str(ableitung.o_id)
            or k.get("modellableitungs_id") != str(ableitung.modellableitungs_id)
            or o.get("modellableitungs_id") != str(ableitung.modellableitungs_id)
            or k.get("projekt_id") != str(ableitung.projekt_id)
            or o.get("projekt_id") != str(ableitung.projekt_id)
            or o.get("k_referenz", {}).get("k_id") != str(ableitung.k_id)
            or o.get("k_referenz", {}).get("gesamtpruefsumme") != k["gesamtpruefsumme"]
            or o.get("k_referenz", {}).get("datei_sha256") != ableitung.k_sha256
        ):
            raise Importintegritaetsfehler("Die Beziehung zwischen K und O ist inkonsistent.")
        if ableitung.mappingversion != MAPPINGVERSION:
            return self._historische_ableitung_pruefen(ableitung, k, o)
        basis = self.grundlage_laden(ableitung.projekt_id, ableitung.aggregations_id)
        if (
            basis.eingabefingerabdruck != ableitung.eingabefingerabdruck
            or k.get("eingangslineage") != basis.lineage
            or k.get("mappingversion") != MAPPINGVERSION
            or o.get("mappingversion") != MAPPINGVERSION
        ):
            raise Importintegritaetsfehler(
                "Die vollständige Lineage oder Mappingversion von K und O ist nicht mehr gültig."
            )
        bestandteile = k.get("modellbestandteile", [])
        ids = [wert.get("bestandteil_id") for wert in bestandteile]
        erwartete_ids = [wert.bestandteil_id.value for wert in MODELLBESTANDTEILE]
        if ids != erwartete_ids:
            raise Importintegritaetsfehler(
                "K enthält nicht exakt die 16 Modellbestandteile in stabiler Reihenfolge."
            )
        for definition, bestandteil in zip(MODELLBESTANDTEILE, bestandteile, strict=True):
            informationsquellen = {
                wert.get("herkunftsartefakt") for wert in bestandteil.get("informationen", [])
            }
            zulaessig = {wert.value for wert in definition.zulaessige_quellen}
            if (
                informationsquellen - zulaessig
                or set(bestandteil.get("verwendete_quellen", [])) != informationsquellen
            ):
                raise Importintegritaetsfehler(
                    "Eine Quellenzuordnung in K widerspricht Tabelle 3.15."
                )
            for information in bestandteil.get("informationen", []):
                quelle = Eingangsartefakt(information["herkunftsartefakt"])
                if quelle is Eingangsartefakt.DATENPROFIL_R:
                    gueltige_profile = {
                        (str(wert["import_id"]), str(wert["profil_sha256"]))
                        for wert in basis.profilreferenzen
                    }
                    gueltig = (
                        str(information["herkunftsartefakt_id"]),
                        str(information["herkunftsartefakt_sha256"]),
                    ) in gueltige_profile
                else:
                    referenz = basis.quellreferenzen[quelle]
                    gueltig = str(information["herkunftsartefakt_sha256"]) == str(
                        referenz["sha256"]
                    )
                if not gueltig:
                    raise Importintegritaetsfehler(
                        "Eine Herkunftsprüfsumme in K ist nicht mehr gültig."
                    )
        offene_ids = {wert.get("offener_eintrag_id") for wert in o.get("offene_eintraege", [])}
        referenzierte_ids = {
            offen_id
            for bestandteil in bestandteile
            for offen_id in bestandteil.get("offene_eintrag_ids", [])
        }
        if offene_ids != referenzierte_ids or any(
            wert.get("status") != "offen" for wert in o.get("offene_eintraege", [])
        ):
            raise Importintegritaetsfehler("Die offenen Einträge in K und O sind inkonsistent.")
        entscheidungen = k.get("fachliche_entscheidungen", [])
        entscheidungen_nach_id = {
            wert.get("bestandteil_id"): wert for wert in entscheidungen if isinstance(wert, dict)
        }
        if (
            len(entscheidungen) != len(MODELLBESTANDTEILE)
            or len(entscheidungen_nach_id) != len(MODELLBESTANDTEILE)
            or o.get("fachliche_entscheidungen") != entscheidungen
            or k.get("menschlich_bestaetigt") is not True
            or o.get("menschlich_bestaetigt") is not True
            or k.get("entscheidungsfingerabdruck") != ableitung.unsicherheitsfingerabdruck
            or o.get("entscheidungsfingerabdruck") != ableitung.unsicherheitsfingerabdruck
            or _sha(
                sorted(
                    (
                        wert["bestandteil_id"],
                        wert["entscheidung"],
                        wert.get("begruendung", ""),
                        wert["entschieden_am"],
                    )
                    for wert in entscheidungen
                )
            )
            != ableitung.unsicherheitsfingerabdruck
        ):
            raise Importintegritaetsfehler(
                "Die fachlichen Einzelentscheidungen in K und O sind inkonsistent."
            )
        for bestandteil in bestandteile:
            entscheidung = entscheidungen_nach_id.get(bestandteil["bestandteil_id"])
            if not isinstance(entscheidung, dict) or (
                bestandteil.get("fachliche_entscheidung") != entscheidung
            ):
                raise Importintegritaetsfehler(
                    "Eine fachliche Entscheidung ist nicht ihrem Modellbestandteil zugeordnet."
                )
            informationen = bestandteil.get("informationen", [])
            if entscheidung["entscheidung"] == "vorschlag_uebernehmen":
                if any(
                    information.get("fachliche_entscheidung") != "vorschlag_uebernehmen"
                    or information.get("bestaetigt_am") != entscheidung["entschieden_am"]
                    for information in informationen
                ):
                    raise Importintegritaetsfehler(
                        "Ein bestätigter K-Eintrag besitzt keine passende Übernahmeentscheidung."
                    )
            elif informationen:
                raise Importintegritaetsfehler(
                    "Ein nicht bestätigter Vorschlag darf keine Information in K enthalten."
                )
        if "prozessmodell_p_soll" in json.dumps(k, ensure_ascii=False):
            raise Importintegritaetsfehler("P_Soll darf kein Eingangsartefakt von K sein.")
        return ableitung, k, o

    @staticmethod
    def _historische_ableitung_pruefen(
        ableitung: Modellableitung,
        k: dict[str, Any],
        o: dict[str, Any],
    ) -> tuple[Modellableitung, dict[str, Any], dict[str, Any]]:
        """Hält alte elfteilige K/O-Artefakte kontrolliert lesbar, aber nicht aktuell nutzbar."""
        alte_ids = [
            "problemstellung",
            "zielsetzung",
            "ausgaben_und_eingaben",
            "modellumfang_grenzen_detaillierungsgrad",
            "entitaeten",
            "aktivitaeten",
            "warteschlangen",
            "ressourcen",
            "annahmen_und_vereinfachungen",
            "datenauswahl_und_daten",
            "darstellung_der_vorgaenge_des_systems",
        ]
        ids = [wert.get("bestandteil_id") for wert in k.get("modellbestandteile", [])]
        if (
            ableitung.mappingversion not in {1, 2}
            or k.get("mappingversion") != ableitung.mappingversion
            or ids != alte_ids
        ):
            raise Importintegritaetsfehler(
                "Die historische Modellableitung besitzt keine unterstützte alte Mappingstruktur."
            )
        k["historische_darstellung"] = True
        o["historische_darstellung"] = True
        return ableitung, k, o

    def k_download_laden(self, modellableitungs_id: UUID) -> bytes:
        ableitung, _, _ = self.laden(modellableitungs_id)
        return self._artefakte.lesen(ableitung.relativer_k_pfad)

    def o_download_laden(self, modellableitungs_id: UUID) -> bytes:
        ableitung, _, _ = self.laden(modellableitungs_id)
        return self._artefakte.lesen(ableitung.relativer_o_pfad)

    def uebergabe_schritt9(
        self, modellableitungs_id: UUID, projekt_id: UUID
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Übergibt ausschließlich erneut validiertes K und O an Schritt 9."""
        ableitung, k, o = self.laden(modellableitungs_id)
        if ableitung.projekt_id != projekt_id:
            raise Domaenenfehler("K und O gehören nicht zum aktiven Projekt.")
        if ableitung.mappingversion != MAPPINGVERSION:
            raise Domaenenfehler(
                "Historische elfteilige K/O-Artefakte können nicht als aktuelle Grundlage "
                "an Schritt 9 übergeben werden."
            )
        return k, o
