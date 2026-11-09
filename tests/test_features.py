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


def test_simulator_distortion_is_small_signal(eng):
    """DATS V3 = Kleinsignal: Klirr eines intakten Treibers liegt an der Messgrenze."""
    from datsmess.dsp.distortion import at_noise_floor
    e, sim = eng
    sim.distortion = True
    sim.set_connection("driver")
    m, _ = e.measure_impedance()
    r = analyze(m.recordings, e.sweep)
    assert at_noise_floor(r)
    assert r.peak(r.thd, 20, 2000)[0] < 0.001              # unter 0,1 %


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
    assert fs[1] < fs[0] * 0.995                    # lauter → etwas tiefere Resonanz (Kleinsignal)
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
    assert "Absturzprotokoll" not in text
    (tmp_path / "absturz.log").write_text("Windows fatal exception: access violation\n", encoding="utf-8")
    assert "access violation" in diagnostics.build_report()     # harter Absturz landet im Bericht


def test_version_compare_and_changelog():
    assert updates.is_newer("0.10.0", "0.9.9") and not updates.is_newer("0.2.0", "0.2.0")
    md = "# Neu\n\n## 0.3.0 – x\n\n- c\n\n## 0.2.0 – y\n\n- b\n\n## 0.1.0\n\n- a\n"
    assert updates.sections_newer_than(md, "0.1.0").count("## ") == 2
    assert "0.3.0" in updates.sections_newer_than(md, "0.2.0")
    assert updates.raw_url("https://github.com/a/b", "x.py") == "https://raw.githubusercontent.com/a/b/main/x.py"
    assert updates.local_changelog().strip(), "NEUERUNGEN.md fehlt"


def test_simulator_distortion_keeps_low_end_clean():
    """Regression 0.2.0: Der Simulator-Klirr machte die Kurve unter 10 Hz unruhig."""
    curves = []
    for dist in (False, True):
        sim = SimulatorBackend(seed=1)
        sim.distortion = dist
        m, _ = MeasurementEngine(sim).measure_impedance()
        curves.append(m.resampled(2000, 48))
    (f, z0), (_, z1) = curves
    sel = (f >= 1) & (f < 10)
    assert np.max(np.abs(z1[sel] / z0[sel] - 1)) < 0.005


# ---- Geräteauswahl (Windows meldet Ein- und Ausgang getrennt) -------------------------

def _win_devices():
    from datsmess.audio.backend import DeviceInfo as D
    return [
        D(0, "Microsoft Soundmapper - Input", "MME", 2, 0, 44100),
        D(1, "Mikrofon (DATS V3)", "MME", 2, 0, 44100),
        D(2, "Mikrofonarray (Realtek(R) Audio", "MME", 2, 0, 44100),       # MME kürzt auf 31 Zeichen
        D(3, "Lautsprecher (DATS V3)", "MME", 0, 2, 44100),
        D(4, "Lautsprecher (Realtek(R) Audio)", "MME", 0, 2, 44100),
        D(5, "Primärer Soundtreiber", "Windows DirectSound", 0, 2, 44100),
        D(6, "Mikrofon (DATS V3)", "Windows DirectSound", 2, 0, 44100),
        D(7, "Lautsprecher (DATS V3)", "Windows DirectSound", 0, 2, 44100),
        D(8, "Lautsprecher (DATS V3)", "Windows WASAPI", 0, 2, 48000),
        D(9, "Mikrofon (DATS V3)", "Windows WASAPI", 2, 0, 48000),
        D(10, "Lautsprecher (Realtek(R) Audio)", "Windows WASAPI", 0, 2, 48000),
        D(11, "Mikrofonarray (Realtek(R) Audio)", "Windows WASAPI", 4, 0, 48000),
        D(12, "Kopfhörer (Bluetooth Headset)", "Windows WASAPI", 0, 2, 48000),
    ]


