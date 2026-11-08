"""Signalgenerator-Tab (FG-01)."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets

from ..dsp.generator import WAVEFORMS, generate
from .appearance import appearance
from .state import AppState


class GeneratorTab(QtWidgets.QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        left = QtWidgets.QGroupBox("Signal")
        left.setMaximumWidth(360)
        fl = QtWidgets.QFormLayout(left)
        self.wave = QtWidgets.QComboBox()
        for k, v in WAVEFORMS.items():
            self.wave.addItem(v, k)
        self.freq = QtWidgets.QDoubleSpinBox()
        self.freq.setRange(1, 20000)
        self.freq.setValue(1000)
        self.freq.setSuffix(" Hz")
        self.f_end = QtWidgets.QDoubleSpinBox()
        self.f_end.setRange(2, 24000)
        self.f_end.setValue(20000)
        self.f_end.setSuffix(" Hz")
        self.level = QtWidgets.QDoubleSpinBox()
        self.level.setRange(-80, 0)
        self.level.setValue(-12)
        self.level.setSuffix(" dBFS")
        self.duration = QtWidgets.QDoubleSpinBox()
        self.duration.setRange(0.1, 60)
        self.duration.setValue(5)
        self.duration.setSuffix(" s")
        self.loop = QtWidgets.QCheckBox("Endlos wiederholen")
        self.loop.setChecked(True)
        fl.addRow("Signalform:", self.wave)
        fl.addRow("Frequenz / Start:", self.freq)
        fl.addRow("Endfrequenz (Sweep):", self.f_end)
        fl.addRow("Pegel (Spitze):", self.level)
        fl.addRow("Dauer (Rauschen/Sweep):", self.duration)
        fl.addRow(self.loop)
        self.btn_play = QtWidgets.QPushButton("▶ Wiedergabe")
        self.btn_stop = QtWidgets.QPushButton("■ Stopp")
        fl.addRow(self.btn_play, self.btn_stop)
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: palette(placeholder-text);")
        fl.addRow(self.note)

        self.preview = pg.PlotWidget()
        self.preview.setLabel("bottom", "Zeit [ms]")
        self.preview.setLabel("left", "Amplitude [FS]")

        lay = QtWidgets.QHBoxLayout(self)
        lay.addWidget(left)
        lay.addWidget(self.preview, 1)

        for w in (self.wave, self.freq, self.f_end, self.level, self.duration):
            sig = w.currentIndexChanged if isinstance(w, QtWidgets.QComboBox) else w.valueChanged
            sig.connect(self._update_preview)
        self.btn_play.clicked.connect(self._play)
        self.btn_stop.clicked.connect(self._stop)
        appearance().changed.connect(self._restyle)
        self._restyle()

    def _restyle(self):
        self.preview.setBackground(appearance().current.plot_bg)
        appearance().style_plot(self.preview.getPlotItem())
        self._update_preview()

    def _signal(self):
        return generate(self.wave.currentData(), self.freq.value(), self.level.value(),
                        self.duration.value(), self.state.engine.sweep.fs, f_end=self.f_end.value())

    def _update_preview(self):
        kind = self.wave.currentData()
        self.f_end.setEnabled(kind == "logsweep")
        fs = self.state.engine.sweep.fs
        x = generate(kind, self.freq.value(), self.level.value(),
                     min(self.duration.value(), 0.25) if kind in ("pink", "white", "logsweep")
                     else 4 / self.freq.value(), fs, f_end=self.f_end.value(), seed=0)
        n = min(len(x), int(0.05 * fs) if kind in ("pink", "white") else len(x))
        t = np.arange(n) / fs * 1000
        self.preview.clear()
        a = appearance().current
        self.preview.plot(t, x[:n], pen=pg.mkPen(a.colors[0], width=a.line_width))

    def _play(self):
        if self.state.busy:
            return
        self.state.backend.play(self._signal(), self.state.engine.sweep.fs, loop=self.loop.isChecked())
        self.note.setText("Simulator: keine echte Wiedergabe." if self.state.is_simulator
                          else "Wiedergabe läuft über das Mess-Interface.")

    def _stop(self):
        self.state.backend.stop()
        self.note.setText("")
