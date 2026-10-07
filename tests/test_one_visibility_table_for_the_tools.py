# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-03` — one visibility table for the Tools (contract C-VIS).

The owner's rule: a tool switched off for everyone, for one person, or in one
browser disappears from **Tools** on the main screen and from every other door,
and comes back when switched on. Measured on `9560d50` (audit SET-M-1…5, 9, 12,
15): a privilege hid the sidebar row and left its rail twin; `/gallery` typed
or linked opened a Gallery its admin had switched off, to a window of 403s;
any Appearance flip brought a privilege-hidden tool back; the Web chip came
back on every mode change; Memory and RAG switched off hid nothing; nothing
applied on the admin's own page until a reload.

Driven, not read (`Law 20`): `static/js/ui_visibility.js` is imported under
node and run against a small DOM; the doors that live in other modules
(`_cmdOpen`, the palette's `_toolEntries`, `applyModeToToggles`, the mode
toggle) are cut out of their files with `tests/helpers/js_source` and run with
the real table beside them; the server's sentence is produced by the real
`require_feature` guard.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
UI_VIS = ROOT / "static" / "js" / "ui_visibility.js"
APP_JS = ROOT / "static" / "app.js"
SLASH_JS = ROOT / "static" / "js" / "slashCommands.js"
PALETTE_JS = ROOT / "static" / "js" / "search-chat.js"
AUTOCOMPLETE_JS = ROOT / "static" / "js" / "slashAutocomplete.js"

NODE = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
pytestmark = NODE

# A small DOM: every door the table names, as nodes with an inline style, a
# parent chain for the click guard, and a window that keeps its listeners.
_DOM = r"""
const nodes = {};
export function node(id, parent = null) {
  const n = { id, style: { display: '' }, parentNode: parent, clicked: 0 };
  n.click = () => click(n);
  nodes[id] = n;
  return n;
}
export const document = { getElementById: (id) => nodes[id] || null };
export const listeners = [];
export const toasts = [];
globalThis.window = {
  addEventListener: (type, fn, capture) => listeners.push({ type, fn, capture }),
  uiModule: { showToast: (m) => toasts.push(String(m)) },
};
export function click(target) {
  const ev = { target, stopped: false, prevented: false,
    stopImmediatePropagation() { this.stopped = true; },
    preventDefault() { this.prevented = true; } };
  for (const l of listeners) if (l.type === 'click' && l.capture) l.fn(ev);
  if (!ev.stopped) target.clicked += 1;
  return ev;
}
export function shown(id) { return nodes[id].style.display !== 'none'; }
export { nodes };
"""

_DOOR_IDS = [
    "tool-gallery-btn", "rail-gallery", "tool-memory-btn", "rail-memory",
    "tool-cookbook-btn", "rail-cookbook", "tool-research-btn", "rail-research",
    "research-toggle-btn", "web-toggle-btn", "overflow-doc-btn", "doc-indicator-btn",
    "rail-documents", "tool-library-btn", "rail-archive", "overflow-rag-btn",
    "rag-indicator-btn", "bash-toggle-btn", "mode-agent-btn", "tool-calendar-btn",
    "rail-calendar",
]


def _node(tmp_path: Path, script: str) -> dict:
    (tmp_path / "dom.mjs").write_text(_DOM)
    entry = tmp_path / "case.mjs"
    entry.write_text(
        "import { node, document, listeners, toasts, click, shown, nodes } from './dom.mjs';\n"
        f"const V = await import({json.dumps(UI_VIS.as_uri())});\n"
        f"for (const id of {json.dumps(_DOOR_IDS)}) node(id);\n"
        + textwrap.dedent(script)
    )
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the three columns, AND semantics ────────────────────────────────────────

def test_gallery_off_for_everyone_hides_both_doors_and_says_the_servers_sentence(tmp_path):
    out = _node(tmp_path, """
        V.applyToolVisibility({ features: { gallery: false } }, document);
        console.log(JSON.stringify({
          sidebar: shown('tool-gallery-btn'), rail: shown('rail-gallery'),
          recorded: [...window.__pantheonFeatureHiddenIds].sort(),
          says: V.toolRefusal('gallery'), others: shown('tool-calendar-btn'),
        }));
    """)
    assert out["sidebar"] is False and out["rail"] is False
    assert out["recorded"] == ["rail-gallery", "tool-gallery-btn"]
    assert out["others"] is True

    # The server says the same sentence when the window is reached anyway.
    from fastapi import HTTPException
    import src.feature_gate as fg
    guard = fg.require_feature("gallery", label="Gallery")
    real = fg.feature_enabled
    fg.feature_enabled = lambda name, features=None: name != "gallery"
    try:
        with pytest.raises(HTTPException) as hit:
            guard()
    finally:
        fg.feature_enabled = real
    assert hit.value.status_code == 403
    assert out["says"] == hit.value.detail == (
        "Gallery is switched off for everyone. An admin can turn it back on in "
        "Settings → Agent Tools.")


def test_a_privilege_hides_the_rail_twin_too(tmp_path):
    """SET-M-1: `init.js` hid `#tool-memory-btn` and nothing else; with the
    sidebar folded to the rail the person saw the Brain as before."""
    out = _node(tmp_path, """
        V.applyToolVisibility({ privileges: { can_manage_memory: false, can_generate_images: false }, auth: true }, document);
        console.log(JSON.stringify({
          memory: [shown('tool-memory-btn'), shown('rail-memory')],
          gallery: [shown('tool-gallery-btn'), shown('rail-gallery')],
          says: V.toolRefusal('brain'),
        }));
    """)
    assert out["memory"] == [False, False]
    assert out["gallery"] == [False, False]
    assert out["says"] == ("Brain is switched off for your account. An admin can turn "
                           "it back on in Settings → Users.")


