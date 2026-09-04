# uavrt_postflight — pulseplotter

MATLAB tool for the UAV-RT wildlife radio-telemetry project. It reads a pulse log
written by **TagTracker** or **MavlinkTagController2**, plots received signal
strength over the flight area, estimates a bearing to the tag, and exports a KMZ
for Google Earth.

Everything here is toolbox-free: base MATLAB only. That is deliberate — see
[Design decisions](#design-decisions).

---

## Active work: the field review feature

If you were pointed at `FIELD_REVIEW.md`, it lives one level up in the hub repository:
**`../docs/FIELD_REVIEW.md`** (absolute: `/Users/mws22/Developer/uavrt/docs/FIELD_REVIEW.md`).

That document is the specification for a post-flight review feature intended to run on the
Herelink controller, so an operator can pick the strongest-signal position in the field
instead of carrying a USB stick to a laptop. **Read it before starting.** In short:

- Prototype in **`python/`**, as a **new entry point** — do not grow `pulseplotter.py`.
- Shared primitives (peak finding, contour extraction, filters) go in **`analysis.py`** so
  the bench app and the field prototype use one implementation.
- `readpulsetable.py`, `geodesy.py` and `analysis.py`'s `build_grid` / `estimate_bearing`
  are reusable as-is.
- Do **not** touch `TagTracker` yet; `FIELD_REVIEW.md` §8 explains why.
- Read the Hazards section below first regardless — MATLAB cannot be run here, App Designer
  clobbers `.mlapp` edits, and MATLAB caches classdefs.

If `../docs/` is absent you are working from a standalone clone of this repository rather
than from inside the `uavrt` hub. Ask for the document; do not guess at the requirements.

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
| `matlab/pulseplotter2.m` | **Default.** Plain classdef. Safe to edit from outside MATLAB. |
| `matlab/pulseplotter.mlapp` | Only when you need App Designer's visual canvas editor. |

`matlab/pulseplotter2.m` exists because App Designer silently overwrites external
edits to the `.mlapp` — see [Hazards](#hazards-read-before-editing).

**They are no longer identical.** They were, until the 2026-09-02 layout rework.
The analysis code is still the same; `createComponents` is not. `pulseplotter2.m`
now builds its window from nested `uigridlayout` containers, and the `.mlapp` and
`pulseplotter_code.txt` still carry App Designer's absolute `Position` vectors.
That was deliberate: hand-written grid code would very likely make App Designer
refuse Design View, and there is no way to check that without MATLAB. Run
`pulseplotter2`. Re-syncing the `.mlapp` is a job for App Designer's canvas, not
for an external edit.

---

## Layout

| File | Lines | Purpose |
|---|---|---|
| `matlab/pulseplotter2.m` | 1193 | The app. Run this. Grid-based layout. |
| `matlab/pulseplotter.mlapp` | 1047 | App Designer package. Same analysis, pre-rework layout. |
| `matlab/readpulsetable.m` | 121 | Reads any TagTracker pulse-log format into a table. |
| `matlab/geo2enu.m` | 35 | Geodetic → local ENU. Replaces `latlon2local`. |
| `matlab/enu2geo.m` | 33 | Local ENU → geodetic. Replaces `local2latlon`. |
| `matlab/kmzwrite.m` | 341 | Writes the KMZ. Replaces the kmltoolbox. |
| `matlab/MONOPOLE_SCAN_MAPPING.m` | 281 | Standalone analysis script; shares all four helpers. |
| `matlab/check_layout.py` | 120 | Checks `createComponents`' grid declarations without MATLAB. |

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
i.e. toward the tag. `updateAreaPlot` takes the **magnitude-weighted circular
mean of the gradient directions**, excluding NaN cells outside the convex hull.

**The weighting does not change the direction.** `w.*ux` is just `fx`, so the
resultant is the plain vector sum of the gradient and the reported bearing is
exactly what averaging `FX`/`FY` would give — verified numerically to 1e-14.
Earlier revisions of this file and of the source comments claimed the circular
mean stopped a few steep cells dominating the direction; it cannot. What the
circular form actually adds is `confidence`, which a component average has no
counterpart for. It reports:

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

**Takeoff and landing are deselected on load, not filtered out.** Pulses received
during the climb and descent are weak and all sit at the launch point, so they
pull the interpolated surface down in one corner — the PI's report, 2026-09-02.
The time slider's **Value** now opens on the flight proper while its **Limits**
stay at the whole log, so the ends are one drag away rather than gone. The rule
is the median altitude of the log: a survey holds a working height, so the median
is the cruise altitude, and the leading and trailing runs below it are the climb
and the descent. Only those two runs are trimmed, so a mid-flight descent
survives. It falls back to the full range when the altitudes cannot support the
judgement — all equal, all missing, or a window keeping under 20% of the pulses.

`analysis.flight_window` (Python) and the private `flightWindow` method (MATLAB)
are the same function; `test_core.py` covers the trapezoid, mid-flight dip,
constant, all-NaN, single-sample and sliver cases, and `test_gui.py` asserts the
limits still span the whole log after a load. On the Cumbria logs it keeps 84%
(Day 5) and 70% (Day 8) of the pulses, and the pulses it drops average 21-27 dB
against 29-43 dB at cruise.

Two consequences worth knowing. Bearings move a little — 1 to 5 degrees on the
well-sampled tags, more on sparse ones where the trim removes a large fraction of
the detections. And **Property = Altitude (m)** now usually yields no surface at
all on the default window, because the aircraft holds one altitude; widen the
slider to get it back.

**The window is built from grids, not `Position` vectors.** App Designer's
generated `createComponents` placed every control at an absolute pixel position
inside a panel. That is fine at exactly the size it was drawn at and wrong
everywhere else: shrinking the figure pushed the top of the control column off
the panel, and the proportional resize MATLAB applies to panel children stretched
labels away from the fields they belong to. `createComponents` now uses nested
`uigridlayout` containers throughout — a `ControlGrid` in the left panel and a
`PlotGrid` in the right — and grid cells cannot overlap or be clipped.

Two consequences worth knowing before editing it:

- `ControlGrid` rows all have **fixed heights**, collected into a `heights` cell
  array as the rows are created and applied in one assignment at the end. Fixed
  heights are what let `Scrollable` compute a scroll extent; a `'1x'` row in
  there would silently break scrolling. Add controls by bumping `row` and
  appending a height in the same place, so the two cannot drift apart.
- The radio buttons inside the two `uibuttongroup`s are still absolutely
  positioned, because `uiradiobutton` must be a direct child of its ButtonGroup
  and cannot go in a grid. Those groups sit in fixed-size cells and have
  `AutoResizeChildren` off, so nothing moves. If you add a radio button, keep it
  inside the 210 px the two grid columns give the group.

The Python port mirrors this: the same four sections in the same order and a
scrolling control column. `python/test_layout.py` audits the real Tk geometry;
`matlab/check_layout.py` is the nearest MATLAB-side equivalent, and it can only
check the declarations, not what MATLAB actually draws.

---

## Hazards, read before editing

**App Designer silently reverts `.mlapp` edits.** A `.mlapp` is a zip whose code
lives in `matlab/document.xml`. Editing it externally works — but if App Designer
has the app open it holds its own copy in memory and writes it back over your
edit. **Pressing Run saves first**, and so does quitting MATLAB. This reverted
the same change three times before it was diagnosed.

Before editing `matlab/pulseplotter.mlapp`:

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
the package was re-zipped, not restored. **Prefer editing `matlab/pulseplotter2.m`** —
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

- **The gradient bearing estimator is known to fail where there is significant topography near the
  drone.** The method assumes the interpolated SNR surface slopes monotonically toward the
  transmitter; nearby terrain breaks that assumption. Known from field experience (PI, 2026-09-01).
  This is a *separate* problem from the lack of ground-truth validation below. Consistent with
  Mohammadi 2026, which reports peak signal occurring slightly downhill of the tag rather than above
  it. Treat the estimator as experimental, and prefer the directional antenna and triangulation where
  terrain is a factor.
- **The bearing estimator has never been checked against ground truth.** Cumbria
  Tag 42 is the obvious test — the true tag position is known. Do this before the
  estimator gets baked into a mobile port.
- `matlab/MONOPOLE_SCAN_MAPPING.m` still has hard-coded absolute paths to
  `FLIGHT_TESTING_DATA`, some under a stale `/Users/mshafer/` username (those
  lines are commented out). It also calls `system('open …')` to launch Google
  Earth, replicating the old `f.run`.
- The mobile port (iOS/Android/macOS) is the stated next step. The four shared
  helpers are the intended shared layer.

## History

**2026-09-02, layout.** `createComponents` was rebuilt on `uigridlayout`; see
[Design decisions](#design-decisions). The bug that prompted it was in the Python
port — the matplotlib toolbar was drawn over the SNR sliders and the lower one
vanished — but the MATLAB app had the same class of problem from absolute
positioning. Also then: `BearingEditField` became a text field showing `-` rather
than a numeric field showing `-Inf`, and `Confidence` and `Spread (deg)` readouts
were added beside it; the plot title wraps to two lines so it does not run off a
narrow axes. Verified by static inspection only — block balance, every declared
component referenced, and `matlab/check_layout.py`, which interprets
`createComponents` and confirms every child lands in a declared grid cell and
no two share one. **MATLAB never ran.**

The app was reviewed and largely rewritten in Aug 2026. Fixed then: saved
bearings threw on every replot (missing `(i)` index) and drew in a meaningless
direction (degrees passed to radian trig, `sin`/`cos` swapped — an intended 0°
was drawn at 116.6°); Save/Clear crashed with "Off" selected; `uigetfile` and
`inputdlg` cancel paths crashed; rotation rows corrupted the data; `axis equal`
distorted the lon/lat view by ~1.7× at Cumbria latitude; Grid Res accepted 0;
stale bearings survived a file load. The takeoff-elevation modal dialog became an
`Elev (m)` field, because a legacy `inputdlg` blocks a `uifigure` app from behind.
