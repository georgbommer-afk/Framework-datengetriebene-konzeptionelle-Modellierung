"""Domänenverträge der gezielten O-Behandlung in Schritt 9."""

from dataclasses import replace

import pytest

from framework_mvp.application.modellvalidierung_service import ModellvalidierungService
from framework_mvp.application.modellvalidierung_struktur import (
    DARSTELLUNGSFORMEN,
    modellbezugsoptionen,
    validiere_strukturierten_inhalt,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    BehandlungOffenerEintrag,
    Gesamtvalidierungsstatus,
    ModellbestandteilId,
    Offenheitsentscheidung,
    Offenheitskategorie,
    ZusaetzlicheModellanpassung,
)


def _behandlung(
    *,
    kategorie: Offenheitskategorie = Offenheitskategorie.FACHLICH_UNSICHER,
    entscheidung: Offenheitsentscheidung = Offenheitsentscheidung.BESTAETIGT,
    struktur: dict[str, object] | None = None,
    kommentar: str = "",
) -> BehandlungOffenerEintrag:
    return BehandlungOffenerEintrag(
        "offen-1",
        ModellbestandteilId.PROBLEMSTELLUNG,
        kategorie,
        "Eine fachliche Prüfung ist erforderlich.",
        entscheidung,
        begruendung=kommentar,
        strukturierter_inhalt=struktur or {},
    )


@pytest.mark.parametrize(
    "entscheidung",
    [
        Offenheitsentscheidung.BESTAETIGT,
        Offenheitsentscheidung.NICHT_BEKANNT_ODER_BESTIMMBAR,
        Offenheitsentscheidung.NICHT_ANWENDBAR,
    ],
)
def test_behandlungen_ohne_pflichtkommentar_erlaubt(entscheidung: Offenheitsentscheidung) -> None:
    assert _behandlung(entscheidung=entscheidung).begruendung == ""


@pytest.mark.parametrize(
    "kategorie",
    [Offenheitskategorie.FEHLEND, Offenheitskategorie.NICHT_ABLEITBAR],
)
def test_nur_fachlich_unsichere_information_darf_bestaetigt_werden(
    kategorie: Offenheitskategorie,
) -> None:
    with pytest.raises(Domaenenfehler, match="fachlich unsicherer"):
        _behandlung(kategorie=kategorie)


def test_ergaenzung_braucht_struktur_andere_behandlungen_erzeugen_keinen_inhalt() -> None:
    with pytest.raises(Domaenenfehler, match="strukturierten fachlichen Inhalt"):
        _behandlung(entscheidung=Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST)
    with pytest.raises(Domaenenfehler, match="dürfen keinen Modellinhalt"):
        _behandlung(
            entscheidung=Offenheitsentscheidung.NICHT_BEKANNT_ODER_BESTIMMBAR,
            struktur={"strukturtyp": "problemstellung", "beschreibung": "Erfunden"},
        )


def test_zusaetzliche_anpassung_bleibt_nur_historischer_vertrag() -> None:
    with pytest.raises(Domaenenfehler, match="Inhalt und Begründung"):
        ZusaetzlicheModellanpassung(ModellbestandteilId.DATEN, "", "Begründung")


def test_entscheidungsfingerabdruck_reagiert_auf_struktur_kommentar_und_bestaetigung() -> None:
    behandlung = _behandlung(
        entscheidung=Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST,
        struktur={"strukturtyp": "problemstellung", "beschreibung": "Engpass analysieren"},
    )

    def fingerabdruck(
        wert: BehandlungOffenerEintrag = behandlung,
        vermerk: str = "Gesamtvermerk",
        bestaetigt: bool = True,
    ) -> str:
        return ModellvalidierungService.entscheidungsfingerabdruck(
            (wert,), (), Gesamtvalidierungsstatus.FACHLICH_VALIDIERT, vermerk, bestaetigt
        )

    basis = fingerabdruck()
    varianten = {
        fingerabdruck(
            replace(
                behandlung,
                strukturierter_inhalt={
                    "strukturtyp": "problemstellung",
                    "beschreibung": "Andere Beschreibung",
                },
            )
        ),
        fingerabdruck(replace(behandlung, begruendung="Optionaler Kommentar")),
        fingerabdruck(vermerk="Anderer Gesamtvermerk"),
        fingerabdruck(bestaetigt=False),
    }
    assert basis not in varianten
    assert len(varianten) == 4