def test_device_choices_pair_and_prefer_wasapi():
    from datsmess.audio.backend import device_choices
    ch = device_choices(_win_devices(), 48000, supports=lambda i, o, fs: True)
    dats = ch[0]
    assert dats.is_dats and dats.usable and dats.hostapi == "Windows WASAPI" and dats.indices == (9, 8)
    realtek = next(c for c in ch if "Realtek" in c.name)
    assert realtek.usable and realtek.dimmed and realtek.indices == (11, 10)
    grey = [c for c in ch if not c.usable]
    assert [c.out.name for c in grey] == ["Kopfhörer (Bluetooth Headset)"]
    assert "nur einen Ausgang" in grey[0].reason
    assert not any("Soundmapper" in c.label or "Primärer" in c.label for c in ch)
    assert len([c for c in ch if c.usable]) == 2                       # keine Dubletten je Schnittstelle


def test_device_choices_fall_back_when_wasapi_rejects_rate():
    from datsmess.audio.backend import device_choices
    ch = device_choices(_win_devices(), 44100, supports=lambda i, o, fs: o.hostapi != "Windows WASAPI")
    assert ch[0].is_dats and ch[0].hostapi == "Windows DirectSound"


def test_device_choices_full_duplex_and_keys_stable():
    from datsmess.audio.backend import DeviceInfo as D, device_choices
    mac = [D(0, "DATS V3", "Core Audio", 2, 2, 48000), D(1, "Mac mini-Lautsprecher", "Core Audio", 0, 2, 48000)]
    ch = device_choices(mac, 48000, supports=lambda i, o, fs: True)
    assert ch[0].indices == (0, 0) and ch[0].label == "★ DATS V3 (Core Audio)"
    assert not ch[1].usable
    k48 = device_choices(_win_devices(), 48000, supports=lambda i, o, fs: True)[0].key
    k44 = device_choices(_win_devices(), 44100, supports=lambda i, o, fs: o.hostapi != "Windows WASAPI")[0].key
    assert k48 == k44                                                    # Auswahl bleibt beim Ratenwechsel


def test_device_choices_real_windows_laptop():
    """Echte Geräteliste eines Tester-Laptops (Windows 10, Realtek, ohne DATS) aus dem Fehlerbericht."""
    from datsmess.audio.backend import DeviceInfo as D, device_choices
    devs = [
        D(0, "Microsoft Sound Mapper - Input", "MME", 2, 0, 44100),
        D(1, "Mikrofonarray (Realtek(R) Audio", "MME", 2, 0, 44100),
        D(2, "Microsoft Sound Mapper - Output", "MME", 0, 2, 44100),
        D(3, "Lautsprecher (Realtek(R) Audio)", "MME", 0, 2, 44100),
        D(4, "Primärer Soundaufnahmetreiber", "Windows DirectSound", 2, 0, 44100),
        D(5, "Mikrofonarray (Realtek(R) Audio)", "Windows DirectSound", 2, 0, 44100),
        D(6, "Primärer Soundtreiber", "Windows DirectSound", 0, 2, 44100),
        D(7, "Lautsprecher (Realtek(R) Audio)", "Windows DirectSound", 0, 2, 44100),
        D(8, "Lautsprecher (Realtek(R) Audio)", "Windows WASAPI", 0, 2, 48000),
        D(9, "Mikrofonarray (Realtek(R) Audio)", "Windows WASAPI", 2, 0, 48000),
        D(10, "Speakers (Realtek HD Audio output)", "Windows WDM-KS", 0, 2, 44100),
        D(11, "Stereomix (Realtek HD Audio Stereo input)", "Windows WDM-KS", 2, 0, 48000),
        D(12, "Mikrofonarray (Realtek HD Audio Mic input)", "Windows WDM-KS", 2, 0, 44100),
    ]
    ch = device_choices(devs, 48000, supports=lambda i, o, fs: o.hostapi == "Windows WASAPI" or fs == 44100)
    assert [(c.name, c.hostapi, c.usable, c.dimmed) for c in ch] == [
        ("Realtek(R) Audio", "Windows WASAPI", True, True)]
    assert ch[0].indices == (9, 8)
    ch44 = device_choices(devs, 44100, supports=lambda i, o, fs: o.hostapi != "Windows WASAPI")
    assert [(c.name, c.hostapi) for c in ch44] == [("Realtek(R) Audio", "Windows DirectSound")]


