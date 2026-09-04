"""Checks for the field-review primitives and the fieldreview entry point.

    python3 test_fieldreview.py

Synthetic surfaces with known answers for the primitives; a real Cumbria log
for the pipeline when FLIGHT_TESTING_DATA is reachable, a synthetic one
otherwise. The terrain checks run only when the Copernicus tile is present
under data/dem/ (dem.fetch_copernicus downloads it; nothing here does).
"""

import json
import os
import sys
import tempfile

import numpy as np

import analysis
import dem
import fieldreview
import geodesy
from readpulsetable import COLUMNS, PulseTable, read_pulse_table

DATA_ROOT = ("/Users/mws22/Library/CloudStorage/"
             "OneDrive-NorthernArizonaUniversity/FLIGHT_TESTING_DATA")
CUMBRIA = os.path.join(DATA_ROOT, "2025-11-21-Cumbria-Day5-Fri", "HERELINK_LOGS",
                       "Pulse-2025-11-21-11-08-41-149.csv")
TAG42 = (54.327254, -2.966997)

_failures = []


def check(label, ok, detail=""):
    print("  %-56s %s%s" % (label, "PASS" if ok else "FAIL",
                            ("  " + detail) if detail else ""))
    if not ok:
        _failures.append(label)


def synth_table(n=200, tag=42, confirmed=1, lat0=54.3270, lon0=-2.9700):
    """A lawnmower over a point source, as a PulseTable."""
    rng = np.random.default_rng(1)
    t = 1775188930.0 + 1.5 * np.arange(n)
    rows = np.arange(n) // 40
    along = np.where(rows % 2 == 0, np.arange(n) % 40, 39 - np.arange(n) % 40) * 10.0
    xe, yn = along, rows * 50.0
    alt = np.clip(np.minimum(np.arange(n) * 3.0, (n - 1 - np.arange(n)) * 3.0), 0, 60)
    snr = 45.0 - 0.08 * np.hypot(xe - 250.0, yn - 120.0) + 0.3 * rng.standard_normal(n)
    lat, lon, _ = geodesy.enu2geo(xe, yn, alt, (lat0, lon0, 0.0))
    m = np.zeros((n, len(COLUMNS)))
    m[:, 0] = 1
    m[:, 1] = tag
    m[:, 2] = 150e6
    m[:, 3] = t
    m[:, 4] = t + 1.5
    m[:, 5] = snr
    m[:, 6] = 0.1
    m[:, 11] = 1
    m[:, 12] = confirmed
    m[:, 13] = lat
    m[:, 14] = lon
    m[:, 15] = alt
    return PulseTable(m)


def test_select_pulses():
    print("\nselect_pulses")
    a = synth_table(100, tag=42)
    b = synth_table(50, tag=7, confirmed=0)
    t = PulseTable(np.vstack([a.as_matrix(), b.as_matrix()]))
    check("no constraints keeps everything (confirmed off)",
          analysis.select_pulses(t, confirmed_only=False).sum() == 150)
    check("confirmed only drops the unconfirmed rows",
          analysis.select_pulses(t).sum() == 100)
    check("tag filter", analysis.select_pulses(t, tag_id=7, confirmed_only=False).sum() == 50)
    t0 = t.start_time_seconds.min()
    k = analysis.select_pulses(t, tag_id=42, time_range=(t0 + 30.0, t0 + 10.0))
    check("time window, bounds in either order, inclusive",
          k.sum() == 14 and np.all(t.start_time_seconds[k] >= t0 + 10.0), str(k.sum()))
    k = analysis.select_pulses(t, tag_id=42, alt_range=(60, 60))
    check("altitude window", k.sum() > 0 and np.all(t.alt_rel[k] == 60.0), str(k.sum()))
    lat_mid = np.median(a.lat)
    k = analysis.select_pulses(t, tag_id=42, box=(lat_mid, 90.0, -180.0, 180.0))
    check("spatial box", 0 < k.sum() < 100 and np.all(t.lat[k] >= lat_mid), str(k.sum()))
    k = analysis.select_pulses(t, tag_id=42, time_range=(t0 + 10.0, t0 + 30.0),
                               alt_range=(0, 100), box=(-90, 90, -180, 180))
    check("filters combine with AND", k.sum() == 14)