def _k() -> dict[str, object]:
    return {
        "modellbestandteile": [
            {
                "bestandteil_id": "aktivitaeten",
                "informationen": [
                    {"strukturreferenz": "sichtbare_aktivitaeten", "wert": ["Fräsen", "Lackieren"]}
                ],
            },
            {
                "bestandteil_id": "ressourcen",
                "informationen": [
                    {
                        "strukturreferenz": "strukturierte_ergebnisse.ressourcen",
                        "wert": {
                            "zuordnungen": [
                                {"aktivitaet": "Fräsen", "ressourcen": ["Maschine M01"]}
                            ]
                        },
                    }
                ],
            },
            {
                "bestandteil_id": "datenauswahl",
                "informationen": [
                    {
                        "strukturreferenz": "zeitbezogene_datenauswahl",
                        "wert": {
                            "potenzielle_wartezeiten": [
                                {"von_aktivitaet": "Fräsen", "zu_aktivitaet": "Lackieren"}
                            ]
                        },
                    }
                ],
            },
        ]
    }


@pytest.mark.parametrize(
    "struktur",
    [
        {
            "strukturtyp": "experimenteller_faktor",
            "bezugstyp": "ressource",
            "konkreter_bezug": "Maschine M01",
            "bezeichnung": "Pausenzeit",
            "art": "quantitativer_parameter",
            "unterer_wert": 0,
            "oberer_wert": 30,
            "einheit": "min",
        },
        {
            "strukturtyp": "experimenteller_faktor",
            "bezugstyp": "ressource",
            "konkreter_bezug": "Maschine M01",
            "bezeichnung": "Verfügbare Anzahl",
            "art": "quantitativer_parameter",
            "unterer_wert": 1,
            "oberer_wert": 3,
            "einheit": "Maschinen",
        },
        {
            "strukturtyp": "experimenteller_faktor",
            "bezugstyp": "aktivitaet",
            "konkreter_bezug": "Lackieren",
            "bezeichnung": "Bearbeitungsweise",
            "art": "qualitative_regel",
            "auspraegungen": ["Einzelfertigung", "Batchfertigung"],
        },
    ],
)
def test_experimentelle_faktoren_werden_strukturiert_validiert(
    struktur: dict[str, object],
) -> None:
    assert validiere_strukturierten_inhalt(ModellbestandteilId.EINGABEN, struktur, _k()) == struktur


def test_experimenteller_faktor_darf_nur_vorhandenes_k_element_referenzieren() -> None:
    struktur = {
        "strukturtyp": "experimenteller_faktor",
        "bezugstyp": "ressource",
        "konkreter_bezug": "Technische-ID-999",
        "bezeichnung": "Pausenzeit",
        "art": "quantitativer_parameter",
        "unterer_wert": 0,
        "oberer_wert": 30,
        "einheit": "min",
    }
    with pytest.raises(Domaenenfehler, match="nicht als Modellelement in K"):
        validiere_strukturierten_inhalt(ModellbestandteilId.EINGABEN, struktur, _k())


def test_ressource_warteschlange_und_detaillierungsgrad_nutzen_k_referenzen() -> None:
    ressourcen = {
        "strukturtyp": "ressourcenergaenzung",
        "ressource": "Maschine M01",
        "rolle": "Bearbeitung",
        "verfuegbare_anzahl": 2,
        "kapazitaet": "2 Aufträge",
        "schichtstart": "06:00",
        "schichtende": "14:00",
        "pausenzeiten": "09:00–09:15",
    }
    warteschlange = {
        "strukturtyp": "warteschlangenergaenzung",
        "vorgaengeraktivitaet": "Fräsen",
        "folgeaktivitaet": "Lackieren",
        "fachlich_bestaetigt": True,
        "kapazitaet": "5 Aufträge",
        "regel": "FIFO",
        "potenzieller_wartestellenhinweis": [
            {"von_aktivitaet": "Fräsen", "zu_aktivitaet": "Lackieren"}
        ],
    }
    detail = {
        "strukturtyp": "detaillierungsentscheidung",
        "bezugstyp": "ressource",
        "konkreter_bezug": "Maschine M01",
        "detailmerkmal": "Schichtmodell",
        "behandlung": "beruecksichtigen",
    }
    assert validiere_strukturierten_inhalt(ModellbestandteilId.RESSOURCEN, ressourcen, _k())
    assert validiere_strukturierten_inhalt(ModellbestandteilId.WARTESCHLANGEN, warteschlange, _k())
    assert validiere_strukturierten_inhalt(ModellbestandteilId.DETAILLIERUNGSGRAD, detail, _k())
    assert modellbezugsoptionen(_k()).warteschlangen == ("Wartestelle Fräsen → Lackieren",)


