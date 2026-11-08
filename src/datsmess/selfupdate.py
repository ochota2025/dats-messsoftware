"""Selbst-Update ohne Konsolenfenster.

Ablauf (aus dem Programm heraus, siehe ``gui/update_dialog.py``):

1. neuesten Stand als ZIP von GitHub laden (über den Commit-SHA – nie veraltet)
2. entpacken und prüfen, ob es wirklich die DATS-Messsoftware ist
3. Dateien im Programmordner ersetzen – geht bei laufendem Programm, denn Python-Dateien werden
   nur beim Import gelesen und nicht gesperrt; die Python-Umgebung ``.venv`` bleibt unberührt
4. nur wenn sich die Bibliotheksliste in ``pyproject.toml`` geändert hat: ``pip install -e .``
   unsichtbar im Hintergrund
5. Programm neu starten (der neue Prozess wartet, bis der alte beendet ist)

Schlägt etwas fehl, bleibt die laufende Version unverändert in Betrieb; ``Update-Windows.bat`` bzw.
``Update-Mac.command`` bleiben als Notlösung.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .updates import PROJECT_ROOT, latest_commit, repo_url

log = logging.getLogger("datsmess")

EDITABLE_FLAG = Path(".venv") / "datsmess-editable.flag"


class UpdateError(Exception):
    pass


def can_self_update(root: Path = PROJECT_ROOT) -> bool:
    """Nur bei der normalen Installation (Programmordner mit Start-/Update-Dateien)."""
    return (root / "pyproject.toml").exists() and (root / "src" / "datsmess").is_dir() and \
        (root / "update-quelle.txt").exists()


def archive_url(repo: str, ref: str) -> str:
    return f"{repo.rstrip('/')}/archive/{ref}.zip" if ref != "main" else f"{repo.rstrip('/')}/archive/refs/heads/main.zip"


def download(url: str, progress=None, timeout: float = 30.0) -> bytes:
    """ZIP laden; ``progress(geladen, gesamt_oder_0)``."""
    req = urllib.request.Request(url, headers={"User-Agent": f"datsmess/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:        # noqa: S310 – feste https-Adresse
        total = int(r.headers.get("Content-Length") or 0)
        buf, done = io.BytesIO(), 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            buf.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return buf.getvalue()


def _deps_fingerprint(pyproject: str) -> str:
    """Alles aus pyproject.toml, was eine Neuinstallation nötig macht – ohne die Versionsnummer."""
    try:
        import tomllib
        d = tomllib.loads(pyproject)
        proj = d.get("project", {})
        key = repr((d.get("build-system"), proj.get("dependencies"), proj.get("optional-dependencies"),
                    proj.get("scripts"), proj.get("requires-python"), d.get("tool", {}).get("setuptools")))
    except Exception:       # noqa: BLE001 – Python 3.10 ohne tomllib: Datei ohne Versionszeile
        key = re.sub(r"(?m)^version\s*=.*$", "", pyproject)
    return hashlib.sha256(key.encode()).hexdigest()


def extract(data: bytes, dest: Path) -> Path:
    """Entpacken; liefert den Projektordner im Archiv und prüft, dass es die DATS-Messsoftware ist."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(dest)
    except zipfile.BadZipFile as e:
        raise UpdateError("Der Download ist keine gültige ZIP-Datei.") from e
    dirs = [p for p in dest.iterdir() if p.is_dir()]
    src = dirs[0] if len(dirs) == 1 else dest
    init = src / "src" / "datsmess" / "__init__.py"
    if not init.exists() or not (src / "pyproject.toml").exists():
        raise UpdateError("Das Archiv enthält nicht die DATS-Messsoftware.")
    return src


def new_version(src: Path) -> str:
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)', (src / "src" / "datsmess" / "__init__.py").read_text("utf-8"))
    return m.group(1) if m else "?"


def copy_tree(src: Path, root: Path, progress=None) -> int:
    """Dateien ersetzen (je Datei atomar über eine Zwischendatei). Nichts wird gelöscht."""
    files = [p for p in src.rglob("*") if p.is_file()]
    failed = []
    for i, f in enumerate(files, start=1):
        rel = f.relative_to(src)
        if rel.parts and rel.parts[0] in (".venv", ".git"):
            continue
        target = root / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".neu")
            shutil.copy2(f, tmp)
            os.replace(tmp, target)
        except OSError as e:
            failed.append(f"{rel}: {e}")
        if progress:
            progress(i, len(files))
    if failed:
        raise UpdateError("Einige Dateien konnten nicht ersetzt werden:\n" + "\n".join(failed[:8]))
    return len(files)


