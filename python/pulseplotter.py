#!/usr/bin/env python3
"""pulseplotter - plot UAV-RT pulse logs and export a KMZ for Google Earth.

Python port of pulseplotter2.m. Same behaviour, no MATLAB required.

    python3 pulseplotter.py [optional-pulse-log.csv]

Needs numpy and matplotlib. tkinter ships with Python.
"""

import os
import sys
import traceback

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib import colormaps
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg, NavigationToolbar2Tk)
from matplotlib.figure import Figure

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import analysis
import geodesy
from kmzwrite import kmzwrite
from readpulsetable import PulseLogError, read_pulse_table

PROPERTIES = ("SNR", "STFT Score", "Time", "Altitude (m)")
AXIS_MODES = ("x, y", "Lon, Lat")
N_BEARING_SLOTS = 3
SCATTER_BINS = 100


def empty_bearing():
    return {"bearing_deg": np.nan, "confidence": np.nan, "spread_deg": np.nan,
            "tag_id": np.nan, "property": "",
            "x": None, "y": None, "lon": None, "lat": None}


class PulsePlotter(ttk.Frame):

    def __init__(self, master):
        ttk.Frame.__init__(self, master)
        self.pack(fill=tk.BOTH, expand=True)

        self.data = None
        self.file_path = None
        self.file_name = ""
        self.plot_state = None
        self.current_bearing = empty_bearing()
        self.bearings = [empty_bearing() for _ in range(N_BEARING_SLOTS)]
        self.colorbar = None
        self._loading = False

        self._build_controls()
        self._build_plot()
        self.ax.set_title("Load a pulse CSV to begin")
        self.canvas.draw_idle()

    # ------------------------------------------------------------------ UI

    def _build_controls(self):
        left = ttk.Frame(self, padding=8)
        left.pack(side=tk.LEFT, fill=tk.Y)
        row = [0]

        def put(widget, span=2, **kw):
            widget.grid(row=row[0], column=0, columnspan=span, sticky="ew",
                        pady=1, **kw)
            row[0] += 1

        def pair(label, widget):
            ttk.Label(left, text=label).grid(row=row[0], column=0, sticky="w")
            widget.grid(row=row[0], column=1, sticky="ew", pady=1)
            row[0] += 1

        buttons = ttk.Frame(left)
        ttk.Button(buttons, text="Load Data", command=self.on_load).pack(
            side=tk.LEFT, padx=(0, 4))
        ttk.Button(buttons, text="Export KMZ", command=self.on_export).pack(
            side=tk.LEFT)
        put(buttons)

        self.file_var = tk.StringVar(value="(no file)")
        put(ttk.Label(left, textvariable=self.file_var, foreground="#555"))
        put(ttk.Separator(left, orient=tk.HORIZONTAL))

        self.tag_var = tk.StringVar()
        self.tag_box = ttk.Combobox(left, textvariable=self.tag_var,
                                    state="readonly", width=12, values=[])
        self.tag_box.bind("<<ComboboxSelected>>", lambda e: self.update_plot())
        pair("Tag ID", self.tag_box)

        self.axis_var = tk.StringVar(value=AXIS_MODES[0])
        box = ttk.Combobox(left, textvariable=self.axis_var, state="readonly",
                           width=12, values=list(AXIS_MODES))
        box.bind("<<ComboboxSelected>>", lambda e: self.update_plot())
        pair("Axis", box)

        self.prop_var = tk.StringVar(value=PROPERTIES[0])
        box = ttk.Combobox(left, textvariable=self.prop_var, state="readonly",
                           width=12, values=list(PROPERTIES))
        box.bind("<<ComboboxSelected>>", lambda e: self.update_plot())
        pair("Property", box)

        self.smooth_var = tk.IntVar(value=6)
        pair("Smoothing", tk.Spinbox(left, from_=0, to=10, width=8,
                                     textvariable=self.smooth_var,
                                     command=self.update_plot))

        self.grid_var = tk.IntVar(value=5)
        pair("Grid Res. (m)", tk.Spinbox(left, from_=1, to=50, width=8,
                                         textvariable=self.grid_var,
                                         command=self.update_plot))

        self.elev_var = tk.DoubleVar(value=0.0)
        elev = ttk.Entry(left, textvariable=self.elev_var, width=10)
        elev.bind("<Return>", lambda e: self.update_plot())
        elev.bind("<FocusOut>", lambda e: self.update_plot())
        pair("Elev (m)", elev)

        put(ttk.Separator(left, orient=tk.HORIZONTAL))

        self.plot_prop_var = tk.StringVar(value="Value")
        group = ttk.LabelFrame(left, text="Plot Property", padding=4)
        for text in ("Value", "Divergence"):
            ttk.Radiobutton(group, text=text, value=text,
                            variable=self.plot_prop_var,
                            command=self.update_plot).pack(anchor="w")
        put(group)

        self.tag_lat_var = tk.DoubleVar(value=0.0)
        self.tag_lon_var = tk.DoubleVar(value=0.0)
        for label, var in (("Tag Lat", self.tag_lat_var),
                           ("Tag Lon", self.tag_lon_var)):
            entry = ttk.Entry(left, textvariable=var, width=12)
            entry.bind("<Return>", lambda e: self.update_plot())
            entry.bind("<FocusOut>", lambda e: self.update_plot())
            pair(label, entry)

        self.plot_tag_var = tk.BooleanVar(value=False)
        put(ttk.Checkbutton(left, text="Plot Tag", variable=self.plot_tag_var,
                            command=self.update_plot))

        put(ttk.Separator(left, orient=tk.HORIZONTAL))

        group = ttk.LabelFrame(left, text="Active Bearing", padding=4)
        self.slot_var = tk.IntVar(value=0)
        for text, value in (("Off", 0), ("1", 1), ("2", 2), ("3", 3)):
            ttk.Radiobutton(group, text=text, value=value,
                            variable=self.slot_var).pack(side=tk.LEFT)
        buttons = ttk.Frame(group)
        ttk.Button(buttons, text="Save", width=6,
                   command=self.on_save_bearing).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Clear", width=6,
                   command=self.on_clear_bearing).pack(side=tk.LEFT)
        buttons.pack(pady=(4, 0))
        put(group)

        self.bearing_var = tk.StringVar(value="Bearing:  -")
        put(ttk.Label(left, textvariable=self.bearing_var))

        left.columnconfigure(1, weight=1)

    def _build_plot(self):
        right = ttk.Frame(self)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.figure = Figure(figsize=(7.5, 6.0), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas, right).update()

        sliders = ttk.Frame(right, padding=(8, 4))
        sliders.pack(fill=tk.X)

        self.time_lo, self.time_hi, self.time_label = self._range_slider(
            sliders, "Time (min)", 0)
        self.snr_lo, self.snr_hi, self.snr_label = self._range_slider(
            sliders, "SNR range", 1)
        sliders.columnconfigure(1, weight=1)

    def _range_slider(self, parent, label, base_row):
        """Two scales acting as a min/max pair. Tk has no native range slider."""
        ttk.Label(parent, text=label).grid(row=base_row * 2, column=0,
                                           rowspan=2, sticky="w", padx=(0, 6))
        lo = ttk.Scale(parent, from_=0.0, to=1.0, orient=tk.HORIZONTAL)
        hi = ttk.Scale(parent, from_=0.0, to=1.0, orient=tk.HORIZONTAL)
        lo.grid(row=base_row * 2, column=1, sticky="ew")
        hi.grid(row=base_row * 2 + 1, column=1, sticky="ew")
        lo.set(0.0)
        hi.set(1.0)
        value = tk.StringVar(value="-")
        ttk.Label(parent, textvariable=value, width=20).grid(
            row=base_row * 2, column=2, rowspan=2, sticky="w", padx=(6, 0))
        # Replot on release, like MATLAB's ValueChanged, not on every pixel.
        for scale in (lo, hi):
            scale.configure(command=lambda _v: self._refresh_slider_labels())
            scale.bind("<ButtonRelease-1>", lambda e: self.update_plot())
        return lo, hi, value

    # -------------------------------------------------------------- helpers

    def _slider_range(self, lo, hi):
        a, b = float(lo.get()), float(hi.get())
        return (a, b) if a <= b else (b, a)

    def _refresh_slider_labels(self):
        if self.data is None:
            return
        t0, t1 = self._slider_range(self.time_lo, self.time_hi)
        s0, s1 = self._slider_range(self.snr_lo, self.snr_hi)
        self.time_label.set("%.2f  to  %.2f min" % (t0, t1))
        self.snr_label.set("%.1f  to  %.1f dB" % (s0, s1))

    def _float(self, var, default=0.0):
        try:
            return float(var.get())
        except (tk.TclError, ValueError):
            return default

    def _int(self, var, default=0):
        try:
            return int(var.get())
        except (tk.TclError, ValueError):
            return default

    # ------------------------------------------------------------ callbacks

    def on_load(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(
                title="Select CSV Pulse Log",
                filetypes=[("Pulse logs", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            table, warn = read_pulse_table(path)
        except (PulseLogError, OSError) as exc:
            messagebox.showerror("Could not read pulse log", str(exc))
            return
        if warn:
            messagebox.showwarning("Pulse log warning", warn)

        self._loading = True
        try:
            self.data = table
            self.file_path = os.path.dirname(path)
            self.file_name = os.path.splitext(os.path.basename(path))[0]
            self.file_var.set(self.file_name)

            # A new flight invalidates anything saved against the old one.
            self.bearings = [empty_bearing() for _ in range(N_BEARING_SLOTS)]
            self.current_bearing = empty_bearing()
            self.plot_state = None

            tags = np.unique(table.tag_id)
            self.tag_box["values"] = [self._fmt_tag(t) for t in tags]
            values, counts = np.unique(table.tag_id, return_counts=True)
            self.tag_var.set(self._fmt_tag(values[np.argmax(counts)]))

            minutes = (table.start_time_seconds
                       - table.start_time_seconds[0]) / 60.0
            t_lo, t_hi = float(minutes.min()), float(minutes.max())
            if t_hi <= t_lo:
                t_hi = t_lo + 1.0 / 60.0
            for scale in (self.time_lo, self.time_hi):
                scale.configure(from_=t_lo, to=t_hi)
            self.time_lo.set(t_lo)
            self.time_hi.set(t_hi)

            snr = table.snr[np.isfinite(table.snr)]
            s_lo = float(snr.min()) if snr.size else 0.0
            s_hi = float(snr.max()) if snr.size else 1.0
            if s_hi <= s_lo:
                s_hi = s_lo + 1.0
            for scale in (self.snr_lo, self.snr_hi):
                scale.configure(from_=s_lo, to=s_hi)
            self.snr_lo.set(s_lo)
            self.snr_hi.set(s_hi)
        finally:
            self._loading = False

        self._refresh_slider_labels()
        self.update_plot()

    @staticmethod
    def _fmt_tag(value):
        return str(int(value)) if float(value).is_integer() else "%g" % value

    def on_save_bearing(self):
        slot = self.slot_var.get()
        if slot == 0:
            messagebox.showinfo("No bearing slot selected",
                                "Select bearing slot 1, 2 or 3 before saving.")
            return
        if not np.isfinite(self.current_bearing["bearing_deg"]):
            messagebox.showinfo("No bearing",
                                "There is no bearing to save for the current "
                                "selection.")
            return
        self.bearings[slot - 1] = dict(self.current_bearing)
        self.update_plot()

    def on_clear_bearing(self):
        slot = self.slot_var.get()
        if slot == 0:
            messagebox.showinfo("No bearing slot selected",
                                "Select bearing slot 1, 2 or 3 before clearing.")
            return
        self.bearings[slot - 1] = empty_bearing()
        self.update_plot()

    def on_export(self):
        if self.plot_state is None or self.data is None:
            messagebox.showinfo("Nothing to export",
                                "Load a pulse log and plot it before exporting.")
            return
        state = self.plot_state
        default = "%s_%s_KML.kmz" % (
            self.file_name, state["property"].replace(" ", "_").replace("(", "")
                                             .replace(")", ""))
        path = filedialog.asksaveasfilename(
            title="Save KMZ", defaultextension=".kmz",
            initialdir=self.file_path, initialfile=default,
            filetypes=[("Google Earth KMZ", "*.kmz")])
        if not path:
            return
        try:
            self.export_kmz(path)
        except Exception as exc:                      # noqa: BLE001
            traceback.print_exc()
            messagebox.showerror("KMZ export failed", str(exc))
            return
        messagebox.showinfo("Export complete", "Wrote %s" % path)

    def export_kmz(self, path):
        """Write the current plot to a KMZ. Separate from the dialog so it can
        be called directly, including from tests."""
        state = self.plot_state
        if state is None:
            raise RuntimeError("nothing plotted")
        kwargs = dict(name=self.file_name,
                          description="Tag %s, %s" % (state["tag_id"],
                                                      state["property"]),
                      value_name=state["property"])
        if state["grid"] is not None:
            kwargs.update(grid_lat=state["grid_lat"],
                          grid_lon=state["grid_lon"],
                          grid_value=state["grid"])
        if state["lat"].size:
            kwargs.update(point_lat=state["lat"], point_lon=state["lon"],
                          point_alt=state["alt_abs"],
                          point_value=state["prop"],
                          point_altitude_mode="absolute",
                          point_folder_name="Pulses (tag %s)" % state["tag_id"])
        if state["plot_tag"]:
            kwargs.update(marker_lat=state["tag_lat"],
                          marker_lon=state["tag_lon"],
                          marker_name="Tag", marker_folder_name="Tag")
        return kmzwrite(path, **kwargs)

    # ------------------------------------------------------------ the plot

    def update_plot(self, *_):
        if self.data is None or self._loading or not self.tag_var.get():
            return
        try:
            self._update_plot()
        except Exception as exc:                      # noqa: BLE001
            traceback.print_exc()
            messagebox.showerror("Plot failed", str(exc))

    def _update_plot(self):
        table = self.data
        selected_tag = float(self.tag_var.get())

        time_sec = table.start_time_seconds - table.start_time_seconds[0]
        t_lo, t_hi = self._slider_range(self.time_lo, self.time_hi)
        s_lo, s_hi = self._slider_range(self.snr_lo, self.snr_hi)

        mask = ((table.tag_id == selected_tag)
                & (time_sec >= t_lo * 60.0) & (time_sec <= t_hi * 60.0)
                & (table.snr >= s_lo) & (table.snr <= s_hi))
        sub = table.mask(mask)

        # Origin of the local frame: the first pulse of the flight.
        home = (float(table.lat[0]), float(table.lon[0]), 0.0)
        xe_all, yn_all, _ = geodesy.geo2enu(table.lat, table.lon,
                                            table.alt_rel, home)
        xe, yn, zu = geodesy.geo2enu(sub.lat, sub.lon, sub.alt_rel, home)

        use_lonlat = self.axis_var.get() == "Lon, Lat"

        prop_name = self.prop_var.get()
        if prop_name == "SNR":
            prop = sub.snr
        elif prop_name == "STFT Score":
            prop = sub.stft_score
        elif prop_name == "Time":
            prop = time_sec[mask]
        else:
            prop = zu
        prop = np.asarray(prop, dtype=float)

        smooth = self._int(self.smooth_var, 0)
        if smooth > 1 and prop.size:
            prop = analysis.movmean(prop, smooth)

        grid_res = max(self._int(self.grid_var, 5), 1)
        X, Y, grid, grid_res = analysis.build_grid(xe, yn, prop, grid_res)
        grid_lat = grid_lon = None
        if grid is not None:
            grid_lat, grid_lon, _ = geodesy.enu2geo(X, Y, np.zeros_like(X), home)

        bearing = empty_bearing()
        bearing["tag_id"] = selected_tag
        bearing["property"] = prop_name
        if grid is not None:
            b, conf, spread = analysis.estimate_bearing(grid, grid_res)
            bearing["bearing_deg"] = b
            bearing["confidence"] = conf
            bearing["spread_deg"] = spread
            bearing["x"] = float(np.nanmean(xe))
            bearing["y"] = float(np.nanmean(yn))
            blat, blon, _ = geodesy.enu2geo(bearing["x"], bearing["y"], 0.0, home)
            bearing["lat"] = float(blat)
            bearing["lon"] = float(blon)
        self.current_bearing = bearing

        # ---- draw ----
        ax = self.ax
        if self.colorbar is not None:
            try:
                self.colorbar.remove()
            except Exception:                          # noqa: BLE001
                pass
            self.colorbar = None
        ax.clear()

        if use_lonlat:
            ax.scatter(table.lon, table.lat, s=40, c="#cccccc", label="All pulses")
        else:
            ax.scatter(xe_all, yn_all, s=40, c="#cccccc", label="All pulses")

        if self.plot_tag_var.get():
            tag_lat = self._float(self.tag_lat_var)
            tag_lon = self._float(self.tag_lon_var)
            if use_lonlat:
                tx, ty = tag_lon, tag_lat
            else:
                tx, ty, _ = geodesy.geo2enu(tag_lat, tag_lon, 0.0, home)
            ax.scatter([tx], [ty], s=260, c="k", marker="*", label="Tag",
                       zorder=5)

        if grid is not None:
            horiz, vert = (grid_lon, grid_lat) if use_lonlat else (X, Y)
            if self.plot_prop_var.get() == "Divergence":
                fx, fy = analysis.gradient_field(grid, grid_res)
                field = analysis.divergence(fx, fy, grid_res)
                cs = ax.contourf(horiz, vert, field, cmap="viridis")
                self.colorbar = self.figure.colorbar(cs, ax=ax)
                self.colorbar.set_label("div(grad %s)" % prop_name)
            else:
                cs = ax.contourf(horiz, vert, grid, alpha=0.6, cmap="turbo")
                self.colorbar = self.figure.colorbar(cs, ax=ax)
                self.colorbar.set_label(prop_name)

        if use_lonlat:
            ax.set_xlabel("Longitude (deg)")
            ax.set_ylabel("Latitude (deg)")
            # A degree of longitude is shorter than a degree of latitude, so an
            # equal aspect would stretch the map east-west.
            ax.set_aspect(1.0 / np.cos(np.radians(home[0])))
        else:
            ax.set_xlabel("X-position, East (m)")
            ax.set_ylabel("Y-position, North (m)")
            ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)

        span = min(np.ptp(ax.get_xlim()), np.ptp(ax.get_ylim()))
        if not np.isfinite(span) or span <= 0:
            span = 1.0
        arrow = 0.2 * span
        lon_scale = 1.0 / np.cos(np.radians(home[0])) if use_lonlat else 1.0

        for entry, style in ([(bearing, "--")]
                             + [(b, "-") for b in self.bearings]):
            if not np.isfinite(entry["bearing_deg"]) or entry["x"] is None:
                continue
            dx = np.sin(np.radians(entry["bearing_deg"])) * lon_scale
            dy = np.cos(np.radians(entry["bearing_deg"]))
            ox, oy = ((entry["lon"], entry["lat"]) if use_lonlat
                      else (entry["x"], entry["y"]))
            ax.annotate("", xy=(ox + arrow * dx, oy + arrow * dy),
                        xytext=(ox, oy),
                        arrowprops=dict(arrowstyle="->", lw=1.6,
                                        color="#333333",
                                        linestyle="dashed" if style == "--"
                                        else "solid"))

        if prop.size:
            colors = colormaps["turbo"](
                analysis.color_bins(prop, SCATTER_BINS) / (SCATTER_BINS - 1.0))
            if use_lonlat:
                ax.scatter(sub.lon, sub.lat, s=40, c=colors,
                           edgecolors="none", label="Selected pulses")
            else:
                ax.scatter(xe, yn, s=40, c=colors, edgecolors="none",
                           label="Selected pulses")

        if np.isfinite(bearing["bearing_deg"]):
            text = ("bearing %.1f° (conf %.2f, ±%.0f°)"
                    % (bearing["bearing_deg"], bearing["confidence"],
                       bearing["spread_deg"]))
            self.bearing_var.set("Bearing:  %.1f°\nconf %.2f  ±%.0f°"
                                 % (bearing["bearing_deg"],
                                    bearing["confidence"],
                                    bearing["spread_deg"]))
        else:
            text = "bearing n/a"
            self.bearing_var.set("Bearing:  -")

        ax.set_title("Tag %s  |  %s  |  %d of %d pulses  |  %s"
                     % (self.tag_var.get(), prop_name, len(sub), len(table),
                        text), fontsize=10)
        self.canvas.draw_idle()

        # Snapshot for the exporter. Building the KMZ here would rebuild every
        # placemark on every slider drag, which is what made the original crawl.
        self.plot_state = {
            "lat": sub.lat, "lon": sub.lon,
            "alt_abs": zu + self._float(self.elev_var),
            "prop": prop, "grid": grid,
            "grid_lat": grid_lat, "grid_lon": grid_lon,
            "property": prop_name, "tag_id": self.tag_var.get(),
            "plot_tag": bool(self.plot_tag_var.get()),
            "tag_lat": self._float(self.tag_lat_var),
            "tag_lon": self._float(self.tag_lon_var),
        }


def main(argv):
    root = tk.Tk()
    root.title("pulseplotter")
    root.geometry("1150x720")
    app = PulsePlotter(root)
    if len(argv) > 1 and os.path.exists(argv[1]):
        root.after(100, lambda: app.on_load(argv[1]))
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
