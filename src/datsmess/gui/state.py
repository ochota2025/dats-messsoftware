"""Gemeinsamer Anwendungszustand und Hintergrund-Ausführung von Messungen."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from PySide6 import QtCore

from ..analysis.quality import summary
from ..audio.backend import AudioBackend
from ..audio.simulator import SimulatorBackend
from ..dsp.calibration import Calibration
from ..io import project as projio
from ..io.ts_export import DriverInfo
from ..io.watch import WatchFolderConfig, deliver
from ..measurement import Measurement, MeasurementEngine
from .appearance import appearance

log = logging.getLogger("datsmess")


class FnThread(QtCore.QThread):
    done = QtCore.Signal(object)
    error = QtCore.Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:      # noqa: BLE001 – Fehler an die Oberfläche melden
            log.exception("Fehler im Hintergrund")
            self.error.emit(f"{type(e).__name__}: {e}")


N_SLOTS = 8


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:60] or "geraet"


class AppState(QtCore.QObject):
    measurementsChanged = QtCore.Signal()
    calibrationChanged = QtCore.Signal()
    busyChanged = QtCore.Signal(bool)
    connectionChanged = QtCore.Signal(str)
    status = QtCore.Signal(str)
    projectChanged = QtCore.Signal()        # Titel / Dirty-Status / Treiberinfo
    projectLoaded = QtCore.Signal()         # komplettes Projekt ersetzt (T/S-Tab neu befüllen)
    slotsChanged = QtCore.Signal()
    progress = QtCore.Signal(int, int)      # Fortschritt längerer Abläufe (aus dem Hintergrund-Thread)
    audioStopped = QtCore.Signal()          # Generator/Oszilloskop wurde beendet
    failed = QtCore.Signal(str, str)        # Titel, Meldung – Fehler ohne eigene Behandlung

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = MeasurementEngine(SimulatorBackend())
        self.measurements: list[Measurement] = []
        self.busy = False
        self._threads: list[FnThread] = []
        self._color_i = 0
        self._counter = 0
        # Projekt
        self.info = DriverInfo()
        self.project_path: Path | None = None
        self.project_created = ""
        self.dirty = False
        self.ts_state: dict | None = None
        self.known_calibrations: dict[str, Calibration] = {}
        self.watch = WatchFolderConfig()
        self.ts_text_provider = None        # Callable[[Measurement], str | None] (T/S-Tab)
        # Speicherplätze: Messungs-ID je Platz + Sichtbarkeit
        self.slots: list[str | None] = [None] * N_SLOTS
        self.slot_visible: list[bool] = [True] * N_SLOTS
        self.auto_hide = True               # ältere, nicht abgelegte Messungen ausblenden
        self.measurementsChanged.connect(self._prune_slots)
        self.measurementsChanged.connect(self.mark_dirty)

    # -- Speicherplätze ------------------------------------------------------
    def _by_id(self, mid: str | None) -> Measurement | None:
        return next((m for m in self.measurements if m.id == mid), None) if mid else None

    def slot_measurement(self, i: int) -> Measurement | None:
        return self._by_id(self.slots[i])

    def slot_of(self, m: Measurement) -> int | None:
        return self.slots.index(m.id) if m.id in self.slots else None

    def slot_color(self, i: int) -> str:
        cols = appearance().current.colors
        return cols[i % len(cols)]

    def free_color(self, i: int) -> str:
        """Farben für nicht abgelegte Messungen – kräftig, aber anders als die 8 Platzfarben."""
        cols = appearance().current.free_colors
        return cols[i % len(cols)]

    def _prune_slots(self):
        ids = {m.id for m in self.measurements}
        if any(s is not None and s not in ids for s in self.slots):
            self.slots = [s if s in ids else None for s in self.slots]
            self.slotsChanged.emit()

    def store_in_slot(self, i: int, m: Measurement):
        """Messung auf Platz i ablegen (feste Farbe des Platzes, sichtbar)."""
        old = self.slot_of(m)
        if old is not None:
            self.slots[old] = None
        self.slots[i] = m.id
        self.slot_visible[i] = True
        m.visible = True
        m.color = self.slot_color(i)
        self.slotsChanged.emit()
        self.measurementsChanged.emit()
        self.status.emit(f"„{m.name}“ auf Speicherplatz {i + 1} abgelegt.")

    def clear_slot(self, i: int):
        m = self.slot_measurement(i)
        self.slots[i] = None
        if m is not None:
            m.visible = False
        self.slotsChanged.emit()
        self.measurementsChanged.emit()

    def toggle_slot(self, i: int, visible: bool | None = None):
        m = self.slot_measurement(i)
        self.slot_visible[i] = (not self.slot_visible[i]) if visible is None else visible
        if m is not None:
            m.visible = self.slot_visible[i]
            self.measurementsChanged.emit()
        self.slotsChanged.emit()

    def current_measurement(self) -> Measurement | None:
        return self.measurements[-1] if self.measurements else None

    # -- Projekt -------------------------------------------------------------
    def mark_dirty(self, *_):
        self.dirty = True
        self.projectChanged.emit()

    @property
    def project_title(self) -> str:
        name = self.project_path.stem if self.project_path else "Unbenannt"
        return f"{name}{' *' if self.dirty else ''}"

    def new_project(self):
        self.measurements.clear()
        self.slots = [None] * N_SLOTS
        self.slot_visible = [True] * N_SLOTS
        self.slotsChanged.emit()
        self.info = DriverInfo()
        self.project_path = None
        self.project_created = ""
        self.ts_state = None
        self._counter = 0
        self._color_i = 0
        self.measurementsChanged.emit()
        self.projectLoaded.emit()
        self.dirty = False
        self.projectChanged.emit()

    def to_project(self, settings: dict) -> projio.Project:
        p = projio.Project(info=self.info, measurements=list(self.measurements), ts=self.ts_state,
                           settings=settings,
                           slots=[{"id": s, "visible": v} for s, v in zip(self.slots, self.slot_visible)])
        if self.project_created:
            p.created = self.project_created
        cal = self.engine.calibration
        if cal is not None:
            p.add_calibration(cal)
            p.active_calibration_id = cal.id
        for m in self.measurements:
            cid = m.meta.get("calibration_id")
            if cid in self.known_calibrations:
                p.calibrations[cid] = self.known_calibrations[cid]
        return p

    def save_project(self, path: Path, settings: dict):
        p = self.to_project(settings)
        projio.save_project(path, p)
        self.project_path = Path(path)
        self.project_created = p.created
        self.dirty = False
        self.projectChanged.emit()
        self.status.emit(f"Projekt gespeichert: {path}")

    def load_project(self, path: Path) -> projio.Project:
        p = projio.load_project(path)
        self.measurements = list(p.measurements)
        ids = {m.id for m in self.measurements}
        slots = (p.slots or [])[:N_SLOTS] + [{}] * max(0, N_SLOTS - len(p.slots or []))
        self.slots = [d.get("id") if d.get("id") in ids else None for d in slots]
        self.slot_visible = [bool(d.get("visible", True)) for d in slots]
        self.slotsChanged.emit()
        self.known_calibrations.update(p.calibrations)
        self.info = p.info
        self.ts_state = p.ts
        self.project_path = Path(path)
        self.project_created = p.created
        self._counter = len(self.measurements)
        self._color_i = len(self.measurements)
        self.measurementsChanged.emit()
        self.projectLoaded.emit()
        self.dirty = False
        self.projectChanged.emit()
        n_raw = sum(m.has_raw for m in self.measurements)
        self.status.emit(f"Projekt geladen: {len(self.measurements)} Messungen ({n_raw} mit Rohdaten), "
                         f"{len(p.calibrations)} Kalibrierung(en).")
        return p

    def set_info(self, info: DriverInfo):
        self.info = info
        self.mark_dirty()

    def set_ts_state(self, ts_state: dict | None):
        self.ts_state = ts_state
        self.mark_dirty()

    # -- Watch-Folder --------------------------------------------------------
    def deliver(self, m: Measurement) -> list[Path]:
        tsp = self.ts_text_provider(m) if self.ts_text_provider else None
        files = deliver(self.watch, m, self.info, tsp)
        self.status.emit("An Watch-Folder übergeben: " + ", ".join(p.name for p in files))
        return files

    # -- Backend / Kalibrierung -------------------------------------------
    @property
    def backend(self) -> AudioBackend:
        return self.engine.backend

    @property
    def is_simulator(self) -> bool:
        return self.backend.is_simulator

    def stop_audio(self):
        try:
            self.backend.stop()
        except Exception:       # noqa: BLE001
            log.exception("Audio stoppen")
        self.audioStopped.emit()

    def set_backend(self, backend: AudioBackend):
        if self.engine.backend is not backend:
            self.stop_audio()
        log.info("Gerät: %s", backend.describe())
        self.engine.backend = backend
        self.engine.calibration = None
        self.load_calibration()

    def calibration_path(self) -> Path:
        base = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.AppDataLocation)
        return Path(base) / f"calibration_{_slug(self.backend.describe())}.npz"

    def load_calibration(self):
        p = self.calibration_path()
        if p.exists():
            try:
                self.engine.calibration = Calibration.load(p)
                self.known_calibrations[self.engine.calibration.id] = self.engine.calibration
            except Exception as e:  # noqa: BLE001
                self.status.emit(f"Kalibrierdatei konnte nicht gelesen werden: {e}")
        self.calibrationChanged.emit()

    def set_calibration(self, cal: Calibration | None):
        log.info("Kalibrierung %s", f"gesetzt: {', '.join(cal.steps)}, R_cal {cal.r_cal:g} Ω" if cal else "verworfen")
        self.engine.calibration = cal
        if cal is not None:
            self.known_calibrations[cal.id] = cal
            cal.save(self.calibration_path())
        else:
            self.calibration_path().unlink(missing_ok=True)
        self.calibrationChanged.emit()

    def set_connection(self, kind: str):
        if self.is_simulator:
            self.backend.set_connection(kind)
            self.connectionChanged.emit(kind)

    # -- Messungen -----------------------------------------------------------
    def next_name(self, prefix: str = "Messung") -> str:
        self._counter += 1
        return f"{prefix} {self._counter}"

    def add_measurement(self, m: Measurement):
        if m.color is None:
            # Farben hinter den 8 Platzfarben weiterzählen, damit es keine Verwechslung gibt
            m.color = self.free_color(self._color_i)
            self._color_i += 1
        if self.auto_hide:
            for o in self.measurements:
                slot = self.slot_of(o)
                if slot is None:
                    o.visible = False
        self.measurements.append(m)
        self.measurementsChanged.emit()

    def recolor_measurements(self):
        for i, m in enumerate(self.measurements):
            slot = self.slot_of(m)
            m.color = self.slot_color(slot) if slot is not None else self.free_color(i)
        self._color_i = len(self.measurements)
        self.measurementsChanged.emit()

    def remove_measurement(self, m: Measurement):
        if m in self.measurements:
            self.measurements.remove(m)
            self.measurementsChanged.emit()

    def clear_measurements(self):
        self.measurements.clear()
        self.measurementsChanged.emit()

    # -- Hintergrundausführung ------------------------------------------------
    def run(self, fn, on_done, on_error=None, text: str = "Messung läuft …") -> bool:
        if self.busy:
            self.status.emit("Bitte warten – es läuft bereits eine Messung.")
            return False
        if self.backend.streaming:          # Generator/Oszilloskop würde das Gerät blockieren
            self.stop_audio()
        self.busy = True
        self.busyChanged.emit(True)
        self.status.emit(text)
        th = FnThread(fn, self)
        self._threads.append(th)

        def finish():
            self.busy = False
            self.busyChanged.emit(False)
            self._threads.remove(th)
            th.deleteLater()

        def ok(result):
            finish()
            on_done(result)

        def err(msg):
            finish()
            self.status.emit(f"Fehler: {msg}")
            if on_error:
                on_error(msg)
            else:
                self.failed.emit("Messung fehlgeschlagen", msg)

        th.done.connect(ok)
        th.error.connect(err)
        th.start()
        return True

    def measure(self, name: str | None = None, connection: str | None = None, on_done=None,
                on_error=None) -> bool:
        """Impedanzmessung im Hintergrund; Ergebnis wird der Messliste hinzugefügt."""
        name = name or self.next_name()
        if connection:
            self.set_connection(connection)

        def job():
            return self.engine.measure_impedance(name)

        def done(result):
            m, raw = result
            self.add_measurement(m)
            msgs = [f"„{m.name}“ gemessen ({len(m.f)} Frequenzpunkte)"]
            if raw.quality is not None:
                msgs.append(summary(raw.quality))
                log.info("Messung „%s“: %s", m.name, summary(raw.quality))
            else:
                if raw.clipped:
                    msgs.append("WARNUNG: Übersteuerung – Pegel reduzieren!")
                if raw.peak_meas < 1e-3:
                    msgs.append("WARNUNG: kaum Signal am Messkanal – Verbindung prüfen.")
            if not self.engine.calibrated:
                msgs.append("unkalibriert")
            if self.watch.auto and self.watch.path:
                try:
                    deliver(self.watch, m, self.info, None)
                    msgs.append("→ Watch-Folder")
                except Exception as e:      # noqa: BLE001
                    msgs.append(f"Watch-Folder-Fehler: {e}")
            self.status.emit(" · ".join(msgs))
            if on_done:
                on_done(m)

        return self.run(job, done, on_error, text=f"Messe „{name}“ … ({self.engine.sweep.duration_s:.1f} s"
                                                   f" × {self.engine.sweep.averages})")
