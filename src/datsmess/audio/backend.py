"""Audio-Backends: echtes DATS-Interface über Standard-Audiotreiber und Simulator.

Das DATS V3 meldet sich als USB-Audio-Class-Gerät; unter macOS (CoreAudio),
Windows (WASAPI/DirectSound/ASIO) und Linux (ALSA/PulseAudio/PipeWire) ist
daher kein proprietärer Treiber nötig. Der Zugriff erfolgt über PortAudio
(Python-Paket ``sounddevice``).
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

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


def rescan_devices() -> bool:
    """PortAudio neu initialisieren: Die Geräteliste wird nur beim Initialisieren gelesen, neu
    eingesteckte Geräte (z. B. das DATS) erscheinen sonst erst nach einem Programmneustart.
    Vorher alle Audioströme stoppen."""
    try:
        import sounddevice as sd
        sd._terminate()
        sd._initialize()
        return True
    except Exception:          # noqa: BLE001
        return False


def find_dats(devices: list[DeviceInfo] | None = None) -> DeviceInfo | None:
    for d in devices if devices is not None else list_devices():
        if d.looks_like_dats and d.max_in > 0 and d.max_out > 0:
            return d
    return None


# --------------------------------------------------------------------------
# Geräteauswahl: Ein- und Ausgang zusammenführen, beste Treiber-Schnittstelle wählen
# --------------------------------------------------------------------------
#
# Windows meldet USB-Audiogeräte (auch das DATS) bei MME, DirectSound und WASAPI als *zwei* Geräte:
# „Lautsprecher (Gerät)“ nur mit Ausgang und „Mikrofon (Gerät)“ nur mit Eingang – und das für jede
# Schnittstelle noch einmal. Für die Auswahl werden Ein- und Ausgang desselben Geräts (gleicher Name
# in Klammern, gleiche Schnittstelle) zu einem Eintrag zusammengefasst; je Gerät bleibt der Eintrag
# der besten Schnittstelle, die die Abtastrate kann. WASAPI liefert die Daten ohne Umweg über den
# alten MME-Mixer (der Namen auf 31 Zeichen kürzt und ggf. umrechnet).

HOSTAPI_RANK = {"Windows WASAPI": 0, "Core Audio": 0, "ALSA": 0, "JACK Audio Connection Kit": 1,
                "Windows DirectSound": 2, "MME": 3, "Windows WDM-KS": 4}
# Sammel-/Ersatzeinträge der Treiber, die kein echtes Gerät sind
PSEUDO_DEVICES = ("microsoftsoundmapper", "primärersound", "primarysound", "soundmapper")


def is_pseudo(name: str) -> bool:
    """Sammel-/Ersatzeinträge wie „Microsoft Sound Mapper - Input“ oder „Primärer Soundtreiber“."""
    return "".join(name.lower().split()).startswith(PSEUDO_DEVICES)


def device_key(name: str) -> str:
    """Gerätename ohne Schnittstelle (MME kürzt auf 31 Zeichen) – zum Zusammenfassen."""
    return " ".join(name[:31].split()).lower()


def physical_name(name: str) -> str:
    """„Lautsprecher (Realtek(R) Audio)“ → „Realtek(R) Audio“ (auch bei von MME gekürzten Namen)."""
    i = name.find("(")
    if i < 0:
        return name.strip()
    inner = name[i + 1:].strip()
    if inner.endswith(")") and inner.count("(") < inner.count(")"):
        inner = inner[:-1]
    inner = inner.strip()
    if not inner or all(ch in "0123456789abcdefABCDEF- " for ch in inner):
        return name[:i].strip() or name.strip()     # „Babyface Pro (71994324)“: Klammer = Seriennummer
    return inner


@dataclass
class DeviceChoice:
    """Ein Eintrag der Geräteauswahl (Eingang und Ausgang können verschiedene Geräte sein)."""
    inp: DeviceInfo | None
    out: DeviceInfo | None
    hostapi: str
    usable: bool                      # auswählbar
    reason: str                       # Erklärung für den Tooltip
    alternatives: list[str] = field(default_factory=list)
    marked: bool = False              # vom Nutzer bzw. Geräte-Check als DATS bestätigt

    @property
    def is_dats(self) -> bool:
        return self.marked or any(d is not None and d.looks_like_dats for d in (self.inp, self.out))

    @property
    def dimmed(self) -> bool:
        """Auswählbar, aber kein DATS erkannt (z. B. eingebaute Soundkarte) → grau darstellen."""
        return self.usable and not self.is_dats

    @property
    def indices(self) -> tuple[int, int] | None:
        return (self.inp.index, self.out.index) if self.usable else None

    @property
    def name(self) -> str:
        if self.inp is not None and self.out is not None and self.inp.index != self.out.index:
            return physical_name(self.out.name)
        return (self.inp or self.out).name

    @property
    def key(self) -> str:
        if self.usable:
            return "pair|" + device_key(physical_name(self.out.name)) + "|" + device_key(self.out.name)
        d = self.inp or self.out
        return "single|" + device_key(d.name)

    @property
    def label(self) -> str:
        if not self.usable:
            d = self.inp or self.out
            return f"{d.name} – {'nur Ausgang' if self.inp is None else 'nur Eingang'}"
        star = "★ " if self.is_dats else ""
        return f"{star}{self.name} ({self.hostapi})"


def _supports(sd, inp: DeviceInfo, out: DeviceInfo, fs: int) -> bool:
    try:
        sd.check_input_settings(device=inp.index, channels=min(2, inp.max_in), samplerate=fs)
        sd.check_output_settings(device=out.index, channels=min(2, out.max_out), samplerate=fs)
        return True
    except Exception:       # noqa: BLE001
        return False


def _pair_reason(inp: DeviceInfo, out: DeviceInfo, api: str, ok_fs: bool, fs: int) -> str:
    if inp.index == out.index:
        lines = [inp.name, f"Schnittstelle: {api}, {inp.max_in} Eingänge / {out.max_out} Ausgänge"]
    else:
        lines = [physical_name(out.name), f"Schnittstelle: {api}",
                 f"Ausgang: {out.name} ({out.max_out} Kanäle)", f"Eingang: {inp.name} ({inp.max_in} Kanäle)"]
    if not ok_fs:
        lines.append(f"Achtung: {fs / 1000:g} kHz werden laut Treiber nicht unterstützt – andere Abtastrate wählen.")
    if inp.looks_like_dats or out.looks_like_dats:
        lines.append("DATS erkannt – dieses Gerät zum Messen verwenden.")
    else:
        lines.append("Kein DATS erkannt. Ausgabe und Aufnahme funktionieren (z. B. für Generator und "
                     "Oszilloskop), aber Impedanzen lassen sich nur mit der Messbrücke des DATS messen.")
        if inp.max_in < 2:
            lines.append("Nur ein Eingang – für die Messbrücke werden zwei gebraucht.")
    return "\n".join(lines)


def device_choices(devices: list[DeviceInfo], fs: int, supports=None,
                   dats_keys=frozenset()) -> list[DeviceChoice]:
    """Einträge für die Geräteauswahl. ``supports(inp, out, fs)`` ist für Tests austauschbar;
    ``dats_keys`` sind Geräte, die als DATS bestätigt wurden (auch wenn der Name es nicht verrät)."""
    if supports is None:
        try:
            import sounddevice as sd
            supports = lambda i, o, rate: _supports(sd, i, o, rate)     # noqa: E731
        except Exception:   # noqa: BLE001
            supports = lambda i, o, rate: True                          # noqa: E731
    devices = [d for d in devices if not is_pseudo(d.name)]

    # 1) Kandidaten je Schnittstelle: Vollduplex-Geräte und Paare (Mikrofon + Lautsprecher desselben Geräts)
    pairs: list[tuple[DeviceInfo, DeviceInfo]] = []
    paired: set[int] = set()
    for d in devices:
        if d.max_in >= 1 and d.max_out >= 1:
            pairs.append((d, d))
            paired.add(d.index)
    groups: dict[tuple[str, str], list[DeviceInfo]] = {}
    for d in devices:
        if d.index not in paired:
            groups.setdefault((d.hostapi, device_key(physical_name(d.name))), []).append(d)
    for members in groups.values():
        ins = sorted((d for d in members if d.max_in >= 1), key=lambda d: -d.max_in)
        outs = [d for d in members if d.max_out >= 1]
        if ins and outs:
            for o in outs:
                pairs.append((ins[0], o))
                paired.update({ins[0].index, o.index})

    # 2) je Gerät die beste Schnittstelle (die die Abtastrate kann)
    best: dict[str, tuple] = {}
    for inp, out in pairs:
        k = device_key(physical_name(out.name)) + "|" + device_key(out.name if inp is not out else out.name)
        ok = supports(inp, out, fs)
        rank = (not ok, HOSTAPI_RANK.get(out.hostapi, 5), -len(out.name))
        entry = best.get(k)
        apis = (entry[3] if entry else set()) | {out.hostapi}
        if entry is None or rank < entry[0]:
            best[k] = (rank, inp, out, apis, ok)
        else:
            best[k] = (*entry[:3], apis, entry[4])
    out_list = [DeviceChoice(inp, out, out.hostapi, True, _pair_reason(inp, out, out.hostapi, ok, fs),
                             sorted(a for a in apis if a != out.hostapi))
                for _rank, inp, out, apis, ok in best.values()]

    for c in out_list:
        if c.key in dats_keys:
            c.marked = True
            c.reason = c.reason.replace("Kein DATS erkannt.", "Als DATS bestätigt.")

    # 3) übrig gebliebene reine Ein- oder Ausgänge: anzeigen, aber nicht auswählbar
    singles: dict[str, DeviceInfo] = {}
    for d in sorted(devices, key=lambda d: HOSTAPI_RANK.get(d.hostapi, 5)):
        if d.index in paired:
            continue
        if d.hostapi == "Windows WDM-KS":
            continue        # dieselbe Hardware wie bei MME/WASAPI, nur unter anderem Namen – Dublette
        singles.setdefault(device_key(d.name), d)
    taken = {device_key(c.out.name) for c in out_list} | {device_key(c.inp.name) for c in out_list}
    for k, d in singles.items():
        if k in taken:
            continue
        if d.max_in == 0:
            reason = (f"{d.name} hat nur einen Ausgang (Lautsprecher/Kopfhörer).\n"
                      "Zum Messen braucht es Ein- und Ausgang mit Messbrücke – das DATS.\n"
                      "Die eingebaute Soundkarte meldet Windows als getrennte Geräte (Lautsprecher und Mikrofon).")
            out_list.append(DeviceChoice(None, d, d.hostapi, False, reason))
        else:
            reason = (f"{d.name} hat nur einen Eingang (Mikrofon).\n"
                      "Zum Messen braucht es Ein- und Ausgang mit Messbrücke – das DATS.\n"
                      "Eingebaute Mikrofone sind meist einkanalig und regeln den Pegel automatisch.")
            out_list.append(DeviceChoice(d, None, d.hostapi, False, reason))
    out_list.sort(key=lambda c: (not c.usable, not c.is_dats, c.name.lower()))
    return out_list


def latency_of(stimulus: np.ndarray, rec: np.ndarray) -> int | None:
    """Verzögerung der Aufnahme gegenüber dem Stimulus (Samples) – aus dem lautesten Eingangskanal.
    ``None``, wenn praktisch kein Signal ankam (dann lässt sich nichts ausrichten)."""
    from ..dsp.transfer import estimate_delay
    rec = np.asarray(rec, dtype=float)
    if rec.ndim == 1:
        rec = rec[:, None]
    rms = np.sqrt(np.mean(np.square(rec), axis=0))
    if not len(rms) or float(np.max(rms)) < 1e-5:
        return None
    return estimate_delay(np.asarray(stimulus, dtype=float), rec[:, int(np.argmax(rms))])


def align_recording(rec: np.ndarray, n: int, latency: int | None, margin: int) -> np.ndarray:
    """Schneidet aus einer (längeren) Aufnahme ``n`` Samples so heraus, dass nur noch ``margin``
    Samples Latenz übrig bleiben – Vorlauf, Sweep und Nachlauf liegen dann wie im Stimulus."""
    rec = np.asarray(rec, dtype=float)
    start = 0 if latency is None else max(0, latency - margin)
    start = min(start, max(0, len(rec) - n))
    out = rec[start:start + n]
    if len(out) < n:
        out = np.vstack([out, np.zeros((n - len(out), rec.shape[1]))])
    return out


class SoundDeviceBackend(AudioBackend):
    name = "Audio-Gerät"

    def __init__(self, input_device: int | None, output_device: int | None, label: str | None = None):
        import sounddevice as sd
        self._sd = sd
        self.input_device = input_device
        self.output_device = output_device
        self.label = label

    def describe(self) -> str:
        if self.label:
            return self.label
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

    # Unter Windows (MME/DirectSound) liegen zwischen Ausgabe und Aufnahme oft 0,3–0,6 s. Ohne
    # Nachlauf fehlte das Ende des Sweeps – also die höchsten Frequenzen – in der Aufnahme.
    PAD_S = 1.0                     # zusätzliche Aufnahmezeit (mindestens)
    MARGIN_S = 0.01                 # so viel Vorlauf bleibt nach dem Latenzausgleich stehen
    last_latency: int | None = None  # gemessene Latenz Ausgang → Eingang (Samples) der letzten Aufnahme

    def _playrec(self, stimulus: np.ndarray, fs: int, n_in: int) -> np.ndarray:
        n_out = self._out_channels()
        out = np.tile(stimulus.astype(np.float32)[:, None], (1, n_out))
        rec = self._sd.playrec(out, samplerate=fs, channels=n_in, dtype="float32",
                               device=(self.input_device, self.output_device), blocking=True)
        return np.asarray(rec, dtype=float)

    def play_record(self, stimulus: np.ndarray, fs: int, in_channels: int = 2) -> np.ndarray:
        self.stop()                 # laufender Generator/Oszilloskop-Strom würde das Gerät blockieren
        n = len(stimulus)
        n_in = self._in_channels(in_channels)
        prev = self.last_latency or 0
        pad = int(fs * self.PAD_S) + int(1.5 * prev)
        for _attempt in range(2):
            rec = self._playrec(np.concatenate([stimulus, np.zeros(pad)]), fs, n_in)
            lat = latency_of(stimulus, rec)
            if lat is None or lat <= pad:
                break
            pad = int(1.5 * lat) + int(0.2 * fs)    # Latenz größer als gedacht → länger aufnehmen
        self.last_latency = lat
        rec = align_recording(rec, n, lat, int(self.MARGIN_S * fs))
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
