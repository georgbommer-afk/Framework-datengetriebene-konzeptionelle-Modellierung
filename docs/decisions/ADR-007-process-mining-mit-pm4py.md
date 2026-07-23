# ADR-007: Process Mining mit PM4Py

## Kontext

Nach ETL, semantischem Mapping, Event-Log-Aufbau und Qualitätsprüfung liegt ein
qualitätsgeprüfter Event Log im kanonischen Format mit `case_id`, `activity` und
`timestamp` vor. Framework-Schritt 6 soll daraus reproduzierbare
Verhaltensübersichten und Prozessmodelle erzeugen, ohne dieses Artefakt zu verändern.

## Entscheidung

PM4Py wird über eine klar getrennte Integrationsschicht eingesetzt. Sie überführt
eine Arbeitskopie des kanonischen Logs in die von PM4Py erwarteten Spaltennamen.
PM4Py-spezifische Namen werden nicht dauerhaft gespeichert. Die verwendete
PM4Py-Version wird mit jeder Analyse dokumentiert.

Der frequenzbasierte Directly-Follows-Graph ist die grundlegende Prozesssicht.
Inductive Miner ist das vorausgewählte Standardverfahren; Heuristics Miner ist die
einzige Alternative. Varianten- und Aktivitätsfilter erzeugen ausschließlich eine
dokumentierte Analysesicht. DFG-Darstellungsfilter reduzieren nur sichtbare Kanten
und beeinflussen die Discovery-Eingabe nicht.

Gespeichert werden JSON, CSV.GZ, PNML, optional PTML und bei verfügbarer lokaler
Graphviz-Ausführung SVG. Python-Pickle-Dateien werden nicht verwendet. Das
qualitätsgeprüfte Original bleibt unverändert.

## Konsequenzen

- Analysegrundlage, Filter, Verfahren, Parameter und PM4Py-Version sind
  nachvollziehbar.
- Fehlendes Graphviz verhindert weder tabellarische DFG-Ausgaben noch Speicherung.
- Discovery, Oberfläche und Persistenz bleiben getrennt testbar.
- PM4Py unterliegt der AGPLv3; deren Bedingungen sind bei Nutzung und Verteilung zu
  berücksichtigen.

## Verworfene Alternativen

- Eine eigene Process-Mining-Notation wurde zugunsten öffentlicher PM4Py-APIs
  verworfen.
- Pickle wurde wegen Sicherheits-, Portabilitäts- und Versionsrisiken verworfen.
- Beliebige Miner und freie JSON-Parameter wurden zugunsten eines überschaubaren,
  typisierten MVP verworfen.
- Filter als Datenbereinigung wurden verworfen; fachliche Datenänderungen gehören
  in die vorgelagerten Schritte.

## Abgrenzung

Schritt 6 umfasst Discovery, Varianten, Häufigkeiten, Filter und DFG. Conformance
Checking, Token Replay, Alignments, Performance Mining, Bottleneck-Analyse,
KPI-Aggregation und Framework-Schritt 7 sind nicht Bestandteil dieser Entscheidung.
