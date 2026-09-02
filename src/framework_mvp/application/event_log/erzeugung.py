# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportAssignmentType=false, reportReturnType=false
"""Reine Erzeugung des fallbezogenen Event Logs E gemäß Abschnitt 3.6.8."""

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

import pandas as pd

from framework_mvp.application.transformation import kombiniere_textspalten
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Attributrolle,
    Ereignisrolle,
    Mappingeintragsart,
    MappingModus,
    Mappingtabelle,
    SemantischesMapping,
    TechnischeWertreferenz,
)


@dataclass(frozen=True, slots=True)
class EventLogErgebnis:
    """Kanonische Ereignisse, Kennzahlen, Herkunft und transparente Hinweise."""

    ereignisse: pd.DataFrame
    ereignisanzahl: int
    fallanzahl: int
    aktivitaetsanzahl: int
    fruehester_zeitpunkt: pd.Timestamp | None
    spaetester_zeitpunkt: pd.Timestamp | None
    herkunft_standardspalten: dict[str, str]
    attributrollen: dict[str, str]
    warnungen: tuple[str, ...]
    attributherkunft: dict[str, str]
    angewandte_mappingeintraege: tuple[dict[str, str], ...]


def _ist_leer(wert: object) -> bool:
    try:
        if bool(pd.isna(wert)):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(wert, str) and not wert.strip()


def _fachlicher_wert(
    mappingtabelle: Mappingtabelle | None, quellspalte: str, wert: object
) -> object:
    """Wendet typ- und spaltengebundenes Wertmapping an, sonst bleibt der Wert erhalten."""
    if mappingtabelle is None or _ist_leer(wert):
        return wert
    referenz = TechnischeWertreferenz.aus_wert(wert)
    for eintrag in mappingtabelle.eintraege:
        if (
            eintrag.art is Mappingeintragsart.TECHNISCHER_WERT
            and eintrag.technische_quellspalte == quellspalte
            and eintrag.wertreferenz is not None
            and eintrag.wertreferenz.schluessel == referenz.schluessel
        ):
            return eintrag.fachliche_bezeichnung
    return wert


def _fachliche_serie(
    daten: pd.DataFrame, spalte: str, mappingtabelle: Mappingtabelle | None
) -> pd.Series:
    return daten[spalte].map(lambda wert: _fachlicher_wert(mappingtabelle, spalte, wert))


def _fall_ids(
    daten: pd.DataFrame,
    konfiguration: SemantischesMapping,
    mappingtabelle: Mappingtabelle | None,
) -> tuple[pd.Series, pd.Series]:
    spalten = konfiguration.fall_id.spalten
    if len(spalten) == 1:
        roh = daten[spalten[0]].copy(deep=True)
        return _fachliche_serie(daten, spalten[0], mappingtabelle), roh
    # Kontrollierter Legacy-Pfad für bestehende zusammengesetzte Fall-IDs.
    teile = daten[list(spalten)].astype("string")
    leer = teile.isna().any(axis=1) | teile.apply(
        lambda zeile: any(not str(wert).strip() for wert in zeile), axis=1
    )
    ids = teile.fillna("").agg(konfiguration.fall_id.trennzeichen.join, axis=1).astype("string")
    ids.loc[leer] = pd.NA
    roh = daten[list(spalten)].apply(
        lambda zeile: json.dumps(list(zeile), ensure_ascii=False, default=str), axis=1
    )
    return ids, roh


def _event_id(
    datensatz_id: UUID, konfigurations_id: UUID, quellzeile: int, herkunftsspalte: str
) -> str:
    roh = f"{datensatz_id}|{konfigurations_id}|{quellzeile}|{herkunftsspalte}".encode()
    return hashlib.sha256(roh).hexdigest()


def _ausgabenamen(
    konfiguration: SemantischesMapping, mappingtabelle: Mappingtabelle | None
) -> tuple[dict[str, str], dict[str, str]]:
    """Löst gleiche fachliche Namen reproduzierbar und ohne Datenverlust auf."""
    technische_spalten = list(konfiguration.zusaetzliche_attribute)
    basen = {
        spalte: (
            mappingtabelle.fachliche_spaltenbezeichnung(spalte)
            if mappingtabelle is not None
            else spalte
        )
        for spalte in technische_spalten
    }
    haeufigkeit = {basis: list(basen.values()).count(basis) for basis in set(basen.values())}
    reserviert = {"case_id", "activity", "timestamp", "event_id"}
    if konfiguration.konfigurationsversion >= 3:
        reserviert.update(
            {
                "start_timestamp",
                "end_timestamp",
                "plan_start_timestamp",
                "plan_end_timestamp",
                "lifecycle",
                "resource",
            }
        )
    verwendet = set(reserviert)
    ausgabenamen: dict[str, str] = {}
    herkunft: dict[str, str] = {}
    for spalte in technische_spalten:
        basis = basen[spalte]
        kandidat = basis
        if haeufigkeit[basis] > 1 or kandidat in verwendet or kandidat.startswith("_"):
            kandidat = f"{basis} [{spalte}]"
        nummer = 2
        eindeutig = kandidat
        while eindeutig in verwendet:
            eindeutig = f"{kandidat} #{nummer}"
            nummer += 1
        verwendet.add(eindeutig)
        ausgabenamen[spalte] = eindeutig
        herkunft[eindeutig] = spalte
    return ausgabenamen, herkunft


