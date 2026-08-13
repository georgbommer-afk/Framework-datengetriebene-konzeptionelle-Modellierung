# ADR-011: Portable Projekte und private Kursmandanten

## Status

Akzeptiert

## Kontext

Die öffentliche Community-Cloud-App soll anonym ausprobierbar bleiben und zugleich private
Lehrveranstaltungen unterstützen. Der Community-Cloud-Dateispeicher ist nicht dauerhaft
garantiert; eine externe Datenbank oder eigene Passwortverwaltung gehört nicht zum MVP.

## Entscheidung

OIDC authentifiziert mit `st.login`, `st.user` und `st.logout`; Autorisierung bleibt eine
separate Application-Service-Aufgabe. Ein expliziter Zugriffskontext enthält entweder eine über
Issuer und Subject gebundene Benutzer-ID oder einen flüchtigen Gast-Besitznachweis. Policies
verweigern standardmäßig, prüfen Mitgliedschaften bei jedem Zugriff neu und behandeln bekannte
UUIDs nie als Rechte. Gruppenleitungen lesen alle eigenen Gruppenprojekte, bearbeiten sie aber
nur nach expliziter Teamzuweisung. Systemadministration vermittelt keine pauschale
Projektbearbeitung.

SQLite-Schemaversion 11 ergänzt Mandanten-, Rollen-, Einladungs-, Fortschritts-,
Aufbewahrungs- und Betriebsmetadaten. Legacy-Projekte werden `legacy_unassigned`, nicht
öffentlich. WAL, Foreign Keys, `busy_timeout`, kurze Transaktionen und Projektlocks begrenzen
lokale Parallelitätsrisiken.

Projekt-ZIP v1 ist die portable Sicherung. Es enthält ausschließlich den letzten gespeicherten
Projektstand und keine lokalen Rechte. Ein Import validiert Ressourcen, Struktur, CRC,
Prüfsummen, JSON-Schemata und Lineage vor einer gestagten Übernahme. Kursarchive verschachteln
validierte Projektarchive; lokale Mitgliedschaften und neue Einladungen sind nach Import erneut
einzurichten.

Gastprojekte besitzen eine Aktivitäts-TTL. Sofortige Löschung ist eine bewusste Benutzeraktion;
Appstart und relevante Zugriffe führen eine begrenzte opportunistische Bereinigung aus.

## Folgen

- Öffentlicher Gastzugang und private Kurse können in derselben App sicher getrennt werden.
- Archive, nicht lokaler Cloud-Speicher, sind die dauerhafte Übergabe- und Sicherungsstrategie.
- SQLite bleibt für kleine Lehrveranstaltungen geeignet, ist aber kein hochskalierender
  Mehrbenutzerspeicher.
- Importierte HTML-Berichte bleiben Dateien und werden nicht ungeprüft als aktiver Webinhalt
  veröffentlicht.
