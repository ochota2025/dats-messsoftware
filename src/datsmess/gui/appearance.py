"""Darstellungs-Einstellungen: Farbschema (hell/dunkel), Kurvenfarben, Linienstärke.

Ein zentraler ``AppearanceManager`` hält die Einstellungen, speichert sie in den
QSettings und meldet Änderungen über das Signal ``changed``; Diagramme und Fenster
passen sich daraufhin sofort an.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

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

    # Oberflächen-Design (abgestimmt auf das Programmsymbol)
    @property
    def accent(self) -> str:
        return "#3d9bff" if self.dark else "#1f6fd6"

    @property
    def accent_hi(self) -> str:          # Verlauf hell (wie im Symbol)
        return "#4aa6ff" if self.dark else "#3aa0ff"

    @property
    def accent_lo(self) -> str:          # Verlauf dunkel
        return "#1660c4" if self.dark else "#1259b8"

    @property
    def accent_tint(self) -> str:        # dezente Akzentfläche (Hover, Auswahl)
        return "#1f3550" if self.dark else "#e6f0fd"

    @property
    def window_bg(self) -> str:
        return "#16181c" if self.dark else "#eef2f7"

    @property
    def card_bg(self) -> str:
        return "#202328" if self.dark else "#ffffff"

    @property
    def input_bg(self) -> str:
        return "#1a1c20" if self.dark else "#f7f9fc"

    @property
    def header_bg(self) -> str:
        return "#262a30" if self.dark else "#f3f6fa"

    @property
    def border(self) -> str:
        return "#323740" if self.dark else "#dbe2ec"

    @property
    def border_strong(self) -> str:
        return "#454b56" if self.dark else "#c3ccd8"

    @property
    def text(self) -> str:
        return "#e6e9ed" if self.dark else "#1b2430"

    @property
    def muted(self) -> str:
        return "#99a3b0" if self.dark else "#667185"


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
            P.Window: "#16181c", P.WindowText: "#e6e9ed", P.Base: "#202328", P.AlternateBase: "#262a30",
            P.Text: "#e6e9ed", P.Button: "#2a2e35", P.ButtonText: "#e6e9ed", P.BrightText: "#ffffff",
            P.Highlight: "#2f7fd8", P.HighlightedText: "#ffffff", P.ToolTipBase: "#2a2e35",
            P.ToolTipText: "#e6e9ed", P.PlaceholderText: "#99a3b0", P.Link: "#6cb4ff",
            P.Light: "#454b56", P.Midlight: "#3a3f48", P.Mid: "#454b56", P.Dark: "#121418", P.Shadow: "#000000",
        }
        disabled = ("#6e7076", "#25272a", "#2e3034")
    else:
        colors = {
            P.Window: "#eef2f7", P.WindowText: "#1b2430", P.Base: "#ffffff", P.AlternateBase: "#f3f6fa",
            P.Text: "#1b2430", P.Button: "#ffffff", P.ButtonText: "#1b2430", P.BrightText: "#ffffff",
            P.Highlight: "#1f6fd6", P.HighlightedText: "#ffffff", P.ToolTipBase: "#ffffff",
            P.ToolTipText: "#1b2430", P.PlaceholderText: "#667185", P.Link: "#1f6fd6",
            P.Light: "#ffffff", P.Midlight: "#e3e8ef", P.Mid: "#c3ccd8", P.Dark: "#9aa5b4", P.Shadow: "#5a5a5a",
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
    app.setStyleSheet(stylesheet(Appearance(theme="dark" if dark else "light")))
    # Stylesheets mit palette(...)-Verweisen neu auswerten
    for w in app.allWidgets():
        if w.styleSheet():
            w.setStyleSheet(w.styleSheet())


RESOURCES = Path(__file__).resolve().parents[1] / "resources"


def _res(name: str) -> str:
    return (RESOURCES / name).as_posix()


def stylesheet(a: Appearance) -> str:
    """Modernes, flaches Design im Stil des Programmsymbols (Karten, runde Ecken, blauer Akzent)."""
    mode = "dark" if a.dark else "light"
    down, up, check = _res(f"ui_down_{mode}.png"), _res(f"ui_up_{mode}.png"), _res("ui_check_white.png")
    return f"""
QMainWindow, QDialog, QWizard {{ background: {a.window_bg}; }}
QWidget#sidebar, QScrollArea#sidebarScroll, QScrollArea#sidebarScroll > QWidget > QWidget {{ background: {a.window_bg}; }}
QLabel#brandTitle {{ font-size: 15px; font-weight: 700; color: {a.text}; }}
QLabel#brandSub {{ font-size: 11px; color: {a.muted}; }}

QGroupBox {{
    background: {a.card_bg}; border: 1px solid {a.border}; border-radius: 12px;
    margin-top: 18px; padding: 8px 8px 6px 8px; font-weight: 600; color: {a.muted};
}}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 8px; top: 1px;
    padding: 0 2px; color: {a.muted}; font-weight: 600; }}
QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QRadioButton {{ font-weight: normal; color: {a.text}; }}
QGroupBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {a.border_strong};
    background: {a.input_bg}; }}
QGroupBox::indicator:checked {{ background: {a.accent}; border-color: {a.accent}; image: url({check}); }}

