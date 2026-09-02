"""Checks for the non-GUI core. Run with:  python3 test_core.py

Uses real logs from FLIGHT_TESTING_DATA when they are present, and falls back
to synthetic data otherwise, so it still runs on a machine that only has this
directory.
"""

import os
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

import numpy as np

import analysis
import geodesy
from kmzwrite import kmzwrite
from readpulsetable import PulseLogError, read_pulse_table

DATA_ROOT = ("/Users/mws22/Library/CloudStorage/"
             "OneDrive-NorthernArizonaUniversity/FLIGHT_TESTING_DATA")

REAL_LOGS = [
    ("2023 headerless + rotation rows",
     "2023-08-18-NAVHDA Site/Pulse-2023-08-18-16-04-59-715.csv"),
    ("2025-01 position_x header",
     "2025-01-13-Raymond Park Scan Flights/Pulse-2025-01-13-15-56-01-556.csv"),
    ("2025-11 Cumbria, 4 tags",
     "2025-11-21-Cumbria-Day5-Fri/HERELINK_LOGS/Pulse-2025-11-21-11-08-41-149.csv"),
]

_failures = []


def check(label, ok, detail=""):
    print("  %-52s %s%s" % (label, "PASS" if ok else "FAIL",
                            ("  " + detail) if detail else ""))
    if not ok:
        _failures.append(label)


