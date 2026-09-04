"""Gridding, smoothing and the bearing estimator.

Port of the numeric core of pulseplotter2.m. Kept free of any GUI so it can be
tested headlessly and reused.
"""

import numpy as np
from matplotlib.tri import LinearTriInterpolator, Triangulation

MAX_GRID_CELLS = 200_000


def movmean(x, k):
    """Centred moving mean, matching MATLAB movmean(x, k, 'omitnan').

    Windows shrink at the endpoints. For even k MATLAB centres the window
    about the current and previous elements, i.e. k//2 samples before the
    current one and k//2 - 1 after it.
    """
    x = np.asarray(x, dtype=float)
    n = x.size
    if k is None or k <= 1 or n == 0:
        return x.copy()
    before = k // 2
    after = k - before - 1

    idx = np.arange(n)
    lo = np.maximum(idx - before, 0)
    hi = np.minimum(idx + after, n - 1)

    valid = np.isfinite(x)
    filled = np.where(valid, x, 0.0)
    csum = np.concatenate(([0.0], np.cumsum(filled)))
    ccount = np.concatenate(([0], np.cumsum(valid.astype(np.int64))))

    total = csum[hi + 1] - csum[lo]
    count = ccount[hi + 1] - ccount[lo]
    out = np.full(n, np.nan)
    np.divide(total, count, out=out, where=count > 0)
    return out


def build_grid(x_east, y_north, values, grid_res):
    """Interpolate scattered values onto a regular grid.

    Returns (X, Y, grid, grid_res_used). grid is NaN outside the convex hull of
    the input points, which is what makes the KML overlay transparent there.
    grid_res_used may be coarser than requested: a 1 m grid over a
    multi-kilometre flight is millions of cells and would lock the UI up.
    """
    x_east = np.asarray(x_east, dtype=float)
    y_north = np.asarray(y_north, dtype=float)
    values = np.asarray(values, dtype=float)

    finite = np.isfinite(values)
    if finite.sum() <= 3 or np.unique(values[finite]).size <= 1:
        return None, None, None, grid_res

    grid_res = max(float(grid_res), 1.0)
    span_e = np.ceil(x_east.max()) - np.floor(x_east.min())
    span_n = np.ceil(y_north.max()) - np.floor(y_north.min())
    def _cells(res):
        return (np.floor(span_e / res) + 1) * (np.floor(span_n / res) + 1)

    if _cells(grid_res) > MAX_GRID_CELLS:
        # Closed form gets close, but the +1 per axis can still land over the
        # cap, so nudge until it actually holds.
        grid_res = max(grid_res, float(np.sqrt(span_e * span_n / MAX_GRID_CELLS)))
        while _cells(grid_res) > MAX_GRID_CELLS:
            grid_res *= 1.02

    x_vec = np.arange(np.floor(x_east.min()), np.ceil(x_east.max()) + 1e-9, grid_res)
    y_vec = np.arange(np.floor(y_north.min()), np.ceil(y_north.max()) + 1e-9, grid_res)
    if x_vec.size < 2 or y_vec.size < 2:
        return None, None, None, grid_res

    X, Y = np.meshgrid(x_vec, y_vec)
    try:
        # Delaunay-based linear interpolation, equivalent to MATLAB's
        # griddata(..., 'linear'). Masked (NaN) outside the hull.
        tri = Triangulation(x_east[finite], y_north[finite])
        interp = LinearTriInterpolator(tri, values[finite])
        grid = np.asarray(interp(X, Y).filled(np.nan), dtype=float)
    except Exception:
        # Collinear or otherwise degenerate point sets.
        return None, None, None, grid_res

    if not np.any(np.isfinite(grid)):
        return None, None, None, grid_res
    return X, Y, grid, grid_res


