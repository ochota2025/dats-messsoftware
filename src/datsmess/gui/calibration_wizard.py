"""Kalibrier-Assistent (DM-03): Leerlauf → Kurzschluss → Kalibrierwiderstand."""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtWidgets

from ..analysis.quality import grade
from ..dsp.calibration import Calibration
from .appearance import appearance
from .state import AppState

STEPS = {
    "open": ("Schritt: Leerlauf",
             "Die beiden Krokodilklemmen <b>offen</b> lassen – sie dürfen sich nicht berühren "
             "und nichts anderes kontaktieren.<br><br>Damit wird das Verhältnis der beiden "
             "Eingangskanäle sowie der Eingangswiderstand des Interfaces bestimmt."),
    "short": ("Schritt: Kurzschluss",
              "Die beiden Krokodilklemmen <b>direkt miteinander</b> verbinden (Metall auf Metall, "
              "fest zusammengeklemmt).<br><br>Damit werden Kabel- und Übergangswiderstände "
              "der Messleitungen ermittelt und später herausgerechnet."),
    "cal": ("Schritt: Kalibrierwiderstand",
            "Die Krokodilklemmen an die beiden <b>Messpunkte des internen Kalibrierwiderstands</b> "
            "am Gehäuse des DATS anschließen (beim DATS V1/V2: an den mitgelieferten losen "
            "1-kΩ-Widerstand).<br><br>Damit wird der wirksame Referenzwiderstand "
            "der Messbrücke frequenzabhängig bestimmt."),
}
PAGE_IDS = {"intro": 0, "open": 1, "short": 2, "cal": 3, "result": 4}


class IntroPage(QtWidgets.QWizardPage):
    def __init__(self, wiz: "CalibrationWizard"):
        super().__init__()
        self.setTitle("Kalibrierung des Mess-Interfaces")
        self.setSubTitle("Kompensiert Kanaltoleranzen, Kabel- und Übergangswiderstände.")
        lay = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel(
            "Die Kalibrierung gilt für das gewählte Gerät, die Abtastrate und die Sweep-Länge. "
            "Sie wird gespeichert und beim nächsten Start automatisch geladen.<br><br>"
            "Empfohlen sind alle drei Schritte. Wird nur der Kalibrierwiderstand gemessen, "
            "verwendet die Software den eingestellten Nennwert des Referenzwiderstands.")
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QtWidgets.QFormLayout()
        self.r_cal = QtWidgets.QDoubleSpinBox()
        self.r_cal.setRange(0.1, 100000.0)
        self.r_cal.setDecimals(3)
        self.r_cal.setSuffix(" Ω")
        self.r_cal.setValue(wiz.r_cal_default)
        form.addRow("Wert des Kalibrierwiderstands:", self.r_cal)
        self.do_open = QtWidgets.QCheckBox("Leerlauf-Messung (empfohlen)")
        self.do_open.setChecked(True)
        self.do_short = QtWidgets.QCheckBox("Kurzschluss-Messung (empfohlen)")
        self.do_short.setChecked(True)
        form.addRow(self.do_open)
        form.addRow(self.do_short)
        lay.addLayout(form)
        lay.addStretch(1)


class StepPage(QtWidgets.QWizardPage):
    def __init__(self, wiz: "CalibrationWizard", kind: str):
        super().__init__()
        self.wiz = wiz
        self.kind = kind
        title, text = STEPS[kind]
        self.setTitle(title)
        lay = QtWidgets.QVBoxLayout(self)
        lbl = QtWidgets.QLabel(text)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        self.sim_note = QtWidgets.QLabel()
        self.sim_note.setStyleSheet("color: palette(link);")
        lay.addWidget(self.sim_note)
        self.btn = QtWidgets.QPushButton("Messen")
        self.btn.setMinimumHeight(36)
        self.btn.clicked.connect(self._measure)
        lay.addWidget(self.btn)
        self.result = QtWidgets.QLabel("Noch nicht gemessen.")
        self.result.setWordWrap(True)
        lay.addWidget(self.result)
        lay.addStretch(1)

    def initializePage(self):
        st = self.wiz.state
        if st.is_simulator:
            st.set_connection(self.kind)
            self.sim_note.setText("Simulator: Verbindung wurde automatisch hergestellt.")
        else:
            self.sim_note.setText("")

    def _measure(self):
        self.btn.setEnabled(False)
        self.result.setText("Messung läuft …")
        eng = self.wiz.state.engine
        self.wiz.state.run(eng.measure_H, self._done, self._fail, text="Kalibriermessung läuft …")

    def _done(self, raw):
        self.btn.setEnabled(True)
        self.wiz.H[self.kind] = raw.H
        self.wiz.R[self.kind] = raw.recordings
        msg = [f"✔ gemessen – Spitzenpegel Referenz {20 * np.log10(raw.peak_ref + 1e-12):.1f} dBFS, "
               f"Messkanal {20 * np.log10(raw.peak_meas + 1e-12):.1f} dBFS"]
        a = appearance().current
        if raw.quality is not None:
            g, hints = grade(raw.quality, self.kind)
            for h in hints:
                msg.append(f"<span style='color:{a.err if g == 'bad' else a.warn}'>{h}</span>")
            if g == "ok":
                msg.append(f"<span style='color:{a.ok}'>Signalqualität gut.</span>")
        else:
            if raw.clipped:
                msg.append(f"<span style='color:{a.err}'>Übersteuerung! Pegel reduzieren und wiederholen.</span>")
            if self.kind != "short" and raw.peak_meas < 1e-3:
                msg.append(f"<span style='color:{a.err}'>Kaum Signal am Messkanal – Verbindung prüfen.</span>")
        self.result.setText("<br>".join(msg))
        self.completeChanged.emit()

    def _fail(self, err):
        self.btn.setEnabled(True)
        self.result.setText(f"<span style='color:#e04848'>Fehler: {err}</span>")

    def isComplete(self):
        return self.kind in self.wiz.H


