# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# pyright: reportCallIssue=false, reportGeneralTypeIssues=false
# pyright: reportOptionalOperand=false, reportOptionalMemberAccess=false
"""Direkte zeitbezogene Soll-Ist-Auswertung ohne fachliche Umdeutung."""

import hashlib
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID, uuid4

import pandas as pd

from framework_mvp.application.datenimport_service import DatenimportService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Dateityp,
    Sollzeitdaten,
    Vergleichsebene,
    Vorkommensregel,
    Zeitabweichung,
    ZeitvergleichErgebnis,
    ZeitvergleichKonfiguration,
)


def lese_externe_sollzeitdaten(
    *,
    projekt_id: UUID,
    dateiname: str,
    originalbytes: bytes,
    tabellenblatt: str | int | None = None,
    trennzeichen: str = ",",
    kodierung: str = "utf-8",
    sollzeitdaten_id: UUID | None = None,
) -> tuple[Sollzeitdaten, pd.DataFrame]:
    """Verwendet die sichere Uploadprüfung und hält Original und Tabelle getrennt."""
    metadaten = DatenimportService().datei_pruefen(dateiname, originalbytes)
    try:
        if metadaten.dateityp is Dateityp.CSV:
            daten = pd.read_csv(BytesIO(originalbytes), sep=trennzeichen, encoding=kodierung)
        else:
            daten = pd.read_excel(BytesIO(originalbytes), sheet_name=tabellenblatt or 0)
    except Exception as fehler:
        raise Domaenenfehler(
            f"Die Soll-Zeitdatentabelle konnte nicht gelesen werden: {fehler}"
        ) from fehler
    if not isinstance(daten, pd.DataFrame) or daten.empty:
        raise Domaenenfehler("Die Soll-Zeitdatentabelle enthält keine auswertbaren Zeilen.")
    artefakt = Sollzeitdaten(
        sollzeitdaten_id or uuid4(),
        projekt_id,
        metadaten.urspruenglicher_dateiname,
        metadaten.dateityp.value,
        originalbytes,
        hashlib.sha256(originalbytes).hexdigest(),
        datetime.now(UTC),
    )
    return artefakt, daten.copy(deep=True)


def _pruefe_spalten(daten: pd.DataFrame, spalten: tuple[str, ...], quelle: str) -> None:
    fehlend = [wert for wert in spalten if not wert or wert not in daten.columns]
    if fehlend:
        raise Domaenenfehler(
            f"In {quelle} fehlen ausdrücklich zuzuordnende Spalten: " + ", ".join(fehlend)
        )


def _zeitspalte(daten: pd.DataFrame, spalte: str) -> pd.Series:
    return pd.to_datetime(daten[spalte], errors="coerce", utc=True)


def _klassifikation(sekunden: float) -> str:
    if sekunden < 0:
        return "verfrüht"
    if sekunden > 0:
        return "verspätet"
    return "termingerecht"


def _gueltiger_schluessel(daten: pd.DataFrame, spalten: tuple[str, ...]) -> pd.Series:
    """Markiert ausschließlich vollständig gesetzte, nicht leere Zuordnungsschlüssel."""
    gueltig = pd.Series(True, index=daten.index, dtype="bool")
    for spalte in spalten:
        werte = daten[spalte]
        gueltig &= werte.notna() & werte.astype("string").str.strip().ne("")
    return gueltig


