# ADR-009: Vorläufiges Modell K und offene Bestandteile O

## Kontext

Algorithmus 8 ordnet die vorhandenen Ergebnisse U, S, Q, R, T, E*, P und A_G den 16
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
umfasst genau 16 Bestandteile. Ausgaben/Eingaben, Modellumfang/Modellgrenzen/
Detaillierungsgrad, Annahmen/Vereinfachungen und Datenauswahl/Daten bleiben jeweils getrennt.
Informationen werden ausschließlich direkt übernommen, als
kontrollierte Metadaten zusammengefasst oder als Artefakt referenziert. Jeder Eintrag enthält
Quellartefakt, Quell-ID, Quellprüfsumme und Strukturpfad. Nicht in Tabelle 3.15 vorgesehene
Quellen werden im Modell und beim erneuten Laden abgewiesen.

Problemstellung und Zielsetzung stammen ausschließlich aus U. KPI-Status und -Ergebnisse aus
A_G werden als potenzielle Ausgaben dokumentiert; `nicht_berechenbar` bleibt ohne Schätzung.
Experimentelle Faktoren und Wertebereiche werden nicht erfunden. P wird in den Notationen
Prozessbaum, Petrinetz und BPMN über die öffentliche PM4Py-Schnittstelle gelesen. Nur sichtbare
Aktivitäten werden übernommen. P_Soll wird weder gelesen noch als P verwendet. A_D, A_C,
KPI-Ergebnisse und A_V werden nur über A_G berücksichtigt.

Ressourcen, Entitäten, Warteschlangen und zeitbezogene Datenauswahl werden nur aus der
versionierten strukturierten Sektion von A_G übernommen. Schritt 8 berechnet diese Inhalte
niemals aus E* neu. Nur explizit bestätigte Warteschlangen sind als Warteschlangen übernehmbar;
potenzielle Wartezeiten bleiben davon getrennt und gehören zur Datenauswahl. `case_id` belegt
Entitätsinstanzen, nicht den fachlichen Typ. Maschinen bleiben Ressourcen. Der in A_G
referenzierte Discovery-Schwellwert k > 0 dokumentiert ausschließlich eine Abstraktion von P
und legt keinen fachlichen Detaillierungsgrad des Gesamtmodells fest.

Die automatisch erzeugte Zuordnung ist zunächst nur ein Vorschlag. Für jeden der 16 Bestandteile
ist eine explizite Entscheidung `vorschlag_uebernehmen`, `offen_fachlich_unsicher` oder
`vorschlag_nicht_uebernehmen` erforderlich. Die beiden letzten Entscheidungen benötigen eine
Begründung. Erst bestätigte Informationen werden K zugeordnet; nicht bestätigte Vorschläge
werden mit vollständigem Beleg und Begründung O zugeordnet.

K enthält alle 16 Bestandteile in stabiler Reihenfolge, ihre bestätigten Informationen, Status
und Referenzen auf O. O enthält ausschließlich offene Einträge der Kategorien `fehlend`,
`nicht_ableitbar` und `fachlich_unsicher`; Kennzeichnungsherkunft und Belege bleiben erhalten,
der Status ist stets `offen`. Systematisch erkannte und durch menschliche Prüfung entstandene
offene Punkte bleiben unterscheidbar. Teilweise offene Bestandteile können gleichzeitig
bestätigte K-Informationen und O-Referenzen besitzen.

K und O werden als zwei technische JSON-Artefakte mit eigener ID und Prüfsumme gemeinsam
erzeugt. O referenziert ID, Gesamt- und Dateiprüfsumme von K. Eine additive Schemaversion 9
speichert die gemeinsame Modellableitungs-ID, K-/O-IDs, A_G-, Analyse- und E*-Bezug,
Eingabefingerabdruck, Mappingversion, den aus Kompatibilitätsgründen in der Spalte
`unsicherheitsfingerabdruck` gespeicherten Entscheidungsfingerabdruck, Pfade und Prüfsummen.
Die aktuelle Quellenmatrix ist Mappingversion 3. Entscheidungen, Begründungen und Zeitpunkte
gehen in den Fingerabdruck ein. K/O mit Mappingversion 1 oder 2 werden kontrolliert historisch
gelesen, aber weder automatisch migriert noch als aktuelle Grundlage an Schritt 9 übergeben.
Identische Läufe werden über einen eindeutigen Schlüssel wiederverwendet. Dateischreibfehler
werden kompensiert.

Beim Laden werden Dateien, Artefakt- und Mappingversion, Gesamtprüfsummen, Beziehung zwischen K
und O, Quellenmatrix, Herkunftsprüfsummen, offene Referenzen, alle Einzelentscheidungen und die vollständige aktuelle
Lineage erneut geprüft. Änderungen an U, S, Q, R, T, E*, P oder A_G
erzwingen eine neue Vorschau. Schritt 9 erhält ausschließlich das validierte Paar K und O.

## Konsequenzen

- Eingangsartefakte werden nur als tiefe Arbeitskopien gelesen und nicht verändert.
- T und E* erscheinen nur als Referenzen, Schema- und Umfangszusammenfassungen; Zeilen werden
  nicht nach K kopiert.
- `case_id`, Attributnamen und Prozessstrukturen führen zu keiner automatischen fachlichen
  Interpretation; strukturierte Schritt-7-Ergebnisse werden lediglich zugeordnet.
- Ein technisches `menschlich_bestaetigt=True` entsteht erst nach allen 16 Entscheidungen.
- K ist ausdrücklich vorläufig und keine Vorwegnahme von K*.

## Abgrenzung

Nicht enthalten sind Datenaufbereitung, Process Discovery, KPI-Neuberechnung, Conformance
Checking, Warteschlangen- oder Ressourcenneuberechnung, semantische Interpretation,
fachliche Ergänzung, Konfliktauflösung, Maßnahmenempfehlung, Simulation, Validierung von K,
Erzeugung von K* oder eine endgültige Ausgabeform.
