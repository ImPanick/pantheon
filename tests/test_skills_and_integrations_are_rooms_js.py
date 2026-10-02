# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-21` — Skills and MCP & Integrations are Workbench rooms, and rooms are not destroyed.

Contract C-R (design § 3 C): `openWorkbench({room, view?, skill?, serverId?,
…today's})`, `ROOMS` entries `{id, label, panel, mount?}`, and
`#workbench-room-integrations` holding `#unified-intg-form`.

Driven, in the window test's glue harness (`test_the_workbench_window_js.py`):
the real `workbench/workbench.js`, the real Automations room (`workflowRoom.js`,
canvas and all, with the task form stubbed to its contract), and the window's
DOM rebuilt from `static/index.html`'s own `#workbench-modal` block. The two
modules the new rooms load on first show are recorded stand-ins: `skills.js`
(whose real mount is driven in `test_one_skills_module_two_places_js.py`) and
`settings.js` (its `initUnifiedIntegrations` draws one MCP card, as the real
list does). `escMenuStack.js` is the real one — the Escape cases ask it what
`ui.js`'s arbiter asks (`dismissTopMenu`). `MutationObserver` is the browser's;
here it is one the case fires by hand.

And Settings' half: `settings.js`'s `open` and `_openIntegrationsRoom`, cut out
of the shipped file and run with the Workbench recorded — `open('integrations')`
opens the room, and opens Settings' door card only when Settings is on screen.

Proven:
  * three tabs from `ROOMS`, each naming its panel; Left/Right/Home/End move
    between them and the room follows the focus;
  * an unsaved Automations step form survives Skills → Automations — same
    nodes, no second mount, nothing fetched again;
  * every door lands: `room` + `view` + `skill` on Skills, `serverId` on
    Integrations, a workflow door on Automations from wherever the window was;
  * Escape: with the integration form open it closes the form, not the window;
    with an Automations layer left open in a hidden room it closes the window
    (which asks about unsaved work), not the invisible layer; back in
    Automations it closes the layer again;
  * the markup: the Integrations card's ids exist once, inside the room;
    Settings keeps a door; the Skills window is still its own window.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _DOM, _make_sandbox, _run  # noqa: E402
from test_the_workbench_window_js import (  # noqa: E402
    _GLUE_SHIM, _GLUE_STUBS, _UP, _window_tree,
)
from tests.helpers.js_source import js_definition  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
WORKBENCH_JS = JS / "workbench" / "workbench.js"
SETTINGS_JS = JS / "settings.js"
INDEX = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_ROOM_STUBS = dict(_GLUE_STUBS)
_ROOM_STUBS["skills.js"] = (
    "globalThis.__skills = { mounts: [], calls: [] };\n"
    "export function mountSkills(host, want) {\n"
    "  globalThis.__skills.mounts.push({ host: host.id, want });\n"
    "  return { shown() { globalThis.__skills.calls.push(['shown']); return Promise.resolve(); },\n"
    "    showView(v) { globalThis.__skills.calls.push(['view', v]); },\n"
    "    focusSkill(n) { globalThis.__skills.calls.push(['skill', n]); } };\n"
    "}\n"
)
_ROOM_STUBS["settings.js"] = (
    "globalThis.__settings = { inits: 0, clicked: null };\n"
    "export default { initUnifiedIntegrations() {\n"
    "  globalThis.__settings.inits += 1;\n"
    "  if (globalThis.__settings.inits > 1) return Promise.resolve();\n"
    "  const card = document.createElement('div');\n"
    "  card.className = 'intg-card'; card.dataset.intgType = 'mcp'; card.dataset.intgId = 'srv-1';\n"
    "  card.addEventListener('click', () => { globalThis.__settings.clicked = 'srv-1'; });\n"
    "  document.getElementById('unified-integrations-list').appendChild(card);\n"
    "  return Promise.resolve(); } };\n"
)


@pytest.fixture(scope="module")
def glue(tmp_path_factory):
    root = tmp_path_factory.mktemp("wbrooms")
    (root / "workbench").mkdir()
    shim = _GLUE_SHIM.replace("__TREE__", json.dumps(_window_tree()))
    sandbox = _make_sandbox(root / "workbench", WORKBENCH_JS, shim, {})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    for rel, src in _ROOM_STUBS.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(src, encoding="utf-8")
    return sandbox


