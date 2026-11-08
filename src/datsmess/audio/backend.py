"""Audio-Backends: echtes DATS-Interface über Standard-Audiotreiber und Simulator.

Das DATS V3 meldet sich als USB-Audio-Class-Gerät; unter macOS (CoreAudio),
Windows (WASAPI/DirectSound/ASIO) und Linux (ALSA/PulseAudio/PipeWire) ist
daher kein proprietärer Treiber nötig. Der Zugriff erfolgt über PortAudio
(Python-Paket ``sounddevice``).
"""
from __future__ import annotations

import threading
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
    "driver_rub": "Treiber mit Schleifgeräusch",
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
        """Signalgenerator-Wiedergabe (nicht blockierend) – Eingänge laufen für das Oszilloskop mit."""
        self.start_stream(signal, fs, loop)

    # -- Dauerbetrieb (Generator, Oszilloskop, Pegelanzeige) -------------------
    def start_stream(self, signal: np.ndarray | None, fs: int, loop: bool = True) -> None:
        """Spielt ``signal`` (oder Stille) und nimmt fortlaufend beide Eingänge auf."""

    def read_input(self, n: int) -> np.ndarray | None:
        """Die letzten ``n`` aufgenommenen Samples (n, 2) – ``None``, wenn kein Strom läuft."""
        return None

    @property
    def streaming(self) -> bool:
        return False

    @property
    def stream_fs(self) -> int | None:
        return None

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
        self.stop()                 # laufender Generator/Oszilloskop-Strom würde das Gerät blockieren
        n_out = self._out_channels()
        out = np.tile(stimulus.astype(np.float32)[:, None], (1, n_out))
        n_in = self._in_channels(in_channels)
        rec = self._sd.playrec(out, samplerate=fs, channels=n_in, dtype="float32",
                               device=(self.input_device, self.output_device), blocking=True)
        rec = np.asarray(rec, dtype=float)
        if rec.shape[1] < in_channels:
            rec = np.hstack([rec, np.zeros((rec.shape[0], in_channels - rec.shape[1]))])
        return rec

    # -- Dauerbetrieb ----------------------------------------------------------
    _stream = None

    def start_stream(self, signal: np.ndarray | None, fs: int, loop: bool = True) -> None:
        self.stop()
        n_out = self._out_channels()
        n_in = self._in_channels(2)
        sig = np.zeros(1, np.float32) if signal is None else np.asarray(signal, np.float32)
        ring = RingBuffer(int(fs * 2), 2)
        pos = [0]

        def callback(indata, outdata, frames, _time, _status):
            ring.write(indata[:, :n_in])
            i = pos[0]
            if signal is None:
                out = np.zeros(frames, np.float32)
            elif loop:
                idx = (np.arange(frames) + i) % len(sig)
                out = sig[idx]
            else:
                out = np.zeros(frames, np.float32)
                k = max(0, min(frames, len(sig) - i))
                out[:k] = sig[i:i + k]
            pos[0] = i + frames
            outdata[:] = out[:, None]

        st = self._sd.Stream(samplerate=fs, device=(self.input_device, self.output_device),
                             channels=(n_in, n_out), dtype="float32", callback=callback)
        st.start()
        self._stream, self._ring, self._fs = st, ring, fs

    def read_input(self, n: int) -> np.ndarray | None:
        if self._stream is None:
            return None
        return self._ring.read(n)

    @property
    def streaming(self) -> bool:
        return self._stream is not None

    @property
    def stream_fs(self) -> int | None:
        return self._fs if self._stream is not None else None

    def stop(self) -> None:
        st, self._stream = self._stream, None
        if st is not None:
            try:
                st.stop()
                st.close()
            except Exception:       # noqa: BLE001
                pass
        self._sd.stop()


class RingBuffer:
    """Thread-sicherer Ringpuffer für Eingangssamples (Audio-Callback schreibt, GUI liest)."""

    def __init__(self, size: int, channels: int):
        self.buf = np.zeros((size, channels), np.float32)
        self.pos = 0
        self.filled = 0
        self.lock = threading.Lock()

    def write(self, block: np.ndarray) -> None:
        block = np.asarray(block, np.float32)
        n, size = len(block), len(self.buf)
        if n == 0:
            return
        with self.lock:
            if n >= size:
                block, n = block[-size:], size
            c = block.shape[1]
            end = self.pos + n
            if end <= size:
                self.buf[self.pos:end, :c] = block
            else:
                k = size - self.pos
                self.buf[self.pos:, :c] = block[:k]
                self.buf[:n - k, :c] = block[k:]
            self.pos = end % size
            self.filled = min(size, self.filled + n)

    def read(self, n: int) -> np.ndarray:
        with self.lock:
            n = min(n, len(self.buf))
            idx = (np.arange(self.pos - n, self.pos)) % len(self.buf)
            out = self.buf[idx].copy()
            if self.filled < n:
                out[: n - self.filled] = 0.0
            return out
