"""Mess-Engine: Sweep abspielen, Übertragungsfunktion bilden, Impedanz berechnen."""
from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass, field

import numpy as np

from .analysis.quality import compute_quality
from .audio.backend import AudioBackend
from .dsp.calibration import Calibration, nominal_impedance
from .dsp.sweep import SweepConfig, make_stimulus
from .dsp.transfer import CrossSpectrum, estimate_delay, resample_log, shift


@dataclass
class ChannelConfig:
    """Zuordnung der Eingangskanäle.

    two_channel:    H = Messkanal / Referenzkanal (Standard, latenzunabhängig)
    single_channel: H = Messkanal / Ausgangssignal (Latenz wird geschätzt;
                    Leerlauf-Kalibrierung ist dann Pflicht)
    """
    mode: str = "two_channel"
    ref_channel: int = 0
    meas_channel: int = 1
    r_nominal: float = 100.0       # nur für unkalibrierte Schätzung

    def to_dict(self) -> dict:
        return dict(mode=self.mode, ref_channel=self.ref_channel, meas_channel=self.meas_channel,
                    r_nominal=self.r_nominal)

    @classmethod
    def from_dict(cls, d: dict) -> "ChannelConfig":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class RawResult:
    f: np.ndarray
    H: np.ndarray
    peak_ref: float
    peak_meas: float
    latency: int | None = None
    recordings: np.ndarray | None = None      # (Mittelungen, Samples, Kanäle), float32
    quality: dict | None = None               # Kennzahlen für die Qualitäts-Ampel (analysis.quality)

    @property
    def clipped(self) -> bool:
        return max(self.peak_ref, self.peak_meas) > 0.98


@dataclass
class Measurement:
    name: str
    f: np.ndarray
    Z: np.ndarray
    created: str = field(default_factory=lambda: _dt.datetime.now().isoformat(timespec="seconds"))
    meta: dict = field(default_factory=dict)
    color: str | None = None
    visible: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    raw_H: np.ndarray | None = None           # unkalibrierte Übertragungsfunktion
    recordings: np.ndarray | None = None      # Rohaufnahmen des Sweeps

    @property
    def magnitude(self) -> np.ndarray:
        return np.abs(self.Z)

    @property
    def phase_deg(self) -> np.ndarray:
        return np.degrees(np.angle(self.Z))

    @property
    def has_raw(self) -> bool:
        return self.recordings is not None and "sweep" in self.meta and "channels" in self.meta

    def resampled(self, n: int = 1000, octave_frac: float | None = None,
                  f_lo: float | None = None, f_hi: float | None = None) -> tuple[np.ndarray, np.ndarray]:
        if n <= 0 or n >= len(self.f):
            return self.f, self.Z
        return resample_log(self.f, self.Z, f_lo, f_hi, n, octave_frac)


def transfer_from_recordings(recordings: np.ndarray, cfg: SweepConfig, ch: ChannelConfig) -> RawResult:
    """Übertragungsfunktion aus Rohaufnahmen – identisch für Messung und Reproduktion."""
    stim = make_stimulus(cfg)
    acc = CrossSpectrum(cfg.nfft)
    peak_ref = peak_meas = 0.0
    latency = None
    for rec in recordings:
        rec = np.asarray(rec, dtype=float)
        meas = rec[:, ch.meas_channel]
        if ch.mode == "single_channel":
            latency = estimate_delay(stim, meas)
            ref = shift(stim, latency)
        else:
            ref = rec[:, ch.ref_channel]
        peak_ref = max(peak_ref, float(np.max(np.abs(ref))))
        peak_meas = max(peak_meas, float(np.max(np.abs(meas))))
        acc.add(ref, meas)
    band = cfg.band_mask()
    H = acc.transfer()[band]
    quality = None
    try:
        lat = latency
        if lat is None:
            lat = estimate_delay(stim, np.asarray(recordings[0][:, ch.ref_channel], dtype=float))
        coh = None
        if acc.count > 1:
            f = cfg.frequencies()
            coh = acc.coherence()[band][(f >= 20) & (f <= 10000)]
        quality = compute_quality(recordings, stim, cfg, ch, lat, coh)
    except Exception:       # noqa: BLE001 – Qualitätsbewertung darf eine Messung nie verhindern
        quality = None
    return RawResult(cfg.frequencies(), H, peak_ref, peak_meas, latency, recordings, quality)


class MeasurementEngine:
    def __init__(self, backend: AudioBackend, sweep: SweepConfig | None = None,
                 channels: ChannelConfig | None = None):
        self.backend = backend
        self.sweep = sweep or SweepConfig()
        self.channels = channels or ChannelConfig()
        self.calibration: Calibration | None = None

    # ------------------------------------------------------------------
    @property
    def calibrated(self) -> bool:
        return self.calibration is not None and self.calibration.is_compatible(self.sweep)

    def record(self, cfg: SweepConfig, progress=None) -> np.ndarray:
        stim = make_stimulus(cfg)
        recs = []
        n = max(1, cfg.averages)
        for i in range(n):
            recs.append(np.asarray(self.backend.play_record(stim, cfg.fs, in_channels=2), dtype=np.float32))
            if progress:
                progress(i + 1, n)
        return np.stack(recs)

    def measure_H(self, sweep: SweepConfig | None = None, progress=None) -> RawResult:
        cfg = sweep or self.sweep
        return transfer_from_recordings(self.record(cfg, progress), cfg, self.channels)

    def impedance_from_H(self, H: np.ndarray, calibration: Calibration | None = None) -> np.ndarray:
        cal = calibration if calibration is not None else (self.calibration if self.calibrated else None)
        if cal is not None:
            return cal.correct(H)
        return nominal_impedance(H, self.channels.r_nominal)

    def measure_impedance(self, name: str = "Messung", progress=None) -> tuple[Measurement, RawResult]:
        raw = self.measure_H(progress=progress)
        Z = self.impedance_from_H(raw.H)
        cal = self.calibration if self.calibrated else None
        meta = {
            "calibrated": cal is not None,
            "calibration_id": cal.id if cal is not None else None,
            "sweep": self.sweep.to_dict(),
            "channels": self.channels.to_dict(),
            "device": self.backend.describe(),
            "peak_ref": raw.peak_ref,
            "peak_meas": raw.peak_meas,
            "quality": raw.quality,
        }
        m = Measurement(name=name, f=raw.f, Z=Z, meta=meta, raw_H=raw.H, recordings=raw.recordings)
        return m, raw


def reprocess(m: Measurement, calibration: Calibration | None) -> np.ndarray:
    """Berechnet die Impedanz einer Messung aus den Rohaufnahmen neu.

    Mit der ursprünglichen Kalibrierung ergibt sich exakt das gespeicherte Ergebnis;
    mit einer neueren Kalibrierung lassen sich alte Messungen nachträglich korrigieren.
    """
    if not m.has_raw:
        raise ValueError(f"„{m.name}“ enthält keine Rohdaten (importierte Kurve?).")
    cfg = SweepConfig.from_dict(m.meta["sweep"])
    ch = ChannelConfig.from_dict(m.meta["channels"])
    raw = transfer_from_recordings(m.recordings, cfg, ch)
    if calibration is not None:
        if not calibration.is_compatible(cfg):
            raise ValueError("Kalibrierung passt nicht zu Abtastrate/Sweep-Länge der Messung.")
        return calibration.correct(raw.H)
    return nominal_impedance(raw.H, ch.r_nominal)
