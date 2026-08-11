"""Tests der strukturierten Domänenobjekte und Kataloge."""

from collections.abc import Callable
from datetime import date

import pytest

from framework_mvp.domain.exceptions import Domaenenfehler, UngueltigerBetrachtungszeitraum
from framework_mvp.domain.kataloge import (
    ERZEUGNISSTRUKTURTYP_BEZEICHNUNGEN,
    GESTALT_DER_GUETER_BEZEICHNUNGEN,
    INTRALOGISTIKSPEZIFISCHE_MERKMALE,
    MATERIALFLUSSKONTINUITAET_BEZEICHNUNGEN,
    PRODUKTIONSSPEZIFISCHE_MERKMALE,
    SYSTEMTYP_BEZEICHNUNGEN,
    ZIELGROESSEN_BEZEICHNUNGEN,
    ZIELGRUPPEN,
    bereinige_kpi_auswahl,
    leite_kpi_kandidaten_ab,
)
from framework_mvp.domain.models import (
    BeteiligtePerson,
    Betrachtungszeitraum,
    BetrachtungszeitraumModus,
    Erzeugnisstrukturtyp,
    GestaltDerGueter,
    Intralogistikklassifikation,
    LogistischeZielgroesse,
    Produktionsklassifikation,
    Systemklassifikation,
    Systemtyp,
    Untersuchungsauftrag,
)


def test_beteiligte_person_normalisiert_werte_und_erlaubt_freie_rolle() -> None:
    """Namen und eine frei gewählte Rolle werden bereinigt."""
    assert BeteiligtePerson(" Ada ", " Lovelace ", " Leitung ") == BeteiligtePerson(
        "Ada", "Lovelace", "Leitung"
    )


def test_beteiligte_person_benoetigt_einen_namen() -> None:
    """Mindestens einer der beiden Namensteile muss vorhanden sein."""
    with pytest.raises(Domaenenfehler):
        BeteiligtePerson(" ", " ", "Rolle")


def test_zielgroessen_und_ids_sind_stabil_und_mehrfach_waehlbar() -> None:
    """Mehrere technische Ziel-IDs bleiben in Eingabereihenfolge erhalten."""
    ziele = (LogistischeZielgroesse.DURCHLAUFZEIT, LogistischeZielgroesse.QUALITAET)
    auftrag = Untersuchungsauftrag(
        "Problem", "Analyse", Systemtyp.PRODUKTION, "Grenze", logistische_zielgroessen=ziele
    )
    assert auftrag.logistische_zielgroessen == ziele
    assert LogistischeZielgroesse.DURCHLAUFZEIT.value == "durchlaufzeit_reduzieren"


def test_kpis_werden_abgeleitet_und_kontrolliert_bereinigt() -> None:
    """Entfernte Zielgrößen entfernen nicht mehr passende KPI-IDs."""
    kandidaten = leite_kpi_kandidaten_ab((LogistischeZielgroesse.DURCHLAUFZEIT,))
    assert [(k.kpi_id, k.bezeichnung) for k in kandidaten] == [
        ("mittlere_dlz_wareneingang", "Mittlere DLZ Wareneingang")
    ]
    assert bereinige_kpi_auswahl(
        (LogistischeZielgroesse.DURCHLAUFZEIT,), ("gesamtdurchlaufzeit",)
    ) == ("mittlere_dlz_wareneingang",)


@pytest.mark.parametrize(
    ("systemtyp", "produktion", "intralogistik"),
    [
        (Systemtyp.PRODUKTION, Produktionsklassifikation(), None),
        (Systemtyp.INTRALOGISTIK, None, Intralogistikklassifikation()),
    ],
)
def test_systemklassifikation_fuer_alle_systemtypen(
    systemtyp: Systemtyp,
    produktion: Produktionsklassifikation | None,
    intralogistik: Intralogistikklassifikation | None,
) -> None:
    """Die beiden Systemtypen aus Tabelle 3.4 tragen den jeweils passenden Teilblock."""
    system = Systemklassifikation(produktion=produktion, intralogistik=intralogistik)
    auftrag = Untersuchungsauftrag(
        "Problem", "Analyse", systemtyp, "Grenze", systemklassifikation=system
    )
    assert auftrag.systemklassifikation.produktion is produktion
    assert auftrag.systemklassifikation.intralogistik is intralogistik


