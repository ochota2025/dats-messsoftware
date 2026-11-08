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


def plot_card(widget: QtWidgets.QWidget, margins=(10, 10, 10, 6)) -> QtWidgets.QWidget:
    """Diagramm in eine Karte mit runden Ecken setzen (Rahmen/Hintergrund aus dem Stylesheet)."""
    card = QtWidgets.QWidget()
    card.setObjectName("plotCard")
    card.setAttribute(QtCore.Qt.WA_StyledBackground, True)
    lay = QtWidgets.QVBoxLayout(card)
    lay.setContentsMargins(*margins)
    lay.addWidget(widget)
    return card


def display_data(m, smoothing) -> tuple[np.ndarray, np.ndarray]:
    if smoothing == "raw":
        return m.f, m.Z
    return m.resampled(4000 if smoothing is None else 2000, octave_frac=smoothing)


FREQ_PRESETS = [("Komplett (1 Hz – 20 kHz)", 1.0, 20000.0), ("Hörbereich (20 Hz – 20 kHz)", 20.0, 20000.0),
                ("Tiefton/Resonanz (5 Hz – 500 Hz)", 5.0, 500.0), ("Mittel-/Hochton (200 Hz – 20 kHz)", 200.0, 20000.0)]


class AxisRangeDialog(QtWidgets.QDialog):
    """Achsbereiche in echten Einheiten (Hz, Ω, °) statt in internen Log-Werten."""

    def __init__(self, plot: "ImpedancePlot"):
        super().__init__(plot)
        from .de import button_box
        self.setWindowTitle("Bereich festlegen")
        (x0, x1), (y0, y1) = plot.top.vb.viewRange()
        _, (p0, p1) = plot.bottom.vb.viewRange()
        if plot.top_is_log:
            y0, y1 = 10 ** y0, 10 ** y1
        form = QtWidgets.QFormLayout(self)

        def spin(lo, hi, val, dec, suffix):
            sp = QtWidgets.QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(dec)
            sp.setSuffix(" " + suffix)
            sp.setValue(val)
            sp.setKeyboardTracking(False)
            return sp

        top_name = "|Z|" if plot.mode == "magphase" else "Re{Z}"
        bot_name, bot_unit = ("Phase", "°") if plot.mode == "magphase" else ("Im{Z}", "Ω")
        ymin = 0.001 if plot.top_is_log else -1e6
        self.f0 = spin(0.1, 100000, max(10 ** x0, 0.1), 1, "Hz")
        self.f1 = spin(0.1, 100000, 10 ** x1, 1, "Hz")
        self.z0 = spin(ymin, 1e6, max(y0, ymin), 3, "Ω")
        self.z1 = spin(ymin, 1e6, y1, 3, "Ω")
        self.p0 = spin(-1e6, 1e6, p0, 1, bot_unit)
        self.p1 = spin(-1e6, 1e6, p1, 1, bot_unit)
        self.z_auto = QtWidgets.QCheckBox("automatisch an die Kurven anpassen")
        self.p_auto = QtWidgets.QCheckBox("automatisch an die Kurven anpassen")
        self.z_auto.toggled.connect(lambda on: [w.setEnabled(not on) for w in (self.z0, self.z1)])
        self.p_auto.toggled.connect(lambda on: [w.setEnabled(not on) for w in (self.p0, self.p1)])

        def pair(a, b):
            w = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(a)
            h.addWidget(QtWidgets.QLabel("bis"))
            h.addWidget(b)
            return w

        form.addRow("Frequenz von", pair(self.f0, self.f1))
        form.addRow(f"{top_name} von", pair(self.z0, self.z1))
        form.addRow("", self.z_auto)
        form.addRow(f"{bot_name} von", pair(self.p0, self.p1))
        form.addRow("", self.p_auto)
        self.err = QtWidgets.QLabel()
        self.err.setStyleSheet("color: #e04848;")
        form.addRow(self.err)
        form.addRow(button_box(self, "Ok", "Cancel"))

    def accept(self):
        if self.f0.value() >= self.f1.value():
            self.err.setText("Die Startfrequenz muss kleiner als die Endfrequenz sein.")
            return
        if not self.z_auto.isChecked() and self.z0.value() >= self.z1.value():
            self.err.setText("Der untere Wert muss kleiner als der obere sein.")
            return
        if not self.p_auto.isChecked() and self.p0.value() >= self.p1.value():
            self.err.setText("Der untere Wert muss kleiner als der obere sein.")
            return
        super().accept()


