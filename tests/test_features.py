"""Tests für Version 0.2: Qualitäts-Ampel, Geräte-Check, Klirr/Rub & Buzz, Paarvergleich,
Impedanzkorrektur, Fehlerbericht, Update-Vergleich, Simulator-Dauerbetrieb."""
import numpy as np
import pytest

from datsmess import diagnostics, updates
from datsmess.analysis import correction as corr
from datsmess.analysis import matching
from datsmess.analysis.quality import grade
from datsmess.analysis.setup_check import channel_levels, detect_assignment, estimate_bridge
from datsmess.analysis.ts import fit_driver, quick_parameters
from datsmess.audio.simulator import SimulatorBackend
from datsmess.dsp.distortion import analyze, rub_buzz_verdict
from datsmess.dsp.generator import generate
from datsmess.dsp.sweep import SweepConfig, make_stimulus
from datsmess.measurement import ChannelConfig, MeasurementEngine


@pytest.fixture()
def eng():
    sim = SimulatorBackend(seed=5)
    return MeasurementEngine(sim), sim


# ---- Messqualität -------------------------------------------------------------

@pytest.mark.parametrize("level,conn,context,expected", [
    (-10, "driver", "dut", "ok"),
    (-40, "driver", "dut", "warn"),          # zu wenig Pegel
    (0, "driver", "dut", "bad"),             # Übersteuerung
    (-10, "short", "short", "ok"),           # stiller Messkanal ist beim Kurzschluss normal
])
def test_quality_grades(eng, level, conn, context, expected):
    e, sim = eng
    sim.set_connection(conn)
    e.sweep = e.sweep.with_(level_dbfs=level, sweep_exp=16)
    q = e.measure_H().quality
    assert q["latency_ms"] == pytest.approx(1000 * sim.hw.latency / e.sweep.fs, abs=0.1)
    assert grade(q, context)[0] == expected


def test_quality_detects_swapped_channels(eng):
    e, sim = eng
    sim.set_connection("driver")
    e.channels = ChannelConfig(ref_channel=1, meas_channel=0)
    g, msgs = grade(e.measure_H().quality)
    assert g == "warn" and any("vertauscht" in m for m in msgs)


def test_quality_detects_hum(eng):
    e, sim = eng
    sim.set_connection("driver")
    rec = e.record(e.sweep)
    t = np.arange(rec.shape[1]) / e.sweep.fs
    rec = rec + (3e-3 * np.sin(2 * np.pi * 50 * t))[None, :, None]
    from datsmess.measurement import transfer_from_recordings
    q = transfer_from_recordings(rec, e.sweep, e.channels).quality
    assert q["hum"] and q["hum"]["hz"] == 50


# ---- Geräte-Check ------------------------------------------------------------------

@pytest.mark.parametrize("swapped", [False, True])
def test_device_check(eng, swapped):
    e, sim = eng
    e.sweep = e.sweep.with_(sweep_exp=16)
    recs = {}
    for k, c in (("open", "open"), ("short", "short"), ("cal", "cal"), ("known", "resistor")):
        sim.set_connection(c)
        r = e.record(e.sweep)
        recs[k] = r[:, :, ::-1].copy() if swapped else r
    asg = detect_assignment(channel_levels(recs["open"], e.sweep), channel_levels(recs["short"], e.sweep))
    assert asg.confident and asg.swap == swapped
    est = estimate_bridge(e.sweep, ChannelConfig(ref_channel=asg.ref, meas_channel=asg.meas), recs, 100.0,
                          sim.resistor)
    assert est.r_cal == pytest.approx(sim.hw.r_cal, rel=0.01)
    assert est.r_ref == pytest.approx(sim.hw.r_series, rel=0.02)


def test_device_check_single_channel():
    asg = detect_assignment([-14.0, -240.0], [-14.0, -240.0])
    assert asg.single_channel


# ---- Klirr / Rub & Buzz ------------------------------------------------------------

def test_distortion_matches_static_nonlinearity():
    cfg = SweepConfig()
    s = make_stimulus(cfg)
    a = 10 ** (cfg.level_dbfs / 20)
    lat = 200
    delay = lambda x: np.concatenate([np.zeros(lat), x[:-lat]])   # noqa: E731
    meas = 0.5 * s + 0.1 * (0.5 * s) ** 2 / 0.5                     # k2 = 0,1·A/2
    rec = np.stack([np.column_stack([delay(0.98 * s), delay(meas)])])
    r = analyze(rec, cfg)
    assert r.at(r.h2, 200) == pytest.approx(0.1 * a / 2, rel=0.05)
    assert np.nanmax(r.thd_ref) < 1e-4 if np.isfinite(r.thd_ref).any() else True