@pytest.mark.parametrize("name,expected", [
    ("Lautsprecher (Realtek(R) Audio)", "Realtek(R) Audio"),
    ("Mikrofonarray (Realtek(R) Audio", "Realtek(R) Audio"),        # von MME gekürzt
    ("Mikrofon (DATS V3)", "DATS V3"),
    ("Babyface Pro (71994324)", "Babyface Pro"),                     # macOS: Seriennummer in Klammern
    ("DATS V3", "DATS V3"),
])
def test_physical_name(name, expected):
    from datsmess.audio.backend import physical_name
    assert physical_name(name) == expected


def test_device_marked_as_dats_by_key():
    """Meldet sich das DATS unter fremdem Namen, kann es als DATS gemerkt werden."""
    from datsmess.audio.backend import DeviceInfo as D, device_choices
    devs = [D(0, "Lautsprecher (USB Audio CODEC)", "Windows WASAPI", 0, 2, 48000),
            D(1, "Mikrofon (USB Audio CODEC)", "Windows WASAPI", 2, 0, 48000)]
    plain = device_choices(devs, 48000, supports=lambda i, o, fs: True)[0]
    assert not plain.is_dats and plain.dimmed
    marked = device_choices(devs, 48000, supports=lambda i, o, fs: True, dats_keys={plain.key})[0]
    assert marked.is_dats and not marked.dimmed and marked.label.startswith("★")
    assert "Als DATS bestätigt" in marked.reason


