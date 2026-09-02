"""Local east/north/up conversions, WGS84 flat-earth approximation.

Port of geo2enu.m / enu2geo.m from the MATLAB version, which in turn replaced
latlon2local / local2latlon from the Automated Driving Toolbox. Same argument
order and same return order as those, so the three implementations agree.

Accuracy: better than 5 cm against a rigorous ECEF-based ENU transform over a
1 km box, verified from -37 to +54 degrees latitude. This is a local
approximation and is not meant for spans of tens of kilometres.
"""

import numpy as np

WGS84_A = 6378137.0                 # semi-major axis, m
WGS84_F = 1.0 / 298.257223563       # flattening
_E2 = WGS84_F * (2.0 - WGS84_F)


def earth_radii(ref_lat_deg):
    """Meridional and normal radii of curvature at a reference latitude."""
    s = np.sin(np.radians(ref_lat_deg))
    d = 1.0 - _E2 * s * s
    r_normal = WGS84_A / np.sqrt(d)
    r_meridional = WGS84_A * (1.0 - _E2) / d ** 1.5
    return r_meridional, r_normal


def geo2enu(lat, lon, alt, home):
    """Geodetic -> local ENU metres, relative to home = (lat, lon, alt)."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    alt = np.asarray(alt, dtype=float)
    r_m, r_n = earth_radii(home[0])
    x_east = np.radians(lon - home[1]) * r_n * np.cos(np.radians(home[0]))
    y_north = np.radians(lat - home[0]) * r_m
    z_up = alt - home[2]
    return x_east, y_north, z_up


def enu2geo(x_east, y_north, z_up, home):
    """Local ENU metres -> geodetic. Exact inverse of geo2enu.

    Linear in x_east and y_north independently, so a rectangular ENU grid maps
    to an exactly rectangular lat/lon box. That is what lets the KML
    GroundOverlay be exact rather than approximate.
    """
    x_east = np.asarray(x_east, dtype=float)
    y_north = np.asarray(y_north, dtype=float)
    z_up = np.asarray(z_up, dtype=float)
    r_m, r_n = earth_radii(home[0])
    lon = home[1] + np.degrees(x_east / (r_n * np.cos(np.radians(home[0]))))
    lat = home[0] + np.degrees(y_north / r_m)
    alt = z_up + home[2]
    return lat, lon, alt
