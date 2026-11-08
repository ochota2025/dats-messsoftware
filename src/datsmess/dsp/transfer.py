"""Übertragungsfunktion, Laufzeitschätzung und logarithmisches Resampling."""
from __future__ import annotations

import numpy as np


class CrossSpectrum:
    """Mittelt Kreuz- und Autospektren mehrerer Sweeps (H1-Schätzer)."""

    def __init__(self, nfft: int):
        self.nfft = nfft
        self.sxy = None
        self.sxx = None
        self.syy = None
        self.count = 0

    def add(self, ref: np.ndarray, meas: np.ndarray) -> None:
        X = np.fft.rfft(ref, self.nfft)
        Y = np.fft.rfft(meas, self.nfft)
        sxy = Y * np.conj(X)
        sxx = (X * np.conj(X)).real
        syy = (Y * np.conj(Y)).real
        if self.sxy is None:
            self.sxy, self.sxx, self.syy = sxy, sxx, syy
        else:
            self.sxy = self.sxy + sxy
            self.sxx = self.sxx + sxx
            self.syy = self.syy + syy
        self.count += 1

    def transfer(self) -> np.ndarray:
        reg = 1e-14 * float(np.max(self.sxx))
        return self.sxy / (self.sxx + reg)

    def coherence(self) -> np.ndarray:
        """Betragsquadrat-Kohärenz (nur bei ≥ 2 Mittelungen aussagekräftig)."""
        den = self.sxx * self.syy
        return np.abs(self.sxy) ** 2 / np.where(den > 0, den, np.inf)


def estimate_delay(ref: np.ndarray, rec: np.ndarray) -> int:
    """Ganzzahlige Verzögerung von ``rec`` gegenüber ``ref`` (Samples, ≥ 0)."""
    n = 1 << int(np.ceil(np.log2(len(ref) + len(rec))))
    xc = np.fft.irfft(np.fft.rfft(rec, n) * np.conj(np.fft.rfft(ref, n)), n)
    lag = int(np.argmax(np.abs(xc[: n // 2])))
    return lag


def shift(x: np.ndarray, delay: int) -> np.ndarray:
    out = np.zeros_like(x)
    if delay <= 0:
        return x.copy()
    out[delay:] = x[:-delay]
    return out


def log_grid(f_lo: float, f_hi: float, n: int) -> np.ndarray:
    return np.geomspace(f_lo, f_hi, n)


def resample_log(f: np.ndarray, Z: np.ndarray, f_lo: float | None = None, f_hi: float | None = None,
                 n: int = 1000, octave_frac: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Komplexe Daten auf ein logarithmisches Raster bringen.

    Mit ``octave_frac`` (z. B. 24 für 1/24 Oktave) wird über ein Fenster
    konstanter relativer Bandbreite gemittelt; liegt im Fenster kein Bin,
    wird linear interpoliert.
    """
    f = np.asarray(f, float)
    Z = np.asarray(Z)
    f_lo = max(f_lo or f[0], f[0])
    f_hi = min(f_hi or f[-1], f[-1])
    fo = log_grid(f_lo, f_hi, n)
    zi = np.interp(fo, f, Z.real) + 1j * np.interp(fo, f, Z.imag) if np.iscomplexobj(Z) else np.interp(fo, f, Z)
    if not octave_frac:
        return fo, zi
    half = 2.0 ** (1.0 / (2.0 * octave_frac))
    lo_idx = np.searchsorted(f, fo / half, side="left")
    hi_idx = np.searchsorted(f, fo * half, side="right")
    csum = np.concatenate(([0.0], np.cumsum(Z)))
    cnt = hi_idx - lo_idx
    avg = np.where(cnt > 0, (csum[hi_idx] - csum[lo_idx]) / np.maximum(cnt, 1), zi)
    return fo, avg


def smooth_octave(f: np.ndarray, Z: np.ndarray, octave_frac: float) -> np.ndarray:
    """Glättung auf dem Originalraster (konstante relative Bandbreite)."""
    half = 2.0 ** (1.0 / (2.0 * octave_frac))
    lo_idx = np.searchsorted(f, f / half, side="left")
    hi_idx = np.searchsorted(f, f * half, side="right")
    csum = np.concatenate(([0.0], np.cumsum(Z)))
    cnt = np.maximum(hi_idx - lo_idx, 1)
    return (csum[hi_idx] - csum[lo_idx]) / cnt
