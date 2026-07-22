# ADR-002: Strukturierter Untersuchungsauftrag

## Status

Akzeptiert

## Kontext

Der bisherige Untersuchungsauftrag bestand weitgehend aus Freitexten und wurde in einem langen
Formular erfasst. Für Datenimport, Process Mining und die spätere Ableitung eines konzeptionellen
Modells werden stabile fachliche Strukturen, nachvollziehbare Zielgrößen und explizite
Systemmerkmale benötigt. Bereits vorhandene lokale Projektdaten müssen erhalten bleiben.

## Entscheidung

Der Untersuchungsauftrag wird durch unveränderliche, typisierte Domänenobjekte strukturiert.
Die Erfassung erfolgt in einem siebenschrittigen Streamlit-Wizard. Zielgrößen besitzen stabile
technische IDs; KPI-Kandidaten werden außerhalb der UI aus einem zentralen Katalog abgeleitet.

## Domänenobjekte

- `BeteiligtePerson` trennt Vorname, Nachname und Rolle.
- `Systemklassifikation` enthält gemeinsame Merkmale sowie optionale Produktions- und
  Intralogistikblöcke.
- `Rahmenbedingungen` trennt Datenschutz, technische Einschränkungen, Annahmen, Ausschlüsse
  und sonstige Angaben.
- `Betrachtungszeitraum` verwendet die Modi `AUS_DATEN`, `MANUELL` und `OFFEN`.
- `LogistischeZielgroesse` und `KpiKandidat` verwenden stabile IDs.

## Wizard-Struktur

Der Wizard führt von Projekt und Personen über Problem, Zweck, Ziele, Systemklassifikation,
Auswertungen und Zeitraum bis zur Zusammenfassung. Ein Entwurf kann aus jedem Schritt gespeichert
werden. Temporäre Eingaben liegen im Session State; SQLite bleibt die persistente Datenquelle.

## Schemaversion 2

Projektkopfdaten bleiben relationale Spalten. Beteiligte Personen und der strukturierte
Untersuchungsauftrag werden nachvollziehbar als JSON gespeichert. Das ermöglicht die Erweiterung
verschachtelter Fachobjekte, ohne deren Struktur in Freitexte zurückzuführen.

## Migration

Beim ersten Zugriff auf eine Version-1-Datenbank wird die vorhandene Tabelle innerhalb einer
SQLite-Transaktion umbenannt, in das neue Format überführt und ersetzt. Alte Personentexte werden
verlustfrei als Nachname mit der Rolle „Sonstige“ gespeichert. Die alte Zielsetzung wird zum
individuellen Ziel, alte Kennzahlen werden im gekennzeichneten Legacy-Feld bewahrt. Vorhandene
Datumswerte ergeben den manuellen Modus, leere Datumswerte den offenen Modus. Erst nach
erfolgreicher Transformation wird `user_version` auf 2 gesetzt. Fehler rollen die gesamte
Migration zurück.

## Konsequenzen

- Spätere Frameworkschritte können auf stabilen IDs und strukturierten Merkmalen aufbauen.
- Die UI ist umfangreicher, führt Nutzende aber schrittweise durch fachlich zusammenhängende
  Fragen.
- Individuelle Rollen und Ressourcen bleiben möglich.
- Das JSON-Format muss bei künftigen Schemaänderungen versioniert migriert werden.

## Verworfene Alternativen

Ein weiterhin ausschließlich freitextbasierter Auftrag wurde verworfen, weil er keine stabile
automatische Weiterverarbeitung erlaubt. Eine vollständige Normalisierung jedes Auswahlwerts in
eigene SQLite-Tabellen wurde wegen der lokalen MVP-Nutzung und der hohen Zahl verschachtelter,
optionaler Merkmale verworfen. Eine zweite Datenbankdatei für Schema 2 wurde verworfen, weil sie
uneindeutige Datenstände und manuellen Migrationsaufwand erzeugen würde.