def flight_window(times, altitudes, min_fraction=0.2):
    """The span of the flight proper, with takeoff and landing trimmed off.

    A survey flies out at a working altitude and holds it, so the median
    altitude of the log is the cruise altitude. Everything before the aircraft
    first reaches it, and everything after it last leaves it, is the climb and
    the descent: pulses received close to the ground, weaker than the rest, and
    all clustered around the launch point, which drags the interpolated surface
    down exactly where the flight starts and ends.

    Only the leading and trailing runs are trimmed, so a mid-flight descent is
    kept. `times` must be sorted, which is what readpulsetable guarantees.

    This is a default, not a filter: callers set the slider's *value* from it
    and leave its limits at the full range, so the discarded ends stay one drag
    away.

    Returns (start, end) in the units of `times`, falling back to the full range
    when the altitudes cannot support the judgement - all equal, all missing, or
    a window so short (less than min_fraction of the samples) that the altitude
    is more likely to be junk than the flight to have been that brief.
    """
    times = np.asarray(times, dtype=float)
    altitudes = np.asarray(altitudes, dtype=float)
    if times.size == 0:
        return np.nan, np.nan
    full = (float(np.nanmin(times)), float(np.nanmax(times)))

    finite = np.isfinite(altitudes) & np.isfinite(times)
    if np.count_nonzero(finite) < 2:
        return full

    cruise = float(np.median(altitudes[finite]))
    above = finite & (altitudes >= cruise)
    if not np.any(above):
        return full

    first = int(np.argmax(above))
    last = int(above.size - 1 - np.argmax(above[::-1]))
    if last <= first:
        return full

    start, end = float(times[first]), float(times[last])
    kept = int(np.count_nonzero((times >= start) & (times <= end)))
    if kept < max(2, min_fraction * times.size):
        return full
    return start, end


def estimate_bearing(grid, grid_res):
    """Bearing to the tag from the gradient of the interpolated surface.

    The gradient points uphill, i.e. towards the tag. This takes the
    magnitude-weighted circular mean of the gradient directions. Note that the
    magnitude weight cancels the unit-vector normalisation, w * u == grad, so
    the resultant is the plain vector sum and the reported *direction* is
    exactly what averaging the components would give. What the circular form
    adds is the confidence: the length of the summed vector over the sum of the
    lengths, which measures whether the field agrees on a direction and has no
    counterpart in a component average. Cells outside the convex hull are NaN
    and are excluded rather than averaged in.

    Returns (bearing_deg, confidence, spread_deg) where bearing_deg is compass
    degrees (0 = north, clockwise), confidence is the resultant length in 0..1
    (1 = every cell agrees, 0 = no consensus) and spread_deg is the matching
    circular standard deviation. All three are NaN when no bearing is possible.
    """
    if grid is None:
        return np.nan, np.nan, np.nan

    # np.gradient returns d/drow first; rows are y, columns are x.
    fy, fx = np.gradient(np.asarray(grid, dtype=float), grid_res, grid_res)
    valid = np.isfinite(fx) & np.isfinite(fy)
    fx_v, fy_v = fx[valid], fy[valid]
    weight = np.hypot(fx_v, fy_v)
    sel = weight > 0
    if not np.any(sel):
        return np.nan, np.nan, np.nan

    ux = fx_v[sel] / weight[sel]
    uy = fy_v[sel] / weight[sel]
    w = weight[sel]

    rx = float(np.sum(w * ux))
    ry = float(np.sum(w * uy))
    total = float(np.sum(w))

    math_deg = np.degrees(np.arctan2(ry, rx))
    bearing_deg = float(np.mod(90.0 - math_deg, 360.0))
    confidence = float(min(np.hypot(rx, ry) / total, 1.0))
    spread_deg = float(np.degrees(np.sqrt(max(-2.0 * np.log(max(confidence, 1e-16)), 0.0))))
    return bearing_deg, confidence, spread_deg


def divergence(fx, fy, grid_res):
    """Divergence of a 2-D vector field sampled on a regular grid."""
    dfx_dx = np.gradient(fx, grid_res, axis=1)
    dfy_dy = np.gradient(fy, grid_res, axis=0)
    return dfx_dx + dfy_dy


def gradient_field(grid, grid_res):
    """Return (fx, fy) of a grid, with x along columns and y along rows."""
    fy, fx = np.gradient(np.asarray(grid, dtype=float), grid_res, grid_res)
    return fx, fy


def color_bins(values, n_bins):
    """Map values onto 0..n_bins-1, NaN-safe. Constant input -> top bin."""
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0 or np.unique(finite).size == 1:
        return np.full(values.size, n_bins - 1, dtype=int)
    lo, hi = finite.min(), finite.max()
    idx = np.round((values - lo) / (hi - lo) * (n_bins - 1))
    idx[~np.isfinite(idx)] = 0
    return np.clip(idx, 0, n_bins - 1).astype(int)


# ---------------------------------------------------------------------------
# Field-review primitives.
#
# Shared by the bench app (pulseplotter.py, kmzwrite.py) and the field
# prototype (fieldreview.py), so there is one implementation of each. Keep
# them free of any GUI and of anything that assumes a particular map renderer:
# contours come back as coordinate arrays, peaks as numbers.
# ---------------------------------------------------------------------------

