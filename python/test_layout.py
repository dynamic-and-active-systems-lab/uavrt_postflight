"""Layout audit: nothing clipped, nothing overlapping, at any window size.

Tk's pack and grid managers do not complain when a widget will not fit - they
just hand it less room than it asked for, or none at all, and the result is
text cut in half or one control drawn over another. This builds the real window
at a range of sizes and checks the geometry Tk actually produced:

    clipping   every widget got at least the size it requested
    spill      no widget extends past the edge of its parent
    overlap    no two widgets sharing a parent occupy the same pixels
    visible    every widget is mapped and has a real size

Run with the venv active:

    python test_layout.py
"""

import sys
import tkinter as tk

# Sizes to audit: the enforced minimum, a couple of ordinary working sizes,
# a tall-and-narrow shape, and one deliberately below the minimum to confirm
# the control column scrolls rather than losing its bottom rows.
SIZES = [
    ("minimum", 900, 560),
    ("default", 1150, 760),
    ("wide", 1600, 900),
    ("narrow", 920, 1000),
    ("below minimum", 820, 470),
]

# The figure canvas asks for figsize*dpi and is meant to give that up first;
# separators are 1px by design; the toolbar's spacer frames are 1px too.
EXEMPT_CLASSES = {"TSeparator", "TSizegrip"}

_failures = []


def check(label, ok, detail=""):
    print("  %-52s %s%s" % (label, "PASS" if ok else "FAIL",
                            ("  " + detail) if detail else ""))
    if not ok:
        _failures.append(label)


def describe(widget):
    return "%s(%s)" % (widget.winfo_class(), str(widget).rsplit(".", 1)[-1])


def collect(widget, exempt, out=None, inside_canvas=False):
    """Every managed widget, with its allocated and requested geometry."""
    out = [] if out is None else out
    manager = widget.winfo_manager()
    if manager in ("grid", "pack") and widget not in exempt:
        out.append({
            "w": widget,
            "class": widget.winfo_class(),
            "x": widget.winfo_x(), "y": widget.winfo_y(),
            "width": widget.winfo_width(), "height": widget.winfo_height(),
            "req_w": widget.winfo_reqwidth(),
            "req_h": widget.winfo_reqheight(),
            "mapped": bool(widget.winfo_ismapped()),
            "parent": widget.nametowidget(widget.winfo_parent()),
            "scrolled": inside_canvas,
        })
    for child in widget.winfo_children():
        collect(child, exempt, out,
                inside_canvas or child.winfo_manager() == "canvas")
    return out


def overlaps(a, b):
    return not (a["x"] + a["width"] <= b["x"]
                or b["x"] + b["width"] <= a["x"]
                or a["y"] + a["height"] <= b["y"]
                or b["y"] + b["height"] <= a["y"])


def audit(app, root, label):
    # The figure canvas asks for figsize*dpi and is the one widget meant to
    # give up space, so neither it nor the containers whose requested size it
    # drives can be held to their request. matplotlib builds its toolbar frame
    # with width=figure.bbox.width, so that request is a copy of the figure's
    # rather than a measure of the toolbar's own contents - the toolbar's
    # buttons are checked individually like everything else.
    exempt = {app.toolbar}
    node = app.canvas.get_tk_widget()
    while node is not None:
        exempt.add(node)
        node = None if node is root else node.nametowidget(node.winfo_parent())
    exempt.add(root)
    widgets = collect(root, exempt)

    # A widget that deliberately asks for a hairline - ttk separators, the
    # spacer frames matplotlib puts between toolbar button groups - is not a
    # layout failure; one that asked for real space and got a hairline is.
    invisible = [describe(e["w"]) for e in widgets
                 if e["class"] not in EXEMPT_CLASSES
                 and e["req_w"] > 2 and e["req_h"] > 2
                 and (not e["mapped"] or e["width"] <= 1 or e["height"] <= 1)]
    check("%s: every widget visible" % label, not invisible,
          ", ".join(invisible[:4]))

    # A widget handed less than it asked for is a widget with cut-off text.
    # Anything inside the scrolling column is exempt vertically: the column is
    # allowed to be taller than the viewport, that is what the scrollbar is for.
    clipped = []
    for e in widgets:
        if e["class"] in EXEMPT_CLASSES:
            continue
        if e["width"] + 1 < e["req_w"]:
            clipped.append("%s w %d<%d" % (describe(e["w"]), e["width"],
                                           e["req_w"]))
        elif e["height"] + 1 < e["req_h"]:
            clipped.append("%s h %d<%d" % (describe(e["w"]), e["height"],
                                           e["req_h"]))
    check("%s: nothing clipped below its requested size" % label, not clipped,
          "; ".join(clipped[:4]))

    # Spilling past the parent is how the toolbar came to sit on the sliders.
    spilling = []
    for e in widgets:
        if e["scrolled"]:
            continue
        pw = e["parent"].winfo_width()
        ph = e["parent"].winfo_height()
        if (e["x"] < 0 or e["y"] < 0
                or e["x"] + e["width"] > pw + 1
                or e["y"] + e["height"] > ph + 1):
            spilling.append("%s %dx%d+%d+%d in %dx%d"
                            % (describe(e["w"]), e["width"], e["height"],
                               e["x"], e["y"], pw, ph))
    check("%s: nothing spills outside its parent" % label, not spilling,
          "; ".join(spilling[:3]))

    by_parent = {}
    for e in widgets:
        by_parent.setdefault(str(e["parent"]), []).append(e)
    collisions = []
    for siblings in by_parent.values():
        for i, a in enumerate(siblings):
            for b in siblings[i + 1:]:
                if overlaps(a, b):
                    collisions.append("%s over %s" % (describe(a["w"]),
                                                      describe(b["w"])))
    check("%s: no two siblings overlap" % label, not collisions,
          "; ".join(collisions[:3]))


def main():
    print("pulseplotter layout audit")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print("  no display available: %s" % exc)
        return 0

    import pulseplotter

    root.minsize(*pulseplotter.MIN_WINDOW)
    app = pulseplotter.PulsePlotter(root)

    for label, width, height in SIZES:
        # minsize would refuse the deliberately-too-small case, so lift it.
        root.minsize(1, 1)
        root.geometry("%dx%d" % (width, height))
        root.update_idletasks()
        root.update()
        print("\n%s  (%dx%d)" % (label, root.winfo_width(),
                                 root.winfo_height()))
        audit(app, root, label)

    scrolled = app.sidebar.scrollbar.winfo_ismapped()
    print()
    check("control column scrolls when the window is too short", scrolled)

    root.minsize(1, 1)
    root.geometry("1150x760")
    root.update_idletasks()
    root.update()
    check("scrollbar goes away again when it is not needed",
          not app.sidebar.scrollbar.winfo_ismapped())

    root.destroy()
    print("\n%s" % ("ALL PASS" if not _failures
                    else "FAILURES: " + ", ".join(_failures)))
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
