#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""check-icon-floor.py — no glyph paints a stroke under one device pixel.

`B782`, ruled in `D-2026-10-17-02` §4. An inline `<svg>` with a 24-unit
viewBox scales its `stroke-width` by `size / 24`, so a stroke-2 glyph at 11px
paints **0.917** device pixels at 1× — a line the browser cannot draw, which it
renders as a grey smear or drops on one side. `P5-13` wrote that sentence as an
example; `B782` measured it and found **115** such glyphs on 2026-09-19, 102 of
them exactly that pair. It was filed rather than fixed because the fix is not
one-directional and `B291` holds that icon geometry needs a written decision.

**What the ruling decided, and where this file corrects it.** §4 says the floor
is fixed by raising the **size**, on the argument that raising a stroke adds a
width to a ladder `P5-13` exists to shrink while raising 11 → 12 removes a size
and lands on one the tree already uses 153 times. That argument is right for
the 107 sites whose stroke is the house stroke 2 — but applied as a rule it is
wrong for four of the eight failing pairs, because their *strokes* are the rare
value. `16px @ 1.4` is the clearest: `1.4` appears **once** in the whole tree,
and moving it to `1.5` (11 uses) paints exactly 1.000px, changes no glyph's
size, and **deletes a width from the ladder**. So the rule actually applied is
§4's own criterion rather than its conclusion: **move whichever of the two
values is the rarer, and only onto a value the tree already uses.** Nothing new
entered either ladder, and three stroke widths left it.

  | was | now | painted | sites | moved |
  | --- | --- | --- | --- | --- |
  | 11px @ 2    | 12px @ 2   | 1.000 | 103 | size, stroke 2 has 826 uses |
  | 10px @ 2.2  | 11px @ 2.2 | 1.008 | 5   | size, 11px has 185 uses |
  | 10px @ 2    | 12px @ 2   | 1.000 | 4   | size, house stroke again |
  | 16px @ 1.4  | 16px @ 1.5 | 1.000 | 1   | stroke, 1.4 was used once |
  | 14px @ 1.6  | 14px @ 2   | 1.167 | 1   | stroke, 1.6 was used once |
  | 14px @ 1.7  | 14px @ 2   | 1.167 | 1   | stroke, 1.7 was used once |
  | 8px @ 2.5   | 8px @ 3    | 1.000 | 1   | stroke, keeps an 8px control's size |
  | 6px @ 3     | 8px @ 3    | 1.000 | 1   | size, stroke 4 would be a new width |

**The census moved between the ruling and the fix**, which is the argument for
checking it rather than recording it: 115 on 2026-09-19, **117** when the sweep
ran. Two arrived in the three weeks between.

**Both ladders got shorter anyway, which is the result worth recording.** Over
this file's scope — square glyphs declaring all four attributes, a narrower
population than `P5-13`'s 24-sizes-and-13-strokes count — the sweep took the
sizes from **19 to 18** (6px is gone) and the stroke widths from **14 to 11**
(1.4, 1.6 and 1.7 are gone), with nothing new entering either. Fixing a floor
is not usually also a simplification; it was here because the rule followed was
*move the rarer value*.

**The ladders are still deliberately NOT enforced.** `B291` measured the
chevron family site by site and found its three 8px glyphs carry
`stroke-width: 3.5` *because* 2.5 at that size paints 0.83px — correct
compensation a flattening pass would destroy. So *"the variation is not
uniformly drift"* is a measured claim, and collapsing what is left onto three
sizes and one stroke would delete the compensation along with the drift. This
file reports both ladders and fails neither; `P5-13`, `P5-14` and `B394` stay
open for a sitting with eyes on a screen.

**One glyph is sized by its caller and that is a hole a census cannot see.**
`langIcon(lang, size = 14)` in `static/js/langIcons.js` writes
`width="${size}"` with a literal `stroke-width="2"`, so *its* floor is a
minimum size of 12 and nothing in the file says so. Its default and all of its
call sites are checked here too.

    python3 .pantheon/check-icon-floor.py            # verify
    python3 .pantheon/check-icon-floor.py --report   # both ladders, with counts

Exits 0 when no glyph paints under 1.0 device pixel and no caller of a
parameterised glyph asks for a size that would.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: One device pixel at 1×. A stroke below this cannot be drawn.
FLOOR = 1.0

#: `B782`'s scope line, kept as code: the shipped surfaces, not the vendored ones.
def sources():
    yield from sorted((ROOT / "static").glob("*.html"))
    yield from sorted((ROOT / "static" / "js").rglob("*.js"))
    app = ROOT / "static" / "app.js"
    if app.exists():
        yield app


SVG_TAG = re.compile(r"<svg\b[^>]*>", re.I)
NUMBER = re.compile(r"[0-9.]+")

#: `{module: (function, literal stroke, viewBox)}` — glyphs whose size is an
#: argument, so the floor is a rule about their callers.
PARAMETERISED = {"static/js/langIcons.js": ("langIcon", 2.0, 24.0)}