def test_device_watcher_polls_signature(qtbot=None):
    """Windows-Weg (ohne QtMultimedia): Änderung der Geräte-Signatur löst ``changed`` aus."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])   # auch für spätere Widget-Tests
    from datsmess.gui.device_watch import DeviceWatcher, windows_device_signature
    import sys
    if sys.platform != "win32":
        assert windows_device_signature() is None
    sig = {"v": (("Mikrofon (DATS V3)", 2),), }
    w = DeviceWatcher(interval_ms=10, signature=lambda: sig["v"])
    assert w.mode == "Windows-Geräteabfrage"
    hits = []
    w.changed.connect(lambda: hits.append(1))
    w._poll()
    assert hits == []
    sig["v"] = ()
    w._poll()
    w._poll()
    assert hits == [1]
    del app


# ---- T/S: Mindestverschiebung durch Zusatzmasse / Testgehäuse -------------------------

@pytest.mark.parametrize("method,kw,expect", [
    ("added_mass", {"added_mass": 0.0005}, "abort"),      # ~1 % Absenkung
    ("added_mass", {"added_mass": 0.005}, "warn"),        # ~10 %
    ("added_mass", {"added_mass": 0.020}, "ok"),          # ~28 %
    ("test_box", {"vb": 0.2}, "abort"),                   # ~5 % Anhebung (knapp darunter)
    ("test_box", {"vb": 0.08}, "warn"),                   # ~12 %
    ("test_box", {"vb": 0.02}, "ok"),                     # ~41 %
])
def test_ts_minimum_shift(method, kw, expect):
    from datsmess.analysis.ts import VasMethod, derive_ts, fit_driver
    d = SimulatorBackend().driver
    f = np.geomspace(5, 20000, 4000)
    fit1 = fit_driver(f, d.impedance(f))
    z2 = d.impedance(f, added_mass=kw["added_mass"]) if "added_mass" in kw else d.impedance(f, box_volume=kw["vb"])
    fit2 = fit_driver(f, z2, re_dc=fit1.Re, fix_re=True)
    meth = VasMethod.ADDED_MASS if method == "added_mass" else VasMethod.TEST_BOX
    if expect == "abort":
        with pytest.raises(ValueError, match="zu wenig"):
            derive_ts(fit1, meth, sd=d.Sd, second=fit2, **kw)
        return
    p = derive_ts(fit1, meth, sd=d.Sd, second=fit2, **kw)
    assert p.shift > 0.05 and p.uncertainty > 0
    has_warning = any("unsicher" in w for w in p.warnings)
    assert has_warning == (expect == "warn")
    assert p.Vas == pytest.approx(d.Vas, rel=0.02)
    keys = [r[0] for r in p.rows()]
    assert "shift" in keys and "unc" in keys


def test_ts_recommendation_values():
    from datsmess.analysis.ts import VasMethod, derive_ts, fit_driver
    d = SimulatorBackend().driver
    f = np.geomspace(5, 20000, 4000)
    fit1 = fit_driver(f, d.impedance(f))
    fit2 = fit_driver(f, d.impedance(f, added_mass=0.005), re_dc=fit1.Re, fix_re=True)
    p = derive_ts(fit1, VasMethod.ADDED_MASS, sd=d.Sd, second=fit2, added_mass=0.005)
    assert "17 g" in p.recommendation                # Mms 22 g · (1/0,75² − 1) ≈ 17 g


def test_latest_commit_rejects_non_github():
    from datsmess import updates
    assert updates.latest_commit("https://example.org/x/y") is None
    assert updates.raw_url("https://github.com/a/b", "f.py", "0123abc") == \
        "https://raw.githubusercontent.com/a/b/0123abc/f.py"


# ---- Selbst-Update (ohne Konsolenfenster) ------------------------------------------------

def _fake_install(root, version="0.2.8", deps='["numpy"]'):
    (root / "src" / "datsmess").mkdir(parents=True)
    (root / "src" / "datsmess" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (root / "pyproject.toml").write_text(f'[project]\nname = "datsmess"\nversion = "{version}"\n'
                                         f'dependencies = {deps}\n')
    (root / "update-quelle.txt").write_text("https://github.com/a/b\n")
    (root / ".venv").mkdir()
    return root


def _zip_of(folder):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in folder.rglob("*"):
            if p.is_file():
                z.write(p, f"dats-messsoftware-abc/{p.relative_to(folder)}")
    return buf.getvalue()


@pytest.mark.parametrize("new_deps,expect_pip", [('["numpy"]', False), ('["numpy", "scipy"]', True)])
def test_self_update_replaces_files(tmp_path, monkeypatch, new_deps, expect_pip):
    from datsmess import selfupdate
    root = _fake_install(tmp_path / "inst")
    new = _fake_install(tmp_path / "neu", version="0.2.9", deps=new_deps)
    (new / "NEUERUNGEN.md").write_text("## 0.2.9\n")
    calls = []
    monkeypatch.setattr(selfupdate, "reinstall", lambda r: calls.append(r))
    steps = []
    res = selfupdate.run_update(root, progress=lambda *a: steps.append(a[0]), fetch=lambda: _zip_of(new))
    assert res.version == "0.2.9" and res.reinstalled == expect_pip and bool(calls) == expect_pip
    assert '0.2.9' in (root / "src" / "datsmess" / "__init__.py").read_text()
    assert (root / "NEUERUNGEN.md").exists() and (root / ".venv" / "datsmess-editable.flag").exists()
    assert not list(root.rglob("*.neu"))
    assert steps[0] == "download" and "copy" in steps


def test_self_update_rejects_bad_archives(tmp_path):
    from datsmess import selfupdate
    root = _fake_install(tmp_path / "inst")
    with pytest.raises(selfupdate.UpdateError, match="keine gültige ZIP"):
        selfupdate.run_update(root, fetch=lambda: b"kein zip")
    other = tmp_path / "anderes"
    other.mkdir()
    (other / "README.md").write_text("x")
    with pytest.raises(selfupdate.UpdateError, match="nicht die DATS"):
        selfupdate.run_update(root, fetch=lambda: _zip_of(other))
    assert '0.2.8' in (root / "src" / "datsmess" / "__init__.py").read_text()     # unverändert


def test_deps_fingerprint_ignores_version():
    from datsmess.selfupdate import _deps_fingerprint
    a = '[project]\nname = "x"\nversion = "0.2.8"\ndependencies = ["numpy"]\n'
    assert _deps_fingerprint(a) == _deps_fingerprint(a.replace("0.2.8", "0.2.9"))
    assert _deps_fingerprint(a) != _deps_fingerprint(a.replace('["numpy"]', '["numpy", "scipy"]'))


def test_wait_for_pid_returns_after_exit():
    """Wie beim Neustart: der abgewartete Prozess ist kein Kindprozess (sonst bliebe er als Zombie)."""
    import subprocess
    import sys
    import time
    from datsmess.selfupdate import wait_for_pid
    if sys.platform == "win32":
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
        pid = p.pid
    else:
        out = subprocess.run(["sh", "-c", "sleep 0.5 & echo $!"], capture_output=True, text=True)
        pid = int(out.stdout.strip())
    t = time.monotonic()
    wait_for_pid(pid, timeout=10)
    assert time.monotonic() - t < 5


def test_whats_new_shows_history_below_news():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datsmess.gui import help as helpdlg
    md = helpdlg.whats_new_markdown("0.2.5")
    assert md.startswith("# Neu seit deiner Version 0.2.5")
    news, history = md.split("# Frühere Versionen")
    assert "## 0.2.6" in news and "## 0.2.5" not in news
    assert "## 0.2.5" in history and "## 0.1.0" in history


# ---- Darstellung: Taskleiste, Diagrammhintergrund, Touch ---------------------------------

def test_taskbar_relaunch_properties(monkeypatch, tmp_path):
    """Angeheftet: Neustart über pythonw.exe (kein Konsolenfenster), eigenes Symbol, gleiche App-ID."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datsmess.gui import icon
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "pythonw.exe").write_text("")
    monkeypatch.setattr(icon.sys, "executable", str(scripts / "python.exe"))
    props = icon.relaunch_properties()
    assert list(props) == [2, 4, 3, 5]                     # Relaunch-Angaben vor der ID
    assert props[2] == f'"{scripts / "pythonw.exe"}" -m datsmess'
    assert props[3].endswith("icon.ico,0") and (icon.RESOURCES / "icon.ico").exists()
    assert props[5] == icon.APP_ID
    if icon.sys.platform != "win32":
        assert icon.set_window_relaunch(object()) is False


