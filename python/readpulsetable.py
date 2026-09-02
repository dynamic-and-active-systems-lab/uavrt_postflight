"""Reader for TagTracker / MavlinkTagController2 pulse logs.

Port of readpulsetable.m.

TagTracker has shipped four header variants of the same file:

    2023 builds             no header at all,                       20 columns
    2024 -> 2026-04         "# 7, tag_id, ... position_x, _y, _z,
                             orientation_x, _y, _z, _w, antenna_offset"  21 cols
    master since 2026-04-10 "# 1, tag_id, ... latitude, longitude,
                             altitude_rel, roll_deg, pitch_deg, yaw_deg,
                             antenna_offset"                             20 cols

In every one of them the first 16 fields of a pulse record are in the same
order and columns 14/15/16 are latitude/longitude/altitude, so this parses
positionally and does not care what the header calls them.

The full pulse log also interleaves 4-field rotation start/stop records. A
naive CSV reader turns those into "pulses" carrying a latitude in the tag_id
column and no position, which corrupts the tag list and any local frame
anchored on the first row. They are dropped here, along with records missing a
time or a usable fix.
"""

import numpy as np

N_KEEP = 16

COLUMNS = (
    "command_id", "tag_id", "frequency_hz", "start_time_seconds",
    "predict_next_start_seconds", "snr", "stft_score",
    "group_seq_counter", "group_ind", "group_snr", "noise_psd",
    "detection_status", "confirmed_status", "lat", "lon", "alt_rel",
)


class PulseTable(object):
    """Column-oriented table of pulse records. Each column is a numpy array."""

    __slots__ = COLUMNS + ("n",)

    def __init__(self, matrix):
        matrix = np.asarray(matrix, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] != N_KEEP:
            raise ValueError("expected an n x %d matrix" % N_KEEP)
        for i, name in enumerate(COLUMNS):
            setattr(self, name, matrix[:, i])
        self.n = matrix.shape[0]

    def __len__(self):
        return self.n

    def as_matrix(self):
        return np.column_stack([getattr(self, c) for c in COLUMNS])

    def mask(self, keep):
        """Return a new PulseTable containing only the selected rows."""
        return PulseTable(self.as_matrix()[np.asarray(keep, dtype=bool)])

    def __repr__(self):
        tags = np.unique(self.tag_id)
        return "<PulseTable %d pulses, tags %s>" % (self.n, tags.tolist())


class PulseLogError(Exception):
    """Raised when a file holds no usable pulse records."""


def read_pulse_table(path):
    """Read a pulse log. Returns (PulseTable, warning_message).

    warning_message is an empty string when nothing was unusual.
    """
    warn = ""

    with open(path, "r", errors="replace") as fh:
        raw = [line.strip() for line in fh]
    raw = [line for line in raw if line]
    if not raw:
        raise PulseLogError("The file contains no data.")

    header = [l for l in raw if l.startswith("#") or "tag_id" in l]
    body = [l for l in raw if not (l.startswith("#") or "tag_id" in l)]
    if not body:
        raise PulseLogError("The file contains no pulse records.")

    # Warn if a future format moves the position fields off 14/15/16.
    if header:
        tokens = [t.strip() for t in header[0].lstrip("#").split(",")]
        if len(tokens) >= N_KEEP:
            lat_name = tokens[13].lower()
            if "latitude" not in lat_name and "position_x" not in lat_name:
                warn = ('Unrecognised pulse log header. Column 14 is "%s", '
                        'expected "latitude" or "position_x". Positions may be '
                        "wrong." % tokens[13])

    rows = []
    for line in body:
        values = []
        for field in line.split(","):
            try:
                values.append(float(field))
            except ValueError:
                break
        if len(values) >= N_KEEP:
            rows.append(values[:N_KEEP])
    if not rows:
        raise PulseLogError(
            "No complete pulse records found (rotation markers only?).")

    matrix = np.array(rows, dtype=float)

    # Keep only the dominant record type.
    ids, counts = np.unique(matrix[:, 0], return_counts=True)
    matrix = matrix[matrix[:, 0] == ids[np.argmax(counts)]]

    # Then only rows with a usable time and a plausible fix.
    lat, lon = matrix[:, 13], matrix[:, 14]
    ok = (np.isfinite(matrix[:, 3]) & np.isfinite(matrix[:, 1])
          & np.isfinite(lat) & np.isfinite(lon)
          & (np.abs(lat) <= 90.0) & (np.abs(lon) <= 180.0)
          & ~((lat == 0.0) & (lon == 0.0)))
    dropped = int((~ok).sum())
    matrix = matrix[ok]
    if matrix.size == 0:
        raise PulseLogError("No pulse records with a valid time and position.")
    if dropped:
        note = "%d record(s) dropped for a missing time or position." % dropped
        warn = (warn + "\n" + note).strip() if warn else note

    # Altitude is optional.
    alt = matrix[:, 15]
    alt[~np.isfinite(alt)] = 0.0

    # Pulses are logged as they arrive; sorting lets callers assume order.
    matrix = matrix[np.argsort(matrix[:, 3], kind="stable")]

    return PulseTable(matrix), warn
