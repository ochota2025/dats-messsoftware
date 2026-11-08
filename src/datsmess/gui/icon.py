"""Programmsymbol, Windows-Taskleiste und Desktop-Verknüpfung.

Unter Windows läuft das Programm als ``pythonw.exe``; ohne eigene AppUserModelID zeigt die
Taskleiste deshalb das Python-Symbol. ``set_windows_app_id`` muss vor dem ersten Fenster laufen.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6 import QtGui

log = logging.getLogger("datsmess")

RESOURCES = Path(__file__).resolve().parents[1] / "resources"
APP_ID = "datsmess.messsoftware"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def app_icon() -> QtGui.QIcon:
    icon = QtGui.QIcon()
    for p in sorted(RESOURCES.glob("icon_*.png")):
        icon.addFile(str(p))
    return icon


def icon_pixmap(size: int) -> QtGui.QPixmap:
    return app_icon().pixmap(size, size)


def set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception as e:      # noqa: BLE001
        log.warning("AppUserModelID nicht gesetzt: %s", e)


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def create_desktop_shortcut(root: Path = PROJECT_ROOT) -> Path | None:
    """Legt „DATS-Messsoftware.lnk“ auf dem Desktop an (nur Windows). Ziel ist Start-Windows.bat
    (minimiert gestartet), damit Updates weiterhin automatisch eingerichtet werden."""
    if sys.platform != "win32":
        return None
    bat = root / "Start-Windows.bat"
    ico = RESOURCES / "icon.ico"
    if not bat.exists():
        log.warning("Desktop-Verknüpfung: %s fehlt", bat)
        return None
    script = (
        "$d = [Environment]::GetFolderPath('Desktop');"
        "$p = Join-Path $d 'DATS-Messsoftware.lnk';"
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($p);"
        f"$s.TargetPath = {_ps_quote(str(bat))};"
        f"$s.WorkingDirectory = {_ps_quote(str(root))};"
        f"$s.IconLocation = {_ps_quote(str(ico) + ',0')};"
        "$s.WindowStyle = 7;"
        "$s.Description = 'DATS-Messsoftware - Impedanz, T/S, LCR';"
        "$s.Save();"
        "Write-Output $p"
    )
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                             capture_output=True, text=True, timeout=30, creationflags=flags)
        if out.returncode != 0:
            log.warning("Desktop-Verknüpfung fehlgeschlagen: %s", out.stderr.strip()[:500])
            return None
        path = Path(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else None
        log.info("Desktop-Verknüpfung angelegt: %s", path)
        return path
    except Exception as e:      # noqa: BLE001
        log.warning("Desktop-Verknüpfung fehlgeschlagen: %s", e)
        return None


def shortcut_supported() -> bool:
    return sys.platform == "win32" and os.environ.get("DATSMESS_NO_SHORTCUT") is None
