# Anleitung: DATS-Messsoftware installieren und aktuell halten

Für Windows und Mac. Du brauchst keine Programmierkenntnisse, kein Git und kein GitHub-Konto.

---

## 1. Einmalig: Python installieren

1. <https://www.python.org/downloads/> öffnen und auf den großen gelben Download-Knopf klicken.
2. Installieren:
   - **Windows:** Der „Python install manager“ ist richtig. Einfach durchklicken. Erscheint
     danach ein schwarzes Fenster mit Fragen (z. B. ob etwas zum PATH hinzugefügt werden soll):
     mit **y** und Enter bestätigen.
   - **Mac:** Das .pkg öffnen und durchklicken.

## 2. Einmalig: Software herunterladen

1. Die Projektseite öffnen: **https://github.com/ochota2025/dats-messsoftware**
2. Auf den grünen Knopf **<> Code** klicken → **Download ZIP**.
3. Die ZIP-Datei entpacken, z. B. in „Dokumente“. Es entsteht ein Ordner
   `dats-messsoftware-main`. Den kannst du umbenennen, wie du willst.

> Hattest du die Software schon per WhatsApp-ZIP installiert? Dann den alten Ordner einfach
> löschen und hier neu anfangen. Das geht schneller als beim ersten Mal, weil die Bibliotheken
> schon auf dem Rechner zwischengespeichert sind.

## 3. Starten

Im Ordner doppelklicken:

| | Datei |
|---|---|
| Windows | **`Start-Windows.bat`** |
| Mac | **`Start-Mac.command`** (beim allerersten Mal: Rechtsklick → *Öffnen*, sonst blockiert macOS) |

Beim **ersten Start** richtet sich alles selbst ein (einige Minuten, ca. 500 MB). Ein schwarzes
Fenster zeigt den Fortschritt. **Nicht hineinklicken!** Unter Windows hält ein Klick das Fenster
an (oben steht dann „Auswählen“; mit **Esc** geht es weiter). Am Ende schließt sich das Fenster,
und das Programm öffnet sich. Beim allerersten Mal kann das bis zu einer Minute dauern.

Danach startet das Programm bei jedem Doppelklick sofort.

## 4. Updates holen

1. Programm schließen.
2. Im Ordner doppelklicken:
   - Windows: **`Update-Windows.bat`**
   - Mac: **`Update-Mac.command`**
3. Wenn „Update fertig“ erscheint: Fenster schließen und wie gewohnt starten.
   Beim ersten Start nach einem Update steht kurz „Neue Version wird eingerichtet“.

Deine Messungen und Projektdateien (`.datsproj`) bleiben dabei unverändert, solange du sie
nicht im Programmordner selbst speicherst. Am besten legst du sie in einen eigenen Ordner.

## 5. Erste Schritte ohne DATS (Simulator)

Ohne angeschlossenes DATS läuft ein eingebauter Simulator mit einem virtuellen 6,5″-Tieftöner.

1. **Kalibrier-Assistent …** → bei jedem Schritt *Messen*, dann *Weiter*. Danach steht links
   grün „Kalibriert“.
2. **Impedanz messen** → Impedanzkurve mit Resonanzspitze.
3. Tab **T/S-Parameter** → *Messen* (Freiluft), *Messen* (Zusatzmasse), **Parameter berechnen**.
4. Tab **Bauteile (LCR)** → Typ „Kondensator“ → *Bauteil messen*.

## 6. Mit echtem DATS V3

1. DATS per USB anschließen und das Programm starten.
2. Oben bei **Gerät** das DATS auswählen (mit ★ markiert). Wird es nicht angezeigt: auf ↻ klicken.
3. **Kalibrier-Assistent** durchlaufen, diesmal mit echten Klemmen (offen, kurzgeschlossen,
   Kalibrierwiderstand am Gehäuse).
4. Die Ergebnisseite des Assistenten fotografieren und schicken. Mit echter Hardware ist die
   Software noch nicht getestet, das Foto hilft beim Prüfen.

## 7. Wenn etwas nicht klappt

- **„Python wurde nicht gefunden“:** Schritt 1 wiederholen, danach die Startdatei erneut doppelklicken.
- **Fenster hängt ohne Fortschritt:** einmal **Esc** drücken. Hilft das nicht: Foto schicken.
- **Programm erscheint nicht:** Im Programmordner oben in die Adresszeile des Explorers `cmd`
  tippen, Enter, dann `.venv\Scripts\python -m datsmess` eingeben und Enter drücken.
  Ein Foto der Meldung schicken.
- **Update schlägt fehl:** Foto vom Fenster schicken. Notlösung: Schritt 2 wiederholen und den
  *Inhalt* des Ordners `dats-messsoftware-main` aus der neuen ZIP in den Programmordner kopieren
  („Dateien ersetzen“).
- **Fehler melden oder Wünsche äußern:** per Nachricht, oder mit GitHub-Konto auf der
  Projektseite unter **Issues → New issue** (Fotos lassen sich hineinziehen).
