"""Geräte-Check: Kanalzuordnung, Referenz- und Kalibrierwiderstand ohne Herstellerunterlagen bestimmen.

Ablauf (jeweils ein kurzer Sweep):

1. **Leerlauf** – beide Eingänge sehen fast dieselbe Spannung.
2. **Kurzschluss** – der *Mess*eingang wird still, der Referenzeingang nicht. Damit ist die
   Kanalzuordnung eindeutig.
3. **Kalibrierwiderstand** – liefert das Verhältnis R_cal / R_ref.
4. optional **bekannter Widerstand** (mit dem Multimeter gemessen) – liefert R_ref absolut und
   damit auch den tatsächlichen Wert des Kalibrierwiderstands.

Mathematisch wird dieselbe Möbius-Beziehung wie bei der Kalibrierung genutzt:
``h(H) = H / (k − H)`` mit ``k = H_open``; dann ist ``Z / R_ref = h(H) − h(H_short)``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..measurement import ChannelConfig, transfer_from_recordings


def channel_levels(recordings: np.ndarray, cfg) -> list[float]:
    """Effektivpegel (dBFS) je Eingangskanal während des Sweeps."""
    rec = np.asarray(recordings, float)[0]
    s0 = cfg.pre_samples
    s1 = min(len(rec), s0 + cfg.sweep_samples)
    out = []
    for c in range(rec.shape[1]):
        r = float(np.sqrt(np.mean(np.square(rec[s0:s1, c]))))
        out.append(float(20 * np.log10(max(r, 1e-12))))
    return out


@dataclass
class Assignment:
    ref: int | None
    meas: int | None
    single_channel: bool = False
    confident: bool = False
    drop_db: float = 0.0
    message: str = ""

    @property
    def swap(self) -> bool:
        return self.meas == 0 and self.ref == 1


def detect_assignment(open_levels: list[float], short_levels: list[float]) -> Assignment:
    """Der Kanal, der beim Kurzschluss deutlich leiser wird, ist der Messkanal."""
    if len(open_levels) < 2 or open_levels[1] < -100:
        return Assignment(None, 0, single_channel=True, confident=open_levels[0] > -60,
                          message="Das Gerät liefert nur einen Eingangskanal – Messprinzip „1 Kanal“ "
                                  "wählen und unbedingt mit Leerlauf kalibrieren.")
    if max(open_levels) < -60:
        return Assignment(None, None, message="Bei offenen Klemmen kommt kaum Signal an – Ausgang, "
                                              "System-Lautstärke und USB-Verbindung prüfen.")
    drops = [o - s for o, s in zip(open_levels, short_levels)]
    meas = int(np.argmax(drops))
    ref = 1 - meas
    diff = drops[meas] - drops[ref]
    a = Assignment(ref, meas, confident=diff > 15, drop_db=float(drops[meas]))
    if a.confident:
        a.message = (f"Beim Kurzschluss wird Eingang {meas + 1} um {drops[meas]:.0f} dB leiser, "
                     f"Eingang {ref + 1} bleibt ({drops[ref]:+.0f} dB). → Referenz = Eingang {ref + 1}, "
                     f"Messung = Eingang {meas + 1}.")
    else:
        a.message = ("Kein Eingang wird beim Kurzschluss deutlich leiser – waren die Klemmen wirklich "
                     "fest verbunden? Bitte den Schritt wiederholen.")
    return a


def _band_median(f: np.ndarray, x: np.ndarray, lo: float, hi: float) -> float:
    m = (f >= lo) & (f <= hi)
    return float(np.median(x[m])) if m.any() else float("nan")


@dataclass
class BridgeEstimate:
    ratio_cal: float                     # R_cal / R_ref
    flatness: float                      # relative Schwankung von R_cal/R_ref (20 Hz … 10 kHz)
    r_ref: float | None = None           # aus bekanntem Widerstand
    r_cal: float | None = None
    r_known_measured: float | None = None
    lines: list[str] = field(default_factory=list)


def estimate_bridge(cfg, ch: ChannelConfig, recs: dict[str, np.ndarray], r_nominal: float,
                    r_known: float | None = None) -> BridgeEstimate:
    """``recs``: Rohaufnahmen für "open", "short", "cal" und optional "known"."""
    H = {k: transfer_from_recordings(r, cfg, ch).H for k, r in recs.items()}
    f = cfg.frequencies()
    k = H["open"]

    def h(x):
        return x / (k - x)

    h_short = h(H["short"]) if "short" in H else 0.0
    z_cal = h(H["cal"]) - h_short                  # = R_cal / R_ref (komplex)
    ratio = _band_median(f, z_cal.real, 100, 5000)
    band = (f >= 20) & (f <= 10000)
    mag = np.abs(z_cal[band])
    flat = float(np.ptp(mag) / np.median(mag)) if band.any() else float("nan")
    est = BridgeEstimate(ratio, flat)
    est.lines.append(f"Verhältnis Kalibrierwiderstand / Referenzwiderstand: {ratio:.3f}")
    if "known" in H and r_known:
        z_known = h(H["known"]) - h_short
        rk = _band_median(f, z_known.real, 100, 2000)
        if rk > 0:
            est.r_ref = r_known / rk
            est.r_cal = ratio * est.r_ref
            est.lines.append(f"Aus dem bekannten Widerstand ({r_known:g} Ω): "
                             f"Referenzwiderstand ≈ {est.r_ref:.2f} Ω, Kalibrierwiderstand ≈ {est.r_cal:.1f} Ω")
    else:
        est.lines.append(f"Mit angenommenem Referenzwiderstand {r_nominal:g} Ω wäre der Kalibrierwiderstand "
                         f"≈ {ratio * r_nominal:.1f} Ω.")
    if flat > 0.05:
        est.lines.append(f"Achtung: R_cal/R_ref schwankt über die Frequenz um {flat * 100:.1f} % – "
                         "Verbindungen prüfen.")
    return est
