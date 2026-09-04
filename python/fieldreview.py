#!/usr/bin/env python3
"""Field review: post-flight analysis meant for the Herelink, prototyped here.

After a flight the operator needs one thing: where do I walk next? This
answers it from the pulse log TagTracker already writes, with a deliberately
small control set (FIELD_REVIEW.md in the uavrt hub's docs/):

  tag              which transmitter; logs carry several
  time window      opens on the flight proper, takeoff and landing trimmed
  altitude window  drops near-field pulses when the path recrosses launch
  spatial box      the rectangle an operator would draw on the map

and reports the strongest-signal position, any other lobe worth knowing
about, a bearing with its confidence, contour lines, and the track.

    python fieldreview.py Pulse-2025-11-21-11-08-41-149.csv --tag 42
    python fieldreview.py LOG --tag 42 --time 2 12 --alt 50 70 --png out.png
    python fieldreview.py LOG --tag 42 --truth 54.327254 -2.966997 --json r.json

The strongest-signal position is where the received signal peaked. It is
not the tag position. Mohammadi 2026 documents the peak landing 20-30 m from
the tag, downhill of it, because of the monopole's toroidal pattern and the
terrain. The report says so every time it prints a position.

Everything computational lives in analysis.py, shared with the bench app.
This file is orchestration, a text report, a figure, and a command line.
"""

import argparse
import json
import math
import os
import sys

import numpy as np

import analysis
import geodesy
from readpulsetable import PulseLogError, read_pulse_table

DEFAULT_SMOOTH = 6              # pulses, same as the bench app
DEFAULT_LEVELS = 8              # contour lines
DEFAULT_WITHIN_DB = 10.0        # a lobe must be within this of the strongest
DEFAULT_MIN_PROMINENCE_DB = 2.0  # and stand this far above its saddle
DEFAULT_MAX_PEAKS = 3
WEAK_CONTRAST_DB = 10.0         # peak this little above the surface median: warn

CAVEAT = ("This is where the signal peaked, not where the tag is. Expect the tag "
          "uphill of it, typically 20-30 m away (Mohammadi 2026).")

_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass_name(deg):
    if not np.isfinite(deg):
        return "-"
    return _COMPASS[int(round(float(deg) / 22.5)) % 16]


def wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