def strip_comments(text: str, path: Path) -> str:
    """The repository's one comment blanker, loaded not reimplemented (`B290`)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_icon_floor_check_specifiers", ROOT / ".pantheon" / "check-specifiers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.strip_comments(text, mode=module.mode_for(path))


def attribute(tag: str, name: str) -> str | None:
    """One attribute off an `<svg>` open tag.

    Two traps, both of which produced a wrong census before they were fixed:
    a quoted value may contain spaces (`viewBox="0 0 24 24"` is the whole point
    of this file, and an unquoted-value pattern returns `0`), and `\\b` is not a
    left boundary for an attribute name because `-` is a word character
    boundary — `\\bwidth=` matches inside `stroke-width=`, which read eleven
    strokes as sizes. That is `B1404`'s hyphen bug in a second census.
    """
    guard = rf'(?<![-\w]){name}\s*=\s*'
    found = (re.search(guard + r'"([^"]*)"', tag, re.I)
             or re.search(guard + r"'([^']*)'", tag, re.I))
    return found.group(1) if found else None


def glyphs() -> list:
    """Every square inline `<svg>` that declares a numeric size, viewBox and stroke."""
    out = []
    for path in sources():
        text = strip_comments(path.read_text(encoding="utf-8", errors="replace"), path)
        for match in SVG_TAG.finditer(text):
            tag = match.group(0)
            width, height, view, stroke = (
                attribute(tag, name)
                for name in ("width", "height", "viewBox", "stroke-width"))
            if not (width and height and view and stroke):
                continue
            # A glyph sized at runtime declares no size; `PARAMETERISED` holds those.
            if not all(NUMBER.fullmatch(v) for v in (width, height, stroke)):
                continue
            parts = view.replace(",", " ").split()
            if len(parts) != 4 or parts[2] != parts[3] or width != height:
                continue
            try:
                size, pen, box = float(width), float(stroke), float(parts[2])
            except ValueError:
                continue
            if not box:
                continue
            out.append({
                "file": str(path.relative_to(ROOT)),
                "line": text.count("\n", 0, match.start()) + 1,
                "size": size, "stroke": pen, "view": box,
                "painted": pen * size / box,
            })
    return out


def minimum_size(stroke: float, view: float) -> float:
    """The smallest size at which `stroke` paints a whole device pixel."""
    return FLOOR * view / stroke


def parameterised_problems() -> list:
    """A glyph whose size is an argument, checked at its default and its callers."""
    problems = []
    for relative, (function, stroke, view) in sorted(PARAMETERISED.items()):
        path = ROOT / relative
        if not path.exists():
            problems.append(f"{relative} is gone; retire its entry in PARAMETERISED")
            continue
        text = strip_comments(path.read_text(encoding="utf-8"), path)
        if f'stroke-width="{stroke:g}"' not in text:
            problems.append(
                f"{relative} no longer writes `stroke-width=\"{stroke:g}\"`, so the "
                f"minimum size this file enforces on {function}()'s callers is stale")
            continue
        floor_size = minimum_size(stroke, view)
        default = re.search(rf"function {function}\([^)]*?size\s*=\s*([0-9.]+)", text)
        if default and float(default.group(1)) < floor_size:
            problems.append(
                f"{relative}: {function}()'s default size {default.group(1)} paints "
                f"{stroke * float(default.group(1)) / view:.3f}px; it needs {floor_size:g}")
        for caller in sources():
            if caller == path:
                continue
            body = strip_comments(caller.read_text(encoding="utf-8", errors="replace"), caller)
            for call in re.finditer(rf"\b{function}\(\s*[^,()]*,\s*([0-9.]+)", body):
                asked = float(call.group(1))
                if asked < floor_size:
                    problems.append(
                        f"{caller.relative_to(ROOT)}:{body.count(chr(10), 0, call.start()) + 1}"
                        f" calls {function}() at {asked:g}px, which paints "
                        f"{stroke * asked / view:.3f}px; the floor is {floor_size:g}px")
    return problems


def main() -> int:
    report = "--report" in sys.argv
    found = glyphs()
    under = [g for g in found if g["painted"] < FLOOR - 1e-9]

    print(f"icon floor — {len(found)} square sized glyphs with a stroke, "
          f"{len(under)} under one device pixel")

    problems = []
    for glyph in sorted(under, key=lambda g: (g["file"], g["line"])):
        problems.append(
            f"{glyph['file']}:{glyph['line']} — {glyph['size']:g}px at stroke "
            f"{glyph['stroke']:g} paints {glyph['painted']:.3f}px; raise the rarer of "
            f"the two onto a value the tree already uses (size "
            f"{minimum_size(glyph['stroke'], glyph['view']):.4g}+, or stroke "
            f"{FLOOR * glyph['view'] / glyph['size']:.4g}+)")
    problems.extend(parameterised_problems())

    sizes = Counter(g["size"] for g in found)
    strokes = Counter(g["stroke"] for g in found)
    print(f"  ladders, reported and NOT enforced (`B291`): {len(sizes)} sizes, "
          f"{len(strokes)} stroke widths")
    if report:
        print("\n  sizes:   " + "  ".join(f"{k:g}({v})" for k, v in sorted(sizes.items())))
        print("  strokes: " + "  ".join(f"{k:g}({v})" for k, v in sorted(strokes.items())))
        print("\n  the tightest glyphs in the tree:")
        for glyph in sorted(found, key=lambda g: g["painted"])[:8]:
            print(f"    {glyph['painted']:.3f}px  {glyph['size']:g}px @ {glyph['stroke']:g}"
                  f"  {glyph['file']}:{glyph['line']}")

    if problems:
        print(f"\nicon floor DRIFTED — {len(problems)} problem(s)")
        for problem in problems[:25]:
            print(f"  E {problem}")
        if len(problems) > 25:
            print(f"  … and {len(problems) - 25} more")
        return 1
    print("\nicon floor OK — every glyph paints at least one device pixel, and no "
          "caller of a parameterised glyph asks for a size that would not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
