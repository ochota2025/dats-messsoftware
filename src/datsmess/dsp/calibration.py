"""Kalibrierung (Leerlauf / Kurzschluss / Kalibrierwiderstand).

Unabhängig von der genauen internen Beschaltung des Interfaces gilt für jede
lineare Messbrücke, dass die gemessene Spannungsübertragung H = U_mess/U_ref
eine gebrochen-lineare (Möbius-) Funktion der Impedanz am Messkabelende ist.
Wir parametrieren diese als

    Z = R_s · ( h(H) − h(H_short) ),    h(H) = H / (k − H)

mit drei komplexen, frequenzabhängigen Größen:

* k        – Kanalverhältnis bei offenen Klemmen          (Leerlauf-Messung)
* H_short  – Restimpedanz von Kabel und Klemmen           (Kurzschluss-Messung)
* R_s      – effektiver Referenzwiderstand                (Kalibrierwiderstand)

Ohne Kurzschluss-Messung wird h_short = 0 angenommen. Ohne Leerlauf-Messung ist
das System unterbestimmt; dann wird der Referenzwiderstand als bekannt
(Nennwert ``r_nominal``) vorausgesetzt und stattdessen das Kanalverhältnis k aus
der Widerstandsmessung bestimmt (Ein-Punkt-Kalibrierung wie beim Original).
Ungleiche Verstärkung der beiden Eingangskanäle wird so trotzdem kompensiert.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .sweep import SweepConfig


def nominal_impedance(H: np.ndarray, r_nominal: float) -> np.ndarray:
    """Unkalibrierte Schätzung für eine einfache Spannungsteiler-Brücke."""
    return r_nominal * H / (1.0 - H)


@dataclass
class Calibration:
    sweep: SweepConfig
    r_cal: float
    f: np.ndarray
    H_load: np.ndarray
    H_open: np.ndarray | None = None
    H_short: np.ndarray | None = None
    r_nominal: float = 100.0
    device: str = ""
    created: str = field(default_factory=lambda: _dt.datetime.now().isoformat(timespec="seconds"))
    # optional: Rohaufnahmen je Schritt ("open"/"short"/"cal") + Kanalzuordnung – erlauben eine
    # kompakte, bitgenaue Archivierung im Projekt (H wird daraus neu berechnet)
    recordings: dict | None = field(default=None, repr=False)
    channels: dict | None = None

    # -- Korrektur ----------------------------------------------------------
    @property
    def k(self) -> np.ndarray:
        if self.H_open is not None:
            return self.H_open
        return self.H_load * (self.r_cal + self.r_nominal) / self.r_cal

    def _h(self, H: np.ndarray) -> np.ndarray:
        return H / (self.k - H)

    @property
    def _h_short(self) -> np.ndarray:
        return self._h(self.H_short) if self.H_short is not None else np.zeros_like(self.H_load)

    @property
    def r_s(self) -> np.ndarray:
        """Effektiver (komplexer) Referenzwiderstand je Frequenz."""
        return self.r_cal / (self._h(self.H_load) - self._h_short)

    def correct(self, H: np.ndarray) -> np.ndarray:
        return self.r_s * (self._h(H) - self._h_short)

    @property
    def steps(self) -> list[str]:
        s = []
        if self.H_open is not None:
            s.append("Leerlauf")
        if self.H_short is not None:
            s.append("Kurzschluss")
        s.append("Referenzwiderstand")
        return s

    def is_compatible(self, sweep: SweepConfig) -> bool:
        return self.sweep.grid_key() == sweep.grid_key()

    def lead_resistance(self, f_lo: float = 20.0, f_hi: float = 200.0) -> float | None:
        """Mittlerer Kabel-/Übergangswiderstand aus der Kurzschluss-Messung."""
        if self.H_short is None:
            return None
        z = self.r_s * self._h(self.H_short)
        m = (self.f >= f_lo) & (self.f <= f_hi)
        return float(np.median(z[m].real)) if m.any() else None

    @property
    def id(self) -> str:
        """Eindeutige Kennung (Inhalt-Hash) – verknüpft Messungen mit ihrer Kalibrierung."""
        h = hashlib.sha1(self.created.encode())
        h.update(np.float64(self.r_cal).tobytes())
        for a in (self.H_load, self.H_open, self.H_short):
            if a is not None:
                h.update(np.ascontiguousarray(a).tobytes())
        return h.hexdigest()[:12]

    # -- Persistenz ---------------------------------------------------------
    def save(self, path) -> None:
        """Speichert als .npz; ``path`` darf auch ein Dateiobjekt sein."""
        if not hasattr(path, "write"):
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as fh:
                self.save(fh)
            return
        meta = {"sweep": self.sweep.to_dict(), "r_cal": self.r_cal, "r_nominal": self.r_nominal,
                "device": self.device, "created": self.created}
        arrays = {"f": self.f, "H_load": self.H_load}
        if self.H_open is not None:
            arrays["H_open"] = self.H_open
        if self.H_short is not None:
            arrays["H_short"] = self.H_short
        np.savez_compressed(path, meta=np.array(json.dumps(meta)), **arrays)

    @classmethod
    def load(cls, path) -> "Calibration":
        with np.load(path, allow_pickle=False) as d:
            meta = json.loads(str(d["meta"]))
            return cls(sweep=SweepConfig.from_dict(meta["sweep"]), r_cal=float(meta["r_cal"]),
                       f=d["f"], H_load=d["H_load"],
                       H_open=d["H_open"] if "H_open" in d else None,
                       H_short=d["H_short"] if "H_short" in d else None,
                       r_nominal=float(meta.get("r_nominal", 100.0)),
                       device=meta.get("device", ""), created=meta.get("created", ""))