def _fallvergleich(
    soll: pd.DataFrame,
    ist: pd.DataFrame,
    konfiguration: ZeitvergleichKonfiguration,
) -> tuple[list[Zeitabweichung], dict[str, int]]:
    _pruefe_spalten(
        soll,
        (konfiguration.soll_case_id_spalte, konfiguration.soll_zeitstempel_spalte),
        "den Soll-Daten",
    )
    _pruefe_spalten(
        ist,
        (
            konfiguration.ist_case_id_spalte,
            konfiguration.ist_zeitstempel_spalte,
            konfiguration.ist_activity_spalte,
        ),
        "E*",
    )
    if not konfiguration.ausgewaehlte_ist_aktivitaet:
        raise Domaenenfehler(
            "Die fallbezogene Auswertung benötigt eine ausdrücklich gewählte Start-, "
            "End- oder Abschlussaktivität."
        )
    soll_kopie = soll.copy(deep=True)
    gueltige_sollschluessel = _gueltiger_schluessel(
        soll_kopie, (konfiguration.soll_case_id_spalte,)
    )
    nicht_zuordenbar = int((~gueltige_sollschluessel).sum())
    soll_kopie = soll_kopie.loc[gueltige_sollschluessel].copy()
    soll_kopie["_case"] = soll_kopie[konfiguration.soll_case_id_spalte].astype("string")
    if bool(soll_kopie["_case"].duplicated(keep=False).any()):
        raise Domaenenfehler(
            "Die fallbezogenen Soll-Daten enthalten mehr als einen Datensatz je Fall-ID."
        )
    ist_kopie = ist[
        ist[konfiguration.ist_activity_spalte].astype("string")
        == konfiguration.ausgewaehlte_ist_aktivitaet
    ].copy(deep=True)
    gueltige_istschluessel = _gueltiger_schluessel(ist_kopie, (konfiguration.ist_case_id_spalte,))
    nicht_zuordenbar += int((~gueltige_istschluessel).sum())
    ist_kopie = ist_kopie.loc[gueltige_istschluessel].copy()
    ist_kopie["_case"] = ist_kopie[konfiguration.ist_case_id_spalte].astype("string")
    ist_kopie["_ist"] = _zeitspalte(ist_kopie, konfiguration.ist_zeitstempel_spalte)
    ist_kopie = ist_kopie.sort_values("_ist", kind="stable")
    gruppiert = ist_kopie.groupby("_case", sort=False, dropna=False)
    ist_eindeutig = (
        gruppiert.tail(1)
        if konfiguration.vorkommensregel is Vorkommensregel.LETZTES
        else gruppiert.head(1)
    )
    soll_kopie["_soll"] = _zeitspalte(soll_kopie, konfiguration.soll_zeitstempel_spalte)
    verbunden = soll_kopie[["_case", "_soll"]].merge(
        ist_eindeutig[["_case", "_ist"]], on="_case", how="outer", indicator=True
    )
    return _werte_aus_verknuepfung(
        verbunden, Vergleichsebene.FALL, nicht_zuordenbar=nicht_zuordenbar
    )


def _ereignisvergleich(
    soll: pd.DataFrame,
    ist: pd.DataFrame,
    konfiguration: ZeitvergleichKonfiguration,
) -> tuple[list[Zeitabweichung], dict[str, int]]:
    _pruefe_spalten(
        soll,
        (
            konfiguration.soll_case_id_spalte,
            konfiguration.soll_activity_spalte,
            konfiguration.soll_zeitstempel_spalte,
        ),
        "den Soll-Daten",
    )
    _pruefe_spalten(
        ist,
        (
            konfiguration.ist_case_id_spalte,
            konfiguration.ist_activity_spalte,
            konfiguration.ist_zeitstempel_spalte,
        ),
        "E*",
    )
    soll_kopie = soll.copy(deep=True)
    ist_kopie = ist.copy(deep=True)
    gueltige_sollschluessel = _gueltiger_schluessel(
        soll_kopie,
        (konfiguration.soll_case_id_spalte, konfiguration.soll_activity_spalte),
    )
    gueltige_istschluessel = _gueltiger_schluessel(
        ist_kopie,
        (konfiguration.ist_case_id_spalte, konfiguration.ist_activity_spalte),
    )
    nicht_zuordenbar = int((~gueltige_sollschluessel).sum()) + int((~gueltige_istschluessel).sum())
    soll_kopie = soll_kopie.loc[gueltige_sollschluessel].copy()
    ist_kopie = ist_kopie.loc[gueltige_istschluessel].copy()
    for daten, case_spalte, activity_spalte in (
        (soll_kopie, konfiguration.soll_case_id_spalte, konfiguration.soll_activity_spalte),
        (ist_kopie, konfiguration.ist_case_id_spalte, konfiguration.ist_activity_spalte),
    ):
        daten["_case"] = daten[case_spalte].astype("string")
        daten["_activity"] = daten[activity_spalte].astype("string")
    schluessel = ["_case", "_activity"]
    wiederholt = bool(soll_kopie.duplicated(schluessel, keep=False).any()) or bool(
        ist_kopie.duplicated(schluessel, keep=False).any()
    )
    if wiederholt and not konfiguration.soll_auftretensnummer_spalte:
        raise Domaenenfehler(
            "Wiederholte Aktivitäten benötigen eine ausdrücklich zugeordnete Auftretensnummer."
        )
    if konfiguration.soll_auftretensnummer_spalte:
        _pruefe_spalten(
            soll,
            (konfiguration.soll_auftretensnummer_spalte,),
            "den Soll-Daten",
        )
        soll_kopie["_vorkommen"] = pd.to_numeric(
            soll_kopie[konfiguration.soll_auftretensnummer_spalte], errors="coerce"
        ).astype("Int64")
        gueltige_vorkommen = soll_kopie["_vorkommen"].notna()
        nicht_zuordenbar += int((~gueltige_vorkommen).sum())
        soll_kopie = soll_kopie.loc[gueltige_vorkommen].copy()
        ist_kopie["_vorkommen"] = ist_kopie.groupby(schluessel, sort=False).cumcount() + 1
        schluessel.append("_vorkommen")
    else:
        soll_kopie["_vorkommen"] = 1
        ist_kopie["_vorkommen"] = 1
        schluessel.append("_vorkommen")
    if bool(soll_kopie.duplicated(schluessel, keep=False).any()) or bool(
        ist_kopie.duplicated(schluessel, keep=False).any()
    ):
        raise Domaenenfehler("Die bestätigten Ereignisschlüssel sind nicht eindeutig.")
    soll_kopie["_soll"] = _zeitspalte(soll_kopie, konfiguration.soll_zeitstempel_spalte)
    ist_kopie["_ist"] = _zeitspalte(ist_kopie, konfiguration.ist_zeitstempel_spalte)
    verbunden = soll_kopie[[*schluessel, "_soll"]].merge(
        ist_kopie[[*schluessel, "_ist"]], on=schluessel, how="outer", indicator=True
    )
    return _werte_aus_verknuepfung(
        verbunden, Vergleichsebene.EREIGNIS, nicht_zuordenbar=nicht_zuordenbar
    )


