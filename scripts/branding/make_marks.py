#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pantheon's mark, its wordmark, and every icon file made from them.

`P0-13`, `B71`, `D-2026-10-02-03` §2. Until this existed every picture of
Pantheon was upstream's: a red sailing boat in the favicon, on the login card,
on the welcome screen, in the tray and in the macOS app icon, and a screenshot
of the old product as the macOS icon's source. The decision was *"an agent
makes a simple mark"* — so this is a simple mark, and the owner may replace it.

**One geometry, every output.** The temple below is described once, in design
units, and both the SVGs and the bitmaps are made from that description: the
SVG paths are written from it and the PNG / ICO / ICNS files are rasterised from
it by Pillow. Nothing is traced, nothing is drawn by hand twice, and no font is
read — the wordmark's capitals are built here from rectangles, lines and arcs,
so there is no typeface licence to carry and nothing to fetch (`Law 16`).

**What it draws.** The Pantheon in Rome seen from the front: a portico (a
pediment, an entablature, four columns, a step) with the rotunda's dome
cresting behind the pediment. The dome is what makes it *this* building rather
than the generic "bank" pictogram, and it survives at 16 px as a domed temple.
The wordmark is PANTHEON in spaced, monoline geometric capitals — the way a
name is cut into an architrave.

**The eight route glyphs.** `static/index.html` and `static/js/theme.js` draw a
different favicon on `/calendar`, `/notes`, `/cookbook`, `/email`, `/memory`,
`/gallery`, `/tasks` and `/library`, so a bookmark says which tool it opens.
Those shapes were upstream's too (`P0-13`: *"do not reuse … the per-route
favicon shapes"*). They are redrawn here in the mark's language — solid shapes
with the detail cut out of them, not 2.5-unit outlines — and written to
`docs/brand/routes/`, which is what the two inline copies are tested against.

Usage (from the repository root; needs Pillow, which the app already pulls in):

    python3 scripts/branding/make_marks.py           # write every file
    python3 scripts/branding/make_marks.py --check   # compare, write nothing

`--check` regenerates in memory and compares with the files in the tree — the
SVGs byte for byte, the bitmaps decoded pixel for pixel (so a different zlib
cannot fail it) — and exits 1 naming any file that differs.
"""
from __future__ import annotations

import argparse
import io
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "docs" / "brand"

# ── Colours ──────────────────────────────────────────────────────────────────
# Two inks, for the two kinds of background, and a tile for the app icon. They
# are the default palette's own colours (`static/js/theme.js` THEMES.dark: bg
# #282c34, fg #9cdef2), so the icon on a dock looks like the product it opens.
# Inside the app the mark is never drawn in these: it takes `currentColor`, which
# the welcome screen and login card set to each palette's brand colour.
INK_ON_LIGHT = "#1f232b"   # deep slate, for light backgrounds
INK_ON_DARK = "#ece7dd"    # warm marble, for dark backgrounds
TILE_BG = "#282c34"        # the default palette's background
TILE_FG = "#9cdef2"        # the default palette's foreground

# Light and dark backgrounds the contact sheet proves the mark on.
SHEET_LIGHT = "#faf6f0"
SHEET_DARK = "#1e2128"


# ── Geometry ─────────────────────────────────────────────────────────────────


def _num(v: float) -> str:
    """A coordinate as the shortest exact-enough text: 2 decimals, no trailing zeros."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


