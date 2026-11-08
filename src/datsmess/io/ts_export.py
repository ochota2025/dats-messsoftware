"""T/S-Parameter-Export (FS-02): strukturierte Datei (.tsp/.ini) und Exportprofile.

Die nativen Treiberdateien von WinISD, VituixCAD, Boxsim, LEAP und AJ-Horn sind nicht
öffentlich spezifiziert. Die Profile liefern deshalb die Werte in Reihenfolge, Bezeichnung
und Einheiten der jeweiligen Eingabemaske – zum Einfügen aus der Zwischenablage (tabulator-
getrennt: Feld, Wert, Einheit) oder als Textdatei. Gerundete Werte werden konsistent
gehalten: Qts wird aus den *gerundeten* Qms/Qes berechnet (WinISD prüft das auf 1/1000).
"""
from __future__ import annotations

import configparser
import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..analysis.ts import TSParameters, VAS_METHOD_LABELS
from .formats import atomic_write_text


@dataclass
class DriverInfo:
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    notes: str = ""

    @property
    def title(self) -> str:
        return " ".join(s for s in (self.manufacturer, self.model) if s) or "Treiber"


def ts_values(ts: TSParameters, xmax: float | None = None) -> dict[str, float]:
    """Alle verfügbaren Werte in SI-Einheiten."""
    f = ts.fit
    z1k, z10k = (abs(z) for z in f.model(np.array([1000.0, 10000.0])))
    v = {"fs": f.fs, "Re": f.Re, "Qms": f.Qms, "Qes": f.Qes, "Qts": f.Qts, "Le": f.le_at(1000.0),
         "Le10k": f.le_at(10000.0), "Zmax": f.Zmax, "Z1k": float(z1k), "Z10k": float(z10k),
         "Kr": f.Kr, "Xr": f.Xr, "Ki": f.Ki, "Xi": f.Xi, "EBP": f.fs / f.Qes}
    for k in ("Sd", "Vas", "Mms", "Mmd", "Cms", "Rms", "Bl", "eta0", "SPL_1W", "SPL_283", "Vd"):
        val = getattr(ts, k)
        if val is not None:
            v[k] = float(val)
    if xmax:
        v["Xmax"] = xmax
    return v


# (Feldname im Zielprogramm, Schlüssel, Einheit, Faktor SI→Einheit, Nachkommastellen)
Field = tuple[str, str, str, float, int]


@dataclass
class Profile:
    key: str
    name: str
    fields: list[Field]
    hint: str = ""
    ext: str = ".txt"


_PROFILES = [
    Profile("winisd", "WinISD", [
        ("Fs", "fs", "Hz", 1, 2), ("Qms", "Qms", "", 1, 3), ("Qes", "Qes", "", 1, 3),
        ("Qts", "Qts", "", 1, 3), ("Vas", "Vas", "l", 1e3, 2), ("Re", "Re", "Ω", 1, 3),
        ("Le", "Le", "mH", 1e3, 3), ("Sd", "Sd", "cm²", 1e4, 1), ("Xmax", "Xmax", "mm", 1e3, 2),
    ], "Reihenfolge Qes, Qms, Fs, Vas, Re, Le, Sd, Xmax eingeben – Qts, Mms, Cms und Bl "
       "berechnet WinISD selbst (vermeidet Konsistenzwarnungen)."),
    Profile("vituixcad", "VituixCAD (Enclosure)", [
        ("Re", "Re", "Ω", 1, 3), ("fs", "fs", "Hz", 1, 2), ("Qms", "Qms", "", 1, 3),
        ("Qes", "Qes", "", 1, 3), ("Qts", "Qts", "", 1, 3), ("Vas", "Vas", "l", 1e3, 2),
        ("Sd", "Sd", "cm²", 1e4, 1), ("Le", "Le", "mH", 1e3, 3), ("Mms", "Mms", "g", 1e3, 2),
        ("Bl", "Bl", "Tm", 1, 3), ("Xmax", "Xmax", "mm", 1e3, 2),
        ("Z1k", "Z1k", "Ω", 1, 2), ("Z10k", "Z10k", "Ω", 1, 2),
    ], "Impedanzkurve für die Frequenzweiche als .zma übergeben (Watch-Folder)."),
    Profile("boxsim", "Boxsim", [
        ("fs", "fs", "Hz", 1, 2), ("Qms", "Qms", "", 1, 3), ("Qes", "Qes", "", 1, 3),
        ("Qts", "Qts", "", 1, 3), ("Vas", "Vas", "l", 1e3, 2), ("Re", "Re", "Ω", 1, 3),
        ("Le", "Le", "mH", 1e3, 3), ("Sd", "Sd", "cm²", 1e4, 1), ("Mms", "Mms", "g", 1e3, 2),
        ("Bl", "Bl", "Tm", 1, 3), ("Xmax", "Xmax", "mm", 1e3, 2),
    ], "Impedanzkurve zusätzlich als .zma importieren."),
    Profile("leap", "LEAP", [
        ("Re", "Re", "Ω", 1, 3), ("Le", "Le", "mH", 1e3, 3), ("Fs", "fs", "Hz", 1, 2),
        ("Qms", "Qms", "", 1, 3), ("Qes", "Qes", "", 1, 3), ("Qts", "Qts", "", 1, 3),
        ("Vas", "Vas", "l", 1e3, 2), ("Sd", "Sd", "cm²", 1e4, 1), ("Bl", "Bl", "Tm", 1, 3),
        ("Mms", "Mms", "g", 1e3, 2), ("Cms", "Cms", "mm/N", 1e3, 4), ("Rms", "Rms", "kg/s", 1, 3),
        ("Xmax", "Xmax", "mm", 1e3, 2),
    ], "Für das Schwingspulenmodell zusätzlich die Wright-Werte aus der .tsp-Datei nutzen."),
    Profile("ajhorn", "AJ-Horn", [
        ("Fs", "fs", "Hz", 1, 2), ("Qms", "Qms", "", 1, 3), ("Qes", "Qes", "", 1, 3),
        ("Qts", "Qts", "", 1, 3), ("Vas", "Vas", "l", 1e3, 2), ("Re", "Re", "Ω", 1, 3),
        ("Le", "Le", "mH", 1e3, 3), ("Sd", "Sd", "cm²", 1e4, 1), ("Mms", "Mms", "g", 1e3, 2),
        ("Bl", "Bl", "Tm", 1, 3), ("Xmax", "Xmax", "mm", 1e3, 2),
    ]),
]
PROFILES = {p.key: p for p in _PROFILES}


