# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-02` — the Skills window: opened from somewhere, counted truly, sorted and
filtered apart, its settings where its skills are, and two words for two states.

Driven under node against the real `static/js/skills.js` in the real Skills
window and Workbench markup — the harness of
`tests/test_one_skills_module_two_places_js.py` (its shim, its fake server),
imported, not copied (`Law 14`). One neighbour is swapped: `modalManager.js` is
a **fake of C-NAV** (`/work/notes/FIX-WAVES.md`, fx-back builds the real one in
parallel) that records `showWindow(id, { from, tab })`.

What each case measured on `32df791` before the fix is in its docstring.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_one_skills_module_two_places_js import SHIM, STUBS, _markup  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.js_source import js_definition

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_FAKE_NAV = """
export const nav = { shown: [] };
export function setBackgroundWork(){ return false; }
export function isMinimized(){ return false; }
export function restore(){}
export function openClosedWindow(){}
export function showWindow(id, opts = {}){ nav.shown.push({ id, ...opts }); return 'opened'; }
"""


def _nav_specifier() -> str:
    """The specifier `skills.js` reaches the window manager by (node keys a
    module by its whole URL, cache-buster included)."""
    m = re.search(r"import\('(\./modalManager\.js[^']*)'\)", SKILLS_JS.read_text(encoding="utf-8"))
    assert m, "openSkillsWindow no longer imports the window manager"
    return m.group(1)


