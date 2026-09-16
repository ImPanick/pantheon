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

import json
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


def _h(mode: str):
    proc = subprocess.run(["node", str(HARNESS), mode],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _blank(src: str) -> str:
    """Comments blanked, newlines kept so a reported line number is real.

    `Law 20`'s own warning, which this row is the reason for: `icons.js` spells
    all five old geometries out in its header to say what it replaced, and
    `checklist.js` still explains the one `B12` picked. A plain grep would count
    those as six surviving triangles.
    """
    src = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                 src, flags=re.S)
    return re.sub(r"^([ \t]*)//.*$",
                  lambda m: m.group(1) + " " * (len(m.group(0)) - len(m.group(1))),
                  src, flags=re.M)


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


def test_no_module_hand_writes_a_play_or_stop_svg_any_more():
    """The other half of one-place: a module could import the table and still
    inline its own `<svg>` around a glyph. Every site now goes through
    `playIcon`/`stopIcon`/`iconSvg` or takes the bare glyph, so the count of
    modules importing the table is the count of modules drawing these two."""
    importers = {}
    for path in _modules():
        src = _blank(path.read_text(encoding="utf-8"))
        # `compare/icons.js` exists too, so the specifier is not interchangeable:
        # inside a subdirectory the shared table is `../icons.js` and
        # `./icons.js` is the compare panel's own set.
        spec = "'./icons.js'" if path.parent == CLIENT else "'../icons.js'"
        if f"from {spec}" in src and path != TABLE:
            names = re.findall(r"\b(PLAY_GLYPH|STOP_GLYPH|playIcon|stopIcon|iconSvg)\b",
                               src)
            importers[path.relative_to(ROOT).as_posix()] = sorted(set(names))
    assert importers == {
        "static/js/chat.js": ["playIcon", "stopIcon"],
        "static/js/checklist.js": [],
        "static/js/compare/icons.js": ["playIcon"],
        "static/js/compare/index.js": ["stopIcon"],
        "static/js/compare/panes.js": ["stopIcon"],
        "static/js/compare/selector.js": ["playIcon"],
        "static/js/cookbook-diagnosis.js": ["STOP_GLYPH"],
        "static/js/cookbook.js": ["playIcon"],
        "static/js/cookbookRunning.js": ["PLAY_GLYPH", "STOP_GLYPH", "stopIcon"],
        "static/js/cookbookServe.js": ["playIcon"],
        "static/js/document.js": ["playIcon"],
        "static/js/markdown.js": ["playIcon"],
        "static/js/queuePanel.js": ["playIcon", "stopIcon"],
        "static/js/research/panel.js": ["playIcon"],
        "static/js/skills.js": ["PLAY_GLYPH"],
        "static/js/tasks.js": ["PLAY_GLYPH", "playIcon", "stopIcon"],
        "static/js/tts-ai.js": ["playIcon", "stopIcon"],
    }, importers


# ---------------------------------------------------------------------------
# the chevron, measured and deliberately not moved
# ---------------------------------------------------------------------------

def test_the_chevron_is_still_measured_so_the_next_pass_starts_from_a_number():
    """`B83` named 5 chevrons "on the same footing"; re-measured over the whole
    client it is 45 in four spellings across 22 modules, 12 of them in
    `emailLibrary.js` and `notes.js`. This pins the count so `B230` is a row
    about a number rather than an impression — and it fails if somebody moves
    part of the family, which is the outcome the row argues against."""
    spellings = {"6 9 12 15 18 9", "18 15 12 9 6 15", "9 18 15 12 9 6",
                 "15 18 9 12 15 6"}
    sites = []
    for path in _modules():
        src = _blank(path.read_text(encoding="utf-8"))
        for m in re.finditer(r'points="([^"]*)"', src):
            if " ".join(m.group(1).replace(",", " ").split()) in spellings:
                sites.append(path.relative_to(ROOT).as_posix())
    assert len(sites) == 45, len(sites)
    assert len(set(sites)) == 22, sorted(set(sites))
    other_agents = [s for s in sites
                    if s.endswith(("emailLibrary.js", "notes.js"))]
    assert len(other_agents) == 12, other_agents
