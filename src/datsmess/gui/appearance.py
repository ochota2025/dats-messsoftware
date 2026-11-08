"""Darstellungs-Einstellungen: Farbschema (hell/dunkel), Kurvenfarben, Linienstärke.

Ein zentraler ``AppearanceManager`` hält die Einstellungen, speichert sie in den
QSettings und meldet Änderungen über das Signal ``changed``; Diagramme und Fenster
passen sich daraufhin sofort an.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

PALETTES = {
    "standard": ("Standard", ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b",
                              "#e377c2", "#17becf", "#7f7f7f", "#bcbd22"]),
    "kraeftig": ("Kräftig (gut auf dunklem Hintergrund)",
                 ["#4fc3f7", "#ff5252", "#69f0ae", "#ffd740", "#e040fb", "#ff9100",
                  "#18ffff", "#b2ff59", "#ff80ab", "#ffffff"]),
    "gedeckt": ("Gedeckt", ["#4e79a7", "#e15759", "#59a14f", "#f28e2b", "#b07aa1", "#9c755f",
                            "#76b7b2", "#edc948", "#ff9da7", "#bab0ac"]),
    "mono": ("Graustufen + Akzent", ["#d62728", "#333333", "#777777", "#aaaaaa", "#1f77b4",
                                     "#555555", "#999999", "#2ca02c", "#bbbbbb", "#ff7f0e"]),
}
THEMES = {"light": "Hell", "dark": "Dunkel"}


@dataclass
class Appearance:
    theme: str = "light"
    line_width: float = 1.6
    palette: str = "standard"
    grid: float = 0.25          # Deckkraft der Gitterlinien 0 … 1

    @property
    def dark(self) -> bool:
        return self.theme == "dark"

    @property
    def colors(self) -> list[str]:
        return PALETTES.get(self.palette, PALETTES["standard"])[1]

    # Farben für Diagramme und Statusanzeigen
    @property
    def plot_bg(self) -> str:
        return "#1b1d21" if self.dark else "#ffffff"

    @property
    def plot_fg(self) -> str:
        return "#d6d6d6" if self.dark else "#333333"

    @property
    def model(self) -> str:          # Modellkurven (gestrichelt)
        return "#f0f0f0" if self.dark else "#000000"

    @property
    def model2(self) -> str:
        return "#a0a0a0" if self.dark else "#555555"

    @property
    def ok(self) -> str:
        return "#5bd17a" if self.dark else "#1a7f37"

    @property
    def warn(self) -> str:
        return "#ffb74d" if self.dark else "#b35a00"

    @property
    def err(self) -> str:
        return "#ff6b6b" if self.dark else "#c00000"


def apply_palette(app: QtWidgets.QApplication, dark: bool) -> None:
    """Feste Qt-Palette – unabhängig vom Dunkelmodus des Betriebssystems."""
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):           # Qt ≥ 6.8
        try:
            hints.setColorScheme(QtCore.Qt.ColorScheme.Dark if dark else QtCore.Qt.ColorScheme.Light)
        except Exception:                           # noqa: BLE001
            pass
    app.setStyle("Fusion")
    P, C = QtGui.QPalette, QtGui.QColor
    if dark:
        colors = {
            P.Window: "#2b2d31", P.WindowText: "#e6e6e6", P.Base: "#1e1f22", P.AlternateBase: "#26282c",
            P.Text: "#e6e6e6", P.Button: "#35373c", P.ButtonText: "#e6e6e6", P.BrightText: "#ffffff",
            P.Highlight: "#2f7fd8", P.HighlightedText: "#ffffff", P.ToolTipBase: "#3a3c42",
            P.ToolTipText: "#e6e6e6", P.PlaceholderText: "#9a9ca3", P.Link: "#6cb4ff",
            P.Light: "#45474d", P.Midlight: "#3a3c41", P.Mid: "#5a5c63", P.Dark: "#18191b", P.Shadow: "#000000",
        }
        disabled = ("#6e7076", "#25272a", "#2e3034")
    else:
        colors = {
            P.Window: "#f0f0f0", P.WindowText: "#1a1a1a", P.Base: "#ffffff", P.AlternateBase: "#f5f7fa",
            P.Text: "#1a1a1a", P.Button: "#f0f0f0", P.ButtonText: "#1a1a1a", P.BrightText: "#ffffff",
            P.Highlight: "#1f6fbf", P.HighlightedText: "#ffffff", P.ToolTipBase: "#ffffe1",
            P.ToolTipText: "#1a1a1a", P.PlaceholderText: "#7a7a7a", P.Link: "#1f6fbf",
            P.Light: "#ffffff", P.Midlight: "#e3e3e3", P.Mid: "#b8b8b8", P.Dark: "#9f9f9f", P.Shadow: "#5a5a5a",
        }
        disabled = ("#9a9a9a", "#f3f3f3", "#ececec")
    pal = QtGui.QPalette()
    for role, value in colors.items():
        pal.setColor(role, C(value))
    for role in (P.WindowText, P.Text, P.ButtonText):
        pal.setColor(P.Disabled, role, C(disabled[0]))
    pal.setColor(P.Disabled, P.Base, C(disabled[1]))
    pal.setColor(P.Disabled, P.Button, C(disabled[2]))
    app.setPalette(pal)
    # Stylesheets mit palette(...)-Verweisen neu auswerten
    for w in app.allWidgets():
        if w.styleSheet():
            w.setStyleSheet(w.styleSheet())


class AppearanceManager(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.settings = QtCore.QSettings()
        try:
            d = json.loads(self.settings.value("appearance", "{}"))
            self.current = Appearance(**{k: d[k] for k in Appearance.__dataclass_fields__ if k in d})
        except (ValueError, TypeError):
            self.current = Appearance()

    def set(self, ap: Appearance) -> None:
        self.current = ap
        self.settings.setValue("appearance", json.dumps(asdict(ap)))
        app = QtWidgets.QApplication.instance()
        if app is not None:
            apply_palette(app, ap.dark)
        self.changed.emit()

    def apply_initial(self, app: QtWidgets.QApplication) -> None:
        apply_palette(app, self.current.dark)

    def style_plot(self, plot_item: pg.PlotItem) -> None:
        a = self.current
        for name in ("left", "bottom", "right", "top"):
            ax = plot_item.getAxis(name)
            ax.setPen(pg.mkPen(a.plot_fg))
            ax.setTextPen(pg.mkPen(a.plot_fg))
        plot_item.showGrid(x=True, y=True, alpha=a.grid)
        if plot_item.legend is not None:
            plot_item.legend.setLabelTextColor(a.plot_fg)


_manager: AppearanceManager | None = None


def appearance() -> AppearanceManager:
    global _manager
    if _manager is None:
        _manager = AppearanceManager()
    return _manager


class AppearanceDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Darstellung")
        a = appearance().current
        form = QtWidgets.QFormLayout(self)
        self.theme = QtWidgets.QComboBox()
        for k, v in THEMES.items():
            self.theme.addItem(v, k)
        self.theme.setCurrentIndex(self.theme.findData(a.theme))
        self.width = QtWidgets.QDoubleSpinBox()
        self.width.setRange(0.5, 6.0)
        self.width.setSingleStep(0.5)
        self.width.setDecimals(1)
        self.width.setSuffix(" px")
        self.width.setValue(a.line_width)
        self.grid = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.grid.setRange(0, 100)
        self.grid.setValue(int(a.grid * 100))
        self.palette = QtWidgets.QComboBox()
        for k, (label, cols) in PALETTES.items():
            self.palette.addItem(self._swatch(cols), label, k)
        self.palette.setIconSize(QtCore.QSize(110, 14))
        self.palette.setCurrentIndex(max(self.palette.findData(a.palette), 0))
        self.recolor = QtWidgets.QCheckBox("Vorhandene Messungen neu einfärben")
        self.recolor.setChecked(True)
        form.addRow("Farbschema:", self.theme)
        form.addRow("Linienstärke:", self.width)
        form.addRow("Gitterlinien:", self.grid)
        form.addRow("Kurvenfarben:", self.palette)
        form.addRow(self.recolor)
        hint = QtWidgets.QLabel("Einzelne Kurven lassen sich zusätzlich im Tab „Impedanz“ über "
                                "„Farbe …“ umfärben.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        form.addRow(hint)
        from .de import button_box
        bb = button_box(self, "Ok", "Apply", "Cancel")
        bb.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(self.apply)
        form.addRow(bb)
        self._applied = False

    @staticmethod
    def _swatch(cols: list[str]) -> QtGui.QIcon:
        pm = QtGui.QPixmap(110, 14)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        for i, c in enumerate(cols[:10]):
            p.fillRect(i * 11, 0, 10, 14, QtGui.QColor(c))
        p.end()
        return QtGui.QIcon(pm)

    def value(self) -> Appearance:
        return Appearance(theme=self.theme.currentData(), line_width=self.width.value(),
                          palette=self.palette.currentData(), grid=self.grid.value() / 100)

    def apply(self):
        appearance().set(self.value())
        self._applied = True

    def accept(self):
        self.apply()
        super().accept()
