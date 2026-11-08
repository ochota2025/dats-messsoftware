# Neuerungen

## 0.2.16 – 08.11.2026

- **Klarere Grenzen bei Pegelreihe und Klirr:** Das DATS V3 ist eine Soundkarte mit Messwiderstand
  und liefert nur Kleinsignal, die Membran bewegt sich kaum. Die Hinweise in beiden Tabs sagen das
  jetzt deutlich: Die Pegelreihe zeigt Änderungen von wenigen Prozent, nicht das Großsignal-Verhalten.
  Die Klirrmessung findet vor allem grobe Fehler wie eine schleifende Schwingspule. Für echte
  Lautstärke braucht es einen Verstärker (z. B. DATS LA).
- Liegt der Klirr nur an der Messgrenze, sagt das Ergebnis das ausdrücklich.
- **Simulator realistischer:** Klirr und Pegelabhängigkeit sind auf das Maß gesenkt, das mit dem
  DATS V3 zu erwarten ist. Bisher sahen die Kurven im Simulator eindrucksvoller aus, als ein echtes
  DATS V3 sie liefern kann.

## 0.2.15 – 08.11.2026

- **Achsenbeschriftung einstellbar:** Unter *Ansicht → Darstellung … → Achsenbeschriftung* lassen
  sich Größe (6–24 pt oder „Standard“) und „fett“ für die Zahlen und Achsentitel neben den
  Diagrammen einstellen. Das gilt für alle Diagramme. Die Achse wird automatisch breiter, damit
  nichts abgeschnitten wird. Bei großer Schrift blendet das Diagramm Zwischenwerte (z. B. 20, 50)
  aus, damit sich nichts überlappt. Die Legende im Diagramm bleibt klein.

## 0.2.14 – 08.11.2026

- **Diagramme starten mit 20 Hz – 20 kHz** statt mit 1 Hz – 20 kHz.
- **Die Skalierung bleibt erhalten:** Jedes Diagramm merkt sich seinen Frequenzbereich und „|Z|
  log“, auch nach dem Schließen und Neustarten. Gilt für Zoomen, Verschieben, *Rechtsklick →
  Frequenzbereich* und „Bereich festlegen …“. Im Tab „Impedanz“ bleiben außerdem Ansicht
  (Betrag/Phase oder Real/Imaginär) und Glättung erhalten.
- Eine neue Messung passt nur noch die senkrechte Achse an die Kurven an. Der Frequenzbereich bleibt
  so, wie du ihn eingestellt hast. Die senkrechte Achse richtet sich dabei nach dem sichtbaren
  Bereich.
- „Alles zeigen“ zeigt wie bisher den ganzen Bereich ab 1 Hz. Zurück zum Hörbereich geht es über
  *Rechtsklick → Frequenzbereich → Hörbereich*.

## 0.2.13 – 08.11.2026

- **Taskleiste (Windows):** Angeheftet bleibt jetzt das Programmsymbol, nicht das Python-Symbol,
  und ein Klick startet wieder die Messsoftware. *Wer das Programm schon angeheftet hat: einmal
  lösen und bei laufendem Programm neu anheften.*
- **Diagrammhintergrund frei wählbar:** *Ansicht → Darstellung …* hat einen Schieberegler von
  dunkel über grau bis weiß, dazu „Farbe …“ für jede beliebige Farbe. „Wie Farbschema“ stellt den
  Standard wieder her. Achsen, Schrift und Modellkurven passen sich automatisch an.
- **Touch-Bedienung:** Für Touchscreens (z. B. Surface) gibt es große Knöpfe, Auswahlfelder,
  Häkchen, Reiter, Bildlaufleisten und Regler. Einstellbar in *Ansicht → Darstellung … →
  Bedienung*: „Automatisch“ schaltet sie ein, wenn ein Touchscreen erkannt wird. Der Schnellschalter
  ist *Ansicht → Große Schaltflächen (Touch)*.
- Im Darstellungs-Fenster wirken Hintergrund und Bedienung sofort. „Abbrechen“ stellt den vorherigen
  Zustand wieder her.

