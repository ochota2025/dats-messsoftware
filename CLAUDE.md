# CLAUDE.md – Arbeitsabsprachen für dieses Projekt

DATS-Messsoftware: plattformübergreifende Impedanz-, T/S- und LCR-Messsoftware für das
Dayton Audio DATS V3 (Python 3.12, PySide6-Essentials, pyqtgraph, NumPy/SciPy, sounddevice).
Öffentlich auf GitHub: `ochota2025/dats-messsoftware`, Zweig `main`.

## Zusammenarbeit

- Mit dem Nutzer **auf Deutsch und per du** sprechen. Oberfläche, Meldungen, Anleitungen: Deutsch.
- **Committen und pushen ohne Rückfrage erlaubt** (Freigabe vom 08.11.2026) – aber nur fertige,
  geprüfte Stände (Tests grün, GUI durchgespielt), der Tester holt direkt von `main`.
  Commit-Nachrichten auf Deutsch: Überschrift + Stichpunkte, Abschluss `Co-Authored-By: Claude …`.
- Update-Prüfung: `updates.fetch_remote` holt erst den Commit-SHA über die GitHub-API (≤ 60 s alt),
  dann die Rohdatei an diesem SHA – raw.githubusercontent.com cached `main` sonst bis zu 5 Minuten.
- **Bei jeder Veröffentlichung `__version__` erhöhen** (`src/datsmess/__init__.py` und
  `pyproject.toml`) und einen Abschnitt in `NEUERUNGEN.md` ergänzen – darauf beruhen der
  Update-Hinweis in der App und „Was ist neu?“. Versionen werden numerisch verglichen (0.2.10 > 0.2.9).
- Git-Identität ist repo-lokal gesetzt (`ochota2025`, noreply-Adresse) – nicht ändern.
- Ein Tester nutzt **Windows 10** (Laptop, Realtek, Python 3.15) und holt Updates in der App über
  *Hilfe → Nach Updates suchen → Jetzt aktualisieren* (Notlösung: `Update-Windows.bat`). Er ist
  kritisch, achtet auf Optik („altbacken“), Bedienkomfort und saubere Kurven – und meldet viel.
  Nach jedem Push dem Nutzer eine kurze, fertige Messenger-Nachricht für den Tester vorschlagen
  (Codeblock, du-Form, Emojis sparsam). Der Nutzer leitet Fotos/Texte des Testers weiter.
- Rückmeldungen kommen oft als Handyfotos vom Bildschirm – genau hinsehen, welche Version
  zu sehen ist (Versionsnummer steht seit 0.2.0 in Titel- und Statusleiste). Besser: Tester um
  *Hilfe → Fehlerbericht → Kopieren* bitten.
- Keine personenbezogenen Daten (Namen, E-Mail) in Dateien des öffentlichen Repos.

## Prüfen vor jedem Commit

```bash
.venv/bin/python -m pytest -q          # muss grün sein (derzeit 101 Tests)
```

GUI-Änderungen zusätzlich offscreen durchspielen und per Screenshot ansehen:
`QT_QPA_PLATFORM=offscreen`, `QtCore.QStandardPaths.setTestModeEnabled(True)` und eine eigene
`setOrganizationName(...)`, damit echte Einstellungen/Kalibrierungen unberührt bleiben.
Dazu `DATSMESS_NO_UPDATE_CHECK=1` setzen (sonst fragt die App GitHub nach Updates).
Ohne Hardware immer mit dem Simulator (`audio/simulator.py`) testen; die GUI schaltet dort
`level_dependent` und `distortion` ein, die Grundtests nicht.

## Aufbau (Kurzfassung, Details in README.md)

