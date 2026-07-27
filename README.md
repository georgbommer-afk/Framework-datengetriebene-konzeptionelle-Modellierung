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

## Aktueller Funktionsumfang

Die Streamlit-Anwendung besitzt sechs Hauptbereiche: Projektverwaltung, ETL, semantisches
Mapping, Event-Log-Aufbau, Datenqualitätsprüfung und Process Mining. Projektbezogene
Datenquellen werden im Datenquellenkatalog Q registriert. Der zentral in Schritt 1 gewählte
Projektkontext gilt auch für den ETL-Schritt; ein Projektwechsel führt zurück zu Schritt 1. Der
fünfstufige ETL-Ablauf verbindet Datenquelle und Datei, Tabelle und Vorschau, Datenprofil,
Transformation und Ergebnis. CSV oder XLSX werden anhand von Endung und Inhalt erkannt.
CSV-Grundeinstellungen werden nach Möglichkeit automatisch ermittelt und können in erweiterten
Einstellungen korrigiert werden. Die unveränderte Vorschau umfasst maximal 200 Zeilen.

Vor einer Bestätigung bleiben Uploadbytes und Berechnungsergebnisse im Streamlit-Sitzungszustand.
Nach der im Profil integrierten Bestätigung werden Raw-Datei und Profil dauerhaft gespeichert.
Bestätigte Importe sind mit lesbarer Datei-, Tabellen- und Zeitangabe erneut wählbar; Raw-Pfad,
Prüfsumme und Profil werden vor der Wiederverwendung validiert. Die maximale Uploadgröße beträgt
standardmäßig 50 MB und kann mit einer positiven Ganzzahl in
`FRAMEWORK_MVP_MAX_UPLOAD_MB` angepasst werden.

Die technische Profilierung berechnet Gesamtkennzahlen, echte Pandas-Fehlwerte, getrennte
textuelle Fehlwertplatzhalter sowie numerische, kategoriale und zeitbezogene Spaltenprofile auf
der vollständigen Tabelle. Aggregierte Histogramme, Boxplots, Kategoriehäufigkeiten und
Zeitintervalle unterstützen die visuelle Prüfung, ohne die Quelldaten zu verändern. Eine
Die Profilansicht erklärt leere Werte und textuelle Platzhalter getrennt, übersetzt technische
Datentypen und hebt auffällige Spalten hervor. Die verbindliche Auswahl als Ausgangsdaten ist
direkt am Ende dieses Abschnitts angeordnet.

Die lokale Artefaktstruktur lautet:

```text
workspace/projects/<projekt-id>/
├── raw/<sha256>/<sicherer-dateiname>
├── profiles/<import-id>.json
├── interim/<zwischendatensatz-id>.csv.gz
├── interim/<zwischendatensatz-id>.schema.json
├── interim/<zwischendatensatz-id>.transformation.json
├── mappings/<mapping-id>.json
├── event_logs/<event-log-id>.csv.gz
├── event_logs/<event-log-id>.schema.json
├── event_logs/<event-log-id>.lineage.json
├── quality/<quality-run-id>.report.json
├── quality/<quality-run-id>.measures.json
├── quality/<quality-run-id>.csv.gz
├── process_mining/<analyse-id>.summary.json
├── process_mining/<analyse-id>.variants.csv.gz
├── process_mining/<analyse-id>.dfg.json
└── process_mining/<analyse-id>.model.pnml
```

Nach der Importbestätigung können geordnete, aktivierbare Transformationspläne erstellt werden.
Sie unterstützen Spaltenauswahl und -umbenennung, Typkonvertierung, explizite Behandlung von
Platzhaltern, Fehlwerten, Duplikaten und Ausreißern, Filter sowie das Kombinieren beliebig vieler
Textspalten. Die Oberfläche verwendet typisierte Eingaben; reproduzierbares JSON bleibt
schreibgeschützt einsehbar. Kontrollierte Left-, Inner- und Full-Outer-Joins erklären ihre
fachliche Wirkung, prüfen Schlüssel und Kardinalität und verlangen bei n:m-Beziehungen eine
Bestätigung. Raw-Dateien bleiben unverändert. Ein erzeugter Zwischendatensatz T wird als
`CSV.GZ`, Schema-JSON und Transformation-JSON im Ordner `interim` gespeichert. Nach erfolgreicher
Prüfung der Artefakte navigiert die Anwendung automatisch zum semantischen Mapping.