## 0.2.12 – 08.11.2026

- „Was ist neu?“ nach einem Update zeigt oben, was seit deiner letzten Version neu ist, und darunter
  die komplette Geschichte aller früheren Versionen.

## 0.2.11 – 08.11.2026

- Bei festgelegten Frequenzbereichen („Hörbereich“, „Bereich festlegen …“) stehen die
  Eckfrequenzen (z. B. 20 Hz und 20 kHz) jetzt in der Achsenbeschriftung. Die Achse hat dafür
  einen kleinen Rand.
- Betrags- und Phasendiagramm liegen exakt bündig übereinander.

## 0.2.10 – 08.11.2026

- **Behoben:** Beim Umschalten von „|Z| log“ (und zwischen Betrag/Phase und Real/Imaginär) sprang
  die Frequenzachse auf den ganzen Bereich zurück, ein eingestellter Zoom ging verloren. Der
  gewählte Frequenzbereich bleibt jetzt erhalten; „Alles zeigen“ setzt ihn wie gewohnt zurück.
- Simulator: Der simulierte Klirr ist auf ein realistisches Maß gesenkt. Die Kurve war beim Zoomen
  um 60–150 Hz leicht wellig. Echte Messungen waren nicht betroffen.

## 0.2.9 – 08.11.2026

- **Aktualisieren ohne schwarze Fenster:** „Jetzt aktualisieren“ zeigt ein kleines Fenster mit
  Fortschrittsbalken, spielt die neue Version ein und startet das Programm neu. Die Bibliotheken
  werden nur noch neu eingerichtet, wenn sich ihre Liste tatsächlich geändert hat, dann unsichtbar
  im Hintergrund. Klappt etwas nicht, läuft die bisherige Version einfach weiter.
  *Gilt ab dem nächsten Update* – dieses hier läuft noch über den alten Weg.
- Die Update-Dateien im Programmordner bleiben als Notlösung erhalten.

## 0.2.8 – 08.11.2026

- **Behoben:** „Nach Updates suchen“ meldete direkt nach einer Veröffentlichung bis zu 5 Minuten
  lang noch die alte Version, weil GitHub die Datei zwischenspeichert. Jetzt fragt das Programm
  zuerst nach dem neuesten Stand und liest die Versionsnummer genau dieses Stands. Eine neue
  Version wird so spätestens nach etwa einer Minute erkannt.

## 0.2.7 – 08.11.2026

- **Mindestverschiebung bei der Vas-Bestimmung:** Zusatzmasse bzw. Testgehäuse müssen fs
  ausreichend verschieben, sonst werden kleine Messfehler stark vergrößert (1 % Verschiebung →
  Vas/Mms rund ±25 % daneben).
  - unter 5 % Verschiebung: keine Berechnung, mit Erklärung
  - 5 bis 20 %: Berechnung mit deutlicher Warnung und geschätzter Unsicherheit
  - in beiden Fällen der konkrete Tipp, welche Zusatzmasse bzw. welches Testvolumen etwa
    25–30 % Verschiebung ergibt
- Verschiebung und geschätzte Unsicherheit stehen in der Ergebnistabelle und auf dem Datenblatt.
- Schlägt eine Berechnung fehl, verschwindet das alte Ergebnis, damit es nicht für das neue
  gehalten wird.
- Voreinstellung der Zusatzmasse 20 g statt 10 g.

## 0.2.6 – 08.11.2026

- **Kennwerte als große Kacheln:** fs, Qts (hervorgehoben), Re, Qes, Zmax, Qms, Le und die
  Messqualität sind jetzt gut lesbar. Gezeigt wird die in der Liste markierte Messung, sonst die
  neueste. Sind mehrere Kurven sichtbar, steht darunter eine Vergleichstabelle.
- **Seitenleiste ausblendbar:** ☰ links neben den Reitern oder *Ansicht → Seitenleiste anzeigen*
  (Strg+B). Der Mess-Knopf erscheint dann kompakt oben rechts. Ohne Seitenleiste lässt sich das
  Fenster auf etwa 780 Pixel verkleinern; die Werkzeugleiste bricht bei Bedarf in eine zweite
  Zeile um.
