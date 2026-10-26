# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1537` — every tour passes a step with nothing on screen, through one step runner.

`static/js/slashCommands.js` held ten step runners, one per tour. Eight of them
resolved `'skip'` when a step's target was not rendered, and their loops read
that as the person pressing *skip tour*: one hidden control ended the Forge,
Theme, Settings, Gallery, Notes, Brain, Tasks, Research or Library tour where it
stood. Only the Compare and first-run tours passed the step (`B1346`). Now there
is one runner (`_tourSession`): it resolves `'absent'` for a step with nothing
on screen, and its `walk` passes it in the direction of travel, whichever tour.

Driven in headless Chromium (the `playwright` node package, as
`test_the_compare_tour_points_only_at_what_is_shown.py` is): each tour function
and the runner are cut out of the module and run against a page holding that
tour's window, with one step's target `display: none`. The tour is walked with
its own → buttons (and, where a step waits for the person to act, by pressing
the highlighted control or typing into `#message`) until it says its closing
line.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_binding, js_definition, js_function
from tests.helpers.source_text import blank_text
from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SLASH = (ROOT / "static" / "js" / "slashCommands.js").read_text(encoding="utf-8")
browser = pytest.mark.skipif(NODE is None, reason=_SKIP or "")


def _cut(signature: str) -> str:
    return js_definition(SLASH, blank_text(SLASH, "js").index(signature))


def _harness() -> str:
    return (
        "window.replies = [];\n"
        "window._isAdmin = false;\n"
        "const topPortalZ = () => 10031;\n"
        "const scrollBehavior = () => 'auto';\n"
        "const slashReply = (m) => window.replies.push(String(m));\n"
        "const typewriterReply = async (m) => { window.replies.push(String(m));\n"
        "  const d = document.createElement('div'); document.body.appendChild(d); return d; };\n"
        "const _hasConfiguredModels = async () => true;\n"
        "const _isStreamingFn = () => false;\n"
        "const Storage = { KEYS: { TOGGLES: 't' }, getJSON: () => ({}), setJSON: () => {} };\n"
        + js_binding(SLASH, "_TOUR_CSS") + "\n"
        + "\n".join(_cut(sig) for sig in (
            "function _tourTargets(", "function _tourTarget(", "function _clearTourCommand(",
            "function _tourSession(", "async function _cmdDemo(", "async function _cmdTourCompare(",
            "async function _cmdTourCookbook(", "async function _cmdTourTheme(",
            "async function _cmdTourSettings(", "async function _cmdTourGallery(",
            "async function _cmdTourNotes(", "async function _cmdTourBrain(",
            "async function _openTasksForTour(", "async function _runTaskTour(",
            "async function _cmdTourTask2(", "async function _cmdTourResearch(",
            "async function _cmdTourLibrary(")) + "\n"
        "window.startTour = (name) => { window.tour = window[name] ? window[name]([], {}) : eval(name)([], {}); };\n"
    )


H = 'style="display:none"'   # the step that has nothing on screen

