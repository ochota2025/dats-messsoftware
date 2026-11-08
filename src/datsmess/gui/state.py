"""Gemeinsamer Anwendungszustand und Hintergrund-Ausführung von Messungen."""
from __future__ import annotations

import re
import traceback
from pathlib import Path

from PySide6 import QtCore

from ..audio.backend import AudioBackend
from ..audio.simulator import SimulatorBackend
from ..dsp.calibration import Calibration
from ..io import project as projio
from ..io.ts_export import DriverInfo
from ..io.watch import WatchFolderConfig, deliver
from ..measurement import Measurement, MeasurementEngine
from .appearance import appearance

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
            traceback.print_exc()
            self.error.emit(f"{type(e).__name__}: {e}")


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
        self.measurementsChanged.connect(self.mark_dirty)

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
                           settings=settings)
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

    def set_backend(self, backend: AudioBackend):
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
            cols = appearance().current.colors
            m.color = cols[self._color_i % len(cols)]
            self._color_i += 1
        self.measurements.append(m)
        self.measurementsChanged.emit()

    def recolor_measurements(self):
        cols = appearance().current.colors
        for i, m in enumerate(self.measurements):
            m.color = cols[i % len(cols)]
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
