#!/usr/bin/env python3
"""Validate the field-review prototype against flights with a known tag position.

Answers the four questions FIELD_REVIEW.md section 6 asks of the prototype,
with numbers rather than opinions:

  1. grid spacing: what the rule chooses across every dataset on disk, and
     how far the peak and bearing move when the spacing is changed
  2. contours at small scale: a raster-only and a raster-plus-contours
     rendering at roughly the size of a 7-inch screen
  3. two lobes: what the peak finder reports on a surface with two
  4. against truth: how far the reported peak is from the real tag on
     Cumbria (four tags, two sites) and Ponui (two kiwi), and whether it
     sits downhill of it, from a terrain model

Writes into DOCS/figures/: fieldreview-*.pdf and .png figures, a results JSON,
and LaTeX table fragments that fieldreview-prototype.tex includes, so the
numbers in the document are the numbers the code produced.

    python validate_fieldreview.py            # everything
    python validate_fieldreview.py --no-dem   # skip terrain (no network needed)

Needs the logs under FLIGHT_TESTING_DATA and, for terrain, the DEM rasters
(downloaded on first use into data/dem/, see dem.py).
"""

import argparse
import glob
import json
import os
import sys
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import analysis
import dem
import fieldreview
import geodesy
from readpulsetable import read_pulse_table

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "DOCS", "figures")
DATA = os.path.expanduser(
    "~/Library/CloudStorage/OneDrive-NorthernArizonaUniversity/FLIGHT_TESTING_DATA")

# ---- ground truth -----------------------------------------------------------
# Cumbria, 21 Nov 2025: from the PI's Tag42_Above_60m_PROCESS.m beside the
# logs. Tags 40 and 41 share one site, 42 and 43 the other.
CUMBRIA_LAUNCH = (54.327994, -2.970637)
TAG40 = (54.326601, -2.9684094)
TAG42 = (54.327254, -2.966997)
# Ponui, March 2025: the two kiwi of Mohammadi 2026 sections 5.2 and 5.3,
# positions from the PI's field notebook (4 Sep 2026). Case 1 was found under
# a bush and may have moved during the day; the position is certain for the
# last flight. Case 2 was in a burrow.
KIWI1 = (-36.887851, 175.184943)
KIWI2 = (-36.886383, 175.178570)

CUMB = os.path.join(DATA, "2025-11-21-Cumbria-Day5-Fri", "HERELINK_LOGS")
PON5 = os.path.join(DATA, "2025-03-20-Ponui-Day5-Thur", "HERELINK LOGS", "TagTracker Daily", "Logs")
PON8 = os.path.join(DATA, "2025-03-23-Ponui-Day8-Sun", "HERELINK_LOGS", "TagTracker Daily", "Logs")