@dataclass
class Contour:
    """One closed outline, kept twice: as SVG commands (exact arcs) and as a
    polyline (arcs flattened finely) for the rasteriser. Both are built by the
    same calls, so they cannot describe different shapes."""

    cmds: list = field(default_factory=list)
    pts: list = field(default_factory=list)

    def move(self, x, y):
        self.cmds.append(("M", x, y))
        self.pts.append((x, y))
        return self

    def line(self, x, y):
        self.cmds.append(("L", x, y))
        self.pts.append((x, y))
        return self

    def arc(self, cx, cy, r, a0, a1, ry=None):
        """Arc about (cx, cy) from angle a0 to a1, degrees, screen axes (y down,
        so increasing angle runs clockwise). Radius r, or r × ry for an ellipse.
        Starts where the pen is."""
        ry = r if ry is None else ry
        steps = max(8, int(abs(a1 - a0) / 2))
        for i in range(1, steps + 1):
            a = math.radians(a0 + (a1 - a0) * i / steps)
            self.pts.append((cx + r * math.cos(a), cy + ry * math.sin(a)))
        # SVG cannot draw a 360° arc in one command; split anything over 180°.
        span = a1 - a0
        pieces = 2 if abs(span) > 180 else 1
        for p in range(1, pieces + 1):
            a = math.radians(a0 + span * p / pieces)
            ex, ey = cx + r * math.cos(a), cy + ry * math.sin(a)
            self.cmds.append(("A", r, ry, 1 if span > 0 else 0, ex, ey))
        return self

    def close(self):
        self.cmds.append(("Z",))
        return self

    def moved(self, dx, dy, k=1.0):
        out = Contour()
        for c in self.cmds:
            if c[0] in "ML":
                out.cmds.append((c[0], c[1] * k + dx, c[2] * k + dy))
            elif c[0] == "A":
                out.cmds.append(("A", c[1] * k, c[2] * k, c[3], c[4] * k + dx, c[5] * k + dy))
            else:
                out.cmds.append(c)
        out.pts = [(x * k + dx, y * k + dy) for x, y in self.pts]
        return out

    def d(self) -> str:
        out = []
        for c in self.cmds:
            if c[0] in "ML":
                out.append(f"{c[0]}{_num(c[1])} {_num(c[2])}")
            elif c[0] == "A":
                out.append(f"A{_num(c[1])} {_num(c[2])} 0 0 {c[3]} {_num(c[4])} {_num(c[5])}")
            else:
                out.append("Z")
        return "".join(out)


def poly(*points) -> Contour:
    c = Contour().move(*points[0])
    for p in points[1:]:
        c.line(*p)
    return c.close()


