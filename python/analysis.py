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


def estimate_bearing(grid, grid_res):
    """Bearing to the tag from the gradient of the interpolated surface.

    The gradient points uphill, i.e. towards the tag. Averaging the gradient
    components directly lets a handful of steep cells dominate and says nothing
    about whether the field agrees on a direction, so this takes the
    magnitude-weighted circular mean of the gradient directions. Cells outside
    the convex hull are NaN and are excluded rather than averaged in.

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
