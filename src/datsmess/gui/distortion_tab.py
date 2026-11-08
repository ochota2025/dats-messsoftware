"""Klirr & Rub/Buzz (FA-03): elektrischer Klirrfaktor und höhere Harmonische aus dem Impedanz-Sweep."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from ..dsp.distortion import analyze, at_noise_floor, rub_buzz_verdict
from ..dsp.sweep import SweepConfig
from ..measurement import ChannelConfig
from .appearance import appearance
from .plots import LogAxis, plot_card
from .state import AppState
from .ts_tab import MeasurementCombo


class DistortionTab(QtWidgets.QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.res = None

        left = QtWidgets.QWidget()
        left.setMaximumWidth(380)
        ll = QtWidgets.QVBoxLayout(left)
        g = QtWidgets.QGroupBox("Messung")
        gl = QtWidgets.QVBoxLayout(g)
        self.meas = MeasurementCombo(state)
        gl.addWidget(self.meas)
        row = QtWidgets.QHBoxLayout()
        self.btn_measure = QtWidgets.QPushButton("Neu messen")
        self.btn_eval = QtWidgets.QPushButton("Auswerten")
        row.addWidget(self.btn_measure)
        row.addWidget(self.btn_eval)
        gl.addLayout(row)
        self.auto = QtWidgets.QCheckBox("Neue Messungen automatisch auswerten")
        self.auto.setChecked(True)
        gl.addWidget(self.auto)
        ll.addWidget(g)

        gs = QtWidgets.QGroupBox("Anzeige")
        fs = QtWidgets.QFormLayout(gs)
        self.scale = QtWidgets.QComboBox()
        self.scale.addItem("Prozent", "pct")
        self.scale.addItem("dB", "db")
        self.show_ref = QtWidgets.QCheckBox("Wandler/Verstärker (Referenzkanal)")
        self.show_ref.setChecked(True)
        self.show_noise = QtWidgets.QCheckBox("Rauschgrenze")
        self.show_noise.setChecked(True)
        fs.addRow("Skala:", self.scale)
        fs.addRow(self.show_ref)
        fs.addRow(self.show_noise)
        ll.addWidget(gs)

        self.verdict = QtWidgets.QLabel()
        self.verdict.setWordWrap(True)
        self.verdict.setTextFormat(QtCore.Qt.RichText)
        self.verdict.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        gv = QtWidgets.QGroupBox("Ergebnis")
        QtWidgets.QVBoxLayout(gv).addWidget(self.verdict)
        ll.addWidget(gv)
        hint = QtWidgets.QLabel(
            "Ausgewertet wird die <b>Spannung an den Klemmen</b> während des Impedanz-Sweeps – keine "
            "zusätzliche Messung nötig. <b>Grenzen mit dem DATS V3:</b> Es liefert nur Kleinsignal, die "
            "Membran bewegt sich kaum. Der Klirr des Treibers liegt dann meist unter dem Eigenklirr und "
            "Rauschen der Soundkarte (Kurven „Wandler“ und „Rauschgrenze“). Aussagekräftig ist die "
            "Messung vor allem für <b>grobe Fehler</b> wie eine schleifende Schwingspule oder lose Teile, "
            "die schon bei kleiner Auslenkung Geräusche machen. Dazu mit dem höchsten Pegel messen, "
            "der noch nicht übersteuert (z. B. −3 dBFS). Klirr bei echter Lautstärke braucht einen "
            "Verstärker, akustischen Klirr misst nur ein Mikrofon.")
        hint.setWordWrap(True)
        hint.setTextFormat(QtCore.Qt.RichText)
        hint.setStyleSheet("color: palette(placeholder-text);")
        ll.addWidget(hint)
        ll.addStretch(1)

        self.plot = pg.PlotWidget(axisItems={"bottom": LogAxis("bottom")})
        self.plot.setLogMode(x=True, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.setLabel("bottom", "Grundtonfrequenz [Hz]")
        self.legend = self.plot.addLegend(offset=(-10, 10))
        split = QtWidgets.QSplitter()
        split.addWidget(left)
        split.addWidget(plot_card(self.plot))
        split.setStretchFactor(1, 1)
        QtWidgets.QHBoxLayout(self).addWidget(split)

        self.btn_eval.clicked.connect(lambda: self.evaluate(self.meas.currentData()))
        self.btn_measure.clicked.connect(self._measure)
        self.meas.currentIndexChanged.connect(lambda: self.evaluate(self.meas.currentData()))
        for w in (self.show_ref, self.show_noise):
            w.toggled.connect(self.draw)
        self.scale.currentIndexChanged.connect(self.draw)
        state.busyChanged.connect(lambda b: self.btn_measure.setEnabled(not b))
        state.measurementsChanged.connect(self._new_measurement)
        appearance().changed.connect(self._restyle)
        self._last_count = 0
        self._restyle()

    def _restyle(self):
        self.plot.setBackground(appearance().current.plot_bg)
        appearance().style_plot(self.plot.getPlotItem())
        self.draw()

    def _new_measurement(self):
        n = len(self.state.measurements)
        if n > self._last_count and self.auto.isChecked() and self.isVisible():
            m = self.state.current_measurement()
            if m is not None and m.has_raw:
                self.meas.select(m)
        self._last_count = n

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.meas.currentData() is None:
            raw = [m for m in self.state.measurements if m.has_raw]
            if raw:
                self.meas.select(raw[-1])

    def _measure(self):
        if self.state.is_simulator and not self.state.backend.connection.startswith("driver"):
            self.state.set_connection("driver")
        self.state.measure(on_done=lambda m: (self.meas.select(m), self.evaluate(m)))

    def evaluate(self, m):
        self.res = None
        if m is None:
            self.verdict.setText("Bitte eine Messung wählen.")
            self.draw()
            return
        if not m.has_raw:
            self.verdict.setText("Diese Messung enthält keine Sweep-Rohdaten (importiert oder berechnet) – "
                                 "Klirr lässt sich nur aus eigenen Messungen bestimmen.")
            self.draw()
            return
        cfg = SweepConfig.from_dict(m.meta["sweep"])
        ch = ChannelConfig.from_dict(m.meta["channels"])
        try:
            self.res = analyze(m.recordings, cfg, ch.ref_channel, ch.meas_channel,
                               single_channel=ch.mode == "single_channel")
        except Exception as e:      # noqa: BLE001
            self.verdict.setText(f"Auswertung fehlgeschlagen: {e}")
            self.draw()
            return
        r = self.res
        a = appearance().current
        kind, text = rub_buzz_verdict(r)
        thd_max, f_max = r.peak(r.thd, 20, 2000)
        lines = [f"<b>{m.name}</b> – Pegel {cfg.level_dbfs:+.0f} dBFS"]
        if np.isfinite(thd_max):
            lines.append(f"Klirrfaktor (k2 … k5) max. <b>{thd_max * 100:.2f} %</b> bei {f_max:.0f} Hz")
            for f0 in (100, 1000):
                v = r.at(r.thd, f0)
                if np.isfinite(v):
                    lines.append(f"bei {f0:g} Hz: {v * 100:.3f} %")
        lines.append(f"<span style='color:{a.ok if kind == 'ok' else a.warn}'>{text}</span>")
        if kind == "ok" and at_noise_floor(r):
            lines.append(f"<span style='color:{a.muted}'>Der Klirr liegt überwiegend an der Messgrenze "
                         "(Rauschen der Soundkarte). Mit dem DATS V3 allein ist das normal – die Membran "
                         "bewegt sich kaum.</span>")
        self.verdict.setText("<br>".join(lines))
        self.draw()

    def draw(self, *_):
        self.plot.clear()
        self.legend.clear()
        r = self.res
        db = self.scale.currentData() == "db"
        self.plot.setLabel("left", "Anteil am Grundton [dB]" if db else "Anteil am Grundton [%]")
        if r is None:
            return
        a = appearance().current

        def y(arr):
            arr = np.asarray(arr, float)
            with np.errstate(invalid="ignore", divide="ignore"):
                return 20 * np.log10(np.maximum(arr, 1e-7)) if db else 100 * arr

        def curve(arr, color, name, width=1.0, dash=False):
            arr = np.asarray(arr, float)
            if np.isfinite(arr).sum() < 2:
                return
            pen = pg.mkPen(color, width=a.line_width * width,
                           style=QtCore.Qt.DashLine if dash else QtCore.Qt.SolidLine)
            # Lücken (unter der Rauschgrenze) nicht verbinden
            self.plot.plot(r.f, y(np.where(np.isfinite(arr), arr, np.nan)), pen=pen, name=name, connect="finite")

        if self.show_noise.isChecked() and r.noise_thd is not None:
            curve(r.noise_thd, a.model2, "Rauschgrenze", 0.8, dash=True)
        if self.show_ref.isChecked():
            curve(r.thd_ref, a.colors[8 % len(a.colors)], "Wandler (Referenz)", 0.8, dash=True)
        curve(r.thd, a.colors[0], "THD (k2…k5)", 1.4)
        curve(r.h2, a.colors[2], "k2")
        curve(r.h3, a.colors[3], "k3")
        curve(r.hohd, a.colors[1], "Rub & Buzz (k10…k20)", 1.2)
        if db:
            self.plot.addLine(y=-50, pen=pg.mkPen(a.warn, width=1, style=QtCore.Qt.DotLine))
