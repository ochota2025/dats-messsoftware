"""Datenblatt: eine A4-Seite mit Impedanzkurve und Parametern – als PDF oder Ausdruck.

Die Seite wird mit QPainter gezeichnet (vektoriell im PDF). Dieselbe Zeichenroutine
liefert die Vorschau im Dialog, den PDF-Export und den Ausdruck.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtPrintSupport, QtWidgets

from .. import __version__
from ..analysis.ts import VAS_METHOD_LABELS, TSParameters, VasMethod, derive_ts, quick_parameters
from ..measurement import Measurement
from .plots import LogAxis

A4 = (210.0, 297.0)          # mm
MARGIN = 15.0

# Schlüssel aus TSParameters.rows() → (Symbol, Bezeichnung)
SYMBOLS = {
    "fs": ("fs", "Resonanzfrequenz"), "Re": ("Re", "Gleichstromwiderstand"),
    "Zmax": ("Zmax", "Impedanz bei fs"), "Qes": ("Qes", "Elektrische Güte"),
    "Qms": ("Qms", "Mechanische Güte"), "Qts": ("Qts", "Gesamtgüte"),
    "Le1k": ("Le", "Induktivität bei 1 kHz"), "Le10k": ("Le", "Induktivität bei 10 kHz"),
    "Res": ("Res", "Mech. Verluste (elektrisch)"), "EBP": ("EBP", "fs / Qes"),
    "Sd": ("Sd", "Membranfläche"), "Mms": ("Mms", "Bewegte Masse inkl. Luft"),
    "Mmd": ("Mmd", "Membranmasse"), "Cms": ("Cms", "Nachgiebigkeit"),
    "Rms": ("Rms", "Mech. Verlustwiderstand"), "Bl": ("Bl", "Kraftfaktor"),
    "Vd": ("Vd", "Verdrängungsvolumen"), "Vas": ("Vas", "Äquivalentvolumen"),
    "eta0": ("η0", "Wirkungsgrad"), "SPL1W": ("SPL", "Kennschalldruck 1 W / 1 m"),
    "SPL283": ("SPL", "Kennschalldruck 2,83 V / 1 m"),
    "Kr": ("Kr", "Verlustanteil"), "Xr": ("Xr", "Exponent Verlust"),
    "Ki": ("Ki", "Induktiver Anteil"), "Xi": ("Xi", "Exponent induktiv"),
}
GROUPS_LEFT = [("Elektrisch", ["Re", "fs", "Zmax", "Qes", "Qms", "Qts", "Le1k", "Le10k", "EBP"]),
               ("Wright-Modell der Schwingspule", ["Kr", "Xr", "Ki", "Xi"])]
GROUPS_RIGHT = [("Mechanisch", ["Sd", "Mms", "Mmd", "Cms", "Rms", "Bl", "Vd"]),
                ("Akustisch", ["Vas", "eta0", "SPL1W", "SPL283"])]


@dataclass
class SheetCurve:
    name: str
    f: np.ndarray
    Z: np.ndarray
    color: str
    dashed: bool = False


@dataclass
class SheetData:
    title: str
    subtitle: str
    curves: list[SheetCurve]
    left: list[tuple[str, list[tuple[str, str, str, str]]]] = field(default_factory=list)
    right: list[tuple[str, list[tuple[str, str, str, str]]]] = field(default_factory=list)
    conditions: list[tuple[str, str]] = field(default_factory=list)
    notes: str = ""
    message: str = ""          # z. B. „keine Treiberresonanz erkannt“
    comment: str = ""          # Kommentar aus dem Datenblatt-Dialog (je Messung gespeichert)


# --------------------------------------------------------------------------
# Daten zusammenstellen
# --------------------------------------------------------------------------

def _groups(ts: TSParameters, spec) -> list:
    vals = {k: (v, unit, fmt) for k, _label, v, unit, fmt in ts.rows() if v is not None}
    out = []
    for title, keys in spec:
        rows = []
        for k in keys:
            if k in vals:
                v, unit, fmt = vals[k]
                sym, desc = SYMBOLS[k]
                rows.append((sym, desc, fmt.format(v), unit))
        if rows:
            out.append((title, rows))
    return out


def build_sheet(m: Measurement, *, title: str, info, ts: TSParameters | None = None,
                second: Measurement | None = None, ts_inputs: dict | None = None,
                show_model: bool = True, show_second: bool = True, comment: str = "") -> SheetData:
    """``ts`` = vollständiges Ergebnis aus dem T/S-Tab (zu ``m``); sonst nur Kennwerte aus ``m``."""
    curves = []
    f, Z = m.resampled(1500, 48)
    curves.append(SheetCurve(m.name, f, Z, "#1f5fa8"))
    message = ""
    if ts is None:
        fit = quick_parameters(m.f, m.Z)
        if fit is not None:
            ts = derive_ts(fit, VasMethod.NONE, sd=None)
        else:
            message = "Keine Lautsprecherresonanz erkannt – es werden nur die Messkurven gezeigt."
    if ts is not None and show_model:
        lo, hi = ts.fit.f_range
        fm = np.geomspace(lo, hi, 600)
        curves.append(SheetCurve("Modell", fm, ts.fit.model(fm), "#222222", dashed=True))
    if second is not None and show_second:
        f2, Z2 = second.resampled(1500, 48)
        curves.append(SheetCurve(second.name, f2, Z2, "#c0392b"))

    parts = [p for p in (f"S/N {info.serial}" if info.serial else "", f"Messung „{m.name}“",
                         m.created.replace("T", " ")[:16]) if p]
    data = SheetData(title=title or "Treiber-Datenblatt", subtitle="  ·  ".join(parts), curves=curves,
                     notes=info.notes.strip(), message=message, comment=comment.strip())
    if ts is not None:
        data.left = _groups(ts, GROUPS_LEFT)
        data.right = _groups(ts, GROUPS_RIGHT)

    cond = []
    if ts is not None:
        meth = ts.method
        txt = VAS_METHOD_LABELS[meth] if meth != VasMethod.NONE else "keine (nur Einzelmessung)"
        inp = ts_inputs or {}
        if meth == VasMethod.ADDED_MASS and "added_mass_g" in inp:
            txt += f", {inp['added_mass_g']:g} g"
        elif meth == VasMethod.TEST_BOX and "vb_l" in inp:
            txt += f", {inp['vb_l']:g} L"
        elif meth == VasMethod.SPECIFIED_MMD and "mmd_g" in inp:
            txt += f", Mmd {inp['mmd_g']:g} g"
        elif meth == VasMethod.SPECIFIED_SPL and "spl_db" in inp:
            txt += f", {inp['spl_db']:g} dB"
        cond.append(("Vas-Methode", txt))
        if ts.second_fit is not None:
            cond.append(("Zweitmessung", f"fs = {ts.second_fit.fs:.2f} Hz, Qes = {ts.second_fit.Qes:.3f}"))
        cond.append(("Modellabweichung", f"{ts.fit.rms_error * 100:.2f} % "
                                         f"({ts.fit.f_range[0]:.0f} Hz – {ts.fit.f_range[1] / 1000:.0f} kHz)"))
    cond.append(("Kalibrierung", "ja" if m.meta.get("calibrated") else "nein / importiert"))
    sw = m.meta.get("sweep")
    if sw:
        cond.append(("Sweep", f"{sw.get('fs', 0) / 1000:g} kHz, {2 ** sw.get('sweep_exp', 17) / sw.get('fs', 48000):.1f} s, "
                              f"{sw.get('level_dbfs', 0):g} dBFS, {sw.get('averages', 1)}× gemittelt"))
    if m.meta.get("device"):
        cond.append(("Messgerät", str(m.meta["device"])))
    data.conditions = cond
    return data


# --------------------------------------------------------------------------
# Zeichnen
# --------------------------------------------------------------------------

def _font(dpi: float, pt: float, bold: bool = False) -> QtGui.QFont:
    f = QtGui.QFont()
    f.setPixelSize(max(1, round(pt * dpi / 72.0)))
    f.setBold(bold)
    return f


def _render_plot(painter: QtGui.QPainter, target: QtCore.QRectF, curves: list[SheetCurve], dpi: float) -> None:
    W, H = 820.0, 470.0
    glw = pg.GraphicsLayoutWidget()
    glw.setBackground("w")
    top = glw.addPlot(row=0, col=0, axisItems={"bottom": LogAxis("bottom"), "left": LogAxis("left")})
    bot = glw.addPlot(row=1, col=0, axisItems={"bottom": LogAxis("bottom")})
    glw.ci.layout.setRowStretchFactor(0, 3)
    glw.ci.layout.setRowStretchFactor(1, 2)
    for p in (top, bot):
        p.setLogMode(x=True, y=False)
        p.showGrid(x=True, y=True, alpha=0.35)
        for ax in ("left", "bottom"):
            p.getAxis(ax).setPen(pg.mkPen("#333"))
            p.getAxis(ax).setTextPen(pg.mkPen("#222"))
            p.getAxis(ax).enableAutoSIPrefix(False)
    bot.setXLink(top)
    top.setLabel("left", "|Z| [Ω]")
    bot.setLabel("left", "Phase [°]")
    bot.setLabel("bottom", "Frequenz [Hz]")
    f_lo = min(float(c.f[c.f > 0][0]) for c in curves) if curves else 1.0
    for c in curves:
        m = c.f > 0
        pen = pg.mkPen(c.color, width=1.1 if c.dashed else 2.6,
                       style=QtCore.Qt.DashLine if c.dashed else QtCore.Qt.SolidLine)
        top.plot(c.f[m], np.abs(c.Z[m]), pen=pen)
        bot.plot(c.f[m], np.degrees(np.angle(c.Z[m])), pen=pen)
    top.setXRange(np.log10(max(f_lo, 5.0)), np.log10(20000.0), padding=0.01)
    glw.resize(int(W), int(H))
    glw.ci.setGeometry(QtCore.QRectF(0, 0, W, H))
    glw.ci.layout.activate()
    # Über ein Zwischenbild mit Bildschirm-DPI rendern: Direkt in ein 300-dpi-PDF gezeichnet,
    # würden die Schriften der Szene ein zweites Mal hochskaliert.
    scale = 3
    img = QtGui.QImage(int(W * scale), int(H * scale), QtGui.QImage.Format_ARGB32)
    img.setDotsPerMeterX(int(96 / 0.0254))
    img.setDotsPerMeterY(int(96 / 0.0254))
    img.fill(QtGui.QColor("white"))
    ip = QtGui.QPainter(img)
    ip.setRenderHint(QtGui.QPainter.Antialiasing)
    ip.setRenderHint(QtGui.QPainter.TextAntialiasing)
    glw.scene().render(ip, QtCore.QRectF(0, 0, W * scale, H * scale), QtCore.QRectF(0, 0, W, H))
    ip.end()
    painter.save()
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    painter.drawImage(target, img)
    # Legende selbst zeichnen (pyqtgraph skaliert ihre Schrift beim Rendern nicht mit)
    mm = dpi / 25.4
    painter.setFont(_font(dpi, 8))
    fm = painter.fontMetrics()
    line_h = fm.height() + 0.8 * mm
    box_w = max(fm.horizontalAdvance(c.name) for c in curves) + 12 * mm if curves else 0
    box = QtCore.QRectF(target.right() - box_w - 4 * mm, target.top() + 3 * mm, box_w,
                        line_h * len(curves) + 2 * mm)
    painter.setPen(QtGui.QPen(QtGui.QColor("#cccccc"), 0.2 * mm))
    painter.setBrush(QtGui.QColor(255, 255, 255, 230))
    painter.drawRect(box)
    for i, c in enumerate(curves):
        yy = box.top() + 1 * mm + i * line_h + line_h / 2
        pen = QtGui.QPen(QtGui.QColor(c.color), (0.3 if c.dashed else 0.6) * mm)
        if c.dashed:
            pen.setStyle(QtCore.Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(QtCore.QPointF(box.left() + 2 * mm, yy), QtCore.QPointF(box.left() + 8 * mm, yy))
        painter.setPen(QtGui.QColor("#222222"))
        painter.drawText(QtCore.QRectF(box.left() + 10 * mm, yy - line_h / 2, box_w - 10 * mm, line_h),
                         QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, c.name)
    painter.restore()
    glw.deleteLater()


def paint_sheet(painter: QtGui.QPainter, page: QtCore.QRectF, data: SheetData, dpi: float) -> None:
    mm = dpi / 25.4
    x0, y0 = page.left() + MARGIN * mm, page.top() + MARGIN * mm
    w = page.width() - 2 * MARGIN * mm
    bottom = page.bottom() - MARGIN * mm
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
    accent = QtGui.QColor("#1f5fa8")
    grey = QtGui.QColor("#666666")
    ink = QtGui.QColor("#1a1a1a")

    # Kopf
    painter.setPen(ink)
    painter.setFont(_font(dpi, 18, True))
    fm = painter.fontMetrics()
    painter.drawText(QtCore.QPointF(x0, y0 + fm.ascent()), data.title)
    y = y0 + fm.height()
    painter.setFont(_font(dpi, 9))
    painter.setPen(grey)
    fm = painter.fontMetrics()
    painter.drawText(QtCore.QPointF(x0, y + fm.ascent()), data.subtitle)
    painter.drawText(QtCore.QRectF(x0, y, w, fm.height()), QtCore.Qt.AlignRight, "Datenblatt")
    y += fm.height() + 1.5 * mm
    painter.setPen(QtGui.QPen(accent, 0.6 * mm))
    painter.drawLine(QtCore.QPointF(x0, y), QtCore.QPointF(x0 + w, y))
    y += 3 * mm

    # Diagramm
    plot_h = 92 * mm
    _render_plot(painter, QtCore.QRectF(x0, y, w, plot_h), data.curves, dpi)
    y += plot_h + 3 * mm

    if data.message:
        painter.setFont(_font(dpi, 9))
        painter.setPen(QtGui.QColor("#b35a00"))
        painter.drawText(QtCore.QRectF(x0, y, w, 6 * mm), QtCore.Qt.AlignLeft, data.message)
        y += 7 * mm

    # Parametertabellen (zwei Spalten)
    gap = 6 * mm
    col_w = (w - gap) / 2
    row_h = 5.0 * mm

    def table(x: float, ytop: float, groups) -> float:
        yy = ytop
        for title, rows in groups:
            painter.setFont(_font(dpi, 9.5, True))
            painter.setPen(accent)
            fmh = painter.fontMetrics()
            painter.drawText(QtCore.QPointF(x, yy + fmh.ascent()), title)
            yy += fmh.height() + 0.6 * mm
            painter.setPen(QtGui.QPen(accent, 0.25 * mm))
            painter.drawLine(QtCore.QPointF(x, yy), QtCore.QPointF(x + col_w, yy))
            yy += 0.6 * mm
            for i, (sym, desc, val, unit) in enumerate(rows):
                r = QtCore.QRectF(x, yy, col_w, row_h)
                if i % 2 == 0:
                    painter.fillRect(r, QtGui.QColor("#f2f5f9"))
                painter.setPen(ink)
                painter.setFont(_font(dpi, 8.5, True))
                painter.drawText(r.adjusted(1.2 * mm, 0, 0, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, sym)
                painter.setFont(_font(dpi, 8))
                painter.setPen(grey)
                painter.drawText(r.adjusted(13 * mm, 0, 0, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, desc)
                painter.setPen(ink)
                painter.setFont(_font(dpi, 8.5, True))
                painter.drawText(r.adjusted(0, 0, -15 * mm, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, val)
                painter.setFont(_font(dpi, 8))
                painter.drawText(r.adjusted(col_w - 14 * mm, 0, 0, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                                 unit)
                yy += row_h
            yy += 3 * mm
        return yy

    y = max(table(x0, y, data.left), table(x0 + col_w + gap, y, data.right)) if (data.left or data.right) else y

    # Messbedingungen
    if data.conditions:
        painter.setFont(_font(dpi, 9.5, True))
        painter.setPen(accent)
        fmh = painter.fontMetrics()
        painter.drawText(QtCore.QPointF(x0, y + fmh.ascent()), "Messbedingungen")
        y += fmh.height() + 0.8 * mm
        painter.setFont(_font(dpi, 8))
        fmc = painter.fontMetrics()
        lh = fmc.height() + 0.6 * mm
        for k, v in data.conditions:
            painter.setPen(grey)
            painter.drawText(QtCore.QPointF(x0, y + fmc.ascent()), k)
            painter.setPen(ink)
            painter.drawText(QtCore.QRectF(x0 + 32 * mm, y, w - 32 * mm, lh), QtCore.Qt.AlignLeft,
                             fmc.elidedText(v, QtCore.Qt.ElideRight, int(w - 32 * mm)))
            y += lh
        y += 2.5 * mm

    footer_h = 7 * mm

    # Kommentar (aus dem Datenblatt-Dialog)
    if data.comment and y < bottom - footer_h - 10 * mm:
        painter.setFont(_font(dpi, 9.5, True))
        painter.setPen(accent)
        fmh = painter.fontMetrics()
        painter.drawText(QtCore.QPointF(x0, y + fmh.ascent()), "Kommentar")
        y += fmh.height() + 0.8 * mm
        painter.setFont(_font(dpi, 9))
        flags = QtCore.Qt.TextWordWrap | QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft
        avail = bottom - footer_h - y - 2 * mm
        need = painter.boundingRect(QtCore.QRectF(0, 0, w - 5 * mm, avail), flags, data.comment).height()
        box = QtCore.QRectF(x0, y, w, min(avail, need + 3.5 * mm))
        painter.fillRect(box, QtGui.QColor("#fff8e6"))
        painter.fillRect(QtCore.QRectF(x0, y, 0.8 * mm, box.height()), QtGui.QColor("#e0a020"))
        painter.setPen(ink)
        painter.drawText(box.adjusted(3 * mm, 1.5 * mm, -2 * mm, -1.5 * mm), flags, data.comment)
        y += box.height() + 3 * mm

    # Notizen
    if data.notes and y < bottom - footer_h - 10 * mm:
        painter.setFont(_font(dpi, 9.5, True))
        painter.setPen(accent)
        fmh = painter.fontMetrics()
        painter.drawText(QtCore.QPointF(x0, y + fmh.ascent()), "Notizen")
        y += fmh.height() + 0.8 * mm
        box = QtCore.QRectF(x0, y, w, bottom - footer_h - y - 2 * mm)
        painter.setPen(QtGui.QPen(QtGui.QColor("#cccccc"), 0.2 * mm))
        painter.drawRect(box)
        painter.setPen(ink)
        painter.setFont(_font(dpi, 8.5))
        painter.drawText(box.adjusted(2 * mm, 1.5 * mm, -2 * mm, -1.5 * mm),
                         QtCore.Qt.TextWordWrap | QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft, data.notes)

    # Fußzeile
    painter.setFont(_font(dpi, 7.5))
    painter.setPen(grey)
    fmf = painter.fontMetrics()
    painter.setPen(QtGui.QPen(QtGui.QColor("#cccccc"), 0.2 * mm))
    painter.drawLine(QtCore.QPointF(x0, bottom - fmf.height() - 1 * mm), QtCore.QPointF(x0 + w, bottom - fmf.height() - 1 * mm))
    painter.setPen(grey)
    stamp = _dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    painter.drawText(QtCore.QRectF(x0, bottom - fmf.height(), w, fmf.height()), QtCore.Qt.AlignLeft,
                     f"Erstellt mit DATS-Messsoftware {__version__} · {stamp}")
    painter.drawText(QtCore.QRectF(x0, bottom - fmf.height(), w, fmf.height()), QtCore.Qt.AlignRight,
                     "Messwerte des Einzelexemplars – ohne Gewähr")


def render_image(data: SheetData, dpi: float = 110) -> QtGui.QImage:
    w, h = int(A4[0] / 25.4 * dpi), int(A4[1] / 25.4 * dpi)
    img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
    img.setDotsPerMeterX(int(dpi / 0.0254))
    img.setDotsPerMeterY(int(dpi / 0.0254))
    img.fill(QtGui.QColor("white"))
    p = QtGui.QPainter(img)
    paint_sheet(p, QtCore.QRectF(0, 0, w, h), data, dpi)
    p.end()
    return img


def save_pdf(path: str, data: SheetData) -> None:
    writer = QtGui.QPdfWriter(path)
    writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.A4))
    writer.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0))
    writer.setResolution(300)
    writer.setTitle(data.title)
    writer.setCreator(f"DATS-Messsoftware {__version__}")
    p = QtGui.QPainter(writer)
    paint_sheet(p, QtCore.QRectF(0, 0, writer.width(), writer.height()), data, 300)
    p.end()


def print_sheet(parent, data: SheetData) -> bool:
    printer = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.HighResolution)
    printer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.A4))
    printer.setFullPage(True)
    printer.setDocName(data.title)
    dlg = QtPrintSupport.QPrintDialog(printer, parent)
    dlg.setWindowTitle("Datenblatt drucken")
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return False
    p = QtGui.QPainter(printer)
    rect = printer.paperRect(QtPrintSupport.QPrinter.DevicePixel)
    paint_sheet(p, QtCore.QRectF(0, 0, rect.width(), rect.height()), data, printer.resolution())
    p.end()
    return True


# --------------------------------------------------------------------------
# Dialog
# --------------------------------------------------------------------------

class DatasheetDialog(QtWidgets.QDialog):
    def __init__(self, state, ts_tab, parent=None):
        super().__init__(parent)
        from .ts_tab import MeasurementCombo      # Import hier, um Zyklen zu vermeiden
        self.state = state
        self.ts_tab = ts_tab
        self.setWindowTitle("Datenblatt")
        self.resize(900, 820)

        form = QtWidgets.QFormLayout()
        self.meas = MeasurementCombo(state)
        free = getattr(ts_tab, "_free", None) if ts_tab.result is not None else None
        self.meas.select(free or state.current_measurement())
        self.title = QtWidgets.QLineEdit()
        self.title.setPlaceholderText("z. B. Hersteller und Modell")
        info_title = state.info.title if state.info.title != "Treiber" else ""
        self.title.setText(info_title)
        self.show_model = QtWidgets.QCheckBox("Modellkurve einzeichnen")
        self.show_model.setChecked(True)
        self.show_second = QtWidgets.QCheckBox("Zweitmessung (Zusatzmasse/Testbox) einzeichnen")
        self.show_second.setChecked(True)
        self.scope = QtWidgets.QLabel()
        self.scope.setWordWrap(True)
        self.scope.setStyleSheet("color: palette(placeholder-text);")
        self.comment = QtWidgets.QPlainTextEdit()
        self.comment.setPlaceholderText("z. B. Prüfergebnis, Einbausituation, Auffälligkeiten – erscheint "
                                        "auf dem Datenblatt und wird mit der Messung gespeichert")
        self.comment.setFixedHeight(self.comment.fontMetrics().lineSpacing() * 4 + 14)
        self.comment.setTabChangesFocus(True)
        form.addRow("Messung:", self.meas)
        form.addRow("Titel:", self.title)
        form.addRow("Kommentar:", self.comment)
        form.addRow(self.show_model)
        form.addRow(self.show_second)
        form.addRow(self.scope)

        self.preview = QtWidgets.QLabel()
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setStyleSheet("background: #808080;")
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(self.preview)
        scroll.setWidgetResizable(True)

        btn_pdf = QtWidgets.QPushButton("Als PDF speichern …")
        btn_print = QtWidgets.QPushButton("Drucken …")
        btn_close = QtWidgets.QPushButton("Schließen")
        btn_pdf.setDefault(True)
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        for b in (btn_pdf, btn_print, btn_close):
            btns.addWidget(b)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(scroll, 1)
        lay.addLayout(btns)

        self._comment_for = None
        self._load_comment()
        self.meas.currentIndexChanged.connect(self._load_comment)
        self.meas.currentIndexChanged.connect(self.update_preview)
        self.title.textChanged.connect(self._debounce)
        self.comment.textChanged.connect(self._comment_changed)
        self.show_model.toggled.connect(self.update_preview)
        self.show_second.toggled.connect(self.update_preview)
        btn_pdf.clicked.connect(self._pdf)
        btn_print.clicked.connect(self._print)
        btn_close.clicked.connect(self.reject)
        self._timer = QtCore.QTimer(self, singleShot=True, interval=300)
        self._timer.timeout.connect(self.update_preview)
        self.update_preview()

    def _debounce(self):
        self._timer.start()

    def _load_comment(self, *_):
        m = self.meas.currentData()
        self._comment_for = None
        self.comment.setPlainText(m.meta.get("sheet_comment", "") if m is not None else "")
        self.comment.setEnabled(m is not None)
        self._comment_for = m

    def _comment_changed(self):
        m = self._comment_for
        if m is None:
            return
        text = self.comment.toPlainText()
        if text.strip():
            m.meta["sheet_comment"] = text
        else:
            m.meta.pop("sheet_comment", None)
        self.state.mark_dirty()
        self._debounce()

    def data(self) -> SheetData | None:
        m = self.meas.currentData()
        if m is None:
            return None
        res = self.ts_tab.result
        full = res is not None and getattr(self.ts_tab, "_free", None) is m
        second = getattr(self.ts_tab, "_second", None) if full else None
        self.show_second.setEnabled(second is not None)
        if full:
            self.scope.setText("Alle Parameter aus dem Tab „T/S-Parameter“ (inkl. Vas, Mms, Bl).")
        else:
            self.scope.setText("Nur Kennwerte aus dieser Messung. Für Vas, Mms, Bl zuerst im Tab "
                               "„T/S-Parameter“ mit dieser Messung als Freiluft-Messung rechnen.")
        inputs = (self.state.ts_state or {}).get("inputs") if full else None
        return build_sheet(m, title=self.title.text().strip() or m.name, info=self.state.info,
                           ts=res if full else None, second=second, ts_inputs=inputs,
                           show_model=self.show_model.isChecked(), show_second=self.show_second.isChecked(),
                           comment=self.comment.toPlainText())

    def update_preview(self, *_):
        d = self.data()
        if d is None:
            self.preview.setText("Keine Messung ausgewählt.")
            return
        img = render_image(d, dpi=96)
        self.preview.setPixmap(QtGui.QPixmap.fromImage(img))

    def _pdf(self):
        d = self.data()
        if d is None:
            return
        name = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in d.title).strip() or "Datenblatt"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Datenblatt speichern", f"{name}.pdf", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        save_pdf(path, d)
        self.state.status.emit(f"Datenblatt gespeichert: {path}")
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def _print(self):
        d = self.data()
        if d is not None and print_sheet(self, d):
            self.state.status.emit("Datenblatt an den Drucker gesendet.")
