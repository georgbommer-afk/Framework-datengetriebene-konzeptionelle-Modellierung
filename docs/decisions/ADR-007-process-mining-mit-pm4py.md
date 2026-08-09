# ADR-007: Process Mining mit PM4Py

## Kontext

Nach Schritt 5 liegt der freigegebene Event Log E* im kanonischen Format mit `case_id`,
`activity` und `timestamp` vor. Framework-Schritt 6 erzeugt daraus das Prozessmodell P und die
Discovery-Ergebnisse A_D, ohne E* zu verändern.

## Entscheidung

PM4Py wird über eine klar getrennte Integrationsschicht eingesetzt. Sie überführt
eine Arbeitskopie des kanonischen Logs in die von PM4Py erwarteten Spaltennamen.
PM4Py-spezifische Namen werden nicht dauerhaft gespeichert. Die verwendete
PM4Py-Version wird mit jeder Analyse dokumentiert.

Der frequenzbasierte Directly-Follows-Graph wird immer aus dem vollständigen E* gebildet. Es gibt
keine vorgelagerten Varianten-, Aktivitäts- oder DFG-Filter. Die anwendende Person entscheidet
ausschließlich über den Schwellwert `k ∈ [0,1]` und die Prozessnotation. Bei `k=0` wird der
reguläre Inductive Miner, bei `k>0` Inductive Miner – infrequent verwendet. k beeinflusst nur
die Prozessentdeckung, niemals DFG oder E*.

Der Inductive Miner erzeugt genau einmal einen Prozessbaum. Dieser wird entweder selbst als P
gewählt und als PTML gespeichert oder in ein Petrinetz (PNML) beziehungsweise BPMN
(BPMN-XML) überführt. Der interne Prozessbaum bleibt in den beiden letzten Fällen als
Reproduzierbarkeitsartefakt erhalten, ist aber nicht P. A_D ist ein versioniertes JSON-Artefakt
mit vollständigem DFG, k, Miner-Variante, Notation, PM4Py-Version sowie Referenzen und
Prüfsummen von P und den technischen Artefakten. SVG ist optional; fehlendes Graphviz blockiert
die strukturierten Ergebnisse nicht. Es entstehen weder Varianten-CSV noch Event-Log-Kopie oder
Pickle.

Jede Vorschau und Speicherung ist an Projekt, Freigabe-ID, Event-Log-ID und -Prüfsumme gebunden.
Beim Laden werden die E*-Freigabe und alle Artefaktprüfsummen erneut validiert. Nur neue gültige
Analysen exakt derselben Freigabe werden in der Oberfläche angeboten und an Schritt 7 übergeben.
Ältere Heuristics-Miner- oder Filteranalysen bleiben über den Legacy-Ladepfad lesbar.

## Konsequenzen

- E*, k, Miner-Variante, Prozessnotation und PM4Py-Version sind nachvollziehbar.
- Fehlendes Graphviz verhindert weder tabellarische DFG-Ausgaben noch Speicherung.
- Discovery, Oberfläche und Persistenz bleiben getrennt testbar.
- PM4Py unterliegt der AGPLv3; deren Bedingungen sind bei Nutzung und Verteilung zu
  berücksichtigen.

## Verworfene Alternativen

- Eine eigene Process-Mining-Notation wurde zugunsten öffentlicher PM4Py-APIs
  verworfen.
- Pickle wurde wegen Sicherheits-, Portabilitäts- und Versionsrisiken verworfen.
- Heuristics Miner und weitere Miner wurden verworfen; Algorithmus 6 legt IM beziehungsweise
  IMi eindeutig durch k fest.
- Varianten-, Aktivitäts- und gesonderte DFG-Schwellwerte wurden aus dem regulären Schritt 6
  entfernt.

## Abgrenzung

Schritt 6 umfasst ausschließlich den vollständigen DFG und Process Discovery. Conformance
Checking, Token Replay, Fitness, Performance- und Durchlaufzeitanalyse, Ressourcen- und
Engpassanalyse, KPI-Aggregation und Verbesserungspotenziale gehören zu Schritt 7. Schritt 6
stellt dafür lediglich die erneut validierten Ausgaben P und A_D im zentralen Kontext bereit.
