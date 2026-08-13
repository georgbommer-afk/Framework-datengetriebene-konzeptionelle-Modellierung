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

Soll-Zeitstempel können aus T, E* oder einer getrennten unveränderten CSV-/XLSX-Datei stammen.
Spaltenrollen und Verknüpfungen werden explizit bestätigt. Der fallbezogene Vergleich verwendet
eine ausgewählte tatsächliche Aktivität und eine Vorkommensregel; der ereignisbezogene Vergleich
verwendet Fall, Aktivität und bei Wiederholungen eine Auftretensnummer. Mehrdeutige Schlüssel
blockieren. A_V enthält ausschließlich Ist minus Soll, die drei zeitlichen Klassen und getrennte
Fehl-/Zuordnungsanzahlen.

A_G enthält die unveränderte A_D-Referenz, KPI-Konfigurationen und -Ergebnisse sowie optionale
Artefaktreferenzen. A_G-Artefaktversion 2 enthält zusätzlich die intern versionierte Sektion
`strukturierte_ergebnisse` (Ergebnisversion 1). Darin werden die in Schritt 7 abgeschlossene
Ressourcenentscheidung (`automatisch`, `manuell` oder begründet `nicht_moeglich`), robuste
Übergangswartezeiten mit `Start(B) − Ende(A)` und die bestätigte zeitbezogene Datenauswahl aus
Q/R/T/E* gespeichert. Bearbeitungszeit, Übergangswartezeit und Zwischenankunftszeit bleiben
begrifflich und strukturell getrennt. Negative und nicht auswertbare Werte werden explizit
ausgewiesen. A_G-Artefaktversion 1 bleibt lesbar und wird nicht migriert; neue Läufe schreiben
Version 2. Eine additive Schemaversion 8 speichert nur ID, vollständige Eingabe- und
Konfigurationsfingerabdrücke, Pfad, Prüfsumme, Status und Zeit. Detailartefakte werden atomar
geschrieben; identische IDs und Fingerabdrücke sind idempotent. Änderungen an U, R, T, E*, P,
A_D oder einer bestätigten Konfiguration invalidieren eine Vorschau beziehungsweise ein
gespeichertes A_G. Schritt 8 erhält nach erneuter Validierung ausschließlich P und A_G.

## Konsequenzen

- KPI-Berechnung, Conformance Checking und Zeitvergleich bleiben unabhängig.
- A_G ist auch ohne A_C und A_V gültig; in v2 sind A_D-Referenz und strukturierte Ergebnisse enthalten.
- P und P_Soll sind technisch und fachlich getrennt.
- Externe Modellierungs- oder Netzwerkausfälle blockieren weder PNML-Upload noch Aggregation.
- Fall- und Ereignisdetails stehen zusätzlich als CSV bereit.

## Abgrenzung

Nicht enthalten sind freie KPIs oder Formeln, semantische Automatik, erneute Datenaufbereitung,
Process Discovery, Verwendung von P als P_Soll, Alignments, Precision, Modellreparatur,
generische Varianten- oder Engpassanalysen, kausale Erklärungen und automatische
Maßnahmenempfehlungen.
