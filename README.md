# Datengetriebene konzeptionelle Modellierung

Dieses Repository enthält einen ausführbaren Streamlit-Prototyp zur systematischen
Aufbereitung historischer Ereignisdaten, zur Process-Mining-Analyse und zur Ableitung eines
fachlich validierten konzeptionellen Modells. Die Anwendung führt durch zehn aufeinander
aufbauende Frameworkschritte und bewahrt die technische Lineage der erzeugten Artefakte.

## Wissenschaftlicher Zweck und Prototypstatus

Die Software ist die technische Instanziierung des im Rahmen der Masterarbeit
**„Datengetriebene konzeptionelle Modellierung von Produktions- und
Intralogistiksystemen: Framework zur systematischen Nutzung historischer Ereignisdaten“**
entwickelten Frameworks. Sie unterstützt die Fallstudie und macht die einzelnen Arbeitsschritte
reproduzierbar ausführbar.

Im Mittelpunkt steht die Forschungsfrage:

> Wie können historische Ereignisdaten aus industriellen Informationssystemen systematisch
> aufbereitet und mit Process Mining analysiert werden, um Elemente für ein konzeptionelles
> Modell eines Produktions- oder Intralogistiksystems abzuleiten?

Das methodische Framework ist das primäre Forschungsartefakt. Die Anwendung ist ein Minimum
Viable Product (MVP), kein fertiges Simulationswerkzeug und keine vollautomatische
Modellgenerierung. Fachliche Auswahl, Domänenwissen und menschliche Validierung bleiben bewusst
Bestandteil des Ablaufs.

Nicht zum Funktionsumfang gehören insbesondere:

- die Erzeugung oder Ausführung eines operationellen Simulationsmodells,
- die Verarbeitung kontinuierlicher Echtzeitdatenströme,
- eine automatische Bewertung oder Umsetzung von Verbesserungsmaßnahmen,
- eine dauerhaft garantierte Cloud-Persistenz,
- eine XLSX-Reportgenerierung.

## Betriebsarten, Authentifizierung und Mandantentrennung

Die Anwendung bietet getrennte öffentliche und private Einstiege:

- **Neues Projekt** öffnet einen leeren, temporären Bereich ohne vorab erzeugtes Projekt und
  ohne Demowerte. **Demoprojekt öffnen** erzeugt dagegen bewusst einen vollständigen,
  isolierten Durchlauf der Schritte 1–10 aus den versionierten synthetischen Produktionsdaten.
  Der kryptografisch zufällige Besitznachweis liegt nur im Streamlit Session State. Die
  Standard-TTL beträgt 24 Stunden seit der letzten Aktivität; bei Appstarts werden abgelaufene
  Gastprojekte opportunistisch bereinigt. Vor Ablauf kann jedes Projekt als portables Archiv
  exportiert werden.
- **Anmelden / Kursgruppe öffnen** verwendet Streamlits native OIDC-Funktionen `st.login`,
  `st.user` und `st.logout`. Die Anwendung speichert weder Passwörter noch OIDC-Token. Private
  Kursgruppen, Mitgliedschaften, Projektteams, Einladungen, Fortschritt, Aufbewahrung und
  Kursarchive werden serverseitig autorisiert verwaltet.

Teilnehmende sehen nur Projekte, denen sie aktiv zugewiesen sind. Gruppenleitungen können den
Fortschritt der Gruppenprojekte einsehen, erhalten durch das reine Öffnen aber keinen
Bearbeitungszugriff. Eine bekannte UUID ist kein Berechtigungsnachweis; Projekt- und
Gruppenoperationen prüfen den persistenten Zugriffskontext erneut.

Einladungstoken besitzen mindestens 256 Bit Entropie, werden nur einmal vollständig angezeigt
und in SQLite ausschließlich als SHA-256-Hash gespeichert. Der initiale Systemadmin wird über
ein exaktes Paar aus OIDC-Issuer und Subject konfiguriert; E-Mail-Adressen dienen nicht als
Identitätsschlüssel. Ohne OIDC-Konfiguration bleibt der Gastmodus verfügbar, es werden jedoch
keine Kurs- oder Administrationsrechte vergeben.

## Funktionsumfang und zehn Frameworkschritte

Die Anwendung zeigt oberhalb jeder Fachseite genau eine zentrale Fortschrittsanzeige. Sie
berücksichtigt den aktuellen Frameworkschritt und dessen fachlichen Unterschritt und gliedert den
Ablauf in drei Phasen:

1. **Phase 1 – Aufbereitung der Datenbasis:** Schritte 1–5
2. **Phase 2 – Datengetriebene Analyse des Systems:** Schritte 6–7
3. **Phase 3 – Überführung in das konzeptionelle Modell:** Schritte 8–10

Technische Anzeigeabschnitte zählen nicht als fachliche Unterschritte. Der aktuelle Fortschritt
wird für Gast- und Kursprojekte persistiert und im Kursdashboard mit derselben zentralen
Definition ausgewertet.

### 1. Projektrahmen definieren

Erfasst Projektbezeichnung, Problemstellung, Systemgrenze, Untersuchungszwecke, logistische
Zielgrößen, Systemklassifikation, gewünschte Auswertungen und KPIs. Daraus entstehen der
Untersuchungsauftrag U und das Systemprofil S.

### 2. ETL durchführen

Importiert CSV- oder XLSX-Dateien, dokumentiert ihre Datenquelle und erzeugt den
Datenquellenkatalog Q, das Datenprofil R und einen aufbereiteten Zwischendatensatz T. CSV-
Struktur, Kodierung und Kopfzeile beziehungsweise Excel-Arbeitsblatt und Kopfzeile werden vor
dem Speichern geprüft.

Transformationspläne unterstützen:

- Datentyp konvertieren,
- Werte ersetzen,
- exakte Tupel-Duplikate entfernen,
- vollständig leere Spalten entfernen,
- Zeilen anhand expliziter Text-, Leerwert-, Zahlen-, Zeit- oder Mengenbedingungen löschen,
- ein festes Präfix oder Suffix entfernen,
- Text zwischen zwei Begrenzern extrahieren.

Die Textbereinigung verwendet für Live-Vorschau und tatsächliche Transformation dieselbe reine
Funktion. Die Vorschau zeigt unterschiedliche, nichtleere Original- und Ergebniswerte, verändert
aber weder T noch den Transformationsplan. Nichttreffer bleiben unverändert. Lange Zellinhalte
werden nur für die Darstellung gekürzt.

Mehrere separat aufbereitete Datensätze können kontrolliert per LEFT-, RIGHT-, INNER- oder
OUTER-Join verknüpft werden. Vor der Ausführung werden Kardinalität, Trefferquote, erwartete
Zeilenzahl und Risiken einer Zeilenvervielfachung angezeigt.

### 3. Semantisches Mapping

Erzeugt optional die Mappingtabelle M. Sie ordnet vorhandene technische Spaltenbezeichnungen
oder tatsächlich vorkommende, typisierte Werte fachlichen Bezeichnungen zu. T wird weder
umbenannt noch verändert. Wenn keine Interpretation erforderlich ist, kann ein ausdrücklich
leeres M gespeichert werden. Fall-ID, Aktivität, Zeitbezug und weitere Event-Log-Rollen werden
erst in Schritt 4 festgelegt.

### 4. Event Log aufbauen

Konfiguriert Fallidentifikation, Aktivitätsdefinition, Zeitstempelquellen, Strukturart und
zusätzliche Attribute. Das Ergebnis E enthält mindestens die kanonischen Spalten `case_id`,
`activity` und `timestamp`.

Event-Log-Konfigurationsversion 3 unterstützt zusätzlich die optionalen semantischen Rollen:

- Ressourcenspalte → `resource`,
- Startzeitstempel → `start_timestamp`,
- Endzeitstempel → `end_timestamp`,
- Lifecycle-/Statusspalte → `lifecycle`.

Eine technische Quellspalte kann nicht zugleich mehreren Standardrollen und einem allgemeinen
Attribut zugeordnet werden. In ereignisorientierten Daten werden alle vier Rollen unterstützt.
Bei breiten Zeitstempeldaten können Ressource und Lifecycle je Zeitstempelzuordnung übernommen
werden; eine nicht eindeutig vorhandene Start-/Endpaarung wird nicht erfunden.

Konfigurationsversionen 1 und 2 bleiben mit ihrer bisherigen Semantik lesbar und reproduzierbar.
Insbesondere werden zusätzliche Attribute aus Version 2 weiterhin als allgemeine Attribute
behandelt. E wird stabil sortiert und als CSV.GZ mit Schema- und Lineage-JSON gespeichert.

