# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B83` — one play triangle and one stop square, from one place.

**Measured before the change** (2026-09-16, `static/js/**` excluding
`static/lib/**`, comments blanked so a comment about a triangle is not counted
as one)::

    play triangle   19 sites, 5 geometries
      5 3 19 12 5 21 5 3   8   cookbook cookbookServe document×3 markdown
                               skills tasks
      6 4 20 12 6 20 6 4   5   chat cookbookRunning queuePanel tasks×2
      5 3 19 12 5 21       3   compare/icons compare/selector research
      6 3 20 12 6 21 6 3   2   chat(TTS) tts-ai
      7 4 19 12 7 20 7 4   1   tasks (the `active` badge)

The fifth geometry was found BY the detector below and not by a list: it
classifies a polygon by its shape rather than against the spellings somebody
already knew, and `tasks.js:909` — the badge that says a task is running — came
out of it. Matching known spellings is how `B12` counted two.

    stop square     13 sites, 4 geometries
      6 6 12 12 rx=1       5   cookbook-diagnosis cookbookRunning queuePanel
                               tasks×2
      6 6 12 12 rx=2       4   chat compare/index×2 compare/panes
      5 5 14 14 rx=2       3   chat(TTS) tts-ai×2
      5 5 14 14 rx=1.5     1   cookbookRunning (Stop all)

`B12` counted the triangle at two, `B83` re-counted it at seven in two
spellings. Both were narrower scopes. Nineteen and thirteen are the numbers over
the whole client, and two of the play geometries were on the same screen.

