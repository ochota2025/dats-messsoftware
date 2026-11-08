"""End-to-End-Tests gegen den Simulator: Kalibrierung, Impedanz, T/S, LCR, Export."""
import numpy as np
import pytest

from datsmess.analysis import lcr
from datsmess.analysis.ts import VasMethod, derive_ts, fit_driver
from datsmess.audio.simulator import SimulatorBackend
from datsmess.dsp.calibration import Calibration
from datsmess.dsp.sweep import SweepConfig
from datsmess.io.formats import export_impedance, import_impedance
from datsmess.measurement import ChannelConfig, MeasurementEngine


def calibrate(engine, sim, steps=("open", "short", "cal")):
    H = {}
    for s in steps:
        sim.set_connection(s)
        H[s] = engine.measure_H().H
    engine.calibration = Calibration(engine.sweep, sim.hw.r_cal, engine.sweep.frequencies(), H["cal"],
                                     H.get("open"), H.get("short"))


@pytest.fixture(scope="module")
def setup():
    sim = SimulatorBackend(seed=3)
    eng = MeasurementEngine(sim, SweepConfig(fs=48000, sweep_exp=17))
    calibrate(eng, sim)
    return eng, sim


def band(f, Z, lo, hi):
    m = (f >= lo) & (f <= hi)
    return f[m], Z[m]


def test_grid_has_over_30000_points():
    assert len(SweepConfig().frequencies()) > 30000


def test_resistor_accuracy(setup):
    eng, sim = setup
    sim.set_connection("resistor")
    m, _ = eng.measure_impedance()
    f, Z = m.resampled(200, octave_frac=6, f_lo=10, f_hi=18000)
    true = sim.dut_impedance(f)
    assert np.max(np.abs(Z - true) / np.abs(true)) < 0.002     # systematischer Fehler < 0,2 %


def test_calibration_compensates_leads(setup):
    eng, sim = setup
    sim.set_connection("short")
    m, _ = eng.measure_impedance()
    f, Z = band(m.f, m.Z, 20, 1000)
    assert abs(np.median(Z.real)) < 0.005          # Kabelwiderstand (0,12 Ω) herausgerechnet
    assert eng.calibration.lead_resistance() == pytest.approx(sim.hw.lead_r, abs=0.01)


def test_load_only_calibration_still_reasonable():
    sim = SimulatorBackend(seed=5)
    eng = MeasurementEngine(sim)
    calibrate(eng, sim, steps=("cal",))
    sim.set_connection("resistor")
    m, _ = eng.measure_impedance()
    f, Z = band(m.f, m.Z, 50, 5000)
    # ohne Kurzschluss-Messung bleibt der Kabelwiderstand (0,12 Ω) im Ergebnis
    assert np.median(Z.real) == pytest.approx(sim.resistor + sim.hw.lead_r, rel=0.01)


def test_ts_parameters_added_mass(setup):
    eng, sim = setup
    d = sim.driver
    sim.set_connection("driver")
    free, _ = eng.measure_impedance()
    sim.set_connection("driver_mass")
    mass, _ = eng.measure_impedance()
    fit1 = fit_driver(free.f, free.Z)
    fit2 = fit_driver(mass.f, mass.Z, re_dc=fit1.Re, fix_re=True)
    assert fit1.fs == pytest.approx(d.fs, rel=0.005)
    assert fit1.Re == pytest.approx(d.Re, rel=0.01)
    assert fit1.Qms == pytest.approx(d.Qms, rel=0.02)
    assert fit1.Qes == pytest.approx(d.Qes, rel=0.02)
    assert fit1.Ki == pytest.approx(d.Ki, rel=0.1)
    assert fit1.Xi == pytest.approx(d.Xi, abs=0.02)
    assert fit1.rms_error < 0.01
    ts = derive_ts(fit1, VasMethod.ADDED_MASS, sd=d.Sd, second=fit2, added_mass=sim.added_mass)
    assert ts.Mms == pytest.approx(d.Mms, rel=0.03)
    assert ts.Vas == pytest.approx(d.Vas, rel=0.03)
    assert ts.Bl == pytest.approx(d.Bl, rel=0.02)