### 5. Datenqualität prüfen

Prüft die vollständige Artefaktkette Q, T, optional M und E. Automatische Integritäts- und
Vollständigkeitsprüfungen werden mit begründeten menschlichen Bewertungen kombiniert. Schritt 5
verändert die Daten nicht. Bei bestandener Prüfung verweist E* unverändert auf E; zusätzlich
wird ein JSON-Freigabebericht mit Entscheidungen, Referenzen und Prüfsummen gespeichert. Ein
festgestellter Mangel führt zum fachlich passenden früheren Schritt zurück.

### 6. Process Mining durchführen

Verwendet ausschließlich eine erneut validierte E*-Freigabe. Die Anwendung berechnet einen
vollständigen frequenzbasierten Directly-Follows-Graph und entdeckt mit PM4Py über den Inductive
Miner ein Prozessmodell. Der einstellbare Schwellwert `k` beeinflusst nur die Prozessentdeckung,
nicht E* oder den vollständigen DFG.

Als Prozessmodell P stehen Prozessbaum, Petrinetz und BPMN zur Auswahl. Discovery-Ergebnisse A_D
und Modellartefakte werden gemeinsam gespeichert. Performance-, Ressourcen- oder
Engpassanalysen sind nicht Teil dieses Schritts.

### 7. Ergebnisse aggregieren

Verknüpft die erneut geprüfte Lineage aus U, R, T, E*, P und A_D. Für die in U ausgewählten
KPIs stehen feste, versionierte Definitionen zur Verfügung; benötigte Operanden werden
ausdrücklich Profilkennzahlen oder Datenspalten zugeordnet. Nicht eindeutig berechenbare
Kennzahlen werden entsprechend gekennzeichnet.

Optional können ein unabhängiger Sollprozess, Token-Replay-Conformance-Checking und eine
ausdrücklich konfigurierte Soll-Ist-Zeitauswertung ergänzt werden. A_G-Version 2 speichert
zusätzlich strukturierte Aktivität-Ressourcen-Zuordnungen, Übergangswartezeiten und die
zeitbezogene Datenauswahl. Vollständige kanonische Ressourcen werden automatisch übernommen;
andernfalls ist eine manuelle Zuordnung oder die begründete Entscheidung `nicht_moeglich`
erforderlich. A_G-Version 1 bleibt lesbar.

Die fachliche Vorschau wird neu berechnet und anschließend ohne redundante
Bestätigungscheckbox mit einem primären Button gespeichert und an Schritt 8 übergeben.

### 8. Modellbestandteile ableiten

Ordnet Informationen aus U, S, Q, R, T, E*, P und A_G anhand der festen Quellenmatrix aus
Tabelle 3.15 exakt 16 getrennten Modellbestandteilen zu. Erst fachlich bestätigte Vorschläge
bilden das vorläufige Modell K; fehlende, nicht ableitbare, unsichere oder nicht bestätigte
Punkte werden getrennt in O dokumentiert.

Schritt 8 führt keine neue fachliche Berechnung durch. Ressourcen-, Übergangswartezeit- und
Zeitdatenergebnisse werden ausschließlich aus der strukturierten A_G-Sektion übernommen. Bei
A_G-Version 1 bleiben diese Inhalte nachvollziehbar offen, statt aus E* nachberechnet zu werden.
Eine `case_id` wird nicht automatisch zum Entitätstyp und Zeitlücken werden nicht automatisch
zu Warteschlangen.

Die Vorschläge entstehen beim Öffnen automatisch. Für jeden Bestandteil ist ausdrücklich
`Vorschlag übernehmen`, `Offen / fachlich unsicher` oder `Vorschlag nicht übernehmen` zu
entscheiden; offene und abgelehnte Vorschläge benötigen eine Begründung. Erst nach allen 16
Entscheidungen speichert der primäre Button K und O und navigiert zu Schritt 9.

### 9. Modell ergänzen und validieren

Lädt das zusammengehörige K/O-Paar und verlangt für jeden offenen Punkt eine dokumentierte
Entscheidung. Begründete fachliche Ergänzungen werden getrennt von den ursprünglichen
Informationen gespeichert. Ein einzelner primärer Button validiert die Eingaben, nennt konkret
fehlende Pflichtentscheidungen, speichert K* und navigiert zu Schritt 10. Nach erfolgreicher
Speicherung erscheint kein redundanter Weiter-Button.

