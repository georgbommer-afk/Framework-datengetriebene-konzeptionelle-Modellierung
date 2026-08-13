"""Verträge der gemeinsamen Reporting-Pipeline für Schritt 10."""

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

import framework_mvp.application.modellausgabe_service as ausgabe_modul
from framework_mvp.application.modellausgabe_service import ModellausgabeService
from framework_mvp.application.modellvalidierung_service import ModellvalidierungService
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.reporting.asset_resolver import ReportAssetFehler, resolve_report_assets
from framework_mvp.reporting.html_renderer import render_report_html, template_verzeichnis
from framework_mvp.reporting.pdf_renderer import render_report_pdf
from framework_mvp.reporting.report_data import (
    ERWARTETE_BESTANDTEIL_IDS,
    ReportDataFehler,
    build_report_data,
)
from framework_mvp.workspace import WorkspaceKonfiguration


def _information(referenz: str, wert: object, artefakt: str = "E*") -> dict[str, object]:
    return {
        "informations_id": str(uuid4()),
        "strukturreferenz": referenz,
        "wert": wert,
        "herkunftsartefakt": artefakt,
        "herkunftsartefakt_id": str(uuid4()),
        "herkunftsartefakt_sha256": "a" * 64,
        "uebernahmeart": "metadatenzusammenfassung",
    }


def _k_stern(*, neue_felder: bool = True) -> dict[str, object]:
    projekt_id, analyse_id = uuid4(), uuid4()
    bestandteile = []
    for bestandteil_id in ERWARTETE_BESTANDTEIL_IDS:
        informationen: list[dict[str, object]] = []
        menschliche_eintraege: list[dict[str, object]] = []
        if bestandteil_id == "problemstellung":
            informationen.append(
                _information("untersuchungsauftrag.problemstellung", "Materialfluss prüfen", "U")
            )
        elif bestandteil_id == "aktivitaeten":
            informationen.append(_information("sichtbare_aktivitaeten", ["A", "B"], "P"))
        elif bestandteil_id == "warteschlangen" and neue_felder:
            informationen.append(
                _information(
                    "strukturierte_ergebnisse.warteschlangen_und_wartezeiten",
                    {
                        "status": "ableitbar",
                        "berechnungsregel": "Start(B) − Ende(A)",
                        "uebergaenge": [
                            {
                                "von_aktivitaet": "A",
                                "zu_aktivitaet": "B",
                                "statistik": {
                                    "anzahl": 2,
                                    "mittelwert_sekunden": 90.0,
                                    "median_sekunden": 90.0,
                                },
                            }
                        ],
                    },
                    "A_G",
                )
            )
        elif bestandteil_id == "ressourcen" and neue_felder:
            informationen.append(
                _information(
                    "strukturierte_ergebnisse.ressourcen",
                    {
                        "modus": "manuell",
                        "herkunft": "menschlich bestätigte Zuordnung in Schritt 7",
                        "quellspalte": "",
                        "zuordnungen": [
                            {"aktivitaet": "A", "ressourcen": ["M1", "M2"]}
                        ],
                    },
                    "A_G",
                )
            )
        elif bestandteil_id == "datenauswahl_und_daten" and neue_felder:
            informationen.append(
                _information(
                    "strukturierte_ergebnisse.zeitbezogene_datenauswahl",
                    {
                        "bestaetigte_datenbasis": ["Q", "R", "T", "E*"],
                        "ankunftsregel": (
                            "Erster gültiger kanonischer Ereigniszeitstempel je Fall."
                        ),
                        "zwischenankunftszeit": {
                            "anzahl": 2,
                            "mittelwert_sekunden": 120.0,
                            "median_sekunden": 120.0,
                        },
                        "bearbeitungszeiten": [
                            {
                                "aktivitaet": "A",
                                "statistik": {
                                    "anzahl": 2,
                                    "mittelwert_sekunden": 60.0,
                                    "median_sekunden": 60.0,
                                },
                            }
                        ],
                    },
                    "A_G",
                )
            )
        elif bestandteil_id == "darstellung_der_vorgaenge_des_systems":
            informationen.append(
                _information(
                    "prozessmodell_referenz",
                    {
                        "prozessmodell_id": str(analyse_id),
                        "process_mining_analyse_id": str(analyse_id),
                        "notation": "petrinetz",
                        "relativer_pfad": "modell.pnml",
                    },
                    "P",
                )
            )
        bestandteile.append(
            {
                "bestandteil_id": bestandteil_id,
                "bezeichnung": bestandteil_id.replace("_", " ").title(),
                "validierungsstatus": "fachlich_validiert",
                "urspruenglicher_bestandteil": {
                    "status": "vollstaendig_zugeordnet",
                    "verwendete_quellen": ["E*"],
                    "informationen": informationen,
                },
                "menschliche_eintraege": menschliche_eintraege,
            }
        )
    return {
        "artefaktart": "fachlich_validiertes_modell_k_stern",
        "artefaktversion": 1,
        "projekt_id": str(projekt_id),
        "k_stern_id": str(uuid4()),
        "validierungslauf_id": str(uuid4()),
        "erstellt_am": "2026-08-12T10:00:00+00:00",
        "modellbestandteile": bestandteile,
        "gesamtvalidierung": {
            "status": "fachlich_validiert",
            "validierungsvermerk": "Geprüft",
            "menschlich_bestaetigt": True,
        },
        "behandlungen_offener_eintraege": [],
        "k_referenz": {},
        "o_referenz": {},
        "eingabefingerabdruck": "b" * 64,
        "entscheidungsfingerabdruck": "c" * 64,
        "gesamtpruefsumme": "d" * 64,
    }


