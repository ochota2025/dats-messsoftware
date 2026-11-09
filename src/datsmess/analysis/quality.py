"""Messqualität („Ampel“): Pegel, Übersteuerung, Signal-Rausch-Abstand, Brummen, Kohärenz.

Die Kennzahlen werden aus den Rohaufnahmen eines Sweeps bestimmt:

* Spitzen- und Effektivpegel beider Kanäle
* Rauschpegel im Nachlauf nach dem Sweep (Stille) → Signal-Rausch-Abstand des Messkanals
* Anteil von 50/60-Hz-Brummen am Rauschen (Masseschleife?)
* bei mehreren Mittelungen: Kohärenz zwischen Referenz- und Messkanal
* Hinweis auf vertauschte Eingänge (Messkanal lauter als Referenz)
"""
from __future__ import annotations

import numpy as np

CLIP = 0.98
NEAR_CLIP = 0.89          # −1 dBFS
NO_SIGNAL = 1e-3          # −60 dBFS

GRADE_LABEL = {"ok": "gut", "warn": "mäßig", "bad": "schlecht"}


def db(x: float) -> float:
    return float(20 * np.log10(max(float(x), 1e-12)))


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def hum_fraction(noise: np.ndarray, fs: int) -> tuple[float, int | None]:
    """Anteil der Rauschleistung bei 50/60 Hz und Oberwellen (bis 300 Hz); (Anteil, Netzfrequenz)."""
    n = len(noise)
    if n < fs // 10:
        return 0.0, None
    w = np.hanning(n)
    P = np.abs(np.fft.rfft((noise - noise.mean()) * w)) ** 2
    f = np.fft.rfftfreq(n, 1 / fs)
    total = float(P[f > 10].sum()) or 1e-30
    best, best_f = 0.0, None
    for mains in (50, 60):
        m = np.zeros_like(f, dtype=bool)
        for k in range(1, 7):
            m |= np.abs(f - k * mains) <= max(2.0, 1.5 * fs / n)
        frac = float(P[m].sum()) / total
        if frac > best:
            best, best_f = frac, mains
    return best, best_f


def compute_quality(recordings: np.ndarray, stimulus: np.ndarray, cfg, ch, latency: int | None,
                    coherence: np.ndarray | None = None) -> dict:
    """Kennzahlen (alles JSON-tauglich). ``latency`` = Verzögerung Ausgang → Eingang in Samples."""
    recs = np.asarray(recordings, dtype=float)
    first = recs[0]
    n = first.shape[0]
    meas = first[:, ch.meas_channel]
    two = ch.mode != "single_channel" and first.shape[1] > ch.ref_channel
    ref = first[:, ch.ref_channel] if two else None
    peak_meas = float(np.max(np.abs(recs[:, :, ch.meas_channel])))
    peak_ref = float(np.max(np.abs(recs[:, :, ch.ref_channel]))) if two else None
    lat = int(latency or 0)
    s0 = min(n, cfg.pre_samples + lat)
    s1 = min(n, s0 + cfg.sweep_samples)
    guard = int(0.02 * cfg.fs)
    noise = meas[min(n, s1 + guard):]
    # Gleichspannungsanteil des Wandlers (USB-Codecs: oft −60 … −80 dBFS) ist kein Rauschen –
    # er wirkt nur auf 0 Hz und würde den Signal-Rausch-Abstand sonst künstlich begrenzen.
    dc = float(np.mean(noise)) if len(noise) else 0.0
    noise = noise - dc
    sig_meas = _rms(meas[s0:s1] - dc)
    noise_rms = _rms(noise) if len(noise) >= 1024 else None
    q = {
        "peak_meas_db": db(peak_meas),
        "peak_ref_db": db(peak_ref) if peak_ref is not None else None,
        "rms_meas_db": db(sig_meas),
        "rms_ref_db": db(_rms(ref[s0:s1])) if two else None,
        "noise_db": db(noise_rms) if noise_rms is not None else None,
        "snr_db": db(sig_meas / noise_rms) if noise_rms else None,
        "latency_ms": round(1000.0 * lat / cfg.fs, 1) if latency is not None else None,
        "clipped": bool(max(peak_meas, peak_ref or 0.0) > CLIP),
        "hum": None,
        "coherence_p5": None,
        "two_channel": bool(two),
        "averages": int(recs.shape[0]),
    }
    if noise_rms is not None and q["noise_db"] is not None and q["noise_db"] > -85:
        frac, mains = hum_fraction(noise, cfg.fs)
        if frac > 0.5:
            q["hum"] = {"hz": mains, "fraction": round(frac, 2)}
    if coherence is not None and len(coherence):
        q["coherence_p5"] = float(np.percentile(coherence, 5))
    return q


