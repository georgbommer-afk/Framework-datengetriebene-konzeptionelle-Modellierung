"""Zentrale Kataloge für Zielgrößen und KPI-Kandidaten."""

from dataclasses import dataclass

from framework_mvp.domain.models.projekt import LogistischeZielgroesse


@dataclass(frozen=True, slots=True)
class ZielgruppenEintrag:
    """Darstellung einer Zielgruppe mit ihren auswählbaren Zielgrößen."""

    titel: str
    beschreibung: str
    zielgroessen: tuple[LogistischeZielgroesse, ...]


@dataclass(frozen=True, slots=True)
class KpiKandidat:
    """Ein aus Zielgrößen ableitbarer KPI-Kandidat."""

    kpi_id: str
    bezeichnung: str
    beschreibung: str
    voraussetzungen: str


ZIELGROESSEN_BEZEICHNUNGEN: dict[LogistischeZielgroesse, str] = {
    ziel: text
    for ziel, text in zip(
        LogistischeZielgroesse,
        (
            "Lieferfähigkeit erhöhen",
            "Lieferbereitschaft erhöhen",
            "Liefertreue erhöhen",
            "Lieferzeit reduzieren",
            "Durchlaufzeit reduzieren",
            "Wartezeit reduzieren",
            "Transportzeit reduzieren",
            "Reaktionszeit reduzieren",
            "Prozessvariabilität reduzieren",
            "Prozesssicherheit erhöhen",
            "Qualität erhöhen",
            "Nacharbeit reduzieren",
            "Ressourcenauslastung erhöhen",
            "Rüstzeit reduzieren",
            "Umlauf- und Lagerbestände reduzieren",
            "Prozess- und Transportkosten reduzieren",
        ),
        strict=True,
    )
}

ZIELGRUPPEN = (
    ZielgruppenEintrag(
        "Lieferleistung steigern",
        "Zuverlässige Versorgung und Termine.",
        tuple(LogistischeZielgroesse)[:3],
    ),
    ZielgruppenEintrag(
        "Zeiten verbessern",
        "Zeitliche Reaktions- und Prozessleistung.",
        tuple(LogistischeZielgroesse)[3:8],
    ),
    ZielgruppenEintrag(
        "Prozessstabilität und Zuverlässigkeit erhöhen",
        "Stabile und qualitätsgerechte Abläufe.",
        tuple(LogistischeZielgroesse)[8:12],
    ),
    ZielgruppenEintrag(
        "Ressourcennutzung erhöhen",
        "Bestände, Kosten und Kapazitäten verbessern.",
        tuple(LogistischeZielgroesse)[12:],
    ),
)

