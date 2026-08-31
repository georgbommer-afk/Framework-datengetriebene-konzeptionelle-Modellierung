# pyright: reportArgumentType=false
"""Fachliche End-to-End-Verträge der Algorithmen 9 und 10."""

import copy
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from framework_mvp.application.modellableitung import MODELLBESTANDTEILE
from framework_mvp.application.modellausgabe_service import ModellausgabeService
from framework_mvp.application.modellvalidierung_service import (
    ModellvalidierungService,
    _json_bytes,
    _sha,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    BehandlungOffenerEintrag,
    Gesamtvalidierungsstatus,
    Modellableitung,
    Modellableitungsstatus,
    ModellbestandteilId,
    Modellvalidierungsstatus,
    Offenheitsentscheidung,
    Offenheitskategorie,
    ZusaetzlicheModellanpassung,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.workspace import WorkspaceKonfiguration


class _Repository:
    def __init__(self) -> None:
        self.werte = {}

    def speichern(self, validierung):  # type: ignore[no-untyped-def]
        if validierung.validierungslauf_id in self.werte:
            raise AssertionError("doppelte ID")
        self.werte[validierung.validierungslauf_id] = validierung

    def laden(self, validierungslauf_id):  # type: ignore[no-untyped-def]
        return self.werte.get(validierungslauf_id)

    def finde_identisch(
        self, projekt_id, modellableitungs_id, eingabefingerabdruck, entscheidungsfingerabdruck
    ):  # type: ignore[no-untyped-def]
        return next(
            (
                wert
                for wert in self.werte.values()
                if wert.projekt_id == projekt_id
                and wert.modellableitungs_id == modellableitungs_id
                and wert.eingabefingerabdruck == eingabefingerabdruck
                and wert.entscheidungsfingerabdruck == entscheidungsfingerabdruck
            ),
            None,
        )


class _Modellableitungen:
    def __init__(self, ableitung, k, o):  # type: ignore[no-untyped-def]
        self.ableitung = ableitung
        self.k = k
        self.o = o

    def uebergabe_schritt9(self, modellableitungs_id, projekt_id):  # type: ignore[no-untyped-def]
        if modellableitungs_id != self.ableitung.modellableitungs_id:
            raise Importintegritaetsfehler("K/O fehlen")
        if projekt_id != self.ableitung.projekt_id:
            raise Domaenenfehler("projektfremdes K/O-Paar")
        return copy.deepcopy(self.k), copy.deepcopy(self.o)

    def laden(self, modellableitungs_id):  # type: ignore[no-untyped-def]
        if modellableitungs_id != self.ableitung.modellableitungs_id:
            raise Importintegritaetsfehler("K/O fehlen")
        return copy.deepcopy(self.ableitung), copy.deepcopy(self.k), copy.deepcopy(self.o)


def _umgebung(tmp_path):  # type: ignore[no-untyped-def]
    projekt_id, modellableitungs_id, k_id, o_id = uuid4(), uuid4(), uuid4(), uuid4()
    bestandteile = []
    for index, definition in enumerate(MODELLBESTANDTEILE, 1):
        bestandteile.append(
            {
                "bestandteil_id": definition.bestandteil_id.value,
                "bezeichnung": definition.bezeichnung,
                "status": "teilweise_offen" if index <= 2 else "vollstaendig_zugeordnet",
                "verwendete_quellen": ["U"],
                "informationen": [
                    {
                        "informations_id": f"info-{index}",
                        "bestandteil_id": definition.bestandteil_id.value,
                        "herkunftsartefakt": "U",
                        "herkunftsartefakt_id": str(projekt_id),
                        "herkunftsartefakt_sha256": "1" * 64,
                        "strukturreferenz": f"U.feld_{index}",
                        "wert": {"Text": f"Ursprung {index}", "Werte": [index, index + 1]},
                        "uebernahmeart": "direkte_uebernahme",
                    }
                ],
                "offene_eintrag_ids": [f"offen-{index}"] if index <= 2 else [],
            }
        )
    k = {
        "artefaktart": "vorlaeufiges_konzeptionelles_modell_k",
        "artefaktversion": 1,
        "mappingversion": 3,
        "k_id": str(k_id),
        "modellableitungs_id": str(modellableitungs_id),
        "projekt_id": str(projekt_id),
        "modellbestandteile": bestandteile,
        "gesamtpruefsumme": "2" * 64,
    }
    offene = [
        {
            "offener_eintrag_id": f"offen-{index}",
            "bestandteil_id": MODELLBESTANDTEILE[index - 1].bestandteil_id.value,
            "kategorie": (
                Offenheitskategorie.NICHT_ABLEITBAR.value
                if index == 1
                else Offenheitskategorie.FACHLICH_UNSICHER.value
            ),
            "begruendung": f"Fachliche Prüfung {index} erforderlich.",
            "status": "offen",
            "kennzeichnungsherkunft": "systematisch_erkannt",
            "belegreferenzen": [],
        }
        for index in (1, 2)
    ]
    o = {
        "artefaktart": "offene_modellbestandteile_o",
        "artefaktversion": 1,
        "o_id": str(o_id),
        "modellableitungs_id": str(modellableitungs_id),
        "projekt_id": str(projekt_id),
        "k_referenz": {"k_id": str(k_id)},
        "offene_eintraege": offene,
        "gesamtpruefsumme": "3" * 64,
    }
    ableitung = Modellableitung(
        modellableitungs_id,
        k_id,
        o_id,
        projekt_id,
        uuid4(),
        uuid4(),
        uuid4(),
        "4" * 64,
        3,
        "5" * 64,
        "k.json",
        "6" * 64,
        "o.json",
        "7" * 64,
        Modellableitungsstatus.GESPEICHERT,
        datetime.now(UTC),
    )
    repository = _Repository()
    artefakte = ImportartefaktSpeicher(WorkspaceKonfiguration(tmp_path / "workspace"))
    modellableitungen = _Modellableitungen(ableitung, k, o)
    service = ModellvalidierungService(repository, modellableitungen, artefakte)
    projekte = SimpleNamespace(
        projekt_laden=lambda angefordert: (
            SimpleNamespace(projekt_id=projekt_id, bezeichnung="Förderanlage Süd / ÄÖÜ")
            if angefordert == projekt_id
            else None
        )
    )
    return (
        service,
        ModellausgabeService(service, projekte, WorkspaceKonfiguration(tmp_path / "workspace")),
        repository,
        artefakte,
        modellableitungen,
    )


def _behandlungen(o):  # type: ignore[no-untyped-def]
    return tuple(
        BehandlungOffenerEintrag(
            wert["offener_eintrag_id"],
            MODELLBESTANDTEILE[index].bestandteil_id,
            Offenheitskategorie(wert["kategorie"]),
            wert["begruendung"],
            Offenheitsentscheidung.BESTAETIGT
            if wert["kategorie"] == Offenheitskategorie.FACHLICH_UNSICHER.value
            else Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST,
            (
                ""
                if wert["kategorie"] == Offenheitskategorie.FACHLICH_UNSICHER.value
                else f"Fachliche Ergänzung {index + 1}"
            ),
            f"Menschliche Begründung {index + 1}",
        )
        for index, wert in enumerate(o["offene_eintraege"])
    )


def _arbeitsfassung(service, modellableitungen, **abweichungen):  # type: ignore[no-untyped-def]
    a = modellableitungen.ableitung
    parameter = {
        "projekt_id": a.projekt_id,
        "modellableitungs_id": a.modellableitungs_id,
        "erwartete_k_id": a.k_id,
        "erwartete_o_id": a.o_id,
        "behandlungen": _behandlungen(modellableitungen.o),
        "zusaetzliche_anpassungen": (
            ZusaetzlicheModellanpassung(
                MODELLBESTANDTEILE[5].bestandteil_id,
                "Aktivität C wird fachlich ergänzt.",
                "Im aktuellen Prozess fachlich erforderlich.",
            ),
        ),
        "gesamtvalidierungsstatus": Gesamtvalidierungsstatus.FACHLICH_VALIDIERT,
        "validierungsvermerk": "Mit Prozesseignerin geprüft.",
        "gesamtpruefung_bestaetigt": True,
    }
    parameter.update(abweichungen)
    return service.arbeitsfassung_erstellen(**parameter)


def test_k_stern_entsteht_idempotent_und_laesst_k_und_o_unveraendert(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, repository, _, ableitungen = _umgebung(tmp_path)
    k_vorher, o_vorher = copy.deepcopy(ableitungen.k), copy.deepcopy(ableitungen.o)
    arbeitsfassung = _arbeitsfassung(service, ableitungen)
    gespeichert = service.speichern(
        arbeitsfassung,
        validierungslauf_id=uuid4(),
        k_stern_id=uuid4(),
    )
    erneut = service.speichern(
        arbeitsfassung,
        validierungslauf_id=uuid4(),
        k_stern_id=uuid4(),
    )
    geladen, k_stern = service.laden(gespeichert.validierungslauf_id)

    assert erneut == gespeichert == geladen
    assert len(repository.werte) == 1
    assert geladen.status is Modellvalidierungsstatus.FACHLICH_VALIDIERT
    assert k_stern["artefaktversion"] == 2
    assert k_stern["mappingversion"] == 3
    assert [wert["bestandteil_id"] for wert in k_stern["modellbestandteile"]] == [
        wert.bestandteil_id.value for wert in MODELLBESTANDTEILE
    ]
    assert [
        wert["urspruenglicher_bestandteil"] for wert in k_stern["modellbestandteile"]
    ] == ableitungen.k["modellbestandteile"]
    assert {wert["offener_eintrag_id"] for wert in k_stern["behandlungen_offener_eintraege"]} == {
        "offen-1",
        "offen-2",
    }
    assert all(
        wert["menschliche_entscheidung"]
        for bestandteil in k_stern["modellbestandteile"]
        for wert in bestandteil["menschliche_eintraege"]
    )
    ergaenzung = k_stern["modellbestandteile"][0]["menschliche_eintraege"][0]
    assert ergaenzung["fachlicher_inhalt"] == "Fachliche Ergänzung 1"
    assert ergaenzung["modellinhalt_erzeugt"] is True
    bestaetigung = k_stern["modellbestandteile"][1]["menschliche_eintraege"][0]
    assert bestaetigung["entscheidung"] == Offenheitsentscheidung.BESTAETIGT.value
    assert bestaetigung["fachlicher_inhalt"] == ""
    assert bestaetigung["modellinhalt_erzeugt"] is False
    zusaetzlich = k_stern["modellbestandteile"][5]["menschliche_eintraege"][-1]
    assert zusaetzlich["eintragstyp"] == "zusaetzliche_anpassung"
    assert zusaetzlich["fuer_k_stern_massgeblich"] is True
    assert ableitungen.k == k_vorher
    assert ableitungen.o == o_vorher


def test_manuelle_mehrfachressource_und_bewusst_offen_erscheinen_in_k_stern(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    service, _, _, _, ableitungen = _umgebung(tmp_path)
    ressourcen_offen = {
        "offener_eintrag_id": "ressourcen-manuell",
        "bestandteil_id": ModellbestandteilId.RESSOURCEN.value,
        "kategorie": Offenheitskategorie.NICHT_ABLEITBAR.value,
        "begruendung": (
            "E* enthält kein kanonisches Ressourcenattribut resource. "
            "Die Zuordnung ist in Schritt 9 zu dokumentieren."
        ),
        "status": "offen",
        "kennzeichnungsherkunft": "systematisch_erkannt",
        "belegreferenzen": [],
    }
    ableitungen.o["offene_eintraege"].append(ressourcen_offen)
    dokumentation = {
        "aktivitaet_ressourcen": [
            {
                "aktivitaet": "A",
                "ressourcen": ["M1", "M2"],
                "status": "zugeordnet",
                "menschliche_entscheidung": True,
            },
            {
                "aktivitaet": "B",
                "ressourcen": [],
                "status": "bewusst_offen",
                "menschliche_entscheidung": True,
            },
        ]
    }
    behandlungen = (
        *_behandlungen({"offene_eintraege": ableitungen.o["offene_eintraege"][:2]}),
        BehandlungOffenerEintrag(
            "ressourcen-manuell",
            ModellbestandteilId.RESSOURCEN,
            Offenheitskategorie.NICHT_ABLEITBAR,
            ressourcen_offen["begruendung"],
            Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST,
            json.dumps(dokumentation, ensure_ascii=False, sort_keys=True),
            "Ressourcenzuordnung wurde durch die Prozesseignerin ergänzt.",
        ),
    )
    arbeitsfassung = _arbeitsfassung(service, ableitungen, behandlungen=behandlungen)

    gespeichert = service.speichern(
        arbeitsfassung,
        validierungslauf_id=uuid4(),
        k_stern_id=uuid4(),
    )
    _, k_stern = service.laden(gespeichert.validierungslauf_id)

    ressourcen = next(
        wert
        for wert in k_stern["modellbestandteile"]
        if wert["bestandteil_id"] == ModellbestandteilId.RESSOURCEN.value
    )
    menschlicher_eintrag = next(
        wert
        for wert in ressourcen["menschliche_eintraege"]
        if wert["offener_eintrag_id"] == "ressourcen-manuell"
    )
    assert menschlicher_eintrag["menschliche_entscheidung"] is True
    assert (
        json.loads(menschlicher_eintrag["fachliche_ergaenzung_oder_begruendung"]) == dokumentation
    )


def test_finalisierung_verlangt_alle_o_eintraege_validierung_und_bestaetigung(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, _, _, ableitungen = _umgebung(tmp_path)
    unvollstaendig = _arbeitsfassung(
        service, ableitungen, behandlungen=_behandlungen(ableitungen.o)[:1]
    )
    assert unvollstaendig.unbehandelte_offene_eintrag_ids == ("offen-2",)
    with pytest.raises(Domaenenfehler, match="alle Einträge aus O"):
        service.speichern(
            unvollstaendig,
            validierungslauf_id=uuid4(),
            k_stern_id=uuid4(),
        )
    anpassungsbedarf = _arbeitsfassung(
        service,
        ableitungen,
        gesamtvalidierungsstatus=Gesamtvalidierungsstatus.ANPASSUNGSBEDARF,
    )
    with pytest.raises(Domaenenfehler, match="Anpassungsbedarf"):
        service.speichern(
            anpassungsbedarf,
            validierungslauf_id=uuid4(),
            k_stern_id=uuid4(),
        )
    with pytest.raises(Domaenenfehler, match="bewusste fachliche Bestätigung"):
        service.speichern(
            _arbeitsfassung(service, ableitungen, gesamtpruefung_bestaetigt=False),
            validierungslauf_id=uuid4(),
            k_stern_id=uuid4(),
        )


def test_doppelte_unbekannte_o_behandlung_und_unbekannter_bestandteil_werden_abgewiesen(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    service, _, _, _, ableitungen = _umgebung(tmp_path)
    behandlungen = _behandlungen(ableitungen.o)
    with pytest.raises(Domaenenfehler, match="nur einmal"):
        _arbeitsfassung(service, ableitungen, behandlungen=(*behandlungen, behandlungen[0]))
    with pytest.raises(Domaenenfehler, match="keinen Eintrag"):
        _arbeitsfassung(
            service,
            ableitungen,
            behandlungen=(replace(behandlungen[0], offener_eintrag_id="unbekannt"),),
        )
    unbekannt = ZusaetzlicheModellanpassung(
        cast(ModellbestandteilId, "unbekannt"), "Inhalt", "Begründung"
    )
    with pytest.raises(Domaenenfehler, match="keinem der 16 Modellbestandteile"):
        _arbeitsfassung(service, ableitungen, zusaetzliche_anpassungen=(unbekannt,))


def test_iterative_validierung_aendert_fingerabdruck_und_erzeugt_nur_final_k_stern(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    service, _, repository, _, ableitungen = _umgebung(tmp_path)
    arbeitsstand = _arbeitsfassung(
        service,
        ableitungen,
        gesamtvalidierungsstatus=Gesamtvalidierungsstatus.ANPASSUNGSBEDARF,
        gesamtpruefung_bestaetigt=False,
    )
    assert not arbeitsstand.finalisierbar
    assert repository.werte == {}
    mit_anpassung = _arbeitsfassung(
        service,
        ableitungen,
        zusaetzliche_anpassungen=(
            *arbeitsstand.zusaetzliche_anpassungen,
            ZusaetzlicheModellanpassung(
                ModellbestandteilId.DATEN,
                "Datenumfang fachlich korrigiert.",
                "Ergebnis der erneuten Gesamtprüfung.",
            ),
        ),
        gesamtvalidierungsstatus=Gesamtvalidierungsstatus.ANPASSUNGSBEDARF,
        gesamtpruefung_bestaetigt=False,
    )
    final = _arbeitsfassung(
        service,
        ableitungen,
        zusaetzliche_anpassungen=mit_anpassung.zusaetzliche_anpassungen,
        gesamtpruefung_bestaetigt=True,
    )
    assert (
        len(
            {
                arbeitsstand.entscheidungsfingerabdruck,
                mit_anpassung.entscheidungsfingerabdruck,
                final.entscheidungsfingerabdruck,
            }
        )
        == 3
    )
    assert final.finalisierbar
    gespeichert = service.speichern(final, validierungslauf_id=uuid4(), k_stern_id=uuid4())
    assert repository.laden(gespeichert.validierungslauf_id) == gespeichert


def test_nicht_anwendbar_erzeugt_keinen_kuenstlichen_modellinhalt(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, _, _, _, ableitungen = _umgebung(tmp_path)
    behandlungen = list(_behandlungen(ableitungen.o))
    behandlungen[0] = replace(
        behandlungen[0],
        entscheidung=Offenheitsentscheidung.NICHT_ANWENDBAR,
        fachlicher_inhalt="",
        begruendung="Für den Modellzweck fachlich nicht relevant.",
    )
    arbeitsfassung = _arbeitsfassung(service, ableitungen, behandlungen=tuple(behandlungen))
    gespeichert = service.speichern(arbeitsfassung, validierungslauf_id=uuid4(), k_stern_id=uuid4())
    _, k_stern = service.laden(gespeichert.validierungslauf_id)
    eintrag = k_stern["modellbestandteile"][0]["menschliche_eintraege"][0]
    assert eintrag["entscheidung"] == Offenheitsentscheidung.NICHT_ANWENDBAR.value
    assert eintrag["fachlicher_inhalt"] == ""
    assert eintrag["modellinhalt_erzeugt"] is False
    assert eintrag["begruendung"] == "Für den Modellzweck fachlich nicht relevant."


def test_projektfremde_inkonsistente_oder_manipulierte_artefakte_werden_abgewiesen(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    service, _, _, artefakte, ableitungen = _umgebung(tmp_path)
    with pytest.raises(Domaenenfehler, match="projektfremd"):
        service.grundlage_laden(uuid4(), ableitungen.ableitung.modellableitungs_id)
    with pytest.raises(Importintegritaetsfehler, match="aktive K-ID"):
        service.grundlage_laden(
            ableitungen.ableitung.projekt_id,
            ableitungen.ableitung.modellableitungs_id,
            erwartete_k_id=uuid4(),
        )
    arbeitsfassung = _arbeitsfassung(service, ableitungen)
    gespeichert = service.speichern(
        arbeitsfassung,
        validierungslauf_id=uuid4(),
        k_stern_id=uuid4(),
    )
    artefakte.pfad(gespeichert.relativer_k_stern_pfad).write_bytes(b"manipuliert")
    with pytest.raises(Importintegritaetsfehler, match="Dateiprüfsumme"):
        service.laden(gespeichert.validierungslauf_id)


def test_historisches_k_stern_v1_bleibt_kontrolliert_lesbar_aber_nicht_uebergabefaehig(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    service, _, repository, artefakte, ableitungen = _umgebung(tmp_path)
    gespeichert = service.speichern(
        _arbeitsfassung(service, ableitungen),
        validierungslauf_id=uuid4(),
        k_stern_id=uuid4(),
    )
    _, struktur = service.laden(gespeichert.validierungslauf_id)
    historisch = copy.deepcopy(struktur)
    historisch.pop("gesamtpruefsumme")
    historisch["artefaktversion"] = 1
    historisch["gesamtpruefsumme"] = _sha(historisch)
    inhalt = _json_bytes(historisch)
    artefakte.pfad(gespeichert.relativer_k_stern_pfad).write_bytes(inhalt)
    repository.werte[gespeichert.validierungslauf_id] = replace(
        gespeichert, k_stern_sha256=hashlib.sha256(inhalt).hexdigest()
    )

    _, gelesen = service.laden(gespeichert.validierungslauf_id)
    assert gelesen["artefaktversion"] == 1
    assert gelesen["historischer_lesemodus"] is True
    with pytest.raises(Domaenenfehler, match=r"historisches K\*"):
        service.uebergabe_schritt10(
            gespeichert.validierungslauf_id,
            gespeichert.projekt_id,
            gespeichert.k_stern_id,
        )


def test_geaenderte_eingaben_oder_menschliche_entscheidung_invalidieren_arbeitsfassung(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    service, _, _, _, ableitungen = _umgebung(tmp_path)
    arbeitsfassung = _arbeitsfassung(service, ableitungen)
    ableitungen.ableitung = replace(ableitungen.ableitung, k_sha256="8" * 64)
    with pytest.raises(Domaenenfehler, match="Arbeitsfassung ist ungültig"):
        service.speichern(
            arbeitsfassung,
            validierungslauf_id=uuid4(),
            k_stern_id=uuid4(),
        )

    service, _, _, _, ableitungen = _umgebung(tmp_path / "menschlich")
    arbeitsfassung = _arbeitsfassung(service, ableitungen)
    manipuliert = replace(arbeitsfassung, validierungsvermerk="nachträglich geändert")
    with pytest.raises(Domaenenfehler, match="Menschliche Eingaben wurden verändert"):
        service.speichern(
            manipuliert,
            validierungslauf_id=uuid4(),
            k_stern_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("html", "pdf"),
    [(True, False), (False, True), (True, True)],
)
def test_html_pdf_und_gemeinsame_auswahl_enthalten_alle_16_ohne_mutation(
    tmp_path, html, pdf
) -> None:  # type: ignore[no-untyped-def]
    service, ausgaben, _, _, ableitungen = _umgebung(tmp_path)
    gespeichert = service.speichern(
        _arbeitsfassung(service, ableitungen),
        validierungslauf_id=uuid4(),
        k_stern_id=uuid4(),
    )
    _, vorher = service.laden(gespeichert.validierungslauf_id)
    ergebnis = ausgaben.erzeugen(
        validierungslauf_id=gespeichert.validierungslauf_id,
        projekt_id=gespeichert.projekt_id,
        k_stern_id=gespeichert.k_stern_id,
        html=html,
        pdf=pdf,
    )
    if html:
        assert ergebnis.report_html is not None
        assert ergebnis.html_dateiname is not None
        assert ergebnis.html_dateiname.endswith(".html")
        html_text = ergebnis.report_html.decode("utf-8")
        assert "<style>" in html_text
        assert "report_html.css" not in html_text
        assert all(wert.bezeichnung in html_text for wert in MODELLBESTANDTEILE)
    else:
        assert ergebnis.report_html is None
    if pdf:
        assert ergebnis.report_pdf is not None
        assert ergebnis.pdf_dateiname is not None
        assert ergebnis.pdf_dateiname == "Konzeptionelles Modell Förderanlage Süd ÄÖÜ.pdf"
        assert ergebnis.report_pdf.startswith(b"%PDF-")
    else:
        assert ergebnis.report_pdf is None
    assert service.laden(gespeichert.validierungslauf_id)[1] == vorher


def test_schritt_10_akzeptiert_nur_passendes_fachlich_validiertes_k_stern(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service, ausgaben, _, _, ableitungen = _umgebung(tmp_path)
    gespeichert = service.speichern(
        _arbeitsfassung(service, ableitungen),
        validierungslauf_id=uuid4(),
        k_stern_id=uuid4(),
    )
    with pytest.raises(Domaenenfehler, match=r"aktive K\*"):
        ausgaben.erzeugen(
            validierungslauf_id=gespeichert.validierungslauf_id,
            projekt_id=gespeichert.projekt_id,
            k_stern_id=uuid4(),
            html=True,
            pdf=False,
        )
    with pytest.raises(Importintegritaetsfehler, match="Mindestens HTML oder PDF"):
        ausgaben.erzeugen(
            validierungslauf_id=gespeichert.validierungslauf_id,
            projekt_id=gespeichert.projekt_id,
            k_stern_id=gespeichert.k_stern_id,
            html=False,
            pdf=False,
        )