### 10. Konzeptionelles Modell ausgeben

Akzeptiert ausschließlich ein erneut geprüftes und fachlich validiertes K*. HTML und PDF werden
aus derselben formatneutralen Reportdatenstruktur erzeugt und verändern K* nicht.

- **HTML** wird als vollständiges, selbstständiges Dokument mit eingebettetem CSS über den Link
  **„Konzeptionelles Modell im neuen Tab öffnen“** bereitgestellt. Der Link verwendet
  `target="_blank"` und `rel="noopener noreferrer"`; HTML wird nicht als Download angeboten.
- **PDF** bleibt ein Download. Der sichere Dateiname enthält die zur validierten Projekt-ID
  gehörende Projektbezeichnung, beispielsweise `Konzeptionelles Modell Projekt Ä.pdf`.
- **XLSX** ist sichtbar, aber als noch nicht implementierter Platzhalter deaktiviert.

UUIDs, SHA-256-Werte, Fingerabdrücke und vollständige Lineage bleiben intern erhalten, werden in
der normalen Fachansicht jedoch nicht angezeigt. Soweit eine Diagnose sinnvoll ist, stehen sie
in einem standardmäßig geschlossenen Bereich **Technische Details**.

## Voraussetzungen und lokale Installation

Vorausgesetzt werden:

- Python **>= 3.12, < 3.15**,
- `pip`,
- ein lokaler Checkout des Repositorys,
- optional Graphviz für Process-Mining-Grafiken.

```bash
git clone <URL-DES-REPOSITORYS>
cd Masterarbeit
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Unter Windows PowerShell wird die Umgebung mit `.venv\Scripts\Activate.ps1` aktiviert. Die
optionale Abhängigkeitsgruppe `dev` installiert Pytest, Coverage, Ruff und Pyright. Jinja2 und
WeasyPrint sind reguläre Laufzeitabhängigkeiten für das Reporting; Authlib wird für Streamlits
OIDC-Integration benötigt.

## Anwendung starten

```bash
.venv/bin/python -m streamlit run streamlit_app.py
```

Streamlit zeigt anschließend die lokale Adresse an, standardmäßig
`http://localhost:8501`.

Workspace und SQLite-Datenbank können getrennt konfiguriert werden:

```bash
export FRAMEWORK_MVP_WORKSPACE_PATH=/absoluter/pfad/zum/workspace
export FRAMEWORK_MVP_DB_PATH=/absoluter/pfad/framework_mvp.sqlite
.venv/bin/python -m streamlit run streamlit_app.py
```

Weitere optionale Umgebungsvariablen:

| Variable | Bedeutung | Standard |
|---|---|---:|
| `FRAMEWORK_MVP_GUEST_TTL_HOURS` | Gast-TTL seit letzter Aktivität | `24` |
| `FRAMEWORK_MVP_MAX_UPLOAD_MB` | maximale CSV-/XLSX-Uploadgröße | `50` |
| `FRAMEWORK_MVP_LOCAL_AUTH_TEST_MODE` | feste lokale Testidentität aktivieren | aus |
| `FRAMEWORK_MVP_LOCAL_AUTH_TEST_ADMIN` | Testidentität als Systemadmin bootstrappen | aus |
| `FRAMEWORK_MVP_ARCHIVE_MAX_COMPRESSED_MB` | komprimierte Projektarchivgröße | `250` |
| `FRAMEWORK_MVP_ARCHIVE_MAX_UNCOMPRESSED_MB` | entpackte Projektarchivgröße | `1024` |
| `FRAMEWORK_MVP_ARCHIVE_MAX_FILES` | Dateien je Projektarchiv | `5000` |
| `FRAMEWORK_MVP_ARCHIVE_MAX_FILE_MB` | Größe je Archivdatei | `250` |
| `FRAMEWORK_MVP_ARCHIVE_MAX_RATIO` | maximales Kompressionsverhältnis | `100` |
| `FRAMEWORK_MVP_ARCHIVE_MAX_PATH_BYTES` | maximale UTF-8-Pfadlänge | `512` |

Der lokale Auth-Testmodus ist ausschließlich für Entwicklung und Tests vorgesehen und muss
explizit aktiviert werden.

## OIDC und Community Cloud konfigurieren