CASES = [
    # key, label, log, tag, truth, dem source
    ("cumbria-t42", "Cumbria 11:08, tag 42", os.path.join(CUMB, "Pulse-2025-11-21-11-08-41-149.csv"), 42, TAG42, "ea"),
    ("cumbria-t43", "Cumbria 11:08, tag 43", os.path.join(CUMB, "Pulse-2025-11-21-11-08-41-149.csv"), 43, TAG42, "ea"),
    ("cumbria-t40", "Cumbria 11:08, tag 40", os.path.join(CUMB, "Pulse-2025-11-21-11-08-41-149.csv"), 40, TAG40, "ea"),
    ("cumbria-t41", "Cumbria 11:08, tag 41", os.path.join(CUMB, "Pulse-2025-11-21-11-08-41-149.csv"), 41, TAG40, "ea"),
    ("cumbria-0935-t42", "Cumbria 09:35, tag 42", os.path.join(CUMB, "Pulse-2025-11-21-09-35-00-804.csv"), 42, TAG42, "ea"),
    ("cumbria-0935-t40", "Cumbria 09:35, tag 40", os.path.join(CUMB, "Pulse-2025-11-21-09-35-00-804.csv"), 40, TAG40, "ea"),
    ("cumbria-1305-t42", "Cumbria 13:05, tag 42", os.path.join(CUMB, "Pulse-2025-11-21-13-05-56-134.csv"), 42, TAG42, "ea"),
    ("cumbria-1305-t40", "Cumbria 13:05, tag 40", os.path.join(CUMB, "Pulse-2025-11-21-13-05-56-134.csv"), 40, TAG40, "ea"),
    ("cumbria-1412-t42", "Cumbria 14:12, tag 42", os.path.join(CUMB, "Pulse-2025-11-21-14-12-30-177.csv"), 42, TAG42, "ea"),
    ("cumbria-1412-t40", "Cumbria 14:12, tag 40", os.path.join(CUMB, "Pulse-2025-11-21-14-12-30-177.csv"), 40, TAG40, "ea"),
    ("ponui-c1-f1", "Ponui case 1, flight 1", os.path.join(PON5, "Pulse-2025-03-19-20-43-41-207.csv"), 12, KIWI1, "cop"),
    ("ponui-c1-f2", "Ponui case 1, flight 2", os.path.join(PON5, "Pulse-2025-03-19-21-11-08-338.csv"), 12, KIWI1, "cop"),
    ("ponui-c1-f3", "Ponui case 1, flight 3", os.path.join(PON5, "Pulse-2025-03-19-23-13-47-865.csv"), 12, KIWI1, "cop"),
    ("ponui-c1-f4", "Ponui case 1, flight 4", os.path.join(PON5, "Pulse-2025-03-19-23-34-26-893.csv"), 12, KIWI1, "cop"),
    ("ponui-c2-f1", "Ponui case 2, flight 1", os.path.join(PON8, "Pulse-2025-03-22-21-22-49-155.csv"), 24, KIWI2, "cop"),
    ("ponui-c2-f2", "Ponui case 2, flight 2", os.path.join(PON8, "Pulse-2025-03-22-21-39-27-783.csv"), 24, KIWI2, "cop"),
    ("ponui-c2-f3", "Ponui case 2, flight 3", os.path.join(PON8, "Pulse-2025-03-22-22-09-11-170.csv"), 24, KIWI2, "cop"),
]
FIGURE_CASES = ["cumbria-t42", "cumbria-t40", "cumbria-t41", "cumbria-t43",
                "ponui-c1-f1", "ponui-c1-f2", "ponui-c1-f3", "ponui-c1-f4",
                "ponui-c2-f1", "ponui-c2-f2", "ponui-c2-f3"]
SENSITIVITY_CASES = ["cumbria-t42", "cumbria-t40", "ponui-c2-f3", "ponui-c1-f4"]

# Logs without truth, for the grid-spacing survey and the timing.
SPACING_LOGS = [
    ("Cumbria 09:35 (largest survey)", os.path.join(CUMB, "Pulse-2025-11-21-09-35-00-804.csv"), 42),
    ("Cumbria 11:08", os.path.join(CUMB, "Pulse-2025-11-21-11-08-41-149.csv"), 42),
    ("Ponui case 2 flight 3", os.path.join(PON8, "Pulse-2025-03-22-22-09-11-170.csv"), 24),
    ("Ponui case 1 flight 4", os.path.join(PON5, "Pulse-2025-03-19-23-34-26-893.csv"), 12),
    ("Raymond Park scan 2025-01-13", os.path.join(DATA, "2025-01-13-Raymond Park Scan Flights", "Pulse-2025-01-13-15-56-01-556.csv"), 6),
    ("Engineering lawn lawnmower 2025-01-03", os.path.join(DATA, "2025-01-03-Egr_Lawn_Mower_Scan_with_Hanging_Monopole", "Pulse-2025-01-03-22-26-36-149.csv"), 6),
    ("Raymond Park monopole 2024-10-11", os.path.join(DATA, "2024-10-11-Ramond_Park_Monopole_Testing", "HERELINK CONTROLLER LOGS", "Pulse Log Files", "Pulse-2024-10-11-15-25-35-497.csv"), 4),
    ("NAVHDA 2023-08-18 (1 km, headerless)", os.path.join(DATA, "2023-08-18-NAVHDA Site", "Pulse-2023-08-18-16-04-59-715.csv"), 2),
]

FIG = (7.2, 5.4)


def tex_escape(s):
    return str(s).replace("_", "\\_").replace("%", "\\%").replace("&", "\\&")


def fmt(v, spec="%.0f", nan="--"):
    try:
        if v is None or not np.isfinite(v):
            return nan
    except TypeError:
        return str(v)
    return spec % v


