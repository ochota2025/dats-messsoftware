"""Vergleich und Paarabgleich: Treiber-Exemplare gegen eine Referenz, Toleranz-Ampel, beste Paare."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..analysis import matching
from ..analysis.ts import quick_parameters
from .appearance import appearance
from .plots import LogAxis
from .state import AppState
from .ts_tab import MeasurementCombo


class CompareTab(QtWidgets.QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._fits: dict[str, tuple[int, object]] = {}

        left = QtWidgets.QWidget()
        left.setMaximumWidth(360)
        ll = QtWidgets.QVBoxLayout(left)
        g = QtWidgets.QGroupBox("Auswahl")
        gl = QtWidgets.QVBoxLayout(g)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Referenz:"))
        self.ref = MeasurementCombo(state)
        row.addWidget(self.ref, 1)
        gl.addLayout(row)
        gl.addWidget(QtWidgets.QLabel("Vergleichen mit (Haken setzen):"))
        self.list = QtWidgets.QListWidget()
        gl.addWidget(self.list, 1)
        btns = QtWidgets.QHBoxLayout()
        b_all = QtWidgets.QPushButton("Alle Treiber")
        b_none = QtWidgets.QPushButton("Keine")
        btns.addWidget(b_all)
        btns.addWidget(b_none)
        gl.addLayout(btns)
        ll.addWidget(g, 1)

        gt = QtWidgets.QGroupBox("Toleranzen (±)")
        ft = QtWidgets.QFormLayout(gt)
        self.tol: dict[str, QtWidgets.QDoubleSpinBox] = {}
        for key, label in (("fs", "fs"), ("Qts", "Qts"), ("Qes", "Qes"), ("Re", "Re"), ("curve", "|Z|-Verlauf (RMS)")):
            sp = QtWidgets.QDoubleSpinBox()
            sp.setRange(0.5, 50)
            sp.setDecimals(1)
            sp.setSuffix(" %")
            sp.setValue(matching.DEFAULT_TOL[key])
            sp.valueChanged.connect(self.refresh)
            ft.addRow(label + ":", sp)
            self.tol[key] = sp
        ll.addWidget(gt)
        self.pairs = QtWidgets.QLabel()
        self.pairs.setWordWrap(True)
        self.pairs.setTextFormat(QtCore.Qt.RichText)
        self.pairs.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        gp = QtWidgets.QGroupBox("Beste Paare")
        QtWidgets.QVBoxLayout(gp).addWidget(self.pairs)
        ll.addWidget(gp)

        self.table = QtWidgets.QTableWidget(0, 0)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.plot = pg.PlotWidget(axisItems={"bottom": LogAxis("bottom")})
        self.plot.setLogMode(x=True, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.setLabel("bottom", "Frequenz [Hz]")
        self.plot.setLabel("left", "Abweichung |Z| ggü. Referenz [%]")
        self.legend = self.plot.addLegend(offset=(-10, 10))
        right = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        right.addWidget(self.table)
        right.addWidget(self.plot)
        right.setSizes([260, 480])

        split = QtWidgets.QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        QtWidgets.QHBoxLayout(self).addWidget(split)

        self.ref.currentIndexChanged.connect(self.refresh)
        self.list.itemChanged.connect(lambda _it: self.refresh())
        b_all.clicked.connect(lambda: self._check_all(True))
        b_none.clicked.connect(lambda: self._check_all(False))
        state.measurementsChanged.connect(self._rebuild_list)
        state.slotsChanged.connect(self._rebuild_list)
        appearance().changed.connect(self._restyle)
        self._restyle()
        self._rebuild_list()

    def _restyle(self):
        self.plot.setBackground(appearance().current.plot_bg)
        appearance().style_plot(self.plot.getPlotItem())
        self.refresh()

    def fit(self, m):
        key = id(m.Z)
        hit = self._fits.get(m.id)
        if hit is None or hit[0] != key:
            hit = (key, quick_parameters(m.f, m.Z))
            self._fits[m.id] = hit
        return hit[1]

    def _rebuild_list(self):
        checked = {self.list.item(i).data(QtCore.Qt.UserRole).id for i in range(self.list.count())
                   if self.list.item(i).checkState() == QtCore.Qt.Checked}
        self.list.blockSignals(True)
        self.list.clear()
        for m in self.state.measurements:
            slot = self.state.slot_of(m)
            it = QtWidgets.QListWidgetItem(f"[{slot + 1}] {m.name}" if slot is not None else m.name)
            it.setData(QtCore.Qt.UserRole, m)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if m.id in checked else QtCore.Qt.Unchecked)
            pm = QtGui.QPixmap(12, 12)
            pm.fill(QtGui.QColor(m.color or "#888"))
            it.setIcon(QtGui.QIcon(pm))
            self.list.addItem(it)
        self.list.blockSignals(False)
        if self.ref.currentData() is None and self.state.measurements:
            self.ref.setCurrentIndex(1)
        self.refresh()

    def _check_all(self, on: bool):
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            it = self.list.item(i)
            m = it.data(QtCore.Qt.UserRole)
            it.setCheckState(QtCore.Qt.Checked if on and self.fit(m) is not None else QtCore.Qt.Unchecked)
        self.list.blockSignals(False)
        self.refresh()

    def tolerances(self) -> dict:
        tol = dict(matching.DEFAULT_TOL)
        for k, sp in self.tol.items():
            tol[k] = sp.value()
        return tol

    def selected(self):
        ref = self.ref.currentData()
        others = [self.list.item(i).data(QtCore.Qt.UserRole) for i in range(self.list.count())
                  if self.list.item(i).checkState() == QtCore.Qt.Checked]
        return ref, [m for m in others if m is not ref]

    # ------------------------------------------------------------------
    def refresh(self, *_):
        if not hasattr(self, "plot"):
            return
        a = appearance().current
        ref, others = self.selected()
        tol = self.tolerances()
        self.plot.clear()
        self.legend.clear()
        cols = [c for _k, c, _u, _f in matching.PARAMS] + ["|Z| RMS"]
        self.table.setColumnCount(len(cols) + 1)
        self.table.setHorizontalHeaderLabels(["Messung"] + [f"{n}\n{u}" if u else n for _k, n, u, _f in
                                                             matching.PARAMS] + ["|Z| RMS\n%"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        rfit = self.fit(ref) if ref is not None else None
        rows = ([ref] if ref is not None else []) + others
        self.table.setRowCount(len(rows))
        rvals = matching.values(rfit) if rfit else None
        for r, m in enumerate(rows):
            fit = self.fit(m)
            name = QtWidgets.QTableWidgetItem(("◆ " if m is ref else "") + m.name)
            pm = QtGui.QPixmap(10, 10)
            pm.fill(QtGui.QColor(m.color or "#888"))
            name.setIcon(QtGui.QIcon(pm))
            self.table.setItem(r, 0, name)
            vals = matching.values(fit) if fit else None
            for c, (k, _n, _u, fmt) in enumerate(matching.PARAMS, start=1):
                if vals is None:
                    it = QtWidgets.QTableWidgetItem("–")
                else:
                    txt = fmt.format(vals[k])
                    it = QtWidgets.QTableWidgetItem(txt)
                    if rvals is not None and m is not ref:
                        dev = matching.deviation_pct(vals[k], rvals[k])
                        it.setText(f"{txt}  ({dev:+.1f} %)")
                        t = tol.get(k)
                        if t:
                            col = a.ok if abs(dev) <= t else (a.warn if abs(dev) <= 2 * t else a.err)
                            it.setForeground(QtGui.QColor(col))
                it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self.table.setItem(r, c, it)
            last = QtWidgets.QTableWidgetItem("–" if m is ref else "")
            if ref is not None and m is not ref:
                g, dev = matching.curve_deviation(ref.f, ref.Z, m.f, m.Z)
                rms = matching.rms(dev)
                last.setText(f"{rms:.1f}")
                col = a.ok if rms <= tol["curve"] else (a.warn if rms <= 2 * tol["curve"] else a.err)
                last.setForeground(QtGui.QColor(col))
                self.plot.plot(g, dev, pen=pg.mkPen(m.color or "#888", width=a.line_width), name=m.name)
            last.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.table.setItem(r, len(cols), last)
        if ref is not None and others:
            band = pg.LinearRegionItem(values=(-tol["curve"], tol["curve"]), orientation="horizontal",
                                       movable=False, brush=pg.mkBrush(QtGui.QColor(a.ok).red(),
                                                                       QtGui.QColor(a.ok).green(),
                                                                       QtGui.QColor(a.ok).blue(), 28))
            band.setZValue(-10)
            for line in band.lines:
                line.setPen(pg.mkPen(None))
            self.plot.addItem(band)
        self._pairs(rows, tol)

    def _pairs(self, rows, tol):
        items = []
        for m in rows:
            fit = self.fit(m)
            if fit is not None:
                items.append((m.name, matching.values(fit), m.f, m.Z))
        if len(items) < 2:
            self.pairs.setText("Mindestens zwei Treibermessungen auswählen (Referenz + Haken).")
            return
        a = appearance().current
        lines = []
        for i, j, score in matching.best_pairs(items, tol):
            col = a.ok if score <= 1 else (a.warn if score <= 2 else a.err)
            mark = "✔" if score <= 1 else ("≈" if score <= 2 else "✘")
            lines.append(f"<span style='color:{col}'>{mark}</span> <b>{items[i][0]}</b> + <b>{items[j][0]}</b> "
                         f"– größte Abweichung {score:.2f} × Toleranz")
        rest = len(items) % 2
        if rest:
            lines.append("<span style='color:palette(placeholder-text)'>(ein Treiber bleibt übrig)</span>")
        self.pairs.setText("<br>".join(lines))
