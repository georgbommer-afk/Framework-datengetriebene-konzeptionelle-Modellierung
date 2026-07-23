# ADR-006: Kanonisches Event Log und regelbasierte Datenqualität

## Kontext

Nach ETL und semantischem Mapping benötigt das Framework ein reproduzierbares Event Log als
Eingabe späterer Analysen. Vor Process Mining muss dessen technische und fachliche Qualität
transparent geprüft werden. Automatische Korrekturen würden Herkunft und fachliche Entscheidung
verschleiern.

## Entscheidung

Das kanonische Event Log besitzt mindestens `case_id`, `activity`, `timestamp` und eine stabile
technische `event_id`. Optionale Standardspalten und gemappte Fall-, Ereignis-, Ressourcen- und
Objektattribute bleiben erhalten. Technische Herkunftsspalten sichern Quellzeile und bei breiten
Datensätzen die ursprüngliche Zeitstempelspalte. Ereignisorientierte Daten werden zeilenweise
übernommen; breite Zeitstempeldaten werden anhand der gespeicherten Zuordnungen kontrolliert
unpivotiert. Zeitzonenlose Werte erhalten keine stillschweigende UTC-Annahme.

CSV.GZ ist das führende Event-Log-Artefakt. Schema-JSON dokumentiert Spalten, Typen, Rollen,
Zeitformat und Prüfsumme; Lineage-JSON verweist auf Projekt, Zwischendatensatz, Mapping,
Transformationsplan und Quellimporte. XES wird nicht erzeugt: Obwohl PM4Py vorhanden ist, bleibt
CSV.GZ in diesem Inkrement der eindeutig prüfbare Vertrag, und ein optionaler Export soll nicht
zusätzliche Semantik vorwegnehmen.

Die Datenqualität wird durch typisierte, konfigurierbare Regeln für Vollständigkeit, Validität,
Konsistenz, Eindeutigkeit und zeitliche Plausibilität geprüft. Befunde verändern keine Daten.
Maßnahmen sind unveränderlich, geordnet und müssen ausdrücklich gewählt werden. Ihre Vorschau
arbeitet auf einer Kopie und wird erneut geprüft. Das Original-Event-Log bleibt unverändert.

Rückkopplungen werden als Empfehlungen dargestellt: Import- und Typfehler verweisen auf Schritt
2, Rollenprobleme auf Schritt 3, Aufbau- oder Unpivotingprobleme auf Schritt 4 und rein
qualitative Entscheidungen verbleiben in Schritt 5. Es erfolgt keine automatische Navigation.

## Konsequenzen

- Event-IDs und technische Herkunft machen Quellereignisse reproduzierbar unterscheidbar.
- Process Mining kann später auf einen stabilen kanonischen Vertrag aufbauen.
- Qualitätsberichte und Maßnahmen bleiben prüfbar und wiederholbar.
- Ausschlüsse oder Ersetzungen erscheinen nur in einer neuen qualitätsgeprüften Arbeitskopie.
- CSV bewahrt spezialisierte Datentypen nicht vollständig; Schema und ISO-Zeitvertrag
  dokumentieren die Rekonstruktion.

## Verworfene Alternativen

- Direkte Mutation des ursprünglichen Event Logs wurde verworfen.
- Automatische destruktive Maßnahmen wurden verworfen.
- Freie Regel- oder Python-Code-Eingabe wurde aus Sicherheitsgründen verworfen.
- XES als führendes Format wurde wegen des zusätzlichen semantischen Übersetzungsschritts
  verworfen.