def test_zeitraummodi_aus_daten_und_offen() -> None:
    """Automatischer und offener Modus benötigen keine Datumswerte."""
    assert Betrachtungszeitraum().modus is BetrachtungszeitraumModus.AUS_DATEN
    assert Betrachtungszeitraum(BetrachtungszeitraumModus.OFFEN).beginn is None


def test_manueller_zeitraum_benoetigt_beide_daten() -> None:
    """Ein manueller Zeitraum ist nur mit Beginn und Ende gültig."""
    with pytest.raises(UngueltigerBetrachtungszeitraum):
        Betrachtungszeitraum(BetrachtungszeitraumModus.MANUELL, date(2026, 1, 1))


def test_manueller_zeitraum_prueft_reihenfolge() -> None:
    """Das Ende darf auch im neuen Zeitraumobjekt nicht vor dem Beginn liegen."""
    with pytest.raises(UngueltigerBetrachtungszeitraum):
        Betrachtungszeitraum(BetrachtungszeitraumModus.MANUELL, date(2026, 2, 1), date(2026, 1, 1))


def test_neue_vollstaendigkeitsregel() -> None:
    """Nur Problem, Grenze und Untersuchungszweck bestimmen die Vollständigkeit."""
    assert Untersuchungsauftrag(
        "Problem", "Analyse", Systemtyp.PRODUKTION, "Grenze"
    ).ist_vollstaendig()
    assert not Untersuchungsauftrag(
        "Problem", "", Systemtyp.PRODUKTION, "Grenze", individuelles_ziel="Altziel"
    ).ist_vollstaendig()


def test_allgemeine_merkmale_entsprechen_tabelle_3_4_exakt() -> None:
    """Tabelle 3.4 ist ohne zusätzliche auswählbare Ausprägungen abgebildet."""
    assert SYSTEMTYP_BEZEICHNUNGEN == {
        Systemtyp.PRODUKTION: "Produktion",
        Systemtyp.INTRALOGISTIK: "Intralogistik",
    }
    assert tuple(GESTALT_DER_GUETER_BEZEICHNUNGEN.values()) == (
        "Stückgut",
        "geformt/ungeformtes Fließgut",
        "Mischform",
    )
    assert tuple(ERZEUGNISSTRUKTURTYP_BEZEICHNUNGEN.values()) == (
        "linear",
        "konvergierend",
        "divergierend",
        "generell",
    )
    assert tuple(MATERIALFLUSSKONTINUITAET_BEZEICHNUNGEN.values()) == (
        "kontinuierlich",
        "diskontinuierlich",
        "Mischform",
    )
    assert set(Erzeugnisstrukturtyp) == {
        Erzeugnisstrukturtyp.LINEAR,
        Erzeugnisstrukturtyp.KONVERGIEREND,
        Erzeugnisstrukturtyp.DIVERGIEREND,
        Erzeugnisstrukturtyp.GENERELL,
    }
    assert set(GestaltDerGueter) == set(GESTALT_DER_GUETER_BEZEICHNUNGEN)


def test_produktionsmerkmale_entsprechen_tabelle_3_5_exakt() -> None:
    """Bezeichnungen, Werte und Mehrfachauswahl folgen vollständig Tabelle 3.5."""
    assert {
        merkmal.bezeichnung: (merkmal.auspraegungen, merkmal.mehrfachauswahl)
        for merkmal in PRODUKTIONSSPEZIFISCHE_MERKMALE
    } == {
        "Auftragsabwicklungsstrategie": (
            (
                "Engineer-to-Order (ETO)",
                "Configure-to-Order (CTO)",
                "Make-to-Order (MTO)",
                "Assemble-to-Order (ATO)",
                "Make-to-Stock (MTS)",
            ),
            False,
        ),
        "Auflagegröße": (
            ("Einzelproduktion", "Serienproduktion", "Massenproduktion (ggfs. mit Sorten)"),
            False,
        ),
        "Produktionsstückzahl (p.a.)": (
            (
                "gering (1-100 Stück)",
                "mittel (101-10 000 Stück)",
                "hoch (mehr als 10 000 Stück)",
            ),
            False,
        ),
        "Produktvielfalt (Var.)": (
            ("gering (1-10 Var.)", "mittel (11-100 Var.)", "hoch (mehr als 100 Var.)"),
            False,
        ),
        "Organisationstyp": (
            (
                "Werkstattfertigung",
                "Gruppenfertigung",
                "Inselfertigung",
                "Reihenproduktion",
                "Fließproduktion",
            ),
            False,
        ),
        "Anzahl der Arbeitsgänge": (("einstufig", "mehrstufig"), False),
        "Eingesetzte Produktionsressourcen": (
            (
                "Maschinen",
                "Anlagen",
                "Arbeitsplätze",
                "Personal",
                "Werkzeuge",
                "Informationssysteme",
            ),
            True,
        ),
    }


