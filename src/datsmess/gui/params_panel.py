"""Sofort-Kennwerte: fs, Re, Q-Werte, Zmax, Le direkt nach jeder Messung.

Große Kacheln für die markierte (sonst neueste) Messung; sind mehrere Kurven sichtbar, zeigt eine
kleine Tabelle darunter alle nebeneinander – so lassen sich Speicherplätze direkt vergleichen.
Werte, die eine Zweitmessung brauchen (Vas, Mms, Bl …), liefert der Tab „T/S-Parameter“.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ..analysis.quality import GRADE_LABEL, grade
from ..analysis.ts import ImpedanceFit, quick_parameters
from .appearance import appearance
from .state import AppState

# (Schlüssel, Kurzname, Einheit, Wert, Format, Erklärung)
TILES = [
    ("fs", "fs", "Hz", lambda f: f.fs, "{:.2f}", "Resonanzfrequenz"),
    ("Qts", "Qts", "", lambda f: f.Qts, "{:.3f}", "Gesamtgüte – bestimmt, welches Gehäuse passt"),
    ("Re", "Re", "Ω", lambda f: f.Re, "{:.3f}", "Gleichstromwiderstand der Schwingspule"),
    ("Qes", "Qes", "", lambda f: f.Qes, "{:.3f}", "Elektrische Güte"),
    ("Zmax", "Zmax", "Ω", lambda f: f.Zmax, "{:.1f}", "Impedanz bei der Resonanz"),
    ("Qms", "Qms", "", lambda f: f.Qms, "{:.3f}", "Mechanische Güte"),
    ("Le", "Le 1 kHz", "mH", lambda f: f.le_at(1000.0) * 1e3, "{:.3f}", "Induktivität der Schwingspule bei 1 kHz"),
]
ROWS = [(f"{name}  {unit}".strip(), get, fmt) for _k, name, unit, get, fmt, _d in TILES]


class Tile(QtWidgets.QFrame):
    """Eine Kennwert-Kachel: Bezeichnung klein, Wert groß, Einheit daneben."""

    def __init__(self, label: str, unit: str, tip: str, accent: bool = False):
        super().__init__()
        self.setObjectName("tileAccent" if accent else "tile")
        self.setToolTip(tip)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(0)
        self.lbl = QtWidgets.QLabel(label)
        self.lbl.setObjectName("tileLabel")
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        self.val = QtWidgets.QLabel("–")
        self.val.setObjectName("tileValue")
        self.val.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.unit = QtWidgets.QLabel(unit)
        self.unit.setObjectName("tileUnit")
        row.addWidget(self.val)
        row.addWidget(self.unit, 0, QtCore.Qt.AlignBottom)
        row.addStretch(1)
        lay.addWidget(self.lbl)
        lay.addLayout(row)
        self.setMinimumHeight(56)                   # Wert nie abschneiden, auch wenn es eng wird
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

    def set_value(self, text: str, color: str | None = None):
        self.val.setText(text)
        self.val.setStyleSheet(f"color: {color};" if color else "")


class QuickParams(QtWidgets.QGroupBox):
    def __init__(self, state: AppState):
        super().__init__("Kennwerte")
        self.state = state
        self.focus_provider = None          # () -> Measurement | None (markierte bzw. neueste Messung)
        self._cache: dict[str, tuple[int, ImpedanceFit | None]] = {}
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.title = QtWidgets.QLabel()
        self.title.setObjectName("tileTitle")
        self.title.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(self.title)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(6)
        self.tiles: dict[str, Tile] = {}
        for i, (key, name, unit, _get, _fmt, tip) in enumerate(TILES):
            t = Tile(name, unit, tip, accent=key == "Qts")
            grid.addWidget(t, i // 2, i % 2)
            self.tiles[key] = t
        self.tiles["quality"] = Tile("Qualität · S/N", "", "Pegel, Rauschen, Übersteuerung – Details im "
                                                            "Tooltip der Messung in der Liste")
        grid.addWidget(self.tiles["quality"], 3, 1)
        lay.addLayout(grid)

        self.cmp_label = QtWidgets.QLabel("Alle sichtbaren Kurven")
        self.cmp_label.setObjectName("tileLabel")
        lay.addWidget(self.cmp_label)
        self.table = QtWidgets.QTableWidget(len(ROWS), 0)
        self.table.setVerticalHeaderLabels([r[0] for r in ROWS])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.table.horizontalHeader().setDefaultSectionSize(56)
        self.table.horizontalHeader().setMinimumSectionSize(48)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        self.table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        head_h = self.table.fontMetrics().height() + 12
        scroll_h = self.table.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent) + 2
        self.table.setFixedHeight(head_h + 20 * len(ROWS) + scroll_h + 4)
        self.table.setToolTip("Spalten: #n = Speicherplatz n, „neu“ = neueste Messung. "
                              "Vollständiger Name im Tooltip der Spaltenüberschrift.")
        lay.addWidget(self.table)
        self.hint = QtWidgets.QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.hint)

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        state.measurementsChanged.connect(self._schedule)
        state.slotsChanged.connect(self._schedule)
        appearance().changed.connect(self._schedule)
        self.refresh()

    def _schedule(self):
        self._timer.start(0)

    def fit_for(self, m) -> ImpedanceFit | None:
        key = id(m.Z)                       # neu berechnete Messung → neue Kennwerte
        hit = self._cache.get(m.id)
        if hit is None or hit[0] != key:
            hit = (key, quick_parameters(m.f, m.Z))
            self._cache[m.id] = hit
        return hit[1]

    def focus(self):
        m = self.focus_provider() if self.focus_provider else None
        return m or self.state.current_measurement()

    def refresh(self):
        a = appearance().current
        m = self.focus()
        fit = self.fit_for(m) if m is not None else None
        if m is None:
            self.title.setText(f"<span style='color:{a.muted}'>Noch keine Messung</span>")
        else:
            self.title.setText(f"<span style='color:{m.color or a.text}'>■</span>&nbsp; <b>{m.name}</b>")
        for key, _name, _unit, get, fmt, _tip in TILES:
            self.tiles[key].set_value(fmt.format(get(fit)) if fit is not None else "–",
                                      a.accent if key == "Qts" and fit is not None else None)
        q = m.meta.get("quality") if m is not None else None
        qt = self.tiles["quality"]
        if q:
            g, msgs = grade(q)
            qt.set_value(GRADE_LABEL[g], {"ok": a.ok, "warn": a.warn, "bad": a.err}[g])
            qt.unit.setText(f"{q['snr_db']:.0f} dB" if q.get("snr_db") is not None else "")
            qt.setToolTip("\n".join(msgs) or "Pegel und Rauschabstand in Ordnung.")
        else:
            qt.set_value("–")
            qt.unit.setText("")

        visible = [x for x in self.state.measurements if x.visible]
        many = len(visible) >= 2
        self.cmp_label.setVisible(many)
        self.table.setVisible(many)
        if many:
            self._fill_table(visible)
        if m is None:
            self.hint.setText("Nach einer Treibermessung erscheinen hier fs, Re und die Gütefaktoren.")
        elif fit is None:
            self.hint.setText("Keine Lautsprecherresonanz erkannt – für Bauteile den Tab „Bauteile (LCR)“ "
                              "verwenden.")
        else:
            self.hint.setText(f"Modellabweichung {fit.rms_error * 100:.1f} %. Vas, Mms, Bl … brauchen eine "
                              "Zweitmessung → Tab „T/S-Parameter“.")

    def _fill_table(self, visible):
        self.table.setColumnCount(len(visible))
        for c, m in enumerate(visible):
            slot = self.state.slot_of(m)
            title = f"Platz {slot + 1}: {m.name}" if slot is not None else m.name
            if slot is not None:
                short = f"#{slot + 1}"
            elif m is self.state.current_measurement():
                short = "neu"
            else:
                short = m.name[:5]
            head = QtWidgets.QTableWidgetItem(short)
            pm = QtGui.QPixmap(10, 10)
            pm.fill(QtGui.QColor(m.color or "#888"))
            head.setIcon(QtGui.QIcon(pm))
            head.setToolTip(title)
            self.table.setHorizontalHeaderItem(c, head)
            fit = self.fit_for(m)
            for r, (_label, getter, fmt) in enumerate(ROWS):
                it = QtWidgets.QTableWidgetItem("–" if fit is None else fmt.format(getter(fit)))
                it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                if r == 1 and fit is not None:      # Qts hervorheben
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.table.setItem(r, c, it)
        hh = self.table.horizontalHeader()
        fits = len(visible) * 64 <= max(self.table.viewport().width(), 200)
        hh.setSectionResizeMode(QtWidgets.QHeaderView.Stretch if fits else QtWidgets.QHeaderView.Interactive)