def test_this_browser_can_only_take_a_tool_away(tmp_path):
    """SET-M-3: an admin's off outranks a browser's on — every pass, whatever
    order they arrive in."""
    out = _node(tmp_path, """
        V.applyToolVisibility({ ui: { 'tool-gallery': true } }, document);
        V.applyToolVisibility({ features: { gallery: false } }, document);
        // the person flips an unrelated Appearance switch: the browser pass
        // writes '' over every selector (applyUIVis) and hands its column on
        nodes['tool-gallery-btn'].style.display = '';
        V.applyToolVisibility({ ui: { 'tool-gallery': true, 'sidebar-brand': false } }, document);
        const afterFlip = shown('tool-gallery-btn');
        V.applyToolVisibility({ features: { gallery: true }, ui: { 'tool-calendar': false } }, document);
        console.log(JSON.stringify({
          afterFlip, galleryBack: shown('tool-gallery-btn'),
          calendarGone: !shown('tool-calendar-btn') && !shown('rail-calendar'),
          says: V.toolRefusal('calendar'),
        }));
    """)
    assert out["afterFlip"] is False
    assert out["galleryBack"] is True
    assert out["calendarGone"] is True
    assert out["says"] == ("Calendar is hidden in this browser. Turn it back on in "
                           "Settings → Appearance.")


def test_switching_back_on_shows_it_again_live_and_leaves_indicators_to_their_owner(tmp_path):
    """SET-M-12: the admin's own page applies a switch at once
    (`window.applyFeatureFlags`). An indicator the markup starts hidden
    (`#doc-indicator-btn`) is hidden with its tool and never shown by the
    table — its owner shows it when a document is open."""
    out = _node(tmp_path, """
        globalThis.document = document;   // the page's applier writes to the page
        nodes['doc-indicator-btn'].style.display = 'none';
        window.applyFeatureFlags({ document_editor: false, gallery: false });
        const off = [shown('tool-library-btn'), shown('overflow-doc-btn'), shown('doc-indicator-btn')];
        window.applyFeatureFlags({ document_editor: true, gallery: true });
        console.log(JSON.stringify({
          off, on: [shown('tool-library-btn'), shown('overflow-doc-btn'), shown('tool-gallery-btn')],
          indicator: shown('doc-indicator-btn'),
          recorded: [...window.__pantheonFeatureHiddenIds],
        }));
    """)
    assert out["off"] == [False, False, False]
    assert out["on"] == [True, True, True]
    assert out["indicator"] is False
    assert out["recorded"] == []


def test_memory_rag_and_web_search_switches_hide_something_now(tmp_path):
    """SET-M-4/5: the card said "turning one off hides its controls"; for
    Memory and RAG nothing was hidden."""
    out = _node(tmp_path, """
        V.applyToolVisibility({ features: { memory: false, rag: false, web_search: false }, ui: { 'rag-toggle-btn': true } }, document);
        console.log(JSON.stringify({
          brain: [shown('tool-memory-btn'), shown('rail-memory')],
          rag: shown('overflow-rag-btn'), web: shown('web-toggle-btn'),
        }));
    """)
    assert out == {"brain": [False, False], "rag": False, "web": False}


def test_forge_is_for_admins_and_unknown_is_on(tmp_path):
    """SET-M-9. Before `/api/auth/status` answers, or with auth off, the page
    does not know who is looking: unknown is on, and the server decides."""
    out = _node(tmp_path, """
        const before = shown('tool-cookbook-btn');
        V.applyToolVisibility({ isAdmin: null, auth: true }, document);
        const authOff = shown('tool-cookbook-btn');
        V.applyToolVisibility({ isAdmin: false }, document);
        const guest = [shown('tool-cookbook-btn'), shown('rail-cookbook'), V.toolRefusal('forge')];
        V.applyToolVisibility({ isAdmin: true }, document);
        console.log(JSON.stringify({ before, authOff, guest, admin: shown('tool-cookbook-btn') }));
    """)
    assert out["before"] is True and out["authOff"] is True
    assert out["guest"] == [False, False, "Forge is for admins."]
    assert out["admin"] is True


# ── every door asks ─────────────────────────────────────────────────────────

def test_the_door_lookups_name_their_tool(tmp_path):
    out = _node(tmp_path, """
        const k = (spec) => V.toolKeyFor(spec);
        console.log(JSON.stringify({
          slash: [k({ slash: 'tour-brain' }), k({ slash: 'gallery' }), k({ slash: 'cook' }), k({ slash: 'chats' })],
          route: [k({ route: '/gallery' }), k({ route: '/workbench/skills' }), k({ route: '/skills' }), k({ route: '/settings/ai' })],
          window: [k({ window: 'skills-modal' }), k({ window: 'email-lib-modal' })],
          shortcut: k({ shortcut: 'open_cookbook' }),
          element: [k({ element: 'rail-archive' }), k({ element: 'web-toggle-btn' })],
        }));
    """)
    assert out["slash"] == ["brain", "gallery", "forge", None]
    assert out["route"] == ["gallery", "workbench", "brain", None]
    assert out["window"] == ["brain", "email"]
    assert out["shortcut"] == "forge"
    # A composer chip has no door of its own to guard.
    assert out["element"] == ["library", None]


