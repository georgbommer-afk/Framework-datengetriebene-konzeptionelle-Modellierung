# Community-Cloud-Bereitstellung und manueller End-to-End-Test

## Bereitstellung

1. Im OIDC-Client die öffentliche Callback-URL
   `https://<app-name>.streamlit.app/oauth2callback` registrieren.
2. Die Werte aus `.streamlit/secrets.toml.example` in die Secret-Verwaltung der Community-
   Cloud-App übertragen. `cookie_secret` kryptografisch zufällig erzeugen. Echte Secrets nie in
   Repository, Logs oder Projektarchive kopieren.
3. Unter `[[systemadmin.identities]]` den exakten `issuer` und `subject` des ersten Admins
   hinterlegen. E-Mail allein ist unzulässig.
4. Die optionale Gast-TTL und Archivgrenzen über die in README dokumentierten Umgebungsvariablen
   setzen. Ohne Angaben gelten 24 Stunden und 250 MB/1 GB/5.000 Dateien.
5. App deployen. Ohne funktionierende OIDC-Konfiguration muss **Ohne Anmeldung testen** weiter
   funktionieren; **Anmelden / Kursgruppe öffnen** darf keine Kurs- oder Adminrechte gewähren.

## Manueller End-to-End-Test

### Gastprojekt exportieren und importieren

1. **Ohne Anmeldung testen** wählen und den Temporärhinweis prüfen.
2. Projektrahmen ändern und speichern. **Projekt exportieren** und anschließend
   **Projektarchiv herunterladen** wählen.
3. **Demo beenden und Daten löschen**, Zielname im Dialog prüfen und **Löschen** wählen.
4. Eine neue Gastdemo starten, das ZIP unter **Projekt importieren** wählen,
   **Projektarchiv prüfen** ausführen und danach **Projekt importieren** wählen.
5. Projektname, gespeicherten Framework-Schritt und Artefakte prüfen. Ein zweiter Browser mit
   eigener Gastdemo darf das Projekt auch mit bekannter UUID nicht öffnen.

### Tatsächlicher Projektlebenszyklus

- Ein Gastprojekt bleibt serverseitig bis zum Ablauf seiner Aktivitäts-TTL erhalten. Das
  Schließen eines Browser-Tabs ist weder Löschsignal noch verlässliche Wiederaufnahme; der nur
  im Session-State gehaltene Besitznachweis geht dabei verloren. **Demo beenden und Daten
  löschen** ist die einzige sofortige Löschaktion. Vorher steht der vollständige Projektexport
  zur Verfügung; ein Import bindet das Projekt an die neue Gastsitzung.
- Einen separaten Projekttyp „privates Einzelprojekt“ gibt es im aktuellen Datenmodell nicht.
  Dauerhafte angemeldete Projekte liegen in privaten Kurs- oder Arbeitsgruppen. Sie überleben
  Session-State-Bereinigung, Browser-Schließen und App-Neustart in SQLite und im Workspace und
  bleiben bis zu einer berechtigten Löschung oder der Aufbewahrungsbereinigung erhalten.
- Kursprojekte bleiben während Kurslaufzeit und Aufbewahrungsfrist wiederaufnehmbar. Erst nach
  `aufbewahrung_bis` entfernt die kontrollierte Kursbereinigung die zugehörigen Projekte. Vor
  Ablauf warnt die Seitenleiste und bietet den Kursgruppenexport an. Gast-TTL-Bereinigung darf
  weder private Kursgruppen noch ihre Projekte erfassen.

### Systemadmin und Gruppenleitung

1. Mit der in Secrets gebootstrappten Identität **Anmelden / Kursgruppe öffnen** wählen.
2. Im geschlossenen Bereich **Systemadministration** prüfen, dass die Identität Systemadmin ist.
3. Die Professorin einmal anmelden lassen, danach im Benutzerfeld auswählen und
   **Als Gruppenleitung freischalten** wählen.
4. Als Professorin neu anmelden. **Kursgruppe erstellen**, Bezeichnung, Beginn, Kursende,
   Aufbewahrung, Projekt-/Teilnehmendenlimit und Speicherlimit eingeben und speichern.

### Studentischer Beitritt und Projektarbeit

1. Als Professorin **Einladung erzeugen** wählen und den nur einmal vollständig sichtbaren Link
   über einen sicheren Kanal an den Studenten senden.
2. Link in einem getrennten Browser öffnen, OIDC-Anmeldung durchführen und Beitritt prüfen.
3. Als Professorin unter **Mitglieder und Projektteams** den Studenten einem Projekt zuweisen.
4. Als Student neu laden: Nur die beigetretene Gruppe und das zugewiesene Projekt dürfen sichtbar
   sein. Einen Frameworkschritt bearbeiten und speichern.
5. Als Professorin **Projekte und Fortschritt** öffnen. Team, Phase, Schritt,
   Gesamtfortschritt, letzte Aktivität, Ablauf und Speicherverbrauch prüfen. Das Projekt
   schreibgeschützt öffnen; bloßes Öffnen darf keinen Bearbeitungszugriff erzeugen.

### Kursarchiv, Ablauf und Löschung

1. Als Professorin **Kursgruppe exportieren** wählen, Datenschutzhinweis bestätigen und das ZIP
   herunterladen. Im ZIP dürfen keine aktiven Einladungen, Tokens oder Rechte enthalten sein.
2. In einer Testumgebung Kursende/Aufbewahrung auf kurze Werte setzen. Nach Kursende muss die
   Gruppe schreibgeschützt/abgelaufen sein. Vor Aufbewahrungsende muss eine Exportwarnung
   erscheinen.
3. App neu laden oder als Systemadmin **Bereinigung auslösen**. Nach Aufbewahrungsende müssen nur
   Projekte dieser Gruppe und deren Dateien gelöscht sein; andere Gruppen bleiben erhalten.
4. Alternativ als Gruppenleitung **Kursgruppe löschen**, Ziel prüfen und **Löschen** wählen.
5. Das Kursarchiv mit derselben OIDC-Issuer-/Subject-Identität importieren. Projekte und
   Fortschritt müssen zurückkehren; Mitgliederrechte und Einladungen müssen neu eingerichtet
   werden. Eine abweichende Leitung muss abgelehnt werden, außer ein Systemadmin verwendet den
   ausdrücklich gekennzeichneten Wiederherstellungspfad.