**How the claims are made.** "How many literals are in the tree" is a claim
about source and cannot be anything else, so it is made against source with
comments blanked. "What a module draws" is a claim about behaviour, so
`tests/harness/icon_table.js` loads the real table and the real `queuePanel.js`
constants and reports the markup they emit (`Law 20`) — a call site could pass
an option that changed the geometry, and reading the call would not show it.
"""
from __future__ import annotations

import collections
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "harness" / "icon_table.js"
CLIENT = ROOT / "static" / "js"
TABLE = CLIENT / "icons.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _h(mode: str, stdin: str = ""):
    proc = subprocess.run(["node", str(HARNESS), mode], input=stdin,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _blank(src: str) -> str:
    r"""Comments blanked, newlines kept so a reported line number is real.

    `Law 20`'s own warning, which these rows are the reason for: `icons.js`
    spells the old geometries out in its header to say what it replaced, and
    `checklist.js` still explains the one `B12` picked. A plain grep would count
    those as surviving literals.

    **This scans rather than substitutes, and `B230` is why.** `B83` wrote this
    as two regexes, and `re.sub(r"/\*.*?\*/", …, flags=re.S)` cannot tell a
    comment from a string: `input.accept = 'image/*,video/*'` at
    `gallery.js:1202` opens a "comment" that the next `*/` anywhere in the file
    closes. Measured across `static/js/**`: the regex form erases **7,203 lines
    of live code in 77 modules** — 1,745 of `calendar.js`, 1,735 of `notes.js`,
    1,137 of `settings.js`, 1,119 of `gallery.js`, 1,021 of `document.js` — and
    every census built on it was measuring a smaller tree than it claimed.
    `B83` closed on *"one play triangle in the tree, from one place"* with a
    play polygon at `document.js:4986` and two stop squares at `notes.js:4517`
    and `:4586` that it could not see, and counted the chevron at 45 when it was
    **54**. All nine are moved by `B230`. The same two regexes are copied into
    about twenty other test files; that is `B290`, not this row.
    """
    out = list(src)
    i, n = 0, len(src)
    stack = []          # 'tpl', or ('expr', brace depth) inside a `${…}`
    prev = ""           # last significant char — tells a regex from a divide

    def wipe(a, b):
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]
        if stack and stack[-1][0] == "tpl":
            if c == "\\":
                i += 2
            elif c == "`":
                stack.pop(); prev = "`"; i += 1
            elif c == "$" and src[i + 1:i + 2] == "{":
                stack.append(("expr", 0)); prev = "{"; i += 2
            else:
                i += 1
            continue
        if c in "'\"":
            q = c; i += 1
            while i < n and src[i] != q and src[i] != "\n":
                i += 2 if src[i] == "\\" else 1
            i += 1; prev = q; continue
        if c == "`":
            stack.append(("tpl", 0)); i += 1; continue
        if c == "/" and src[i + 1:i + 2] == "/":
            j = src.find("\n", i); j = n if j < 0 else j
            wipe(i, j); i = j; continue
        if c == "/" and src[i + 1:i + 2] == "*":
            j = src.find("*/", i + 2); j = n if j < 0 else j + 2
            wipe(i, j); i = j; continue
        if c == "/" and (prev == "" or prev in "=(,:[!&|?{};+-*%<>~^"):
            i += 1; cls = False
            while i < n:
                if src[i] == "\\":
                    i += 2; continue
                if src[i] == "[":
                    cls = True
                elif src[i] == "]":
                    cls = False
                elif src[i] == "/" and not cls:
                    break
                elif src[i] == "\n":
                    break
                i += 1
            i += 1; prev = "/"; continue
        if stack and stack[-1][0] == "expr":
            if c == "{":
                stack[-1] = ("expr", stack[-1][1] + 1)
            elif c == "}":
                if stack[-1][1] == 0:
                    stack.pop(); prev = "}"; i += 1; continue
                stack[-1] = ("expr", stack[-1][1] - 1)
        if not c.isspace():
            prev = c
        i += 1
    return "".join(out)


def _modules() -> list[Path]:
    return sorted(p for p in CLIENT.rglob("*.js")
                  if "static/lib/" not in p.as_posix())


# A polygon is a play triangle when its points make a left-anchored wedge
# pointing right: two points on the same x near the left edge and one on the
# vertical centre near the right. Derived from the SHAPE rather than matched
# against the four spellings, because the fifth spelling is the one a list would
# miss — which is the whole of `B12`'s mistake, twice.
def _play_polygons(src: str) -> list[tuple[int, str]]:
    found = []
    # `<polygon>` only. `emojiPicker.js` draws the symbol `≥` as a POLYLINE with
    # the same three points and a line under it; an open stroke is not a wedge,
    # and counting it would be the false positive that makes a census noise.
    for m in re.finditer(r'<polygon\b[^>]*\bpoints="([^"]*)"', src):
        raw = m.group(1).replace(",", " ").split()
        try:
            nums = [float(x) for x in raw]
        except ValueError:
            continue
        if len(nums) < 6 or len(nums) % 2:
            continue
        pts = list(zip(nums[0::2], nums[1::2]))
        if pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) != 3:
            continue
        xs = sorted(p[0] for p in pts)
        ys = sorted(p[1] for p in pts)
        tip = max(pts, key=lambda p: p[0])
        back = [p for p in pts if p is not tip]
        if (xs[0] < 8 and xs[-1] > 16 and abs(back[0][0] - back[1][0]) < 0.01
                and abs(tip[1] - 12) < 2 and ys[0] < 8 and ys[-1] > 16):
            found.append((src[:m.start()].count("\n") + 1, " ".join(raw)))
    return found


def _stop_rects(src: str) -> list[tuple[int, str]]:
    found = []
    for m in re.finditer(r"<rect\b[^>]*>", src):
        tag = " ".join(m.group(0).split())
        g = re.search(r'x="([\d.]+)"[^>]*y="([\d.]+)"[^>]*'
                      r'width="([\d.]+)"[^>]*height="([\d.]+)"', tag)
        if not g:
            continue
        x, y, w, h = (float(v) for v in g.groups())
        if (abs(w - h) < 0.01 and 7 <= w <= 14
                and abs(x + w / 2 - 12) < 1.6 and abs(y + h / 2 - 12) < 1.6):
            found.append((src[:m.start()].count("\n") + 1, tag))
    return found


def _census(finder):
    out = []
    for path in _modules():
        rel = path.relative_to(ROOT).as_posix()
        for line, text in finder(_blank(path.read_text(encoding="utf-8"))):
            out.append((f"{rel}:{line}", text))
    return out


# ---------------------------------------------------------------------------
# the count
# ---------------------------------------------------------------------------

def test_the_tree_holds_exactly_one_play_triangle():
    """`B83`'s `Verify`, first half. Nineteen sites in five geometries before;
    now no module writes a play polygon at all — the geometry exists once, as
    `PLAY_POINTS` in the table, and every form the table emits carries it (the
    driven test below)."""
    sites = _census(_play_polygons)
    assert sites == [], sites
    points = _h("glyphs")["points"]
    table = _blank(TABLE.read_text(encoding="utf-8"))
    assert table.count(points) == 1, "the table itself must not spell it twice"
    assert f'points="{points}"' in _h("glyphs")["playGlyph"]


def test_the_tree_holds_exactly_one_stop_square():
    """The second family, moved with the first. `B83` said solving the triangle
    alone and leaving the stops was not a fix, and it was right: `queuePanel.js`
    drew both, a pixel apart from the other copies of each."""
    sites = _census(_stop_rects)
    kept = [s for s, _ in sites if not s.startswith("static/js/emojiPicker.js")]
    # By file, not by line: a line number in an assertion is a test that fails
    # when somebody edits a comment above it.
    assert [s.split(":")[0] for s in kept] == ["static/js/icons.js"], sites
    table = _blank(TABLE.read_text(encoding="utf-8"))
    assert len(_stop_rects(table)) == 1, "the table itself must not spell it twice"
    # The two that stay are the symbol picker's ■ and □ — content, not controls.
    symbols = [s for s, _ in sites if s.startswith("static/js/emojiPicker.js")]
    assert len(symbols) == 2, sites


def test_a_second_literal_fails_this_test(tmp_path):
    """`B83`'s `Verify`, second half, stated as a property of the census rather
    than as a promise: the detector is given a module with a hand-written
    triangle in a geometry NOBODY has used, and finds it. A detector that
    matched the four known spellings would pass this and miss the fifth, which
    is exactly how `B12`'s count came out at two."""
    intruder = "const ICON = '<svg><polygon points=\"4 2 21 12 4 22\"/></svg>';\n"
    assert _play_polygons(intruder), "the census would not see a new geometry"
    # And a comment holding one is NOT a second literal — the trap `Law 20`
    # names, which this file would otherwise walk into itself.
    commented = "// was: <polygon points=\"6 4 20 12 6 20 6 4\"/>\nconst x = 1;\n"
    assert _play_polygons(_blank(commented)) == []
    blocked = "/* <polygon points=\"5 3 19 12 5 21\"/> */\nconst y = 2;\n"
    assert _play_polygons(_blank(blocked)) == []
    # Same for the square.
    assert _stop_rects('<rect x="7" y="7" width="10" height="10"/>')
    assert _stop_rects(_blank('// <rect x="6" y="6" width="12" height="12"/>')) == []


