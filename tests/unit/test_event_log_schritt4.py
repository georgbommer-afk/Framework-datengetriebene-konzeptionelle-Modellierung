"""Fachliche Tests von Pseudocode 4 und Abschnitt 3.6.8."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pandas as pd
import pytest

from framework_mvp.application.event_log import erzeuge_event_log
from framework_mvp.application.mapping import validiere_mapping
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    AKTUELLE_EVENT_LOG_KONFIGURATIONSVERSION,
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    Attributrolle,
    Mappingeintrag,
    MappingModus,
    Mappingstatus,
    Mappingtabelle,
    SemantischesMapping,
    Spaltenzuordnung,
    ZeitstempelZuordnung,
    ZusammengesetzteFallId,
)


def test_aktuelle_event_log_konfigurationsversion_ist_fuenf() -> None:
    assert AKTUELLE_EVENT_LOG_KONFIGURATIONSVERSION == 5


def _konfiguration(
    projekt_id: UUID,
    datensatz_id: UUID,
    *,
    modus: MappingModus = MappingModus.EREIGNISORIENTIERT,
    definition: Aktivitaetsdefinition | None = None,
    zeitzuordnungen: tuple[ZeitstempelZuordnung, ...] = (),
    attribute: tuple[str, ...] = (),
    mappingtabelle_id: UUID | None = None,
) -> SemantischesMapping:
    jetzt = datetime.now(UTC)
    definition = definition or (
        Aktivitaetsdefinition(Aktivitaetsbildungsart.VORHANDENE_SPALTE, ("aktion",))
        if modus is MappingModus.EREIGNISORIENTIERT
        else None
    )
    return SemantischesMapping(
        uuid4(),
        projekt_id,
        datensatz_id,
        modus,
        ZusammengesetzteFallId(("auftrag",)),
        "aktion" if definition and len(definition.quellspalten) == 1 else "",
        "zeit" if modus is MappingModus.EREIGNISORIENTIERT else "",
        "",
        "",
        "",
        "",
        tuple(Spaltenzuordnung(wert, Attributrolle.EREIGNISATTRIBUT) for wert in attribute),
        zeitzuordnungen,
        None,
        jetzt,
        jetzt,
        Mappingstatus.VALIDIERT,
        definition,
        mappingtabelle_id,
        2,
    )


def test_ereignisorientiert_erzeugt_je_tupel_ein_ereignis_und_behaelt_fehler() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A", "A", None],
            "aktion": ["Ende", "Start", None],
            "zeit": ["2025-01-02", "nicht-zeit", None],
        }
    )
    vorher = daten.copy(deep=True)
    konfiguration = _konfiguration(projekt_id, datensatz_id)

    ergebnis = erzeuge_event_log(daten, konfiguration, datensatz_id)

    pd.testing.assert_frame_equal(daten, vorher)
    assert ergebnis.ereignisanzahl == len(daten)
    assert ergebnis.ereignisse["_source_row"].tolist() == [0, 1, 2]
    assert ergebnis.ereignisse["_source_timestamp_raw"].tolist()[:2] == [
        "2025-01-02",
        "nicht-zeit",
    ]
    assert ergebnis.ereignisse["timestamp"].isna().sum() == 2
    assert any("nicht interpretierbar" in wert for wert in ergebnis.warnungen)
    assert any("Schritt 5" in wert for wert in ergebnis.warnungen)


def test_m_wird_typisiert_im_richtigen_spaltenkontext_und_kollisionssicher_angewandt() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    mapping = Mappingtabelle.neu(projekt_id, datensatz_id)
    mapping = mapping.eintrag_hinzufuegen(Mappingeintrag.fuer_spalte("merkmal_a", "Merkmal"))
    mapping = mapping.eintrag_hinzufuegen(Mappingeintrag.fuer_spalte("merkmal_b", "Merkmal"))
    mapping = mapping.eintrag_hinzufuegen(Mappingeintrag.fuer_wert("aktion", "1", "Starten"))
    mapping = mapping.eintrag_hinzufuegen(
        Mappingeintrag.fuer_wert("status", "1", "Freigegeben")
    ).bestaetigen()
    daten = pd.DataFrame(
        {
            "auftrag": ["A", "A"],
            "aktion": ["1", "2"],
            "zeit": ["2025-01-01", "2025-01-02"],
            "status": ["1", "2"],
            "gleichlautend": ["1", "2"],
            "merkmal_a": [10, 11],
            "merkmal_b": [20, 21],
        }
    )
    konfiguration = _konfiguration(
        projekt_id,
        datensatz_id,
        attribute=("status", "gleichlautend", "merkmal_a", "merkmal_b"),
        mappingtabelle_id=mapping.mapping_id,
    )

    ergebnis = erzeuge_event_log(daten, konfiguration, datensatz_id, mapping)

    assert ergebnis.ereignisse["activity"].tolist() == ["Starten", "2"]
    assert ergebnis.ereignisse["status"].tolist() == ["Freigegeben", "2"]
    assert ergebnis.ereignisse["gleichlautend"].tolist() == ["1", "2"]
    assert ergebnis.ereignisse["Merkmal [merkmal_a]"].tolist() == [10, 11]
    assert ergebnis.ereignisse["Merkmal [merkmal_b]"].tolist() == [20, 21]
    assert ergebnis.attributherkunft == {
        "status": "status",
        "gleichlautend": "gleichlautend",
        "Merkmal [merkmal_a]": "merkmal_a",
        "Merkmal [merkmal_b]": "merkmal_b",
    }


def test_zusammengesetzte_aktivitaet_bewahrt_reihenfolge_und_laesst_fehlwert_leer() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A", "A"],
            "von": ["A01", None],
            "zu": ["B03", "C01"],
            "zeit": ["2025-01-01", "2025-01-02"],
        }
    )
    definition = Aktivitaetsdefinition(
        Aktivitaetsbildungsart.ZUSAMMENGESETZT,
        ("von", "zu"),
        " → ",
        fehlwertstrategie="Ergebnis leer lassen",
    )
    konfiguration = _konfiguration(projekt_id, datensatz_id, definition=definition)

    ergebnis = erzeuge_event_log(daten, konfiguration, datensatz_id)

    assert ergebnis.ereignisse["activity"].iloc[0] == "A01 → B03"
    assert pd.isna(ergebnis.ereignisse["activity"].iloc[1])
    wirksame_definition = konfiguration.wirksame_aktivitaetsdefinition
    assert wirksame_definition is not None
    assert wirksame_definition.quellspalten == ("von", "zu")


def test_breiter_pfad_erzeugt_exakt_je_vorhandenem_ausgewaehltem_zeitstempel() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A", "A"],
            "start": ["2025-01-01 10:00", ""],
            "ende": ["2025-01-01 10:00", "2025-01-02 12:00"],
            "nicht_gewaehlt": ["2025-01-03", "2025-01-03"],
            "ressource": ["R1", "R2"],
        }
    )
    konfiguration = _konfiguration(
        projekt_id,
        datensatz_id,
        modus=MappingModus.BREITER_ZEITSTEMPELDATENSATZ,
        zeitzuordnungen=(
            ZeitstempelZuordnung("ende", "Beenden"),
            ZeitstempelZuordnung("start", "Starten"),
        ),
        attribute=("ressource",),
    )

    ergebnis = erzeuge_event_log(daten, konfiguration, datensatz_id)

    assert ergebnis.ereignisanzahl == 3
    assert ergebnis.ereignisse["activity"].tolist() == [
        "Beenden",
        "Starten",
        "Beenden",
    ]
    assert ergebnis.ereignisse["_source_timestamp_column"].tolist() == [
        "ende",
        "start",
        "ende",
    ]
    assert "nicht_gewaehlt" not in ergebnis.ereignisse.columns
    assert ergebnis.ereignisse["ressource"].tolist() == ["R1", "R1", "R2"]


def test_version_drei_erzeugt_optionale_kanonische_rollen_mit_utc_zeiten() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A"],
            "aktion": ["Bearbeiten"],
            "zeit": ["2025-01-01T10:00:00+01:00"],
            "start": ["2025-01-01T09:00:00+01:00"],
            "ende": ["2025-01-01T10:30:00Z"],
            "bearbeiter": ["R1"],
            "status": ["complete"],
        }
    )
    konfiguration = replace(
        _konfiguration(projekt_id, datensatz_id),
        konfigurationsversion=3,
        startzeitstempelspalte="start",
        endzeitstempelspalte="ende",
        ressourcen_spalte="bearbeiter",
        lifecycle_spalte="status",
    )

    ergebnis = erzeuge_event_log(daten, konfiguration, datensatz_id)

    assert ergebnis.ereignisse["resource"].tolist() == ["R1"]
    assert ergebnis.ereignisse["lifecycle"].tolist() == ["complete"]
    assert isinstance(ergebnis.ereignisse["start_timestamp"].dtype, pd.DatetimeTZDtype)
    assert isinstance(ergebnis.ereignisse["end_timestamp"].dtype, pd.DatetimeTZDtype)
    assert str(ergebnis.ereignisse["start_timestamp"].dt.tz) == "UTC"
    assert str(ergebnis.ereignisse["end_timestamp"].dt.tz) == "UTC"
    assert ergebnis.herkunft_standardspalten["resource"] == "bearbeiter"
    assert ergebnis.herkunft_standardspalten["start_timestamp"] == "start"


def test_version_fuenf_erlaubt_ereigniszeitstempel_auch_als_ist_startzeitpunkt() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A", "A"],
            "aktion": ["Starten", "Beenden"],
            "IstStart": ["2025-01-01T08:00:00+01:00", "2025-01-01T09:00:00+01:00"],
            "IstEnde": ["2025-01-01T08:30:00+01:00", "2025-01-01T09:30:00+01:00"],
        }
    )
    konfiguration = replace(
        _konfiguration(projekt_id, datensatz_id),
        konfigurationsversion=5,
        zeitstempelspalte="IstStart",
        startzeitstempelspalte="IstStart",
        endzeitstempelspalte="IstEnde",
    )

    validierung = validiere_mapping(daten, konfiguration).validierung
    ergebnis = erzeuge_event_log(daten, konfiguration, datensatz_id)

    assert validierung.gueltig
    assert not any(wert.code == "DOPPELTE_ROLLENBELEGUNG" for wert in validierung.warnungen)
    timestamp_utc = pd.to_datetime(ergebnis.ereignisse["timestamp"], utc=True)
    pd.testing.assert_series_equal(
        timestamp_utc.reset_index(drop=True),
        ergebnis.ereignisse["start_timestamp"].reset_index(drop=True),
        check_names=False,
    )
    assert ergebnis.herkunft_standardspalten["timestamp"] == "IstStart"
    assert ergebnis.herkunft_standardspalten["start_timestamp"] == "IstStart"
    assert ergebnis.herkunft_standardspalten["end_timestamp"] == "IstEnde"


def test_version_fuenf_erlaubt_ereigniszeitstempel_auch_als_ist_endzeitpunkt() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A"],
            "aktion": ["Fräsen abgeschlossen"],
            "IstEnde": ["2025-01-01T10:00:00Z"],
        }
    )
    konfiguration = replace(
        _konfiguration(projekt_id, datensatz_id),
        konfigurationsversion=5,
        zeitstempelspalte="IstEnde",
        endzeitstempelspalte="IstEnde",
    )

    ergebnis = erzeuge_event_log(daten, konfiguration, datensatz_id)

    assert "start_timestamp" not in ergebnis.ereignisse
    pd.testing.assert_series_equal(
        pd.to_datetime(ergebnis.ereignisse["timestamp"], utc=True),
        ergebnis.ereignisse["end_timestamp"],
        check_names=False,
    )
    assert ergebnis.herkunft_standardspalten["timestamp"] == "IstEnde"
    assert ergebnis.herkunft_standardspalten["end_timestamp"] == "IstEnde"


def test_version_fuenf_verbietet_dieselbe_quelle_fuer_ist_start_und_ist_ende() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    basis = _konfiguration(projekt_id, datensatz_id)

    with pytest.raises(Domaenenfehler, match="Ist-Startzeitpunkt und Ist-Endzeitpunkt"):
        replace(
            basis,
            konfigurationsversion=5,
            startzeitstempelspalte="zeit",
            endzeitstempelspalte="zeit",
        )


def test_version_fuenf_erzeugt_getrennte_plan_start_und_endzeitpunkte() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A"],
            "aktion": ["Bearbeiten"],
            "IstStart": ["2025-01-01T08:00:00Z"],
            "IstEnde": ["2025-01-01T09:00:00Z"],
            "SollStart": ["2025-01-01T07:45:00Z"],
            "SollEnde": ["2025-01-01T08:45:00Z"],
        }
    )
    konfiguration = replace(
        _konfiguration(projekt_id, datensatz_id),
        konfigurationsversion=5,
        zeitstempelspalte="IstStart",
        startzeitstempelspalte="IstStart",
        endzeitstempelspalte="IstEnde",
        plan_startzeitstempelspalte="SollStart",
        plan_endzeitstempelspalte="SollEnde",
    )

    ergebnis = erzeuge_event_log(daten, konfiguration, datensatz_id)

    assert ergebnis.herkunft_standardspalten["plan_start_timestamp"] == "SollStart"
    assert ergebnis.herkunft_standardspalten["plan_end_timestamp"] == "SollEnde"
    assert str(ergebnis.ereignisse["plan_start_timestamp"].dt.tz) == "UTC"
    assert str(ergebnis.ereignisse["plan_end_timestamp"].dt.tz) == "UTC"


def test_version_fuenf_verbietet_dieselbe_planquelle_fuer_start_und_ende() -> None:
    basis = _konfiguration(uuid4(), uuid4())

    with pytest.raises(Domaenenfehler, match="Plan-Startzeitpunkt und Plan-Endzeitpunkt"):
        replace(
            basis,
            konfigurationsversion=5,
            plan_startzeitstempelspalte="soll",
            plan_endzeitstempelspalte="soll",
        )


def test_version_drei_behaelt_das_verbot_der_mehrfachrolle() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    with pytest.raises(Domaenenfehler, match="mehreren Standardrollen"):
        replace(
            _konfiguration(projekt_id, datensatz_id),
            konfigurationsversion=3,
            startzeitstempelspalte="zeit",
        )


def test_version_vier_konstruiert_keine_fehlenden_start_oder_endzeitpunkte() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A", "A"],
            "aktion": ["A", "B"],
            "zeit": ["2025-01-01 08:00", "2025-01-01 08:30"],
        }
    )
    konfiguration = replace(
        _konfiguration(projekt_id, datensatz_id),
        konfigurationsversion=4,
    )

    ereignisse = erzeuge_event_log(daten, konfiguration, datensatz_id).ereignisse

    assert "start_timestamp" not in ereignisse
    assert "end_timestamp" not in ereignisse


def test_version_vier_sortiert_weiterhin_nach_ereigniszeitstempel() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A", "A"],
            "aktion": ["späteres Event", "früheres Event"],
            "ereigniszeit": ["2025-01-01 10:00", "2025-01-01 09:00"],
            "start": ["2025-01-01 07:00", "2025-01-01 08:00"],
            "ende": ["2025-01-01 07:30", "2025-01-01 08:30"],
        }
    )
    konfiguration = replace(
        _konfiguration(projekt_id, datensatz_id),
        konfigurationsversion=4,
        zeitstempelspalte="ereigniszeit",
        startzeitstempelspalte="start",
        endzeitstempelspalte="ende",
    )

    ereignisse = erzeuge_event_log(daten, konfiguration, datensatz_id).ereignisse

    assert ereignisse["activity"].tolist() == ["früheres Event", "späteres Event"]


def test_start_nach_ende_bleibt_transparenter_validierungsbefund() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A"],
            "aktion": ["Bearbeiten"],
            "zeit": ["2025-01-01 09:00"],
            "start": ["2025-01-01 09:00"],
            "ende": ["2025-01-01 08:00"],
        }
    )
    konfiguration = replace(
        _konfiguration(projekt_id, datensatz_id),
        konfigurationsversion=4,
        startzeitstempelspalte="start",
        endzeitstempelspalte="ende",
    )

    ergebnis = validiere_mapping(daten, konfiguration)

    assert ergebnis.validierung.start_nach_ende == 1
    assert any(wert.code == "START_NACH_ENDE" for wert in ergebnis.validierung.warnungen)
    assert daten.loc[0, "start"] == "2025-01-01 09:00"
    assert daten.loc[0, "ende"] == "2025-01-01 08:00"


def test_version_drei_verbietet_ressource_zusaetzlich_als_allgemeines_attribut() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    basis = replace(
        _konfiguration(projekt_id, datensatz_id),
        konfigurationsversion=3,
        ressourcen_spalte="bearbeiter",
    )

    with pytest.raises(Domaenenfehler, match="allgemeines Attribut"):
        replace(
            basis,
            spaltenzuordnungen=(Spaltenzuordnung("bearbeiter", Attributrolle.EREIGNISATTRIBUT),),
        )


def test_version_drei_ordnete_im_breiten_modus_ressource_und_status_je_zeitspalte_zu() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A"],
            "start": ["2025-01-01"],
            "ende": ["2025-01-02"],
            "start_person": ["R1"],
            "ende_person": ["R2"],
            "start_status": ["started"],
            "ende_status": ["complete"],
        }
    )
    basis = _konfiguration(
        projekt_id,
        datensatz_id,
        modus=MappingModus.BREITER_ZEITSTEMPELDATENSATZ,
        zeitzuordnungen=(
            ZeitstempelZuordnung("start", "Start"),
            ZeitstempelZuordnung("ende", "Ende"),
        ),
    )
    konfiguration = replace(
        basis,
        konfigurationsversion=3,
        zeitstempelzuordnungen=(
            ZeitstempelZuordnung("start", "Start", "start_person", "start_status"),
            ZeitstempelZuordnung("ende", "Ende", "ende_person", "ende_status"),
        ),
    )

    ergebnis = erzeuge_event_log(daten, konfiguration, datensatz_id)

    assert ergebnis.ereignisse["resource"].tolist() == ["R1", "R2"]
    assert ergebnis.ereignisse["lifecycle"].tolist() == ["started", "complete"]
    assert "start_timestamp" not in ergebnis.ereignisse
    assert "end_timestamp" not in ergebnis.ereignisse
    assert ergebnis.herkunft_standardspalten["resource"] == (
        "start: start_person; ende: ende_person"
    )


def test_version_eins_und_zwei_behalten_ihre_bisherige_rollensemantik() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A"],
            "aktion": ["Start"],
            "zeit": ["2025-01-01"],
            "bearbeiter": ["R1"],
        }
    )
    basis = _konfiguration(projekt_id, datensatz_id)
    version_eins = replace(
        basis,
        konfigurationsversion=1,
        ressourcen_spalte="bearbeiter",
    )
    version_zwei = replace(
        basis,
        spaltenzuordnungen=(Spaltenzuordnung("bearbeiter", Attributrolle.EREIGNISATTRIBUT),),
    )

    ereignisse_eins = erzeuge_event_log(daten, version_eins, datensatz_id).ereignisse
    ereignisse_zwei = erzeuge_event_log(daten, version_zwei, datensatz_id).ereignisse

    assert ereignisse_eins["resource"].tolist() == ["R1"]
    assert "bearbeiter" not in ereignisse_eins
    assert ereignisse_zwei["bearbeiter"].tolist() == ["R1"]
    assert "resource" not in ereignisse_zwei


def test_neue_konfiguration_weist_legacy_erweiterungen_und_mehrere_fallspalten_ab() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    basis = _konfiguration(projekt_id, datensatz_id)
    with pytest.raises(Domaenenfehler, match="genau eine"):
        replace(basis, fall_id=ZusammengesetzteFallId(("auftrag", "position")))
    definition = Aktivitaetsdefinition(
        Aktivitaetsbildungsart.ZUSAMMENGESETZT,
        ("von", "zu"),
        " → ",
        praefix="von ",
        fehlwertstrategie="Ergebnis leer lassen",
    )
    with pytest.raises(Domaenenfehler, match="Reihenfolge und Verknüpfungselement"):
        replace(basis, aktivitaetsspalte="", aktivitaetsdefinition=definition)


def test_fremdes_m_oder_fremdes_t_wird_abgelehnt() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    konfiguration = _konfiguration(projekt_id, datensatz_id)
    daten = pd.DataFrame({"auftrag": ["A"], "aktion": ["Start"], "zeit": ["2025-01-01"]})
    with pytest.raises(Domaenenfehler, match="aktuellen T"):
        erzeuge_event_log(daten, konfiguration, uuid4())
    fremd = Mappingtabelle.neu(projekt_id, uuid4()).bestaetigen(kein_mapping_erforderlich=True)
    with pytest.raises(Domaenenfehler, match="passen nicht zusammen"):
        erzeuge_event_log(daten, konfiguration, datensatz_id, fremd)


def test_sortierung_ist_bei_gleichstand_und_unlesbaren_zeiten_stabil() -> None:
    projekt_id, datensatz_id = uuid4(), uuid4()
    daten = pd.DataFrame(
        {
            "auftrag": ["A", "A", "A", "A"],
            "aktion": ["ungültig", "erste", "zweite", "fehlend"],
            "zeit": ["keine Zeit", "2025-01-01", "2025-01-01", None],
        }
    )

    ergebnis = erzeuge_event_log(daten, _konfiguration(projekt_id, datensatz_id), datensatz_id)

    assert ergebnis.ereignisse["_source_row"].tolist() == [1, 2, 0, 3]
    assert ergebnis.ereignisse["activity"].tolist() == [
        "erste",
        "zweite",
        "ungültig",
        "fehlend",
    ]
