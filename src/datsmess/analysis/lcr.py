"""Bauteile-Messung (FB-01 … FB-03): Kondensator, Spule, Widerstand."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

KIND_LABELS = {"auto": "Automatisch", "C": "Kondensator", "L": "Spule", "R": "Widerstand"}


@dataclass
class LCRResult:
    kind: str                       # "C", "L" oder "R"
    f_test: float
    values: dict = field(default_factory=dict)   # Name -> formatierter Wert
    raw: dict = field(default_factory=dict)      # Name -> Zahlenwert (SI)

    def summary(self) -> str:
        return ", ".join(f"{k} = {v}" for k, v in self.values.items())


def _eng(value: float, unit: str) -> str:
    if value == 0 or not np.isfinite(value):
        return f"{value:g} {unit}"
    prefixes = [(1e-12, "p"), (1e-9, "n"), (1e-6, "µ"), (1e-3, "m"), (1.0, ""), (1e3, "k"), (1e6, "M")]
    a = abs(value)
    scale, p = prefixes[0]
    for s, pre in prefixes:
        if a >= s:
            scale, p = s, pre
    return f"{value / scale:.4g} {p}{unit}"


def _at(f: np.ndarray, Z: np.ndarray, f0: float, rel_bw: float = 0.03) -> complex:
    m = (f >= f0 * (1 - rel_bw)) & (f <= f0 * (1 + rel_bw))
    if m.sum() < 1:
        return complex(np.interp(f0, f, Z.real), np.interp(f0, f, Z.imag))
    return complex(np.median(Z[m].real), np.median(Z[m].imag))


def detect_kind(f: np.ndarray, Z: np.ndarray) -> str:
    z = _at(f, Z, 1000.0)
    ph = np.degrees(np.angle(z))
    if ph < -20:
        return "C"
    if ph > 20:
        return "L"
    # schwach induktive Spulen: Phase steigt mit der Frequenz deutlich
    z10 = _at(f, Z, 10000.0)
    if np.degrees(np.angle(z10)) > 30:
        return "L"
    return "R"


def _auto_test_frequency(f: np.ndarray, Z: np.ndarray, kind: str, r_ref: float) -> float:
    """Wählt die Messfrequenz so, dass |Z| möglichst nahe am Referenzwiderstand liegt
    (beste Empfindlichkeit), beschränkt auf übliche Normfrequenzen."""
    candidates = np.array([100.0, 120.0, 1000.0, 10000.0])
    candidates = candidates[(candidates >= f[0]) & (candidates <= f[-1])]
    if kind == "R" or len(candidates) == 0:
        return 1000.0
    mags = np.array([abs(_at(f, Z, c)) for c in candidates])
    return float(candidates[np.argmin(np.abs(np.log(mags / r_ref)))])


def analyze(f: np.ndarray, Z: np.ndarray, kind: str = "auto", f_test: float | None = None,
            r_ref: float = 100.0) -> LCRResult:
    f = np.asarray(f, float)
    Z = np.asarray(Z, complex)
    if kind == "auto":
        kind = detect_kind(f, Z)
    if not f_test:
        f_test = _auto_test_frequency(f, Z, kind, r_ref)
    w = 2 * np.pi * f_test
    z = _at(f, Z, f_test)
    res = LCRResult(kind=kind, f_test=f_test)

    if kind == "C":
        C = -1.0 / (w * z.imag) if z.imag < 0 else float("nan")
        esr = z.real
        df = esr * w * C
        res.values = {"C": _eng(C, "F"), "ESR": _eng(esr, "Ω"), "DF": f"{df:.4f}",
                      "Q": f"{(1 / df if df > 0 else float('inf')):.1f}", "|Z|": _eng(abs(z), "Ω")}
        res.raw = {"C": C, "ESR": esr, "DF": df}
    elif kind == "L":
        L = z.imag / w
        lo = (f >= max(f[0], 10.0)) & (f <= 40.0)
        dcr = float(np.median(Z[lo].real)) if lo.any() else float(Z.real[0])
        q = w * L / z.real if z.real > 0 else float("inf")
        res.values = {"L": _eng(L, "H"), "DCR": _eng(dcr, "Ω"), "R(f)": _eng(z.real, "Ω"), "Q": f"{q:.2f}"}
        res.raw = {"L": L, "DCR": dcr, "Q": q}
    else:
        band = (f >= 20.0) & (f <= 200.0)
        R = float(np.median(Z[band].real)) if band.any() else z.real
        z10 = _at(f, Z, 10000.0)
        Ls = z10.imag / (2 * np.pi * 10000.0)
        res.values = {"R": _eng(R, "Ω"), "Ls (10 kHz)": _eng(Ls, "H"), "|Z| 10 kHz": _eng(abs(z10), "Ω")}
        res.raw = {"R": R, "Ls": Ls}
    return res