def test_grid_spacing():
    print("\ngrid spacing rule")
    r, d = analysis.grid_spacing(np.arange(0, 500, 8.0), np.zeros(63))
    check("half the pulse spacing in the middle regime", abs(r - 4.0) < 1e-9 and d["rule"] == "step/2",
          "%.2f m, %s" % (r, d["rule"]))
    r, d = analysis.grid_spacing(np.arange(0, 3000, 1.0), np.zeros(3000))
    check("fine pulses over a wide extent: extent/cells_max wins",
          abs(r - 2999.0 / 300.0) < 1e-9 and d["rule"] == "extent/300", "%.2f m, %s" % (r, d["rule"]))
    r, d = analysis.grid_spacing(np.arange(0, 300, 60.0), np.zeros(5))
    check("sparse pulses over a small extent: extent/cells_min wins",
          abs(r - 4.0) < 1e-9 and d["rule"] == "extent/60", "%.2f m, %s" % (r, d["rule"]))
    r, d = analysis.grid_spacing(np.arange(0, 60, 1.5), np.zeros(40))
    check("never below the 1 m floor", r == 1.0 and d["rule"] == "floor")
    r, d = analysis.grid_spacing([0.0], [0.0])
    check("a single pulse gives the floor", r == 1.0)
    check("median spacing ignores gaps",
          abs(analysis.track_spacing([0, 10, 20, 30, 500, 510, 520], [0] * 7) - 10.0) < 1e-9)


def two_lobes(h1=40.0, h2=37.0, g=2.0):
    X, Y = np.meshgrid(np.arange(-100, 101, g), np.arange(-80, 81, g))
    z = (h1 * np.exp(-((X - 40) ** 2 + (Y - 10) ** 2) / (2 * 20 ** 2))
         + h2 * np.exp(-((X + 50) ** 2 + (Y + 20) ** 2) / (2 * 15 ** 2)))
    z[np.hypot(X, Y) > 110] = np.nan
    return X, Y, z


def test_peaks():
    print("\npeak finder")
    g = 2.0
    X, Y = np.meshgrid(np.arange(-100, 101, g), np.arange(-80, 81, g))
    z = 40 * np.exp(-((X - 30) ** 2 + (Y + 10) ** 2) / (2 * 25 ** 2))
    pk = analysis.find_peaks(X, Y, z)
    check("one lobe gives exactly one peak, at the maximum",
          len(pk) == 1 and pk[0]["x"] == 30.0 and pk[0]["y"] == -10.0, str(len(pk)))

    X, Y, z = two_lobes()
    pk = analysis.find_peaks(X, Y, z)
    check("two lobes give two peaks, tallest first",
          len(pk) == 2 and pk[0]["value"] > pk[1]["value"]
          and (pk[0]["x"], pk[0]["y"]) == (40.0, 10.0)
          and (pk[1]["x"], pk[1]["y"]) == (-50.0, -20.0))
    # The saddle between two isotropic Gaussians lies on the line joining
    # their centres; the prominence must equal the second peak minus it.
    s = np.linspace(0, 1, 2001)
    xs, ys = 40 + s * (-50 - 40), 10 + s * (-20 - 10)
    line = (40 * np.exp(-((xs - 40) ** 2 + (ys - 10) ** 2) / (2 * 20 ** 2))
            + 37 * np.exp(-((xs + 50) ** 2 + (ys + 20) ** 2) / (2 * 15 ** 2)))
    expected = pk[1]["value"] - line.min()
    check("prominence equals height above the connecting saddle",
          abs(pk[1]["prominence"] - expected) < 0.05,
          "%.3f vs %.3f dB" % (pk[1]["prominence"], expected))
    check("second peak reports its offset from the first",
          abs(pk[1]["distance_m"] - np.hypot(90, 30)) < 1e-6 and abs(pk[1]["below_db"] - 3.0) < 0.05)
    check("parent of the second peak is the first",
          analysis.peak_prominence(z)[1]["parent"] == 0)

    X, Y, z = two_lobes(h2=34.0)
    check("a lobe 6 dB down is excluded at 3 dB and kept at 6 dB",
          len(analysis.find_peaks(X, Y, z, within_db=3.0)) == 1
          and len(analysis.find_peaks(X, Y, z, within_db=6.0)) == 2)

    rng = np.random.default_rng(3)
    X, Y, z = two_lobes(h2=0.0)
    zn = z + 0.3 * rng.standard_normal(z.shape)
    n_all = len(analysis.peak_prominence(zn))
    pk = analysis.find_peaks(X, Y, zn)
    check("noise wrinkles do not become lobes (%d local maxima)" % n_all,
          n_all > 10 and len(pk) == 1, str(len(pk)))

    X, Y, z = two_lobes()
    pk = analysis.find_peaks(X, Y, z, min_separation=200.0)
    check("min_separation suppresses a nearby lobe", len(pk) == 1)
    pk = analysis.find_peaks(X, Y, z, max_peaks=1)
    check("max_peaks caps the list", len(pk) == 1 and pk[0]["rank"] == 0)
    check("empty grid gives no peaks",
          analysis.find_peaks(X, Y, np.full_like(z, np.nan)) == []
          and analysis.find_peaks(X, Y, None) == [])
    X2, Y2 = np.meshgrid(np.arange(0, 5.0), np.arange(0, 5.0))
    flat = np.full((5, 5), 3.0)
    pk = analysis.find_peaks(X2, Y2, flat)
    check("a flat surface gives one peak, not twenty-five", len(pk) == 1)

    X, Y, z = two_lobes(h2=0.0)
    inside = analysis.find_peaks(X, Y, z)[0]
    z_cut = z.copy()
    z_cut[X > 40] = np.nan                     # survey stops at the summit
    edge = analysis.find_peaks(X, Y, z_cut)[0]
    check("a peak inside the data is not on the edge, one at the cut is",
          not inside["on_edge"] and edge["on_edge"])