1. Beim OIDC-Provider als Callback lokal
   `http://localhost:8501/oauth2callback` beziehungsweise in Community Cloud
   `https://<app-name>.streamlit.app/oauth2callback` registrieren.
2. `.streamlit/secrets.toml.example` nach `.streamlit/secrets.toml` kopieren oder die Werte in
   den Community-Cloud-Secrets hinterlegen. Echte Secrets dürfen nicht committet werden.
3. Unter `[auth]` `redirect_uri`, ein zufälliges `cookie_secret`, `client_id`, `client_secret`
   und `server_metadata_url` setzen.
4. Den initialen Systemadmin unter `[[systemadmin.identities]]` mit dem exakten OIDC-Issuer und
   Subject eintragen.

Streamlit Community Cloud und ihr lokaler Speicher besitzen keine Persistenzgarantie. Die
Anwendung ist für MVP, Fallstudie und überschaubare Lehrveranstaltungen ausgelegt. Für größere
Parallelität oder dauerhaft produktiven Betrieb ist ein anderer Speicheradapter hinter den
vorhandenen Ports erforderlich.

## Speicherung, Lineage und Migration

Die Anwendung verwendet eine hybride lokale Persistenz:

- **SQLite** speichert Metadaten, IDs, Zustände, Beziehungen, Mandanten, Rechte und Referenzen.
  Die aktuelle Schemaversion ist **11**. Die Migrationskette aktualisiert bestehende Versionen
  schrittweise; neuere unbekannte Versionen werden abgelehnt. Vorhandene Projekte aus Version 10
  werden verlustfrei als `legacy_unassigned` markiert und nicht öffentlich aufgelistet.
- **`workspace/`** enthält Rohdateien und größere fachliche Artefakte. Das Verzeichnis ist in
  `.gitignore` ausgeschlossen und stellt keine automatische Datensicherung dar.

Vereinfacht entsteht folgende Struktur:

```text
workspace/
├── framework_mvp.sqlite
└── projects/<projekt-id>/
    ├── raw/
    ├── profiles/
    ├── interim/
    ├── mapping_tables/
    ├── mappings/
    ├── event_logs/
    ├── quality/
    ├── process_mining/
    ├── aggregation/
    ├── model_derivations/
    └── model_validations/
```

Persistierte Artefakte verwenden projektbezogene UUIDs, Versionen, Referenzen und
SHA-256-Prüfsummen. Beim Laden werden IDs, Pfade und Prüfsummen erneut geprüft. Die normale
Oberfläche bleibt dennoch fachlich kompakt; technische Lineage wird nicht gelöscht, sondern nur
aus der Hauptansicht herausgehalten.

SQLite läuft mit aktivierten Foreign Keys, WAL, fünf Sekunden `busy_timeout` und kurzen
Transaktionen.

## Portable Projekt- und Kursarchive

Projektarchive verwenden ZIP-Formatversion 1 mit Manifest, projektbezogenen Datenbankzeilen,
Artefakten und einer lesbaren Kurzbeschreibung. Manifest und jede Datei werden anhand von Größe
und SHA-256 geprüft. Benutzer, Rollen, Einladungen, Sessions, Tokens, Secrets, fremde Projekte,
die globale SQLite-Datei, Caches und temporäre Dateien werden nicht exportiert.

Importe werden vor dem ersten Schreibzugriff auf ZIP-Struktur, Pfadtraversal, Symlinks,
Verschlüsselung, Doppelpfade, CRC, erlaubte Pfade und Dateitypen, Ressourcenlimits, Manifest,
Prüfsummen, Tabellenschema und Lineage geprüft. Es wird kein unkontrolliertes `extractall`
verwendet. Eine bereits vorhandene Projekt-ID wird nur bei identischem Inhalt und bestehender
Autorisierung wieder geöffnet; abweichende Inhalte werden nicht überschrieben.

Kursarchive enthalten die einzeln validierten Projektarchive und fachliche Teamhinweise. Aktive
Einladungen und Zugriffsrechte werden nicht übernommen. Archive sind **nicht verschlüsselt** und
können Originaldaten oder personenbezogene Zuordnungshinweise enthalten.

## Löschen über die Benutzeroberfläche

Im Sidebar-Bereich **Projektrahmen** stehen für das aktive, bearbeitbare Projekt die Aktionen
**Projekt löschen** und – nur bei vorhandenen Zwischendatensätzen – **Datensatz löschen**. Im
Gastmodus heißt die Projektaktion **Demo beenden und Daten löschen**.

