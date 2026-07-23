"""Deterministische Grundauswertung und Filterung kanonischer Event Logs."""

import json
from dataclasses import dataclass
from typing import cast

import pandas as pd

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    DfgErgebnis,
    DfgKante,
    ProcessMiningFilter,
    ProcessMiningFiltertyp,
    ProzessVariante,
    VariantenErgebnis,
)


def _geordnet(daten: pd.DataFrame) -> pd.DataFrame:
    erforderlich = {"case_id", "activity", "timestamp"}
    fehlend = erforderlich - set(daten)
    if fehlend:
        raise Domaenenfehler("Dem Event Log fehlen Pflichtspalten: " + ", ".join(sorted(fehlend)))
    kopie = daten.copy(deep=True)
    if kopie.empty:
        raise Domaenenfehler("Der Event Log enthält keine Ereignisse.")
    for spalte in ("case_id", "activity"):
        leer = kopie[spalte].isna() | kopie[spalte].astype("string").str.strip().eq("")
        if leer.any():
            raise Domaenenfehler(f"Die Pflichtspalte {spalte} enthält leere Werte.")
    zeit = pd.to_datetime(kopie["timestamp"], errors="coerce", utc=True)
    if zeit.isna().any():
        raise Domaenenfehler("Die Pflichtspalte timestamp enthält ungültige Zeitwerte.")
    kopie["timestamp"] = zeit
    kopie["_pm_reihenfolge"] = range(len(kopie))
    return kopie.sort_values(
        ["case_id", "timestamp", "_pm_reihenfolge"], kind="stable"
    ).reset_index(drop=True)


def berechne_varianten(daten: pd.DataFrame) -> VariantenErgebnis:
    """Berechnet alle Häufigkeiten auf dem vollständigen übergebenen Log."""
    geordnet = _geordnet(daten)
    spuren = geordnet.groupby("case_id", sort=False)["activity"].agg(tuple)
    zaehler = spuren.value_counts(sort=False).to_dict()
    sortiert = sorted(zaehler.items(), key=lambda wert: (-wert[1], wert[0]))
    fallanzahl = int(spuren.size)
    kumuliert = 0.0
    varianten: list[ProzessVariante] = []
    for rang, (folge, anzahl) in enumerate(sortiert, 1):
        anteil = int(anzahl) / fallanzahl
        kumuliert += anteil
        varianten.append(
            ProzessVariante(
                rang, tuple(str(wert) for wert in folge), int(anzahl), anteil, kumuliert
            )
        )
    fallgroessen = [len(gruppe) for _, gruppe in geordnet.groupby("case_id")]

    def haeufigkeiten(serie: pd.Series) -> tuple[tuple[str, int], ...]:
        werte = serie.astype(str).value_counts()
        return tuple(
            sorted(((str(name), int(anzahl)) for name, anzahl in werte.items()), key=lambda x: x[0])
        )

    return VariantenErgebnis(
        len(geordnet),
        fallanzahl,
        len(set(cast("pd.Series", geordnet["activity"]).astype(str))),
        len(varianten),
        sum(fallgroessen) / len(fallgroessen),
        min(fallgroessen),
        max(fallgroessen),
        haeufigkeiten(cast("pd.Series", geordnet["activity"])),
        haeufigkeiten(
            cast("pd.Series", geordnet.groupby("case_id", sort=False).head(1)["activity"])
        ),
        haeufigkeiten(
            cast("pd.Series", geordnet.groupby("case_id", sort=False).tail(1)["activity"])
        ),
        tuple(varianten),
    )


def berechne_dfg(daten: pd.DataFrame) -> DfgErgebnis:
    """Erzeugt einen frequenzbasierten Directly-Follows-Graph."""
    geordnet = _geordnet(daten)
    paare: dict[tuple[str, str], int] = {}
    for _, gruppe in geordnet.groupby("case_id", sort=False):
        aktivitaeten = gruppe["activity"].astype(str).tolist()
        for quelle, ziel in zip(aktivitaeten, aktivitaeten[1:], strict=False):
            paare[(quelle, ziel)] = paare.get((quelle, ziel), 0) + 1
    gesamt = sum(paare.values())
    kanten = tuple(
        DfgKante(quelle, ziel, anzahl, anzahl / gesamt if gesamt else 0.0)
        for (quelle, ziel), anzahl in sorted(paare.items())
    )
    basis = berechne_varianten(geordnet)
    return DfgErgebnis(
        tuple(sorted(geordnet["activity"].astype(str).unique())),
        basis.aktivitaetshaeufigkeiten,
        kanten,
        basis.startaktivitaeten,
        basis.endaktivitaeten,
    )


