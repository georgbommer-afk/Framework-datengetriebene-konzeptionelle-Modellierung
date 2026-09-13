"""Persistenzvertrag für die selektiven Folgen einer KPI-only-Änderung."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from framework_mvp.application.aktive_lineage_service import (
    AktiveLineageService,
    LineageEndpunkt,
)
from framework_mvp.application.fortschritt_service import (
    FACHLICHE_UNTERSCHRITTE,
    VOLLSTAENDIGER_ABSCHLUSS,
)
from framework_mvp.bootstrap import erstelle_projekt_service
from framework_mvp.domain.models import (
    LogistischeZielgroesse,
    Projektfortschritt,
    Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.persistence.sqlite_zugriffs_repository import (
    SQLiteZugriffsRepository,
)


def _auftrag(kpis: tuple[str, ...]) -> Untersuchungsauftrag:
    return Untersuchungsauftrag(
        "Problem",
        "Leistung bewerten",
        Systemtyp.PRODUKTION,
        "Werk",
        logistische_zielgroessen=(
            LogistischeZielgroesse.LIEFERFAEHIGKEIT,
            LogistischeZielgroesse.NACHARBEIT,
        ),
        ausgewaehlte_kpi_ids=kpis,
    )


def _referenzen() -> dict[str, UUID]:
    return {
        "aktuelle_datenquellen_id": uuid4(),
        "aktueller_zwischendatensatz_id": uuid4(),
        "aktuelle_mappingtabelle_id": uuid4(),
        "aktuelle_mapping_id": uuid4(),
        "mapping_id": uuid4(),
        "aktuelle_event_log_konfiguration_id": uuid4(),
        "aktuelles_event_log_id": uuid4(),
        "event_log_id": uuid4(),
        "aktuelle_freigabe_id": uuid4(),
        "freigegebenes_event_log_id": uuid4(),
        "aktuelle_analyse_id": uuid4(),
        "aktuelles_prozessmodell_id": uuid4(),
        "aktuelle_discovery_ergebnisse_id": uuid4(),
        "aktuelle_aggregations_id": uuid4(),
        "aktuelle_modellableitungs_id": uuid4(),
        "aktuelle_k_id": uuid4(),
        "aktuelle_o_id": uuid4(),
        "aktuelle_validierungslauf_id": uuid4(),
        "aktuelle_k_stern_id": uuid4(),
    }


def test_kpi_only_kuerzt_persistierte_lineage_bis_p_a_d_und_setzt_schritt_sieben(tmp_path) -> None:  # type: ignore[no-untyped-def]
    datenbank = tmp_path / "framework.sqlite"
    projekte = erstelle_projekt_service(datenbank)
    projekt = projekte.projekt_anlegen(
        bezeichnung="Fortgeschritten",
        untersuchungsauftrag=_auftrag(("servicegrad",)),
    )
    lineage = AktiveLineageService(datenbank)
    alle_referenzen = _referenzen()
    vorher = lineage.aktivieren(projekt.projekt_id, LineageEndpunkt.K_STERN, alle_referenzen)
    zugriff = SQLiteZugriffsRepository(datenbank)
    zugriff.fortschritt_speichern(
        Projektfortschritt(
            projekt_id=projekt.projekt_id,
            framework_schritt=10,
            fachlicher_unterschritt=FACHLICHE_UNTERSCHRITTE[10][-1],
            fortschritt_zaehler=sum(VOLLSTAENDIGER_ABSCHLUSS),
            fortschritt_nenner=sum(map(len, FACHLICHE_UNTERSCHRITTE.values())),
            phase=3,
            status="abgeschlossen",
            gespeichert_am=datetime.now(UTC),
            revision=1,
            abgeschlossene_unterschritte=VOLLSTAENDIGER_ABSCHLUSS,
        )
    )

    umbenannt = projekte.projekt_aktualisieren(
        projekt.projekt_id,
        bezeichnung="Nur Anzeige geändert",
        untersuchungsauftrag=projekt.untersuchungsauftrag,
        status=projekt.status,
    )
    nach_umbenennung = lineage.laden(projekt.projekt_id)
    assert nach_umbenennung == vorher

    projekte.projekt_aktualisieren(
        projekt.projekt_id,
        bezeichnung=umbenannt.bezeichnung,
        untersuchungsauftrag=replace(
            projekt.untersuchungsauftrag,
            ausgewaehlte_kpi_ids=("servicegrad", "nacharbeitsquote_rr"),
        ),
        status=projekt.status,
    )

    nach_neustart = AktiveLineageService(datenbank).laden(projekt.projekt_id)
    assert nach_neustart is not None
    assert nach_neustart.endpunkt is LineageEndpunkt.P_A_D
    for schluessel in (
        "aktueller_zwischendatensatz_id",
        "aktuelle_mappingtabelle_id",
        "aktuelle_event_log_konfiguration_id",
        "aktuelles_event_log_id",
        "aktuelle_freigabe_id",
        "aktuelle_analyse_id",
        "aktuelles_prozessmodell_id",
        "aktuelle_discovery_ergebnisse_id",
    ):
        assert nach_neustart.referenzen[schluessel] == vorher.referenzen[schluessel]
    for schluessel in (
        "aktuelle_aggregations_id",
        "aktuelle_modellableitungs_id",
        "aktuelle_k_id",
        "aktuelle_o_id",
        "aktuelle_validierungslauf_id",
        "aktuelle_k_stern_id",
    ):
        assert schluessel not in nach_neustart.referenzen

    fortschritt = SQLiteZugriffsRepository(datenbank).fortschritt_laden(projekt.projekt_id)
    assert fortschritt is not None
    assert fortschritt.framework_schritt == 7
    assert fortschritt.fachlicher_unterschritt == FACHLICHE_UNTERSCHRITTE[7][0]
    assert fortschritt.abgeschlossene_unterschritte[:6] == tuple(
        len(FACHLICHE_UNTERSCHRITTE[index]) for index in range(1, 7)
    )
    assert fortschritt.abgeschlossene_unterschritte[6:] == (0, 0, 0, 0)
    assert fortschritt.status == "in_bearbeitung"


def test_kpi_only_vor_p_a_d_belaesst_das_bisherige_verhalten(tmp_path) -> None:  # type: ignore[no-untyped-def]
    datenbank = tmp_path / "framework.sqlite"
    projekte = erstelle_projekt_service(datenbank)
    projekt = projekte.projekt_anlegen(
        bezeichnung="Früh",
        untersuchungsauftrag=_auftrag(("servicegrad",)),
    )
    lineage = AktiveLineageService(datenbank)
    vorher = lineage.aktivieren(
        projekt.projekt_id,
        LineageEndpunkt.E_STERN,
        _referenzen(),
    )

    projekte.projekt_aktualisieren(
        projekt.projekt_id,
        bezeichnung=projekt.bezeichnung,
        untersuchungsauftrag=replace(
            projekt.untersuchungsauftrag,
            ausgewaehlte_kpi_ids=("servicegrad", "nacharbeitsquote_rr"),
        ),
        status=projekt.status,
    )

    assert AktiveLineageService(datenbank).laden(projekt.projekt_id) == vorher
