"""Mess-Sweep (exponentieller Sinus-Sweep) und zugehöriges Frequenzraster."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np


def db_to_lin(db: float) -> float:
    return float(10.0 ** (db / 20.0))


@dataclass(frozen=True)
class SweepConfig:
    """Parameter eines Impedanz-Sweeps.

    Das Frequenzraster (und damit die Kompatibilität mit einer Kalibrierung)
    hängt nur von Abtastrate, Sweep-Länge, Pausen und Frequenzbereich ab –
    nicht vom Pegel und nicht von der Anzahl der Mittelungen.
    """

    fs: int = 48000
    f_start: float = 1.0
    f_stop: float = 20000.0
    sweep_exp: int = 17          # Sweep-Länge = 2**sweep_exp Samples (2,7 s bei 48 kHz)
    level_dbfs: float = -10.0
    pre_s: float = 0.05
    post_s: float = 0.30
    averages: int = 1

    # -- abgeleitete Größen -------------------------------------------------
    @property
    def sweep_samples(self) -> int:
        return 1 << self.sweep_exp

    @property
    def pre_samples(self) -> int:
        return int(round(self.pre_s * self.fs))

    @property
    def post_samples(self) -> int:
        return int(round(self.post_s * self.fs))

    @property
    def total_samples(self) -> int:
        return self.pre_samples + self.sweep_samples + self.post_samples

    @property
    def nfft(self) -> int:
        return 1 << int(np.ceil(np.log2(self.total_samples)))

    @property
    def effective_f_stop(self) -> float:
        return min(self.f_stop, 0.48 * self.fs)

    @property
    def duration_s(self) -> float:
        return self.total_samples / self.fs

    def fft_frequencies(self) -> np.ndarray:
        return np.fft.rfftfreq(self.nfft, 1.0 / self.fs)

    def band_mask(self) -> np.ndarray:
        f = self.fft_frequencies()
        return (f >= self.f_start) & (f <= self.effective_f_stop)

    def frequencies(self) -> np.ndarray:
        """Frequenzen aller FFT-Bins im Messbereich (Ergebnisraster)."""
        return self.fft_frequencies()[self.band_mask()]

    def grid_key(self) -> tuple:
        return (self.fs, self.sweep_exp, self.pre_samples, self.post_samples,
                round(self.f_start, 6), round(self.effective_f_stop, 6))

    def with_(self, **kw) -> "SweepConfig":
        return replace(self, **kw)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SweepConfig":
        fields = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**fields)


def exp_sweep(f1: float, f2: float, n: int, fs: int, fade_in: float = 0.01, fade_out: float = 0.005) -> np.ndarray:
    """Exponentieller Sinus-Sweep (Farina) mit Ein-/Ausblendung, Amplitude 1."""
    t = np.arange(n) / fs
    T = n / fs
    L = T / np.log(f2 / f1)
    x = np.sin(2.0 * np.pi * f1 * L * (np.exp(t / L) - 1.0))
    ni = max(1, int(fade_in * n))
    no = max(1, int(fade_out * n))
    x[:ni] *= 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, ni))
    x[-no:] *= 0.5 + 0.5 * np.cos(np.linspace(0.0, np.pi, no))
    return x


def make_stimulus(cfg: SweepConfig) -> np.ndarray:
    """Komplettes Wiedergabesignal inkl. Vor- und Nachlauf (Stille)."""
    sweep = exp_sweep(cfg.f_start, cfg.effective_f_stop, cfg.sweep_samples, cfg.fs)
    out = np.zeros(cfg.total_samples)
    out[cfg.pre_samples:cfg.pre_samples + cfg.sweep_samples] = sweep * db_to_lin(cfg.level_dbfs)
    return out
