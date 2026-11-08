"""Dialoge: Projektinfo/Notizen, Watch-Folder, Exportoptionen."""
from __future__ import annotations

from PySide6 import QtWidgets

from ..io.formats import COLUMN_SETS, DELIMITERS, FREQ_UNITS, IMP_UNITS, TextExportOptions
from ..io.ts_export import DriverInfo
from ..io.watch import WatchFolderConfig
from .de import button_box
from .plots import SMOOTHING

EXPORT_POINTS = {"Alle Messpunkte (verlustfrei)": 0, "Logarithmisch, 2000 Punkte": 2000,
                 "Logarithmisch, 1000 Punkte": 1000, "Logarithmisch, 500 Punkte": 500}
EXPORT_SMOOTHING = {"Keine": None, **{k: v for k, v in SMOOTHING.items() if isinstance(v, int)}}


def _buttons(dlg):
    return button_box(dlg, "Ok", "Cancel")


class ProjectInfoDialog(QtWidgets.QDialog):
    def __init__(self, info: DriverInfo, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Projektinfo & Notizen")
        self.resize(480, 380)
        form = QtWidgets.QFormLayout(self)
        self.manufacturer = QtWidgets.QLineEdit(info.manufacturer)
        self.model = QtWidgets.QLineEdit(info.model)
        self.serial = QtWidgets.QLineEdit(info.serial)
        self.notes = QtWidgets.QPlainTextEdit(info.notes)
        self.notes.setPlaceholderText("z. B. Einspielzeit, Raumtemperatur, Auffälligkeiten, Einbausituation …")
        form.addRow("Hersteller:", self.manufacturer)
        form.addRow("Modell:", self.model)
        form.addRow("Serien-/Chargennr.:", self.serial)
        form.addRow("Notizen:", self.notes)
        form.addRow(_buttons(self))

    def info(self) -> DriverInfo:
        return DriverInfo(self.manufacturer.text().strip(), self.model.text().strip(),
                          self.serial.text().strip(), self.notes.toPlainText())


class WatchFolderDialog(QtWidgets.QDialog):
    def __init__(self, cfg: WatchFolderConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Watch-Folder (Übergabe an Simulationsprogramme)")
        self.resize(560, 260)
        form = QtWidgets.QFormLayout(self)
        info = QtWidgets.QLabel("Messungen werden als .zma (R<sub>e</sub> im Dateikopf) und optional mit "
                                ".tsp-Parameterdatei in diesen Ordner geschrieben. Programme wie VituixCAD "
                                "laden geänderte .zma-Dateien automatisch neu.")
        info.setWordWrap(True)
        form.addRow(info)
        row = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit(cfg.path)
        btn = QtWidgets.QPushButton("Wählen …")
        btn.clicked.connect(self._choose)
        row.addWidget(self.path, 1)
        row.addWidget(btn)
        form.addRow("Ordner:", row)
        self.auto = QtWidgets.QCheckBox("Jede neue Messung automatisch übergeben")
        self.auto.setChecked(cfg.auto)
        self.with_tsp = QtWidgets.QCheckBox(".tsp-Datei mit T/S-Parametern mitliefern (falls berechnet)")
        self.with_tsp.setChecked(cfg.with_tsp)
        self.points = QtWidgets.QComboBox()
        self.points.addItems(list(EXPORT_POINTS))
        if not cfg.lossless:
            i = self.points.findText(next((k for k, v in EXPORT_POINTS.items() if v == cfg.points),
                                          "Logarithmisch, 2000 Punkte"))
            self.points.setCurrentIndex(max(i, 0))
        form.addRow(self.auto)
        form.addRow(self.with_tsp)
        form.addRow("Frequenzraster:", self.points)
        form.addRow(_buttons(self))

    def _choose(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Watch-Folder wählen", self.path.text())
        if d:
            self.path.setText(d)

    def config(self) -> WatchFolderConfig:
        n = EXPORT_POINTS[self.points.currentText()]
        return WatchFolderConfig(path=self.path.text().strip(), auto=self.auto.isChecked(),
                                 with_tsp=self.with_tsp.isChecked(), lossless=n == 0, points=n or 2000)


class ExportDialog(QtWidgets.QDialog):
    """Exportoptionen (FS-01). Spalten-/Einheiten-Optionen nur für .txt/.csv."""

    def __init__(self, ext: str, opt: TextExportOptions, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exportoptionen")
        self.ext = ext
        form = QtWidgets.QFormLayout(self)
        self.points = QtWidgets.QComboBox()
        self.points.addItems(list(EXPORT_POINTS))
        self.points.setCurrentIndex(2)
        self.smoothing = QtWidgets.QComboBox()
        self.smoothing.addItems(list(EXPORT_SMOOTHING))
        self.smoothing.setCurrentIndex(1)
        form.addRow("Frequenzraster:", self.points)
        form.addRow("Glättung:", self.smoothing)
        self.points.currentIndexChanged.connect(
            lambda: self.smoothing.setEnabled(EXPORT_POINTS[self.points.currentText()] != 0))

        self.delim = QtWidgets.QComboBox()
        for k, (label, _c) in DELIMITERS.items():
            self.delim.addItem(label, k)
        self.decimal = QtWidgets.QComboBox()
        self.decimal.addItem("Punkt (1.23)", ".")
        self.decimal.addItem("Komma (1,23)", ",")
        self.funit = QtWidgets.QComboBox()
        self.funit.addItems(list(FREQ_UNITS))
        self.zunit = QtWidgets.QComboBox()
        for u in IMP_UNITS:
            self.zunit.addItem(u.replace("Ohm", "Ω"), u)
        self.punit = QtWidgets.QComboBox()
        self.punit.addItem("Grad", "deg")
        self.punit.addItem("Radiant", "rad")
        self.cols = QtWidgets.QComboBox()
        for k, v in COLUMN_SETS.items():
            self.cols.addItem(v, k)
        self.header = QtWidgets.QCheckBox("Kopfzeilen mit Einheiten schreiben")
        self.lossless = QtWidgets.QCheckBox("Volle Genauigkeit (17 Stellen)")
        for cb, val in ((self.delim, opt.delimiter), (self.decimal, opt.decimal), (self.punit, opt.phase_unit),
                        (self.zunit, opt.imp_unit), (self.cols, opt.columns)):
            cb.setCurrentIndex(max(cb.findData(val), 0))
        self.funit.setCurrentText(opt.freq_unit)
        self.header.setChecked(opt.header)
        self.lossless.setChecked(opt.lossless)

        table = ext in (".txt", ".csv")
        for label, w in (("Trennzeichen:", self.delim), ("Dezimalzeichen:", self.decimal),
                         ("Frequenzeinheit:", self.funit), ("Impedanzeinheit:", self.zunit),
                         ("Phaseneinheit:", self.punit), ("Spalten:", self.cols)):
            if table:
                form.addRow(label, w)
        if table:
            form.addRow(self.header)
        form.addRow(self.lossless)
        if not table:
            form.addRow(QtWidgets.QLabel(f"{ext}: feste Spalten Frequenz [Hz], |Z| [Ω], Phase [°]."))
        self.err = QtWidgets.QLabel()
        self.err.setStyleSheet("color: #e04848;")
        form.addRow(self.err)
        form.addRow(_buttons(self))

    def accept(self):
        try:
            self.options().validate()
        except ValueError as e:
            self.err.setText(str(e))
            return
        super().accept()

    def options(self) -> TextExportOptions:
        return TextExportOptions(delimiter=self.delim.currentData(), decimal=self.decimal.currentData(),
                                 freq_unit=self.funit.currentText(), imp_unit=self.zunit.currentData(),
                                 phase_unit=self.punit.currentData(), columns=self.cols.currentData(),
                                 header=self.header.isChecked(), lossless=self.lossless.isChecked())

    def resampling(self) -> tuple[int, float | None]:
        return EXPORT_POINTS[self.points.currentText()], EXPORT_SMOOTHING[self.smoothing.currentText()]
