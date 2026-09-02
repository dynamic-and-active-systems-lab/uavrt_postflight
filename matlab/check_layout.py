#!/usr/bin/env python3
"""Check that pulseplotter2.m's grid layout is self-consistent. No MATLAB needed.

A Python script in a MATLAB directory looks odd, but MATLAB cannot be run here
(expired licence - see ../CLAUDE.md) and this is the project's stated fallback:
transliterate the logic and check it outside MATLAB. It is the only automated
layout check the MATLAB app has. It is *not* a substitute for opening the app:
it cannot tell you whether a label is too small for its text, only whether the
grid declarations contradict each other.

It reads createComponents, simulates the row counter that numbers the control
column, and checks:

  * every child is placed in a row and column that its grid actually declares
  * no two children of the same grid land in the same cell
  * every row of the scrolling control column has a height, and the number of
    rows used matches the number declared

Run it after any change to createComponents:

    python3 check_layout.py pulseplotter2.m
"""

import re, sys

src = open(sys.argv[1]).read()
body = src[src.index("function createComponents(app)"):src.index("app.UIFigure.Visible = 'on';")]
lines = [l.strip() for l in body.split("\n")]

grids = {}          # name -> {"rows": n, "cols": n, "cells": {}}
parent_of = {}      # component name -> grid name
row = 0
heights = []
placements = []     # (grid, name, rows, cols, source line)
pending = {}        # component -> partial layout

def note(grid, name, rows, cols, ln):
    placements.append((grid, name, rows, cols, ln))

def cellspan(expr):
    expr = expr.strip().rstrip(";").strip()
    if expr == "row":
        return [row]
    if expr.startswith("["):
        a, b = expr.strip("[]").split()
        return list(range(int(a), int(b) + 1))
    if expr.isdigit():
        return [int(expr)]
    raise ValueError(expr)

for ln, line in enumerate(lines, 1):
    m = re.match(r"(\S+) = uigridlayout\(([^)]+)\);", line)
    if m:
        name, parent = m.group(1), m.group(2)
        grids[name] = {"rows": 1, "cols": 1, "cells": {}}
        parent_of[name] = parent
        continue
    m = re.match(r"(\S+)\.ColumnWidth = (.+);", line)
    if m and m.group(1) in grids:
        v = m.group(2)
        if "repmat" in v:
            grids[m.group(1)]["cols"] = int(re.search(r",\s*(\d+)\)", v).group(1))
        else:
            grids[m.group(1)]["cols"] = v.count(",") + 1
        continue
    m = re.match(r"(\S+)\.RowHeight = (.+);", line)
    if m and m.group(1) in grids:
        v = m.group(2)
        if "repmat" in v:
            grids[m.group(1)]["rows"] = int(re.search(r"1,\s*(\d+)\)", v).group(1))
        elif v.strip() == "heights":
            grids[m.group(1)]["rows"] = len(heights)
            grids[m.group(1)]["final_heights"] = list(heights)
        else:
            grids[m.group(1)]["rows"] = v.count(",") + 1
        continue

    if line == "row = row + 1;":
        row += 1
        continue
    m = re.match(r"heights\{row\} = (\d+);", line)
    if m:
        while len(heights) < row:
            heights.append(None)
        heights[row - 1] = int(m.group(1))
        continue
    if "app.addSection(" in line:
        gname = re.search(r"addSection\((\S+?),", line).group(1)
        for h in (22, 1):
            row += 1
            heights.append(h)
            note(gname, "section-row-%d" % row, [row], [1, 2], ln)
        continue

    m = re.match(r"(\S+) = ui\w+\(([^,)]+)[,)]", line)
    if m and m.group(2) in grids:
        parent_of[m.group(1)] = m.group(2)
        continue
    m = re.match(r"(\S+) = app\.addLabel\((\S+?), row, ", line)
    if m:
        note(m.group(2), m.group(1), [row], [1], ln)
        continue
    m = re.match(r"app\.addReadout\((\S+?), row, ", line)
    if m:
        note(m.group(1), "readout-label-%d" % row, [row], [1], ln)
        note(m.group(1), "readout-field-%d" % row, [row], [2], ln)
        continue
    m = re.match(r"(\S+)\.Layout\.Row = (.+);", line)
    if m:
        pending.setdefault(m.group(1), {})["rows"] = cellspan(m.group(2))
        continue
    m = re.match(r"(\S+)\.Layout\.Column = (.+);", line)
    if m:
        p = pending.setdefault(m.group(1), {})
        p["cols"] = cellspan(m.group(2))
        if "rows" in p:
            note(parent_of.get(m.group(1), "?"), m.group(1), p["rows"], p["cols"], ln)
            pending.pop(m.group(1))
        continue

problems = []
for grid, name, rows, cols, ln in placements:
    if grid not in grids:
        problems.append("%s: unknown grid %s" % (name, grid))
        continue
    g = grids[grid]
    for r in rows:
        for c in cols:
            if r < 1 or r > g["rows"] or c < 1 or c > g["cols"]:
                problems.append("%s at %s(%d,%d) outside %dx%d"
                                % (name, grid, r, c, g["rows"], g["cols"]))
            elif (r, c) in g["cells"]:
                problems.append("%s collides with %s in %s cell (%d,%d)"
                                % (name, g["cells"][(r, c)], grid, r, c))
            else:
                g["cells"][(r, c)] = name

print("grids declared:")
for name, g in grids.items():
    used = len({r for r, _ in g["cells"]})
    print("  %-16s %2d rows x %d cols, %2d rows used, %2d children"
          % (name, g["rows"], g["cols"], used, len(g["cells"])))

cg = grids["app.ControlGrid"]
fh = cg.get("final_heights", [])
spacing = int(re.search(r"ControlGrid\.RowSpacing = (\d+);", src).group(1))
padding = sum(int(v) for v in re.search(
    r"ControlGrid\.Padding = \[(\d+) (\d+) (\d+) (\d+)\]",
    src).group(2, 4))
print("\ncontrol column: %d rows, %d px of content"
      % (len(fh), sum(fh) + (len(fh) - 1) * spacing + padding))
print("every row has a height:",
      "yes" if all(h is not None for h in cg.get("final_heights", [])) else "NO")
print("rows used == rows declared:",
      "yes" if max(r for r, _ in cg["cells"]) == cg["rows"] else
      "NO (used %d, declared %d)" % (max(r for r, _ in cg["cells"]), cg["rows"]))

print("\nproblems:", "none" if not problems else "")
for p in problems:
    print("  " + p)
sys.exit(1 if problems else 0)
