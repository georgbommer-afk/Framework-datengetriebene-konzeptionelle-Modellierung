# Masterarbeit
Dieses Repository enthält die softwaretechnische Instanziierung eines im Rahmen der Masterarbeit entwickelten methodischen Frameworks.

Das Framework beschreibt, wie historische Ereignisdaten aus Produktions- und Intralogistiksystemen systematisch extrahiert, aufbereitet und mittels Process Mining analysiert werden können, um daraus Bestandteile eines konzeptionellen Modells für eine spätere ereignisbasierte Simulation abzuleiten. Die Software wird als ausführbares Minimum Viable Product (MVP) umgesetzt und soll die praktische Anwendung der einzelnen Frameworkschritte unterstützen.

## Zielsetzung
Ziel des Projekts ist die Entwicklung einer minimalen, ausführbaren Softwareanwendung, welche die Anwendung des methodischen Frameworks unterstützt, der Fallstudie als Werkzeug dient und hoffentlich späteren Interessierten Studenten zugute kommt.

Die geplante Verarbeitung umfasst insbesondere (siehe dazu auch die zehn Schritte des theoretischen Frameworks):
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
Das Repository begleitet die Masterarbeit mit dem Titel: **Datengetriebene konzeptionelle Modellierung von Produktions- und Intralogistiksystemen: Framework zur systematischen Nutzung historischer Ereignisdaten**

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

## Aktueller Funktionsumfang

Die Streamlit-Anwendung besitzt sechs Hauptbereiche: Projektverwaltung, ETL, semantisches
Mapping, Event Log Aufbau, Datenqualitätsprüfung und Process Mining. Schritt 2 übernimmt als
fachliche Eingabe bereitgestellte CSV- oder XLSX-Datensätze (D) und erzeugt drei persistente
Ausgaben: den Datenquellenkatalog (Q), das Datenprofil (R) und den aufbereiteten
Zwischendatensatz (T). Der Projektkontext dient dabei nur der technischen Zuordnung.

Die lokale Struktur lautet:

```text
workspace/projects/<projekt-id>/
├── raw/<sha256>/<sicherer-dateiname>
├── profiles/<import-id>.json
├── interim/<zwischendatensatz-id>.csv.gz
├── interim/<zwischendatensatz-id>.schema.json
├── interim/<zwischendatensatz-id>.transformation.json
├── mapping_tables/<mapping-id>.json
├── mappings/<event-log-konfigurations-id>.json
├── event_logs/<event-log-id>.csv.gz
├── event_logs/<event-log-id>.schema.json
├── event_logs/<event-log-id>.lineage.json
├── quality/<freigabe-id>.release.json
├── process_mining/<analyse-id>.discovery.json
├── process_mining/<analyse-id>.dfg.json
├── process_mining/<analyse-id>.process-tree.ptml
└── process_mining/<analyse-id>.model.{ptml|pnml|bpmn}
```

## Geplante Funktionen
### Datenimport
Die Anwendung importiert strukturierte historische Daten aus Dateien. Direkte Abfragen aus
betrieblichen Quellsystemen oder Datenbanken sind nicht Bestandteil von Schritt 2.

Aktuell unterstützte Formate sind:
- CSV,
- Excel,

Direkte Datenbankverbindungen und weitere tabellarische Formate sind erst für spätere
Ausbaustufen vorgesehen.

Bekannte Einschränkung: Beim Lesen einzelner XLSX-Dateien kann Openpyxl auf unbekannte oder
bedingte Formatierungserweiterungen hinweisen. Diese Warnungen betreffen die Darstellung der
Arbeitsmappe, werden nicht global unterdrückt und verändern weder die hochgeladene Originaldatei
noch die importierten Zellwerte.

### Semantisches Mapping

Schritt 3 erhält den aktiven, integritätsgeprüften Zwischendatensatz (T) und erzeugt
ausschließlich die optionale Mappingtabelle (M). Darin können vorhandene technische
Spaltenbezeichnungen und tatsächlich enthaltene technische Werte freien fachlichen
Bezeichnungen zugeordnet werden. Wertzuordnungen bewahren Quellspalte, technischen Typ und Wert
als reproduzierbare Referenz. T selbst wird weder umbenannt noch inhaltlich verändert.