Die Aktionen verlangen weder Projektname noch UUID, Schlüssel oder Kurz-ID. Ein kompakter
Dialog benennt das Ziel und bietet **Löschen** und **Abbrechen**. Nach einer Projektlöschung wird
der projektbezogene Session State bereinigt; nach einer Datensatzlöschung werden nur T und seine
abhängigen Artefakte zurückgesetzt. Andere Projekte, Datensätze, Rohimporte und Datenquellen
bleiben unberührt, soweit sie nicht fachlich vom gelöschten Ziel abhängen.

Dateien werden zunächst in einen projektbezogenen Staging-Bereich verschoben. Schlägt die
Datenbanktransaktion fehl, wird die Dateiverschiebung zurückgerollt.

## Softwarearchitektur

```text
Masterarbeit/
├── streamlit_app.py
├── pyproject.toml
├── src/framework_mvp/
│   ├── application/
│   │   └── ports/
│   ├── domain/
│   ├── infrastructure/
│   ├── reporting/
│   ├── ui/
│   ├── bootstrap.py
│   └── workspace.py
├── tests/
│   ├── unit/
│   └── integration/
├── docs/decisions/
└── examples/anonymisierte_daten/
```

- `application/` enthält Anwendungsservices und fachliche Ablaufkoordination.
- `application/ports/` definiert Repository-Schnittstellen, sodass Services nicht direkt von
  konkreten SQLite-Klassen abhängen.
- `domain/` enthält Modelle, Kataloge, Enums, Validierungsregeln und Domänenausnahmen.
- `infrastructure/` implementiert Dateiimporte, Artefaktspeicherung und SQLite-Repositories
  einschließlich Schema und Migrationen.
- `reporting/` erzeugt formatneutrale Berichtsdaten und rendert HTML und PDF.
- `ui/` enthält Streamlit-Seiten, Komponenten, zentrale Fortschrittsdefinition, Navigation und
  Session-State-Bereinigung.

`src/framework_mvp/bootstrap.py` ist der Composition Root. Dort werden konkrete Repositories,
Autorisierungs- und Fachservices sowie der lokale Artefaktspeicher zusammengesetzt.

## Reporting

Schritt 10 verwendet für HTML und PDF dieselbe formatneutrale Datenstruktur:

- `src/framework_mvp/reporting/report_data.py` prüft K* und erzeugt `report_data` Version 1.
- `src/framework_mvp/reporting/templates/conceptual_model/V1/` enthält versionierte HTML- und
  PDF-Templates sowie die jeweiligen Layouts.
- Jinja2 rendert die Dokumente; WeasyPrint erzeugt das PDF.
- `asset_resolver.py` bindet vorhandene SVG-Darstellungen von Prozessmodell, DFG und
  Prozessbaum ein. Fehlende optionale Assets blockieren den Report nicht; vorhandene ungültige
  SVG-Dateien werden als Fehler behandelt.

Die Ausgaben entstehen temporär und werden nicht als neues fachliches Artefakt persistiert.

## Synthetische Produktions-Testdaten

`tests/Testdatagenerator.py` erzeugt einen reproduzierbaren, vollständig erfundenen
Produktionsdatensatz mit genau 20 Aktivitäten, logischen Fertigungsvarianten, Ressourcen- und
Kapazitätsbelegung, Soll-/Ist-Zeiten sowie getrennt konfigurierbaren Qualitätsauffälligkeiten.
Die Parameter werden primär im gut sichtbaren Block `KONFIGURATION` am Dateianfang angepasst.

```bash
.venv/bin/python tests/Testdatagenerator.py
```

Der Lauf erzeugt `tests/datasets/Testdatensatz_Produktion.xlsx` und das statische, von Seed und
Fallzahl unabhängige `tests/datasets/Sollprozess_Produktion.pnml`. In Schritt 2 wird das Blatt
`Ereignisdaten` als Haupttabelle importiert und per LEFT JOIN über `Ressourcen_ID` mit dem Blatt
`Ressourcenstamm` verknüpft. `Produktionsauftrag` wird kontrolliert in Text konvertiert.

Für Schritt 4 wird folgende semantische Zuordnung empfohlen:

