"""Impedanzkorrektur: Zobel-Glied und Saugkreis berechnen, Wirkung anzeigen, Kurve übernehmen."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ..analysis import correction as corr
from ..analysis.ts import fit_driver, looks_like_driver
from ..measurement import Measurement
from .appearance import appearance
from .plots import Curve, ImpedancePlot
from .state import AppState
from .ts_tab import MeasurementCombo


def _spin(lo, hi, dec, suffix, step=None):
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSuffix(" " + suffix)
    if step:
        s.setSingleStep(step)
    s.setKeyboardTracking(False)
    return s


class CorrectionTab(QtWidgets.QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.fit = None
        self._busy = False

        left = QtWidgets.QWidget()
        left.setMaximumWidth(400)
        ll = QtWidgets.QVBoxLayout(left)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Messung:"))
        self.meas = MeasurementCombo(state)
        row.addWidget(self.meas, 1)
        ll.addLayout(row)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color: palette(placeholder-text);")
        ll.addWidget(self.info)

        self.g_zobel = QtWidgets.QGroupBox("Zobel-Glied (gegen den Anstieg im Hochton)")
        self.g_zobel.setCheckable(True)
        fz = QtWidgets.QFormLayout(self.g_zobel)
        self.z_r = _spin(0.1, 1000, 2, "Ω", 0.1)
        self.z_c = _spin(0.01, 1000, 2, "µF", 0.1)
        fz.addRow("R:", self.z_r)
        fz.addRow("C:", self.z_c)
        ll.addWidget(self.g_zobel)

        self.g_notch = QtWidgets.QGroupBox("Saugkreis (gegen die Resonanzspitze)")
        self.g_notch.setCheckable(True)
        self.g_notch.setChecked(False)
        fn = QtWidgets.QFormLayout(self.g_notch)
        self.n_r = _spin(0.1, 1000, 2, "Ω", 0.1)
        self.n_l = _spin(0.01, 1000, 2, "mH", 0.1)
        self.n_c = _spin(1, 100000, 0, "µF", 10)
        fn.addRow("R (inkl. Spulenwiderstand):", self.n_r)
        fn.addRow("L:", self.n_l)
        fn.addRow("C:", self.n_c)
        ll.addWidget(self.g_notch)

        row = QtWidgets.QHBoxLayout()
        self.btn_calc = QtWidgets.QPushButton("Werte berechnen")
        self.btn_round = QtWidgets.QPushButton("Auf Normwerte runden")
        self.btn_round.setToolTip("Kondensatoren und Spulen auf E12, Widerstände auf E24")
        row.addWidget(self.btn_calc)
        row.addWidget(self.btn_round)
        ll.addLayout(row)
        self.result = QtWidgets.QLabel()
        self.result.setWordWrap(True)
        self.result.setTextFormat(QtCore.Qt.RichText)
        ll.addWidget(self.result)
        self.btn_take = QtWidgets.QPushButton("Korrigierte Kurve in die Messliste übernehmen")
        ll.addWidget(self.btn_take)
        hint = QtWidgets.QLabel(
            "Beide Glieder werden parallel zum Treiber geschaltet. Belastbarkeit beachten: Der Zobel-"
            "Widerstand nimmt im Hochton einen großen Teil der Leistung auf, der Saugkreis-Widerstand "
            "bei der Resonanz. Die korrigierte Kurve lässt sich wie jede Messung als .zma exportieren "
            "(z. B. für die Weichensimulation).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        ll.addWidget(hint)
        ll.addStretch(1)

        self.plot = ImpedancePlot()
        split = QtWidgets.QSplitter()
        split.addWidget(left)
        split.addWidget(self.plot)
        split.setStretchFactor(1, 1)
        QtWidgets.QHBoxLayout(self).addWidget(split)

        self.meas.currentIndexChanged.connect(self.calculate)
        self.btn_calc.clicked.connect(self.calculate)
        self.btn_round.clicked.connect(self._round)
        self.btn_take.clicked.connect(self._take)
        for w in (self.z_r, self.z_c, self.n_r, self.n_l, self.n_c):
            w.valueChanged.connect(self.redraw)
        self.g_zobel.toggled.connect(self.redraw)
        self.g_notch.toggled.connect(self.redraw)
        appearance().changed.connect(self.redraw)
        self._set_enabled(False)

    def _set_enabled(self, on: bool):
        for w in (self.g_zobel, self.g_notch, self.btn_round, self.btn_take):
            w.setEnabled(on)

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.meas.currentData() is None and self.state.measurements:
            self.meas.select(self.state.current_measurement())

    # ------------------------------------------------------------------
    def calculate(self, *_):
        m = self.meas.currentData()
        self.fit = None
        if m is None or not looks_like_driver(m.f, m.Z):
            self.info.setText("Bitte eine Treibermessung wählen (mit Resonanz)." if m is not None else
                              "Bitte eine Messung wählen.")
            self._set_enabled(False)
            self.plot.set_curves([])
            self.result.setText("")
            return
        try:
            self.fit = fit_driver(m.f, m.Z)
        except Exception as e:      # noqa: BLE001
            self.info.setText(f"Anpassung fehlgeschlagen: {e}")
            self._set_enabled(False)
            return
        fit = self.fit
        self.info.setText(f"fs = {fit.fs:.1f} Hz, Re = {fit.Re:.2f} Ω, Qms = {fit.Qms:.2f}, Qes = {fit.Qes:.3f}, "
                          f"Le(1 kHz) = {fit.le_at(1000) * 1e3:.3f} mH")
        z = corr.optimize_zobel(m.f, m.Z, fit)
        n = corr.notch_from_fit(fit)
        self._busy = True
        self.z_r.setValue(z.R)
        self.z_c.setValue(z.C * 1e6)
        self.n_r.setValue(n.R)
        self.n_l.setValue(n.L * 1e3)
        self.n_c.setValue(n.C * 1e6)
        self._busy = False
        self._set_enabled(True)
        self.redraw()

    def _round(self):
        self._busy = True
        self.z_r.setValue(corr.nearest_e(self.z_r.value(), corr.E24))
        self.z_c.setValue(corr.nearest_e(self.z_c.value(), corr.E12))
        self.n_r.setValue(corr.nearest_e(self.n_r.value(), corr.E24))
        self.n_l.setValue(corr.nearest_e(self.n_l.value(), corr.E12))
        self.n_c.setValue(corr.nearest_e(self.n_c.value(), corr.E12))
        self._busy = False
        self.redraw()

    def networks(self):
        zobel = corr.Zobel(self.z_r.value(), self.z_c.value() * 1e-6) if self.g_zobel.isChecked() else None
        notch = (corr.Notch(self.n_r.value(), self.n_l.value() * 1e-3, self.n_c.value() * 1e-6)
                 if self.g_notch.isChecked() else None)
        return zobel, notch

    def corrected(self):
        m = self.meas.currentData()
        zobel, notch = self.networks()
        return corr.corrected(m.f, m.Z, zobel, notch)

    def redraw(self, *_):
        if self._busy or self.fit is None:
            return
        m = self.meas.currentData()
        if m is None:
            return
        zc = self.corrected()
        f, Z = m.resampled(2000, 48)
        _, Zc = Measurement(m.name, m.f, zc).resampled(2000, 48)
        self.plot.set_curves([Curve(m.name, f, Z, "model2", dashed=True),
                              Curve("korrigiert", f, Zc, appearance().current.colors[0])], autorange=True)
        lo, hi = corr.magnitude_range(m.f, m.Z, 20, 20000)
        clo, chi = corr.magnitude_range(m.f, zc, 20, 20000)
        self.result.setText(f"|Z| 20 Hz – 20 kHz: vorher <b>{lo:.1f} … {hi:.1f} Ω</b>, "
                            f"nachher <b>{clo:.1f} … {chi:.1f} Ω</b>")

    def _take(self):
        m = self.meas.currentData()
        if m is None or self.fit is None:
            return
        zobel, notch = self.networks()
        parts = []
        if zobel:
            parts.append(f"Zobel {zobel.R:.2f} Ω + {zobel.C * 1e6:.2f} µF")
        if notch:
            parts.append(f"Saugkreis {notch.R:.2f} Ω + {notch.L * 1e3:.2f} mH + {notch.C * 1e6:.0f} µF")
        new = Measurement(f"{m.name} (korrigiert)", m.f.copy(), self.corrected(),
                          meta={"source": "Impedanzkorrektur", "base": m.name, "correction": "; ".join(parts),
                                "calibrated": m.meta.get("calibrated")})
        self.state.add_measurement(new)
        self.state.status.emit(f"„{new.name}“ übernommen ({'; '.join(parts) or 'ohne Korrektur'}).")
