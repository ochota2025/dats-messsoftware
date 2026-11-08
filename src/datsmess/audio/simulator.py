"""Virtuelles DATS-Interface.

Simuliert die Messbrücke inklusive typischer Fehlerquellen, damit Software,
Kalibrierung und Auswertung ohne Hardware entwickelt und geprüft werden können:

* Referenz-Serienwiderstand, Eingangswiderstand des Messkanals
* unterschiedliche Kanalverstärkung, AC-Kopplung (Hochpass) je Kanal
* Kabel- und Übergangswiderstand + Leitungsinduktivität
* Latenz, 16-Bit-Quantisierung, Rauschen

Optional (für die Oberfläche eingeschaltet, in den Grundtests aus):

* ``sample``          – Treiber-Exemplar 1 … 8 mit Fertigungsstreuung (1 = Nennwerte)
* ``level_dependent`` – fs/Qms/Qes ändern sich mit dem Pegel (für Pegelreihen)
* ``distortion``      – schwache Nichtlinearität des Treibers (Klirr), beim
                        Anschluss „Treiber mit Schleifgeräusch“ zusätzlich Rub & Buzz
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace

import numpy as np

from .backend import AudioBackend

REF_LEVEL = 10 ** (-10 / 20)        # Bezugspegel −10 dBFS: dort gelten die Nennwerte


@dataclass
class SimDriver:
    Re: float = 5.6
    fs: float = 38.0
    Qms: float = 4.2
    Qes: float = 0.42
    Mms: float = 0.022           # kg
    Sd: float = 0.0132           # m²
    Kr: float = 0.003
    Xr: float = 0.67
    Ki: float = 0.0083
    Xi: float = 0.63

    @property
    def Cms(self) -> float:
        return 1 / ((2 * np.pi * self.fs) ** 2 * self.Mms)

    @property
    def Bl(self) -> float:
        return float(np.sqrt(2 * np.pi * self.fs * self.Mms * self.Re / self.Qes))

    @property
    def Rms(self) -> float:
        return 2 * np.pi * self.fs * self.Mms / self.Qms

    @property
    def Vas(self) -> float:
        return 1.204 * 343.2 ** 2 * self.Sd ** 2 * self.Cms

    def parts(self, f: np.ndarray, added_mass: float = 0.0,
              box_volume: float | None = None) -> tuple[np.ndarray, np.ndarray]:
        """(elektrischer Teil Ze, Bewegungsimpedanz Zmot)."""
        w = 2 * np.pi * np.maximum(f, 1e-3)
        cms = self.Cms
        if box_volume:
            cmb = box_volume / (1.204 * 343.2 ** 2 * self.Sd ** 2)
            cms = cms * cmb / (cms + cmb)
        zmech = self.Rms + 1j * w * (self.Mms + added_mass) + 1 / (1j * w * cms)
        ze = self.Re + self.Kr * w ** self.Xr + 1j * self.Ki * w ** self.Xi
        return ze, self.Bl ** 2 / zmech

    def impedance(self, f: np.ndarray, added_mass: float = 0.0, box_volume: float | None = None) -> np.ndarray:
        ze, zm = self.parts(f, added_mass, box_volume)
        return ze + zm


@dataclass
class SimHardware:
    r_series: float = 100.0       # interner Referenzwiderstand
    r_in: float = 20e3            # Eingangswiderstand Messkanal
    gain_ref: float = 0.98
    gain_meas: float = 1.013
    hp_ref: float = 2.0           # Hz, AC-Kopplung
    hp_meas: float = 2.3
    hp_out: float = 3.0
    lead_r: float = 0.12          # Ω (Kabel + Krokodilklemmen)
    lead_l: float = 0.4e-6        # H
    latency: int = 311            # Samples
    noise_dbfs: float = -96.0
    r_cal: float = 1000.0         # tatsächlicher Wert des Kalibrierwiderstands


DRIVER_CONNECTIONS = ("driver", "driver_mass", "driver_box", "driver_rub")


class SimulatorBackend(AudioBackend):
    name = "Simulator"
    is_simulator = True

    def __init__(self, seed: int | None = 1):
        self.hw = SimHardware()
        self.driver = SimDriver()
        self.connection = "driver"
        self.added_mass = 0.010              # kg
        self.box_volume = 0.020              # m³
        self.resistor = 8.2
        self.capacitor = 10e-6
        self.cap_esr = 0.05
        self.inductor = 1.0e-3
        self.inductor_dcr = 0.35
        self.rng = np.random.default_rng(seed)
        self.sample = 1                      # Treiber-Exemplar (1 = Nennwerte)
        self.level_dependent = False
        self.distortion = False
        self._stream: dict | None = None

    def set_connection(self, kind: str) -> None:
        self.connection = kind

    # -- Treiber ------------------------------------------------------------
    def sample_driver(self, sample: int | None = None) -> SimDriver:
        """Exemplar mit Fertigungsstreuung (reproduzierbar je Nummer)."""
        sample = self.sample if sample is None else sample
        d = self.driver
        if sample <= 1:
            return d
        r = np.random.default_rng(7919 * sample).normal(0.0, 1.0, 5)
        return replace(d, Re=d.Re * (1 + 0.02 * r[0]), fs=d.fs * (1 + 0.05 * r[1]),
                       Qms=d.Qms * (1 + 0.08 * r[2]), Qes=d.Qes * (1 + 0.05 * r[3]),
                       Mms=d.Mms * (1 + 0.03 * r[4]))

    def driver_at_level(self, amplitude: float) -> SimDriver:
        d = self.sample_driver()
        if not self.level_dependent:
            return d
        x = amplitude - REF_LEVEL               # > 0: lauter als der Bezugspegel
        return replace(d, fs=d.fs * (1 - 0.10 * x), Qms=d.Qms * (1 - 0.25 * x), Qes=d.Qes * (1 + 0.06 * x))

    def _driver_parts(self, f: np.ndarray, drv: SimDriver) -> tuple[np.ndarray, np.ndarray]:
        c = self.connection
        if c == "driver_mass":
            return drv.parts(f, added_mass=self.added_mass)
        if c == "driver_box":
            return drv.parts(f, box_volume=self.box_volume)
        return drv.parts(f)

    def dut_impedance(self, f: np.ndarray, amplitude: float = REF_LEVEL) -> np.ndarray:
        w = 2 * np.pi * np.maximum(f, 1e-3)
        c = self.connection
        if c == "open":
            return np.full(f.shape, 1e12 + 0j)
        if c == "short":
            return np.zeros(f.shape, complex)
        if c == "cal":
            return np.full(f.shape, self.hw.r_cal + 0j)
        if c in DRIVER_CONNECTIONS:
            ze, zm = self._driver_parts(f, self.driver_at_level(amplitude))
            return ze + zm
        if c == "resistor":
            return self.resistor + 1j * w * 0.8e-6
        if c == "capacitor":
            return self.cap_esr + 1 / (1j * w * self.capacitor) + 1j * w * 20e-9
        if c == "inductor":
            return self.inductor_dcr + 1j * w * self.inductor
        raise ValueError(c)

    # -- Messbrücke -----------------------------------------------------------
    def _simulate(self, stimulus: np.ndarray, fs: int, circular: bool = False) -> np.ndarray:
        """Spannungen an Referenz- und Messeingang (ohne Rauschen), Länge = len(stimulus)."""
        hw = self.hw
        n = len(stimulus)
        nfft = n if circular else 1 << int(np.ceil(np.log2(n + hw.latency + 1024)))
        f = np.fft.rfftfreq(nfft, 1 / fs)
        X = np.fft.rfft(stimulus, nfft)
        jw = 1j * 2 * np.pi * f

        def hp(fc):
            return jw / (jw + 2 * np.pi * fc)

        amp = float(np.max(np.abs(stimulus))) if n else 0.0
        z_dut = self.dut_impedance(f, amp)
        z_term = z_dut + hw.lead_r + jw * hw.lead_l
        z_eff = z_term * hw.r_in / (z_term + hw.r_in)
        divider = z_eff / (hw.r_series + z_eff)
        delay = np.exp(-jw * hw.latency / fs)
        v_src = X * hp(hw.hp_out) * delay
        a = np.fft.irfft(v_src * hw.gain_ref * hp(hw.hp_ref), nfft)[:n]
        v_meas = v_src * divider
        b = np.fft.irfft(v_meas * hw.gain_meas * hp(hw.hp_meas), nfft)[:n]
        if self.distortion and self.connection in DRIVER_CONNECTIONS:
            b = b + self._nonlinear(f, v_meas, z_dut, nfft, n) * hw.gain_meas
        return np.column_stack([a, b])

    def _nonlinear(self, f, v_meas, z_dut, nfft, n) -> np.ndarray:
        """Verzerrungen aus der Gegen-EMK (∝ Membrangeschwindigkeit): k2/k3 und optional Rub & Buzz."""
        _ze, zm = self._driver_parts(f, self.driver_at_level(REF_LEVEL))
        emf = np.fft.irfft(v_meas * zm / np.where(np.abs(z_dut) > 0, z_dut, 1.0), nfft)[:n]
        out = 0.015 * emf ** 2 + 0.12 * emf ** 3       # ~0,1 % Klirr bei −10 dBFS an der Resonanz
        if self.connection == "driver_rub":
            # „Schleifen“: kurzes Knacken (abklingender 3-kHz-Burst), jedes Mal wenn die Membran-
            # geschwindigkeit eine Schwelle überschreitet – kaum mehr THD, aber viele hohe Harmonische
            over = np.abs(emf) > 0.04
            hits = np.flatnonzero(over[1:] & ~over[:-1]) + 1
            if len(hits):
                fs = int(round(2 * f[-1]))
                t = np.arange(int(0.004 * fs)) / fs
                burst = np.exp(-t / 0.0006) * np.sin(2 * np.pi * 3000 * t)
                pulses = np.zeros(n)
                pulses[hits] = 0.02 * np.sign(emf[hits])
                out = out + np.convolve(pulses, burst)[:n]
        # Der quadratische Anteil enthält einen langsam schwankenden Gleichanteil (Hüllkurve²). Ein
        # echtes Interface ist wechselspannungsgekoppelt; ungefiltert erschiene er als Unruhe der
        # Impedanzkurve unterhalb von ~10 Hz. Deshalb Hochpass 4. Ordnung bei 15 Hz.
        jw = 1j * 2 * np.pi * f
        hp = (jw / (jw + 2 * np.pi * 15.0)) ** 4
        return np.fft.irfft(np.fft.rfft(out, nfft) * hp, nfft)[:n]

    def _finish(self, rec: np.ndarray) -> np.ndarray:
        noise = 10 ** (self.hw.noise_dbfs / 20)
        rec = rec + noise * self.rng.standard_normal(rec.shape)
        return np.round(np.clip(rec, -1, 32767 / 32768) * 32768) / 32768   # 16 Bit wie USB-Audio

    def play_record(self, stimulus: np.ndarray, fs: int, in_channels: int = 2) -> np.ndarray:
        rec = self._finish(self._simulate(np.asarray(stimulus, float), fs))
        if in_channels == 1:
            return rec[:, 1:2]
        return rec

    # -- Dauerbetrieb (Generator / Oszilloskop / Pegelanzeige) ------------------
    def start_stream(self, signal: np.ndarray | None, fs: int, loop: bool = True) -> None:
        sig = np.zeros(int(0.5 * fs)) if signal is None or len(signal) == 0 else np.asarray(signal, float)
        if not loop:
            sig = np.concatenate([sig, np.zeros(int(0.5 * fs))])
        self._stream = {"sig": sig, "fs": fs, "loop": loop, "t0": time.monotonic(), "key": None, "resp": None}

    def _response(self) -> np.ndarray:
        st = self._stream
        key = (self.connection, self.sample, self.level_dependent, self.distortion)
        if st["key"] != key:
            st["resp"] = self._simulate(st["sig"], st["fs"], circular=st["loop"])
            st["key"] = key
        return st["resp"]

    def read_input(self, n: int) -> np.ndarray | None:
        st = self._stream
        if st is None:
            return None
        resp = self._response()
        end = int((time.monotonic() - st["t0"]) * st["fs"])
        idx = np.arange(end - n, end)
        N = len(resp)
        if st["loop"]:
            out = resp[idx % N]
        else:
            out = np.zeros((n, 2))
            ok = (idx >= 0) & (idx < N)
            out[ok] = resp[idx[ok]]
        out[idx < 0] = 0.0
        return self._finish(out).astype(np.float32)

    @property
    def streaming(self) -> bool:
        return self._stream is not None

    @property
    def stream_fs(self) -> int | None:
        return self._stream["fs"] if self._stream else None

    def stop(self) -> None:
        self._stream = None
