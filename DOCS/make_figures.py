#!/usr/bin/env python3
"""Regenerate the plot figures in pulseplotter-guide.tex.

Every figure here is real output from the application: the script builds the
actual PulsePlotter window with its root withdrawn, loads a real pulse log,
drives the same controls a user would, and saves the app's own matplotlib
figure. Nothing is redrawn or idealised for the document.

The two logs live outside the repository, under FLIGHT_TESTING_DATA. Pass other
paths as arguments if yours are elsewhere:

    python3 make_figures.py [day5.csv] [day8.csv]

Run it from DOCS/ with the python/ venv active, or:

    ../python/.venv/bin/python make_figures.py
"""

import os
import sys
import tkinter as tk

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FIGURES = os.path.join(HERE, "figures")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "python"))

FLIGHT_DATA = os.path.expanduser(
    "~/Library/CloudStorage/OneDrive-NorthernArizonaUniversity/FLIGHT_TESTING_DATA")
DAY5 = os.path.join(FLIGHT_DATA, "2025-11-21-Cumbria-Day5-Fri", "HERELINK_LOGS",
                    "Pulse-2025-11-21-11-08-41-149.csv")
DAY8 = os.path.join(FLIGHT_DATA, "2025-11-24-Cumbria-Day8-Mon", "HERELINK_LOGS",
                    "Pulse-2025-11-24-15-42-40-343.csv")

# Two sizes: figures that appear across the full text width, and figures that
# appear two-up. Saving the two-up ones smaller means less reduction on the
# page, which keeps their axis and title text legible.
FIG_SIZE = (7.2, 4.6)
FIG_SIZE_HALF = (4.9, 3.5)
DPI = 200


def set_time_range(app, lo=None, hi=None):
    """Drive the time slider. With no arguments, widen it to the whole log -
    which is what a user does to look at takeoff and landing."""
    lo = float(app.time_lo.cget("from")) if lo is None else lo
    hi = float(app.time_hi.cget("to")) if hi is None else hi
    app.time_lo.set(lo)
    app.time_hi.set(hi)
    app.update_plot()


def default_time_range(app):
    """The window on_load chose: the flight proper, takeoff and landing off."""
    return app._slider_range(app.time_lo, app.time_hi)


def save(app, name, size=FIG_SIZE):
    app.figure.set_size_inches(*size)
    app.canvas.draw()
    path = os.path.join(FIGURES, name)
    app.figure.savefig(path, dpi=DPI, bbox_inches="tight")
    print("  %-28s %s" % (name, app.ax.get_title().replace("\n", " | ")))
    return path


def main(argv):
    day5 = argv[1] if len(argv) > 1 else DAY5
    day8 = argv[2] if len(argv) > 2 else DAY8
    for path in (day5, day8):
        if not os.path.exists(path):
            print("missing pulse log: %s" % path)
            return 1
    os.makedirs(FIGURES, exist_ok=True)

    import pulseplotter
    import analysis

    root = tk.Tk()
    root.withdraw()
    app = pulseplotter.PulsePlotter(root)

    print("figures from %s" % os.path.basename(day8))
    app.on_load(day8)
    app.tag_var.set("12")

    app.axis_var.set("Lon, Lat")
    app.update_plot()
    save(app, "plot-day8-lonlat.pdf", FIG_SIZE_HALF)
    app.axis_var.set("x, y")

    app.plot_prop_var.set("Divergence")
    app.update_plot()
    save(app, "plot-day8-divergence.pdf", FIG_SIZE_HALF)
    app.plot_prop_var.set("Value")

    print("figures from %s" % os.path.basename(day5))
    app.on_load(day5)
    for tag in ("42", "40"):
        app.tag_var.set(tag)
        app.update_plot()
        save(app, "plot-day5-tag%s.pdf" % tag, FIG_SIZE_HALF)

    # The altitude caution needs the whole flight: with takeoff and landing
    # deselected the aircraft holds one altitude, so there is no surface to
    # take a gradient of. The caption says the slider was widened.
    app.tag_var.set("42")
    app.prop_var.set("Altitude (m)")
    set_time_range(app)
    save(app, "plot-day5-altitude.pdf", FIG_SIZE_HALF)
    app.prop_var.set("SNR")

    # What the default time window is for: the same tag with the climb and
    # descent included, and with them deselected.
    print("takeoff/landing comparison")
    app.on_load(day8)
    app.tag_var.set("12")
    app.update_plot()
    cruise = default_time_range(app)
    set_time_range(app)
    save(app, "plot-day8-with-takeoff.pdf", FIG_SIZE_HALF)
    set_time_range(app, *cruise)
    save(app, "plot-day8-cruise.pdf", FIG_SIZE_HALF)

    # The gradient field the bearing is computed from, on real data: one flight
    # where the field agrees on a direction and one where it does not.
    print("theory figures")
    gradient_figure(app, analysis, [
        (day5, "42", "Day 5, tag 42 - the field agrees"),
        (day8, "12", "Day 8, tag 12 - flown over the tag"),
    ])
    root.destroy()

    confidence_figure(analysis)
    return 0