def test_build_report_data_projiziert_neue_felder_ohne_k_stern_mutation() -> None:
    k_stern = _k_stern()
    vorher = copy.deepcopy(k_stern)

    report = build_report_data(k_stern)

    assert k_stern == vorher
    assert report["warteschlangen"]["wartestellenhinweise"][0]["anzahl"] == 2
    assert report["ressourcen"]["aktivitaet_ressourcen"] == [
        {"aktivitaet": "A", "ressourcen": ["M1", "M2"]}
    ]
    assert report["ressourcen"]["zuordnungsmodus"] == "manuell"
    assert report["ressourcen"]["zuordnungsherkunft"].endswith("Schritt 7")
    assert report["daten"]["zeitbezogene_datenauswahl"]["zwischenankunftszeit"][
        "median_sekunden"
    ] == 120.0


def test_aelteres_k_stern_ohne_optionale_felder_bleibt_renderbar(tmp_path: Path) -> None:
    report = resolve_report_assets(
        build_report_data(_k_stern(neue_felder=False)), workspace_root=tmp_path
    )

    assert report["warteschlangen"]["wartestellenhinweise"] == []
    assert report["ressourcen"]["aktivitaet_ressourcen"] == []
    assert report["ressourcen"]["manuelle_aktivitaet_ressourcen"] == []
    assert "<!DOCTYPE html>" in render_report_html(report)
    ziel = render_report_pdf(report, tmp_path / "alt.pdf")
    assert ziel.read_bytes().startswith(b"%PDF-")


def test_automatische_und_manuelle_ressourcen_werden_gleichwertig_mit_ursprung_berichtet() -> None:
    manuell = build_report_data(_k_stern())
    automatisch_k = _k_stern()
    bestandteile = cast(list[dict[str, Any]], automatisch_k["modellbestandteile"])
    ressourcen = next(
        wert
        for wert in bestandteile
        if wert["bestandteil_id"] == "ressourcen"
    )
    information = ressourcen["urspruenglicher_bestandteil"]["informationen"][0]
    information["wert"]["modus"] = "automatisch"
    information["wert"]["herkunft"] = "kanonische Ressourcenspalte in E*"

    automatisch = build_report_data(automatisch_k)

    assert automatisch["ressourcen"]["aktivitaet_ressourcen"] == manuell["ressourcen"][
        "aktivitaet_ressourcen"
    ]
    assert automatisch["ressourcen"]["zuordnungsmodus"] == "automatisch"
    assert automatisch["ressourcen"]["zuordnungsherkunft"].startswith("kanonische")


