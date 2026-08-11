# pyright: reportArgumentType=false, reportGeneralTypeIssues=false
"""Eigenständiges P_Soll, Aktivitätsmapping und Token-Based Replay."""

import hashlib
import tempfile
import warnings
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

import pandas as pd
import pm4py
from pm4py.objects.petri_net.obj import Marking, PetriNet
from pm4py.objects.petri_net.utils import petri_utils

from framework_mvp.application.process_mining.pm4py_adapter import Pm4pyAdapter
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Aktivitaetsmapping,
    ConformanceErgebnis,
    SollmodellErstellungsart,
    SollmodellMetadaten,
    SollmodellVorschau,
    TokenDiagnose,
)

MAX_PNML_BYTES = 10 * 1024 * 1024


def _pnml_sicherheitspruefung(dateiname: str, inhalt: bytes) -> None:
    if PurePosixPath(dateiname.replace("\\", "/")).suffix.lower() != ".pnml":
        raise Domaenenfehler("Das Sollprozessmodell muss eine PNML-Datei sein.")
    if not inhalt:
        raise Domaenenfehler("Die PNML-Datei ist leer.")
    if len(inhalt) > MAX_PNML_BYTES:
        raise Domaenenfehler("Die PNML-Datei überschreitet die maximalen 10 MB.")
    gross = inhalt[: min(len(inhalt), 1_000_000)].upper()
    if b"<!DOCTYPE" in gross or b"<!ENTITY" in gross:
        raise Domaenenfehler(
            "PNML mit Dokumenttyp- oder Entitätsdeklarationen wird aus "
            "Sicherheitsgründen abgewiesen."
        )
    try:
        wurzel = ET.fromstring(inhalt)
    except ET.ParseError as fehler:
        raise Domaenenfehler("Die PNML-Datei enthält kein gültiges XML.") from fehler
    if wurzel.tag.rsplit("}", 1)[-1].lower() != "pnml":
        raise Domaenenfehler("Das XML-Wurzelelement ist kein PNML-Element.")


def _pnml_schreiben(
    netz: PetriNet, anfang: Marking, ende: Marking, dateiname: str = "sollmodell.pnml"
) -> bytes:
    with tempfile.TemporaryDirectory(prefix="framework-sollmodell-") as verzeichnis:
        pfad = Path(verzeichnis) / dateiname
        pm4py.write_pnml(netz, anfang, ende, str(pfad))
        wurzel = ET.fromstring(pfad.read_bytes())
        kanten = sorted(
            (element for element in wurzel.iter() if element.tag.rsplit("}", 1)[-1] == "arc"),
            key=lambda element: (
                element.attrib.get("source", ""),
                element.attrib.get("target", ""),
            ),
        )
        for index, kante in enumerate(kanten):
            kante.set("id", f"arc_{index}")
        rang = {"name": 0, "place": 1, "transition": 2, "arc": 3}
        for element in wurzel.iter():
            if element.tag.rsplit("}", 1)[-1] != "page":
                if element.text is not None and not element.text.strip():
                    element.text = None
                if element.tail is not None and not element.tail.strip():
                    element.tail = None
            else:
                element[:] = sorted(
                    element,
                    key=lambda kind: (
                        rang.get(kind.tag.rsplit("}", 1)[-1], 9),
                        kind.attrib.get("id", ""),
                        kind.attrib.get("source", ""),
                        kind.attrib.get("target", ""),
                    ),
                )
                if element.text is not None and not element.text.strip():
                    element.text = None
                if element.tail is not None and not element.tail.strip():
                    element.tail = None
        return ET.tostring(wurzel, encoding="utf-8", xml_declaration=True)


