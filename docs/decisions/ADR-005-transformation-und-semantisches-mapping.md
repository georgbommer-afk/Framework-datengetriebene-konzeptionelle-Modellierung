# ADR-005: Reproduzierbare Transformation und getrennte Mappingtabelle M

## Status

Für Schritt 2 und Schritt 3 fachlich an die Abschnitte 3.6.6 und 3.6.7 angepasst.

## Kontext

Bestätigte Rohdaten sollen nach der technischen Profilierung kontrolliert aufbereitet werden.
Die Aufbereitung muss fachlich nachvollziehbar bleiben und darf die unveränderten Raw-Artefakte
nicht überschreiben. Anschließend müssen technische Spalten einem ereignisorientierten
Begriffsmodell zugeordnet werden können, ohne bereits ein Event Log zu erzeugen.

## Entscheidung

Transformationen werden als unveränderliche, geordnete und aktivierbare Schritte in einem
Transformationsplan modelliert. Jeder Schritt enthält Typ, betroffene Spalten, explizite
Parameter, Reihenfolge, Beschreibung und optionale fachliche Begründung. Die Ausführung beginnt
bei jeder Vorschau erneut mit den bestätigten Rohdaten und arbeitet auf Kopien. Für neue Pläne
sind gemäß Tabelle 3.11 ausschließlich Datentypkonvertierung, Wertersetzung, Entfernung exakter
Tupel-Duplikate und Entfernung vollständig leerer Spalten auswählbar. Ein Plan ohne
Transformation ist zulässig. Frühere Typen bleiben zur kontrollierten Erkennung alter Pläne im
Lademodell, werden aber weder angeboten noch als aktueller Sollprozess ausgeführt.

Joins sind eine nachgelagerte Verknüpfungsoperation zwischen separat bestätigten und
aufbereiteten Datensätzen. Unterstützt werden Left, Right, Inner und Outer Join. Vor der
Ausführung werden Schlüsselanzahl, Vorhandensein, technische Typen, Leerwerte, nicht zuordenbare
Schlüssel, Kardinalität, die erwartete Zeilenanzahl der gewählten Join-Art, Datenverlust und
Zeilenvervielfachung geprüft. Risikobehaftete Vervielfachungen benötigen eine ausdrückliche
Bestätigung.

Die ETL-Oberfläche bündelt den Ablauf in fünf fachlichen Abschnitten. Sie übernimmt das zentral
gewählte Projekt, erkennt CSV und XLSX automatisch und kann bestätigte Importe nach einer
Integritätsprüfung ohne erneuten Upload wiederherstellen. Technische Import- und
Transformationsparameter bleiben reproduzierbar. Die anwendende Person wählt jede
Transformation, ihre Zielspalte beziehungsweise Zielwerte und die Behandlung ausdrücklich.
Fachliche Interpretationen technischer Bezeichnungen sind Schritt 3 vorbehalten; das Bilden oder Kombinieren neuer Attribute
erfolgt erst in Schritt 4.

Ein erzeugter Zwischendatensatz besteht aus einer komprimierten CSV-Datei, einer Schema-JSON und
einer Herkunfts- und Transformation-JSON im projektbezogenen `interim`-Verzeichnis. Diese enthält
alle Ausgangsimporte, Profilreferenzen und die ausgeführte Historie. SQLite speichert Metadaten
und Beziehungen. Eine zusätzliche Schemamigration ist dafür nicht erforderlich.

Schritt 3 verwendet das zentral gewählte Projekt und den aktiven, integritätsgeprüften
Zwischendatensatz T ohne lokale Projekt- oder Datensatzauswahl. Seine einzige fachliche Ausgabe
ist die Mappingtabelle M. Ein Eintrag ordnet eine vorhandene technische Spaltenbezeichnung oder
einen tatsächlich enthaltenen technischen Wert einer freien fachlichen Bezeichnung zu.
Wertreferenzen bleiben an Quellspalte, technischen Datentyp und kanonisch serialisierten Wert
gebunden. Mehrere technische Referenzen dürfen dieselbe fachliche Bedeutung erhalten; eine
einzelne technische Referenz darf nicht widersprüchlich zugeordnet werden.

M beginnt als leere Menge und kann ausdrücklich als nicht erforderlich bestätigt werden. T wird
weder logisch noch physisch verändert. M wird datensatzbezogen als versioniertes JSON unter
`mapping_tables` und mit getrennten SQLite-Metadaten gespeichert. Beim Laden werden Artefakt,
Projekt, T sowie alle Spalten- und Wertreferenzen erneut geprüft.

Die bisher `SemantischesMapping` genannte Konfiguration von Datenstruktur, Fall-ID, Aktivität,
Zeitstempeln, Standardrollen und Attributgruppen ist fachlich eine Event-Log-Konfiguration für
Schritt 4. Ihr Domänen- und Artefaktformat bleibt aus Rückwärtskompatibilität erhalten, wird aber
nicht als M geladen. Der neue Alias `EventLogKonfiguration` benennt diese Rolle für neue Aufrufer
eindeutig. Schritt 4 erhält T und das leere oder befüllte M getrennt; eine fachliche Benennung
legt noch keine Event-Log-Rolle fest.

Die frühere globale SVG-Prozessgrafik wird entfernt. Die Anwendung nutzt drei klar benannte
Hauptbereiche und lokale Fortschrittsanzeigen der jeweiligen Wizards.

## Konsequenzen

- Raw-Daten bleiben unverändert und Transformationen sind reproduzierbar.
- Zwischendatensätze lassen sich über Prüfsumme, Schema und Transformationshistorie prüfen.
- Datenquellenkatalog Q, Datenprofil R und Zwischendatensatz T werden am Ende getrennt ausgegeben.
- Technische Referenzen, fachliche Bezeichnungen und Event-Log-Rollen bleiben getrennt.
- Die additive Schemaversion 7 führt nur die Tabelle `mappingtabellen` für M ein.
- CSV als Interim-Format ist lokal transparent und ohne zusätzliche Persistenzabhängigkeit
  nutzbar, bewahrt aber nicht jeden spezialisierten Pandas-Datentyp verlustfrei.
- JSON-Parameter erlauben intern eine vollständige Abbildung bestehender und neuer Regeln, ohne
  Benutzer mit frei editierbaren technischen Definitionen zu belasten.

## Verworfene Alternativen

- Direkte Veränderung bestätigter Raw-Dateien wurde wegen fehlender Reproduzierbarkeit
  verworfen.
- Abgeleitete oder kombinierte Spalten sowie freie Python-Ausdrücke wurden für Schritt 2
  verworfen, weil sie Tabelle 3.11 überschreiten und spätere Frameworkschritte vorwegnehmen.
- Eine zusätzliche Workflow-, Datenbank- oder Visualisierungsbibliothek wurde vermieden.
- Die unmittelbare Erzeugung eines Event Logs wurde verworfen, weil sie einen späteren
  Framework-Schritt vorwegnehmen würde.
- Eine Gleichsetzung fachlicher Bezeichnungen mit Fall-, Aktivitäts- oder Zeitrollen wurde
  verworfen, weil Abschnitt 3.6.7 die Attributfunktion ausdrücklich erst Schritt 4 zuordnet.