def select_pulses(table, tag_id=None, confirmed_only=True, time_range=None,
                  alt_range=None, box=None):
    """Boolean mask over a PulseTable for the field-review filter set.

    Every constraint is optional and None means "do not filter on this":

      tag_id          keep pulses whose tag_id equals this
      confirmed_only  keep pulses whose confirmed_status is non-zero
      time_range      (t0, t1), inclusive, in the units of start_time_seconds
      alt_range       (lo, hi), inclusive, metres of alt_rel
      box             (lat_lo, lat_hi, lon_lo, lon_hi), inclusive, degrees;
                      the spatial box an operator would draw on the map

    Bounds may be given in either order. Rows with a NaN in a filtered column
    fail that filter, which is the safe direction for a field tool.
    """
    keep = np.ones(table.n, dtype=bool)
    if tag_id is not None:
        keep &= table.tag_id == float(tag_id)
    if confirmed_only:
        keep &= table.confirmed_status != 0
    if time_range is not None:
        t0, t1 = sorted(float(v) for v in time_range)
        keep &= (table.start_time_seconds >= t0) & (table.start_time_seconds <= t1)
    if alt_range is not None:
        lo, hi = sorted(float(v) for v in alt_range)
        keep &= (table.alt_rel >= lo) & (table.alt_rel <= hi)
    if box is not None:
        lat_lo, lat_hi = sorted(float(v) for v in box[:2])
        lon_lo, lon_hi = sorted(float(v) for v in box[2:])
        keep &= ((table.lat >= lat_lo) & (table.lat <= lat_hi)
                 & (table.lon >= lon_lo) & (table.lon <= lon_hi))
    return keep


def track_spacing(x_east, y_north):
    """Median distance between consecutive samples, metres.

    The samples must be in flight order, which readpulsetable guarantees.
    The median is used rather than the mean so that gaps where the tag was
    not heard for a while do not inflate it. NaN with fewer than two samples.
    """
    x = np.asarray(x_east, dtype=float)
    y = np.asarray(y_north, dtype=float)
    if x.size < 2:
        return np.nan
    step = np.hypot(np.diff(x), np.diff(y))
    # Consecutive pulses at exactly the same position come from a position
    # feed slower than the pulse rate (the 2023 logs); they say nothing
    # about spacing, so they are left out rather than dragging the median
    # to zero.
    step = step[np.isfinite(step) & (step > 0)]
    return float(np.median(step)) if step.size else np.nan


