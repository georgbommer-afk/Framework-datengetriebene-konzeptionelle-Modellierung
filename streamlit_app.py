"""Öffentlicher Einstieg mit isoliertem Gastmodus und privaten OIDC-Kursgruppen."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import streamlit as st

from framework_mvp import __version__
from framework_mvp.application.autorisierung import AutorisierungsService
from framework_mvp.application.gast_service import GAST_HINWEIS, GastService
from framework_mvp.application.kursdashboard_service import KursdashboardService
from framework_mvp.application.kursgruppen_service import KursgruppenLoeschService
from framework_mvp.application.mandanten_projekt_service import (
    AutorisierterLoeschService,
    MandantenProjektService,
)
from framework_mvp.application.systemadmin_service import SystemadminService
from framework_mvp.bootstrap import (
    ermittle_datenbankpfad,
    ermittle_gast_ttl,
    erstelle_bereinigungs_service,
    erstelle_datenimport_service,
    erstelle_datenqualitaet_service,
    erstelle_datenquelle_service,
    erstelle_einladungs_service,
    erstelle_ergebnisaggregation_service,
    erstelle_event_log_konfigurations_service,
    erstelle_event_log_service,
    erstelle_fortschritt_service,
    erstelle_identitaets_service,
    erstelle_importvorgang_service,
    erstelle_kursarchiv_service,
    erstelle_kursgruppen_service,
    erstelle_loesch_service,
    erstelle_mappingtabelle_service,
    erstelle_modellableitung_service,
    erstelle_modellausgabe_service,
    erstelle_modellvalidierung_service,
    erstelle_process_mining_service,
    erstelle_projekt_service,
    erstelle_projektarchiv_service,
    erstelle_transformations_service,
    erstelle_zugriffs_repository,
)
from framework_mvp.domain.exceptions import Domaenenfehler, ZugriffVerweigert
from framework_mvp.domain.models.zugriff import (
    GlobaleRolle,
    Gruppenaktion,
    Gruppenrolle,
    Mitgliedschaftsstatus,
    Projektaktion,
    Zugriffskontext,
)
from framework_mvp.infrastructure.dateiimport.datei_metadaten import bereinige_dateiname
from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion
from framework_mvp.ui.cloud_access import GebundenerLoeschService, GebundenerProjektService
from framework_mvp.ui.fortschritt import (
    fortschrittsstand,
    fortschrittsstand_aus_persistenz,
    zeige_gesamtfortschritt,
)
from framework_mvp.ui.navigation import FRAMEWORK_BEREICHE
from framework_mvp.ui.oidc import lokaler_test_claims, oidc_konfiguration_ermitteln
from framework_mvp.ui.pages.datenqualitaet import zeige_datenqualitaet_seite
from framework_mvp.ui.pages.ergebnisaggregation import zeige_ergebnisaggregation_seite
from framework_mvp.ui.pages.etl import zeige_etl_seite
from framework_mvp.ui.pages.event_log import zeige_event_log_seite
from framework_mvp.ui.pages.modellableitung import zeige_modellableitung_seite
from framework_mvp.ui.pages.modellausgabe import zeige_modellausgabe_seite
from framework_mvp.ui.pages.modellvalidierung import zeige_modellvalidierung_seite
from framework_mvp.ui.pages.process_mining import zeige_process_mining_seite
from framework_mvp.ui.pages.projektverwaltung import zeige_projektverwaltung
from framework_mvp.ui.pages.semantisches_mapping import zeige_semantisches_mapping
from framework_mvp.workspace import WorkspaceKonfiguration

st.set_page_config(page_title="Framework-MVP", page_icon="🏭", layout="wide")
st.title("Datengetriebene konzeptionelle Modellierung")
st.caption(f"Framework-MVP · Version {__version__}")

workspace = WorkspaceKonfiguration.ermitteln()
datenbankpfad = ermittle_datenbankpfad()
zugriff = erstelle_zugriffs_repository(datenbankpfad)
autorisierung = AutorisierungsService(zugriff)
roh_projekte = erstelle_projekt_service(datenbankpfad)
roh_loeschen = erstelle_loesch_service(datenbankpfad, workspace)


def _secrets() -> dict[str, object]:
    try:
        return dict(st.secrets)
    except Exception:
        return {}


auth_konfiguration = oidc_konfiguration_ermitteln(_secrets())


def _anmeldekontext() -> tuple[Zugriffskontext | None, bool]:
    identitaeten = auth_konfiguration.systemadmin_identitaeten
    if auth_konfiguration.lokaler_testmodus:
        claims = lokaler_test_claims()
        if auth_konfiguration.lokaler_testadmin:
            identitaeten = identitaeten | frozenset({(claims["iss"], claims["sub"])})
        kontext, _ = erstelle_identitaets_service(datenbankpfad).aus_oidc_claims(
            claims, systemadmin_identitaeten=identitaeten
        )
        return kontext, True
    user = st.user
    if bool(getattr(user, "is_logged_in", False)):
        claims = user.to_dict() if hasattr(user, "to_dict") else dict(user)
        kontext, _ = erstelle_identitaets_service(datenbankpfad).aus_oidc_claims(
            claims, systemadmin_identitaeten=identitaeten
        )
        return kontext, True
    geheimnis = st.session_state.get("gast_geheimnis")
    if isinstance(geheimnis, str):
        try:
            return Zugriffskontext.gast(geheimnis), False
        except Domaenenfehler:
            st.session_state.pop("gast_geheimnis", None)
    return None, False


try:
    erstelle_bereinigungs_service(datenbankpfad, workspace).opportunistisch(limit=10)
except Exception:
    # Die App bleibt bei einem vorübergehenden Bereinigungsfehler benutzbar.
    pass

try:
    kontext, ist_angemeldet = _anmeldekontext()
except NichtUnterstuetzteSchemaversion as fehler:
    st.error(str(fehler))
    st.stop()


def _gast_starten() -> None:
    mandanten = MandantenProjektService(
        roh_projekte, zugriff, autorisierung, gast_ttl=ermittle_gast_ttl()
    )
    loeschen = AutorisierterLoeschService(roh_loeschen, autorisierung)
    demo = GastService(mandanten, loeschen).demo_starten()
    st.session_state.gast_geheimnis = demo.kontext.gast_geheimnis
    st.session_state.gast_projekt_id = str(demo.projekt.projekt_id)
    st.session_state.aktuelles_projekt_id = str(demo.projekt.projekt_id)
    st.session_state.ausgewaehlte_projekt_id = demo.projekt.projekt_id
    st.rerun()


def _startseite() -> None:
    st.header("Willkommen")
    st.write(
        "Testen Sie das Framework anonym mit temporärer Speicherung oder öffnen Sie "
        "nach der Anmeldung eine private Kursgruppe."
    )
    links, rechts = st.columns(2)
    with links:
        st.subheader("Temporärer Demomodus")
        st.caption("Keine Anmeldung · isoliertes Projekt · Export als portable Sicherung")
        if st.button("Ohne Anmeldung testen", type="primary", width="stretch"):
            _gast_starten()
    with rechts:
        st.subheader("Private Kursgruppe")
        st.caption("OIDC-Anmeldung · nur ausdrücklich zugewiesene Gruppen und Projekte")
        if st.button(
            "Anmelden / Kursgruppe öffnen",
            disabled=not auth_konfiguration.konfiguriert,
            width="stretch",
        ):
            st.login()
        if not auth_konfiguration.konfiguriert:
            st.info("Für Kursgruppen ist in diesem Deployment noch kein OIDC konfiguriert.")


if kontext is None:
    _startseite()
    st.stop()

if auth_konfiguration.lokaler_testmodus:
    st.warning("Lokaler Authentifizierungs-Testmodus ist ausdrücklich aktiviert.")
if kontext.gast_geheimnis is not None:
    st.warning(GAST_HINWEIS)

globale_rollen = (
    frozenset()
    if kontext.benutzer_id is None
    else zugriff.globale_rollen_laden(kontext.benutzer_id)
)

if ist_angemeldet and "invite" in st.query_params:
    token = str(st.query_params.get("invite", ""))
    try:
        mitgliedschaft = erstelle_einladungs_service(datenbankpfad).einloesen(kontext, token)
    except ZugriffVerweigert:
        st.error("Die Einladung ist nicht verfügbar.")
    else:
        st.session_state.aktive_gruppen_id = str(mitgliedschaft.gruppen_id)
        del st.query_params["invite"]
        st.success("Sie sind der Kursgruppe beigetreten.")


def _gruppenrahmen() -> UUID | None:
    if kontext is None or kontext.benutzer_id is None:
        return None
    kurs_service = erstelle_kursgruppen_service(datenbankpfad)
    gruppen = kurs_service.gruppen_auflisten(kontext)
    st.sidebar.subheader("Kursgruppen")
    if gruppen:
        auswahl = st.sidebar.selectbox(
            "Private Kursgruppe",
            gruppen,
            format_func=lambda gruppe: gruppe.bezeichnung,
            key="cloud_gruppenauswahl",
        )
        st.session_state.aktive_gruppen_id = str(auswahl.gruppen_id)
        aktive_id: UUID | None = auswahl.gruppen_id
    else:
        st.sidebar.caption("Noch keine Kursgruppenmitgliedschaft")
        aktive_id = None
    if globale_rollen.intersection({GlobaleRolle.GRUPPENLEITUNG, GlobaleRolle.SYSTEMADMIN}):
        if st.sidebar.button("Kursgruppe erstellen"):
            st.session_state.kursgruppe_anlegen = True
        if st.session_state.get("kursgruppe_anlegen"):
            with st.sidebar.form("kursgruppe_anlegen_form"):
                name = st.text_input("Bezeichnung der Kursgruppe")
                beschreibung = st.text_input("Beschreibung")
                beginn = st.date_input("Beginn", value=date.today())
                ende = st.date_input("Fachliches Kursende", value=date.today() + timedelta(days=90))
                aufbewahrungstage = st.number_input(
                    "Aufbewahrung nach Kursende (Tage)", min_value=1, max_value=365, value=30
                )
                maximale_projekte = st.number_input(
                    "Maximale Projektanzahl", min_value=1, max_value=500, value=15
                )
                maximale_teilnehmende = st.number_input(
                    "Maximale Teilnehmendenzahl", min_value=1, max_value=10_000, value=100
                )
                speicher_mb = st.number_input(
                    "Maximales Speichervolumen je Projekt (MB)",
                    min_value=10,
                    max_value=2_000,
                    value=200,
                )
                if st.form_submit_button("Kursgruppe speichern", type="primary"):
                    gruppe = kurs_service.gruppe_anlegen(
                        kontext,
                        bezeichnung=name,
                        beschreibung=beschreibung,
                        beginn_am=beginn,
                        ende_am=ende,
                        maximale_teilnehmende=int(maximale_teilnehmende),
                        maximale_projekte=int(maximale_projekte),
                        speicherlimit_pro_projekt_bytes=int(speicher_mb) * 1024 * 1024,
                        aufbewahrung_bis=datetime.combine(
                            ende + timedelta(days=int(aufbewahrungstage)),
                            datetime.min.time(),
                            tzinfo=UTC,
                        ),
                    )
                    st.session_state.aktive_gruppen_id = str(gruppe.gruppen_id)
                    st.session_state.kursgruppe_anlegen = False
                    st.rerun()
        kursimport = st.sidebar.file_uploader(
            "Kursgruppe importieren", type=["zip"], key="cloud_kursimport"
        )
        if kursimport is not None and st.sidebar.button("Kursarchiv prüfen und importieren"):
            try:
                gruppe = erstelle_kursarchiv_service(datenbankpfad, workspace).importieren(
                    kontext,
                    kursimport.getvalue(),
                    systemadmin_wiederherstellung=(GlobaleRolle.SYSTEMADMIN in globale_rollen),
                )
            except Domaenenfehler as fehler:
                st.sidebar.error(str(fehler))
            else:
                st.session_state.aktive_gruppen_id = str(gruppe.gruppen_id)
                st.rerun()
    return aktive_id


aktive_gruppen_id = _gruppenrahmen()


def _kursaktionen(gruppen_id: UUID | None) -> None:
    if gruppen_id is None or kontext is None:
        return
    if not autorisierung.gruppen_zugriff_erlaubt(
        kontext, gruppen_id, Gruppenaktion.EINLADUNGEN_VERWALTEN
    ):
        return
    st.sidebar.subheader("Gruppenleitung")
    if st.sidebar.button("Einladung erzeugen"):
        _, token = erstelle_einladungs_service(datenbankpfad).erstellen(
            kontext, gruppen_id, maximale_nutzungen=1
        )
        st.sidebar.success("Einladungslink (wird nur jetzt vollständig angezeigt):")
        st.sidebar.code(f"?invite={token}")
    einladungs_service = erstelle_einladungs_service(datenbankpfad)
    einladungen = einladungs_service.auflisten(kontext, gruppen_id)
    if einladungen:
        with st.sidebar.expander("Einladungen", expanded=False):
            for einladung in einladungen:
                status = (
                    "widerrufen"
                    if einladung.widerrufen_am is not None
                    else f"{einladung.anzahl_nutzungen}/{einladung.maximale_nutzungen} verwendet"
                )
                st.caption(f"Gültig bis {einladung.laeuft_ab_am:%d.%m.%Y %H:%M} UTC · {status}")
                if einladung.widerrufen_am is None and st.button(
                    "Einladung widerrufen",
                    key=f"einladung_widerrufen_{einladung.einladungs_id}",
                ):
                    einladungs_service.widerrufen(kontext, gruppen_id, einladung.einladungs_id)
                    st.rerun()
    mitgliedschaften = zugriff.gruppenmitgliedschaften_auflisten(gruppen_id)
    aktive_mitglieder = [
        wert for wert in mitgliedschaften if wert.status is Mitgliedschaftsstatus.AKTIV
    ]
    with st.sidebar.expander("Mitglieder und Projektteams", expanded=False):
        for mitgliedschaft in aktive_mitglieder:
            benutzer = zugriff.benutzer_laden(mitgliedschaft.benutzer_id)
            st.caption(
                f"{(benutzer.anzeigename or benutzer.email) if benutzer else 'Mitglied'} · "
                f"{mitgliedschaft.rolle.value}"
            )
        verwaltbar = [
            wert for wert in aktive_mitglieder if wert.rolle is not Gruppenrolle.GRUPPENLEITUNG
        ]
        if verwaltbar:
            auswahl = st.selectbox(
                "Mitglied verwalten",
                verwaltbar,
                format_func=lambda wert: (
                    (benutzer.anzeigename or benutzer.email)
                    if (benutzer := zugriff.benutzer_laden(wert.benutzer_id))
                    else "Mitglied"
                ),
            )
            rolle = st.selectbox(
                "Gruppenrolle",
                (Gruppenrolle.TEILNEHMER, Gruppenrolle.GRUPPENASSISTENZ),
                format_func=lambda wert: wert.value,
            )
            if st.button("Rolle speichern"):
                erstelle_kursgruppen_service(datenbankpfad).mitgliedschaft_setzen(
                    kontext,
                    gruppen_id,
                    auswahl.benutzer_id,
                    rolle=rolle,
                    berechtigungen=(
                        frozenset({"gruppe_lesen", "projekte_lesen", "fortschritt_lesen"})
                        if rolle is Gruppenrolle.GRUPPENASSISTENZ
                        else frozenset()
                    ),
                )
                st.rerun()
            if st.button("Mitglied entfernen"):
                erstelle_kursgruppen_service(datenbankpfad).mitgliedschaft_setzen(
                    kontext,
                    gruppen_id,
                    auswahl.benutzer_id,
                    rolle=auswahl.rolle,
                    status=Mitgliedschaftsstatus.ENTFERNT,
                )
                st.rerun()
            projekt_ids = zugriff.projekt_ids_fuer_gruppe(gruppen_id)
            if projekt_ids:
                projekt_id = st.selectbox(
                    "Projekt zuweisen",
                    projekt_ids,
                    format_func=lambda wert: (
                        projekt.bezeichnung
                        if (projekt := roh_projekte.projekt_laden(wert))
                        else "Projekt"
                    ),
                )
                if st.button("Projektteam zuweisen"):
                    erstelle_kursgruppen_service(datenbankpfad).projekt_zuweisen(
                        kontext,
                        gruppen_id,
                        projekt_id,
                        auswahl.benutzer_id,
                    )
                    st.rerun()
    if st.sidebar.button("Kursgruppe exportieren"):
        st.session_state.kursarchiv = erstelle_kursarchiv_service(
            datenbankpfad, workspace
        ).exportieren(kontext, gruppen_id)
    if archiv := st.session_state.get("kursarchiv"):
        gruppe = zugriff.kursgruppe_laden(gruppen_id)
        name = "Kursgruppe" if gruppe is None else gruppe.bezeichnung
        st.sidebar.warning(
            "Das Archiv kann Projektdateien und personenbezogene Zuordnungshinweise enthalten."
        )
        st.sidebar.download_button(
            "Kursarchiv herunterladen",
            data=archiv,
            file_name=bereinige_dateiname(f"Kursgruppe – {name}.zip"),
            mime="application/zip",
        )
    gruppe = zugriff.kursgruppe_laden(gruppen_id)
    if gruppe and gruppe.aufbewahrung_bis:
        rest = gruppe.aufbewahrung_bis - datetime.now(UTC)
        if timedelta(0) <= rest <= timedelta(days=7):
            st.sidebar.warning(
                f"Aufbewahrung endet in {max(0, rest.days)} Tagen. "
                "Exportieren Sie die Kursgruppe rechtzeitig."
            )
    if st.sidebar.button("Kursgruppe löschen"):
        st.session_state.cloud_kurs_loeschbestaetigung = str(gruppen_id)
    if st.session_state.get("cloud_kurs_loeschbestaetigung") == str(gruppen_id):
        st.sidebar.warning("Alle Projekte dieser Kursgruppe werden dauerhaft gelöscht.")
        loeschen, abbrechen = st.sidebar.columns(2)
        if loeschen.button("Löschen", key="kurs_loeschen_final", type="primary"):
            KursgruppenLoeschService(zugriff, autorisierung, roh_loeschen).gruppe_loeschen(
                kontext, gruppen_id
            )
            st.session_state.pop("aktive_gruppen_id", None)
            st.session_state.pop("cloud_kurs_loeschbestaetigung", None)
            st.rerun()
        if abbrechen.button("Abbrechen", key="kurs_loeschen_abbrechen"):
            st.session_state.pop("cloud_kurs_loeschbestaetigung", None)
            st.rerun()


_kursaktionen(aktive_gruppen_id)


def _projekt_id_aus_session() -> UUID | None:
    roh = st.session_state.get("aktuelles_projekt_id")
    try:
        return None if roh is None else UUID(str(roh))
    except ValueError:
        st.session_state.pop("aktuelles_projekt_id", None)
        return None


def _projektaktionen(projekt_id: UUID | None) -> None:
    if kontext is None:
        return
    st.sidebar.subheader("Projektrahmen")
    import_erlaubt = kontext.gast_geheimnis is not None or (
        aktive_gruppen_id is not None
        and autorisierung.gruppen_zugriff_erlaubt(
            kontext, aktive_gruppen_id, Gruppenaktion.ARCHIVIEREN
        )
    )
    if import_erlaubt:
        upload = st.sidebar.file_uploader(
            "Projekt importieren", type=["zip"], key="cloud_projektimport"
        )
        if upload is not None and st.sidebar.button("Projektarchiv prüfen und importieren"):
            try:
                ergebnis = erstelle_projektarchiv_service(datenbankpfad, workspace).importieren(
                    kontext,
                    upload.getvalue(),
                    ziel_gruppen_id=aktive_gruppen_id,
                )
            except Domaenenfehler as fehler:
                st.sidebar.error(str(fehler))
            else:
                st.session_state.aktuelles_projekt_id = str(ergebnis.projekt_id)
                st.session_state.ausgewaehlte_projekt_id = ergebnis.projekt_id
                if kontext.gast_geheimnis is not None:
                    st.session_state.gast_projekt_id = str(ergebnis.projekt_id)
                st.rerun()
    if projekt_id is None or not autorisierung.projekt_zugriff_erlaubt(
        kontext, projekt_id, Projektaktion.ANSEHEN
    ):
        return
    projekt = roh_projekte.projekt_laden(projekt_id)
    if projekt is None:
        return
    if st.sidebar.button("Projekt exportieren"):
        try:
            st.session_state.projektarchiv = erstelle_projektarchiv_service(
                datenbankpfad, workspace
            ).exportieren(kontext, projekt_id)
        except Domaenenfehler as fehler:
            st.sidebar.error(str(fehler))
    if archiv := st.session_state.get("projektarchiv"):
        st.sidebar.caption("Exportiert wird der letzte gespeicherte fachliche Stand.")
        st.sidebar.warning(
            "Projektarchive sind nicht verschlüsselt und können Originaldaten enthalten."
        )
        name = bereinige_dateiname(
            f"Framework-Projekt – {projekt.bezeichnung} – {date.today().isoformat()}.zip"
        )
        st.sidebar.download_button(
            "Projektarchiv herunterladen",
            data=archiv,
            file_name=name,
            mime="application/zip",
        )


aktive_projekt_id = _projekt_id_aus_session()
_projektaktionen(aktive_projekt_id)

if ist_angemeldet:
    if st.sidebar.button("Abmelden"):
        st.logout()


def _dashboard(gruppen_id: UUID | None) -> None:
    if gruppen_id is None or kontext is None:
        return
    if not autorisierung.gruppen_zugriff_erlaubt(
        kontext, gruppen_id, Gruppenaktion.EINLADUNGEN_VERWALTEN
    ):
        return
    dashboard = KursdashboardService(
        zugriff,
        roh_projekte,
        erstelle_fortschritt_service(datenbankpfad),
        autorisierung,
        workspace,
    ).laden(kontext, gruppen_id)
    if dashboard:
        with st.expander("Projekte und Fortschritt", expanded=False):
            st.dataframe(
                [
                    {
                        "Projekt": zeile.projektname,
                        "Team": ", ".join(zeile.mitglieder) or "Noch nicht zugewiesen",
                        "Phase": zeile.phase,
                        "Schritt": zeile.schritt,
                        "Gesamtfortschritt": f"{zeile.fortschritt_prozent} %",
                        "Letzte Aktivität": zeile.letzte_aktivitaet,
                        "Ablauf": zeile.ablaufdatum,
                        "Speicher": f"{zeile.speicherverbrauch_bytes / 1024 / 1024:.1f} MB",
                    }
                    for zeile in dashboard
                ],
                hide_index=True,
            )


_dashboard(aktive_gruppen_id)


def _systemadmin_bereich() -> None:
    if kontext is None or GlobaleRolle.SYSTEMADMIN not in globale_rollen:
        return
    with st.sidebar.expander("Systemadministration", expanded=False):
        benutzer = zugriff.benutzer_auflisten()
        if benutzer:
            auswahl = st.selectbox(
                "Angemeldete Benutzer",
                benutzer,
                format_func=lambda wert: wert.anzeigename or wert.email or "Benutzer",
            )
            ist_leitung = GlobaleRolle.GRUPPENLEITUNG in zugriff.globale_rollen_laden(
                auswahl.benutzer_id
            )
            beschriftung = (
                "Gruppenleiterfreigabe entziehen"
                if ist_leitung
                else "Als Gruppenleitung freischalten"
            )
            if st.button(beschriftung):
                service = SystemadminService(zugriff, autorisierung)
                if ist_leitung:
                    service.gruppenleitung_entziehen(kontext, auswahl.benutzer_id)
                else:
                    service.gruppenleitung_freischalten(kontext, auswahl.benutzer_id)
                st.rerun()
        gruppen = zugriff.kursgruppen_auflisten_betrieb()
        workspace_bytes = sum(
            datei.stat().st_size
            for datei in workspace.basisverzeichnis.rglob("*")
            if datei.is_file() and not datei.is_symlink()
        )
        projektanzahl = sum(
            len(zugriff.projekt_ids_fuer_gruppe(gruppe.gruppen_id)) for gruppe in gruppen
        )
        st.caption(
            f"Betrieb: {len(gruppen)} Kursgruppen · "
            f"{projektanzahl} Projekte · "
            f"{workspace_bytes / 1024 / 1024:.1f} MB lokaler Speicher"
        )
        if gruppen:
            gruppe = st.selectbox(
                "Kursgruppe sperren",
                gruppen,
                format_func=lambda wert: f"{wert.bezeichnung} ({wert.status.value})",
            )
            if st.button("Ausgewählte Kursgruppe sperren"):
                SystemadminService(zugriff, autorisierung).gruppe_sperren(
                    kontext, gruppe.gruppen_id
                )
                st.rerun()
        if st.button("Bereinigung auslösen"):
            anzahl = SystemadminService(
                zugriff,
                autorisierung,
                erstelle_bereinigungs_service(datenbankpfad, workspace),
            ).bereinigung_ausloesen(kontext)
            st.success(f"{anzahl} abgelaufene Gastprojekte bereinigt.")


_systemadmin_bereich()

if ist_angemeldet and not aktive_gruppen_id and not auth_konfiguration.lokaler_testmodus:
    st.header("Private Kursgruppen")
    if GlobaleRolle.SYSTEMADMIN in globale_rollen:
        st.info(
            "Für die fachliche Projektarbeit ist auch für Systemadministratoren eine "
            "Kursgruppe erforderlich. Legen Sie in der Seitenleiste eine Gruppe an oder "
            "treten Sie über eine Einladung bei."
        )
    else:
        st.info("Sie sind noch keiner Kursgruppe zugeordnet.")
    st.stop()

if naechster_bereich := st.session_state.pop("naechster_framework_bereich", None):
    st.session_state.framework_bereich = naechster_bereich

seite = st.sidebar.radio("Framework-Bereich", FRAMEWORK_BEREICHE, key="framework_bereich")

mandanten_projekte = MandantenProjektService(
    roh_projekte, zugriff, autorisierung, gast_ttl=ermittle_gast_ttl()
)
gebundene_projekte = GebundenerProjektService(
    kontext,
    roh_projekte,
    mandanten_projekte,
    autorisierung,
    ziel_gruppen_id=aktive_gruppen_id,
    gast_projekt_id=(
        UUID(st.session_state.gast_projekt_id) if st.session_state.get("gast_projekt_id") else None
    ),
    globale_rollen=globale_rollen,
    legacy_erstellung_erlaubt=auth_konfiguration.lokaler_testmodus,
)
gebundenes_loeschen = GebundenerLoeschService(kontext, roh_loeschen, autorisierung)


def _gastmodus_nach_projektloeschung_beenden() -> None:
    for schluessel in ("gast_geheimnis", "gast_projekt_id", "projektarchiv"):
        st.session_state.pop(schluessel, None)


aktive_projekt_id = _projekt_id_aus_session()
if aktive_projekt_id is not None:
    if not autorisierung.projekt_zugriff_erlaubt(
        kontext, aktive_projekt_id, Projektaktion.BEARBEITEN
    ):
        if autorisierung.projekt_zugriff_erlaubt(kontext, aktive_projekt_id, Projektaktion.ANSEHEN):
            fortschritt = erstelle_fortschritt_service(datenbankpfad).laden(
                kontext, aktive_projekt_id, dashboard=True
            )
            zeige_gesamtfortschritt(fortschrittsstand_aus_persistenz(fortschritt))
            st.header("Projekt schreibgeschützt")
            projekt = roh_projekte.projekt_laden(aktive_projekt_id)
            if projekt is not None:
                st.subheader(projekt.bezeichnung)
                st.write(projekt.untersuchungsauftrag.problemstellung)
                st.caption(
                    f"Systemtyp: {projekt.untersuchungsauftrag.systemtyp.value} · "
                    f"Status: {projekt.status.value}"
                )
            st.info(
                "Die Gruppenleitung kann dieses Projekt und seinen Fortschritt ansehen und "
                "exportieren. Das reine Öffnen erteilt keinen Bearbeitungszugriff."
            )
        else:
            st.error("Die angeforderte Ressource ist nicht verfügbar.")
        st.stop()

stand = fortschrittsstand(seite, st.session_state)
zeige_gesamtfortschritt(stand)

if aktive_projekt_id is not None and autorisierung.projekt_zugriff_erlaubt(
    kontext, aktive_projekt_id, Projektaktion.BEARBEITEN
):
    try:
        erstelle_fortschritt_service(datenbankpfad).aktualisieren(
            kontext,
            aktive_projekt_id,
            schritt=stand.framework_schritt,
            unterschritt=stand.unterschritt_name,
        )
    except Domaenenfehler:
        pass

if seite == "Schritt 1: Projektrahmen definieren":
    zeige_projektverwaltung(
        gebundene_projekte,
        erstelle_transformations_service(datenbankpfad, workspace),
        gebundenes_loeschen,
        sidebar_titel_anzeigen=False,
        projekt_loesch_label=(
            "Demo beenden und Daten löschen"
            if kontext.gast_geheimnis is not None
            else "Projekt löschen"
        ),
        projektloeschung_nachbereiten=(
            _gastmodus_nach_projektloeschung_beenden if kontext.gast_geheimnis is not None else None
        ),
    )
elif seite == "2 ETL durchführen":
    zeige_etl_seite(
        gebundene_projekte,
        erstelle_datenquelle_service(datenbankpfad),
        erstelle_datenimport_service(),
        erstelle_importvorgang_service(datenbankpfad, workspace),
        erstelle_transformations_service(datenbankpfad, workspace),
        workspace,
    )
elif seite == "3 Semantisches Mapping":
    zeige_semantisches_mapping(
        gebundene_projekte,
        erstelle_transformations_service(datenbankpfad, workspace),
        erstelle_mappingtabelle_service(datenbankpfad, workspace),
        erstelle_datenquelle_service(datenbankpfad),
    )
elif seite == "4 Event Log aufbauen":
    zeige_event_log_seite(
        gebundene_projekte,
        erstelle_event_log_konfigurations_service(datenbankpfad, workspace),
        erstelle_mappingtabelle_service(datenbankpfad, workspace),
        erstelle_transformations_service(datenbankpfad, workspace),
        erstelle_event_log_service(datenbankpfad, workspace),
        erstelle_datenquelle_service(datenbankpfad),
    )
elif seite == "5 Datenqualität prüfen":
    zeige_datenqualitaet_seite(
        gebundene_projekte,
        erstelle_event_log_service(datenbankpfad, workspace),
        erstelle_datenqualitaet_service(datenbankpfad, workspace),
    )
elif seite == "6 Process Mining durchführen":
    zeige_process_mining_seite(
        gebundene_projekte,
        erstelle_datenqualitaet_service(datenbankpfad, workspace),
        erstelle_process_mining_service(datenbankpfad, workspace),
    )
elif seite == "7 Ergebnisse aggregieren":
    zeige_ergebnisaggregation_seite(
        gebundene_projekte,
        erstelle_ergebnisaggregation_service(datenbankpfad, workspace),
    )
elif seite == "8 Modellbestandteile ableiten":
    zeige_modellableitung_seite(
        gebundene_projekte,
        erstelle_modellableitung_service(datenbankpfad, workspace),
    )
elif seite == "9 Modell ergänzen und validieren":
    zeige_modellvalidierung_seite(
        gebundene_projekte,
        erstelle_modellvalidierung_service(datenbankpfad, workspace),
    )
else:
    zeige_modellausgabe_seite(
        gebundene_projekte,
        erstelle_modellvalidierung_service(datenbankpfad, workspace),
        erstelle_modellausgabe_service(datenbankpfad, workspace),
    )