def _attribute_ereignisorientiert(
    daten: pd.DataFrame,
    konfiguration: SemantischesMapping,
    mappingtabelle: Mappingtabelle | None,
    ziel: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str]]:
    ausgabenamen, herkunft = _ausgabenamen(konfiguration, mappingtabelle)
    rollen: dict[str, str] = {}
    for zuordnung in konfiguration.spaltenzuordnungen:
        if zuordnung.rolle is Attributrolle.IGNORIERT:
            continue
        zielname = ausgabenamen.get(zuordnung.spaltenname)
        if konfiguration.konfigurationsversion < 2 and (
            zuordnung.rolle is Ereignisrolle.QUELL_EREIGNIS_ID
        ):
            zielname = "source_event_id"
            herkunft[zielname] = zuordnung.spaltenname
        if zielname is None:
            zielname = zuordnung.spaltenname
            herkunft[zielname] = zuordnung.spaltenname
        ziel[zielname] = _fachliche_serie(daten, zuordnung.spaltenname, mappingtabelle).to_numpy()
        rollen[zielname] = (
            "Zusätzliches Attribut"
            if konfiguration.konfigurationsversion >= 2
            else zuordnung.rolle.value
        )
    return ziel, rollen, herkunft


def _zusammengesetzte_aktivitaet(
    daten: pd.DataFrame,
    konfiguration: SemantischesMapping,
    mappingtabelle: Mappingtabelle | None,
) -> tuple[pd.Series, pd.Series]:
    definition = konfiguration.wirksame_aktivitaetsdefinition
    assert definition is not None
    roh = daten[list(definition.quellspalten)].apply(
        lambda zeile: json.dumps(list(zeile), ensure_ascii=False, default=str), axis=1
    )
    if konfiguration.konfigurationsversion < 2:
        return (
            kombiniere_textspalten(
                daten,
                definition.quellspalten,
                trennzeichen=definition.trennzeichen,
                praefix=definition.praefix,
                suffix=definition.suffix,
                fehlwertstrategie=definition.fehlwertstrategie,
                ersatztext=definition.ersatztext,
            ),
            roh,
        )
    fachliche_spalten = pd.DataFrame(
        {
            spalte: _fachliche_serie(daten, spalte, mappingtabelle)
            for spalte in definition.quellspalten
        }
    )

    def verbinden(zeile: pd.Series) -> object:
        if any(_ist_leer(wert) for wert in zeile):
            return pd.NA
        return definition.trennzeichen.join(str(wert).strip() for wert in zeile)

    return fachliche_spalten.apply(verbinden, axis=1).astype("string"), roh


