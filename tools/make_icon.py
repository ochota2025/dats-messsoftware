"""Erzeugt das Programmsymbol (PNG in mehreren Größen + Windows-.ico).

Motiv: Impedanzkurve mit Resonanzspitze auf blauem Verlauf. Jede Größe wird direkt als Vektor-
grafik gezeichnet; kleine Größen bekommen dickere Linien und weniger Details, damit das Symbol
auch in der Taskleiste (16–32 px) klar erkennbar bleibt.

Aufruf:  .venv/bin/python tools/make_icon.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

OUT = Path(__file__).resolve().parents[1] / "src" / "datsmess" / "resources"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256, 512)


def curve_points(n: int = 200) -> list[tuple[float, float]]:
    """Stilisierte Impedanzkurve (x, y ∈ 0 … 1, y nach oben): flache Grundlinie, breite
    Resonanzglocke, Senke bei Re und der sanfte Anstieg durch die Schwingspuleninduktivität."""
    x = np.linspace(0.0, 1.0, n)
    bell = np.exp(-((x - 0.34) / 0.13) ** 2)
    rise = np.clip((x - 0.55) / 0.45, 0.0, None) ** 1.7
    y = 0.06 + 0.94 * bell + 0.50 * rise
    return list(zip(x, y))


def draw(size: int) -> QtGui.QImage:
    s = float(size)
    small = size <= 24
    img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)

    # Grundfläche: abgerundetes Quadrat mit diagonalem Blauverlauf
    m = 0.0 if small else s * 0.04
    rect = QtCore.QRectF(m, m, s - 2 * m, s - 2 * m)
    radius = rect.width() * (0.20 if small else 0.225)
    g = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0.0, QtGui.QColor("#3aa0ff"))
    g.setColorAt(0.55, QtGui.QColor("#1665c9"))
    g.setColorAt(1.0, QtGui.QColor("#0b3a86"))
    path = QtGui.QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.fillPath(path, g)
    p.setClipPath(path)

    # dezenter Glanz oben
    gl = QtGui.QLinearGradient(rect.topLeft(), QtCore.QPointF(rect.left(), rect.top() + rect.height() * 0.55))
    gl.setColorAt(0.0, QtGui.QColor(255, 255, 255, 46))
    gl.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
    p.fillRect(rect, gl)

    # Messgitter (nur größere Symbole)
    if size >= 40:
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 30))
        pen.setWidthF(max(1.0, s / 256))
        p.setPen(pen)
        for i in range(1, 4):
            x = rect.left() + rect.width() * i / 4
            p.drawLine(QtCore.QPointF(x, rect.top()), QtCore.QPointF(x, rect.bottom()))
        for i in range(1, 3):
            y = rect.top() + rect.height() * i / 3
            p.drawLine(QtCore.QPointF(rect.left(), y), QtCore.QPointF(rect.right(), y))

    # Kurve
    pad_x = rect.width() * (0.12 if small else 0.14)
    top = rect.top() + rect.height() * (0.20 if small else 0.25)
    bottom = rect.top() + rect.height() * (0.80 if small else 0.74)
    pts = [QtCore.QPointF(rect.left() + pad_x + x * (rect.width() - 2 * pad_x), bottom - y * (bottom - top))
           for x, y in curve_points()]
    line = QtGui.QPainterPath(pts[0])
    for q in pts[1:]:
        line.lineTo(q)

    if size >= 32:                                  # weiche Fläche unter der Kurve
        area = QtGui.QPainterPath(line)
        area.lineTo(pts[-1].x(), rect.bottom())
        area.lineTo(pts[0].x(), rect.bottom())
        area.closeSubpath()
        ga = QtGui.QLinearGradient(0, top, 0, rect.bottom())
        ga.setColorAt(0.0, QtGui.QColor(255, 255, 255, 95))
        ga.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
        p.fillPath(area, ga)

    width = s * (0.105 if size <= 16 else 0.085 if small else 0.062 if size <= 48 else 0.05)
    if size >= 48:                                  # weicher Schatten unter der Linie
        for k, a in ((2.6, 22), (1.7, 30)):
            sh = QtGui.QPen(QtGui.QColor(0, 25, 70, a), width * k, QtCore.Qt.SolidLine,
                            QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
            p.setPen(sh)
            p.drawPath(line.translated(0, width * 0.3))
    pen = QtGui.QPen(QtGui.QColor("#ffffff"), width, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)
    p.drawPath(line)

    # Akzentpunkt auf der Resonanzspitze
    if size >= 24:
        peak = min(pts, key=lambda q: q.y())
        r = width * (1.25 if size >= 48 else 1.05)
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), width * 0.55))
        p.setBrush(QtGui.QColor("#ffb020"))
        p.drawEllipse(peak, r, r)
    p.end()
    return img


def png_bytes(img: QtGui.QImage) -> bytes:
    ba = QtCore.QByteArray()
    buf = QtCore.QBuffer(ba)
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def write_ico(path: Path, images: dict[int, bytes]) -> None:
    sizes = [s for s in sorted(images) if s <= 256]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, data = b"", b""
    for s in sizes:
        blob = images[s]
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    path.write_bytes(header + entries + data)


def glyph(kind: str, color: str, size: int = 32) -> QtGui.QImage:
    """Kleine Bedienelement-Symbole für das Stylesheet (Häkchen, Pfeile), doppelte Auflösung."""
    img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    s = float(size)
    pen = QtGui.QPen(QtGui.QColor(color), s * (0.13 if kind == "check" else 0.11), QtCore.Qt.SolidLine,
                     QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
    p.setPen(pen)
    path = QtGui.QPainterPath()
    if kind == "check":
        path.moveTo(s * 0.24, s * 0.53)
        path.lineTo(s * 0.43, s * 0.71)
        path.lineTo(s * 0.77, s * 0.32)
    elif kind == "down":
        path.moveTo(s * 0.28, s * 0.40)
        path.lineTo(s * 0.50, s * 0.62)
        path.lineTo(s * 0.72, s * 0.40)
    elif kind == "up":
        path.moveTo(s * 0.28, s * 0.60)
        path.lineTo(s * 0.50, s * 0.38)
        path.lineTo(s * 0.72, s * 0.60)
    p.drawPath(path)
    p.end()
    return img


GLYPHS = {"check_white": ("check", "#ffffff"), "down_light": ("down", "#5b6676"), "up_light": ("up", "#5b6676"),
          "down_dark": ("down", "#aeb6c2"), "up_dark": ("up", "#aeb6c2")}


def main() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)  # noqa: F841
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (kind, color) in GLYPHS.items():
        glyph(kind, color).save(str(OUT / f"ui_{name}.png"))
    blobs = {}
    for s in SIZES:
        blobs[s] = png_bytes(draw(s))
        (OUT / f"icon_{s}.png").write_bytes(blobs[s])
    write_ico(OUT / "icon.ico", blobs)
    print(f"Symbole geschrieben nach {OUT}")


if __name__ == "__main__":
    main()
