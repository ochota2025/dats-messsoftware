"""Hauptfenster: Dashboard mit Hardware-, Kalibrier- und Messbereich (ANR-03)."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__
from ..audio.backend import CONNECTIONS, SoundDeviceBackend, find_dats, list_devices
from ..audio.simulator import SimulatorBackend
from ..io import project as projio
from ..io.watch import WatchFolderConfig
from ..measurement import ChannelConfig
from .calibration_wizard import CalibrationWizard
from .appearance import AppearanceDialog, appearance
from .datasheet import DatasheetDialog
from .de import ask
from .dialogs import ProjectInfoDialog, WatchFolderDialog
from .generator_tab import GeneratorTab
from .impedance_tab import ImpedanceTab
from .lcr_tab import LCRTab
from .state import N_SLOTS, AppState
from .ts_tab import TSTab

SWEEP_LENGTHS = {15: "kurz (≈ 0,7 s)", 16: "mittel (≈ 1,4 s)", 17: "standard (≈ 2,7 s)", 18: "lang (≈ 5,5 s)"}


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DATS-Messsoftware")
        self.resize(1360, 860)
        self.settings = QtCore.QSettings()
        self.state = AppState(self)
        self._sim = SimulatorBackend()

        self._build_sidebar()
        self.tabs = QtWidgets.QTabWidget()
        self.imp_tab = ImpedanceTab(self.state)
        self.ts_tab = TSTab(self.state)
        self.ts_tab.datasheetRequested.connect(lambda: self.open_datasheet())
        self.lcr_tab = LCRTab(self.state)
        self.gen_tab = GeneratorTab(self.state)
        self.tabs.addTab(self.imp_tab, "Impedanz")
        self.tabs.addTab(self.ts_tab, "T/S-Parameter")
        self.tabs.addTab(self.lcr_tab, "Bauteile (LCR)")
        self.tabs.addTab(self.gen_tab, "Signalgenerator")

        split = QtWidgets.QSplitter()
        split.addWidget(self.sidebar_scroll)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        split.setSizes([330, 1030])
        self.setCentralWidget(split)
        self._build_menu()

        self.status_label = QtWidgets.QLabel()
        self.statusBar().addWidget(self.status_label, 1)
        self.state.status.connect(self.status_label.setText)
        self.state.calibrationChanged.connect(self._update_cal_status)
        self.state.busyChanged.connect(self._busy)
        self.state.connectionChanged.connect(self._sync_connection)
        self.state.projectChanged.connect(self._update_title)
        appearance().changed.connect(self._appearance_changed)
        self.imp_tab.slot_bar.useForTS.connect(self._slot_for_ts)
        self.imp_tab.slot_bar.exportSlot.connect(
            lambda i: self.imp_tab.export_selected([self.state.slot_measurement(i)]))

        self._restore_settings()
        self._populate_devices(select_saved=True)
        self.state.dirty = False
        self._update_title()
        self.state.status.emit("Bereit.")

    # -- Projekt (FS-04) -----------------------------------------------------
    def _update_title(self):
        info = self.state.info.title
        extra = f" – {info}" if info != "Treiber" else ""
        self.setWindowTitle(f"{self.state.project_title}{extra} – DATS-Messsoftware")

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
            QtWidgets.QMessageBox.warning(self, "Projekt öffnen", f"Projekt konnte nicht geladen werden:\n{e}")

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
            QtWidgets.QMessageBox.warning(self, "Projekt speichern", str(e))
            return False
        self.settings.setValue("project_dir", str(path.parent))
        return True

    def _project_dir(self) -> str:
        return str(self.settings.value("project_dir", str(Path.home())))

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
        lay = QtWidgets.QVBoxLayout(w)

        g_hw = QtWidgets.QGroupBox("Hardware")
        f = QtWidgets.QFormLayout(g_hw)
        row = QtWidgets.QHBoxLayout()
        self.cb_device = QtWidgets.QComboBox()
        self.cb_device.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_device.setMinimumContentsLength(8)
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
        self.cb_mode.addItem("2 Kanäle (Referenz + Messung)", "two_channel")
        self.cb_mode.addItem("1 Kanal (Ausgang + Messung)", "single_channel")
        self.cb_mode.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_mode.setMinimumContentsLength(8)
        f.addRow("Messprinzip:", self.cb_mode)
        self.chk_swap = QtWidgets.QCheckBox("Eingangskanäle tauschen (L ↔ R)")
        f.addRow(self.chk_swap)
        self.r_nom = QtWidgets.QDoubleSpinBox()
        self.r_nom.setRange(1, 100000)
        self.r_nom.setDecimals(2)
        self.r_nom.setSuffix(" Ω")
        self.r_nom.setValue(100.0)
        self.r_nom.setToolTip("Nennwert des internen Referenzwiderstands. Nur relevant für unkalibrierte "
                              "Messungen und für die Ein-Punkt-Kalibrierung.")
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
        lbl = QtWidgets.QLabel("Virtuelles DATS mit Testtreiber (6,5″-Tieftöner) und Bauteilen – "
                               "zum Ausprobieren ohne Hardware.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: palette(placeholder-text);")
        fs.addRow(lbl)
        lay.addWidget(self.g_sim)

        g_cal = QtWidgets.QGroupBox("Kalibrierung")
        vc = QtWidgets.QVBoxLayout(g_cal)
        self.lbl_cal = QtWidgets.QLabel()
        self.lbl_cal.setWordWrap(True)
        self.btn_cal = QtWidgets.QPushButton("Kalibrier-Assistent …")
        vc.addWidget(self.lbl_cal)
        vc.addWidget(self.btn_cal)
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
        self.btn_measure.setMinimumHeight(44)
        font = self.btn_measure.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self.btn_measure.setFont(font)
        self.btn_measure.setStyleSheet("QPushButton{background:#1f6fbf;color:white;border-radius:5px;}"
                                       "QPushButton:disabled{background:#9bb;}")
        fm.addRow(self.btn_measure)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        fm.addRow(self.progress)
        lay.addWidget(g_sw)
        lay.addStretch(1)

        self.sidebar_scroll = QtWidgets.QScrollArea()
        self.sidebar_scroll.setWidget(w)
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setMinimumWidth(320)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        self.cb_device.currentIndexChanged.connect(self._device_changed)
        for wdg in (self.cb_fs, self.cb_len, self.cb_mode):
            wdg.currentIndexChanged.connect(self._sweep_changed)
        self.level.valueChanged.connect(self._sweep_changed)
        self.averages.valueChanged.connect(self._sweep_changed)
        self.chk_swap.toggled.connect(self._sweep_changed)
        self.r_nom.valueChanged.connect(self._sweep_changed)
        self.cb_conn.currentIndexChanged.connect(lambda: self.state.set_connection(self.cb_conn.currentData()))
        self.btn_cal.clicked.connect(self.open_calibration)
        self.btn_measure.clicked.connect(self.measure)

    def _build_menu(self):
        mb = self.menuBar()
        m_file = mb.addMenu("&Datei")
        m_file.addAction("Neues Projekt", self.new_project).setShortcut(QtGui.QKeySequence.New)
        m_file.addAction("Projekt öffnen …", self.open_project).setShortcut(QtGui.QKeySequence.Open)
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
        m_meas.addAction("Kalibrier-Assistent …", self.open_calibration)
        m_meas.addAction("Kalibrierung verwerfen", lambda: self.state.set_calibration(None))
        m_view = mb.addMenu("&Ansicht")
        a = m_view.addAction("Darstellung …", self.edit_appearance)
        a.setShortcut(QtGui.QKeySequence("Ctrl+,"))
        self.act_dark = m_view.addAction("Dunkler Modus")
        self.act_dark.setCheckable(True)
        self.act_dark.setChecked(appearance().current.dark)
        self.act_dark.setShortcut(QtGui.QKeySequence("Ctrl+Shift+D"))
        self.act_dark.toggled.connect(self._toggle_dark)
        m_help = mb.addMenu("&Hilfe")
        m_help.addAction("Über …", self._about)

    # -- Geräte ---------------------------------------------------------
    def _populate_devices(self, select_saved: bool = False):
        saved = self.settings.value("device_name", "") if select_saved else self.cb_device.currentText()
        self.cb_device.blockSignals(True)
        self.cb_device.clear()
        self.cb_device.addItem("Simulator (ohne Hardware)", None)
        devices = [d for d in list_devices() if d.max_in >= 1 and d.max_out >= 1]
        for d in devices:
            self.cb_device.addItem(("★ " if d.looks_like_dats else "") + d.label, d.index)
        idx = self.cb_device.findText(saved) if saved else -1
        if idx < 0:
            dats = find_dats(devices)
            idx = self.cb_device.findData(dats.index) if dats else 0
        self.cb_device.setCurrentIndex(max(idx, 0))
        self.cb_device.blockSignals(False)
        self._device_changed()

    def _device_changed(self):
        idx = self.cb_device.currentData()
        if idx is None:
            backend = self._sim
        else:
            try:
                backend = SoundDeviceBackend(idx, idx)
            except Exception as e:      # noqa: BLE001
                QtWidgets.QMessageBox.warning(self, "Audio", f"Gerät kann nicht geöffnet werden: {e}")
                self.cb_device.setCurrentIndex(0)
                return
        self.g_sim.setVisible(backend.is_simulator)
        self._sweep_changed()
        self.state.set_backend(backend)
        if backend.is_simulator:
            self.state.set_connection(self.cb_conn.currentData())
        self.state.status.emit(f"Gerät: {backend.describe()}")

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

    # -- Messen -----------------------------------------------------------
    def measure(self):
        name = self.name.text().strip() or None
        if self.state.measure(name):
            self.name.clear()
            self.tabs.setCurrentWidget(self.imp_tab) if self.tabs.currentWidget() is self.gen_tab else None

    def _busy(self, busy):
        self.btn_measure.setEnabled(not busy)
        self.btn_cal.setEnabled(not busy)
        self.progress.setVisible(busy)

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
        self.state.backend.stop()
        super().closeEvent(ev)

    def _about(self):
        QtWidgets.QMessageBox.about(
            self, "Über",
            f"<b>DATS-Messsoftware {__version__}</b><br>"
            "Impedanz-, Thiele/Small- und LCR-Messung für das Dayton Audio DATS V3 Interface "
            "über Standard-Audiotreiber (CoreAudio, WASAPI/ASIO, ALSA).<br><br>"
            "Unabhängiges Projekt, nicht mit Dayton Audio verbunden.")
