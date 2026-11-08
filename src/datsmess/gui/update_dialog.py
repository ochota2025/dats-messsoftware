"""Kleines Fortschrittsfenster für das Selbst-Update – statt schwarzer Konsolenfenster."""
from __future__ import annotations

import logging

from PySide6 import QtCore, QtWidgets

from .. import selfupdate
from .appearance import appearance
from .icon import icon_pixmap

log = logging.getLogger("datsmess")


class _Worker(QtCore.QThread):
    progress = QtCore.Signal(str, str, int, int)
    finished_ok = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, fetch=None, root=None):
        super().__init__()
        self.fetch = fetch
        self.root = root

    def run(self):
        try:
            kw = {"progress": lambda *a: self.progress.emit(*a), "fetch": self.fetch}
            if self.root is not None:
                kw["root"] = self.root
            self.finished_ok.emit(selfupdate.run_update(**kw))
        except Exception as e:      # noqa: BLE001
            log.exception("Selbst-Update fehlgeschlagen")
            self.failed.emit(str(e))


class UpdateDialog(QtWidgets.QDialog):
    """Zeigt Laden → Entpacken → Einspielen → (Bibliotheken) und startet danach neu."""

    def __init__(self, parent=None, target_version: str = "", fetch=None, root=None, restart=True):
        super().__init__(parent)
        self.setWindowTitle("Aktualisieren")
        self.setModal(True)
        self.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
        self.result_info = None
        self.do_restart = restart
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(10)
        head = QtWidgets.QHBoxLayout()
        logo = QtWidgets.QLabel()
        logo.setPixmap(icon_pixmap(44))
        head.addWidget(logo)
        title = QtWidgets.QLabel(f"<b>DATS-Messsoftware wird aktualisiert</b>"
                                 + (f"<br><span style='color:{appearance().current.muted}'>auf Version "
                                    f"{target_version}</span>" if target_version else ""))
        title.setTextFormat(QtCore.Qt.RichText)
        head.addWidget(title, 1)
        lay.addLayout(head)
        self.status = QtWidgets.QLabel("Wird vorbereitet …")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        self.hint = QtWidgets.QLabel("Das Programm startet danach von selbst neu. Deine Projekte und "
                                     "Einstellungen bleiben erhalten.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.hint)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.btn = QtWidgets.QPushButton("Schließen")
        self.btn.setVisible(False)
        self.btn.clicked.connect(self.reject)
        row.addWidget(self.btn)
        lay.addLayout(row)
        self.setMinimumWidth(440)

        self.worker = _Worker(fetch, root)
        self.worker.progress.connect(self._progress)
        self.worker.finished_ok.connect(self._ok)
        self.worker.failed.connect(self._fail)
        QtCore.QTimer.singleShot(150, self.worker.start)

    def _progress(self, _step: str, text: str, value: int, total: int):
        self.status.setText(text)
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(value)
            if _step == "download":
                self.status.setText(f"{text}  {value / 1e6:.1f} von {total / 1e6:.1f} MB")
        else:
            self.bar.setRange(0, 0)
            if _step == "download" and value:
                self.status.setText(f"{text}  {value / 1e6:.1f} MB")

    def _ok(self, info):
        self.result_info = info
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.status.setText(f"<span style='color:{appearance().current.ok}'>✔ Version {info.version} ist "
                            "eingespielt – das Programm startet neu …</span>")
        QtCore.QTimer.singleShot(900, self.accept)

    def _fail(self, msg: str):
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        a = appearance().current
        self.status.setText(f"<span style='color:{a.err}'><b>Das Update hat nicht geklappt.</b></span><br>{msg}")
        self.status.setTextFormat(QtCore.Qt.RichText)
        self.hint.setText("Die bisherige Version läuft unverändert weiter. Alternativ: Programm schließen und "
                          "im Programmordner die Update-Datei doppelklicken.")
        self.btn.setVisible(True)
        self.adjustSize()

    def reject(self):
        if self.worker.isRunning():         # nicht mitten im Einspielen abbrechen
            return
        super().reject()

    def closeEvent(self, ev):
        if self.worker.isRunning():
            ev.ignore()
            return
        super().closeEvent(ev)
