"""Elevation sampling, for validating the field-review prototype.

Not part of the field feature. The Herelink carries no terrain data and the
review reports where the signal peaked, not where the tag is. This module
exists to answer one question from FIELD_REVIEW.md: does the reported peak sit
downhill of the true tag position, as Mohammadi 2026 predicts?

Two sources, neither needing a login or a key:

  fetch_ea_dtm      Environment Agency LiDAR composite DTM, 1 m, England.
                    A lat/lon bounding box is requested from their WCS
                    service, which resamples to about 1 m in both axes.
  fetch_copernicus  Copernicus GLO-30 DSM, 30 m, global, as one-degree
                    tiles from the public AWS bucket. A *surface* model:
                    tree canopy is included, which matters on Ponui.

Rasters are cached under python/data/dem/ (gitignored) and read with PIL
alone, so nothing beyond the app's own dependencies is needed.
"""

import os
import struct
import urllib.request

import numpy as np
from PIL import Image

import geodesy

Image.MAX_IMAGE_PIXELS = None

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "dem")

EA_WCS = ("https://environment.data.gov.uk/spatialdata/"
          "lidar-composite-digital-terrain-model-dtm-1m/wcs")
EA_COVERAGE = "13787b9a-26a4-4775-8523-806d13af58fc__Lidar_Composite_Elevation_DTM_1m"
COPERNICUS_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/"
                  "Copernicus_DSM_COG_10_%s_DEM/Copernicus_DSM_COG_10_%s_DEM.tif")

# TIFF / GeoTIFF tags.
_MODEL_PIXEL_SCALE = 33550
_MODEL_TIEPOINT = 33922
_GEO_KEY_DIRECTORY = 34735
_MODEL_TRANSFORMATION = 34264
_GDAL_NODATA = 42113
_RASTER_TYPE_KEY = 1025          # 1 = PixelIsArea, 2 = PixelIsPoint


class Dem(object):
    """A north-up elevation raster on a regular lat/lon grid.

    z[row, col] with rows running south (dlat < 0). lat0/lon0 are the
    coordinates of the *centre* of cell (0, 0).
    """

    def __init__(self, z, lat0, lon0, dlat, dlon, source=""):
        self.z = np.asarray(z, dtype=float)
        self.lat0, self.lon0 = float(lat0), float(lon0)
        self.dlat, self.dlon = float(dlat), float(dlon)
        self.source = source

    @property
    def shape(self):
        return self.z.shape

    def bounds(self):
        """(lat_lo, lat_hi, lon_lo, lon_hi) of the cell centres."""
        nrow, ncol = self.z.shape
        lats = (self.lat0, self.lat0 + (nrow - 1) * self.dlat)
        lons = (self.lon0, self.lon0 + (ncol - 1) * self.dlon)
        return min(lats), max(lats), min(lons), max(lons)

    def cell_size_m(self, lat=None):
        """(north, east) size of a cell in metres at the given latitude."""
        lat = self.lat0 if lat is None else lat
        r_m, r_n = geodesy.earth_radii(lat)
        return (abs(np.radians(self.dlat)) * r_m,
                abs(np.radians(self.dlon)) * r_n * np.cos(np.radians(lat)))

    def elevation(self, lat, lon):
        """Bilinear elevation at (lat, lon); NaN outside the raster or on nodata."""
        lat = np.asarray(lat, dtype=float)
        lon = np.asarray(lon, dtype=float)
        r = (lat - self.lat0) / self.dlat
        c = (lon - self.lon0) / self.dlon
        nrow, ncol = self.z.shape
        out = np.full(np.broadcast(r, c).shape, np.nan)
        r, c = np.broadcast_arrays(r, c)
        ok = (r >= 0) & (r <= nrow - 1) & (c >= 0) & (c <= ncol - 1)
        if not np.any(ok):
            return out if out.ndim else float(out)
        r0 = np.clip(np.floor(r[ok]).astype(int), 0, nrow - 2)
        c0 = np.clip(np.floor(c[ok]).astype(int), 0, ncol - 2)
        fr = r[ok] - r0
        fc = c[ok] - c0
        z = self.z
        val = ((1 - fr) * (1 - fc) * z[r0, c0] + (1 - fr) * fc * z[r0, c0 + 1]
               + fr * (1 - fc) * z[r0 + 1, c0] + fr * fc * z[r0 + 1, c0 + 1])
        out[ok] = val
        return out if out.ndim else float(out)

    def slope(self, lat, lon, radius_m=25.0):
        """Local terrain gradient from a plane fitted to the cells within radius_m.

        Returns a dict: dz_de and dz_dn (m/m), slope_deg, downhill_deg (the
        compass direction the ground falls away in), elevation (of the fitted
        plane at the point) and n_cells. All NaN when fewer than six cells
        are available.
        """
        lat, lon = float(lat), float(lon)
        r_m, r_n = geodesy.earth_radii(lat)
        half_lat = radius_m / r_m
        half_lon = radius_m / (r_n * np.cos(np.radians(lat)))
        nrow, ncol = self.z.shape
        rows = np.arange(nrow)
        cols = np.arange(ncol)
        lat_r = self.lat0 + rows * self.dlat
        lon_c = self.lon0 + cols * self.dlon
        rsel = rows[np.abs(lat_r - lat) <= np.degrees(half_lat)]
        csel = cols[np.abs(lon_c - lon) <= np.degrees(half_lon)]
        nan = dict(dz_de=np.nan, dz_dn=np.nan, slope_deg=np.nan, downhill_deg=np.nan,
                   elevation=np.nan, n_cells=0)
        if rsel.size == 0 or csel.size == 0:
            return nan
        R, C = np.meshgrid(rsel, csel, indexing="ij")
        e, n, _ = geodesy.geo2enu(lat_r[R], lon_c[C], 0.0, (lat, lon, 0.0))
        z = self.z[R, C]
        inside = np.isfinite(z) & (np.hypot(e, n) <= radius_m)
        if np.count_nonzero(inside) < 6:
            return nan
        A = np.column_stack([np.ones(inside.sum()), e[inside], n[inside]])
        coef, _, _, _ = np.linalg.lstsq(A, z[inside], rcond=None)
        z0, ge, gn = (float(v) for v in coef)
        return dict(dz_de=ge, dz_dn=gn,
                    slope_deg=float(np.degrees(np.arctan(np.hypot(ge, gn)))),
                    downhill_deg=float(np.mod(np.degrees(np.arctan2(-ge, -gn)), 360.0)),
                    elevation=z0, n_cells=int(inside.sum()))