def box(x0, y0, x1, y1) -> Contour:
    return poly((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def rounded(x0, y0, x1, y1, r) -> Contour:
    return (Contour().move(x0 + r, y0).line(x1 - r, y0).arc(x1 - r, y0 + r, r, -90, 0)
            .line(x1, y1 - r).arc(x1 - r, y1 - r, r, 0, 90).line(x0 + r, y1)
            .arc(x0 + r, y1 - r, r, 90, 180).line(x0, y0 + r).arc(x0 + r, y0 + r, r, 180, 270)
            .close())


def circle(cx, cy, r) -> Contour:
    return Contour().move(cx + r, cy).arc(cx, cy, r, 0, 360).close()


@dataclass
class Shape:
    """Contours filled with the even-odd rule: a contour inside another is a hole."""

    contours: list
    width: float
    height: float

    def d(self) -> str:
        return "".join(c.d() for c in self.contours)

    def placed(self, dx, dy, k=1.0) -> list:
        return [c.moved(dx, dy, k) for c in self.contours]


# ── The mark: portico and dome, on a 32-unit square ──────────────────────────
# Horizontal edges sit on even units wherever the drawing allows, so at 16 px
# (two units to a pixel) the entablature, columns and step land on whole
# pixels. The dome and the pediment's slopes cannot, and are anti-aliased.

DOME_C = (16.0, 14.0)
DOME_R = 11.0
PED_APEX = (16.0, 10.0)
PED_BASE_Y = 16.0
PED_HALF = 14.0
GAP = 2.0          # between the dome and the pediment's raking edges
DOME_CUT_Y = 12.0  # the dome's two horns end here, flat, not in a hairline


def _mark() -> Shape:
    cx, cy = DOME_C
    ax, ay = PED_APEX
    rise = PED_BASE_Y - ay
    slant = math.hypot(PED_HALF, rise)
    # The raking edges moved outward by GAP: the apex rises by GAP·slant/half.
    oay = ay - GAP * slant / PED_HALF

    def edge_x(y, side):  # x of the offset raking edge at height y
        return ax + side * (y - oay) * PED_HALF / rise

    half_chord = math.sqrt(DOME_R ** 2 - (cy - DOME_CUT_Y) ** 2)
    a_left = math.degrees(math.atan2(DOME_CUT_Y - cy, -half_chord))   # ~ -169°
    a_right = math.degrees(math.atan2(DOME_CUT_Y - cy, half_chord))   # ~ -11°
    dome = (Contour().move(cx - half_chord, DOME_CUT_Y)
            .arc(cx, cy, DOME_R, a_left + 360 if a_left < -180 else a_left, a_right)
            .line(edge_x(DOME_CUT_Y, +1), DOME_CUT_Y)
            .line(ax, oay)
            .line(edge_x(DOME_CUT_Y, -1), DOME_CUT_Y)
            .close())
    pediment = poly((ax, ay), (ax + PED_HALF, PED_BASE_Y), (ax - PED_HALF, PED_BASE_Y))
    entablature = box(4, 18, 28, 20)
    # Four columns between x 5 and 27, 3 units wide: three gaps of 3⅓.
    cols = []
    n, w, x0, x1 = 4, 3.0, 5.0, 27.0
    gap = (x1 - x0 - n * w) / (n - 1)
    for i in range(n):
        left = x0 + i * (w + gap)
        cols.append(box(left, 20, left + w, 26))
    step = box(2, 26, 30, 28)    # as thick as the entablature; whole pixels at 16
    return Shape([dome, pediment, entablature, *cols, step], 32, 32)


MARK = _mark()


# ── The wordmark: PANTHEON in monoline capitals, cap height 100 ──────────────

CAP = 100.0
STEM = 16.0


def _glyph_P():
    w, r = 64.0, 29.0                 # bowl: 2r tall, its arc's centre at x = w - r
    ri = r - STEM
    outer = (Contour().move(0, 0).line(w - r, 0).arc(w - r, r, r, -90, 90)
             .line(STEM, 2 * r).line(STEM, CAP).line(0, CAP).close())
    inner = (Contour().move(STEM, STEM).line(w - r, STEM).arc(w - r, r, ri, -90, 90)
             .line(STEM, 2 * r - STEM).close())
    return [outer, inner], w


def _glyph_A():
    w, flat = 82.0, 10.0              # flat: the apex is cut square, not a needle
    ax0, ax1 = w / 2 - flat / 2, w / 2 + flat / 2
    run = ax0                          # horizontal run of each outer edge
    t = STEM * math.hypot(run, CAP) / CAP   # a leg's horizontal thickness
    bar_top, bar_bot = 62.0, 62.0 + STEM * 0.9

    def inner_x(y, side):  # the inner edge of a leg at height y
        if side < 0:
            return t + run * (CAP - y) / CAP
        return w - t - run * (CAP - y) / CAP

    y_meet = CAP - (w / 2 - t) * CAP / run   # where the two inner edges meet
    outer = poly((0, CAP), (ax0, 0), (ax1, 0), (w, CAP), (w - t, CAP),
                 (inner_x(bar_bot, 1), bar_bot), (inner_x(bar_bot, -1), bar_bot), (t, CAP))
    counter = poly((inner_x(bar_top, -1), bar_top), (w / 2, y_meet), (inner_x(bar_top, 1), bar_top))
    return [outer, counter], w


def _glyph_N():
    w = 76.0
    dx = STEM * math.hypot(w, CAP) / CAP * 0.92   # the diagonal, as a horizontal thickness
    yc = CAP * (w - STEM - dx) / (w - dx)          # upper edge meets the right stem
    ye = CAP * STEM / (w - dx)                     # lower edge meets the left stem
    outline = poly((0, 0), (dx, 0), (w - STEM, yc), (w - STEM, 0), (w, 0), (w, CAP),
                   (w - dx, CAP), (STEM, ye), (STEM, CAP), (0, CAP))
    return [outline], w


def _glyph_T():
    w = 72.0
    c = w / 2
    return [poly((0, 0), (w, 0), (w, STEM), (c + STEM / 2, STEM), (c + STEM / 2, CAP),
                 (c - STEM / 2, CAP), (c - STEM / 2, STEM), (0, STEM))], w


def _glyph_H():
    w = 74.0
    b0 = 47.0 - STEM / 2
    b1 = b0 + STEM
    return [poly((0, 0), (STEM, 0), (STEM, b0), (w - STEM, b0), (w - STEM, 0), (w, 0),
                 (w, CAP), (w - STEM, CAP), (w - STEM, b1), (STEM, b1), (STEM, CAP),
                 (0, CAP))], w


def _glyph_E():
    w, wm = 58.0, 52.0
    m0 = 47.0 - STEM / 2
    m1 = m0 + STEM
    return [poly((0, 0), (w, 0), (w, STEM), (STEM, STEM), (STEM, m0), (wm, m0), (wm, m1),
                 (STEM, m1), (STEM, CAP - STEM), (w, CAP - STEM), (w, CAP), (0, CAP))], w


def _glyph_O():
    # A round letter overshoots the cap height and baseline a little or it looks
    # smaller than its square neighbours; its stroke is a touch heavier for the
    # same reason.
    over = 2.0
    r = CAP / 2 + over
    return [circle(r, CAP / 2, r), circle(r, CAP / 2, r - STEM * 1.06)], 2 * r


GLYPHS = {"P": _glyph_P, "A": _glyph_A, "N": _glyph_N, "T": _glyph_T,
          "H": _glyph_H, "E": _glyph_E, "O": _glyph_O}

# Space between letters: a base measure, adjusted per pair by eye for the empty
# triangle beside an A's slope, a T's arms, and an O's curve.
TRACK = 30.0
PAIRS = {"PA": -12.0, "AN": -10.0, "NT": -8.0, "TH": -8.0, "HE": 0.0, "EO": -4.0, "ON": -4.0}


def _wordmark(text="PANTHEON") -> Shape:
    contours, x = [], 0.0
    for i, ch in enumerate(text):
        if i:
            x += TRACK + PAIRS.get(text[i - 1] + ch, 0.0)
        parts, w = GLYPHS[ch]()
        contours += [c.moved(x, 0) for c in parts]
        x += w
    return Shape(contours, x, CAP)


WORDMARK = _wordmark()


# ── The eight route glyphs (32-unit square, solid with the detail cut out) ────


def _routes() -> dict:
    r = {}
    r["/calendar"] = [
        box(9, 3, 12, 7), box(20, 3, 23, 7),       # binder rings
        box(4, 7, 28, 12),                         # header band
        box(4, 14, 28, 28), box(17, 18, 23, 24),   # page, and today cut out of it
    ]
    r["/notes"] = [
        poly((7, 4), (19, 4), (25, 10), (25, 28), (7, 28)),
        box(11, 13, 21, 15), box(11, 18, 21, 20), box(11, 23, 17, 25),
    ]
    r["/cookbook"] = [  # the Forge: an anvil
        poly((2, 9), (9, 8), (29, 8), (29, 13), (24, 13), (21, 17), (21, 21), (26, 22),
             (27, 27), (9, 27), (10, 22), (15, 21), (15, 17), (12, 13), (9, 13)),
    ]
    r["/email"] = [
        box(4, 8, 28, 25),
        poly((6, 10), (16, 17), (26, 10), (26, 12.5), (16, 19.5), (6, 12.5)),
    ]
    r["/memory"] = [_hemisphere(-1), _hemisphere(+1)]  # the Brain, seen from above
    r["/gallery"] = [
        box(4, 6, 28, 26),
        poly((7, 23), (13, 15), (17, 20), (20, 17), (25, 23)),
        circle(11.5, 11, 2.5),
    ]
    r["/tasks"] = [
        rounded(4, 4, 28, 28, 4),
        poly((8.5, 16.5), (11, 14), (14, 17), (21.5, 9.5), (24, 12), (14, 22)),
    ]
    r["/library"] = [  # three books lying in a stack, each with a label cut in
        box(4, 22, 28, 28), box(23, 24, 25, 26),
        box(7, 15, 25, 20), box(20, 17, 22, 18),
        box(5, 8, 23, 13), box(18, 10, 20, 11),
    ]
    return r


def _hemisphere(side, bumps=4) -> Contour:
    """Half a brain seen from above: a half-ellipse whose outer edge is a row of
    bulges, and a straight edge along the fissure. Written as arcs, not points,
    so the inline copies in index.html and theme.js stay short."""
    # Centred one unit left of the square's middle so the fissure (x 14–16)
    # falls on whole pixels at 16 px and at 32.
    cx, cy, rx, ry, mid = 15.0, 16.0, 12.5, 11.5, 1.0
    x_mid = cx + side * mid
    pts = [(x_mid + side * (rx - mid) * math.sin(math.pi * i / bumps),
            cy - ry * math.cos(math.pi * i / bumps)) for i in range(bumps + 1)]
    c = Contour().move(*pts[0])
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        mx, my = (ax + bx) / 2, (ay + by) / 2
        chord = math.hypot(bx - ax, by - ay)
        nx, ny = (by - ay) / chord, -(bx - ax) / chord
        if nx * (mx - x_mid) + ny * (my - cy) < 0:   # point it away from the middle
            nx, ny = -nx, -ny
        rb = chord * 0.62
        h = math.sqrt(rb * rb - (chord / 2) ** 2)
        ox, oy = mx - nx * h, my - ny * h             # centre inside: the short arc bulges out
        a0 = math.degrees(math.atan2(ay - oy, ax - ox))
        a1 = math.degrees(math.atan2(by - oy, bx - ox))
        sweep = (a1 - a0 + 180) % 360 - 180          # the short way round
        c.arc(ox, oy, rb, a0, a0 + sweep)
    return c.close()


ROUTES = _routes()


# ── Rasteriser ───────────────────────────────────────────────────────────────


def _hex(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def coverage(contours, w, h, ss=8):
    """An 8-bit coverage mask: each contour XORed in at `ss`× resolution (the
    even-odd rule), then box-filtered down, so an edge's grey is its true area."""
    from PIL import Image, ImageChops, ImageDraw

    W, H = w * ss, h * ss
    acc = Image.new("1", (W, H), 0)
    for c in contours:
        m = Image.new("1", (W, H), 0)
        ImageDraw.Draw(m).polygon([(x * ss, y * ss) for x, y in c.pts], fill=1)
        acc = ImageChops.logical_xor(acc, m)
    return acc.convert("L").resize((w, h), Image.Resampling.BOX)


def paint(mask, ink, bg=None):
    from PIL import Image

    rgb = _hex(ink)
    if bg is None:
        img = Image.new("RGBA", mask.size, rgb + (0,))
        img.putalpha(mask)
        return img
    img = Image.new("RGBA", mask.size, _hex(bg) + (255,))
    img.paste(Image.new("RGBA", mask.size, rgb + (255,)), (0, 0), mask)
    return img


def _ss_for(px):
    return 8 if px <= 256 else 4


def render_mark(px, ink, pad=0.0, bg=None):
    """The mark alone on a px-square, `pad` (a fraction of px) clear on each side."""
    k = px * (1 - 2 * pad) / 32.0
    off = px * pad
    return paint(coverage(MARK.placed(off, off, k), px, px, _ss_for(px)), ink, bg)


def _tile_layout(px, maskable):
    """(inset, corner radius, mark scale) as fractions of the side.

    Large tiles follow the desktop icon grid (a rounded square inset ~9% with
    the mark inside it). At 16–24 px that padding would leave a nine-pixel
    mark, so small tiles fill the square and the mark grows to fill the tile.
    Maskable icons are full-bleed and keep the mark inside the 80% circle."""
    if maskable:
        return 0.0, 0.0, 0.56
    if px <= 24:
        return 0.0, 0.18, 0.84
    if px <= 48:
        return 0.03, 0.2, 0.72
    return 0.09, 0.2, 0.6


def render_tile(px, maskable=False):
    """The app icon: the mark in the default palette's foreground on its
    background (`any`: rounded square, transparent corners; `maskable`: full
    bleed)."""
    from PIL import Image, ImageDraw

    inset, radius, scale = _tile_layout(px, maskable)
    ss = _ss_for(px)
    bgmask = Image.new("L", (px * ss, px * ss), 0)
    i = round(px * inset) * ss
    ImageDraw.Draw(bgmask).rounded_rectangle(
        [i, i, px * ss - i - 1, px * ss - i - 1], radius=round(px * radius * ss), fill=255)
    bgmask = bgmask.resize((px, px), Image.Resampling.BOX)
    k = px * scale / 32.0
    off = (px - 32 * k) / 2
    tile = paint(bgmask, TILE_BG)
    mark = coverage(MARK.placed(off, off, k), px, px, ss)
    tile.paste(Image.new("RGBA", (px, px), _hex(TILE_FG) + (255,)), (0, 0), mark)
    return tile


def render_shape(shape: Shape, height_px, ink, pad_px=0, bg=None):
    k = height_px / shape.height
    w = math.ceil(shape.width * k) + 2 * pad_px
    h = height_px + 2 * pad_px
    return paint(coverage(shape.placed(pad_px, pad_px, k), w, h, 4), ink, bg)


# The lockup: the word stands on the same ground as the building — its baseline
# is the step's bottom edge and its caps rise to the pediment's base.
LOCKUP_BASELINE = 29.0
LOCKUP_CAP = 13.0
LOCKUP_GAP = 9.0


def render_lockup(height_px, ink, bg=None):
    """Mark beside the wordmark, on one baseline."""
    k_mark = height_px / 32.0
    cap_px = LOCKUP_CAP * k_mark
    k_word = cap_px / CAP
    word_x = (32 + LOCKUP_GAP) * k_mark
    word_y = (LOCKUP_BASELINE - LOCKUP_CAP) * k_mark
    w = math.ceil(word_x + WORDMARK.width * k_word)
    contours = MARK.placed(0, 0, k_mark) + WORDMARK.placed(word_x, word_y, k_word)
    return paint(coverage(contours, w, height_px, 4 if height_px > 200 else 8), ink, bg)


# ── SVG writers ──────────────────────────────────────────────────────────────

SVG_HEAD = '<svg xmlns="http://www.w3.org/2000/svg"'


def svg(view_w, view_h, body, title="Pantheon", width=None, height=None):
    size = f' width="{_num(width)}" height="{_num(height)}"' if width else ""
    return (f'{SVG_HEAD} viewBox="0 0 {_num(view_w)} {_num(view_h)}"{size} role="img" '
            f'aria-label="{title}"><title>{title}</title>{body}</svg>\n')


def path(d, fill):
    return f'<path fill="{fill}" fill-rule="evenodd" d="{d}"/>'


def lockup_svg(ink):
    k = LOCKUP_CAP / CAP
    word_x = 32 + LOCKUP_GAP
    word_y = LOCKUP_BASELINE - LOCKUP_CAP
    d = MARK.d() + "".join(c.d() for c in WORDMARK.placed(word_x, word_y, k))
    return svg(word_x + WORDMARK.width * k, 32, path(d, ink))


def wordmark_svg(ink):
    return svg(WORDMARK.width, CAP, path(WORDMARK.d(), ink))


def tile_svg(maskable=False):
    """The 512-unit app icon as SVG, laid out exactly as `render_tile(512)`."""
    inset, radius, scale = _tile_layout(512, maskable)
    i = round(512 * inset)
    bg = (f'<rect x="{i}" y="{i}" width="{512 - 2 * i}" height="{512 - 2 * i}" '
          f'rx="{_num(512 * radius)}" fill="{TILE_BG}"/>')
    k = 512 * scale / 32.0
    off = (512 - 32 * k) / 2
    d = "".join(c.d() for c in MARK.placed(off, off, k))
    return svg(512, 512, bg + path(d, TILE_FG))


# ── Outputs ──────────────────────────────────────────────────────────────────


def outputs() -> dict:
    """Every file this script owns: relative path -> bytes, or a callable that
    returns a PIL image (or a list of them, for .ico / .icns)."""
    out = {}
    b = "docs/brand/"
    # Sources. `pantheon-mark.svg` is drawn in currentColor: it is the one the
    # app's inline copies are tested against, and the one to embed in a page.
    out[b + "pantheon-mark.svg"] = svg(32, 32, path(MARK.d(), "currentColor")).encode()
    out[b + "pantheon-mark-light.svg"] = svg(32, 32, path(MARK.d(), INK_ON_LIGHT)).encode()
    out[b + "pantheon-mark-dark.svg"] = svg(32, 32, path(MARK.d(), INK_ON_DARK)).encode()
    out[b + "pantheon-wordmark-light.svg"] = wordmark_svg(INK_ON_LIGHT).encode()
    out[b + "pantheon-wordmark-dark.svg"] = wordmark_svg(INK_ON_DARK).encode()
    out[b + "pantheon-lockup-light.svg"] = lockup_svg(INK_ON_LIGHT).encode()
    out[b + "pantheon-lockup-dark.svg"] = lockup_svg(INK_ON_DARK).encode()
    out[b + "pantheon-app-icon.svg"] = tile_svg().encode()
    out[b + "pantheon-app-icon-maskable.svg"] = tile_svg(maskable=True).encode()
    for route, contours in ROUTES.items():
        name = route.strip("/")
        out[f"{b}routes/{name}.svg"] = svg(
            32, 32, path("".join(c.d() for c in contours), "currentColor"),
            title=f"Pantheon — {name}").encode()

    # Renders.
    for theme, ink in (("light", INK_ON_LIGHT), ("dark", INK_ON_DARK)):
        for px in (32, 256, 1024):
            out[f"{b}png/pantheon-mark-{theme}-{px}.png"] = (lambda px=px, ink=ink: render_mark(px, ink))
        for h in (48, 192):
            out[f"{b}png/pantheon-wordmark-{theme}-{h}.png"] = (
                lambda h=h, ink=ink: render_shape(WORDMARK, h, ink, pad_px=h // 6))
        for h in (64, 256):
            out[f"{b}png/pantheon-lockup-{theme}-{h}.png"] = (lambda h=h, ink=ink: render_lockup(h, ink))
    out[b + "png/pantheon-app-icon-1024.png"] = lambda: render_tile(1024)

    # The files the product ships.
    out["static/icons/icon-192.png"] = lambda: render_tile(192)
    out["static/icons/icon-512.png"] = lambda: render_tile(512)
    out["static/icons/icon-maskable-512.png"] = lambda: render_tile(512, maskable=True)
    # Windows: the PyInstaller exe icon (`Pantheon.spec`, `build-windows-portable.ps1`)
    # and the launcher's tray icon. Every size is drawn at that size, not shrunk.
    out["static/icon.ico"] = lambda: [render_tile(s) for s in (256, 128, 64, 48, 32, 24, 16)]
    # macOS: `build-macos-app.sh` copies this into the bundle as pantheon.icns.
    out[b + "pantheon.icns"] = lambda: [render_tile(s) for s in (1024, 512, 256, 128, 64, 32)]
    out[b + "contact-sheet.png"] = contact_sheet
    return out


def _encode(rel, value) -> bytes:
    if isinstance(value, bytes):
        return value
    img = value()
    buf = io.BytesIO()
    if rel.endswith(".ico"):
        img[0].save(buf, format="ICO", sizes=[i.size for i in img], append_images=img[1:])
    elif rel.endswith(".icns"):
        img[0].save(buf, format="ICNS", append_images=img[1:])
    else:
        img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _frames(data: bytes, rel: str):
    """Decoded pixels of a bitmap file, frame by frame, for --check."""
    from PIL import Image

    im = Image.open(io.BytesIO(data))
    if rel.endswith(".ico"):
        return [(s, im.ico.getimage(s).convert("RGBA").tobytes()) for s in sorted(im.ico.sizes())]
    if rel.endswith(".icns"):
        out = []
        for s in sorted(im.info.get("sizes", [])):
            im.size = s[:2] if len(s) == 3 and s[2] == 1 else (s[0] * s[2], s[1] * s[2])
            im.best_size = s
            im.load()
            out.append((s, im.convert("RGBA").tobytes()))
            im = Image.open(io.BytesIO(data))
        return out
    return [(im.size, im.convert("RGBA").tobytes())]


def _same(rel, new: bytes, old: bytes) -> bool:
    if rel.endswith(".svg"):
        return new == old
    try:
        return _frames(new, rel) == _frames(old, rel)
    except Exception:  # an unreadable committed file is a difference, not a crash
        return False


# ── Contact sheet ────────────────────────────────────────────────────────────


def _palettes():
    """The sixteen built-in palettes as (name, bg, brand colour) — read from
    `static/js/theme.js` itself, so the sheet cannot show a palette that is not
    shipped. The brand colour is the palette's `advanced.brandColor` if it sets
    one (`gpt` does), else its red (`computeAdvancedDefaults`)."""
    import re

    src = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")
    start = src.index("export const THEMES")
    body = src[start:src.index("\n};", start)]
    out = []
    for m in re.finditer(r"^  (\w+):\s*\{(.*?)(?=^  \w+:\s*\{|\Z)", body, re.S | re.M):
        name, block = m.group(1), m.group(2)
        bg = re.search(r"\bbg:\s*'(#[0-9a-fA-F]{6})'", block)
        red = re.search(r"\bred:\s*'(#[0-9a-fA-F]{6})'", block)
        brand = re.search(r"\bbrandColor:\s*'(#[0-9a-fA-F]{6})'", block)
        if bg and red:
            out.append((name, bg.group(1), (brand or red).group(1)))
    return out


def contact_sheet():
    """Everything above at the sizes it is actually seen, on a light and a dark
    ground: the review copy, regenerated with the rest so it cannot go stale."""
    from PIL import Image, ImageDraw, ImageFont

    W, pad = 1320, 24
    font = ImageFont.load_default(size=12)
    small = ImageFont.load_default(size=10)
    sections = []

    def band(h, bg):
        im = Image.new("RGBA", (W, h), _hex(bg) + (255,))
        return im, ImageDraw.Draw(im)

    def label(d, xy, text, bg, f=font):
        light = sum(_hex(bg)) > 382
        d.text(xy, text, font=f, fill=(90, 90, 96) if light else (160, 164, 172))

    def glyph(contours, s, ink):
        return paint(coverage([c.moved(0, 0, s / 32) for c in contours], s, s), ink)

    for bg, ink, name in ((SHEET_LIGHT, INK_ON_LIGHT, "on light"), (SHEET_DARK, INK_ON_DARK, "on dark")):
        # The mark at real sizes.
        im, d = band(256 + 3 * pad, bg)
        label(d, (pad, 8), f"Mark {name}, real pixels (not scaled)", bg)
        x = pad
        for px in (16, 24, 32, 48, 64, 128, 256):
            im.alpha_composite(render_mark(px, ink), (x, 256 + pad + 6 - px))
            label(d, (x, 256 + pad + 12), f"{px}", bg, small)
            x += px + pad
        im.alpha_composite(render_lockup(96, ink), (x + pad, 40))
        im.alpha_composite(render_shape(WORDMARK, 36, ink), (x + pad, 170))
        label(d, (x + pad, 150), "wordmark", bg, small)
        label(d, (x + pad, 20), "lockup", bg, small)
        sections.append(im)

    # The app icon: tile at its shipped sizes on both grounds, and the maskable
    # one with the 80% safe circle a platform may crop it to.
    im, d = band(220 + 2 * pad, SHEET_LIGHT)
    d.rectangle([W // 2, 0, W, im.height], fill=_hex(SHEET_DARK))
    for half, bg in ((0, SHEET_LIGHT), (W // 2, SHEET_DARK)):
        label(d, (half + pad, 8), "App icon (PWA, .ico, .icns)", bg)
        x = half + pad
        for px in (16, 32, 48, 64, 128):
            im.alpha_composite(render_tile(px), (x, 200 - px))
            label(d, (x, 206), f"{px}", bg, small)
            x += px + 18
        m = render_tile(160, maskable=True)
        md = ImageDraw.Draw(m)
        md.ellipse([16, 16, 144, 144], outline=(255, 120, 120, 255), width=1)
        im.alpha_composite(m, (x + 8, 40))
        label(d, (x + 8, 206), "maskable, 80% safe circle", bg, small)
    sections.append(im)

    # The sixteen palettes, painted the way the app paints them: the palette's
    # brand colour on its background, at the welcome screen's 1.8rem (≈29 px)
    # and at a 16 px tab.
    pal = _palettes()
    cell_w, cell_h, per_row = (W - 2 * pad) // 8, 92, 8
    im, d = band(pad + 2 * cell_h + pad // 2, "#808080")
    for i, (name, bg, brand) in enumerate(pal):
        cx = pad + (i % per_row) * cell_w
        cy = pad // 2 + (i // per_row) * cell_h
        d.rectangle([cx + 2, cy + 2, cx + cell_w - 4, cy + cell_h - 6], fill=_hex(bg))
        im.alpha_composite(render_mark(29, brand), (cx + 16, cy + 40))
        im.alpha_composite(render_mark(16, brand), (cx + 60, cy + 53))
        label(d, (cx + 10, cy + 10), name, bg, small)
    sections.append(im)

    # The route glyphs.
    im, d = band(110, SHEET_LIGHT)
    d.rectangle([W // 2, 0, W, im.height], fill=_hex(SHEET_DARK))
    for half, bg, ink in ((0, SHEET_LIGHT, INK_ON_LIGHT), (W // 2, SHEET_DARK, INK_ON_DARK)):
        label(d, (half + pad, 8), "Route favicons, 32 and 16", bg)
        x = half + pad
        for route, contours in ROUTES.items():
            im.alpha_composite(glyph(contours, 32, ink), (x, 34))
            im.alpha_composite(glyph(contours, 16, ink), (x + 8, 74))
            label(d, (x, 94), route.strip("/")[:6], bg, small)
            x += 66
    sections.append(im)

    sheet = Image.new("RGBA", (W, sum(s.height for s in sections)), (0, 0, 0, 255))
    y = 0
    for sec in sections:
        sheet.alpha_composite(sec, (0, y))
        y += sec.height
    return sheet.convert("RGB")


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="compare with the tree; write nothing")
    ap.add_argument("--only", default="", help="comma-separated path prefixes to limit the run")
    args = ap.parse_args(argv)
    only = tuple(p for p in args.only.split(",") if p)
    bad = []
    for rel, value in outputs().items():
        if only and not rel.startswith(only):
            continue
        data = _encode(rel, value)
        target = ROOT / rel
        if args.check:
            if not target.exists() or not _same(rel, data, target.read_bytes()):
                bad.append(rel)
            continue
        if target.exists() and _same(rel, data, target.read_bytes()):
            continue  # unchanged pixels: leave the committed bytes alone
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"wrote {rel}")
    if bad:
        print("differs from what make_marks.py draws:\n  " + "\n  ".join(bad))
        return 1
    if args.check:
        print("brand files OK — every one is what make_marks.py draws")
    return 0


if __name__ == "__main__":
    sys.exit(main())