def test_a_programmatic_click_on_a_hidden_door_is_refused_before_its_handler(tmp_path):
    """The `open_*` shortcuts, the rail's delegation, `/open`, a deep link —
    every module that presses a sidebar row with `el.click()` — go through one
    capture-phase guard; a shown tool's click is untouched."""
    out = _node(tmp_path, """
        V.installToolDoorGuard(window);
        V.installToolDoorGuard(window);   // once, however often it is asked
        V.applyToolVisibility({ features: { gallery: false } }, document);
        const icon = { id: '', parentNode: nodes['tool-gallery-btn'] };   // the <svg> inside
        const refused = click(icon);
        const ok = click(nodes['tool-calendar-btn']);
        console.log(JSON.stringify({
          guards: listeners.filter((l) => l.type === 'click' && l.capture).length,
          refused: [refused.stopped, refused.prevented, nodes['tool-gallery-btn'].clicked],
          ok: [ok.stopped, nodes['tool-calendar-btn'].clicked],
          toasts,
        }));
    """)
    assert out["guards"] == 1
    assert out["refused"] == [True, True, 0]
    assert out["ok"] == [False, 1]
    assert out["toasts"] == ["Gallery is switched off for everyone. An admin can turn it "
                             "back on in Settings → Agent Tools."]


def test_a_link_to_a_hidden_tool_waits_for_the_switches_then_says_why(tmp_path):
    """SET-M-2 (URL half): `/gallery` linked opened the Gallery its admin had
    switched off. A link is followed at load, before the switches are known,
    so the guard waits for them."""
    out = _node(tmp_path, """
        let opened = 0;
        const said = [];
        const go = V.guardRouteOpener('/gallery', () => { opened += 1; }, { say: (t) => said.push(t) });
        const run = go();
        V.applyToolVisibility({ features: { gallery: false } }, document);
        V.applyToolVisibility({ privileges: {}, isAdmin: true, auth: true }, document);
        await run;
        const notes = V.guardRouteOpener('/notes', () => { opened += 10; });
        await notes();
        const other = V.guardRouteOpener('/settings/ai', null);
        console.log(JSON.stringify({ opened, said, other }));
    """)
    assert out["opened"] == 10
    assert out["said"] == ["Gallery is switched off for everyone. An admin can turn it back "
                           "on in Settings → Agent Tools."]
    assert out["other"] is None


def test_open_by_name_refuses_a_hidden_tool_in_the_chat(tmp_path):
    """SET-M-2 (slash half): `/open gallery` pressed a `display:none` button.

    Round 2 (`B-NEW-2`): the refusal is the door's toast, as at the URL and the
    sidebar — said through `slashReply` it was saved into the chat as an
    assistant message on every try. Nothing is said in the chat now."""
    src = SLASH_JS.read_text(encoding="utf-8")
    body = js_function(src, "async function _cmdOpen")
    out = _node(tmp_path, """
        window.pantheonToolDoor = V.toolDoor;
        const replies = [];
        const slashReply = (t) => replies.push(t);
        const cookbookModule = null, settingsModule = null;
        globalThis.document = document;
        async function _cmdOpen(args, ctx) %s
        const ctx = { esc: (t) => String(t) };
        V.applyToolVisibility({ privileges: { can_generate_images: false }, auth: true }, document);
        await _cmdOpen(['gallery'], ctx);
        await _cmdOpen(['documents'], ctx);
        console.log(JSON.stringify({
          replies, toasts, gallery: nodes['tool-gallery-btn'].clicked, library: nodes['tool-library-btn'].clicked,
        }));
    """ % body)
    assert out["gallery"] == 0
    assert out["library"] == 1
    assert out["replies"] == []
    assert out["toasts"] == ["Gallery is switched off for your account. An admin can turn "
                             "it back on in Settings → Users."]


def test_the_slash_catalogue_does_not_offer_a_hidden_tool(tmp_path):
    """The `/` popup and the palette read one catalogue (`slashCatalog`)."""
    (tmp_path / "js").mkdir()
    shutil.copy(AUTOCOMPLETE_JS, tmp_path / "js" / "slashAutocomplete.js")
    shutil.copy(UI_VIS, tmp_path / "js" / "ui_visibility.js")
    (tmp_path / "js" / "toolWindowZOrder.js").write_text("export function topPortalZ() { return 1; }\n")
    commands = {name: {"handler": True, "category": "Tools", "help": name}
                for name in ("brain", "gallery", "tour-brain", "notes", "forge")}
    (tmp_path / "js" / "slashCommands.js").write_text(
        "const h = () => true;\n"
        f"export const COMMANDS = Object.fromEntries(Object.entries({json.dumps(commands)})"
        ".map(([k, v]) => [k, { ...v, handler: h }]));\n"
        "export const LEGACY_ALIASES = { memories: { parent: 'brain', sub: 'list' } };\n")
    text = (tmp_path / "js" / "slashAutocomplete.js").read_text()
    (tmp_path / "js" / "slashAutocomplete.js").write_text(
        text.replace("./slashCommands.js?v=20261007approvalp23", "./slashCommands.js"))
    out = _node(tmp_path, """
        globalThis.document = { addEventListener() {}, getElementById: () => null };
        const T = await import('./js/ui_visibility.js');
        const { slashCatalog } = await import('./js/slashAutocomplete.js');
        const before = slashCatalog().map((e) => e.token);
        T.applyToolVisibility({ features: { memory: false }, isAdmin: false, auth: true }, null);
        const after = slashCatalog().map((e) => e.token);
        console.log(JSON.stringify({ before, after }));
    """)
    assert set(out["before"]) == {"/brain", "/gallery", "/tour-brain", "/notes", "/forge"}
    assert out["after"] == ["/gallery", "/notes"]


