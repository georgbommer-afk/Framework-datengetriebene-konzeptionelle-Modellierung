"""Domänenvertrag für Algorithmus 9: fachlich validiertes Modell K*."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models.modellableitung import ModellbestandteilId, Offenheitskategorie


class Offenheitsentscheidung(StrEnum):
    """Zulässige menschliche Behandlung eines Eintrags aus O."""

    BESTAETIGT = "bestätigt"
    ERGAENZT_ODER_ANGEPASST = "ergänzt_oder_angepasst"
    NICHT_ANWENDBAR = "nicht_anwendbar"


class Gesamtvalidierungsstatus(StrEnum):
    """Ergebnis einer menschlichen fachlichen Gesamtprüfung."""

    ANPASSUNGSBEDARF = "anpassungsbedarf"
    FACHLICH_VALIDIERT = "fachlich_validiert"


class MenschlicherEintragstyp(StrEnum):
    """Unterscheidet O-Behandlungen von zusätzlichen Anpassungen."""

    BEHANDLUNG_OFFENER_EINTRAG = "behandlung_offener_eintrag"
    ZUSAETZLICHE_ANPASSUNG = "zusaetzliche_anpassung"


class Modellvalidierungsstatus(StrEnum):
    """Persistenzstatus eines abgeschlossenen Algorithmus-9-Laufs."""

    FACHLICH_VALIDIERT = "fachlich_validiert"


@dataclass(frozen=True, slots=True)
class BehandlungOffenerEintrag:
    """Menschliche Entscheidung zu genau einem unveränderten O-Eintrag."""

    offener_eintrag_id: str
    bestandteil_id: ModellbestandteilId
    urspruengliche_kategorie: Offenheitskategorie
    urspruengliche_begruendung: str
    entscheidung: Offenheitsentscheidung
    fachliche_ergaenzung_oder_begruendung: str
    menschliche_entscheidung: bool = True

    def __post_init__(self) -> None:
        if not self.offener_eintrag_id.strip():
            raise Domaenenfehler("Die Behandlung benötigt die ID des offenen Eintrags.")
        if not self.urspruengliche_begruendung.strip():
            raise Domaenenfehler("Die ursprüngliche Begründung aus O darf nicht fehlen.")
        if not self.fachliche_ergaenzung_oder_begruendung.strip():
            raise Domaenenfehler(
                "Jede Behandlung benötigt eine fachliche Ergänzung beziehungsweise Begründung."
            )
        if not self.menschliche_entscheidung:
            raise Domaenenfehler(
                "Eine O-Behandlung muss als menschliche Entscheidung markiert sein."
            )


@dataclass(frozen=True, slots=True)
class ZusaetzlicheModellanpassung:
    """Separater menschlicher Eintrag, der ursprüngliche K-Inhalte nicht überschreibt."""

    bestandteil_id: ModellbestandteilId
    fachlicher_inhalt: str
    begruendung: str
    menschliche_entscheidung: bool = True

    def __post_init__(self) -> None:
        if not self.fachlicher_inhalt.strip() or not self.begruendung.strip():
            raise Domaenenfehler(
                "Eine zusätzliche Anpassung benötigt fachlichen Inhalt und Begründung."
            )
        if not self.menschliche_entscheidung:
            raise Domaenenfehler(
                "Eine zusätzliche Anpassung muss als menschliche Entscheidung markiert sein."
            )


@dataclass(frozen=True, slots=True)
class Modellvalidierung:
    """Persistierte Metadaten eines abgeschlossenen K*-Validierungslaufs."""

    validierungslauf_id: UUID
    k_stern_id: UUID
    projekt_id: UUID
    modellableitungs_id: UUID
    k_id: UUID
    o_id: UUID
    eingabefingerabdruck: str
    entscheidungsfingerabdruck: str
    relativer_k_stern_pfad: str
    k_stern_sha256: str
    status: Modellvalidierungsstatus
    erstellt_am: datetime

    def __post_init__(self) -> None:
        for wert in (
            self.eingabefingerabdruck,
            self.entscheidungsfingerabdruck,
            self.k_stern_sha256,
        ):
            if len(wert) != 64 or any(zeichen not in "0123456789abcdef" for zeichen in wert):
                raise Domaenenfehler("Eine Prüfsumme der Modellvalidierung ist ungültig.")
        if self.erstellt_am.utcoffset() is None:
            raise Domaenenfehler("Der Erstellungszeitpunkt muss zeitzonenbewusst sein.")
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))
