# SPDX-License-Identifier: AGPL-3.0-or-later
"""What on the desktop can be clicked or typed into, read from its
accessibility tree. `G2` of screen grounding (`D-2026-11-01-04`).

The owner (2026-11-01, on the game plan): *"Those top 3 you selected should be
first up"* — the first being screen grounding: the agent is shown the screen
with every control numbered on it, and clicks a number instead of guessing a
pixel. A small local model (the owner drives a 12B) reads a number off a
picture far more reliably than it reads coordinates.

**Where the numbers come from.** XFCE's apps are GTK, and GTK tells AT-SPI —
the desktop's accessibility bus, what a screen reader listens to — every
button, menu, tab, field and list row a window shows, with its role, its name
and where it is on the screen. Firefox does the same for the page it shows
once accessibility is asked for (`GNOME_ACCESSIBILITY=1`, which the desktop's
session is started with, `workstation/ubuntu.py`). So most of the screen is
described exactly, by the apps themselves, with no picture read at all.

**How it runs.** As the account, on its display, with the system's own
Python (the only one with PyGObject), fed this file on stdin by
`XDisplay.marks` — so it needs nothing installed where the daemon's code is
and imports nothing from it: the standard library and `gi` only. It prints one
JSON object and exits:

    {"marks": [{"role", "name", "box": [x, y, w, h], "app", "window"}],
     "windows": [{"app", "name", "box", "active", "marks"}]}

or {"why": "<a sentence>"} when the tree cannot be read. `windows` lets the
caller see which windows the tree describes well and which it does not (an
app that tells AT-SPI nothing — a game, a canvas), so it can look at those
with its picture-reading fallback (`src/screen_marks.py`, `G3`) instead.

**What is left out.** Anything not showing; anything off the screen or too
small to hit; and a control inside a window that another window covers — the
active window is on top, the panels above all (they are docks), and a
control under either is not a thing a click reaches.
"""

import json
import sys
import time

SCREEN_W = 1280
SCREEN_H = 800
MAX_MARKS = 80
MAX_NODES = 6000
MAX_DEPTH = 40
BUDGET_S = 2.5
MIN_SIDE = 4
NAME_MAX = 80

# The roles a person clicks or types into. A label, a panel, a filler, a
# scroll pane is not one; a list row and a tree row are (a file in Thunar, a
# message in a list), and so is a link on a page Firefox describes.
ROLES = frozenset({
    "push button", "toggle button", "check box", "radio button", "combo box", "menu",
    "menu item", "check menu item", "radio menu item", "tearoff menu item", "page tab",
    "text", "entry", "password text", "spin button", "slider", "link", "list item",
    "table cell", "tree item", "icon", "tool bar button", "push button menu", "toggle button menu",
    "editbar", "terminal", "autocomplete", "calendar", "table row", "split button",
    "switch", "search box", "heading",
})
# A cell or row that holds others is described by what it holds.
_CONTAINER_ROLES = frozenset({"table cell", "table row"})
# Apps that are the desktop itself: always on top (panels) or always beneath
# (the desktop's icons), never covered by another window's box in our sense.
DOCK_APPS = frozenset({"xfce4-panel", "wrapper-2.0", "wrapper-1.0", "xfce4-notifyd"})
BACKDROP_APPS = frozenset({"xfdesktop"})


def _box(acc, Atspi):
    try:
        e = acc.get_extents(Atspi.CoordType.SCREEN)
    except Exception:  # noqa: BLE001 — a node that will not say where it is is not marked
        return None
    x, y, w, h = int(e.x), int(e.y), int(e.width), int(e.height)
    if w < MIN_SIDE or h < MIN_SIDE:
        return None
    # Clipped to the screen; a box wholly off it is none.
    x2, y2 = min(x + w, SCREEN_W), min(y + h, SCREEN_H)
    x, y = max(x, 0), max(y, 0)
    if x2 - x < MIN_SIDE or y2 - y < MIN_SIDE:
        return None
    return [x, y, x2 - x, y2 - y]


def _inside(point, box):
    px, py = point
    x, y, w, h = box
    return x <= px < x + w and y <= py < y + h


def _clean(text):
    return " ".join(str(text or "").split())[:NAME_MAX]