class ResultPage(QtWidgets.QWizardPage):
    def __init__(self, wiz: "CalibrationWizard"):
        super().__init__()
        self.wiz = wiz
        self.setTitle("Ergebnis")
        lay = QtWidgets.QVBoxLayout(self)
        self.text = QtWidgets.QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(self.text)
        lay.addStretch(1)

    def initializePage(self):
        w = self.wiz
        eng = w.state.engine
        cal = Calibration(sweep=eng.sweep, r_cal=w.intro.r_cal.value(), f=eng.sweep.frequencies(),
                          H_load=w.H["cal"], H_open=w.H.get("open") if w.intro.do_open.isChecked() else None,
                          H_short=w.H.get("short") if w.intro.do_short.isChecked() else None,
                          r_nominal=eng.channels.r_nominal, device=w.state.backend.describe())
        used = ["cal"] + [k for k, on in (("open", w.intro.do_open.isChecked()),
                                          ("short", w.intro.do_short.isChecked())) if on]
        cal.recordings = {k: w.R[k] for k in used if w.R.get(k) is not None}
        cal.channels = eng.channels.to_dict()
        w.calibration = cal
        f = cal.f
        i1k = int(np.argmin(np.abs(f - 1000)))
        rs = cal.r_s[i1k]
        k = cal.k[i1k]
        lines = [f"<b>Schritte:</b> {', '.join(cal.steps)}",
                 f"<b>Referenzwiderstand im DATS (gemessen) @ 1 kHz:</b> {abs(rs):.3f} Ω ∠ {np.degrees(np.angle(rs)):+.2f}°",
                 f"<b>Kanalverhältnis @ 1 kHz:</b> {abs(k):.4f} ∠ {np.degrees(np.angle(k)):+.2f}°"]
        lr = cal.lead_resistance()
        if lr is not None:
            lines.append(f"<b>Kabel-/Übergangswiderstand:</b> {lr * 1000:.1f} mΩ")
            if lr > 0.5:
                lines.append(f"<span style='color:{appearance().current.warn}'>Recht hoher Leitungswiderstand – "
                             "sitzen die Klemmen beim Kurzschluss fest? Er wird aber herausgerechnet.</span>")
        band = (f > 20) & (f < 10000)
        spread = np.ptp(np.abs(cal.r_s[band])) / np.median(np.abs(cal.r_s[band]))
        lines.append(f"<b>Schwankung Referenzwiderstand 20 Hz–10 kHz:</b> {spread * 100:.2f} %")
        if spread > 0.05:
            lines.append(f"<span style='color:{appearance().current.warn}'>Starke Frequenzabhängigkeit – Kanalzuordnung "
                         "oder Verbindungen prüfen.</span>")
        lines.append("<br>Mit <b>Fertigstellen</b> wird die Kalibrierung übernommen und gespeichert.")
        self.text.setText("<br>".join(lines))


class CalibrationWizard(QtWidgets.QWizard):
    def __init__(self, state: AppState, parent=None, r_cal_default: float = 1000.0):
        super().__init__(parent)
        self.state = state
        self.r_cal_default = r_cal_default
        self.H: dict[str, np.ndarray] = {}
        self.R: dict[str, np.ndarray] = {}      # Rohaufnahmen je Schritt (für das Projektarchiv)
        self.calibration: Calibration | None = None
        self.setWindowTitle("Kalibrier-Assistent")
        self.setWizardStyle(QtWidgets.QWizard.ModernStyle)
        self.setMinimumSize(560, 420)
        self.intro = IntroPage(self)
        self.setPage(PAGE_IDS["intro"], self.intro)
        for k in ("open", "short", "cal"):
            self.setPage(PAGE_IDS[k], StepPage(self, k))
        self.setPage(PAGE_IDS["result"], ResultPage(self))
        self.setButtonText(QtWidgets.QWizard.NextButton, "Weiter >")
        self.setButtonText(QtWidgets.QWizard.BackButton, "< Zurück")
        self.setButtonText(QtWidgets.QWizard.FinishButton, "Fertigstellen")
        self.setButtonText(QtWidgets.QWizard.CancelButton, "Abbrechen")

    def nextId(self):
        cur = self.currentId()
        order = ["intro"]
        if self.intro.do_open.isChecked():
            order.append("open")
        if self.intro.do_short.isChecked():
            order.append("short")
        order += ["cal", "result"]
        names = {v: k for k, v in PAGE_IDS.items()}
        name = names.get(cur)
        if name not in order or order.index(name) == len(order) - 1:
            return -1
        return PAGE_IDS[order[order.index(name) + 1]]

    def accept(self):
        if self.calibration is not None:
            self.state.set_calibration(self.calibration)
            self.state.status.emit("Kalibrierung gespeichert.")
        super().accept()

    def done(self, result):
        # Simulator nach der Kalibrierung wieder an den Testtreiber „anschließen“,
        # sonst misst die nächste Messung den Kalibrierwiderstand.
        if self.state.is_simulator:
            self.state.set_connection("driver")
        super().done(result)
