"""Virtuelles DATS-Interface.

Simuliert die Messbrücke inklusive typischer Fehlerquellen, damit Software,
Kalibrierung und Auswertung ohne Hardware entwickelt und geprüft werden können:

* Referenz-Serienwiderstand, Eingangswiderstand des Messkanals
* unterschiedliche Kanalverstärkung, AC-Kopplung (Hochpass) je Kanal
* Kabel- und Übergangswiderstand + Leitungsinduktivität
* Latenz, 16-Bit-Quantisierung, Rauschen
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .backend import AudioBackend


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

    def impedance(self, f: np.ndarray, added_mass: float = 0.0, box_volume: float | None = None) -> np.ndarray:
        w = 2 * np.pi * np.maximum(f, 1e-3)
        cms = self.Cms
        if box_volume:
            cmb = box_volume / (1.204 * 343.2 ** 2 * self.Sd ** 2)
            cms = cms * cmb / (cms + cmb)
        zmech = self.Rms + 1j * w * (self.Mms + added_mass) + 1 / (1j * w * cms)
        return self.Re + self.Kr * w ** self.Xr + 1j * self.Ki * w ** self.Xi + self.Bl ** 2 / zmech


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

    def set_connection(self, kind: str) -> None:
        self.connection = kind

    def dut_impedance(self, f: np.ndarray) -> np.ndarray:
        w = 2 * np.pi * np.maximum(f, 1e-3)
        c = self.connection
        if c == "open":
            return np.full(f.shape, 1e12 + 0j)
        if c == "short":
            return np.zeros(f.shape, complex)
        if c == "cal":
            return np.full(f.shape, self.hw.r_cal + 0j)
        if c == "driver":
            return self.driver.impedance(f)
        if c == "driver_mass":
            return self.driver.impedance(f, added_mass=self.added_mass)
        if c == "driver_box":
            return self.driver.impedance(f, box_volume=self.box_volume)
        if c == "resistor":
            return self.resistor + 1j * w * 0.8e-6
        if c == "capacitor":
            return self.cap_esr + 1 / (1j * w * self.capacitor) + 1j * w * 20e-9
        if c == "inductor":
            return self.inductor_dcr + 1j * w * self.inductor
        raise ValueError(c)

    def play_record(self, stimulus: np.ndarray, fs: int, in_channels: int = 2) -> np.ndarray:
        hw = self.hw
        n = len(stimulus)
        nfft = 1 << int(np.ceil(np.log2(n + hw.latency + 1024)))
        f = np.fft.rfftfreq(nfft, 1 / fs)
        X = np.fft.rfft(stimulus, nfft)
        jw = 1j * 2 * np.pi * f

        def hp(fc):
            return jw / (jw + 2 * np.pi * fc)

        z_dut = self.dut_impedance(f)
        z_term = z_dut + hw.lead_r + jw * hw.lead_l
        z_eff = z_term * hw.r_in / (z_term + hw.r_in)
        divider = z_eff / (hw.r_series + z_eff)
        delay = np.exp(-jw * hw.latency / fs)
        v_src = X * hp(hw.hp_out) * delay
        a = np.fft.irfft(v_src * hw.gain_ref * hp(hw.hp_ref), nfft)[:n]
        b = np.fft.irfft(v_src * divider * hw.gain_meas * hp(hw.hp_meas), nfft)[:n]
        noise = 10 ** (hw.noise_dbfs / 20)
        rec = np.column_stack([a, b]) + noise * self.rng.standard_normal((n, 2))
        rec = np.round(np.clip(rec, -1, 32767 / 32768) * 32768) / 32768   # 16 Bit wie USB-Audio
        if in_channels == 1:
            return rec[:, 1:2]
        return rec

    def play(self, signal: np.ndarray, fs: int, loop: bool = True) -> None:
        pass