def _ereignisorientiert(
    daten: pd.DataFrame,
    konfiguration: SemantischesMapping,
    mappingtabelle: Mappingtabelle | None,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str], dict[str, str]]:
    quellzeilen = pd.Series(range(len(daten)), index=daten.index, dtype="int64")
    fall_ids, fall_roh = _fall_ids(daten, konfiguration, mappingtabelle)
    definition = konfiguration.wirksame_aktivitaetsdefinition
    if definition is None:
        aktivitaeten = pd.Series(pd.NA, index=daten.index)
        aktivitaet_roh = aktivitaeten.copy()
        aktivitaetsherkunft = ""
    elif definition.bildungsart is Aktivitaetsbildungsart.VORHANDENE_SPALTE:
        spalte = definition.quellspalten[0]
        aktivitaeten = _fachliche_serie(daten, spalte, mappingtabelle)
        aktivitaet_roh = daten[spalte].copy(deep=True)
        aktivitaetsherkunft = spalte
    else:
        aktivitaeten, aktivitaet_roh = _zusammengesetzte_aktivitaet(
            daten, konfiguration, mappingtabelle
        )
        aktivitaetsherkunft = " + ".join(definition.quellspalten)
    ereignisse = pd.DataFrame(
        {
            "case_id": fall_ids,
            "activity": aktivitaeten,
            "timestamp": daten[konfiguration.zeitstempelspalte],
            "_source_case_id_raw": fall_roh,
            "_source_activity_raw": aktivitaet_roh,
            "_source_timestamp_raw": daten[konfiguration.zeitstempelspalte].copy(deep=True),
            "_source_row": quellzeilen,
            "_source_timestamp_column": konfiguration.zeitstempelspalte,
            "_source_timestamp_order": 0,
        }
    )
    standardherkunft = {
        "case_id": konfiguration.fall_id.trennzeichen.join(konfiguration.fall_id.spalten),
        "activity": aktivitaetsherkunft,
        "timestamp": konfiguration.zeitstempelspalte,
    }
    # Version 1 bleibt im bisherigen Rohwertpfad; ab Version 3 gilt dieselbe fachliche
    # Wertabbildung für alle expliziten Rollen.
    if konfiguration.konfigurationsversion != 2:
        for ziel, quelle in {
            "start_timestamp": konfiguration.startzeitstempelspalte,
            "end_timestamp": konfiguration.endzeitstempelspalte,
            "plan_start_timestamp": konfiguration.plan_startzeitstempelspalte,
            "plan_end_timestamp": konfiguration.plan_endzeitstempelspalte,
            "lifecycle": konfiguration.lifecycle_spalte,
            "resource": konfiguration.ressourcen_spalte,
        }.items():
            if quelle:
                ereignisse[ziel] = (
                    _fachliche_serie(daten, quelle, mappingtabelle)
                    if konfiguration.konfigurationsversion >= 3
                    else daten[quelle]
                )
                if konfiguration.konfigurationsversion >= 3:
                    standardherkunft[ziel] = quelle
    ereignisse, rollen, attributherkunft = _attribute_ereignisorientiert(
        daten, konfiguration, mappingtabelle, ereignisse
    )
    return (
        ereignisse,
        standardherkunft,
        rollen,
        attributherkunft,
    )


def _breit(
    daten: pd.DataFrame,
    konfiguration: SemantischesMapping,
    mappingtabelle: Mappingtabelle | None,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str], dict[str, str]]:
    fall_ids, fall_roh = _fall_ids(daten, konfiguration, mappingtabelle)
    ausgabenamen, attributherkunft = _ausgabenamen(konfiguration, mappingtabelle)
    rollen = {name: "Zusätzliches Attribut" for name in ausgabenamen.values()}
    teile: list[pd.DataFrame] = []
    for reihenfolge, zuordnung in enumerate(konfiguration.zeitstempelzuordnungen):
        maske = daten[zuordnung.zeitstempelspalte].map(lambda wert: not _ist_leer(wert))
        positionen = [position for position, vorhanden in enumerate(maske) if vorhanden]
        if not positionen:
            continue
        teil = pd.DataFrame(
            {
                "case_id": fall_ids.iloc[positionen].to_numpy(),
                "activity": zuordnung.aktivitaetsbezeichnung,
                "timestamp": daten[zuordnung.zeitstempelspalte].iloc[positionen].to_numpy(),
                "_source_case_id_raw": fall_roh.iloc[positionen].to_numpy(),
                "_source_activity_raw": pd.NA,
                "_source_timestamp_raw": daten[zuordnung.zeitstempelspalte]
                .iloc[positionen]
                .to_numpy(),
                "_source_row": positionen,
                "_source_timestamp_column": zuordnung.zeitstempelspalte,
                "_source_timestamp_order": reihenfolge,
            }
        )
        if konfiguration.konfigurationsversion != 2:
            if zuordnung.ressourcenspalte:
                quelle = (
                    _fachliche_serie(daten, zuordnung.ressourcenspalte, mappingtabelle)
                    if konfiguration.konfigurationsversion >= 3
                    else daten[zuordnung.ressourcenspalte]
                )
                teil["resource"] = quelle.iloc[positionen].to_numpy()
            if zuordnung.statusspalte:
                quelle = (
                    _fachliche_serie(daten, zuordnung.statusspalte, mappingtabelle)
                    if konfiguration.konfigurationsversion >= 3
                    else daten[zuordnung.statusspalte]
                )
                teil["lifecycle"] = quelle.iloc[positionen].to_numpy()
        for attribut in konfiguration.spaltenzuordnungen:
            if attribut.rolle is Attributrolle.IGNORIERT:
                continue
            zielname = ausgabenamen.get(attribut.spaltenname, attribut.spaltenname)
            teil[zielname] = (
                _fachliche_serie(daten, attribut.spaltenname, mappingtabelle)
                .iloc[positionen]
                .to_numpy()
            )
            if konfiguration.konfigurationsversion < 2:
                rollen[zielname] = attribut.rolle.value
                attributherkunft[zielname] = attribut.spaltenname
        teile.append(teil)
    ereignisse = (
        pd.concat(teile, ignore_index=True)
        if teile
        else pd.DataFrame(
            columns=[
                "case_id",
                "activity",
                "timestamp",
                "_source_case_id_raw",
                "_source_activity_raw",
                "_source_timestamp_raw",
                "_source_row",
                "_source_timestamp_column",
                "_source_timestamp_order",
            ]
        )
    )
    standardherkunft = {
        "case_id": konfiguration.fall_id.trennzeichen.join(konfiguration.fall_id.spalten),
        "activity": "Aktivitätsbeschreibung der jeweiligen Zeitstempelzuordnung",
        "timestamp": "jeweilige ausgewählte technische Zeitstempelspalte",
    }
    if konfiguration.konfigurationsversion >= 3:
        ressourcenherkunft = [
            f"{wert.zeitstempelspalte}: {wert.ressourcenspalte}"
            for wert in konfiguration.zeitstempelzuordnungen
            if wert.ressourcenspalte
        ]
        lifecycleherkunft = [
            f"{wert.zeitstempelspalte}: {wert.statusspalte}"
            for wert in konfiguration.zeitstempelzuordnungen
            if wert.statusspalte
        ]
        if ressourcenherkunft:
            standardherkunft["resource"] = "; ".join(ressourcenherkunft)
        if lifecycleherkunft:
            standardherkunft["lifecycle"] = "; ".join(lifecycleherkunft)
    return (
        ereignisse,
        standardherkunft,
        rollen,
        attributherkunft,
    )