def _pnml_einlesen(inhalt: bytes) -> tuple[PetriNet, Marking, Marking]:
    with tempfile.TemporaryDirectory(prefix="framework-sollmodell-") as verzeichnis:
        pfad = Path(verzeichnis) / "sollmodell.pnml"
        pfad.write_bytes(inhalt)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return pm4py.read_pnml(str(pfad), auto_guess_final_marking=False)
        except Exception as fehler:
            raise Domaenenfehler(
                "Das Petrinetz konnte über die öffentliche PM4Py-Schnittstelle nicht "
                f"eingelesen werden: {fehler}"
            ) from fehler


def _netz_validieren(
    netz: PetriNet,
    anfang: Marking,
    ende: Marking,
    *,
    ableitung_bestaetigt: bool,
) -> tuple[Marking, Marking, str, str, bool, tuple[str, ...]]:
    if not netz.places or not netz.transitions:
        raise Domaenenfehler("Das Sollmodell benötigt Stellen und Transitionen.")
    sichtbare = [transition for transition in netz.transitions if transition.label is not None]
    if not sichtbare:
        raise Domaenenfehler("Das Sollmodell benötigt mindestens eine sichtbare Transition.")
    labels = [str(transition.label).strip() for transition in sichtbare]
    if any(not label for label in labels):
        raise Domaenenfehler("Sichtbare Transitionen dürfen keine leere Bezeichnung besitzen.")
    if len(labels) != len(set(labels)):
        raise Domaenenfehler(
            "Sichtbare Transitionsbezeichnungen müssen für die Aktivitätszuordnung eindeutig sein."
        )
    knoten = set(netz.places) | set(netz.transitions)
    for kante in netz.arcs:
        if kante.source not in knoten or kante.target not in knoten:
            raise Domaenenfehler("Das Sollmodell enthält eine inkonsistente Kantenreferenz.")
        if isinstance(kante.source, type(kante.target)):
            raise Domaenenfehler(
                "Petrinetzkanten müssen Stellen und Transitionen abwechselnd verbinden."
            )
    quellen = [platz for platz in netz.places if not platz.in_arcs]
    senken = [platz for platz in netz.places if not platz.out_arcs]
    if len(quellen) != 1 or len(senken) != 1:
        raise Domaenenfehler(
            "Das Workflow-Netz benötigt genau einen strukturell eindeutigen Start- und Endplatz."
        )
    startplatz, endplatz = quellen[0], senken[0]
    abgeleitet = False
    warnungen: list[str] = []
    if not anfang or not ende:
        if not ableitung_bestaetigt:
            raise Domaenenfehler(
                "Anfangs- oder Endmarkierung fehlt. Die eindeutige strukturelle "
                "Ableitung muss menschlich bestätigt werden."
            )
        if not anfang:
            anfang = Marking({startplatz: 1})
        if not ende:
            ende = Marking({endplatz: 1})
        abgeleitet = True
        warnungen.append(
            "Anfangs- und/oder Endmarkierung wurden nach menschlicher Bestätigung "
            "aus dem eindeutigen Quell- und Senkenplatz abgeleitet."
        )
    if set(anfang) != {startplatz} or anfang[startplatz] != 1:
        raise Domaenenfehler(
            "Die Anfangsmarkierung muss genau ein Token im eindeutigen Startplatz besitzen."
        )
    if set(ende) != {endplatz} or ende[endplatz] != 1:
        raise Domaenenfehler(
            "Die Endmarkierung muss genau ein Token im eindeutigen Endplatz besitzen."
        )
    if not pm4py.check_is_workflow_net(netz):
        raise Domaenenfehler("Das importierte Petrinetz ist kein geeignetes Workflow-Netz.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sound, _ = pm4py.check_soundness(netz, anfang, ende)
    except Exception as fehler:
        raise Domaenenfehler(
            f"Die Soundness-Prüfung konnte nicht durchgeführt werden: {fehler}"
        ) from fehler
    if not sound:
        raise Domaenenfehler(
            "Das Sollprozessmodell ist nicht sound und wird für Replay abgewiesen."
        )
    return anfang, ende, str(startplatz.name), str(endplatz.name), abgeleitet, tuple(warnungen)


def _metadaten(
    *,
    sollmodell_id: UUID,
    projekt_id: UUID,
    bezeichnung: str,
    erstellungsart: SollmodellErstellungsart,
    fachliche_grundlage: str,
    modellversion: str,
    person: str,
    freigabedatum: date,
    original: bytes,
    menschlich_bestaetigt: bool,
) -> SollmodellMetadaten:
    return SollmodellMetadaten(
        sollmodell_id,
        projekt_id,
        bezeichnung,
        erstellungsart,
        fachliche_grundlage,
        modellversion,
        person,
        freigabedatum,
        datetime.now(UTC),
        hashlib.sha256(original).hexdigest(),
        menschlich_bestaetigt,
    )


def erzeuge_lineares_sollmodell(
    *,
    projekt_id: UUID,
    aktivitaeten: Iterable[str],
    bezeichnung: str,
    fachliche_grundlage: str,
    modellversion: str,
    person: str,
    freigabedatum: date,
    menschlich_bestaetigt: bool,
    sollmodell_id: UUID | None = None,
) -> SollmodellVorschau:
    """Erzeugt ausschließlich eine bestätigte lineare Sequenz als Workflow-Petrinetz."""
    reihenfolge = tuple(str(wert).strip() for wert in aktivitaeten)
    if not reihenfolge or any(not wert for wert in reihenfolge):
        raise Domaenenfehler(
            "Der lineare Sollprozess benötigt mindestens eine nicht leere Aktivität."
        )
    if len(reihenfolge) != len(set(reihenfolge)):
        raise Domaenenfehler("Aktivitäten dürfen im linearen Assistenten nicht wiederholt werden.")
    if not menschlich_bestaetigt:
        raise Domaenenfehler(
            "Die fachliche Sollreihenfolge muss vor der Erzeugung bestätigt werden."
        )
    netz = PetriNet("linearer_sollprozess")
    plaetze = [PetriNet.Place(f"p_{index}") for index in range(len(reihenfolge) + 1)]
    netz.places.update(plaetze)
    for index, label in enumerate(reihenfolge):
        transition = PetriNet.Transition(f"t_{index}", label)
        netz.transitions.add(transition)
        petri_utils.add_arc_from_to(plaetze[index], transition, netz)
        petri_utils.add_arc_from_to(transition, plaetze[index + 1], netz)
    anfang, ende = Marking({plaetze[0]: 1}), Marking({plaetze[-1]: 1})
    original = _pnml_schreiben(netz, anfang, ende)
    metadaten = _metadaten(
        sollmodell_id=sollmodell_id or uuid4(),
        projekt_id=projekt_id,
        bezeichnung=bezeichnung,
        erstellungsart=SollmodellErstellungsart.LINEARER_ASSISTENT,
        fachliche_grundlage=fachliche_grundlage,
        modellversion=modellversion,
        person=person,
        freigabedatum=freigabedatum,
        original=original,
        menschlich_bestaetigt=menschlich_bestaetigt,
    )
    return SollmodellVorschau(
        metadaten,
        original,
        original,
        hashlib.sha256(original).hexdigest(),
        reihenfolge,
        str(plaetze[0].name),
        str(plaetze[-1].name),
        False,
        True,
        True,
        True,
    )


def validiere_pnml_sollmodell(
    *,
    projekt_id: UUID,
    dateiname: str,
    originalbytes: bytes,
    bezeichnung: str,
    fachliche_grundlage: str,
    modellversion: str,
    person: str,
    freigabedatum: date,
    menschlich_bestaetigt: bool,
    markierungsableitung_bestaetigt: bool,
    sollmodell_id: UUID | None = None,
) -> SollmodellVorschau:
    """Importiert PNML sicher, bewahrt das Original und normalisiert nur für Replay."""
    _pnml_sicherheitspruefung(dateiname, originalbytes)
    netz, anfang, ende = _pnml_einlesen(originalbytes)
    anfang, ende, start, end, abgeleitet, warnungen = _netz_validieren(
        netz,
        anfang,
        ende,
        ableitung_bestaetigt=markierungsableitung_bestaetigt,
    )
    normalisiert = _pnml_schreiben(netz, anfang, ende, "replay.pnml")
    metadaten = _metadaten(
        sollmodell_id=sollmodell_id or uuid4(),
        projekt_id=projekt_id,
        bezeichnung=bezeichnung,
        erstellungsart=SollmodellErstellungsart.PNML_UPLOAD,
        fachliche_grundlage=fachliche_grundlage,
        modellversion=modellversion,
        person=person,
        freigabedatum=freigabedatum,
        original=originalbytes,
        menschlich_bestaetigt=menschlich_bestaetigt,
    )
    labels = tuple(sorted(str(t.label).strip() for t in netz.transitions if t.label is not None))
    return SollmodellVorschau(
        metadaten,
        originalbytes,
        normalisiert,
        hashlib.sha256(normalisiert).hexdigest(),
        labels,
        start,
        end,
        abgeleitet,
        markierungsableitung_bestaetigt,
        True,
        True,
        warnungen,
    )


def aktivitaetsreferenz_csv(event_log: pd.DataFrame) -> bytes:
    """Erzeugt nur eine Benennungsreferenz aus dem unveränderten E*."""
    if "activity" not in event_log:
        raise Domaenenfehler("E* enthält keine kanonische Aktivitätsspalte.")
    haeufigkeiten = event_log["activity"].astype("string").value_counts(dropna=False).sort_index()
    return (
        haeufigkeiten.rename_axis("aktivitaetsbezeichnung")
        .rename("absolute_haeufigkeit")
        .to_csv()
        .encode("utf-8")
    )


def erstelle_aktivitaetsmapping(
    *,
    projekt_id: UUID,
    sollmodell_id: UUID,
    event_aktivitaeten: Iterable[str],
    modell_transitionen: Iterable[str],
    manuelle_zuordnungen: dict[str, str],
    menschlich_bestaetigt: bool,
    mapping_id: UUID | None = None,
) -> Aktivitaetsmapping:
    """Verwendet ausschließlich exakte Treffer und ausdrücklich eingegebene Zuordnungen."""
    events = tuple(sorted(set(str(wert) for wert in event_aktivitaeten)))
    modelle = tuple(sorted(set(str(wert) for wert in modell_transitionen)))
    exakt = tuple((wert, wert) for wert in events if wert in modelle)
    event_offen = set(events) - {links for links, _ in exakt}
    modell_offen = set(modelle) - {rechts for _, rechts in exakt}
    manuell = tuple(
        sorted((str(links), str(rechts)) for links, rechts in manuelle_zuordnungen.items())
    )
    if any(links not in event_offen or rechts not in modell_offen for links, rechts in manuell):
        raise Domaenenfehler(
            "Manuelle Aktivitätszuordnungen müssen tatsächlich vorhandene, nicht "
            "exakt übereinstimmende Bezeichnungen verbinden."
        )
    ziele = [rechts for _, rechts in (*exakt, *manuell)]
    if len(ziele) != len(set(ziele)):
        raise Domaenenfehler(
            "Jede sichtbare Solltransition darf höchstens einer Log-Aktivität zugeordnet werden."
        )
    zugeordnet_events = {links for links, _ in (*exakt, *manuell)}
    zugeordnet_modelle = {rechts for _, rechts in (*exakt, *manuell)}
    return Aktivitaetsmapping(
        mapping_id or uuid4(),
        projekt_id,
        sollmodell_id,
        exakt,
        manuell,
        tuple(sorted(set(events) - zugeordnet_events)),
        tuple(sorted(set(modelle) - zugeordnet_modelle)),
        menschlich_bestaetigt,
    )


def fitness_gleichung_3_13(
    *,
    produzierte_tokens: int,
    konsumierte_tokens: int,
    fehlende_tokens: int,
    verbleibende_tokens: int,
) -> float | None:
    """Berechnet Gleichung 3.13 exakt mit aggregierten Tokenmengen."""
    if konsumierte_tokens == 0 or produzierte_tokens == 0:
        return None
    return 0.5 * (1 - fehlende_tokens / konsumierte_tokens) + 0.5 * (
        1 - verbleibende_tokens / produzierte_tokens
    )


def token_replay(
    *,
    event_log: pd.DataFrame,
    sollmodell: SollmodellVorschau,
    mapping: Aktivitaetsmapping,
    conformance_id: UUID | None = None,
) -> ConformanceErgebnis:
    """Spielt das vollständige E* unverfälscht gegen das bestätigte P_Soll ab."""
    if not sollmodell.metadaten.menschlich_bestaetigt or not mapping.menschlich_bestaetigt:
        raise Domaenenfehler("Sollmodell und Aktivitätsmapping müssen menschlich bestätigt sein.")
    if mapping.sollmodell_id != sollmodell.metadaten.sollmodell_id:
        raise Domaenenfehler("Aktivitätsmapping und Sollmodell gehören nicht zusammen.")
    if mapping.nur_event_log:
        raise Domaenenfehler(
            "Nicht zugeordnete Event-Log-Aktivitäten blockieren das Replay: "
            + ", ".join(mapping.nur_event_log)
        )
    original = event_log.copy(deep=True)
    replay_kopie = event_log.copy(deep=True)
    umbenennung = dict((*mapping.exakte_zuordnungen, *mapping.manuelle_zuordnungen))
    replay_kopie["activity"] = replay_kopie["activity"].astype("string").map(umbenennung)
    if replay_kopie["activity"].isna().any():
        raise Domaenenfehler(
            "Mindestens eine Aktivität ist für das Replay nicht eindeutig zugeordnet."
        )
    netz, anfang, ende = _pnml_einlesen(sollmodell.replay_pnml)
    log = Pm4pyAdapter().arbeitskopie(replay_kopie)
    diagnose_roh = pm4py.conformance_diagnostics_token_based_replay(log, netz, anfang, ende)
    fall_ids = tuple(replay_kopie["case_id"].astype("string").drop_duplicates())
    if len(diagnose_roh) != len(fall_ids):
        raise Domaenenfehler("PM4Py lieferte keine eindeutige Token-Diagnose für jeden Fall.")
    diagnosen = tuple(
        TokenDiagnose(
            str(fall_id),
            int(wert["produced_tokens"]),
            int(wert["consumed_tokens"]),
            int(wert["missing_tokens"]),
            int(wert["remaining_tokens"]),
            bool(wert["trace_is_fit"]),
        )
        for fall_id, wert in zip(fall_ids, diagnose_roh, strict=True)
    )
    p_t = sum(wert.produzierte_tokens for wert in diagnosen)
    c_t = sum(wert.konsumierte_tokens for wert in diagnosen)
    m_t = sum(wert.fehlende_tokens for wert in diagnosen)
    r_t = sum(wert.verbleibende_tokens for wert in diagnosen)
    fitness = fitness_gleichung_3_13(
        produzierte_tokens=p_t,
        konsumierte_tokens=c_t,
        fehlende_tokens=m_t,
        verbleibende_tokens=r_t,
    )
    pm4py_fitness = pm4py.fitness_token_based_replay(log, netz, anfang, ende).get("log_fitness")
    pd.testing.assert_frame_equal(event_log, original, check_dtype=True)
    return ConformanceErgebnis(
        conformance_id or uuid4(),
        mapping.mapping_id,
        diagnosen,
        p_t,
        c_t,
        m_t,
        r_t,
        sum(wert.konform for wert in diagnosen),
        sum(not wert.konform for wert in diagnosen),
        fitness,
        float(pm4py_fitness) if pm4py_fitness is not None else None,
        (),
        version("pm4py"),
        datetime.now(UTC),
    )