def test_plot_background_and_touch_stylesheet():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from datsmess.gui.appearance import Appearance, gray_for, level_for, stylesheet
    assert Appearance().plot_bg == "#ffffff" and not Appearance().plot_dark
    assert Appearance(theme="dark").plot_dark
    # Schieberegler dunkel → weiß, Umkehrung passt
    assert gray_for(100) == "#ffffff" and level_for(gray_for(0)) == 0
    for lv in (0, 30, 55, 80, 100):
        assert abs(level_for(gray_for(lv)) - lv) <= 1
    # Achsen/Modellkurven richten sich nach dem Hintergrund, nicht nach dem Farbschema
    light_on_dark = Appearance(theme="light", plot_bg_custom=gray_for(5))
    assert light_on_dark.plot_dark and light_on_dark.model == "#f0f0f0"
    grey = Appearance(theme="dark", plot_bg_custom=gray_for(70))
    assert not grey.plot_dark and grey.model == "#000000"
    assert Appearance(plot_bg_custom="kaputt").plot_bg == "#ffffff"
    # Touch: Zusatz-Stylesheet mit großen Knöpfen nur im Touch-Modus
    assert "min-height: 34px" in stylesheet(Appearance(touch="touch"))
    assert "min-height: 34px" not in stylesheet(Appearance(touch="mouse"))
    del app


