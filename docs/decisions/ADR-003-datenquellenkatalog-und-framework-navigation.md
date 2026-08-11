# ADR-003: Datenquellenkatalog und Framework-Navigation

## Status

Aktualisiert durch die Umsetzung von Abschnitt 3.6.6 und ADR-005

## Kontext

Nach der Projektdefinition in Framework-Schritt 1 benötigt die ETL-Phase einen
projektbezogenen Datenquellenkatalog Q. Gleichzeitig soll der fachliche Zusammenhang der zehn
Framework-Schritte in jeder Hauptseite sichtbar sein. Inkrement B ergänzt einen temporären
Dateiimport bis zur unveränderten Datenvorschau. Inkrement C ergänzt darauf aufbauend die
technische Datenprofilierung und Qualitätsübersicht.

## Entscheidung

Die ursprüngliche Entscheidung für eine globale SVG-Prozessgrafik wurde mit ADR-005 aufgehoben.
Die Hauptnavigation verwendet seither klar benannte Framework-Bereiche; Wizards besitzen lokale
Fortschrittsanzeigen.

Der Datenquellenkatalog Q gehört ausschließlich zu Schritt 2 und verwendet das unveränderliche
Domänenmodell `Datenquelle`, einen Anwendungsservice und ein Repository-Protocol. Neu auswählbar
sind die Quellsystemtypen ERP-System, ME-System, WM-System und sonstiges System. Als Dateiformate
sind ausschließlich CSV und XLSX vorgesehen. Historische Werte für Datenbank und Dateiexport
bleiben kontrolliert ladbar, werden aber nicht mehr als neue Sollausprägungen angeboten. Eine
direkte technische Datenbankanbindung ist nicht Bestandteil des Schritts.

CSV- und XLSX-Dateien werden projektbezogen verarbeitet. Unveränderliche Importparameter,
Datei-Metadaten, technische Leselogik,
Vorschauaufbereitung und Oberfläche sind getrennt. Cache-Schlüssel kombinieren SHA-256-Prüfsumme
und Importparameter. Bestätigte Raw-Dateien und Profile werden integritätsgesichert im Workspace
gespeichert. Gemeinsame Schlüsselattribute sind Bestandteil von Q und werden in SQLite dauerhaft
bewahrt. Die maximale Dateigröße beträgt standardmäßig 50 MB und ist über
`FRAMEWORK_MVP_MAX_UPLOAD_MB` konfigurierbar.

Das persistierte Datenprofil R trennt Berechnung, unveränderliche Profilmodelle,
Diagrammdaten und Streamlit-Darstellung. Echte Pandas-Fehlwerte und exakt erkannte textuelle
Platzhalter werden getrennt ausgewiesen. Die fachliche JSON-Projektion folgt den Tabellen 3.7
bis 3.10 und Gleichung 3.10. Histogramme, Kategoriehäufigkeiten und Zeitverteilungen bleiben
ergänzende, transient berechnete Visualisierungen und sind keine zusätzlichen Bestandteile von R.
Sämtliche Kennzahlen basieren auf dem vollständigen DataFrame.

## Persistenz und Migration

Schemaversion 2 bleibt dem strukturierten Untersuchungsauftrag vorbehalten. Der
Datenquellenkatalog verwendet Schemaversion 3. Die bestehende Migration von Version 1 auf
Version 2 transformiert weiterhin das flache Projektmodell zum strukturierten Auftrag. Die
Migration von Version 2 auf Version 3 legt innerhalb einer Transaktion ausschließlich die neue
Tabelle `datenquellen` an und setzt erst danach `PRAGMA user_version = 3`. Die strukturierte
Projekttabelle und ihre Datensätze werden dabei nicht verändert. Neuere unbekannte Versionen
werden abgelehnt.

## Workspace

Der zentrale Workspace wird unabhängig vom aktuellen Arbeitsverzeichnis ermittelt. Ein expliziter
Pfad hat Vorrang vor `FRAMEWORK_MVP_WORKSPACE_PATH`; andernfalls wird das Repositoryverzeichnis
`workspace/` verwendet. Beim ersten Bedarf entstehen projektbezogen `raw`, `profiles` und
`interim`. In diesem Inkrement enthalten sie noch keine Nutzdaten.

## Konsequenzen

- Datenquellen sind strukturiert und projektbezogen katalogisiert.
- Weitere ETL-Inkremente können auf stabilen Quellen-IDs aufbauen.
- Die Hauptbereiche sind über die Streamlit-Navigation erreichbar.
- Die gemeinsame SQLite-Datei bleibt die eindeutige Metadatenquelle.
- CSV- und XLSX-Vorschauen sind vor der ausdrücklichen Bestätigung möglich.
- Das SQLite-Schema bleibt in Version 3 unverändert.
- Bestätigte Profile und unveränderte Raw-Dateien sind dauerhaft und integritätsgesichert.
- Schritt 2 fasst Q, R und T als drei getrennte Ausgaben zusammen.

## Verworfene Alternativen

Eine getrennte Datenbank für Datenquellen wurde verworfen, weil sie Transaktionen und
Projektbezug unnötig erschwert. Eine sofortige technische Datenbankanbindung wurde verworfen, da
sie nicht zum Umfang dieses Inkrements gehört.