_PREAMBLE = (
    "globalThis.__keydown = [];\n"
    "globalThis.addEventListener = (type, fn, capture) => { if (type === 'keydown' && capture) globalThis.__keydown.push(fn); };\n"
    "globalThis.__observers = [];\n"
    "globalThis.MutationObserver = class { constructor(fn) { this.fn = fn; globalThis.__observers.push(this); }\n"
    "  observe(t) { this.t = t; } disconnect() {} };\n"
    "import { document, modal, server, fire, settle, $, Node } from './shim.js';\n"
    "// The browser's `HTMLElement.click()`; the shim has none.\n"
    "Node.prototype.click = function click() { this.dispatchEvent({ type: 'click', target: this,\n"
    "  currentTarget: this, preventDefault() {}, stopPropagation() {} }); };\n"
    "import { dismissTopMenu, registerMenuDismiss } from '../escMenuStack.js';\n"
    "const wb = await import('./workbench.js');\n"
    "const mutate = () => globalThis.__observers.forEach((o) => o.fn([]));\n"
    "const shown = () => ['workbench-room', 'workbench-room-skills', 'workbench-room-integrations']\n"
    "  .filter((id) => !$(id).hidden);\n"
    "const tab = (id) => $('workbench-room-tab-' + id);\n"
    "const key = (id, k) => tab(id).dispatchEvent({ type: 'keydown', key: k, preventDefault() {} });\n"
    "const nodeOf = (id) => $('workbench-room').querySelectorAll('.wb-node').find((n) => n.dataset.taskId === id);\n"
    "const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };\n"
)


def test_three_rooms_each_naming_its_panel_and_the_keys_move_between_them(glue):
    o = _run(glue, _PREAMBLE, """
        wb.openWorkbench({});
        await settle(5);
        const rooms = wb.ROOMS.map((r) => ({ id: r.id, label: r.label, panel: r.panel, mount: typeof r.mount }));
        const walk = [shown()];
        key('automations', 'ArrowRight'); await settle(2); walk.push(shown());
        key('skills', 'ArrowRight'); await settle(2); walk.push(shown());
        key('integrations', 'ArrowRight'); await settle(2); walk.push(shown());
        key('automations', 'ArrowLeft'); await settle(2); walk.push(shown());
        key('integrations', 'Home'); await settle(2); walk.push(shown());
        key('automations', 'End'); await settle(2); walk.push(shown());
        out({ rooms, walk, focused: tab('integrations').focused,
              selected: ['automations', 'skills', 'integrations'].map((id) => tab(id).getAttribute('aria-selected')),
              labelled: $('workbench-room-integrations').getAttribute('aria-labelledby'),
              current: wb.currentRoom() });
    """)
    assert o["rooms"] == [
        {"id": "automations", "label": "Automations", "panel": "workbench-room", "mount": "function"},
        {"id": "skills", "label": "Skills", "panel": "workbench-room-skills", "mount": "function"},
        {"id": "integrations", "label": "MCP & Integrations", "panel": "workbench-room-integrations",
         "mount": "function"},
    ]
    a, s, i = ["workbench-room"], ["workbench-room-skills"], ["workbench-room-integrations"]
    assert o["walk"] == [a, s, i, a, i, a, i]
    assert o["focused"] is True and o["selected"] == ["false", "false", "true"]
    assert o["labelled"] == "workbench-room-tab-integrations" and o["current"] == "integrations"


def test_an_unsaved_step_form_survives_skills_and_back(glue):
    """Design § 0.7: every switch used to `replaceChildren()` the one host, so
    going to Skills took an unsaved Automations draft with it."""
    o = _run(glue, _PREAMBLE, """
        wb.openWorkbench({});
        await settle(5);
        fire(nodeOf('a'), 'click');
        const form = globalThis.__fields[0];
        const panelHost = $('workbench-room').querySelector('.wb-panel-host');
        const reads = server.calls.length;
        fire(tab('skills'), 'click'); await settle(5);
        const away = { automationsHidden: $('workbench-room').hidden, destroyed: form.destroyed };
        fire(tab('automations'), 'click'); await settle(5);
        out({ away, back: { destroyed: form.destroyed, forms: globalThis.__fields.length,
              sameHost: $('workbench-room').querySelector('.wb-panel-host') === panelHost,
              refetched: server.calls.length - reads, shown: shown() },
              skillsMounted: globalThis.__skills.mounts });
    """)
    assert o["away"] == {"automationsHidden": True, "destroyed": False}
    assert o["back"] == {"destroyed": False, "forms": 1, "sameHost": True, "refetched": 0,
                         "shown": ["workbench-room"]}
    assert o["skillsMounted"] == [{"host": "skills-room", "want": {"view": None, "skill": None}}]


