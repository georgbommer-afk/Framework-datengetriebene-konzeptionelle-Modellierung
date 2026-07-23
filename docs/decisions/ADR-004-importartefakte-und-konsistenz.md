# ADR-004: Importartefakte und Konsistenz

## Status

Akzeptiert

## Kontext

Nach Datenvorschau und technischer Profilierung muss ein bestätigter Import reproduzierbar
erhalten bleiben. Strukturierte Metadaten sollen abfragbar sein, während unveränderte
Originaldateien und vollständige Profilberichte deutlich größer werden können. SQLite und das
lokale Dateisystem bieten keine gemeinsame atomare Transaktion.

## Entscheidung

SQLite bleibt die führende Ablage für Importmetadaten, Beziehungen, Status,
Profilzusammenfassungen und relative Artefaktpfade. Die unveränderte Originaldatei wird im
projektbezogenen Workspace unter `raw/<sha256>/<sicherer-dateiname>` inhaltsadressiert abgelegt.
Dadurch können mehrere Importe oder Excel-Blätter dieselbe geprüfte Raw-Datei referenzieren, ohne
sie unkontrolliert zu duplizieren. Das vollständige technische Profil wird mit einer zentralen
Profilversion als UTF-8-JSON unter `profiles/<import-id>.json` gespeichert.

Raw-Datei und Profil werden zunächst in temporäre Dateien im jeweiligen Zielverzeichnis
geschrieben, synchronisiert und mit `os.replace` atomar an ihren Zielort verschoben. Vor dem
SQLite-Schreibvorgang werden die Raw-Prüfsumme und die JSON-Struktur erneut validiert. SQLite
speichert ausschließlich relative Pfade; jeder Zugriff prüft, dass der aufgelöste Pfad innerhalb
des konfigurierten Workspace verbleibt.

## Kompensationsstrategie

Eine gemeinsame Transaktion über SQLite und Dateisystem ist technisch nicht verfügbar. Deshalb
werden zuerst die atomaren Dateisystemartefakte fertiggestellt und anschließend die
Importmetadaten innerhalb einer SQLite-Transaktion gespeichert. Schlägt ein Schritt fehl, werden
ausschließlich Artefakte entfernt, die im aktuellen Bestätigungsablauf neu erzeugt wurden. Eine
bereits vorher vorhandene, prüfsummengleiche Raw-Datei wird niemals durch die Kompensation
gelöscht. Ein fehlgeschlagener Ablauf erzeugt keinen bestätigten SQLite-Datensatz.

Die vor dem Schreiben stabil erzeugte Import-ID macht einen Streamlit-Bestätigungsvorgang
idempotent. Ist diese ID bereits gespeichert, wird derselbe Import zurückgegeben. Ein später
bewusst gestarteter Wizard-Durchlauf erhält eine neue ID und darf dieselbe Datei erneut
referenzieren.

## Integritätsprüfung beim Öffnen

Beim erneuten Öffnen werden Projekt- und Datenquellenbezug, sichere relative Pfade, Existenz und
SHA-256 der Raw-Datei sowie Existenz, Profilversion, Import-ID und Datei-Prüfsumme des Profil-JSONs
geprüft. Inkonsistente Importe werden mit einer verständlichen Meldung angezeigt und nicht als
fehlerfrei behandelt.

## Konsequenzen

- Schemaversion 4 ergänzt die Tabelle `importvorgaenge` und passende Suchindizes additiv.
- Originalbytes, Importparameter und technische Profile bleiben reproduzierbar nachvollziehbar.
- Gleiche Originaldateien können ohne unkontrolliertes Überschreiben wiederverwendet werden.
- Verwaiste Artefakte sind bei einem nicht kompensierbaren Prozessabbruch grundsätzlich möglich
  und können später durch eine Wartungsfunktion erkannt werden.
- Datenbereinigung, Transformation und konsolidierte Zwischendatensätze sind nicht Bestandteil
  dieser Entscheidung.

## Verworfene Alternativen

Dateiblobs in SQLite wurden wegen Datenbankwachstum und unhandlicher Dateioperationen verworfen.
Absolute Pfade wurden wegen mangelnder Portabilität verworfen. Eine Speicherung unter dem
Originaldateinamen ohne Prüfsummenverzeichnis wurde wegen Überschreibungs- und
Verwechslungsrisiken verworfen. Eine vorgetäuschte gemeinsame Transaktion über SQLite und
Dateisystem wurde verworfen, weil sie keine belastbare Atomaritätsgarantie bieten kann.