Wenn keine Interpretation erforderlich ist, wird ein ausdrücklich bestätigtes leeres M
gespeichert. Fall-ID, Aktivität, Zeitstempel, Ressourcen und weitere Event-Log-Rollen werden
erst in Schritt 4 konfiguriert. Bestehende Konfigurationen dafür bleiben im kompatiblen
`mappings`-Artefaktformat erhalten und werden nicht als M interpretiert.

### Datenaufbereitung
Das persistierte Profil umfasst die Strukturkennzahlen, fachlich benannte technische Datentypen,
potenzielle Fehlwertplatzhalter, Modus beziehungsweise Ausprägungsanzahl kategorialer Spalten
sowie die numerischen Kennzahlen und IQR-Ausreißergrenzen aus Abschnitt 3.6.6. Quartile werden
nach Gleichung 3.10 berechnet; die Stichprobenstandardabweichung gehört nicht zu (R).

Neue Transformationspläne bieten ausschließlich:

- Datentyp konvertieren,
- Werte ersetzen,
- exakte Tupel-Duplikate entfernen,
- vollständig leere Spalten entfernen.

Die Auswahl und Ausführung erfolgt ausdrücklich durch die anwendende Person; ein unveränderter
Durchlauf ist zulässig. Separat aufbereitete Datensätze können per Left, Right, Inner oder Outer
Join verknüpft werden. Fachliche Interpretationen werden erst in Schritt 3 in M erfasst, neue beziehungsweise
kombinierte Attribute erst in Schritt 4.

### Event-Log-Erstellung

Schritt 4 verwendet das zentrale Projekt, den aktiven integritätsgeprüften Zwischendatensatz T
und optional die getrennt gespeicherte Mappingtabelle M. Die Event-Log-Konfiguration enthält
Fallidentifikation, Aktivitätsdefinition, Zeitstempelquellen, Strukturart und die ausdrücklich
ausgewählten zusätzlichen Attribute; diese Angaben werden nicht in M gespeichert.

Bei ereignisorientierten Daten entsteht aus jeder Zeile von T genau ein Ereignis. Die Aktivität
kann aus einer vorhandenen Spalte oder aus mindestens zwei geordneten Attributen mit optionalem
Verknüpfungselement gebildet werden. Bei breiten Zeitstempeldaten entsteht für jeden vorhandenen
Wert einer ausgewählten Zeitstempelspalte ein Ereignis mit der dafür festgelegten
Aktivitätsbeschreibung. Nicht ausgewählte Attribute werden nicht nach E übernommen.

Spalten- und typisierte Wertzuordnungen aus M werden ausschließlich beim Erzeugen von E
angewandt; T und M bleiben unverändert. E besitzt mindestens `case_id`, `activity` und
`timestamp`, wird fallweise chronologisch und bei Gleichständen stabil geordnet und als CSV.GZ
mit Schema- und Lineage-JSON gespeichert. Strukturelle Konfigurationsfehler blockieren Schritt 4;
fehlende oder nicht interpretierbare Ereigniswerte bleiben für das Quality-Gate in Schritt 5
erhalten.

### Datenqualität und Freigabe

Schritt 5 ist ein nicht veränderndes Quality-Gate für die vollständige, aus der Lineage von E
abgeleitete Artefaktkette. Es prüft die vier Kriterien aus Tabelle 3.14: nachvollziehbar
dokumentierte Herkunft und Grundlagen in Q, die Vollständigkeit der für Schritt 4 benötigten
Daten in T, bei vorhandenem M eindeutige und fachlich verständliche Zuordnungen sowie
vollständige und interpretierbare Mindestbestandteile in E. Fehlendes, ausdrücklich bestätigt
leeres und befülltes M werden getrennt behandelt.