def test_ts_parameters_test_box(setup):
    eng, sim = setup
    d = sim.driver
    sim.set_connection("driver")
    free, _ = eng.measure_impedance()
    sim.set_connection("driver_box")
    box, _ = eng.measure_impedance()
    fit1 = fit_driver(free.f, free.Z)
    fit2 = fit_driver(box.f, box.Z, re_dc=fit1.Re, fix_re=True)
    ts = derive_ts(fit1, VasMethod.TEST_BOX, sd=d.Sd, second=fit2, vb=sim.box_volume)
    assert ts.Vas == pytest.approx(d.Vas, rel=0.04)


def test_ts_specified_methods(setup):
    eng, sim = setup
    d = sim.driver
    sim.set_connection("driver")
    free, _ = eng.measure_impedance()
    fit1 = fit_driver(free.f, free.Z)
    ref = derive_ts(fit1, VasMethod.ADDED_MASS, sd=d.Sd,
                    second=fit_driver(*_mass(eng, sim), re_dc=fit1.Re, fix_re=True), added_mass=sim.added_mass)
    by_mmd = derive_ts(fit1, VasMethod.SPECIFIED_MMD, sd=d.Sd, mmd=ref.Mmd)
    assert by_mmd.Vas == pytest.approx(ref.Vas, rel=1e-6)
    by_spl = derive_ts(fit1, VasMethod.SPECIFIED_SPL, sd=d.Sd, spl=ref.SPL_1W)
    assert by_spl.Vas == pytest.approx(ref.Vas, rel=1e-6)
    by_spl283 = derive_ts(fit1, VasMethod.SPECIFIED_SPL, sd=d.Sd, spl=ref.SPL_283, spl_ref="2.83V")
    assert by_spl283.Vas == pytest.approx(ref.Vas, rel=1e-6)


def _mass(eng, sim):
    sim.set_connection("driver_mass")
    m, _ = eng.measure_impedance()
    return m.f, m.Z


@pytest.mark.parametrize("conn,kind,key,attr,tol", [
    ("capacitor", "C", "C", "capacitor", 0.01),
    ("inductor", "L", "L", "inductor", 0.01),
    ("inductor", "L", "DCR", "inductor_dcr", 0.02),
    ("resistor", "R", "R", "resistor", 0.002),
])
def test_lcr(setup, conn, kind, key, attr, tol):
    eng, sim = setup
    sim.set_connection(conn)
    m, _ = eng.measure_impedance()
    r = lcr.analyze(m.f, m.Z)
    assert r.kind == kind
    assert r.raw[key] == pytest.approx(getattr(sim, attr), rel=tol)


def test_capacitor_esr(setup):
    eng, sim = setup
    sim.set_connection("capacitor")
    m, _ = eng.measure_impedance()
    r = lcr.analyze(m.f, m.Z, kind="C", f_test=1000)
    assert r.raw["ESR"] == pytest.approx(sim.cap_esr, abs=0.02)


def test_single_channel_mode():
    sim = SimulatorBackend(seed=7)
    eng = MeasurementEngine(sim, channels=ChannelConfig(mode="single_channel"))
    calibrate(eng, sim)
    sim.set_connection("resistor")
    m, _ = eng.measure_impedance()
    f, Z = band(m.f, m.Z, 20, 10000)
    assert np.median(Z.real) == pytest.approx(sim.resistor, rel=0.005)


@pytest.mark.parametrize("ext", [".zma", ".frd", ".txt", ".csv"])
def test_export_import_roundtrip(tmp_path, ext):
    f = np.geomspace(1, 20000, 500)
    Z = 6 + 1j * f * 1e-4 + 30 / (1 + 1j * 4 * (f / 40 - 40 / f))
    p = tmp_path / f"x{ext}"
    export_impedance(p, f, Z, header=["Test"])
    f2, Z2 = import_impedance(p)
    assert np.allclose(f2, f, rtol=1e-6)
    assert np.allclose(Z2, Z, rtol=1e-4, atol=1e-5)


def test_calibration_save_load(tmp_path, setup):
    eng, _ = setup
    p = tmp_path / "cal.npz"
    eng.calibration.save(p)
    c = Calibration.load(p)
    assert c.is_compatible(eng.sweep)
    assert np.allclose(c.r_s, eng.calibration.r_s)