def write_tex_table(path, header, rows, align):
    with open(path, "w") as fh:
        fh.write("\\begin{tabular}{%s}\n\\toprule\n" % align)
        fh.write(" & ".join(header) + " \\\\\n\\midrule\n")
        for r in rows:
            fh.write(" & ".join(r) + " \\\\\n")
        fh.write("\\bottomrule\n\\end{tabular}\n")


def get_dem(kind, cache, no_dem):
    if no_dem:
        return None
    if kind in cache:
        return cache[kind]
    try:
        if kind == "ea":
            d = dem.fetch_ea_dtm(54.3225, 54.3345, -2.9800, -2.9550, "cumbria_day5")
        else:
            d = dem.fetch_copernicus(-36.885, 175.18)
    except Exception as exc:                          # noqa: BLE001
        print("  terrain unavailable (%s): %s" % (kind, exc))
        d = None
    cache[kind] = d
    return d


def terrain_check(result, d):
    """Elevation of truth and peak, slope at truth, and the downhill component
    of the offset (positive = the peak is on the downhill side of the tag)."""
    out = dict(z_truth=np.nan, z_peak=np.nan, dz=np.nan, slope_deg=np.nan,
               downhill_deg=np.nan, downhill_m=np.nan, source="")
    if d is None or not result["peaks"] or result["truth"] is None:
        return out
    t = result["truth"]
    p = result["peaks"][0]
    radius = 25.0 if d.cell_size_m()[0] < 5 else 60.0
    s = d.slope(t["lat"], t["lon"], radius_m=radius)
    zt = d.elevation(t["lat"], t["lon"])
    zp = d.elevation(p["lat"], p["lon"])
    out.update(z_truth=float(zt), z_peak=float(zp), dz=float(zp - zt),
               slope_deg=s["slope_deg"], downhill_deg=s["downhill_deg"], source=d.source)
    if np.isfinite(s["downhill_deg"]):
        dx, dy = p["x"] - t["x"], p["y"] - t["y"]
        ux, uy = np.sin(np.radians(s["downhill_deg"])), np.cos(np.radians(s["downhill_deg"]))
        out["downhill_m"] = float(dx * ux + dy * uy)
    return out


def run_cases(args, dem_cache):
    results = {}
    tables = []
    print("cases")
    for key, label, log, tag, truth, dkind in CASES:
        if not os.path.exists(log):
            print("  %-34s missing log" % label)
            continue
        table, _ = read_pulse_table(log)
        t0 = time.perf_counter()
        r = fieldreview.review(table, tag_id=tag, truth=truth)
        elapsed = time.perf_counter() - t0
        terr = terrain_check(r, get_dem(dkind, dem_cache, args.no_dem))
        p = r["peaks"][0] if r["peaks"] else None
        q = r.get("quality", {})
        row = dict(key=key, label=label, log=os.path.basename(log), tag=tag,
                   n_selected=r["n_selected"], n_tag=r["n_tag"],
                   grid_m=r["grid"]["res_m"], cells=r["grid"]["cells"], seconds=elapsed,
                   peak_lat=p["lat"] if p else np.nan, peak_lon=p["lon"] if p else np.nan,
                   peak_snr=q.get("peak_snr_db", np.nan), contrast=q.get("contrast_db", np.nan),
                   weak=q.get("weak", True), on_edge=bool(p and p.get("on_edge")),
                   lobes=len(r["peaks"]),
                   offset_m=p["truth_distance_m"] if p else np.nan,
                   offset_dir=p["truth_bearing_deg"] if p else np.nan,
                   bearing=r["bearing"]["deg"], confidence=r["bearing"]["confidence"],
                   bearing_true=r["truth"].get("bearing_true_deg", np.nan) if r["truth"] else np.nan,
                   bearing_err=r["truth"].get("bearing_error_deg", np.nan) if r["truth"] else np.nan,
                   truth=list(truth), **terr)
        results[key] = row
        print("  %-34s %4d pulses  peak %5.1f dB  contrast %4.1f dB  offset %4.0f m to %3s"
              "  dz %+5.1f m  downhill %+5.0f m  bearing err %+4.0f deg  lobes %d%s%s"
              % (label, row["n_selected"], row["peak_snr"], row["contrast"], row["offset_m"],
                 fieldreview.compass_name(row["offset_dir"]), row["dz"], row["downhill_m"],
                 row["bearing_err"], row["lobes"], "  WEAK" if row["weak"] else "",
                 "  EDGE" if row["on_edge"] else ""))
        if key in FIGURE_CASES:
            fig = fieldreview.plot_review(r)
            for ext in ("pdf", "png"):
                fig.savefig(os.path.join(OUT, "fieldreview-%s.%s" % (key, ext)), dpi=150)
            plt.close(fig)
        if key == "cumbria-t42":
            with open(os.path.join(OUT, "fieldreview-report-t42.txt"), "w") as fh:
                fh.write(fieldreview.report(r, os.path.basename(log)))
        if key == "cumbria-t40":
            with open(os.path.join(OUT, "fieldreview-report-t40.txt"), "w") as fh:
                fh.write(fieldreview.report(r, os.path.basename(log)))
        tables.append(row)

    header = ["Case", "Pulses", "Peak SNR", "Contrast", "Offset", "Dir.", "$\\Delta z$",
              "Downhill", "Bearing err.", "Lobes"]
    rows = []
    for row in tables:
        flag = ""
        if row["weak"]:
            flag = " (weak)"
        elif row["on_edge"]:
            flag = " (edge)"
        rows.append([tex_escape(row["label"]) + flag, "%d" % row["n_selected"],
                     fmt(row["peak_snr"], "%.0f dB"), fmt(row["contrast"], "%.0f dB"),
                     fmt(row["offset_m"], "%.0f m"),
                     fieldreview.compass_name(row["offset_dir"]),
                     fmt(row["dz"], "%+.0f m"), fmt(row["downhill_m"], "%+.0f m"),
                     fmt(row["bearing_err"], "%+.0f$^\\circ$"), "%d" % row["lobes"]])
    write_tex_table(os.path.join(OUT, "fieldreview-table-cases.tex"), header, rows, "lrrrrrrrrr")
    return results