def test_every_door_lands_in_its_room(glue):
    o = _run(glue, _PREAMBLE, """
        wb.openWorkbench({ room: 'skills', view: 'add', skill: 'clear-print-queue' });
        await settle(5);
        const first = { shown: shown(), mounts: globalThis.__skills.mounts.slice() };
        wb.openWorkbench({ room: 'skills', view: 'browse', skill: 'tidy-logs' });
        await settle(5);
        const again = globalThis.__skills.calls.slice();
        wb.openWorkbench({ room: 'integrations', serverId: 'srv-1' });
        await settle(10);
        const intg = { shown: shown(), inits: globalThis.__settings.inits, clicked: globalThis.__settings.clicked,
                       formHere: !!$('workbench-room-integrations').querySelector('#unified-intg-form') };
        wb.openWorkbench({ workflowId: 'w-1' });
        await settle(5);
        const toAutomations = shown();
        wb.openWorkbench({});
        const stays = shown();
        out({ first, again, intg, toAutomations, stays });
    """)
    assert o["first"]["shown"] == ["workbench-room-skills"]
    assert o["first"]["mounts"] == [{"host": "skills-room",
                                     "want": {"view": "add", "skill": "clear-print-queue"}}]
    assert o["again"] == [["view", "browse"], ["skill", "tidy-logs"]], "an open room is landed, not remounted"
    assert o["intg"] == {"shown": ["workbench-room-integrations"], "inits": 1, "clicked": "srv-1",
                         "formHere": True}
    assert o["toAutomations"] == ["workbench-room"]
    assert o["stays"] == ["workbench-room"], "a door with no room moved an open window"


def test_escape_closes_the_integration_form_before_the_window(glue):
    o = _run(glue, _PREAMBLE, """
        wb.openWorkbench({ room: 'integrations' });
        await settle(5);
        const form = $('unified-intg-form');
        form.appendChild(document.createElement('div'));
        form.style.display = 'block';
        mutate();
        const marked = $('workbench-room-integrations').dataset.escLayer;
        const took = dismissTopMenu();
        out({ marked, took, formShut: form.style.display, emptied: form.childNodes.length,
              open: wb.isWorkbenchOpen(), unmarked: $('workbench-room-integrations').dataset.escLayer || null });
    """)
    assert o == {"marked": "open", "took": True, "formShut": "none", "emptied": 0,
                 "open": True, "unmarked": None}


def test_escape_never_closes_a_layer_in_a_room_nobody_can_see(glue):
    o = _run(glue, _PREAMBLE, """
        wb.openWorkbench({});
        await settle(5);
        fire(nodeOf('a'), 'click');                 // the step panel: a layer on the stack
        await settle(2);
        const panelOpen = () => !!$('workbench-room').querySelector('.wb-panel:not(.hidden)')
          || !!$('workbench-room').querySelector('.wb-panel-host');
        fire(tab('skills'), 'click'); await settle(5);
        const guard = $('workbench-room-skills').dataset.escLayer;
        // Back to Automations: its own layer is on top again.
        fire(tab('automations'), 'click'); await settle(5);
        const unguarded = $('workbench-room-skills').dataset.escLayer || null;
        const first = dismissTopMenu();
        const afterBack = { open: wb.isWorkbenchOpen(), form: globalThis.__fields[0].destroyed };
        // Again, but Escape while on Skills.
        fire(nodeOf('a'), 'click'); await settle(2);
        fire(tab('skills'), 'click'); await settle(5);
        dismissTopMenu();
        await settle(300);
        out({ guard, unguarded, first, afterBack,
              closed: { open: wb.isWorkbenchOpen(), hidden: modal._classes().includes('hidden') } });
    """)
    assert o["guard"] == "guard" and o["unguarded"] is None
    assert o["first"] is True and o["afterBack"]["open"] is True, \
        "back in Automations, Escape closed the window instead of its own step panel"
    assert o["closed"] == {"open": False, "hidden": True}, \
        "on Skills, Escape spent itself on the hidden step panel and the window stayed"


def test_escape_over_a_rooms_menu_closes_the_menu_not_the_window(glue):
    """A skill's ⋯ and *Add Integration*'s list are drawn on `<body>` and sit on
    the Escape stack; the arbiter only asks the stack first for a window marked
    `data-esc-layer`. Measured in the drive before this: one Escape over an open
    *Add Integration* menu closed the whole Workbench."""
    o = _run(glue, _PREAMBLE, """
        wb.openWorkbench({ room: 'integrations' });
        await settle(5);
        const press = () => globalThis.__keydown.forEach((fn) => fn({ key: 'Escape' }));
        press();
        const idle = $('workbench-room-integrations').dataset.escLayer || null;
        let menus = 0;
        registerMenuDismiss(() => { menus += 1; });     // what bindMenuDismiss does for a menu
        press();
        const marked = $('workbench-room-integrations').dataset.escLayer || null;
        // What `ui.js`'s arbiter asks next, for the window under the pointer:
        const asked = !!modal.querySelector('[data-esc-layer]') && dismissTopMenu();
        await settle(5);
        out({ idle, marked, asked, menus, open: wb.isWorkbenchOpen(),
              after: $('workbench-room-integrations').dataset.escLayer || null });
    """)
    assert o == {"idle": None, "marked": "menu", "asked": True, "menus": 1, "open": True, "after": None}