# tour function, its window, the hidden step's opening words, its closing line.
TOURS = {
    "_cmdTourNotes": (
        '<div id="notes-pane"><div class="notes-pane-body">notes</div>'
        f'<input id="notes-search" {H}><button id="notes-view-toggle">v</button>'
        '<button id="notes-archive-toggle">a</button><button id="notes-select-btn">s</button></div>',
        "<b>Search</b>", "That’s Notes."),
    "_cmdTourGallery": (
        '<div id="gallery-modal" class="modal"><div class="modal-content">g'
        '<button class="gallery-tab" data-tab="images">i</button>'
        f'<div id="gallery-upload-tile" {H}>u</div>'
        '<button class="gallery-tab" data-tab="albums">a</button>'
        '<button class="gallery-tab" data-tab="editor">e</button></div></div>',
        "Drop or click", "That’s Gallery."),
    "_cmdTourBrain": (
        '<div id="memory-modal" class="modal"><div class="memory-modal-content">b'
        f'<button id="memory-tidy-btn" {H}>t</button><button id="memory-skills-door">s</button>'
        '<div class="memory-tab-panel" data-memory-panel="rag">r</div>'
        '<div class="memory-tab-panel" data-memory-panel="settings">s</div></div></div>',
        "<b>Tidy</b>", "That’s Brain."),
    "_cmdTourCookbook": (
        '<div id="cookbook-modal" class="modal"><div class="modal-content">f'
        '<button class="cookbook-tab" data-backend="Settings">s</button>'
        f'<input id="cookbook-dl-repo" {H}><div class="admin-card"><div id="hwfit-list">h</div></div>'
        '<button id="hwfit-hw-manual-btn">m</button><button id="cookbook-hf-latest-toggle">t</button>'
        '<button class="cookbook-tab" data-backend="Serve">v</button>'
        '<button class="cookbook-tab" data-backend="Dependencies">d</button></div></div>',
        "Paste a HuggingFace", "That’s Forge."),
    "_cmdTourTheme": (
        '<div id="theme-modal" class="modal"><div id="theme-popup">t'
        '<div id="theme-tabs"><button class="admin-tab" data-tab="theme-tab-browse">b</button>'
        '<button class="admin-tab" data-tab="theme-tab-customize">c</button></div>'
        f'<div id="themeGrid">g</div><div id="theme-harmony-card" {H}>h</div>'
        '<div id="themeCustom">c</div><select id="theme-bg-pattern-select"></select>'
        '<div id="theme-opacity-wrap">o</div></div></div>',
        "<b>Colour harmony</b>", "That’s Theme."),
    "_cmdTourSettings": (
        '<div id="settings-modal" class="modal"><div class="modal-content">s'
        + "".join(f'<button class="settings-nav-item" data-settings-tab="{t}"'
                  + (f" {H}" if t == "search" else "") + f'>{t}</button>'
                  for t in ("integrations", "search", "appearance", "email", "reminders", "services"))
        + '</div></div>',
        "<b>Search</b>", "Done."),
    "_cmdTourTask2": (
        '<div id="tasks-modal" class="modal"><div class="modal-content">'
        '<button class="tasks-tab" data-tab="new">n</button><button class="tasks-tab" data-tab="tasks">t</button>'
        f'<textarea id="task-ai-input" {H}></textarea><div class="memory-item" data-idx="0">m</div>'
        '<button id="task-form-save">s</button></div></div><textarea id="message"></textarea>',
        "Describe it in plain words", "That’s Tasks."),
    "_cmdTourResearch": (
        '<div id="research-overlay"><div id="research-pane">r'
        f'<input id="research-query" {H}><div id="research-settings-body">s</div></div></div>',
        "Type the question", "That’s Deep Research"),
    "_cmdTourLibrary": (
        '<div id="doclib-modal"><div class="doclib-modal-content">l'
        f'<button id="doclib-create-btn" {H}>c</button>'
        '<div id="doclib-grid"><div class="doclib-card">d</div></div></div></div>',
        "<b>Create</b>", "Create or import a document"),
    "_cmdDemo": (
        '<div id="sidebar"><button id="sidebar-new-chat-btn">new</button></div>'
        '<button id="model-picker-btn">model</button><div class="mode-toggle">'
        '<button id="mode-chat-btn">chat</button><button id="mode-agent-btn">agent</button></div>'
        f'<button id="web-toggle-btn" {H}>web</button><button id="overflow-plus-btn">+</button>'
        '<textarea id="message"></textarea>',
        "<b>Web search</b>", "That’s the tour."),
}

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const [HARNESS, CASES] = [fs.readFileSync(process.argv[2], 'utf8'), JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const results = {};
  for (const [name, [html, , closing]] of Object.entries(CASES)) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.setContent('<!doctype html><html><body>' + html + '</body></html>');
    await page.addScriptTag({ content: HARNESS });
    await page.evaluate((n) => window.startTour(n), name);
    const out = { texts: [], done: false, errors };
    for (let n = 0; n < 80; n++) {
      await page.waitForTimeout(250);
      const seen = await page.evaluate((closing) => {
        const t = document.getElementById('tour-tooltip');
        return { text: t ? (t.querySelector('.tour-text')?.innerHTML || '') : null,
                 next: !!(t && t.querySelector('[data-act="next"]')),
                 done: window.replies.some((r) => r.startsWith(closing)) };
      }, closing);
      if (seen.done) { out.done = true; break; }
      if (seen.text == null) continue;
      if (out.texts[out.texts.length - 1] !== seen.text) out.texts.push(seen.text);
      if (seen.next) { await page.click('#tour-tooltip [data-act="next"]'); continue; }
      // A step that waits for the person: press what it lights, or type and Enter.
      const lit = await page.evaluate(() => {
        const el = document.querySelector('.pantheon-highlight');
        return el ? el.id : null;
      });
      if (lit === 'message') { await page.fill('#message', 'hello'); await page.press('#message', 'Enter'); }
      else if (lit) await page.click('#' + lit);
    }
    results[name] = out;
    await page.close();
  }
  console.log(JSON.stringify(results));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def walked(tmp_path_factory):
    d = tmp_path_factory.mktemp("tours")
    (d / "harness.js").write_text(_harness(), encoding="utf-8")
    (d / "cases.json").write_text(json.dumps(TOURS), encoding="utf-8")
    (d / "run.cjs").write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(d / "run.cjs"), str(d / "harness.js"), str(d / "cases.json")],
                          capture_output=True, text=True, timeout=420)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@browser
@pytest.mark.parametrize("tour", sorted(TOURS))
def test_a_hidden_step_is_passed_and_the_tour_goes_on_to_its_end(walked, tour):
    """The row's `Verify:` — with one step's target hidden, the tour skips that
    step and goes on: it says its closing line, it never showed the hidden
    step, and it showed the step after it."""
    out = walked[tour]
    _html, hidden, _closing = TOURS[tour]
    assert out["errors"] == [], out["errors"]
    assert out["done"], f"{tour} ended before its closing line: {out['texts']}"
    assert not any(hidden in t for t in out["texts"]), f"{tour} showed the hidden step"
    assert len(out["texts"]) >= 2, out["texts"]


def test_the_file_has_one_step_runner():
    """The other half of the `Verify:`. Every tour draws and walks through
    `_tourSession`; none keeps a step runner, a halo maker or a tooltip of its
    own. Scoped per tour function (`Law 20`), not grepped file-wide."""
    code = blank_text(SLASH, "js")
    tours = re.findall(r"async function (_cmdDemo|_cmdTour\w+|_runTaskTour)\(", code)
    assert len(tours) >= 11, tours
    for name in tours:
        body = js_function(SLASH, f"async function {name}(")
        if name in ("_cmdTourTask1", "_cmdTourTask2"):
            assert "_runTaskTour(" in body, name
            continue
        assert "_tourSession(" in body, f"{name} does not use the one step runner"
        assert ".walk(" in body, f"{name} walks its steps itself"
        for own in ("function _showStep", "function showStep", "function _makeHalo",
                    "function makeHalo", "'tour-styles'", "createElement('div');\n  tooltip.id"):
            assert own not in body, f"{name} still has its own {own!r}"
    runners = re.findall(r"function (?:_?showStep)\(", code)
    assert runners == ["function showStep("], runners
