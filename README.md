# DATS-Messsoftware

Plattformübergreifende (macOS, Windows, Linux) Mess-Software für das **Dayton Audio DATS V3**
Mess-Interface – Impedanz, Thiele/Small-Parameter, Wright-Modell und LCR-Messung über
Standard-Audiotreiber (CoreAudio, WASAPI/DirectSound/ASIO, ALSA/PipeWire), ohne Zusatztreiber.

Unabhängiges Projekt, nicht mit Dayton Audio verbunden.

## Schnellstart (ohne Vorkenntnisse)

1. Python 3.10 oder neuer installieren: <https://www.python.org/downloads/>
2. Oben auf dieser Seite **<> Code → Download ZIP**, entpacken.
3. Im Ordner doppelklicken: **`Start-Windows.bat`** bzw. **`Start-Mac.command`**.
4. Updates: **`Update-Windows.bat`** bzw. **`Update-Mac.command`** doppelklicken.

Ausführlich, mit Hilfe bei Problemen: **[ANLEITUNG-Benutzer.md](ANLEITUNG-Benutzer.md)**.
Projekt pflegen und Updates veröffentlichen: [ANLEITUNG-Projektpflege.md](ANLEITUNG-Projektpflege.md).

## Start für Entwickler

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/datsmess            # oder: .venv/bin/python -m datsmess
```

Ohne angeschlossene Hardware wählt die Software den **Simulator** (virtuelles DATS mit
6,5″-Testtreiber, Widerstand, Kondensator, Spule). Wird ein Gerät mit „DATS“/„Dayton“ im
Namen gefunden, wird es automatisch ausgewählt (★).

Tests: `.venv/bin/python -m pytest`

## Umfang dieses MVP (Bezug zum Forderungskatalog)

| Anforderung | Status |
|---|---|
| ANR-01 Plattformunabhängig (Python + PySide6) | ✔ |
| ANR-02 Standard-Audiotreiber via PortAudio (`sounddevice`) | ✔ – mit echter Hardware noch zu verifizieren |
| ANR-03 Ein-Fenster-Dashboard | ✔ |
| FN-01 Swept-Sine-Impedanzmessung, > 30 000 Punkte (≈ 109 000 bei 48 kHz), |Z|/Phase und Re/Im, zoombar | ✔ |
| FN-02 T/S-Parameter (fs, Re, Qms, Qes, Qts, Vas, Mms, Mmd, Cms, Rms, Bl, η0, SPL, Le …) | ✔ |
| FN-03 Vas: Testgehäuse, Zusatzmasse, bekannter SPL, bekannte Mmd | ✔ |
| FA-02 Wright-Parameter Kr, Xr, Ki, Xi (aus Modell-Fit) | ✔ |
| FB-01…03 LCR: C + ESR/DF/Q, L + DCR/Q, R + Ls | ✔ |
| FG-01 Signalgenerator (Sinus, Rechteck, Dreieck, Sägezahn, Impuls, Rauschen, Log-Sweep) | ✔ |
| DM-01 Export .zma/.frd/.txt/.csv, Import, T/S-Export .txt/.csv | ✔ |
| DM-02 Overlay-/Vergleichsmodus | ✔ |
| DM-03 Kalibrier-Assistent (Leerlauf / Kurzschluss / Kalibrierwiderstand) | ✔ |
| FS-01 .zma sowie .txt/.csv mit wählbarem Trennzeichen, Dezimalzeichen, Frequenz-/Impedanz-/Phaseneinheit und Spalten; Import erkennt die Einheiten | ✔ |
| FS-02 T/S-Export als .tsp/.ini, Profile WinISD, VituixCAD, Boxsim, LEAP, AJ-Horn – Datei oder Zwischenablage | ✔ (siehe Hinweis) |
| FS-03 Watch-Folder: atomare .zma-Übergabe (R_e verlustfrei im Kopf) + .tsp, optional automatisch nach jeder Messung | ✔ |
| FS-04 Projektarchiv .datsproj (Rohaufnahmen, Kalibrierungen, T/S, Treiberinfo + Notizen), bitgenau reproduzierbar | ✔ |
| Datenblatt (A4) mit Kurve und Parametern als PDF oder Ausdruck | ✔ |
| 8 Speicherplätze mit Tastenkürzeln, Sofort-Kennwerte, Hell/Dunkel | ✔ |
| FA-01 Pegelabhängige Messreihen (fs, Q, Re über dem Pegel) | ✔ |
| FA-03 Rub & Buzz – elektrisch, aus dem Impedanz-Sweep (höhere Harmonische) | ✔ (akustisch nur mit Mikrofon) |
| OS-01 Oszilloskop (Zeitverlauf mit Trigger, Spektrum, THD+N) | ✔ |
| Messqualitäts-Ampel, Geräte-Check (Kanalzuordnung, R_ref, R_cal) | ✔ |
| Paarvergleich, Impedanzkorrektur (Zobel, Saugkreis) | ✔ |
| Fehlerbericht, Update-Hinweis, automatisches Sichern | ✔ |

## Messprinzip

Ausgang → interner Referenzwiderstand → Messobjekt. Zwei Eingänge messen Referenz- und
Messspannung; die Übertragungsfunktion H = U_mess / U_ref wird aus Kreuz-/Autospektren eines
exponentiellen Sweeps gebildet (latenzunabhängig, mittelbar).

Die Kalibrierung nutzt, dass H bei jeder linearen Messbrücke eine Möbius-Funktion der Impedanz
ist: Mit drei Standards (offen, kurz, Kalibrierwiderstand) werden Kanaltoleranzen,
Eingangswiderstand, AC-Kopplung, Kabel- und Übergangswiderstände frequenzabhängig vollständig
herausgerechnet (siehe `src/datsmess/dsp/calibration.py`). Mit nur dem Kalibrierwiderstand wird
der Nennwert des Referenzwiderstands (Seitenleiste) als bekannt angenommen.

T/S-Parameter entstehen durch nichtlineare Anpassung des Modells
`Z = Re + Kr·ω^Xr + j·Ki·ω^Xi + Res / (1 + j·Qms·(f/fs − fs/f))` an die komplexe Impedanz;
die klassische Zmax/√(Zmax·Re)-Methode liefert die Startwerte.

## Schnittstellen zu Simulationsprogrammen

**Exportprofile (FS-02):** Die nativen Treiberdateien von WinISD (.wdr), VituixCAD
(`VituixCAD_drivers.txt`), Boxsim, LEAP und AJ-Horn sind nicht öffentlich spezifiziert. Die
Profile liefern die Werte deshalb in Reihenfolge, Bezeichnung und Einheit der jeweiligen
Eingabemaske (tabulatorgetrennt: Feld, Wert, Einheit). Gerundete Werte bleiben konsistent:
Qts wird aus den *gerundeten* Qms/Qes berechnet, sonst meldet WinISD Inkonsistenzen. Wer
das Originalformat eines Programms kennt (z. B. eine echte .wdr-Datei), kann es in
`src/datsmess/io/ts_export.py` als weiteres Profil ergänzen.

**.tsp/.ini:** INI-Datei mit `[Driver]`, `[Measurement]`, `[Parameters]` und `[Units]`,
inklusive Wright-Parametern; lesbar mit jedem INI-Parser.

**Watch-Folder (FS-03):** *Datei → Watch-Folder einstellen …* Messungen werden unter
gleichbleibendem Namen atomar (temporäre Datei + Umbenennen) als `.zma` geschrieben. Programme,
die geladene Dateien überwachen (z. B. VituixCAD), lesen dadurch nie eine halb geschriebene Datei.
R_e steht mit voller Genauigkeit im Kommentarkopf; liegen T/S-Parameter zur Messung vor, wird
eine `.tsp` daneben gelegt.

**Projektarchiv (FS-04):** `.datsproj` ist ein ZIP-Container (Aufbau in
`src/datsmess/io/project.py`). Gespeichert werden die 16-Bit-Rohaufnahmen jedes Sweeps, alle
verwendeten Kalibrierungen (ebenfalls als Rohaufnahmen), Sweep- und Kanaleinstellungen,
T/S-Eingaben und -Ergebnisse sowie Treiberinfo und Notizen. Impedanz und Übertragungsfunktion
werden beim Laden exakt neu berechnet; sie werden nur dann weggelassen, wenn beim Speichern
geprüft wurde, dass die Neuberechnung bitgleich ist. So belegt ein Projekt mit zwei Messungen
und Kalibrierung etwa 2 MB statt 13 MB. Mit *Neu berechnen* lassen sich alte Messungen aus den
Rohdaten mit einer neueren Kalibrierung korrigieren.

## Vor dem ersten Einsatz mit echter Hardware prüfen

Die interne Beschaltung des DATS V3 ist nicht öffentlich dokumentiert. Folgende Punkte sind
deshalb einstellbar und sollten einmal geprüft werden:

1. **Kanalzuordnung** – welcher Eingang Referenz und welcher Messung ist
   („Eingangskanäle tauschen“). Bei falscher Zuordnung meldet der Assistent eine starke
   Frequenzabhängigkeit des Referenzwiderstands.
2. **Wert des Kalibrierwiderstands** (Standard 1000 Ω) im Assistenten.
3. **Nennwert des Referenzwiderstands** (nur für Ein-Punkt-Kalibrierung relevant).
4. Falls das Gerät nur **einen Eingangskanal** meldet: Messprinzip „1 Kanal“ wählen und
   unbedingt mit Leerlauf kalibrieren.

## Aufbau

```
src/datsmess/
  dsp/        sweep.py, transfer.py, calibration.py, generator.py,
              distortion.py (Klirr/Rub & Buzz nach Farina)
  analysis/   ts.py (T/S, Wright, Vas-Methoden), lcr.py, quality.py (Ampel),
              setup_check.py (Geräte-Check), matching.py (Paarvergleich),
              correction.py (Zobel, Saugkreis)
  audio/      backend.py (PortAudio, Dauerbetrieb mit Ringpuffer), simulator.py (virtuelles DATS)
  io/         formats.py, ts_export.py, watch.py, project.py (.datsproj)
  gui/        main_window.py + ein Modul je Tab, appearance.py (Design hell/dunkel),
              device_check.py, calibration_wizard.py, datasheet.py, errors.py (Fehlerbericht),
              help.py, icon.py (Symbol, Taskleiste, Desktop-Verknüpfung), plots.py, state.py
  resources/  Programmsymbol (PNG/ICO) und Stylesheet-Symbole – erzeugt mit tools/make_icon.py
  diagnostics.py   Protokoll und Fehlerbericht
  updates.py       Versionsvergleich mit GitHub, NEUERUNGEN.md
  measurement.py   Mess-Engine (ohne GUI nutzbar)
tests/        End-to-End-Tests gegen den Simulator
```

### Klirr und Rub & Buzz

Beim exponentiellen Sweep liegen die Impulsantworten der Oberwellen nach der Entfaltung zeitlich
vor der linearen Antwort (Abstand `L·ln k`). `dsp/distortion.py` schneidet sie aus, rechnet den
Anteil heraus, der schon im Referenzkanal steckt (Wandler/Verstärker), und zieht die Rauschleistung
ab, die aus der Stille nach dem Sweep geschätzt wird. Ausgewertet wird die Klemmenspannung –
Rub & Buzz zeigt sich an den Harmonischen 10 … 20.
