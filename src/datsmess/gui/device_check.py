"""Geräte-Check (Ersteinrichtung): Live-Pegel, Kanalzuordnung, Referenz- und Kalibrierwiderstand.

Gedacht für den ersten Einsatz eines echten DATS V3, dessen Beschaltung nicht dokumentiert ist.
Am Ende werden Kanalzuordnung, Referenzwiderstand und Kalibrierwiderstand übernommen; das
Ergebnis landet zusätzlich als Text im Fehlerbericht.
"""
from __future__ import annotations

import logging

import numpy as np
from PySide6 import QtCore, QtWidgets

from ..analysis.quality import grade
from ..analysis.setup_check import channel_levels, detect_assignment, estimate_bridge
from ..dsp.generator import generate
from ..measurement import ChannelConfig, MeasurementEngine
from .appearance import appearance
from .state import AppState

log = logging.getLogger("datsmess")

STEP_TEXT = {
    "open": ("Leerlauf", "Die beiden Krokodilklemmen <b>offen</b> lassen (sie dürfen sich nicht berühren)."),
    "short": ("Kurzschluss", "Die beiden Krokodilklemmen <b>direkt miteinander</b> verbinden – Metall auf "
                             "Metall, fest zusammengeklemmt."),
    "cal": ("Kalibrierwiderstand", "Die Klemmen an die <b>Messpunkte des internen Kalibrierwiderstands</b> "
                                   "am Gehäuse des DATS anschließen."),
    "known": ("Bekannter Widerstand (optional)",
              "Einen Widerstand anschließen, dessen Wert du <b>mit einem Multimeter</b> gemessen hast "
              "(ideal 4 … 100 Ω, z. B. 8,2 Ω oder 47 Ω), und den Wert unten eintragen. Damit lassen sich "
              "Referenz- und Kalibrierwiderstand absolut bestimmen. Ohne Multimeter: Schritt überspringen."),
}
SIM_CONN = {"open": "open", "short": "short", "cal": "cal", "known": "resistor"}


class LevelMeter(QtWidgets.QWidget):
    """Zwei waagerechte Pegelbalken (dBFS) für die Eingänge."""

    def __init__(self):
        super().__init__()
        lay = QtWidgets.QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.bars, self.labels = [], []
        for i in range(2):
            bar = QtWidgets.QProgressBar()
            bar.setRange(-80, 0)
            bar.setTextVisible(False)
            bar.setMinimumHeight(18)
            lbl = QtWidgets.QLabel("–")
            lbl.setMinimumWidth(90)
            lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            lay.addWidget(QtWidgets.QLabel(f"Eingang {i + 1}:"), i, 0)
            lay.addWidget(bar, i, 1)
            lay.addWidget(lbl, i, 2)
            self.bars.append(bar)
            self.labels.append(lbl)

    def set_levels(self, levels: list[float | None]):
        for bar, lbl, lv in zip(self.bars, self.labels, levels):
            if lv is None:
                bar.setValue(-80)
                lbl.setText("–")
                continue
            bar.setValue(int(max(-80, min(0, lv))))
            lbl.setText(f"{lv:6.1f} dBFS")


