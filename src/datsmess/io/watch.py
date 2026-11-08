"""Watch-Folder-Übergabe an Frequenzweichen-Simulatoren (FS-03).

Programme wie VituixCAD überwachen geladene .zma-Dateien und lesen sie bei Änderung neu ein.
Die Übergabe schreibt deshalb immer unter gleichem Dateinamen und atomar (temporäre Datei +
Umbenennen), damit nie eine halb geschriebene Datei gelesen wird. R_e steht verlustfrei im
Kommentarkopf der .zma; optional wird eine .tsp-Datei mit allen T/S-Parametern daneben gelegt.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from ..measurement import Measurement
from .formats import atomic_write_text, zma_text
from .ts_export import DriverInfo


@dataclass
class WatchFolderConfig:
    path: str = ""
    auto: bool = False              # jede neue Messung automatisch übergeben
    with_tsp: bool = True           # .tsp-Datei mitliefern, falls T/S-Parameter vorliegen
    lossless: bool = True           # alle Messpunkte mit voller Genauigkeit
    points: int = 2000              # sonst: logarithmisches Raster
    smoothing: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WatchFolderConfig":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def safe_filename(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return s or "messung"


def deliver(cfg: WatchFolderConfig, m: Measurement, info: DriverInfo | None = None,
            tsp: str | None = None) -> list[Path]:
    if not cfg.path:
        raise ValueError("Kein Watch-Folder eingestellt.")
    folder = Path(cfg.path)
    if not folder.is_dir():
        raise ValueError(f"Watch-Folder existiert nicht: {folder}")
    base = safe_filename(m.name)
    header = [f"Name: {m.name}", f"Datum: {m.created}"]
    if info and info.title != "Treiber":
        header.append(f"Treiber: {info.title}")
    re_val = m.meta.get("Re")
    if re_val is not None:
        header.append(f"Re = {float(re_val)!r} Ohm")
    header.append(f"Kalibriert: {'ja' if m.meta.get('calibrated') else 'nein'}")
    if cfg.lossless:
        f, Z = m.f, m.Z
    else:
        f, Z = m.resampled(cfg.points, cfg.smoothing)
    files = [folder / f"{base}.zma"]
    atomic_write_text(files[0], zma_text(f, Z, header, lossless=cfg.lossless))
    if cfg.with_tsp and tsp:
        files.append(folder / f"{base}.tsp")
        atomic_write_text(files[1], tsp)
    return files
