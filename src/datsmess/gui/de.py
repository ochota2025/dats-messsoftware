"""Deutsche Beschriftung für Standard-Knöpfe und kleine Abfragen.

Die schlanke Qt-Variante (PySide6-Essentials) enthält keine Übersetzungsdateien;
Standard-Knöpfe hießen sonst „Cancel“, „Apply“ usw.
"""
from __future__ import annotations

from PySide6 import QtWidgets

_BB = QtWidgets.QDialogButtonBox
_MB = QtWidgets.QMessageBox
_LABELS = {"Ok": "OK", "Cancel": "Abbrechen", "Apply": "Übernehmen", "Save": "Speichern",
           "Discard": "Verwerfen", "Yes": "Ja", "No": "Nein", "Close": "Schließen"}


def germanize(box) -> None:
    """Für QDialogButtonBox oder QMessageBox."""
    enum = _BB if isinstance(box, QtWidgets.QDialogButtonBox) else _MB
    for name, text in _LABELS.items():
        b = box.button(getattr(enum, name))
        if b is not None:
            b.setText(text)


def button_box(dialog, *names: str) -> QtWidgets.QDialogButtonBox:
    flags = _BB.StandardButton(0)
    for n in names or ("Ok", "Cancel"):
        flags |= getattr(_BB, n)
    bb = QtWidgets.QDialogButtonBox(flags)
    bb.accepted.connect(dialog.accept)
    bb.rejected.connect(dialog.reject)
    germanize(bb)
    return bb


def ask(parent, title: str, text: str, buttons=_MB.Ok | _MB.Cancel, default=None):
    mb = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, title, text, buttons, parent)
    if default is not None:
        mb.setDefaultButton(default)
    germanize(mb)
    return mb.exec()


def _input(parent, title: str, label: str) -> QtWidgets.QInputDialog:
    d = QtWidgets.QInputDialog(parent)
    d.setWindowTitle(title)
    d.setLabelText(label)
    d.setOkButtonText("OK")
    d.setCancelButtonText("Abbrechen")
    return d


def get_text(parent, title: str, label: str, text: str = "") -> tuple[str, bool]:
    d = _input(parent, title, label)
    d.setTextValue(text)
    ok = d.exec() == QtWidgets.QDialog.Accepted
    return d.textValue(), ok


def get_item(parent, title: str, label: str, items: list[str]) -> tuple[str, bool]:
    d = _input(parent, title, label)
    d.setComboBoxItems(items)
    d.setComboBoxEditable(False)
    ok = d.exec() == QtWidgets.QDialog.Accepted
    return d.textValue(), ok