# ── Settings' half: open('integrations') is the room ─────────────────────────

def _settings_case(tmp_path, shown: bool) -> dict:
    src = SETTINGS_JS.read_text(encoding="utf-8")
    cut = "\n".join(js_definition(src, src.index(sig)) for sig in (
        "function _openIntegrationsRoom(", "export function open(tab) {"))
    cut = cut.replace("export function open(", "function open(")
    (tmp_path / "workbench").mkdir()
    (tmp_path / "workbench" / "workbench.js").write_text(
        "globalThis.__opened = [];\nexport function openWorkbench(o) { globalThis.__opened.push(o); return true; }\n")
    (tmp_path / "dom.js").write_text(_DOM)
    case = """
import { installDom } from './dom.js';
const document = installDom();
const seen = { inits: 0, activated: [], shownSettings: 0 };
let initialized = false;
let modalEl = document.body.appendChild(document.createElement('div'));
modalEl.setAttribute('id', 'settings-modal');
modalEl.className = %(cls)s;
const uiModule = { showError: (m) => { throw new Error(m); } };
function initAll() { seen.inits += 1; initialized = true; }
function syncAppearanceCheckboxes() {}
function showSettingsModal() { seen.shownSettings += 1; }
function syncAdminVisibility() {}
function activateSettingsPanel(m, tab) { seen.activated.push(tab); }
function getActiveSettingsTab() { return 'integrations'; }
function onSettingsPanelActivated() {}
function isAdminManagedSettingsTab() { return false; }
%(cut)s
open('integrations');
await new Promise((r) => setTimeout(r, 20));
console.log(JSON.stringify({ ...seen, opened: globalThis.__opened }));
""" % {"cls": json.dumps("modal" if shown else "modal hidden"), "cut": cut}
    (tmp_path / "case.mjs").write_text(case)
    proc = subprocess.run(["node", str(tmp_path / "case.mjs")], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_open_integrations_opens_the_room_and_not_settings(tmp_path):
    """The Email panel's *Manage in Integrations*, the Google sign-in's return and
    a calendar link all reach `open('integrations')`."""
    o = _settings_case(tmp_path, shown=False)
    assert o["opened"] == [{"room": "integrations"}]
    assert o["shownSettings"] == 0 and o["inits"] == 0 and o["activated"] == []


def test_the_settings_nav_entry_opens_the_room_and_shows_its_door(tmp_path):
    o = _settings_case(tmp_path, shown=True)
    assert o["opened"] == [{"room": "integrations"}]
    assert o["activated"] == ["integrations"], "the nav did not say where the person is"


# ── the markup ──────────────────────────────────────────────────────────────

def test_the_integrations_card_moved_with_its_ids_and_settings_keeps_a_door():
    html = INDEX.read_text(encoding="utf-8")
    room = html[html.index('id="workbench-room-integrations"'):html.index("<!-- Theme Popup (floating panel) -->")]
    panel_at = html.index('<div data-settings-panel="integrations"')
    settings = html[panel_at:html.index("<!-- ═══ TOOLS TAB ═══ -->", panel_at)]
    for control in ("unified-integrations-list", "unified-intg-form", "unified-intg-add-btn"):
        assert html.count(f'id="{control}"') == 1, control
        assert f'id="{control}"' in room, f"{control} is not in the room"
        assert f'id="{control}"' not in settings, f"{control} is still in Settings"
    assert 'id="settings-open-integrations-room"' in settings
    assert "MCP servers, APIs, mail and calendars — what Pantheon connects to." in room


def test_the_skills_window_is_still_a_window_and_the_room_is_beside_it():
    """`D-2026-10-02-02` §2 kept the window (the design had recommended retiring
    it): `#skills-modal` and its ids stay, and the room is an empty host the
    module stamps."""
    html = INDEX.read_text(encoding="utf-8")
    assert html.count('<div id="skills-modal" class="modal hidden">') == 1
    assert html.count('id="skills-list"') == 1
    host = re.search(r'<div id="skills-room"[^>]*></div>', html)
    assert host, "the Skills room's host is not an empty element"
    wb = html[html.index('<div id="workbench-modal"'):html.index("<!-- Theme Popup (floating panel) -->")]
    assert 'id="skills-room"' in wb