def grid_spacing(x_east, y_north, min_res=1.0, cells_min=60, cells_max=300):
    """Interpolation grid spacing derived from the data, not a fixed number.

    Two things bound a sensible spacing. The surface is a linear interpolation
    between pulses, so it carries no detail finer than the pulse spacing: the
    starting point is half the median distance between consecutive pulses,
    which is also the PI's rule of thumb (about 10 m at 15 mph and 1.5 s per
    pulse). And the map is drawn at a fixed size whatever the flight covered:
    fewer than `cells_min` cells across the longer side looks blocky, more
    than `cells_max` is invisible and slow. So

        res = clip(step / 2,  L / cells_max,  L / cells_min)

    with L the longer side of the flown extent, floored at `min_res`. A
    60 m lawnmower and a 1 km survey both come out at roughly 100-300 cells
    across. build_grid still applies its own cell cap on top.

    Returns (res, detail) where detail records the inputs and which bound
    decided, for the report.
    """
    x = np.asarray(x_east, dtype=float)
    y = np.asarray(y_north, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    x, y = x[finite], y[finite]
    detail = {"step_m": np.nan, "extent_m": np.nan, "rule": "floor"}
    if x.size < 2:
        return float(min_res), detail

    step = track_spacing(x, y)
    extent = float(max(np.ptp(x), np.ptp(y)))
    detail["step_m"] = step
    detail["extent_m"] = extent

    lo, hi = extent / float(cells_max), extent / float(cells_min)
    res = step / 2.0 if np.isfinite(step) else hi
    if res < lo:
        res, rule = lo, "extent/%d" % cells_max
    elif res > hi:
        res, rule = hi, "extent/%d" % cells_min
    else:
        rule = "step/2"
    if res < min_res:
        res, rule = float(min_res), "floor"
    detail["rule"] = rule
    return float(res), detail


def peak_prominence(grid):
    """Every local maximum of a grid, with its topographic prominence.

    Prominence is the height of a peak above the highest saddle that connects
    it to any higher ground: how far the surface has to drop before it can
    climb to something taller. A wrinkle on the side of a lobe has a
    prominence of a fraction of a dB; a second lobe has a prominence of the
    whole dip between the two. It is what separates "two blobs" from "one
    blob with noise on it", which is the question a peak finder has to answer
    before it reports a second candidate.

    Computed as 0-dimensional persistence: cells are visited from the highest
    down, each one either starting a new component (it is a local maximum) or
    joining the components of its already-visited 8-neighbours. When two
    components meet, the one with the lower peak dies at the current level
    and its prominence is peak minus that level. NaN cells are never visited,
    so nothing crosses the edge of the interpolated area. The global maximum
    never dies; its prominence is taken as its height above the lowest cell.

    Returns a list of dicts sorted by height, descending:
      row, col       cell of the peak
      value          height
      prominence     as above
      saddle         height of the saddle it dies at (NaN for the global max)
      parent         index in this list of the higher peak it merges into,
                     or None for the global max
    """
    z = np.asarray(grid, dtype=float)
    if z.ndim != 2:
        raise ValueError("grid must be 2-D")
    nrow, ncol = z.shape
    flat = z.ravel()
    finite_idx = np.flatnonzero(np.isfinite(flat))
    if finite_idx.size == 0:
        return []
    order = finite_idx[np.argsort(-flat[finite_idx], kind="stable")]

    parent = np.full(flat.size, -1, dtype=np.int64)     # -1: not yet visited
    comp_peak = {}                                       # root cell -> peak cell
    peak_cells = []                                      # in order of discovery
    died = {}                                            # peak cell -> (saddle level, into peak cell)

    def find(a):
        root = a
        while parent[root] != root:
            root = parent[root]
        while parent[a] != root:                         # path compression
            nxt = parent[a]
            parent[a] = root
            a = nxt
        return root

    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    for cell in order:
        r, c = divmod(int(cell), ncol)
        v = flat[cell]
        roots = set()
        for dr, dc in offsets:
            rr, cc = r + dr, c + dc
            if 0 <= rr < nrow and 0 <= cc < ncol:
                nb = rr * ncol + cc
                if parent[nb] != -1:
                    roots.add(find(nb))
        if not roots:
            parent[cell] = cell
            comp_peak[cell] = cell
            peak_cells.append(int(cell))
            continue
        best = max(roots, key=lambda rt: (flat[comp_peak[rt]], -comp_peak[rt]))
        for rt in roots:
            if rt != best:
                pk = comp_peak[rt]
                died[pk] = (float(v), comp_peak[best])
                parent[rt] = best
        parent[cell] = best

    z_min = float(flat[finite_idx].min())
    index_of = {pk: i for i, pk in enumerate(peak_cells)}
    peaks = []
    for i, pk in enumerate(peak_cells):
        r, c = divmod(pk, ncol)
        v = float(flat[pk])
        if pk in died:
            saddle, into = died[pk]
            peaks.append({"row": r, "col": c, "value": v, "prominence": v - saddle,
                          "saddle": saddle, "parent": index_of[into]})
        else:
            peaks.append({"row": r, "col": c, "value": v, "prominence": v - z_min,
                          "saddle": np.nan, "parent": None})
    # Discovery order is descending height already; make it explicit and
    # renumber parents to match.
    order = sorted(range(len(peaks)), key=lambda i: (-peaks[i]["value"], i))
    renum = {old: new for new, old in enumerate(order)}
    out = [dict(peaks[i]) for i in order]
    for p in out:
        if p["parent"] is not None:
            p["parent"] = renum[p["parent"]]
    return out


def edge_distance(grid, row, col, max_rings=None):
    """Distance, in cells, from a cell to the edge of the data.

    The edge is the border of the array or a NaN cell, i.e. the hull of the
    flown area. 0 means the cell itself is NaN, 1 that a neighbour is. A
    strongest-signal position within a cell or two of the edge means the
    surface was still rising when the survey ran out: the tag is probably
    beyond it, and the useful advice is to fly further that way.
    """
    z = np.asarray(grid)
    nrow, ncol = z.shape
    if not np.isfinite(z[row, col]):
        return 0
    limit = max(nrow, ncol) if max_rings is None else int(max_rings)
    for ring in range(1, limit + 1):
        r0, r1 = row - ring, row + ring + 1
        c0, c1 = col - ring, col + ring + 1
        if r0 < 0 or c0 < 0 or r1 > nrow or c1 > ncol:
            return ring
        if not np.all(np.isfinite(z[r0:r1, c0:c1])):
            return ring
    return limit


EDGE_CELLS = 2      # a peak this close to the edge is "on" it


def find_peaks(X, Y, grid, within_db=3.0, min_prominence=1.0, max_peaks=5,
               min_separation=None):
    """Strongest-signal candidates on an interpolated surface.

    The first entry is always the global maximum: the strongest-signal
    position the field review reports. The rest are the other lobes an
    operator should know about, in descending height. A local maximum is
    reported as a lobe when it is

      - no more than `within_db` below the global maximum,
      - at least `min_prominence` above the saddle joining it to higher
        ground (see peak_prominence), so wrinkles on one lobe do not count,
      - and, if `min_separation` is set, at least that far in metres from
        every taller candidate already kept.

    At most `max_peaks` are returned. Each dict carries x, y (the grid
    coordinates of X and Y), value, prominence, saddle, rank (0 for the
    strongest), and for the lobes below the top one: below_db (how far under
    the strongest), distance_m and bearing_deg (compass) from the strongest.
    Returns [] for a grid with no finite cells.
    """
    if grid is None:
        return []
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    all_peaks = peak_prominence(grid)
    if not all_peaks:
        return []

    top = all_peaks[0]
    kept = []
    for p in all_peaks:
        if kept and p["value"] < top["value"] - float(within_db):
            break
        if kept and p["prominence"] < float(min_prominence):
            continue
        px, py = float(X[p["row"], p["col"]]), float(Y[p["row"], p["col"]])
        if min_separation is not None and any(
                np.hypot(px - q["x"], py - q["y"]) < float(min_separation) for q in kept):
            continue
        q = dict(p)
        q["x"], q["y"] = px, py
        q["rank"] = len(kept)
        q["edge_cells"] = edge_distance(grid, p["row"], p["col"], max_rings=EDGE_CELLS + 1)
        q["on_edge"] = q["edge_cells"] <= EDGE_CELLS
        if kept:
            dx, dy = px - kept[0]["x"], py - kept[0]["y"]
            q["below_db"] = top["value"] - p["value"]
            q["distance_m"] = float(np.hypot(dx, dy))
            q["bearing_deg"] = float(np.mod(np.degrees(np.arctan2(dx, dy)), 360.0))
        else:
            q["below_db"] = 0.0
            q["distance_m"] = 0.0
            q["bearing_deg"] = np.nan
        kept.append(q)
        if len(kept) >= int(max_peaks):
            break
    return kept


def contour_levels(grid, n):
    """`n` evenly spaced 'nice' contour levels strictly inside the data range.

    The same level choice matplotlib makes for an integer `levels` argument,
    so the KMZ contours look as they always did.
    """
    from matplotlib.ticker import MaxNLocator
    finite = np.asarray(grid, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0 or n is None or int(n) <= 0:
        return np.array([], dtype=float)
    lo, hi = float(finite.min()), float(finite.max())
    if hi <= lo:
        return np.array([], dtype=float)
    lev = np.asarray(MaxNLocator(int(n) + 1, min_n_ticks=1).tick_values(lo, hi), dtype=float)
    return lev[(lev > lo) & (lev < hi)]


def contour_polylines(X, Y, grid, levels):
    """Contour lines of a gridded surface as plain coordinate arrays.

    `levels` is either an integer count (see contour_levels) or an iterable
    of values. Returns a list of (level, polylines) pairs in ascending level
    order, each polyline an (n, 2) array of (x, y) in the units of X and Y.
    Lines stop at the edge of the interpolated area (NaN cells) rather than
    being drawn through it. No figure is created: this is for handing to a
    map renderer, a KML writer or a plot alike.
    """
    from contourpy import contour_generator
    if grid is None:
        return []
    if np.isscalar(levels):
        levels = contour_levels(grid, int(levels))
    levels = np.asarray(list(levels), dtype=float)
    if levels.size == 0:
        return []
    z = np.ma.masked_invalid(np.asarray(grid, dtype=float))
    if z.count() == 0:
        return []
    gen = contour_generator(x=np.asarray(X, dtype=float), y=np.asarray(Y, dtype=float),
                            z=z, name="serial", corner_mask=True, line_type="Separate")
    out = []
    for lev in np.sort(levels):
        lines = [np.asarray(line, dtype=float) for line in gen.lines(float(lev))]
        out.append((float(lev), [line for line in lines if line.shape[0] >= 2]))
    return out