def test_plot_remembers_frequency_range_and_log():
    """Start mit 20 Hz – 20 kHz; gewählter Bereich und |Z| log überstehen einen Neustart; eine neue
    Messung passt nur die senkrechte Achse an."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore, QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    QtCore.QStandardPaths.setTestModeEnabled(True)
    app.setOrganizationName("datsmess-test-plots")
    QtCore.QSettings().clear()
    from datsmess.gui.plots import Curve, ImpedancePlot

    def freq(p):
        x0, x1 = p.top.vb.viewRange()[0]
        return 10 ** x0, 10 ** x1

    p = ImpedancePlot(name="t")
    lo, hi = freq(p)
    assert 15 < lo < 20 and 20000 < hi < 26000             # Hörbereich mit kleinem Rand
    f = np.geomspace(1, 20000, 200)
    p.set_curves([Curve("a", f, 6 + 0j * f)], autorange=True)
    assert abs(freq(p)[0] - lo) < 1e-6                       # Messung ändert die Frequenzachse nicht
    p.set_freq_range(5, 500)
    p.set_log_y(True)
    p._save_settings()
    q = ImpedancePlot(name="t")                              # „Neustart“
    lo, hi = freq(q)
    assert 4 < lo < 5 and 500 < hi < 600 and q.log_y
    p.auto_range()
    p.set_curves([Curve("a", f, 6 + 0j * f)])
    p.top.vb.updateAutoRange()                               # sonst erst beim Zeichnen (Fenster unsichtbar)
    p._save_settings()
    assert freq(ImpedancePlot(name="t"))[0] < 1.5            # „Alles anzeigen“ wird ebenfalls gemerkt
    assert ImpedancePlot().log_y is False                    # ohne Namen: nichts geladen
    QtCore.QSettings().clear()


def test_axis_font_size_and_weight():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from datsmess.gui.appearance import Appearance, appearance
    from datsmess.gui.plots import ImpedancePlot
    assert Appearance().axis_font().pointSizeF() == app.font().pointSizeF()      # Standard = Systemschrift
    f = Appearance(axis_font_pt=16, axis_bold=True).axis_font()
    assert f.pointSizeF() == 16 and f.bold()
    old = appearance().current
    try:
        p = ImpedancePlot()
        w_small = p.top.getAxis("left").fixedWidth
        appearance().current = Appearance(axis_font_pt=18, axis_bold=True)
        p._restyle()
        ax = p.top.getAxis("left")
        assert ax.style["tickFont"].pointSizeF() == 18
        assert ax.labelStyle["font-size"] == "18pt" and ax.labelStyle["font-weight"] == "bold"
        assert ax.fixedWidth > w_small                          # Platz für größere Zahlen
        assert p.bottom.getAxis("left").fixedWidth == ax.fixedWidth   # beide Diagramme bündig
    finally:
        appearance().current = old


class _LaggySoundDevice:
    """Ersatz für ``sounddevice``: Simulator mit großer Windows-Latenz (DirectSound ~0,5 s)."""

    def __init__(self, sim, latency_s):
        self.sim, self.latency_s = sim, latency_s

    def query_devices(self, *_a, **_k):
        return {"max_output_channels": 2, "max_input_channels": 2, "name": "USB AUDIO  CODEC"}

    def playrec(self, out, samplerate, channels, **_k):
        rec = self.sim.play_record(np.asarray(out)[:, 0], samplerate, in_channels=channels)
        lag = int(self.latency_s * samplerate)
        return np.vstack([np.zeros((lag, rec.shape[1])), rec])[:len(out)]

    def stop(self):
        pass


@pytest.mark.parametrize("latency_s", [0.0, 0.537, 1.4])
def test_large_device_latency_keeps_high_frequencies(latency_s):
    """Tester mit echtem DATS (09.11.2026): 537 ms Latenz schnitten das Sweep-Ende ab → Müll ab ~10 kHz."""
    from datsmess.audio.backend import SoundDeviceBackend
    cfg = SweepConfig(fs=44100, sweep_exp=16)
    sim = SimulatorBackend()
    sim.set_connection("driver")
    ref = MeasurementEngine(sim, cfg)
    m_ref, _ = ref.measure_impedance()
    be = SoundDeviceBackend.__new__(SoundDeviceBackend)
    be._sd, be.input_device, be.output_device, be.label = _LaggySoundDevice(sim, latency_s), 0, 0, None
    eng = MeasurementEngine(be, cfg)
    m, raw = eng.measure_impedance()
    assert abs(be.last_latency / cfg.fs - latency_s) < 0.02
    hf = (m.f > 5000) & (m.f < 17000)
    err = np.abs(m.Z[hf] - m_ref.Z[hf]) / np.abs(m_ref.Z[hf])
    assert np.median(err) < 0.01
    assert raw.quality["noise_db"] is not None        # Nachlauf (Rauschmessung) liegt in der Aufnahme


def test_quick_parameters_ignore_noisy_treble(eng):
    """Gestörte Höhen (z. B. abgeschnittener Sweep) dürfen fs/Re einer klaren Resonanz nicht verhindern."""
    e, sim = eng
    sim.set_connection("driver")
    m, _ = e.measure_impedance()
    rng = np.random.default_rng(1)
    Z = m.Z.copy()
    hf = m.f > 10000
    Z[hf] *= 1 + 3 * (rng.standard_normal(hf.sum()) + 1j * rng.standard_normal(hf.sum()))
    clean, noisy = quick_parameters(m.f, m.Z), quick_parameters(m.f, Z)
    assert clean is not None and noisy is not None
    assert abs(noisy.fs / clean.fs - 1) < 0.02 and abs(noisy.Re / clean.Re - 1) < 0.02


def test_ts_tab_preselects_new_measurement():
    """Tester (09.11.2026): Messung vom großen Mess-Knopf erschien im T/S-Tab nicht."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # noqa: F841
    from datsmess.gui.state import AppState
    from datsmess.gui.ts_tab import TSTab
    state = AppState()
    tab = TSTab(state)
    sim = state.backend
    sim.set_connection("driver")
    m, _ = state.engine.measure_impedance("Messung 1")
    state.add_measurement(m)
    assert tab.cb_free.currentData() is m
    assert tab.table.rowCount() > 0 and "Zweitmessung" in tab.warn.text()


