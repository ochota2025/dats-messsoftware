"""Hilfe: „Erste Schritte“ (eingebaute Kurzanleitung) und „Was ist neu?“."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .. import __version__, updates

MOD = "⌘" if QtCore.QSysInfo.productType() == "macos" else "Strg+"

GUIDE = f"""
# Erste Schritte

## 1 · Ohne DATS ausprobieren (Simulator)

Ist kein DATS angeschlossen, ist links **„Simulator (ohne Hardware)“** gewählt. Unter
*Simulator → Angeschlossen* wählst du, was virtuell an den Klemmen hängt (Treiber, Widerstand,
Kondensator …). Mit *Exemplar* gibt es mehrere leicht unterschiedliche Treiber – ideal zum
Ausprobieren des Paarvergleichs.

## 2 · Mit dem echten DATS – einmalig einrichten

1. DATS per USB anschließen, Programm starten. Das Gerät wird erkannt und mit ★ markiert.
2. **Messung → Geräte-Check …** – findet heraus, welcher Eingang Referenz und welcher Messung
   ist, und bestimmt Referenz- und Kalibrierwiderstand (mit einem Multimeter-Widerstand sogar
   absolut). Das Ergebnis wird übernommen.
3. **Kalibrier-Assistent …** (links) – Leerlauf, Kurzschluss, Kalibrierwiderstand. Danach steht
   links grün „Kalibriert“.

## 3 · Messen

* **Impedanz messen** ({MOD}M). Neben jeder Messung zeigt ein farbiger Punkt die
  **Messqualität**: grün = gut, gelb = mäßig, rot = schlecht. Der Tooltip nennt den Grund
  (z. B. Übersteuerung, zu wenig Pegel, Brummen).
* Rechts oben erscheinen sofort fs, Re, Qms, Qes, Qts, Zmax und Le.
* **Speicherplätze 1 … 8** über dem Diagramm: {MOD}1 … 8 legt die aktuelle Messung ab.

## 4 · Auswerten

| Tab | Wofür |
|---|---|
| **T/S-Parameter** | Vas, Mms, Bl … mit Zusatzmasse oder Testgehäuse; Export für WinISD, VituixCAD & Co. |
| **Pegelreihe** | Misst bei mehreren Pegeln und zeigt, wie sich fs, Q und Re verändern. |
| **Vergleich** | Treiber-Exemplare vergleichen, Toleranz-Ampel, beste Paare für Stereo. |
| **Korrektur** | Zobel-Glied und Saugkreis berechnen, korrigierte Kurve übernehmen. |
| **Klirr & Rub/Buzz** | Elektrischer Klirrfaktor und Schleifgeräusche aus einer vorhandenen Messung. |
| **Bauteile (LCR)** | Kondensatoren, Spulen, Widerstände. |
| **Generator & Oszilloskop** | Testsignale ausgeben und beide Eingänge live ansehen. |

## 5 · Speichern und weitergeben

* **Datei → Projekt speichern** ({MOD}S) – alles in einer `.datsproj`-Datei. Zwischendurch
  sichert das Programm automatisch; nach einem Absturz wird angeboten, die Messungen
  wiederherzustellen. **Datei → Zuletzt geöffnet** listet die letzten Projekte.
* **Datei → Datenblatt** ({MOD}P) – A4-Datenblatt als PDF oder Ausdruck, mit eigenem Kommentar.

## 6 · Wenn etwas nicht klappt

**Hilfe → Fehlerbericht …** kopiert Version, System, Audio-Geräte, Einstellungen und das Protokoll
in die Zwischenablage – einfach in den Messenger einfügen. Persönliche Ordnernamen werden dabei
entfernt. Bei einem Programmfehler öffnet sich dieser Bericht automatisch.
"""


class MarkdownDialog(QtWidgets.QDialog):
    def __init__(self, parent, title: str, markdown: str, size=(720, 640)):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QtWidgets.QVBoxLayout(self)
        self.view = QtWidgets.QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setMarkdown(markdown)
        lay.addWidget(self.view, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        btn = QtWidgets.QPushButton("Schließen")
        btn.setDefault(True)
        btn.clicked.connect(self.accept)
        row.addWidget(btn)
        lay.addLayout(row)
        self.resize(*size)


def show_guide(parent) -> None:
    MarkdownDialog(parent, "Erste Schritte", GUIDE).exec()


def whats_new_markdown(since: str | None = None) -> str:
    md = updates.local_changelog()
    if not md:
        return f"# Version {__version__}\n\nKeine Änderungsliste gefunden."
    if since:
        newer = updates.sections_newer_than(md, since)
        if newer:
            return f"# Neu seit Version {since}\n\n{newer}"
    return md


def show_whats_new(parent, since: str | None = None) -> None:
    MarkdownDialog(parent, "Was ist neu?", whats_new_markdown(since)).exec()
