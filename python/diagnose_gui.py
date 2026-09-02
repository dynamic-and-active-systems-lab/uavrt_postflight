#!/usr/bin/env python3
"""Report what the pulseplotter window actually contains and how big it is.

Run from the python/ directory with the venv active:

    python diagnose_gui.py

Builds the real app, lets Tk lay it out, then walks the widget tree printing
each widget's class, geometry and whether it is mapped (actually on screen).
A widget that exists but reports 1x1 or is unmapped is the bug; a widget that
is missing entirely means construction failed earlier than expected.
"""
import sys, traceback
import tkinter as tk


def walk(w, depth=0, out=None):
    out = out if out is not None else []
    try:
        cls = w.winfo_class()
        mapped = bool(w.winfo_ismapped())
        geo = f"{w.winfo_width()}x{w.winfo_height()}+{w.winfo_x()}+{w.winfo_y()}"
        mgr = w.winfo_manager() or "-"
        flag = "" if mapped and w.winfo_width() > 1 else "   <== NOT VISIBLE"
        out.append(f"{'  ' * depth}{cls:<18} {geo:<20} mgr={mgr:<6} mapped={mapped}{flag}")
        for child in w.winfo_children():
            walk(child, depth + 1, out)
    except Exception as e:
        out.append(f"{'  ' * depth}<error reading widget: {e}>")
    return out


def main():
    try:
        import pulseplotter
    except Exception:
        print("IMPORT FAILED:"); traceback.print_exc(); return 1

    root = tk.Tk()
    root.title("pulseplotter-diagnostic")
    root.geometry("1150x720")

    try:
        app = pulseplotter.PulsePlotter(root)
    except Exception:
        print("CONSTRUCTION FAILED:"); traceback.print_exc(); return 1

    root.update_idletasks()
    root.update()

    print(f"root: {root.winfo_width()}x{root.winfo_height()}")
    print(f"tk version: {root.tk.call('info', 'patchlevel')}")
    try:
        import matplotlib
        print(f"matplotlib: {matplotlib.__version__}  backend: {matplotlib.get_backend()}")
    except Exception:
        pass
    print()
    print("widget tree (class, geometry, manager, mapped):")
    for line in walk(root):
        print("  " + line)

    print()
    for name in ("figure", "ax", "canvas"):
        print(f"  app.{name}: {getattr(app, name, None)!r}"[:110])

    root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