class ImpedancePlot(QtWidgets.QWidget):
    """Zwei gekoppelte Diagramme (|Z| + Phase bzw. Re + Im) mit Cursor-Anzeige."""

    logYChanged = QtCore.Signal(bool)

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
            p.setMenuEnabled(False)     # eigenes Menü mit echten Werten statt interner Log-Werte
            p.hideButtons()
        self.bottom.setXLink(self.top)
        self.bottom.setLabel("bottom", "Frequenz [Hz]")
        self.legend = self.top.addLegend(offset=(-10, 10))

        pen = pg.mkPen("#888", width=1, style=QtCore.Qt.DashLine)
        self.vline_top = pg.InfiniteLine(angle=90, pen=pen)
        self.vline_bottom = pg.InfiniteLine(angle=90, pen=pen)
        self.readout = QtWidgets.QLabel(" ")
        self.readout.setStyleSheet("color: palette(window-text); font-family: monospace;")

        self.setObjectName("plotCard")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 4)
        lay.addWidget(self.glw, 1)
        lay.addWidget(self.readout)
        self.glw.scene().sigMouseMoved.connect(self._mouse_moved)
        self.glw.scene().sigMouseClicked.connect(self._scene_clicked)
        self.glw.setToolTip("Mausrad: zoomen · Ziehen: verschieben · Rechtsklick: Bereich, Skalierung, Export")
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
        if self.log_y == on:
            return
        self.log_y = on
        self._apply_labels()
        self._redraw()
        self.top.enableAutoRange(axis="y")
        self.logYChanged.emit(on)

    @property
    def top_is_log(self) -> bool:
        return self.log_y and self.mode == "magphase"

    # -- Kontextmenü und Bereiche ----------------------------------------------
    def _scene_clicked(self, ev):
        if ev.button() == QtCore.Qt.RightButton:
            ev.accept()
            self._context_menu(ev.screenPos().toPoint())

    def _context_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.addAction("Alles anzeigen", self.auto_range)
        menu.addAction("Bereich festlegen …", self.edit_range)
        fm = menu.addMenu("Frequenzbereich")
        for label, lo, hi in FREQ_PRESETS:
            fm.addAction(label, lambda lo=lo, hi=hi: self.set_freq_range(lo, hi))
        if self.mode == "magphase":
            a = menu.addAction("|Z| logarithmisch")
            a.setCheckable(True)
            a.setChecked(self.log_y)
            a.toggled.connect(self.set_log_y)
        menu.addSeparator()
        rect = menu.addAction("Zoomen durch Aufziehen eines Rechtecks")
        rect.setCheckable(True)
        rect.setChecked(self.top.vb.state["mouseMode"] == pg.ViewBox.RectMode)
        rect.toggled.connect(self.set_rect_zoom)
        menu.addSeparator()
        menu.addAction("Diagramm als Bild speichern …", self.save_image)
        menu.exec(pos)

    def auto_range(self):
        self.top.enableAutoRange()
        self.bottom.enableAutoRange()

    def set_freq_range(self, lo: float, hi: float):
        self.top.setXRange(np.log10(lo), np.log10(hi), padding=0)

    def set_rect_zoom(self, on: bool):
        mode = pg.ViewBox.RectMode if on else pg.ViewBox.PanMode
        for p in (self.top, self.bottom):
            p.vb.setMouseMode(mode)

    def edit_range(self):
        dlg = AxisRangeDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        self.set_freq_range(dlg.f0.value(), dlg.f1.value())
        if dlg.z_auto.isChecked():
            self.top.enableAutoRange(axis="y")
        else:
            lo, hi = dlg.z0.value(), dlg.z1.value()
            if self.top_is_log:
                lo, hi = np.log10(max(lo, 1e-6)), np.log10(hi)
            self.top.setYRange(lo, hi, padding=0)
        if dlg.p_auto.isChecked():
            self.bottom.enableAutoRange(axis="y")
        else:
            self.bottom.setYRange(dlg.p0.value(), dlg.p1.value(), padding=0)

    def save_image(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Diagramm speichern", "Impedanz.png",
                                                        "PNG-Bild (*.png)")
        if path:
            if not path.lower().endswith(".png"):
                path += ".png"
            self.glw.grab().save(path)

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
