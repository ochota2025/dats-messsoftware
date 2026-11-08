"""T/S-Parameter-Tab (FN-02, FN-03, FA-02)."""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..analysis.ts import (NEEDS_SECOND_MEASUREMENT, VAS_METHOD_LABELS, VasMethod, derive_ts,
                           fit_driver, sd_from_diameter)
from .. import __version__
from ..io.formats import export_parameters
from ..io.ts_export import PROFILES, profile_text, save_text, tsp_text
from .appearance import appearance, keep_scroll_wide_enough
from .de import ask
from .plots import Curve, ImpedancePlot
from .state import AppState


def _spin(lo, hi, val, dec=2, suffix="", step=None):
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    if suffix:
        s.setSuffix(" " + suffix)
    if step:
        s.setSingleStep(step)
    return s


class MeasurementCombo(QtWidgets.QComboBox):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        state.measurementsChanged.connect(self.refresh)
        state.slotsChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        cur = self.currentData()
        self.blockSignals(True)
        self.clear()
        self.addItem("– keine –", None)
        for m in self.state.measurements:
            slot = self.state.slot_of(m)
            self.addItem(f"[{slot + 1}] {m.name}" if slot is not None else m.name, m)
        idx = self.findData(cur) if cur is not None else -1
        self.setCurrentIndex(idx if idx >= 0 else 0)
        self.blockSignals(False)

    def select(self, m):
        i = self.findData(m)
        if i >= 0:
            self.setCurrentIndex(i)


