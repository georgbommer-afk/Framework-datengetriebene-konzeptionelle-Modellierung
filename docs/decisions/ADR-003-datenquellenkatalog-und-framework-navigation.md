# ADR-003: Datenquellenkatalog und Framework-Navigation

## Status

Teilweise abgelöst durch ADR-005

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

Der Datenquellenkatalog verwendet das unveränderliche Domänenmodell `Datenquelle`, einen
Anwendungsservice und ein Repository-Protocol. CSV, Excel und Datenbanken werden fachlich
modelliert. Eine technische Datenbankanbindung ist noch nicht enthalten.

CSV- und XLSX-Dateien werden ausschließlich im projektbezogenen Streamlit-Sitzungszustand
verarbeitet. Unveränderliche Importparameter, Datei-Metadaten, technische Leselogik,
Vorschauaufbereitung und Oberfläche sind getrennt. Cache-Schlüssel kombinieren SHA-256-Prüfsumme
und Importparameter. Damit lösen nur Datei- oder Parameteränderungen ein erneutes vollständiges
Einlesen aus. Uploadbytes werden weder in SQLite noch im Workspace gespeichert. Die maximale
Dateigröße beträgt standardmäßig 50 MB und ist über `FRAMEWORK_MVP_MAX_UPLOAD_MB` konfigurierbar.

Das ebenfalls temporäre Datenprofil trennt Berechnung, unveränderliche Profilmodelle,
Diagrammdaten und Streamlit-Darstellung. Echte Pandas-Fehlwerte und exakt erkannte textuelle
Platzhalter werden getrennt ausgewiesen. Numerische Kennzahlen verwenden nur endliche Werte;
Unendlichkeiten werden separat gezählt. Histogramme, Boxplots, Kategoriehäufigkeiten und
Zeitverteilungen gelangen ausschließlich aggregiert in die Oberfläche. Sämtliche Kennzahlen
basieren auf dem vollständigen DataFrame.

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
- CSV- und XLSX-Vorschauen sind ohne persistente Rohdatei möglich.
- Das SQLite-Schema bleibt in Version 3 unverändert.
- Technische Datenprofile und Qualitätsdiagramme sind temporär verfügbar.
- Datenbereinigung, Transformation, dauerhafte Profilspeicherung und Importbestätigung bleiben
  späteren Inkrementen vorbehalten.

## Verworfene Alternativen

Eine getrennte Datenbank für Datenquellen wurde verworfen, weil sie Transaktionen und
Projektbezug unnötig erschwert. Eine sofortige technische Datenbankanbindung wurde verworfen, da
sie nicht zum Umfang dieses Inkrements gehört.