def synth_log(path, command_id=1, header=True, rotation_rows=True, n=60):
    lines = []
    if header:
        lines.append("# %d, tag_id, frequency_hz, start_time_seconds, "
                     "predict_next_start_seconds, snr, stft_score, "
                     "group_seq_counter, group_ind, group_snr, noise_psd, "
                     "detection_status, confirmed_status, latitude, longitude, "
                     "altitude_rel, roll_deg, pitch_deg, yaw_deg, antenna_offset"
                     % command_id)
    for i in range(n):
        lines.append("%d, 42, 150000000, %.6f, %.6f, %.6f, 0.08, 1, %d, 35.3, "
                     "1.2e-10, 1, 1, %.6f, %.6f, %.3f, 0.1, 0.2, 110.8, 0.0"
                     % (command_id, 1775188930 + i, 1775188931 + i,
                        30 + (i % 7), i, 54.3270 + 0.0002 * (i % 9),
                        -2.9710 + 0.0002 * (i // 9), 10.0 + i))
    if rotation_rows:
        lines.append("2,54.3279,-2.9706,120.0")
        lines.append("3,54.3280,-2.9705,120.0")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def test_reader():
    print("\nreader")
    tmp = tempfile.mkdtemp()

    p = os.path.join(tmp, "dev.csv")
    synth_log(p, command_id=1)
    t, warn = read_pulse_table(p)
    check("dev-master format, rotation rows dropped", len(t) == 60, "n=%d" % len(t))
    check("latitudes are latitudes, not tag ids",
          bool(np.all(np.abs(t.lat - 54.3) < 0.1)))
    check("no warning on a clean file", warn == "", repr(warn))

    p2 = os.path.join(tmp, "old.csv")
    synth_log(p2, command_id=7, header=False, rotation_rows=True)
    t2, _ = read_pulse_table(p2)
    check("headerless 2023-style file", len(t2) == 60, "n=%d" % len(t2))

    p3 = os.path.join(tmp, "rot_only.csv")
    with open(p3, "w") as fh:
        fh.write("10,-18.717122,27.231837,1037.220000\n")
    try:
        read_pulse_table(p3)
        check("rotation-only file raises", False)
    except PulseLogError:
        check("rotation-only file raises", True)

    p4 = os.path.join(tmp, "sorted.csv")
    synth_log(p4, rotation_rows=False)
    t4, _ = read_pulse_table(p4)
    check("rows sorted by time",
          bool(np.all(np.diff(t4.start_time_seconds) >= 0)))

    found = 0
    for label, rel in REAL_LOGS:
        full = os.path.join(DATA_ROOT, rel)
        if not os.path.exists(full):
            continue
        found += 1
        t, warn = read_pulse_table(full)
        ok = len(t) > 0 and np.all(np.abs(t.lat) <= 90)
        check("real log: %s" % label, ok,
              "%d pulses, tags %s%s" % (len(t), np.unique(t.tag_id).tolist(),
                                        "  [" + warn.splitlines()[0] + "]" if warn else ""))
    if found == 0:
        print("  (no real logs reachable; synthetic coverage only)")


def test_movmean():
    print("\nmovmean vs MATLAB semantics")
    x = np.arange(1.0, 11.0)
    # MATLAB: movmean(1:10, 3) -> [1.5 2 3 4 5 6 7 8 9 9.5]
    expect3 = np.array([1.5, 2, 3, 4, 5, 6, 7, 8, 9, 9.5])
    check("odd window k=3", np.allclose(analysis.movmean(x, 3), expect3))
    # MATLAB: movmean(1:10, 4) -> [1.5 2 2.5 3.5 4.5 5.5 6.5 7.5 8.5 9]
    expect4 = np.array([1.5, 2, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9])
    check("even window k=4 (centred on current+previous)",
          np.allclose(analysis.movmean(x, 4), expect4))
    check("k<=1 is identity", np.allclose(analysis.movmean(x, 1), x))
    y = x.copy(); y[3] = np.nan
    check("NaN omitted, not propagated",
          np.all(np.isfinite(analysis.movmean(y, 3))))


def test_geodesy():
    print("\ngeodesy")
    a, f = geodesy.WGS84_A, geodesy.WGS84_F
    e2 = f * (2 - f)

    def ecef(lat, lon, h):
        la, lo = np.radians(lat), np.radians(lon)
        n = a / np.sqrt(1 - e2 * np.sin(la) ** 2)
        return ((n + h) * np.cos(la) * np.cos(lo),
                (n + h) * np.cos(la) * np.sin(lo),
                (n * (1 - e2) + h) * np.sin(la))

    worst = 0.0
    for home in [(54.3280, -2.9706, 0.0), (35.1781, -111.6567, 0.0),
                 (-18.7171, 27.2318, 0.0), (-36.85, 175.18, 0.0)]:
        rng = np.random.default_rng(1)
        lat = home[0] + rng.uniform(-0.005, 0.005, 2000)
        lon = home[1] + rng.uniform(-0.005, 0.005, 2000)
        alt = rng.uniform(0, 120, 2000)
        xe, yn, _ = geodesy.geo2enu(lat, lon, alt, home)
        x, y, z = ecef(lat, lon, alt)
        x0, y0, z0 = ecef(*home)
        dx, dy, dz = x - x0, y - y0, z - z0
        la, lo = np.radians(home[0]), np.radians(home[1])
        e = -np.sin(lo) * dx + np.cos(lo) * dy
        n = (-np.sin(la) * np.cos(lo) * dx - np.sin(la) * np.sin(lo) * dy
             + np.cos(la) * dz)
        worst = max(worst, float(np.abs(xe - e).max()), float(np.abs(yn - n).max()))
        la2, lo2, _ = geodesy.enu2geo(xe, yn, np.zeros_like(xe), home)
        assert np.allclose(la2, lat) and np.allclose(lo2, lon)
    check("agrees with rigorous ECEF ENU", worst < 0.05, "max %.1f cm" % (worst * 100))
    check("enu2geo is an exact inverse", True)


def test_bearing():
    print("\nbearing estimator")
    g = 5.0
    X, Y = np.meshgrid(np.arange(-100, 101, g), np.arange(-100, 101, g))
    worst = 0.0
    for truth in [0, 45, 90, 135, 180, 225, 270, 315]:
        field = np.sin(np.radians(truth)) * X + np.cos(np.radians(truth)) * Y
        b, conf, _ = analysis.estimate_bearing(field, g)
        worst = max(worst, abs((b - truth + 180) % 360 - 180))
    check("exact on clean linear fields, 8 bearings", worst < 1e-6,
          "max err %.2e deg" % worst)

    field = -np.hypot(X - 400.0, Y - 400.0)
    b, conf, _ = analysis.estimate_bearing(field, g)
    check("point source to the NE reads 45 deg", abs(b - 45.0) < 0.5,
          "%.2f deg, conf %.3f" % (b, conf))

    rng = np.random.default_rng(0)
    confs = []
    for noise in [0, 1, 5, 20, 100]:
        f = 0.2 * (np.sin(np.radians(45)) * X + np.cos(np.radians(45)) * Y)
        f = f + noise * rng.standard_normal(X.shape)
        _, c, _ = analysis.estimate_bearing(f, g)
        confs.append(c)
    check("confidence falls monotonically with noise",
          all(confs[i] >= confs[i + 1] for i in range(len(confs) - 1)),
          " ".join("%.3f" % c for c in confs))
    check("no bearing from an empty grid",
          np.isnan(analysis.estimate_bearing(None, 5.0)[0]))


def test_flight_window():
    print("\nflight window (takeoff and landing trimming)")

    # A textbook profile: 15 s climb, cruise at 60 m, 15 s descent.
    t = np.arange(0.0, 100.0)
    alt = np.clip(np.minimum(t * 4.0, (99.0 - t) * 4.0), 0.0, 60.0)
    lo, hi = analysis.flight_window(t, alt)
    check("trims the climb and the descent", (lo, hi) == (15.0, 84.0),
          "%.0f..%.0f of 0..99" % (lo, hi))
    check("the trimmed ends are the low-altitude ones",
          alt[: int(lo)].max() < 60.0 and alt[int(hi) + 1:].max() < 60.0)

    # Only the ends are trimmed: a mid-flight descent is survey data.
    dipped = alt.copy()
    dipped[45:55] = 5.0
    check("keeps a mid-flight descent",
          analysis.flight_window(t, dipped) == (15.0, 84.0))

    # Degenerate altitude cannot support the judgement; keep everything.
    check("constant altitude keeps the whole log",
          analysis.flight_window(t, np.full_like(t, 50.0)) == (0.0, 99.0))
    check("missing altitude keeps the whole log",
          analysis.flight_window(t, np.full_like(t, np.nan)) == (0.0, 99.0))
    check("a single sample keeps the whole log",
          analysis.flight_window(np.array([7.0]), np.array([50.0]))
          == (7.0, 7.0))

    # A window so short the altitude is more likely junk than the flight brief.
    spike = np.zeros_like(t)
    spike[50] = 100.0
    lo, hi = analysis.flight_window(t, spike)
    check("falls back when the window would be a sliver",
          (lo, hi) == (0.0, 99.0), "%.0f..%.0f" % (lo, hi))

    # It is a default, not a filter: the caller still sees every pulse.
    check("returns bounds inside the input range",
          lo >= t.min() and hi <= t.max())


def test_grid_and_kmz():
    print("\ngridding and KMZ")
    rng = np.random.default_rng(3)
    n = 400
    xe = rng.uniform(-150, 150, n)
    yn = rng.uniform(-150, 150, n)
    snr = 40 - np.hypot(xe - 200, yn - 200) * 0.05

    X, Y, grid, used = analysis.build_grid(xe, yn, snr, 5.0)
    check("grid built", grid is not None and np.any(np.isfinite(grid)),
          "shape %s" % (grid.shape,))
    check("NaN outside the convex hull", bool(np.any(np.isnan(grid))))

    Xb, Yb, gb, used_b = analysis.build_grid(xe * 40, yn * 40, snr, 1.0)
    check("grid resolution coarsened rather than exploding",
          gb is None or gb.size <= analysis.MAX_GRID_CELLS,
          "res %.1f m, cells %s" % (used_b, gb.size if gb is not None else 0))

    home = (54.3280, -2.9706, 0.0)
    lat, lon, _ = geodesy.enu2geo(X, Y, np.zeros_like(X), home)
    plat, plon, _ = geodesy.enu2geo(xe, yn, np.zeros_like(xe), home)

    out = os.path.join(tempfile.mkdtemp(), "test.kmz")
    kmzwrite(out, grid_lat=lat, grid_lon=lon, grid_value=grid,
             point_lat=plat, point_lon=plon, point_alt=np.zeros(n),
             point_value=snr, point_altitude_mode="absolute",
             marker_lat=54.3300, marker_lon=-2.9650, marker_name="Tag",
             point_folder_name="Pulses (tag 42)", marker_folder_name="Tag",
             name="unit test", value_name="SNR")

    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        doc = z.read("doc.kml").decode("utf-8")
    check("kmz holds doc.kml + both pngs",
          names == {"doc.kml", "files/dot.png", "files/surface.png"},
          str(sorted(names)))

    root = ET.fromstring(doc)
    check("doc.kml is well-formed XML", True)
    ns = "{http://www.opengis.net/kml/2.2}"
    defined = {e.get("id") for e in root.iter(ns + "Style")}
    used_ids = {e.text.lstrip("#") for e in root.iter(ns + "styleUrl")}
    check("no dangling styleUrl references", not (used_ids - defined),
          str(sorted(used_ids - defined)))
    check("exactly one GroundOverlay",
          len(list(root.iter(ns + "GroundOverlay"))) == 1)
    check("no external http references", "http://maps.google" not in doc)
    folders = [e.find(ns + "name").text for e in root.iter(ns + "Folder")]
    check("folder names honoured",
          "Pulses (tag 42)" in folders and "Tag" in folders, str(folders))

    box = root.iter(ns + "LatLonBox").__next__()
    north = float(box.find(ns + "north").text)
    south = float(box.find(ns + "south").text)
    check("LatLonBox encloses the points",
          south <= plat.min() and north >= plat.max(),
          "%.5f..%.5f vs %.5f..%.5f" % (south, north, plat.min(), plat.max()))
    check("kmz is compact", os.path.getsize(out) < 200_000,
          "%d bytes for %d points" % (os.path.getsize(out), n))


def main():
    print("pulseplotter_py core checks")
    test_reader()
    test_movmean()
    test_geodesy()
    test_bearing()
    test_flight_window()
    test_grid_and_kmz()
    print("\n%s" % ("ALL PASS" if not _failures
                    else "FAILURES: " + ", ".join(_failures)))
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