def test_closed_wizards_are_deleted_and_theme_switch_keeps_gc(tmp_path):
    """Tester (09.11.2026): Absturz beim Umschalten auf „Dunkel“ – der Garbage-Collector löschte einen
    geschlossenen Assistenten, während Qt in setStyleSheet rohe Zeiger auf dessen Widgets hielt."""
    import gc
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["DATSMESS_NO_UPDATE_CHECK"] = "1"
    from dataclasses import replace
    from PySide6 import QtCore, QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    QtCore.QStandardPaths.setTestModeEnabled(True)
    app.setOrganizationName("datsmess-test-theme")
    from datsmess.gui.appearance import appearance
    from datsmess.gui.main_window import MainWindow
    w = MainWindow()

    def close_modal():
        d = app.activeModalWidget()
        if d is not None:
            d.reject()
        else:
            QtCore.QTimer.singleShot(50, close_modal)
    for fn in (w.open_calibration, w.open_device_check):
        QtCore.QTimer.singleShot(50, close_modal)
        fn()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    assert not [x for x in app.allWidgets() if isinstance(x, QtWidgets.QWizard)]
    cur = appearance().current
    for theme in ("dark", "light"):
        appearance().set(replace(cur, theme=theme))
        assert gc.isenabled()
    w.state.dirty = False
    w.close()
    w.deleteLater()
