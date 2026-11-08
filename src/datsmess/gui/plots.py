"""Zoombare Impedanz-Diagramme (FN-01, DM-02)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from .appearance import appearance

pg.setConfigOptions(antialias=True, background="w", foreground="#333")

SMOOTHING = {
    "1/48 Oktave": 48,
    "1/24 Oktave": 24,
    "1/12 Oktave": 12,
    "1/6 Oktave": 6,
    "1/3 Oktave": 3,
    "Keine (4000 Punkte)": None,
    "Alle Messpunkte": "raw",
}

VIEWS = {"magphase": "Betrag & Phase", "reim": "Real- & Imaginärteil"}


def _short(x: float) -> str:
    """20 → „20“, 2000 → „2k“, 0.5 → „0.5“."""
    if x >= 1000:
        return f"{x / 1000:g}k"
    return f"{x:g}"


class LogAxis(pg.AxisItem):
    """Logarithmische Achse in Audio-Schreibweise: nur 1-2-5-Werte beschriftet (…, 20, 50, 100, 1k …)."""

    def logTickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            x = 10.0 ** v
            mant = x / 10.0 ** np.floor(np.log10(x) + 1e-9)
            out.append(_short(float(f"{x:.6g}")) if any(abs(mant - m) < 1e-6 for m in (1, 2, 5)) else "")
        return out


@dataclass
class Curve:
    name: str
    f: np.ndarray
    Z: np.ndarray
    color: str = "#1f77b4"          # oder "model" / "model2" (Farbe aus dem Farbschema)
    width: float | None = None      # None = Linienstärke aus den Darstellungs-Einstellungen
    dashed: bool = False


def display_data(m, smoothing) -> tuple[np.ndarray, np.ndarray]:
    if smoothing == "raw":
        return m.f, m.Z
    return m.resampled(4000 if smoothing is None else 2000, octave_frac=smoothing)


class ImpedancePlot(QtWidgets.QWidget):
    """Zwei gekoppelte Diagramme (|Z| + Phase bzw. Re + Im) mit Cursor-Anzeige."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "magphase"
        self.log_y = False
        self._curves: list[Curve] = []

        self.glw = pg.GraphicsLayoutWidget()
        self.top = self.glw.addPlot(row=0, col=0, axisItems={"bottom": LogAxis("bottom"),
                                                              "left": LogAxis("left")})
        self.bottom = self.glw.addPlot(row=1, col=0, axisItems={"bottom": LogAxis("bottom")})
        self.glw.ci.layout.setRowStretchFactor(0, 3)
        self.glw.ci.layout.setRowStretchFactor(1, 2)
        for p in (self.top, self.bottom):
            p.setLogMode(x=True, y=False)
            p.setMenuEnabled(True)
        self.bottom.setXLink(self.top)
        self.bottom.setLabel("bottom", "Frequenz [Hz]")
        self.legend = self.top.addLegend(offset=(-10, 10))

        pen = pg.mkPen("#888", width=1, style=QtCore.Qt.DashLine)
        self.vline_top = pg.InfiniteLine(angle=90, pen=pen)
        self.vline_bottom = pg.InfiniteLine(angle=90, pen=pen)
        self.readout = QtWidgets.QLabel(" ")
        self.readout.setStyleSheet("color: palette(window-text); font-family: monospace;")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.glw, 1)
        lay.addWidget(self.readout)
        self.glw.scene().sigMouseMoved.connect(self._mouse_moved)
        self._apply_labels()
        self._default_range()
        appearance().changed.connect(self._restyle)
        self._restyle()

    # ------------------------------------------------------------------
    def _restyle(self):
        a = appearance().current
        self.glw.setBackground(a.plot_bg)
        for p in (self.top, self.bottom):
            appearance().style_plot(p)
        pen = pg.mkPen(a.model2, width=1, style=QtCore.Qt.DashLine)
        self.vline_top.setPen(pen)
        self.vline_bottom.setPen(pen)
        self._redraw()

    def _apply_labels(self):
        if self.mode == "magphase":
            self.top.setLabel("left", "|Z| [Ω]")
            self.bottom.setLabel("left", "Phase [°]")
        else:
            self.top.setLabel("left", "Re{Z} [Ω]")
            self.bottom.setLabel("left", "Im{Z} [Ω]")
        self.top.setLogMode(x=True, y=self.log_y and self.mode == "magphase")

    def set_mode(self, mode: str):
        self.mode = mode
        self._apply_labels()
        self._redraw()

    def set_log_y(self, on: bool):
        self.log_y = on
        self._apply_labels()
        self._redraw()

    def set_curves(self, curves: list[Curve], autorange: bool = False):
        self._curves = curves
        self._redraw()
        if autorange:
            self.top.enableAutoRange()
            self.bottom.enableAutoRange()

    def _redraw(self):
        self.top.clear()
        self.bottom.clear()
        self.legend.clear()
        for c in self._curves:
            m = c.f > 0
            f, Z = c.f[m], c.Z[m]
            if self.mode == "magphase":
                y1, y2 = np.abs(Z), np.degrees(np.angle(Z))
            else:
                y1, y2 = Z.real, Z.imag
            a = appearance().current
            color = {"model": a.model, "model2": a.model2}.get(c.color, c.color)
            width = a.line_width if c.width is None else c.width * a.line_width / 1.6
            pen = pg.mkPen(color, width=width, style=QtCore.Qt.DashLine if c.dashed else QtCore.Qt.SolidLine)
            self.top.plot(f, y1, pen=pen, name=c.name)
            self.bottom.plot(f, y2, pen=pen)
        self.top.addItem(self.vline_top, ignoreBounds=True)
        self.bottom.addItem(self.vline_bottom, ignoreBounds=True)
        if not self._curves:
            self._default_range()

    def _default_range(self):
        """Leeres Diagramm: sinnvoller Bereich 1 Hz … 20 kHz statt Autoskalierung auf 1 … 10."""
        self.top.setXRange(0.0, np.log10(20000.0), padding=0.02)
        if self.mode == "magphase":
            if self.log_y:
                self.top.setYRange(0.0, 2.0, padding=0)
            else:
                self.top.setYRange(0.0, 50.0, padding=0)
            self.bottom.setYRange(-90.0, 90.0, padding=0)
        else:
            self.top.setYRange(0.0, 50.0, padding=0)
            self.bottom.setYRange(-30.0, 30.0, padding=0)

    def _mouse_moved(self, pos):
        for plot in (self.top, self.bottom):
            if plot.sceneBoundingRect().contains(pos):
                x = plot.vb.mapSceneToView(pos).x()
                break
        else:
            return
        f0 = 10 ** x
        self.vline_top.setPos(x)
        self.vline_bottom.setPos(x)
        parts = [f"f = {f0:9.2f} Hz"]
        for c in self._curves[:4]:
            if len(c.f) < 2 or f0 < c.f[0] or f0 > c.f[-1]:
                continue
            z = complex(np.interp(f0, c.f, c.Z.real), np.interp(f0, c.f, c.Z.imag))
            if self.mode == "magphase":
                parts.append(f"{c.name}: {abs(z):.3f} Ω ∠ {np.degrees(np.angle(z)):+.1f}°")
            else:
                parts.append(f"{c.name}: {z.real:.3f} {z.imag:+.3f}j Ω")
        self.readout.setText("   |   ".join(parts))