def test_intralogistikmerkmale_entsprechen_tabelle_3_6_exakt() -> None:
    """Die fünf Merkmale aus Tabelle 3.6 bleiben fachlich getrennt."""
    katalog = {merkmal.bezeichnung: merkmal for merkmal in INTRALOGISTIKSPEZIFISCHE_MERKMALE}
    assert tuple(katalog) == (
        "Handlingvorgänge",
        "Transportorganisation",
        "Lagerplatzzuordnung",
        "Materialbereitstellungsprinzip",
        "Eingesetzte Intralogistikressourcen",
    )
    assert katalog["Handlingvorgänge"].auspraegungen == (
        "Einlagerung",
        "Auslagerung",
        "Sortierung",
        "Kommissionierung",
        "Verteilung",
    )
    assert katalog["Transportorganisation"].auspraegungen == (
        "Direkttransport",
        "gebündelter Rundlauf (“Milk-Run”)",
    )
    assert katalog["Lagerplatzzuordnung"].auspraegungen == (
        "feste Zuordnung",
        "Zonenzuordnung",
        "wahlfreie/chaotische Zuordnung",
    )
    assert katalog["Materialbereitstellungsprinzip"].auspraegungen == (
        "Vorratshaltung",
        "Einzelbeschaffung im Bedarfsfall",
        "einsatzsynchrone Bereitstellung",
    )
    assert katalog["Eingesetzte Intralogistikressourcen"].auspraegungen == (
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
    )


@pytest.mark.parametrize(
    "klassifikation",
    [
        lambda: Produktionsklassifikation(auflagegroesse="Sortenproduktion"),
        lambda: Intralogistikklassifikation(transportorganisation="Sammeltransport"),
    ],
)
def test_nicht_definierte_systemauspraegungen_werden_abgelehnt(
    klassifikation: Callable[[], object],
) -> None:
    """Nicht in 3.5 oder 3.6 enthaltene Werte gelangen nicht in das Systemprofil."""
    with pytest.raises(Domaenenfehler, match="Ungültige Ausprägung"):
        klassifikation()


def test_vier_zielgruppen_enthalten_je_vier_korrekte_zielgroessen() -> None:
    """Insbesondere Lieferzeit gehört zur Lieferleistung und nicht zu den Zeiten."""
    assert [gruppe.titel for gruppe in ZIELGRUPPEN] == [
        "Lieferleistung steigern",
        "Zeiten verbessern",
        "Prozessstabilität und Zuverlässigkeit erhöhen",
        "Ressourcennutzung erhöhen",
    ]
    assert all(len(gruppe.zielgroessen) == 4 for gruppe in ZIELGRUPPEN)
    assert LogistischeZielgroesse.LIEFERZEIT in ZIELGRUPPEN[0].zielgroessen
    assert LogistischeZielgroesse.LIEFERZEIT not in ZIELGRUPPEN[1].zielgroessen
    assert len(ZIELGROESSEN_BEZEICHNUNGEN) == 16


def test_16_zielgroessen_haben_je_genau_einen_kpi_kandidaten() -> None:
    """A.7 bis A.10 bilden eine vollständige Eins-zu-eins-Zuordnung."""
    kandidaten = leite_kpi_kandidaten_ab(tuple(LogistischeZielgroesse))
    assert len(kandidaten) == 16
    assert len({k.zielgroesse for k in kandidaten}) == 16
    assert [k.bezeichnung for k in kandidaten] == [
        "Servicegrad",
        "Verfügbarkeit zum Planstarttermin",
        "Liefertreue",
        "Mittlere DLZ Warenausgang",
        "Mittlere DLZ Wareneingang",
        "Tatsächliche (tats.) Wartezeit (AQT)",
        "Mittlere Transportzeit je Warensendung",
        "Mittlere Reaktionszeit",
        "Standardabweichung DLZ Warenausgang",
        "Anteil regulär abgeschlossener Fälle",
        "Lieferqualitätstreue",
        "Nacharbeitsquote (RR)",
        "Nutzungseffizienz (UE)",
        "Rüstzeitanteil",
        "Bewertete Umschlagshäufigkeit",
        "Mittlere Kosten der Produktionslogistik pro Produktionsauftrag",
    ]
