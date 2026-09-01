# uavrt_postflight

Post-flight analysis tools for the UAV-RT wildlife radio-telemetry system.

Reads a pulse log recorded during a flight, plots received signal strength across the search area, estimates a bearing to the tag, and exports a KMZ for Google Earth.

Developed under NSF awards [1556417](https://www.nsf.gov/awardsearch/show-award?AWD_ID=1556417) and [2104570](https://www.nsf.gov/awardsearch/show-award?AWD_ID=2104570).

## Where this sits

```
TagTracker (GCS)  ──writes──>  Pulse-<timestamp>.csv
                               Rotation-<N>.csv
                                     │
                                     ▼
                            uavrt_postflight
                                     │
                         plots • bearing • KMZ
```

The detection side of the system lives in [`uavrt_detection`](https://github.com/dynamic-and-active-systems-lab/uavrt_detection) and [`MavlinkTagController2`](https://github.com/DonLakeFlyer/MavlinkTagController2); the ground station is [`TagTracker`](https://github.com/DonLakeFlyer/TagTracker). This repository picks up after the aircraft lands.

## Requirements

MATLAB, base install only — **no toolboxes**. That is deliberate: the app runs on a bare MATLAB, and the numeric core is plain arithmetic and string building so it ports cleanly to other platforms.

Previously required and now removed: Automated Driving Toolbox (`latlon2local`/`local2latlon`), Mapping Toolbox (`wrapTo360`), Statistics Toolbox (`nanmean`), and a third-party KML toolbox.

## Quick start

```matlab
clear classes        % MATLAB caches classdefs - do not skip after an edit
pulseplotter2
```

**Load Data** → choose a `Pulse-*.csv` → **Export KML** writes a `.kmz`.

## Contents

| File | Purpose |
|---|---|
| `pulseplotter2.m` | The application. Run this one. |
| `pulseplotter.mlapp` | Identical code as an App Designer package; use only when you need the visual canvas editor. |
| `readpulsetable.m` | Reads any TagTracker pulse-log variant into a stable table. |
| `kmzwrite.m` | Writes the KMZ. |
| `geo2enu.m` / `enu2geo.m` | Geodetic ↔ local ENU conversion. |
| `MONOPOLE_SCAN_MAPPING.m` | Standalone antenna-pattern analysis script sharing the same helpers. |

The four helper functions must sit alongside the app — it calls them by name. Moving the `.mlapp` on its own, or packaging it as a MATLAB App, breaks it unless the helpers come too.

## Pulse log formats

TagTracker has shipped four header variants of the same file, including one 2023 build with no header at all. In every variant the first 16 fields of a pulse record appear in the same order, with columns 14/15/16 being latitude, longitude and altitude, so `readpulsetable` parses **positionally** and ignores the header names.

It also handles two things `readtable` gets wrong: the leading `#` on the header line, and the 4-field rotation start/stop records interleaved among the pulse records — which `readtable` turns into bogus "pulses" carrying a latitude in the `tag_id` column.

Output is a table sorted by `start_time_seconds` with stable column names regardless of source build.

## Bearing estimate

The gradient of the interpolated SNR surface points toward the tag. Rather than averaging the gradient components directly — which lets a few steep cells dominate and says nothing about whether the field agrees — the estimator takes the magnitude-weighted circular mean of gradient directions, excluding cells outside the convex hull. It reports three numbers, all shown in the plot title:

- **bearing** — compass degrees, 0 = north, clockwise
- **confidence** — resultant length, 0 to 1; 1 means every cell agrees
- **spread** — circular standard deviation

> **Not yet validated against ground truth.** The estimator is verified numerically — exact on clean linear fields, 45.00° on a point-source field whose true bearing is 45°, with confidence collapsing as noise rises — but it has not been checked against a flight with a known tag position. Treat bearings as indicative until that is done.

## KMZ output

Styles are declared once and referenced by `styleUrl`, and the marker icon is packaged inside the archive, so exports render **with no network connection** — which matters in the field. The interpolated surface ships as a GroundOverlay raster with transparent NaN cells; contour lines are included in a separate folder, switched off by default.

For reference, the previous third-party-toolbox output inlined a full `<Style>` block into every placemark and pointed each icon at `maps.google.com`: 894 bytes per pulse against 311 now, and 582 KB against 162 KB on a representative export.

## Geodesy

A flat-earth approximation using WGS84 meridional and normal radii at the reference latitude — the same approach as `latlon2local`, with the same argument order, so it is a drop-in replacement. Agreement with a rigorous ECEF-based ENU transform is under 5 cm over a 1 km box, checked from −37° to +54° latitude.

Because the transform is linear in x and y independently, a rectangular ENU grid maps to an exactly rectangular latitude/longitude box, which is what makes the KML GroundOverlay exact rather than approximate.

## Notes for contributors

`CLAUDE.md` in this directory carries the working notes: editing hazards (App Designer silently reverts external edits to `.mlapp` files), MATLAB path collisions with sibling repositories, verification practice, and open items. Read it before making changes.

## License

GPL-3.0. See [LICENSE](LICENSE).