- `Produktionsauftrag` → Fall-ID
- `Vorgang` → Aktivität
- `Buchungszeitpunkt` → Ereigniszeitpunkt
- `Ist_Start` → Startzeitpunkt
- `Ist_Ende` → Endzeitpunkt
- `Ressourcenbezeichnung` → Ressource, erst nach dem Join
- `Soll_Start` und `Soll_Ende` → zusätzliche Ereignisattribute für die Soll-Ist-Auswertung

Die Arbeitsmappe enthält außerdem Aktivitäts- und Variantenkatalog, Vorschläge für den manuell
zu bestätigenden Projektrahmen sowie Generierungs- und Datenqualitätsprotokolle. Das PNML bildet
zulässige Routen, optionale Schweiß-/Lackpfade und beide Nacharbeitsschleifen ab und kann in
Schritt 7 als komplexer Sollprozess importiert werden.

## Tests und statische Qualitätssicherung

```bash
.venv/bin/python -m pytest
.venv/bin/python -m pytest --cov=framework_mvp --cov-report=term-missing
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pyright
```

Die Tests umfassen Unit-, Integrations-, Persistenz-, Migrations-, Streamlit-App- und
End-to-End-Prüfungen. Unter anderem werden die Migrationskette bis Schema 11, Event-Log-
Konfigurationen v1–v3, Projekt- und Kursarchive, Mandantentrennung, Löschdialoge, Fortschritt,
Reporting und die vollständigen fachlichen Artefaktketten geprüft.

## Architecture Decision Records

- [ADR-001: Lokale Persistenz](docs/decisions/ADR-001-lokale-persistenz.md)
- [ADR-002: Strukturierter Untersuchungsauftrag](docs/decisions/ADR-002-strukturierter-untersuchungsauftrag.md)
- [ADR-003: Datenquellenkatalog und Framework-Navigation](docs/decisions/ADR-003-datenquellenkatalog-und-framework-navigation.md)
- [ADR-004: Importartefakte und Konsistenz](docs/decisions/ADR-004-importartefakte-und-konsistenz.md)
- [ADR-005: Transformation und semantisches Mapping](docs/decisions/ADR-005-transformation-und-semantisches-mapping.md)
- [ADR-006: Kanonisches Event Log und E*-Freigabe](docs/decisions/ADR-006-event-log-und-datenqualitaet.md)
- [ADR-007: Process Mining mit PM4Py](docs/decisions/ADR-007-process-mining-mit-pm4py.md)
- [ADR-008: Ergebnisaggregation A_G](docs/decisions/ADR-008-ergebnisaggregation-a-g.md)
- [ADR-009: Vorläufiges Modell K und offene Bestandteile O](docs/decisions/ADR-009-vorlaeufiges-modell-k-und-offene-bestandteile-o.md)
- [ADR-010: K* validieren und strukturiert ausgeben](docs/decisions/ADR-010-validierung-k-stern-und-strukturierte-ausgabe.md)
- [ADR-011: Portable Projekte und Kursmandanten](docs/decisions/ADR-011-portable-projekte-und-kursmandanten.md)

## Bekannte Einschränkungen und mögliche Erweiterungen

- CSV und XLSX sind die regulär unterstützten Importformate. Direkte Datenbankzugriffe und
  Echtzeitquellen sind nicht implementiert.
- Warteschlangen und Ressourcen werden nur quellengebunden übernommen. Fehlen geeignete
  Informationen, bleiben sie in O offen und müssen in Schritt 9 fachlich behandelt werden.
- Schritt 6 bietet Process Discovery und einen vollständigen DFG, aber keine eigenständige
  Performance-, Ressourcen- oder Engpassanalyse.
- Der lineare Sollprozessassistent in Schritt 7 bildet keine Verzweigungen, Parallelität,
  Synchronisation oder Schleifen ab; komplexere Sollnetze müssen als PNML bereitgestellt werden.
- Die XLSX-Reportausgabe ist noch nicht implementiert.
- Der lokale Workspace und Community-Cloud-Speicher sind keine automatische Datensicherung.
- Ein austauschbarer, dauerhaft persistenter Cloud-Speicheradapter ist eine mögliche spätere
  Erweiterung.
- Im Repository liegt derzeit keine `LICENSE`-Datei. Aus dem Quellcode folgt daher keine
  behauptete Open-Source-Lizenz oder allgemeine Erlaubnis zur freien Weiterverwendung.
