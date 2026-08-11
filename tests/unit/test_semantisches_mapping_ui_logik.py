"""Tests der Schritt-4-Logik für Event-Log-Struktur und Rollen."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pandas as pd
import streamlit as st

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import MappingModus, Zwischendatensatz
from framework_mvp.ui.pages.semantisches_mapping import (
    _aktiven_datensatz_laden,
    _standardrollenvorschlaege,
    _struktur_vorschlagen,
)


def _datensatz(
    projekt_id: UUID, erstellt_am: datetime, datensatz_id: UUID | None = None
) -> Zwischendatensatz:
    identitaet = datensatz_id or uuid4()
    return Zwischendatensatz(
        identitaet,
        projekt_id,
        uuid4(),
        (uuid4(),),
        f"projects/{projekt_id}/interim/{identitaet}.csv.gz",
        f"projects/{projekt_id}/interim/{identitaet}.schema.json",
        f"projects/{projekt_id}/interim/{identitaet}.transformation.json",
        "a" * 64,
        2,
        3,
        erstellt_am,
    )


class _TransformationsService:
    def __init__(
        self,
        datensaetze: list[Zwischendatensatz],
        inkonsistent: set[UUID] | None = None,
    ) -> None:
        self.datensaetze = datensaetze
        self.inkonsistent = inkonsistent or set()

    def datensaetze_fuer_projekt(self, projekt_id: UUID) -> list[Zwischendatensatz]:
        return self.datensaetze

    def zwischendatensatz_laden(self, datensatz_id: UUID) -> tuple[Zwischendatensatz, pd.DataFrame]:
        if datensatz_id in self.inkonsistent:
            raise Domaenenfehler("Inkonsistent")
        datensatz = next(
            wert for wert in self.datensaetze if wert.zwischendatensatz_id == datensatz_id
        )
        return datensatz, pd.DataFrame(
            {"fall": ["A", "A"], "aktivitaet": ["Start", "Ende"], "zeit": [1, 2]}
        )


def test_strukturvorschlag_unterscheidet_ereignisorientiert_und_breit() -> None:
    """Aktivität plus Zeit spricht für Ereigniszeilen, mehrere Zeiten für breite Daten."""
    ereignisse = pd.DataFrame(
        {
            "fall": ["A", "A"],
            "Aktivität": ["Start", "Ende"],
            "Zeit": ["2025-01-01", "2025-01-02"],
        }
    )
    breit = pd.DataFrame(
        {
            "fall": ["A"],
            "Auftrag_angelegt": ["2025-01-01"],
            "Bearbeitung_Ende": ["2025-01-02"],
        }
    )
    assert _struktur_vorschlagen(ereignisse) is MappingModus.EREIGNISORIENTIERT
    assert _struktur_vorschlagen(breit) is MappingModus.BREITER_ZEITSTEMPELDATENSATZ


def test_standardrollen_vorschlaege_bleiben_namensbasiert_und_unverbindlich() -> None:
    """Ressource, Lifecycle sowie Start und Ende werden nur als Kandidaten erkannt."""
    vorschlaege = _standardrollenvorschlaege(
        ["Maschine", "Lifecycle_Status", "Beginn", "Abschluss", "Menge"]
    )
    assert vorschlaege["Ressource"] == ("Maschine",)
    assert vorschlaege["Lifecycle"] == ("Lifecycle_Status",)
    assert vorschlaege["Startzeitstempel"] == ("Beginn",)
    assert vorschlaege["Endzeitstempel"] == ("Abschluss",)


def test_session_datensatz_hat_vorrang_vor_neuestem_fallback() -> None:
    """Ein konsistenter aktiver Datensatz wird trotz eines neueren Datensatzes bewahrt."""
    st.session_state.clear()
    projekt_id = uuid4()
    alt = _datensatz(projekt_id, datetime.now(UTC) - timedelta(days=1))
    neu = _datensatz(projekt_id, datetime.now(UTC))
    st.session_state.aktueller_zwischendatensatz_id = str(alt.zwischendatensatz_id)
    geladen = _aktiven_datensatz_laden(
        _TransformationsService([alt, neu]),  # type: ignore[arg-type]
        projekt_id,
    )
    assert geladen is not None and geladen[0] == alt


def test_inkonsistenter_session_datensatz_faellt_auf_neuesten_zurueck() -> None:
    """Ein defekter aktiver Datensatz wird übersprungen und nicht implizit verwendet."""
    st.session_state.clear()
    projekt_id = uuid4()
    alt = _datensatz(projekt_id, datetime.now(UTC) - timedelta(days=1))
    neu = _datensatz(projekt_id, datetime.now(UTC))
    st.session_state.aktueller_zwischendatensatz_id = str(alt.zwischendatensatz_id)
    geladen = _aktiven_datensatz_laden(
        _TransformationsService([alt, neu], {alt.zwischendatensatz_id}),  # type: ignore[arg-type]
        projekt_id,
    )
    assert geladen is not None and geladen[0] == neu
    assert st.session_state.aktueller_zwischendatensatz_id == str(neu.zwischendatensatz_id)


def test_datensatz_eines_anderen_projekts_wird_nicht_verwendet() -> None:
    """Selbst ein neuer fremder Datensatz darf den zentralen Projektbezug nicht verletzen."""
    st.session_state.clear()
    projekt_id = uuid4()
    fremd = _datensatz(uuid4(), datetime.now(UTC))
    assert (
        _aktiven_datensatz_laden(
            _TransformationsService([fremd]),  # type: ignore[arg-type]
            projekt_id,
        )
        is None
    )
