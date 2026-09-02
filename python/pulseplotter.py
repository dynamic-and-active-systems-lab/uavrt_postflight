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
from tkinter import filedialog, font as tkfont, messagebox, ttk

import analysis
import geodesy
from kmzwrite import kmzwrite
from readpulsetable import PulseLogError, read_pulse_table

PROPERTIES = ("SNR", "STFT Score", "Time", "Altitude (m)")
AXIS_MODES = ("x, y", "Lon, Lat")
N_BEARING_SLOTS = 3
SCATTER_BINS = 100

# Layout constants. The control column is a fixed width so that a long file
# name can never widen it and squeeze the plot; it scrolls instead of clipping
# when the window is too short, which is what GridLayout.Scrollable does in the
# MATLAB app. MIN_WINDOW is the smallest size at which every control still has
# its natural size, and is enforced with wm_minsize.
SIDEBAR_WIDTH = 262
MIN_WINDOW = (900, 560)


def empty_bearing():
    return {"bearing_deg": np.nan, "confidence": np.nan, "spread_deg": np.nan,
            "tag_id": np.nan, "property": "",
            "x": None, "y": None, "lon": None, "lat": None}


class ScrollableSidebar(ttk.Frame):
    """Fixed-width control column that scrolls instead of clipping.

    Tk's pack and grid managers silently cut off whatever does not fit, so a
    short window would otherwise hide the controls at the bottom of the column
    with no indication that they exist. This mirrors GridLayout.Scrollable in
    the MATLAB app: the column keeps its natural width, and grows a scrollbar
    only when there is something to scroll.
    """

    def __init__(self, master, width=SIDEBAR_WIDTH):
        ttk.Frame.__init__(self, master)
        background = ttk.Style().lookup("TFrame", "background")

        self.canvas = tk.Canvas(self, width=width, borderwidth=0,
                                highlightthickness=0, takefocus=0)
        if background:
            self.canvas.configure(background=background)
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL,
                                       command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._sync_scrollbar)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.body = ttk.Frame(self.canvas, padding=(12, 10, 12, 14))
        self._window = self.canvas.create_window((0, 0), window=self.body,
                                                 anchor="nw")
        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        # bind_all rather than <Enter>/<Leave>: crossing into a child widget
        # fires Leave on the parent, which would keep switching the wheel off.
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(sequence, self._on_wheel, add="+")

    def _on_body_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # Keep the column exactly as wide as the visible canvas, so nothing is
        # pushed off the right-hand edge and no horizontal scrolling is needed.
        self.canvas.itemconfigure(self._window, width=event.width)

    def _sync_scrollbar(self, first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.scrollbar.pack_forget()
        elif not self.scrollbar.winfo_ismapped():
            self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.scrollbar.set(first, last)

    def _on_wheel(self, event):
        if not self.scrollbar.winfo_ismapped():
            return
        under = self.winfo_containing(event.x_root, event.y_root)
        while under is not None:
            if under is self:
                break
            under = getattr(under, "master", None)
        else:
            return
        if event.num == 4:
            step = -1
        elif event.num == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step, "units")


def install_styles():
    """Named styles used across the window. Keeps the platform's native ttk
    theme - aqua on macOS, vista on Windows - and only adds to it."""
    style = ttk.Style()
    base = tkfont.nametofont("TkDefaultFont")
    heading = base.copy()
    heading.configure(size=max(base.cget("size") - 1, 9), weight="bold")
    small = base.copy()
    small.configure(size=max(base.cget("size") - 1, 9))

    style.configure("Section.TLabel", font=heading, foreground="#4a5568")
    style.configure("Readout.TLabel", font=small, foreground="#4a5568")
    style.configure("Filename.TEntry", font=small)
    return style