def test_contours():
    print("\ncontour extraction")
    g = 1.0
    X, Y = np.meshgrid(np.arange(-60, 61, g), np.arange(-60, 61, g))
    z = -np.hypot(X, Y)
    z[np.hypot(X, Y) > 58] = np.nan
    out = analysis.contour_polylines(X, Y, z, [-40.0, -20.0])
    check("one polyline per level on a cone", len(out) == 2 and all(len(p) == 1 for _, p in out))
    worst = 0.0
    closed = True
    for level, lines in out:
        for line in lines:
            worst = max(worst, float(np.abs(np.hypot(line[:, 0], line[:, 1]) + level).max()))
            closed &= bool(np.allclose(line[0], line[-1]))
    check("every vertex sits on its level to within a cell", worst < 1.0, "%.2f m" % worst)
    check("loops inside the hull are closed", closed)
    out = analysis.contour_polylines(X, Y, z, 6)
    lev = analysis.contour_levels(z, 6)
    check("an integer asks for nice levels inside the range",
          len(out) == len(lev) and 4 <= len(lev) <= 8 and lev.min() > np.nanmin(z)
          and lev.max() < np.nanmax(z), "%d levels" % len(lev))
    check("lines stop at the edge of the data",
          all(np.all(np.isfinite(l)) for _, ls in out for l in ls))
    check("nothing from an empty grid",
          analysis.contour_polylines(X, Y, None, 5) == []
          and analysis.contour_polylines(X, Y, np.full_like(z, np.nan), 5) == [])


def test_kmz_uses_shared_contours():
    print("\nkmzwrite")
    import zipfile
    from kmzwrite import kmzwrite
    g = 5.0
    X, Y = np.meshgrid(np.arange(-100, 101, g), np.arange(-100, 101, g))
    z = -np.hypot(X, Y)
    home = (54.33, -2.97, 0.0)
    lat, lon, _ = geodesy.enu2geo(X, Y, np.zeros_like(X), home)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.kmz")
        kmzwrite(path, point_lat=lat[::4, ::4].ravel(), point_lon=lon[::4, ::4].ravel(),
                 point_alt=np.zeros(lat[::4, ::4].size), point_value=z[::4, ::4].ravel(),
                 grid_lat=lat, grid_lon=lon, grid_value=z, contour_levels=6)
        with zipfile.ZipFile(path) as zf:
            kml = zf.read("doc.kml").decode("utf-8")
    n = kml.count("<LineString>")
    check("KMZ still carries contour lines through the shared routine", n >= 4, "%d lines" % n)


