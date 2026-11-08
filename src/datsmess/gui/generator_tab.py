"""Signalgenerator (FG-01) und Oszilloskop (OS-01).

Der Generator gibt über das Interface aus; gleichzeitig laufen beide Eingänge mit und werden als
Oszilloskop (Zeitverlauf mit Trigger) oder Spektrum (mit Pegel-, Frequenz- und THD+N-Anzeige)
dargestellt. Ohne Wiedergabe kann das Oszilloskop auch nur die Eingänge zeigen.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from ..dsp.generator import WAVEFORMS, generate
from .appearance import appearance
from .plots import LogAxis, plot_card
from .state import AppState

TIMEBASES = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100]      # ms/Teilung (10 Teilungen)


def thd_n(x: np.ndarray, fs: int) -> tuple[float, float, float]:
    """(Grundfrequenz Hz, Effektivpegel dBFS, THD+N in %) eines Sinus-Ausschnitts."""
    n = len(x)
    if n < 256:
        return float("nan"), float("nan"), float("nan")
    w = np.blackman(n)
    X = np.abs(np.fft.rfft((x - x.mean()) * w))
    f = np.fft.rfftfreq(n, 1 / fs)
    k = int(np.argmax(X[1:])) + 1
    rms = float(np.sqrt(np.mean(np.square(x - x.mean()))))
    lvl = 20 * np.log10(max(rms, 1e-9))
    if k < 2 or k > len(X) - 3:
        return float(f[k]), lvl, float("nan")
    a, b, c = X[k - 1], X[k], X[k + 1]
    d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
    f0 = float((k + d) * fs / n)
    P = X ** 2
    lo, hi = max(1, k - 6), min(len(P), k + 7)
    fund = float(P[lo:hi].sum())
    rest = float(P[1:].sum()) - fund
    return f0, lvl, 100 * np.sqrt(max(rest, 0.0) / max(fund, 1e-30))


class GeneratorTab(QtWidgets.QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._playing = False

        left = QtWidgets.QWidget()
        left.setMaximumWidth(360)
        ll = QtWidgets.QVBoxLayout(left)
        g = QtWidgets.QGroupBox("Signalgenerator")
        fl = QtWidgets.QFormLayout(g)
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
        ll.addWidget(g)

        gs = QtWidgets.QGroupBox("Oszilloskop")
        fs = QtWidgets.QFormLayout(gs)
        self.btn_scope = QtWidgets.QPushButton("Eingänge anzeigen (ohne Wiedergabe)")
        self.btn_scope.setCheckable(True)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("Zeitverlauf", "time")
        self.mode.addItem("Spektrum", "fft")
        self.timebase = QtWidgets.QComboBox()
        for t in TIMEBASES:
            self.timebase.addItem(f"{t:g} ms/Teil", t)
        self.timebase.setCurrentIndex(TIMEBASES.index(0.5))
        self.trigger = QtWidgets.QComboBox()
        self.trigger.addItem("Eingang 1, steigend", 0)
        self.trigger.addItem("Eingang 2, steigend", 1)
        self.trigger.addItem("frei laufend", None)
        self.ch1 = QtWidgets.QCheckBox("Eingang 1")
        self.ch2 = QtWidgets.QCheckBox("Eingang 2")
        self.ch1.setChecked(True)
        self.ch2.setChecked(True)
        chrow = QtWidgets.QHBoxLayout()
        chrow.addWidget(self.ch1)
        chrow.addWidget(self.ch2)
        self.hold = QtWidgets.QCheckBox("Anhalten")
        fs.addRow(self.btn_scope)
        fs.addRow("Darstellung:", self.mode)
        fs.addRow("Zeitbasis:", self.timebase)
        fs.addRow("Trigger:", self.trigger)
        fs.addRow("Kanäle:", chrow)
        fs.addRow(self.hold)
        ll.addWidget(gs)
        self.readout = QtWidgets.QLabel()
        self.readout.setWordWrap(True)
        self.readout.setTextFormat(QtCore.Qt.RichText)
        self.readout.setStyleSheet("font-family: monospace;")
        ll.addWidget(self.readout)
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: palette(placeholder-text);")
        ll.addWidget(self.note)
        ll.addStretch(1)

        self.preview = pg.PlotWidget()
        self.preview.setMenuEnabled(False)
        self.preview.setLabel("bottom", "Zeit [ms]")
        self.preview.setLabel("left", "Ausgang [FS]")
        self.preview.setMaximumHeight(190)
        self.scope = pg.PlotWidget()
        self.scope.setMenuEnabled(False)
        self.scope_legend = self.scope.addLegend(offset=(-10, 10))
        self.spec = pg.PlotWidget(axisItems={"bottom": LogAxis("bottom")})
        self.spec.setMenuEnabled(False)
        self.spec.setLogMode(x=True, y=False)
        self.spec.setLabel("bottom", "Frequenz [Hz]")
        self.spec.setLabel("left", "Pegel [dBFS]")
        self.spec.setYRange(-140, 0)
        self.spec.addLegend(offset=(-10, 10))
        for w in (self.preview, self.scope, self.spec):
            for ax in ("left", "bottom"):
                w.getAxis(ax).enableAutoSIPrefix(False)
        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.scope)
        self.stack.addWidget(self.spec)
        right = QtWidgets.QVBoxLayout()
        right.addWidget(plot_card(self.preview))
        right.addWidget(plot_card(self.stack), 1)

        lay = QtWidgets.QHBoxLayout(self)
        lay.addWidget(left)
        lay.addLayout(right, 1)

        for w in (self.wave, self.freq, self.f_end, self.level, self.duration):
            sig = w.currentIndexChanged if isinstance(w, QtWidgets.QComboBox) else w.valueChanged
            sig.connect(self._update_preview)
        self.btn_play.clicked.connect(self._play)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_scope.toggled.connect(self._scope_only)
        self.mode.currentIndexChanged.connect(lambda i: self.stack.setCurrentIndex(i))
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._poll)
        state.audioStopped.connect(self._stopped_elsewhere)
        appearance().changed.connect(self._restyle)
        self._restyle()
        self._idle_text()

    def _restyle(self):
        a = appearance().current
        for w in (self.preview, self.scope, self.spec):
            w.setBackground(a.plot_bg)
            appearance().style_plot(w.getPlotItem())
        self._update_preview()

    def _idle_text(self):
        self.readout.setText("")
        self.note.setText("Bei laufender Wiedergabe zeigt das Oszilloskop beide Eingänge: Eingang 1 "
                          "(meist Referenz) und Eingang 2 (Spannung am Messobjekt)."
                          + (" Im Simulator hängt das links gewählte Messobjekt an den Klemmen."
                             if self.state.is_simulator else ""))

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

    # -- Wiedergabe / Strom -------------------------------------------------
    def _start(self, signal, loop: bool) -> bool:
        if self.state.busy:
            self.state.status.emit("Bitte warten – es läuft eine Messung.")
            return False
        try:
            self.state.backend.start_stream(signal, self.state.engine.sweep.fs, loop=loop)
        except Exception as e:      # noqa: BLE001
            self.note.setText(f"Audio-Gerät lässt sich nicht öffnen: {e}")
            return False
        self.timer.start()
        return True

    def _play(self):
        if self._start(self._signal(), self.loop.isChecked()):
            self._playing = True
            self.btn_scope.blockSignals(True)
            self.btn_scope.setChecked(False)
            self.btn_scope.blockSignals(False)
            self.note.setText("Wiedergabe läuft – Eingänge siehe Oszilloskop."
                              + (" (Simulator)" if self.state.is_simulator else ""))

    def _scope_only(self, on: bool):
        if on:
            if self._start(None, True):
                self.note.setText("Eingänge werden angezeigt (keine Wiedergabe).")
            else:
                self.btn_scope.setChecked(False)
        else:
            self._stop()

    def _stop(self):
        self.state.stop_audio()

    def _stopped_elsewhere(self):
        self.timer.stop()
        self._playing = False
        self.btn_scope.blockSignals(True)
        self.btn_scope.setChecked(False)
        self.btn_scope.blockSignals(False)
        self._idle_text()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.timer.stop()               # Anzeige ruht, Wiedergabe läuft weiter

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.state.backend.streaming:
            self.timer.start()

    # -- Anzeige ------------------------------------------------------------
    def _poll(self):
        if self.hold.isChecked():
            return
        be = self.state.backend
        fs = be.stream_fs
        if fs is None:
            self._stopped_elsewhere()
            return
        a = appearance().current
        chans = [c for c, box in ((0, self.ch1), (1, self.ch2)) if box.isChecked()]
        names = ["Eingang 1", "Eingang 2"]
        if self.mode.currentData() == "time":
            span = self.timebase.currentData() * 10 / 1000
            n = max(64, int(span * fs))
            x = be.read_input(3 * n)
            if x is None:
                return
            start = len(x) - n
            trig = self.trigger.currentData()
            if trig is not None:
                s = x[: len(x) - n, trig]
                thr = 0.5 * (s.max() + s.min())
                idx = np.flatnonzero((s[:-1] < thr) & (s[1:] >= thr))
                if len(idx) and (s.max() - s.min()) > 1e-4:
                    start = int(idx[-1])
            seg = x[start:start + n]
            t = np.arange(len(seg)) / fs * 1000
            self.scope.clear()
            self.scope_legend.clear()
            for c in chans:
                self.scope.plot(t, seg[:, c], pen=pg.mkPen(a.colors[c], width=a.line_width), name=names[c])
            self.scope.setLabel("bottom", "Zeit [ms]")
            self.scope.setLabel("left", "Spannung [FS]")
            self.scope.setXRange(0, span * 1000, padding=0)
            stats = x[-n:]
        else:
            n = 16384
            x = be.read_input(n)
            if x is None:
                return
            self.spec.clear()
            w = np.blackman(n)
            f = np.fft.rfftfreq(n, 1 / fs)
            for c in chans:
                X = np.abs(np.fft.rfft(x[:, c] * w)) * 2 / w.sum()
                db = 20 * np.log10(np.maximum(X, 1e-9))
                self.spec.plot(f[1:], db[1:], pen=pg.mkPen(a.colors[c], width=a.line_width * 0.8), name=names[c])
            stats = x[-8192:]
        lines = []
        for c in chans:
            f0, lvl, thdn = thd_n(stats[:, c].astype(float), fs)
            peak = 20 * np.log10(max(float(np.max(np.abs(stats[:, c]))), 1e-9))
            txt = f"<span style='color:{a.colors[c]}'>■</span> {names[c]}: {lvl:6.1f} dBFS eff, Spitze {peak:5.1f}"
            if np.isfinite(thdn) and lvl > -70 and self.wave.currentData() == "sine" and self._playing:
                txt += f", {f0:7.1f} Hz, THD+N {thdn:.3f} %"
            lines.append(txt)
        self.readout.setText("<br>".join(lines))