@pytest.mark.parametrize(
    ("bestandteil_id", "struktur"),
    [
        (
            ModellbestandteilId.ANNAHMEN,
            {"strukturtyp": "annahme", "annahme": "Ankünfte sind unabhängig.", "hintergrund": ""},
        ),
        (
            ModellbestandteilId.VEREINFACHUNGEN,
            {
                "strukturtyp": "vereinfachung",
                "bezugstyp": "gesamtsystem",
                "konkreter_bezug": "",
                "beschreibung": "Rüstvarianten werden zusammengefasst.",
                "begruendung": "Für den Modellierungszweck ausreichend.",
            },
        ),
        *(
            (
                ModellbestandteilId.DATEN,
                {
                    "strukturtyp": "datenanforderung",
                    "beschreibung": "Pausenzeiten",
                    "zustand": zustand,
                    "quelle": "Schichtplan" if zustand != "nicht_vorhanden" else "",
                    "naeherung": (
                        "Mittelwert der letzten Woche"
                        if zustand == "angenähert_oder_geschätzt"
                        else ""
                    ),
                },
            )
            for zustand in ("vorhanden", "angenähert_oder_geschätzt", "nicht_vorhanden")
        ),
    ],
)
def test_weitere_theoriegestuetzte_strukturen(
    bestandteil_id: ModellbestandteilId, struktur: dict[str, object]
) -> None:
    assert validiere_strukturierten_inhalt(bestandteil_id, struktur, _k()) == struktur


@pytest.mark.parametrize(
    ("bestandteil_id", "struktur"),
    [
        (
            ModellbestandteilId.MODELLGRENZEN,
            {
                "strukturtyp": "modellumfang_und_grenze",
                "beschreibung": "Vom Auftragseingang bis Lackieren.",
                "einbezogen": ["Fräsen", "Lackieren"],
                "ausgeschlossen": ["Versand"],
            },
        ),
        (
            ModellbestandteilId.ENTITAETEN,
            {
                "strukturtyp": "entitaetsergaenzung",
                "entitaetstyp": "Produktionsauftrag",
                "objektbezug": "Auftrag",
                "bezeichnung": "Fertigungsauftrag",
                "granularitaet": "Ein Auftrag je Entität",
            },
        ),
        (
            ModellbestandteilId.AKTIVITAETEN,
            {
                "strukturtyp": "aktivitaetsergaenzung",
                "vorhandene_aktivitaet": "Fräsen",
                "fachliche_bezeichnung": "Fräsen",
                "objektbezug": "Werkstück",
                "granularitaet": "Ein Arbeitsgang",
                "variantenbezug": "Standardvariante",
            },
        ),
        (
            ModellbestandteilId.PROBLEMSTELLUNG,
            {"strukturtyp": "problemstellung", "beschreibung": "Hohe Durchlaufzeit"},
        ),
        (
            ModellbestandteilId.ZIELSETZUNG,
            {
                "strukturtyp": "zielsetzung",
                "modellierungszweck": "Engpasswirkung untersuchen",
                "angestrebter_zustand": "Kürzere Durchlaufzeit",
            },
        ),
        (
            ModellbestandteilId.AUSGABEN,
            {
                "strukturtyp": "modellausgabe",
                "gewuenschte_ausgabe": "Bereits vorgesehene Durchlaufzeit-Kennzahl",
            },
        ),
    ],
)
def test_weitere_modellbestandteile_bleiben_begrenzt_strukturiert(
    bestandteil_id: ModellbestandteilId, struktur: dict[str, object]
) -> None:
    assert validiere_strukturierten_inhalt(bestandteil_id, struktur, _k()) == struktur


def test_fachfremde_strukturfelder_werden_abgewiesen() -> None:
    with pytest.raises(Domaenenfehler, match="fachfremde Felder"):
        validiere_strukturierten_inhalt(
            ModellbestandteilId.RESSOURCEN,
            {
                "strukturtyp": "ressourcenergaenzung",
                "ressource": "Maschine M01",
                "rolle": "Bearbeitung",
                "kapazitaet": "",
                "schichtstart": "",
                "schichtende": "",
                "pausenzeiten": "",
                "individueller_maschinenzustand": "nicht zulässig",
            },
            _k(),
        )


def test_systemdarstellung_kennt_genau_drei_theorieformen() -> None:
    assert DARSTELLUNGSFORMEN == (
        "prozessflussdiagramm",
        "ablaufdiagramm",
        "aktivitaetszyklusdiagramm",
    )
