"""Sofort-Kennwerte: fs, Re, Q-Werte, Zmax, Le direkt nach jeder Messung.

Für jede sichtbare Kurve eine Spalte – so lassen sich Speicherplätze unmittelbar vergleichen.
Werte, die eine Zweitmessung brauchen (Vas, Mms, Bl …), liefert der Tab „T/S-Parameter“.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ..analysis.ts import ImpedanceFit, quick_parameters
from .appearance import appearance
from .state import AppState

ROWS = [
    ("fs  Hz", lambda f: f.fs, "{:.2f}"),
    ("Re  Ω", lambda f: f.Re, "{:.3f}"),
    ("Qms", lambda f: f.Qms, "{:.3f}"),
    ("Qes", lambda f: f.Qes, "{:.3f}"),
    ("Qts", lambda f: f.Qts, "{:.3f}"),
    ("Zmax  Ω", lambda f: f.Zmax, "{:.1f}"),
    ("Le  mH", lambda f: f.le_at(1000.0) * 1e3, "{:.3f}"),
]


class QuickParams(QtWidgets.QGroupBox):
    def __init__(self, state: AppState):
        super().__init__("Kennwerte")
        self.state = state
        self._cache: dict[str, tuple[int, ImpedanceFit | None]] = {}
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.table = QtWidgets.QTableWidget(len(ROWS), 0)
        self.table.setVerticalHeaderLabels([r[0] for r in ROWS])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.table.horizontalHeader().setDefaultSectionSize(56)
        self.table.horizontalHeader().setMinimumSectionSize(48)
        self.table.verticalHeader().setDefaultSectionSize(21)
        self.table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        self.table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        head_h = self.table.fontMetrics().height() + 12
        scroll_h = self.table.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent) + 2
        self.table.setFixedHeight(head_h + 21 * len(ROWS) + scroll_h + 4)
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

    def refresh(self):
        visible = [m for m in self.state.measurements if m.visible]
        self.table.setColumnCount(len(visible))
        any_driver = False
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
            any_driver |= fit is not None
            for r, (_label, getter, fmt) in enumerate(ROWS):
                if fit is None:
                    it = QtWidgets.QTableWidgetItem("–")
                    it.setToolTip("Keine Lautsprecherresonanz erkannt – für Bauteile den Tab "
                                  "„Bauteile (LCR)“ verwenden.")
                else:
                    it = QtWidgets.QTableWidgetItem(fmt.format(getter(fit)))
                    it.setToolTip(f"Modellabweichung {fit.rms_error * 100:.1f} %")
                it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                if r == 4 and fit is not None:      # Qts hervorheben
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.table.setItem(r, c, it)
        hh = self.table.horizontalHeader()
        fits = len(visible) * 64 <= max(self.table.viewport().width(), 200)
        hh.setSectionResizeMode(QtWidgets.QHeaderView.Stretch if fits else QtWidgets.QHeaderView.Interactive)
        if not visible:
            self.hint.setText("Nach einer Treibermessung erscheinen hier fs, Re und die Gütefaktoren.")
        elif any_driver:
            self.hint.setText("Vas, Mms, Bl … brauchen eine Zweitmessung → Tab „T/S-Parameter“.")
        else:
            self.hint.setText("Keine Lautsprecherresonanz in den sichtbaren Kurven.")