QPushButton, QToolButton {{
    background: {a.card_bg}; color: {a.text}; border: 1px solid {a.border_strong}; border-radius: 8px;
    padding: 4px 12px; min-height: 18px;
}}
QPushButton:hover, QToolButton:hover {{ border-color: {a.accent}; background: {a.accent_tint}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {a.border}; }}
QPushButton:checked {{ background: {a.accent}; border-color: {a.accent}; color: white; }}
QPushButton:disabled, QToolButton:disabled {{ color: {a.muted}; border-color: {a.border}; background: {a.window_bg}; }}
QPushButton:default {{ border-color: {a.accent}; }}
QPushButton#primary {{
    color: white; font-size: 15px; font-weight: 700; border: none; border-radius: 11px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {a.accent_hi}, stop:1 {a.accent_lo});
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #5cb2ff, stop:1 {a.accent});
}}
QPushButton#primary:pressed {{ background: {a.accent_lo}; }}
QPushButton#primary:disabled {{ background: {a.border_strong}; color: {a.card_bg}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {a.input_bg}; color: {a.text}; border: 1px solid {a.border}; border-radius: 7px;
    padding: 3px 6px; selection-background-color: {a.accent}; selection-color: white;
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QPlainTextEdit:hover {{
    border-color: {a.border_strong}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus,
QTextEdit:focus {{ border: 1px solid {a.accent}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {a.muted};
    background: {a.window_bg}; }}
QComboBox {{ padding-right: 24px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 22px; border: none; }}
QComboBox::down-arrow {{ image: url({down}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {a.card_bg}; color: {a.text}; border: 1px solid {a.border};
    border-radius: 6px; padding: 4px; selection-background-color: {a.accent_tint}; selection-color: {a.text};
    outline: none; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; border: none; border-top-right-radius: 7px; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; border: none; border-bottom-right-radius: 7px; background: transparent; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {a.accent_tint}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({up}); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}

QCheckBox, QRadioButton {{ spacing: 7px; color: {a.text}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {a.border_strong};
    background: {a.input_bg}; }}
QCheckBox::indicator:hover {{ border-color: {a.accent}; }}
QCheckBox::indicator:checked {{ background: {a.accent}; border-color: {a.accent}; image: url({check}); }}
QCheckBox::indicator:disabled {{ background: {a.window_bg}; border-color: {a.border}; }}
QListView::indicator, QTableView::indicator {{ width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {a.border_strong}; background: {a.input_bg}; }}
QListView::indicator:checked, QTableView::indicator:checked {{ background: {a.accent}; border-color: {a.accent};
    image: url({check}); }}

QTabWidget::pane {{ border: none; border-top: 1px solid {a.border}; top: -1px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {a.muted}; border: none; border-bottom: 3px solid transparent;
    padding: 8px 13px 7px 13px; margin-right: 1px; font-weight: 600; }}
QTabBar::tab:hover {{ color: {a.text}; border-bottom-color: {a.border_strong}; }}
QTabBar::tab:selected {{ color: {a.accent}; border-bottom-color: {a.accent}; }}

QListWidget, QListView, QTableWidget, QTableView, QTreeView, QTextBrowser {{
    background: {a.card_bg}; color: {a.text}; border: 1px solid {a.border}; border-radius: 10px;
    alternate-background-color: {a.header_bg}; gridline-color: {a.border};
    selection-background-color: {a.accent_tint}; selection-color: {a.text}; outline: none;
}}
QListWidget::item, QListView::item {{ padding: 3px 4px; border-radius: 6px; }}
QListWidget::item:hover, QListView::item:hover {{ background: {a.header_bg}; }}
QListWidget::item:selected, QListView::item:selected {{ background: {a.accent_tint}; color: {a.text}; }}
QHeaderView::section {{ background: {a.header_bg}; color: {a.muted}; border: none;
    border-bottom: 1px solid {a.border}; border-right: 1px solid {a.border}; padding: 4px 6px; font-weight: 600; }}
QTableCornerButton::section {{ background: {a.header_bg}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {a.border_strong}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {a.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{ background: {a.border}; border: none; border-radius: 3px; text-align: center; color: {a.text}; }}
QProgressBar::chunk {{ border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {a.accent_hi}, stop:1 {a.accent_lo}); }}

QMenuBar {{ background: {a.window_bg}; color: {a.text}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 6px; background: transparent; }}
QMenuBar::item:selected {{ background: {a.accent_tint}; }}
QMenu {{ background: {a.card_bg}; color: {a.text}; border: 1px solid {a.border}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 26px 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {a.accent_tint}; color: {a.text}; }}
QMenu::item:disabled {{ color: {a.muted}; }}
QMenu::separator {{ height: 1px; background: {a.border}; margin: 5px 8px; }}
QMenu::indicator:checked {{ image: url({check}); background: {a.accent}; border-radius: 4px; width: 14px;
    height: 14px; left: 4px; }}

QStatusBar {{ background: {a.window_bg}; color: {a.muted}; border-top: 1px solid {a.border}; }}
QStatusBar QLabel {{ color: {a.text}; }}
QToolTip {{ background: {a.card_bg}; color: {a.text}; border: 1px solid {a.border_strong}; border-radius: 6px;
    padding: 5px 7px; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}
QSlider::groove:horizontal {{ height: 4px; background: {a.border}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; background: {a.accent}; }}
QSlider::sub-page:horizontal {{ background: {a.accent}; border-radius: 2px; }}
QWizard QFrame {{ background: transparent; }}
"""


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