- **Jetzt aktualisieren:** Der Hinweis auf eine neue Version hat einen Knopf, der das Programm
  schließt, die neue Version holt und sie wieder startet.
- **Update-Dateien starten das Programm danach automatisch** (nur bei Erfolg; bei einem Fehler
  bleibt das Fenster mit der Meldung offen). Läuft das Programm noch, wartet das Update, bis es
  geschlossen ist. *Wirkt ab dem nächsten Update* – dieses hier läuft noch mit dem alten Skript.

## 0.2.5 – 08.11.2026

- **Behoben:** Unter Windows hat die Überwachung von Ein- und Ausstecken in 0.2.4 nicht
  gearbeitet. Das schlanke Qt-Paket enthält dort das dafür vorgesehene Multimedia-Modul nicht.
  Jetzt fragt das Programm die Geräteliste alle 2 Sekunden direkt bei Windows ab. Das erkennt
  Einstecken und Abziehen ebenso wie „Deaktivieren/Aktivieren“ in den Sound-Einstellungen.

## 0.2.4 – 08.11.2026

- **Ein- und Ausstecken wird bemerkt:** Wird ein Audiogerät angeschlossen oder getrennt, liest das
  Programm die Geräteliste von selbst neu ein. Vorher erschien ein bei laufendem Programm
  eingestecktes DATS erst nach einem Neustart; auch der ↻-Knopf liest die Liste jetzt wirklich neu.
- **Neues Gerät – ist das das DATS?** Ein frisch eingestecktes DATS wird automatisch gewählt.
  Meldet sich ein neues Gerät mit zwei Eingängen unter einem anderen Namen, fragt das Programm
  nach. Nach „Ja“ merkt es sich das Gerät, zeigt es mit ★ und wählt es künftig automatisch.
  Von Hand: *Messung → Gewähltes Gerät als DATS merken / vergessen*.
- Der **Geräte-Check** merkt sich ein Gerät als DATS, sobald er die Messbrücke nachgewiesen hat.
- Wird das gewählte Gerät getrennt, sagt das Programm Bescheid und wechselt zum Simulator.

## 0.2.3 – 08.11.2026

- **Eingang und Ausgang einzeln wählen** (⚙ neben der Geräteauswahl oder *Messung → Audio-Geräte
  einzeln wählen*) – wie im Original-Programm von Dayton: erst die Schnittstelle (WASAPI,
  DirectSound, MME …), dann Aufnahme- und Wiedergabegerät. Der Dialog prüft sofort, ob der Treiber
  die Kombination mit der eingestellten Abtastrate annimmt. Die Wahl erscheint als „✎ … (manuell)“
  in der Geräteliste und bleibt gespeichert.
- Geräteliste aufgeräumt: „Microsoft Sound Mapper“ und doppelte WDM-KS-Einträge (dieselbe
  Hardware unter anderem Namen) werden nicht mehr angezeigt.
- Automatisches Sichern nur noch nach Änderungen (vorher alle 2 Minuten, auch ohne Änderung).
- Die Geräteliste wird beim Start nur noch einmal aufgebaut.

## 0.2.2 – 08.11.2026

- **Geräteauswahl überarbeitet:** Windows meldet Soundkarten – auch das DATS – als zwei getrennte
  Geräte (Lautsprecher und Mikrofon), und das für jede Treiber-Schnittstelle noch einmal. Die
  Auswahl führt Ein- und Ausgang jetzt zu einem Eintrag zusammen und wählt automatisch die beste
  Schnittstelle (WASAPI, sonst DirectSound oder MME), die die eingestellte Abtastrate kann.
  Ohne diese Änderung wäre das DATS unter Windows vermutlich gar nicht in der Liste erschienen.
- Die eingebaute Soundkarte steht jetzt in der Liste, aber grau. Geräte mit nur Ausgang oder nur
  Eingang sind grau und kursiv und lassen sich nicht wählen. Wer mit der Maus darüberfährt, sieht
  die Erklärung.

