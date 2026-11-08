"""Tests für FS-01 … FS-04: Textexport, T/S-Profile, Watch-Folder, Projektarchiv."""
import numpy as np
import pytest

from datsmess.analysis.ts import VasMethod, derive_ts, fit_driver
from datsmess.audio.simulator import SimulatorBackend
from datsmess.dsp.calibration import Calibration
from datsmess.io.formats import TextExportOptions, export_impedance, import_impedance
from datsmess.io.project import Project, load_project, save_project
from datsmess.io.ts_export import PROFILES, DriverInfo, profile_text, read_tsp, save_text, tsp_text
from datsmess.io.watch import WatchFolderConfig, deliver
from datsmess.measurement import MeasurementEngine, reprocess


@pytest.fixture(scope="module")
def rig():
    sim = SimulatorBackend(seed=11)
    eng = MeasurementEngine(sim)
    H, R = {}, {}
    for s in ("open", "short", "cal"):
        sim.set_connection(s)
        raw = eng.measure_H()
        H[s], R[s] = raw.H, raw.recordings
    eng.calibration = Calibration(eng.sweep, sim.hw.r_cal, eng.sweep.frequencies(), H["cal"], H["open"], H["short"],
                                  recordings=R, channels=eng.channels.to_dict())
    sim.set_connection("driver")
    free, _ = eng.measure_impedance("Freiluft")
    sim.set_connection("driver_mass")
    mass, _ = eng.measure_impedance("Masse")
    fit1 = fit_driver(free.f, free.Z)
    fit2 = fit_driver(mass.f, mass.Z, re_dc=fit1.Re, fix_re=True)
    ts = derive_ts(fit1, VasMethod.ADDED_MASS, sd=sim.driver.Sd, second=fit2, added_mass=sim.added_mass)
    return eng, sim, free, mass, ts


# ---- FS-01 ---------------------------------------------------------------

@pytest.mark.parametrize("opt", [
    TextExportOptions(delimiter="tab", decimal=",", freq_unit="kHz", imp_unit="mOhm", phase_unit="rad"),
    TextExportOptions(delimiter="semicolon", decimal=",", columns="magphase"),
    TextExportOptions(delimiter="comma", columns="reim", imp_unit="kOhm"),
    TextExportOptions(delimiter="space", columns="magphase", phase_unit="rad", lossless=True),
])
def test_text_export_options_roundtrip(tmp_path, opt):
    f = np.geomspace(1, 20000, 300)
    Z = 6 + 1j * f * 1e-4 + 30 / (1 + 1j * 4 * (f / 40 - 40 / f))
    p = tmp_path / "x.txt"
    export_impedance(p, f, Z, ["Kopf"], opt)
    f2, Z2 = import_impedance(p)
    assert np.allclose(f2, f, rtol=1e-6)
    assert np.allclose(Z2, Z, rtol=1e-4, atol=1e-5)


def test_decimal_comma_with_comma_delimiter_rejected(tmp_path):
    with pytest.raises(ValueError):
        export_impedance(tmp_path / "x.csv", np.array([1.0]), np.array([1 + 0j]),
                         options=TextExportOptions(delimiter="comma", decimal=","))


def test_lossless_zma_is_bit_exact(tmp_path, rig):
    _eng, _sim, free, *_ = rig
    p = tmp_path / "x.zma"
    export_impedance(p, free.f, free.Z, options=TextExportOptions(lossless=True))
    f2, Z2 = import_impedance(p)
    assert np.array_equal(f2, free.f)
    assert np.allclose(Z2, free.Z, rtol=1e-14, atol=0)


# ---- FS-02 ---------------------------------------------------------------

@pytest.mark.parametrize("key", list(PROFILES))
def test_profiles_qts_consistent(rig, key):
    *_, ts = rig
    text = profile_text(key, ts, DriverInfo("Test", "W6"), xmax=0.005)
    vals = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        label, value, _unit = line.split("\t")
        vals[label.lower()] = float(value)
    qms, qes, qts = vals["qms"], vals["qes"], vals["qts"]
    assert abs(qms * qes / (qms + qes) - qts) <= 0.0005 + 1e-12
    assert vals["fs"] == pytest.approx(ts.fit.fs, abs=0.01)
    assert vals["vas"] == pytest.approx(ts.Vas * 1e3, abs=0.01)


def test_tsp_structure(tmp_path, rig):
    *_, ts = rig
    p = tmp_path / "d.tsp"
    save_text(p, tsp_text(ts, DriverInfo("Hersteller", "Modell", "SN1", "Zeile 1\nZeile 2"), xmax=0.005))
    d = read_tsp(p)
    assert d["Driver"]["Model"] == "Modell"
    assert d["Driver"]["Notes"] == "Zeile 1\\nZeile 2"
    assert float(d["Parameters"]["fs"]) == pytest.approx(ts.fit.fs, abs=1e-3)
    assert d["Units"]["Vas"] == "l"
    assert "Kr" in d["Parameters"] and "Xi" in d["Parameters"]