def _rounded(values: dict[str, float], fields: list[Field]) -> list[tuple[str, str, str]]:
    """Formatiert Felder; Qts wird aus den gerundeten Qms/Qes neu berechnet."""
    dec = {k: d for _l, k, _u, _s, d in fields}
    r = {k: round(values[k] * s, d) for _l, k, _u, s, d in fields if k in values}
    if "Qts" in r and "Qms" in values and "Qes" in values:
        qms = round(values["Qms"], dec.get("Qms", 3))
        qes = round(values["Qes"], dec.get("Qes", 3))
        r["Qts"] = round(qms * qes / (qms + qes), dec["Qts"])
    out = []
    for label, k, unit, _s, d in fields:
        if k in r:
            out.append((label, f"{r[k]:.{d}f}", unit))
    return out


def profile_text(profile_key: str, ts: TSParameters, info: DriverInfo, xmax: float | None = None,
                 with_header: bool = True) -> str:
    p = PROFILES[profile_key]
    rows = _rounded(ts_values(ts, xmax), p.fields)
    lines = []
    if with_header:
        lines.append(f"# {info.title} – T/S-Parameter für {p.name}")
        if p.hint:
            lines.append(f"# Hinweis: {p.hint}")
    lines += [f"{label}\t{val}\t{unit}" for label, val, unit in rows]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Strukturierte Datei (.tsp / .ini)
# --------------------------------------------------------------------------

TSP_FIELDS: list[Field] = [
    ("fs", "fs", "Hz", 1, 3), ("Re", "Re", "Ohm", 1, 4), ("Qms", "Qms", "", 1, 4),
    ("Qes", "Qes", "", 1, 4), ("Qts", "Qts", "", 1, 4), ("Vas", "Vas", "l", 1e3, 3),
    ("Sd", "Sd", "cm2", 1e4, 2), ("Mms", "Mms", "g", 1e3, 3), ("Mmd", "Mmd", "g", 1e3, 3),
    ("Cms", "Cms", "mm/N", 1e3, 5), ("Rms", "Rms", "kg/s", 1, 4), ("Bl", "Bl", "Tm", 1, 4),
    ("Le", "Le", "mH", 1e3, 4), ("Le10k", "Le10k", "mH", 1e3, 4), ("Zmax", "Zmax", "Ohm", 1, 3),
    ("Z1k", "Z1k", "Ohm", 1, 3), ("Z10k", "Z10k", "Ohm", 1, 3), ("eta0", "eta0", "%", 100, 4),
    ("SPL_1W", "SPL_1W", "dB", 1, 2), ("SPL_2.83V", "SPL_283", "dB", 1, 2), ("EBP", "EBP", "", 1, 2),
    ("Xmax", "Xmax", "mm", 1e3, 2), ("Vd", "Vd", "cm3", 1e6, 2),
    ("Kr", "Kr", "Ohm*s^Xr", 1, 8), ("Xr", "Xr", "", 1, 5), ("Ki", "Ki", "Ohm*s^Xi", 1, 8),
    ("Xi", "Xi", "", 1, 5),
]


def tsp_text(ts: TSParameters, info: DriverInfo, xmax: float | None = None,
             measurement_name: str = "", app_version: str = "") -> str:
    vals = ts_values(ts, xmax)
    rows = _rounded(vals, TSP_FIELDS)
    notes = info.notes.replace("\r", "").replace("\n", "\\n")
    lines = ["; T/S-Parameterdatei der DATS-Messsoftware",
             "; Werte in [Parameters], zugehörige Einheiten in [Units]; Qts aus gerundeten Qms/Qes.",
             "", "[Driver]",
             f"Manufacturer={info.manufacturer}", f"Model={info.model}", f"Serial={info.serial}",
             f"Notes={notes}", "",
             "[Measurement]",
             f"Date={_dt.datetime.now().isoformat(timespec='seconds')}",
             f"Source={measurement_name}",
             f"VasMethod={ts.method.value}",
             f"VasMethodLabel={VAS_METHOD_LABELS[ts.method]}",
             f"FitError_percent={ts.fit.rms_error * 100:.3f}",
             f"FitRange_Hz={ts.fit.f_range[0]:.1f}-{ts.fit.f_range[1]:.1f}",
             f"Software=DATS-Messsoftware {app_version}".rstrip(), "",
             "[Parameters]"]
    lines += [f"{label}={val}" for label, val, _u in rows]
    lines += ["", "[Units]"]
    lines += [f"{label}={unit}" for label, _v, unit in rows]
    return "\n".join(lines) + "\n"


def read_tsp(path: str | Path) -> dict[str, dict[str, str]]:
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(path, encoding="utf-8")
    return {s: dict(cp[s]) for s in cp.sections()}


def save_text(path: str | Path, text: str) -> None:
    atomic_write_text(Path(path), text)