Framework-Schritt 3 übernimmt das zentral gewählte Projekt und den aktiven, integritätsgeprüften
Zwischendatensatz. Der kompakte Ablauf besteht aus Datenstruktur, Zuordnung sowie Prüfung und
Speicherung. Ereignisorientierte Daten besitzen eine Ereigniszeile mit Fall-ID, Aktivität und
Zeitstempel; breite Daten enthalten mehrere Zeitstempelspalten, aus denen Schritt 4 Ereignisse
erzeugt. Neue Mappings verwenden genau eine vorhandene oder bereits in Schritt 2 kombinierte
Fall-ID-Spalte. Die Aktivität kann aus einer vorhandenen Spalte stammen oder virtuell aus mehreren
Spalten, Affixen und einem Trennzeichen zusammengesetzt werden. Optionale Standardrollen und
Attributgruppen werden dynamisch ausschließlich aus noch verfügbaren Spalten angeboten.
Validierung, Warnungsbestätigung und eine auf 100 Zeilen begrenzte kanonische Vorschau helfen bei
der fachlichen Prüfung. Schritt 3 verändert den Zwischendatensatz nicht und erzeugt noch kein
Event Log. Nach erfolgreicher Speicherung navigiert die Anwendung automatisch zu Schritt 4;
Mappingdateien liegen projektbezogen unter `mappings/`.

Framework-Schritt 4 wendet ein validiertes Mapping reproduzierbar an und erzeugt ein kanonisches
Event Log mit `case_id`, `activity`, `timestamp`, stabiler `event_id`, zusätzlichen Attributen
und technischer Herkunft. CSV.GZ ist das führende Artefakt; Schema und Lineage werden als JSON
gespeichert. Framework-Schritt 5 prüft dieses Event Log regelbasiert auf Vollständigkeit,
Validität, Konsistenz, Eindeutigkeit und zeitliche Plausibilität. Maßnahmen werden ausschließlich
explizit auf einer Arbeitskopie angewendet und gemeinsam mit Bericht und Vorher-Nachher-Vergleich
gespeichert. Das ursprüngliche Event Log bleibt unverändert.

Framework-Schritt 6 berechnet Varianten, Aktivitäts-, Start-, End- und
Directly-Follows-Häufigkeiten. Filter bilden ausschließlich eine dokumentierte
Analysesicht. Als Discovery-Verfahren stehen Inductive Miner und Heuristics Miner über
PM4Py zur Verfügung. Analysen werden als JSON, CSV.GZ und PNML sowie optional als PTML
und SVG gespeichert; Pickle wird nicht verwendet. Die SQLite-Schemaversion ist 6.
Conformance Checking, Token Replay, Alignments, Performance- und
Durchlaufzeitanalysen, Bottleneck-Analyse und KPI-Aggregation sind noch nicht enthalten.

## Geplante Funktionen
### Datenimport
Die Anwendung soll strukturierte historische Daten aus Dateien importieren können. Abhängig vom Entwicklungsstand können später zusätzlich direkte Datenbankverbindungen unterstützt werden.

Aktuell unterstützte Formate sind:
- CSV,
- Excel,

Direkte Datenbankverbindungen und weitere tabellarische Formate sind erst für spätere
Ausbaustufen vorgesehen.

Bekannte Einschränkung: Beim Lesen einzelner XLSX-Dateien kann Openpyxl auf unbekannte oder
bedingte Formatierungserweiterungen hinweisen. Diese Warnungen betreffen die Darstellung der
Arbeitsmappe, werden nicht global unterdrückt und verändern weder die hochgeladene Originaldatei
noch die importierten Zellwerte.

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

### Miniguide
für das Bearbeiten der sqlite-Dateien
1 - Finden
  cd /Users/georgbommer/MasterarbeitGithubRepo

  find . -type f \
    \( -iname "*.sqlite" -o -iname "*.sqlite3" -o -iname "*.db" \) \
    -not -path "./.git/*" \
    -not -path "./.venv/*" \
    -print
2 - Löschen
  find . -type f \
  \( -iname "*.sqlite" -o -iname "*.sqlite3" -o -iname "*.db" \) \
  -not -path "./.git/*" \
  -not -path "./.venv/*" \
  -print -delete
3 - Kontrollieren
find . -type f \
  \( -iname "*.sqlite" -o -iname "*.sqlite3" -o -iname "*.db" \) \
  -not -path "./.git/*" \
  -not -path "./.venv/*" \
  -print

Initieren der streamlit App als localhost
  .venv/bin/python -m streamlit run streamlit_app.py