@dataclass(frozen=True, slots=True)
class AnalysesichtErgebnis:
    """Gefilterte Arbeitskopie mit dokumentierter Wirkung."""

    daten: pd.DataFrame
    vorher: VariantenErgebnis
    nachher: VariantenErgebnis
    fallabdeckung: float
    ausgeschlossene_varianten: int


def filtere_analysesicht(
    daten: pd.DataFrame, filter: tuple[ProcessMiningFilter, ...]
) -> AnalysesichtErgebnis:
    """Wendet Varianten- und Aktivitätsfilter nur auf eine tiefe Kopie an."""
    original = _geordnet(daten)
    vorher = berechne_varianten(original)
    arbeitskopie = original.copy(deep=True)
    erlaubte_faelle = set(arbeitskopie["case_id"].astype(str))
    for entscheidung in filter:
        parameter = json.loads(entscheidung.parameter_json)
        if entscheidung.filtertyp is ProcessMiningFiltertyp.VARIANTEN_TOP_K:
            k = int(parameter["k"])
            if not 1 <= k <= vorher.variantenanzahl:
                raise Domaenenfehler("Top-k muss zwischen eins und der Variantenanzahl liegen.")
            folgen = {wert.aktivitaetsfolge for wert in vorher.varianten[:k]}
            spuren = arbeitskopie.groupby("case_id", sort=False)["activity"].agg(tuple)
            erlaubte_faelle &= {str(fall) for fall, folge in spuren.items() if folge in folgen}
        elif entscheidung.filtertyp is ProcessMiningFiltertyp.VARIANTEN_ABDECKUNG:
            abdeckung = float(parameter["abdeckung"])
            if not 0.0 < abdeckung <= 1.0:
                raise Domaenenfehler(
                    "Die Variantenabdeckung muss größer null und höchstens eins sein."
                )
            folgen: set[tuple[str, ...]] = set()
            for variante in vorher.varianten:
                folgen.add(variante.aktivitaetsfolge)
                if variante.kumulierter_anteil >= abdeckung:
                    break
            spuren = arbeitskopie.groupby("case_id", sort=False)["activity"].agg(tuple)
            erlaubte_faelle &= {str(fall) for fall, folge in spuren.items() if folge in folgen}
        elif entscheidung.filtertyp is ProcessMiningFiltertyp.AKTIVITAETEN:
            aktivitaeten = {str(wert) for wert in parameter["aktivitaeten"]}
            aktivitaetsmaske = (
                cast("pd.Series", arbeitskopie["activity"]).astype(str).isin(list(aktivitaeten))
            )
            arbeitskopie = cast("pd.DataFrame", arbeitskopie.loc[aktivitaetsmaske]).copy()
    fallmaske = cast("pd.Series", arbeitskopie["case_id"]).astype(str).isin(list(erlaubte_faelle))
    arbeitskopie = cast("pd.DataFrame", arbeitskopie.loc[fallmaske]).copy()
    if arbeitskopie.empty or arbeitskopie["case_id"].nunique() == 0:
        raise Domaenenfehler("Nach der Filterung verbleiben keine analysierbaren Fälle.")
    nachher = berechne_varianten(arbeitskopie)
    return AnalysesichtErgebnis(
        arbeitskopie.drop(columns=["_pm_reihenfolge"], errors="ignore"),
        vorher,
        nachher,
        nachher.fallanzahl / vorher.fallanzahl,
        vorher.variantenanzahl - nachher.variantenanzahl,
    )


def filtere_dfg_darstellung(
    dfg: DfgErgebnis, *, mindesthaeufigkeit: int = 0, mindestanteil: float = 0.0
) -> DfgErgebnis:
    """Reduziert nur dargestellte Kanten und lässt Analysedaten unberührt."""
    kanten = tuple(
        wert
        for wert in dfg.kanten
        if wert.haeufigkeit >= mindesthaeufigkeit and wert.anteil >= mindestanteil
    )
    return DfgErgebnis(
        dfg.aktivitaeten,
        dfg.aktivitaetshaeufigkeiten,
        kanten,
        dfg.startaktivitaeten,
        dfg.endaktivitaeten,
    )
