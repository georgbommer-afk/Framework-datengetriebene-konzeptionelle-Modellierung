# ADR-005: Reproduzierbare Transformation und semantisches Mapping

## Kontext

Bestätigte Rohdaten sollen nach der technischen Profilierung kontrolliert aufbereitet werden.
Die Aufbereitung muss fachlich nachvollziehbar bleiben und darf die unveränderten Raw-Artefakte
nicht überschreiben. Anschließend müssen technische Spalten einem ereignisorientierten
Begriffsmodell zugeordnet werden können, ohne bereits ein Event Log zu erzeugen.

## Entscheidung

Transformationen werden als unveränderliche, geordnete und aktivierbare Schritte in einem
Transformationsplan modelliert. Jeder Schritt enthält Typ, betroffene Spalten, explizite
Parameter, Reihenfolge, Beschreibung und optionale fachliche Begründung. Die Ausführung beginnt
bei jeder Vorschau erneut mit den bestätigten Rohdaten und arbeitet auf Kopien. Joins prüfen vor
der Ausführung Schlüsseltypen, Leerwerte, Kardinalität, nicht zuordenbare Schlüssel und die
erwartete Zeilenvervielfachung. Eine n:m-Verknüpfung benötigt eine ausdrückliche Bestätigung.

Die ETL-Oberfläche bündelt den Ablauf in fünf fachlichen Abschnitten. Sie übernimmt das zentral
gewählte Projekt, erkennt CSV und XLSX automatisch und kann bestätigte Importe nach einer
Integritätsprüfung ohne erneuten Upload wiederherstellen. Technische Import- und
Transformationsparameter bleiben reproduzierbar, werden jedoch nur schreibgeschützt angezeigt.
Jede Transformation besitzt fachlich typisierte Eingabefelder. Die abgeleitete Spalte unterstützt
insbesondere das geordnete Kombinieren beliebig vieler Textspalten mit Präfix, Suffix,
Trennzeichen und expliziter Fehlwertstrategie.

Ein erzeugter Zwischendatensatz besteht aus einer komprimierten CSV-Datei, einer Schema-JSON und
einer Transformation-JSON im projektbezogenen `interim`-Verzeichnis. SQLite speichert die
Metadaten und Beziehungen. Die drei bereits mit Inkrement D eingeführten Tabellen der
Schemaversion 4 werden dafür genutzt; die Schemaversion wird nicht unnötig erhöht.

Das semantische Mapping unterstützt ereignisorientierte und breite Zeitstempeldatensätze.
Mappingkonfiguration, Validierungsergebnis und Warnungen werden in SQLite sowie als
projektbezogene JSON-Datei gespeichert. Die Validierung erzeugt ausschließlich eine temporäre
Standardvorschau. Ein Event Log und Process Mining sind nicht Teil dieser Entscheidung.

Schritt 3 verwendet das zentral gewählte Projekt und den aktiven, integritätsgeprüften
Zwischendatensatz ohne lokale Projekt- oder Datensatzauswahl. Der Mappingablauf gliedert sich in
Datenstruktur, Rollen und Aktivität sowie Prüfung und Speicherung. Neue Mappings verwenden genau
eine Fall-ID-Spalte. Alte zusammengesetzte Fall-IDs bleiben beim Laden und beim Event-Log-Aufbau
ausführbar.

Eine Aktivität wird entweder aus einer vorhandenen Spalte übernommen oder durch eine additive
`Aktivitaetsdefinition` virtuell aus mehreren vorhandenen Spalten gebildet. Die Definition
speichert Reihenfolge, Trennzeichen, Präfix, Suffix und Fehlwertstrategie im bestehenden
Mapping-JSON. Fehlt sie in einem älteren Mapping, gilt weiterhin dessen bisherige
Aktivitätsspalte. Dadurch ist keine SQLite-Schemamigration erforderlich. Schritt 4 wendet die
gespeicherte Definition an, ohne sie neu zu interpretieren.

Optionale Standardrollen und die Attributgruppen Ereignis, Fall, Ressource und
Objektidentifikator werden dynamisch aus den tatsächlich verbleibenden Spalten angeboten. Eine
Spalte kann nur einmal verwendet werden. Validierungsfehler verhindern die Speicherung;
Warnungen erfordern eine ausdrückliche Kenntnisnahme. Die Vorschau erzeugt noch kein
Event-Log-Artefakt und der Zwischendatensatz bleibt unverändert.

Die frühere globale SVG-Prozessgrafik wird entfernt. Die Anwendung nutzt drei klar benannte
Hauptbereiche und lokale Fortschrittsanzeigen der jeweiligen Wizards.

## Konsequenzen

- Raw-Daten bleiben unverändert und Transformationen sind reproduzierbar.
- Zwischendatensätze lassen sich über Prüfsumme, Schema und Transformationshistorie prüfen.
- Fachliche Rollen bleiben von technischen Spaltennamen getrennt.
- CSV als Interim-Format ist lokal transparent und ohne zusätzliche Persistenzabhängigkeit
  nutzbar, bewahrt aber nicht jeden spezialisierten Pandas-Datentyp verlustfrei.
- JSON-Parameter erlauben intern eine vollständige Abbildung bestehender und neuer Regeln, ohne
  Benutzer mit frei editierbaren technischen Definitionen zu belasten.

## Verworfene Alternativen

- Direkte Veränderung bestätigter Raw-Dateien wurde wegen fehlender Reproduzierbarkeit
  verworfen.
- Freie Python-Ausdrücke für abgeleitete Spalten wurden aus Sicherheits- und
  Nachvollziehbarkeitsgründen verworfen.
- Eine zusätzliche Workflow-, Datenbank- oder Visualisierungsbibliothek wurde vermieden.
- Die unmittelbare Erzeugung eines Event Logs wurde verworfen, weil sie einen späteren
  Framework-Schritt vorwegnehmen würde.
