"""Bauteile-Tab: LCR-Meter (FB-01 … FB-03)."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ..analysis import lcr
from .plots import Curve, ImpedancePlot, display_data
from .state import AppState
from .ts_tab import MeasurementCombo

SIM_CONNECTION = {"C": "capacitor", "L": "inductor", "R": "resistor"}


class LCRTab(QtWidgets.QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        left = QtWidgets.QWidget()
        left.setMaximumWidth(380)
        ll = QtWidgets.QVBoxLayout(left)

        g = QtWidgets.QGroupBox("Bauteil")
        fl = QtWidgets.QFormLayout(g)
        self.kind = QtWidgets.QComboBox()
        for k, label in lcr.KIND_LABELS.items():
            self.kind.addItem(label, k)
        self.f_test = QtWidgets.QComboBox()
        self.f_test.addItem("Automatisch", None)
        for v in (100, 120, 1000, 10000):
            self.f_test.addItem(f"{v:g} Hz" if v < 1000 else f"{v / 1000:g} kHz", float(v))
        fl.addRow("Typ:", self.kind)
        fl.addRow("Prüffrequenz:", self.f_test)
        ll.addWidget(g)

        self.btn_measure = QtWidgets.QPushButton("Bauteil messen")
        self.btn_measure.setMinimumHeight(38)
        ll.addWidget(self.btn_measure)

        g2 = QtWidgets.QGroupBox("Vorhandene Messung auswerten")
        h = QtWidgets.QHBoxLayout(g2)
        self.cb_meas = MeasurementCombo(state)
        self.btn_eval = QtWidgets.QPushButton("Auswerten")
        h.addWidget(self.cb_meas, 1)
        h.addWidget(self.btn_eval)
        ll.addWidget(g2)

        self.result_box = QtWidgets.QGroupBox("Ergebnis")
        self.result_grid = QtWidgets.QGridLayout(self.result_box)
        ll.addWidget(self.result_box)
        hint = QtWidgets.QLabel("Messbereiche (Richtwerte): C 0,002 µF … 10 000 µF, L 0,05 mH … 100 mH, "
                                "R 0,002 Ω … 10 kΩ. Kalibrierung mit Kurzschluss verbessert kleine "
                                "Widerstände und Induktivitäten, Leerlauf kleine Kapazitäten.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        ll.addWidget(hint)
        ll.addStretch(1)

        self.plot = ImpedancePlot(name="lcr")
        split = QtWidgets.QSplitter()
        split.addWidget(left)
        split.addWidget(self.plot)
        split.setStretchFactor(1, 1)
        lay = QtWidgets.QHBoxLayout(self)
        lay.addWidget(split)

        self.btn_measure.clicked.connect(self._measure)
        self.btn_eval.clicked.connect(lambda: self.evaluate(self.cb_meas.currentData()))
        state.busyChanged.connect(lambda b: self.btn_measure.setEnabled(not b))

    def _measure(self):
        k = self.kind.currentData()
        conn = SIM_CONNECTION.get(k) if self.state.is_simulator else None
        prefix = {"C": "Kondensator", "L": "Spule", "R": "Widerstand"}.get(k, "Bauteil")
        self.state.measure(self.state.next_name(prefix), connection=conn,
                           on_done=lambda m: (self.cb_meas.select(m), self.evaluate(m)))

    def evaluate(self, m):
        if m is None:
            return
        r = lcr.analyze(m.f, m.Z, self.kind.currentData(), self.f_test.currentData(),
                        r_ref=self.state.engine.channels.r_nominal)
        while self.result_grid.count():
            w = self.result_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        title = QtWidgets.QLabel(f"<b>{lcr.KIND_LABELS[r.kind]}</b> – Prüffrequenz {r.f_test:g} Hz")
        self.result_grid.addWidget(title, 0, 0, 1, 2)
        for i, (k, v) in enumerate(r.values.items(), start=1):
            a = QtWidgets.QLabel(k)
            b = QtWidgets.QLabel(v)
            big = i == 1
            b.setStyleSheet(f"font-size:{22 if big else 15}px; font-weight:{'bold' if big else 'normal'};")
            b.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            b.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.result_grid.addWidget(a, i, 0)
            self.result_grid.addWidget(b, i, 1)
        f, Z = display_data(m, 24)
        self.plot.set_curves([Curve(m.name, f, Z, m.color or "#1f77b4")], autorange=True)
        self.state.status.emit(f"{m.name}: {r.summary()}")
