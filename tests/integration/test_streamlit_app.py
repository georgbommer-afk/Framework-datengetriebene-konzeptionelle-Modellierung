"""Bedientests der reduzierten Projektverwaltung und Hauptnavigation."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.bootstrap import (
    DATENBANKPFAD_UMGEBUNGSVARIABLE,
    erstelle_datenquelle_service,
    erstelle_projekt_service,
)
from framework_mvp.domain.models import (
    Betrachtungszeitraum,
    BetrachtungszeitraumModus,
    Erzeugnisstrukturtyp,
    GestaltDerGueter,
    LogistischeZielgroesse,
    Materialflusskontinuitaet,
    Projektstatus,
    Quellenart,
    Quellsystemtyp,
    Rahmenbedingungen,
    Systemklassifikation,
    Systemtyp,
    Untersuchungsauftrag,
)

ANWENDUNGSPFAD = Path(__file__).parents[2] / "streamlit_app.py"

VOLLSTAENDIGE_PRODUKTION = {
    "auftragsabwicklungsstrategie": "Make-to-Order (MTO)",
    "auflagegroesse": "Serienproduktion",
    "produktionsstueckzahl": "mittel (101-10 000 Stück)",
    "produktvielfalt": "mittel (11-100 Var.)",
    "organisationstyp": "Reihenproduktion",
    "anzahl_arbeitsgaenge": "mehrstufig",
    "ressourcen": ("Maschinen", "Personal"),
}


def _vollstaendiges_produktionsprofil(entwurf: dict) -> None:  # type: ignore[type-arg]
    entwurf.update(
        {
            "systemtyp": Systemtyp.PRODUKTION,
            "gestalt": GestaltDerGueter.STUECKGUT,
            "erzeugnisstrukturtyp": Erzeugnisstrukturtyp.LINEAR,
            "kontinuitaet": Materialflusskontinuitaet.KONTINUIERLICH,
            "produktion": dict(VOLLSTAENDIGE_PRODUKTION),
        }
    )


def _anwendung_starten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    datenbankpfad = tmp_path / "streamlit.sqlite"
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(datenbankpfad))
    return AppTest.from_file(ANWENDUNGSPFAD).run()


def _schaltflaeche(anwendung: AppTest, beschriftung: str):  # type: ignore[no-untyped-def]
    return next(element for element in anwendung.button if element.label == beschriftung)


def test_anwendung_startet_mit_fuenf_schritten_und_tooltips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schritt 1 beginnt kompakt mit genau den beiden fachlichen Textbereichen."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    assert not anwendung.exception
    assert any(
        element.value == "Schritt 1: Projektrahmen definieren" for element in anwendung.header
    )
    assert any("Gesamtfortschritt" in element.value for element in anwendung.caption)
    assert len(anwendung.get("progress")) == 1
    assert {element.label for element in anwendung.text_area} == {
        "Problemstellung",
        "Systemgrenze",
    }
    problem = next(element for element in anwendung.text_area if element.label == "Problemstellung")
    grenze = next(element for element in anwendung.text_area if element.label == "Systemgrenze")
    assert "betriebliche Problem" in problem.help
    assert "außerhalb der Untersuchung" in grenze.help
    assert not any(element.label == "Projektstatus" for element in anwendung.selectbox)


def test_problemstellung_bleibt_bei_reruns_und_vor_zurueck_navigation_erhalten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    problem = next(wert for wert in anwendung.text_area if wert.label == "Problemstellung")
    problem.set_value("Unveränderte fachliche Problemstellung").run()
    anwendung.run()
    _schaltflaeche(anwendung, "Weiter").click().run()
    _schaltflaeche(anwendung, "Zurück").click().run()

    problem = next(wert for wert in anwendung.text_area if wert.label == "Problemstellung")
    assert problem.value == "Unveränderte fachliche Problemstellung"
    assert (
        anwendung.session_state["wizard_entwurf"]["problemstellung"]
        == "Unveränderte fachliche Problemstellung"
    )


def test_projektwechsel_vermischt_keine_widgetwerte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    datenbankpfad = tmp_path / "streamlit.sqlite"
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(datenbankpfad))
    service = erstelle_projekt_service()
    for name, problem in (("Projekt A", "Problem A"), ("Projekt B", "Problem B")):
        service.projekt_anlegen(
            bezeichnung=name,
            untersuchungsauftrag=Untersuchungsauftrag(
                problem, "System analysieren", Systemtyp.PRODUKTION, "Grenze"
            ),
        )
    anwendung = AppTest.from_file(ANWENDUNGSPFAD).run()
    projektauswahl = next(
        wert for wert in anwendung.selectbox if wert.label == "Vorhandenes Projekt auswählen"
    )
    projektauswahl.select_index(projektauswahl.options.index("Projekt A")).run()
    next(wert for wert in anwendung.text_area if wert.label == "Problemstellung").set_value(
        "Ungespeicherte Änderung A"
    ).run()

    projektauswahl = next(
        wert for wert in anwendung.selectbox if wert.label == "Vorhandenes Projekt auswählen"
    )
    projektauswahl.select_index(projektauswahl.options.index("Projekt B")).run()
    assert (
        next(wert for wert in anwendung.text_area if wert.label == "Problemstellung").value
        == "Problem B"
    )

    projektauswahl = next(
        wert for wert in anwendung.selectbox if wert.label == "Vorhandenes Projekt auswählen"
    )
    projektauswahl.select_index(projektauswahl.options.index("Projekt A")).run()
    assert (
        next(wert for wert in anwendung.text_area if wert.label == "Problemstellung").value
        == "Problem A"
    )


def test_untersuchungszwecke_und_logistikziele_sind_kompakt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vordefinierte und individuelle Zwecke teilen sich eine Auswahl."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    _schaltflaeche(anwendung, "Weiter").click().run()
    zwecke = next(
        element for element in anwendung.multiselect if element.label == "Untersuchungszwecke"
    )
    assert "System analysieren" in zwecke.options
    assert any(
        element.label == "Weiteren Untersuchungszweck hinzufügen …"
        for element in anwendung.checkbox
    )
    assert any("Logistische Zielgrößen" in element.value for element in anwendung.markdown)
    assert {
        "Lieferleistung steigern",
        "Zeiten verbessern",
        "Prozessstabilität und Zuverlässigkeit erhöhen",
        "Ressourcennutzung erhöhen",
    } <= {element.value.removeprefix("#### ") for element in anwendung.markdown}
    oberziel = "Übergeordnetes Ziel: Leistungsfähigkeit des betrachteten Systems steigern"
    assert sum(oberziel in element.value for element in anwendung.caption) == 1
    assert all(element.label != oberziel for element in anwendung.checkbox)
    assert not any(
        element.label == "Weiteres individuelles Ziel" for element in anwendung.text_area
    )


def test_individueller_zweck_wird_ausgewaehlt_und_duplikat_abgelehnt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein bereinigter Zweck wird ergänzt; Groß-/Kleinschreibung erzeugt kein Duplikat."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_schritt"] = 2
    anwendung.run()
    next(
        element
        for element in anwendung.checkbox
        if element.label == "Weiteren Untersuchungszweck hinzufügen …"
    ).check().run()
    next(
        element
        for element in anwendung.text_input
        if element.label == "Individueller Untersuchungszweck"
    ).set_value("  Materialfluss erklären  ")
    _schaltflaeche(anwendung, "Untersuchungszweck hinzufügen").click().run()
    assert "Materialfluss erklären" in anwendung.session_state["wizard_entwurf"]["zwecke"]
    assert (
        "Materialfluss erklären" in anwendung.session_state["wizard_entwurf"]["individuelle_zwecke"]
    )

    next(
        element
        for element in anwendung.checkbox
        if element.label == "Weiteren Untersuchungszweck hinzufügen …"
    ).check().run()
    next(
        element
        for element in anwendung.text_input
        if element.label == "Individueller Untersuchungszweck"
    ).set_value("materialfluss ERKLÄREN")
    _schaltflaeche(anwendung, "Untersuchungszweck hinzufügen").click().run()
    assert any("bereits vorhanden" in element.value for element in anwendung.error)
    assert len(anwendung.session_state["wizard_entwurf"]["individuelle_zwecke"]) == 1


def test_systemklassifikation_enthaelt_keine_freien_beschreibungsfelder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neue Projekte wählen eindeutig Produktion oder Intralogistik."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_schritt"] = 3
    anwendung.run()
    systemtyp = next(element for element in anwendung.selectbox if element.label == "Systemtyp")
    assert systemtyp.value is None
    assert systemtyp.proto.placeholder == "Choose an option"
    assert "Produktion" in systemtyp.options
    assert "Intralogistik" in systemtyp.options
    assert "Kombiniert" not in systemtyp.options
    assert next(
        element for element in anwendung.selectbox if element.label == "Erzeugnisstrukturtyp"
    ).options == ["linear", "konvergierend", "divergierend", "generell"]
    assert next(
        element for element in anwendung.selectbox if element.label == "Gestalt der Güter"
    ).options == ["Stückgut", "geformt/ungeformtes Fließgut", "Mischform"]
    entfernte_felder = {
        "Beschreibung des Inputs",
        "Beschreibung der Transformation",
        "Beschreibung des Outputs",
        "Kapazitätsgrenzen",
        "Gewünschter Detaillierungsgrad",
    }
    assert not entfernte_felder & {
        element.label for element in (*anwendung.text_input, *anwendung.text_area)
    }


def test_systemspezifische_merkmale_werden_bedingt_angezeigt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Produktion und Intralogistik zeigen ausschließlich den jeweils relevanten Block."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_schritt"] = 3
    anwendung.run()
    systemtyp = next(element for element in anwendung.selectbox if element.label == "Systemtyp")
    systemtyp.set_value("Produktion").run()
    labels = {element.label for element in (*anwendung.selectbox, *anwendung.multiselect)}
    assert {
        "Auftragsabwicklungsstrategie",
        "Auflagegröße",
        "Produktionsstückzahl (p.a.)",
        "Produktvielfalt (Var.)",
        "Organisationstyp",
        "Anzahl der Arbeitsgänge",
        "Eingesetzte Produktionsressourcen",
    } <= labels
    assert "Handlingvorgänge" not in labels

    intralogistik_app = _anwendung_starten(tmp_path, monkeypatch)
    intralogistik_app.session_state["wizard_entwurf"]["systemtyp"] = Systemtyp.INTRALOGISTIK
    intralogistik_app.session_state["wizard_schritt"] = 3
    intralogistik_app.run()
    labels = {
        element.label for element in (*intralogistik_app.selectbox, *intralogistik_app.multiselect)
    }
    assert {
        "Handlingvorgänge",
        "Transportorganisation",
        "Lagerplatzzuordnung",
        "Materialbereitstellungsprinzip",
        "Eingesetzte Intralogistikressourcen",
    } <= labels
    assert "Auflagegröße" not in labels


def test_handlingvorgaenge_bleiben_beim_erweitern_gemeinsam_ausgewaehlt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_schritt"] = 3
    anwendung.run()
    next(wert for wert in anwendung.selectbox if wert.label == "Systemtyp").set_value(
        "Intralogistik"
    ).run()
    handling = next(wert for wert in anwendung.multiselect if wert.label == "Handlingvorgänge")
    handling.set_value(["Kommissionierung"]).run()
    handling = next(wert for wert in anwendung.multiselect if wert.label == "Handlingvorgänge")
    handling.set_value(["Kommissionierung", "Sortierung"]).run()

    assert set(anwendung.session_state["wizard_entwurf"]["intralogistik"]["handlingvorgaenge"]) == {
        "Kommissionierung",
        "Sortierung",
    }
    assert set(
        next(wert for wert in anwendung.multiselect if wert.label == "Handlingvorgänge").value
    ) == {"Kommissionierung", "Sortierung"}


def test_kpi_hinweis_und_entfernte_allgemeine_freitexte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KPI-Bedarf bleibt auswählbar, allgemeine Annahmen werden nicht mehr erhoben."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_entwurf"]["zielgroessen"] = [
        LogistischeZielgroesse.DURCHLAUFZEIT
    ]
    anwendung.session_state["wizard_entwurf"]["kpis"] = ["nicht_mehr_gueltiger_kpi"]
    anwendung.session_state["wizard_schritt"] = 4
    anwendung.run()
    assert any("Mittlere DLZ Wareneingang" in element.value for element in anwendung.markdown)
    assert any("Sie haben" in element.value for element in anwendung.caption)
    assert anwendung.session_state["wizard_entwurf"]["kpis"] == []
    assert any("Analysebedarf" in element.value for element in anwendung.info)
    assert not {
        "Bekannte Annahmen",
        "Technische Einschränkungen",
        "Sonstige fachliche Rahmenbedingungen",
        "Anmerkungen",
    } & {element.label for element in anwendung.text_area}


def test_ausgaben_u_und_s_sind_vollstaendig_und_q_ist_abwesend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der letzte Schritt benennt ausschließlich U und S und bietet keine Datumseingabe."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_entwurf"].update(
        {
            "bezeichnung": "Rahmen A",
            "problemstellung": "Lange Lieferzeiten",
            "systemgrenze": "Wareneingang bis Versand",
            "zwecke": ["System analysieren", "Materialfluss erklären"],
            "individuelle_zwecke": ["Materialfluss erklären"],
            "zielgroessen": [LogistischeZielgroesse.LIEFERZEIT],
            "kpis": ["mittlere_dlz_warenausgang"],
        }
    )
    _vollstaendiges_produktionsprofil(anwendung.session_state["wizard_entwurf"])
    anwendung.session_state["wizard_schritt"] = 5
    anwendung.run()
    texte = [element.value for element in anwendung.markdown]
    assert any("Untersuchungsauftrag (U)" in text for text in texte)
    assert any("Systemprofil (S)" in text for text in texte)
    assert any("**Projektbezeichnung:** Rahmen A" in text for text in texte)
    assert any(
        "**Individueller Untersuchungszweck:** Materialfluss erklären" in text for text in texte
    )
    assert any("Produktionsspezifische Merkmale" in text for text in texte)
    assert any(
        "Lieferzeit reduzieren" in str(zelle) or "Mittlere DLZ Warenausgang" in str(zelle)
        for dataframe in anwendung.dataframe
        for zelle in dataframe.value.to_numpy().flat
    )
    assert not any("Datenquellenkatalog Q" in text for text in texte)
    assert not anwendung.date_input


def test_vorhandene_datenquelle_ist_von_schritt_1_entkoppelt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eine vorhandene Datenquelle erzeugt in Schritt 1 keine Ausgabe Q mehr."""
    datenbankpfad = tmp_path / "streamlit.sqlite"
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(datenbankpfad))
    projekt = erstelle_projekt_service().projekt_anlegen(
        bezeichnung="Katalog",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Problem", "System analysieren", Systemtyp.PRODUKTION, "Grenze"
        ),
    )
    erstelle_datenquelle_service().datenquelle_anlegen(
        projekt_id=projekt.projekt_id,
        bezeichnung="ERP-Export",
        quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
        quellenart=Quellenart.CSV,
    )
    anwendung = AppTest.from_file(ANWENDUNGSPFAD).run()
    next(
        element
        for element in anwendung.selectbox
        if element.label == "Vorhandenes Projekt auswählen"
    ).select_index(1).run()
    anwendung.session_state["wizard_schritt"] = 5
    anwendung.run()
    assert not any("ERP-Export" in element.value for element in anwendung.markdown)
    assert not anwendung.date_input
    assert any(
        element.label == "Projektrahmen speichern und zu Schritt 2" for element in anwendung.button
    )