def _geokey(tags, key_id):
    """Value of one GeoKey from the GeoKeyDirectory, or None."""
    directory = tags.get(_GEO_KEY_DIRECTORY)
    if not directory:
        return None
    directory = list(directory)
    n_keys = directory[3]
    for i in range(n_keys):
        kid, location, count, value = directory[4 + 4 * i: 8 + 4 * i]
        if kid == key_id and location == 0:
            return value
    return None


def read_geotiff(path, source=""):
    """Read a single-band GeoTIFF on a geographic (lat/lon) grid into a Dem.

    Handles the two ways a GeoTIFF states its georeferencing: a tie-point
    plus pixel scale (Copernicus) and a model transformation matrix (the EA
    WCS output). Honours PixelIsPoint versus PixelIsArea so that cell centres
    are placed correctly.
    """
    im = Image.open(path)
    tags = im.tag_v2
    z = np.array(im, dtype=float)
    if z.ndim == 3:
        z = z[..., 0]

    if _MODEL_TRANSFORMATION in tags:
        m = [float(v) for v in tags[_MODEL_TRANSFORMATION]]
        dlon, lon_org = m[0], m[3]
        dlat, lat_org = m[5], m[7]
        if abs(m[1]) > 0 or abs(m[4]) > 0:
            raise ValueError("rotated rasters are not supported: %s" % path)
    elif _MODEL_PIXEL_SCALE in tags and _MODEL_TIEPOINT in tags:
        sx, sy = [float(v) for v in tags[_MODEL_PIXEL_SCALE]][:2]
        tp = [float(v) for v in tags[_MODEL_TIEPOINT]]
        i, j, lon_tp, lat_tp = tp[0], tp[1], tp[3], tp[4]
        dlon, dlat = sx, -sy
        lon_org = lon_tp - i * dlon
        lat_org = lat_tp - j * dlat
    else:
        raise ValueError("no georeferencing tags in %s" % path)

    raster_type = _geokey(tags, _RASTER_TYPE_KEY)
    if raster_type == 2:                       # PixelIsPoint: origin is a centre
        lat0, lon0 = lat_org, lon_org
    else:                                      # PixelIsArea: origin is a corner
        lat0, lon0 = lat_org + 0.5 * dlat, lon_org + 0.5 * dlon

    nodata = tags.get(_GDAL_NODATA)
    if nodata is not None:
        try:
            nodata = float(str(nodata).strip("\x00"))
            z[np.isclose(z, nodata, rtol=1e-6, atol=0.0)] = np.nan
        except ValueError:
            pass
    z[z < -1e30] = np.nan
    return Dem(z, lat0, lon0, dlat, dlon, source=source or os.path.basename(path))


def _download(url, path, timeout=600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with urllib.request.urlopen(url, timeout=timeout) as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    with open(tmp, "rb") as fh:
        magic = fh.read(4)
    if magic not in (b"II*\x00", b"MM\x00*"):
        os.remove(tmp)
        raise IOError("%s did not return a TIFF" % url)
    os.replace(tmp, path)


def fetch_ea_dtm(lat_lo, lat_hi, lon_lo, lon_hi, name, data_dir=DATA_DIR):
    """Environment Agency 1 m DTM for a lat/lon box, cached as data/dem/<name>.tif."""
    path = os.path.join(data_dir, "EA_DTM_1m_%s.tif" % name)
    if not os.path.exists(path):
        url = ("%s?service=WCS&version=2.0.1&request=GetCoverage&coverageId=%s"
               "&subset=Lat(%.6f,%.6f)&subset=Long(%.6f,%.6f)"
               "&subsettingCrs=http://www.opengis.net/def/crs/EPSG/0/4326"
               "&outputCrs=http://www.opengis.net/def/crs/EPSG/0/4326"
               "&format=image/tiff"
               % (EA_WCS, EA_COVERAGE, min(lat_lo, lat_hi), max(lat_lo, lat_hi),
                  min(lon_lo, lon_hi), max(lon_lo, lon_hi)))
        _download(url, path)
    return read_geotiff(path, source="EA LiDAR composite DTM 1 m")


def copernicus_tile_name(lat, lon):
    """Tile covering (lat, lon): named by its south-west corner, e.g. N54_00_W003_00."""
    la, lo = int(np.floor(lat)), int(np.floor(lon))
    return "%s%02d_00_%s%03d_00" % ("N" if la >= 0 else "S", abs(la),
                                    "E" if lo >= 0 else "W", abs(lo))


def fetch_copernicus(lat, lon, data_dir=DATA_DIR):
    """Copernicus GLO-30 tile containing (lat, lon), cached under data/dem/."""
    tile = copernicus_tile_name(lat, lon)
    path = os.path.join(data_dir, "Copernicus_DSM_COG_10_%s_DEM.tif" % tile)
    if not os.path.exists(path):
        _download(COPERNICUS_URL % (tile, tile), path)
    return read_geotiff(path, source="Copernicus GLO-30 DSM")