# ---------------------------------------------------------------------------
# what the modules draw (`Law 20`)
# ---------------------------------------------------------------------------

def test_every_form_the_table_emits_carries_the_same_geometry():
    """Filled, outlined, sized, styled, and the bare glyph the three menu tables
    take — one polygon and one rect out of all of them. The option that would
    silently fork the shape is the reason this is driven and not read."""
    out = _h("glyphs")
    assert set(out["polygons"]) == {"5 3 19 12 5 21"}, out["polygons"]
    assert len(set(out["rects"])) == 1, out["rects"]
    assert out["points"] == "5 3 19 12 5 21"
    # `Law 1`. Two sites draw the play triangle as a stroked outline —
    # `cookbookServe.js`'s serve button and `markdown.js`'s run-code button —
    # and the default is the filled wedge everything else used. The two must not
    # swap: a filled wedge where a hairline outline was is a different button.
    assert 'fill="currentColor"' in out["filled"], out["filled"]
    assert 'stroke="none"' in out["filled"]
    assert 'fill="none"' in out["outline"], out["outline"]
    assert 'stroke="currentColor"' in out["outline"]
    assert 'stroke-width="2"' in out["outline"]
    assert 'fill="currentColor"' in out["stop"], out["stop"]


def test_the_two_controls_on_one_row_are_drawn_by_the_same_table():
    """`Law 15` is the stake. `queuePanel.js`'s docked row carries play and stop
    next to each other and both constants are evaluated out of the shipped
    module — same size, same paint, same viewBox, and each glyph the table's."""
    panel = _h("panel")
    glyphs = _h("glyphs")
    for key in ("play", "stop"):
        assert 'viewBox="0 0 24 24"' in panel[key]
        assert 'width="9"' in panel[key] and 'height="9"' in panel[key]
    assert glyphs["playGlyph"] in panel["play"]
    assert glyphs["stopGlyph"] in panel["stop"]


def test_the_icon_table_names_no_colour():
    """**Themes are protected.** Sixteen themes ship and an icon table that
    invented a token would be a seventeenth. Every paint attribute the table can
    emit is `currentColor` or `none`, which is what all 31 literals already did
    — so this is a move, not a restyle."""
    out = _h("glyphs")
    assert set(out["paints"]) <= {'fill="currentColor"', 'stroke="currentColor"',
                                  'fill="none"', 'stroke="none"'}, out["paints"]
    src = _blank(TABLE.read_text(encoding="utf-8"))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), "a hex literal in the table"
    assert "var(--" not in src, "the table must not reach for a theme token"


