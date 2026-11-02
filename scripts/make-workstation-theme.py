#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
make-workstation-theme.py — the workstation desktop's look, drawn from the
cockpit's own colours (`D-2026-10-31-02`).

The workstation's desktop is XFCE (`workstation/provision.sh`). What makes it
look like Pantheon rather than stock XFCE is drawn here, from the five tokens
of the default theme (`static/js/theme.js`, THEMES.dark, "Original") mixed the
way `static/cockpit.css` mixes them, so a change of the cockpit's palette is a
change of one table below and one run of this script:

  workstation/desktop/themes/Pantheon/xfwm4/   the window frames: a 30 px
      title bar of the cockpit's glass, a lit top edge, rounded top corners
      and flat buttons that light on hover (the close button in the accent);
      `themerc` plus one XPM per part
  workstation/desktop/pantheon-desktop.svg     the wallpaper: the cockpit's
      light field (its four blurred lights over the canvas, and the vignette)
  workstation/desktop/pantheon-mark.svg        the menu button's icon

Everything is computed, with nothing but the standard library, so the output
is the same on every machine: antialiasing is 4x4 supersampling, done here.
The XPMs are opaque (xfwm4 does not blend a button onto its title bar), so
every edge is blended onto the exact title-bar pixels behind it; the only
transparent pixels are the corners' outside, which shapes the frame.

No grain, unlike the cockpit: the desktop is streamed (KasmVNC), and grain is
the one thing a video encoder cannot compress.

Usage:
    python3 scripts/make-workstation-theme.py          write the files
    python3 scripts/make-workstation-theme.py --check  exit 1 if they differ
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "workstation" / "desktop"
XFWM4 = DESKTOP / "themes" / "Pantheon" / "xfwm4"

# THEMES.dark in static/js/theme.js ("Original"), the cockpit's default.
# `tests/test_the_workstation_desktop_looks_like_pantheon.py` holds the two equal.
TOKENS = {"bg": "#282c34", "fg": "#9cdef2", "panel": "#111111", "border": "#355a66",
          "red": "#e06c75"}
# style.css `--color-muted`, dark arm: the pivot `--fg-muted` is mixed toward.
COLOR_MUTED = "#949494"

RGB = Tuple[float, float, float]  # 0..1 sRGB


# ── colour ───────────────────────────────────────────────────────────────────

def hex_rgb(h: str) -> RGB:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_hex(c: RGB) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in c)