def test_terrain():
    print("\nterrain")
    z = np.zeros((41, 41))
    lat0, lon0 = 54.33, -2.97
    r_m, r_n = geodesy.earth_radii(lat0)
    dlat = -np.degrees(10.0 / r_m)
    dlon = np.degrees(10.0 / (r_n * np.cos(np.radians(lat0))))
    rows, cols = np.mgrid[0:41, 0:41]
    z = 100.0 + 0.1 * (cols - 20) * 10.0 - 0.05 * (20 - rows) * 10.0   # rises east, falls north
    d = dem.Dem(z, lat0, lon0, dlat, dlon)
    e = d.elevation(lat0, lon0)
    check("bilinear sampling hits a cell centre exactly", abs(e - z[0, 0]) < 1e-9, "%.3f" % e)
    s = d.slope(lat0 + 20 * dlat, lon0 + 20 * dlon, radius_m=45)
    # The cell spacing was defined at lat0 and the fit converts at the query
    # latitude 200 m south, so agreement is to a few parts in 1e5, not exact.
    check("plane fit recovers the gradient", abs(s["dz_de"] - 0.1) < 1e-4 and abs(s["dz_dn"] + 0.05) < 1e-4,
          "%.3f %.3f" % (s["dz_de"], s["dz_dn"]))
    want = np.degrees(np.arctan2(-0.1, 0.05)) % 360
    check("downhill direction is compass degrees",
          abs(s["downhill_deg"] - want) < 0.01, "%.1f" % s["downhill_deg"])
    check("outside the raster is NaN", np.isnan(d.elevation(0.0, 0.0)))
    check("tile naming follows the south-west corner",
          dem.copernicus_tile_name(54.33, -2.97) == "N54_00_W003_00"
          and dem.copernicus_tile_name(-36.88, 175.18) == "S37_00_E175_00")
    tile = os.path.join(dem.DATA_DIR, "Copernicus_DSM_COG_10_N54_00_W003_00_DEM.tif")
    if os.path.exists(tile):
        c = dem.read_geotiff(tile)
        cf = c.elevation(54.7034, -2.4854)      # Cross Fell, 893 m
        sea = c.elevation(54.10, -2.95)         # Morecambe Bay
        check("Copernicus tile: Cross Fell and the sea", abs(cf - 893) < 25 and abs(sea) < 3,
              "%.0f m, %.1f m" % (cf, sea))
    else:
        print("  (Copernicus tile not present; skipped)")


def test_review():
    print("\nfieldreview pipeline")
    if os.path.exists(CUMBRIA):
        table, _ = read_pulse_table(CUMBRIA)
        r = fieldreview.review(table, tag_id=42, truth=TAG42)
        check("Cumbria tag 42: a surface, a bearing and a peak",
              r["arrays"]["grid"] is not None and np.isfinite(r["bearing"]["deg"]) and r["peaks"])
        p = r["peaks"][0]
        check("the strongest signal is within 60 m of the true tag",
              p["truth_distance_m"] < 60.0, "%.0f m" % p["truth_distance_m"])
        check("the default window is the flight proper",
              "trimmed" in r["filter"]["time_note"] and r["n_selected"] < r["n_tag"])
        check("grid spacing came from the data",
              r["grid"]["rule"] == "step/2" and 3.0 <= r["grid"]["res_m"] <= 8.0,
              "%.1f m" % r["grid"]["res_m"])
        r2 = fieldreview.review(table, tag_id=42, box=(54.3265, 54.3285, -2.9700, -2.9640))
        check("a spatial box cuts the selection", 0 < r2["n_selected"] < r["n_selected"])
        r3 = fieldreview.review(table, tag_id=42, grid_res=10.0)
        check("a requested spacing is honoured", r3["grid"]["res_m"] == 10.0 and r3["grid"]["rule"] == "requested")
        dp = np.hypot(r3["peaks"][0]["x"] - p["x"], r3["peaks"][0]["y"] - p["y"])
        check("the peak barely moves with the grid (interpolant maxima sit on pulses)",
              dp < 15.0, "%.0f m between 5 m and 10 m grids" % dp)
    else:
        table = synth_table()
        print("  (Cumbria log not reachable; synthetic lawnmower)")
        truth_lat, truth_lon, _ = geodesy.enu2geo(250.0, 120.0, 0.0, (54.3270, -2.9700, 0.0))
        r = fieldreview.review(table, truth=(float(truth_lat), float(truth_lon)))
        check("synthetic: peak within one transect spacing of the source",
              r["peaks"] and r["peaks"][0]["truth_distance_m"] < 50.0)
    text = fieldreview.report(r, "log")
    check("the report carries the caveat", fieldreview.CAVEAT in text)
    check("positions are decimal degrees to five places",
          fieldreview.fmt_latlon(1.23456789, -2.1) == "1.23457, -2.10000")
    js = json.dumps(fieldreview.to_json(r))
    check("result serialises to JSON without its arrays", "arrays" not in js and "peaks" in js)
    import matplotlib
    matplotlib.use("Agg")
    fig = fieldreview.plot_review(r)
    check("figure draws", fig is not None)
    import matplotlib.pyplot as plt
    plt.close(fig)
    empty = fieldreview.review(table, tag_id=99999)
    check("an unknown tag gives no surface and says so",
          empty["arrays"]["grid"] is None and "No surface" in fieldreview.report(empty))


def main():
    test_select_pulses()
    test_grid_spacing()
    test_peaks()
    test_contours()
    test_kmz_uses_shared_contours()
    test_terrain()
    test_review()
    print()
    if _failures:
        print("FAILED: %d check(s):" % len(_failures))
        for f in _failures:
            print("  - " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
