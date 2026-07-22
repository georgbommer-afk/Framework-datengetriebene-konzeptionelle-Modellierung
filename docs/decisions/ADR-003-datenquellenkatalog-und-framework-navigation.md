# ADR-003: Datenquellenkatalog und Framework-Navigation

## Status

Akzeptiert

## Kontext

Nach der Projektdefinition in Framework-Schritt 1 benötigt die ETL-Phase einen
projektbezogenen Datenquellenkatalog Q. Gleichzeitig soll der fachliche Zusammenhang der zehn
Framework-Schritte in jeder Hauptseite sichtbar sein. In diesem Inkrement werden Quellen nur
registriert; Dateien, Tabellen und Datenprofile werden noch nicht verarbeitet.

## Entscheidung

Das zehnstufige Framework wird als programmatisch erzeugtes SVG dargestellt. Es folgt der
schlangenförmigen Anordnung der Masterarbeit und kennzeichnet aktuelle, abgeschlossene und
zukünftige Schritte. Das SVG wird ohne Screenshot, globale CSS-Regeln oder externe Bibliothek
erzeugt.

Der Datenquellenkatalog verwendet das unveränderliche Domänenmodell `Datenquelle`, einen
Anwendungsservice und ein Repository-Protocol. CSV, Excel und Datenbanken werden fachlich
modelliert. Eine technische Datenbankanbindung ist noch nicht enthalten.

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
- Die Framework-Navigation ist auf weiteren Seiten wiederverwendbar.
- Die gemeinsame SQLite-Datei bleibt die eindeutige Metadatenquelle.
- Dateiupload, Import, Vorschau und Profilierung folgen erst in späteren Inkrementen.

## Verworfene Alternativen

Ein Screenshot der Framework-Grafik wurde wegen mangelnder Zustandsdarstellung und Skalierbarkeit
verworfen. Eine getrennte Datenbank für Datenquellen wurde verworfen, weil sie Transaktionen und
Projektbezug unnötig erschwert. Eine sofortige technische Datenbankanbindung wurde verworfen, da
sie nicht zum Umfang dieses Inkrements gehört.