- `dsp/` Sweep, Übertragungsfunktion, Kalibrierung (Möbius-OSL), Signalgenerator
- `analysis/` T/S-Fit inkl. Wright-Modell, Vas-Methoden, `quick_parameters`/Treibererkennung, LCR
- `audio/` PortAudio-Backend, Simulator · `measurement.py` Mess-Engine (Rohaufnahmen bitgenau reproduzierbar)
- `io/` Exportformate, T/S-Profile, Watch-Folder, Projektarchiv `.datsproj`
- `gui/` Hauptfenster, ein Modul je Tab, `appearance.py` (Design-Tokens + Stylesheet hell/dunkel),
  `slots.py` (8 Speicherplätze), `params_panel.py` (Sofort-Kennwerte), `datasheet.py` (PDF/Druck,
  Kommentar), `device_check.py`, `errors.py` (Fehlerbericht, globale Ausnahmebehandlung),
  `help.py`, `icon.py`, `de.py` (deutsche Knöpfe)
- `analysis/quality.py` Ampel, `setup_check.py`, `matching.py`, `correction.py`;
  `dsp/distortion.py` Klirr/Rub & Buzz; `diagnostics.py` Protokoll; `updates.py` Versionsvergleich
- Programmsymbol: `tools/make_icon.py` erzeugt `src/datsmess/resources/` (nicht von Hand ändern)

## Bekannte Fallstricke

- **PySide6-Essentials enthält keine Qt-Übersetzungen**: Standardknöpfe über `gui/de.py`
  (`button_box`, `ask`, `get_text`, `get_item`, `germanize`) eindeutschen, nie `QMessageBox.question` direkt.
- **DATS V3 = Kleinsignal** (Soundkarte + Messwiderstand, kein Leistungsverstärker): Pegelreihe und
  Klirr nie mit Großsignal-Versprechen beschreiben; der Simulator (`level_dependent`, `distortion`)
  ist darauf gedämpft (Test `test_simulator_distortion_is_small_signal`). Großsignal kann das DATS LA.
- **Diagramm-Skalierung** (0.2.14): `ImpedancePlot(name=…)` speichert Frequenzbereich + |Z| log unter
  `plot/<name>` (Standard 20 Hz – 20 kHz); `set_curves(autorange=True)` passt nur Y an (`setAutoVisible`).
  Qt-Tests brauchen eine `QApplication` (nicht `QCoreApplication`), sonst stürzen spätere Widget-Tests ab.
- **pyqtgraph-Log-Achsen** rechnen intern in log10: Bereiche mit `np.log10(...)` setzen, beim
  Anzeigen zurückrechnen. Das eingebaute ViewBox-Menü ist bewusst deaktiviert (eigenes Menü in `plots.py`).
- **Farben** nie fest verdrahten: `appearance().current` (plot_bg, plot_fg, ok, warn, err, accent,
  card_bg, border, muted …) oder Stylesheets mit `palette(...)`; Diagramme reagieren auf
  `appearance().changed`. Das globale Stylesheet steht in `appearance.stylesheet()`; der große
  Mess-Knopf ist `objectName("primary")`.
- **Windows-Geräte:** MME/DirectSound/WASAPI melden jedes Gerät (auch das DATS) als getrenntes
  „Lautsprecher (…)“ und „Mikrofon (…)“ – je Schnittstelle. `audio/backend.device_choices` führt
  sie über den Namen in Klammern zu Paaren zusammen und bevorzugt WASAPI (Fallback, wenn die
  Abtastrate nicht passt). Gespeichert wird `device_key`, nicht der Anzeigetext.
  PortAudio liest Geräte nur beim Initialisieren: `rescan_devices()` (vorher Audio stoppen);
  Ein-/Ausstecken meldet `gui/device_watch.py`: unter Windows winmm-Abfrage alle 2 s, denn
  **PySide6-Essentials enthält unter Windows kein QtMultimedia** (auf dem Mac schon!). Als DATS bestätigte Geräte stehen in
  `dats_keys`, bekannte in `known_devices` (neue Geräte → Rückfrage „Ist das das DATS?“).