def _referenzen_pruefen(daten: pd.DataFrame, konfiguration: SemantischesMapping) -> None:
    definition = konfiguration.wirksame_aktivitaetsdefinition
    referenzen = {
        *konfiguration.fall_id.spalten,
        *(definition.quellspalten if definition else ()),
        konfiguration.zeitstempelspalte,
        *(wert.zeitstempelspalte for wert in konfiguration.zeitstempelzuordnungen),
        *konfiguration.zusaetzliche_attribute,
    }
    if konfiguration.konfigurationsversion != 2:
        referenzen.update(
            {
                konfiguration.startzeitstempelspalte,
                konfiguration.endzeitstempelspalte,
                konfiguration.plan_startzeitstempelspalte,
                konfiguration.plan_endzeitstempelspalte,
                konfiguration.lifecycle_spalte,
                konfiguration.ressourcen_spalte,
                *(wert.ressourcenspalte for wert in konfiguration.zeitstempelzuordnungen),
                *(wert.statusspalte for wert in konfiguration.zeitstempelzuordnungen),
            }
        )
    fehlend = sorted(wert for wert in referenzen if wert and wert not in daten.columns)
    if fehlend:
        raise Domaenenfehler(
            "Die Event-Log-Konfiguration referenziert fehlende Spalten in T: " + ", ".join(fehlend)
        )


def _mapping_lineage(mappingtabelle: Mappingtabelle | None) -> tuple[dict[str, str], ...]:
    if mappingtabelle is None:
        return ()
    return tuple(
        {
            "mappingeintrag_id": str(eintrag.mappingeintrag_id),
            "art": eintrag.art.value,
            "technische_bezeichnung": eintrag.technische_bezeichnung,
            "fachliche_bezeichnung": eintrag.fachliche_bezeichnung,
            "technische_quellspalte": eintrag.technische_quellspalte,
            "technischer_datentyp": (
                eintrag.wertreferenz.technischer_datentyp
                if eintrag.wertreferenz is not None
                else ""
            ),
            "technischer_wert_json": (
                eintrag.wertreferenz.wert_json if eintrag.wertreferenz is not None else ""
            ),
        }
        for eintrag in mappingtabelle.eintraege
    )