class IntroPage(QtWidgets.QWizardPage):
    def __init__(self, wiz: "DeviceCheckWizard"):
        super().__init__()
        self.wiz = wiz
        self.setTitle("Geräte-Check")
        self.setSubTitle("Findet Kanalzuordnung und Widerstandswerte des Mess-Interfaces – "
                         "einmalig vor der ersten Kalibrierung.")
        lay = QtWidgets.QVBoxLayout(self)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(self.info)
        g = QtWidgets.QGroupBox("Live-Pegel (Klemmen offen lassen)")
        gl = QtWidgets.QVBoxLayout(g)
        self.meter = LevelMeter()
        gl.addWidget(self.meter)
        self.btn_tone = QtWidgets.QPushButton("Prüfton 1 kHz einschalten")
        self.btn_tone.setCheckable(True)
        gl.addWidget(self.btn_tone)
        self.meter_hint = QtWidgets.QLabel()
        self.meter_hint.setWordWrap(True)
        gl.addWidget(self.meter_hint)
        lay.addWidget(g)
        lay.addStretch(1)
        self.btn_tone.toggled.connect(self._tone)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._poll)

    def initializePage(self):
        st = self.wiz.state
        be = st.backend
        lines = [f"<b>Gerät:</b> {be.describe()}"]
        if st.is_simulator:
            lines.append("Simulator aktiv – die Verbindungen werden bei jedem Schritt automatisch hergestellt.")
            st.set_connection("open")
        else:
            lines.append("Vor dem Start: <b>System-Lautstärke für das DATS auf 100 %</b> stellen "
                         "(Windows: Lautsprechersymbol → Ausgabegerät DATS; macOS: Audio-MIDI-Setup). "
                         "Andere Programme, die Ton ausgeben, schließen.")
        self.info.setText("<br><br>".join(lines))

    def _tone(self, on: bool):
        be = self.wiz.state.backend
        if on:
            fs = self.wiz.state.engine.sweep.fs
            try:
                be.start_stream(generate("sine", 1000.0, -20.0, 1.0, fs), fs, loop=True)
            except Exception as e:          # noqa: BLE001
                self.btn_tone.setChecked(False)
                self.meter_hint.setText(f"<span style='color:{appearance().current.err}'>Gerät lässt sich "
                                        f"nicht öffnen: {e}</span>")
                log.warning("Geräte-Check: Prüfton fehlgeschlagen: %s", e)
                return
            self.btn_tone.setText("Prüfton ausschalten")
            self.timer.start()
        else:
            self.timer.stop()
            be.stop()
            self.btn_tone.setText("Prüfton 1 kHz einschalten")
            self.meter.set_levels([None, None])

    def _poll(self):
        be = self.wiz.state.backend
        fs = be.stream_fs or 48000
        x = be.read_input(int(0.1 * fs))
        if x is None:
            return
        lv = [float(20 * np.log10(max(np.sqrt(np.mean(np.square(x[:, c]))), 1e-9))) for c in range(x.shape[1])]
        self.meter.set_levels(lv)
        a = appearance().current
        if max(lv) < -60:
            self.meter_hint.setText(f"<span style='color:{a.err}'>Kein Signal – Ausgabegerät, Lautstärke und "
                                    "USB-Kabel prüfen.</span>")
        elif abs(lv[0] - lv[1]) > 6:
            self.meter_hint.setText(f"<span style='color:{a.warn}'>Die Eingänge unterscheiden sich um "
                                    f"{abs(lv[0] - lv[1]):.0f} dB, obwohl die Klemmen offen sind – Klemmen "
                                    "berühren sich? Nur ein Eingang aktiv?</span>")
        else:
            self.meter_hint.setText(f"<span style='color:{a.ok}'>✔ Signal kommt an beiden Eingängen an "
                                    "(bei offenen Klemmen etwa gleich laut).</span>")

    def cleanupPage(self):
        self.btn_tone.setChecked(False)

    def validatePage(self):
        self.btn_tone.setChecked(False)
        return True


class StepPage(QtWidgets.QWizardPage):
    def __init__(self, wiz: "DeviceCheckWizard", kind: str):
        super().__init__()
        self.wiz = wiz
        self.kind = kind
        title, text = STEP_TEXT[kind]
        self.setTitle(f"Schritt: {title}")
        lay = QtWidgets.QVBoxLayout(self)
        lbl = QtWidgets.QLabel(text)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        if kind == "known":
            form = QtWidgets.QFormLayout()
            self.r_known = QtWidgets.QDoubleSpinBox()
            self.r_known.setRange(0.5, 10000)
            self.r_known.setDecimals(3)
            self.r_known.setSuffix(" Ω")
            self.r_known.setValue(8.2)
            form.addRow("Gemessener Wert:", self.r_known)
            lay.addLayout(form)
        self.sim_note = QtWidgets.QLabel()
        self.sim_note.setStyleSheet("color: palette(link);")
        lay.addWidget(self.sim_note)
        self.btn = QtWidgets.QPushButton("Messen")
        self.btn.setMinimumHeight(34)
        self.btn.clicked.connect(self._measure)
        lay.addWidget(self.btn)
        self.result = QtWidgets.QLabel("Noch nicht gemessen.")
        self.result.setWordWrap(True)
        self.result.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(self.result)
        lay.addStretch(1)

    def initializePage(self):
        st = self.wiz.state
        if st.is_simulator:
            st.set_connection(SIM_CONN[self.kind])
            self.sim_note.setText("Simulator: Verbindung wurde automatisch hergestellt"
                                  + (" (8,2-Ω-Widerstand)." if self.kind == "known" else "."))
            if self.kind == "known":
                self.r_known.setValue(st.backend.resistor)

    def _measure(self):
        self.btn.setEnabled(False)
        self.result.setText("Messung läuft …")
        eng = self.wiz.engine()
        self.wiz.state.run(lambda: eng.record(eng.sweep), self._done, self._fail, text="Geräte-Check läuft …")

    def _done(self, recs):
        self.btn.setEnabled(True)
        self.wiz.recs[self.kind] = recs
        lv = channel_levels(recs, self.wiz.engine().sweep)
        a = appearance().current
        txt = [f"✔ gemessen – Eingang 1: {lv[0]:.1f} dBFS, Eingang 2: {lv[1]:.1f} dBFS"]
        peak = float(np.max(np.abs(recs)))
        if peak > 0.98:
            txt.append(f"<span style='color:{a.err}'>Übersteuerung – Pegel in der Seitenleiste verringern "
                       "und wiederholen.</span>")
        if self.kind == "short" and "open" in self.wiz.recs:
            asg = detect_assignment(channel_levels(self.wiz.recs["open"], self.wiz.engine().sweep), lv)
            self.wiz.assignment = asg
            col = a.ok if asg.confident else a.warn
            txt.append(f"<span style='color:{col}'>{asg.message}</span>")
        self.result.setText("<br>".join(txt))
        self.completeChanged.emit()

    def _fail(self, err):
        self.btn.setEnabled(True)
        self.result.setText(f"<span style='color:{appearance().current.err}'>Fehler: {err}</span>")

    def isComplete(self):
        return self.kind == "known" or self.kind in self.wiz.recs


