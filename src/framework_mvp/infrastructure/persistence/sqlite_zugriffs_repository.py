"""SQLite-Adapter für die zentral geprüfte Mandanten- und Zugriffsschicht."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from framework_mvp.domain.exceptions import Domaenenfehler, ZugriffVerweigert
from framework_mvp.domain.models.zugriff import (
    Benutzer,
    GlobaleRolle,
    Gruppeneinladung,
    Gruppenmitgliedschaft,
    Gruppenrolle,
    Gruppenstatus,
    Kursgruppe,
    Mitgliedschaftsstatus,
    Projektfortschritt,
    Projektmitglied,
    Projektzugehoerigkeit,
    Projektzugriffsart,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


def _zeit(wert: str | None) -> datetime | None:
    return None if wert is None else datetime.fromisoformat(wert).astimezone(UTC)


def _datum(wert: str | None) -> date | None:
    return None if wert is None else date.fromisoformat(wert)


class SQLiteZugriffsRepository:
    """Speichert Zugriffsmetadaten in kurzen, expliziten Transaktionen."""

    def __init__(self, datenbankpfad: Path | str = STANDARD_DATENBANKPFAD) -> None:
        self._datenbankpfad = Path(datenbankpfad)

    @contextmanager
    def _verbindung(self) -> Iterator[sqlite3.Connection]:
        self._datenbankpfad.parent.mkdir(parents=True, exist_ok=True)
        verbindung = sqlite3.connect(self._datenbankpfad, timeout=5.0)
        verbindung.row_factory = sqlite3.Row
        try:
            initialisiere_schema(verbindung)
            yield verbindung
        finally:
            verbindung.close()

    def oidc_benutzer_speichern(
        self, *, issuer: str, subject: str, email: str, anzeigename: str
    ) -> Benutzer:
        issuer = issuer.strip()
        subject = subject.strip()
        if not issuer or not subject:
            raise Domaenenfehler("OIDC-Issuer und Subject müssen vorhanden sein.")
        jetzt = datetime.now(UTC).isoformat()
        with self._verbindung() as verbindung, verbindung:
            vorhanden = verbindung.execute(
                "SELECT benutzer_id FROM benutzer WHERE oidc_issuer = ? AND oidc_subject = ?",
                (issuer, subject),
            ).fetchone()
            benutzer_id = str(uuid4()) if vorhanden is None else vorhanden["benutzer_id"]
            verbindung.execute(
                """
                INSERT INTO benutzer (
                    benutzer_id, oidc_issuer, oidc_subject, email, anzeigename,
                    status, erstellt_am_utc, zuletzt_angemeldet_am_utc
                ) VALUES (?, ?, ?, ?, ?, 'aktiv', ?, ?)
                ON CONFLICT(oidc_issuer, oidc_subject) DO UPDATE SET
                    email = excluded.email,
                    anzeigename = excluded.anzeigename,
                    zuletzt_angemeldet_am_utc = excluded.zuletzt_angemeldet_am_utc
                """,
                (benutzer_id, issuer, subject, email.strip(), anzeigename.strip(), jetzt, jetzt),
            )
            zeile = verbindung.execute(
                "SELECT * FROM benutzer WHERE oidc_issuer = ? AND oidc_subject = ?",
                (issuer, subject),
            ).fetchone()
        assert zeile is not None
        return self._benutzer(zeile)

    def benutzer_laden(self, benutzer_id: UUID) -> Benutzer | None:
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM benutzer WHERE benutzer_id = ?", (str(benutzer_id),)
            ).fetchone()
        return None if zeile is None else self._benutzer(zeile)

    def benutzer_auflisten(self) -> list[Benutzer]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT * FROM benutzer ORDER BY anzeigename, email, benutzer_id"
            ).fetchall()
        return [self._benutzer(zeile) for zeile in zeilen]

    def globale_rollen_laden(self, benutzer_id: UUID) -> frozenset[GlobaleRolle]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT rolle FROM globale_rollen WHERE benutzer_id = ?", (str(benutzer_id),)
            ).fetchall()
        return frozenset(GlobaleRolle(zeile["rolle"]) for zeile in zeilen)

    def globale_rolle_setzen(
        self, benutzer_id: UUID, rolle: GlobaleRolle, *, vergeben_von: UUID | None
    ) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT OR IGNORE INTO globale_rollen
                    (benutzer_id, rolle, vergeben_am_utc, vergeben_von_benutzer_id)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(benutzer_id),
                    rolle.value,
                    datetime.now(UTC).isoformat(),
                    None if vergeben_von is None else str(vergeben_von),
                ),
            )

    def globale_rolle_entfernen(self, benutzer_id: UUID, rolle: GlobaleRolle) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                "DELETE FROM globale_rollen WHERE benutzer_id = ? AND rolle = ?",
                (str(benutzer_id), rolle.value),
            )

    def kursgruppe_speichern(self, gruppe: Kursgruppe) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT INTO kursgruppen (
                    gruppen_id, bezeichnung, beschreibung, gruppenleitung_benutzer_id,
                    beginn_am, ende_am, maximale_teilnehmende, maximale_projekte,
                    speicherlimit_pro_projekt_bytes,
                    aufbewahrung_bis_utc, status, erstellt_am_utc, geaendert_am_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(gruppen_id) DO UPDATE SET
                    bezeichnung = excluded.bezeichnung,
                    beschreibung = excluded.beschreibung,
                    beginn_am = excluded.beginn_am,
                    ende_am = excluded.ende_am,
                    maximale_teilnehmende = excluded.maximale_teilnehmende,
                    maximale_projekte = excluded.maximale_projekte,
                    speicherlimit_pro_projekt_bytes = excluded.speicherlimit_pro_projekt_bytes,
                    aufbewahrung_bis_utc = excluded.aufbewahrung_bis_utc,
                    status = excluded.status,
                    geaendert_am_utc = excluded.geaendert_am_utc
                """,
                (
                    str(gruppe.gruppen_id),
                    gruppe.bezeichnung,
                    gruppe.beschreibung,
                    str(gruppe.gruppenleitung_benutzer_id),
                    None if gruppe.beginn_am is None else gruppe.beginn_am.isoformat(),
                    None if gruppe.ende_am is None else gruppe.ende_am.isoformat(),
                    gruppe.maximale_teilnehmende,
                    gruppe.maximale_projekte,
                    gruppe.speicherlimit_pro_projekt_bytes,
                    None
                    if gruppe.aufbewahrung_bis is None
                    else gruppe.aufbewahrung_bis.isoformat(),
                    gruppe.status.value,
                    gruppe.erstellt_am.isoformat(),
                    gruppe.geaendert_am.isoformat(),
                ),
            )

    def kursgruppe_laden(self, gruppen_id: UUID) -> Kursgruppe | None:
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM kursgruppen WHERE gruppen_id = ?", (str(gruppen_id),)
            ).fetchone()
        return None if zeile is None else self._kursgruppe(zeile)

    def kursgruppen_auflisten_betrieb(self) -> list[Kursgruppe]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT * FROM kursgruppen ORDER BY status, bezeichnung, gruppen_id"
            ).fetchall()
        return [self._kursgruppe(zeile) for zeile in zeilen]

    def gruppenmitgliedschaft_speichern(self, mitgliedschaft: Gruppenmitgliedschaft) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT INTO gruppenmitgliedschaften (
                    gruppen_id, benutzer_id, rolle, status, berechtigungen_json,
                    beigetreten_am_utc, geaendert_am_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(gruppen_id, benutzer_id) DO UPDATE SET
                    rolle = excluded.rolle,
                    status = excluded.status,
                    berechtigungen_json = excluded.berechtigungen_json,
                    geaendert_am_utc = excluded.geaendert_am_utc
                """,
                (
                    str(mitgliedschaft.gruppen_id),
                    str(mitgliedschaft.benutzer_id),
                    mitgliedschaft.rolle.value,
                    mitgliedschaft.status.value,
                    json.dumps(sorted(mitgliedschaft.berechtigungen), separators=(",", ":")),
                    mitgliedschaft.beigetreten_am.isoformat(),
                    mitgliedschaft.geaendert_am.isoformat(),
                ),
            )

    def gruppenmitgliedschaft_laden(
        self, gruppen_id: UUID, benutzer_id: UUID
    ) -> Gruppenmitgliedschaft | None:
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                """
                SELECT * FROM gruppenmitgliedschaften
                WHERE gruppen_id = ? AND benutzer_id = ?
                """,
                (str(gruppen_id), str(benutzer_id)),
            ).fetchone()
        return None if zeile is None else self._mitgliedschaft(zeile)

    def gruppenmitgliedschaften_auflisten(self, gruppen_id: UUID) -> list[Gruppenmitgliedschaft]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                """
                SELECT * FROM gruppenmitgliedschaften
                WHERE gruppen_id = ? ORDER BY status, rolle, benutzer_id
                """,
                (str(gruppen_id),),
            ).fetchall()
        return [self._mitgliedschaft(zeile) for zeile in zeilen]

    def gruppen_fuer_benutzer(self, benutzer_id: UUID) -> list[Kursgruppe]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                """
                SELECT g.* FROM kursgruppen g
                JOIN gruppenmitgliedschaften m ON m.gruppen_id = g.gruppen_id
                WHERE m.benutzer_id = ? AND m.status = 'aktiv' AND g.status != 'geloescht'
                ORDER BY g.bezeichnung, g.gruppen_id
                """,
                (str(benutzer_id),),
            ).fetchall()
        return [self._kursgruppe(zeile) for zeile in zeilen]

    def kursgruppen_mit_abgelaufener_aufbewahrung(
        self, *, zeitpunkt: datetime, limit: int
    ) -> list[Kursgruppe]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                """
                SELECT * FROM kursgruppen
                WHERE aufbewahrung_bis_utc IS NOT NULL
                  AND aufbewahrung_bis_utc <= ?
                  AND status IN ('abgelaufen', 'gesperrt')
                ORDER BY aufbewahrung_bis_utc LIMIT ?
                """,
                (zeitpunkt.isoformat(), max(1, min(limit, 1000))),
            ).fetchall()
        return [self._kursgruppe(zeile) for zeile in zeilen]

    def kursgruppen_mit_abgelaufenem_kursende(
        self, *, datum: datetime, limit: int
    ) -> list[Kursgruppe]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                """
                SELECT * FROM kursgruppen
                WHERE ende_am IS NOT NULL AND ende_am < ? AND status = 'aktiv'
                ORDER BY ende_am LIMIT ?
                """,
                (datum.date().isoformat(), max(1, min(limit, 1000))),
            ).fetchall()
        return [self._kursgruppe(zeile) for zeile in zeilen]

    def kursgruppe_status_setzen(
        self, gruppen_id: UUID, *, status: str, zeitpunkt: datetime
    ) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                UPDATE kursgruppen SET status = ?, geaendert_am_utc = ?
                WHERE gruppen_id = ?
                """,
                (status, zeitpunkt.isoformat(), str(gruppen_id)),
            )

    def projektzugehoerigkeit_speichern(self, zugehoerigkeit: Projektzugehoerigkeit) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT INTO projektzugehoerigkeiten (
                    projekt_id, zugriffsart, gruppen_id, gast_geheimnis_sha256,
                    gast_ablauf_am_utc, zuletzt_aktiv_am_utc, revision, erstellt_am_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(projekt_id) DO UPDATE SET
                    zugriffsart = excluded.zugriffsart,
                    gruppen_id = excluded.gruppen_id,
                    gast_geheimnis_sha256 = excluded.gast_geheimnis_sha256,
                    gast_ablauf_am_utc = excluded.gast_ablauf_am_utc,
                    zuletzt_aktiv_am_utc = excluded.zuletzt_aktiv_am_utc,
                    revision = projektzugehoerigkeiten.revision + 1
                """,
                (
                    str(zugehoerigkeit.projekt_id),
                    zugehoerigkeit.zugriffsart.value,
                    None if zugehoerigkeit.gruppen_id is None else str(zugehoerigkeit.gruppen_id),
                    zugehoerigkeit.gast_geheimnis_sha256,
                    None
                    if zugehoerigkeit.gast_ablauf_am is None
                    else zugehoerigkeit.gast_ablauf_am.isoformat(),
                    zugehoerigkeit.zuletzt_aktiv_am.isoformat(),
                    zugehoerigkeit.revision,
                    zugehoerigkeit.erstellt_am.isoformat(),
                ),
            )

    def projektzugehoerigkeit_laden(self, projekt_id: UUID) -> Projektzugehoerigkeit | None:
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM projektzugehoerigkeiten WHERE projekt_id = ?",
                (str(projekt_id),),
            ).fetchone()
        return None if zeile is None else self._projektzugehoerigkeit(zeile)

    def projektmitglied_speichern(self, mitglied: Projektmitglied, *, zeitpunkt: datetime) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT INTO projektmitglieder (
                    projekt_id, benutzer_id, darf_bearbeiten, status, zugewiesen_am_utc
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(projekt_id, benutzer_id) DO UPDATE SET
                    darf_bearbeiten = excluded.darf_bearbeiten,
                    status = excluded.status
                """,
                (
                    str(mitglied.projekt_id),
                    str(mitglied.benutzer_id),
                    int(mitglied.darf_bearbeiten),
                    "aktiv" if mitglied.aktiv else "entfernt",
                    zeitpunkt.isoformat(),
                ),
            )

    def projektmitglied_laden(self, projekt_id: UUID, benutzer_id: UUID) -> Projektmitglied | None:
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                """
                SELECT * FROM projektmitglieder WHERE projekt_id = ? AND benutzer_id = ?
                """,
                (str(projekt_id), str(benutzer_id)),
            ).fetchone()
        if zeile is None:
            return None
        return Projektmitglied(
            projekt_id=UUID(zeile["projekt_id"]),
            benutzer_id=UUID(zeile["benutzer_id"]),
            darf_bearbeiten=bool(zeile["darf_bearbeiten"]),
            aktiv=zeile["status"] == "aktiv",
        )

    def projektmitglieder_auflisten(self, projekt_id: UUID) -> list[Projektmitglied]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                """
                SELECT * FROM projektmitglieder
                WHERE projekt_id = ? AND status = 'aktiv'
                ORDER BY benutzer_id
                """,
                (str(projekt_id),),
            ).fetchall()
        return [
            Projektmitglied(
                projekt_id=UUID(zeile["projekt_id"]),
                benutzer_id=UUID(zeile["benutzer_id"]),
                darf_bearbeiten=bool(zeile["darf_bearbeiten"]),
                aktiv=True,
            )
            for zeile in zeilen
        ]

    def projekt_ids_fuer_benutzer(self, benutzer_id: UUID) -> list[UUID]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                """
                SELECT DISTINCT pm.projekt_id FROM projektmitglieder pm
                JOIN projektzugehoerigkeiten pz ON pz.projekt_id = pm.projekt_id
                JOIN gruppenmitgliedschaften gm
                  ON gm.gruppen_id = pz.gruppen_id AND gm.benutzer_id = pm.benutzer_id
                JOIN kursgruppen g ON g.gruppen_id = pz.gruppen_id
                WHERE pm.benutzer_id = ? AND pm.status = 'aktiv'
                  AND gm.status = 'aktiv' AND g.status != 'geloescht'
                ORDER BY pm.projekt_id
                """,
                (str(benutzer_id),),
            ).fetchall()
        return [UUID(zeile["projekt_id"]) for zeile in zeilen]

    def projekt_ids_fuer_gruppe(self, gruppen_id: UUID) -> list[UUID]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                """
                SELECT projekt_id FROM projektzugehoerigkeiten
                WHERE gruppen_id = ? AND zugriffsart = 'kursgruppe'
                ORDER BY projekt_id
                """,
                (str(gruppen_id),),
            ).fetchall()
        return [UUID(zeile["projekt_id"]) for zeile in zeilen]

    def legacy_projekt_ids(self) -> list[UUID]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                """
                SELECT projekt_id FROM projektzugehoerigkeiten
                WHERE zugriffsart = 'legacy_unassigned' ORDER BY projekt_id
                """
            ).fetchall()
        return [UUID(zeile["projekt_id"]) for zeile in zeilen]

    def abgelaufene_gastprojekt_ids(self, *, zeitpunkt: datetime, limit: int) -> list[UUID]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                """
                SELECT projekt_id FROM projektzugehoerigkeiten
                WHERE zugriffsart = 'gast' AND gast_ablauf_am_utc <= ?
                ORDER BY gast_ablauf_am_utc LIMIT ?
                """,
                (zeitpunkt.isoformat(), max(1, min(limit, 1000))),
            ).fetchall()
        return [UUID(zeile["projekt_id"]) for zeile in zeilen]

    def projekt_aktivitaet_beruehren(
        self, projekt_id: UUID, *, zeitpunkt: datetime, neue_ablaufzeit: datetime | None = None
    ) -> None:
        with self._verbindung() as verbindung, verbindung:
            if neue_ablaufzeit is None:
                verbindung.execute(
                    """
                    UPDATE projektzugehoerigkeiten
                    SET zuletzt_aktiv_am_utc = ?, revision = revision + 1
                    WHERE projekt_id = ?
                    """,
                    (zeitpunkt.isoformat(), str(projekt_id)),
                )
            else:
                verbindung.execute(
                    """
                    UPDATE projektzugehoerigkeiten
                    SET zuletzt_aktiv_am_utc = ?, gast_ablauf_am_utc = ?, revision = revision + 1
                    WHERE projekt_id = ? AND zugriffsart = 'gast'
                    """,
                    (zeitpunkt.isoformat(), neue_ablaufzeit.isoformat(), str(projekt_id)),
                )

    def fortschritt_speichern(self, fortschritt: Projektfortschritt) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT INTO projektfortschritt (
                    projekt_id, framework_schritt, fachlicher_unterschritt,
                    fortschritt_zaehler, fortschritt_nenner, phase, status,
                    gespeichert_am_utc, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(projekt_id) DO UPDATE SET
                    framework_schritt = excluded.framework_schritt,
                    fachlicher_unterschritt = excluded.fachlicher_unterschritt,
                    fortschritt_zaehler = excluded.fortschritt_zaehler,
                    fortschritt_nenner = excluded.fortschritt_nenner,
                    phase = excluded.phase,
                    status = excluded.status,
                    gespeichert_am_utc = excluded.gespeichert_am_utc,
                    revision = projektfortschritt.revision + 1
                """,
                (
                    str(fortschritt.projekt_id),
                    fortschritt.framework_schritt,
                    fortschritt.fachlicher_unterschritt,
                    fortschritt.fortschritt_zaehler,
                    fortschritt.fortschritt_nenner,
                    fortschritt.phase,
                    fortschritt.status,
                    fortschritt.gespeichert_am.isoformat(),
                    fortschritt.revision,
                ),
            )

    def fortschritt_laden(self, projekt_id: UUID) -> Projektfortschritt | None:
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM projektfortschritt WHERE projekt_id = ?", (str(projekt_id),)
            ).fetchone()
        if zeile is None:
            return None
        return Projektfortschritt(
            projekt_id=UUID(zeile["projekt_id"]),
            framework_schritt=zeile["framework_schritt"],
            fachlicher_unterschritt=zeile["fachlicher_unterschritt"],
            fortschritt_zaehler=zeile["fortschritt_zaehler"],
            fortschritt_nenner=zeile["fortschritt_nenner"],
            phase=zeile["phase"],
            status=zeile["status"],
            gespeichert_am=_zeit(zeile["gespeichert_am_utc"]),  # type: ignore[arg-type]
            revision=zeile["revision"],
        )

    def einladung_speichern(self, einladung: Gruppeneinladung) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT INTO gruppeneinladungen (
                    einladungs_id, gruppen_id, token_sha256, laeuft_ab_am_utc,
                    maximale_nutzungen, anzahl_nutzungen, erlaubte_email_domain,
                    erlaubte_emails_json, widerrufen_am_utc,
                    erstellt_von_benutzer_id, erstellt_am_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(einladung.einladungs_id),
                    str(einladung.gruppen_id),
                    einladung.token_sha256,
                    einladung.laeuft_ab_am.isoformat(),
                    einladung.maximale_nutzungen,
                    einladung.anzahl_nutzungen,
                    einladung.erlaubte_email_domain,
                    json.dumps(einladung.erlaubte_emails, separators=(",", ":")),
                    None
                    if einladung.widerrufen_am is None
                    else einladung.widerrufen_am.isoformat(),
                    str(einladung.erstellt_von_benutzer_id),
                    einladung.erstellt_am.isoformat(),
                ),
            )

    def einladung_laden_per_hash(self, token_sha256: str) -> Gruppeneinladung | None:
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM gruppeneinladungen WHERE token_sha256 = ?", (token_sha256,)
            ).fetchone()
        return None if zeile is None else self._einladung(zeile)

    def einladung_widerrufen(self, einladungs_id: UUID, *, zeitpunkt: datetime) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                UPDATE gruppeneinladungen SET widerrufen_am_utc = ?
                WHERE einladungs_id = ? AND widerrufen_am_utc IS NULL
                """,
                (zeitpunkt.isoformat(), str(einladungs_id)),
            )

    def einladung_atomar_einloesen(
        self, *, token_sha256: str, benutzer: Benutzer, zeitpunkt: datetime
    ) -> Gruppenmitgliedschaft:
        with self._verbindung() as verbindung:
            verbindung.execute("BEGIN IMMEDIATE")
            try:
                zeile = verbindung.execute(
                    "SELECT * FROM gruppeneinladungen WHERE token_sha256 = ?", (token_sha256,)
                ).fetchone()
                if zeile is None:
                    raise ZugriffVerweigert("Die Einladung ist nicht verfügbar.")
                einladung = self._einladung(zeile)
                email = benutzer.email.strip().casefold()
                erlaubte = {wert.casefold() for wert in einladung.erlaubte_emails}
                domain = einladung.erlaubte_email_domain.casefold().lstrip("@")
                domain_ok = bool(domain and email.endswith(f"@{domain}"))
                if (
                    einladung.widerrufen_am is not None
                    or einladung.laeuft_ab_am <= zeitpunkt
                    or einladung.anzahl_nutzungen >= einladung.maximale_nutzungen
                    or (erlaubte or domain)
                    and email not in erlaubte
                    and not domain_ok
                ):
                    raise ZugriffVerweigert("Die Einladung ist nicht verfügbar.")
                gruppe = verbindung.execute(
                    "SELECT * FROM kursgruppen WHERE gruppen_id = ?",
                    (str(einladung.gruppen_id),),
                ).fetchone()
                if gruppe is None or gruppe["status"] != "aktiv":
                    raise ZugriffVerweigert("Die Einladung ist nicht verfügbar.")
                anzahl = verbindung.execute(
                    """
                    SELECT count(*) FROM gruppenmitgliedschaften
                    WHERE gruppen_id = ? AND status = 'aktiv'
                    """,
                    (str(einladung.gruppen_id),),
                ).fetchone()[0]
                if anzahl >= gruppe["maximale_teilnehmende"]:
                    raise ZugriffVerweigert("Die Einladung ist nicht verfügbar.")
                verbindung.execute(
                    """
                    INSERT INTO gruppenmitgliedschaften (
                        gruppen_id, benutzer_id, rolle, status, berechtigungen_json,
                        beigetreten_am_utc, geaendert_am_utc
                    ) VALUES (?, ?, 'teilnehmer', 'aktiv', '[]', ?, ?)
                    ON CONFLICT(gruppen_id, benutzer_id) DO UPDATE SET
                        status = 'aktiv', rolle = 'teilnehmer',
                        geaendert_am_utc = excluded.geaendert_am_utc
                    """,
                    (
                        str(einladung.gruppen_id),
                        str(benutzer.benutzer_id),
                        zeitpunkt.isoformat(),
                        zeitpunkt.isoformat(),
                    ),
                )
                aktualisiert = verbindung.execute(
                    """
                    UPDATE gruppeneinladungen SET anzahl_nutzungen = anzahl_nutzungen + 1
                    WHERE einladungs_id = ? AND anzahl_nutzungen < maximale_nutzungen
                    """,
                    (str(einladung.einladungs_id),),
                )
                if aktualisiert.rowcount != 1:
                    raise ZugriffVerweigert("Die Einladung ist nicht verfügbar.")
                verbindung.commit()
            except Exception:
                verbindung.rollback()
                raise
        return Gruppenmitgliedschaft(
            gruppen_id=einladung.gruppen_id,
            benutzer_id=benutzer.benutzer_id,
            rolle=Gruppenrolle.TEILNEHMER,
            status=Mitgliedschaftsstatus.AKTIV,
            berechtigungen=frozenset(),
            beigetreten_am=zeitpunkt,
            geaendert_am=zeitpunkt,
        )

    def bereinigung_protokollieren(
        self,
        *,
        projekt_id: UUID | None,
        gruppen_id: UUID | None,
        aktion: str,
        ergebnis: str,
        details: dict[str, object],
        zeitpunkt: datetime,
    ) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT INTO bereinigungsprotokoll (
                    eintrag_id, projekt_id, gruppen_id, aktion,
                    ergebnis, details_json, erstellt_am_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    None if projekt_id is None else str(projekt_id),
                    None if gruppen_id is None else str(gruppen_id),
                    aktion,
                    ergebnis,
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                    zeitpunkt.isoformat(),
                ),
            )

    def archiv_metadaten_speichern(
        self,
        *,
        archiv_id: UUID,
        projekt_id: UUID | None,
        gruppen_id: UUID | None,
        archivtyp: str,
        archivversion: int,
        sha256: str,
        groesse_bytes: int,
        benutzer_id: UUID | None,
        status: str,
        details: dict[str, object],
        zeitpunkt: datetime,
    ) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT INTO archivmetadaten (
                    archiv_id, projekt_id, gruppen_id, archivtyp, archivversion,
                    sha256, groesse_bytes, erstellt_von_benutzer_id,
                    erstellt_am_utc, status, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(archiv_id),
                    None if projekt_id is None else str(projekt_id),
                    None if gruppen_id is None else str(gruppen_id),
                    archivtyp,
                    archivversion,
                    sha256,
                    groesse_bytes,
                    None if benutzer_id is None else str(benutzer_id),
                    zeitpunkt.isoformat(),
                    status,
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                ),
            )

    @staticmethod
    def _benutzer(zeile: sqlite3.Row) -> Benutzer:
        return Benutzer(
            benutzer_id=UUID(zeile["benutzer_id"]),
            oidc_issuer=zeile["oidc_issuer"],
            oidc_subject=zeile["oidc_subject"],
            email=zeile["email"],
            anzeigename=zeile["anzeigename"],
            aktiv=zeile["status"] == "aktiv",
            erstellt_am=_zeit(zeile["erstellt_am_utc"]),  # type: ignore[arg-type]
            zuletzt_angemeldet_am=_zeit(zeile["zuletzt_angemeldet_am_utc"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _kursgruppe(zeile: sqlite3.Row) -> Kursgruppe:
        return Kursgruppe(
            gruppen_id=UUID(zeile["gruppen_id"]),
            bezeichnung=zeile["bezeichnung"],
            beschreibung=zeile["beschreibung"],
            gruppenleitung_benutzer_id=UUID(zeile["gruppenleitung_benutzer_id"]),
            beginn_am=_datum(zeile["beginn_am"]),
            ende_am=_datum(zeile["ende_am"]),
            maximale_teilnehmende=zeile["maximale_teilnehmende"],
            maximale_projekte=zeile["maximale_projekte"],
            speicherlimit_pro_projekt_bytes=zeile["speicherlimit_pro_projekt_bytes"],
            aufbewahrung_bis=_zeit(zeile["aufbewahrung_bis_utc"]),
            status=Gruppenstatus(zeile["status"]),
            erstellt_am=_zeit(zeile["erstellt_am_utc"]),  # type: ignore[arg-type]
            geaendert_am=_zeit(zeile["geaendert_am_utc"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _mitgliedschaft(zeile: sqlite3.Row) -> Gruppenmitgliedschaft:
        return Gruppenmitgliedschaft(
            gruppen_id=UUID(zeile["gruppen_id"]),
            benutzer_id=UUID(zeile["benutzer_id"]),
            rolle=Gruppenrolle(zeile["rolle"]),
            status=Mitgliedschaftsstatus(zeile["status"]),
            berechtigungen=frozenset(json.loads(zeile["berechtigungen_json"])),
            beigetreten_am=_zeit(zeile["beigetreten_am_utc"]),  # type: ignore[arg-type]
            geaendert_am=_zeit(zeile["geaendert_am_utc"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _projektzugehoerigkeit(zeile: sqlite3.Row) -> Projektzugehoerigkeit:
        return Projektzugehoerigkeit(
            projekt_id=UUID(zeile["projekt_id"]),
            zugriffsart=Projektzugriffsart(zeile["zugriffsart"]),
            gruppen_id=None if zeile["gruppen_id"] is None else UUID(zeile["gruppen_id"]),
            gast_geheimnis_sha256=zeile["gast_geheimnis_sha256"],
            gast_ablauf_am=_zeit(zeile["gast_ablauf_am_utc"]),
            zuletzt_aktiv_am=_zeit(zeile["zuletzt_aktiv_am_utc"]),  # type: ignore[arg-type]
            revision=zeile["revision"],
            erstellt_am=_zeit(zeile["erstellt_am_utc"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _einladung(zeile: sqlite3.Row) -> Gruppeneinladung:
        return Gruppeneinladung(
            einladungs_id=UUID(zeile["einladungs_id"]),
            gruppen_id=UUID(zeile["gruppen_id"]),
            token_sha256=zeile["token_sha256"],
            laeuft_ab_am=_zeit(zeile["laeuft_ab_am_utc"]),  # type: ignore[arg-type]
            maximale_nutzungen=zeile["maximale_nutzungen"],
            anzahl_nutzungen=zeile["anzahl_nutzungen"],
            erlaubte_email_domain=zeile["erlaubte_email_domain"],
            erlaubte_emails=tuple(json.loads(zeile["erlaubte_emails_json"])),
            widerrufen_am=_zeit(zeile["widerrufen_am_utc"]),
            erstellt_von_benutzer_id=UUID(zeile["erstellt_von_benutzer_id"]),
            erstellt_am=_zeit(zeile["erstellt_am_utc"]),  # type: ignore[arg-type]
        )
