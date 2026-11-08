"""Projektarchiv .datsproj (FS-04).

Container = ZIP (Deflate) mit:

    manifest.json                       Format/Version, Treiberinfo + Notizen, Einstellungen,
                                        Messungs-Metadaten, T/S-Eingaben und -Ergebnisse
    measurements/<id>/recordings.npy    Sweep-Rohaufnahmen (Mittelungen×Samples×Kanäle);
                                        int16, wenn die Werte exakt 16-Bit-Stufen sind, sonst float32
    measurements/<id>/Z.npy             Impedanz (complex128) – nur, falls nicht bitgenau aus
                                        Rohaufnahmen + Kalibrierung reproduzierbar (z. B. Import)
    measurements/<id>/f.npy             Frequenzraster – nur, falls nicht aus dem Sweep ableitbar
    measurements/<id>/H.npy             Übertragungsfunktion – nur ohne Rohaufnahmen
    calibrations/<id>/meta.json + <schritt>.npy   Kalibrierung als Rohaufnahmen, oder
    calibrations/<id>.npz               Kalibrierung als Übertragungsfunktionen

Verlustfreiheit: Abgeleitete Daten werden nur weggelassen, wenn beim Speichern geprüft wurde,
dass die Neuberechnung *bitgenau* dasselbe Ergebnis liefert. Beim Laden wird exakt so neu
berechnet; jede Messung ist damit vollständig reproduzierbar.
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .. import __version__
from ..dsp.calibration import Calibration
from ..dsp.sweep import SweepConfig
from ..measurement import ChannelConfig, Measurement, reprocess, transfer_from_recordings
from .ts_export import DriverInfo

FORMAT_NAME = "datsproj"
FORMAT_VERSION = 1
EXTENSION = ".datsproj"
CAL_STEPS = {"open": "H_open", "short": "H_short", "cal": "H_load"}


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


@dataclass
class Project:
    info: DriverInfo = field(default_factory=DriverInfo)
    measurements: list[Measurement] = field(default_factory=list)
    calibrations: dict[str, Calibration] = field(default_factory=dict)
    active_calibration_id: str | None = None
    ts: dict | None = None            # Eingaben, Messungs-IDs und Ergebnis-Zeilen des T/S-Tabs
    settings: dict = field(default_factory=dict)
    created: str = field(default_factory=_now)
    modified: str = ""

    def add_calibration(self, cal: Calibration | None) -> None:
        if cal is not None:
            self.calibrations[cal.id] = cal


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def _npy(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, np.asarray(arr), allow_pickle=False)
    return buf.getvalue()


def _load_npy(z: zipfile.ZipFile, name: str) -> np.ndarray:
    return np.load(io.BytesIO(z.read(name)), allow_pickle=False)


def _pack(rec: np.ndarray) -> tuple[np.ndarray, str]:
    """int16, falls verlustfrei möglich (Werte = k/32768), sonst float32."""
    rec = np.asarray(rec, dtype=np.float32)
    scaled = rec.astype(np.float64) * 32768.0
    ints = np.round(scaled)
    if np.array_equal(scaled, ints) and ints.min() >= -32768 and ints.max() <= 32767:
        return ints.astype(np.int16), "int16/32768"
    return rec, "float32"


def _unpack(arr: np.ndarray, enc: str) -> np.ndarray:
    if enc == "int16/32768":
        return arr.astype(np.float32) / np.float32(32768.0)
    return arr.astype(np.float32)


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def _cal_from_recordings(meta: dict, recs: dict[str, np.ndarray]) -> Calibration:
    sweep = SweepConfig.from_dict(meta["sweep"])
    ch = ChannelConfig.from_dict(meta["channels"])
    H = {CAL_STEPS[k]: transfer_from_recordings(r, sweep, ch).H for k, r in recs.items()}
    return Calibration(sweep=sweep, r_cal=float(meta["r_cal"]), f=sweep.frequencies(),
                       H_load=H["H_load"], H_open=H.get("H_open"), H_short=H.get("H_short"),
                       r_nominal=float(meta.get("r_nominal", 100.0)), device=meta.get("device", ""),
                       created=meta.get("created", ""), recordings=recs, channels=meta["channels"])


def _write_calibration(z: zipfile.ZipFile, cid: str, cal: Calibration) -> None:
    if cal.recordings and cal.channels and set(cal.recordings) >= {"cal"}:
        packed, encs = {}, {}
        for k, r in cal.recordings.items():
            packed[k], encs[k] = _pack(r)
        meta = {"sweep": cal.sweep.to_dict(), "channels": cal.channels, "r_cal": cal.r_cal,
                "r_nominal": cal.r_nominal, "device": cal.device, "created": cal.created,
                "steps": {k: encs[k] for k in packed}}
        rebuilt = _cal_from_recordings(meta, {k: _unpack(packed[k], encs[k]) for k in packed})
        same = all((getattr(cal, a) is None) == (getattr(rebuilt, a) is None) and
                   (getattr(cal, a) is None or np.array_equal(getattr(cal, a), getattr(rebuilt, a)))
                   for a in ("H_load", "H_open", "H_short"))
        if same:
            z.writestr(f"calibrations/{cid}/meta.json", json.dumps(_jsonable(meta), indent=2))
            for k, arr in packed.items():
                z.writestr(f"calibrations/{cid}/{k}.npy", _npy(arr))
            return
    buf = io.BytesIO()
    cal.save(buf)
    z.writestr(f"calibrations/{cid}.npz", buf.getvalue())


def _read_calibration(z: zipfile.ZipFile, cid: str, names: set[str]) -> Calibration:
    if f"calibrations/{cid}.npz" in names:
        return Calibration.load(io.BytesIO(z.read(f"calibrations/{cid}.npz")))
    meta = json.loads(z.read(f"calibrations/{cid}/meta.json"))
    recs = {k: _unpack(_load_npy(z, f"calibrations/{cid}/{k}.npy"), enc) for k, enc in meta["steps"].items()}
    return _cal_from_recordings(meta, recs)


# --------------------------------------------------------------------------
# Speichern / Laden
# --------------------------------------------------------------------------

def save_project(path: str | Path, project: Project) -> None:
    path = Path(path)
    project.modified = _now()
    entries: dict[str, bytes] = {}
    meas_meta = []
    for m in project.measurements:
        base = f"measurements/{m.id}/"
        mm = {"id": m.id, "name": m.name, "created": m.created, "color": m.color, "visible": m.visible,
              "meta": m.meta, "points": int(len(m.f)), "recordings_encoding": None,
              "f_from_sweep": False, "Z_from_raw": False}
        try:
            f_sweep = SweepConfig.from_dict(m.meta["sweep"]).frequencies()
            mm["f_from_sweep"] = f_sweep.shape == m.f.shape and bool(np.array_equal(f_sweep, m.f))
        except (KeyError, TypeError):
            pass
        if m.recordings is not None:
            packed, enc = _pack(m.recordings)
            mm["recordings_encoding"] = enc
            entries[base + "recordings.npy"] = _npy(packed)
            if m.has_raw and mm["f_from_sweep"]:
                trial = Measurement(m.name, m.f, m.Z, meta=m.meta, recordings=_unpack(packed, enc))
                cid = m.meta.get("calibration_id")
                cal = project.calibrations.get(cid) if cid else None
                if cid is None or cal is not None:
                    try:
                        mm["Z_from_raw"] = bool(np.array_equal(reprocess(trial, cal), m.Z))
                    except ValueError:
                        pass
        elif m.raw_H is not None:
            entries[base + "H.npy"] = _npy(m.raw_H)
        if not mm["f_from_sweep"]:
            entries[base + "f.npy"] = _npy(np.asarray(m.f, float))
        if not mm["Z_from_raw"]:
            entries[base + "Z.npy"] = _npy(np.asarray(m.Z, complex))
        meas_meta.append(mm)

    manifest = {
        "format": FORMAT_NAME, "version": FORMAT_VERSION, "software": f"DATS-Messsoftware {__version__}",
        "created": project.created, "modified": project.modified,
        "info": asdict(project.info), "settings": project.settings,
        "active_calibration_id": project.active_calibration_id,
        "calibrations": sorted(project.calibrations), "measurements": meas_meta, "ts": project.ts,
    }
    tmp = path.with_name(f".~{path.name}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr("manifest.json", json.dumps(_jsonable(manifest), indent=2, ensure_ascii=False))
            for name, data in entries.items():
                z.writestr(name, data)
            for cid, cal in project.calibrations.items():
                _write_calibration(z, cid, cal)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def load_project(path: str | Path) -> Project:
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != FORMAT_NAME:
            raise ValueError("Keine gültige .datsproj-Datei.")
        if int(manifest.get("version", 0)) > FORMAT_VERSION:
            raise ValueError("Projekt wurde mit einer neueren Programmversion gespeichert.")
        names = set(z.namelist())
        cals = {cid: _read_calibration(z, cid, names) for cid in manifest.get("calibrations", [])}
        meas = []
        for mm in manifest.get("measurements", []):
            base = f"measurements/{mm['id']}/"
            meta = mm.get("meta", {})
            f = SweepConfig.from_dict(meta["sweep"]).frequencies() if mm.get("f_from_sweep") \
                else _load_npy(z, base + "f.npy")
            m = Measurement(name=mm["name"], f=f, Z=np.zeros(len(f), complex), created=mm.get("created", ""),
                            meta=meta, color=mm.get("color"), visible=mm.get("visible", True), id=mm["id"])
            if base + "recordings.npy" in names:
                m.recordings = _unpack(_load_npy(z, base + "recordings.npy"), mm["recordings_encoding"])
                if m.has_raw:
                    m.raw_H = transfer_from_recordings(m.recordings, SweepConfig.from_dict(meta["sweep"]),
                                                       ChannelConfig.from_dict(meta["channels"])).H
            elif base + "H.npy" in names:
                m.raw_H = _load_npy(z, base + "H.npy")
            if mm.get("Z_from_raw"):
                cid = meta.get("calibration_id")
                m.Z = reprocess(m, cals[cid] if cid else None)
            else:
                m.Z = _load_npy(z, base + "Z.npy")
            meas.append(m)
    info = DriverInfo(**{k: v for k, v in manifest.get("info", {}).items() if k in DriverInfo.__dataclass_fields__})
    return Project(info=info, measurements=meas, calibrations=cals,
                   active_calibration_id=manifest.get("active_calibration_id"), ts=manifest.get("ts"),
                   settings=manifest.get("settings", {}), created=manifest.get("created", ""),
                   modified=manifest.get("modified", ""))
