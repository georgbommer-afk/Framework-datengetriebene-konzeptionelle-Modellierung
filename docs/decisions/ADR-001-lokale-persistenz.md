# ADR-001: Lokale Persistenz

## Status

Akzeptiert

## Kontext

Das Framework-MVP wird lokal ausgeführt und verarbeitet Projektinformationen sowie später
eingelesene Ereignisdaten und daraus erzeugte Analyseartefakte. Projektmetadaten benötigen eine
strukturierte, transaktionale und reproduzierbare Ablage. Rohdaten und Analyseergebnisse können
dagegen groß sein und unterschiedliche Dateiformate besitzen. Die erste Ausbaustufe soll ohne
zusätzlichen Datenbankdienst und ohne weitere Python-Abhängigkeit funktionieren.

## Entscheidung

Das MVP wird lokal ausgeführt. Strukturierte Projektmetadaten werden in einer SQLite-Datenbank
gespeichert. Der Standardpfad lautet `workspace/framework_mvp.sqlite`. Der Ordner und die
Datenbank werden beim ersten Zugriff automatisch angelegt.

Dateien, importierte Daten und spätere Analyseartefakte werden ebenfalls unterhalb des lokalen
Verzeichnisses `workspace/` abgelegt. Dieses Verzeichnis ist von Git ausgeschlossen, damit
Fallstudiendaten, temporäre Ergebnisse und lokale Datenbanken nicht versehentlich versioniert
werden. SQLite-Zugriffe erfolgen über die Python-Standardbibliothek und Schreiboperationen werden
transaktional ausgeführt. Die Schemaversion wird mit `PRAGMA user_version` verwaltet.

## Konsequenzen

- Das MVP benötigt keinen separat betriebenen Datenbankserver.
- Projektmetadaten lassen sich strukturiert abfragen und atomar speichern.
- Eine lokale Projektdatei kann einfach gesichert oder zwischen Arbeitsständen kopiert werden.
- Die Anwendung bleibt zunächst auf lokale Nutzung und eine geringe Zahl gleichzeitiger Zugriffe
  ausgerichtet.
- Datenbankmigrationen müssen bei künftigen Schemaänderungen anhand der Schemaversion ergänzt
  werden.
- Das ignorierte `workspace`-Verzeichnis ist nicht durch die Versionsverwaltung gesichert. Eine
  fachlich geeignete Sicherungsstrategie liegt bei der anwendenden Person.

## Verworfene Alternativen

### Ausschließliche JSON-Dateien

JSON wäre leicht lesbar, bietet aber keine vergleichbar robuste Transaktionssteuerung und wird
bei strukturierten Abfragen sowie partiellen Aktualisierungen schnell unübersichtlich.

### Externer Datenbankserver

PostgreSQL oder ein vergleichbarer Dienst würde bessere Mehrbenutzerfähigkeit bieten, erhöht für
das lokal ausgeführte MVP jedoch Installations-, Konfigurations- und Betriebsaufwand ohne
unmittelbaren fachlichen Nutzen.

### Speicherung aller Artefakte in SQLite

Binäre Dateien, umfangreiche Datensätze und Process-Mining-Artefakte als Datenbankinhalte würden
die Datenbank unnötig vergrößern und die Arbeit mit spezialisierten Dateiformaten erschweren.
Deshalb bleiben solche Artefakte als Dateien im ignorierten Arbeitsverzeichnis.
