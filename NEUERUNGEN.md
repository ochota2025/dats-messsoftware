# Neuerungen

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
