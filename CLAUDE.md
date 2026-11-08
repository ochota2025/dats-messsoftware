# CLAUDE.md – Arbeitsabsprachen für dieses Projekt

DATS-Messsoftware: plattformübergreifende Impedanz-, T/S- und LCR-Messsoftware für das
Dayton Audio DATS V3 (Python 3.12, PySide6-Essentials, pyqtgraph, NumPy/SciPy, sounddevice).
Öffentlich auf GitHub: `ochota2025/dats-messsoftware`, Zweig `main`.

## Zusammenarbeit

- Mit dem Nutzer **auf Deutsch und per du** sprechen. Oberfläche, Meldungen, Anleitungen: Deutsch.
- **Committen und pushen ohne Rückfrage erlaubt** (Freigabe vom 08.11.2026) – aber nur fertige,
  geprüfte Stände (Tests grün, GUI durchgespielt), der Tester holt direkt von `main`.
  Commit-Nachrichten auf Deutsch: Überschrift + Stichpunkte, Abschluss `Co-Authored-By: Claude …`.
- **Bei jeder Veröffentlichung `__version__` erhöhen** (`src/datsmess/__init__.py` und
  `pyproject.toml`) und einen Abschnitt in `NEUERUNGEN.md` ergänzen – darauf beruhen der
  Update-Hinweis in der App und „Was ist neu?“.
  Git-Identität ist repo-lokal gesetzt (`ochota2025`, noreply-Adresse) – nicht ändern.
- Ein Tester nutzt **Windows** und holt Updates mit `Update-Windows.bat` (lädt `main` als ZIP
  von GitHub). Nach jedem Push dem Nutzer eine kurze, fertige Messenger-Nachricht für den
  Tester vorschlagen (Codeblock, du-Form, Emojis sparsam).
- Rückmeldungen kommen oft als Handyfotos vom Bildschirm – genau hinsehen, welche Version
  zu sehen ist (Versionsnummer steht seit 0.2.0 in Titel- und Statusleiste). Besser: Tester um
  *Hilfe → Fehlerbericht → Kopieren* bitten.
- Keine personenbezogenen Daten (Namen, E-Mail) in Dateien des öffentlichen Repos.

## Prüfen vor jedem Commit

```bash
.venv/bin/python -m pytest -q          # muss grün sein (derzeit 70 Tests)
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
- **Audio-Dauerbetrieb** (Generator/Oszilloskop/Pegelanzeige) blockiert das Gerät: `AppState.run`
  stoppt ihn vor jeder Messung (`stop_audio`), `SoundDeviceBackend.play_record` ebenfalls.
- Unter Windows läuft `pythonw` ohne Konsole: Fehler gehen ins Protokoll (`datsmess.log` im
  App-Datenordner) und in den Fehlerdialog; `print` ist dort unsichtbar.
- **Szene in PDF rendern** skaliert Schriften doppelt → im Datenblatt über ein Zwischenbild (96 dpi, ×3).
- Startdateien: `.bat` und `tools/update.ps1` nur ASCII und CRLF. Update-Skripte so bauen, dass
  sie sich während des Laufs selbst überschreiben dürfen (bash: alles in einer Funktion; .bat: eine Zeile).
- Installation ist editierbar (`pip install -e .`); das Flag `.venv/datsmess-editable.flag`
  steuert die einmalige Neu-Einbindung nach einem Update.

## Stand und offene Punkte

- Läuft beim Tester unter Windows (Simulator). **Noch nie mit echtem DATS V3 getestet** –
  Kanalzuordnung, Wert des Kalibrierwiderstands und Kalibrierung sind die Unbekannten.
- Forderungskatalog vollständig (FA-01, FA-03 elektrisch, OS-01 seit 0.2.0). Native Treiberdateien von WinISD/VituixCAD/Boxsim/LEAP/AJ-Horn sind
  nicht öffentlich spezifiziert – Profile liefern Eingabelisten.
