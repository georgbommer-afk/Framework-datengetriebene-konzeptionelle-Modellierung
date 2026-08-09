"""Fachliche Kataloge für Schritt 1 gemäß Tabellen 3.4 bis 3.6 und A.7 bis A.10."""

from dataclasses import dataclass

from framework_mvp.domain.models.projekt import (
    Erzeugnisstrukturtyp,
    GestaltDerGueter,
    LogistischeZielgroesse,
    Materialflusskontinuitaet,
    Systemtyp,
)


@dataclass(frozen=True, slots=True)
class ZielgruppenEintrag:
    """Eine fachliche Zielgruppe mit ihren vier logistischen Zielgrößen."""

    titel: str
    zielgroessen: tuple[LogistischeZielgroesse, ...]


@dataclass(frozen=True, slots=True)
class KpiKandidat:
    """Der einer logistischen Zielgröße eindeutig zugeordnete KPI-Kandidat."""

    kpi_id: str
    bezeichnung: str
    zielgroesse: LogistischeZielgroesse


@dataclass(frozen=True, slots=True)
class MerkmalsEintrag:
    """Ein systemspezifisches Merkmal mit den zulässigen Ausprägungen."""

    feldname: str
    bezeichnung: str
    auspraegungen: tuple[str, ...]
    mehrfachauswahl: bool = False


SYSTEMTYP_BEZEICHNUNGEN: dict[Systemtyp, str] = {
    Systemtyp.PRODUKTION: "Produktion",
    Systemtyp.INTRALOGISTIK: "Intralogistik",
}

GESTALT_DER_GUETER_BEZEICHNUNGEN: dict[GestaltDerGueter, str] = {
    GestaltDerGueter.STUECKGUT: "Stückgut",
    GestaltDerGueter.GEFORMT_UNGEFORMTES_FLIESSGUT: "geformt/ungeformtes Fließgut",
    GestaltDerGueter.MISCHFORM: "Mischform",
}

ERZEUGNISSTRUKTURTYP_BEZEICHNUNGEN: dict[Erzeugnisstrukturtyp, str] = {
    Erzeugnisstrukturtyp.LINEAR: "linear",
    Erzeugnisstrukturtyp.KONVERGIEREND: "konvergierend",
    Erzeugnisstrukturtyp.DIVERGIEREND: "divergierend",
    Erzeugnisstrukturtyp.GENERELL: "generell",
}

MATERIALFLUSSKONTINUITAET_BEZEICHNUNGEN: dict[Materialflusskontinuitaet, str] = {
    Materialflusskontinuitaet.KONTINUIERLICH: "kontinuierlich",
    Materialflusskontinuitaet.DISKONTINUIERLICH: "diskontinuierlich",
    Materialflusskontinuitaet.GEMISCHT: "Mischform",
}

PRODUKTIONSSPEZIFISCHE_MERKMALE = (
    MerkmalsEintrag(
        "auftragsabwicklungsstrategie",
        "Auftragsabwicklungsstrategie",
        (
            "Engineer-to-Order (ETO)",
            "Configure-to-Order (CTO)",
            "Make-to-Order (MTO)",
            "Assemble-to-Order (ATO)",
            "Make-to-Stock (MTS)",
        ),
    ),
    MerkmalsEintrag(
        "auflagegroesse",
        "Auflagegröße",
        ("Einzelproduktion", "Serienproduktion", "Massenproduktion (ggfs. mit Sorten)"),
    ),
    MerkmalsEintrag(
        "produktionsstueckzahl",
        "Produktionsstückzahl (p.a.)",
        (
            "gering (1-100 Stück)",
            "mittel (101-10 000 Stück)",
            "hoch (mehr als 10 000 Stück)",
        ),
    ),
    MerkmalsEintrag(
        "produktvielfalt",
        "Produktvielfalt (Var.)",
        ("gering (1-10 Var.)", "mittel (11-100 Var.)", "hoch (mehr als 100 Var.)"),
    ),
    MerkmalsEintrag(
        "organisationstyp",
        "Organisationstyp",
        (
            "Werkstattfertigung",
            "Gruppenfertigung",
            "Inselfertigung",
            "Reihenproduktion",
            "Fließproduktion",
        ),
    ),
    MerkmalsEintrag("anzahl_arbeitsgaenge", "Anzahl der Arbeitsgänge", ("einstufig", "mehrstufig")),
    MerkmalsEintrag(
        "ressourcen",
        "Eingesetzte Produktionsressourcen",
        ("Maschinen", "Anlagen", "Arbeitsplätze", "Personal", "Werkzeuge", "Informationssysteme"),
        mehrfachauswahl=True,
    ),
)

