# CLAUDE.md – Arbeitsabsprachen für dieses Projekt

DATS-Messsoftware: plattformübergreifende Impedanz-, T/S- und LCR-Messsoftware für das
Dayton Audio DATS V3 (Python 3.12, PySide6-Essentials, pyqtgraph, NumPy/SciPy, sounddevice).
Öffentlich auf GitHub: `ochota2025/dats-messsoftware`, Zweig `main`.

## Zusammenarbeit

- Mit dem Nutzer **auf Deutsch und per du** sprechen. Oberfläche, Meldungen, Anleitungen: Deutsch.
- **Committen und pushen nur nach ausdrücklichem OK.** Commit-Nachrichten auf Deutsch:
  Überschrift + Stichpunkte, Abschluss `Co-Authored-By: Claude …`.
  Git-Identität ist repo-lokal gesetzt (`ochota2025`, noreply-Adresse) – nicht ändern.
- Ein Tester nutzt **Windows** und holt Updates mit `Update-Windows.bat` (lädt `main` als ZIP
  von GitHub). Nach jedem Push dem Nutzer eine kurze, fertige Messenger-Nachricht für den
  Tester vorschlagen (Codeblock, du-Form, Emojis sparsam).
- Rückmeldungen kommen oft als Handyfotos vom Bildschirm – genau hinsehen, welche Version
  zu sehen ist (alte Version = dunkles Design ohne „Ansicht“-Menü, keine Kennwerte rechts oben).
- Keine personenbezogenen Daten (Namen, E-Mail) in Dateien des öffentlichen Repos.

## Prüfen vor jedem Commit

```bash
.venv/bin/python -m pytest -q          # muss grün sein (derzeit 44 Tests)
```

GUI-Änderungen zusätzlich offscreen durchspielen und per Screenshot ansehen:
`QT_QPA_PLATFORM=offscreen`, `QtCore.QStandardPaths.setTestModeEnabled(True)` und eine eigene
`setOrganizationName(...)`, damit echte Einstellungen/Kalibrierungen unberührt bleiben.
Ohne Hardware immer mit dem Simulator (`audio/simulator.py`) testen.

## Aufbau (Kurzfassung, Details in README.md)

- `dsp/` Sweep, Übertragungsfunktion, Kalibrierung (Möbius-OSL), Signalgenerator
- `analysis/` T/S-Fit inkl. Wright-Modell, Vas-Methoden, `quick_parameters`/Treibererkennung, LCR
- `audio/` PortAudio-Backend, Simulator · `measurement.py` Mess-Engine (Rohaufnahmen bitgenau reproduzierbar)
- `io/` Exportformate, T/S-Profile, Watch-Folder, Projektarchiv `.datsproj`
- `gui/` Hauptfenster, Tabs, `appearance.py` (Hell/Dunkel), `slots.py` (8 Speicherplätze),
  `params_panel.py` (Sofort-Kennwerte), `datasheet.py` (PDF/Druck), `de.py` (deutsche Knöpfe)

## Bekannte Fallstricke

- **PySide6-Essentials enthält keine Qt-Übersetzungen**: Standardknöpfe über `gui/de.py`
  (`button_box`, `ask`, `get_text`, `get_item`, `germanize`) eindeutschen, nie `QMessageBox.question` direkt.
- **pyqtgraph-Log-Achsen** rechnen intern in log10: Bereiche mit `np.log10(...)` setzen, beim
  Anzeigen zurückrechnen. Das eingebaute ViewBox-Menü ist bewusst deaktiviert (eigenes Menü in `plots.py`).
- **Farben** nie fest verdrahten: `appearance().current` (plot_bg, plot_fg, ok, warn, err …) oder
  Stylesheets mit `palette(...)`; Diagramme reagieren auf `appearance().changed`.
- **Szene in PDF rendern** skaliert Schriften doppelt → im Datenblatt über ein Zwischenbild (96 dpi, ×3).
- Startdateien: `.bat` und `tools/update.ps1` nur ASCII und CRLF. Update-Skripte so bauen, dass
  sie sich während des Laufs selbst überschreiben dürfen (bash: alles in einer Funktion; .bat: eine Zeile).
- Installation ist editierbar (`pip install -e .`); das Flag `.venv/datsmess-editable.flag`
  steuert die einmalige Neu-Einbindung nach einem Update.

## Stand und offene Punkte

- Läuft beim Tester unter Windows (Simulator). **Noch nie mit echtem DATS V3 getestet** –
  Kanalzuordnung, Wert des Kalibrierwiderstands und Kalibrierung sind die Unbekannten.
- Offen laut Forderungskatalog: pegelabhängige Messreihen (FA-01), Rub & Buzz (FA-03),
  Oszilloskop (OS-01). Native Treiberdateien von WinISD/VituixCAD/Boxsim/LEAP/AJ-Horn sind
  nicht öffentlich spezifiziert – Profile liefern Eingabelisten.