_PREAMBLE = (
    "import { document, server, fire, tick, $, cards, names } from './shim.js';\n"
    "import { calls } from './ui.js';\n"
    "import { nav } from '__NAV__';\n"
    "if (typeof globalThis.addEventListener !== 'function') {\n"
    "  globalThis.addEventListener = () => {}; globalThis.removeEventListener = () => {};\n"
    "}\n"
    "const skills = await import('./skills.js');\n"
    "fire(document, 'DOMContentLoaded');\n"
    "await tick();\n"
    "const room = skills.mountSkills($('skills-room'));\n"
    "await tick();\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const change = (el, v) => { el.value = v; fire(el, 'change'); };\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    shim = SHIM.replace("__MARKUP__", json.dumps(_markup()))
    stubs = dict(STUBS)
    stubs["modalManager.js"] = _FAKE_NAV
    return _make_sandbox(tmp_path_factory.mktemp("skillsopener"), SKILLS_JS, shim, stubs)


def _go(box, script):
    return _run(box, _PREAMBLE.replace("__NAV__", _nav_specifier()), script)


# ── C-NAV · the opener travels to the window manager ────────────────────────

def test_open_skills_window_passes_its_opener_to_show_window(box):
    """`NAV-U-1`. C-NAV: `openSkillsWindow(view, { from })` passes `from` (and
    the opener's `tab`) through to `showWindow`. On `32df791` it took only a
    view and called `restore` / `openClosedWindow` itself, so nothing could
    ever say `← Brain`. A door inside another window (`[data-open-skills]`)
    names that window as the opener."""
    o = _go(box, """
        await skills.openSkillsWindow('browse', { from: 'memory-modal', tab: 'rag' });
        await skills.openSkillsWindow('add');
        const door = document.createElement('button');
        door.setAttribute('data-open-skills', 'add');
        $('workbench-modal').appendChild(door);
        for (const fn of (document.listeners.click || []).slice()) fn({ type: 'click', target: door });
        await tick();
        out({ shown: nav.shown });
    """)
    assert o["shown"] == [
        {"id": "skills-modal", "from": "memory-modal", "tab": "rag"},
        {"id": "skills-modal"},
        {"id": "skills-modal", "from": "workbench-modal"},
    ]


# ── BRAIN-M-10 / COPY-U-15 · the count beside the heading ───────────────────

def test_the_heading_counts_what_is_on_screen_and_only_when_some_are_hidden(box):
    """`BRAIN-M-10`. On `32df791` `updateCount` wrote `skills.length` whatever
    was shown: "8 skills" over five cards under *Yours*, and over none under a
    filter. Each place says its own."""
    o = _go(box, """
        $('wb-skills-search').value = 'print'; fire($('wb-skills-search'), 'input');
        const searched = [$('skills-count-h2').textContent, $('wb-skills-count-h2').textContent];
        $('wb-skills-search').value = ''; fire($('wb-skills-search'), 'input');
        out({ searched, cleared: [$('skills-count-h2').textContent, $('wb-skills-count-h2').textContent] });
    """)
    assert o["searched"] == ["", "1 of 2"]
    assert o["cleared"] == ["", ""]


# ── BRAIN-U-5 · sort and filter are two controls ────────────────────────────

def test_sort_and_filter_are_two_controls_and_an_emptied_list_says_so(box):
    """`BRAIN-U-5`. On `32df791` one dropdown held both: pick *Confidence ≤ 70%*
    (the list empties), then *A-Z*, and the control read "A-Z" with the filter
    still applied, over "No skills yet. Import a package under Add…" with ten
    skills in the library."""
    o = _go(box, """
        change($('skills-filter'), 'filter:published');
        const filtered = { cards: names('skills-list').length, text: $('skills-list').textContent };
        change($('skills-sort'), 'sort:alpha');
        const sorted = { cards: names('skills-list').length, filter: $('skills-filter').value, sort: $('skills-sort').value };
        const clear = $('skills-list').querySelector('[data-skills-clear-filter]');
        for (const fn of ($('skills-list').listeners.click || [])) fn({ type: 'click', target: clear });
        await tick();
        out({ filtered, sorted, cleared: { cards: names('skills-list').length, filter: $('skills-filter').value },
              hadClear: !!clear,
              sortOptions: $('skills-sort').querySelectorAll('option').map((x) => x.value),
              filterOptions: $('skills-filter').querySelectorAll('option').map((x) => x.textContent.trim()) });
    """)
    assert o["filtered"]["cards"] == 0
    assert "No skills match this filter." in o["filtered"]["text"]
    assert "No skills yet" not in o["filtered"]["text"]
    assert o["hadClear"] is True
    assert o["sorted"] == {"cards": 0, "filter": "filter:published", "sort": "sort:alpha"}
    assert o["cleared"] == {"cards": 2, "filter": "filter:all"}
    assert all(v.startswith("sort:") for v in o["sortOptions"])
    assert o["filterOptions"][:3] == ["All skills", "Drafts only", "Published only"]


# ── BRAIN-U-17 / BRAIN-M-9 · two words, and a fork is not a duplicate ───────

def test_a_draft_reads_draft_and_a_fork_is_not_its_origins_duplicate(box):
    """`BRAIN-U-17`: the pill says *draft* (it said *uncatalogued*, beside
    *active*, *Approve* and *Auto-approve* elsewhere). `BRAIN-M-9`: a fresh
    fork opened branded "duplicate #1 · lower-priority" of its own origin."""
    o = _go(box, """
        const card = (n) => cards('skills-list').find((c) => c.dataset.skillName === n);
        const pills = (n) => (card(n) ? card(n).querySelectorAll('.memory-cat-badge').map((p) => p.textContent.trim()) : null);
        server.skills.push({ name: 'alpha-logs-fork', description: 'tidy the build logs', status: 'draft',
                             confidence: 0.8, version: '1.0.0', body_extra: 'Forked from `alpha-logs`.' });
        await skills.loadSkills(); await tick();
        const fork = pills('alpha-logs-fork'), origin = pills('alpha-logs');
        server.skills.pop();
        server.skills.push({ name: 'alpha-logs-copy', description: 'tidy the build logs', status: 'draft',
                             confidence: 0.8, version: '1.0.0' });
        await skills.loadSkills(); await tick();
        out({ fork, origin, copy: pills('alpha-logs-copy') });
    """)
    assert "draft" in o["origin"]
    assert not any("duplicate" in p for p in o["fork"]), o["fork"]
    assert any("duplicate" in p for p in o["copy"]), "the detector no longer sees a real copy"


# ── BRAIN-U-12 · an open card says the way back ─────────────────────────────

def test_an_open_card_has_a_labelled_way_back_to_the_list(box):
    """`BRAIN-U-12`. An open card hides the toolbar and every other card, and
    the way back was an unlabelled ˄ (Fork and Import land here)."""
    o = _go(box, """
        const c = cards('skills-list')[0];
        fire(c, 'click'); await tick();
        const opened = c.classList.contains('doclib-card-expanded');
        const back = c.querySelector('.skill-back-to-list');
        const label = back && [back.textContent.trim(), back.getAttribute('aria-label'), back.tagName];
        if (back) for (const fn of (back.listeners.click || [])) fn({ type: 'click', target: back, stopPropagation() {} });
        await tick();
        out({ opened, label, closed: !c.classList.contains('doclib-card-expanded') });
    """)
    assert o["opened"] is True
    assert o["label"] == ["← Skills", "Back to the list", "BUTTON"]
    assert o["closed"] is True


# ── BRAIN-U-10 · the skill settings live with the skills ────────────────────

def test_the_skill_settings_are_a_view_of_the_skills_window_and_the_room_mirrors_them(box):
    """`BRAIN-U-10`. The three skill settings stayed in the Brain's Settings
    tab after Skills moved out. They are a third view here; the room's stamped
    copy presses the window's controls (which `memory.js` owns) and shows what
    they say."""
    o = _go(box, """
        const tabs = $('skills-modal').querySelectorAll('[data-skills-view]').map((t) => t.getAttribute('data-skills-view'));
        const wbSettings = $('skills-room').querySelector('[data-skills-view="settings"]');
        fire(wbSettings, 'click');
        const shown = !$('skills-room').querySelector('[data-skills-view-panel="settings"]').classList.contains('hidden');
        const theirs = $('auto-skills-toggle'), mine = $('wb-auto-skills-toggle');
        const writes = [];
        theirs.addEventListener('change', () => writes.push(theirs.checked));
        mine.checked = true; fire(mine, 'change');
        const slider = $('skill-confidence-slider');
        $('skill-confidence-label').textContent = '≥ 90%';
        slider.value = '90'; fire(slider, 'input');
        out({ tabs, shown, writes, followed: theirs.checked,
              label: $('wb-skill-confidence-label').textContent, wbSlider: $('wb-skill-confidence-slider').value,
              inBrain: !!$('memory-modal') });
    """)
    assert o["tabs"] == ["browse", "add", "settings"]
    assert o["shown"] is True
    assert o["writes"] == [True] and o["followed"] is True
    assert o["label"] == "≥ 90%" and o["wbSlider"] == "90"


# ── BRAIN-M-13 · Publish is offered on a pass, not on an unclear verdict ────

_VERDICT_HARNESS = r"""
const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const _applyVerdictToHeader = () => {};
const el = (html) => ({ innerHTML: '', querySelector: () => null, _set(h) { this.innerHTML = h; } });
__FN__
const out = {};
for (const [verdict, status] of [['pass', 'draft'], ['inconclusive', 'draft'], ['fail', 'draft'], ['unknown', 'draft'], ['fail', 'published']]) {
  const box = { innerHTML: '', querySelector: () => null };
  _renderTestVerdict(box, { verdict, confidence: 0.5, summary: 's' }, { dataset: { skillStatus: status } }, 'x');
  const m = /data-act="approve">([^<]*)</.exec(box.innerHTML);
  out[verdict + '/' + status] = m ? m[1] : null;
}
console.log(JSON.stringify(out));
"""


def test_publish_is_offered_on_a_pass_and_unpublish_on_a_published_skill(tmp_path):
    """`BRAIN-M-13`. On `32df791` the verdict *UNCLEAR · 0%* still offered
    **Approve** (and the button said *Approve* / *Approved*, two more words for
    the two states). The function is cut out and run, not read (`Law 20`)."""
    src = SKILLS_JS.read_text(encoding="utf-8")
    fn = js_definition(src, src.index("function _renderTestVerdict("))
    case = tmp_path / "verdict.mjs"
    case.write_text(_VERDICT_HARNESS.replace("__FN__", fn), encoding="utf-8")
    proc = subprocess.run(["node", str(case)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    assert got == {"pass/draft": "Publish", "inconclusive/draft": None, "fail/draft": None,
                   "unknown/draft": None, "fail/published": "Unpublish"}


# ── BRAIN-M-16 · the Workbench reopens on its room; `openWorkbench({ from })` ─

from test_the_workbench_window_js import (  # noqa: E402
    _GLUE_SHIM, _GLUE_STUBS, _UP, _window_tree, JS as _JS, WORKBENCH_JS,
)


@pytest.fixture(scope="module")
def wbglue(tmp_path_factory):
    """`tests/test_the_workbench_window_js.py`'s glue sandbox, with its window
    manager stub given C-NAV's `showWindow` as a recorder."""
    root = tmp_path_factory.mktemp("wbopener")
    (root / "workbench").mkdir()
    shim = _GLUE_SHIM.replace("__TREE__", json.dumps(_window_tree()))
    sandbox = _make_sandbox(root / "workbench", WORKBENCH_JS, shim, {})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(_JS / rel, root / rel)
    stubs = dict(_GLUE_STUBS)
    stubs["modalManager.js"] = stubs["modalManager.js"] + (
        "globalThis.__shown = [];\n"
        "export function showWindow(id, opts) { globalThis.__shown.push({ id, ...(opts || {}) }); return 'raised'; }\n")
    for rel, src in stubs.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(src, encoding="utf-8")
    return sandbox


_WB_PREAMBLE = (
    "import { document, modal, fire, settle, $ } from './shim.js';\n"
    "const wb = await import('./workbench.js');\n"
    "const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };\n"
)


def test_the_workbench_reopens_on_the_room_it_was_closed_on(wbglue):
    """`BRAIN-M-16`. Measured on `32df791`: closed on Skills, reopened on
    Automations (`_open && _current` was cleared by the close). A door that
    names a room still wins."""
    o = _run(wbglue, _WB_PREAMBLE, """
        wb.openWorkbench({}); await settle(5);
        fire($('workbench-room-tab-integrations'), 'click'); await settle(5);
        const before = wb.currentRoom();
        wb.closeWorkbench(); await settle(300);
        wb.openWorkbench({}); await settle(5);
        const reopened = wb.currentRoom();
        wb.closeWorkbench(); await settle(300);
        wb.openWorkbench({ room: 'automations' }); await settle(5);
        out({ before, reopened, asked: wb.currentRoom() });
    """)
    assert o == {"before": "integrations", "reopened": "integrations", "asked": "automations"}


def test_open_workbench_passes_its_opener_once_the_window_is_up(wbglue):
    """C-NAV: `openWorkbench({ room, from })` passes `from` (and `tab`) to
    `showWindow` — after the window is shown, so the manager's "raise" case is
    the one taken and the window's own door is never pressed back into here."""
    o = _run(wbglue, _WB_PREAMBLE, """
        wb.openWorkbench({ from: 'settings-modal', tab: 'integrations' }); await settle(5);
        wb.openWorkbench({}); await settle(5);
        out({ shown: globalThis.__shown, hidden: modal._classes().includes('hidden') });
    """)
    assert o["shown"] == [{"id": "workbench-modal", "from": "settings-modal", "tab": "integrations"}]
    assert o["hidden"] is False