_POPUP_SHIM = r"""
import { installDom } from './dom.js';
export const document = installDom();
globalThis.window = globalThis;
globalThis.addEventListener = globalThis.addEventListener || (() => {});
globalThis.Event = class Event { constructor(type, init) { this.type = type; Object.assign(this, init || {}); } };
"""

_POPUP_COMMANDS = """
const h = () => true;
export const COMMANDS = {
  gallery: { category: 'Tools', help: 'Open Gallery', usage: '/gallery', handler: h },
  'tour-gallery': { category: 'Tours', help: 'Gallery tour', usage: '/tour-gallery', handler: h },
  notes: { category: 'Tools', help: 'Open Notes', usage: '/notes', handler: h },
};
export const LEGACY_ALIASES = {};
export default { COMMANDS };
"""


def test_the_slash_popup_asks_the_table_each_time_it_opens(tmp_path):
    """`B-NEW-1`. Measured on `a936b5c` in Chromium: with Gallery off (a fresh
    page or a live switch), typing `/gal` listed `/gallery Open Gallery` and
    `/tour-gallery`, while `slashCatalog()`, Ctrl+K and the dispatcher had all
    dropped it — the popup filtered its list once, when the message box was
    wired, before `/api/auth/features` had answered. Driven: the real popup
    (`slashAutocomplete.js`) on a DOM shim with the real `ui_visibility.js`
    beside it; the rows read off the popup it draws."""
    from test_tool_effect_surfaces_js import _make_sandbox, _run

    sandbox = _make_sandbox(tmp_path, AUTOCOMPLETE_JS, _POPUP_SHIM,
                            {"slashCommands.js": _POPUP_COMMANDS})
    out = _run(sandbox, "import { document } from './shim.js';\n", """
        const T = await import('./ui_visibility.js');
        const ac = await import('./slashAutocomplete.js');
        const box = () => {
          const ta = document.createElement('textarea');
          document.body.appendChild(ta);
          ta.getBoundingClientRect = () => ({ top: 500, left: 10, width: 600, height: 40, bottom: 540, right: 610 });
          ac.initSlashAutocomplete(ta);
          return ta;
        };
        const offered = (ta, q) => {
          ta.value = q;
          ta.dispatchEvent(new Event('input', { bubbles: true }));
          const pop = document.getElementById('slash-autocomplete');
          if (!pop || pop.style.display === 'none') return [];
          return [...String(pop.innerHTML).matchAll(/data-token="([^"]+)"/g)].map((m) => m[1]);
        };
        // The page wires the box at load, before the switches are known.
        const ta = box();
        const before = offered(ta, '/gal');
        T.applyToolVisibility({ features: { gallery: false } }, null);
        const off = offered(ta, '/gal');
        const offAll = offered(ta, '/');
        // A box wired while Gallery is off, then Gallery back on, live. (The
        // popup is one element by id: the first box closes it first.)
        offered(ta, 'done');
        const late = box();
        const lateOff = offered(late, '/gal');
        T.applyToolVisibility({ features: { gallery: true } }, null);
        // The late box first: the popup is one element, so the first box's
        // rows must not be the ones read for it.
        const lateBack = offered(late, '/gal');
        offered(late, 'done');
        console.log(JSON.stringify({ before, off, offAll, lateOff, lateBack, back: offered(ta, '/gal') }));
    """)
    assert out["before"] == ["/gallery", "/tour-gallery"]
    assert out["off"] == [], "the popup offered a tool switched off after the box was wired"
    assert out["offAll"] == ["/notes"]
    assert out["lateOff"] == []
    assert out["back"] == ["/gallery", "/tour-gallery"]
    assert out["lateBack"] == ["/gallery", "/tour-gallery"], (
        "a box wired while the tool was off never offered it again")


def test_the_palette_does_not_offer_a_hidden_tools_window(tmp_path):
    """Ctrl+K offered Skills (its door is a function, not a button) with the
    Brain taken away."""
    src = PALETTE_JS.read_text(encoding="utf-8")
    body = js_function(src, "function _toolEntries")
    out = _node(tmp_path, """
        const { toolKeyFor, toolShown } = V;
        const listWindows = () => [
          { id: 'skills-modal', label: 'Skills', door: false, doors: [], state: 'closed' },
          { id: 'gallery-modal', label: 'Gallery', door: true, doors: [], state: 'closed' },
          { id: 'calendar-modal', label: 'Calendar', door: true, doors: [], state: 'closed' },
        ];
        const _DOOR_FUNCTIONS = { 'skills-modal': () => {} };
        const _DOOR_SHOWN = {};
        const _wordsMatch = () => true, isMinimized = () => false, showWindow = () => {};
        const _STATE_WORDS = {}, _toolKey = () => '', _compareIsOn = () => '';
        function _toolEntries(terms) %s
        const before = _toolEntries([]).map((e) => e.label);
        V.applyToolVisibility({ privileges: { can_manage_memory: false }, auth: true, ui: { 'tool-gallery': false } }, document);
        console.log(JSON.stringify({ before, after: _toolEntries([]).map((e) => e.label) }));
    """ % body)
    assert out["before"] == ["Skills", "Gallery", "Calendar"]
    assert out["after"] == ["Calendar"]