def test_rub_and_buzz_detected_only_on_rubbing_driver(eng):
    e, sim = eng
    sim.distortion = True
    e.sweep = e.sweep.with_(level_dbfs=-6)
    verdicts = {}
    for conn in ("driver", "driver_rub", "resistor"):
        sim.set_connection(conn)
        m, _ = e.measure_impedance()
        verdicts[conn] = rub_buzz_verdict(analyze(m.recordings, e.sweep))[0]
    assert verdicts == {"driver": "ok", "driver_rub": "warn", "resistor": "ok"}


def test_distortion_does_not_spoil_ts(eng):
    e, sim = eng
    sim.distortion = True
    sim.set_connection("driver")
    m, _ = e.measure_impedance()
    fit = quick_parameters(m.f, m.Z)
    assert fit is not None and fit.fs == pytest.approx(sim.driver.fs, rel=0.03)


# ---- Pegelreihe / Exemplare ------------------------------------------------------

def test_level_dependence_and_samples(eng):
    e, sim = eng
    sim.level_dependent = True
    sim.set_connection("driver")
    fs = []
    for lvl in (-30, -6):
        e.sweep = e.sweep.with_(level_dbfs=lvl, sweep_exp=16)
        m, _ = e.measure_impedance()
        fs.append(fit_driver(m.f, m.Z).fs)
    assert fs[1] < fs[0] * 0.98                     # lauter → tiefere Resonanz
    assert sim.sample_driver(1) == sim.driver
    assert sim.sample_driver(3).fs != sim.driver.fs


# ---- Paarvergleich ---------------------------------------------------------------

def test_best_pairs_finds_identical():
    f = np.geomspace(5, 20000, 2000)
    base = SimulatorBackend().driver
    from dataclasses import replace
    drivers = [base, replace(base, fs=base.fs * 1.08), base, replace(base, fs=base.fs * 1.08)]
    items = []
    for i, d in enumerate(drivers):
        z = d.impedance(f)
        items.append((f"T{i}", matching.values(fit_driver(f, z)), f, z))
    pairs = matching.best_pairs(items, matching.DEFAULT_TOL)
    assert {tuple(sorted((i, j))) for i, j, _ in pairs} == {(0, 2), (1, 3)}
    assert all(score < 0.2 for _i, _j, score in pairs)


# ---- Impedanzkorrektur ----------------------------------------------------------

def test_correction_flattens_impedance():
    f = np.geomspace(5, 20000, 3000)
    z = SimulatorBackend().driver.impedance(f)
    fit = fit_driver(f, z)
    zc = corr.corrected(f, z, corr.optimize_zobel(f, z, fit), corr.notch_from_fit(fit))
    lo, hi = corr.magnitude_range(f, zc, 20, 20000)
    assert hi / lo < 1.6
    assert corr.magnitude_range(f, z, 20, 20000)[1] / hi > 5


@pytest.mark.parametrize("v,series,expected", [(4.75, corr.E12, 4.7), (6.61, corr.E24, 6.8),
                                               (1766, corr.E12, 1800), (0.0099, corr.E12, 0.01)])
def test_nearest_e(v, series, expected):
    assert corr.nearest_e(v, series) == pytest.approx(expected)


# ---- Simulator-Dauerbetrieb (Oszilloskop) -------------------------------------------

def test_simulator_stream():
    sim = SimulatorBackend()
    assert sim.read_input(100) is None
    sim.set_connection("open")
    sim.start_stream(generate("sine", 1000, -20, 1.0, 48000), 48000)
    sim._stream["t0"] -= 1.0                        # so tun, als liefe der Strom schon 1 s
    x = sim.read_input(4800)
    assert x.shape == (4800, 2)
    rms = np.sqrt(np.mean(x ** 2, axis=0))
    assert rms[0] == pytest.approx(0.1 / np.sqrt(2) * sim.hw.gain_ref, rel=0.1)
    sim.stop()
    assert not sim.streaming


# ---- Fehlerbericht / Updates -------------------------------------------------------

def test_report_is_anonymized(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/maxmuster")))
    diagnostics.setup_logging(tmp_path)
    diagnostics.log.info("Projekt /Users/maxmuster/Messungen/a.datsproj geöffnet")
    text = diagnostics.build_report({"Gerät": "Simulator"}, error="ValueError: x")
    assert "maxmuster" not in text and "~/Messungen/a.datsproj" in text
    assert "Version:" in text and "Gerät: Simulator" in text and "ValueError" in text


def test_version_compare_and_changelog():
    assert updates.is_newer("0.10.0", "0.9.9") and not updates.is_newer("0.2.0", "0.2.0")
    md = "# Neu\n\n## 0.3.0 – x\n\n- c\n\n## 0.2.0 – y\n\n- b\n\n## 0.1.0\n\n- a\n"
    assert updates.sections_newer_than(md, "0.1.0").count("## ") == 2
    assert "0.3.0" in updates.sections_newer_than(md, "0.2.0")
    assert updates.raw_url("https://github.com/a/b", "x.py") == "https://raw.githubusercontent.com/a/b/main/x.py"
    assert updates.local_changelog().strip(), "NEUERUNGEN.md fehlt"