def console_python() -> str:
    """python.exe statt pythonw.exe (pip braucht eine Konsole – die bleibt aber unsichtbar)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.with_name("python.exe")).exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def _no_window() -> dict:
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def reinstall(root: Path, timeout: float = 900) -> None:
    """``pip install -e .`` unsichtbar; Ausgabe ins Protokoll."""
    cmd = [console_python(), "-m", "pip", "install", "--disable-pip-version-check", "-e", str(root)]
    log.info("Bibliotheken werden neu eingerichtet: %s", " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=timeout, **_no_window())
    log.info("pip: %s", (r.stdout or "")[-2000:])
    if r.returncode != 0:
        (root / EDITABLE_FLAG).unlink(missing_ok=True)      # Start-Datei richtet beim nächsten Start neu ein
        raise UpdateError("Die Bibliotheken konnten nicht eingerichtet werden. Beim nächsten Start über die "
                          "Start-Datei wird es erneut versucht.\n\n" + (r.stderr or "")[-800:])


@dataclass
class UpdateResult:
    version: str
    files: int
    reinstalled: bool


def run_update(root: Path = PROJECT_ROOT, progress=None, fetch=None) -> UpdateResult:
    """Gesamtablauf ohne GUI. ``progress(schritt, text, wert, gesamt)``; ``fetch()`` liefert die ZIP-Bytes
    (für Tests austauschbar)."""
    def step(name, text, value=0, total=0):
        if progress:
            progress(name, text, value, total)

    if not can_self_update(root):
        raise UpdateError("Automatisches Aktualisieren ist nur bei der Installation über die Start-Datei möglich.")
    if fetch is None:
        repo = repo_url(root)
        ref = latest_commit(repo) or "main"
        url = archive_url(repo, ref)
        log.info("Selbst-Update: lade %s", url)

        def fetch():
            return download(url, lambda d, t: step("download", "Neue Version wird geladen …", d, t))
    step("download", "Neue Version wird geladen …")
    try:
        data = fetch()
    except UpdateError:
        raise
    except Exception as e:      # noqa: BLE001
        raise UpdateError(f"Download fehlgeschlagen ({type(e).__name__}: {e}). Internetverbindung prüfen.") from e
    old_fp = _deps_fingerprint((root / "pyproject.toml").read_text("utf-8"))
    with tempfile.TemporaryDirectory(prefix="datsmess-update-") as tmp:
        step("extract", "Wird entpackt …")
        src = extract(data, Path(tmp))
        version = new_version(src)
        step("copy", f"Version {version} wird eingespielt …")
        n = copy_tree(src, root, lambda i, t: step("copy", f"Version {version} wird eingespielt …", i, t))
    new_fp = _deps_fingerprint((root / "pyproject.toml").read_text("utf-8"))
    reinstalled = False
    if new_fp != old_fp:
        step("pip", "Bibliotheken werden aktualisiert … (kann ein paar Minuten dauern)")
        reinstall(root)
        reinstalled = True
    flag = root / EDITABLE_FLAG
    if flag.parent.is_dir():
        flag.write_text("ok\n")                  # Start-Datei soll nicht noch einmal neu einrichten
    log.info("Selbst-Update auf %s fertig (%d Dateien, Bibliotheken %s)", version, n,
             "neu eingerichtet" if reinstalled else "unverändert")
    return UpdateResult(version, n, reinstalled)


def restart(root: Path = PROJECT_ROOT) -> None:
    """Neuen Programmprozess starten (ohne Konsole); er wartet, bis dieser hier beendet ist."""
    cmd = [sys.executable, "-m", "datsmess", "--wait-pid", str(os.getpid())]
    kw = {"cwd": str(root), "close_fds": True}
    if sys.platform == "win32":
        kw["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0)
                               | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)


def wait_for_pid(pid: int, timeout: float = 15.0) -> None:
    """Beim Neustart: warten, bis der alte Programmprozess beendet ist."""
    if pid <= 0:
        return
    end = time.monotonic() + timeout
    if sys.platform == "win32":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x00100000, False, pid)       # SYNCHRONIZE
            if h:
                k.WaitForSingleObject(h, int(timeout * 1000))
                k.CloseHandle(h)
            return
        except Exception:   # noqa: BLE001
            return
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.1)