def run_spacing(args):
    print("\ngrid spacing across datasets")
    rows, out = [], []
    for label, log, tag in SPACING_LOGS:
        if not os.path.exists(log):
            print("  %-40s missing" % label)
            continue
        table, _ = read_pulse_table(log)
        t0 = time.perf_counter()
        r = fieldreview.review(table, tag_id=tag)
        dt = time.perf_counter() - t0
        g = r["grid"]
        print("  %-40s extent %4.0f x %4.0f m  step %5.1f m  grid %4.1f m (%s)  %6d cells  %.2f s"
              % (label, g["extent_e_m"], g["extent_n_m"], g["step_m"], g["res_m"], g["rule"],
                 g["cells"], dt))
        rows.append([tex_escape(label), "%d" % r["n_selected"],
                     "%.0f $\\times$ %.0f" % (g["extent_e_m"], g["extent_n_m"]),
                     "%.1f" % g["step_m"], "%.1f" % g["res_m"], tex_escape(g["rule"]),
                     "%d" % g["cells"], "%.2f" % dt])
        out.append(dict(label=label, extent_e=g["extent_e_m"], extent_n=g["extent_n_m"],
                        step=g["step_m"], res=g["res_m"], rule=g["rule"], cells=g["cells"],
                        seconds=dt))
    write_tex_table(os.path.join(OUT, "fieldreview-table-spacing.tex"),
                    ["Dataset", "Pulses", "Extent (m)", "Step (m)", "Grid (m)", "Bound", "Cells", "Time (s)"],
                    rows, "lrrrrlrr")
    return out


