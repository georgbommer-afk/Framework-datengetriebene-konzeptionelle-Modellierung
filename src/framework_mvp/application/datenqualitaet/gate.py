# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""Reine Quality-Gate-Prüfung von Q, T, optional M und E gemäß Pseudocode 5."""

import hashlib
import json
from dataclasses import asdict, dataclass

import pandas as pd

from framework_mvp.application.event_log_service import EventLogKontext
from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Datenquelle,
    ErforderlicheSpaltenpruefung,
    FachlicheEntscheidung,
    Importvorgang,
    Mappingeintragsart,
    MappingModus,
    Mappingtabellenstatus,
    Mappingzustand,
    QualityGateBefund,
    QualityGateBereich,
    QualityGateErgebnis,
    QualityGateStatus,
)


@dataclass(frozen=True, slots=True)
class QualityGateKontext:
    """Vollständig integritätsgeprüfte Eingabe der reinen Gate-Prüfung."""

    event_log: EventLogKontext
    datenquellen: tuple[Datenquelle, ...]
    importe: tuple[Importvorgang, ...]
    mappingtabelle_sha256: str = ""


def _kanonisch(wert: object) -> bytes:
    return json.dumps(
        wert,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha(wert: object) -> str:
    return hashlib.sha256(_kanonisch(wert)).hexdigest()


def _beispiele(daten: pd.DataFrame, maske: pd.Series, spalten: list[str]) -> str:
    vorhandene = [wert for wert in spalten if wert in daten.columns]
    beispiele = (
        daten.loc[maske, vorhandene]
        .head(5)
        .reset_index(names="quellzeile")
        .to_dict(orient="records")
    )
    return json.dumps(beispiele, ensure_ascii=False, default=str)


def _leer(serie: pd.Series) -> tuple[pd.Series, pd.Series]:
    fehlend = serie.isna()
    text = serie.astype("string")
    leer = ~fehlend & text.str.strip().eq("").fillna(False)
    return fehlend, leer


def _betroffene_faelle(ereignisse: pd.DataFrame, maske: pd.Series) -> int:
    if "case_id" not in ereignisse:
        return 0
    return int(ereignisse.loc[maske, "case_id"].nunique(dropna=True))


def _fachlicher_befund(
    kriterium_id: str,
    bereich: QualityGateBereich,
    kriterium: str,
    meldung: str,
    ruecksprung: int,
    entscheidungen: dict[str, FachlicheEntscheidung],
    *,
    technische_quellen: tuple[str, ...] = (),
    betroffene_ereignisse: int = 0,
    beispiele_json: str = "[]",
) -> QualityGateBefund:
    entscheidung = entscheidungen.get(kriterium_id)
    if entscheidung is None:
        status = QualityGateStatus.FACHLICHE_BESTAETIGUNG_ERFORDERLICH
        begruendung = ""
        ziel = None
    elif entscheidung.ist_mangel:
        status = QualityGateStatus.FACHLICH_ALS_MANGEL_BEWERTET
        begruendung = entscheidung.begruendung
        ziel = entscheidung.ruecksprung_schritt or ruecksprung
    else:
        status = QualityGateStatus.FACHLICH_BEGRUENDET_KEIN_MANGEL
        begruendung = entscheidung.begruendung
        ziel = None
    return QualityGateBefund(
        kriterium_id,
        bereich,
        kriterium,
        status,
        meldung,
        False,
        ziel,
        betroffene_ereignisse,
        0,
        0.0,
        technische_quellen,
        beispiele_json,
        begruendung,
    )


def _automatischer_mangel(
    kriterium_id: str,
    bereich: QualityGateBereich,
    kriterium: str,
    meldung: str,
    ruecksprung: int,
    *,
    ereignisse: pd.DataFrame | None = None,
    maske: pd.Series | None = None,
    technische_quellen: tuple[str, ...] = (),
    beispiele_json: str = "[]",
) -> QualityGateBefund:
    anzahl = int(maske.sum()) if maske is not None else 0
    gesamt = len(ereignisse) if ereignisse is not None else 0
    return QualityGateBefund(
        kriterium_id,
        bereich,
        kriterium,
        QualityGateStatus.AUTOMATISCHER_MANGEL,
        meldung,
        True,
        ruecksprung,
        anzahl,
        _betroffene_faelle(ereignisse, maske)
        if ereignisse is not None and maske is not None
        else 0,
        anzahl / gesamt if gesamt else 0.0,
        technische_quellen,
        beispiele_json,
    )


def _q_pruefen(
    kontext: QualityGateKontext,
    entscheidungen: dict[str, FachlicheEntscheidung],
) -> tuple[list[QualityGateBefund], list[dict[str, object]]]:
    event = kontext.event_log
    befunde: list[QualityGateBefund] = []
    snapshots: list[dict[str, object]] = []
    verwendete_ids = {wert.datenquellen_id for wert in kontext.importe}
    verwendete_quellen = tuple(
        wert for wert in kontext.datenquellen if wert.datenquellen_id in verwendete_ids
    )
    quellen_nach_id = {wert.datenquellen_id: wert for wert in verwendete_quellen}
    if len(quellen_nach_id) != len(verwendete_quellen):
        befunde.append(
            _automatischer_mangel(
                "q_nicht_eindeutig",
                QualityGateBereich.DATENQUELLENKATALOG,
                "Herkunft und Grundlagen nachvollziehbar dokumentiert",
                "Verwendete Datenquellen lassen sich technisch nicht eindeutig unterscheiden.",
                1,
            )
        )
    for importvorgang in kontext.importe:
        quelle = quellen_nach_id.get(importvorgang.datenquellen_id)
        if quelle is None:
            befunde.append(
                _automatischer_mangel(
                    f"q_quelle_fehlt:{importvorgang.import_id}",
                    QualityGateBereich.DATENQUELLENKATALOG,
                    "Herkunft und Grundlagen nachvollziehbar dokumentiert",
                    f"Zum verwendeten Import {importvorgang.import_id} fehlt der Eintrag in Q.",
                    1,
                    technische_quellen=(str(importvorgang.import_id),),
                )
            )
            continue
        if quelle.projekt_id != event.artefakt.projekt_id or (
            importvorgang.projekt_id != event.artefakt.projekt_id
        ):
            befunde.append(
                _automatischer_mangel(
                    f"q_projektbindung:{quelle.datenquellen_id}",
                    QualityGateBereich.DATENQUELLENKATALOG,
                    "Herkunft und Grundlagen nachvollziehbar dokumentiert",
                    "Datenquelle, Import und Event Log gehören nicht zum selben Projekt.",
                    1,
                    technische_quellen=(str(quelle.datenquellen_id),),
                )
            )
        fehlende_angaben = [
            name
            for name, wert in (
                ("verwendete Tabelle/Datei/Arbeitsblatt", importvorgang.tabellenbezeichnung),
            )
            if not wert.strip()
        ]
        if fehlende_angaben:
            befunde.append(
                _automatischer_mangel(
                    f"q_angaben_fehlen:{quelle.datenquellen_id}",
                    QualityGateBereich.DATENQUELLENKATALOG,
                    "Herkunft und Grundlagen nachvollziehbar dokumentiert",
                    "Eindeutig erforderliche Herkunftsangaben fehlen: "
                    + ", ".join(fehlende_angaben),
                    1,
                    technische_quellen=(str(quelle.datenquellen_id),),
                )
            )
        snapshots.append(
            {
                "datenquelle": asdict(quelle),
                "import_id": str(importvorgang.import_id),
                "import_sha256": importvorgang.sha256,
                "originaldateiname": importvorgang.originaldateiname,
                "tabellenbezeichnung": importvorgang.tabellenbezeichnung,
            }
        )
    if not any(wert.bereich is QualityGateBereich.DATENQUELLENKATALOG for wert in befunde):
        befunde.append(
            QualityGateBefund(
                "q_technische_kette",
                QualityGateBereich.DATENQUELLENKATALOG,
                "Herkunft und Grundlagen nachvollziehbar dokumentiert",
                QualityGateStatus.AUTOMATISCH_BESTANDEN,
                "Alle verwendeten Importe sind vollständig und projektbezogen mit Q verknüpft.",
                False,
            )
        )
    befunde.append(
        _fachlicher_befund(
            "q_nachvollziehbar",
            QualityGateBereich.DATENQUELLENKATALOG,
            "Herkunft und Grundlagen nachvollziehbar dokumentiert",
            "Die anwendende Person beurteilt die Nachvollziehbarkeit der angezeigten Herkunft.",
            1,
            entscheidungen,
            technische_quellen=tuple(str(wert.datenquellen_id) for wert in verwendete_quellen),
        )
    )
    return befunde, snapshots


def _t_verwendungen(kontext: QualityGateKontext) -> dict[str, tuple[str, bool, bool]]:
    config = kontext.event_log.konfiguration
    verwendungen: dict[str, tuple[str, bool, bool]] = {}
    for spalte in config.fall_id.spalten:
        verwendungen[spalte] = ("Fallidentifikation", True, False)
    definition = config.wirksame_aktivitaetsdefinition
    if definition is not None:
        for position, spalte in enumerate(definition.quellspalten, 1):
            beschreibung = (
                "Aktivitätsbeschreibung"
                if definition.bildungsart is Aktivitaetsbildungsart.VORHANDENE_SPALTE
                else f"{position}. Bestandteil der Aktivitätsbeschreibung"
            )
            verwendungen[spalte] = (beschreibung, True, False)
    if config.mapping_modus is MappingModus.EREIGNISORIENTIERT:
        verwendungen[config.zeitstempelspalte] = ("Ereigniszeitstempel", True, True)
        if config.konfigurationsversion >= 3:
            for spalte, beschreibung, ist_zeit in (
                (config.startzeitstempelspalte, "Startzeitstempel", True),
                (config.endzeitstempelspalte, "Endzeitstempel", True),
                (config.lifecycle_spalte, "Lifecycle-/Statusangabe", False),
                (config.ressourcen_spalte, "Ressource", False),
            ):
                if spalte:
                    verwendungen[spalte] = (beschreibung, False, ist_zeit)
    else:
        for wert in config.zeitstempelzuordnungen:
            verwendungen[wert.zeitstempelspalte] = (
                f"Zeitstempel für Aktivität „{wert.aktivitaetsbezeichnung}“",
                True,
                True,
            )
            if config.konfigurationsversion >= 3:
                if wert.ressourcenspalte:
                    verwendungen[wert.ressourcenspalte] = (
                        f"Ressource für Aktivität „{wert.aktivitaetsbezeichnung}“",
                        False,
                        False,
                    )
                if wert.statusspalte:
                    verwendungen[wert.statusspalte] = (
                        f"Lifecycle für Aktivität „{wert.aktivitaetsbezeichnung}“",
                        False,
                        False,
                    )
    for spalte in config.zusaetzliche_attribute:
        verwendungen[spalte] = ("Ausgewähltes zusätzliches Attribut", False, False)
    return verwendungen


def _t_pruefen(
    kontext: QualityGateKontext,
    entscheidungen: dict[str, FachlicheEntscheidung],
) -> tuple[list[QualityGateBefund], list[ErforderlicheSpaltenpruefung]]:
    event = kontext.event_log
    daten = event.zwischendaten.copy(deep=True)
    mapping = event.mappingtabelle
    befunde: list[QualityGateBefund] = []
    pruefungen: list[ErforderlicheSpaltenpruefung] = []
    for spalte, (verwendung, minimum, ist_zeit) in _t_verwendungen(kontext).items():
        if spalte not in daten:
            befunde.append(
                _automatischer_mangel(
                    f"t_spalte_fehlt:{spalte}",
                    QualityGateBereich.ZWISCHENDATENSATZ,
                    "Erforderliche Daten vollständig vorhanden",
                    f"Die in Schritt 4 verwendete Spalte „{spalte}“ fehlt in T.",
                    2,
                    technische_quellen=(spalte,),
                )
            )
            continue
        serie = daten[spalte]
        fehlend, leer = _leer(serie)
        roh_vorhanden = ~(fehlend | leer)
        ungueltig = (
            roh_vorhanden & pd.to_datetime(serie, errors="coerce", format="mixed").isna()
            if ist_zeit
            else pd.Series(False, index=daten.index)
        )
        fachlich = mapping.fachliche_spaltenbezeichnung(spalte) if mapping else spalte
        problem = fehlend | leer | ungueltig
        pruefungen.append(
            ErforderlicheSpaltenpruefung(
                spalte,
                fachlich,
                verwendung,
                str(serie.dtype),
                int(fehlend.sum()),
                int(leer.sum()),
                int(ungueltig.sum()),
                _beispiele(daten, problem, [spalte]),
                minimum,
            )
        )
        breite_zeit = (
            event.konfiguration.mapping_modus is MappingModus.BREITER_ZEITSTEMPELDATENSATZ
            and ist_zeit
        )
        fehlanzahl = int((fehlend | leer).sum())
        if fehlanzahl and breite_zeit:
            befunde.append(
                _fachlicher_befund(
                    f"t_breiter_zeitstempel:{spalte}",
                    QualityGateBereich.ZWISCHENDATENSATZ,
                    "Erforderliche Daten vollständig vorhanden",
                    f"{fehlanzahl} leere Werte in „{spalte}“ können fachlich bedeuten, dass "
                    "die Aktivität nicht stattgefunden hat.",
                    2,
                    entscheidungen,
                    technische_quellen=(spalte,),
                    betroffene_ereignisse=fehlanzahl,
                    beispiele_json=_beispiele(daten, fehlend | leer, [spalte]),
                )
            )
        elif fehlanzahl and minimum:
            befunde.append(
                _automatischer_mangel(
                    f"t_mindestwert_fehlt:{spalte}",
                    QualityGateBereich.ZWISCHENDATENSATZ,
                    "Erforderliche Daten vollständig vorhanden",
                    f"{fehlanzahl} Werte der erforderlichen Spalte „{spalte}“ fehlen.",
                    2,
                    ereignisse=daten,
                    maske=fehlend | leer,
                    technische_quellen=(spalte,),
                    beispiele_json=_beispiele(daten, fehlend | leer, [spalte]),
                )
            )
        elif fehlanzahl:
            befunde.append(
                _fachlicher_befund(
                    f"t_zusatzattribut:{spalte}",
                    QualityGateBereich.ZWISCHENDATENSATZ,
                    "Erforderliche Daten vollständig vorhanden",
                    f"{fehlanzahl} Werte des ausgewählten Zusatzattributs „{spalte}“ fehlen.",
                    2,
                    entscheidungen,
                    technische_quellen=(spalte,),
                    betroffene_ereignisse=fehlanzahl,
                    beispiele_json=_beispiele(daten, fehlend | leer, [spalte]),
                )
            )
        if int(ungueltig.sum()):
            befunde.append(
                _automatischer_mangel(
                    f"t_zeit_uninterpretierbar:{spalte}",
                    QualityGateBereich.ZWISCHENDATENSATZ,
                    "Erforderliche Daten vollständig vorhanden",
                    f"{int(ungueltig.sum())} vorhandene Werte in „{spalte}“ sind nicht als "
                    "Zeitstempel interpretierbar.",
                    2,
                    ereignisse=daten,
                    maske=ungueltig,
                    technische_quellen=(spalte,),
                    beispiele_json=_beispiele(daten, ungueltig, [spalte]),
                )
            )
    if not any(wert.bereich is QualityGateBereich.ZWISCHENDATENSATZ for wert in befunde):
        befunde.append(
            QualityGateBefund(
                "t_vollstaendig",
                QualityGateBereich.ZWISCHENDATENSATZ,
                "Erforderliche Daten vollständig vorhanden",
                QualityGateStatus.AUTOMATISCH_BESTANDEN,
                "Alle von Schritt 4 tatsächlich benötigten Spalten und Werte sind vorhanden.",
                False,
            )
        )
    return befunde, pruefungen


def _erwartete_mapping_lineage(kontext: QualityGateKontext) -> list[dict[str, str]]:
    mapping = kontext.event_log.mappingtabelle
    if mapping is None:
        return []
    return [
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
        for eintrag in mapping.eintraege
    ]


def _m_pruefen(
    kontext: QualityGateKontext,
    entscheidungen: dict[str, FachlicheEntscheidung],
) -> tuple[list[QualityGateBefund], Mappingzustand]:
    mapping = kontext.event_log.mappingtabelle
    config = kontext.event_log.konfiguration
    lineage_mapping_id = kontext.event_log.lineage.get("mappingtabelle_id")
    angewandt = kontext.event_log.lineage.get("angewandte_fachliche_zuordnungen", [])
    if mapping is None:
        if config.mappingtabelle_id is not None or lineage_mapping_id is not None or angewandt:
            return (
                [
                    _automatischer_mangel(
                        "m_fehlende_referenz_abweichend",
                        QualityGateBereich.MAPPINGTABELLE,
                        "Technische Bezeichnungen eindeutig und fachlich verständlich zugeordnet",
                        "E dokumentiert eine Mappingverwendung, obwohl kein zugehöriges M "
                        "integritätsgeprüft geladen wurde.",
                        4,
                    )
                ],
                Mappingzustand.NICHT_VORHANDEN,
            )
        return (
            [
                QualityGateBefund(
                    "m_nicht_vorhanden",
                    QualityGateBereich.MAPPINGTABELLE,
                    "Technische Bezeichnungen eindeutig und fachlich verständlich zugeordnet",
                    QualityGateStatus.NICHT_ANWENDBAR,
                    "Kein semantisches Mapping erforderlich; Schritt 4 verwendete technische "
                    "Bezeichnungen direkt.",
                    False,
                )
            ],
            Mappingzustand.NICHT_VORHANDEN,
        )
    if mapping.kein_mapping_erforderlich:
        if (
            config.mappingtabelle_id != mapping.mapping_id
            or mapping.projekt_id != config.projekt_id
            or mapping.zwischendatensatz_id != config.zwischendatensatz_id
            or lineage_mapping_id != str(mapping.mapping_id)
            or angewandt
            or mapping.status is not Mappingtabellenstatus.BESTAETIGT
            or len(kontext.mappingtabelle_sha256) != 64
        ):
            return (
                [
                    _automatischer_mangel(
                        "m_leere_referenz_abweichend",
                        QualityGateBereich.MAPPINGTABELLE,
                        "Technische Bezeichnungen eindeutig und fachlich verständlich zugeordnet",
                        "Das ausdrücklich bestätigte leere M ist nicht vollständig und "
                        "prüfsummengesichert mit T, Konfiguration und E verknüpft.",
                        3,
                        technische_quellen=(str(mapping.mapping_id),),
                    )
                ],
                Mappingzustand.BESTAETIGT_LEER,
            )
        return (
            [
                QualityGateBefund(
                    "m_bestaetigt_leer",
                    QualityGateBereich.MAPPINGTABELLE,
                    "Technische Bezeichnungen eindeutig und fachlich verständlich zugeordnet",
                    QualityGateStatus.NICHT_ANWENDBAR,
                    "Leeres Mapping wurde in Schritt 3 ausdrücklich bestätigt und ist intakt.",
                    False,
                    technische_quellen=(str(mapping.mapping_id),),
                )
            ],
            Mappingzustand.BESTAETIGT_LEER,
        )
    befunde: list[QualityGateBefund] = []
    if (
        config.mappingtabelle_id != mapping.mapping_id
        or mapping.projekt_id != config.projekt_id
        or mapping.zwischendatensatz_id != config.zwischendatensatz_id
        or lineage_mapping_id != str(mapping.mapping_id)
        or angewandt != _erwartete_mapping_lineage(kontext)
        or mapping.status is not Mappingtabellenstatus.BESTAETIGT
        or len(kontext.mappingtabelle_sha256) != 64
    ):
        befunde.append(
            _automatischer_mangel(
                "m_lineage_abweichend",
                QualityGateBereich.MAPPINGTABELLE,
                "Technische Bezeichnungen eindeutig und fachlich verständlich zugeordnet",
                "Die in E dokumentierten Zuordnungen stimmen nicht vollständig mit M überein.",
                3,
                technische_quellen=(str(mapping.mapping_id),),
            )
        )
    referenzen = [wert.technischer_referenzschluessel for wert in mapping.eintraege]
    if len(referenzen) != len(set(referenzen)) or any(
        not wert.fachliche_bezeichnung for wert in mapping.eintraege
    ):
        befunde.append(
            _automatischer_mangel(
                "m_referenzen_ungueltig",
                QualityGateBereich.MAPPINGTABELLE,
                "Technische Bezeichnungen eindeutig und fachlich verständlich zugeordnet",
                "M enthält eine doppelte technische Referenz oder leere fachliche Bezeichnung.",
                3,
                technische_quellen=(str(mapping.mapping_id),),
            )
        )
    if any(
        wert.art is Mappingeintragsart.TECHNISCHER_WERT
        and (not wert.technische_quellspalte or wert.wertreferenz is None)
        for wert in mapping.eintraege
    ):
        befunde.append(
            _automatischer_mangel(
                "m_wertkontext_ungueltig",
                QualityGateBereich.MAPPINGTABELLE,
                "Technische Bezeichnungen eindeutig und fachlich verständlich zugeordnet",
                "Mindestens ein Wertmapping ist nicht an Quellspalte und Datentyp gebunden.",
                3,
            )
        )
    if not befunde:
        befunde.append(
            QualityGateBefund(
                "m_technisch_eindeutig",
                QualityGateBereich.MAPPINGTABELLE,
                "Technische Bezeichnungen eindeutig und fachlich verständlich zugeordnet",
                QualityGateStatus.AUTOMATISCH_BESTANDEN,
                "M ist intakt, eindeutig referenziert und stimmt mit der Anwendung in E überein.",
                False,
            )
        )
    befunde.append(
        _fachlicher_befund(
            "m_verstaendlich",
            QualityGateBereich.MAPPINGTABELLE,
            "Technische Bezeichnungen eindeutig und fachlich verständlich zugeordnet",
            "Die anwendende Person beurteilt Eindeutigkeit und fachliche Verständlichkeit von M.",
            3,
            entscheidungen,
            technische_quellen=(str(mapping.mapping_id),),
        )
    )
    return befunde, Mappingzustand.BEFUELLT


def _e_pruefen(
    kontext: QualityGateKontext,
    entscheidungen: dict[str, FachlicheEntscheidung],
) -> list[QualityGateBefund]:
    event = kontext.event_log
    daten = event.ereignisse.copy(deep=True)
    befunde: list[QualityGateBefund] = []
    if daten.empty:
        befunde.append(
            _automatischer_mangel(
                "e_leer",
                QualityGateBereich.EVENT_LOG,
                "Mindestbestandteile vollständig und interpretierbar vorhanden",
                "E enthält kein Ereignis.",
                4,
            )
        )
    fehlende_spalten = sorted({"case_id", "activity", "timestamp"} - set(daten.columns))
    for spalte in fehlende_spalten:
        befunde.append(
            _automatischer_mangel(
                f"e_spalte_fehlt:{spalte}",
                QualityGateBereich.EVENT_LOG,
                "Mindestbestandteile vollständig und interpretierbar vorhanden",
                f"Der Mindestbestandteil „{spalte}“ fehlt als eigene Spalte in E.",
                4,
                technische_quellen=(spalte,),
            )
        )
    for spalte, bezeichnung in (
        ("case_id", "Fallidentifikation"),
        ("activity", "Aktivitätsbeschreibung"),
    ):
        if spalte not in daten:
            continue
        fehlend, leer = _leer(daten[spalte])
        maske = fehlend | leer
        if int(maske.sum()):
            befunde.append(
                _automatischer_mangel(
                    f"e_wert_fehlt:{spalte}",
                    QualityGateBereich.EVENT_LOG,
                    "Mindestbestandteile vollständig und interpretierbar vorhanden",
                    f"{int(maske.sum())} Ereignisse besitzen keine {bezeichnung}.",
                    2,
                    ereignisse=daten,
                    maske=maske,
                    technische_quellen=(
                        str(event.lineage.get("herkunft_standardspalten", {}).get(spalte, spalte)),
                    ),
                    beispiele_json=_beispiele(
                        daten,
                        maske,
                        ["event_id", "case_id", "activity", "timestamp", "_source_row"],
                    ),
                )
            )
    if "timestamp" in daten:
        raw_name = (
            "_source_timestamp_raw"
            if "_source_timestamp_raw" in daten
            else "_timestamp_raw"
            if "_timestamp_raw" in daten
            else ""
        )
        raw = daten[raw_name] if raw_name else daten["timestamp"]
        raw_fehlend, raw_leer = _leer(raw)
        interpretiert = pd.to_datetime(daten["timestamp"], errors="coerce", format="mixed")
        fehlend = raw_fehlend | raw_leer
        ungueltig = ~(raw_fehlend | raw_leer) & interpretiert.isna()
        if int(fehlend.sum()):
            befunde.append(
                _automatischer_mangel(
                    "e_zeit_fehlt",
                    QualityGateBereich.EVENT_LOG,
                    "Mindestbestandteile vollständig und interpretierbar vorhanden",
                    f"{int(fehlend.sum())} Ereignisse besitzen keinen Zeitstempel.",
                    2,
                    ereignisse=daten,
                    maske=fehlend,
                    technische_quellen=(raw_name or "timestamp",),
                    beispiele_json=_beispiele(
                        daten, fehlend, ["event_id", "case_id", "activity", raw_name, "_source_row"]
                    ),
                )
            )
        if int(ungueltig.sum()):
            befunde.append(
                _automatischer_mangel(
                    "e_zeit_uninterpretierbar",
                    QualityGateBereich.EVENT_LOG,
                    "Mindestbestandteile vollständig und interpretierbar vorhanden",
                    f"{int(ungueltig.sum())} vorhandene Rohzeitstempel sind nicht interpretierbar.",
                    2,
                    ereignisse=daten,
                    maske=ungueltig,
                    technische_quellen=(raw_name or "timestamp",),
                    beispiele_json=_beispiele(
                        daten,
                        ungueltig,
                        ["event_id", "case_id", "activity", raw_name, "_source_row"],
                    ),
                )
            )
    herkunft = event.lineage.get("herkunft_standardspalten", {})
    technische_pflicht = {
        "event_id",
        "_source_row",
        "_source_case_id_raw",
        "_source_activity_raw",
        "_source_timestamp_raw",
        "_source_timestamp_column",
    }
    fehlende_herkunft = sorted(technische_pflicht - set(daten.columns))
    if (
        not isinstance(herkunft, dict)
        or not {"case_id", "activity", "timestamp"} <= set(herkunft)
        or fehlende_herkunft
    ):
        befunde.append(
            _automatischer_mangel(
                "e_herkunft_unvollstaendig",
                QualityGateBereich.EVENT_LOG,
                "Mindestbestandteile vollständig und interpretierbar vorhanden",
                "Die technische Herkunft der Mindestbestandteile ist nicht vollständig "
                "dokumentiert.",
                4,
                technische_quellen=tuple(fehlende_herkunft),
            )
        )
    if "event_id" in daten and bool(daten["event_id"].duplicated().any()):
        maske = daten["event_id"].duplicated(keep=False)
        befunde.append(
            _automatischer_mangel(
                "e_event_id_nicht_eindeutig",
                QualityGateBereich.EVENT_LOG,
                "Mindestbestandteile vollständig und interpretierbar vorhanden",
                "Die technische event_id ist nicht eindeutig.",
                4,
                ereignisse=daten,
                maske=maske,
                technische_quellen=("event_id",),
                beispiele_json=_beispiele(daten, maske, ["event_id", "_source_row"]),
            )
        )
    if not any(wert.bereich is QualityGateBereich.EVENT_LOG for wert in befunde):
        befunde.append(
            QualityGateBefund(
                "e_mindestbestandteile",
                QualityGateBereich.EVENT_LOG,
                "Mindestbestandteile vollständig und interpretierbar vorhanden",
                QualityGateStatus.AUTOMATISCH_BESTANDEN,
                "Fallidentifikation, Aktivitätsbeschreibung und Zeitstempel sind vollständig "
                "und technisch interpretierbar.",
                False,
            )
        )
    befunde.append(
        _fachlicher_befund(
            "e_interpretierbar",
            QualityGateBereich.EVENT_LOG,
            "Mindestbestandteile vollständig und interpretierbar vorhanden",
            "Die anwendende Person beurteilt die fachliche Interpretierbarkeit der drei "
            "Mindestbestandteile.",
            4,
            entscheidungen,
            technische_quellen=("case_id", "activity", "timestamp"),
        )
    )
    return befunde


def pruefe_quality_gate(
    kontext: QualityGateKontext,
    fachliche_entscheidungen: tuple[FachlicheEntscheidung, ...] = (),
) -> tuple[QualityGateErgebnis, tuple[dict[str, object], ...]]:
    """Prüft Q, T, optional M und E auf tiefen Kopien ohne Korrekturfunktionen."""
    event = kontext.event_log
    entscheidungen = {wert.kriterium_id: wert for wert in fachliche_entscheidungen}
    q_befunde, q_snapshot = _q_pruefen(kontext, entscheidungen)
    t_befunde, spaltenpruefungen = _t_pruefen(kontext, entscheidungen)
    m_befunde, mappingzustand = _m_pruefen(kontext, entscheidungen)
    e_befunde = _e_pruefen(kontext, entscheidungen)
    q_sha = _sha(q_snapshot)
    config_sha = _sha(asdict(event.konfiguration))
    kettenstruktur = {
        "projekt_id": str(event.artefakt.projekt_id),
        "datenquellen_snapshot_sha256": q_sha,
        "zwischendatensatz_id": str(event.zwischendatensatz.zwischendatensatz_id),
        "zwischendatensatz_sha256": event.zwischendatensatz.sha256,
        "mappingtabelle_id": (
            str(event.mappingtabelle.mapping_id) if event.mappingtabelle is not None else None
        ),
        "mappingtabelle_sha256": kontext.mappingtabelle_sha256,
        "mappingzustand": mappingzustand.value,
        "konfiguration_id": str(event.konfiguration.mapping_id),
        "konfiguration_sha256": config_sha,
        "event_log_id": str(event.artefakt.event_log_id),
        "event_log_sha256": event.artefakt.sha256,
    }
    ergebnis = QualityGateErgebnis(
        event.artefakt.projekt_id,
        event.artefakt.event_log_id,
        event.zwischendatensatz.zwischendatensatz_id,
        event.konfiguration.mapping_id,
        event.mappingtabelle.mapping_id if event.mappingtabelle is not None else None,
        mappingzustand,
        tuple(dict.fromkeys(wert.datenquellen_id for wert in kontext.importe)),
        json.dumps(q_snapshot, ensure_ascii=False, default=str),
        event.konfiguration.mapping_modus.value,
        event.artefakt.sha256,
        event.zwischendatensatz.sha256,
        kontext.mappingtabelle_sha256,
        config_sha,
        q_sha,
        _sha(kettenstruktur),
        len(event.ereignisse),
        int(event.ereignisse["case_id"].nunique(dropna=True))
        if "case_id" in event.ereignisse
        else 0,
        int(event.ereignisse["activity"].nunique(dropna=True))
        if "activity" in event.ereignisse
        else 0,
        event.artefakt.zeitraum_von,
        event.artefakt.zeitraum_bis,
        tuple((*q_befunde, *t_befunde, *m_befunde, *e_befunde)),
        tuple(spaltenpruefungen),
        fachliche_entscheidungen,
    )
    return ergebnis, tuple(q_snapshot)
