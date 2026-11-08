"""Pegelabhängige Messreihe (FA-01): Impedanz bei mehreren Pegeln, Kennwerte über dem Pegel."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..analysis.quality import grade
from ..analysis.ts import quick_parameters
from ..measurement import MeasurementEngine
from .appearance import appearance
from .plots import Curve, ImpedancePlot, plot_card
from .state import AppState

COLS = [("Pegel", "dBFS", "{:+.0f}"), ("fs", "Hz", "{:.2f}"), ("Re", "Ω", "{:.3f}"), ("Qms", "", "{:.3f}"),
        ("Qes", "", "{:.3f}"), ("Qts", "", "{:.3f}"), ("Zmax", "Ω", "{:.1f}")]
TRACKED = ["fs", "Re", "Qms", "Qes", "Qts"]


def _levels(start: float, stop: float, step: float) -> list[float]:
    step = abs(step) or 1.0
    if stop < start:
        start, stop = stop, start
    n = int(np.floor((stop - start) / step + 1e-9)) + 1
    return [round(start + i * step, 2) for i in range(max(1, min(n, 25)))]


def _gradient(i: int, n: int) -> str:
    """Farbverlauf leise (blau) → laut (rot)."""
    t = i / max(1, n - 1)
    c = QtGui.QColor.fromHsvF(0.62 - 0.62 * t, 0.85, 0.9 if not appearance().current.dark else 1.0)
    return c.name()


class LevelTab(QtWidgets.QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.rows: list[dict] = []

        left = QtWidgets.QWidget()
        left.setMaximumWidth(480)
        left.setMinimumWidth(400)
        ll = QtWidgets.QVBoxLayout(left)
        g = QtWidgets.QGroupBox("Messreihe")
        f = QtWidgets.QFormLayout(g)

        def spin(lo, hi, val, step=1.0, suffix=" dBFS"):
            s = QtWidgets.QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(0)
            s.setSingleStep(step)
            s.setValue(val)
            s.setSuffix(suffix)
            return s

        self.start = spin(-60, 0, -36)
        self.stop = spin(-60, 0, -6)
        self.step = spin(1, 20, 6, suffix=" dB")
        self.keep = QtWidgets.QCheckBox("Messungen in die Messliste übernehmen")
        self.keep.setChecked(False)
        self.plan = QtWidgets.QLabel()
        self.plan.setWordWrap(True)
        self.plan.setStyleSheet("color: palette(placeholder-text);")
        f.addRow("Von:", self.start)
        f.addRow("Bis:", self.stop)
        f.addRow("Schritt:", self.step)
        f.addRow(self.keep)
        f.addRow(self.plan)
        ll.addWidget(g)
        self.btn_run = QtWidgets.QPushButton("Messreihe starten")
        self.btn_run.setMinimumHeight(38)
        fb = self.btn_run.font()
        fb.setBold(True)
        self.btn_run.setFont(fb)
        ll.addWidget(self.btn_run)
        hint = QtWidgets.QLabel(
            "Zeigt, wie sich Resonanz und Güten mit dem Pegel ändern (Nachgiebigkeit, Verluste, "
            "Erwärmung). Für T/S-Werte nach Datenblatt gilt meist der Kleinsignalbereich – dort, wo "
            "sich die Werte kaum noch ändern. Vorsicht bei Hochtönern: hohe Pegel nur kurz.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        ll.addWidget(hint)
        self.table = QtWidgets.QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([f"{n}\n{u}" if u else n for n, u, _ in COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        ll.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        self.btn_copy = QtWidgets.QPushButton("Tabelle kopieren")
        self.btn_csv = QtWidgets.QPushButton("Als CSV speichern …")
        row.addWidget(self.btn_copy)
        row.addWidget(self.btn_csv)
        ll.addLayout(row)

        self.imp = ImpedancePlot()
        self.trend = pg.PlotWidget()
        self.trend.setLabel("bottom", "Pegel [dBFS]")
        self.trend.setLabel("left", "Änderung ggü. leisestem Pegel [%]")
        self.trend.setMenuEnabled(False)
        self.trend_legend = self.trend.addLegend(offset=(10, 10))
        right = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        right.addWidget(self.imp)
        right.addWidget(plot_card(self.trend))
        right.setSizes([480, 300])

        split = QtWidgets.QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        lay = QtWidgets.QHBoxLayout(self)
        lay.addWidget(split)

        for s in (self.start, self.stop, self.step):
            s.valueChanged.connect(self._update_plan)
        self.btn_run.clicked.connect(self.run)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_csv.clicked.connect(self._csv)
        state.busyChanged.connect(lambda b: self.btn_run.setEnabled(not b))
        appearance().changed.connect(self._restyle)
        self._restyle()
        self._update_plan()

    def _restyle(self):
        self.trend.setBackground(appearance().current.plot_bg)
        appearance().style_plot(self.trend.getPlotItem())
        self._draw()

    def levels(self) -> list[float]:
        return _levels(self.start.value(), self.stop.value(), self.step.value())

    def _update_plan(self):
        lv = self.levels()
        dur = self.state.engine.sweep.duration_s * self.state.engine.sweep.averages * len(lv)
        self.plan.setText(f"{len(lv)} Messungen ({', '.join(f'{v:+.0f}' for v in lv)} dBFS), "
                          f"Dauer ca. {dur:.0f} s.")

    # ------------------------------------------------------------------
    def run(self):
        lv = self.levels()
        main = self.state.engine
        if self.state.is_simulator:
            self.state.set_connection("driver")
        state = self.state

        def job():
            out = []
            for i, level in enumerate(lv):
                eng = MeasurementEngine(main.backend, main.sweep.with_(level_dbfs=level), main.channels)
                eng.calibration = main.calibration
                m, raw = eng.measure_impedance(f"Pegel {level:+.0f} dBFS")
                out.append((level, m))
                state.progress.emit(i + 1, len(lv))
            return out

        state.run(job, self._done, text=f"Pegelreihe: {len(lv)} Messungen …")

    def _done(self, results):
        self.rows = []
        for level, m in results:
            fit = quick_parameters(m.f, m.Z)
            g, msgs = grade(m.meta.get("quality"))
            self.rows.append({"level": level, "m": m, "fit": fit, "grade": g, "msgs": msgs})
            if self.keep.isChecked():
                m.color = None
                self.state.add_measurement(m)
        n_ok = sum(r["fit"] is not None for r in self.rows)
        self.state.status.emit(f"Pegelreihe fertig: {len(self.rows)} Messungen, {n_ok} mit Treiberresonanz.")
        self._fill_table()
        self._draw()

    def _fill_table(self):
        a = appearance().current
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            fit = row["fit"]
            vals = [row["level"]] + ([fit.fs, fit.Re, fit.Qms, fit.Qes, fit.Qts, fit.Zmax] if fit else [None] * 6)
            for c, ((_n, _u, fmt), v) in enumerate(zip(COLS, vals)):
                it = QtWidgets.QTableWidgetItem("–" if v is None else fmt.format(v))
                it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                if c == 0 and row["grade"] != "ok":
                    it.setForeground(QtGui.QColor(a.err if row["grade"] == "bad" else a.warn))
                    it.setToolTip("\n".join(row["msgs"]))
                self.table.setItem(r, c, it)

    def _draw(self):
        curves = []
        n = len(self.rows)
        for i, row in enumerate(self.rows):
            f, Z = row["m"].resampled(1500, 24)
            curves.append(Curve(row["m"].name, f, Z, _gradient(i, n)))
        self.imp.set_curves(curves, autorange=True)
        self.trend.clear()
        self.trend_legend.clear()
        good = [r for r in self.rows if r["fit"] is not None]
        if len(good) < 2:
            return
        a = appearance().current
        x = np.array([r["level"] for r in good])
        for i, key in enumerate(TRACKED):
            y = np.array([getattr(r["fit"], key) for r in good])
            pct = 100 * (y / y[0] - 1)
            pen = pg.mkPen(a.colors[i % len(a.colors)], width=a.line_width)
            self.trend.plot(x, pct, pen=pen, symbol="o", symbolSize=6,
                            symbolBrush=a.colors[i % len(a.colors)], name=key)

    def table_text(self, sep: str = "\t") -> str:
        head = sep.join(f"{n} [{u}]" if u else n for n, u, _ in COLS)
        lines = [head]
        for row in self.rows:
            fit = row["fit"]
            vals = [row["level"]] + ([fit.fs, fit.Re, fit.Qms, fit.Qes, fit.Qts, fit.Zmax] if fit else [None] * 6)
            lines.append(sep.join("" if v is None else fmt.format(v) for (_n, _u, fmt), v in zip(COLS, vals)))
        return "\n".join(lines)

    def _copy(self):
        QtWidgets.QApplication.clipboard().setText(self.table_text().replace(".", ","))
        self.state.status.emit("Tabelle der Pegelreihe kopiert (Dezimalkomma, tabulatorgetrennt).")

    def _csv(self):
        if not self.rows:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Pegelreihe speichern", "Pegelreihe.csv",
                                                        "CSV (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.table_text(";").replace(".", ",") + "\n")
            self.state.status.emit(f"Pegelreihe gespeichert: {path}")