def _werte_aus_verknuepfung(
    verbunden: pd.DataFrame, ebene: Vergleichsebene, *, nicht_zuordenbar: int = 0
) -> tuple[list[Zeitabweichung], dict[str, int]]:
    anzahl = {
        "eindeutig_vergleichbar": 0,
        "fehlender_sollwert": 0,
        "fehlender_istwert": 0,
        "nicht_eindeutig_zuordenbar": nicht_zuordenbar,
        "verfrüht": 0,
        "termingerecht": 0,
        "verspätet": 0,
    }
    ergebnisse: list[Zeitabweichung] = []
    for _, zeile in verbunden.iterrows():
        soll = zeile.get("_soll")
        ist = zeile.get("_ist")
        if zeile["_merge"] == "right_only" or pd.isna(soll):
            anzahl["fehlender_sollwert"] += 1
            continue
        if zeile["_merge"] == "left_only" or pd.isna(ist):
            anzahl["fehlender_istwert"] += 1
            continue
        sekunden = float((ist - soll).total_seconds())
        klasse = _klassifikation(sekunden)
        anzahl["eindeutig_vergleichbar"] += 1
        anzahl[klasse] += 1
        ergebnisse.append(
            Zeitabweichung(
                ebene,
                str(zeile["_case"]),
                str(zeile.get("_activity", "")),
                int(zeile["_vorkommen"]) if "_vorkommen" in zeile else None,
                soll.isoformat(),
                ist.isoformat(),
                sekunden,
                klasse,
            )
        )
    return ergebnisse, anzahl


def zeitvergleich_berechnen(
    *,
    soll_daten: pd.DataFrame,
    event_log: pd.DataFrame,
    konfiguration: ZeitvergleichKonfiguration,
    auswertungs_id: UUID | None = None,
) -> ZeitvergleichErgebnis:
    """Berechnet ausschließlich direktes Ist minus Soll auf bestätigten Rollen."""
    soll_original = soll_daten.copy(deep=True)
    ist_original = event_log.copy(deep=True)
    if konfiguration.ebene is Vergleichsebene.FALL:
        abweichungen, anzahl = _fallvergleich(soll_daten, event_log, konfiguration)
    else:
        abweichungen, anzahl = _ereignisvergleich(soll_daten, event_log, konfiguration)
    pd.testing.assert_frame_equal(soll_daten, soll_original, check_dtype=True)
    pd.testing.assert_frame_equal(event_log, ist_original, check_dtype=True)
    return ZeitvergleichErgebnis(
        auswertungs_id or uuid4(),
        konfiguration,
        tuple(abweichungen),
        anzahl,
        anzahl["fehlender_sollwert"],
        anzahl["fehlender_istwert"],
        0,
        anzahl["nicht_eindeutig_zuordenbar"],
        datetime.now(UTC),
    )
