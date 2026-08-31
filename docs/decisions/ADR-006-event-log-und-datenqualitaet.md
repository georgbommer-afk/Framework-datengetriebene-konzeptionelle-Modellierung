# ADR-006: Kanonisches Event Log und unveränderte E*-Freigabe

## Kontext

Nach ETL und semantischem Mapping benötigt das Framework ein reproduzierbares Event Log als
Eingabe späterer Analysen. Vor Process Mining muss dessen technische und fachliche Qualität
transparent geprüft werden. Automatische Korrekturen würden Herkunft und fachliche Entscheidung
verschleiern.

## Entscheidung

Mappingtabelle M und Event-Log-Konfiguration sind getrennte Artefakte. M enthält ausschließlich
fachliche Zuordnungen technischer Spaltenbezeichnungen und typisierter technischer Werte. Die
Event-Log-Konfiguration aus Schritt 4 bindet sich an genau ein Projekt und T und enthält optional
die ID von M, die Strukturart, genau eine Fallidentifikationsspalte, die Aktivitätsdefinition,
die Zeitstempelquellen, optionale semantische Rollen und die ausdrücklich ausgewählten
zusätzlichen Attribute. Konfigurationsversion 3 erlaubt in ereignisorientierten Daten die
kanonischen Rollen `resource`, `start_timestamp`, `end_timestamp` und `lifecycle` bei eindeutiger
technischer Belegung. Version 4 unterscheidet den verpflichtenden Ereigniszeitstempel `timestamp`
von den optionalen tatsächlichen Zeitpunkten `start_timestamp` und `end_timestamp`. Eine
Quellspalte darf in Version 4 zusätzlich zum Ereigniszeitstempel genau eine dieser beiden
Zeitrollen erfüllen; dieselbe Quelle darf nicht zugleich Start und Ende sein. Fehlende Start-
oder Endzeitpunkte werden niemals konstruiert. In breiten Daten werden Ressource und Lifecycle
ausschließlich je Zeitstempelzuordnung verwendet; eine nicht eindeutig begründete
Start-/Endpaarung wird nicht erzeugt. Version 1 bis 3 behalten ihre bisherige Semantik.

Das kanonische Event Log besitzt mindestens `case_id`, `activity`, `timestamp` und eine stabile
technische `event_id`. Bei ereignisorientierten Daten wird jede Zeile von T zu genau einem
Ereignis. Eine Aktivität stammt entweder aus einer vorhandenen Spalte oder aus mindestens zwei
geordneten Attributen mit optionalem Verknüpfungselement. Breite Zeitstempeldaten werden nur über
ausgewählte Zeitstempelspalten unpivotiert; jeder vorhandene Wert erzeugt ein Ereignis mit der
für diese Spalte konfigurierten Aktivitätsbeschreibung. Nur ausdrücklich ausgewählte zusätzliche
Attribute werden übernommen. Eine technische Quellspalte darf in Version 3 nicht mehreren
Standardrollen oder zusätzlich einem allgemeinen Attribut zugeordnet sein. Version 4 lockert
diese Regel ausschließlich für `timestamp` zusammen mit `start_timestamp` oder `end_timestamp`.

Fachliche Spalten- und Wertzuordnungen aus M werden auf einer tiefen Arbeitskopie angewandt. T und
M werden nicht verändert. Nicht gemappte Werte bleiben erhalten, Wertzuordnungen sind an
Quellspalte und Datentyp gebunden und gleiche fachliche Spaltennamen werden kollisionssicher
aufgelöst. Technische Herkunftsspalten und die zielrollenbezogene Lineage sichern Rohwerte,
Quellzeile und bei breiten Datensätzen die ursprüngliche Zeitstempelspalte. Innerhalb eines Falls
wird anhand von `timestamp` chronologisch sowie bei
Gleichständen stabil nach Quellzeile und Zeitstempelspaltenreihenfolge geordnet. Der allgemeine
Ereigniszeitstempel erhält weiterhin keine stillschweigende UTC-Annahme; konfigurierte Start- und
Endzeitstempel ab Version 3 werden als UTC-kompatible kanonische Spalten normalisiert.

CSV.GZ ist das führende Event-Log-Artefakt. Schema-JSON dokumentiert fachliche und technische
Spalten, Typen, Zeitformat und Prüfsumme. Lineage-JSON enthält Projekt, T, optionale M-ID, die
vollständige Event-Log-Konfiguration, angewandte Zuordnungen, technische Quellen,
Transformationsplan und Quellimporte. XES wird nicht erzeugt: Obwohl PM4Py vorhanden ist, bleibt
CSV.GZ in diesem Inkrement der eindeutig prüfbare Vertrag, und ein optionaler Export soll nicht
zusätzliche Semantik vorwegnehmen.

