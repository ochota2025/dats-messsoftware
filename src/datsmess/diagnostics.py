"""Fehlerprotokoll und Fehlerbericht.

* ``setup_logging`` schreibt ein Protokoll (``datsmess.log``, rotierend) in den
  Einstellungsordner und hängt ``faulthandler`` an, damit auch harte Abstürze
  (z. B. im Audiotreiber) eine Spur hinterlassen.
* ``build_report`` erzeugt einen Text, den Tester per Messenger schicken können:
  Version, System, Audio-Geräte, Einstellungen und die letzten Protokollzeilen.
  Persönliche Pfade (Benutzerordner) werden dabei durch ``~`` ersetzt.
"""
from __future__ import annotations

import datetime as _dt
import faulthandler
import logging
import logging.handlers
import platform
import sys
from pathlib import Path

from . import __version__

log = logging.getLogger("datsmess")

LOG_NAME = "datsmess.log"
_state: dict = {"path": None, "fault_file": None}


def setup_logging(folder: Path) -> Path:
    """Protokoll einrichten; liefert den Pfad der Protokolldatei."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LOG_NAME
    root = logging.getLogger("datsmess")
    if _state["path"] == path:
        return path
    for h in list(root.handlers):
        root.removeHandler(h)
    h = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    root.addHandler(h)
    root.setLevel(logging.INFO)
    root.propagate = False
    try:
        fh = open(folder / "absturz.log", "a", encoding="utf-8")     # noqa: SIM115 – bleibt offen
        faulthandler.enable(fh)
        _state["fault_file"] = fh
    except (OSError, ValueError, RuntimeError):
        pass
    _state["path"] = path
    log.info("Start DATS-Messsoftware %s (%s, Python %s)", __version__, system_text(), platform.python_version())
    return path


def log_path() -> Path | None:
    return _state["path"]


def anonymize(text: str) -> str:
    """Benutzerordner (enthält meist den Namen) durch ~ ersetzen."""
    home = str(Path.home())
    for variant in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
        if len(variant) > 3:
            text = text.replace(variant, "~")
    return text


def system_text() -> str:
    s = platform.system()
    if s == "Windows":
        rel, ver = platform.release(), platform.version()
        try:                                    # Windows 11 meldet sich als „10“ mit Build ≥ 22000
            if rel == "10" and int(ver.split(".")[-1]) >= 22000:
                rel = "11"
        except ValueError:
            pass
        return f"Windows {rel} ({ver}, {platform.machine()})"
    if s == "Darwin":
        return f"macOS {platform.mac_ver()[0]} ({platform.machine()})"
    return f"{s} {platform.release()} ({platform.machine()})"


def library_versions() -> str:
    parts = [f"Python {platform.python_version()}"]
    for mod, label in (("PySide6", "PySide6"), ("numpy", "NumPy"), ("scipy", "SciPy"), ("pyqtgraph", "pyqtgraph")):
        try:
            m = __import__(mod)
            parts.append(f"{label} {getattr(m, '__version__', '?')}")
        except Exception:                       # noqa: BLE001
            parts.append(f"{label} fehlt")
    try:
        from PySide6 import QtCore
        parts.append(f"Qt {QtCore.qVersion()}")
    except Exception:                           # noqa: BLE001
        pass
    try:
        import sounddevice as sd
        parts.append(f"sounddevice {sd.__version__} / {sd.get_portaudio_version()[1]}")
    except Exception as e:                      # noqa: BLE001
        parts.append(f"sounddevice nicht verfügbar ({type(e).__name__})")
    return ", ".join(parts)


def device_lines() -> list[str]:
    from .audio.backend import list_devices
    try:
        devs = list_devices()
    except Exception as e:                      # noqa: BLE001
        return [f"  Geräteliste nicht lesbar: {e}"]
    if not devs:
        return ["  (keine Audio-Geräte gefunden oder PortAudio fehlt)"]
    return [f"  [{d.index}] {'★ ' if d.looks_like_dats else ''}{d.name} ({d.hostapi}) – "
            f"{d.max_in} ein / {d.max_out} aus, {d.default_fs:g} Hz" for d in devs]


def tail(path: Path | None, n: int = 150) -> list[str]:
    if path is None or not Path(path).exists():
        return ["(kein Protokoll vorhanden)"]
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return [f"(Protokoll nicht lesbar: {e})"]
    return lines[-n:]


def build_report(context: dict[str, str] | None = None, error: str | None = None, n_log: int = 150) -> str:
    """Fehlerbericht als Klartext (ohne persönliche Pfade)."""
    now = _dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    out = ["DATS-Messsoftware – Fehlerbericht",
           "=================================",
           f"Version:   {__version__}",
           f"Erstellt:  {now}",
           f"System:    {system_text()}",
           f"Bibliotheken: {library_versions()}",
           ""]
    if error:
        out += ["Fehler:", error.rstrip(), ""]
    for k, v in (context or {}).items():
        v = str(v).rstrip()
        if "\n" in v:
            out += [f"{k}:", *("  " + line for line in v.splitlines())]
        else:
            out.append(f"{k}: {v}")
    out += ["", "Audio-Geräte:", *device_lines(), "",
            f"Protokoll (letzte {n_log} Zeilen):", "-" * 40, *tail(log_path(), n_log)]
    return anonymize("\n".join(out)) + "\n"