## 0.2.1 – 08.11.2026

- **Behoben:** Im Simulator war die Impedanzkurve unterhalb von etwa 10 Hz unruhig. Ursache war
  der neue simulierte Klirr; echte Messungen waren nicht betroffen.
- Neue Messungen ohne Speicherplatz bekommen kräftige Farben statt Grau und Oliv.
- Diagramme als Karten mit runden Ecken, passend zum übrigen Design.
- Die Kennwerte-Tabelle füllt die Breite aus.
- Nach dem Update von 0.1 erscheint „Was ist neu?“ statt „Erste Schritte“.

## 0.2.0 – 08.11.2026

**Neues Aussehen**
- Modernes Design im Stil des neuen Programmsymbols: Karten mit runden Ecken, flache Reiter,
  blauer Mess-Knopf – in Hell und Dunkel.
- Eigenes Programmsymbol in Fenster und Taskleiste (statt des Python-Symbols). Unter Windows wird
  beim ersten Start eine Desktop-Verknüpfung „DATS-Messsoftware“ angelegt.

**Messen**
- **Messqualität auf einen Blick:** Neben jeder Messung ein grüner, gelber oder roter Punkt. Der
  Tooltip nennt den Grund – Übersteuerung, zu wenig Pegel, Rauschen, Brummen, vertauschte Eingänge.
- **Geräte-Check** (Messung → Geräte-Check): findet beim echten DATS heraus, welcher Eingang Referenz
  und welcher Messung ist, und bestimmt Referenz- und Kalibrierwiderstand – mit einem
  Multimeter-Widerstand sogar absolut. Live-Pegelanzeige für beide Eingänge.
- **Pegelreihe** (neuer Tab): misst automatisch bei mehreren Pegeln und zeigt, wie sich fs, Qms,
  Qes, Qts und Re mit dem Pegel ändern.

**Auswerten**
- **Vergleich** (neuer Tab): Treiber-Exemplare gegen eine Referenz, Abweichungen in Prozent mit
  Toleranz-Ampel, |Z|-Abweichung über der Frequenz und Vorschlag der besten Paare.
- **Korrektur** (neuer Tab): Zobel-Glied und Saugkreis berechnen, auf Normwerte runden, Wirkung
  ansehen und die korrigierte Kurve in die Messliste übernehmen.
- **Klirr & Rub/Buzz** (neuer Tab): elektrischer Klirrfaktor (k2 … k5) und Schleifgeräusche aus
  jeder vorhandenen Messung – ohne zusätzliche Messung.
- **Oszilloskop** im Tab „Generator & Oszilloskop“: beide Eingänge live als Zeitverlauf (mit
  Trigger) oder Spektrum, mit Pegel, Frequenz und THD+N.
- **Datenblatt:** eigenes Kommentarfeld, wird mit der Messung gespeichert.

**Komfort und Hilfe**
- **Fehlerbericht** (Hilfe → Fehlerbericht): kopiert Version, System, Audio-Geräte, Einstellungen
  und Protokoll in die Zwischenablage – ohne persönliche Ordnernamen. Bei einem Programmfehler
  öffnet er sich automatisch, das Programm läuft weiter.
- **Hinweis auf neue Versionen** beim Start (abschaltbar unter Hilfe).
- **Erste Schritte** und **Was ist neu?** im Hilfe-Menü.
- **Automatisches Sichern** alle 2 Minuten; nach einem Absturz werden die Messungen zur
  Wiederherstellung angeboten.
- **Datei → Zuletzt geöffnet.**
- Versionsnummer in Titelleiste und Statusleiste.
- Simulator: mehrere Treiber-Exemplare, pegelabhängiges Verhalten und ein „Treiber mit
  Schleifgeräusch“ zum Ausprobieren.

## 0.1.0

- Erste Version: Impedanz, T/S-Parameter mit Wright-Modell, LCR, Signalgenerator, Kalibrier-
  Assistent, Export/Import, Watch-Folder, Projektarchiv, Speicherplätze, Datenblatt.