Automatische Integritäts- und Vollständigkeitsprüfungen werden mit begründeten menschlichen
Bewertungen verbunden; die vier Prüfbereiche können nicht deaktiviert werden und es gibt keinen
numerischen Gesamtscore. Ein Mangel blockiert die Freigabe und führt abhängig von seiner
Ursache zu Schritt 1, 2, 3 oder 4 zurück. Schritt 5 korrigiert, markiert, filtert, ersetzt oder
löscht keine Daten und erzeugt weder Maßnahmenplan noch Qualitäts-CSV.

Bei vollständig bestandenem Gate bedeutet `E* ← E`, dass eine persistierte Freigabereferenz auf
exakt den ursprünglichen Event Log entsteht. Event-Log-ID, Prüfsumme, Ereignisreihenfolge,
Spalten, Werte und Datentypen bleiben unverändert. Der JSON-Freigabebericht dokumentiert Q-, T-,
M-, Konfigurations- und E-Prüfsummen, Lineage, alle Befunde und die menschlichen Begründungen.
Beim Laden wird die gesamte Kette erneut validiert. Ältere Qualitätsberichte, Maßnahmenpläne und
Qualitätskopien bleiben als Legacy-Bestand kontrolliert lesbar, gelten aber nicht als E*.

### Process Mining
Schritt 6 verwendet ausschließlich eine aktuell gültige E*-Freigabe desselben zentralen
Projekts und lädt damit das unveränderte ursprüngliche E. Legacy-Qualitätskopien und nicht
freigegebene Event Logs werden nicht als Analysegrundlage angeboten. Aus dem vollständigen E*
wird stets ein frequenzbasierter Directly-Follows-Graph mit Häufigkeiten gebildet. Der
menschlich festgelegte Schwellwert `k ∈ [0,1]` wirkt ausschließlich auf die anschließende
Prozessentdeckung: Bei `k=0` läuft der reguläre Inductive Miner, bei `k>0` Inductive Miner –
infrequent. Ein höheres k erhöht den Abstraktionsgrad und kann seltenes Verhalten aus dem
Prozessmodell ausschließen; der DFG und E* bleiben davon unberührt.

Der Inductive Miner erzeugt genau einen Prozessbaum. Die anwendende Person wählt diesen
Prozessbaum, ein daraus konvertiertes Petrinetz oder BPMN als Prozessmodell P. P wird als PTML,
PNML beziehungsweise BPMN-XML gespeichert. Die Discovery-Ergebnisse A_D dokumentieren den
vollständigen DFG, k, Miner-Variante, Notation, PM4Py-Version sowie Referenzen und Prüfsummen.
Neue Analysen erzeugen keine Varianten- oder gefilterte Event-Log-Arbeitskopie. Bestehende
Heuristics-Miner- und Filteranalysen bleiben als Legacy lesbar, werden aber nicht im regulären
Ablauf angeboten. Nach erneuter Integritätsprüfung werden P und A_D an Schritt 7 übergeben.

Conformance Checking, Token Replay, Fitness, Performance-, Ressourcen-, Engpass- und
Kennzahlenanalysen gehören nicht zu Schritt 6.

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
```

## temporärer Miniguide für das Bearbeiten der sqlite-Dateien
### 1 - Finden
  cd /Users/georgbommer/MasterarbeitGithubRepo
  find . -type f \
    \( -iname "*.sqlite" -o -iname "*.sqlite3" -o -iname "*.db" \) \
    -not -path "./.git/*" \
    -not -path "./.venv/*" \
    -print
### 2 - Löschen
  find . -type f \
  \( -iname "*.sqlite" -o -iname "*.sqlite3" -o -iname "*.db" \) \
  -not -path "./.git/*" \
  -not -path "./.venv/*" \
  -print -delete
### 3 - Kontrollieren
find . -type f \
  \( -iname "*.sqlite" -o -iname "*.sqlite3" -o -iname "*.db" \) \
  -not -path "./.git/*" \
  -not -path "./.venv/*" \
  -print

## Initieren der streamlit App als localhost
  .venv/bin/python -m streamlit run streamlit_app.py
