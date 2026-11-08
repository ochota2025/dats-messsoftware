"""Audio-Geräte einzeln wählen: Treiber-Schnittstelle, Eingang und Ausgang – wie im Original-Programm.

Die automatische Auswahl (Seitenleiste) fasst Ein- und Ausgang eines Geräts zusammen. Meldet sich
ein Gerät ungewöhnlich, lassen sich beide hier von Hand festlegen. PortAudio verlangt für den
gleichzeitigen Betrieb von Wiedergabe und Aufnahme dieselbe Schnittstelle.
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ..audio.backend import HOSTAPI_RANK, DeviceInfo
from .appearance import appearance
from .de import button_box

API_LABELS = {
    "Windows WASAPI": "WASAPI (empfohlen)",
    "Windows DirectSound": "DirectSound",
    "MME": "MME (älteste Schnittstelle)",
    "Windows WDM-KS": "WDM-KS (Kernel-Streaming)",
    "Core Audio": "Core Audio",
    "ALSA": "ALSA",
}


def check_pair(inp: DeviceInfo, out: DeviceInfo, fs: int) -> str | None:
    """None, wenn der Treiber Ein- und Ausgang mit ``fs`` akzeptiert, sonst die Fehlermeldung."""
    try:
        import sounddevice as sd
    except Exception as e:      # noqa: BLE001
        return f"PortAudio nicht verfügbar: {e}"
    try:
        sd.check_input_settings(device=inp.index, channels=min(2, inp.max_in), samplerate=fs)
        sd.check_output_settings(device=out.index, channels=min(2, out.max_out), samplerate=fs)
    except Exception as e:      # noqa: BLE001
        return str(e)
    return None


class DeviceDialog(QtWidgets.QDialog):
    def __init__(self, devices: list[DeviceInfo], fs: int, current: tuple[int, int] | None = None,
                 parent=None, checker=check_pair):
        super().__init__(parent)
        self.setWindowTitle("Audio-Geräte einzeln wählen")
        self.devices = devices
        self.fs = fs
        self.checker = checker
        lay = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "Normalerweise wählt das Programm Ein- und Ausgang automatisch. Hier lassen sich beide "
            "einzeln festlegen – wie im Original-Programm von Dayton.<br><br>"
            "<b>Beim DATS:</b> Eingang „Mikrofon (…DATS…)“, Ausgang „Lautsprecher (…DATS…)“. "
            "Eingang und Ausgang müssen dieselbe Schnittstelle verwenden. Macht WASAPI Probleme, "
            "DirectSound oder MME versuchen.")
        intro.setWordWrap(True)
        intro.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(intro)

        form = QtWidgets.QFormLayout()
        self.api = QtWidgets.QComboBox()
        apis = sorted({d.hostapi for d in devices}, key=lambda a: (HOSTAPI_RANK.get(a, 5), a))
        for a in apis:
            self.api.addItem(API_LABELS.get(a, a), a)
        self.inp = QtWidgets.QComboBox()
        self.out = QtWidgets.QComboBox()
        for cb in (self.inp, self.out):
            cb.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
            cb.setMinimumWidth(360)
        form.addRow("Schnittstelle:", self.api)
        form.addRow("Eingang (Aufnahme):", self.inp)
        form.addRow("Ausgang (Wiedergabe):", self.out)
        lay.addLayout(form)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(self.status)
        self.bb = button_box(self, "Ok", "Cancel")
        lay.addWidget(self.bb)

        if current is not None:
            cur_in = next((d for d in devices if d.index == current[0]), None)
            if cur_in is not None:
                self.api.setCurrentIndex(max(0, self.api.findData(cur_in.hostapi)))
        self.api.currentIndexChanged.connect(self._fill)
        self.inp.currentIndexChanged.connect(self._check)
        self.out.currentIndexChanged.connect(self._check)
        self._fill()
        if current is not None:
            for cb, idx in ((self.inp, current[0]), (self.out, current[1])):
                i = cb.findData(idx)
                if i >= 0:
                    cb.setCurrentIndex(i)
        self._check()

    def _fill(self, *_):
        api = self.api.currentData()
        for cb, attr in ((self.inp, "max_in"), (self.out, "max_out")):
            cb.blockSignals(True)
            cb.clear()
            for d in self.devices:
                n = getattr(d, attr)
                if d.hostapi == api and n >= 1:
                    cb.addItem(f"{'★ ' if d.looks_like_dats else ''}{d.name} – {n} Kanäle", d.index)
            dats = next((i for i in range(cb.count()) if cb.itemText(i).startswith("★")), 0)
            cb.setCurrentIndex(dats)
            cb.blockSignals(False)
        self._check()

    def _device(self, cb) -> DeviceInfo | None:
        idx = cb.currentData()
        return next((d for d in self.devices if d.index == idx), None)

    def selection(self) -> tuple[DeviceInfo, DeviceInfo] | None:
        i, o = self._device(self.inp), self._device(self.out)
        return (i, o) if i is not None and o is not None else None

    def _check(self, *_):
        a = appearance().current
        sel = self.selection()
        ok_btn = self.bb.button(QtWidgets.QDialogButtonBox.Ok)
        if sel is None:
            self.status.setText(f"<span style='color:{a.err}'>Diese Schnittstelle hat keinen passenden "
                                "Eingang oder Ausgang.</span>")
            ok_btn.setEnabled(False)
            return
        inp, out = sel
        err = self.checker(inp, out, self.fs)
        notes = []
        if inp.max_in < 2:
            notes.append("Der Eingang hat nur einen Kanal – Messprinzip „1 Kanal“ wählen.")
        if err is None:
            self.status.setText(f"<span style='color:{a.ok}'>✔ Der Treiber akzeptiert diese Kombination mit "
                                f"{self.fs / 1000:g} kHz.</span>" + "".join(f"<br>{n}" for n in notes))
        else:
            self.status.setText(f"<span style='color:{a.warn}'>Der Treiber meldet ein Problem mit "
                                f"{self.fs / 1000:g} kHz: {err}</span><br>Andere Abtastrate oder Schnittstelle "
                                "versuchen. Übernehmen ist trotzdem möglich." + "".join(f"<br>{n}" for n in notes))
        ok_btn.setEnabled(True)
