# ADR-010: K* validieren und strukturiert ausgeben

## Status

Akzeptiert

## Kontext

Algorithmus 9 erhält ausschließlich das persistierte und erneut validierte Paar K/O sowie
menschliches Domänenwissen. Algorithmus 10 erhält ausschließlich das fachlich validierte K*.
Die ursprünglichen, datengetrieben übernommenen Inhalte und ihre Herkunft müssen erhalten
bleiben.

## Entscheidung

K* ist ein neues, unveränderliches JSON-Artefakt. Es referenziert K und O einschließlich ihrer
Datei- und Inhaltsprüfsummen, übernimmt alle elf ursprünglichen Bestandteile unverändert und
ordnet menschliche Behandlungen und zusätzliche Anpassungen separat dem jeweiligen Bestandteil
zu. Alle O-Einträge müssen behandelt sein; der Gesamtstatus muss `fachlich_validiert` lauten und
bewusst bestätigt werden. Identische Eingaben und Entscheidungen ergeben idempotent denselben
persistierten Validierungslauf. Schemaversion 10 ergänzt dafür eine additive Metadatentabelle.

Report und Excel werden bei Bedarf reproduzierbar direkt aus dem erneut validierten K* erzeugt.
Sie sind keine neuen Modellartefakte und werden nicht in der Datenbank gespeichert. Der Report
enthält keine neue Interpretation; die Arbeitsmappe löst verschachtelte Werte kontrolliert in
Tabellenzeilen auf und trennt ursprüngliche von menschlichen Inhalten.

## Folgen

K und O bleiben unverändert und prüfbar. Menschliche Entscheidungen sind explizit, einem
Bestandteil zugeordnet und durch einen Entscheidungsfingerabdruck gebunden. Schritt 10 kann ohne
erneute Datenaufbereitung, Process-Mining-Analyse oder Modellvalidierung ausgeführt werden.