def test_the_palettes_commands_follow_a_switch_made_after_they_were_read(tmp_path):
    """Driven in Chromium: Ctrl+K kept offering `/gallery` and `/tour-gallery`
    after the admin switched Gallery off, because the palette reads the
    catalogue once. The rows are asked again on every query."""
    src = PALETTE_JS.read_text(encoding="utf-8")
    body = js_function(src, "function _commandEntries")
    out = _node(tmp_path, """
        const { toolKeyFor, toolShown } = V;
        let reads = 0;
        const slashCatalog = () => { reads += 1; return [
          { token: '/gallery', help: 'Open Gallery' }, { token: '/tour-gallery', help: 'Tour' },
          { token: '/notes', help: 'Open Notes' }]; };
        let _catalog = null;
        const _wordsMatch = () => true;
        function _commandEntries(terms) %s
        const before = _commandEntries([]).map((e) => e.label);
        window.applyFeatureFlags({ gallery: false });
        const after = _commandEntries([]).map((e) => e.label);
        console.log(JSON.stringify({ before, after, reads }));
    """ % body)
    assert out == {"before": ["/gallery", "/tour-gallery", "/notes"], "after": ["/notes"], "reads": 1}


def test_a_chip_the_table_hides_stays_hidden_through_a_mode_change(tmp_path):
    """SET-M-4: `applyModeToToggles` wrote `display = ''` on every chip half a
    second after every mode change, and the guard after it could never be
    true."""
    src = APP_JS.read_text(encoding="utf-8")
    body = js_function(src, "function applyModeToToggles")
    out = _node(tmp_path, """
        const el = (id) => document.getElementById(id);
        const MODE_TOOLS = [
          { btnId: 'web-toggle-btn', checkboxId: null, stateKey: 'web' },
          { btnId: 'bash-toggle-btn', checkboxId: null, stateKey: 'bash' },
        ];
        const loadToolPref = () => false;
        for (const id of ['web-toggle-btn', 'bash-toggle-btn']) nodes[id].classList = { toggle() {} };
        function applyModeToToggles(mode) %s
        V.applyToolVisibility({ features: { web_search: false } }, document);
        applyModeToToggles('agent');
        console.log(JSON.stringify({ web: shown('web-toggle-btn'), bash: shown('bash-toggle-btn') }));
    """ % body)
    assert out == {"web": False, "bash": True}


def test_the_chat_mode_getter_answers(tmp_path):
    """CHAT-M-2: `__pantheonGetChatMode` returned `st.mode`, and `st` is a
    `const` inside `setMode`: every call threw."""
    src = APP_JS.read_text(encoding="utf-8")
    body = js_function(src, "function initModeToggle")
    out = _node(tmp_path, """
        const mk = (id) => { const n = node(id); n.listeners = {};
          n.addEventListener = (t, f) => { n.listeners[t] = f; };
          n.classList = { toggle() {} }; n.setAttribute = () => {}; n.closest = () => null; return n; };
        mk('mode-agent-btn'); mk('mode-chat-btn');
        const el = (id) => document.getElementById(id);
        let stored = { mode: 'chat' };
        const loadToggleState = () => ({ ...stored });
        const saveToggleState = (s) => { stored = s; };
        const workspaceModule = { applyMode() {} };
        const applyModeToToggles = () => {};
        const _syncResearchIndicator = () => {};
        const onToolVisibilityApplied = V.onToolVisibilityApplied;
        globalThis.setTimeout = () => 0;
        (function initModeToggle() %s)();
        const first = window.__pantheonGetChatMode();
        nodes['mode-agent-btn'].listeners.click();
        console.log(JSON.stringify({ first, after: window.__pantheonGetChatMode(), stored: stored.mode }));
    """ % body)
    assert out == {"first": "chat", "after": "agent", "stored": "agent"}