def _lin(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _gam(v: float) -> float:
    v = max(0.0, min(1.0, v))
    return v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def to_oklab(c: RGB) -> RGB:
    r, g, b = (_lin(v) for v in c)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def from_oklab(c: RGB) -> RGB:
    L, a, b = c
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (_gam(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
            _gam(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
            _gam(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s))


def mix(a: RGB, b: RGB, t: float) -> RGB:
    """`color-mix(in oklab, a (1-t), b t)`."""
    x, y = to_oklab(a), to_oklab(b)
    return from_oklab(tuple(x[i] + (y[i] - x[i]) * t for i in range(3)))  # type: ignore[arg-type]


def mix_srgb(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))  # type: ignore[return-value]


def blend(under: RGB, over: RGB, alpha: float) -> RGB:
    """`over` at `alpha` painted on `under`, as a screen does it (sRGB)."""
    return mix_srgb(under, over, alpha)


WHITE, BLACK = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)


def palette() -> Dict[str, RGB]:
    """The cockpit's derived colours (`static/cockpit.css`, dark tone)."""
    bg, fg, panel, border, red = (hex_rgb(TOKENS[k]) for k in ("bg", "fg", "panel", "border", "red"))
    fg_muted = mix_srgb(hex_rgb(COLOR_MUTED), fg, 0.30)  # style.css --fg-muted
    glass = mix(panel, fg, 0.12)                          # --ck-glass-base
    p = {
        "bg": bg, "fg": fg, "accent": red, "border": border, "fg_muted": fg_muted,
        "text": fg,                                       # --ck-text
        "text_2": mix(fg_muted, fg, 0.55),                # --ck-text-2
        # The title bar is the glass, a step under the cockpit's slabs so the
        # window's own content (a terminal at --panel's depth) sits below it.
        "title": glass,
        "title_top": mix(glass, WHITE, 0.035),
        "title_off": mix(panel, fg, 0.06),
        "edge": mix(glass, fg, 0.15),                     # --ck-edge, opaque
        "edge_off": mix(mix(panel, fg, 0.06), fg, 0.08),
        "lit": mix(glass, WHITE, 0.14),                   # --ck-edge-hi
        "lit_off": mix(mix(panel, fg, 0.06), WHITE, 0.05),
        "tint": mix(glass, fg, 0.12),                     # --ck-tint-2 over the glass
        "tint_down": mix(glass, fg, 0.20),
        "close": red,
        "close_down": mix(red, BLACK, 0.18),
        "on_accent": WHITE,                               # --ck-on-accent
    }
    p["glyph"] = p["text_2"]
    p["glyph_off"] = mix(fg_muted, p["title_off"], 0.45)
    p["text_off"] = mix(fg_muted, p["title_off"], 0.25)
    # The light field (cockpit.css, #ck-field).
    hue = red
    accent_2 = mix(red, WHITE, 0.22)
    p["field_a"] = mix(bg, hue, 0.58)
    p["field_b"] = mix(bg, fg, 0.40)
    p["field_c"] = mix(border, hue, 0.30)
    p["field_d"] = mix(bg, accent_2, 0.55)
    return p


# ── drawing ──────────────────────────────────────────────────────────────────

SS = 4  # supersampling per axis
Image = List[List[Optional[RGB]]]  # rows of pixels; None is transparent


def render(w: int, h: int, shade: Callable[[float, float], Optional[RGB]]) -> Image:
    """Each pixel the mean of `shade` at SS x SS points inside it; a pixel
    whose points are mostly outside (None) is transparent, and its inside
    points are averaged on their own."""
    out: Image = []
    for j in range(h):
        row: List[Optional[RGB]] = []
        for i in range(w):
            acc = [0.0, 0.0, 0.0]
            n = 0
            for sy in range(SS):
                for sx in range(SS):
                    c = shade(i + (sx + 0.5) / SS, j + (sy + 0.5) / SS)
                    if c is not None:
                        n += 1
                        for k in range(3):
                            acc[k] += c[k]
            row.append(tuple(v / n for v in acc) if n * 2 >= SS * SS else None)  # type: ignore[misc]
        out.append(row)
    return out


def seg_dist(px: float, py: float, a: Tuple[float, float], b: Tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def rrect_inside(px: float, py: float, x0: float, y0: float, x1: float, y1: float,
                 r: float) -> bool:
    cx = min(max(px, x0 + r), x1 - r)
    cy = min(max(py, y0 + r), y1 - r)
    return math.hypot(px - cx, py - cy) <= r and x0 <= px <= x1 and y0 <= py <= y1


def rrect_stroke(px: float, py: float, x0: float, y0: float, x1: float, y1: float,
                 r: float, width: float) -> bool:
    return (rrect_inside(px, py, x0 - width / 2, y0 - width / 2, x1 + width / 2, y1 + width / 2,
                         r + width / 2)
            and not rrect_inside(px, py, x0 + width / 2, y0 + width / 2, x1 - width / 2,
                                 y1 - width / 2, max(0.0, r - width / 2)))


# ── the frame ────────────────────────────────────────────────────────────────

TITLE_H = 30
RADIUS = 8
CORNER_W = RADIUS
BUTTON_W = 30
SIDE = 1  # the 1 px hairline round the window


def title_shade(p: Dict[str, RGB], active: bool) -> Callable[[float, float], RGB]:
    """The title bar's column at height y: the hairline, the lit edge, then
    the glass with a faint sheen toward the top."""
    top, base = (p["title_top"], p["title"]) if active else (p["title_off"], p["title_off"])
    edge, lit = (p["edge"], p["lit"]) if active else (p["edge_off"], p["lit_off"])

    def at(_x: float, y: float) -> RGB:
        if y < 1:
            return edge
        if y < 2:
            return lit
        return mix_srgb(top, base, min(1.0, (y - 2) / (TITLE_H - 2)))
    return at


def corner(p: Dict[str, RGB], active: bool, right: bool) -> Image:
    column = title_shade(p, active)
    edge = p["edge"] if active else p["edge_off"]
    lit = p["lit"] if active else p["lit_off"]
    r = RADIUS

    def at(x: float, y: float) -> Optional[RGB]:
        if right:
            x = CORNER_W - x
        if x < r and y < r:
            d = r - math.hypot(r - x, r - y)  # inward distance from the arc
            if d < 0:
                return None
            if d < 1:
                return edge
            # the lit edge runs round the top of the arc and fades down its side
            if d < 2:
                k = max(0.0, min(1.0, (r - y) / r * 1.6 - 0.3))
                return mix_srgb(column(x, 2.5), lit, k)
            return column(x, max(y, 2.0))
        if x < SIDE:
            return edge
        return column(x, y)
    return render(CORNER_W, TITLE_H, at)


def glyph_shape(name: str, cx: float, cy: float) -> Callable[[float, float], bool]:
    """Where the button's glyph is ink: 10 px glyphs, 1 px strokes on the
    pixel grid where they are straight."""
    s = 4.5
    if name == "close":
        return lambda x, y: (seg_dist(x, y, (cx - s, cy - s), (cx + s, cy + s)) <= 0.7
                             or seg_dist(x, y, (cx - s, cy + s), (cx + s, cy - s)) <= 0.7)
    if name == "hide":
        return lambda x, y: abs(y - (cy + 0.5)) <= 0.5 and abs(x - cx) <= 5
    if name == "maximize":
        return lambda x, y: rrect_stroke(x, y, cx - 4.5, cy - 4.5, cx + 4.5, cy + 4.5, 1.5, 1.0)
    if name == "maximize-toggled":
        back = lambda x, y: rrect_stroke(x, y, cx - 2.5, cy - 4.5, cx + 4.5, cy + 2.5, 1.2, 1.0)  # noqa: E731
        front = lambda x, y: rrect_stroke(x, y, cx - 4.5, cy - 2.5, cx + 2.5, cy + 4.5, 1.2, 1.0)  # noqa: E731
        hole = lambda x, y: rrect_inside(x, y, cx - 4.0, cy - 2.0, cx + 2.0, cy + 4.0, 0.7)  # noqa: E731
        return lambda x, y: front(x, y) or (back(x, y) and not hole(x, y))
    if name in ("shade", "shade-toggled"):
        d = -1 if name == "shade" else 1
        return lambda x, y: (seg_dist(x, y, (cx - 4.5, cy - d * 2.2), (cx, cy + d * 2.3)) <= 0.7
                             or seg_dist(x, y, (cx, cy + d * 2.3), (cx + 4.5, cy - d * 2.2)) <= 0.7)
    if name == "menu":
        return lambda x, y: any(math.hypot(x - (cx + dx), y - cy) <= 1.3 for dx in (-4, 0, 4))
    if name == "stick":
        return lambda x, y: abs(math.hypot(x - cx, y - cy) - 3.5) <= 0.6
    if name == "stick-toggled":
        return lambda x, y: math.hypot(x - cx, y - cy) <= 4.0
    raise ValueError(name)


BUTTONS = ("close", "hide", "maximize", "maximize-toggled", "menu", "shade", "shade-toggled",
           "stick", "stick-toggled")
STATES = ("active", "inactive", "prelight", "pressed")


def button(p: Dict[str, RGB], name: str, state: str) -> Image:
    active = state != "inactive"
    column = title_shade(p, active)
    cx, cy = BUTTON_W / 2, TITLE_H / 2
    ink = glyph_shape(name, cx, cy)
    plate: Optional[RGB] = None
    glyph = p["glyph"] if active else p["glyph_off"]
    if state in ("prelight", "pressed"):
        if name == "close":
            plate = p["close"] if state == "prelight" else p["close_down"]
            glyph = p["on_accent"]
        else:
            plate = p["tint"] if state == "prelight" else p["tint_down"]
            glyph = p["text"]

    def at(x: float, y: float) -> RGB:
        c = column(x, y)
        if plate is not None and rrect_inside(x, y, cx - 11, cy - 11, cx + 11, cy + 11, 6):
            c = plate
        return glyph if ink(x, y) else c
    return render(BUTTON_W, TITLE_H, at)


def solid(w: int, h: int, c: RGB) -> Image:
    return [[c] * w for _ in range(h)]


def frame_parts(p: Dict[str, RGB]) -> Dict[str, Image]:
    parts: Dict[str, Image] = {}
    for state in ("active", "inactive"):
        on = state == "active"
        edge = p["edge"] if on else p["edge_off"]
        parts[f"top-left-{state}"] = corner(p, on, right=False)
        parts[f"top-right-{state}"] = corner(p, on, right=True)
        column = title_shade(p, on)
        for n in range(1, 6):
            parts[f"title-{n}-{state}"] = render(4, TITLE_H, column)
        parts[f"left-{state}"] = solid(SIDE, 4, edge)
        parts[f"right-{state}"] = solid(SIDE, 4, edge)
        parts[f"bottom-{state}"] = solid(4, SIDE, edge)
        parts[f"bottom-left-{state}"] = solid(4, SIDE, edge)
        parts[f"bottom-right-{state}"] = solid(4, SIDE, edge)
    for name in BUTTONS:
        for state in STATES:
            parts[f"{name}-{state}"] = button(p, name, state)
    return parts


_SYMBOLS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-"


def xpm(name: str, img: Image) -> str:
    h, w = len(img), len(img[0])
    colours: Dict[Optional[str], str] = {}
    for row in img:
        for c in row:
            key = None if c is None else rgb_hex(c)
            if key not in colours:
                n = len(colours)
                colours[key] = _SYMBOLS[n // len(_SYMBOLS)] + _SYMBOLS[n % len(_SYMBOLS)]
    ident = name.replace("-", "_")
    lines = ["/* XPM */", f"static char * {ident}_xpm[] = {{",
             f'"{w} {h} {len(colours)} 2",']
    for key, sym in colours.items():
        lines.append(f'"{sym}\tc {key or "None"}",')
    for j, row in enumerate(img):
        text = "".join(colours[None if c is None else rgb_hex(c)] for c in row)
        lines.append(f'"{text}"' + ("," if j < h - 1 else ""))
    lines.append("};")
    return "\n".join(lines) + "\n"


def themerc(p: Dict[str, RGB]) -> str:
    return "\n".join([
        "# SPDX-License-Identifier: AGPL-3.0-or-later",
        "# Pantheon's window frames for the workstation (D-2026-10-31-02).",
        "# Generated by scripts/make-workstation-theme.py from the cockpit's colours;",
        "# edit that script, not this file.",
        "button_offset=4",
        "button_spacing=0",
        "full_width_title=true",
        "title_horizontal_offset=0",
        "title_vertical_offset_active=1",
        "title_vertical_offset_inactive=1",
        "title_shadow_active=false",
        "title_shadow_inactive=false",
        "show_app_icon=false",
        "maximized_offset=0",
        f"active_text_color={rgb_hex(p['text_2'])}",
        f"inactive_text_color={rgb_hex(p['text_off'])}",
        "",
    ])


# ── the wallpaper and the mark ───────────────────────────────────────────────

W, H = 1280, 800  # workstation/protocol.py SCREEN_WIDTH, SCREEN_HEIGHT
BLUR = 60  # the field's blur(60px): the standard deviation of its Gaussian
FIELD_ALPHA = 0.5
# (cx, cy, r, colour) of the field's four lights at 1280x800, from cockpit.css
# #ck-field span:nth-child(1..4) (width in vw, offsets in vw/vh).
LIGHTS = (
    (-0.10 * W + 0.26 * W, -0.18 * W + 0.26 * W, 0.26 * W, "field_a"),
    (W + 0.12 * W - 0.23 * W, 0.08 * H + 0.23 * W, 0.23 * W, "field_b"),
    (0.30 * W + 0.20 * W, H + 0.22 * W - 0.20 * W, 0.20 * W, "field_c"),
    (W - 0.14 * W - 0.17 * W, H + 0.06 * W - 0.17 * W, 0.17 * W, "field_d"),
)
MARK_PATH = ("M5.18 12A11 11 0 0 1 26.82 12L25.74 12L16 7.82L6.26 12ZM16 10L30 16L2 16Z"
             "M4 18L28 18L28 20L4 20ZM5 20L8 20L8 26L5 26ZM11.33 20L14.33 20L14.33 26L11.33 26Z"
             "M17.67 20L20.67 20L20.67 26L17.67 26ZM24 20L27 20L27 26L24 26ZM2 26L30 26L30 28L2 28Z")


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def wallpaper(p: Dict[str, RGB]) -> str:
    """The light field as an SVG: each light a disc blurred by a Gaussian,
    which radially is 1 - Phi((rho - r) / sigma) — drawn as a radial gradient
    with that profile sampled every half sigma."""
    defs: List[str] = []
    shapes: List[str] = []
    for n, (cx, cy, r, key) in enumerate(LIGHTS, 1):
        reach = r + 3 * BLUR
        stops = []
        rho = max(0.0, r - 3 * BLUR)
        if rho > 0:
            stops.append((0.0, FIELD_ALPHA))
        while rho <= reach + 1e-9:
            stops.append((rho / reach, FIELD_ALPHA * (1 - _phi((rho - r) / BLUR))))
            rho += BLUR / 2
        stops[-1] = (1.0, 0.0)
        colour = rgb_hex(p[key])
        defs.append(f'<radialGradient id="light{n}" gradientUnits="userSpaceOnUse" '
                    f'cx="{cx:.1f}" cy="{cy:.1f}" r="{reach:.1f}">'
                    + "".join(f'<stop offset="{o:.4f}" stop-color="{colour}" '
                              f'stop-opacity="{a:.4f}"/>' for o, a in stops)
                    + "</radialGradient>")
        shapes.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{reach:.1f}" fill="url(#light{n})"/>')
    # the vignette: radial-gradient(130% 110% at 15% 0%, transparent 40%, bg/50% 100%)
    vx, vy, rx, ry = 0.15 * W, 0.0, 1.30 * W, 1.10 * H
    bg = rgb_hex(p["bg"])
    defs.append(f'<radialGradient id="vignette" gradientUnits="userSpaceOnUse" cx="{vx:.1f}" '
                f'cy="{vy:.1f}" r="{rx:.1f}" gradientTransform="translate({vx:.1f} {vy:.1f}) '
                f'scale(1 {ry / rx:.4f}) translate({-vx:.1f} {-vy:.1f})">'
                f'<stop offset="0.4" stop-color="{bg}" stop-opacity="0"/>'
                f'<stop offset="1" stop-color="{bg}" stop-opacity="0.5"/></radialGradient>')
    mark = 168
    mx, my = (W - mark) / 2, (H - mark) / 2 - 24
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        "<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->",
        "<!-- The workstation's wallpaper: the cockpit's light field (D-2026-10-31-02).",
        "     Generated by scripts/make-workstation-theme.py; edit that, not this. -->",
        "<defs>" + "".join(defs) + "</defs>",
        f'<rect width="{W}" height="{H}" fill="{bg}"/>',
        *shapes,
        f'<rect width="{W}" height="{H}" fill="url(#vignette)"/>',
        f'<path transform="translate({mx:.1f} {my:.1f}) scale({mark / 32:.4f})" '
        f'fill="{rgb_hex(p["fg"])}" fill-opacity="0.07" fill-rule="evenodd" d="{MARK_PATH}"/>',
        "</svg>",
        "",
    ])


def mark_icon(p: Dict[str, RGB]) -> str:
    return "\n".join([
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">',
        "<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->",
        "<!-- Pantheon's mark (docs/brand/pantheon-mark.svg) for the workstation's menu"
        " button. Generated by scripts/make-workstation-theme.py. -->",
        f'<path fill="{rgb_hex(p["fg"])}" fill-rule="evenodd" d="{MARK_PATH}"/>',
        "</svg>",
        "",
    ])


# ── output ───────────────────────────────────────────────────────────────────

def outputs() -> Dict[Path, str]:
    p = palette()
    out: Dict[Path, str] = {XFWM4 / "themerc": themerc(p)}
    for name, img in sorted(frame_parts(p).items()):
        out[XFWM4 / f"{name}.xpm"] = xpm(name, img)
    out[DESKTOP / "pantheon-desktop.svg"] = wallpaper(p)
    out[DESKTOP / "pantheon-mark.svg"] = mark_icon(p)
    return out


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="change nothing; exit 1 if a committed file differs")
    args = ap.parse_args(argv)
    stale = []
    files = outputs()
    for path, text in files.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        stale.append(path)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    extra = sorted(set(XFWM4.glob("*")) - set(files)) if XFWM4.is_dir() else []
    for path in extra:
        stale.append(path)
        if not args.check:
            path.unlink()
    for path in stale:
        print(("stale: " if args.check else "wrote: ") + str(path.relative_to(ROOT)))
    return 1 if args.check and stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
