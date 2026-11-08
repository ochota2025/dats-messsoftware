"""Klirrfaktor und Rub & Buzz aus dem Impedanz-Sweep (Farina-Verfahren).

Beim exponentiellen Sweep liegen die Impulsantworten der Oberwellen nach der Entfaltung zeitlich
*vor* der linearen Antwort, Harmonische k im Abstand ``L·ln(k)`` (L = T / ln(f2/f1)). So lassen
sich H1 … Hk aus einer einzigen Messung trennen, ganz ohne zusätzliche Messung.

Gemessen wird die **Spannung an den Klemmen** (elektrischer Klirr). Damit Verzerrungen des
Wandlers/Verstärkers nicht dem Treiber zugeschrieben werden, wird der Anteil, der schon im
Referenzkanal steckt, über die lineare Brückenübertragung herausgerechnet:

    D_k(F) = M_k(F) − H(F) · R_k(F),      H = M_1 / R_1

``THD(f) = sqrt(Σ_k |D_k(k·f)|²) / |M_1(f)|``. Höhere Harmonische (ab k = 10) zeigen
Schleifen, Kratzen, lose Teile (Rub & Buzz); sie treten bei intakten Treibern kaum auf.
Akustischer Klirr (Schalldruck) braucht ein Mikrofon – dafür ist diese Auswertung nicht gedacht.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .sweep import SweepConfig, make_stimulus
from .transfer import estimate_delay, resample_log, smooth_octave

HOHD_ORDERS = range(10, 21)          # „höhere Harmonische“ für Rub & Buzz
LOW_ORDERS = range(2, 6)


@dataclass
class DistortionResult:
    f: np.ndarray                     # Grundtonfrequenz
    thd: np.ndarray                   # Treiber (Messkanal, ohne Wandleranteil), Anteil (0.01 = 1 %)
    h2: np.ndarray
    h3: np.ndarray
    hohd: np.ndarray                  # Rub-&-Buzz-Anteil (k = 10 … 20)
    thd_ref: np.ndarray               # Wandler/Verstärker (Referenzkanal)
    level_dbfs: float
    noise_thd: np.ndarray | None = None   # Rauschgrenze für THD (k = 2 … 5)
    noise_hohd: np.ndarray | None = None  # Rauschgrenze für die höheren Harmonischen

    def at(self, arr: np.ndarray, f0: float) -> float:
        return float(np.interp(np.log(f0), np.log(self.f), arr))

    def peak(self, arr: np.ndarray, lo: float, hi: float) -> tuple[float, float]:
        m = (self.f >= lo) & (self.f <= hi) & np.isfinite(arr)
        if not m.any():
            return float("nan"), float("nan")
        i = int(np.argmax(np.where(m, arr, -np.inf)))
        return float(arr[i]), float(self.f[i])


def _impulse(x: np.ndarray, S: np.ndarray, nfft: int) -> np.ndarray:
    X = np.fft.rfft(x, nfft)
    reg = 1e-10 * float(np.max(np.abs(S) ** 2))
    return np.fft.irfft(X * np.conj(S) / (np.abs(S) ** 2 + reg), nfft)


def _noise_like(x: np.ndarray, start: int) -> np.ndarray | None:
    """Rauschen in Länge der Aufnahme: die Stille nach dem Sweep, aneinandergereiht."""
    tail = x[start:]
    if len(tail) < 2048:
        return None
    tail = tail - tail.mean()
    reps = int(np.ceil(len(x) / len(tail)))
    return np.tile(tail, reps)[: len(x)]


def _spectra(ir: np.ndarray, nfft: int, t0: int, L_samp: float, orders: list[int],
             fs: int, offset: int = 0) -> dict[int, np.ndarray]:
    """Spektren der linearen (k=1) und harmonischen Impulsantworten (k ≥ 2)."""
    out = {}
    pos = {k: t0 - L_samp * np.log(k) for k in [1, *orders]}
    for k in [1, *orders]:
        # Fenster: von kurz vor der Harmonischen k bis kurz vor der nächst-späteren (k−1)
        nxt = L_samp * np.log(k / (k - 1)) if k > 1 else None
        prv = L_samp * np.log((k + 1) / k)
        start = int(round(pos[k] - 0.15 * prv)) + offset
        length = int(round(0.85 * nxt + 0.15 * prv)) if nxt else int(min(0.5 * fs, nfft // 4))
        idx = (np.arange(start, start + length)) % nfft
        seg = ir[idx]
        fade = max(4, length // 16)
        w = np.ones(length)
        w[:fade] = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, fade))
        w[-fade:] = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, fade))
        buf = np.zeros(nfft)
        buf[:length] = seg * w
        out[k] = np.fft.rfft(buf, nfft)
    return out


def analyze(recordings: np.ndarray, cfg: SweepConfig, ref_channel: int = 0, meas_channel: int = 1,
            single_channel: bool = False, n_points: int = 300) -> DistortionResult:
    rec = np.asarray(recordings, float).mean(axis=0)            # Mittelung im Zeitbereich
    stim = make_stimulus(cfg)
    fs = cfg.fs
    nfft = 1 << int(np.ceil(np.log2(2 * len(stim))))
    S = np.fft.rfft(stim, nfft)
    f_axis = np.fft.rfftfreq(nfft, 1 / fs)
    f1, f2 = cfg.f_start, cfg.effective_f_stop
    L_samp = cfg.sweep_samples / np.log(f2 / f1)
    meas = rec[:, meas_channel]
    ref = rec[:, ref_channel] if not single_channel else None
    lat = estimate_delay(stim, ref if ref is not None else meas)
    orders = [*LOW_ORDERS, *HOHD_ORDERS]
    ir_m = _impulse(meas, S, nfft)
    ir_r = _impulse(ref, S, nfft) if ref is not None else None
    M = _spectra(ir_m, nfft, lat, L_samp, orders, fs)
    R = _spectra(ir_r, nfft, lat, L_samp, orders, fs) if ir_r is not None else None
    # Rauschgrenze: dieselbe Auswertung auf das Rauschen aus der Stille nach dem Sweep anwenden
    quiet = cfg.pre_samples + cfg.sweep_samples + lat + int(0.02 * fs)
    nm = _noise_like(meas, quiet)
    zero = {k: np.zeros(nfft // 2 + 1, complex) for k in [1, *orders]}
    NM = _spectra(_impulse(nm, S, nfft), nfft, lat, L_samp, orders, fs) if nm is not None else zero
    nr = _noise_like(ref, quiet) if ref is not None else None
    NR = _spectra(_impulse(nr, S, nfft), nfft, lat, L_samp, orders, fs) if nr is not None else zero
    Hlin = M[1] / np.where(np.abs(R[1]) > 0, R[1], 1) if R is not None else None

    lo = max(20.0, f1 * 2)
    hi = 0.45 * f2
    f0 = np.geomspace(lo, hi, n_points)

    def pow_at(spec, freqs):
        """Leistung, über 1/12 Oktave geglättet, an den Frequenzen ``freqs``."""
        p = smooth_octave(f_axis, np.abs(spec) ** 2, 12)
        return np.interp(freqs, f_axis, p, left=np.nan, right=np.nan)

    m1 = np.sqrt(pow_at(M[1], f0))
    r1 = np.sqrt(pow_at(R[1], f0)) if R is not None else None
    parts, noise, ref_parts = {}, {}, {}
    for k in orders:
        D = M[k] - Hlin * R[k] if R is not None else M[k]
        ND = NM[k] - Hlin * NR[k] if R is not None else NM[k]
        valid = k * f0 <= 0.9 * f2              # Ausblendung am Sweep-Ende meiden
        pd = np.where(valid, pow_at(D, k * f0), np.nan)
        pn = np.where(valid, pow_at(ND, k * f0), np.nan)
        # Rauschleistung abziehen; was nicht deutlich (3 dB) über dem Rauschen liegt, ist nicht messbar
        parts[k] = np.where(pd > 2.0 * pn, np.sqrt(np.maximum(pd - pn, 0.0)), np.nan) / m1
        noise[k] = np.sqrt(pn) / m1
        if R is not None:
            prs, prn = pow_at(R[k], k * f0), pow_at(NR[k], k * f0)
            ref_parts[k] = np.where(valid & (prs > 2.0 * prn), np.sqrt(np.maximum(prs - prn, 0.0)), np.nan) / r1

    def total(d, ks):
        arr = np.array([d[k] for k in ks])
        ok = np.isfinite(arr)
        s = np.sqrt(np.nansum(np.where(ok, arr, 0) ** 2, axis=0))
        return np.where(ok.any(axis=0), s, np.nan)

    def smooth(y):
        good = np.isfinite(y)
        if good.sum() < 4:
            return y
        _, ys = resample_log(f0[good], y[good], f0[good][0], f0[good][-1], int(good.sum()), octave_frac=12)
        out = np.full_like(y, np.nan)
        out[good] = ys
        return out

    thd = smooth(total(parts, LOW_ORDERS))
    hohd = smooth(total(parts, HOHD_ORDERS))
    thd_ref = smooth(total(ref_parts, LOW_ORDERS)) if ref_parts else np.full_like(f0, np.nan)
    return DistortionResult(f0, thd, smooth(parts[2]), smooth(parts[3]), hohd, thd_ref, cfg.level_dbfs,
                            smooth(total(noise, LOW_ORDERS)), smooth(total(noise, HOHD_ORDERS)))


def rub_buzz_verdict(res: DistortionResult, limit_db: float = -50.0) -> tuple[str, str]:
    """("ok" | "warn", Text) anhand der höheren Harmonischen zwischen 20 Hz und 1 kHz."""
    band = (res.f >= 20.0) & (res.f <= 1000.0)
    if not band.any() or (res.noise_hohd is not None and not np.isfinite(res.noise_hohd[band]).any()):
        return "ok", "Rub & Buzz: nicht auswertbar (Sweep zu kurz oder Frequenzbereich zu klein)."
    excess = np.where(np.isfinite(res.hohd), res.hohd, 0.0)   # NaN = unter der Rauschgrenze
    peak, f_at = res.peak(excess, 20.0, 1000.0)
    if not np.isfinite(peak):
        return "ok", "Rub & Buzz: nicht auswertbar (Sweep zu kurz oder Frequenzbereich zu klein)."
    db = 20 * np.log10(max(peak, 1e-12))
    if peak <= 0:
        return "ok", "Rub & Buzz unauffällig (höhere Harmonische unter der Rauschgrenze)."
    if db > limit_db:
        return "warn", (f"Rub & Buzz auffällig: höhere Harmonische bis {db:.0f} dB ({peak * 100:.2f} %) "
                        f"bei {f_at:.0f} Hz – auf Schleifen, Kratzen oder lose Teile prüfen.")
    return "ok", f"Rub & Buzz unauffällig (höhere Harmonische max. {db:.0f} dB bei {f_at:.0f} Hz)."
