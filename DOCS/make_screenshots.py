#!/usr/bin/env python3
"""Recapture the application screenshots in pulseplotter-guide.tex.

Opens the real window with a real log loaded and photographs it, so the guide's
screenshots can be refreshed after a UI change rather than going stale.

    python3 make_screenshots.py [pulse-log.csv]

macOS only, and it needs Screen Recording permission for whatever is running
this: System Settings -> Privacy & Security -> Screen & System Audio Recording.
Without it screencapture fails with "could not create image from display".

The window must fit on the main display. WINDOW below is sized for a 1080-wide
portrait monitor; widen it if yours is bigger and the guide will get a roomier
screenshot.
"""

import os
import subprocess
import sys
import tempfile
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
FIGURES = os.path.join(HERE, "figures")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "python"))

DEFAULT_LOG = os.path.expanduser(
    "~/Library/CloudStorage/OneDrive-NorthernArizonaUniversity/"
    "FLIGHT_TESTING_DATA/2025-11-21-Cumbria-Day5-Fri/HERELINK_LOGS/"
    "Pulse-2025-11-21-11-08-41-149.csv")
TAG = "42"
WINDOW = (1024, 742, 28, 96)      # width, height, x, y
TITLE_BAR = 29                    # captured above the window's own origin


def capture(region, path):
    result = subprocess.run(
        ["screencapture", "-x", "-R", "%d,%d,%d,%d" % region, path],
        capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(path):
        raise SystemExit("screencapture failed: %s\n"
                         "Grant Screen Recording permission and try again."
                         % (result.stderr.strip() or "no output"))


def compose_columns(raw, out, cuts, body_height):
    """The control column is tall and thin; split it into two so it is legible
    at page width. Split on a section header so nothing is cut through."""
    from PIL import Image
    im = Image.open(raw).convert("RGB")
    w, h = im.size
    scale = h / float(body_height)
    cuts = [int(round(c * scale)) for c in cuts]
    cut = min(cuts, key=lambda c: abs(c - h / 2.0))

    gap, pad = 20, 8
    top, bottom = im.crop((0, 0, w, cut)), im.crop((0, cut, w, h))
    canvas = Image.new("RGB", (w * 2 + gap + pad * 2,
                               max(top.size[1], bottom.size[1]) + pad * 2),
                       "white")
    canvas.paste(top, (pad, pad))
    canvas.paste(bottom, (pad + w + gap, pad))
    canvas.save(out)
    return canvas.size


def main(argv):
    if sys.platform != "darwin":
        raise SystemExit("this script drives macOS screencapture")
    log = argv[1] if len(argv) > 1 else DEFAULT_LOG
    if not os.path.exists(log):
        raise SystemExit("missing pulse log: %s" % log)
    os.makedirs(FIGURES, exist_ok=True)

    import pulseplotter

    w, h, x, y = WINDOW
    root = tk.Tk()
    root.title("pulseplotter")
    root.minsize(*pulseplotter.MIN_WINDOW)
    root.geometry("%dx%d+%d+%d" % (w, h, x, y))
    app = pulseplotter.PulsePlotter(root)
    app.on_load(log)
    app.tag_var.set(TAG)
    app.update_plot()
    root.update_idletasks()
    root.update()
    root.lift()
    root.attributes("-topmost", True)

    state = {}

    def shoot():
        for _ in range(6):
            root.update_idletasks()
            root.update()
        wx, wy = root.winfo_rootx(), root.winfo_rooty()
        ww, wh = root.winfo_width(), root.winfo_height()
        if wx + ww > root.winfo_screenwidth():
            print("warning: the window runs off the main display; the capture "
                  "will include whatever is beside it. Shrink WINDOW.")

        # Exactly the window's own rectangle: one row more and the capture
        # picks up whatever is behind it along the bottom edge.
        full = os.path.join(FIGURES, "screen-window.png")
        capture((wx - 1, wy - TITLE_BAR, ww + 2, wh + TITLE_BAR), full)
        state["window"] = (full, (ww + 2, wh + TITLE_BAR))

        # Ask Tk where the section headers are: a section is the frame holding
        # a label and a separator.
        cuts = [c.winfo_y() for c in app.sidebar.body.winfo_children()
                if c.winfo_class() == "TFrame"
                and any(k.winfo_class() == "TSeparator"
                        for k in c.winfo_children())]
        raw = os.path.join(tempfile.mkdtemp(), "sidebar-raw.png")
        body_h = app.sidebar.body.winfo_reqheight()
        capture((wx, wy, app.sidebar.winfo_width(), body_h), raw)
        state["controls"] = (cuts, body_h, raw)
        root.destroy()

    root.after(1500, shoot)
    root.mainloop()

    print("  %-24s %dx%d" % ("screen-window.png", *state["window"][1]))
    cuts, body_h, raw = state["controls"]
    out = os.path.join(FIGURES, "screen-controls.png")
    size = compose_columns(raw, out, cuts, body_h)
    os.remove(raw)
    os.rmdir(os.path.dirname(raw))
    print("  %-24s %dx%d  (split at section header y=%d of %d)"
          % ("screen-controls.png", size[0], size[1],
             min(cuts, key=lambda c: abs(c - body_h / 2.0)), body_h))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
