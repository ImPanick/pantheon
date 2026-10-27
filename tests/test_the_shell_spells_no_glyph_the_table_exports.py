# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1561` — the shell spells no glyph geometry that `icons.js` exports.

`B398` made the shell's chevrons the table's: `static/index.html` writes
`{{chevron:<direction>}}` and `src/shell_glyphs.py` draws it from `icons.js`
before the page is hashed, cached and served. Two families were left: the play
triangle, `5 3 19 12 5 21` written out five times (the skills bulk Audit
button, and four *Test* buttons) and pinned by no test — `test_one_icon_table`'s
census reads `static/js/**` only — and the workflow glyph, `WORKFLOW_GLYPH`
spelled four times (the Workbench's rail button, Tools row, Customize UI switch
and window title) and held equal to the table by a test, which kept the copies
from drifting without making them one.

Now the file asks for both by name — `{{glyph:play-points}}` and
`{{glyph:workflow}}` — and the server reads the exports and draws them.

Driven (`Law 20`): the table's exports are read by importing `icons.js` in
node; the page is the one `app_helpers._read_page` serves.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_one_icon_table import _play_polygons

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
ICONS_JS = ROOT / "static" / "js" / "icons.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def exports() -> dict:
    """Every string `icons.js` exports, by name, from the module itself."""
    script = ("import * as icons from '%s';"
              "const out = {}; for (const [k, v] of Object.entries(icons))"
              " if (typeof v === 'string') out[k] = v;"
              "console.log(JSON.stringify(out));" % ICONS_JS.as_posix())
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert {"PLAY_POINTS", "WORKFLOW_GLYPH", "CHEVRON_POINTS", "STOP_GLYPH"} <= set(out), sorted(out)
    return out


def test_the_shell_file_spells_no_geometry_the_table_exports(exports):
    """The row's `Verify:`."""
    raw = INDEX.read_text(encoding="utf-8")
    spelled = {name: raw.count(value) for name, value in exports.items() if value in raw}
    assert spelled == {}, spelled
    # And by shape, not spelling: no play wedge in any geometry
    # (`test_one_icon_table`'s detector, the one the module census uses).
    assert _play_polygons(raw) == [], _play_polygons(raw)


def test_the_shell_asks_for_each_by_name():
    raw = INDEX.read_text(encoding="utf-8")
    assert raw.count('<polygon points="{{glyph:play-points}}"/>') == 5
    assert raw.count("{{glyph:workflow}}") == 4


def test_the_server_draws_what_icons_js_exports(exports):
    from src import shell_glyphs

    assert shell_glyphs.glyph("play-points") == exports["PLAY_POINTS"]
    assert shell_glyphs.glyph("workflow") == exports["WORKFLOW_GLYPH"]


def test_the_page_the_route_serves_is_drawn(exports):
    from src.app_helpers import _read_page

    body = _read_page(str(INDEX)).body.decode("utf-8")
    assert "{{glyph:" not in body, "a placeholder reached the page"
    assert body.count(f'<polygon points="{exports["PLAY_POINTS"]}"/>') == 5
    assert body.count(exports["WORKFLOW_GLYPH"]) == 4


def _moved_table(tmp_path, monkeypatch, old: str, new: str):
    from src import shell_glyphs

    src = ICONS_JS.read_text(encoding="utf-8")
    assert src.count(old) == 1, old
    moved = tmp_path / "icons.js"
    moved.write_text(src.replace(old, new), encoding="utf-8")
    monkeypatch.setattr(shell_glyphs, "ICONS_JS", str(moved))
    monkeypatch.setattr(shell_glyphs, "_cache", {})
    return shell_glyphs


def test_a_change_to_the_table_reaches_the_shell(tmp_path, monkeypatch):
    """Read, not copied: give the table another triangle and the shell is
    drawn with it."""
    g = _moved_table(tmp_path, monkeypatch, "export const PLAY_POINTS = '5 3 19 12 5 21';",
                     "export const PLAY_POINTS = '6 4 20 12 6 20';")
    assert g.render('<polygon points="{{glyph:play-points}}"/>') == '<polygon points="6 4 20 12 6 20"/>'


def test_an_export_it_cannot_read_is_left_as_written_and_said(tmp_path, monkeypatch, caplog):
    """A glyph the reader cannot read is an invisible glyph, logged — never a
    page that fails to serve, and never a guess."""
    g = _moved_table(tmp_path, monkeypatch, "export const WORKFLOW_GLYPH =\n",
                     "export const WORKFLOW_GLYPH = `${''}` +\n")
    with caplog.at_level(logging.ERROR, logger="src.shell_glyphs"):
        out = g.render('<svg>{{glyph:workflow}}</svg><polygon points="{{glyph:play-points}}"/>')
    assert out == '<svg>{{glyph:workflow}}</svg><polygon points="5 3 19 12 5 21"/>', out
    assert any("WORKFLOW_GLYPH" in r.getMessage() for r in caplog.records)
    with caplog.at_level(logging.ERROR, logger="src.shell_glyphs"):
        assert g.render("{{glyph:nonesuch}}") == "{{glyph:nonesuch}}"
    assert any("nonesuch" in r.getMessage() for r in caplog.records)
