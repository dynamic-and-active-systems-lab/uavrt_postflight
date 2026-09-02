"""KMZ writer. Port of kmzwrite.m.

Writes a Google Earth KMZ holding an optional raster surface, contour lines,
colour-coded points and marker points. Styles are declared once and referenced
by styleUrl, and the marker icon is packaged inside the archive, so exports are
compact and render with no network.
"""

import io
import os
import zipfile

import numpy as np
from matplotlib import colormaps
import matplotlib.pyplot as plt

N_POINT_BINS = 64
N_LINE_BINS = 16


def _escape(text):
    return (str(text).replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;"))


def _kml_color(rgb, alpha=255):
    """KML colours are aabbggrr, the reverse of the usual order."""
    r, g, b = [int(round(255 * min(max(float(c), 0.0), 1.0))) for c in rgb[:3]]
    return "%02X%02X%02X%02X" % (int(alpha), b, g, r)


def _dot_png():
    """A white disc with a soft edge, tinted per style by IconStyle <color>."""
    m = 64
    xx, yy = np.meshgrid(np.linspace(-1, 1, m), np.linspace(-1, 1, m))
    r = np.hypot(xx, yy)
    alpha = np.clip((0.90 - r) * (m / 6.0), 0.0, 1.0)
    rgba = np.dstack([np.ones((m, m)), np.ones((m, m)), np.ones((m, m)), alpha])
    buf = io.BytesIO()
    plt.imsave(buf, rgba, format="png")
    return buf.getvalue()


def _surface_png(grid):
    """Turbo-mapped raster, transparent where the grid is NaN.

    PNG row 0 is the north edge of a GroundOverlay but row 0 of a meshgrid is
    its south edge, hence the flip.
    """
    grid = np.asarray(grid, dtype=float)
    finite = np.isfinite(grid)
    lo = float(grid[finite].min())
    hi = float(grid[finite].max())
    if hi <= lo:
        hi = lo + 1.0
    norm = np.clip((grid - lo) / (hi - lo), 0.0, 1.0)
    norm[~finite] = 0.0
    rgba = colormaps["turbo"](norm)
    rgba[..., 3] = finite.astype(float)
    buf = io.BytesIO()
    plt.imsave(buf, np.flipud(rgba), format="png")
    return buf.getvalue()


def kmzwrite(kmz_path,
             grid_lat=None, grid_lon=None, grid_value=None,
             surface_opacity=0.8, contour_levels=10,
             point_lat=None, point_lon=None, point_alt=None, point_value=None,
             point_altitude_mode="clampToGround",
             marker_lat=None, marker_lon=None, marker_name="Marker",
             point_folder_name="Points", marker_folder_name="Markers",
             name=None, description="", value_name="Value"):
    """Write a KMZ. Every section is optional; supply only what you have."""

    if name is None:
        name = os.path.splitext(os.path.basename(kmz_path))[0]

    have_grid = (grid_value is not None and grid_lat is not None
                 and grid_lon is not None
                 and np.any(np.isfinite(np.asarray(grid_value, dtype=float))))
    if have_grid:
        grid_lat = np.asarray(grid_lat, dtype=float)
        grid_lon = np.asarray(grid_lon, dtype=float)
        grid_value = np.asarray(grid_value, dtype=float)
        if not (grid_lat.shape == grid_lon.shape == grid_value.shape):
            raise ValueError("grid_lat, grid_lon and grid_value must match in shape")

    p_lat = np.atleast_1d(np.asarray(point_lat, dtype=float)) if point_lat is not None else np.empty(0)
    p_lon = np.atleast_1d(np.asarray(point_lon, dtype=float)) if point_lon is not None else np.empty(0)
    if p_lat.size != p_lon.size:
        raise ValueError("point_lat and point_lon must be the same length")
    n_pts = p_lat.size
    if point_alt is None:
        p_alt = np.zeros(n_pts)
    else:
        p_alt = np.atleast_1d(np.asarray(point_alt, dtype=float))
        if p_alt.size == 1:
            p_alt = np.full(n_pts, float(p_alt[0]))
    p_val = np.atleast_1d(np.asarray(point_value, dtype=float)) if point_value is not None else None
    if p_val is not None and p_val.size != n_pts:
        raise ValueError("point_value must match point_lat in length")

    m_lat = np.atleast_1d(np.asarray(marker_lat, dtype=float)) if marker_lat is not None else np.empty(0)
    m_lon = np.atleast_1d(np.asarray(marker_lon, dtype=float)) if marker_lon is not None else np.empty(0)
    if m_lat.size != m_lon.size:
        raise ValueError("marker_lat and marker_lon must be the same length")
    if isinstance(marker_name, str):
        m_names = [marker_name] * m_lat.size
    else:
        m_names = list(marker_name)

    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n',
             '<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n',
             "<name>%s</name>\n" % _escape(name)]
    if description:
        parts.append("<description>%s</description>\n" % _escape(description))

    # ---- shared styles ------------------------------------------------
    point_cmap = colormaps["turbo"].resampled(N_POINT_BINS)
    for k in range(N_POINT_BINS):
        parts.append(
            '<Style id="p%02d"><IconStyle><color>%s</color><scale>0.5</scale>'
            '<Icon><href>files/dot.png</href></Icon></IconStyle>'
            '<LabelStyle><scale>0</scale></LabelStyle></Style>\n'
            % (k, _kml_color(point_cmap(k))))
    line_cmap = colormaps["turbo"].resampled(N_LINE_BINS)
    for k in range(N_LINE_BINS):
        parts.append(
            '<Style id="l%02d"><LineStyle><color>%s</color><width>2</width>'
            '</LineStyle></Style>\n' % (k, _kml_color(line_cmap(k))))
    parts.append('<Style id="marker"><IconStyle><color>FF000000</color>'
                 '<scale>1.4</scale><Icon><href>files/dot.png</href></Icon>'
                 '</IconStyle></Style>\n')

    files = {"files/dot.png": _dot_png()}

    # ---- ground overlay -----------------------------------------------
    if have_grid:
        files["files/surface.png"] = _surface_png(grid_value)
        # GroundOverlay maps image edges to the box, but grid values sit at
        # cell centres, so the box grows by half a cell each way.
        half_lat = abs(grid_lat[1, 0] - grid_lat[0, 0]) / 2 if grid_lat.shape[0] > 1 else 0.0
        half_lon = abs(grid_lon[0, 1] - grid_lon[0, 0]) / 2 if grid_lon.shape[1] > 1 else 0.0
        alpha_hex = "%02x" % int(round(255 * min(max(surface_opacity, 0.0), 1.0)))
        parts.append(
            '<Folder><name>%s surface</name>\n<GroundOverlay><name>%s</name>'
            '<color>%sffffff</color>\n'
            '<Icon><href>files/surface.png</href></Icon>\n'
            '<LatLonBox><north>%.10f</north><south>%.10f</south>'
            '<east>%.10f</east><west>%.10f</west></LatLonBox>\n'
            '</GroundOverlay></Folder>\n'
            % (_escape(value_name), _escape(value_name), alpha_hex,
               grid_lat.max() + half_lat, grid_lat.min() - half_lat,
               grid_lon.max() + half_lon, grid_lon.min() - half_lon))

    # ---- contour lines, off by default --------------------------------
    if have_grid and contour_levels and contour_levels > 0:
        finite = grid_value[np.isfinite(grid_value)]
        g_lo, g_hi = float(finite.min()), float(finite.max())
        if g_hi <= g_lo:
            g_hi = g_lo + 1.0
        fig = plt.figure()
        try:
            cs = plt.contour(grid_lon, grid_lat, grid_value, levels=contour_levels)
            segments = []
            for level, paths in zip(cs.levels, cs.allsegs):
                ci = int(np.clip(round((level - g_lo) / (g_hi - g_lo) * (N_LINE_BINS - 1)),
                                 0, N_LINE_BINS - 1))
                for path in paths:
                    if len(path) < 2:
                        continue
                    coords = " ".join("%.8f,%.8f,0" % (x, y) for x, y in path)
                    segments.append(
                        '<Placemark><name>%.4g</name><styleUrl>#l%02d</styleUrl>'
                        '<LineString><tessellate>1</tessellate>'
                        '<altitudeMode>clampToGround</altitudeMode>'
                        '<coordinates>%s</coordinates></LineString></Placemark>\n'
                        % (level, ci, coords))
        finally:
            plt.close(fig)
        if segments:
            parts.append('<Folder><name>Contour lines</name>'
                         '<visibility>0</visibility>\n')
            parts.extend(segments)
            parts.append("</Folder>\n")

    # ---- points --------------------------------------------------------
    if n_pts:
        if p_val is None:
            bins = np.full(n_pts, N_POINT_BINS - 1, dtype=int)
        else:
            finite = p_val[np.isfinite(p_val)]
            if finite.size == 0 or np.unique(finite).size == 1:
                bins = np.full(n_pts, N_POINT_BINS - 1, dtype=int)
            else:
                lo, hi = finite.min(), finite.max()
                idx = np.round((p_val - lo) / (hi - lo) * (N_POINT_BINS - 1))
                idx[~np.isfinite(idx)] = 0
                bins = np.clip(idx, 0, N_POINT_BINS - 1).astype(int)

        label = _escape(value_name)
        mode = _escape(point_altitude_mode)
        parts.append("<Folder><name>%s</name>\n" % _escape(point_folder_name))
        chunks = []
        for i in range(n_pts):
            if p_val is None:
                desc = ""
            else:
                desc = "<description>%s = %.4g</description>" % (label, p_val[i])
            chunks.append(
                '<Placemark><styleUrl>#p%02d</styleUrl>%s'
                '<Point><altitudeMode>%s</altitudeMode>'
                '<coordinates>%.8f,%.8f,%.2f</coordinates></Point></Placemark>\n'
                % (bins[i], desc, mode, p_lon[i], p_lat[i], p_alt[i]))
        parts.append("".join(chunks))
        parts.append("</Folder>\n")

    # ---- markers -------------------------------------------------------
    if m_lat.size:
        parts.append("<Folder><name>%s</name>\n" % _escape(marker_folder_name))
        for i in range(m_lat.size):
            parts.append(
                '<Placemark><name>%s</name><styleUrl>#marker</styleUrl>'
                '<Point><altitudeMode>clampToGround</altitudeMode>'
                '<coordinates>%.8f,%.8f,0</coordinates></Point></Placemark>\n'
                % (_escape(m_names[i]), m_lon[i], m_lat[i]))
        parts.append("</Folder>\n")

    parts.append("</Document>\n</kml>\n")

    with zipfile.ZipFile(kmz_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", "".join(parts))
        for arcname, blob in files.items():
            z.writestr(arcname, blob)
    return kmz_path