class ResultPage(QtWidgets.QWizardPage):
    def __init__(self, wiz: "DeviceCheckWizard"):
        super().__init__()
        self.wiz = wiz
        self.setTitle("Ergebnis")
        lay = QtWidgets.QVBoxLayout(self)
        self.text = QtWidgets.QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(QtCore.Qt.RichText)
        self.text.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(self.text)
        self.apply = QtWidgets.QCheckBox("Ergebnis übernehmen (Kanalzuordnung, Referenz- und Kalibrierwiderstand)")
        self.apply.setChecked(True)
        lay.addWidget(self.apply)
        lay.addStretch(1)

    def initializePage(self):
        w = self.wiz
        a = appearance().current
        lines, report = [], []
        asg = w.assignment
        if asg is None:
            lines.append("Kanalzuordnung: nicht bestimmt.")
        else:
            lines.append(asg.message)
        report.append(lines[-1])
        w.estimate = None
        if asg is not None and asg.meas is not None and {"open", "short", "cal"} <= set(w.recs):
            if asg.single_channel:
                ch = ChannelConfig(mode="single_channel", ref_channel=0, meas_channel=0,
                                   r_nominal=w.state.engine.channels.r_nominal)
            else:
                ch = ChannelConfig(ref_channel=asg.ref, meas_channel=asg.meas,
                                   r_nominal=w.state.engine.channels.r_nominal)
            w.channels = ch
            known_page = w.page(w.PAGE_KNOWN)
            recs = {k: v for k, v in w.recs.items() if k in ("open", "short", "cal", "known")}
            try:
                est = estimate_bridge(w.engine().sweep, ch, recs, ch.r_nominal,
                                      known_page.r_known.value() if "known" in recs else None)
                w.estimate = est
                lines += est.lines
                report += est.lines
            except Exception as e:      # noqa: BLE001
                lines.append(f"<span style='color:{a.err}'>Auswertung fehlgeschlagen: {e}</span>")
                log.exception("Geräte-Check-Auswertung")
            q_open = None
            try:
                from ..measurement import transfer_from_recordings
                q_open = transfer_from_recordings(w.recs["open"], w.engine().sweep, ch).quality
            except Exception:           # noqa: BLE001
                pass
            if q_open:
                g, msgs = grade(q_open, "open")
                lines.append(f"Signalqualität (Leerlauf): Latenz {q_open.get('latency_ms')} ms, "
                             f"Rauschen {q_open.get('noise_db') or float('nan'):.0f} dBFS"
                             + ("" if not msgs else " – " + msgs[0]))
                report.append(lines[-1])
        lines.append("<br>Nächster Schritt: <b>Kalibrier-Assistent</b> (Leerlauf, Kurzschluss, "
                     "Kalibrierwiderstand) mit den übernommenen Werten.")
        self.text.setText("<br>".join(lines))
        w.report = "\n".join(report)


class DeviceCheckWizard(QtWidgets.QWizard):
    PAGE_INTRO, PAGE_OPEN, PAGE_SHORT, PAGE_CAL, PAGE_KNOWN, PAGE_RESULT = range(6)

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.recs: dict[str, np.ndarray] = {}
        self.assignment = None
        self.estimate = None
        self.channels: ChannelConfig | None = None
        self.report = ""
        self.setWindowTitle("Geräte-Check")
        self.setWizardStyle(QtWidgets.QWizard.ModernStyle)
        self.setMinimumSize(600, 480)
        self.setPage(self.PAGE_INTRO, IntroPage(self))
        for pid, k in ((self.PAGE_OPEN, "open"), (self.PAGE_SHORT, "short"), (self.PAGE_CAL, "cal"),
                       (self.PAGE_KNOWN, "known")):
            self.setPage(pid, StepPage(self, k))
        self.setPage(self.PAGE_RESULT, ResultPage(self))
        self.setButtonText(QtWidgets.QWizard.NextButton, "Weiter >")
        self.setButtonText(QtWidgets.QWizard.BackButton, "< Zurück")
        self.setButtonText(QtWidgets.QWizard.FinishButton, "Fertigstellen")
        self.setButtonText(QtWidgets.QWizard.CancelButton, "Abbrechen")
        self._engine = None

    def engine(self) -> MeasurementEngine:
        """Eigene Engine mit kurzem Sweep (Kalibrierung und Einstellungen bleiben unberührt)."""
        if self._engine is None:
            main = self.state.engine
            self._engine = MeasurementEngine(main.backend, main.sweep.with_(sweep_exp=16, averages=1),
                                             main.channels)
        return self._engine

    def done(self, result):
        self.state.backend.stop()
        if self.state.is_simulator:
            self.state.set_connection("driver")
        super().done(result)
