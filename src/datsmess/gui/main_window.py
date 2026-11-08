"""Hauptfenster: Dashboard mit Hardware-, Kalibrier- und Messbereich (ANR-03)."""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__, diagnostics, updates
from ..audio.backend import CONNECTIONS, SoundDeviceBackend, find_dats, list_devices
from ..audio.simulator import SimulatorBackend
from ..io import project as projio
from ..io.watch import WatchFolderConfig
from ..measurement import ChannelConfig
from . import errors, help as helpdlg
from .appearance import AppearanceDialog, appearance
from .calibration_wizard import CalibrationWizard
from .compare_tab import CompareTab
from .correction_tab import CorrectionTab
from .datasheet import DatasheetDialog
from .de import ask
from .device_check import DeviceCheckWizard
from .dialogs import ProjectInfoDialog, WatchFolderDialog
from .distortion_tab import DistortionTab
from .generator_tab import GeneratorTab
from .icon import create_desktop_shortcut, icon_pixmap, shortcut_supported
from .impedance_tab import ImpedanceTab
from .lcr_tab import LCRTab
from .level_tab import LevelTab
from .state import N_SLOTS, AppState
from .ts_tab import TSTab

log = logging.getLogger("datsmess")

SWEEP_LENGTHS = {15: "kurz (≈ 0,7 s)", 16: "mittel (≈ 1,4 s)", 17: "standard (≈ 2,7 s)", 18: "lang (≈ 5,5 s)"}
MAX_RECENT = 8
AUTOSAVE_MS = 120_000