def test_altprojekt_wird_ohne_verlust_verdeckt_geladen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gemischt, Anmerkung, Rahmenbedingungen und Altbeschreibungen verursachen keinen Fehler."""
    datenbankpfad = tmp_path / "streamlit.sqlite"
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(datenbankpfad))
    service = erstelle_projekt_service()
    entwurf = service.projekt_anlegen(
        bezeichnung="Altprojekt",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Problem",
            "System analysieren",
            Systemtyp.KOMBINIERT,
            "Grenze",
            systemklassifikation=Systemklassifikation(
                input_beschreibung="Alter Input",
                transformation_beschreibung="Alte Transformation",
                output_beschreibung="Alter Output",
                kapazitaetsgrenzen="Alte Kapazität",
            ),
            detaillierungsgrad="Alt",
            rahmenbedingungen=Rahmenbedingungen(bekannte_annahmen="Altannahme"),
            anmerkungen="Alte Anmerkung",
            betrachtungszeitraum=Betrachtungszeitraum(
                BetrachtungszeitraumModus.MANUELL,
                __import__("datetime").date(2025, 1, 1),
                __import__("datetime").date(2025, 12, 31),
            ),
        ),
    )
    projekt = service.projekt_aktualisieren(
        entwurf.projekt_id,
        bezeichnung=entwurf.bezeichnung,
        untersuchungsauftrag=entwurf.untersuchungsauftrag,
        status=Projektstatus.AKTIV,
    )
    anwendung = AppTest.from_file(ANWENDUNGSPFAD).run()
    next(
        element
        for element in anwendung.selectbox
        if element.label == "Vorhandenes Projekt auswählen"
    ).select_index(1).run()
    anwendung.session_state["wizard_schritt"] = 3
    anwendung.run()
    assert not anwendung.exception
    assert any("Altprojekt ist als Gemischt klassifiziert" in e.value for e in anwendung.warning)
    assert service.projekt_laden(projekt.projekt_id).status is Projektstatus.AKTIV  # type: ignore[union-attr]
    systemtyp = next(element for element in anwendung.selectbox if element.label == "Systemtyp")
    systemtyp.set_value("Produktion").run()
    _vollstaendiges_produktionsprofil(anwendung.session_state["wizard_entwurf"])
    anwendung.session_state["wizard_schritt"] = 5
    anwendung.run()
    _schaltflaeche(anwendung, "Projektrahmen speichern und zu Schritt 2").click().run()
    erneut = service.projekt_laden(projekt.projekt_id)
    assert erneut is not None
    assert erneut.status is Projektstatus.AKTIV
    assert erneut.untersuchungsauftrag.anmerkungen == "Alte Anmerkung"
    assert erneut.untersuchungsauftrag.systemklassifikation.input_beschreibung == "Alter Input"


def test_vollstaendiges_neues_projekt_navigiert_zu_etl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Erst erfolgreiche Persistenz öffnet Schritt 2 und bewahrt die Projekt-ID."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    entwurf = anwendung.session_state["wizard_entwurf"]
    entwurf.update(
        {
            "bezeichnung": "Navigationsprojekt",
            "problemstellung": "Problem",
            "systemgrenze": "Grenze",
            "zwecke": ["System analysieren"],
            "zielgroessen": [LogistischeZielgroesse.DURCHLAUFZEIT],
        }
    )
    _vollstaendiges_produktionsprofil(entwurf)
    anwendung.session_state["wizard_schritt"] = 5
    anwendung.run()
    _schaltflaeche(anwendung, "Projektrahmen speichern und zu Schritt 2").click().run()
    assert not anwendung.exception
    gespeicherte = erstelle_projekt_service().projekte_auflisten()
    assert len(gespeicherte) == 1
    assert str(gespeicherte[0].projekt_id) == anwendung.session_state["aktuelles_projekt_id"]
    assert gespeicherte[0].status is Projektstatus.ENTWURF
    assert anwendung.radio[0].value == "2 ETL durchführen"


def test_validierungsfehler_verhindert_navigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leere Pflichtangaben lassen Eingaben und Framework-Schritt unverändert."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_entwurf"].update(
        {"bezeichnung": "Ungültig", "systemtyp": Systemtyp.PRODUKTION}
    )
    anwendung.session_state["wizard_schritt"] = 5
    anwendung.run()
    _schaltflaeche(anwendung, "Projektrahmen speichern und zu Schritt 2").click().run()
    assert anwendung.radio[0].value == "Schritt 1: Projektrahmen definieren"
    assert any("müssen ausgefüllt sein" in element.value for element in anwendung.error)
    assert not erstelle_projekt_service().projekte_auflisten()


def test_nicht_ausgewaehlte_pflicht_dropdowns_blockieren_das_speichern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_entwurf"].update(
        {
            "bezeichnung": "Unvollständiges Systemprofil",
            "problemstellung": "Problem",
            "systemgrenze": "Grenze",
            "zwecke": ["System analysieren"],
            "zielgroessen": [LogistischeZielgroesse.DURCHLAUFZEIT],
        }
    )
    anwendung.session_state["wizard_schritt"] = 5
    anwendung.run()

    _schaltflaeche(anwendung, "Projektrahmen speichern und zu Schritt 2").click().run()

    assert any("Wählen Sie für die Systemklassifikation" in wert.value for wert in anwendung.error)
    assert not erstelle_projekt_service().projekte_auflisten()


def test_schritte_zwei_bis_zehn_bleiben_in_der_navigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die Navigation enthält die validierten Übergabepunkte bis Schritt 10."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    assert anwendung.radio[0].options == [
        "Schritt 1: Projektrahmen definieren",
        "2 ETL durchführen",
        "3 Semantisches Mapping",
        "4 Event Log aufbauen",
        "5 Datenqualität prüfen",
        "6 Process Mining durchführen",
        "7 Ergebnisse aggregieren",
        "8 Modellbestandteile ableiten",
        "9 Modell ergänzen und validieren",
        "10 Konzeptionelles Modell ausgeben",
    ]