def test_every_feature_the_table_names_is_enforced_on_the_server_too():
    """H05's rule, kept: hiding a button was never the problem, it was that
    hiding a button was ALL there was. Every feature key the table hides a
    tool for is also refused by the agent gate or the HTTP gate."""
    import re
    proc = subprocess.run(
        ["node", "--input-type=module", "-e",
         f"const V = await import({json.dumps(UI_VIS.as_uri())});"
         "console.log(JSON.stringify([...new Set(Object.values(V.TOOL_VISIBILITY)"
         ".map((d) => d.feature).filter(Boolean))]));"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    flags = set(json.loads(proc.stdout))
    assert flags == {"memory", "deep_research", "gallery", "document_editor", "web_search", "rag"}

    from src.settings import DEFAULT_FEATURES
    from src.tool_security import _FEATURE_TOOLS
    gated = set()
    for path in ("routes/research/research_routes.py", "routes/gallery/gallery_routes.py",
                 "routes/memory/memory_routes.py", "routes/document/document_routes.py"):
        gated |= set(re.findall(r'require_feature\(\s*"([a-z_]+)"',
                                (ROOT / path).read_text(encoding="utf-8")))
    for flag in flags:
        assert flag in DEFAULT_FEATURES, flag
        assert _FEATURE_TOOLS.get(flag) or flag in gated, f"{flag} is hidden and enforced nowhere"


# ── the switches say what they did (SET-M-10/11/12, SET-U-1) ────────────────

ADMIN_JS = ROOT / "static" / "js" / "admin.js"
REFUSAL_JS = ROOT / "static" / "js" / "workbench" / "refusal.js"


def _admin_fn(name: str) -> str:
    """One function of `admin.js`, cut out whole: signature, parameters, body."""
    src = ADMIN_JS.read_text(encoding="utf-8")
    sig = f"async function {name}" if f"async function {name}(" in src else f"function {name}"
    at = src.index(sig + "(") + len(sig) + 1
    return f"{sig}({src[at:src.index(')', at)]}) " + js_function(src, sig)


def _switch_case(tmp_path: Path, script: str) -> dict:
    src = ADMIN_JS.read_text(encoding="utf-8")
    from tests.helpers.js_source import js_binding
    return _node(tmp_path, f"""
        const {{ readRefusal }} = await import({json.dumps(REFUSAL_JS.as_uri())});
        const {{ toolsHiddenBy }} = V;
        const said = {{ toasts: [], errors: [] }};
        const uiModule = {{ showToast: (m) => said.toasts.push(m), showError: (m) => said.errors.push(m) }};
        let answer = null;
        const posted = [];
        globalThis.fetch = async (url, init) => {{ posted.push({{ url, body: init && init.body }}); return answer(url); }};
        const res = (status, body) => ({{ ok: status < 400, status, json: async () => body }});
        {js_binding(src, "featureLabels")};
        {_admin_fn("_hidesLine")}
        {_admin_fn("_saveFeature")}
        {_admin_fn("_savePrivilege")}
        {textwrap.dedent(script)}
    """)


def test_a_feature_switch_applies_on_the_admins_page_and_says_so(tmp_path):
    out = _switch_case(tmp_path, """
        globalThis.document = document;
        answer = () => res(200, { gallery: false, memory: true });
        const toggle = { dataset: { admFeature: 'gallery' }, checked: false };
        const ok = await _saveFeature(toggle);
        console.log(JSON.stringify({ ok, said, gallery: shown('tool-gallery-btn'), checked: toggle.checked }));
    """)
    assert out["ok"] is True and out["checked"] is False
    assert out["gallery"] is False, "the admin's own page still showed it until a reload (SET-M-12)"
    assert out["said"] == {"toasts": ["Gallery off for everyone. Others see it after their next reload."],
                           "errors": []}


def test_a_refused_switch_goes_back_and_says_the_servers_sentence(tmp_path):
    out = _switch_case(tmp_path, """
        answer = () => res(403, { detail: 'Admin only' });
        const toggle = { dataset: { admFeature: 'memory' }, checked: false };
        const feature = await _saveFeature(toggle);
        answer = () => res(404, { detail: 'User not found' });
        const input = { type: 'checkbox', checked: false, dataset: { user: 'guest', priv: 'can_manage_memory' } };
        const priv = await _savePrivilege(input);
        console.log(JSON.stringify({ feature, priv, said, toggle: toggle.checked, input: input.checked }));
    """)
    assert out["feature"] is False and out["toggle"] is True
    assert out["priv"] is False and out["input"] is True
    assert out["said"] == {"toasts": [], "errors": ["Admin only", "User not found"]}


def test_a_privilege_saved_says_when_it_takes_effect(tmp_path):
    out = _switch_case(tmp_path, """
        answer = () => res(200, { ok: true });
        const input = { type: 'checkbox', checked: false, dataset: { user: 'guest', priv: 'can_generate_images' } };
        const ok = await _savePrivilege(input);
        console.log(JSON.stringify({ ok, said, body: JSON.parse(posted[0].body) }));
    """)
    assert out["ok"] is True
    assert out["body"] == {"can_generate_images": False}
    assert out["said"]["toasts"] == ["Saved. guest sees it after their next reload."]


def test_each_switch_names_the_tools_entry_it_hides(tmp_path):
    """SET-U-1: nothing on any of the four cards said which Tools entry it
    affected. The line is read from the table, so it cannot claim more than
    the applier does."""
    out = _switch_case(tmp_path, """
        console.log(JSON.stringify({
          memory: _hidesLine({ feature: 'memory' }),
          docs: _hidesLine({ feature: 'document_editor' }),
          web: _hidesLine({ feature: 'web_search' }),
          filter: _hidesLine({ feature: 'sensitive_filter' }),
          images: _hidesLine({ privilege: 'can_generate_images' }),
          agent: _hidesLine({ privilege: 'can_use_agent' }),
          browser: _hidesLine({ privilege: 'can_use_browser' }),
        }));
    """)
    assert out == {
        "memory": "Off hides Brain.",
        "docs": "Off hides Library and the Document editor button.",
        "web": "Off hides the Web search button.",
        "filter": "",
        "images": "Off hides Gallery.",
        "agent": "Off hides the Agent mode button.",
        "browser": "",
    }


def test_the_users_list_offers_no_revoke_on_the_only_admin_and_a_privileges_button(tmp_path):
    """SET-M-11: *Revoke admin* on the only admin confirmed, then answered
    "Cannot demote the last admin". SET-U-7: "Click to manage privileges"
    never changed; the row's button says what pressing it does."""
    from test_tool_effect_surfaces_js import _DOM as SHIM_DOM, _run
    from tests.helpers.esc_stub import esc_source
    from tests.helpers.js_source import js_binding
    src = ADMIN_JS.read_text(encoding="utf-8")
    (tmp_path / "dom.js").write_text(SHIM_DOM)

    def case(users):
        return "\n".join([
            "import { installDom, Node } from './dom.js';",
            "const document = installDom();",
            esc_source(),
            "const uiModule = { esc, showError: () => {}, showToast: () => {} };",
            "function chevronIcon() { return '<svg></svg>'; }",
            "function el(id) { return document.getElementById(id); }",
            f"import {{ toolsHiddenBy }} from {json.dumps(UI_VIS.as_uri())};",
            js_binding(src, "PRIV_LABELS") + ";",
            js_binding(src, "NON_ADMIN_RETIRED_PRIVS") + ";",
            _admin_fn("_hidesLine"),
            "async function loadUsers() " + js_function(src, "async function loadUsers"),
            f"const PAYLOAD = {json.dumps({'users': users})};",
            "globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => PAYLOAD });",
            "const list = document.body.appendChild(new Node('div'));",
            "list.setAttribute('id', 'adm-userList');",
            "await loadUsers();",
            "const out = {};",
            "for (const row of list.children) {",
            "  const head = row.children[0]._html;",
            "  const name = (head.match(/admin-user-name\">([^<]*)</) || [])[1];",
            "  const panel = row.querySelector('.admin-priv-panel');",
            "  out[name] = { revoke: head.includes('Revoke admin'), make: head.includes('Make admin'),",
            "    privileges: head.includes('data-adm-privs'), hint: head.includes('Click to manage'),",
            "    canUse: panel ? panel._html.includes('>Can use<') : null,",
            "    hides: panel ? panel._html.includes('Off hides Brain.') : null };",
            "}",
            "console.log(JSON.stringify(out));",
        ])

    one = _run(tmp_path, "", case([
        {"username": "rowan", "is_admin": True, "privileges": {}},
        {"username": "guest", "is_admin": False, "privileges": {"can_manage_memory": True}},
    ]))
    assert one["rowan"]["revoke"] is False, "Revoke admin offered on the only admin"
    assert one["guest"] == {"revoke": False, "make": True, "privileges": True, "hint": False,
                            "canUse": True, "hides": True}
    two = _run(tmp_path, "", case([
        {"username": "rowan", "is_admin": True, "privileges": {}},
        {"username": "kit", "is_admin": True, "privileges": {}},
    ]))
    assert two["rowan"]["revoke"] is True and two["kit"]["revoke"] is True


# ── Settings for the person it is open for (SET-U-2, SET-U-13, SET-M-3) ────

SETTINGS_JS = ROOT / "static" / "js" / "settings.js"
REGISTRY_JS = ROOT / "static" / "js" / "settings" / "registry.js"
SEARCH_JS = ROOT / "static" / "js" / "settings" / "search.js"


def test_a_non_admin_opens_on_account_and_is_never_sent_to_an_admin_panel(tmp_path):
    src = SETTINGS_JS.read_text(encoding="utf-8")
    body = js_function(src, "export function open")
    out = _node(tmp_path, f"""
        const R = await import({json.dumps(REGISTRY_JS.as_uri())});
        const {{ isAdminOnlySettingsTab, NON_ADMIN_SETTINGS_PANEL_ID }} = R;
        const viewerIsAdmin = V.viewerIsAdmin;
        let active = 'services', initialized = true, activated = [];
        const modalEl = {{ classList: {{ contains: () => true }}, style: {{}} }};
        const initAll = () => {{}}, syncAppearanceCheckboxes = () => {{}}, showSettingsModal = () => {{}};
        const syncAdminVisibility = () => {{}}, onSettingsPanelActivated = () => {{}};
        const isAdminManagedSettingsTab = () => false, _openIntegrationsRoom = () => {{}};
        const getActiveSettingsTab = () => active;
        const activateSettingsPanel = (m, tab) => {{ activated.push(tab); active = tab; }};
        function open(tab) {body}
        V.applyToolVisibility({{ isAdmin: false, auth: true }}, null);
        open(); open('ai'); open('appearance');
        const guest = activated.slice();
        activated = []; active = 'services';
        V.applyToolVisibility({{ isAdmin: true }}, null);
        open(); open('ai');
        console.log(JSON.stringify({{ guest, admin: activated }}));
    """)
    assert out["guest"] == ["account", "account", "appearance"]
    assert out["admin"] == ["ai"]


def test_a_result_names_a_group_only_to_someone_who_can_see_it(tmp_path):
    """SET-U-13: a non-admin's result said "Workstation · Administration"."""
    src = SEARCH_JS.read_text(encoding="utf-8")
    body = js_function(src, "function groupLabelFor")
    out = _node(tmp_path, f"""
        const {{ SETTINGS_GROUPS, getSettingsPanel }} = await import({json.dumps(REGISTRY_JS.as_uri())});
        function groupLabelFor(panel, isAdmin = true) {body}
        const ws = getSettingsPanel('workstation');
        console.log(JSON.stringify({{ guest: groupLabelFor(ws, false), admin: groupLabelFor(ws, true),
          email: groupLabelFor(getSettingsPanel('email'), false) }}));
    """)
    assert out == {"guest": "", "admin": "Administration", "email": "Communications"}


def test_a_browser_switch_an_admin_overrode_says_why_instead_of_flipping(tmp_path):
    """SET-M-3's other half: the Appearance switch for a tool an admin took away
    flipped and changed nothing. It is disabled and says which column holds it."""
    src = SETTINGS_JS.read_text(encoding="utf-8")
    from tests.helpers.js_source import js_binding
    body = js_function(src, "function _syncToolSwitchWhy")
    out = _node(tmp_path, f"""
        const {{ TOOL_VISIBILITY, toolOff, toolRefusal }} = V;
        document.createElement = () => ({{ className: '', textContent: '', remove() {{ this.gone = true; }} }});
        {js_binding(src, "_UI_KEY_TOOL").replace("var _UI_KEY_TOOL", "const _UI_KEY_TOOL")};
        function row() {{
          const label = {{ kids: [], appendChild(n) {{ this.kids.push(n); }} }};
          const r = {{ title: null, label,
            querySelector: (sel) => sel === '.vis-label' ? label : (label.kids.find((k) => !k.gone) || null),
            setAttribute(k, v) {{ this.title = v; }}, removeAttribute() {{ this.title = null; }} }};
          return {{ disabled: false, closest: () => r, r }};
        }}
        function _syncToolSwitchWhy(chk, key) {body}
        V.applyToolVisibility({{ features: {{ gallery: false }}, privileges: {{ can_manage_memory: false }}, ui: {{ 'tool-notes': false }}, auth: true }}, null);
        const g = row(), b = row(), n = row();
        _syncToolSwitchWhy(g, 'tool-gallery'); _syncToolSwitchWhy(b, 'tool-memory'); _syncToolSwitchWhy(n, 'tool-notes');
        V.applyToolVisibility({{ features: {{ gallery: true }} }}, null);
        const before = g.r.label.kids[0].textContent;
        _syncToolSwitchWhy(g, 'tool-gallery');
        console.log(JSON.stringify({{
          gallery: [g.disabled, before, g.r.title], brain: [b.disabled, b.r.label.kids[0].textContent],
          notes: [n.disabled, n.r.label.kids.length], galleryBack: [g.disabled, !!g.r.label.kids[0].gone],
        }}));
    """)
    assert out["gallery"][0] is False  # re-read after the switch came back on
    assert out["gallery"][1] == "Off for everyone"
    assert out["brain"] == [True, "Off for your account"]
    assert out["notes"] == [False, 0], "this browser's own switch stays the person's to flip"
    assert out["galleryBack"] == [False, True]


# ── what the System panel says (COPY-M-8, COPY-U-44, COPY-U-41) ────────────

def test_the_embedding_check_names_the_labels_a_person_can_find(monkeypatch):
    """COPY-M-8: it named the settings by their keys (`EMBEDDING_URL`,
    `allow_model_download`)."""
    import src.embedding_lanes as lanes
    import src.embeddings as emb
    import src.self_checks as sc
    monkeypatch.setattr(emb, "get_embedding_client", lambda: None)
    monkeypatch.setattr(lanes, "fastembed_model_is_cached", lambda: False)
    monkeypatch.setattr(lanes, "model_download_allowed", lambda: False)
    check = sc.embedding_availability()
    words = json.dumps(check, ensure_ascii=False)
    assert "EMBEDDING_URL" not in words and "allow_model_download" not in words
    assert "Remote embedding endpoint (Settings → Embeddings)" in words
    assert "Download models from the internet (Settings → System)" in words
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "Remote embedding endpoint</h2>" in index
    assert "'Download models from the internet'" in SETTINGS_JS.read_text(encoding="utf-8")


def test_a_down_vector_store_says_what_a_person_loses():
    from src.service_health import chromadb_health

    class Down:
        healthy = False

    row = chromadb_health(Down(), Down())
    assert row["status"] == "down"
    assert row["detail"] == "Memory and document search are down."


def test_an_embedding_model_row_reads_language_tokens_year(tmp_path):
    """COPY-U-41: each row printed the library's own catalogue string."""
    src = (ROOT / "static" / "js" / "embeddings.js").read_text(encoding="utf-8")
    body = js_function(src, "function _shortDescription")
    out = _node(tmp_path, f"""
        function _shortDescription(text) {body}
        console.log(JSON.stringify([
          _shortDescription('Text embeddings, Unimodal (text), English, 512 input tokens truncation, Prefixes for queries/documents: not so necessary, 2023 year.'),
          _shortDescription('Text embeddings, Multilingual, 8192 input tokens truncation, 2024 year'),
          _shortDescription('a model'), _shortDescription(null)]));
    """)
    assert out == ["English · 512 tokens · 2023", "Multilingual · 8192 tokens · 2024", "", ""]


def test_the_forges_own_opener_refuses_a_non_admin(tmp_path):
    """The model picker's *Open Forge* calls `cookbookModule.open()` directly —
    no button to guard — so the opener asks the table itself (SET-M-9)."""
    src = (ROOT / "static" / "js" / "cookbook.js").read_text(encoding="utf-8")
    body = js_function(src, "export async function open")
    out = _node(tmp_path, """
        window.pantheonToolDoor = (spec) => V.toolDoor(spec, { say: (t) => said.push(t) });
        const said = [], asked = [];
        document.getElementById = (id) => { asked.push(id); return null; };
        async function open(opts) %s
        V.applyToolVisibility({ isAdmin: false, auth: true }, null);
        await open();
        const guest = asked.slice();
        V.applyToolVisibility({ isAdmin: true }, null);
        await open();
        console.log(JSON.stringify({ guest, admin: asked.slice(guest.length), said }));
    """ % body)
    assert out == {"guest": [], "admin": ["cookbook-modal"], "said": ["Forge is for admins."]}
