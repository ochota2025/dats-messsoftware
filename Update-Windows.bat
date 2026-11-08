@echo off
rem Neueste Version von GitHub holen und das Programm danach neu starten. Alles in einer Zeile, damit das Ueberschreiben dieser Datei waehrend des Updates nichts stoert. Bei einem Fehler bleibt das Fenster offen.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\update.ps1" || (echo. & pause) & exit /b