- **Audio-Dauerbetrieb** (Generator/Oszilloskop/Pegelanzeige) blockiert das Gerät: `AppState.run`
  stoppt ihn vor jeder Messung (`stop_audio`), `SoundDeviceBackend.play_record` ebenfalls.
- Unter Windows läuft `pythonw` ohne Konsole: Fehler gehen ins Protokoll (`datsmess.log` im
  App-Datenordner) und in den Fehlerdialog; `print` ist dort unsichtbar.
- **Szene in PDF rendern** skaliert Schriften doppelt → im Datenblatt über ein Zwischenbild (96 dpi, ×3).
- Selbst-Update (Standard seit 0.2.9): `selfupdate.py` + `gui/update_dialog.py` – laden (Commit-SHA),
  Dateien atomar ersetzen, `pip install -e .` nur wenn sich Abhängigkeiten in pyproject.toml ändern
  (Versionsnummer zählt nicht), Neustart mit `--wait-pid`. Keine Konsolenfenster.
- Update-Ablauf (Notlösung): `tools/update.ps1` (bzw. `Update-Mac.command`) wartet, bis das Programm geschlossen
  ist, aktualisiert und startet es nur bei Erfolg neu; `-FromApp` (Knopf „Jetzt aktualisieren“,
  `updates.launch_updater`) startet auch nach einem Fehler die alte Version wieder. Änderungen an
  den Update-Skripten wirken erst beim *übernächsten* Update – das nächste läuft mit dem alten Skript.
- Startdateien: `.bat` und `tools/update.ps1` nur ASCII und CRLF. Update-Skripte so bauen, dass
  sie sich während des Laufs selbst überschreiben dürfen (bash: alles in einer Funktion; .bat: eine Zeile).
- Installation ist editierbar (`pip install -e .`); das Flag `.venv/datsmess-editable.flag`
  steuert die einmalige Neu-Einbindung nach einem Update.

## Stand und offene Punkte (09.11.2026, Version 0.2.17)

**Läuft:** beim Tester unter Windows mit dem Simulator; Design im Stil des Icons (hell/dunkel),
Kennwert-Kacheln, ausblendbare Seitenleiste, Qualitäts-Ampel, Geräte-Check, Pegelreihe, Vergleich,
Korrektur, Klirr & Rub/Buzz, Oszilloskop, Datenblatt mit Kommentar, Fehlerbericht, Autosave,
Selbst-Update mit Fortschrittsfenster. Geräteerkennung und Ein-/Aussteck-Überwachung sind mit der
echten Geräteliste des Testers bestätigt (Testfall in `tests/test_features.py`).

**Echtes DATS V3 – erster Test (09.11.2026, Windows 11, 0.2.16):**
- Meldet sich als „USB AUDIO  CODEC“ (zwei Leerzeichen; „Lautsprecher (…)“ + „Line (…)“) – kein
  „DATS“ im Namen, wird über `dats_keys` gemerkt. **Referenz = Eingang 2, Messung = Eingang 1**
  (also „Eingangskanäle tauschen“ an). Kalibrierwiderstand (1 kΩ) ist beim V3 **im Gerät verbaut**
  (zwei Klemmen am Gehäuse); bei V1/V2 ein loser 1-kΩ-Widerstand. Wirksamer Referenzwiderstand ≈ 94 Ω (R_cal 1 kΩ: Verhältnis
  10,66). Kurzschluss: Messkanal −44 dB, Leitungswiderstand ~0,6 Ω.
- DirectSound: **Latenz 537 ms** → das Sweep-Ende fehlte (Müll ab ~9 kHz). Seit 0.2.17 nimmt
  `SoundDeviceBackend.play_record` ≥ 1 s länger auf und schneidet latenzbereinigt aus
  (`latency_of`, `align_recording`, `last_latency`). WASAPI scheiterte: Ausgang 48 kHz, Eingang
  44,1 kHz in Windows eingestellt → „Invalid sample rate“ (Tester soll beide gleich stellen).