class PulsePlotter(ttk.Frame):

    def __init__(self, master):
        ttk.Frame.__init__(self, master)
        install_styles()
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
        sidebar = ScrollableSidebar(self)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar = sidebar
        left = sidebar.body
        left.columnconfigure(0, weight=0)
        left.columnconfigure(1, weight=1)
        row = [0]

        def full(widget, **kw):
            """A widget that spans the whole column."""
            kw.setdefault("pady", 2)
            widget.grid(row=row[0], column=0, columnspan=2, sticky="ew", **kw)
            row[0] += 1
            return widget

        def pair(label, widget):
            """A right-aligned caption and its control, on one line."""
            ttk.Label(left, text=label, anchor="e").grid(
                row=row[0], column=0, sticky="e", padx=(0, 8), pady=2)
            widget.grid(row=row[0], column=1, sticky="ew", pady=2)
            row[0] += 1
            return widget

        def section(text):
            """Caption plus a rule running out to the right-hand edge."""
            holder = ttk.Frame(left)
            holder.grid(row=row[0], column=0, columnspan=2, sticky="ew",
                        pady=(12, 4))
            ttk.Label(holder, text=text, style="Section.TLabel").pack(
                side=tk.LEFT)
            ttk.Separator(holder, orient=tk.HORIZONTAL).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
            row[0] += 1

        def readout(label):
            var = tk.StringVar(value="-")
            entry = ttk.Entry(left, textvariable=var, width=8,
                              state="readonly", justify="right")
            pair(label, entry)
            return var

        # ---- file -----------------------------------------------------
        buttons = ttk.Frame(left)
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="Load Data", command=self.on_load).grid(
            row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="Export KMZ", command=self.on_export).grid(
            row=0, column=1, sticky="ew")
        full(buttons, pady=(0, 4))

        self.file_var = tk.StringVar(value="(no file loaded)")
        # Read-only entry rather than a label: a label would size itself to the
        # file name and widen the whole column.
        file_entry = ttk.Entry(left, textvariable=self.file_var, width=8,
                               state="readonly", style="Filename.TEntry")
        pair("File", file_entry)

        # ---- data selection -------------------------------------------
        section("Data selection")

        self.tag_var = tk.StringVar()
        self.tag_box = ttk.Combobox(left, textvariable=self.tag_var,
                                    state="readonly", width=8, values=[])
        self.tag_box.bind("<<ComboboxSelected>>", lambda e: self.update_plot())
        pair("Tag ID", self.tag_box)

        self.axis_var = tk.StringVar(value=AXIS_MODES[0])
        box = ttk.Combobox(left, textvariable=self.axis_var, state="readonly",
                           width=8, values=list(AXIS_MODES))
        box.bind("<<ComboboxSelected>>", lambda e: self.update_plot())
        pair("Axis", box)

        self.prop_var = tk.StringVar(value=PROPERTIES[0])
        box = ttk.Combobox(left, textvariable=self.prop_var, state="readonly",
                           width=8, values=list(PROPERTIES))
        box.bind("<<ComboboxSelected>>", lambda e: self.update_plot())
        pair("Property", box)

        # ---- surface ---------------------------------------------------
        section("Surface")

        self.smooth_var = tk.IntVar(value=6)
        pair("Smoothing", tk.Spinbox(left, from_=0, to=10, width=6,
                                     justify="right",
                                     textvariable=self.smooth_var,
                                     command=self.update_plot))

        self.grid_var = tk.IntVar(value=5)
        pair("Grid Res. (m)", tk.Spinbox(left, from_=1, to=50, width=6,
                                         justify="right",
                                         textvariable=self.grid_var,
                                         command=self.update_plot))

        self.elev_var = tk.DoubleVar(value=0.0)
        elev = ttk.Entry(left, textvariable=self.elev_var, width=8,
                         justify="right")
        elev.bind("<Return>", lambda e: self.update_plot())
        elev.bind("<FocusOut>", lambda e: self.update_plot())
        pair("Elev (m)", elev)

        self.plot_prop_var = tk.StringVar(value="Value")
        radios = ttk.Frame(left)
        ttk.Label(radios, text="Plot").pack(side=tk.LEFT, padx=(0, 8))
        for text in ("Value", "Divergence"):
            ttk.Radiobutton(radios, text=text, value=text,
                            variable=self.plot_prop_var,
                            command=self.update_plot).pack(side=tk.LEFT,
                                                           padx=(0, 10))
        full(radios)

        # ---- tag position ----------------------------------------------
        section("Tag position")

        self.tag_lat_var = tk.DoubleVar(value=0.0)
        self.tag_lon_var = tk.DoubleVar(value=0.0)
        for label, var in (("Tag Lat", self.tag_lat_var),
                           ("Tag Lon", self.tag_lon_var)):
            entry = ttk.Entry(left, textvariable=var, width=8,
                              justify="right")
            entry.bind("<Return>", lambda e: self.update_plot())
            entry.bind("<FocusOut>", lambda e: self.update_plot())
            pair(label, entry)

        self.plot_tag_var = tk.BooleanVar(value=False)
        check = ttk.Frame(left)
        ttk.Checkbutton(check, text="Show on plot",
                        variable=self.plot_tag_var,
                        command=self.update_plot).pack(side=tk.LEFT)
        pair("Plot Tag", check)

        # ---- bearing ----------------------------------------------------
        section("Bearing")

        self.slot_var = tk.IntVar(value=0)
        slots = ttk.Frame(left)
        ttk.Label(slots, text="Active").pack(side=tk.LEFT, padx=(0, 8))
        for text, value in (("Off", 0), ("1", 1), ("2", 2), ("3", 3)):
            ttk.Radiobutton(slots, text=text, value=value,
                            variable=self.slot_var).pack(side=tk.LEFT,
                                                         padx=(0, 6))
        full(slots)

        actions = ttk.Frame(left)
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Save", command=self.on_save_bearing).grid(
            row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(actions, text="Clear", command=self.on_clear_bearing).grid(
            row=0, column=1, sticky="ew")
        full(actions, pady=(4, 2))

        self.bearing_var = readout("Bearing (deg)")
        self.confidence_var = readout("Confidence")
        self.spread_var = readout("Spread (deg)")

    def _build_plot(self):
        right = ttk.Frame(self)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Grid, not pack: the plot is the only row that gives up space, so the
        # toolbar and the sliders always get the height they asked for. Packing
        # the canvas first with expand=True let it take its full requested
        # height and left the last-packed strip to be clipped - which is how
        # the toolbar ended up drawn over the SNR sliders.
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1, minsize=160)   # plot
        right.rowconfigure(1, weight=0)                # matplotlib toolbar
        right.rowconfigure(2, weight=0)                # range sliders

        # constrained layout keeps the title, axis labels and colorbar inside
        # the canvas at any size instead of letting them run off the edge.
        self.figure = Figure(figsize=(6.0, 4.2), dpi=100, layout="constrained")
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        self.toolbar = NavigationToolbar2Tk(self.canvas, right,
                                            pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.grid(row=1, column=0, sticky="ew")
        background = ttk.Style().lookup("TFrame", "background")
        if background:
            for widget in [self.toolbar] + self.toolbar.winfo_children():
                try:
                    widget.configure(background=background)
                except tk.TclError:
                    pass

        sliders = ttk.Frame(right, padding=(12, 6, 14, 10))
        sliders.grid(row=2, column=0, sticky="ew")
        sliders.columnconfigure(0, weight=0)
        sliders.columnconfigure(1, weight=1)
        # Fixed minimum so the readout never has to shrink into an ellipsis and
        # the slider column does not jump about as the numbers change width.
        sliders.columnconfigure(2, weight=0, minsize=170)

        self.time_lo, self.time_hi, self.time_label = self._range_slider(
            sliders, "Time (min)", 0)
        self.snr_lo, self.snr_hi, self.snr_label = self._range_slider(
            sliders, "SNR range", 1)

    def _range_slider(self, parent, label, base_row):
        """Two scales acting as a min/max pair. Tk has no native range slider."""
        top = base_row * 2
        ttk.Label(parent, text=label).grid(
            row=top, column=0, rowspan=2, sticky="e", padx=(0, 10))
        lo = ttk.Scale(parent, from_=0.0, to=1.0, orient=tk.HORIZONTAL)
        hi = ttk.Scale(parent, from_=0.0, to=1.0, orient=tk.HORIZONTAL)
        lo.grid(row=top, column=1, sticky="ew", pady=(0, 1))
        hi.grid(row=top + 1, column=1, sticky="ew", pady=(1, 0))
        lo.set(0.0)
        hi.set(1.0)
        value = tk.StringVar(value="-")
        ttk.Label(parent, textvariable=value, style="Readout.TLabel",
                  anchor="w").grid(row=top, column=2, rowspan=2, sticky="w",
                                   padx=(10, 0))
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
            # Limits span the whole log; only the initial value is narrowed to
            # the flight proper, so takeoff and landing stay one drag away.
            for scale in (self.time_lo, self.time_hi):
                scale.configure(from_=t_lo, to=t_hi)
            c_lo, c_hi = analysis.flight_window(minutes, table.alt_rel)
            if not (np.isfinite(c_lo) and np.isfinite(c_hi) and c_lo < c_hi):
                c_lo, c_hi = t_lo, t_hi
            self.time_lo.set(min(max(c_lo, t_lo), t_hi))
            self.time_hi.set(max(min(c_hi, t_hi), t_lo))

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
            self.bearing_var.set("%.1f" % bearing["bearing_deg"])
            self.confidence_var.set("%.2f" % bearing["confidence"])
            self.spread_var.set("%.0f" % bearing["spread_deg"])
        else:
            text = "bearing n/a"
            for var in (self.bearing_var, self.confidence_var,
                        self.spread_var):
                var.set("-")

        # Two lines: one long title runs off the ends of a narrow canvas.
        ax.set_title("Tag %s  ·  %s  ·  %d of %d pulses\n%s"
                     % (self.tag_var.get(), prop_name, len(sub), len(table),
                        text), fontsize=10)
        self.canvas.draw_idle()

        # Snapshot for the exporter. Building the KMZ here would rebuild every
        # placemark on every slider drag, which is what made the original crawl.
        self.plot_state = {
            "lat": sub.lat, "lon": sub.lon,
            "alt_abs": zu + self._float(self.elev_var),
            "prop": prop, "grid": grid, "grid_res": grid_res,
            "grid_lat": grid_lat, "grid_lon": grid_lon,
            "property": prop_name, "tag_id": self.tag_var.get(),
            "plot_tag": bool(self.plot_tag_var.get()),
            "tag_lat": self._float(self.tag_lat_var),
            "tag_lon": self._float(self.tag_lon_var),
        }


def main(argv):
    root = tk.Tk()
    root.title("pulseplotter")
    root.minsize(*MIN_WINDOW)
    root.geometry("1150x760")
    app = PulsePlotter(root)
    if len(argv) > 1 and os.path.exists(argv[1]):
        root.after(100, lambda: app.on_load(argv[1]))
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
