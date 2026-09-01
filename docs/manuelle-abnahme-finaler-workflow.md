# Manuelle Abnahme des finalen Workflows

Diese Abnahme ergänzt die automatisierten Tests um die Browser- und Navigationspfade, die
Streamlit-AppTest nicht vollständig simulieren kann. Für einen isolierten Lauf können eine eigene
Datenbank und ein eigener Workspace gesetzt werden:

```bash
export FRAMEWORK_MVP_DB_PATH=/tmp/framework-mvp-abnahme/framework.sqlite
export FRAMEWORK_MVP_WORKSPACE_PATH=/tmp/framework-mvp-abnahme/workspace
export FRAMEWORK_MVP_LOCAL_AUTH_TEST_MODE=true
python -m streamlit run streamlit_app.py
```

## Zehn-Schritte-Workflow

1. Ein Projekt anlegen und Schritt 1 abschließen. In Schritt 2 eine CSV- oder XLSX-Datei
   importieren und als Ausgangsdaten verwenden.
2. `Zeilen löschen` wählen. Vor dem Anwenden müssen Trefferzahl, Beispielzeilen und erwartete
   Restzeilenzahl sichtbar sein. `Transformation anwenden` muss Plan, Ergebnis, Profil und
   Vorschau in einem Durchgang aktualisieren.
3. Eine zweite Transformation anwenden, zu einem späteren Schritt navigieren und anschließend in
   Schritt 2 zurückkehren. Beide Transformationen müssen chronologisch sichtbar sein; die zweite
   Transformation muss auf dem ersten Zwischenstand aufbauen. Folgeartefakte müssen als neu zu
   erzeugen gelten und der Fortschritt muss auf Schritt 2 zurückgesetzt sein.
4. Die Schritte 3 bis 10 mit den fachlich erforderlichen Eingaben durchlaufen. In Schritt 6 muss
   `DFG und Prozessmodell berechnen`, im Ergebnis-Unterschritt prüfen und erst mit
   `Weiter zu Schritt 7: Ergebnisse aggregieren` in Schritt 7
   `A_G berechnen und zu Schritt 8` jeweils ohne nachgeschaltete Speicherbestätigung weiterführen.
5. In mehreren späteren Frameworkschritten prüfen, dass Projekt- und Datensatzlöschung weiterhin
   links erreichbar sind. Die Dialoge müssen das Ziel nennen und nur `Abbrechen` sowie
   `Endgültig löschen` anbieten. Den Abbruchpfad ausführen und prüfen, dass nichts gelöscht wurde.

## HTML-Bericht im Browser

1. In Schritt 10 `HTML und PDF erzeugen` ausführen.
2. `Konzeptionelles Modell in neuem Tab öffnen` normal mit der linken Maustaste anklicken.
3. Es muss genau ein neuer Tab mit einer URL der Form `/media/<Prüfsumme>.html` geöffnet werden;
   `about:blank`, `data:` und lokale Dateipfade sind unzulässig.
4. Titel, Text, CSS-Layout und SVG-Grafiken prüfen. Der HTML- und der PDF-Download müssen
   angeboten werden; XLSX muss klar als deaktivierter Platzhalter erkennbar sein.
5. Optional in den Browser-Entwicklerwerkzeugen prüfen, dass der Link `target="_blank"` und
   `rel="noopener noreferrer"` enthält.

## Projektarchiv

1. Im Projektbereich prüfen, dass Import und Export gleich breite primäre Aktionen sind und der
   ZIP-Uploader keinen Dateigrößenhinweis anzeigt.
2. Das aktive Projekt exportieren und das unveränderte ZIP unmittelbar wieder auswählen.
3. Projektname, Projekt-ID und Exportzeitpunkt müssen angezeigt werden. Weil die ID bereits
   existiert, dürfen nur `Abbrechen` und `Vorhandenes Projekt ersetzen` angeboten werden.
4. Zuerst abbrechen und den unveränderten Projektstand prüfen. Danach dasselbe Archiv erneut
   auswählen, das Ersetzen bestätigen und Projektwahl, Fortschritt, Daten und Artefakte prüfen.
5. Mit einem Benutzer ohne Lösch-/Importrecht wiederholen. Das fremde Projekt darf weder ersetzt
   noch als verfügbar offengelegt werden.
