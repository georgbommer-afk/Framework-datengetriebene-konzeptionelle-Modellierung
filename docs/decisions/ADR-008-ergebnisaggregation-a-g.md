# ADR-008: Ergebnisaggregation A_G

## Kontext

Algorithmus 7 führt die Discovery-Ergebnisse A_D mit den in U ausgewählten Kennzahlen und
optional Conformance-Ergebnissen A_C sowie direkten zeitbezogenen Soll-Ist-Abweichungen A_V
zusammen. U, R, T, E*, P und A_D sind unveränderliche Eingaben. P_Soll ist ein eigenständiges
Sollprozessmodell und darf nicht mit P oder der Mappingtabelle M gleichgesetzt werden.

## Entscheidung

Schritt 7 besitzt einen eigenen Aggregationsservice. Er lädt keine frei gewählten Artefakte,
sondern leitet die vollständige Kette aus zentraler Projekt-, Freigabe- und Analyse-ID über die
vorhandenen Services ab. Projektbindung, Freigabe, Event-Log- und T-Prüfsummen sowie P- und
A_D-Referenzen werden bei Vorschau, Speicherung, Laden und Übergabe erneut geprüft. Alle
Berechnungen verwenden tiefe Arbeitskopien.

Die 16 KPI-IDs aus A.7 bis A.10 sind als unveränderlicher Katalog mit Definitionsversion,
Bezeichnung, Formel, Operanden, Operandentyp, zulässiger Quelle, Ergebnistyp, Einheit und
Bezugsmenge implementiert. Schritt 7 bietet nur die IDs aus U. Operanden werden explizit R, T
oder E* sowie konkreten Spalten, Bedingungen, Zeitstempeln oder Aktivitäten zugeordnet. Eine
nicht eindeutig berechenbare KPI wird mitsamt konkreter Ursache als `nicht_berechenbar`
gespeichert und blockiert keine andere Komponente.

Profilkennzahlen aus R werden ab A_G-Artefaktversion 4 über einen strukturierten Katalog mit
stabiler interner Referenz, Import-/Datenquellenbezug, Spalte, Kennzahltyp, Wert,
Profilprüfsumme und gegebenenfalls vollständiger Indikatorbedingung ausgewählt. Die UI zeigt
daraus fachliche Bezeichnungen statt technischer String-Suffixe. Zeilenanzahl, gültige
Beobachtungen und die in R gespeicherte absolute Indikatorhäufigkeit sind ausschließlich für
ANZAHL-Operanden nutzbar; ein arithmetisches Mittel ausschließlich für MITTELWERT. R wird für
SUMME nur bei einer tatsächlich gespeicherten Summe, für MESSWERTE gar nicht und für eine
Zeitdifferenzsumme nur bei einer exakt passenden gespeicherten Kennzahl angeboten. Insbesondere
wird keine Summe aus Mittelwert und Anzahl rekonstruiert. Der Benutzer bestätigt die fachliche
Bedeutung weiterhin durch die konkrete Zuordnung.

Eine gewählte Indikatorhäufigkeit wird nicht erneut auf T oder E* ausgewertet. A_G übernimmt
das gespeicherte n_B und dokumentiert Profil, Spalte, Operator, Vergleichswert, Wert und
Prüfsummenbezug. Davon getrennte Bedingungen auf T oder E* werden erst in Schritt 7 ausgewertet
und als solche gekennzeichnet. Alte String-Referenzen bleiben kontrolliert lesbar; neue
Konfigurationen verwenden die strukturierte KPI-Konfigurationsversion 2.

Für P_Soll bestehen drei Wege: kein Sollmodell, ein bestätigter linearer Assistent oder ein
PNML-Upload. Der lineare Assistent verwendet nur eindeutige Aktivitäten aus E*, erzeugt genau
eine Start- und Endstelle und eine sichtbare Transition je Aktivität und behauptet keine
komplexen Kontrollflussmuster. Für komplexe Netze ist WoPeD Next über eine feste HTTPS-URL in
einem 900 Pixel hohen iframe eingebettet; derselbe feste Link steht unmittelbar davor als
Fallback. Die Anwendung liest keinen externen Browserzustand aus.

