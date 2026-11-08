"""Bemerkt, wenn Audiogeräte angeschlossen, getrennt, aktiviert oder deaktiviert werden.

PortAudio liest seine Geräteliste nur beim Initialisieren. Damit ein bei laufendem Programm
eingestecktes DATS erscheint, meldet diese Klasse Änderungen; das Hauptfenster liest dann neu ein.

* **Windows:** Die schlanke Qt-Variante (PySide6-Essentials) enthält dort kein QtMultimedia. Daher
  wird alle 2 s die Geräteliste der Windows-Audiobibliothek (winmm: Namen aller Aufnahme- und
  Wiedergabegeräte) abgefragt – kostet Mikrosekunden und erkennt Einstecken ebenso wie
  „Deaktivieren/Aktivieren“ in den Sound-Einstellungen.
* **macOS/Linux:** ``QMediaDevices`` aus QtMultimedia, sofern vorhanden.
* sonst: keine Überwachung – der ↻-Knopf liest die Liste neu ein.
"""
from __future__ import annotations

import logging
import sys

from PySide6 import QtCore

log = logging.getLogger("datsmess")


def windows_device_signature() -> tuple | None:
    """Namen aller MME-Aufnahme- und Wiedergabegeräte – ``None`` außerhalb von Windows."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class WAVEINCAPSW(ctypes.Structure):
        _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                    ("szPname", wintypes.WCHAR * 32), ("dwFormats", wintypes.DWORD),
                    ("wChannels", wintypes.WORD), ("wReserved1", wintypes.WORD)]

    class WAVEOUTCAPSW(ctypes.Structure):
        _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                    ("szPname", wintypes.WCHAR * 32), ("dwFormats", wintypes.DWORD),
                    ("wChannels", wintypes.WORD), ("wReserved1", wintypes.WORD),
                    ("dwSupport", wintypes.DWORD)]

    winmm = ctypes.windll.winmm
    ins, outs = [], []
    for count, getcaps, Caps, out in ((winmm.waveInGetNumDevs, winmm.waveInGetDevCapsW, WAVEINCAPSW, ins),
                                      (winmm.waveOutGetNumDevs, winmm.waveOutGetDevCapsW, WAVEOUTCAPSW, outs)):
        for i in range(int(count())):
            caps = Caps()
            if getcaps(ctypes.c_size_t(i), ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                out.append((caps.szPname, int(caps.wChannels)))
    return tuple(ins), tuple(outs)


class DeviceWatcher(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, parent=None, interval_ms: int = 2000, signature=windows_device_signature):
        super().__init__(parent)
        self.mode = "aus"
        self._signature = signature
        self._last = None
        self._timer = None
        self._media = None
        try:
            self._last = signature()
        except Exception as e:      # noqa: BLE001
            log.info("Windows-Geräteabfrage nicht möglich: %s", e)
            self._last = None
        if self._last is not None:
            self._timer = QtCore.QTimer(self)
            self._timer.setInterval(interval_ms)
            self._timer.timeout.connect(self._poll)
            self._timer.start()
            self.mode = "Windows-Geräteabfrage"
            return
        try:
            from PySide6.QtMultimedia import QMediaDevices
            self._media = QMediaDevices(self)
            self._media.audioInputsChanged.connect(self.changed)
            self._media.audioOutputsChanged.connect(self.changed)
            self.mode = "QtMultimedia"
        except Exception as e:      # noqa: BLE001
            log.info("Geräteüberwachung nicht verfügbar (%s) – ↻ liest die Liste neu ein", e)

    def _poll(self):
        try:
            sig = self._signature()
        except Exception:           # noqa: BLE001
            return
        if sig != self._last:
            self._last = sig
            self.changed.emit()
