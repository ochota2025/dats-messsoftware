@echo off
rem Neueste Version von GitHub holen (alles in einer Zeile, damit das Ueberschreiben dieser Datei waehrend des Updates nichts stoert)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\update.ps1" & echo. & pause & exit /b
