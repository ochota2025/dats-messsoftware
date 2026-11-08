"""Fehleranzeige mit „Fehlerbericht kopieren“ und globale Ausnahmebehandlung.

Unbehandelte Fehler beenden das Programm nicht mehr stillschweigend (unter Windows läuft es
ohne Konsolenfenster), sondern landen im Protokoll und in einem Dialog, aus dem sich der
komplette Fehlerbericht kopieren oder speichern lässt.
"""
from __future__ import annotations

import logging
import sys
import threading
import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .. import diagnostics

log = logging.getLogger("datsmess")

# Liefert Zusatzinfos (Gerät, Einstellungen, Kalibrierung …) – setzt das Hauptfenster.
context_provider = None


def report_text(error: str | None = None) -> str:
    ctx = {}
    if context_provider is not None:
        try:
            ctx = context_provider()
        except Exception as e:      # noqa: BLE001 – der Bericht selbst darf nie scheitern
            ctx = {"Kontext": f"nicht verfügbar ({e})"}
    return diagnostics.build_report(ctx, error)


def copy_report(error: str | None = None, parent=None) -> str:
    text = report_text(error)
    QtWidgets.QApplication.clipboard().setText(text)
    return text


def save_report(parent, error: str | None = None) -> None:
    default = str(Path.home() / "DATS-Fehlerbericht.txt")
    path, _ = QtWidgets.QFileDialog.getSaveFileName(parent, "Fehlerbericht speichern", default,
                                                    "Textdatei (*.txt)")
    if path:
        Path(path).write_text(report_text(error), encoding="utf-8")


class ReportDialog(QtWidgets.QDialog):
    """Zeigt einen Fehler (oder nur den Bericht) und bietet Kopieren/Speichern an."""

    def __init__(self, parent=None, title: str = "Fehlerbericht", message: str = "",
                 details: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.details = details
        lay = QtWidgets.QVBoxLayout(self)
        if message:
            lbl = QtWidgets.QLabel(message)
            lbl.setWordWrap(True)
            lbl.setTextFormat(QtCore.Qt.RichText)
            lay.addWidget(lbl)
        hint = QtWidgets.QLabel(
            "Mit <b>Kopieren</b> landet der komplette Bericht (Version, System, Audio-Geräte, "
            "Einstellungen, Protokoll) in der Zwischenablage – einfach in den Messenger oder eine "
            "E-Mail einfügen. Persönliche Ordnernamen werden dabei entfernt.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(hint)
        self.text = QtWidgets.QPlainTextEdit(report_text(details))
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.text.setFont(f)
        lay.addWidget(self.text, 1)
        row = QtWidgets.QHBoxLayout()
        self.btn_copy = QtWidgets.QPushButton("Kopieren")
        btn_save = QtWidgets.QPushButton("Als Datei speichern …")
        btn_close = QtWidgets.QPushButton("Schließen")
        self.btn_copy.setDefault(True)
        row.addWidget(self.btn_copy)
        row.addWidget(btn_save)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)
        self.btn_copy.clicked.connect(self._copy)
        btn_save.clicked.connect(lambda: save_report(self, details))
        btn_close.clicked.connect(self.accept)
        self.resize(760, 520)

    def _copy(self):
        QtWidgets.QApplication.clipboard().setText(self.text.toPlainText())
        self.btn_copy.setText("✔ Kopiert")
        QtCore.QTimer.singleShot(2000, lambda: self.btn_copy.setText("Kopieren"))


def show_error(parent, title: str, message: str, details: str | None = None) -> None:
    """Fehlermeldung mit der Möglichkeit, einen Fehlerbericht zu kopieren."""
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, title, message,
                                QtWidgets.QMessageBox.Close, parent)
    btn_report = box.addButton("Fehlerbericht …", QtWidgets.QMessageBox.ActionRole)
    box.button(QtWidgets.QMessageBox.Close).setText("Schließen")
    box.exec()
    if box.clickedButton() is btn_report:
        ReportDialog(parent, "Fehlerbericht", "", details or message).exec()


# --------------------------------------------------------------------------
# Globale Ausnahmebehandlung
# --------------------------------------------------------------------------

class _Relay(QtCore.QObject):
    """Bringt Fehler aus Hintergrund-Threads in den GUI-Thread."""
    raised = QtCore.Signal(str, str)


_relay: _Relay | None = None
_showing = False


def _present(summary: str, details: str) -> None:
    global _showing
    if _showing:                    # Folgefehler nicht stapeln
        return
    _showing = True
    try:
        parent = QtWidgets.QApplication.activeWindow()
        ReportDialog(parent, "Unerwarteter Fehler",
                     "<b>Im Programm ist ein Fehler aufgetreten.</b><br>"
                     f"{summary}<br><br>Das Programm läuft weiter. Bitte den Fehlerbericht kopieren "
                     "und zusammen mit einer kurzen Beschreibung schicken, was du gerade gemacht hast.",
                     details).exec()
    finally:
        _showing = False


def _handle(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    details = "".join(traceback.format_exception(exc_type, exc, tb))
    log.error("Unbehandelter Fehler:\n%s", details)
    summary = f"{exc_type.__name__}: {exc}"
    if _relay is not None:
        _relay.raised.emit(summary.replace("<", "&lt;"), details)


def install_excepthook() -> None:
    global _relay
    _relay = _Relay()
    _relay.raised.connect(_present, QtCore.Qt.QueuedConnection)
    sys.excepthook = _handle
    threading.excepthook = lambda a: _handle(a.exc_type, a.exc_value, a.exc_traceback)

    def qt_messages(mode, ctx, msg):
        if mode in (QtCore.QtMsgType.QtCriticalMsg, QtCore.QtMsgType.QtFatalMsg):
            log.error("Qt: %s", msg)
        elif mode == QtCore.QtMsgType.QtWarningMsg and "propagateSizeHints" not in msg:
            log.warning("Qt: %s", msg)

    QtCore.qInstallMessageHandler(qt_messages)