def grade(q: dict | None, context: str = "dut") -> tuple[str, list[str]]:
    """Bewertung: ("ok" | "warn" | "bad", Hinweise).

    ``context``: "dut" (Messobjekt), "open" (Leerlauf), "short" (Kurzschluss: Messkanal ist still),
    "cal" (Kalibrierwiderstand).
    """
    if not q:
        return "ok", []
    bad, warn = [], []
    pm, pr = q.get("peak_meas_db"), q.get("peak_ref_db")
    peak_max = max(v for v in (pm, pr, -200.0) if v is not None)
    if q.get("clipped"):
        bad.append("Übersteuerung – Pegel verringern.")
    elif peak_max > db(NEAR_CLIP):
        warn.append(f"Knapp an der Übersteuerung ({peak_max:.1f} dBFS) – Pegel etwas verringern.")
    if pr is not None and pr < db(NO_SIGNAL):
        bad.append("Kaum Signal am Referenzkanal – Ausgang, Kabel und Lautstärke (Windows/macOS) prüfen.")
    elif pr is not None and pr < -40:
        warn.append(f"Sehr niedriger Pegel ({pr:.0f} dBFS) – Pegel erhöhen oder System-Lautstärke prüfen.")
    if context != "short":
        if pm is not None and pm < db(NO_SIGNAL):
            bad.append("Kaum Signal am Messkanal – Klemmen und Verbindung prüfen.")
        else:
            snr = q.get("snr_db")
            room = -3.0 - peak_max                  # Luft bis −3 dBFS Spitze
            more = (f"Pegel um etwa {room:.0f} dB erhöhen (Spitze jetzt {peak_max:.0f} dBFS)"
                    if room >= 3 and not q.get("clipped") else "mehr Pegel")
            if snr is not None and snr < 20:
                bad.append(f"Signal-Rausch-Abstand nur {snr:.0f} dB – {more}, mitteln, Störquellen prüfen.")
            elif snr is not None and snr < 40:
                warn.append(f"Signal-Rausch-Abstand {snr:.0f} dB – {more} oder mitteln "
                            "(4 Mittelungen = +6 dB) verbessert das Ergebnis.")
    hum = q.get("hum")
    if hum and (q.get("snr_db") or 99) < 60:
        warn.append(f"Brummen ({hum['hz']} Hz) im Rauschen – Masseschleife? Laptop vom Netzteil trennen "
                    "oder andere USB-Buchse versuchen.")
    coh = q.get("coherence_p5")
    if coh is not None and coh < 0.9:
        warn.append(f"Mittelungen weichen voneinander ab (Kohärenz {coh:.2f}) – Störungen oder Bewegung "
                    "während der Messung?")
    if (q.get("two_channel") and context in ("dut", "cal") and q.get("rms_ref_db") is not None
            and q.get("rms_meas_db") is not None and q["rms_meas_db"] > q["rms_ref_db"] + 1.0):
        warn.append("Messkanal lauter als Referenzkanal – sind die Eingangskanäle vertauscht? "
                    "(Seitenleiste „Eingangskanäle tauschen“ oder Geräte-Check)")
    g = "bad" if bad else ("warn" if warn else "ok")
    return g, bad + warn


def summary(q: dict | None, context: str = "dut") -> str:
    g, msgs = grade(q, context)
    parts = [f"Messqualität {GRADE_LABEL[g]}"]
    if q and q.get("snr_db") is not None and context != "short":
        parts.append(f"S/N {q['snr_db']:.0f} dB")
    if q and q.get("peak_ref_db") is not None:
        parts.append(f"Spitze {max(q['peak_ref_db'], q['peak_meas_db']):.1f} dBFS")
    return ", ".join(parts) + ("" if not msgs else " – " + msgs[0])