_KPI_DATEN: dict[LogistischeZielgroesse, tuple[tuple[str, str], ...]] = {
    LogistischeZielgroesse.LIEFERFAEHIGKEIT: (
        ("lieferfaehigkeitsquote", "Lieferfähigkeitsquote"),
        ("erfuellungsquote", "Erfüllungsquote"),
    ),
    LogistischeZielgroesse.LIEFERBEREITSCHAFT: (
        ("lieferbereitschaftsgrad", "Lieferbereitschaftsgrad"),
        ("materialverfuegbarkeit", "Materialverfügbarkeit"),
    ),
    LogistischeZielgroesse.LIEFERTREUE: (
        ("termintreue", "Termintreue"),
        ("terminabweichung", "Terminabweichung"),
    ),
    LogistischeZielgroesse.LIEFERZEIT: (("lieferzeit", "Lieferzeit"),),
    LogistischeZielgroesse.DURCHLAUFZEIT: (
        ("gesamtdurchlaufzeit", "Gesamtdurchlaufzeit"),
        ("durchlaufzeit_variante", "Durchlaufzeit je Prozessvariante"),
    ),
    LogistischeZielgroesse.WARTEZEIT: (
        ("wartezeit_aktivitaet", "Wartezeit je Aktivität"),
        ("wartezeitanteil", "Anteil der Wartezeit an der Durchlaufzeit"),
    ),
    LogistischeZielgroesse.TRANSPORTZEIT: (
        ("transportzeit", "Transportzeit"),
        ("transportzeit_relation", "Transportzeit je Relation"),
    ),
    LogistischeZielgroesse.REAKTIONSZEIT: (
        ("reaktionszeit", "Reaktionszeit bis zur ersten Aktivität"),
    ),
    LogistischeZielgroesse.PROZESSVARIABILITAET: (
        ("streuung_durchlaufzeit", "Streuung der Durchlaufzeit"),
        ("variationskoeffizient", "Variationskoeffizient"),
        ("quantilabstaende", "Quantilabstände"),
    ),
    LogistischeZielgroesse.PROZESSSICHERHEIT: (
        ("regulaer_abgeschlossen", "Anteil regulär abgeschlossener Fälle"),
        ("ausnahmevarianten", "Anteil von Ausnahmevarianten"),
    ),
    LogistischeZielgroesse.QUALITAET: (
        ("qualitaetsquote", "Qualitätsquote"),
        ("fehler_ausschussquote", "Fehler- oder Ausschussquote"),
    ),
    LogistischeZielgroesse.NACHARBEIT: (
        ("nacharbeitsquote", "Nacharbeitsquote"),
        ("nacharbeitsschleifen", "Anzahl von Nacharbeitsschleifen"),
    ),
    LogistischeZielgroesse.RESSOURCENAUSLASTUNG: (
        ("ressourcenauslastung", "Ressourcenauslastung"),
        ("belegungsanteil", "Aktivitäts- bzw. Belegungsanteil"),
    ),
    LogistischeZielgroesse.RUESTZEIT: (
        ("ruestzeit", "Rüstzeit"),
        ("ruestzeitanteil", "Rüstzeitanteil"),
    ),
    LogistischeZielgroesse.BESTAENDE: (
        ("umlaufbestand", "Umlaufbestand"),
        ("aktive_faelle", "Gleichzeitig aktive Fälle"),
        ("lagerbestand", "Lagerbestand, sofern Bestandsdaten vorhanden sind"),
    ),
    LogistischeZielgroesse.KOSTEN: (
        ("prozesskosten", "Prozesskosten"),
        ("transportkosten", "Transportkosten, sofern Kostendaten vorhanden sind"),
    ),
}


def leite_kpi_kandidaten_ab(
    zielgroessen: tuple[LogistischeZielgroesse, ...],
) -> tuple[KpiKandidat, ...]:
    """Leitet deduplizierte KPI-Kandidaten in stabiler Reihenfolge ab."""
    ergebnis: list[KpiKandidat] = []
    bekannte_ids: set[str] = set()
    for ziel in zielgroessen:
        for kpi_id, bezeichnung in _KPI_DATEN[ziel]:
            if kpi_id not in bekannte_ids:
                bekannte_ids.add(kpi_id)
                ergebnis.append(
                    KpiKandidat(
                        kpi_id,
                        bezeichnung,
                        f"KPI für: {ZIELGROESSEN_BEZEICHNUNGEN[ziel]}",
                        "Ereigniszeitstempel und fachlich passende Attribute",
                    )
                )
    return tuple(ergebnis)


def bereinige_kpi_auswahl(
    zielgroessen: tuple[LogistischeZielgroesse, ...], ausgewaehlte_ids: tuple[str, ...]
) -> tuple[str, ...]:
    """Entfernt KPI-IDs, die aus den gewählten Zielgrößen nicht mehr ableitbar sind."""
    erlaubte_ids = {kandidat.kpi_id for kandidat in leite_kpi_kandidaten_ab(zielgroessen)}
    return tuple(kpi_id for kpi_id in ausgewaehlte_ids if kpi_id in erlaubte_ids)