def gradient_figure(app, analysis, cases):
    """The interpolated surface, its gradient field, and the resultant.

    One panel per case, so the guide can put a field that agrees on a direction
    next to one that does not.
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    fig = Figure(figsize=(7.4, 3.4), layout="constrained")
    axes = fig.subplots(1, len(cases))
    for ax, (log, tag, caption) in zip(np.atleast_1d(axes), cases):
        app.on_load(log)
        app.tag_var.set(tag)
        app.update_plot()
        state = app.plot_state
        grid, res = state["grid"], state["grid_res"]
        ny, nx = grid.shape
        X, Y = np.meshgrid(np.arange(nx) * res, np.arange(ny) * res)
        fx, fy = analysis.gradient_field(grid, res)
        bearing, confidence, spread = analysis.estimate_bearing(grid, res)

        cs = ax.contourf(X, Y, grid, levels=14, cmap="turbo", alpha=0.7)
        fig.colorbar(cs, ax=ax, shrink=0.88).set_label("SNR (dB)", fontsize=8)

        step = max(nx // 16, ny // 16, 1)
        sl = (slice(None, None, step), slice(None, None, step))
        ax.quiver(X[sl], Y[sl], fx[sl], fy[sl], color="#222222", width=0.005,
                  alpha=0.85)

        ok = np.isfinite(fx) & np.isfinite(fy)
        rx, ry = float(np.nansum(fx[ok])), float(np.nansum(fy[ok]))
        norm = np.hypot(rx, ry)
        length = 0.40 * min(np.ptp(X), np.ptp(Y))
        cx = float(np.nanmean(X[np.isfinite(grid)]))
        cy = float(np.nanmean(Y[np.isfinite(grid)]))
        ax.annotate("", xy=(cx + length * rx / norm, cy + length * ry / norm),
                    xytext=(cx, cy),
                    arrowprops=dict(arrowstyle="-|>", lw=2.6, color="k"))
        ax.set_title("%s\n$\\beta$ = %.1f$^\\circ$,  $R$ = %.2f,  "
                     "$\\sigma$ = %.0f$^\\circ$"
                     % (caption, bearing, confidence, spread), fontsize=9)
        ax.set_xlabel("East (m)", fontsize=8)
        ax.set_ylabel("North (m)", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.set_aspect("equal")
        print("  %-28s %s: bearing %.1f deg, R = %.2f, spread %.0f deg"
              % ("theory-gradient.pdf", caption, bearing, confidence, spread))
    fig.savefig(os.path.join(FIGURES, "theory-gradient.pdf"), dpi=DPI,
                bbox_inches="tight")


def confidence_figure(analysis):
    """What R and the bearing error do as the field stops agreeing.

    A clean plane at 45 degrees with increasing zero-mean noise. R collapses
    far faster than the bearing degrades, which is the point worth making in
    the guide: R measures how much the cells agree, not how wrong the answer is.
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    rng = np.random.default_rng(0)
    res, n = 5.0, 60
    x, y = np.meshgrid(np.arange(n) * res, np.arange(n) * res)
    clean = 0.05 * (x * np.sin(np.radians(45)) + y * np.cos(np.radians(45)))
    sigma = np.logspace(np.log10(0.3), np.log10(150.0), 22)
    conf, err = [], []
    for s in sigma:
        trials = [analysis.estimate_bearing(clean + rng.normal(0, s, clean.shape),
                                            res) for _ in range(16)]
        b = np.array([t[0] for t in trials])
        conf.append(np.mean([t[1] for t in trials]))
        err.append(np.std(np.mod(b - 45.0 + 180, 360) - 180))
    conf, err = np.array(conf), np.array(err)

    fig = Figure(figsize=(6.6, 3.0), layout="constrained")
    ax = fig.add_subplot(111)
    ax.semilogx(sigma, conf, "o-", color="#1f77b4", ms=3.5)
    ax.set_xlabel("noise standard deviation added to the surface (dB)")
    ax.set_ylabel("confidence $R$", color="#1f77b4")
    ax.tick_params(axis="y", labelcolor="#1f77b4")
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.3, which="both")
    rhs = ax.twinx()
    rhs.semilogx(sigma, err, "s--", color="#d62728", ms=3.5)
    rhs.set_ylabel("bearing error, deg RMS", color="#d62728")
    rhs.tick_params(axis="y", labelcolor="#d62728")
    fig.savefig(os.path.join(FIGURES, "theory-confidence.pdf"), dpi=DPI,
                bbox_inches="tight")
    half = int(np.argmin(np.abs(conf - 0.5)))
    print("  %-28s R = %.2f at %.1f dB noise, where the bearing is still %.1f deg out"
          % ("theory-confidence.pdf", conf[half], sigma[half], err[half]))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