class _UpdateRelay(QtCore.QObject):
    result = QtCore.Signal(object, object, bool)       # RemoteInfo | None, Fehler | None, manuell


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"DATS-Messsoftware {__version__}")
        self.resize(1400, 880)
        self.settings = QtCore.QSettings()
        self.state = AppState(self)
        self._sim = SimulatorBackend()
        self._sim.level_dependent = True        # Pegelreihe zeigt sichtbare Änderungen
        self._sim.distortion = True             # Klirr-Tab hat etwas zu zeigen
        self._autosave_busy = False

        self._build_sidebar()
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.imp_tab = ImpedanceTab(self.state)
        self.ts_tab = TSTab(self.state)
        self.ts_tab.datasheetRequested.connect(lambda: self.open_datasheet())
        self.level_tab = LevelTab(self.state)
        self.compare_tab = CompareTab(self.state)
        self.corr_tab = CorrectionTab(self.state)
        self.dist_tab = DistortionTab(self.state)
        self.lcr_tab = LCRTab(self.state)
        self.gen_tab = GeneratorTab(self.state)
        for w, name in ((self.imp_tab, "Impedanz"), (self.ts_tab, "T/S-Parameter"), (self.level_tab, "Pegelreihe"),
                        (self.compare_tab, "Vergleich"), (self.corr_tab, "Korrektur"),
                        (self.dist_tab, "Klirr && Rub/Buzz"), (self.lcr_tab, "Bauteile (LCR)"),
                        (self.gen_tab, "Generator && Oszilloskop")):
            self.tabs.addTab(w, name)

        split = QtWidgets.QSplitter()
        split.addWidget(self.sidebar_scroll)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        split.setSizes([365, 1035])
        self.setCentralWidget(split)
        self._build_menu()

        self.status_label = QtWidgets.QLabel()
        self.statusBar().addWidget(self.status_label, 1)
        self.version_label = QtWidgets.QLabel(f"Version {__version__}")
        self.version_label.setStyleSheet("color: palette(placeholder-text); padding: 0 8px;")
        self.statusBar().addPermanentWidget(self.version_label)
        self.state.status.connect(self.status_label.setText)
        self.state.calibrationChanged.connect(self._update_cal_status)
        self.state.busyChanged.connect(self._busy)
        self.state.progress.connect(self._progress)
        self.state.connectionChanged.connect(self._sync_connection)
        self.state.projectChanged.connect(self._update_title)
        self.state.failed.connect(lambda title, msg: errors.show_error(self, title, msg))
        appearance().changed.connect(self._appearance_changed)
        self.imp_tab.slot_bar.useForTS.connect(self._slot_for_ts)
        self.imp_tab.slot_bar.exportSlot.connect(
            lambda i: self.imp_tab.export_selected([self.state.slot_measurement(i)]))
        errors.context_provider = self.report_context

        self._restore_settings()
        self._populate_devices(select_saved=True)
        self.state.dirty = False
        self._update_title()
        self.state.status.emit("Bereit.")

        self._autosave_timer = QtCore.QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_MS)
        self._autosave_timer.timeout.connect(self.autosave)
        self._autosave_timer.start()
        self._update_relay = _UpdateRelay()
        self._update_relay.result.connect(self._update_result)

    # -- Start ------------------------------------------------------------------
    def after_start(self):
        """Einmalige Hinweise nach dem ersten Anzeigen des Fensters (nicht blockierend für den Start)."""
        QtCore.QTimer.singleShot(300, self._startup_tasks)

    def _startup_tasks(self):
        if self._autosave_path().exists():
            self._offer_restore()
        last = self.settings.value("last_version", "")
        if not last:
            helpdlg.show_guide(self)
        elif last != __version__ and updates.is_newer(__version__, str(last)):
            helpdlg.show_whats_new(self, str(last))
        self.settings.setValue("last_version", __version__)
        if shortcut_supported() and not self.settings.value("desktop_shortcut_done", False, type=bool):
            self.settings.setValue("desktop_shortcut_done", True)
            threading.Thread(target=create_desktop_shortcut, daemon=True).start()
        if self.act_update_auto.isChecked() and not os.environ.get("DATSMESS_NO_UPDATE_CHECK"):
            self.check_updates(manual=False)

    # -- Projekt (FS-04) -----------------------------------------------------
    def _update_title(self):
        info = self.state.info.title
        extra = f" – {info}" if info != "Treiber" else ""
        self.setWindowTitle(f"{self.state.project_title}{extra} – DATS-Messsoftware {__version__}")

    def _project_settings(self) -> dict:
        eng = self.state.engine
        return {"sweep": eng.sweep.to_dict(), "channels": eng.channels.to_dict(),
                "device": self.state.backend.describe()}

    def _confirm_discard(self) -> bool:
        if not self.state.dirty or not self.state.measurements:
            return True
        r = ask(self, "Ungespeicherte Änderungen", "Das aktuelle Projekt wurde geändert. Speichern?",
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Save)
        if r == QtWidgets.QMessageBox.Save:
            return self.save_project()
        return r == QtWidgets.QMessageBox.Discard

    def new_project(self):
        if self._confirm_discard():
            self.state.new_project()
            self._remove_autosave()

    def open_project(self, path: str | None = None):
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Projekt öffnen", self._project_dir(),
                                                            f"DATS-Projekt (*{projio.EXTENSION})")
        if not path:
            return
        try:
            self.state.load_project(Path(path))
        except Exception as e:      # noqa: BLE001
            log.exception("Projekt öffnen: %s", path)
            errors.show_error(self, "Projekt öffnen", f"Projekt konnte nicht geladen werden:\n{e}")
            return
        self._add_recent(Path(path))
        self._remove_autosave()

    def save_project(self, ask: bool = False) -> bool:
        path = self.state.project_path
        if ask or path is None:
            default = str(Path(self._project_dir()) / (
                (self.state.info.title.replace(" ", "_") if self.state.info.title != "Treiber" else "Messprojekt")
                + projio.EXTENSION))
            p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Projekt speichern", default,
                                                         f"DATS-Projekt (*{projio.EXTENSION})")
            if not p:
                return False
            path = Path(p if p.endswith(projio.EXTENSION) else p + projio.EXTENSION)
        try:
            self.state.save_project(path, self._project_settings())
        except Exception as e:      # noqa: BLE001
            log.exception("Projekt speichern: %s", path)
            errors.show_error(self, "Projekt speichern", str(e))
            return False
        self.settings.setValue("project_dir", str(path.parent))
        self._add_recent(path)
        self._remove_autosave()
        return True

    def _project_dir(self) -> str:
        return str(self.settings.value("project_dir", str(Path.home())))

    # -- Zuletzt geöffnet ------------------------------------------------------
    def _recent(self) -> list[str]:
        try:
            return [p for p in json.loads(self.settings.value("recent_projects", "[]")) if isinstance(p, str)]
        except (ValueError, TypeError):
            return []

    def _add_recent(self, path: Path):
        items = [str(path)] + [p for p in self._recent() if p != str(path)]
        self.settings.setValue("recent_projects", json.dumps(items[:MAX_RECENT]))

    def _fill_recent_menu(self):
        self.m_recent.clear()
        items = self._recent()
        if not items:
            a = self.m_recent.addAction("(noch keine)")
            a.setEnabled(False)
            return
        for i, p in enumerate(items):
            a = self.m_recent.addAction(f"&{i + 1}  {Path(p).name}", lambda p=p: self.open_project(p))
            a.setToolTip(p)
            a.setEnabled(Path(p).exists())
        self.m_recent.addSeparator()
        self.m_recent.addAction("Liste leeren", lambda: self.settings.setValue("recent_projects", "[]"))

    # -- Automatisches Sichern -----------------------------------------------------
    def _autosave_path(self) -> Path:
        base = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.AppDataLocation)
        return Path(base) / "autosave.datsproj"

    def autosave(self):
        if self._autosave_busy or self.state.busy or not self.state.dirty or not self.state.measurements:
            return
        project = self.state.to_project(self._project_settings())
        target = self._autosave_path()
        origin = str(self.state.project_path or "")
        self._autosave_busy = True

        def work():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(".tmp")
                projio.save_project(tmp, project)
                os.replace(tmp, target)
                log.info("Automatisch gesichert (%d Messungen)", len(project.measurements))
            except Exception:       # noqa: BLE001
                log.exception("Automatisches Sichern")
            finally:
                self._autosave_busy = False

        self.settings.setValue("autosave_origin", origin)
        threading.Thread(target=work, daemon=True).start()

    def _remove_autosave(self):
        try:
            self._autosave_path().unlink(missing_ok=True)
        except OSError:
            pass

    def _offer_restore(self):
        r = ask(self, "Messungen wiederherstellen?",
                "Das Programm wurde beim letzten Mal nicht normal beendet. Es gibt eine automatische "
                "Sicherung mit ungespeicherten Messungen.<br><br>Wiederherstellen?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.Yes)
        if r == QtWidgets.QMessageBox.Yes:
            try:
                self.state.load_project(self._autosave_path())
                origin = self.settings.value("autosave_origin", "")
                self.state.project_path = Path(origin) if origin else None
                self.state.mark_dirty()
                self.state.status.emit("Automatische Sicherung wiederhergestellt – bitte speichern.")
                log.info("Automatische Sicherung wiederhergestellt")
                return
            except Exception as e:      # noqa: BLE001
                log.exception("Wiederherstellen")
                errors.show_error(self, "Wiederherstellen", f"Sicherung konnte nicht geladen werden:\n{e}")
        self._remove_autosave()

    def edit_info(self):
        dlg = ProjectInfoDialog(self.state.info, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.state.set_info(dlg.info())

    def open_datasheet(self):
        if not self.state.measurements:
            QtWidgets.QMessageBox.information(self, "Datenblatt", "Noch keine Messung vorhanden.")
            return
        DatasheetDialog(self.state, self.ts_tab, self).exec()

    # -- Speicherplätze -------------------------------------------------------
    def _slot_for_ts(self, i: int, role: str):
        m = self.state.slot_measurement(i)
        if m is None:
            return
        (self.ts_tab.cb_free if role == "A" else self.ts_tab.cb_second).select(m)
        label = "A (Freiluft)" if role == "A" else "B (Zweitmessung)"
        self.state.status.emit(f"Platz {i + 1} „{m.name}“ als {label} für die T/S-Berechnung gewählt.")

    def _clear_slots(self):
        for i in range(N_SLOTS):
            if self.state.slots[i] is not None:
                self.state.clear_slot(i)

    # -- Darstellung ----------------------------------------------------------
    def edit_appearance(self):
        dlg = AppearanceDialog(self)
        old_palette = appearance().current.palette
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.recolor.isChecked() \
                and appearance().current.palette != old_palette:
            self.state.recolor_measurements()

    def _toggle_dark(self, on: bool):
        cur = appearance().current
        if cur.dark != on:
            appearance().set(replace(cur, theme="dark" if on else "light"))

    def _appearance_changed(self):
        self.act_dark.blockSignals(True)
        self.act_dark.setChecked(appearance().current.dark)
        self.act_dark.blockSignals(False)
        self._update_cal_status()

    def edit_watch(self):
        dlg = WatchFolderDialog(self.state.watch, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.state.watch = dlg.config()
            self.settings.setValue("watch_folder", json.dumps(self.state.watch.to_dict()))
            self.state.status.emit(f"Watch-Folder: {self.state.watch.path or '–'}"
                                   + (" (automatische Übergabe aktiv)" if self.state.watch.auto else ""))

    # ------------------------------------------------------------------
    def _build_sidebar(self):
        w = QtWidgets.QWidget()
        w.setObjectName("sidebar")
        lay = QtWidgets.QVBoxLayout(w)
        lay.setSpacing(4)
        lay.setContentsMargins(8, 6, 8, 6)

        head = QtWidgets.QWidget()
        head.setObjectName("brand")
        hl = QtWidgets.QHBoxLayout(head)
        hl.setContentsMargins(4, 2, 4, 6)
        logo = QtWidgets.QLabel()
        logo.setPixmap(icon_pixmap(40))
        hl.addWidget(logo)
        tl = QtWidgets.QVBoxLayout()
        tl.setSpacing(0)
        t1 = QtWidgets.QLabel("DATS-Messsoftware")
        t1.setObjectName("brandTitle")
        t2 = QtWidgets.QLabel(f"Impedanz · T/S · LCR   ·   Version {__version__}")
        t2.setObjectName("brandSub")
        tl.addWidget(t1)
        tl.addWidget(t2)
        hl.addLayout(tl, 1)
        lay.addWidget(head)

        g_hw = QtWidgets.QGroupBox("Hardware")
        f = QtWidgets.QFormLayout(g_hw)
        f.setRowWrapPolicy(QtWidgets.QFormLayout.DontWrapRows)
        row = QtWidgets.QHBoxLayout()
        self.cb_device = QtWidgets.QComboBox()
        self.cb_device.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_device.setMinimumContentsLength(10)
        btn_refresh = QtWidgets.QToolButton()
        btn_refresh.setText("↻")
        btn_refresh.setToolTip("Geräteliste aktualisieren")
        btn_refresh.clicked.connect(lambda: self._populate_devices())
        row.addWidget(self.cb_device, 1)
        row.addWidget(btn_refresh)
        f.addRow("Gerät:", row)
        self.cb_fs = QtWidgets.QComboBox()
        for fs in (44100, 48000):
            self.cb_fs.addItem(f"{fs / 1000:g} kHz", fs)
        f.addRow("Abtastrate:", self.cb_fs)
        self.cb_mode = QtWidgets.QComboBox()
        self.cb_mode.addItem("2 Kanäle (Standard)", "two_channel")
        self.cb_mode.addItem("1 Kanal", "single_channel")
        self.cb_mode.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_mode.setMinimumContentsLength(8)
        self.cb_mode.setToolTip("2 Kanäle: Referenz- und Messeingang (Standard beim DATS). "
                                "1 Kanal: nur ein Eingang, die Latenz wird geschätzt.")
        f.addRow("Messprinzip:", self.cb_mode)
        self.chk_swap = QtWidgets.QCheckBox("Eingangskanäle tauschen (L ↔ R)")
        f.addRow(self.chk_swap)
        self.r_nom = QtWidgets.QDoubleSpinBox()
        self.r_nom.setRange(1, 100000)
        self.r_nom.setDecimals(2)
        self.r_nom.setSuffix(" Ω")
        self.r_nom.setValue(100.0)
        self.r_nom.setToolTip("Nennwert des internen Referenzwiderstands. Nur relevant für unkalibrierte "
                              "Messungen und für die Ein-Punkt-Kalibrierung. Der Geräte-Check kann ihn bestimmen.")
        f.addRow("Ref.-Widerstand:", self.r_nom)
        lay.addWidget(g_hw)

        self.g_sim = QtWidgets.QGroupBox("Simulator")
        fs = QtWidgets.QFormLayout(self.g_sim)
        self.cb_conn = QtWidgets.QComboBox()
        for k, v in CONNECTIONS.items():
            self.cb_conn.addItem(v, k)
        self.cb_conn.setCurrentIndex(self.cb_conn.findData("driver"))   # sinnvoller Start im Simulator
        self.cb_conn.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_conn.setMinimumContentsLength(8)
        fs.addRow("Angeschlossen:", self.cb_conn)
        self.sim_sample = QtWidgets.QSpinBox()
        self.sim_sample.setRange(1, 8)
        self.sim_sample.setPrefix("Nr. ")
        self.sim_sample.setToolTip("Mehrere Exemplare desselben Treibers mit Fertigungsstreuung – "
                                   "zum Ausprobieren des Paarvergleichs.")
        fs.addRow("Exemplar:", self.sim_sample)
        lbl = QtWidgets.QLabel("Virtuelles DATS mit 6,5″-Testtreiber und Bauteilen.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: palette(placeholder-text);")
        fs.addRow(lbl)
        lay.addWidget(self.g_sim)

        g_cal = QtWidgets.QGroupBox("Kalibrierung")
        vc = QtWidgets.QVBoxLayout(g_cal)
        self.lbl_cal = QtWidgets.QLabel()
        self.lbl_cal.setWordWrap(True)
        self.btn_cal = QtWidgets.QPushButton("Kalibrier-Assistent …")
        self.btn_check = QtWidgets.QPushButton("Geräte-Check …")
        self.btn_check.setToolTip("Einmalig mit neuem Gerät: Kanalzuordnung, Referenz- und "
                                  "Kalibrierwiderstand bestimmen")
        vc.addWidget(self.lbl_cal)
        hb = QtWidgets.QHBoxLayout()
        hb.addWidget(self.btn_check)
        hb.addWidget(self.btn_cal)
        vc.addLayout(hb)
        lay.addWidget(g_cal)

        g_sw = QtWidgets.QGroupBox("Messung")
        fm = QtWidgets.QFormLayout(g_sw)
        self.level = QtWidgets.QDoubleSpinBox()
        self.level.setRange(-40, 0)
        self.level.setValue(-10)
        self.level.setSuffix(" dBFS")
        self.level.setToolTip("Ausgangspegel des Sweeps. Für T/S-Messungen kleine Pegel verwenden "
                              "(Kleinsignalbereich).")
        self.cb_len = QtWidgets.QComboBox()
        for k, v in SWEEP_LENGTHS.items():
            self.cb_len.addItem(v, k)
        self.averages = QtWidgets.QSpinBox()
        self.averages.setRange(1, 16)
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("automatisch")
        fm.addRow("Pegel:", self.level)
        fm.addRow("Sweep-Länge:", self.cb_len)
        fm.addRow("Mittelungen:", self.averages)
        fm.addRow("Name:", self.name)
        self.btn_measure = QtWidgets.QPushButton("Impedanz messen")
        self.btn_measure.setObjectName("primary")
        self.btn_measure.setMinimumHeight(42)
        self.btn_measure.setCursor(QtCore.Qt.PointingHandCursor)
        fm.addRow(self.btn_measure)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.setVisible(False)
        fm.addRow(self.progress)
        lay.addWidget(g_sw)
        lay.addStretch(1)

        self.sidebar_scroll = QtWidgets.QScrollArea()
        self.sidebar_scroll.setObjectName("sidebarScroll")
        self.sidebar_scroll.setWidget(w)
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setMinimumWidth(355)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.sidebar_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        self.cb_device.currentIndexChanged.connect(self._device_changed)
        for wdg in (self.cb_fs, self.cb_len, self.cb_mode):
            wdg.currentIndexChanged.connect(self._sweep_changed)
        self.level.valueChanged.connect(self._sweep_changed)
        self.averages.valueChanged.connect(self._sweep_changed)
        self.chk_swap.toggled.connect(self._sweep_changed)
        self.r_nom.valueChanged.connect(self._sweep_changed)
        self.cb_conn.currentIndexChanged.connect(lambda: self.state.set_connection(self.cb_conn.currentData()))
        self.sim_sample.valueChanged.connect(self._sample_changed)
        self.btn_cal.clicked.connect(self.open_calibration)
        self.btn_check.clicked.connect(self.open_device_check)
        self.btn_measure.clicked.connect(self.measure)

    def _build_menu(self):
        mb = self.menuBar()
        m_file = mb.addMenu("&Datei")
        m_file.addAction("Neues Projekt", self.new_project).setShortcut(QtGui.QKeySequence.New)
        m_file.addAction("Projekt öffnen …", self.open_project).setShortcut(QtGui.QKeySequence.Open)
        self.m_recent = m_file.addMenu("Zuletzt geöffnet")
        self.m_recent.aboutToShow.connect(self._fill_recent_menu)
        m_file.addAction("Projekt speichern", self.save_project).setShortcut(QtGui.QKeySequence.Save)
        m_file.addAction("Projekt speichern unter …", lambda: self.save_project(ask=True)).setShortcut(
            QtGui.QKeySequence("Ctrl+Shift+S"))
        m_file.addAction("Projektinfo && Notizen …", self.edit_info).setShortcut(QtGui.QKeySequence("Ctrl+I"))
        m_file.addSeparator()
        a = m_file.addAction("Messkurven importieren …", self.imp_tab.import_files)
        a.setShortcut(QtGui.QKeySequence("Ctrl+Shift+O"))
        a = m_file.addAction("Messkurve(n) exportieren …", self.imp_tab.export_selected)
        a.setShortcut(QtGui.QKeySequence("Ctrl+E"))
        m_file.addSeparator()
        a = m_file.addAction("Datenblatt (PDF / Drucken) …", self.open_datasheet)
        a.setShortcut(QtGui.QKeySequence.Print)
        m_file.addSeparator()
        m_file.addAction("Watch-Folder einstellen …", self.edit_watch)
        a = m_file.addAction("An Watch-Folder übergeben", self.imp_tab.deliver_selected)
        a.setShortcut(QtGui.QKeySequence("Ctrl+Shift+W"))
        m_file.addSeparator()
        a = m_file.addAction("Beenden", self.close)
        a.setShortcut(QtGui.QKeySequence.Quit)
        m_meas = mb.addMenu("&Messung")
        a = m_meas.addAction("Impedanz messen", self.measure)
        a.setShortcut(QtGui.QKeySequence("Ctrl+M"))
        m_store = m_meas.addMenu("Aktuelle Messung ablegen auf Speicherplatz")
        m_toggle = m_meas.addMenu("Speicherplatz ein-/ausblenden")
        for i in range(N_SLOTS):
            a = m_store.addAction(f"Platz {i + 1}", lambda i=i: self.imp_tab.slot_bar.store(i))
            a.setShortcut(QtGui.QKeySequence(f"Ctrl+{i + 1}"))
            a = m_toggle.addAction(f"Platz {i + 1}", lambda i=i: self.state.toggle_slot(i))
            a.setShortcut(QtGui.QKeySequence(f"Alt+{i + 1}"))
        m_meas.addAction("Alle Speicherplätze leeren", self._clear_slots)
        m_meas.addSeparator()
        m_meas.addAction("Geräte-Check …", self.open_device_check)
        m_meas.addAction("Kalibrier-Assistent …", self.open_calibration)
        m_meas.addAction("Kalibrierung verwerfen", lambda: self.state.set_calibration(None))
        m_meas.addSeparator()
        a = m_meas.addAction("Wiedergabe/Oszilloskop stoppen", self.state.stop_audio)
        a.setShortcut(QtGui.QKeySequence("Ctrl+."))
        m_view = mb.addMenu("&Ansicht")
        a = m_view.addAction("Darstellung …", self.edit_appearance)
        a.setShortcut(QtGui.QKeySequence("Ctrl+,"))
        self.act_dark = m_view.addAction("Dunkler Modus")
        self.act_dark.setCheckable(True)
        self.act_dark.setChecked(appearance().current.dark)
        self.act_dark.setShortcut(QtGui.QKeySequence("Ctrl+Shift+D"))
        self.act_dark.toggled.connect(self._toggle_dark)
        m_help = mb.addMenu("&Hilfe")
        a = m_help.addAction("Erste Schritte", lambda: helpdlg.show_guide(self))
        a.setShortcut(QtGui.QKeySequence.HelpContents)
        m_help.addAction("Was ist neu?", lambda: helpdlg.show_whats_new(self))
        m_help.addSeparator()
        m_help.addAction("Nach Updates suchen …", lambda: self.check_updates(manual=True))
        self.act_update_auto = m_help.addAction("Beim Start nach Updates suchen")
        self.act_update_auto.setCheckable(True)
        self.act_update_auto.setChecked(self.settings.value("update_check", True, type=bool))
        self.act_update_auto.toggled.connect(lambda on: self.settings.setValue("update_check", on))
        m_help.addSeparator()
        a = m_help.addAction("Fehlerbericht …", self.show_report)
        a.setShortcut(QtGui.QKeySequence("Ctrl+Shift+F"))
        m_help.addAction("Protokollordner öffnen", self._open_log_folder)
        if shortcut_supported():
            m_help.addAction("Desktop-Verknüpfung anlegen", self._make_shortcut)
        m_help.addSeparator()
        m_help.addAction("Über …", self._about)

    # -- Hilfe / Diagnose -----------------------------------------------------
    def report_context(self) -> dict[str, str]:
        eng = self.state.engine
        cal = eng.calibration
        sw = eng.sweep
        ctx = {
            "Gerät": self.state.backend.describe() + (" (Simulator)" if self.state.is_simulator else ""),
            "Sweep": f"{sw.fs} Hz, 2^{sw.sweep_exp}, {sw.level_dbfs:g} dBFS, {sw.averages}× gemittelt",
            "Kanäle": f"{eng.channels.mode}, Referenz = Eingang {eng.channels.ref_channel + 1}, "
                      f"Messung = Eingang {eng.channels.meas_channel + 1}, R_ref nominal {eng.channels.r_nominal:g} Ω",
            "Kalibrierung": ("keine" if cal is None else
                             f"{', '.join(cal.steps)}, R_cal {cal.r_cal:g} Ω, {cal.created}, "
                             f"{'passt' if cal.is_compatible(sw) else 'passt NICHT zum Sweep'}"),
            "Messungen im Projekt": str(len(self.state.measurements)),
            "Aktiver Tab": self.tabs.tabText(self.tabs.currentIndex()),
            "Darstellung": "dunkel" if appearance().current.dark else "hell",
        }
        last = self.state.current_measurement()
        if last is not None and last.meta.get("quality"):
            from ..analysis.quality import summary
            ctx["Letzte Messung"] = f"{last.name}: {summary(last.meta['quality'])}"
        check = self.settings.value("last_device_check", "")
        if check:
            ctx["Letzter Geräte-Check"] = str(check)
        return ctx

    def show_report(self):
        errors.ReportDialog(self, "Fehlerbericht", "<b>Fehlerbericht für Rückmeldungen</b>").exec()

    def _open_log_folder(self):
        p = diagnostics.log_path()
        folder = p.parent if p else Path(QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.AppDataLocation))
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))

    def _make_shortcut(self):
        path = create_desktop_shortcut()
        if path:
            QtWidgets.QMessageBox.information(self, "Desktop-Verknüpfung", f"Angelegt: {path.name}")
        else:
            errors.show_error(self, "Desktop-Verknüpfung", "Die Verknüpfung konnte nicht angelegt werden. "
                                                            "Details stehen im Fehlerbericht.")

    def check_updates(self, manual: bool = True):
        if manual:
            self.state.status.emit("Suche nach Updates …")

        def work():
            try:
                info = updates.fetch_remote()
                self._update_relay.result.emit(info, None, manual)
            except Exception as e:      # noqa: BLE001
                log.info("Update-Prüfung: %s", e)
                self._update_relay.result.emit(None, e, manual)

        threading.Thread(target=work, daemon=True).start()

    def _update_result(self, info, err, manual: bool):
        if info is None:
            if manual:
                errors.show_error(self, "Nach Updates suchen",
                                  f"GitHub ist nicht erreichbar ({type(err).__name__}). Internetverbindung prüfen.")
            return
        if not updates.is_newer(info.version):
            if manual:
                QtWidgets.QMessageBox.information(self, "Nach Updates suchen",
                                                  f"Du hast die neueste Version ({__version__}).")
            self.state.status.emit(f"Version {__version__} ist aktuell.")
            return
        skip = self.settings.value("update_skip", "")
        if not manual and skip == info.version:
            return
        self.version_label.setText(f"Version {__version__} – neu: {info.version}")
        self.version_label.setStyleSheet(f"color: {appearance().current.warn}; padding: 0 8px; font-weight: bold;")
        upd = "Update-Windows.bat" if os.name == "nt" else "Update-Mac.command"
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setWindowTitle("Neue Version verfügbar")
        box.setTextFormat(QtCore.Qt.RichText)
        box.setText(f"<b>Version {info.version}</b> ist verfügbar (installiert: {__version__}).<br><br>"
                    f"Zum Aktualisieren: Programm schließen und im Programmordner <b>{upd}</b> doppelklicken.")
        if info.changes:
            box.setDetailedText(info.changes)
        box.addButton("OK", QtWidgets.QMessageBox.AcceptRole)
        b_skip = box.addButton("Für diese Version nicht mehr anzeigen", QtWidgets.QMessageBox.RejectRole)
        b_folder = box.addButton("Programmordner öffnen", QtWidgets.QMessageBox.ActionRole)
        box.exec()
        if box.clickedButton() is b_skip:
            self.settings.setValue("update_skip", info.version)
        elif box.clickedButton() is b_folder:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(updates.PROJECT_ROOT)))

    # -- Geräte ---------------------------------------------------------
    def _populate_devices(self, select_saved: bool = False):
        saved = self.settings.value("device_name", "") if select_saved else self.cb_device.currentText()
        self.cb_device.blockSignals(True)
        self.cb_device.clear()
        self.cb_device.addItem("Simulator", None)
        devices = [d for d in list_devices() if d.max_in >= 1 and d.max_out >= 1]
        for d in devices:
            self.cb_device.addItem(("★ " if d.looks_like_dats else "") + d.label, d.index)
        for i in range(self.cb_device.count()):
            self.cb_device.setItemData(i, self.cb_device.itemText(i), QtCore.Qt.ToolTipRole)
        idx = self.cb_device.findText(saved) if saved else -1
        if idx < 0:
            dats = find_dats(devices)
            idx = self.cb_device.findData(dats.index) if dats else 0
        self.cb_device.setCurrentIndex(max(idx, 0))
        self.cb_device.blockSignals(False)
        self._device_changed()

    def _device_changed(self):
        idx = self.cb_device.currentData()
        self.cb_device.setToolTip(self.cb_device.currentText())
        if idx is None:
            backend = self._sim
        else:
            try:
                backend = SoundDeviceBackend(idx, idx)
            except Exception as e:      # noqa: BLE001
                log.exception("Gerät öffnen")
                errors.show_error(self, "Audio", f"Gerät kann nicht geöffnet werden: {e}")
                self.cb_device.setCurrentIndex(0)
                return
        self.g_sim.setVisible(backend.is_simulator)
        self._sweep_changed()
        self.state.set_backend(backend)
        if backend.is_simulator:
            self.state.set_connection(self.cb_conn.currentData())
        self.state.status.emit(f"Gerät: {backend.describe()}")

    def _sample_changed(self, n: int):
        self._sim.sample = n
        self.state.status.emit(f"Simulator: Treiber-Exemplar Nr. {n}"
                               + (" (Nennwerte)" if n == 1 else " (mit Fertigungsstreuung)"))

    def _sweep_changed(self, *_):
        eng = self.state.engine
        eng.sweep = eng.sweep.with_(fs=self.cb_fs.currentData(), sweep_exp=self.cb_len.currentData(),
                                    level_dbfs=self.level.value(), averages=self.averages.value())
        swap = self.chk_swap.isChecked()
        eng.channels = ChannelConfig(mode=self.cb_mode.currentData(), ref_channel=1 if swap else 0,
                                     meas_channel=0 if swap else 1, r_nominal=self.r_nom.value())
        self._update_cal_status()

    def _sync_connection(self, kind):
        i = self.cb_conn.findData(kind)
        if i >= 0 and i != self.cb_conn.currentIndex():
            self.cb_conn.blockSignals(True)
            self.cb_conn.setCurrentIndex(i)
            self.cb_conn.blockSignals(False)

    # -- Kalibrierung -----------------------------------------------------
    def _update_cal_status(self):
        eng = self.state.engine
        cal = eng.calibration
        if cal is None:
            txt, col = "Nicht kalibriert – Messwerte sind nur Schätzungen.", appearance().current.err
        elif not cal.is_compatible(eng.sweep):
            txt, col = ("Kalibrierung passt nicht zu Abtastrate/Sweep-Länge "
                        f"({cal.sweep.fs / 1000:g} kHz, 2^{cal.sweep.sweep_exp}) – bitte neu kalibrieren."), appearance().current.warn
        else:
            lr = cal.lead_resistance()
            txt = f"✔ Kalibriert ({', '.join(cal.steps)})<br>{cal.created.replace('T', ' ')}"
            if lr is not None:
                txt += f"<br>Leitungswiderstand: {lr * 1000:.0f} mΩ"
            col = appearance().current.ok
        self.lbl_cal.setText(f"<span style='color:{col}'>{txt}</span>")

    def open_calibration(self):
        if self.state.busy:
            return
        r_cal = float(self.settings.value("r_cal", 1000.0))
        wiz = CalibrationWizard(self.state, self, r_cal_default=r_cal)
        if wiz.exec() == QtWidgets.QDialog.Accepted:
            self.settings.setValue("r_cal", wiz.intro.r_cal.value())

    def open_device_check(self):
        if self.state.busy:
            return
        wiz = DeviceCheckWizard(self.state, self)
        if wiz.exec() != QtWidgets.QDialog.Accepted:
            return
        if wiz.report:
            self.settings.setValue("last_device_check", wiz.report)
            log.info("Geräte-Check: %s", wiz.report.replace("\n", " | "))
        if not wiz.page(wiz.PAGE_RESULT).apply.isChecked():
            return
        changed = []
        ch = wiz.channels
        if ch is not None:
            i = self.cb_mode.findData(ch.mode)
            if i >= 0 and i != self.cb_mode.currentIndex():
                self.cb_mode.setCurrentIndex(i)
                changed.append("Messprinzip")
            swap = ch.mode != "single_channel" and ch.meas_channel == 0
            if swap != self.chk_swap.isChecked():
                self.chk_swap.setChecked(swap)
                changed.append("Kanalzuordnung")
        est = wiz.estimate
        if est is not None and est.r_ref:
            self.r_nom.setValue(round(est.r_ref, 2))
            changed.append(f"Referenzwiderstand {est.r_ref:.2f} Ω")
        if est is not None and est.r_cal:
            self.settings.setValue("r_cal", round(est.r_cal, 1))
            changed.append(f"Kalibrierwiderstand {est.r_cal:.1f} Ω")
        self.state.status.emit("Geräte-Check übernommen: " + (", ".join(changed) or "keine Änderungen nötig")
                               + " – jetzt kalibrieren.")

    # -- Messen -----------------------------------------------------------
    def measure(self):
        name = self.name.text().strip() or None
        if self.state.measure(name):
            self.name.clear()
            if self.tabs.currentWidget() in (self.gen_tab, self.level_tab, self.compare_tab):
                self.tabs.setCurrentWidget(self.imp_tab)

    def _busy(self, busy):
        self.btn_measure.setEnabled(not busy)
        self.btn_cal.setEnabled(not busy)
        self.btn_check.setEnabled(not busy)
        self.progress.setRange(0, 0)
        self.progress.setVisible(busy)

    def _progress(self, i: int, n: int):
        self.progress.setRange(0, n)
        self.progress.setValue(i)

    # -- Einstellungen ------------------------------------------------------
    def _restore_settings(self):
        s = self.settings
        for cb, key, default in ((self.cb_fs, "fs", 48000), (self.cb_len, "sweep_exp", 17),
                                 (self.cb_mode, "mode", "two_channel")):
            v = s.value(key, default)
            i = cb.findData(type(default)(v))
            if i >= 0:
                cb.setCurrentIndex(i)
        self.level.setValue(float(s.value("level", -10.0)))
        self.averages.setValue(int(s.value("averages", 1)))
        self.chk_swap.setChecked(s.value("swap", "false") in (True, "true"))
        self.r_nom.setValue(float(s.value("r_nominal", 100.0)))
        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        try:
            self.state.watch = WatchFolderConfig.from_dict(json.loads(s.value("watch_folder", "{}")))
        except (ValueError, TypeError):
            pass

    def closeEvent(self, ev):
        if not self._confirm_discard():
            ev.ignore()
            return
        s = self.settings
        s.setValue("device_name", self.cb_device.currentText())
        s.setValue("fs", self.cb_fs.currentData())
        s.setValue("sweep_exp", self.cb_len.currentData())
        s.setValue("mode", self.cb_mode.currentData())
        s.setValue("level", self.level.value())
        s.setValue("averages", self.averages.value())
        s.setValue("swap", self.chk_swap.isChecked())
        s.setValue("r_nominal", self.r_nom.value())
        s.setValue("geometry", self.saveGeometry())
        self._autosave_timer.stop()
        self._remove_autosave()
        self.state.stop_audio()
        super().closeEvent(ev)

    def _about(self):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Über")
        box.setIconPixmap(icon_pixmap(72))
        box.setTextFormat(QtCore.Qt.RichText)
        box.setText(f"<b>DATS-Messsoftware {__version__}</b><br>"
                    "Impedanz-, Thiele/Small- und LCR-Messung für das Dayton Audio DATS V3 Interface "
                    "über Standard-Audiotreiber (CoreAudio, WASAPI/ASIO, ALSA).<br><br>"
                    f"Projekt: <a href='{updates.repo_url()}'>{updates.repo_url()}</a><br><br>"
                    "Unabhängiges Projekt, nicht mit Dayton Audio verbunden.")
        box.exec()