def test_build_report_data_weist_unvollstaendige_struktur_kontrolliert_ab() -> None:
    k_stern = _k_stern()
    k_stern["modellbestandteile"] = []
    with pytest.raises(ReportDataFehler, match="Fehlend"):
        build_report_data(k_stern)


def test_asset_resolver_loest_realen_workspace_und_optionale_svgs_auf(tmp_path: Path) -> None:
    report = build_report_data(_k_stern())
    projekt_id = report["projekt"]["projekt_id"]
    analyse_id = report["prozessdarstellung"]["process_mining_analyse_id"]
    ordner = tmp_path / "projects" / projekt_id / "process_mining"
    ordner.mkdir(parents=True)
    (ordner / f"{analyse_id}.model.svg").write_text(
        '<?xml version="1.0"?><svg><text>Modell</text></svg>', encoding="utf-8"
    )
    (ordner / f"{analyse_id}.dfg.svg").write_text("<svg><text>DFG</text></svg>", encoding="utf-8")

    aufgeloest = resolve_report_assets(report, workspace_root=tmp_path)

    assert aufgeloest["prozessdarstellung"]["svg_inline"].startswith("<svg")
    assert aufgeloest["prozessdarstellung"]["dfg_svg_inline"].startswith("<svg")
    assert aufgeloest["prozessdarstellung"]["process_tree_svg_inline"] is None
    assert aufgeloest["prozessdarstellung"]["assets"] == {
        "modell_svg": True,
        "dfg_svg": True,
        "process_tree_svg": False,
    }


def test_asset_resolver_toleriert_fehlende_und_verwirft_ungueltige_svgs(
    tmp_path: Path,
) -> None:
    report = build_report_data(_k_stern())
    ohne = resolve_report_assets(report, workspace_root=tmp_path)
    assert not any(ohne["prozessdarstellung"]["assets"].values())
    projekt_id = report["projekt"]["projekt_id"]
    analyse_id = report["prozessdarstellung"]["process_mining_analyse_id"]
    ordner = tmp_path / "projects" / projekt_id / "process_mining"
    ordner.mkdir(parents=True)
    (ordner / f"{analyse_id}.model.svg").write_text("kein SVG", encoding="utf-8")

    with pytest.raises(ReportAssetFehler, match="kein gültiges SVG"):
        resolve_report_assets(report, workspace_root=tmp_path)


def test_html_renderer_bettet_die_einzige_css_quelle_und_svgs_ein(tmp_path: Path) -> None:
    report = resolve_report_assets(build_report_data(_k_stern()), workspace_root=tmp_path)
    css = (template_verzeichnis() / "report_html.css").read_text(encoding="utf-8")

    html = render_report_html(report)

    assert '<link rel="stylesheet" href="report_html.css">' not in html
    assert f"<style>\n{css}\n</style>" in html
    assert "Übergangswartezeiten aus Schritt 7" in html
    assert "Aktivität-Ressourcen-Zuordnungen" in html
    assert "menschlich bestätigte Zuordnung in Schritt 7" in html
    assert "Zwischenankunftszeit" in html
    assert "Ende(A) − Start(A)" in html