# ---- FS-03 ---------------------------------------------------------------

def test_watch_folder_delivery(tmp_path, rig):
    *_, free, _mass, ts = rig
    free.meta["Re"] = ts.fit.Re
    cfg = WatchFolderConfig(path=str(tmp_path))
    files = deliver(cfg, free, DriverInfo("A", "B"), tsp_text(ts, DriverInfo()))
    assert [p.suffix for p in files] == [".zma", ".tsp"]
    text = files[0].read_text()
    assert f"Re = {ts.fit.Re!r} Ohm" in text
    f2, Z2 = import_impedance(files[0])
    assert len(f2) == len(free.f)
    assert not list(tmp_path.glob(".~*"))          # keine Temp-Reste
    with pytest.raises(ValueError):
        deliver(WatchFolderConfig(path=str(tmp_path / "fehlt")), free)


# ---- FS-04 ---------------------------------------------------------------

def test_project_roundtrip_and_exact_reproduction(tmp_path, rig):
    eng, _sim, free, mass, ts = rig
    proj = Project(info=DriverInfo("Hersteller", "W6", "123", "Notiz\nmehrzeilig"),
                   measurements=[free, mass], ts={"inputs": {"method": "added_mass"}, "free_id": free.id},
                   settings={"sweep": eng.sweep.to_dict()})
    proj.add_calibration(eng.calibration)
    proj.active_calibration_id = eng.calibration.id
    p = tmp_path / "p.datsproj"
    save_project(p, proj)
    loaded = load_project(p)
    assert loaded.info.notes == "Notiz\nmehrzeilig"
    assert loaded.ts["free_id"] == free.id
    m2 = loaded.measurements[0]
    assert m2.id == free.id and m2.name == "Freiluft"
    assert np.array_equal(m2.Z, free.Z)
    assert np.array_equal(m2.recordings, free.recordings)
    cal = loaded.calibrations[m2.meta["calibration_id"]]
    assert np.array_equal(reprocess(m2, cal), free.Z)        # bitgenau reproduzierbar


def test_project_is_compact_and_falls_back_losslessly(tmp_path, rig):
    import zipfile
    eng, _sim, free, mass, _ts = rig
    proj = Project(measurements=[free, mass])
    proj.add_calibration(eng.calibration)
    p = tmp_path / "c.datsproj"
    save_project(p, proj)
    names = zipfile.ZipFile(p).namelist()
    assert not any(n.endswith("Z.npy") for n in names)           # Z aus Rohdaten ableitbar
    assert any(n.endswith("/meta.json") for n in names)           # Kalibrierung als Rohdaten
    assert p.stat().st_size < 3_000_000
    loaded = load_project(p)
    assert all(np.array_equal(a.Z, b.Z) for a, b in zip(loaded.measurements, [free, mass]))
    assert loaded.calibrations[eng.calibration.id].id == eng.calibration.id
    # ohne Rohdaten der Kalibrierung: vollständige Übertragungsfunktionen werden gespeichert
    bare = Calibration(eng.sweep, eng.calibration.r_cal, eng.calibration.f, eng.calibration.H_load,
                       eng.calibration.H_open, eng.calibration.H_short, created=eng.calibration.created)
    proj2 = Project(measurements=[free])
    proj2.calibrations[eng.calibration.id] = bare
    save_project(tmp_path / "d.datsproj", proj2)
    l2 = load_project(tmp_path / "d.datsproj")
    assert np.array_equal(l2.measurements[0].Z, free.Z)
    # importierte Kurve ohne Rohdaten
    from datsmess.measurement import Measurement
    imp = Measurement("Import", np.geomspace(10, 1000, 50), np.full(50, 8 + 1j))
    save_project(tmp_path / "e.datsproj", Project(measurements=[imp]))
    l3 = load_project(tmp_path / "e.datsproj").measurements[0]
    assert np.array_equal(l3.Z, imp.Z) and np.array_equal(l3.f, imp.f)


def test_project_slots_roundtrip(tmp_path, rig):
    _eng, _sim, free, mass, _ts = rig
    slots = [{"id": free.id, "visible": True}, {"id": mass.id, "visible": False}] + \
            [{"id": None, "visible": True}] * 6
    save_project(tmp_path / "s.datsproj", Project(measurements=[free, mass], slots=slots))
    loaded = load_project(tmp_path / "s.datsproj")
    assert loaded.slots == slots


def test_reprocess_with_new_calibration(rig):
    eng, sim, free, *_ = rig
    z_nominal = reprocess(free, None)
    assert not np.allclose(z_nominal, free.Z)
    assert np.allclose(reprocess(free, eng.calibration), free.Z)
