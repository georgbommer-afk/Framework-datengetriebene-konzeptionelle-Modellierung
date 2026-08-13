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

Die Streamlit-Anwendung setzt alle zehn Frameworkschritte um. Schritt 2 übernimmt als
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
├── process_mining/<analyse-id>.model.{ptml|pnml|bpmn}
├── aggregation/<aggregations-id>.aggregation.json
├── aggregation/<sollmodell-id>.target.{original|replay}.pnml
├── aggregation/<conformance-id>.conformance.{json|csv}
├── aggregation/<auswertungs-id>.deviations.{json|csv}
├── model_derivations/<modellableitungs-id>/
│   ├── preliminary-conceptual-model-k.json
│   └── open-components-o.json
└── model_validations/<validierungslauf-id>/
    └── validated-conceptual-model-k-star.json
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
Fallidentifikation, Aktivitätsdefinition, Zeitstempelquellen, Strukturart, die optionalen
semantischen Rollen `resource`, `start_timestamp`, `end_timestamp` und `lifecycle` sowie die
ausdrücklich ausgewählten zusätzlichen Attribute; diese Angaben werden nicht in M gespeichert.
Konfigurationsversion 3 führt diese Rollen ein. Version 1 und 2 bleiben mit ihrer bisherigen
Semantik lesbar und reproduzierbar.

Bei ereignisorientierten Daten entsteht aus jeder Zeile von T genau ein Ereignis. Die Aktivität
kann aus einer vorhandenen Spalte oder aus mindestens zwei geordneten Attributen mit optionalem
Verknüpfungselement gebildet werden. Bei breiten Zeitstempeldaten entsteht für jeden vorhandenen
Wert einer ausgewählten Zeitstempelspalte ein Ereignis mit der dafür festgelegten
Aktivitätsbeschreibung. Ressource und Lifecycle können dort je Zeitstempelzuordnung festgelegt
werden; eine Start-/Endpaarung wird nicht abgeleitet. Nicht ausgewählte Attribute werden nicht
nach E übernommen.

Spalten- und typisierte Wertzuordnungen aus M werden ausschließlich beim Erzeugen von E
angewandt; T und M bleiben unverändert. E besitzt mindestens `case_id`, `activity` und
`timestamp` sowie die konfigurierten optionalen kanonischen Spalten, wird fallweise chronologisch
und bei Gleichständen stabil geordnet und als CSV.GZ mit Schema- und Lineage-JSON gespeichert.
Strukturelle Konfigurationsfehler blockieren Schritt 4; fehlende oder nicht interpretierbare
Ereigniswerte bleiben für das Quality-Gate in Schritt 5 erhalten.

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

### Ergebnisaggregation

Schritt 7 verwendet ausschließlich das aktive Projekt und die erneut validierte Lineage aus U,
R, T, E*, P und A_D. Die in U gespeicherten KPI-IDs werden über 16 feste, versionierte
Definitionen aus A.7 bis A.10 angeboten. Jede Rechengröße wird ausdrücklich einer Profilkennzahl
aus R oder einer Spalte beziehungsweise Zeit-/Aktivitätsreferenz aus T oder E* zugeordnet. Es
gibt weder semantisches Raten noch zusätzliche KPIs oder einen Formeleditor. Fehlende oder
mehrdeutige Operanden führen für genau diese Kennzahl zum Status `nicht_berechenbar`; A_D und
andere berechenbare Bestandteile bleiben speicherbar.

Conformance Checking ist unabhängig und optional. Die anwendende Person kann es überspringen,
eine bestätigte lineare Sollsequenz aus vorhandenen E*-Aktivitäten als Workflow-Petrinetz
erzeugen oder ein unabhängig erstelltes PNML hochladen. Das in Schritt 6 entdeckte P wird nie zu
P_Soll erklärt. Der lineare Assistent bildet weder Verzweigungen noch Parallelität,
Synchronisation oder Schleifen ab. Für komplexe Netze steht WoPeD Next eingebettet mit festem
HTTPS-Link und Fallback in einen neuen Tab bereit; die Übernahme erfolgt ausschließlich über
bewussten PNML-Export und Upload.

