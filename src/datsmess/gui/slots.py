"""Speicherplätze 1 … 8 als Reiterleiste (feste Plätze für Vergleich und T/S-Berechnung).

Bedienung:
* Klick auf einen leeren Platz  → aktuelle Messung dort ablegen
* Klick auf einen belegten Platz → ein-/ausblenden
* Rechtsklick                    → ablegen, umbenennen, als A/B für T/S, exportieren, leeren
* Strg+1 … 8 (Mac: ⌘1 … 8)       → aktuelle Messung auf Platz ablegen
* Alt+1 … 8                      → Platz ein-/ausblenden
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from .appearance import appearance
from .de import get_text
from .state import N_SLOTS, AppState

MOD = "⌘" if QtCore.QSysInfo.productType() == "macos" else "Strg+"
ALT = "⌥" if QtCore.QSysInfo.productType() == "macos" else "Alt+"


class SlotBar(QtWidgets.QWidget):
    useForTS = QtCore.Signal(int, str)       # Platz, "A" oder "B"
    exportSlot = QtCore.Signal(int)

    def __init__(self, state: AppState, current_provider):
        super().__init__()
        self.state = state
        self.current_provider = current_provider   # () -> Measurement | None
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(4)
        lbl = QtWidgets.QLabel("Speicherplätze:")
        lay.addWidget(lbl)
        self.buttons: list[QtWidgets.QToolButton] = []
        for i in range(N_SLOTS):
            b = QtWidgets.QToolButton()
            b.setCheckable(True)
            b.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
            b.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            b.clicked.connect(lambda _c=False, i=i: self._clicked(i))
            b.customContextMenuRequested.connect(lambda _p, i=i: self._menu(i))
            lay.addWidget(b)
            self.buttons.append(b)
        state.slotsChanged.connect(self.refresh)
        state.measurementsChanged.connect(self.refresh)
        appearance().changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        for i, b in enumerate(self.buttons):
            m = self.state.slot_measurement(i)
            color = self.state.slot_color(i)
            if m:
                short = m.name if len(m.name) <= 16 else m.name[:15] + "…"
                b.setText(f"{i + 1}  {short}")
                b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                b.setMinimumWidth(b.fontMetrics().horizontalAdvance(b.text()) + 22)
            else:
                b.setText(str(i + 1))
                b.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
                b.setMinimumWidth(30)
            b.blockSignals(True)
            b.setChecked(bool(m) and self.state.slot_visible[i])
            b.blockSignals(False)
            style = "solid" if m else "dotted"
            text = "palette(button-text)" if m else "palette(placeholder-text)"
            b.setStyleSheet(
                f"QToolButton {{ color: {text}; border: 1px solid palette(mid); border-bottom: 4px {style} {color};"
                f" border-radius: 3px; padding: 3px 6px; }}"
                f"QToolButton:checked {{ background: palette(alternate-base); font-weight: bold; }}")
            if m:
                tip = (f"Platz {i + 1}: {m.name}\nKlick: ein-/ausblenden ({ALT}{i + 1})\n"
                       f"Rechtsklick: weitere Aktionen")
            else:
                tip = f"Platz {i + 1} ist leer\nKlick oder {MOD}{i + 1}: aktuelle Messung hier ablegen"
            b.setToolTip(tip)

    def _clicked(self, i: int):
        if self.state.slot_measurement(i) is None:
            self.store(i)
        else:
            self.state.toggle_slot(i)

    def store(self, i: int):
        m = self.current_provider()
        if m is None:
            self.state.status.emit("Keine Messung vorhanden, die abgelegt werden könnte.")
            self.refresh()
            return
        self.state.store_in_slot(i, m)

    def _menu(self, i: int):
        m = self.state.slot_measurement(i)
        menu = QtWidgets.QMenu(self)
        cur = self.current_provider()
        a = menu.addAction(f"Aktuelle Messung hier ablegen\t{MOD}{i + 1}")
        a.setEnabled(cur is not None)
        a.triggered.connect(lambda: self.store(i))
        if m is not None:
            menu.addAction(f"Ein-/ausblenden\t{ALT}{i + 1}", lambda: self.state.toggle_slot(i))
            menu.addSeparator()
            menu.addAction("Als A (Freiluft) für T/S verwenden", lambda: self.useForTS.emit(i, "A"))
            menu.addAction("Als B (Zusatzmasse/Testbox) für T/S verwenden", lambda: self.useForTS.emit(i, "B"))
            menu.addSeparator()
            menu.addAction("Umbenennen …", lambda: self._rename(i))
            menu.addAction("Exportieren …", lambda: self.exportSlot.emit(i))
            menu.addAction("Platz leeren", lambda: self.state.clear_slot(i))
        menu.exec(QtGui.QCursor.pos())

    def _rename(self, i: int):
        m = self.state.slot_measurement(i)
        if m is None:
            return
        name, ok = get_text(self, "Umbenennen", f"Neuer Name für Platz {i + 1}:", m.name)
        if ok and name.strip():
            m.name = name.strip()
            self.state.measurementsChanged.emit()
