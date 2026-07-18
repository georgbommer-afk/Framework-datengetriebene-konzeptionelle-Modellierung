# Masterarbeit
Dieses Repository enthält die softwaretechnische Instanziierung eines im Rahmen meiner Masterarbeit entwickelten methodischen Frameworks.

Das Framework beschreibt, wie historische Ereignisdaten aus Produktions- und Intralogistiksystemen systematisch extrahiert, aufbereitet und mittels Process Mining analysiert werden können, um daraus Bestandteile eines konzeptionellen Modells für eine spätere ereignisbasierte Simulation abzuleiten. Die Software wird als ausführbares Minimum Viable Product (MVP) umgesetzt und soll die praktische Anwendung der einzelnen Frameworkschritte unterstützen.

## Zielsetzung
Ziel des Projekts ist die Entwicklung einer kleinen, ausführbaren Softwareanwendung, welche die Anwendung des methodischen Frameworks unterstützt, der Fallstudie als Werkzeug dient und hoffentlich späteren Interessierten Studenten zugute kommt.

Die geplante Verarbeitung umfasst insbesondere:
1. Import historischer Daten,
2. Auswahl und Zuordnung relevanter Datenspalten,
3. Transformation und Aufbereitung der Rohdaten,
4. Prüfung der Datenqualität,
5. Erstellung eines für Process Mining geeigneten Event Logs,
6. Durchführung ausgewählter Process-Mining-Analysen,
7. Aggregation und Aufbereitung der Analyseergebnisse,
8. Ableitung von Bestandteilen eines konzeptionellen Modells,
9. Ergänzung und Validierung durch die anwendende Person,
10. Speicherung und Export der erzeugten Ergebnisse.

Die Anwendung soll dabei keine vollständig automatisierte Modellbildung darstellen. Fachliche Entscheidungen, Domänenwissen und menschliche Validierung bleiben über den gesamten Ablauf hinweg erforderlich.

## Wissenschaftlicher Kontext
Das Repository begleitet meine Masterarbeit mit dem Titel: **Datengetriebene konzeptionelle Modellierung von Produktions- und Intralogistiksystemen: Framework zur systematischen Nutzung historischer Ereignisdaten**

Im Mittelpunkt steht folgende Forschungsfrage:
> Wie können historische Ereignisdaten aus industriellen Informationssystemen systematisch aufbereitet und mit Process Mining analysiert werden, um Elemente für ein konzeptionelles Modell eines Produktions- oder Intralogistiksystems abzuleiten?
Das methodische Framework stellt das primäre Forschungsartefakt dar. Die Software dient als praktische Instanziierung dieses Frameworks und wird im Rahmen einer Fallstudie demonstriert und evaluiert.

## Abgrenzung
Das Projekt umfasst die Verarbeitung historischer Ereignisdaten bis zur Erstellung eines konzeptionellen Modells. Nicht Bestandteil des MVP sind insbesondere:
- die vollständige automatisierte Generierung eines operationellen Simulationsmodells,
- die Ausführung einer ereignisbasierten Simulation,
- die Verarbeitung kontinuierlich eintreffender Echtzeitdatenströme,
- die automatische Umsetzung oder Bewertung identifizierter Verbesserungsmaßnahmen.

Das erzeugte konzeptionelle Modell kann jedoch als Grundlage für eine spätere technische Umsetzung in einer Simulationssoftware dienen.

## Geplante Funktionen
### Datenimport
Die Anwendung soll strukturierte historische Daten aus Dateien importieren können. Abhängig vom Entwicklungsstand können später zusätzlich direkte Datenbankverbindungen unterstützt werden.

Vorgesehene Formate sind insbesondere:
- CSV,
- Excel,
- gegebenenfalls weitere tabellarische Formate.