def read(Atspi, *, budget_s=BUDGET_S):
    """The marks and windows, as the module docstring says."""
    started = time.monotonic()
    try:
        Atspi.set_timeout(800, -1)
    except Exception:  # noqa: BLE001 — an older libatspi without it keeps its own
        pass
    desktop = Atspi.get_desktop(0)
    windows = []
    marks = []
    seen = [0]

    def walk(acc, depth, app, win):
        if depth > MAX_DEPTH or seen[0] >= MAX_NODES or time.monotonic() - started > budget_s:
            return
        seen[0] += 1
        try:
            states = acc.get_state_set()
            if not states.contains(Atspi.StateType.SHOWING):
                return
            role = acc.get_role_name() or ""
            count = acc.get_child_count()
        except Exception:  # noqa: BLE001 — a node that went away mid-walk
            return
        if role in ROLES and not (role in _CONTAINER_ROLES and count > 0):
            box = _box(acc, Atspi)
            if box is not None and (box[2] * box[3]) < SCREEN_W * SCREEN_H * 0.6:
                try:
                    name = _clean(acc.get_name()) or _clean(acc.get_description())
                except Exception:  # noqa: BLE001
                    name = ""
                marks.append({"role": role, "name": name, "box": box, "app": app, "window": win,
                              "editable": states.contains(Atspi.StateType.EDITABLE)})
                if role in ("terminal", "text") and box[2] * box[3] > 40000:
                    return  # a big text area's children are its lines, not controls
        for i in range(min(count, 400)):
            try:
                child = acc.get_child_at_index(i)
            except Exception:  # noqa: BLE001
                child = None
            if child is not None:
                walk(child, depth + 1, app, win)

    for i in range(desktop.get_child_count()):
        try:
            app_acc = desktop.get_child_at_index(i)
            app = _clean(app_acc.get_name()) if app_acc is not None else ""
            n = app_acc.get_child_count() if app_acc is not None else 0
        except Exception:  # noqa: BLE001 — an app that quit as it was asked
            continue
        for j in range(min(n, 50)):
            try:
                top = app_acc.get_child_at_index(j)
                states = top.get_state_set()
                if not states.contains(Atspi.StateType.SHOWING):
                    continue
                box = _box(top, Atspi)
                if box is None:
                    continue
                name = _clean(top.get_name())
                role = top.get_role_name() or ""
            except Exception:  # noqa: BLE001
                continue
            w = {"app": app, "name": name, "box": box, "role": role,
                 "active": states.contains(Atspi.StateType.ACTIVE), "id": len(windows)}
            windows.append(w)
            before = len(marks)
            walk(top, 0, app, w["id"])
            w["marks"] = len(marks) - before

    # Covered controls: a window's controls under the active window, or
    # under a popup (a menu that is open), are not reachable.
    on_top = [w for w in windows if w["role"] in ("window", "menu", "popup menu", "tool tip")
              and w["app"] not in DOCK_APPS]
    active = [w for w in windows if w["active"] and w["app"] not in DOCK_APPS | BACKDROP_APPS]
    kept = []
    for m in marks:
        win = windows[m["window"]]
        if win["app"] in DOCK_APPS:
            kept.append(m)
            continue
        cx, cy = m["box"][0] + m["box"][2] // 2, m["box"][1] + m["box"][3] // 2
        above = [w for w in on_top + active if w is not win and w["id"] != m["window"]]
        if win in on_top:
            above = []
        elif win in active:
            above = [w for w in on_top if w is not win]
        if any(_inside((cx, cy), w["box"]) for w in above):
            continue
        # A dock (a panel) is above every window.
        if any(_inside((cx, cy), w["box"]) for w in windows
               if w["app"] in DOCK_APPS and w["role"] != "window"):
            continue
        kept.append(m)

    # A row of cells — Thunar's side pane: an expander, an icon, a name — is
    # one thing to click: the named cell, widened over its row's unnamed ones.
    rows = {}
    for m in kept:
        if m["role"] == "table cell":
            rows.setdefault((m["window"], m["box"][1], m["box"][3]), []).append(m)
    for cells in rows.values():
        named = [c for c in cells if c["name"]]
        if not named or len(cells) == 1:
            continue
        for c in cells:
            if not c["name"]:
                kept.remove(c)
        if len(named) == 1:
            n = named[0]
            x1 = min(c["box"][0] for c in cells)
            x2 = max(c["box"][0] + c["box"][2] for c in cells)
            n["box"] = [x1, n["box"][1], x2 - x1, n["box"][3]]

    # One mark per place: a control nested in another of the same box (a
    # button inside its filler) is one thing to click.
    out = []
    seen_boxes = set()
    for m in sorted(kept, key=lambda m: (m["box"][1] // 8, m["box"][0])):
        key = tuple(m["box"])
        if key in seen_boxes:
            continue
        seen_boxes.add(key)
        out.append(m)
        if len(out) >= MAX_MARKS:
            break
    for w in windows:
        w["marks"] = sum(1 for m in out if m["window"] == w["id"])
    return {"marks": out, "windows": windows,
            "took_ms": int((time.monotonic() - started) * 1000)}


def main():
    try:
        # By name, not by `import`: the package needs nothing beyond the
        # standard library (its daemon runs on any Python), and this reader
        # alone runs under the system Python that has PyGObject — without it,
        # it says so below and the caller reads the picture instead.
        import importlib
        gi = importlib.import_module("gi")
        gi.require_version("Atspi", "2.0")
        Atspi = importlib.import_module("gi.repository.Atspi")
    except Exception as e:  # noqa: BLE001 — said, never raised: the caller falls back
        print(json.dumps({"why": "This desktop cannot read its accessibility tree "
                                 f"(PyGObject with AT-SPI is not installed: {type(e).__name__})."}))
        return 0
    try:
        got = read(Atspi)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"why": f"The accessibility tree could not be read ({type(e).__name__})."}))
        return 0
    if not got["windows"]:
        got = {"why": "No app on this desktop is telling the accessibility bus what it shows.",
               "marks": [], "windows": []}
    print(json.dumps(got))
    return 0


if __name__ == "__main__":
    sys.exit(main())