- Ein harter Absturz (ohne Traceback im Protokoll) kurz nach der ersten Messung, Ursache offen –
  seit 0.2.17 steht `absturz.log` (faulthandler) im Fehlerbericht.
- Tester hört beim Messen ein „Fiepen/Unterton“ im Chassis – ungeklärt (Windows-Resampling
  44,1→48 kHz? Klangverbesserungen? USB-Störgeräusch?).
- 2-Ω-Chassis: unsere Werte (fs 78,5 Hz, Re 2,11 Ω, Qts 0,78) laut Tester plausibel zur
  Original-DATS-Software – genauer Vergleich (.zma im Tab „Vergleich“) steht noch aus.
- Tester hatte „Ref.-Widerstand“ von 100 auf 1000 Ω geändert (mit Kalibrierwiderstand verwechselt);
  seit 0.2.18 überschreibt die Kalibrierung das Feld mit dem gemessenen Wert, Beschriftung „(intern)“.
- **Taskleisten-Anheften unter Windows** (0.2.13): `icon.set_window_relaunch` setzt per
  `SHGetPropertyStoreForWindow` RelaunchCommand/-Icon/-Name + AppUserModelID am Hauptfenster –
  nur per Code geprüft. Alte Pins müssen einmal gelöst und neu angeheftet werden.
- **Touch-Modus** (0.2.13, `Appearance.touch`, `touch_stylesheet`) nur am Mac offscreen angesehen,
  nie mit echtem Touchscreen. Pinch-Zoom in Diagrammen gibt es noch nicht (pyqtgraph: nur Ziehen).
- Selbst-Update **mit Neustart unter Windows** (seit 0.2.9; der Tester kam bis dahin über den alten
  Skript-Weg). `--wait-pid`-Neustart unter Windows nur per Code geprüft.

**Vorschläge, vom Nutzer vorerst zurückgestellt** (nicht ungefragt anfangen):
- Startzeit Windows (~6 s laut Protokoll): Startbild + spätes Laden selten gebrauchter Tabs
- Oberflächen-Durchläufe als feste Tests (bisher Hilfsskripte im Scratchpad)
- WASAPI-Exklusivmodus (umgeht Windows-Mixer/Klangverbesserungen)
- Deutsche Dezimalkommas in Anzeige/Eingaben; Einrichtungs-Assistent aus einem Guss
- Simulator-Klirr erzeugte Artefakte in der Impedanzkurve, wenn er zu stark war (zweimal vom Tester
  bemerkt). Seit 0.2.16 ist er ~30× schwächer (realistisch fürs DATS V3) – Thema vermutlich erledigt;
  sonst Zeitfensterung der Oberwellen in der H-Schätzung
- Großsignal-Betrieb (externer Verstärker + Spannungsteiler an den Eingängen) – erst nach dem Test
  mit echtem DATS, dabei Ausgangsspannung und Serienwiderstand des V3 nachmessen
- Bauplan „Messbrücke selbst bauen“ (Soundkarte mit Stereo-Line-In + Widerstand), Android-Version –
  erst nach erfolgreichem Test mit echtem DATS

**Sonstiges:**
- T/S mit Zweitmessung: `analysis/ts.py` prüft die fs-Verschiebung (Abbruch < 5 %, Warnung < 20 %,
  Unsicherheit und Empfehlung für Masse/Volumen) – Schwellen als Konstanten `SHIFT_*`.
- Forderungskatalog vollständig (FA-01, FA-03 elektrisch, OS-01). Native Treiberdateien von
  WinISD/VituixCAD/Boxsim/LEAP/AJ-Horn sind nicht öffentlich spezifiziert – Profile liefern Eingabelisten.
- `main_window.py` ist auf gut 1000 Zeilen gewachsen – bei größeren Änderungen aufteilen.
