"""Audio-Backends: echtes DATS-Interface über Standard-Audiotreiber und Simulator.

Das DATS V3 meldet sich als USB-Audio-Class-Gerät; unter macOS (CoreAudio),
Windows (WASAPI/DirectSound/ASIO) und Linux (ALSA/PulseAudio/PipeWire) ist
daher kein proprietärer Treiber nötig. Der Zugriff erfolgt über PortAudio
(Python-Paket ``sounddevice``).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

# Hinweise für den Simulator, was gerade an den Messklemmen hängt.
CONNECTIONS = {
    "open": "Offene Klemmen",
    "short": "Klemmen kurzgeschlossen",
    "cal": "Kalibrierwiderstand",
    "driver": "Treiber (Freiluft)",
    "driver_mass": "Treiber + Zusatzmasse",
    "driver_box": "Treiber im Testgehäuse",
    "resistor": "Widerstand",
    "capacitor": "Kondensator",
    "inductor": "Spule",
}


class AudioBackend(ABC):
    name = "abstract"
    is_simulator = False

    @abstractmethod
    def play_record(self, stimulus: np.ndarray, fs: int, in_channels: int = 2) -> np.ndarray:
        """Spielt ``stimulus`` (mono) auf allen Ausgängen und nimmt synchron auf.

        Rückgabe: Array (len(stimulus), in_channels), float, Vollaussteuerung = 1.
        """

    def play(self, signal: np.ndarray, fs: int, loop: bool = True) -> None:
        """Signalgenerator-Wiedergabe (nicht blockierend)."""

    def stop(self) -> None:
        pass

    def set_connection(self, kind: str) -> None:
        """Nur für den Simulator relevant – echte Hardware ignoriert das."""

    def describe(self) -> str:
        return self.name


@dataclass
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    max_in: int
    max_out: int
    default_fs: float

    @property
    def label(self) -> str:
        return f"{self.name} ({self.hostapi}) – {self.max_in} ein / {self.max_out} aus"

    @property
    def looks_like_dats(self) -> bool:
        n = self.name.lower()
        return "dats" in n or "dayton" in n


def list_devices() -> list[DeviceInfo]:
    try:
        import sounddevice as sd
    except Exception:          # PortAudio fehlt
        return []
    apis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        out.append(DeviceInfo(i, d["name"], apis[d["hostapi"]]["name"], d["max_input_channels"],
                              d["max_output_channels"], d["default_samplerate"]))
    return out


def find_dats(devices: list[DeviceInfo] | None = None) -> DeviceInfo | None:
    for d in devices if devices is not None else list_devices():
        if d.looks_like_dats and d.max_in > 0 and d.max_out > 0:
            return d
    return None


class SoundDeviceBackend(AudioBackend):
    name = "Audio-Gerät"

    def __init__(self, input_device: int | None, output_device: int | None):
        import sounddevice as sd
        self._sd = sd
        self.input_device = input_device
        self.output_device = output_device

    def describe(self) -> str:
        try:
            i = self._sd.query_devices(self.input_device, "input")["name"]
            o = self._sd.query_devices(self.output_device, "output")["name"]
            return i if i == o else f"{i} / {o}"
        except Exception:
            return "Audio-Gerät"

    def _out_channels(self) -> int:
        info = self._sd.query_devices(self.output_device, "output")
        return min(2, int(info["max_output_channels"]))

    def _in_channels(self, wanted: int) -> int:
        info = self._sd.query_devices(self.input_device, "input")
        return min(wanted, int(info["max_input_channels"]))

    def play_record(self, stimulus: np.ndarray, fs: int, in_channels: int = 2) -> np.ndarray:
        n_out = self._out_channels()
        out = np.tile(stimulus.astype(np.float32)[:, None], (1, n_out))
        n_in = self._in_channels(in_channels)
        rec = self._sd.playrec(out, samplerate=fs, channels=n_in, dtype="float32",
                               device=(self.input_device, self.output_device), blocking=True)
        rec = np.asarray(rec, dtype=float)
        if rec.shape[1] < in_channels:
            rec = np.hstack([rec, np.zeros((rec.shape[0], in_channels - rec.shape[1]))])
        return rec

    def play(self, signal: np.ndarray, fs: int, loop: bool = True) -> None:
        n_out = self._out_channels()
        data = np.tile(signal.astype(np.float32)[:, None], (1, n_out))
        self._sd.play(data, samplerate=fs, device=self.output_device, loop=loop)

    def stop(self) -> None:
        self._sd.stop()
