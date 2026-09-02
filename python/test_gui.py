"""End-to-end smoke test through the GUI code path, with the window hidden.

Builds the real widgets, loads a log, exercises every control that triggers a
replot, saves a bearing, and exports a KMZ. Run with:

    python3 test_gui.py [pulse-log.csv]
"""

import os
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

import numpy as np

CANDIDATES = [
    ("/Users/mws22/Library/CloudStorage/OneDrive-NorthernArizonaUniversity/"
     "FLIGHT_TESTING_DATA/2025-11-21-Cumbria-Day5-Fri/HERELINK_LOGS/"
     "Pulse-2025-11-21-11-08-41-149.csv"),
    ("/Users/mws22/Library/CloudStorage/OneDrive-NorthernArizonaUniversity/"
     "FLIGHT_TESTING_DATA/2023-08-18-NAVHDA Site/"
     "Pulse-2023-08-18-16-04-59-715.csv"),
]

_failures = []


def check(label, ok, detail=""):
    print("  %-50s %s%s" % (label, "PASS" if ok else "FAIL",
                            ("  " + detail) if detail else ""))
    if not ok:
        _failures.append(label)


def synth(path):
    lines = ["# 1, tag_id, frequency_hz, start_time_seconds, "
             "predict_next_start_seconds, snr, stft_score, group_seq_counter, "
             "group_ind, group_snr, noise_psd, detection_status, "
             "confirmed_status, latitude, longitude, altitude_rel, roll_deg, "
             "pitch_deg, yaw_deg, antenna_offset"]
    rng = np.random.default_rng(0)
    for i in range(300):
        lat = 54.3270 + rng.uniform(0, 0.004)
        lon = -2.9710 + rng.uniform(0, 0.006)
        snr = 40 - np.hypot((lat - 54.3310) * 111000, (lon - 2.9650) * 65000) * 0.02
        lines.append("1, 42, 150000000, %.6f, %.6f, %.6f, 0.08, 1, %d, 35.3, "
                     "1.2e-10, 1, 1, %.6f, %.6f, %.3f, 0.1, 0.2, 110.8, 0.0"
                     % (1775188930 + i, 1775188931 + i, snr, i, lat, lon,
                        10 + (i % 90)))
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def main(argv):
    import tkinter as tk
    print("pulseplotter_py GUI smoke test")

    log = None
    if len(argv) > 1 and os.path.exists(argv[1]):
        log = argv[1]
    else:
        for c in CANDIDATES:
            if os.path.exists(c):
                log = c
                break
    if log is None:
        log = synth(os.path.join(tempfile.mkdtemp(), "synthetic.csv"))
        print("  (using synthetic data; no real log reachable)")
    print("  log: %s\n" % os.path.basename(log))

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print("  no display available: %s" % exc)
        return 0
    root.withdraw()                       # build everything, show nothing

    import pulseplotter

    # Modal dialogs would block a headless run, so record them instead.
    dialogs = []
    for fn in ("showinfo", "showwarning", "showerror"):
        setattr(pulseplotter.messagebox, fn,
                lambda title, msg, _f=fn: dialogs.append((_f, title)))

    app = pulseplotter.PulsePlotter(root)
    check("widgets build", app.canvas is not None)
    check("startup title set before any data",
          "Load a pulse CSV" in app.ax.get_title())

    app.on_load(log)
    root.update_idletasks()
    check("log loaded", app.data is not None and len(app.data) > 0,
          "%d pulses" % (len(app.data) if app.data else 0))
    check("tag dropdown populated", len(app.tag_box["values"]) > 0,
          str(list(app.tag_box["values"])))
    check("plot drawn immediately, no modal dialog",
          app.plot_state is not None)
    check("title reports pulses and bearing",
          "pulses" in app.ax.get_title(), app.ax.get_title()[:70])

    b = app.current_bearing
    check("bearing computed", np.isfinite(b["bearing_deg"]),
          "%.1f deg, conf %.2f" % (b["bearing_deg"], b["confidence"])
          if np.isfinite(b["bearing_deg"]) else "")

    # every control that triggers a replot
    for name, action in [
        ("axis -> Lon, Lat", lambda: app.axis_var.set("Lon, Lat")),
        ("axis -> x, y", lambda: app.axis_var.set("x, y")),
        ("property -> STFT Score", lambda: app.prop_var.set("STFT Score")),
        ("property -> Time", lambda: app.prop_var.set("Time")),
        ("property -> Altitude (m)", lambda: app.prop_var.set("Altitude (m)")),
        ("property -> SNR", lambda: app.prop_var.set("SNR")),
        ("plot property -> Divergence",
         lambda: app.plot_prop_var.set("Divergence")),
        ("plot property -> Value", lambda: app.plot_prop_var.set("Value")),
        ("smoothing -> 0", lambda: app.smooth_var.set(0)),
        ("smoothing -> 10", lambda: app.smooth_var.set(10)),
        ("grid res -> 2", lambda: app.grid_var.set(2)),
        ("grid res -> 20", lambda: app.grid_var.set(20)),
        ("plot tag on", lambda: (app.tag_lat_var.set(float(app.data.lat[0])),
                                 app.tag_lon_var.set(float(app.data.lon[0])),
                                 app.plot_tag_var.set(True))),
        ("elev -> 250", lambda: app.elev_var.set(250.0)),
    ]:
        try:
            action()
            app.update_plot()
            root.update_idletasks()
            check(name, True)
        except Exception as exc:                       # noqa: BLE001
            check(name, False, repr(exc))

    # narrow the time and SNR windows
    try:
        t0 = float(app.time_lo.cget("from"))
        t1 = float(app.time_lo.cget("to"))
        app.time_lo.set(t0 + 0.25 * (t1 - t0))
        app.time_hi.set(t0 + 0.75 * (t1 - t0))
        app.update_plot()
        n_sub = len(app.plot_state["lat"])
        check("time window narrows the selection", n_sub < len(app.data),
              "%d of %d" % (n_sub, len(app.data)))
    except Exception as exc:                           # noqa: BLE001
        check("time window narrows the selection", False, repr(exc))

    app.time_lo.set(float(app.time_lo.cget("from")))
    app.time_hi.set(float(app.time_lo.cget("to")))
    app.update_plot()

    # bearings: Off must not crash, slots must round-trip
    app.slot_var.set(0)
    try:
        app.on_save_bearing()          # shows an info box; harmless when hidden
        check("Save with Off selected does not crash", True)
    except Exception as exc:                           # noqa: BLE001
        check("Save with Off selected does not crash", False, repr(exc))

    app.slot_var.set(1)
    app.on_save_bearing()
    root.update_idletasks()
    check("bearing saved into slot 1",
          np.isfinite(app.bearings[0]["bearing_deg"]))
    app.update_plot()
    check("replot with a saved bearing does not crash", True)
    app.on_clear_bearing()
    check("bearing cleared", not np.isfinite(app.bearings[0]["bearing_deg"]))

    # export
    out = os.path.join(tempfile.mkdtemp(), "gui_export.kmz")
    try:
        app.export_kmz(out)
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
            doc = z.read("doc.kml").decode("utf-8")
        check("kmz written", names == {"doc.kml", "files/dot.png",
                                       "files/surface.png"}, str(sorted(names)))
        root_el = ET.fromstring(doc)
        ns = "{http://www.opengis.net/kml/2.2}"
        defined = {e.get("id") for e in root_el.iter(ns + "Style")}
        used = {e.text.lstrip("#") for e in root_el.iter(ns + "styleUrl")}
        check("no dangling style references", not (used - defined))
        folders = [e.find(ns + "name").text for e in root_el.iter(ns + "Folder")]
        check("expected folders", any("Pulses" in f for f in folders),
              str(folders))
        check("no external http references", "http://maps.google" not in doc)
        check("kmz size sane", 0 < os.path.getsize(out) < 5_000_000,
              "%d bytes" % os.path.getsize(out))
    except Exception as exc:                           # noqa: BLE001
        import traceback
        traceback.print_exc()
        check("kmz written", False, repr(exc))

    check("no error dialogs raised during the run",
          not [d for d in dialogs if d[0] == "showerror"], str(dialogs))

    root.destroy()
    print("\n%s" % ("ALL PASS" if not _failures
                    else "FAILURES: " + ", ".join(_failures)))
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