def run_sensitivity(args):
    print("\nsensitivity of the peak and bearing to grid spacing and smoothing")
    factors = [0.5, 1.0, 2.0, 4.0]
    fixed = [5.0, 10.0, 20.0]
    smooths = [1, 3, 6, 12]
    out = {}
    rows = []
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), layout="constrained")
    for key, label, log, tag, truth, _ in CASES:
        if key not in SENSITIVITY_CASES or not os.path.exists(log):
            continue
        table, _ = read_pulse_table(log)
        base = fieldreview.review(table, tag_id=tag, truth=truth)
        p0 = base["peaks"][0]
        b0 = base["bearing"]["deg"]
        rule = base["grid"]["rule_m"]
        rec = dict(rule_m=rule, grid=[], smooth=[])
        for f in factors:
            r = fieldreview.review(table, tag_id=tag, truth=truth, grid_res=rule * f)
            p = r["peaks"][0]
            rec["grid"].append(dict(res=r["grid"]["res_m"], factor=f,
                                    shift=float(np.hypot(p["x"] - p0["x"], p["y"] - p0["y"])),
                                    bearing_shift=float(fieldreview.wrap180(r["bearing"]["deg"] - b0)),
                                    offset=p["truth_distance_m"], lobes=len(r["peaks"])))
        for res in fixed:
            if any(abs(d["res"] - res) < 0.06 * res for d in rec["grid"]):
                continue
            r = fieldreview.review(table, tag_id=tag, truth=truth, grid_res=res)
            p = r["peaks"][0]
            rec["grid"].append(dict(res=res, factor=np.nan,
                                    shift=float(np.hypot(p["x"] - p0["x"], p["y"] - p0["y"])),
                                    bearing_shift=float(fieldreview.wrap180(r["bearing"]["deg"] - b0)),
                                    offset=p["truth_distance_m"], lobes=len(r["peaks"])))
        for s in smooths:
            r = fieldreview.review(table, tag_id=tag, truth=truth, smooth=s)
            p = r["peaks"][0]
            rec["smooth"].append(dict(smooth=s,
                                      shift=float(np.hypot(p["x"] - p0["x"], p["y"] - p0["y"])),
                                      bearing_shift=float(fieldreview.wrap180(r["bearing"]["deg"] - b0)),
                                      offset=p["truth_distance_m"], lobes=len(r["peaks"])))
        out[key] = rec
        gs = sorted(rec["grid"], key=lambda d: d["res"])
        axes[0].plot([d["res"] for d in gs], [d["offset"] for d in gs], "o-", ms=4, label=label)
        axes[1].plot([d["smooth"] for d in rec["smooth"]], [d["offset"] for d in rec["smooth"]],
                     "o-", ms=4, label=label)
        print("  %-28s rule %.1f m | grid: " % (label, rule)
              + " ".join("%.1fm->%.0fm/%+.0fdeg" % (d["res"], d["offset"], d["bearing_shift"]) for d in gs)
              + " | smooth: " + " ".join("%d->%.0fm/%+.0fdeg" % (d["smooth"], d["offset"], d["bearing_shift"])
                                          for d in rec["smooth"]))
        for d in gs:
            rows.append([tex_escape(label), "%.1f" % d["res"],
                         "rule $\\times$ %g" % d["factor"] if np.isfinite(d["factor"]) else "fixed",
                         "%.0f" % d["shift"], "%+.0f" % d["bearing_shift"], "%.0f" % d["offset"],
                         "%d" % d["lobes"]])
    from matplotlib.ticker import FixedLocator, NullLocator, ScalarFormatter
    axes[0].set_xlabel("grid spacing (m)")
    axes[0].set_ylabel("peak to truth (m)")
    axes[0].set_xscale("log")
    axes[0].xaxis.set_major_locator(FixedLocator([1, 2, 5, 10, 20]))
    axes[0].xaxis.set_minor_locator(NullLocator())
    axes[0].xaxis.set_major_formatter(ScalarFormatter())
    axes[0].set_title("grid spacing", fontsize=9)
    axes[1].set_xlabel("smoothing window (pulses)")
    axes[1].set_title("smoothing", fontsize=9)
    for ax in axes:
        ax.grid(True, lw=0.3, alpha=0.5)
        ax.tick_params(labelsize=8)
    axes[1].legend(fontsize=6.5)
    fig.savefig(os.path.join(OUT, "fieldreview-sensitivity.pdf"))
    fig.savefig(os.path.join(OUT, "fieldreview-sensitivity.png"), dpi=150)
    plt.close(fig)
    write_tex_table(os.path.join(OUT, "fieldreview-table-sensitivity.tex"),
                    ["Case", "Grid (m)", "", "Peak shift (m)", "Bearing shift", "Offset (m)", "Lobes"],
                    rows, "lrlrrrr")
    return out


