"""Paarabgleich: Treiber-Exemplare vergleichen und die am besten passenden Paare finden."""
from __future__ import annotations

from itertools import combinations

import numpy as np

from ..dsp.transfer import resample_log
from .ts import ImpedanceFit

# (Schlüssel, Anzeigename, Einheit, Format)
PARAMS = [
    ("fs", "fs", "Hz", "{:.2f}"),
    ("Re", "Re", "Ω", "{:.3f}"),
    ("Qms", "Qms", "", "{:.3f}"),
    ("Qes", "Qes", "", "{:.3f}"),
    ("Qts", "Qts", "", "{:.3f}"),
    ("Zmax", "Zmax", "Ω", "{:.1f}"),
    ("Le", "Le 1 kHz", "mH", "{:.3f}"),
]
DEFAULT_TOL = {"fs": 5.0, "Re": 3.0, "Qms": 10.0, "Qes": 5.0, "Qts": 5.0, "Zmax": 10.0, "Le": 10.0, "curve": 5.0}


def values(fit: ImpedanceFit) -> dict[str, float]:
    return {"fs": fit.fs, "Re": fit.Re, "Qms": fit.Qms, "Qes": fit.Qes, "Qts": fit.Qts, "Zmax": fit.Zmax,
            "Le": fit.le_at(1000.0) * 1e3}


def deviation_pct(a: float, ref: float) -> float:
    return 100.0 * (a - ref) / ref if ref else float("nan")


def curve_deviation(f_ref, Z_ref, f, Z, lo: float = 20.0, hi: float = 20000.0,
                    n: int = 400) -> tuple[np.ndarray, np.ndarray]:
    """Abweichung von |Z| gegenüber der Referenz in % auf gemeinsamem Log-Raster (1/12 Oktave geglättet)."""
    lo = max(lo, f_ref[0], f[0])
    hi = min(hi, f_ref[-1], f[-1])
    g, zr = resample_log(f_ref, Z_ref, lo, hi, n, octave_frac=12)
    _, z = resample_log(f, Z, lo, hi, n, octave_frac=12)
    return g, 100.0 * (np.abs(z) / np.abs(zr) - 1.0)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else float("nan")


def pair_score(a: dict, b: dict, tol: dict, curve_rms: float | None = None) -> float:
    """Größte Abweichung im Verhältnis zur Toleranz (≤ 1: alles innerhalb der Toleranz)."""
    worst = 0.0
    for k, _n, _u, _f in PARAMS:
        t = tol.get(k)
        if t:
            worst = max(worst, abs(deviation_pct(a[k], b[k])) / t)
    if curve_rms is not None and tol.get("curve"):
        worst = max(worst, curve_rms / tol["curve"])
    return worst


def best_pairs(items: list[tuple[str, dict, np.ndarray, np.ndarray]], tol: dict) -> list[tuple[int, int, float]]:
    """Gierige Paarbildung: kleinste Abweichung zuerst. ``items``: (Name, Werte, f, Z)."""
    scores = []
    for i, j in combinations(range(len(items)), 2):
        _, va, fa, za = items[i]
        _, vb, fb, zb = items[j]
        _, dev = curve_deviation(fa, za, fb, zb)
        scores.append((pair_score(va, vb, tol, rms(dev)), i, j))
    scores.sort()
    used, out = set(), []
    for s, i, j in scores:
        if i not in used and j not in used:
            out.append((i, j, s))
            used |= {i, j}
    return out
