# uavrt_postflight — pulseplotter

MATLAB tool for the UAV-RT wildlife radio-telemetry project. It reads a pulse log
written by **TagTracker** or **MavlinkTagController2**, plots received signal
strength over the flight area, estimates a bearing to the tag, and exports a KMZ
for Google Earth.

Everything here is toolbox-free: base MATLAB only. That is deliberate — see
[Design decisions](#design-decisions).

---

## Quick start

```matlab
clear classes        % see "MATLAB caches classdefs" below — do not skip
pulseplotter2
```

Then: **Load Data** → pick a `Pulse-*.csv` → the plot appears immediately →
**Export KML** writes a `.kmz`.

There are two copies of the same app:

| | Use when |
|---|---|
| `pulseplotter2.m` | **Default.** Plain classdef. Safe to edit from outside MATLAB. |
| `pulseplotter.mlapp` | Only when you need App Designer's visual canvas editor. |

They contain identical code apart from the class name. `pulseplotter2.m` exists
because App Designer silently overwrites external edits to the `.mlapp` — see
[Hazards](#hazards-read-before-editing).

---

## Layout

| File | Lines | Purpose |
|---|---|---|
| `pulseplotter2.m` | 1050 | The app. Run this. |
| `pulseplotter.mlapp` | 1047 | Same code, App Designer package. |
| `readpulsetable.m` | 121 | Reads any TagTracker pulse-log format into a table. |
| `geo2enu.m` | 35 | Geodetic → local ENU. Replaces `latlon2local`. |
| `enu2geo.m` | 33 | Local ENU → geodetic. Replaces `local2latlon`. |
| `kmzwrite.m` | 341 | Writes the KMZ. Replaces the kmltoolbox. |
| `MONOPOLE_SCAN_MAPPING.m` | 281 | Standalone analysis script; shares all four helpers. |

The four helpers **must sit alongside the app** — it calls them by name. Moving
the `.mlapp` on its own, or packaging it as a MATLAB App, breaks it unless they
come too. A note at the top of the class says so.

`*_BACKUP_*` files are pre-rewrite originals kept for reference.
`pulseplotter_code.txt` is a plain-text mirror of the `.mlapp` code for review
(it is `.txt`, not `.m`, so it cannot shadow the app on the path).

---

## The pulse log format

This is the single most important piece of domain knowledge here.

TagTracker has shipped **four** header variants of the same file:

| Build | Header | Cols |
|---|---|---|
| 2023 | *(none at all)* | 20 |
| 2024 → 2026-04 | `# 7, tag_id, … position_x, _y, _z, orientation_x, _y, _z, _w, antenna_offset` | 21 |
| master, since 2026-04-10 | `# 1, tag_id, … latitude, longitude, altitude_rel, roll_deg, pitch_deg, yaw_deg, antenna_offset` | 20 |

In **every** variant the first 16 fields of a pulse record are in the same order,
and columns **14/15/16 are latitude / longitude / altitude**. `readpulsetable`
therefore parses *positionally* and ignores what the header calls things.

Three traps `readtable` falls into and `readpulsetable` does not:

1. The leading `#` has to be hand-deleted from the header or `readtable`
   mis-parses. (The old script carried a comment telling you to do this.)
2. Column names differ per build. Code written against `data.position_x` breaks
   on any log from a build after 2026-04-10.
3. **The full pulse log interleaves 4-field rotation start/stop records.**
   `readtable` turns those into "pulses" carrying a *latitude in the `tag_id`
   column* and NaN positions — which corrupts the tag dropdown and any local
   frame anchored on the first row. Real example: the 2023 NAVHDA log has 5 such
   rows among 1,159.

`readpulsetable` returns a table sorted by `start_time_seconds` with stable
columns: `command_id, tag_id, frequency_hz, start_time_seconds,
predict_next_start_seconds, snr, stft_score, group_seq_counter, group_ind,
group_snr, noise_psd, detection_status, confirmed_status, lat, lon, alt_rel`.

Test data lives outside this repo, under `…/OneDrive-…/FLIGHT_TESTING_DATA/`.
Good cases: `2025-11-21-Cumbria-Day5-Fri` (4 tags, known tag position),
`2023-08-18-NAVHDA Site` (headerless + rotation rows),
`2025-01-13-Raymond Park Scan Flights` (the analysis script's own dataset).

---

## Design decisions

**No toolboxes.** `latlon2local`/`local2latlon` (Automated Driving), `wrapTo360`
(Mapping), `nanmean` (Statistics) and the third-party kmltoolbox were all
removed. Partly so the app runs on a bare MATLAB install, partly because the
project intends to port this to iOS/Android/macOS and everything here is now
plain arithmetic and string building that translates directly.

**Geodesy** is a flat-earth approximation using WGS84 meridional and normal radii
at the reference latitude — the same approach `latlon2local` uses, with the same
argument order, so it is a drop-in. Agreement with a rigorous ECEF-based ENU
transform is **under 5 cm over a 1 km box**, checked from −37° to +54° latitude.
Because it is linear in x and y independently, a rectangular ENU grid maps to an
exactly rectangular lat/lon box — which is what makes the KML GroundOverlay
exact rather than approximate.

**Bearing estimate.** The gradient of the interpolated SNR surface points uphill,
i.e. toward the tag. Averaging `FX`/`FY` directly lets a few steep cells dominate
and says nothing about whether the field agrees, so `updateAreaPlot` takes the
**magnitude-weighted circular mean of the gradient directions**, excluding NaN
cells outside the convex hull. It reports:

- `bearingDeg` — **compass degrees** (0 = north, clockwise). One convention
  throughout; convert to ENU with `sind`/`cosd`.
- `confidence` — resultant length, 0..1. 1 = every cell agrees, 0 = no consensus.
- `spreadDeg` — circular standard deviation, `sqrt(-2 ln R)`.

All three appear in the plot title. Verified numerically: exact on clean linear
fields at 8 compass bearings, 45.00° on a point-source field whose true bearing
is 45°, confidence collapsing 1.00 → 0.011 as noise rises.

**KMZ output.** Styles are declared once and referenced by `styleUrl`; the marker
icon is packaged inside the KMZ. The old kmltoolbox inlined a full `<Style>`
into every placemark and pointed each icon at `http://maps.google.com`, so
exports were 894 bytes/pulse (34% pure style boilerplate) and **would not render
without a network** — bad in the field. Now 311 bytes/pulse, 582 KB → 162 KB on
the Cumbria Tag 42 export, zero external references.

The interpolated surface ships as a **GroundOverlay raster** (a turbo-mapped PNG
with NaN cells transparent) rather than banded contour polygons, with contour
lines in a separate folder switched off by default. Confirmed working in Google
Earth.

**KML is built at export time, not on every plot.** It used to be rebuilt
placemark-by-placemark on every slider drag, which is what made the app crawl on
1000+ pulse logs. `updateAreaPlot` stores a `plotState` snapshot;
`ExportKMLButtonPushed` does the work.

---

## Hazards, read before editing

**App Designer silently reverts `.mlapp` edits.** A `.mlapp` is a zip whose code
lives in `matlab/document.xml`. Editing it externally works — but if App Designer
has the app open it holds its own copy in memory and writes it back over your
edit. **Pressing Run saves first**, and so does quitting MATLAB. This reverted
the same change three times before it was diagnosed.

Before editing `pulseplotter.mlapp`:

```bash
pgrep -fl MATLAB                                   # must be empty; check the PID is really gone
cat "$HOME/Library/Application Support/MathWorks/MATLAB/R2025a/AppDesignerMainPanelDocuments.json"
```

After editing, verify it took:

```bash
# must be non-zero; both are in the current code
unzip -p pulseplotter.mlapp matlab/document.xml | grep -c readpulsetable
unzip -p pulseplotter.mlapp matlab/document.xml | grep -c kmzwrite

# or diff the whole thing against the plain-text mirror
diff <(unzip -p pulseplotter.mlapp matlab/document.xml \
        | sed -n 's/.*<!\[CDATA\[//;p' ) pulseplotter_code.txt | head
```

How to tell App Designer did it rather than sync: each reverted file had a
*different* byte size and a different `appdesigner/appModel.mat` hash, meaning
the package was re-zipped, not restored. **Prefer editing `pulseplotter2.m`** —
App Designer does not own it.

**MATLAB cannot be run from the command line here.** Both R2024b and R2025a fail
license checkout (`License Manager Error -10`, expired). `matlab -batch` does not
work, so `checkcode` and any runtime verification are unavailable to the agent.
Interactive MATLAB does work for the user. **Never claim MATLAB code has been
tested.** Verify instead by:

1. Static checks — block/bracket balance, undeclared components, unwired
   callbacks, function-name/filename match.
2. Transliterating the numeric logic to Python and running it against real logs
   in `FLIGHT_TESTING_DATA`. numpy/scipy/matplotlib/PIL are available.

Say which method was used and that MATLAB itself never ran.

**MATLAB caches classdefs.** After any edit, `clear classes` before re-running,
or you silently get the old code. Most confusion in this project has traced back
to either this or the App Designer clobber.

**Name collisions on the MATLAB path.** `uavrt_bearing/` and
`uavrt_localization_utils/` both define a `readpulsecsv.m` with a *different*
contract (`[pulses, commands]` returning `PulseStruct`/`CommandStruct`). That is
why the reader here is called `readpulsetable` — same-named functions shadow each
other by path order and whichever loses fails silently. Check for collisions
before naming any new shared function:

```bash
find <playground-root> -name "<newname>.m"
```

**Searching outside this directory can fail silently.** An agent sandbox may
block traversal of sibling projects, and `find`/`grep` then return *nothing*
rather than an error. Always run a positive control (search for a string you know
exists) before trusting a "no results" answer.

---

## Open items

- **The bearing estimator has never been checked against ground truth.** Cumbria
  Tag 42 is the obvious test — the true tag position is known. Do this before the
  estimator gets baked into a mobile port.
- `MONOPOLE_SCAN_MAPPING.m` still has hard-coded absolute paths to
  `FLIGHT_TESTING_DATA`, some under a stale `/Users/mshafer/` username (those
  lines are commented out). It also calls `system('open …')` to launch Google
  Earth, replicating the old `f.run`.
- The mobile port (iOS/Android/macOS) is the stated next step. The four shared
  helpers are the intended shared layer.

## History

The app was reviewed and largely rewritten in Aug 2026. Fixed then: saved
bearings threw on every replot (missing `(i)` index) and drew in a meaningless
direction (degrees passed to radian trig, `sin`/`cos` swapped — an intended 0°
was drawn at 116.6°); Save/Clear crashed with "Off" selected; `uigetfile` and
`inputdlg` cancel paths crashed; rotation rows corrupted the data; `axis equal`
distorted the lon/lat view by ~1.7× at Cumbria latitude; Grid Res accepted 0;
stale bearings survived a file load. The takeoff-elevation modal dialog became an
`Elev (m)` field, because a legacy `inputdlg` blocks a `uifigure` app from behind.