def run_contours_small(args):
    """Raster alone versus raster plus contours at about 7-inch-screen size."""
    print("\ncontours at small scale")
    log = os.path.join(CUMB, "Pulse-2025-11-21-11-08-41-149.csv")
    if not os.path.exists(log):
        return
    table, _ = read_pulse_table(log)
    r = fieldreview.review(table, tag_id=42, truth=TAG42)
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.6), layout="constrained")
    for ax, with_contours in zip(axes, (False, True)):
        saved = r["contours"]
        if not with_contours:
            r["contours"] = []
        fieldreview.plot_review(r, ax=ax, legend=False,
                                title="raster + contours" if with_contours else "raster only")
        r["contours"] = saved
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(labelsize=5)
    # plot_review adds a colorbar per axes; remove them so both panels share the space.
    for cb in [a for a in fig.axes if a not in axes]:
        cb.remove()
    fig.savefig(os.path.join(OUT, "fieldreview-contours-small.pdf"))
    fig.savefig(os.path.join(OUT, "fieldreview-contours-small.png"), dpi=200)
    plt.close(fig)
    print("  written")


def run_lobes(args):
    """A real two-lobe surface: Cumbria tags 40 and 42 are on different
    frequencies 100 m apart; feeding their pulses to the review as one tag
    is what a log with two transmitters on one channel, or a strong
    reflection, would look like."""
    print("\ntwo lobes")
    log = os.path.join(CUMB, "Pulse-2025-11-21-11-08-41-149.csv")
    if not os.path.exists(log):
        return None
    table, _ = read_pulse_table(log)
    m = table.as_matrix()
    both = (m[:, 1] == 40) | (m[:, 1] == 42)
    m = m[both]
    m[:, 1] = 4042
    from readpulsetable import PulseTable
    merged = PulseTable(m)
    r = fieldreview.review(merged, tag_id=4042)
    fig = fieldreview.plot_review(r, title="tags 40 and 42 merged into one: two lobes")
    ax = fig.axes[0]
    ax.plot(TAG40[1], TAG40[0], "X", ms=10, mfc="lime", mec="k", label="tag 40 site")
    ax.plot(TAG42[1], TAG42[0], "X", ms=10, mfc="cyan", mec="k", label="tag 42 site")
    ax.legend(fontsize=7, loc="upper right", framealpha=0.85)
    fig.savefig(os.path.join(OUT, "fieldreview-lobes.pdf"))
    fig.savefig(os.path.join(OUT, "fieldreview-lobes.png"), dpi=150)
    plt.close(fig)
    with open(os.path.join(OUT, "fieldreview-report-lobes.txt"), "w") as fh:
        fh.write(fieldreview.report(r, "tags 40+42 merged"))
    out = [dict(rank=p["rank"], lat=p["lat"], lon=p["lon"], value=p["value"],
                prominence=p["prominence"], below_db=p["below_db"], distance_m=p["distance_m"])
           for p in r["peaks"]]
    for p in out:
        print("  lobe %d: %.5f, %.5f  %.1f dB  prominence %.1f dB  %.0f m from the first"
              % (p["rank"] + 1, p["lat"], p["lon"], p["value"], p["prominence"], p["distance_m"]))
    all_maxima = analysis.peak_prominence(r["arrays"]["grid"])
    print("  %d local maxima on the surface, %d reported" % (len(all_maxima), len(out)))
    return dict(peaks=out, local_maxima=len(all_maxima))