PNML wird größen- und typbegrenzt sowie ohne Dokumenttyp- und Entitätsdeklarationen verarbeitet.
Das Original bleibt unverändert; eine normalisierte Replay-Fassung ist getrennt. Stellen,
Transitionen, bipartite Kanten, sichtbare und eindeutige Bezeichnungen, genau ein struktureller
Start- und Endplatz, Workflow-Netz und Soundness sind Pflicht. Eindeutig fehlende Markierungen
dürfen erst nach ausdrücklicher Bestätigung aus Quell- und Senkenplatz abgeleitet werden.

Der Aktivitätsabgleich trennt exakte Treffer, reine E*-Aktivitäten und reine Solltransitionen.
Nur exakte oder bestätigte manuelle Zuordnungen wirken auf eine Replay-Kopie. Nicht zugeordnete
Log-Aktivitäten blockieren Token Replay; E* wird nicht gefiltert. A_C dokumentiert PM4Py-Version,
Fall- und Aggregatwerte von p_T, c_T, m_T und r_T sowie Fitness nach Gleichung 3.13. Die
Bibliotheksfitness dient nur der Plausibilisierung.

Ab A_G-Artefaktversion 5 zeigt Schritt 7 die drei Mappinggruppen vor dem Replay getrennt und
verlangt eine ausdrückliche Bestätigung. Nach dem Replay werden Fitness nach Gleichung 3.13,
p_T, c_T, m_T, r_T, Fallanzahlen und fallbezogene Diagnosen unmittelbar dargestellt. Der
PM4Py-Wert bleibt separat als Plausibilisierung sichtbar und verändert den fachlichen Hauptwert
nicht. Ist kein Sollprozess vorhanden, dokumentiert A_G ausdrücklich, dass Conformance Checking
ohne Fehler entfällt.

Soll-Zeitstempel können aus T, E* oder einer getrennten unveränderten CSV-/XLSX-Datei stammen.
Spaltenrollen und Verknüpfungen werden explizit bestätigt. Der fallbezogene Vergleich verwendet
eine ausgewählte tatsächliche Aktivität und eine Vorkommensregel; der ereignisbezogene Vergleich
verwendet Fall, Aktivität und bei Wiederholungen eine Auftretensnummer. Mehrdeutige Schlüssel
blockieren. A_V enthält ausschließlich Ist minus Soll, die drei zeitlichen Klassen und getrennte
Fehl-/Zuordnungsanzahlen.

Die Performance-Auswertung in A_V-Artefaktversion 2 trennt die Fertigstellungsabweichung
`dT = Ist-Ende − Plan-Ende` nach Gleichung 3.1 von der Bearbeitungszeitabweichung
`dB = (Ist-Ende − Ist-Start) − (Plan-Ende − Plan-Start)` nach Gleichung 3.2. Einzelwerte,
verwendete Zeitpunkte, Klassifikationen, Ausschlüsse, Mittelwerte und Mediane bleiben getrennt.
Wiederholte Aktivitäten werden nur über eine bestätigte erste/letzte Vorkommensregel oder eine
Auftretensnummer verbunden. Aus den Ergebnissen werden weder Ursachen noch Maßnahmen abgeleitet.

Die ressourcenbezogene Engpassanalyse verwendet für Gleichung 3.3 dieselbe gemeinsame
Bearbeitungszeitfunktion wie die bereits vorhandene Zeitgrößenanalyse. Gleichung 3.4 bildet
ausschließlich innerhalb einer Ressource die Differenz aufeinanderfolgender Ist-Startzeitpunkte;
sie ist technisch und fachlich von der Zwischenankunftszeit eines Ankunftsstroms q getrennt.
Gleichung 3.5 teilt die Bearbeitungszeit der aktuellen Ausführung durch diese
ressourcenbezogene Zwischenankunftszeit. Nullteiler, negative oder ungültige Zeiten werden mit
Grund ausgeschlossen. A_V speichert Einzelwerte, den bestätigten Zeitraum und Statistiken je
Ressource. Nur bei mindestens zwei auswertbaren Ressourcen wird die Ressource mit dem höchsten
mittleren BR als potenzieller Engpass gekennzeichnet; eine Warteschlange wird nicht behauptet.

