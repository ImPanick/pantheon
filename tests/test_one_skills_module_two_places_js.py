# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-21`, `D-2026-10-02-02` §2 — one Skills module, mounted in two places at once.

The owner kept the Skills window and asked for a Skills room in the Workbench
that **mounts the same module** — not a copy of its code (`Law 7`). So
`static/js/skills.js` now draws into *mounts*: the window's (its ids are the
page's own) and the room's (the window's markup stamped into `#skills-room`,
every id prefixed `wb-`).

Driven here, not read (`Law 20`): the real `skills.js`, against the real
`#skills-modal` and `#workbench-modal` blocks of `static/index.html` parsed
into the shared DOM shim (`installHtmlParsing`, `P22-03`'s opt-in layer, so the
cards `renderSkillsList` writes as markup are real nodes), with a fake server
that keeps state, so an edit made through one place is what the other place
reads back. Proven:

  * the window and the room are on the page together and no id is declared
    twice;
  * both draw the one store;
  * each place keeps its own search, scope and selection;
  * a change made in the window is drawn in the room, and one made in the room
    is drawn in the window;
  * the room's *skills enabled* switch is the window's switch, not a second
    writer.

The browser has `cloneNode`; the shim does not, so the shim gets one.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"
INDEX = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _markup() -> str:
    """The Skills window and the Workbench window, as shipped."""
    html = INDEX.read_text(encoding="utf-8")
    start = html.index('<div id="skills-modal"')
    end = html.index("<!-- Theme Popup (floating panel) -->")
    block = html[start:end]
    assert '<div id="workbench-modal"' in block and 'id="skills-room"' in block
    return block


STUBS = {
    "ui.js": ui_default_stub(
        "showToast: (m) => calls.toasts.push(String(m)), showError: (m) => calls.errors.push(String(m)),"
        " styledConfirm: async () => true, styledPrompt: async () => 'Ops', copyToClipboard: () => {},",
        before="export const calls = { toasts: [], errors: [] };",
    ),
    "spinner.js": ("export function createWhirlpool(){ return { element: { style: {} }, destroy(){} }; }\n"
                   "export default { createWhirlpool: () => ({ element: { style: {} }, destroy(){} }) };\n"),
    "escMenuStack.js": "export function bindMenuDismiss(){ return () => {}; }\nexport function dismissOrRemove(){}\n",
    "toolWindowZOrder.js": "export function topPortalZ(){ return 1; }\n",
    "windowDrag.js": "export function makeWindowDraggable(){}\n",
    "modalManager.js": ("export function setBackgroundWork(){ return false; }\n"
                        "export function isMinimized(){ return false; }\nexport function restore(){}\n"
                        "export function openClosedWindow(){}\n"),
}

SHIM = r"""
import { installDom, installHtmlParsing, Node } from './dom.js';
export const document = installDom();
installHtmlParsing();
globalThis.matchMedia = () => ({ matches: false });
globalThis.getComputedStyle = () => ({});
globalThis.CSS = { escape: (s) => String(s) };
// The browser has these; the shim does not. `removeAttribute` ends a busy
// button's `aria-busy`; `cloneNode` is how `_stampRoom` copies the markup.
if (!Node.prototype.removeAttribute) Node.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
Node.prototype.cloneNode = function cloneNode(deep) {
  const tag = this.tagName === '#TEXT' ? '#text' : this.tagName.toLowerCase();
  const n = tag === '#text' ? new Node('#text') : document.createElement(tag);
  for (const [k, v] of Object.entries(this.attrs)) n.setAttribute(k, v);
  for (const k of ['id', 'className', 'value', 'hidden', 'disabled', 'type', 'title', 'placeholder', 'checked'])
    if (this[k] !== undefined) n[k] = this[k];
  Object.assign(n.dataset, this.dataset);
  for (const [k, v] of Object.entries(this.style)) if (typeof v !== 'function') n.style[k] = v;
  n._text = this._text; n._html = this._html;
  if (deep) for (const c of this.childNodes) n.appendChild(c.cloneNode(true));
  return n;
};
document.body.innerHTML = __MARKUP__;

export const server = {
  calls: [],
  skills: [
    { name: 'alpha-logs', description: 'tidy the build logs', status: 'draft', confidence: 0.8, version: '1.0.0' },
    { name: 'beta-print', description: 'clear the print queue', status: 'draft', confidence: 0.8, version: '1.0.0' },
  ],
  collections: { packages: [], groups: [{ id: 'ops', title: 'Ops', enabled: true, skills: ['alpha-logs'] }], off: {} },
};
globalThis.fetch = async (url, init = {}) => {
  const u = String(url).replace('http://test.local', '');
  const method = init.method || 'GET';
  const body = init.body ? JSON.parse(init.body) : null;
  server.calls.push({ url: u, method, body });
  const ok = (b) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(b)) });
  if (u === '/api/skills' && method === 'GET') return ok({ skills: server.skills, count: server.skills.length });
  if (u === '/api/skills/collections') return ok(server.collections);
  if (u === '/api/skills/builtin') return { ok: false, status: 403, json: async () => ({}) };
  if (u === '/api/skills/audit-all/status') return ok({ status: 'none' });
  if (u === '/api/skills/lint') return ok({ findings: [], counts: { problem: 0, advisory: 0 } });
  if (u === '/api/skills/add' && method === 'POST') {
    server.skills.push({ name: body.name, description: body.description, status: 'draft', confidence: 0.8, version: '1.0.0' });
    return ok({ ok: true, skill: { name: body.name } });
  }
  const one = /^\/api\/skills\/([^/]+)$/.exec(u);
  if (one && method === 'PUT') {
    Object.assign(server.skills.find((s) => s.name === decodeURIComponent(one[1])), body);
    return ok({ ok: true });
  }
  return ok({});
};
export const fire = (node, type) => node.dispatchEvent({ type, target: node, currentTarget: node,
  stopPropagation() {}, preventDefault() {} });
export const tick = async (n = 12) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0)); };
export const $ = (id) => document.getElementById(id);
export const cards = (listId) => ($(listId) ? $(listId).querySelectorAll('.skill-card') : []);
export const names = (listId) => cards(listId).map((c) => c.dataset.skillName);
export function allIds() {
  const out = [];
  const walk = (n) => { if (n.id) out.push(n.id); for (const c of n.childNodes || []) walk(c); };
  walk(document.body);
  return out;
}
"""