PNML-Originalbytes bleiben unverändert. Eine getrennte Replay-Fassung darf eindeutig fehlende
Anfangs- und Endmarkierungen erst nach menschlicher Bestätigung aus genau einem Quell- und
Senkenplatz ergänzen. Import, Stellen, Transitionen, Kanten, sichtbare eindeutige Bezeichnungen,
Workflow-Netz und Soundness werden lokal geprüft. Aktivitäten werden nur exakt oder über ein
bestätigtes manuelles Mapping verbunden. Token Replay verwendet das vollständige E* und
dokumentiert produzierte, konsumierte, fehlende und verbleibende Tokens je Fall und aggregiert;
die Fitness folgt Gleichung 3.13. Diese Ergebnisse bilden A_C.

Die ebenfalls unabhängige Soll-Ist-Zeitauswertung verwendet ausdrücklich zugeordnete
Soll-Zeitstempel aus T, E* oder einer getrennt gespeicherten CSV-/XLSX-Datei. Fall- und
ereignisbezogene Schlüssel, Zeitstempel, Aktivitäten und Auftretensnummern werden menschlich
festgelegt; mehrdeutige Verknüpfungen blockieren die Auswertung. A_V enthält nur direkte
Zeitabweichungen und deren Klassifikation, keine kausale Erklärung oder Maßnahmenempfehlung.

A_G speichert keine Kopie von A_D, sondern dessen ID, Pfad und Prüfsumme. Es enthält die
KPI-Konfigurationen und -Ergebnisse sowie optional Referenzen auf P_Soll, Aktivitätsmapping, A_C,
Soll-Zeitdaten und A_V. A_G-Artefaktversion 2 ergänzt versionierte strukturierte Ergebnisse für
Aktivität-Ressourcen-Zuordnungen, Übergangswartezeiten und die zeitbezogene Datenauswahl aus
Q/R/T/E*. Vollständige kanonische Ressourcen werden automatisch, sonst manuell oder begründet
als `nicht_moeglich` dokumentiert. Bearbeitungszeit ist `Ende(A) − Start(A)`, Übergangswartezeit
ist `Start(B) − Ende(A)` und Zwischenankunftszeit basiert auf einem ausdrücklichen
Ankunftszeitpunkt oder dem ersten gültigen Ereignis je Fall. Negative und nicht auswertbare
Zeitdifferenzen werden getrennt gezählt. A_G v1 bleibt unverändert lesbar; neue Speicherungen
schreiben v2. Schemaversion 8 ergänzt dafür ausschließlich eine additive Metadatentabelle.
Ungespeicherte Vorschauen sind an sämtliche Eingaben und Entscheidungen
gebunden. Beim Laden und vor der Übergabe werden Lineage, Artefaktversion, Existenz und alle
Prüfsummen erneut geprüft. Schritt 8 erhält ausschließlich das unveränderte P aus Schritt 6 und
das gültige A_G.

### Modellbestandteile ableiten

Schritt 8 lädt ausschließlich die aktive und erneut validierte Lineage U, S, Q, R, T, E*, P
und A_G. Q wird dabei nur über die in T referenzierten Importe aufgelöst; P muss exakt der
Prozessmodellreferenz in A_G entsprechen. P_Soll und externe Soll-Zeitdaten sind keine
eigenständigen Quellen von Schritt 8. A_D, A_C, KPI-Ergebnisse und A_V werden ausschließlich
über das unveränderte A_G berücksichtigt.

Die elf Bestandteile aus Abschnitt 2.3.1 werden in stabiler Reihenfolge nach der festen
Quellenmatrix aus Tabelle 3.15 verarbeitet. Direkte Übernahmen, kontrollierte
Metadatenzusammenfassungen und Artefaktreferenzen tragen jeweils Quell-ID, Quellprüfsumme und
Strukturpfad. Es gibt in Schritt 8 keine fachliche Berechnung: Eine `case_id` wird nicht zum
Entitätstyp und Ressourcen-, Übergangswartezeit- sowie Zeitdatenergebnisse werden ausschließlich
aus der strukturierten A_G-Sektion übernommen. Bei A_G v1 bleiben diese Inhalte nachvollziehbar
offen, statt aus E* nachberechnet zu werden. Aktivitäten werden unverändert aus Prozessbaum,
Petrinetz oder BPMN gelesen; stille
Petrinetztransitionen bleiben ausgeschlossen.

