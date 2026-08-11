"""Algorithmus 9: menschliche Ergänzung, Validierung und Persistenz von K*."""

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, cast
from uuid import UUID

from framework_mvp.application.modellableitung import MODELLBESTANDTEILE
from framework_mvp.application.modellableitung_service import ModellableitungService
from framework_mvp.application.ports.modellvalidierung_repository import (
    ModellvalidierungRepository,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    BehandlungOffenerEintrag,
    Gesamtvalidierungsstatus,
    MenschlicherEintragstyp,
    Modellableitung,
    ModellbestandteilId,
    Modellvalidierung,
    Modellvalidierungsstatus,
    Offenheitsentscheidung,
    Offenheitskategorie,
    ZusaetzlicheModellanpassung,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher

K_STERN_ARTEFAKTART = "validiertes_konzeptionelles_modell_k_stern"
K_STERN_ARTEFAKTVERSION = 1


def _normalisieren(wert: Any) -> Any:
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


@dataclass(frozen=True, slots=True)
class Modellvalidierungsgrundlage:
    """Erneut validiertes, tief kopiertes und untrennbares K/O-Paar."""

    ableitung: Modellableitung
    k: dict[str, Any]
    o: dict[str, Any]
    eingabefingerabdruck: str


@dataclass(frozen=True, slots=True)
class Validierungsarbeitsfassung:
    """Ungespeicherte Human-in-the-Loop-Arbeitsfassung, noch kein K*."""

    grundlage: Modellvalidierungsgrundlage
    behandlungen: tuple[BehandlungOffenerEintrag, ...]
    zusaetzliche_anpassungen: tuple[ZusaetzlicheModellanpassung, ...]
    gesamtvalidierungsstatus: Gesamtvalidierungsstatus
    validierungsvermerk: str
    entscheidungsfingerabdruck: str
    unbehandelte_offene_eintrag_ids: tuple[str, ...]

    @property
    def finalisierbar(self) -> bool:
        return (
            not self.unbehandelte_offene_eintrag_ids
            and self.gesamtvalidierungsstatus is Gesamtvalidierungsstatus.FACHLICH_VALIDIERT
        )


class ModellvalidierungService:
    """Erzeugt K* ausschließlich aus K, O und dokumentiertem Domänenwissen."""

    def __init__(
        self,
        repository: ModellvalidierungRepository,
        modellableitungen: ModellableitungService,
        artefakte: ImportartefaktSpeicher,
    ) -> None:
        self._repository = repository
        self._modellableitungen = modellableitungen
        self._artefakte = artefakte

    def grundlage_laden(
        self,
        projekt_id: UUID,
        modellableitungs_id: UUID,
        *,
        erwartete_k_id: UUID | None = None,
        erwartete_o_id: UUID | None = None,
    ) -> Modellvalidierungsgrundlage:
        """Lädt ausschließlich das aktive, erneut validierte Paar K und O."""
        k, o = self._modellableitungen.uebergabe_schritt9(modellableitungs_id, projekt_id)
        ableitung, k_geprueft, o_geprueft = self._modellableitungen.laden(modellableitungs_id)
        if k != k_geprueft or o != o_geprueft:
            raise Importintegritaetsfehler("Die beiden validierten K/O-Übergaben weichen ab.")
        if erwartete_k_id is not None and ableitung.k_id != erwartete_k_id:
            raise Importintegritaetsfehler("Die aktive K-ID gehört nicht zur Modellableitung.")
        if erwartete_o_id is not None and ableitung.o_id != erwartete_o_id:
            raise Importintegritaetsfehler("Die aktive O-ID gehört nicht zur Modellableitung.")
        fingerabdruck = _sha(
            {
                "modellableitungs_id": ableitung.modellableitungs_id,
                "projekt_id": ableitung.projekt_id,
                "k_id": ableitung.k_id,
                "k_datei_sha256": ableitung.k_sha256,
                "k_gesamtpruefsumme": k["gesamtpruefsumme"],
                "o_id": ableitung.o_id,
                "o_datei_sha256": ableitung.o_sha256,
                "o_gesamtpruefsumme": o["gesamtpruefsumme"],
                "mappingversion": ableitung.mappingversion,
            }
        )
        return Modellvalidierungsgrundlage(
            copy.deepcopy(ableitung), copy.deepcopy(k), copy.deepcopy(o), fingerabdruck
        )

    @staticmethod
    def entscheidungsfingerabdruck(
        behandlungen: tuple[BehandlungOffenerEintrag, ...],
        zusaetzliche_anpassungen: tuple[ZusaetzlicheModellanpassung, ...],
        gesamtvalidierungsstatus: Gesamtvalidierungsstatus,
        validierungsvermerk: str,
    ) -> str:
        behandlungen_normalisiert = sorted(
            (_normalisieren(wert) for wert in behandlungen),
            key=lambda wert: str(wert["offener_eintrag_id"]),
        )
        anpassungen_normalisiert = sorted(
            (_normalisieren(wert) for wert in zusaetzliche_anpassungen),
            key=lambda wert: (
                str(wert["bestandteil_id"]),
                str(wert["fachlicher_inhalt"]),
                str(wert["begruendung"]),
            ),
        )
        return _sha(
            {
                "behandlungen": behandlungen_normalisiert,
                "zusaetzliche_anpassungen": anpassungen_normalisiert,
                "gesamtvalidierungsstatus": gesamtvalidierungsstatus,
                "validierungsvermerk": validierungsvermerk.strip(),
            }
        )

    def arbeitsfassung_erstellen(
        self,
        *,
        projekt_id: UUID,
        modellableitungs_id: UUID,
        erwartete_k_id: UUID,
        erwartete_o_id: UUID,
        behandlungen: tuple[BehandlungOffenerEintrag, ...],
        zusaetzliche_anpassungen: tuple[ZusaetzlicheModellanpassung, ...] = (),
        gesamtvalidierungsstatus: Gesamtvalidierungsstatus,
        validierungsvermerk: str = "",
    ) -> Validierungsarbeitsfassung:
        """Prüft menschliche Eingaben, ohne K, O oder ein K*-Artefakt zu verändern."""
        grundlage = self.grundlage_laden(
            projekt_id,
            modellableitungs_id,
            erwartete_k_id=erwartete_k_id,
            erwartete_o_id=erwartete_o_id,
        )
        offene_nach_id = {
            str(wert["offener_eintrag_id"]): wert
            for wert in grundlage.o.get("offene_eintraege", [])
        }
        behandelte_ids: set[str] = set()
        for behandlung in behandlungen:
            if behandlung.offener_eintrag_id in behandelte_ids:
                raise Domaenenfehler("Ein offener Eintrag darf nur einmal behandelt werden.")
            original = offene_nach_id.get(behandlung.offener_eintrag_id)
            if original is None:
                raise Domaenenfehler("Eine Behandlung referenziert keinen Eintrag des aktiven O.")
            if (
                original.get("bestandteil_id") != behandlung.bestandteil_id.value
                or original.get("kategorie") != behandlung.urspruengliche_kategorie.value
                or original.get("begruendung") != behandlung.urspruengliche_begruendung
            ):
                raise Domaenenfehler(
                    "Bestandteil, Kategorie oder Begründung einer O-Behandlung wurde verändert."
                )
            behandelte_ids.add(behandlung.offener_eintrag_id)
        gueltige_bestandteile = {wert.bestandteil_id for wert in MODELLBESTANDTEILE}
        if any(
            anpassung.bestandteil_id not in gueltige_bestandteile
            for anpassung in zusaetzliche_anpassungen
        ):
            raise Domaenenfehler("Eine Anpassung gehört zu keinem der elf Modellbestandteile.")
        unbehandelt = tuple(wert for wert in offene_nach_id if wert not in behandelte_ids)
        fingerabdruck = self.entscheidungsfingerabdruck(
            behandlungen,
            zusaetzliche_anpassungen,
            gesamtvalidierungsstatus,
            validierungsvermerk,
        )
        return Validierungsarbeitsfassung(
            grundlage,
            behandlungen,
            zusaetzliche_anpassungen,
            gesamtvalidierungsstatus,
            validierungsvermerk.strip(),
            fingerabdruck,
            unbehandelt,
        )

    @staticmethod
    def _menschliche_eintraege(
        arbeitsfassung: Validierungsarbeitsfassung, bestandteil_id: ModellbestandteilId
    ) -> list[dict[str, Any]]:
        eintraege: list[dict[str, Any]] = []
        for behandlung in arbeitsfassung.behandlungen:
            if behandlung.bestandteil_id is bestandteil_id:
                eintraege.append(
                    {
                        "eintragstyp": MenschlicherEintragstyp.BEHANDLUNG_OFFENER_EINTRAG,
                        "offener_eintrag_id": behandlung.offener_eintrag_id,
                        "entscheidung": behandlung.entscheidung,
                        "fachliche_ergaenzung_oder_begruendung": (
                            behandlung.fachliche_ergaenzung_oder_begruendung
                        ),
                        "menschliche_entscheidung": True,
                    }
                )
        for index, anpassung in enumerate(arbeitsfassung.zusaetzliche_anpassungen, 1):
            if anpassung.bestandteil_id is bestandteil_id:
                eintraege.append(
                    {
                        "eintragstyp": MenschlicherEintragstyp.ZUSAETZLICHE_ANPASSUNG,
                        "anpassungsnummer": index,
                        "fachlicher_inhalt": anpassung.fachlicher_inhalt,
                        "begruendung": anpassung.begruendung,
                        "menschliche_entscheidung": True,
                    }
                )
        return _normalisieren(eintraege)

    def speichern(
        self,
        arbeitsfassung: Validierungsarbeitsfassung,
        *,
        validierungslauf_id: UUID,
        k_stern_id: UUID,
        fachlich_bestaetigt: bool,
    ) -> Modellvalidierung:
        """Erzeugt und speichert K* erst nach vollständiger fachlicher Validierung."""
        if not fachlich_bestaetigt:
            raise Domaenenfehler("K* erfordert eine bewusste fachliche Bestätigung.")
        if arbeitsfassung.unbehandelte_offene_eintrag_ids:
            raise Domaenenfehler("Vor K* müssen alle Einträge aus O behandelt werden.")
        if (
            arbeitsfassung.gesamtvalidierungsstatus
            is not Gesamtvalidierungsstatus.FACHLICH_VALIDIERT
        ):
            raise Domaenenfehler("Bei festgestelltem Anpassungsbedarf darf kein K* entstehen.")
        basis = self.grundlage_laden(
            arbeitsfassung.grundlage.ableitung.projekt_id,
            arbeitsfassung.grundlage.ableitung.modellableitungs_id,
            erwartete_k_id=arbeitsfassung.grundlage.ableitung.k_id,
            erwartete_o_id=arbeitsfassung.grundlage.ableitung.o_id,
        )
        if basis.eingabefingerabdruck != arbeitsfassung.grundlage.eingabefingerabdruck:
            raise Domaenenfehler("K oder O wurde verändert; die Arbeitsfassung ist ungültig.")
        aktuell = self.entscheidungsfingerabdruck(
            arbeitsfassung.behandlungen,
            arbeitsfassung.zusaetzliche_anpassungen,
            arbeitsfassung.gesamtvalidierungsstatus,
            arbeitsfassung.validierungsvermerk,
        )
        if aktuell != arbeitsfassung.entscheidungsfingerabdruck:
            raise Domaenenfehler(
                "Menschliche Eingaben wurden verändert; die Arbeitsfassung ist ungültig."
            )
        identisch = self._repository.finde_identisch(
            basis.ableitung.projekt_id,
            basis.ableitung.modellableitungs_id,
            basis.eingabefingerabdruck,
            aktuell,
        )
        if identisch is not None:
            return self.laden(identisch.validierungslauf_id)[0]
        if self._repository.laden(validierungslauf_id) is not None:
            raise Domaenenfehler("Die Validierungslauf-ID wird bereits verwendet.")
        k_vorher, o_vorher = copy.deepcopy(basis.k), copy.deepcopy(basis.o)
        zeitpunkt = datetime.now(UTC)
        k_stern: dict[str, Any] = {
            "artefaktart": K_STERN_ARTEFAKTART,
            "artefaktversion": K_STERN_ARTEFAKTVERSION,
            "k_stern_id": str(k_stern_id),
            "validierungslauf_id": str(validierungslauf_id),
            "projekt_id": str(basis.ableitung.projekt_id),
            "k_referenz": {
                "k_id": str(basis.ableitung.k_id),
                "gesamtpruefsumme": basis.k["gesamtpruefsumme"],
                "datei_sha256": basis.ableitung.k_sha256,
            },
            "o_referenz": {
                "o_id": str(basis.ableitung.o_id),
                "gesamtpruefsumme": basis.o["gesamtpruefsumme"],
                "datei_sha256": basis.ableitung.o_sha256,
            },
            "modellbestandteile": [
                {
                    "bestandteil_id": definition.bestandteil_id,
                    "bezeichnung": definition.bezeichnung,
                    "validierungsstatus": Gesamtvalidierungsstatus.FACHLICH_VALIDIERT,
                    "urspruenglicher_bestandteil": copy.deepcopy(original),
                    "menschliche_eintraege": self._menschliche_eintraege(
                        arbeitsfassung, definition.bestandteil_id
                    ),
                }
                for definition, original in zip(
                    MODELLBESTANDTEILE, basis.k["modellbestandteile"], strict=True
                )
            ],
            "behandlungen_offener_eintraege": arbeitsfassung.behandlungen,
            "gesamtvalidierung": {
                "status": Gesamtvalidierungsstatus.FACHLICH_VALIDIERT,
                "validierungsvermerk": arbeitsfassung.validierungsvermerk,
                "menschlich_bestaetigt": True,
            },
            "eingabefingerabdruck": basis.eingabefingerabdruck,
            "entscheidungsfingerabdruck": aktuell,
            "erstellt_am": zeitpunkt,
        }
        k_stern["gesamtpruefsumme"] = _sha(k_stern)
        k_stern_bytes = _json_bytes(k_stern)
        k_stern_sha = hashlib.sha256(k_stern_bytes).hexdigest()
        if basis.k != k_vorher or basis.o != o_vorher:
            raise Importintegritaetsfehler("K oder O wurde während der Validierung verändert.")
        pfad = (
            PurePosixPath("projects")
            / str(basis.ableitung.projekt_id)
            / "model_validations"
            / str(validierungslauf_id)
            / "validated-conceptual-model-k-star.json"
        ).as_posix()
        validierung = Modellvalidierung(
            validierungslauf_id,
            k_stern_id,
            basis.ableitung.projekt_id,
            basis.ableitung.modellableitungs_id,
            basis.ableitung.k_id,
            basis.ableitung.o_id,
            basis.eingabefingerabdruck,
            aktuell,
            pfad,
            k_stern_sha,
            Modellvalidierungsstatus.FACHLICH_VALIDIERT,
            zeitpunkt,
        )
        erzeugt = None
        try:
            erzeugt = self._artefakte.artefakt_speichern(pfad, k_stern_bytes)
            self._repository.speichern(validierung)
        except Exception:
            if erzeugt is not None:
                self._artefakte.neu_erstelltes_artefakt_entfernen(erzeugt)
            raise
        return self.laden(validierungslauf_id)[0]

    @staticmethod
    def _k_stern_json_pruefen(inhalt: bytes) -> dict[str, Any]:
        try:
            struktur = json.loads(inhalt)
            pruefsumme = struktur.pop("gesamtpruefsumme")
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as fehler:
            raise Importintegritaetsfehler("K* ist kein gültiges JSON-Artefakt.") from fehler
        if (
            struktur.get("artefaktart") != K_STERN_ARTEFAKTART
            or struktur.get("artefaktversion") != K_STERN_ARTEFAKTVERSION
            or _sha(struktur) != pruefsumme
        ):
            raise Importintegritaetsfehler(
                "Artefaktart, Version oder Gesamtprüfsumme von K* ist ungültig."
            )
        struktur["gesamtpruefsumme"] = pruefsumme
        return struktur

    def laden(self, validierungslauf_id: UUID) -> tuple[Modellvalidierung, dict[str, Any]]:
        """Lädt K* erst nach Prüfung des K/O-Paars und aller Humanentscheidungen."""
        validierung = self._repository.laden(validierungslauf_id)
        if validierung is None:
            raise Importintegritaetsfehler("Der Modellvalidierungslauf wurde nicht gefunden.")
        inhalt = self._artefakte.lesen(validierung.relativer_k_stern_pfad)
        if hashlib.sha256(inhalt).hexdigest() != validierung.k_stern_sha256:
            raise Importintegritaetsfehler("Die Dateiprüfsumme von K* ist ungültig.")
        k_stern = self._k_stern_json_pruefen(inhalt)
        basis = self.grundlage_laden(
            validierung.projekt_id,
            validierung.modellableitungs_id,
            erwartete_k_id=validierung.k_id,
            erwartete_o_id=validierung.o_id,
        )
        if (
            basis.eingabefingerabdruck != validierung.eingabefingerabdruck
            or k_stern.get("eingabefingerabdruck") != validierung.eingabefingerabdruck
            or k_stern.get("entscheidungsfingerabdruck") != validierung.entscheidungsfingerabdruck
            or k_stern.get("k_stern_id") != str(validierung.k_stern_id)
            or k_stern.get("validierungslauf_id") != str(validierung.validierungslauf_id)
            or k_stern.get("projekt_id") != str(validierung.projekt_id)
            or k_stern.get("k_referenz")
            != {
                "k_id": str(validierung.k_id),
                "gesamtpruefsumme": basis.k["gesamtpruefsumme"],
                "datei_sha256": basis.ableitung.k_sha256,
            }
            or k_stern.get("o_referenz")
            != {
                "o_id": str(validierung.o_id),
                "gesamtpruefsumme": basis.o["gesamtpruefsumme"],
                "datei_sha256": basis.ableitung.o_sha256,
            }
        ):
            raise Importintegritaetsfehler("Referenzen oder Lineage von K* sind inkonsistent.")
        bestandteile = k_stern.get("modellbestandteile", [])
        erwartete_ids = [wert.bestandteil_id.value for wert in MODELLBESTANDTEILE]
        if [wert.get("bestandteil_id") for wert in bestandteile] != erwartete_ids:
            raise Importintegritaetsfehler(
                "K* enthält nicht exakt die elf Modellbestandteile in stabiler Reihenfolge."
            )
        for original, validiert in zip(basis.k["modellbestandteile"], bestandteile, strict=True):
            if validiert.get("urspruenglicher_bestandteil") != original:
                raise Importintegritaetsfehler("Ein ursprünglicher Inhalt aus K wurde verändert.")
            if any(
                not wert.get("menschliche_entscheidung")
                for wert in validiert.get("menschliche_eintraege", [])
            ):
                raise Importintegritaetsfehler(
                    "Eine Ergänzung in K* ist nicht als menschliche Entscheidung gekennzeichnet."
                )
        offene_nach_id = {wert["offener_eintrag_id"]: wert for wert in basis.o["offene_eintraege"]}
        behandlungen = k_stern.get("behandlungen_offener_eintraege", [])
        if {wert.get("offener_eintrag_id") for wert in behandlungen} != set(offene_nach_id):
            raise Importintegritaetsfehler("K* behandelt nicht exakt alle Einträge aus O.")
        for behandlung in behandlungen:
            original = offene_nach_id[behandlung["offener_eintrag_id"]]
            if (
                behandlung.get("bestandteil_id") != original.get("bestandteil_id")
                or behandlung.get("urspruengliche_kategorie") != original.get("kategorie")
                or behandlung.get("urspruengliche_begruendung") != original.get("begruendung")
                or behandlung.get("entscheidung")
                not in {wert.value for wert in Offenheitsentscheidung}
                or not behandlung.get("fachliche_ergaenzung_oder_begruendung", "").strip()
                or not behandlung.get("menschliche_entscheidung")
            ):
                raise Importintegritaetsfehler("Eine O-Behandlung in K* ist inkonsistent.")
        gesamt = k_stern.get("gesamtvalidierung", {})
        if (
            gesamt.get("status") != Gesamtvalidierungsstatus.FACHLICH_VALIDIERT.value
            or gesamt.get("menschlich_bestaetigt") is not True
            or validierung.status is not Modellvalidierungsstatus.FACHLICH_VALIDIERT
        ):
            raise Importintegritaetsfehler("K* ist nicht ausdrücklich fachlich validiert.")
        behandlungsobjekte = tuple(
            BehandlungOffenerEintrag(
                wert["offener_eintrag_id"],
                ModellbestandteilId(wert["bestandteil_id"]),
                Offenheitskategorie(wert["urspruengliche_kategorie"]),
                wert["urspruengliche_begruendung"],
                Offenheitsentscheidung(wert["entscheidung"]),
                wert["fachliche_ergaenzung_oder_begruendung"],
                wert["menschliche_entscheidung"],
            )
            for wert in behandlungen
        )
        zusaetzliche_roh: list[dict[str, Any]] = []
        behandlungs_eintraege = 0
        for bestandteil in bestandteile:
            bestandteil_id = ModellbestandteilId(bestandteil["bestandteil_id"])
            for eintrag in bestandteil.get("menschliche_eintraege", []):
                if eintrag.get("eintragstyp") == (
                    MenschlicherEintragstyp.BEHANDLUNG_OFFENER_EINTRAG.value
                ):
                    behandlungs_eintraege += 1
                    zugehoerig = next(
                        (
                            wert
                            for wert in behandlungen
                            if wert["offener_eintrag_id"] == eintrag.get("offener_eintrag_id")
                        ),
                        None,
                    )
                    if (
                        zugehoerig is None
                        or zugehoerig["bestandteil_id"] != bestandteil_id.value
                        or eintrag.get("entscheidung") != zugehoerig["entscheidung"]
                        or eintrag.get("fachliche_ergaenzung_oder_begruendung")
                        != zugehoerig["fachliche_ergaenzung_oder_begruendung"]
                    ):
                        raise Importintegritaetsfehler(
                            "Eine O-Behandlung ist dem falschen Bestandteil zugeordnet."
                        )
                elif eintrag.get("eintragstyp") == (
                    MenschlicherEintragstyp.ZUSAETZLICHE_ANPASSUNG.value
                ):
                    zusaetzliche_roh.append(
                        {
                            "anpassungsnummer": eintrag.get("anpassungsnummer"),
                            "bestandteil_id": bestandteil_id,
                            "fachlicher_inhalt": eintrag.get("fachlicher_inhalt", ""),
                            "begruendung": eintrag.get("begruendung", ""),
                        }
                    )
                else:
                    raise Importintegritaetsfehler(
                        "K* enthält einen unbekannten menschlichen Eintragstyp."
                    )
        if behandlungs_eintraege != len(behandlungen):
            raise Importintegritaetsfehler(
                "Die O-Behandlungen sind nicht vollständig Modellbestandteilen zugeordnet."
            )
        nummern = [wert["anpassungsnummer"] for wert in zusaetzliche_roh]
        if any(not isinstance(wert, int) for wert in nummern) or sorted(nummern) != list(
            range(1, len(nummern) + 1)
        ):
            raise Importintegritaetsfehler(
                "Die Reihenfolge zusätzlicher menschlicher Anpassungen ist inkonsistent."
            )
        zusaetzliche_roh.sort(key=lambda wert: wert["anpassungsnummer"])
        zusaetzliche_objekte = tuple(
            ZusaetzlicheModellanpassung(
                wert["bestandteil_id"],
                wert["fachlicher_inhalt"],
                wert["begruendung"],
            )
            for wert in zusaetzliche_roh
        )
        if (
            self.entscheidungsfingerabdruck(
                behandlungsobjekte,
                zusaetzliche_objekte,
                Gesamtvalidierungsstatus.FACHLICH_VALIDIERT,
                str(gesamt.get("validierungsvermerk", "")),
            )
            != validierung.entscheidungsfingerabdruck
        ):
            raise Importintegritaetsfehler(
                "Der Fingerabdruck der menschlichen Entscheidungen in K* ist ungültig."
            )
        return validierung, k_stern

    def k_stern_download_laden(self, validierungslauf_id: UUID) -> bytes:
        validierung, _ = self.laden(validierungslauf_id)
        return self._artefakte.lesen(validierung.relativer_k_stern_pfad)

    def uebergabe_schritt10(
        self, validierungslauf_id: UUID, projekt_id: UUID, k_stern_id: UUID
    ) -> dict[str, Any]:
        """Übergibt ausschließlich ein erneut validiertes K* an Algorithmus 10."""
        validierung, k_stern = self.laden(validierungslauf_id)
        if validierung.projekt_id != projekt_id or validierung.k_stern_id != k_stern_id:
            raise Domaenenfehler("Das aktive K* gehört nicht zum aktiven Projekt oder Lauf.")
        return k_stern
