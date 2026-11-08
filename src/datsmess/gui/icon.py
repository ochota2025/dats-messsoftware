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


def relaunch_command() -> str:
    """Befehl, den Windows für ein an die Taskleiste angeheftetes Programm speichert.
    Immer ``pythonw.exe`` (kein Konsolenfenster), auch wenn gerade ``python.exe`` läuft."""
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe" and (exe.parent / "pythonw.exe").exists():
        exe = exe.parent / "pythonw.exe"
    return f'"{exe}" -m datsmess'


def relaunch_properties() -> dict[int, str]:
    """System.AppUserModel.*-Eigenschaften (Schlüssel = PID im Format-ID-Block).
    Reihenfolge wichtig: die Relaunch-Angaben vor der ID setzen."""
    return {
        2: relaunch_command(),                          # RelaunchCommand
        4: "DATS-Messsoftware",                         # RelaunchDisplayNameResource
        3: f"{RESOURCES / 'icon.ico'},0",               # RelaunchIconResource
        5: APP_ID,                                      # ID
    }


def set_window_relaunch(widget) -> bool:
    """Hinterlegt am Fenster, wie Windows das Programm neu startet und mit welchem Symbol.

    Ohne diese Angaben merkt sich „An Taskleiste anheften“ nur ``pythonw.exe`` – angeheftet
    erscheint dann das Python-Symbol, und ein Klick darauf startet nicht die Messsoftware."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("data", ctypes.c_ubyte * 16)]

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

        class PROPVARIANT(ctypes.Structure):
            _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                        ("r3", ctypes.c_ushort), ("pwszVal", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]

        def guid(s: str) -> GUID:
            return GUID.from_buffer_copy(uuid.UUID(s).bytes_le)

        VT_LPWSTR = 31
        fmtid = guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")       # PKEY_AppUserModel_*
        iid = guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")         # IID_IPropertyStore
        shell32 = ctypes.windll.shell32
        shell32.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.POINTER(GUID),
                                                        ctypes.POINTER(ctypes.c_void_p)]
        shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
        store = ctypes.c_void_p()
        hwnd = int(widget.winId())
        hr = shell32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(iid), ctypes.byref(store))
        if hr < 0 or not store.value:
            log.warning("Taskleisten-Eigenschaften: SHGetPropertyStoreForWindow 0x%08X", hr & 0xFFFFFFFF)
            return False
        vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))(vtbl[6])
        commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        ok = True
        try:
            for pid, text in relaunch_properties().items():
                key = PROPERTYKEY(fmtid, pid)
                pv = PROPVARIANT(VT_LPWSTR, 0, 0, 0, text, None)
                hr = set_value(store, ctypes.byref(key), ctypes.byref(pv))
                if hr < 0:
                    ok = False
                    log.warning("Taskleisten-Eigenschaft %d: 0x%08X", pid, hr & 0xFFFFFFFF)
            commit(store)
        finally:
            release(store)
        log.info("Taskleisten-Eigenschaften gesetzt: %s", relaunch_command())
        return ok
    except Exception as e:      # noqa: BLE001
        log.warning("Taskleisten-Eigenschaften nicht gesetzt: %s", e)
        return False


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
