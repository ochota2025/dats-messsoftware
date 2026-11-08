"""Hinweis auf neue Versionen (GitHub) und „Was ist neu?“.

Die Versionsnummer steht in ``datsmess/__init__.py`` und wird bei jeder Veröffentlichung erhöht.
Zum Vergleich wird nur diese eine Datei vom GitHub-Projekt gelesen (keine Anmeldung, kein API-Limit
relevant); die Änderungen stehen in ``NEUERUNGEN.md`` im Projektordner.
"""
from __future__ import annotations

import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__

DEFAULT_REPO = "https://github.com/ochota2025/dats-messsoftware"
PROJECT_ROOT = Path(__file__).resolve().parents[2]      # editierbare Installation: Projektordner
CHANGELOG = "NEUERUNGEN.md"


def parse_version(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+(?:\.\d+)*)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def repo_url(root: Path = PROJECT_ROOT) -> str:
    """Adresse aus ``update-quelle.txt`` (wie die Update-Skripte), sonst das Standardprojekt."""
    try:
        for line in (root / "update-quelle.txt").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(("https://", "http://")):
                return line.rstrip("/").removesuffix(".git")
    except OSError:
        pass
    return DEFAULT_REPO


def raw_url(repo: str, path: str, branch: str = "main") -> str | None:
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)", repo)
    if not m:
        return None
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{branch}/{path}"


def _get(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": f"datsmess/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 – feste https-Adresse
        return r.read(512_000).decode("utf-8", errors="replace")


@dataclass
class RemoteInfo:
    version: str
    changes: str            # Abschnitte aus NEUERUNGEN.md, die neuer als die installierte Version sind


def fetch_remote(repo: str | None = None, timeout: float = 6.0) -> RemoteInfo:
    repo = repo or repo_url()
    url = raw_url(repo, "src/datsmess/__init__.py")
    if url is None:
        raise ValueError(f"Keine GitHub-Adresse: {repo}")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)', _get(url, timeout))
    if not m:
        raise ValueError("Versionsnummer auf GitHub nicht gefunden.")
    changes = ""
    try:
        changes = sections_newer_than(_get(raw_url(repo, CHANGELOG), timeout), __version__)
    except Exception:       # noqa: BLE001 – Änderungsliste ist optional
        pass
    return RemoteInfo(m.group(1), changes)


def split_sections(md: str) -> list[tuple[str, str]]:
    """``## 0.2.0 – Datum`` → [(Überschrift, Inhalt), …] in Dateireihenfolge."""
    out, head, body = [], None, []
    for line in md.splitlines():
        if line.startswith("## "):
            if head is not None:
                out.append((head, "\n".join(body).strip()))
            head, body = line[3:].strip(), []
        elif head is not None:
            body.append(line)
    if head is not None:
        out.append((head, "\n".join(body).strip()))
    return out


def sections_newer_than(md: str, version: str) -> str:
    keep = [f"## {h}\n\n{b}" for h, b in split_sections(md) if is_newer(h, version)]
    return "\n\n".join(keep)


def local_changelog(root: Path = PROJECT_ROOT) -> str:
    try:
        return (root / CHANGELOG).read_text(encoding="utf-8")
    except OSError:
        return ""


def launch_updater(root: Path = PROJECT_ROOT) -> str | None:
    """Startet das Update-Skript in einem eigenen Fenster; es wartet, bis das Programm geschlossen
    ist, aktualisiert und startet das Programm neu. Rückgabe: Fehlermeldung oder ``None``."""
    try:
        if sys.platform == "win32":
            ps1 = root / "tools" / "update.ps1"
            if not ps1.exists():
                return f"{ps1} fehlt."
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
                              "-FromApp"], cwd=str(root), close_fds=True,
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            return None
        if sys.platform == "darwin":
            cmd = root / "Update-Mac.command"
            if not cmd.exists():
                return f"{cmd} fehlt."
            subprocess.Popen(["open", "-a", "Terminal", str(cmd)], close_fds=True)
            return None
        return "Automatisches Aktualisieren gibt es nur unter Windows und macOS."
    except OSError as e:
        return str(e)
