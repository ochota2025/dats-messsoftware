"""Export/Import von Impedanzkurven (DM-01, FS-01).

* .zma / .frd – feste Spaltenfolge Frequenz [Hz], |Z| [Ω], Phase [°], durch Leerzeichen
  getrennt (kompatibel mit VituixCAD, PCD, WinISD, XSim, Boxsim …).
* .txt / .csv – frei konfigurierbar: Trennzeichen, Dezimaltrennzeichen, Einheiten, Spalten.
  Die Einheiten stehen in der Kopfzeile und werden beim Import wieder erkannt.
"""
from __future__ import annotations

import csv
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

FORMATS = {
    ".zma": "Impedanz ZMA (VituixCAD, PCD, WinISD, XSim …) (*.zma)",
    ".txt": "Text, Spalten (*.txt)",
    ".csv": "CSV, Spalten (*.csv)",
    ".frd": "FRD (Betrag/Phase, *.frd)",
}

DELIMITERS = {"tab": ("Tabulator", "\t"), "comma": ("Komma", ","), "semicolon": ("Semikolon", ";"),
              "space": ("Leerzeichen", " ")}
FREQ_UNITS = {"Hz": 1.0, "kHz": 1e-3}
IMP_UNITS = {"Ohm": 1.0, "mOhm": 1e3, "kOhm": 1e-3}
PHASE_UNITS = ("deg", "rad")
COLUMN_SETS = {"magphase": "Frequenz, |Z|, Phase", "reim": "Frequenz, Re, Im",
               "all": "Frequenz, |Z|, Phase, Re, Im"}


@dataclass
class TextExportOptions:
    delimiter: str = "tab"          # Schlüssel aus DELIMITERS
    decimal: str = "."              # "." oder ","
    freq_unit: str = "Hz"
    imp_unit: str = "Ohm"
    phase_unit: str = "deg"
    columns: str = "all"
    header: bool = True
    lossless: bool = False          # 17 signifikante Stellen statt gerundet

    def validate(self) -> None:
        if self.decimal == "," and self.delimiter == "comma":
            raise ValueError("Dezimalkomma und Komma als Trennzeichen schließen sich aus.")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TextExportOptions":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def _fmt(v: float, digits: int, lossless: bool, decimal: str) -> str:
    """``digits`` = signifikante Stellen (unabhängig von der gewählten Einheit)."""
    s = repr(float(v)) if lossless else f"{v:.{digits}g}"
    return s.replace(".", ",") if decimal == "," else s