def run_lobe_sweep(args):
    """How many lobes each case reports as the two thresholds vary, to show
    what the chosen defaults trade off."""
    print("\nlobe rule sweep")
    combos = [(3, 1), (6, 1), (6, 2), (10, 1), (10, 2), (10, 3), (15, 3)]
    log = os.path.join(CUMB, "Pulse-2025-11-21-11-08-41-149.csv")
    if not os.path.exists(log):
        return None
    from readpulsetable import PulseTable
    table, _ = read_pulse_table(log)
    m = table.as_matrix()
    m = m[(m[:, 1] == 40) | (m[:, 1] == 42)]
    m[:, 1] = 4042
    entries = [(k, l, lg, t) for k, l, lg, t, _, _ in CASES]
    entries.append(("merged", "Cumbria 11:08, tags 40+42 merged", None, 4042))
    rows, out = [], []
    header = ["Case", "Contrast"] + ["%d / %d" % c for c in combos]
    for k, l, lg, t in entries:
        if lg is not None and not os.path.exists(lg):
            continue
        tb = PulseTable(m) if lg is None else read_pulse_table(lg)[0]
        r = fieldreview.review(tb, tag_id=t)
        A = r["arrays"]
        if A["grid"] is None:
            continue
        counts = [len(analysis.find_peaks(A["X"], A["Y"], A["grid"], within_db=w,
                                          min_prominence=p, max_peaks=99))
                  for w, p in combos]
        c = r["quality"]["contrast_db"]
        flag = " (weak)" if r["quality"]["weak"] else ""
        rows.append([tex_escape(l) + flag, "%.0f dB" % c] + ["%d" % n for n in counts])
        out.append(dict(key=k, label=l, contrast=c, counts=dict(zip(["%d/%d" % c_ for c_ in combos], counts))))
        print("  %-36s %5.1f dB  " % (l, c) + " ".join("%3d" % n for n in counts))
    write_tex_table(os.path.join(OUT, "fieldreview-table-lobes.tex"), header, rows,
                    "lr" + "r" * len(combos))
    return out


def run_terrain_profiles(args, results, dem_cache):
    """Elevation along the line from the true tag through the reported peak."""
    print("\nterrain profiles")
    keys = ["cumbria-t42", "cumbria-t40", "ponui-c2-f3", "ponui-c1-f4"]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.4), layout="constrained")
    n = 0
    for ax, key in zip(axes.ravel(), keys):
        row = results.get(key)
        if row is None or not np.isfinite(row["peak_lat"]):
            ax.set_visible(False)
            continue
        d = dem_cache.get("ea" if key.startswith("cumbria") else "cop")
        if d is None:
            ax.set_visible(False)
            continue
        tlat, tlon = row["truth"]
        home = (tlat, tlon, 0.0)
        pe, pn, _ = geodesy.geo2enu(row["peak_lat"], row["peak_lon"], 0.0, home)
        L = max(float(np.hypot(pe, pn)), 20.0)
        ux, uy = pe / L, pn / L
        s = np.linspace(-1.5 * L, 2.5 * L, 200)
        la, lo, _ = geodesy.enu2geo(s * ux, s * uy, 0.0, home)
        z = d.elevation(la, lo)
        ax.plot(s, z, color="0.3")
        ax.plot(0, d.elevation(tlat, tlon), "X", ms=9, mfc="lime", mec="k", label="true tag")
        ax.plot(L, d.elevation(row["peak_lat"], row["peak_lon"]), "*", ms=13, mfc="white", mec="red",
                mew=1.6, label="strongest signal")
        ax.set_title("%s: %s, %.0f m %s" % (row["label"], d.source.split()[0], L,
                                            fieldreview.compass_name(row["offset_dir"])), fontsize=8)
        ax.set_xlabel("distance from the tag along the line to the peak (m)", fontsize=7)
        ax.set_ylabel("elevation (m)", fontsize=7)
        ax.tick_params(labelsize=7)
        ax.grid(True, lw=0.3, alpha=0.5)
        if n == 0:
            ax.legend(fontsize=7)
        n += 1
    fig.savefig(os.path.join(OUT, "fieldreview-terrain.pdf"))
    fig.savefig(os.path.join(OUT, "fieldreview-terrain.png"), dpi=150)
    plt.close(fig)
    print("  %d profiles" % n)


def main(argv=None):
    global OUT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-dem", action="store_true", help="skip the terrain checks")
    ap.add_argument("--out", default=OUT, help="figure directory (default DOCS/figures)")
    args = ap.parse_args(argv)
    OUT = args.out
    os.makedirs(OUT, exist_ok=True)
    dem_cache = {}
    results = run_cases(args, dem_cache)
    spacing = run_spacing(args)
    sensitivity = run_sensitivity(args)
    run_contours_small(args)
    lobes = run_lobes(args)
    lobe_sweep = run_lobe_sweep(args)
    run_terrain_profiles(args, results, dem_cache)
    with open(os.path.join(OUT, "fieldreview-results.json"), "w") as fh:
        json.dump(fieldreview._jsonable(dict(cases=results, spacing=spacing,
                                             sensitivity=sensitivity, lobes=lobes,
                                             lobe_sweep=lobe_sweep)), fh, indent=1)
    print("\nwritten to", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
