"""Thiele/Small-Parameter (FN-02, FN-03) und Wright-Modell (FA-02).

Elektrisches Ersatzmodell des Treibers::

    Z(f) = Re + Kr·ω^Xr + j·Ki·ω^Xi  +  Res / (1 + j·Qms·(f/fs − fs/f))

Der erste Teil ist die Schwingspule nach Wright (semi-induktiv), der zweite die
mechanische Resonanz als Parallelschwingkreis. Die Parameter werden per
nichtlinearer Ausgleichsrechnung an die gemessene komplexe Impedanz angepasst;
Startwerte liefert die klassische Methode (Zmax, √(Zmax·Re)-Schnittpunkte).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from scipy.optimize import least_squares

from ..dsp.transfer import resample_log, smooth_octave


@dataclass(frozen=True)
class Air:
    rho: float = 1.204    # kg/m³ (20 °C)
    c: float = 343.2      # m/s

    @property
    def spl_constant(self) -> float:
        """SPL bei 1 W / 1 m in den Halbraum für η0 = 1 (≈ 112,2 dB)."""
        return 10 * np.log10(self.rho * self.c / (2 * np.pi * (2e-5) ** 2))


def air_load_mass(sd: float, air: Air = Air()) -> float:
    """Mitbewegte Luftmasse (beidseitig, Kolben im unendlichen Schallwand-Modell)."""
    a = np.sqrt(sd / np.pi)
    return 16.0 / 3.0 * air.rho * a ** 3


# --------------------------------------------------------------------------
# Modell und Anpassung
# --------------------------------------------------------------------------

def driver_model(f, Re, Res, fs, Qms, Kr, Xr, Ki, Xi):
    f = np.asarray(f, float)
    w = 2 * np.pi * f
    ze = Re + Kr * w ** Xr + 1j * Ki * w ** Xi
    zm = Res / (1 + 1j * Qms * (f / fs - fs / f))
    return ze + zm


PARAM_NAMES = ("Re", "Res", "fs", "Qms", "Kr", "Xr", "Ki", "Xi")


@dataclass
class ImpedanceFit:
    Re: float
    Res: float
    fs: float
    Qms: float
    Kr: float
    Xr: float
    Ki: float
    Xi: float
    rms_error: float = float("nan")      # relativer RMS-Fehler (Anteil, 0.01 = 1 %)
    f_range: tuple[float, float] = (0.0, 0.0)
    classic: dict = field(default_factory=dict)

    @property
    def Qes(self) -> float:
        return self.Qms * self.Re / self.Res

    @property
    def Qts(self) -> float:
        return self.Qms * self.Qes / (self.Qms + self.Qes)

    @property
    def Zmax(self) -> float:
        return float(abs(self.model(np.array([self.fs]))[0]))

    def le_at(self, f: float) -> float:
        w = 2 * np.pi * f
        return self.Ki * w ** self.Xi / w

    def model(self, f) -> np.ndarray:
        return driver_model(f, self.Re, self.Res, self.fs, self.Qms, self.Kr, self.Xr, self.Ki, self.Xi)

    def params(self) -> np.ndarray:
        return np.array([getattr(self, n) for n in PARAM_NAMES])


def _find_resonance(f: np.ndarray, Z: np.ndarray, f_lo: float, f_hi: float) -> float:
    m = (f >= f_lo) & (f <= f_hi)
    fm, zm = f[m], Z[m]
    mag = np.abs(zm)
    ph = np.angle(zm)
    # Kandidaten: Phasen-Nulldurchgang von + nach − (Resonanz)
    idx = np.where((ph[:-1] > 0) & (ph[1:] <= 0))[0]
    if len(idx):
        best = idx[np.argmax(mag[idx])]
        # lineare Interpolation des Nulldurchgangs
        p0, p1 = ph[best], ph[best + 1]
        t = p0 / (p0 - p1) if p0 != p1 else 0.0
        return float(np.exp(np.log(fm[best]) + t * (np.log(fm[best + 1]) - np.log(fm[best]))))
    return float(fm[np.argmax(mag)])


def classic_estimate(f: np.ndarray, Z: np.ndarray, re_dc: float | None = None,
                     f_lo: float = 5.0, f_hi: float = 5000.0) -> dict:
    """Klassische T/S-Bestimmung aus |Z| (Startwerte und Plausibilitätsprüfung)."""
    fs = _find_resonance(f, Z, f_lo, f_hi)
    mag = np.abs(Z)
    if re_dc is None:
        band = (f >= max(f_lo, fs / 10)) & (f <= fs * 20)
        re_dc = float(np.min(Z.real[band]))
    zmax = float(np.interp(fs, f, mag))
    r0 = zmax / re_dc
    z12 = np.sqrt(zmax * re_dc)
    below = (f < fs) & (f >= fs / 10)
    above = (f > fs) & (f <= fs * 10)
    try:
        fb, mb = f[below], mag[below]
        i1 = np.where(mb < z12)[0][-1]
        f1 = float(np.interp(z12, [mb[i1], mb[i1 + 1]], [fb[i1], fb[i1 + 1]]))
        fa, ma = f[above], mag[above]
        i2 = np.where(ma < z12)[0][0]
        f2 = float(np.interp(z12, [ma[i2], ma[i2 - 1]], [fa[i2], fa[i2 - 1]]))
        qms = fs * np.sqrt(r0) / (f2 - f1)
    except IndexError:
        f1 = f2 = float("nan")
        qms = 5.0
    qes = qms / max(r0 - 1, 1e-6)
    return {"fs": fs, "Re": re_dc, "Zmax": zmax, "r0": r0, "f1": f1, "f2": f2,
            "Qms": float(qms), "Qes": float(qes), "Res": zmax - re_dc}


def fit_driver(f: np.ndarray, Z: np.ndarray, *, re_dc: float | None = None, fix_re: bool = False,
               f_lo: float | None = None, f_hi: float = 20000.0, n_points: int = 600) -> ImpedanceFit:
    """Passt das Treibermodell an eine gemessene Impedanzkurve an."""
    f = np.asarray(f, float)
    Z = np.asarray(Z, complex)
    Zs = smooth_octave(f, Z, 96)
    cl = classic_estimate(f, Zs, re_dc)
    fs0 = cl["fs"]
    lo = max(f_lo or fs0 / 8.0, f[0], 2.0)
    hi = min(f_hi, f[-1])
    fr, zr = resample_log(f, Z, lo, hi, n_points, octave_frac=96)

    re0 = cl["Re"]
    w_h = 2 * np.pi * fr[-1]
    zmot_h = cl["Res"] / (1 + 1j * cl["Qms"] * (fr[-1] / fs0 - fs0 / fr[-1]))
    ze_h = zr[-1] - zmot_h
    ki0 = max(ze_h.imag, 1e-3) / w_h ** 0.7
    kr0 = max(ze_h.real - re0, 1e-4) / w_h ** 0.7
    x0 = np.array([re0, max(cl["Res"], 1e-3), fs0, np.clip(cl["Qms"], 0.5, 50), kr0, 0.7, ki0, 0.7])
    lb = np.array([0.2 * re0, 1e-4, 0.5 * fs0, 0.2, 0.0, 0.0, 0.0, 0.0])
    ub = np.array([2.0 * re0, 1e5, 2.0 * fs0, 200.0, np.inf, 1.5, np.inf, 1.5])
    if fix_re:
        lb[0], ub[0] = re0 * (1 - 1e-9), re0 * (1 + 1e-9)
    x0 = np.clip(x0, lb + 1e-12, ub - 1e-12)
    weight = 1.0 / np.abs(zr)

    def resid(p):
        d = (driver_model(fr, *p) - zr) * weight
        return np.concatenate([d.real, d.imag])

    res = least_squares(resid, x0, bounds=(lb, ub), x_scale="jac", max_nfev=4000)
    rms = float(np.sqrt(np.mean(np.abs((driver_model(fr, *res.x) - zr) / zr) ** 2)))
    fit = ImpedanceFit(*[float(v) for v in res.x], rms_error=rms, f_range=(float(lo), float(hi)), classic=cl)
    return fit


def looks_like_driver(f: np.ndarray, Z: np.ndarray, f_lo: float = 3.0, f_hi: float = 5000.0) -> bool:
    """Grobe Prüfung auf eine Lautsprecherresonanz: Phasendurchgang von + nach − bei einer
    Impedanz, die deutlich (≥ 1,5×) über dem kleinsten Realteil liegt. Widerstände, Kondensatoren,
    Spulen und offene/kurze Klemmen fallen damit heraus."""
    f = np.asarray(f, float)
    Z = np.asarray(Z, complex)
    m = (f >= f_lo) & (f <= f_hi)
    if m.sum() < 20:
        return False
    fm, zm = f[m], smooth_octave(f, Z, 24)[m]
    re_min = float(np.min(zm.real))
    if not np.isfinite(re_min) or re_min <= 0:
        return False
    ph = np.angle(zm)
    idx = np.where((ph[:-1] > 0) & (ph[1:] <= 0))[0]
    return bool(np.any(np.abs(zm[idx]) > 1.5 * re_min))


def quick_parameters(f: np.ndarray, Z: np.ndarray, max_error: float = 0.15) -> ImpedanceFit | None:
    """Kennwerte, die schon aus einer einzelnen Freiluftmessung feststehen (fs, Re, Q, Le …).
    ``None``, wenn die Kurve nicht nach einem Lautsprecher aussieht."""
    if not looks_like_driver(f, Z):
        return None
    try:
        fit = fit_driver(f, Z)
    except (ValueError, RuntimeError, FloatingPointError):
        return None
    return fit if fit.rms_error <= max_error else None


# --------------------------------------------------------------------------
# Vas-Methoden und Ableitung aller Parameter
# --------------------------------------------------------------------------

class VasMethod(str, Enum):
    NONE = "none"
    TEST_BOX = "test_box"
    ADDED_MASS = "added_mass"
    SPECIFIED_SPL = "specified_spl"
    SPECIFIED_MMD = "specified_mmd"


VAS_METHOD_LABELS = {
    VasMethod.ADDED_MASS: "Zusatzmasse (Added Mass)",
    VasMethod.TEST_BOX: "Testgehäuse (Test Box)",
    VasMethod.SPECIFIED_MMD: "Bekannte Membranmasse Mmd",
    VasMethod.SPECIFIED_SPL: "Bekannter Kennschalldruck",
    VasMethod.NONE: "Nur elektrische Parameter",
}

NEEDS_SECOND_MEASUREMENT = {VasMethod.ADDED_MASS, VasMethod.TEST_BOX}


@dataclass
class TSParameters:
    method: VasMethod
    fit: ImpedanceFit
    second_fit: ImpedanceFit | None
    Sd: float | None
    Vas: float | None = None
    Mms: float | None = None
    Mmd: float | None = None
    Cms: float | None = None
    Rms: float | None = None
    Bl: float | None = None
    eta0: float | None = None
    SPL_1W: float | None = None
    SPL_283: float | None = None
    Vd: float | None = None
    warnings: list[str] = field(default_factory=list)

    def rows(self) -> list[tuple[str, str, float | None, str, str]]:
        """(Schlüssel, Bezeichnung, Wert in Anzeigeeinheit, Einheit, Format)."""
        f = self.fit

        def s(v, k):
            return None if v is None else v * k

        rows = [
            ("fs", "Resonanzfrequenz f_s", f.fs, "Hz", "{:.2f}"),
            ("Re", "Gleichstromwiderstand R_e", f.Re, "Ω", "{:.3f}"),
            ("Qms", "Mechanische Güte Q_ms", f.Qms, "", "{:.3f}"),
            ("Qes", "Elektrische Güte Q_es", f.Qes, "", "{:.3f}"),
            ("Qts", "Gesamtgüte Q_ts", f.Qts, "", "{:.3f}"),
            ("Zmax", "Impedanz bei f_s Z_max", f.Zmax, "Ω", "{:.2f}"),
            ("Res", "Res (mech. Verluste, elektr.)", f.Res, "Ω", "{:.2f}"),
            ("Le1k", "Le @ 1 kHz", f.le_at(1000.0) * 1e3, "mH", "{:.4f}"),
            ("Le10k", "Le @ 10 kHz", f.le_at(10000.0) * 1e3, "mH", "{:.4f}"),
            ("Sd", "Membranfläche S_d", s(self.Sd, 1e4), "cm²", "{:.1f}"),
            ("Vas", "Äquivalentvolumen V_as", s(self.Vas, 1e3), "L", "{:.2f}"),
            ("Mms", "Bewegte Masse M_ms", s(self.Mms, 1e3), "g", "{:.2f}"),
            ("Mmd", "Membranmasse M_md", s(self.Mmd, 1e3), "g", "{:.2f}"),
            ("Cms", "Nachgiebigkeit C_ms", s(self.Cms, 1e3), "mm/N", "{:.4f}"),
            ("Rms", "Mech. Verlustwiderstand R_ms", self.Rms, "kg/s", "{:.3f}"),
            ("Bl", "Kraftfaktor Bl", self.Bl, "T·m", "{:.3f}"),
            ("eta0", "Wirkungsgrad η0", s(self.eta0, 100), "%", "{:.3f}"),
            ("SPL1W", "Kennschalldruck 1 W/1 m", self.SPL_1W, "dB", "{:.1f}"),
            ("SPL283", "Kennschalldruck 2,83 V/1 m", self.SPL_283, "dB", "{:.1f}"),
            ("EBP", "EBP (f_s/Q_es)", f.fs / f.Qes, "", "{:.1f}"),
            ("Vd", "Verdrängungsvolumen V_d", s(self.Vd, 1e6), "cm³", "{:.1f}"),
            ("Kr", "Wright K_r", f.Kr, "Ω·s^Xr", "{:.5g}"),
            ("Xr", "Wright X_r", f.Xr, "", "{:.4f}"),
            ("Ki", "Wright K_i", f.Ki, "Ω·s^Xi", "{:.5g}"),
            ("Xi", "Wright X_i", f.Xi, "", "{:.4f}"),
            ("fit", "Modellabweichung (RMS)", f.rms_error * 100, "%", "{:.2f}"),
        ]
        if self.second_fit is not None:
            rows.insert(5, ("fs2", "f_s Zweitmessung", self.second_fit.fs, "Hz", "{:.2f}"))
            rows.insert(6, ("Qes2", "Q_es Zweitmessung", self.second_fit.Qes, "", "{:.3f}"))
        return rows


def derive_ts(fit: ImpedanceFit, method: VasMethod, *, sd: float | None, second: ImpedanceFit | None = None,
              added_mass: float | None = None, vb: float | None = None, mmd: float | None = None,
              spl: float | None = None, spl_ref: str = "1W", xmax: float | None = None,
              air: Air = Air()) -> TSParameters:
    """Berechnet alle T/S-Parameter. Einheiten: SI (m², kg, m³, m)."""
    p = TSParameters(method=method, fit=fit, second_fit=second, Sd=sd)
    fs, qes, re = fit.fs, fit.Qes, fit.Re
    ws = 2 * np.pi * fs
    rc2 = air.rho * air.c ** 2

    if method == VasMethod.ADDED_MASS:
        if second is None or not added_mass:
            raise ValueError("Zusatzmassen-Methode benötigt Zweitmessung und Zusatzmasse.")
        ratio = (fs / second.fs) ** 2 - 1
        if ratio <= 0:
            raise ValueError("Resonanz mit Zusatzmasse ist nicht niedriger als ohne – Messung prüfen.")
        p.Mms = added_mass / ratio
        p.Cms = 1 / (ws ** 2 * p.Mms)
        if sd:
            p.Vas = rc2 * sd ** 2 * p.Cms
    elif method == VasMethod.TEST_BOX:
        if second is None or not vb:
            raise ValueError("Testgehäuse-Methode benötigt Zweitmessung und Gehäusevolumen.")
        factor = second.fs * second.Qes / (fs * qes) - 1
        if factor <= 0:
            raise ValueError("Resonanz im Testgehäuse ist nicht höher als in Freiluft – Messung prüfen.")
        p.Vas = vb * factor
        if sd:
            p.Cms = p.Vas / (rc2 * sd ** 2)
            p.Mms = 1 / (ws ** 2 * p.Cms)
    elif method == VasMethod.SPECIFIED_MMD:
        if not mmd or not sd:
            raise ValueError("Mmd-Methode benötigt Membranmasse und Membranfläche.")
        p.Mms = mmd + air_load_mass(sd, air)
        p.Cms = 1 / (ws ** 2 * p.Mms)
        p.Vas = rc2 * sd ** 2 * p.Cms
    elif method == VasMethod.SPECIFIED_SPL:
        if spl is None or not sd:
            raise ValueError("SPL-Methode benötigt Kennschalldruck und Membranfläche.")
        spl1w = spl - 10 * np.log10(2.83 ** 2 / re) if spl_ref == "2.83V" else spl
        eta0 = 10 ** ((spl1w - air.spl_constant) / 10)
        p.Vas = eta0 * air.c ** 3 * qes / (4 * np.pi ** 2 * fs ** 3)
        p.Cms = p.Vas / (rc2 * sd ** 2)
        p.Mms = 1 / (ws ** 2 * p.Cms)

    if p.Mms is not None:
        p.Bl = float(np.sqrt(ws * p.Mms * re / qes))
        p.Rms = ws * p.Mms / fit.Qms
        if sd:
            p.Mmd = p.Mms - air_load_mass(sd, air)
            if p.Mmd <= 0:
                p.warnings.append("Berechnete Mmd ≤ 0 – Membranfläche oder Messung prüfen.")
    if p.Vas is not None:
        p.eta0 = 4 * np.pi ** 2 / air.c ** 3 * fs ** 3 * p.Vas / qes
        p.SPL_1W = air.spl_constant + 10 * np.log10(p.eta0)
        p.SPL_283 = p.SPL_1W + 10 * np.log10(2.83 ** 2 / re)
    if sd and xmax:
        p.Vd = sd * xmax
    if fit.rms_error > 0.05:
        p.warnings.append(f"Modell passt nur mäßig ({fit.rms_error * 100:.1f} % RMS) – Messung/Bereich prüfen.")
    return p


def sd_from_diameter(d_m: float) -> float:
    return np.pi * (d_m / 2) ** 2