def review(table, tag_id=None, time_range=None, alt_range=None, box=None,
           confirmed_only=True, trim=True, smooth=DEFAULT_SMOOTH, grid_res=None,
           levels=DEFAULT_LEVELS, within_db=DEFAULT_WITHIN_DB,
           min_prominence_db=DEFAULT_MIN_PROMINENCE_DB, max_peaks=DEFAULT_MAX_PEAKS,
           min_separation_m=None, truth=None):
    """Run the field review on a PulseTable. Returns a dict (see to_json).

    time_range is in the units of start_time_seconds; None means the flight
    proper when trim is set (analysis.flight_window) and the whole log
    otherwise. truth is an optional (lat, lon) of the real tag position, for
    validation: the result then carries the offset of every peak from it and
    the error of the bearing.
    """
    t_all = table.start_time_seconds
    t_first = float(t_all[0])
    tags, counts = np.unique(table.tag_id, return_counts=True)
    if tag_id is None:
        tag_id = float(tags[np.argmax(counts)])
    tag_id = float(tag_id)
    n_tag = int(np.count_nonzero(table.tag_id == tag_id))

    if time_range is None:
        if trim:
            lo, hi = analysis.flight_window(t_all, table.alt_rel)
            full = (float(t_all.min()), float(t_all.max()))
            if (lo, hi) == full:
                time_note = "whole log; altitudes could not support a trim"
            else:
                time_note = "flight proper, takeoff and landing trimmed"
            time_range = (lo, hi)
        else:
            time_range = (float(t_all.min()), float(t_all.max()))
            time_note = "whole log"
    else:
        time_range = (float(min(time_range)), float(max(time_range)))
        time_note = "as requested"

    mask = analysis.select_pulses(table, tag_id=tag_id, confirmed_only=confirmed_only,
                                  time_range=time_range, alt_range=alt_range, box=box)
    sub = table.mask(mask)

    # Local frame anchored on the first pulse of the log, as the bench app does.
    home = (float(table.lat[0]), float(table.lon[0]), 0.0)
    xe_all, yn_all, _ = geodesy.geo2enu(table.lat, table.lon, table.alt_rel, home)
    xe, yn, _ = geodesy.geo2enu(sub.lat, sub.lon, sub.alt_rel, home)

    prop = np.asarray(sub.snr, dtype=float).copy()
    if smooth and smooth > 1 and prop.size:
        prop = analysis.movmean(prop, int(smooth))

    res_rule, detail = analysis.grid_spacing(xe, yn)
    if grid_res is None:
        res_req = res_rule
    else:
        res_req = float(grid_res)
        detail = dict(detail, rule="requested")
    X, Y, grid, res_used = analysis.build_grid(xe, yn, prop, res_req)

    result = {
        "log": {
            "n_pulses": int(table.n),
            "duration_min": float((t_all[-1] - t_all[0]) / 60.0),
            "tags": {int(t): int(c) for t, c in zip(tags, counts)},
            "t_first": t_first,
        },
        "filter": {
            "tag_id": int(tag_id) if float(tag_id).is_integer() else tag_id,
            "confirmed_only": bool(confirmed_only),
            "time_range_s": [time_range[0], time_range[1]],
            "time_range_min": [(time_range[0] - t_first) / 60.0,
                               (time_range[1] - t_first) / 60.0],
            "time_note": time_note,
            "alt_range": None if alt_range is None else [float(v) for v in alt_range],
            "box": None if box is None else [float(v) for v in box],
        },
        "n_tag": n_tag,
        "n_selected": int(sub.n),
        "home": [home[0], home[1]],
        "smooth": int(smooth or 0),
        "grid": {
            "res_m": float(res_used) if grid is not None else np.nan,
            "requested_m": float(res_req),
            "rule_m": float(res_rule),
            "rule": detail["rule"],
            "step_m": float(detail["step_m"]),
            "extent_m": float(detail["extent_m"]),
            "extent_e_m": float(np.ptp(xe)) if xe.size else np.nan,
            "extent_n_m": float(np.ptp(yn)) if yn.size else np.nan,
            "shape": list(grid.shape) if grid is not None else None,
            "cells": int(grid.size) if grid is not None else 0,
            "finite_cells": int(np.isfinite(grid).sum()) if grid is not None else 0,
        },
        "bearing": {"deg": np.nan, "confidence": np.nan, "spread_deg": np.nan,
                    "anchor_lat": np.nan, "anchor_lon": np.nan},
        "peaks": [],
        "contours": [],
        "quality": {},
        "truth": None,
        "arrays": {
            "X": X, "Y": Y, "grid": grid, "grid_lat": None, "grid_lon": None,
            "track_xy": np.column_stack([xe_all, yn_all]),
            "track_geo": np.column_stack([table.lat, table.lon]),
            "track_time_min": (t_all - t_first) / 60.0,
            "sel_xy": np.column_stack([xe, yn]),
            "sel_geo": np.column_stack([sub.lat, sub.lon]),
            "sel_snr": np.asarray(sub.snr, dtype=float),
            "sel_prop": prop,
            "sel_time_min": (sub.start_time_seconds - t_first) / 60.0,
            "sel_alt": np.asarray(sub.alt_rel, dtype=float),
            "contours_xy": [],
        },
    }

    if grid is None:
        result["note"] = ("No surface: the selection needs at least four pulses that are "
                          "not all in a line and do not all share one SNR.")
        _add_truth(result, truth, home)
        return result

    grid_lat, grid_lon, _ = geodesy.enu2geo(X, Y, np.zeros_like(X), home)
    result["arrays"]["grid_lat"] = grid_lat
    result["arrays"]["grid_lon"] = grid_lon

    b, conf, spread = analysis.estimate_bearing(grid, res_used)
    ax_, ay_ = float(np.nanmean(xe)), float(np.nanmean(yn))
    alat, alon, _ = geodesy.enu2geo(ax_, ay_, 0.0, home)
    result["bearing"] = {"deg": b, "confidence": conf, "spread_deg": spread,
                         "anchor_x": ax_, "anchor_y": ay_,
                         "anchor_lat": float(alat), "anchor_lon": float(alon)}

    peaks = analysis.find_peaks(X, Y, grid, within_db=within_db,
                                min_prominence=min_prominence_db, max_peaks=max_peaks,
                                min_separation=min_separation_m)
    for p in peaks:
        plat, plon, _ = geodesy.enu2geo(p["x"], p["y"], 0.0, home)
        p["lat"], p["lon"] = float(plat), float(plon)
        p["compass"] = compass_name(p["bearing_deg"])
        # Where the peak lies as seen from the middle of the selection: the
        # direction to fly next when it sits on the edge of the flown area.
        p["from_centre_deg"] = float(np.mod(np.degrees(np.arctan2(p["x"] - ax_, p["y"] - ay_)),
                                            360.0))
    result["peaks"] = peaks
    # How much the surface actually peaks. A tag that was only ever heard
    # near the noise floor gives a flat surface whose maximum is meaningless;
    # the height of the peak above the median of the surface says so.
    finite = grid[np.isfinite(grid)]
    contrast = float(peaks[0]["value"] - np.median(finite)) if peaks else np.nan
    result["quality"] = {
        "peak_snr_db": float(peaks[0]["value"]) if peaks else np.nan,
        "median_snr_db": float(np.median(finite)),
        "contrast_db": contrast,
        "weak": bool(contrast < WEAK_CONTRAST_DB) if np.isfinite(contrast) else True,
    }
    result["peak_rule"] = {"within_db": float(within_db),
                           "min_prominence_db": float(min_prominence_db),
                           "max_peaks": int(max_peaks),
                           "min_separation_m": min_separation_m}

    contours = analysis.contour_polylines(X, Y, grid, levels)
    result["arrays"]["contours_xy"] = contours
    for level, lines in contours:
        geo = []
        for line in lines:
            la, lo, _ = geodesy.enu2geo(line[:, 0], line[:, 1], 0.0, home)
            geo.append(np.column_stack([la, lo]))
        result["contours"].append({"level": level, "lines_geo": geo})

    _add_truth(result, truth, home)
    return result


