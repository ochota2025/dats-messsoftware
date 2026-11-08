"""Impedanzkorrektur: Zobel-Glied (gegen den Anstieg durch die Schwingspuleninduktivität) und
Saugkreis (gegen die Resonanzspitze). Ergebnis ist die Impedanz, die eine Frequenzweiche „sieht“.

Saugkreis (Serien-RLC parallel zum Treiber), klassische Formeln aus den T/S-Parametern::

    R = Re + Re·Qes/Qms      L = Qes·Re / (2π·fs)      C = 1 / (2π·fs·Qes·Re)

Zobel (Serien-RC parallel zum Treiber): Startwerte R = Re, C = Le/Re², danach numerische
Optimierung auf möglichst flachen Verlauf im Hochtonbereich.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from .ts import ImpedanceFit

E12 = (1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2)
E24 = (1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1,
       5.6, 6.2, 6.8, 7.5, 8.2, 9.1)


def nearest_e(value: float, series=E12) -> float:
    if value <= 0 or not np.isfinite(value):
        return value
    exp = np.floor(np.log10(value))
    cands = [m * 10 ** e for e in (exp - 1, exp, exp + 1) for m in series]
    return float(min(cands, key=lambda c: abs(np.log(c / value))))


def zobel_impedance(f: np.ndarray, R: float, C: float) -> np.ndarray:
    w = 2 * np.pi * np.asarray(f, float)
    return R + 1 / (1j * w * C)


def notch_impedance(f: np.ndarray, R: float, L: float, C: float) -> np.ndarray:
    w = 2 * np.pi * np.asarray(f, float)
    return R + 1j * w * L + 1 / (1j * w * C)


def parallel(*zs: np.ndarray) -> np.ndarray:
    y = sum(1 / z for z in zs)
    return 1 / y


@dataclass
class Zobel:
    R: float
    C: float


@dataclass
class Notch:
    R: float
    L: float
    C: float


def notch_from_fit(fit: ImpedanceFit) -> Notch:
    re, fs, qes, qms = fit.Re, fit.fs, fit.Qes, fit.Qms
    return Notch(R=re + re * qes / qms, L=qes * re / (2 * np.pi * fs), C=1 / (2 * np.pi * fs * qes * re))


def zobel_start(fit: ImpedanceFit, f_ref: float = 2000.0) -> Zobel:
    le = max(fit.le_at(f_ref), 1e-6)
    return Zobel(R=fit.Re, C=le / fit.Re ** 2)


def optimize_zobel(f: np.ndarray, Z: np.ndarray, fit: ImpedanceFit, f_lo: float | None = None,
                   f_hi: float = 20000.0) -> Zobel:
    """R und C so wählen, dass |Z ∥ Zobel| oberhalb der Resonanz möglichst konstant ≈ R ist."""
    start = zobel_start(fit)
    f = np.asarray(f, float)
    lo = f_lo or max(5 * fit.fs, 300.0)
    m = (f >= lo) & (f <= min(f_hi, f[-1]))
    if m.sum() < 10:
        return start
    idx = np.unique(np.geomspace(1, m.sum(), 300).astype(int) - 1)
    fm, zm = f[m][idx], np.asarray(Z)[m][idx]

    def cost(p):
        R, C = start.R * np.exp(p[0]), start.C * np.exp(p[1])
        zt = parallel(zm, zobel_impedance(fm, R, C))
        return float(np.mean(np.log(np.abs(zt) / R) ** 2))

    res = minimize(cost, [0.0, 0.0], method="Nelder-Mead",
                   options={"xatol": 1e-4, "fatol": 1e-9, "maxiter": 600})
    p = np.clip(res.x, [np.log(0.7), np.log(0.05)], [np.log(1.8), np.log(20)])
    return Zobel(R=float(start.R * np.exp(p[0])), C=float(start.C * np.exp(p[1])))


def corrected(f: np.ndarray, Z: np.ndarray, zobel: Zobel | None, notch: Notch | None) -> np.ndarray:
    parts = [np.asarray(Z, complex)]
    if zobel is not None:
        parts.append(zobel_impedance(f, zobel.R, zobel.C))
    if notch is not None:
        parts.append(notch_impedance(f, notch.R, notch.L, notch.C))
    return parallel(*parts) if len(parts) > 1 else parts[0]


def magnitude_range(f: np.ndarray, Z: np.ndarray, lo: float = 20.0, hi: float = 20000.0) -> tuple[float, float]:
    m = (np.asarray(f) >= lo) & (np.asarray(f) <= hi)
    mag = np.abs(np.asarray(Z)[m])
    return (float(mag.min()), float(mag.max())) if m.any() else (float("nan"), float("nan"))
