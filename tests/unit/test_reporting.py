"""Verträge der gemeinsamen Reporting-Pipeline für Schritt 10."""

import copy
from io import BytesIO
from numbers import Real
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from openpyxl import load_workbook

import framework_mvp.application.modellausgabe_service as ausgabe_modul
import framework_mvp.reporting.xlsx_renderer as xlsx_modul
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
from framework_mvp.reporting.xlsx_renderer import SHEET_NAMES, render_report_xlsx
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
                        "potenzielle_wartezeiten": [
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
                        "zuordnungen": [{"aktivitaet": "A", "ressourcen": ["M1", "M2"]}],
                    },
                    "A_G",
                )
            )
        elif bestandteil_id == "vereinfachungen" and neue_felder:
            informationen.append(
                _information(
                    "strukturierte_ergebnisse.vereinfachungen.etl_abstraktionen",
                    [
                        {
                            "quellspalte": "Von",
                            "vergleichsart": "Beginnt mit",
                            "suchwert_muster": "HRL-04-",
                            "vorher_muster": "HRL-04-*",
                            "abstraktionswert": "HRL-04",
                            "zielspalte": "Von_aggregiert",
                            "betroffene_beobachtungen": 185,
                            "originalwerte_erhalten": True,
                        }
                    ],
                    "A_G",
                )
            )
        elif bestandteil_id == "datenauswahl" and neue_felder:
            informationen.append(
                _information(
                    "strukturierte_ergebnisse.zeitbezogene_datenauswahl",
                    {
                        "bestaetigte_datenbasis": ["Q", "R", "T", "E*"],
                        "ankunftsregel": (
                            "Erster gültiger kanonischer Ereigniszeitstempel je Fall."
                        ),
                        "zwischenankunftszeiten": [
                            {
                                "definition": {"bezeichnung": "Auftragseingang"},
                                "statistik": {
                                    "anzahl": 2,
                                    "mittelwert_sekunden": 120.0,
                                    "median_sekunden": 120.0,
                                },
                            }
                        ],
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
                        "potenzielle_wartezeiten": [
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
    assert (
        report["daten"]["zeitbezogene_datenauswahl"]["zwischenankunftszeiten"][0][
            "statistik"
        ]["median_sekunden"]
        == 120.0
    )
    assert len(report["modellbestandteile"]) == 16


def test_etl_abstraktionen_sind_strukturiert_und_in_html_und_pdf_ausgebbar(
    tmp_path: Path,
) -> None:
    report = build_report_data(_k_stern())

    assert report["vereinfachungen"]["etl_abstraktionen"] == [
        {
            "quellspalte": "Von",
            "vergleichsart": "Beginnt mit",
            "suchwert_muster": "HRL-04-",
            "vorher_muster": "HRL-04-*",
            "abstraktionswert": "HRL-04",
            "zielspalte": "Von_aggregiert",
            "betroffene_beobachtungen": 185,
            "originalwerte_erhalten": True,
        }
    ]
    html = render_report_html(report)
    assert "Regelbasierte ETL-Abstraktionen" in html
    assert "HRL-04-*" in html
    assert "185 Beobachtungen" in html

    ziel = render_report_pdf(report, tmp_path / "abstraktionen.pdf")
    assert ziel.read_bytes().startswith(b"%PDF-")


def test_report_nutzt_potenzielle_wartezeiten_aus_datenauswahl_ohne_warteschlange(
) -> None:
    k_stern = _k_stern()
    bestandteile = cast(list[dict[str, Any]], k_stern["modellbestandteile"])
    warteschlangen = next(
        wert
        for wert in bestandteile
        if wert["bestandteil_id"] == "warteschlangen"
    )
    warteschlangen["urspruenglicher_bestandteil"]["informationen"] = []

    report = build_report_data(k_stern)

    assert report["warteschlangen"]["wartestellenhinweise"] == [
        {
            "uebergang": {"von": "A", "zu": "B"},
            "anzahl": 2,
            "mittlere_wartezeit_sekunden": 90.0,
            "mediane_wartezeit_sekunden": 90.0,
        }
    ]


def test_xlsx_renderer_erzeugt_zehn_geordnete_lesbare_arbeitsblaetter() -> None:
    report = build_report_data(
        _k_stern(),
        projektbezeichnung="Fördertechnik Süd",
        softwareversion="0.1.0-test",
    )

    inhalt = render_report_xlsx(report)
    arbeitsmappe = load_workbook(BytesIO(inhalt), data_only=False)

    assert arbeitsmappe.sheetnames == list(SHEET_NAMES)
    assert all(not blatt.sheet_view.showGridLines for blatt in arbeitsmappe.worksheets)
    assert arbeitsmappe["Übersicht"]["B6"].value == "Fördertechnik Süd"
    assert any(
        zelle.value == "Geprüft"
        for zeile in arbeitsmappe["Validierung"].iter_rows()
        for zelle in zeile
    )
    assert not any(
        isinstance(zelle.value, str) and zelle.value.startswith("=")
        for blatt in arbeitsmappe.worksheets
        for zeile in blatt.iter_rows()
        for zelle in zeile
    )
    assert all(
        zelle.font.name == "Calibri"
        for blatt in arbeitsmappe.worksheets
        for zeile in blatt.iter_rows()
        for zelle in zeile
        if zelle.value is not None
    )
    datenblatt = arbeitsmappe["Daten & Datenauswahl"]
    kopfzeile = next(
        zeile
        for zeile in datenblatt.iter_rows()
        if zeile[0].value == "Kennwert" and zeile[1].value == "Bezug"
    )
    kopfwerte = [zelle.value for zelle in kopfzeile if zelle.value is not None]
    assert "Minimum" not in kopfwerte and "Maximum" not in kopfwerte
    statistikwerte = [
        zeile
        for zeile in datenblatt.iter_rows(min_row=kopfzeile[0].row + 1, values_only=False)
        if zeile[0].value in {"Zwischenankunftszeit", "Bearbeitungszeit", "Wartezeit"}
    ]
    assert {zeile[0].value for zeile in statistikwerte} == {
        "Zwischenankunftszeit",
        "Bearbeitungszeit",
        "Wartezeit",
    }
    assert all(isinstance(zeile[2].value, int) for zeile in statistikwerte)
    assert all(isinstance(zeile[3].value, Real) for zeile in statistikwerte)
    assert all(zeile[3].number_format == "0.00" for zeile in statistikwerte)
    assert len(
        {
            datenblatt.column_dimensions[spalte].width
            for spalte in ("A", "B", "C", "D", "E", "F", "G")
        }
    ) > 2


def test_xlsx_renderer_bettet_prozessgrafik_als_png_ein(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = build_report_data(_k_stern())
    projekt_id = report["projekt"]["projekt_id"]
    analyse_id = report["prozessdarstellung"]["process_mining_analyse_id"]
    ordner = tmp_path / "projects" / projekt_id / "process_mining"
    ordner.mkdir(parents=True)
    (ordner / f"{analyse_id}.model.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"></svg>',
        encoding="utf-8",
    )
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00"
        b"\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    monkeypatch.setattr(xlsx_modul, "_svg_zu_png", lambda _: png)

    inhalt = render_report_xlsx(resolve_report_assets(report, workspace_root=tmp_path))
    arbeitsmappe = load_workbook(BytesIO(inhalt))

    assert len(arbeitsmappe["Prozessmodell"]._images) == 1


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
    ressourcen = next(wert for wert in bestandteile if wert["bestandteil_id"] == "ressourcen")
    information = ressourcen["urspruenglicher_bestandteil"]["informationen"][0]
    information["wert"]["modus"] = "automatisch"
    information["wert"]["herkunft"] = "kanonische Ressourcenspalte in E*"

    automatisch = build_report_data(automatisch_k)

    assert (
        automatisch["ressourcen"]["aktivitaet_ressourcen"]
        == manuell["ressourcen"]["aktivitaet_ressourcen"]
    )
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


def test_service_uebergibt_identische_gemeinsame_reportdaten_an_alle_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    k_stern = _k_stern()
    aufgeloest = {"report_data_version": 1, "gemeinsam": object()}
    aufrufe = {"build": 0, "resolve": 0}
    renderer_ids: list[int] = []

    def build(wert, **metadaten):  # type: ignore[no-untyped-def]
        assert wert is k_stern
        assert metadaten == {
            "projektbezeichnung": "Fördertechnik Süd / ÄÖÜ",
            "softwareversion": "1.2",
        }
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

    def xlsx_renderer(wert):  # type: ignore[no-untyped-def]
        renderer_ids.append(id(wert))
        return b"PK-xlsx-test"

    monkeypatch.setattr(ausgabe_modul, "build_report_data", build)
    monkeypatch.setattr(ausgabe_modul, "resolve_report_assets", resolve)
    monkeypatch.setattr(ausgabe_modul, "render_report_html", html_renderer)
    monkeypatch.setattr(ausgabe_modul, "render_report_pdf", pdf_renderer)
    monkeypatch.setattr(ausgabe_modul, "render_report_xlsx", xlsx_renderer)
    validierungen = SimpleNamespace(uebergabe_schritt10=lambda *_: k_stern)
    projekte = SimpleNamespace(
        projekt_laden=lambda projekt_id: SimpleNamespace(
            projekt_id=projekt_id, bezeichnung="Fördertechnik Süd / ÄÖÜ"
        )
    )
    service = ModellausgabeService(
        cast(ModellvalidierungService, validierungen),
        cast(Any, projekte),
        WorkspaceKonfiguration(tmp_path),
    )

    ergebnis = service.erzeugen(
        validierungslauf_id=UUID(str(k_stern["validierungslauf_id"])),
        projekt_id=UUID(str(k_stern["projekt_id"])),
        k_stern_id=UUID(str(k_stern["k_stern_id"])),
        html=True,
        pdf=True,
        xlsx=True,
    )

    assert aufrufe == {"build": 1, "resolve": 1}
    assert renderer_ids == [id(aufgeloest), id(aufgeloest), id(aufgeloest)]
    assert ergebnis.report_html == b"<html></html>"
    assert ergebnis.report_pdf == b"%PDF-test"
    assert ergebnis.report_xlsx == b"PK-xlsx-test"
    assert ergebnis.pdf_dateiname == "Konzeptionelles Modell Fördertechnik Süd ÄÖÜ.pdf"
    assert ergebnis.xlsx_dateiname == "Konzeptionelles Modell Fördertechnik Süd ÄÖÜ.xlsx"


def test_service_uebersetzt_reportingfehler_in_die_anwendungsschicht(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    k_stern = _k_stern()
    monkeypatch.setattr(
        ausgabe_modul,
        "build_report_data",
        lambda _wert, **_metadaten: (_ for _ in ()).throw(ReportDataFehler("inkompatibel")),
    )
    service = ModellausgabeService(
        cast(
            ModellvalidierungService,
            SimpleNamespace(uebergabe_schritt10=lambda *_: k_stern),
        ),
        cast(
            Any,
            SimpleNamespace(
                projekt_laden=lambda projekt_id: SimpleNamespace(
                    projekt_id=projekt_id, bezeichnung="Reporting"
                )
            ),
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


def test_service_verwendet_keinen_projektnamen_einer_fremden_id(tmp_path: Path) -> None:
    k_stern = _k_stern()
    projekt_id = UUID(str(k_stern["projekt_id"]))
    service = ModellausgabeService(
        cast(
            ModellvalidierungService,
            SimpleNamespace(uebergabe_schritt10=lambda *_: k_stern),
        ),
        cast(
            Any,
            SimpleNamespace(
                projekt_laden=lambda _: SimpleNamespace(
                    projekt_id=uuid4(), bezeichnung="Fremdes Projekt"
                )
            ),
        ),
        WorkspaceKonfiguration(tmp_path),
    )

    with pytest.raises(Importintegritaetsfehler, match="Projektbezeichnung"):
        service.erzeugen(
            validierungslauf_id=UUID(str(k_stern["validierungslauf_id"])),
            projekt_id=projekt_id,
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