PREAMBLE = (
    "import { document, server, fire, tick, $, cards, names, allIds } from './shim.js';\n"
    "import { calls } from './ui.js';\n"
    "const skills = await import('./skills.js');\n"
    "fire(document, 'DOMContentLoaded');\n"
    "await tick();\n"
    "const room = skills.mountSkills($('skills-room'));\n"
    "await tick();\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    shim = SHIM.replace("__MARKUP__", json.dumps(_markup()))
    return _make_sandbox(tmp_path_factory.mktemp("twoplaces"), SKILLS_JS, shim, STUBS)


def test_the_window_and_the_room_are_on_the_page_together_and_no_id_is_declared_twice(box):
    o = _run(box, PREAMBLE, """
        const ids = allIds();
        const roomIds = [];
        const walk = (n) => { if (n.id) roomIds.push(n.id); for (const c of n.childNodes || []) walk(c); };
        for (const c of $('skills-room').childNodes) walk(c);
        const windowBody = $('skills-modal').querySelector('.skills-modal-body');
        const windowIds = [];
        const walk2 = (n) => { if (n.id) windowIds.push(n.id); for (const c of n.childNodes || []) walk2(c); };
        for (const c of windowBody.childNodes) walk2(c);
        out({ dupes: ids.filter((id, i) => ids.indexOf(id) !== i), room: !!room,
              roomIds, windowIds, both: [!!$('skills-list'), !!$('wb-skills-list')] });
    """)
    assert o["room"] is True
    assert o["dupes"] == [], "an id is declared twice"
    assert o["both"] == [True, True]
    assert o["roomIds"] == ["wb-" + i for i in o["windowIds"]], "the room is not the window's markup"
    assert "wb-add-skill-btn" in o["roomIds"] and "wb-skill-draft-btn" in o["roomIds"]


def test_both_places_draw_the_one_store(box):
    o = _run(box, PREAMBLE, """
        out({ win: names('skills-list'), room: names('wb-skills-list'),
              counts: [$('skills-count-h2').textContent, $('wb-skills-count-h2').textContent],
              sides: [$('skills-side').children.length > 0, $('wb-skills-side').children.length > 0] });
    """)
    assert sorted(o["win"]) == sorted(o["room"]) == ["alpha-logs", "beta-print"]
    # `P23-02` (`COPY-U-15`, `BRAIN-M-10`): the header beside "Skills" is bare
    # when everything is shown — the count is said once, on the Brain's door —
    # and says "N of M" only when something hides some.
    assert o["counts"] == ["", ""]
    assert o["sides"] == [True, True]


def test_each_place_keeps_its_own_search_scope_and_selection(box):
    o = _run(box, PREAMBLE, """
        $('wb-skills-search').value = 'print';
        fire($('wb-skills-search'), 'input');
        const searched = { win: names('skills-list'), room: names('wb-skills-list') };
        $('wb-skills-search').value = '';
        fire($('wb-skills-search'), 'input');
        const ops = $('wb-skills-side').querySelectorAll('.skills-side-row')
          .find((r) => r.textContent.startsWith('Ops'));
        fire(ops.querySelector('.skills-side-pick'), 'click');
        const scoped = { win: names('skills-list'), room: names('wb-skills-list'),
          active: [$('skills-side'), $('wb-skills-side')].map((side) => side.querySelectorAll('.skills-side-row')
            .filter((r) => r.className.includes('is-active')).map((r) => r.textContent.replace(/\d+$/, ''))) };
        fire($('wb-skills-select-btn'), 'click');
        const selecting = { room: $('wb-skills-bulk-bar').classList.contains('hidden'),
                            win: $('skills-bulk-bar').classList.contains('hidden'),
                            roomBoxes: $('wb-skills-list').querySelectorAll('.skill-select-cb').length,
                            winBoxes: $('skills-list').querySelectorAll('.skill-select-cb').length };
        fire($('skills-room').querySelector('[data-skills-view="add"]'), 'click');
        const addShown = {
          room: !$('skills-room').querySelector('[data-skills-view-panel="add"]').classList.contains('hidden'),
          win: !$('skills-modal').querySelector('[data-skills-view-panel="add"]').classList.contains('hidden') };
        out({ searched, scoped, selecting, addShown });
    """)
    assert o["searched"] == {"win": ["alpha-logs", "beta-print"], "room": ["beta-print"]}
    assert sorted(o["scoped"]["win"]) == ["alpha-logs", "beta-print"] and o["scoped"]["room"] == ["alpha-logs"]
    assert o["scoped"]["active"] == [["All skills"], ["Ops"]]
    assert o["selecting"] == {"room": False, "win": True, "roomBoxes": 1, "winBoxes": 0}
    assert o["addShown"] == {"room": True, "win": False}


def test_a_change_made_in_the_window_is_drawn_in_the_room(box):
    o = _run(box, PREAMBLE, """
        const card = cards('skills-list').find((c) => c.dataset.skillName === 'beta-print');
        const publish = card.querySelectorAll('.doclib-card-action-btn').find((b) => b.textContent.includes('Publish'));
        fire(publish, 'click');
        await tick(30);
        const roomCard = cards('wb-skills-list').find((c) => c.dataset.skillName === 'beta-print');
        out({ put: server.calls.filter((c) => c.method === 'PUT').map((c) => [c.url, c.body]),
              room: roomCard.dataset.skillStatus,
              pill: roomCard.querySelector('.skill-status-pill').textContent });
    """)
    assert o["put"] == [["/api/skills/beta-print", {"status": "published"}]]
    assert o["room"] == "published" and o["pill"] == "published"


def test_a_skill_added_in_the_room_appears_in_the_window_and_the_windows_form_is_untouched(box):
    o = _run(box, PREAMBLE, """
        $('new-skill-name').value = 'half-typed-in-the-window';
        $('wb-new-skill-name').value = 'gamma-spooler';
        $('wb-new-skill-description').value = 'restart the print spooler';
        fire($('wb-add-skill-btn'), 'click');
        await tick(30);
        out({ post: server.calls.find((c) => c.url === '/api/skills/add').body.name,
              win: names('skills-list'), room: names('wb-skills-list'),
              roomForm: $('wb-new-skill-name').value, winForm: $('new-skill-name').value,
              counts: [$('skills-count-h2').textContent, $('wb-skills-count-h2').textContent] });
    """)
    assert o["post"] == "gamma-spooler"
    assert "gamma-spooler" in o["win"] and "gamma-spooler" in o["room"]
    assert o["roomForm"] == "" and o["winForm"] == "half-typed-in-the-window"
    assert o["counts"] == ["", ""]   # `P23-02`: nothing hidden, nothing said


def test_the_rooms_skills_switch_is_the_windows_switch(box):
    """`memory.js` owns `#skills-enabled-header-toggle` (it reads and writes
    `skills_enabled`); the room's copy must move it, not write the pref itself."""
    o = _run(box, PREAMBLE, """
        const theirs = $('skills-enabled-header-toggle'), mine = $('wb-skills-enabled-header-toggle');
        const writes = [];
        theirs.addEventListener('change', () => writes.push(theirs.checked));   // memory.js's handler
        theirs.checked = true; fire(theirs, 'change');
        const followed = mine.checked;
        mine.checked = false; fire(mine, 'change');
        out({ followed, theirs: theirs.checked, writes,
              dimmed: $('wb-skills-list').style.opacity,
              prefCalls: server.calls.filter((c) => c.url.includes('/api/prefs/')).length });
    """)
    assert o["followed"] is True
    assert o["theirs"] is False and o["writes"] == [True, False]
    assert o["dimmed"] == "0.4"   # `P23-02` (`BRAIN-U-11`): the list, not its toolbar
    assert o["prefCalls"] == 0, "the room wrote the preference itself"
