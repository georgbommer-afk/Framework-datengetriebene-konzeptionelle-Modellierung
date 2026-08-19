# ADR-009: Vorläufiges Modell K und offene Bestandteile O

## Kontext

Algorithmus 8 ordnet die vorhandenen Ergebnisse U, S, Q, R, T, E*, P und A_G den elf
Bestandteilen eines konzeptionellen Modells aus Abschnitt 2.3.1 zu. Das Ergebnis ist noch kein
validiertes Modell K*, sondern das vorläufige Modell K und der explizite Ergänzungs- und
Validierungsbedarf O. Fachliche Ergänzungen und Validierung gehören ausschließlich zu Schritt 9.

## Entscheidung

Schritt 8 besitzt einen abgegrenzten Modellableitungsservice. Ausgangspunkt ist die aktive
Aggregations-ID aus dem zentralen Sessionkontext. A_G und das darin referenzierte P werden über
die Schritt-7-Übergabe erneut validiert. U und S stammen aus derselben Projektspezifikation; R,
T und E* aus derselben Freigabe- und Importlineage. Q wird ausschließlich über die Import-IDs
von T aufgelöst. Eine Suche nach neuesten oder alternativen Artefakten findet nicht statt.

Die Quellenmatrix aus Tabelle 3.15 ist als unveränderlicher, versionierter Katalog kodiert. Sie
umfasst genau elf Bestandteile. Informationen werden ausschließlich direkt übernommen, als
kontrollierte Metadaten zusammengefasst oder als Artefakt referenziert. Jeder Eintrag enthält
Quellartefakt, Quell-ID, Quellprüfsumme und Strukturpfad. Nicht in Tabelle 3.15 vorgesehene
Quellen werden im Modell und beim erneuten Laden abgewiesen.

Problemstellung und Zielsetzung stammen ausschließlich aus U. KPI-Status und -Ergebnisse aus
A_G werden als potenzielle Ausgaben dokumentiert; `nicht_berechenbar` bleibt ohne Schätzung.
Experimentelle Faktoren und Wertebereiche werden nicht erfunden. P wird in den Notationen
Prozessbaum, Petrinetz und BPMN über die öffentliche PM4Py-Schnittstelle gelesen. Nur sichtbare
Aktivitäten werden übernommen. P_Soll wird weder gelesen noch als P verwendet. A_D, A_C,
KPI-Ergebnisse und A_V werden nur über A_G berücksichtigt.

Ressourcen, Übergangswartezeiten und zeitbezogene Datenauswahl werden nur aus der versionierten
strukturierten Sektion von A_G übernommen. Schritt 8 berechnet diese Inhalte niemals aus E* neu.
Ein lesbares A_G v1 ohne diese Sektion erzeugt dafür einen begründeten offenen Eintrag. Start-
und Endaktivitäten aus A_D/P dienen als Beleg des Modellumfangs. Der Discovery-Schwellwert k ist
eine technische Abstraktionsentscheidung und kein fachlicher Detaillierungsgrad.

K enthält alle elf Bestandteile in stabiler Reihenfolge, ihre belegten Informationen, Status und
Referenzen auf O. O enthält ausschließlich offene Einträge der Kategorien `fehlend`,
`nicht_ableitbar` und `fachlich_unsicher`; Kennzeichnungsherkunft und Belege bleiben erhalten,
der Status ist stets `offen`. Schritt 8 ergänzt O nur für tatsächlich fehlende oder nicht
ableitbare Inhalte und besitzt keine menschlichen Unsicherheitsmarkierungen.

K und O werden als zwei technische JSON-Artefakte mit eigener ID und Prüfsumme gemeinsam
erzeugt. O referenziert ID, Gesamt- und Dateiprüfsumme von K. Eine additive Schemaversion 9
speichert die gemeinsame Modellableitungs-ID, K-/O-IDs, A_G-, Analyse- und E*-Bezug,
Eingabefingerabdruck, Mappingversion, Unsicherheitsfingerabdruck, Pfade und Prüfsummen. Die
geänderte Quellenmatrix ist Mappingversion 2. K/O mit Mappingversion 1 werden nicht automatisch
migriert und müssen bei Bedarf aus dem weiterhin lesbaren A_G neu erzeugt werden.
Identische Läufe werden über einen eindeutigen Schlüssel wiederverwendet. Dateischreibfehler
werden kompensiert.

Beim Laden werden Dateien, Artefakt- und Mappingversion, Gesamtprüfsummen, Beziehung zwischen K
und O, Quellenmatrix, Herkunftsprüfsummen, offene Referenzen und die vollständige aktuelle
Lineage erneut geprüft. Änderungen an U, S, Q, R, T, E*, P oder A_G
erzwingen eine neue Vorschau. Schritt 9 erhält ausschließlich das validierte Paar K und O.

## Konsequenzen

- Eingangsartefakte werden nur als tiefe Arbeitskopien gelesen und nicht verändert.
- T und E* erscheinen nur als Referenzen, Schema- und Umfangszusammenfassungen; Zeilen werden
  nicht nach K kopiert.
- `case_id`, Attributnamen und Prozessstrukturen führen zu keiner automatischen fachlichen
  Interpretation; strukturierte Schritt-7-Ergebnisse werden lediglich zugeordnet.
- Widersprüchliche Belege bleiben getrennt und erzeugen einen offenen Klärungsbedarf.
- K ist ausdrücklich vorläufig und keine Vorwegnahme von K*.

## Abgrenzung

Nicht enthalten sind Datenaufbereitung, Process Discovery, KPI-Neuberechnung, Conformance
Checking, Warteschlangen- oder Ressourcenneuberechnung, semantische Interpretation,
fachliche Ergänzung, Konfliktauflösung, Maßnahmenempfehlung, Simulation, Validierung von K,
Erzeugung von K* oder eine endgültige Ausgabeform.