def atomic_write_text(path: Path, text: str) -> None:
    """Schreibt zuerst eine temporäre Datei und benennt sie dann um – überwachende
    Programme (Watch-Folder) sehen so nie eine halb geschriebene Datei."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def zma_text(f: np.ndarray, Z: np.ndarray, header: list[str] | None = None, lossless: bool = False) -> str:
    mag, ph = np.abs(Z), np.degrees(np.angle(Z))
    lines = [f"* {h}" for h in header or []]
    lines.append("* Freq(Hz)  Impedance(Ohm)  Phase(Deg)")
    for a, b, c in zip(f, mag, ph):
        if lossless:
            lines.append(f"{float(a)!r} {float(b)!r} {float(c)!r}")
        else:
            lines.append(f"{a:.6f} {b:.6f} {c:.4f}")
    return "\n".join(lines) + "\n"


def table_text(f: np.ndarray, Z: np.ndarray, opt: TextExportOptions, header: list[str] | None = None,
               comment: str = "#") -> str:
    opt.validate()
    d = DELIMITERS[opt.delimiter][1]
    fs, zs = FREQ_UNITS[opt.freq_unit], IMP_UNITS[opt.imp_unit]
    ph = np.angle(Z) if opt.phase_unit == "rad" else np.degrees(np.angle(Z))
    cols = [("Freq[%s]" % opt.freq_unit, np.asarray(f) * fs, 9)]
    if opt.columns in ("magphase", "all"):
        cols += [(f"|Z|[{opt.imp_unit}]", np.abs(Z) * zs, 8), (f"Phase[{opt.phase_unit}]", ph, 7)]
    if opt.columns in ("reim", "all"):
        cols += [(f"Re[{opt.imp_unit}]", Z.real * zs, 8), (f"Im[{opt.imp_unit}]", Z.imag * zs, 8)]
    lines = []
    if opt.header:
        lines += [f"{comment} {h}" for h in header or []]
        lines.append(d.join(c[0] for c in cols))
    for i in range(len(f)):
        lines.append(d.join(_fmt(c[1][i], c[2], opt.lossless, opt.decimal) for c in cols))
    return "\n".join(lines) + "\n"


def export_impedance(path: str | Path, f: np.ndarray, Z: np.ndarray, header: list[str] | None = None,
                     options: TextExportOptions | None = None) -> None:
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".zma", ".frd"):
        text = zma_text(f, Z, header, lossless=bool(options and options.lossless))
    elif ext in (".txt", ".csv"):
        opt = options or (TextExportOptions(delimiter="comma") if ext == ".csv" else TextExportOptions())
        text = table_text(f, Z, opt, header)
    else:
        raise ValueError(f"Unbekanntes Exportformat: {ext}")
    atomic_write_text(path, text)


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------

def _units_from_header(h: str) -> tuple[float, float, bool, list[str]]:
    """Erkennt Einheiten aus einer Kopfzeile (Skalierung Frequenz, Impedanz, Phase in rad)."""
    cols = [c.strip().lower() for c in re.split(r"[\t;,]+|\s{2,}|\s(?=\S*\[)", h) if c.strip()]
    fscale = 1e3 if re.search(r"k\s*hz", h, re.I) else 1.0
    zscale = 1.0
    if re.search(r"m(?:[Oo]hm|Ω)", h):
        zscale = 1e-3
    elif re.search(r"k(?:[Oo]hm|Ω)", h):
        zscale = 1e3
    rad = bool(re.search(r"\brad\b|\[rad\]", h, re.I))
    return fscale, zscale, rad, cols


def import_impedance(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Liest Dateien mit (f, |Z|, Phase), (f, Re, Im) oder (f, |Z|, Phase, Re, Im).

    Kommentarzeilen (*, #, ;, ") werden übersprungen; Spaltenbedeutung und Einheiten
    werden – falls vorhanden – aus der Kopfzeile übernommen.
    """
    rows, header = [], ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s[0] in "*#;\"'":
                continue
            if s[0].isalpha() or s[0] in "|":
                header = s
                continue
            if re.search(r"[\s;]", s):
                parts = re.split(r"[\s;]+", s)          # Dezimalkomma erlaubt
            else:
                parts = s.split(",")                    # klassisches CSV
            try:
                vals = [float(p.replace(",", ".")) for p in parts if p]
            except ValueError:
                continue
            if len(vals) >= 2:
                rows.append(vals)
    if not rows:
        raise ValueError("Keine numerischen Daten gefunden.")
    fscale, zscale, rad, cols = _units_from_header(header) if header else (1.0, 1.0, False, [])
    ncol = min(len(r) for r in rows)
    a = np.array([r[:ncol] for r in rows])
    f = a[:, 0] * fscale
    reim_only = ncol == 3 and len(cols) >= 3 and cols[1].startswith("re")
    if ncol >= 5:
        Z = (a[:, 3] + 1j * a[:, 4]) * zscale
    elif reim_only:
        Z = (a[:, 1] + 1j * a[:, 2]) * zscale
    elif ncol >= 3:
        ph = a[:, 2] if rad else np.radians(a[:, 2])
        Z = a[:, 1] * zscale * np.exp(1j * ph)
    else:
        Z = (a[:, 1] * zscale).astype(complex)
    order = np.argsort(f)
    return f[order], Z[order]


def export_parameters(path: str | Path, rows: list[tuple], header: list[str] | None = None) -> None:
    """Einfache Parameterliste. rows: (Schlüssel, Bezeichnung, Wert, Einheit, Format)."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["key", "parameter", "value", "unit"])
            for key, label, val, unit, _fmt in rows:
                w.writerow([key, label, "" if val is None else f"{val:.6g}", unit])
    else:
        lines = [f"# {h}" for h in header or []]
        for key, label, val, unit, fmt in rows:
            v = "–" if val is None else fmt.format(val)
            lines.append(f"{label:<34} {v:>12} {unit}")
        atomic_write_text(path, "\n".join(lines) + "\n")