def test_the_checklist_module_re_exports_rather_than_re_declares():
    """`Law 1`. `B12` put `PLAY_POINTS` in `checklist.js` and two modules import
    it from there. The glyph's home moved; the export did not go away."""
    src = _blank((CLIENT / "checklist.js").read_text(encoding="utf-8"))
    assert "export { PLAY_POINTS } from './icons.js';" in src
    assert "PLAY_POINTS = '" not in src, "that would be a second declaration"
    proc = subprocess.run(
        ["node", "--input-type=module", "--eval",
         "import { PLAY_POINTS as a } from '%s';\n"
         "import { PLAY_POINTS as b } from '%s';\n"
         "console.log(JSON.stringify([a, b]));"
         % (CLIENT / "checklist.js", TABLE)],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    a, b = json.loads(proc.stdout)
    assert a == b == "5 3 19 12 5 21"


def test_no_module_hand_writes_a_play_stop_or_chevron_svg_any_more():
    """The other half of one-place: a module could import the table and still
    inline its own `<svg>` around a glyph. Every site goes through
    `playIcon`/`stopIcon`/`chevronIcon`/`iconSvg` or takes a bare glyph, so the
    modules importing the table are the modules drawing these three.

    The names are read out of the IMPORT STATEMENT and not out of the file.
    `B83`'s version scanned the whole module for the word, and three modules
    have a local variable called `iconSvg` (`documentLibrary.js:210`,
    `emailLibrary.js:6748`, and the parameter `signatureFold.js:102` takes) —
    a census that counts those is a census that will be edited until it agrees
    with itself rather than with the tree."""
    importers = {}
    for path in _modules():
        if path == TABLE:
            continue
        src = _blank(path.read_text(encoding="utf-8"))
        # `compare/icons.js` exists too, so the specifier is not interchangeable:
        # inside a subdirectory the shared table is `../icons.js` and
        # `./icons.js` is the compare panel's own set. `editor/build/` is two
        # deep, which is why this is computed rather than a two-armed if.
        up = len(path.relative_to(CLIENT).parts) - 1
        spec = ("../" * up if up else "./") + "icons.js"
        m = re.search(r"^import \{([^}]*)\} from '%s';$" % re.escape(spec),
                      src, re.M)
        if m:
            importers[path.relative_to(ROOT).as_posix()] = sorted(
                n.strip() for n in m.group(1).split(",") if n.strip())
    assert importers == {
        "static/js/admin.js": ["chevronIcon"],
        "static/js/chat.js": ["playIcon", "stopIcon"],
        "static/js/compare/icons.js": ["playIcon"],
        "static/js/compare/index.js": ["chevronIcon", "stopIcon"],
        "static/js/compare/panes.js": ["stopIcon"],
        "static/js/compare/selector.js": ["chevronIcon", "playIcon"],
        "static/js/cookbook-diagnosis.js": ["STOP_GLYPH"],
        "static/js/cookbook.js": ["chevronIcon", "playIcon"],
        "static/js/cookbookRunning.js": ["PLAY_GLYPH", "STOP_GLYPH",
                                         "chevronIcon", "stopIcon"],
        "static/js/cookbookServe.js": ["chevronIcon", "playIcon"],
        "static/js/document.js": ["chevronIcon", "playIcon"],
        "static/js/documentLibrary.js": ["chevronIcon"],
        "static/js/editor/build/topbar.js": ["chevronIcon"],
        "static/js/emailInbox.js": ["chevronIcon"],
        "static/js/emailLibrary.js": ["chevronIcon"],
        "static/js/emailLibrary/signatureFold.js": ["chevronIcon"],
        "static/js/gallery.js": ["chevronIcon"],
        "static/js/galleryEditor.js": ["chevronIcon"],
        "static/js/gallery.js": ["chevronIcon"],
        "static/js/markdown.js": ["playIcon"],
        "static/js/modelPicker.js": ["chevronIcon"],
        "static/js/notes.js": ["chevronIcon", "stopIcon"],
        "static/js/planWindow.js": ["chevronIcon"],
        "static/js/queuePanel.js": ["chevronIcon", "playIcon", "stopIcon"],
        "static/js/research/panel.js": ["chevronIcon", "playIcon"],
        "static/js/section-management.js": ["chevronIcon"],
        "static/js/sessions.js": ["chevronIcon"],
        "static/js/settings.js": ["chevronIcon"],
        "static/js/skills.js": ["PLAY_GLYPH", "chevronIcon"],
        "static/js/tasks.js": ["PLAY_GLYPH", "playIcon", "stopIcon"],
        "static/js/tts-ai.js": ["playIcon", "stopIcon"],
    }, importers
    # `checklist.js` re-exports rather than imports, which the test below pins.
    assert "export { PLAY_POINTS } from './icons.js';" in _blank(
        (CLIENT / "checklist.js").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# the chevron (`B230`) — moved, and measured against what it replaced
# ---------------------------------------------------------------------------
#
# `B83` measured 45 chevrons in four spellings across 22 modules and left them
# where they were, for three written reasons. Re-measured with a comment blanker
# that can tell a comment from a string (see `_blank`) and a detector that
# classifies by shape, it is **57 in five spellings across 23 modules**. `B230`
# answers each reason and moves all 57 in one commit. The risk the row names is a SILENT one: fourteen stylesheet
# rules and six JS handlers rotate a chevron, and every one of them was written
# against a base pointing DOWN. A table that changed a base orientation, or that
# added a rotation of its own, would shift every fold affordance in the product
# and no test that only counted literals would notice. So the claim these tests
# make is not "there is one chevron" but "there is one chevron AND each of the
# 45 sites emits the `<svg>` its literal emitted, attribute for attribute".
#
# The before side is `tests/fixtures/chevron_sites_before_B230.json`, cut from
# the tree as it stood with the literals still in it. The after side is not read
# off the source: the OPTIONS come from the call sites, because that is where a
# size or a class now lives, and the MARKUP comes from the shipped table through
# `tests/harness/icon_table.js` (`Law 20`). Reading `chevronIcon({ size: 12 })`
# does not tell you what `size: 12` produces.

BASELINE = ROOT / "tests" / "fixtures" / "chevron_sites_before_B230.json"

_CHEVRON_SPELLINGS = {"6 9 12 15 18 9": "down", "18 15 12 9 6 15": "up",
                      "15 18 9 12 15 6": "left", "9 18 15 12 9 6": "right"}


def _chevron_polylines(src: str) -> list[tuple[int, str]]:
    """Every hand-written chevron in a module. Shape, not spelling.

    A chevron is three points whose two arms are level with each other and
    whose middle point is a vertex off the line between them — so a spelling
    nobody has used is still found. That is how `B230` found `6 15 12 9 18 15`
    at `document.js` twice and `galleryEditor.js` once, three sites a list of
    the four known spellings could not see; `B83` learned the same lesson on
    the play triangle and it still cost it a geometry.

    And it must be the ONLY child of its `<svg>`. That is not a convenience:
    104 polylines in this client are chevron-shaped and are not this icon —
    the head of a download arrow above its shaft, the two halves of `< >`, the
    hook of a reply arrow. Each shares its `<svg>` with a sibling, and folding
    them into an icon table is how an icon table starts meaning nothing (the
    argument `B83` made for `emojiPicker.js`'s two squares). A census that
    counted them would be one nobody could leave green.
    """
    found = []
    for m in re.finditer(r'<polyline\b[^>]*\bpoints="([^"]*)"', src):
        raw = m.group(1).replace(",", " ").split()
        try:
            nums = [float(x) for x in raw]
        except ValueError:
            continue
        if len(nums) != 6:
            continue
        a, v, b = zip(nums[0::2], nums[1::2])
        horiz = abs(a[1] - b[1]) < 0.01 and abs(a[0] - b[0]) > 6
        vert = abs(a[0] - b[0]) < 0.01 and abs(a[1] - b[1]) > 6
        if not (horiz or vert):
            continue
        if (abs(v[1] - a[1]) if horiz else abs(v[0] - a[0])) < 3:
            continue
        start = src.rfind("<svg", 0, m.start())
        end = src.find("</svg>", m.start())
        if start < 0 or end < 0:
            continue
        body = src[src.index(">", start) + 1:end]
        if len(re.findall(r"<([a-zA-Z]+)", body)) != 1:
            continue
        found.append((src[:m.start()].count("\n") + 1, " ".join(raw)))
    return found


def _js_value(text: str, i: int):
    """One JS literal starting at `text[i]`; returns (value, next index).

    Strings and template literals come back as their raw inner text — a class of
    ``mp-provider-chevron${isCollapsed ? ' collapsed' : ''}`` is passed to the
    table as that string, which is exactly what the template literal it replaced
    interpolated into `class="…"`. That keeps the one dynamic site comparable
    with its own baseline instead of excluded from the count."""
    c = text[i]
    if c in "'\"`":
        j = i + 1
        depth = 0
        while j < len(text):
            if text[j] == "\\":
                j += 2
                continue
            if c == "`" and text[j] == "$" and text[j + 1:j + 2] == "{":
                depth += 1
                j += 2
                continue
            if depth and text[j] == "}":
                depth -= 1
                j += 1
                continue
            if not depth and text[j] == c:
                break
            j += 1
        return text[i + 1:j], j + 1
    m = re.match(r"(true|false|-?\d+(?:\.\d+)?)", text[i:])
    assert m, text[i:i + 40]
    v = m.group(1)
    val = True if v == "true" else False if v == "false" else (
        float(v) if "." in v else int(v))
    return val, i + len(v)


def _chevron_calls(src: str) -> list[dict]:
    """Every `chevronIcon(...)` call in a module, in file order, as options."""
    calls = []
    for m in re.finditer(r"(?<!function )\bchevronIcon\(", src):
        i = m.end()
        while src[i].isspace():
            i += 1
        if src[i] == ")":
            calls.append({})
            continue
        assert src[i] == "{", src[m.start():m.start() + 60]
        i += 1
        opts = {}
        while True:
            while src[i] in " \t\n,":
                i += 1
            if src[i] == "}":
                break
            k = re.match(r"[A-Za-z]+", src[i:]).group(0)
            i += len(k)
            while src[i] in " \t:":
                i += 1
            opts[k], i = _js_value(src, i)
        calls.append(opts)
    return calls


def _svg_attrs(markup: str) -> dict:
    tag = markup[:markup.index(">") + 1]
    return dict(re.findall(r'([a-zA-Z-]+)="([^"]*)"', tag))


def _sites_now() -> dict:
    out = {}
    for path in _modules():
        if path == TABLE:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for n, opts in enumerate(_chevron_calls(_blank(
                path.read_text(encoding="utf-8"))), 1):
            out[f"{rel}#{n}"] = opts
    return out


def test_the_tree_holds_exactly_one_chevron():
    """`B230`'s `Verify`, first half. 57 literals in five spellings across 23
    modules before; none now — the geometry exists once, as `CHEVRON_POINTS`,
    and the other three directions are that one rotated."""
    sites = _census(_chevron_polylines)
    assert sites == [], sites
    table = _blank(TABLE.read_text(encoding="utf-8"))
    spellings = [p for _, p in _chevron_polylines(table)]
    assert spellings == [], "the table draws the chevron from points, not markup"
    assert table.count("'6 9 12 15 18 9'") == 1, "one chevron literal, once"
    for other in _CHEVRON_SPELLINGS:
        if other != "6 9 12 15 18 9":
            assert other not in table, f"{other} is spelled out, not derived"


def test_the_four_directions_are_one_geometry_rotated():
    """The shape question `B83` raised, answered with arithmetic rather than a
    preference. Three of the four spellings the product shipped are the base
    turned 180° and −90° exactly; the fourth is the +90° turn traversed the
    other way, which is the same stroke because every one of the 45 sites sets
    `stroke-linecap="round"`. So `direction` is an argument, not four glyphs."""
    out = _h("chevrons", "[]")
    base = out["base"]
    assert base == "6 9 12 15 18 9"

    def turn(points, deg):
        n = [float(x) for x in points.split()]
        rad = math.radians(deg)
        cos, sin = round(math.cos(rad)), round(math.sin(rad))
        got = []
        for x, y in zip(n[0::2], n[1::2]):
            x, y = x - 12, y - 12
            got.append((12 + x * cos - y * sin, 12 + x * sin + y * cos))
        return got

    def as_points(pairs):
        return " ".join(f"{int(x)} {int(y)}" for x, y in pairs)

    assert out["points"]["down"] == base
    assert out["points"]["up"] == as_points(turn(base, 180)) == "18 15 12 9 6 15"
    assert out["points"]["right"] == as_points(turn(base, -90)) == "9 18 15 12 9 6"
    # +90°, read backwards — the one spelling the product wrote in the other
    # traversal. Same three points, same two segments, same stroke.
    assert out["points"]["left"] == as_points(turn(base, 90)[::-1]) == "15 18 9 12 15 6"
    assert {tuple(sorted(turn(base, d)))
            for d in (0, 90, 180, -90)} != {tuple(sorted(turn(base, 0)))}, \
        "four directions, not one drawn four times"
    # And every spelling the product used is accounted for: no fifth direction
    # is reachable, and asking for one is an error rather than a blank glyph.
    assert set(out["points"].values()) == {"6 9 12 15 18 9", "18 15 12 9 6 15",
                                           "15 18 9 12 15 6", "9 18 15 12 9 6"}
    proc = subprocess.run(
        ["node", "--input-type=module", "--eval",
         "import { chevronPoints } from '%s';\n"
         "try { chevronPoints('sideways'); console.log('NO-THROW'); }\n"
         "catch (e) { console.log('THREW'); }" % TABLE],
        capture_output=True, text=True, timeout=30)
    assert proc.stdout.strip() == "THREW", proc.stdout + proc.stderr


# `B291`'s diff, named site by site, applied to `B230`'s before-fixture.
#
# The fixture stays the record of what the tree emitted with the literals still
# in it — that is evidence about a commit that has landed and it does not get
# rewritten. What each site emits NOW is that record plus this delta and
# nothing else, which is the form that makes "we changed exactly these" an
# assertion instead of a claim.
#
# Two axes moved. Two did not, and they are `B394`.
_B291_LINEJOIN = ("static/js/cookbookRunning.js#1", "static/js/research/panel.js#5")


def _expected_now(before: dict) -> dict:
    """`B230`'s baseline with `B291` applied. Both changes, both explicit."""
    out = {}
    for key, rec in before.items():
        attrs = dict(rec["attrs"])
        # (1) aria-hidden, at every site that did not already state it. The
        #     builder's default carries all 46; the 11 that passed
        #     `ariaHidden: true` are unchanged because the value is the same.
        attrs["aria-hidden"] = "true"
        # (2) the two mitred vertices join their round siblings.
        if key in _B291_LINEJOIN:
            assert "stroke-linejoin" not in rec["attrs"], key
            attrs["stroke-linejoin"] = "round"
        out[key] = {**rec, "attrs": attrs}
    return out


def test_every_chevron_site_emits_what_its_literal_emitted_plus_B291s_two_changes():
    """The measurement `Law 1` asks for, made site by site rather than argued.

    57 before, 57 after, matched by module and by order within the module; for
    each one the `<svg>` the table now produces is compared with the `<svg>` the
    literal produced, every attribute and the stroke — plus exactly the two
    changes `B291` decided, applied by `_expected_now` where a reader can see
    them.

    Everything else is still normalised away by nothing at all: eleven sizes,
    seven stroke widths, one `id` and every inline style stay exactly as they
    were. Sizes and stroke widths are the half of `B291` that needs the owner,
    because the variation there is not uniformly drift — an 8px caret inside a
    toolbar button and a 24px gallery arrow are different controls — and they
    are `B394`.

    **This fails on the tree as it stood before `B291`** (`Law 9`): that tree
    emitted no `aria-hidden` at 46 of the 57 and left `stroke-linejoin` off at
    two, so `_expected_now` disagrees with it at 47 sites."""
    before = json.loads(BASELINE.read_text(encoding="utf-8"))
    want_all = _expected_now(before)
    now = _sites_now()
    assert len(before) == 57
    assert len({k.split("#")[0] for k in before}) == 23
    assert sorted(now) == sorted(before), sorted(set(now) ^ set(before))
    keys = sorted(before)
    rendered = _h("chevrons", json.dumps([now[k] for k in keys]))["rendered"]

    def segments(points):
        n = [float(x) for x in points.split()]
        pts = list(zip(n[0::2], n[1::2]))
        return {frozenset(pair) for pair in zip(pts, pts[1:])}

    diffs, respelled = [], []
    for key, markup in zip(keys, rendered):
        want = want_all[key]
        got = _svg_attrs(markup)
        points = re.search(r'<polyline points="([^"]*)"', markup).group(1)
        if got != want["attrs"] or segments(points) != segments(want["points"]):
            diffs.append((key, want["attrs"], got, want["points"], points))
        elif points != want["points"]:
            respelled.append(key)
    assert not diffs, diffs
    # The 46 that gained the attribute are named by construction: they are the
    # sites the baseline recorded WITHOUT it. Pinning the split stops the
    # decision drifting back one call site at a time.
    gained = {k for k in keys if not before[k]["attrs"].get("aria-hidden")}
    assert len(gained) == 46, sorted(gained)
    assert len(keys) - len(gained) == 11
    # Exactly three sites come out spelled differently, and it is the same
    # stroke: `6 15 12 9 18 15` and `18 15 12 9 6 15` are one polyline read from
    # either end, and every site sets `stroke-linecap="round"` so both ends are
    # drawn the same. Naming them is the honest form of "nothing changed".
    assert sorted(respelled) == ["static/js/document.js#1",
                                 "static/js/document.js#8",
                                 "static/js/galleryEditor.js#1"], respelled
    for key in respelled:
        assert before[key]["attrs"]["stroke-linecap"] == "round"
    # All four directions are live, so `direction` is not a parameter with one
    # value that happens to be the base.
    counts = collections.Counter(before[k]["direction"] for k in keys)
    assert counts == {"down": 43, "left": 6, "up": 5, "right": 3}, counts
    # What `B230` preserved and what `B291` settled, in one place.
    #   sizes / stroke widths — still eleven and seven, still open, still
    #     `B394`. A ratchet, not an endorsement: a TWELFTH size or an EIGHTH
    #     stroke width fails here rather than joining the spread quietly.
    assert len({before[k]["attrs"]["width"] for k in keys}) == 11
    assert len({before[k]["attrs"]["stroke-width"] for k in keys}) == 7
    assert len({_svg_attrs(m)["width"] for m in rendered}) == 11
    assert len({_svg_attrs(m)["stroke-width"] for m in rendered}) == 7
    #   vertices — was two mitred against 55 round; now every chevron in the
    #     product has the same vertex, which is `Law 15` satisfied rather than
    #     asserted.
    assert sum(1 for k in keys
               if "stroke-linejoin" not in before[k]["attrs"]) == 2
    assert all(_svg_attrs(m).get("stroke-linejoin") == "round" for m in rendered)
    #   aria-hidden — was 11 of 57; now 57 of 57.
    assert sum(1 for k in keys
               if before[k]["attrs"].get("aria-hidden")) == 11
    assert all(_svg_attrs(m).get("aria-hidden") == "true" for m in rendered)


def test_the_table_adds_no_rotation_of_its_own():
    """`B83`'s second objection, and the `Law 1` hazard the row names. Twenty
    places already rotate a chevron — fourteen stylesheet rules and six JS
    handlers — and all twenty were written against a base pointing DOWN. The
    table emits bare points and no transform, so the sheet stays the only thing
    that turns a chevron and the glyph never gets rotated twice."""
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    rules = [ln.strip() for ln in css.splitlines()
             if re.search(r"\.[\w-]*(chevron|caret)\b", ln) and "rotate(" in ln]
    assert len(rules) == 14, rules
    handlers = []
    for path in _modules():
        src = _blank(path.read_text(encoding="utf-8"))
        handlers += [path.name for _ in
                     re.finditer(r"chevron\w*\.style\.transform\s*=", src)]
    assert sorted(handlers) == ["admin.js"] * 4 + ["cookbookRunning.js"] * 2, handlers
    out = _h("chevrons", json.dumps([{}, {"direction": "up"},
                                     {"direction": "left", "className": "x"}]))
    for markup in out["rendered"]:
        assert "transform" not in markup, markup
        assert "rotate" not in markup, markup
    # The base is the orientation those twenty rotate FROM. If it moved, every
    # one of them would shift and nothing else here would fail.
    assert out["base"] == "6 9 12 15 18 9"
    assert out["glyph"] == '<polyline points="6 9 12 15 18 9"/>'


def test_a_second_chevron_literal_fails_this_test():
    """`B230`'s `Verify`, second half, as a property of the census rather than a
    promise. The detector is shown a chevron in a geometry nobody has used and
    must find it; shown one inside a comment it must not (`Law 20`); shown the
    polylines this client really draws that are NOT this icon it must stay
    quiet, which is what stops the census being noise nobody can leave green."""
    def svg(inner):
        return '<svg viewBox="0 0 24 24">' + inner + "</svg>"

    # A sixth spelling, in a geometry nobody has used. A census that matched the
    # five known spellings would pass this — and would have missed the three
    # `6 15 12 9 18 15` sites that this detector found.
    assert _chevron_polylines(svg('<polyline points="5 8 12 16 19 8"/>'))
    assert _chevron_polylines(svg('<polyline points="16 5 8 12 16 19"/>'))
    # And the reverse traversal of the shipped base, which is the miss that
    # actually happened.
    assert _chevron_polylines(svg('<polyline points="18 9 12 15 6 9"/>'))
    # A comment holding one is not a literal — the trap this file would walk
    # into itself, since `icons.js` spells the base out in its header.
    assert _chevron_polylines(_blank("// " + svg(
        '<polyline points="6 9 12 15 18 9"/>'))) == []
    assert _chevron_polylines(_blank("/* " + svg(
        '<polyline points="6 9 12 15 18 9"/>') + " */")) == []
    # Real non-chevrons from this tree. The first three are not the shape: the
    # trash-can lid, the file-corner fold, the document's three-dot rule. The
    # last two ARE the shape and are not the icon — a download arrow's head over
    # its shaft, and one half of `< >` — which is what the sole-child rule is
    # for, and why 104 shaped polylines are not counted as chevrons.
    assert _chevron_polylines(svg('<polyline points="3 6 5 6 21 6"/>')) == []
    assert _chevron_polylines(svg('<polyline points="14 2 14 8 20 8"/>')) == []
    assert _chevron_polylines(svg('<polyline points="10 9 9 9 8 9"/>')) == []
    assert _chevron_polylines(svg(
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10 12 15 17 10"/>')) == []
    assert _chevron_polylines(svg('<polyline points="16 18 22 12 16 6"/>'
                                  '<polyline points="8 6 2 12 8 18"/>')) == []
    # The detector is not a spelling list: it does not know the five.
    assert len(_CHEVRON_SPELLINGS) == 4


def test_the_chevron_the_table_draws_names_no_colour():
    """**Themes are protected.** The chevron arrives with seven stroke widths and
    eleven sizes and not one colour: every paint it can emit is `currentColor`
    or `none`, which is what all 57 literals already did. `--accent` is defined
    nowhere new."""
    out = _h("chevrons", "[]")
    assert set(out["paints"]) <= {'fill="none"', 'stroke="currentColor"'}, out["paints"]
    src = _blank(TABLE.read_text(encoding="utf-8"))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src)
    assert "var(--" not in src
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert not re.search(r":root\s*\{[^}]*--accent\s*:", css), \
        "`--accent` must never be defined in `:root`"


# ── `B292` — the shell, which cannot import a table ─────────────────────────
#
# `static/index.html` is markup. A `<script type="module">` cannot rewrite what
# the parser has already read without a flash, and the shell is the one surface
# where a flash is the whole cost `B141` paid to remove — so the seven (nine,
# see below) chevrons there could not move into `icons.js` with the other 57.
#
# `B292` wrote out two honest options: render the shell through a server-side
# template filter that calls one Python glyph table, or leave the markup where
# it is and pin it to the table with a test. The second is taken, and the row
# says it is probably right; the first is the only one that makes the count
# zero, and it needs `routes/` and `app.py`, which this row does not own.
#
# **The row's count was seven and the tree holds nine.** The two it missed are
# `#model-picker-btn`'s caret and `#overflow-plus-btn`'s glyph, both spelled
# `6 15 12 9 18 15` — the UP chevron traversed backwards, which is the fifth
# spelling `B230` found inside `document.js` showing up again in the shell. A
# census that matches the spellings somebody already knows cannot see them;
# `_chevron_polylines` classifies by SHAPE and does, which is the third time
# that technique has corrected a count on this family (`B83`'s fifth play
# triangle, `B230`'s fifth chevron spelling, and this).
#
# Both were respelled to the table's own `18 15 12 9 6 15`. That paints the
# identical stroke — a polyline's traversal is not part of its stroke and every
# one of them sets `stroke-linecap="round"` — so the check below is exact string
# equality rather than a segment-set comparison, and a future edit that reaches
# for a sixth spelling fails instead of joining the spread.

SHELL = ROOT / "static" / "index.html"


def _shell_chevrons() -> list[tuple[int, str, dict]]:
    """Every chevron in the shell: line, points, and the `<svg>`'s attributes.

    Found by `_chevron_polylines`, the same shape detector the module census
    uses, so the shell is measured by the rule rather than by a list of the
    spellings that happened to be there on the day.
    """
    src = SHELL.read_text(encoding="utf-8")
    out = []
    for line, points in _chevron_polylines(src):
        offset = sum(len(l) + 1 for l in src.split("\n")[:line - 1])
        start = src.rfind("<svg", 0, src.index(points, offset))
        out.append((line, points, _svg_attrs(src[start:])))
    return out


def test_the_shell_cannot_spell_a_chevron_the_table_does_not():
    """`B292`'s `Verify`, second option: the markup and `CHEVRON_POINTS` cannot
    drift, because a chevron in the shell that stops matching fails here.

    **This fails on the tree as it stood before this row** (`Law 9`): two of the
    nine spelled `6 15 12 9 18 15`, which is not any value `chevronPoints()`
    returns, and seven of the nine carried no `aria-hidden`.
    """
    table = _h("chevrons", "[]")["points"]
    found = _shell_chevrons()
    assert len(found) == 9, [(l, p) for l, p, _ in found]
    by_direction = collections.Counter()
    for line, points, attrs in found:
        matches = [d for d, p in table.items() if p == points]
        assert matches, (
            f"static/index.html:{line} spells a chevron `{points}` that "
            f"`icons.js` does not export. The table says {table}."
        )
        by_direction[matches[0]] += 1
        # Same decision as `B291`, and the shell is no more exempt from it than
        # a module is: a decorative glyph beside a label, or inside a control
        # that carries its own `title`/`aria-label`, is not announced.
        assert attrs.get("aria-hidden") == "true", (
            f"static/index.html:{line} announces a decorative chevron"
        )
    assert by_direction == {"down": 4, "up": 3, "left": 1, "right": 1}, by_direction


def test_the_shell_is_the_only_place_left_that_spells_one():
    """The scope line in `icons.js`'s header, kept true by measurement.

    `B230` moved 57 sites and left the shell, and said so. If a module grows a
    literal again this fails in `test_the_tree_holds_exactly_one_chevron`; if
    the shell's count moves, it fails here — so "nine, in one file, and that
    file is markup" stays a fact rather than a note somebody wrote once.
    """
    assert _census(_chevron_polylines) == []
    assert len(_shell_chevrons()) == 9
    login = ROOT / "static" / "login.html"
    assert _chevron_polylines(login.read_text(encoding="utf-8")) == [], (
        "the login page has grown a chevron; it is a third place to keep in step"
    )
