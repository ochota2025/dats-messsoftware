"""Signalgenerator (FG-01): Testsignale für Wiedergabe über das Interface."""
from __future__ import annotations

import numpy as np
from scipy import signal as _sig

from .sweep import db_to_lin, exp_sweep

WAVEFORMS = {
    "sine": "Sinus",
    "square": "Rechteck",
    "triangle": "Dreieck",
    "sawtooth": "Sägezahn",
    "impulse": "Impuls",
    "pink": "Rosa Rauschen",
    "white": "Weißes Rauschen",
    "logsweep": "Log-Sweep",
}


def _pink(n: int, rng: np.random.Generator) -> np.ndarray:
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(X), dtype=float)
    f[0] = 1.0
    X /= np.sqrt(f)
    X[0] = 0.0
    return np.fft.irfft(X, n)


def generate(kind: str, freq: float, level_dbfs: float, duration: float, fs: int,
             f_end: float = 20000.0, seed: int | None = None) -> np.ndarray:
    """Erzeugt ``duration`` Sekunden des Signals, Spitzenwert = ``level_dbfs``.

    Bei periodischen Signalen wird die Länge auf ganze Perioden gerundet, damit
    eine Endlosschleife ohne Knackser abgespielt werden kann.
    """
    n = max(1, int(round(duration * fs)))
    rng = np.random.default_rng(seed)
    if kind in ("sine", "square", "triangle", "sawtooth", "impulse"):
        periods = max(1, int(round(duration * freq)))
        n = int(round(periods * fs / freq))
        t = np.arange(n) / fs
        ph = 2 * np.pi * freq * t
        if kind == "sine":
            x = np.sin(ph)
        elif kind == "square":
            x = _sig.square(ph)
        elif kind == "triangle":
            x = _sig.sawtooth(ph, 0.5)
        elif kind == "sawtooth":
            x = _sig.sawtooth(ph)
        else:
            x = np.zeros(n)
            period = fs / freq
            x[np.round(np.arange(0, n, period)).astype(int) % n] = 1.0
    elif kind == "white":
        x = rng.standard_normal(n)
    elif kind == "pink":
        x = _pink(n, rng)
    elif kind == "logsweep":
        x = exp_sweep(max(freq, 1.0), min(f_end, 0.48 * fs), n, fs)
    else:
        raise ValueError(f"Unbekannte Signalform: {kind}")
    peak = np.max(np.abs(x)) or 1.0
    return x / peak * db_to_lin(level_dbfs)
