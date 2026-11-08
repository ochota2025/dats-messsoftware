"""Startpunkt der grafischen Anwendung."""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("DATS-Messsoftware")
    app.setOrganizationName("datsmess")
    from .gui.appearance import appearance

    appearance().apply_initial(app)

    from .gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
