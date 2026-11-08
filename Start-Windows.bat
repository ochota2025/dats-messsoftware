@echo off
rem DATS-Messsoftware starten (Windows). Beim ersten Start wird alles Noetige installiert.
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" goto update

echo.
echo  Erste Einrichtung - dauert einige Minuten (einmaliger Download der Programmbibliotheken) ...
echo  Falls hier eine Frage erscheint (z. B. ob Python installiert werden soll): mit "y" bzw. "j" bestaetigen.
echo.

rem 1. Versuch: "py" (neuer Python install manager oder klassischer Python-Launcher)
set "PY="
where py >nul 2>nul || goto trypython
py -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto trypython
set "PY=py"
goto havepy

rem 2. Versuch: "python"
:trypython
where python >nul 2>nul || goto nopython
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto nopython
set "PY=python"

:havepy
%PY% -m venv .venv || goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto fail
".venv\Scripts\python.exe" -m pip install -e . || goto fail
echo ok> ".venv\datsmess-editable.flag"
goto start

rem Neue Version ueber den alten Ordner entpackt: Programm einmalig neu einbinden (kein grosser Download)
:update
if exist ".venv\datsmess-editable.flag" goto start
echo.
echo  Neue Version wird eingerichtet ...
echo.
".venv\Scripts\python.exe" -m pip install -e . || goto fail
echo ok> ".venv\datsmess-editable.flag"

:start
start "" ".venv\Scripts\pythonw.exe" -m datsmess
exit /b 0

:nopython
echo.
echo  Python 3.10 oder neuer wurde nicht gefunden.
echo  Bitte installieren: https://www.python.org/downloads/
echo  (Der "Python install manager" ist richtig - einfach installieren.
echo   Fragen im schwarzen Fenster, z. B. zum PATH, mit "y" bestaetigen.)
echo  Danach diese Datei erneut doppelklicken.
echo.
pause
exit /b 1

:fail
echo.
echo  Die Einrichtung ist fehlgeschlagen. Bitte einen Screenshot dieses Fensters schicken.
echo  Vor einem neuen Versuch den Ordner ".venv" loeschen.
echo.
pause
exit /b 1
