# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1744`–`B1746` — a phone chat gives the typing its room, a wide table
scrolls, and the model draws flow charts and graphs from shipped skills.

The owner, 2026-11-02, from a phone: *"Model selector in the chatbox takes up
space... once the user types it should vanish and release it's space.. Secondly,
the tables built by the llm in chat, the user cant side-scroll to view. Lets get
sidescroll as needed. Also, the LLM should be able to produce flow charts/graphs
etc, as needed (add these into the inventory of skills Pantheon ships with."*

Measured at 412×900 on `9111a94e`: the tucked-away model chip kept its 119px
slot in the cockpit's flex row, so the message wrapped in 213 of the row's
374px; a four-column table drew its columns a word wide with
`overflow-x: hidden` (the cockpit's rounded-corner rule); and Mermaid charts,
which already render in chat, drew the first `xychart` series in `#EEE` on a
white plot (light) and pie slices from `#0b0000` (dark). The browser numbers
after the change (344px, a table scrolling 653 over 370, both charts in
Mermaid's own palette) were driven with Playwright and are in the row.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from src import constants
from services.memory.skills import SkillsManager, invalidate_skill_cache
from tests.helpers.markdown_harness import harness_import

ROOT = Path(__file__).resolve().parent.parent
COCKPIT = (ROOT / "static" / "cockpit.css").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
SKILLS = ROOT / "library" / "pantheon" / "skills"
HAS_NODE = shutil.which("node") is not None
needs_node = pytest.mark.skipif(not HAS_NODE, reason="node binary not on PATH")


# ── B1744: the tucked-away model chip leaves the row ──────────────────────────

def test_a_tucked_away_model_chip_leaves_the_composer_row():
    """Red before: the cockpit set the chip `position: relative` in the flex
    row and only faded it, so its slot stayed."""
    rule = re.search(
        r"html\.cockpit \.chat-input-top > \.model-picker-wrap:is\(\.model-picker-autohide, \.picker-auto-hidden\),\s*"
        r"html\.cockpit body\.plan-mode-active \.chat-input-top > \.model-picker-wrap \{([^}]*)\}",
        COCKPIT,
    )
    assert rule, "no cockpit rule takes the tucked-away chip out of the row"
    assert "position: absolute !important" in rule.group(1)
    # …and it comes after the rule that put it in the row, so it wins.
    assert COCKPIT.index(rule.group(0)) > COCKPIT.index(
        "html.cockpit .model-picker-wrap { position: relative !important;")


# ── B1745: a wide table scrolls sideways ─────────────────────────────────────

def _render(markdown: str) -> str:
    script = textwrap.dedent(
        r"""
        __HARNESS_IMPORT__
        globalThis.window = { location: { origin: 'http://localhost' }, katex: null };
        globalThis.document = {
          readyState: 'loading', addEventListener() {},
          createElement() { return { _h: '', content: { querySelectorAll() { return []; } },
            set innerHTML(v) { this._h = v; }, get innerHTML() { return this._h; } }; },
        };
        globalThis.MutationObserver = class { observe() {} };
        const mod = await importMarkdown();
        console.log(JSON.stringify({ html: mod.mdToHtml(JSON.parse(process.argv[1])) }));
        """
    ).replace("__HARNESS_IMPORT__", harness_import("importMarkdown").strip())
    out = subprocess.run(["node", "--input-type=module", "-e", script, json.dumps(markdown)],
                         cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.splitlines()[-1])["html"]


@needs_node
def test_a_column_of_sentences_is_marked_and_a_short_one_is_not():
    html = _render(
        "| Step | What to do | Owner |\n|---|---|---|\n"
        "| 8. Compliance & audit | Prepare ISO 27001/PCI-DSS checklists and run regular penetration tests. | Ops |\n"
    )
    heads = re.findall(r"<th([^>]*)>", html)
    assert len(heads) == 3, html
    assert 'class="md-col-mid"' in heads[0], heads
    assert 'class="md-col-wide"' in heads[1], heads
    assert "class=" not in heads[2], heads
    cells = re.findall(r"<td([^>]*)>", html)
    assert 'class="md-col-wide"' in cells[1], cells


def test_the_marked_columns_have_a_floor_and_the_cockpit_table_scrolls():
    assert re.search(r"\.msg :is\(th, td\)\.md-col-mid \{ min-width: 15ch; \}", STYLE)
    assert re.search(r"\.msg :is\(th, td\)\.md-col-wide \{ min-width: 24ch; \}", STYLE)
    table = re.search(r"html\.cockpit \.msg \.body table \{([^}]*)\}", COCKPIT).group(1)
    # Red before: `overflow: hidden` (for the rounded corners) cut the table off.
    assert "overflow: auto hidden" in table, table
    assert not re.search(r"overflow:\s*hidden\s*;", table), table


# ── B1746: charts draw in the scheme's own palette, and wide ones scroll ─────

def _chart_overrides(theme_vars: dict) -> dict:
    js = (f"import {{ chartOverrides }} from '{(ROOT / 'static/js/markdown/mermaidTheme.js').as_posix()}';"
          f"console.log(JSON.stringify(chartOverrides({json.dumps(theme_vars)})));")
    out = subprocess.run(["node", "--input-type=module"], input=js, capture_output=True,
                         text=True, cwd=ROOT, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
def test_the_light_charts_first_series_is_not_the_plots_own_white():
    """`neutral`'s own values on the vendored 11.17.2 bundle."""
    got = _chart_overrides({
        "primaryColor": "#eee", "background": "#ffffff",
        "xyChart": {"backgroundColor": "#ffffff",
                    "plotColorPalette": "#EEE,#6BB8E4,#8ACB88,#C7ACD6,#E8DCC2,#FFB2A8,#FFF380,#7E8D91,#FFD8B1,#FAF3E0"},
    })
    palette = got["xyChart"]["plotColorPalette"].split(",")
    assert palette[0] == "#6BB8E4" and palette[-1] == "#EEE", palette
    assert got["xyChart"]["backgroundColor"] == "transparent"
    assert got["pie1"] == "#6BB8E4" and got["pie10"] == "#EEE"
    assert "pie11" not in got, "only the colours the scheme has"


@needs_node
def test_the_dark_pies_take_the_dark_chart_palette():
    got = _chart_overrides({
        "primaryColor": "#1f2020", "background": "#333",
        "xyChart": {"plotColorPalette": "#3498db,#2ecc71,#e74c3c,#f1c40f"},
    })
    assert [got[f"pie{i}"] for i in range(1, 5)] == ["#3498db", "#2ecc71", "#e74c3c", "#f1c40f"]


@needs_node
def test_a_theme_without_a_chart_palette_is_left_alone():
    assert _chart_overrides({"lineColor": "#666"}) == {}


def test_a_drawn_diagram_keeps_a_readable_width_and_its_frame_scrolls():
    md = (ROOT / "static" / "js" / "markdown.js").read_text(encoding="utf-8")
    assert "Promise.resolve(mermaid.run({ nodes })).then(() => _keepDiagramWidth(nodes))" in md
    assert "const _DIAGRAM_MAX_FLOOR = 560;" in md
    frame = re.search(r"html\.cockpit \.msg \.body \.mermaid-container \{([^}]*)\}", COCKPIT).group(1)
    assert "overflow: auto hidden" in frame, frame


# ── B1746: the two skills ship, and the model finds them ─────────────────────

NEW = ("draw-a-diagram", "chart-the-numbers")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    invalidate_skill_cache()
    yield SkillsManager(str(tmp_path))
    invalidate_skill_cache()


def test_the_diagram_and_chart_skills_ship_published(store):
    rows = {s["name"]: s for s in store.load_all() if s.get("library") == "pantheon"}
    for name in NEW:
        assert name in rows, name
        assert rows[name]["status"] == "published", name
        assert rows[name]["category"] == "visual", name
        assert not rows[name].get("requires_toolsets"), "Mermaid needs no tool"


def test_their_examples_are_mermaid_blocks_pantheon_draws():
    for name in NEW:
        body = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```mermaid\n(.*?)```", body, flags=re.S)
        assert blocks, name
        for b in blocks:
            assert b.split("\n", 1)[0].split()[0] in {
                "flowchart", "xychart-beta", "pie", "sequenceDiagram", "stateDiagram-v2"}, (name, b)


def test_the_catalogue_lists_them_and_a_search_finds_them(store):
    every = ["python", "read_file", "edit_file", "web_search", "agent_browser"]
    listed = {s["name"]: s["category"] for s in store.index_for(owner="alice", active_toolsets=every)}
    assert listed.get("draw-a-diagram") == "visual"
    assert listed.get("chart-the-numbers") == "visual"
    for query, want in (("flow chart", "draw-a-diagram"), ("bar graph of revenue", "chart-the-numbers"),
                        ("pie chart", "chart-the-numbers"), ("sequence diagram", "draw-a-diagram")):
        found = [r["name"] for r in store.find_skills(query, owner="alice", active_toolsets=every)]
        assert want in found[:3], (query, found)