def erzeuge_event_log(
    daten: pd.DataFrame,
    konfiguration: SemantischesMapping,
    zwischendatensatz_id: UUID,
    mappingtabelle: Mappingtabelle | None = None,
) -> EventLogErgebnis:
    """Erzeugt E ausschließlich aus tiefen Kopien von T und optional M."""
    if (
        konfiguration.konfigurationsversion >= 2
        and konfiguration.zwischendatensatz_id != zwischendatensatz_id
    ):
        raise Domaenenfehler("Die Event-Log-Konfiguration gehört nicht zum aktuellen T.")
    if mappingtabelle is not None and (
        mappingtabelle.zwischendatensatz_id != zwischendatensatz_id
        or mappingtabelle.projekt_id != konfiguration.projekt_id
        or (
            konfiguration.mappingtabelle_id is not None
            and mappingtabelle.mapping_id != konfiguration.mappingtabelle_id
        )
    ):
        raise Domaenenfehler(
            "Mappingtabelle M, Event-Log-Konfiguration und T passen nicht zusammen."
        )
    arbeitskopie = daten.copy(deep=True)
    _referenzen_pruefen(arbeitskopie, konfiguration)
    ereignisse, herkunft, rollen, attributherkunft = (
        _ereignisorientiert(arbeitskopie, konfiguration, mappingtabelle)
        if konfiguration.mapping_modus is MappingModus.EREIGNISORIENTIERT
        else _breit(arbeitskopie, konfiguration, mappingtabelle)
    )
    if not {"case_id", "activity", "timestamp"} <= set(ereignisse.columns):
        raise Domaenenfehler(
            "E muss Fallidentifikation, Aktivitätsbeschreibung und Zeitstempel enthalten."
        )
    ereignisse["event_id"] = [
        _event_id(
            zwischendatensatz_id,
            konfiguration.mapping_id,
            int(zeile),
            str(spalte),
        )
        for zeile, spalte in zip(
            ereignisse["_source_row"],
            ereignisse["_source_timestamp_column"],
            strict=True,
        )
    ]
    # Alter Name bleibt für Schritt 5 kompatibel; die neue Herkunftsspalte ist eindeutiger.
    ereignisse["_timestamp_raw"] = ereignisse["_source_timestamp_raw"].copy(deep=True)
    zeit = pd.to_datetime(ereignisse["timestamp"], errors="coerce", format="mixed")
    roh_vorhanden = ereignisse["_source_timestamp_raw"].map(lambda wert: not _ist_leer(wert))
    ungueltig = int((roh_vorhanden & zeit.isna()).sum())
    fehlende_ids = int(ereignisse["case_id"].map(_ist_leer).sum())
    fehlende_aktivitaeten = int(ereignisse["activity"].map(_ist_leer).sum())
    fehlende_zeit = int((~roh_vorhanden).sum())
    warnungen: list[str] = []
    for anzahl, text in (
        (fehlende_ids, "Fallidentifikationen fehlen"),
        (fehlende_aktivitaeten, "Aktivitätsbeschreibungen fehlen oder sind unvollständig"),
        (fehlende_zeit, "Zeitstempel fehlen"),
        (ungueltig, "Zeitstempel sind nicht interpretierbar"),
    ):
        if anzahl:
            warnungen.append(f"{anzahl} {text}; die Ereignisse bleiben für Schritt 5 erhalten.")
    if getattr(zeit.dt, "tz", None) is None and zeit.notna().any():
        warnungen.append(
            "Zeitstempel sind zeitzonenlos; es wurde keine Zeitzone oder UTC-Annahme ergänzt."
        )
    ereignisse["timestamp"] = zeit
    for name in (
        "start_timestamp",
        "end_timestamp",
        "plan_start_timestamp",
        "plan_end_timestamp",
    ):
        if name in ereignisse:
            ereignisse[name] = pd.to_datetime(
                ereignisse[name],
                errors="coerce",
                format="mixed" if konfiguration.konfigurationsversion >= 3 else None,
                utc=konfiguration.konfigurationsversion >= 3,
            )
    ereignisse["_case_sort"] = ereignisse["case_id"].astype("string")
    ereignisse = (
        ereignisse.sort_values(
            [
                "_case_sort",
                "timestamp",
                "_source_row",
                "_source_timestamp_order",
            ],
            kind="stable",
            na_position="last",
        )
        .drop(columns=["_case_sort"])
        .reset_index(drop=True)
    )
    gueltige_zeit = ereignisse["timestamp"].dropna()
    return EventLogErgebnis(
        ereignisse,
        len(ereignisse),
        int(ereignisse["case_id"].nunique(dropna=True)),
        int(ereignisse["activity"].nunique(dropna=True)),
        gueltige_zeit.min() if not gueltige_zeit.empty else None,
        gueltige_zeit.max() if not gueltige_zeit.empty else None,
        {**herkunft, "event_id": "stabiler SHA-256 aus T, Konfiguration und Quellbezug"},
        rollen,
        tuple(warnungen),
        attributherkunft,
        _mapping_lineage(mappingtabelle),
    )