A_G enthält die unveränderte A_D-Referenz, KPI-Konfigurationen und -Ergebnisse sowie optionale
Artefaktreferenzen. Die mit Artefaktversion 3 eingeführte Sektion
`strukturierte_ergebnisse` verwendet ab Artefaktversion 5 Ergebnisversion 3. Beobachtete
Aktivität-Ressource-Paare bleiben auch bei Lücken erhalten; automatische, manuell bestätigte
und offene Beziehungen sind je Aktivität getrennt nachvollziehbar. Ressourcen- und
Entitätsattribute werden ausschließlich über bestätigte Schlüssel aus E* oder T übernommen.
Nur ein über alle Beobachtungen stabiler Wert wird statisch verdichtet; wechselnde Werte bleiben
mit ihrem Zeitbezug erhalten.
`E*.case_id` bezeichnet neutral die beobachtete Entitätsinstanz und begründet allein keinen
fachlichen Entitätstyp.

Explizit bestätigte Warteschlangeninformationen sind von der rein zeitlichen Lücke
`Start(B) − Ende(A)` getrennt. Letztere heißt ausschließlich potenzielle Wartezeit; ihre
Eventfolge wird durch `E*.timestamp` und bei Gleichstand durch die stabile Quellreihenfolge
bestimmt. Negative Differenzen werden als Überlappungen gezählt. Bearbeitungszeiten verwenden
nur Start und Ende derselben Ausführung und werden bei konkreter Ressource nach Aktivität und
Ressource, sonst kenntlich nur nach Aktivität gruppiert.

Zwischenankunftszeiten entstehen nur für einen oder mehrere explizit bestätigte
Ankunftsströme q aus E* oder T. Quelle, Entitäts-ID, Ankunftszeit, Filter und gegebenenfalls
Vorkommensregel werden je Strom gespeichert; mehrdeutige Vorkommen ohne Regel werden
ausgeschlossen. Die Lineage wird pro Zeitgröße gespeichert, nicht pauschal als Q/R/T/E*.
A_G-Artefaktversionen 1 bis 4 bleiben unverändert lesbar und werden nicht migriert. Dadurch
wird eine alte `Übergangswartezeit` insbesondere nicht als explizit bestätigte Warteschlange
interpretiert. Neue Läufe schreiben Version 5. Eine additive Schemaversion 8 speichert nur ID,
vollständige Eingabe- und Konfigurationsfingerabdrücke, Pfad, Prüfsumme, Status und Zeit.
Detailartefakte werden atomar
geschrieben; identische IDs und Fingerabdrücke sind idempotent. Änderungen an U, R, T, E*, P,
A_D oder einer bestätigten Konfiguration invalidieren eine Vorschau beziehungsweise ein
gespeichertes A_G. Schritt 8 erhält nach erneuter Validierung ausschließlich P und A_G.

## Konsequenzen

- KPI-Berechnung, Conformance Checking und Zeitvergleich bleiben unabhängig.
- A_G ist auch ohne A_C und A_V gültig; seit v3 sind A_D-Referenz und strukturierte Ergebnisse
  enthalten.
- P und P_Soll sind technisch und fachlich getrennt.
- Externe Modellierungs- oder Netzwerkausfälle blockieren weder PNML-Upload noch Aggregation.
- Fall- und Ereignisdetails stehen zusätzlich als CSV bereit.

## Abgrenzung

Nicht enthalten sind freie KPIs oder Formeln, semantische Automatik, erneute Datenaufbereitung,
Process Discovery, Verwendung von P als P_Soll, Alignments, Precision, Modellreparatur,
generische Varianten- oder Engpassanalysen, kausale Erklärungen und automatische
Maßnahmenempfehlungen.