Das vorläufige konzeptionelle Modell K enthält nur belegte Informationen. Fehlende, nicht
ableitbare oder fachlich unsichere Inhalte stehen getrennt und unverändert `offen` in O. Die
Bestandteile Ausgaben und Eingaben, Warteschlangen sowie Annahmen und Vereinfachungen behalten
den tatsächlich nicht ableitbaren Ergänzungsbedarf. Die Vorschau wird beim Öffnen automatisch
erzeugt und ordnet alle elf Bestandteile in einer Tabelle zu. Schritt 8 besitzt keine
Unsicherheits- oder Bestätigungscheckbox und keine fachlichen Eingabefelder. UUIDs und
Prüfsummen stehen nur unter den technischen Details. Der Discovery-Wert k wird als technische
Abstraktions- und Darstellungsentscheidung, nicht als fachlicher Detaillierungsgrad ausgewiesen.

K und O werden gemeinsam, projekt-, versions- und lineagegebunden gespeichert. Schemaversion 9
ergänzt dafür ausschließlich eine additive Metadatentabelle. Identische Eingaben,
Mappingversion und Eingabefingerabdruck sind idempotent. Die neue Quellenmatrix verwendet
Mappingversion 2. Bestehende K/O-Artefakte mit Mappingversion 1 werden nicht umgeschrieben;
sie müssen bei Bedarf aus dem weiterhin lesbaren A_G neu abgeleitet werden. Jede Änderung an
U, S, Q, R, T,
E*, P oder A_G invalidiert eine Vorschau. Vor Download, Wiederaufnahme und
Übergabe werden beide Dateien, ihre gegenseitige Referenz, Prüfsummen, elf Bestandteile und die
vollständige Eingangslineage erneut geprüft. Schritt 9 erhält ausschließlich K und O. K ist noch
kein fachlich validiertes K*; Ergänzung, Konfliktauflösung und Validierung gehören zu Schritt 9.

### Modell ergänzen, validieren und ausgeben

Schritt 9 lädt ausschließlich das aktive, erneut validierte Paar K und O. Jeder Eintrag aus O
wird mit der ursprünglichen Kategorie und Begründung einer menschlichen Entscheidung
`bestätigt`, `ergänzt_oder_angepasst` oder `nicht_anwendbar` zugeordnet. Fachliche Inhalte und
Begründungen werden als zusätzliche menschliche Einträge dokumentiert; die ursprünglichen
Informationen aus K und ihre Herkunft bleiben unverändert. Bei Anpassungsbedarf können auch
zuvor nicht offene Bestandteile separat ergänzt werden. K* entsteht erst, wenn alle O-Einträge
behandelt sind, kein weiterer Anpassungsbedarf besteht und die Gesamtvalidierung bewusst
bestätigt wurde.

K* enthält alle elf Bestandteile in stabiler Reihenfolge, Referenzen und Prüfsummen von K und O,
sämtliche menschlichen Entscheidungen sowie Validierungsstatus und -vermerk. Der Lauf wird
atomar, projektgebunden und für identische Eingaben und Entscheidungen idempotent gespeichert.
Die gemeinsame additive Schemaversion 10 ergänzt hierfür nur die Metadaten von K*; K und O
bleiben unverändert.

Schritt 10 akzeptiert ausschließlich ein erneut geprüftes, fachlich validiertes K*. Aus diesem
Artefakt werden wahlweise ein kompakter PDF-Report, eine strukturierte Excel-Arbeitsmappe oder
beide Dateien reproduzierbar erzeugt. Beide Formate enthalten alle elf Bestandteile und trennen
ursprünglich übernommene Informationen von menschlichen Ergänzungen und Anpassungen. Schritt 10
ergänzt oder validiert das Modell nicht und persistiert keine Exportdateien.

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

## Ausgeben der html
open workspace/report_preview/report.html