def _add_truth(result, truth, home):
    if truth is None:
        return
    tlat, tlon = float(truth[0]), float(truth[1])
    te, tn, _ = geodesy.geo2enu(tlat, tlon, 0.0, home)
    info = {"lat": tlat, "lon": tlon, "x": float(te), "y": float(tn)}
    for p in result["peaks"]:
        dx, dy = p["x"] - te, p["y"] - tn
        p["truth_distance_m"] = float(np.hypot(dx, dy))
        # Compass direction from the tag to the peak: where the peak sits
        # relative to the animal.
        p["truth_bearing_deg"] = float(np.mod(np.degrees(np.arctan2(dx, dy)), 360.0))
    b = result["bearing"]
    if np.isfinite(b.get("deg", np.nan)):
        dx, dy = te - b["anchor_x"], tn - b["anchor_y"]
        true_b = float(np.mod(np.degrees(np.arctan2(dx, dy)), 360.0))
        info["bearing_true_deg"] = true_b
        info["bearing_error_deg"] = float(wrap180(b["deg"] - true_b))
        info["distance_from_anchor_m"] = float(np.hypot(dx, dy))
    result["truth"] = info


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items() if k != "arrays"}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def to_json(result):
    """The result without its arrays, with NaN as null, ready for json.dump."""
    return _jsonable(result)


def fmt_latlon(lat, lon):
    return "%.5f, %.5f" % (lat, lon)