INTRALOGISTIKSPEZIFISCHE_MERKMALE = (
    MerkmalsEintrag(
        "handlingvorgaenge",
        "Handlingvorgänge",
        ("Einlagerung", "Auslagerung", "Sortierung", "Kommissionierung", "Verteilung"),
        mehrfachauswahl=True,
    ),
    MerkmalsEintrag(
        "transportorganisation",
        "Transportorganisation",
        ("Direkttransport", "gebündelter Rundlauf (“Milk-Run”)"),
    ),
    MerkmalsEintrag(
        "lagerplatzzuordnung",
        "Lagerplatzzuordnung",
        ("feste Zuordnung", "Zonenzuordnung", "wahlfreie/chaotische Zuordnung"),
    ),
    MerkmalsEintrag(
        "materialbereitstellungsprinzip",
        "Materialbereitstellungsprinzip",
        (
            "Vorratshaltung",
            "Einzelbeschaffung im Bedarfsfall",
            "einsatzsynchrone Bereitstellung",
        ),
    ),
    MerkmalsEintrag(
        "ressourcen",
        "Eingesetzte Intralogistikressourcen",
        (
            "manuelle Transportmittel",
            "Gabelstapler",
            "Routenzüge",
            "Kräne",
            "stationäre Fördertechnik",
            "Fahrerlose Transportsysteme (FTS)",
            "Regalbediengeräte",
            "Lager- und Pufferplätze",
            "Personal",
            "Informationssysteme",
        ),
        mehrfachauswahl=True,
    ),
)

ZIELGROESSEN_BEZEICHNUNGEN: dict[LogistischeZielgroesse, str] = {
    LogistischeZielgroesse.LIEFERFAEHIGKEIT: "Lieferfähigkeit erhöhen",
    LogistischeZielgroesse.LIEFERBEREITSCHAFT: "Lieferbereitschaft erhöhen",
    LogistischeZielgroesse.LIEFERTREUE: "Liefertreue erhöhen",
    LogistischeZielgroesse.LIEFERZEIT: "Lieferzeit reduzieren",
    LogistischeZielgroesse.DURCHLAUFZEIT: "Durchlaufzeit (DLZ) reduzieren",
    LogistischeZielgroesse.WARTEZEIT: "Wartezeit reduzieren",
    LogistischeZielgroesse.TRANSPORTZEIT: "Transportzeit reduzieren",
    LogistischeZielgroesse.REAKTIONSZEIT: "Reaktionszeit reduzieren",
    LogistischeZielgroesse.PROZESSVARIABILITAET: "Prozessvariabilität reduzieren",
    LogistischeZielgroesse.PROZESSSICHERHEIT: "Prozesssicherheit erhöhen",
    LogistischeZielgroesse.QUALITAET: "Qualität erhöhen",
    LogistischeZielgroesse.NACHARBEIT: "Nacharbeit reduzieren",
    LogistischeZielgroesse.RESSOURCENAUSLASTUNG: "Ressourcenauslastung erhöhen",
    LogistischeZielgroesse.RUESTZEIT: "Rüstzeit reduzieren",
    LogistischeZielgroesse.BESTAENDE: "Umlauf- und Lagerbestände reduzieren",
    LogistischeZielgroesse.KOSTEN: "Prozess- und Transportkosten reduzieren",
}

ZIELGRUPPEN = (
    ZielgruppenEintrag("Lieferleistung steigern", tuple(LogistischeZielgroesse)[:4]),
    ZielgruppenEintrag("Zeiten verbessern", tuple(LogistischeZielgroesse)[4:8]),
    ZielgruppenEintrag(
        "Prozessstabilität und Zuverlässigkeit erhöhen", tuple(LogistischeZielgroesse)[8:12]
    ),
    ZielgruppenEintrag("Ressourcennutzung erhöhen", tuple(LogistischeZielgroesse)[12:]),
)