### Datenzuordnung
Die anwendende Person soll relevante Spalten den für Process Mining benötigten Informationen zuordnen können, beispielsweise:
- Fall- oder Objektkennzeichen,
- Aktivitätsbezeichnung,
- Zeitstempel,
- Ressourcen,
- weitere Fall- und Ereignisattribute.

### Datenaufbereitung
Die Software soll ausgewählte Schritte des ETL-Prozesses unterstützen. Dazu zählen unter anderem:
- Auswahl relevanter Datensätze,
- Zusammenführung von Daten,
- Behandlung fehlender Werte,
- Vereinheitlichung von Bezeichnungen,
- zeitliche Sortierung,
- Filterung,
- Aggregation,
- Erkennung auffälliger oder fehlerhafter Einträge.

### Event-Log-Erstellung
Aus den aufbereiteten Daten soll ein standardisiertes Event Log erzeugt werden. Die Mindestanforderungen umfassen:
- Fall- oder Objektzuordnung,
- Aktivitätsbeschreibung,
- Zeitbezug.
Zusätzliche Attribute sollen nach Möglichkeit erhalten und für spätere Analysen nutzbar gemacht werden.

### Process Mining
Das erzeugte Event Log soll für ausgewählte Process-Mining-Analysen verwendet werden können. Geplant sind insbesondere:
- Prozessentdeckung,
- Analyse von Prozessvarianten,
- Häufigkeitsanalysen,
- zeitliche Analysen,
- Analyse von Ressourcenbezügen,
- Identifikation ausgewählter Auffälligkeiten und
  Verbesserungspotenziale.

### Konzeptionelles Modell
Die gewonnenen Ergebnisse sollen strukturiert auf Bestandteile eines konzeptionellen Modells abgebildet werden. Dazu zählen:
- Problemstellung,
- Zielsetzung,
- Modellgrenzen,
- Entitäten,
- Aktivitäten,
- Warteschlangen,
- Ressourcen,
- Ein- und Ausgangsgrößen,
- Annahmen und Vereinfachungen,
- Prozessdarstellung.
Nicht unmittelbar aus den Daten ableitbare Bestandteile werden durch manuelle Eingaben und Domänenwissen ergänzt.

### Speicherung und Export
Die Anwendung soll Zwischenergebnisse und finale Ausgaben speichern beziehungsweise exportieren können. Dazu können gehören:
- aufbereitete Datensätze,
- Event Logs,
- Datenqualitätsberichte,
- Process-Mining-Ergebnisse,
- Prozessgrafiken,
- aggregierte Kennzahlen,
- dokumentierte Modellbestandteile,
- das resultierende konzeptionelle Modell.

## Human-in-the-Loop-Prinzip
Das Framework und seine softwaretechnische Instanziierung folgen einem Human-in-the-Loop-Ansatz. Die Software unterstützt die Datenverarbeitung und Modellableitung, ersetzt jedoch nicht die fachliche Bewertung. An verschiedenen Stellen sind deshalb menschliche Entscheidungen, Prüfungen und mögliche Rücksprünge vorgesehen. Dies betrifft beispielsweise:
- die Auswahl relevanter Daten,
- die semantische Zuordnung von Tabellen und Spalten,
- die Festlegung des Detaillierungsgrads,
- die Behandlung von Datenqualitätsproblemen,
- die Interpretation der Process-Mining-Ergebnisse,
- die Ergänzung nicht beobachtbarer Modellbestandteile,
- die konzeptionelle Validierung.

## Geplante Repository-Struktur
```text
process-mining-conceptual-model-framework/
├── README.md
├── docs/
│   ├── framework/
│   ├── anforderungen/
│   └── entscheidungen/
├── data/
│   ├── beispieldaten/
│   └── README.md
├── examples/
├── src/
│   ├── import/
│   ├── preprocessing/
│   ├── event_log/
│   ├── process_mining/
│   ├── conceptual_model/
│   ├── export/
│   └── app/
├── tests/
├── outputs/
└── requirements.txt