def report(result, name=""):
    """The text an operator would read. Decimal degrees, five places."""
    L = []
    log, flt, g, b = result["log"], result["filter"], result["grid"], result["bearing"]
    tags = ", ".join("%d (%d)" % (t, c) for t, c in sorted(log["tags"].items()))
    L.append("%s%d pulses, %.1f min, tags %s"
             % ((name + ": ") if name else "", log["n_pulses"], log["duration_min"], tags))
    L.append("Tag %s: %d of %d pulses selected" % (flt["tag_id"], result["n_selected"],
                                                   result["n_tag"]))
    parts = ["confirmed only" if flt["confirmed_only"] else "all pulses",
             "time %.1f-%.1f min (%s)" % (flt["time_range_min"][0], flt["time_range_min"][1],
                                         flt["time_note"]),
             "altitude %s" % ("any" if flt["alt_range"] is None
                              else "%.0f-%.0f m" % tuple(flt["alt_range"])),
             "box %s" % ("none" if flt["box"] is None
                         else "%.5f..%.5f, %.5f..%.5f" % tuple(flt["box"]))]
    L.append("  " + "; ".join(parts))
    if result["arrays"]["grid"] is None:
        L.append(result.get("note", "No surface."))
        return "\n".join(L)

    rule = g["rule"]
    if rule == "step/2":
        why = "half the %.1f m median pulse spacing" % g["step_m"]
    elif rule.startswith("extent/"):
        why = "extent / %s, pulse spacing %.1f m" % (rule.split("/")[1], g["step_m"])
    elif rule == "requested":
        why = "requested; the rule would give %.1f m" % g["rule_m"]
    else:
        why = "floor"
    L.append("Grid %.1f m (%s; extent %.0f x %.0f m), %d x %d cells; smoothing %d pulses"
             % (g["res_m"], why, g["extent_e_m"], g["extent_n_m"],
                g["shape"][1], g["shape"][0], result["smooth"]))
    pr = result.get("peak_rule")
    if pr:
        L.append("Lobes reported when within %.0f dB of the strongest and at least %.0f dB "
                 "above the saddle joining them to higher ground, at most %d"
                 % (pr["within_db"], pr["min_prominence_db"], pr["max_peaks"]))
    q = result.get("quality", {})
    if q:
        L.append("Peak SNR %.1f dB, surface median %.1f dB, contrast %.1f dB%s"
                 % (q["peak_snr_db"], q["median_snr_db"], q["contrast_db"],
                    "  <-- WEAK: below %.0f dB, treat the position as unreliable"
                    % WEAK_CONTRAST_DB if q["weak"] else ""))
    L.append("")
    for p in result["peaks"]:
        if p["rank"] == 0:
            L.append("STRONGEST SIGNAL   %s   SNR %.1f dB" % (fmt_latlon(p["lat"], p["lon"]),
                                                              p["value"]))
            L.append("  " + CAVEAT)
            if p.get("on_edge"):
                L.append("  It is on the edge of the flown area, %s of the survey centre: the "
                         "signal was still rising when the flight ran out, so the tag is "
                         "probably beyond it. Fly further that way."
                         % compass_name(p["from_centre_deg"]))
        else:
            L.append("Other lobe         %s   SNR %.1f dB, %.1f dB weaker, %.0f m to the %s "
                     "(%.0f deg), prominence %.1f dB"
                     % (fmt_latlon(p["lat"], p["lon"]), p["value"], p["below_db"],
                        p["distance_m"], p["compass"], p["bearing_deg"], p["prominence"]))
    L.append("")
    if np.isfinite(b["deg"]):
        L.append("BEARING  %.0f deg (%s) from %s, the centre of the selection;"
                 "  confidence %.2f, spread +-%.0f deg"
                 % (b["deg"], compass_name(b["deg"]), fmt_latlon(b["anchor_lat"], b["anchor_lon"]),
                    b["confidence"], b["spread_deg"]))
    else:
        L.append("BEARING  none")
    t = result["truth"]
    if t is not None and result["peaks"]:
        p = result["peaks"][0]
        L.append("")
        L.append("Truth %s: strongest signal is %.0f m away, to the %s (%.0f deg) of the tag"
                 % (fmt_latlon(t["lat"], t["lon"]), p["truth_distance_m"],
                    compass_name(p["truth_bearing_deg"]), p["truth_bearing_deg"]))
        if "bearing_error_deg" in t:
            L.append("  bearing to truth from the selection centre %.0f deg; estimate off by %+.0f deg"
                     % (t["bearing_true_deg"], t["bearing_error_deg"]))
    return "\n".join(L)