_KPI_DATEN: dict[LogistischeZielgroesse, tuple[str, str]] = {
    LogistischeZielgroesse.LIEFERFAEHIGKEIT: ("servicegrad", "Servicegrad"),
    LogistischeZielgroesse.LIEFERBEREITSCHAFT: (
        "verfuegbarkeit_planstarttermin",
        "Verfügbarkeit zum Planstarttermin",
    ),
    LogistischeZielgroesse.LIEFERTREUE: ("liefertreue", "Liefertreue"),
    LogistischeZielgroesse.LIEFERZEIT: (
        "mittlere_dlz_warenausgang",
        "Mittlere DLZ Warenausgang",
    ),
    LogistischeZielgroesse.DURCHLAUFZEIT: (
        "mittlere_dlz_wareneingang",
        "Mittlere DLZ Wareneingang",
    ),
    LogistischeZielgroesse.WARTEZEIT: (
        "tatsaechliche_wartezeit_aqt",
        "Tatsächliche (tats.) Wartezeit (AQT)",
    ),
    LogistischeZielgroesse.TRANSPORTZEIT: (
        "mittlere_transportzeit_je_warensendung",
        "Mittlere Transportzeit je Warensendung",
    ),
    LogistischeZielgroesse.REAKTIONSZEIT: ("mittlere_reaktionszeit", "Mittlere Reaktionszeit"),
    LogistischeZielgroesse.PROZESSVARIABILITAET: (
        "standardabweichung_dlz_warenausgang",
        "Standardabweichung DLZ Warenausgang",
    ),
    LogistischeZielgroesse.PROZESSSICHERHEIT: (
        "anteil_regulaer_abgeschlossener_faelle",
        "Anteil regulär abgeschlossener Fälle",
    ),
    LogistischeZielgroesse.QUALITAET: ("lieferqualitaetstreue", "Lieferqualitätstreue"),
    LogistischeZielgroesse.NACHARBEIT: ("nacharbeitsquote_rr", "Nacharbeitsquote (RR)"),
    LogistischeZielgroesse.RESSOURCENAUSLASTUNG: (
        "nutzungseffizienz_ue",
        "Nutzungseffizienz (UE)",
    ),
    LogistischeZielgroesse.RUESTZEIT: ("ruestzeitanteil", "Rüstzeitanteil"),
    LogistischeZielgroesse.BESTAENDE: (
        "bewertete_umschlagshaeufigkeit",
        "Bewertete Umschlagshäufigkeit",
    ),
    LogistischeZielgroesse.KOSTEN: (
        "mittlere_kosten_produktionslogistik_pro_produktionsauftrag",
        "Mittlere Kosten der Produktionslogistik pro Produktionsauftrag",
    ),
}

_KPI_ID_ALIASE = {
    "lieferfaehigkeitsquote": "servicegrad",
    "erfuellungsquote": "servicegrad",
    "lieferbereitschaftsgrad": "verfuegbarkeit_planstarttermin",
    "materialverfuegbarkeit": "verfuegbarkeit_planstarttermin",
    "termintreue": "liefertreue",
    "terminabweichung": "liefertreue",
    "lieferzeit": "mittlere_dlz_warenausgang",
    "gesamtdurchlaufzeit": "mittlere_dlz_wareneingang",
    "durchlaufzeit_variante": "mittlere_dlz_wareneingang",
    "wartezeit_aktivitaet": "tatsaechliche_wartezeit_aqt",
    "wartezeitanteil": "tatsaechliche_wartezeit_aqt",
    "transportzeit": "mittlere_transportzeit_je_warensendung",
    "transportzeit_relation": "mittlere_transportzeit_je_warensendung",
    "reaktionszeit": "mittlere_reaktionszeit",
    "streuung_durchlaufzeit": "standardabweichung_dlz_warenausgang",
    "variationskoeffizient": "standardabweichung_dlz_warenausgang",
    "quantilabstaende": "standardabweichung_dlz_warenausgang",
    "regulaer_abgeschlossen": "anteil_regulaer_abgeschlossener_faelle",
    "ausnahmevarianten": "anteil_regulaer_abgeschlossener_faelle",
    "qualitaetsquote": "lieferqualitaetstreue",
    "fehler_ausschussquote": "lieferqualitaetstreue",
    "nacharbeitsquote": "nacharbeitsquote_rr",
    "nacharbeitsschleifen": "nacharbeitsquote_rr",
    "ressourcenauslastung": "nutzungseffizienz_ue",
    "belegungsanteil": "nutzungseffizienz_ue",
    "ruestzeit": "ruestzeitanteil",
    "umlaufbestand": "bewertete_umschlagshaeufigkeit",
    "aktive_faelle": "bewertete_umschlagshaeufigkeit",
    "lagerbestand": "bewertete_umschlagshaeufigkeit",
    "prozesskosten": "mittlere_kosten_produktionslogistik_pro_produktionsauftrag",
    "transportkosten": "mittlere_kosten_produktionslogistik_pro_produktionsauftrag",
}


def leite_kpi_kandidaten_ab(
    zielgroessen: tuple[LogistischeZielgroesse, ...],
) -> tuple[KpiKandidat, ...]:
    """Liefert je Zielgröße genau den in A.7 bis A.10 zugeordneten KPI-Kandidaten."""
    return tuple(KpiKandidat(*_KPI_DATEN[ziel], ziel) for ziel in zielgroessen)


def bereinige_kpi_auswahl(
    zielgroessen: tuple[LogistischeZielgroesse, ...], ausgewaehlte_ids: tuple[str, ...]
) -> tuple[str, ...]:
    """Migriert alte KPI-IDs und entfernt nicht zu den gewählten Zielgrößen gehörende IDs."""
    erlaubte_ids = {kandidat.kpi_id for kandidat in leite_kpi_kandidaten_ab(zielgroessen)}
    ergebnis: list[str] = []
    for kpi_id in ausgewaehlte_ids:
        normalisiert = _KPI_ID_ALIASE.get(kpi_id, kpi_id)
        if normalisiert in erlaubte_ids and normalisiert not in ergebnis:
            ergebnis.append(normalisiert)
    return tuple(ergebnis)
