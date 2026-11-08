"""Startpunkt der grafischen Anwendung."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    from PySide6 import QtCore, QtWidgets

    from .gui.icon import app_icon, set_windows_app_id

    argv = list(sys.argv)
    if "--wait-pid" in argv:            # Neustart nach dem Selbst-Update: alten Prozess abwarten
        i = argv.index("--wait-pid")
        try:
            pid = int(argv[i + 1])
        except (IndexError, ValueError):
            pid = 0
        del argv[i:i + 2]
        from .selfupdate import wait_for_pid
        wait_for_pid(pid)
    set_windows_app_id()                # eigenes Symbol in der Windows-Taskleiste statt Python
    app = QtWidgets.QApplication(argv)
    app.setApplicationName("DATS-Messsoftware")
    app.setOrganizationName("datsmess")
    app.setWindowIcon(app_icon())
    from . import diagnostics
    from .gui import errors

    folder = Path(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.AppDataLocation))
    try:
        diagnostics.setup_logging(folder)
    except OSError:
        pass
    errors.install_excepthook()

    from .gui.appearance import appearance

    appearance().apply_initial(app)

    from .gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    w.after_start()
    code = app.exec()
    diagnostics.log.info("Programm beendet (Code %s)", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