def plot_review(result, ax=None, truth=None, title=None, lobes=True, legend=True):
    """Draw the review: raster, contours, track, selected pulses, peaks, bearing.

    Lon/lat axes with the aspect corrected for latitude, so distances look
    right. Returns the figure.
    """
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FormatStrFormatter

    A = result["arrays"]
    home = result["home"]
    if ax is None:
        fig, ax = plt.subplots(figsize=(7.2, 5.6), layout="constrained")
    else:
        fig = ax.figure
    ax.set_aspect(1.0 / math.cos(math.radians(home[0])))

    handles = []
    if A["grid"] is not None:
        mesh = ax.pcolormesh(A["grid_lon"], A["grid_lat"], np.ma.masked_invalid(A["grid"]),
                             cmap="turbo", alpha=0.8, shading="nearest", rasterized=True)
        cb = fig.colorbar(mesh, ax=ax, shrink=0.8, pad=0.02)
        cb.set_label("SNR (dB), smoothed")
        for c in result["contours"]:
            for line in c["lines_geo"]:
                ax.plot(line[:, 1], line[:, 0], color="k", lw=0.5, alpha=0.55)

    tg = A["track_geo"]
    h, = ax.plot(tg[:, 1], tg[:, 0], "-", color="0.5", lw=0.7, alpha=0.9,
                 label="track (every pulse in the log)")
    handles.append(h)
    sg = A["sel_geo"]
    h, = ax.plot(sg[:, 1], sg[:, 0], ".", color="k", ms=3, label="selected pulses")
    handles.append(h)

    for p in result["peaks"]:
        if p["rank"] == 0:
            h, = ax.plot(p["lon"], p["lat"], marker="*", ms=17, mfc="white", mec="red",
                         mew=2.0, ls="none", label="strongest signal")
            handles.append(h)
        elif lobes:
            h, = ax.plot(p["lon"], p["lat"], marker="o", ms=10, mfc="none", mec="red",
                         mew=1.8, ls="none", label="other lobe" if p["rank"] == 1 else None)
            ax.annotate(str(p["rank"] + 1), (p["lon"], p["lat"]), xytext=(6, 6),
                        textcoords="offset points", color="red", fontsize=9, weight="bold")
            if p["rank"] == 1:
                handles.append(h)

    b = result["bearing"]
    if np.isfinite(b.get("deg", np.nan)):
        r_m, r_n = geodesy.earth_radii(home[0])
        length = 0.3 * max(result["grid"]["extent_m"], 50.0)
        de = length * math.sin(math.radians(b["deg"]))
        dn = length * math.cos(math.radians(b["deg"]))
        lat2, lon2, _ = geodesy.enu2geo(b["anchor_x"] + de, b["anchor_y"] + dn, 0.0,
                                        (home[0], home[1], 0.0))
        ax.annotate("", xy=(float(lon2), float(lat2)), xytext=(b["anchor_lon"], b["anchor_lat"]),
                    arrowprops=dict(arrowstyle="-|>", color="magenta", lw=2.2,
                                    shrinkA=0, shrinkB=0))
        h, = ax.plot([], [], color="magenta", lw=2.2,
                     label="bearing %.0f deg, conf %.2f" % (b["deg"], b["confidence"]))
        handles.append(h)

    truth = truth if truth is not None else (
        (result["truth"]["lat"], result["truth"]["lon"]) if result["truth"] else None)
    if truth is not None:
        h, = ax.plot(truth[1], truth[0], marker="X", ms=12, mfc="lime", mec="k", mew=1.2,
                     ls="none", label="true tag position")
        handles.append(h)

    # Extent: the track plus everything marked, with a margin.
    pts = [tg]
    if truth is not None:
        pts.append(np.array([[truth[0], truth[1]]]))
    for p in result["peaks"]:
        pts.append(np.array([[p["lat"], p["lon"]]]))
    pts = np.vstack(pts)
    lat_lo, lat_hi = pts[:, 0].min(), pts[:, 0].max()
    lon_lo, lon_hi = pts[:, 1].min(), pts[:, 1].max()
    pad_lat = max(lat_hi - lat_lo, 1e-4) * 0.08
    pad_lon = max(lon_hi - lon_lo, 1e-4) * 0.08
    ax.set_xlim(lon_lo - pad_lon, lon_hi + pad_lon)
    ax.set_ylim(lat_lo - pad_lat, lat_hi + pad_lat)

    # Scale bar.
    r_m, r_n = geodesy.earth_radii(home[0])
    extent_m = (lon_hi - lon_lo) * math.pi / 180.0 * r_n * math.cos(math.radians(home[0]))
    bar = 10 ** math.floor(math.log10(max(extent_m, 10.0) / 4.0))
    for mult in (5, 2, 1):
        if bar * mult <= extent_m / 4.0:
            bar *= mult
            break
    bar_deg = bar / (r_n * math.cos(math.radians(home[0]))) * 180.0 / math.pi
    x1 = lon_hi + pad_lon - (lon_hi - lon_lo + 2 * pad_lon) * 0.04
    y0 = lat_lo - pad_lat + (lat_hi - lat_lo + 2 * pad_lat) * 0.04
    ax.plot([x1 - bar_deg, x1], [y0, y0], color="k", lw=3, solid_capstyle="butt", zorder=5)
    ax.text(x1 - bar_deg / 2, y0, "%g m" % bar, ha="center", va="bottom", fontsize=8,
            zorder=5, bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.7))

    ax.xaxis.set_major_formatter(FormatStrFormatter("%.4f"))
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.4f"))
    ax.tick_params(labelsize=8)
    ax.set_xlabel("Longitude (deg)")
    ax.set_ylabel("Latitude (deg)")
    ax.grid(True, lw=0.3, alpha=0.5)
    if legend and handles:
        ax.legend(handles=handles, loc="best", fontsize=7, framealpha=0.85)

    if title is None:
        flt = result["filter"]
        title = "Tag %s | %d of %d pulses | %.1f-%.1f min" % (
            flt["tag_id"], result["n_selected"], result["n_tag"],
            flt["time_range_min"][0], flt["time_range_min"][1])
        if result["peaks"]:
            p = result["peaks"][0]
            title += "\nstrongest signal %s" % fmt_latlon(p["lat"], p["lon"])
            if np.isfinite(b.get("deg", np.nan)):
                title += " | bearing %.0f deg (conf %.2f)" % (b["deg"], b["confidence"])
        if result.get("quality", {}).get("weak"):
            title += "\nWEAK SIGNAL: contrast %.1f dB" % result["quality"]["contrast_db"]
        elif result["peaks"] and result["peaks"][0].get("on_edge"):
            title += "\nAT THE EDGE of the flown area: tag probably beyond it"
    ax.set_title(title, fontsize=10)
    return fig


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        description="Field review of a UAV-RT pulse log: strongest-signal position, "
                    "other lobes, bearing, contours.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Positions are decimal degrees. The strongest-signal position is where "
               "the signal peaked, not where the tag is.")
    p.add_argument("log", help="Pulse-*.csv written by TagTracker")
    p.add_argument("--tag", type=float, help="tag id (default: the most common in the log)")
    p.add_argument("--time", nargs=2, type=float, metavar=("START", "END"),
                   help="minutes from the first pulse (default: the flight proper)")
    p.add_argument("--no-trim", action="store_true",
                   help="default time window is the whole log, not the flight proper")
    p.add_argument("--alt", nargs=2, type=float, metavar=("LO", "HI"),
                   help="altitude window, metres relative to launch")
    p.add_argument("--box", nargs=4, type=float, metavar=("LAT0", "LAT1", "LON0", "LON1"),
                   help="spatial box, degrees")
    p.add_argument("--all", action="store_true", help="include unconfirmed pulses")
    p.add_argument("--smooth", type=int, default=DEFAULT_SMOOTH,
                   help="moving-mean window over SNR, pulses (default %(default)s)")
    p.add_argument("--grid", type=float, help="grid spacing, metres (default: from the data)")
    p.add_argument("--levels", type=int, default=DEFAULT_LEVELS,
                   help="number of contour lines (default %(default)s)")
    p.add_argument("--within-db", type=float, default=DEFAULT_WITHIN_DB,
                   help="report lobes within this of the strongest (default %(default)s)")
    p.add_argument("--min-prominence", type=float, default=DEFAULT_MIN_PROMINENCE_DB,
                   help="a lobe must stand this far above its saddle, dB (default %(default)s)")
    p.add_argument("--max-peaks", type=int, default=DEFAULT_MAX_PEAKS)
    p.add_argument("--min-separation", type=float, metavar="M",
                   help="drop lobes closer than this to a taller one, metres")
    p.add_argument("--truth", nargs=2, type=float, metavar=("LAT", "LON"),
                   help="known tag position, for validation")
    p.add_argument("--png", help="write the figure here")
    p.add_argument("--json", help="write the result here")
    p.add_argument("--show", action="store_true", help="open the figure in a window")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        table, warning = read_pulse_table(args.log)
    except (PulseLogError, OSError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if warning:
        print("warning: %s" % warning, file=sys.stderr)

    time_range = None
    if args.time is not None:
        t0 = float(table.start_time_seconds[0])
        time_range = (t0 + 60.0 * args.time[0], t0 + 60.0 * args.time[1])

    result = review(table, tag_id=args.tag, time_range=time_range, alt_range=args.alt,
                    box=args.box, confirmed_only=not args.all, trim=not args.no_trim,
                    smooth=args.smooth, grid_res=args.grid, levels=args.levels,
                    within_db=args.within_db, min_prominence_db=args.min_prominence,
                    max_peaks=args.max_peaks, min_separation_m=args.min_separation,
                    truth=args.truth)
    print(report(result, name=os.path.basename(args.log)))

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(to_json(result), fh, indent=1)
    if args.png or args.show:
        import matplotlib
        if not args.show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = plot_review(result)
        if args.png:
            fig.savefig(args.png, dpi=160)
        if args.show:
            plt.show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
