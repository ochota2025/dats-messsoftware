"""Impedanz-Tab mit Messliste, Overlay-/Vergleichsmodus und Export (FN-01, DM-01, DM-02)."""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

import json

from ..io.formats import FORMATS, TextExportOptions, export_impedance, import_impedance
from ..measurement import Measurement, reprocess
from .de import germanize, get_item, get_text
from .params_panel import QuickParams
from .slots import SlotBar
from .dialogs import ExportDialog
from .plots import SMOOTHING, VIEWS, Curve, ImpedancePlot, display_data
from .state import AppState


class ImpedanceTab(QtWidgets.QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state

        # Werkzeugleiste
        bar = QtWidgets.QHBoxLayout()
        self.view = QtWidgets.QComboBox()
        for k, v in VIEWS.items():
            self.view.addItem(v, k)
        self.smoothing = QtWidgets.QComboBox()
        self.smoothing.addItems(list(SMOOTHING))
        self.log_y = QtWidgets.QCheckBox("|Z| logarithmisch")
        self.auto_hide = QtWidgets.QCheckBox("Ältere ausblenden")
        self.auto_hide.setToolTip("Bei einer neuen Messung alle Messungen ausblenden, "
                                  "die auf keinem Speicherplatz liegen")
        self.auto_hide.setChecked(state.auto_hide)
        self.auto_hide.toggled.connect(lambda on: setattr(state, "auto_hide", on))
        btn_fit = QtWidgets.QPushButton("Ansicht anpassen")
        bar.addWidget(QtWidgets.QLabel("Ansicht:"))
        bar.addWidget(self.view)
        bar.addSpacing(12)
        bar.addWidget(QtWidgets.QLabel("Glättung:"))
        bar.addWidget(self.smoothing)
        bar.addSpacing(12)
        bar.addWidget(self.log_y)
        bar.addSpacing(12)
        bar.addWidget(self.auto_hide)
        bar.addStretch(1)
        bar.addWidget(btn_fit)

        self.plot = ImpedancePlot()

        # Messliste
        side = QtWidgets.QWidget()
        side.setMaximumWidth(340)
        side.setMinimumWidth(250)
        sl = QtWidgets.QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        self.params = QuickParams(state)
        sl.addWidget(self.params)
        sl.addWidget(QtWidgets.QLabel("<b>Messungen</b> (Haken = im Diagramm)"))
        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        sl.addWidget(self.list, 1)
        grid = QtWidgets.QGridLayout()
        self.btn_import = QtWidgets.QPushButton("Importieren …")
        self.btn_export = QtWidgets.QPushButton("Exportieren …")
        self.btn_rename = QtWidgets.QPushButton("Umbenennen")
        self.btn_color = QtWidgets.QPushButton("Farbe …")
        self.btn_remove = QtWidgets.QPushButton("Entfernen")
        self.btn_all = QtWidgets.QPushButton("Alle ein/aus")
        self.btn_reprocess = QtWidgets.QPushButton("Neu berechnen")
        self.btn_reprocess.setToolTip("Ausgewählte Messungen aus den Sweep-Rohdaten mit der aktuellen "
                                      "Kalibrierung neu berechnen")
        self.btn_watch = QtWidgets.QPushButton("→ Watch-Folder")
        self.btn_watch.setToolTip("Ausgewählte Messungen als .zma (+ .tsp) an den Watch-Folder übergeben")
        for i, b in enumerate((self.btn_import, self.btn_export, self.btn_rename, self.btn_color,
                               self.btn_remove, self.btn_all, self.btn_reprocess, self.btn_watch)):
            grid.addWidget(b, i // 2, i % 2)
        sl.addLayout(grid)

        split = QtWidgets.QSplitter()
        pw = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(pw)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addLayout(bar)
        self.slot_bar = SlotBar(state, self.current_measurement)
        pl.addWidget(self.slot_bar)
        pl.addWidget(self.plot, 1)
        split.addWidget(pw)
        split.addWidget(side)
        split.setStretchFactor(0, 1)
        lay = QtWidgets.QHBoxLayout(self)
        lay.addWidget(split)

        self.view.currentIndexChanged.connect(lambda: self.plot.set_mode(self.view.currentData()))
        self.smoothing.currentIndexChanged.connect(lambda _i: self.redraw())
        self.log_y.toggled.connect(self.plot.set_log_y)
        self.plot.logYChanged.connect(self._sync_log_y)
        btn_fit.clicked.connect(lambda: (self.plot.top.enableAutoRange(), self.plot.bottom.enableAutoRange()))
        self.list.itemChanged.connect(self._item_changed)
        self.list.itemDoubleClicked.connect(lambda it: self._rename(it.data(QtCore.Qt.UserRole)))
        self.btn_rename.setToolTip("Markierte Messung umbenennen (ohne Markierung: neueste). "
                                   "Alternativ Doppelklick auf die Messung.")
        self.btn_color.setToolTip("Farbe der markierten Messungen ändern (ohne Markierung: neueste)")
        self.btn_import.clicked.connect(self.import_files)
        self.btn_export.clicked.connect(self.export_selected)
        self.btn_rename.clicked.connect(self._rename)
        self.btn_color.clicked.connect(self._color)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_all.clicked.connect(self._toggle_all)
        self.btn_reprocess.clicked.connect(self._reprocess)
        self.btn_watch.clicked.connect(self.deliver_selected)
        state.measurementsChanged.connect(self.refresh)

    # ------------------------------------------------------------------
    def refresh(self):
        self.list.blockSignals(True)
        self.list.clear()
        for m in self.state.measurements:
            it = QtWidgets.QListWidgetItem(m.name)
            it.setData(QtCore.Qt.UserRole, m)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if m.visible else QtCore.Qt.Unchecked)
            pm = QtGui.QPixmap(14, 14)
            pm.fill(QtGui.QColor(m.color or "#000"))
            it.setIcon(QtGui.QIcon(pm))
            tip = [m.created, "kalibriert" if m.meta.get("calibrated") else "unkalibriert / importiert",
                   m.meta.get("device", m.meta.get("source", ""))]
            it.setToolTip("\n".join(t for t in tip if t))
            self.list.addItem(it)
        self.list.blockSignals(False)
        self.redraw(autorange=True)

    def redraw(self, autorange=False):
        sm = SMOOTHING[self.smoothing.currentText()]
        curves = []
        for m in self.state.measurements:
            if m.visible:
                f, Z = display_data(m, sm)
                curves.append(Curve(m.name, f, Z, m.color or "#1f77b4"))
        self.plot.set_curves(curves, autorange=bool(autorange))

    def _item_changed(self, it):
        m: Measurement = it.data(QtCore.Qt.UserRole)
        m.visible = it.checkState() == QtCore.Qt.Checked
        if it.text() != m.name:
            m.name = it.text()
        self.redraw()

    def _sync_log_y(self, on: bool):
        self.log_y.blockSignals(True)
        self.log_y.setChecked(on)
        self.log_y.blockSignals(False)

    def _selected(self) -> list[Measurement]:
        return [it.data(QtCore.Qt.UserRole) for it in self.list.selectedItems()]

    def _need_selection(self, action: str) -> list[Measurement]:
        sel = self._selected()
        if not sel:
            QtWidgets.QMessageBox.information(
                self, action, "Bitte zuerst rechts in der Liste eine oder mehrere Messungen anklicken "
                              "(Strg/⌘ bzw. Umschalt für Mehrfachauswahl).")
        return sel

    def _rename(self, m: Measurement | None = None):
        m = m or self.current_measurement()          # markierte, sonst neueste Messung
        if m is None:
            return
        name, ok = get_text(self, "Umbenennen", "Neuer Name:", m.name)
        if ok and name.strip():
            m.name = name.strip()
            self.state.measurementsChanged.emit()

    def _color(self):
        sel = self._selected() or ([self.current_measurement()] if self.current_measurement() else [])
        if not sel:
            return
        dlg = QtWidgets.QColorDialog(QtGui.QColor(sel[0].color or "#1f77b4"), self)
        dlg.setWindowTitle(f"Kurvenfarbe – {sel[0].name}" if len(sel) == 1 else "Kurvenfarbe")
        bb = dlg.findChild(QtWidgets.QDialogButtonBox)
        if bb is not None:
            germanize(bb)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.selectedColor().isValid():
            for m in sel:
                m.color = dlg.selectedColor().name()
            self.state.measurementsChanged.emit()

    def _remove(self):
        sel = self._need_selection("Entfernen")
        for m in sel:
            self.state.measurements.remove(m)
        if sel:
            self.state.measurementsChanged.emit()

    def _toggle_all(self):
        on = not all(m.visible for m in self.state.measurements)
        for m in self.state.measurements:
            m.visible = on
        self.state.measurementsChanged.emit()

    # -- Import / Export -------------------------------------------------
    def import_files(self):
        filt = "Messdaten (*.zma *.frd *.txt *.csv);;Alle Dateien (*)"
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Messkurven importieren", "", filt)
        for p in paths:
            try:
                f, Z = import_impedance(p)
            except Exception as e:      # noqa: BLE001
                QtWidgets.QMessageBox.warning(self, "Import", f"{Path(p).name}: {e}")
                continue
            self.state.add_measurement(Measurement(Path(p).stem, f, Z, meta={"source": p}))
        if paths:
            self.state.status.emit(f"{len(paths)} Datei(en) importiert.")

    def current_measurement(self) -> Measurement | None:
        """Für Speicherplätze: genau eine markierte Messung, sonst die neueste."""
        sel = self._selected()
        return sel[0] if len(sel) == 1 else self.state.current_measurement()

    def export_selected(self, measurements: list[Measurement] | None = None):
        sel = measurements or self._selected() or (
            [self.state.measurements[-1]] if self.state.measurements else [])
        if not sel:
            QtWidgets.QMessageBox.information(self, "Export", "Keine Messung vorhanden.")
            return
        filters = ";;".join(FORMATS.values())
        if len(sel) == 1:
            path, chosen = QtWidgets.QFileDialog.getSaveFileName(self, "Messung exportieren",
                                                                 f"{sel[0].name}.zma", filters)
            if not path:
                return
            if not Path(path).suffix:
                path += next(e for e, d in FORMATS.items() if d == chosen)
            targets = [(sel[0], Path(path))]
            ext = Path(path).suffix.lower()
        else:
            folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Zielordner wählen")
            if not folder:
                return
            ext, ok = get_item(self, "Format", "Dateiformat:", list(FORMATS))
            if not ok:
                return
            targets = [(m, Path(folder) / f"{m.name}{ext}") for m in sel]
        if ext not in FORMATS:
            QtWidgets.QMessageBox.warning(self, "Export", f"Unbekanntes Format: {ext}")
            return
        settings = QtCore.QSettings()
        try:
            saved = TextExportOptions.from_dict(json.loads(settings.value(f"export_opts{ext}", "{}")))
        except (ValueError, TypeError):
            saved = TextExportOptions()
        if ext == ".csv" and not settings.contains(f"export_opts{ext}"):
            saved.delimiter = "comma"
        dlg = ExportDialog(ext, saved, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        opt = dlg.options()
        n, frac = dlg.resampling()
        settings.setValue(f"export_opts{ext}", json.dumps(opt.to_dict()))
        for m, p in targets:
            f, Z = m.resampled(n, frac) if n else (m.f, m.Z)
            header = [f"Name: {m.name}", f"Datum: {m.created}",
                      f"Kalibriert: {'ja' if m.meta.get('calibrated') else 'nein'}"]
            if m.meta.get("Re") is not None:
                header.append(f"Re = {m.meta['Re']:.4f} Ohm")
            header.append("Erzeugt mit DATS-Messsoftware")
            export_impedance(p, f, Z, header, opt)
        self.state.status.emit(f"{len(targets)} Datei(en) exportiert.")

    # -- Rohdaten / Watch-Folder -------------------------------------------
    def _reprocess(self):
        sel = self._need_selection("Neu berechnen")
        if not sel:
            return
        cal = self.state.engine.calibration
        done, skipped = 0, []
        for m in sel:
            try:
                m.Z = reprocess(m, cal)
            except ValueError as e:
                skipped.append(str(e))
                continue
            m.meta["calibrated"] = cal is not None
            m.meta["calibration_id"] = cal.id if cal is not None else None
            done += 1
        self.state.measurementsChanged.emit()
        msg = f"{done} Messung(en) mit {'aktueller' if cal else 'ohne'} Kalibrierung neu berechnet."
        if skipped:
            QtWidgets.QMessageBox.information(self, "Neu berechnen", msg + "\n\n" + "\n".join(skipped))
        self.state.status.emit(msg)

    def deliver_selected(self):
        sel = self._selected() or ([self.state.measurements[-1]] if self.state.measurements else [])
        if not sel:
            return
        if not self.state.watch.path:
            QtWidgets.QMessageBox.information(self, "Watch-Folder", "Bitte zuerst unter Datei → "
                                              "Watch-Folder … einen Ordner einstellen.")
            return
        try:
            for m in sel:
                self.state.deliver(m)
        except Exception as e:      # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "Watch-Folder", str(e))