Schritt 4 prüft ausschließlich die Struktur der Konfiguration und die Existenz ihrer Referenzen.
Fehlende oder nicht interpretierbare Werte werden weder entfernt noch ersetzt, sondern mit ihren
Rohwerten in E erhalten. Ihre vollständige Qualitätsbewertung und eine mögliche Freigabe als
`E*` gehören ausschließlich zum Quality-Gate in Schritt 5.

Schritt 5 prüft stets die aus E abgeleitete und integritätsgeprüfte Kette aus Q, T, optional M,
Event-Log-Konfiguration und E. Maßgeblich sind die vier Kriterien aus Tabelle 3.14:

- Q dokumentiert Herkunft und Grundlagen der verwendeten Daten nachvollziehbar.
- T enthält die für die weitere Verarbeitung tatsächlich erforderlichen Daten vollständig.
- Ein vorhandenes M ordnet technische Bezeichnungen eindeutig und fachlich verständlich zu.
- E enthält seine Mindestbestandteile vollständig und interpretierbar.

Strukturelle Bindungen, Prüfsummen, technische Referenzen und die benötigten Spalten und Werte
werden automatisch geprüft. Die Nachvollziehbarkeit von Q, die Verständlichkeit eines befüllten
M und die Interpretierbarkeit von E erfordern zusätzlich begründete menschliche Bestätigungen.
Fachlich erklärbare Abwesenheiten in breiten Zeitstempelspalten oder zusätzlichen Attributen
werden transparent ausgewiesen und begründet bewertet. Es gibt weder deaktivierbare
Prüfbereiche noch einen numerischen Qualitätsscore.

Schritt 5 besitzt keine Korrektur- oder Maßnahmenlogik. Er verändert Q, T, M und E nicht, schließt
keine Ereignisse oder Fälle aus und erzeugt keine Qualitäts-CSV. Nicht behobene Mängel blockieren
die Freigabe und ermöglichen einen tatsächlichen Rücksprung zur Ursache: Q zu Schritt 1, T zu
Schritt 2, M zu Schritt 3 sowie Konfiguration oder Erzeugung von E zu Schritt 4.

Bei bestandenem Gate gilt `E* ← E`: E* ist eine Freigabereferenz auf exakt dasselbe E, keine
Datenkopie. Ein projektbezogener JSON-Bericht speichert Artefakt- und Softwareversion, die
vollständige Kettenbindung und ihre Prüfsummen, Befunde, Entscheidungen und Begründungen. Beim
erneuten Laden werden Bericht und aktuelle Artefaktkette vollständig geprüft. Änderungen an Q,
T, M, Konfiguration oder E entwerten die Freigabe.

Vorhandene regelbasierte Qualitätsberichte, Maßnahmenpläne und veränderte Arbeitskopien bleiben
über die Legacy-Schnittstelle kontrolliert lesbar. Sie werden nicht als E* interpretiert und
nicht an den regulären Schritt 6 übergeben. Process Mining lädt ausschließlich eine gültige
Freigabe desselben Projekts und damit wieder den ursprünglichen Event Log E.

## Konsequenzen

- Event-IDs, vollständige Konfiguration und technische Herkunft machen E reproduzierbar.
- Zusätzliche Attribute werden nicht durch frühere Rollengruppen erweitert, sondern explizit
  ausgewählt.
- Process Mining baut ausschließlich auf einer erneut validierten E*-Freigabe auf.
- Der Freigabebericht ist ein Audit- und Reproduzierbarkeitsartefakt, kein zusätzliches
  Frameworkergebnis und keine Datenkopie.
- Alte Qualitätskopien bleiben aus Rückwärtskompatibilitätsgründen lesbar, sind aber klar vom
  regulären Gate getrennt.
- CSV bewahrt spezialisierte Datentypen nicht vollständig; Schema und ISO-Zeitvertrag
  dokumentieren die Rekonstruktion.

## Verworfene Alternativen

- Direkte Mutation oder eine bereinigte Qualitätskopie von E wurde verworfen.
- Automatische und manuelle Korrekturmaßnahmen innerhalb von Schritt 5 wurden verworfen.
- Konfigurierbare Pflichtregeln und ein numerischer Gesamtscore wurden verworfen.
- XES als führendes Format wurde wegen des zusätzlichen semantischen Übersetzungsschritts
  verworfen.