def test_pdf_renderer_verwendet_pdf_template_und_css(tmp_path: Path) -> None:
    report = resolve_report_assets(build_report_data(_k_stern()), workspace_root=tmp_path)
    template = template_verzeichnis() / "report_pdf.html"
    css = template_verzeichnis() / "report_pdf.css"
    assert 'href="report_pdf.css"' in template.read_text(encoding="utf-8")
    assert "@page" in css.read_text(encoding="utf-8")

    ziel = render_report_pdf(report, tmp_path / "bericht.pdf")

    assert ziel.read_bytes().startswith(b"%PDF-")


def test_service_uebergibt_identische_gemeinsame_reportdaten_an_beide_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    k_stern = _k_stern()
    aufgeloest = {"report_data_version": 1, "gemeinsam": object()}
    aufrufe = {"build": 0, "resolve": 0}
    renderer_ids: list[int] = []

    def build(wert):  # type: ignore[no-untyped-def]
        assert wert is k_stern
        aufrufe["build"] += 1
        return {"report_data_version": 1}

    def resolve(wert, *, workspace_root):  # type: ignore[no-untyped-def]
        assert wert == {"report_data_version": 1}
        assert workspace_root == tmp_path
        aufrufe["resolve"] += 1
        return aufgeloest

    def html_renderer(wert):  # type: ignore[no-untyped-def]
        renderer_ids.append(id(wert))
        return "<html></html>"

    def pdf_renderer(wert, ziel):  # type: ignore[no-untyped-def]
        renderer_ids.append(id(wert))
        Path(ziel).write_bytes(b"%PDF-test")
        return Path(ziel)

    monkeypatch.setattr(ausgabe_modul, "build_report_data", build)
    monkeypatch.setattr(ausgabe_modul, "resolve_report_assets", resolve)
    monkeypatch.setattr(ausgabe_modul, "render_report_html", html_renderer)
    monkeypatch.setattr(ausgabe_modul, "render_report_pdf", pdf_renderer)
    validierungen = SimpleNamespace(uebergabe_schritt10=lambda *_: k_stern)
    service = ModellausgabeService(
        cast(ModellvalidierungService, validierungen), WorkspaceKonfiguration(tmp_path)
    )

    ergebnis = service.erzeugen(
        validierungslauf_id=UUID(str(k_stern["validierungslauf_id"])),
        projekt_id=UUID(str(k_stern["projekt_id"])),
        k_stern_id=UUID(str(k_stern["k_stern_id"])),
        html=True,
        pdf=True,
    )

    assert aufrufe == {"build": 1, "resolve": 1}
    assert renderer_ids == [id(aufgeloest), id(aufgeloest)]
    assert ergebnis.report_html == b"<html></html>"
    assert ergebnis.report_pdf == b"%PDF-test"


def test_service_uebersetzt_reportingfehler_in_die_anwendungsschicht(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    k_stern = _k_stern()
    monkeypatch.setattr(
        ausgabe_modul,
        "build_report_data",
        lambda _: (_ for _ in ()).throw(ReportDataFehler("inkompatibel")),
    )
    service = ModellausgabeService(
        cast(
            ModellvalidierungService,
            SimpleNamespace(uebergabe_schritt10=lambda *_: k_stern),
        ),
        WorkspaceKonfiguration(tmp_path),
    )

    with pytest.raises(Importintegritaetsfehler, match="inkompatibel"):
        service.erzeugen(
            validierungslauf_id=UUID(str(k_stern["validierungslauf_id"])),
            projekt_id=UUID(str(k_stern["projekt_id"])),
            k_stern_id=UUID(str(k_stern["k_stern_id"])),
            html=True,
            pdf=False,
        )


def test_alte_pdf_excel_und_browser_print_logik_ist_nicht_mehr_produktiv() -> None:
    assert not hasattr(ausgabe_modul, "_pdf_erzeugen")
    assert not hasattr(ausgabe_modul, "_excel_erzeugen")
    ui_quelltext = Path("src/framework_mvp/ui/pages/modellausgabe.py").read_text(encoding="utf-8")
    assert "window.print" not in ui_quelltext
    assert "excel_xlsx" not in ui_quelltext