class TSTab(QtWidgets.QWidget):
    datasheetRequested = QtCore.Signal()

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.result = None

        # ---- Eingaben ----------------------------------------------------
        left = QtWidgets.QWidget()
        ll = QtWidgets.QVBoxLayout(left)

        g_method = QtWidgets.QGroupBox("Vas-Bestimmung")
        fm = QtWidgets.QFormLayout(g_method)
        self._form = fm
        self.method = QtWidgets.QComboBox()
        for meth in (VasMethod.ADDED_MASS, VasMethod.TEST_BOX, VasMethod.SPECIFIED_MMD,
                     VasMethod.SPECIFIED_SPL, VasMethod.NONE):
            self.method.addItem(VAS_METHOD_LABELS[meth], meth.value)
        fm.addRow("Methode:", self.method)
        self.diameter = _spin(0.5, 200, 13.0, 2, "cm", 0.1)
        self.sd = _spin(0.1, 20000, 132.0, 1, "cm²")
        fm.addRow("Eff. Membrandurchmesser:", self.diameter)
        fm.addRow("Membranfläche Sd:", self.sd)
        self.added_mass = _spin(0.1, 2000, 20.0, 2, "g", 0.5)
        self.vb = _spin(0.1, 2000, 20.0, 2, "L", 0.5)
        self.mmd = _spin(0.01, 2000, 20.0, 2, "g", 0.5)
        self.spl = _spin(60, 120, 87.0, 1, "dB", 0.5)
        self.spl_ref = QtWidgets.QComboBox()
        self.spl_ref.addItem("1 W / 1 m", "1W")
        self.spl_ref.addItem("2,83 V / 1 m", "2.83V")
        self.rows = {
            "added_mass": ("Zusatzmasse:", self.added_mass),
            "vb": ("Testvolumen Vb:", self.vb),
            "mmd": ("Membranmasse Mmd:", self.mmd),
            "spl": ("Kennschalldruck:", self.spl),
            "spl_ref": ("Bezug:", self.spl_ref),
        }
        for label, w in self.rows.values():
            fm.addRow(label, w)
        ll.addWidget(g_method)

        g_meas = QtWidgets.QGroupBox("Messungen")
        gm = QtWidgets.QGridLayout(g_meas)
        self.cb_free = MeasurementCombo(state)
        self.cb_second = MeasurementCombo(state)
        self.btn_free = QtWidgets.QPushButton("Messen")
        self.btn_second = QtWidgets.QPushButton("Messen")
        self.lbl_second = QtWidgets.QLabel("Zweitmessung:")
        gm.addWidget(QtWidgets.QLabel("1. Freiluft:"), 0, 0)
        gm.addWidget(self.cb_free, 0, 1)
        gm.addWidget(self.btn_free, 0, 2)
        gm.addWidget(self.lbl_second, 1, 0)
        gm.addWidget(self.cb_second, 1, 1)
        gm.addWidget(self.btn_second, 1, 2)
        gm.setColumnStretch(1, 1)
        ll.addWidget(g_meas)

        g_opt = QtWidgets.QGroupBox("Optionen")
        fo = QtWidgets.QFormLayout(g_opt)
        self.re_override = QtWidgets.QCheckBox("Re vorgeben (z. B. mit Multimeter gemessen)")
        self.re_value = _spin(0.01, 1000, 5.6, 3, "Ω", 0.01)
        self.re_value.setEnabled(False)
        self.f_hi = QtWidgets.QComboBox()
        for v in (20000, 10000, 5000, 2000):
            self.f_hi.addItem(f"bis {v / 1000:g} kHz", v)
        self.xmax = _spin(0, 50, 0.0, 2, "mm", 0.5)
        self.xmax.setSpecialValueText("–")
        fo.addRow(self.re_override)
        fo.addRow("Re:", self.re_value)
        fo.addRow("Anpassungsbereich:", self.f_hi)
        fo.addRow("Xmax (für Vd):", self.xmax)
        ll.addWidget(g_opt)

        self.btn_calc = QtWidgets.QPushButton("Parameter berechnen")
        self.btn_calc.setMinimumHeight(38)
        f = self.btn_calc.font()
        f.setBold(True)
        self.btn_calc.setFont(f)
        ll.addWidget(self.btn_calc)

        g_exp = QtWidgets.QGroupBox("Export für Simulationsprogramme")
        fe = QtWidgets.QGridLayout(g_exp)
        self.profile = QtWidgets.QComboBox()
        self.profile.addItem("Parameterdatei (.tsp)", "tsp")
        self.profile.addItem("Parameterdatei (.ini)", "ini")
        for p in PROFILES.values():
            self.profile.addItem(f"Profil {p.name}", p.key)
        self.profile.addItem("Tabelle (.txt / .csv)", "table")
        self.btn_clip = QtWidgets.QPushButton("In Zwischenablage")
        self.btn_export = QtWidgets.QPushButton("Als Datei …")
        self.profile_hint = QtWidgets.QLabel()
        self.profile_hint.setWordWrap(True)
        self.profile_hint.setStyleSheet("color: palette(placeholder-text);")
        fe.addWidget(self.profile, 0, 0, 1, 2)
        fe.addWidget(self.btn_clip, 1, 0)
        fe.addWidget(self.btn_export, 1, 1)
        fe.addWidget(self.profile_hint, 2, 0, 1, 2)
        self.btn_sheet = QtWidgets.QPushButton("Datenblatt (PDF / Drucken) …")
        self.btn_sheet.clicked.connect(self.datasheetRequested.emit)
        fe.addWidget(self.btn_sheet, 3, 0, 1, 2)
        for b in (self.btn_clip, self.btn_export):
            b.setEnabled(False)
        ll.addWidget(g_exp)
        self.warn = QtWidgets.QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color: palette(link);")
        ll.addWidget(self.warn)
        ll.addStretch(1)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)
        keep_scroll_wide_enough(scroll, 360)

        # ---- Ergebnisse ---------------------------------------------------
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Parameter", "Wert", "Einheit"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.plot = ImpedancePlot()
        right = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        right.addWidget(self.plot)
        right.addWidget(self.table)
        right.setSizes([420, 380])

        split = QtWidgets.QSplitter()
        split.addWidget(scroll)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        lay = QtWidgets.QHBoxLayout(self)
        lay.addWidget(split)

        # ---- Signale ------------------------------------------------------
        self.method.currentIndexChanged.connect(self._update_fields)
        self.diameter.valueChanged.connect(lambda d: self._set_sd(sd_from_diameter(d / 100) * 1e4))
        self.sd.valueChanged.connect(self._sd_changed)
        self.re_override.toggled.connect(self.re_value.setEnabled)
        self.btn_free.clicked.connect(self._measure_free)
        self.btn_second.clicked.connect(self._measure_second)
        self.btn_calc.clicked.connect(self.calculate)
        self.btn_export.clicked.connect(self._export)
        self.btn_clip.clicked.connect(self._copy)
        self.profile.currentIndexChanged.connect(self._profile_hint)
        state.busyChanged.connect(lambda b: [w.setEnabled(not b) for w in (self.btn_free, self.btn_second)])
        state.projectLoaded.connect(self._restore)
        state.measurementsChanged.connect(self._refresh_plot)
        state.ts_text_provider = self.tsp_for
        self._set_sd(sd_from_diameter(0.13) * 1e4)
        self._update_fields()
        self._profile_hint()

    # ------------------------------------------------------------------
    def _set_sd(self, v):
        self.sd.blockSignals(True)
        self.sd.setValue(v)
        self.sd.blockSignals(False)

    def _sd_changed(self, v):
        self.diameter.blockSignals(True)
        self.diameter.setValue(2 * np.sqrt(v * 1e-4 / np.pi) * 100)
        self.diameter.blockSignals(False)

    def _method(self) -> VasMethod:
        return VasMethod(self.method.currentData())

    def _update_fields(self):
        m = self._method()
        vis = {"added_mass": m == VasMethod.ADDED_MASS, "vb": m == VasMethod.TEST_BOX,
               "mmd": m == VasMethod.SPECIFIED_MMD, "spl": m == VasMethod.SPECIFIED_SPL,
               "spl_ref": m == VasMethod.SPECIFIED_SPL}
        for key, (_label, w) in self.rows.items():
            self._form.setRowVisible(w, vis[key])
        second = m in NEEDS_SECOND_MEASUREMENT
        for w in (self.lbl_second, self.cb_second, self.btn_second):
            w.setVisible(second)
        self.lbl_second.setText("2. Mit Zusatzmasse:" if m == VasMethod.ADDED_MASS else "2. Im Testgehäuse:")

    # -- Messen ----------------------------------------------------------
    def _confirm(self, text) -> bool:
        if self.state.is_simulator:
            return True
        r = ask(self, "Messung vorbereiten", text)
        return r == QtWidgets.QMessageBox.Ok

    def _measure_free(self):
        if not self._confirm("Treiber an die Klemmen anschließen und frei in der Luft lagern "
                             "(nicht auf den Tisch legen, Membran frei beweglich)."):
            return
        self.state.measure(self.state.next_name("Freiluft"), connection="driver",
                           on_done=self.cb_free.select)

    def _measure_second(self):
        m = self._method()
        sim = self.state.backend if self.state.is_simulator else None
        if m == VasMethod.ADDED_MASS:
            if sim:
                sim.added_mass = self.added_mass.value() / 1000
            text = (f"Zusatzmasse von {self.added_mass.value():g} g gleichmäßig und fest auf der Membran "
                    "(nahe der Schwingspule) anbringen, z. B. mit Knetmasse oder Münzen.")
            conn, prefix = "driver_mass", "Zusatzmasse"
        else:
            if sim:
                sim.box_volume = self.vb.value() / 1000
            text = (f"Treiber luftdicht auf das Testgehäuse ({self.vb.value():g} L Nettovolumen) "
                    "setzen.")
            conn, prefix = "driver_box", "Testbox"
        if not self._confirm(text):
            return
        self.state.measure(self.state.next_name(prefix), connection=conn, on_done=self.cb_second.select)

    # -- Berechnen ---------------------------------------------------------
    def _inputs(self) -> dict:
        return {"method": self._method().value, "sd_cm2": self.sd.value(), "added_mass_g": self.added_mass.value(),
                "vb_l": self.vb.value(), "mmd_g": self.mmd.value(), "spl_db": self.spl.value(),
                "spl_ref": self.spl_ref.currentData(), "re_override": self.re_override.isChecked(),
                "re_ohm": self.re_value.value(), "f_hi": self.f_hi.currentData(), "xmax_mm": self.xmax.value()}

    def _apply_inputs(self, d: dict):
        i = self.method.findData(VasMethod(d.get("method", "added_mass")).value)
        self.method.setCurrentIndex(max(i, 0))
        self.sd.setValue(d.get("sd_cm2", self.sd.value()))
        self._sd_changed(self.sd.value())
        for w, k in ((self.added_mass, "added_mass_g"), (self.vb, "vb_l"), (self.mmd, "mmd_g"),
                     (self.spl, "spl_db"), (self.re_value, "re_ohm"), (self.xmax, "xmax_mm")):
            if k in d:
                w.setValue(float(d[k]))
        self.re_override.setChecked(bool(d.get("re_override", False)))
        for cb, k in ((self.spl_ref, "spl_ref"), (self.f_hi, "f_hi")):
            j = cb.findData(d.get(k))
            if j >= 0:
                cb.setCurrentIndex(j)

    def calculate(self, silent: bool = False):
        def info(msg):
            if not silent:
                QtWidgets.QMessageBox.information(self, "T/S-Parameter", msg)

        free = self.cb_free.currentData()
        if free is None:
            info("Bitte zuerst eine Freiluft-Messung auswählen oder durchführen.")
            return
        meth = self._method()
        second = self.cb_second.currentData() if meth in NEEDS_SECOND_MEASUREMENT else None
        if meth in NEEDS_SECOND_MEASUREMENT and second is None:
            info("Für diese Methode wird eine Zweitmessung benötigt.")
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            re_dc = self.re_value.value() if self.re_override.isChecked() else None
            f_hi = self.f_hi.currentData()
            fit1 = fit_driver(free.f, free.Z, re_dc=re_dc, fix_re=re_dc is not None, f_hi=f_hi)
            fit2 = fit_driver(second.f, second.Z, re_dc=fit1.Re, fix_re=True, f_hi=f_hi) if second else None
            ts = derive_ts(fit1, meth, sd=self.sd.value() * 1e-4, second=fit2,
                           added_mass=self.added_mass.value() / 1000, vb=self.vb.value() / 1000,
                           mmd=self.mmd.value() / 1000, spl=self.spl.value(),
                           spl_ref=self.spl_ref.currentData(), xmax=self._xmax())
        except Exception as e:      # noqa: BLE001
            QtWidgets.QApplication.restoreOverrideCursor()
            # altes Ergebnis nicht stehen lassen – es passt nicht mehr zu den Eingaben
            self.result = None
            self.table.setRowCount(0)
            for b in (self.btn_clip, self.btn_export, self.btn_sheet):
                b.setEnabled(False)
            self.warn.setStyleSheet(f"color: {appearance().current.err};")
            self.warn.setText(f"Keine Berechnung: {e}")
            if not silent:
                QtWidgets.QMessageBox.warning(self, "T/S-Parameter", str(e))
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        self.result = ts
        self._free = free
        self._second = second
        free.meta["Re"] = fit1.Re          # R_e verlustfrei an der Messung (ZMA-Kopf, Watch-Folder)
        self._show(ts, free, second)
        self.state.set_ts_state({
            "inputs": self._inputs(), "free_id": free.id, "second_id": second.id if second else None,
            "rows": [[k, label, val, unit] for k, label, val, unit, _f in ts.rows()],
            "warnings": ts.warnings,
        })
        self.state.status.emit(f"T/S-Parameter berechnet: fs = {fit1.fs:.2f} Hz, Qts = {fit1.Qts:.3f}"
                               + (f", Vas = {ts.Vas * 1e3:.2f} L" if ts.Vas else ""))

    def _xmax(self):
        return self.xmax.value() / 1000 if self.xmax.value() > 0 else None

    def _restore(self):
        """Nach dem Laden eines Projekts: Eingaben und Messungsauswahl wiederherstellen."""
        self.result = None
        self.table.setRowCount(0)
        self.plot.set_curves([])
        for b in (self.btn_clip, self.btn_export):
            b.setEnabled(False)
        st = self.state.ts_state
        if not st:
            return
        self._apply_inputs(st.get("inputs", {}))
        by_id = {m.id: m for m in self.state.measurements}
        if st.get("free_id") in by_id:
            self.cb_free.select(by_id[st["free_id"]])
        if st.get("second_id") in by_id:
            self.cb_second.select(by_id[st["second_id"]])
        dirty = self.state.dirty
        self.calculate(silent=True)
        self.state.dirty = dirty
        self.state.projectChanged.emit()

    def _refresh_plot(self):
        """Farben/Namen geändert → Diagramm neu zeichnen (nur wenn die Messungen noch existieren)."""
        free, second = getattr(self, "_free", None), getattr(self, "_second", None)
        if self.result is not None and free in self.state.measurements:
            self._plot(self.result, free, second if second in self.state.measurements else None)

    def _show(self, ts, free, second):
        rows = [r for r in ts.rows() if r[2] is not None]
        self.table.setRowCount(len(rows))
        bold = QtGui.QFont()
        bold.setBold(True)
        key_params = {"fs", "Qts", "Vas", "Re", "Qes", "Qms", "Bl", "Mms"}
        for i, (key, label, val, unit, fmt) in enumerate(rows):
            items = [QtWidgets.QTableWidgetItem(label), QtWidgets.QTableWidgetItem(fmt.format(val)),
                     QtWidgets.QTableWidgetItem(unit)]
            items[1].setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            for c, it in enumerate(items):
                if key in key_params:
                    it.setFont(bold)
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.warn.setStyleSheet(f"color: {appearance().current.warn};")
        self.warn.setText("\n\n".join(ts.warnings))
        for b in (self.btn_clip, self.btn_export, self.btn_sheet):
            b.setEnabled(True)
        self._plot(ts, free, second)

    def _plot(self, ts, free, second):
        curves = []
        lo, hi = ts.fit.f_range
        fm = np.geomspace(lo, hi, 800)
        f1, z1 = free.resampled(2000, 48)
        curves.append(Curve(free.name, f1, z1, free.color or "#1f77b4"))
        curves.append(Curve("Modell", fm, ts.fit.model(fm), "model", 1.2, dashed=True))
        if second is not None and ts.second_fit is not None:
            f2, z2 = second.resampled(2000, 48)
            curves.append(Curve(second.name, f2, z2, second.color or "#d62728"))
            curves.append(Curve("Modell 2", fm, ts.second_fit.model(fm), "model2", 1.2, dashed=True))
        self.plot.set_curves(curves, autorange=True)

    # -- Export (FS-02) ------------------------------------------------------
    def tsp_for(self, m) -> str | None:
        """Für den Watch-Folder: .tsp-Text, falls die T/S-Parameter zu dieser Messung gehören."""
        if self.result is None or getattr(self, "_free", None) is not m:
            return None
        return tsp_text(self.result, self.state.info, self._xmax(), m.name, __version__)

    def _profile_hint(self):
        key = self.profile.currentData()
        p = PROFILES.get(key)
        if p:
            txt = (f"Werte in Reihenfolge und Einheiten der Eingabemaske von {p.name} "
                   "(Feld ⇥ Wert ⇥ Einheit). " + p.hint)
        elif key in ("tsp", "ini"):
            txt = "Strukturierte INI-Datei: [Driver], [Measurement], [Parameters], [Units] inkl. Wright-Parametern."
        else:
            txt = "Vollständige Ergebnistabelle wie angezeigt."
        self.profile_hint.setText(txt)

    def _text(self, key: str) -> str:
        free = getattr(self, "_free", None)
        name = free.name if free else ""
        if key in ("tsp", "ini"):
            return tsp_text(self.result, self.state.info, self._xmax(), name, __version__)
        if key in PROFILES:
            return profile_text(key, self.result, self.state.info, self._xmax())
        return "\n".join(f"{label}\t{'' if val is None else fmt.format(val)}\t{unit}"
                         for _k, label, val, unit, fmt in self.result.rows()) + "\n"

    def _copy(self):
        if self.result is None:
            return
        key = self.profile.currentData()
        text = self._text(key)
        if key in PROFILES:      # Zwischenablage ohne Kommentarzeilen
            text = "\n".join(line for line in text.splitlines() if not line.startswith("#")) + "\n"
        QtWidgets.QApplication.clipboard().setText(text)
        self.state.status.emit(f"T/S-Parameter ({self.profile.currentText()}) in die Zwischenablage kopiert.")

    def _export(self):
        if self.result is None:
            return
        key = self.profile.currentData()
        base = self.state.info.title.replace(" ", "_") if self.state.info.title != "Treiber" else "ts-parameter"
        if key in ("tsp", "ini"):
            default, filt = f"{base}.{key}", f"Parameterdatei (*.{key})"
        elif key in PROFILES:
            default, filt = f"{base}_{key}.txt", "Text (*.txt)"
        else:
            default, filt = f"{base}.txt", "Text (*.txt);;CSV (*.csv)"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "T/S-Parameter exportieren", default, filt)
        if not path:
            return
        if key == "table":
            free = getattr(self, "_free", None)
            header = [f"T/S-Parameter – {self.state.info.title} – {free.name if free else ''}",
                      f"Methode: {VAS_METHOD_LABELS[self.result.method]}"]
            export_parameters(path, self.result.rows(), header)
        else:
            save_text(path, self._text(key))
        self.state.status.emit(f"Parameter exportiert: {path}")
