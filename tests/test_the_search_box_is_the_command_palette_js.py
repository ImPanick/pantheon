# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-01` — the command palette is the search overlay, extended.

The row: *"Command palette, framed as extending the existing search rather than
a parallel component. Every data source is already a registry: slash commands,
settings panels with keywords, the modal auto-wire map, the route table."* And
FORBIDDEN.md Part 1: `#search-overlay`, `#search-input` and `#search-results`
stay in the DOM and keep working for their callers.

Driven under node against the real `search-chat.js`, and against the real
registries it reads — `modalManager.js` (`_AUTO_WIRE`, `_LABELS`),
`settings/registry.js` and `settings/search.js`, `slashAutocomplete.js`, and the
`COMMANDS` / `LEGACY_ALIASES` tables lifted out of `slashCommands.js` with
`js_binding` (its handlers replaced by recorders, so a test can see that none of
them ran). The overlay, the icon rail, the sidebar and the Settings panels are
built from `static/index.html` itself, parsed at test time — so a rail button
or an ARIA attribute that leaves the markup leaves this test's world too.
`keyboard-shortcuts.js` is driven for real for the Ctrl+K call site.

What is pinned, and why each one is a defect rather than a preference:

  * **Every registry is read, none is copied.** A tool comes from `_AUTO_WIRE`
    and opens through the door a person would press; a Settings panel comes
    from the registry's own `searchSettingsPanels`, with its admin rule; a
    command is one the composer's own `/` popup offers, hidden ones excluded.
  * **The palette changes nothing itself.** A command goes into the message
    box and is never run; a draft already there is never overwritten.
  * **A door is a toggle.** "Calendar" with Calendar already open must raise
    it, not close it; a minimized one is restored, as the dock does.
  * **Keyboard alone, and said out loud.** One active option, named by the
    box's `aria-activedescendant`; Escape closes, hands focus back to where it
    was, and goes no further (it used to reach `abortCurrentRequest`); Tab stays
    in the box; a live status line says what was found.
  * **Text is text.** A hostile chat title and snippet arrive as characters —
    the renderer builds no markup at all.
  * **The chat search is unchanged.** Same request, same grouping, and a stale
    answer can no longer overwrite a newer one.
  * **The callers still work**: Ctrl+K through the real keybind dispatcher, and
    `/find` — which the brief lists as a caller — shown never to touch the
    overlay at all. The rail button, the sidebar button and `app.js`'s Escape
    chain are driven in a real browser by
    `tests/test_the_command_palette_in_a_browser.py`.
"""

import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.helpers.esc_stub import esc_source, ui_default_stub
from tests.helpers.js_source import js_binding, js_definition
from test_background_work_dock_js import _SHIM as _DOCK_SHIM  # noqa: E402
from test_background_work_dock_js import _STUBS as _DOCK_STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _copy_unstubbed_imports, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
SEARCH_JS = JS / "search-chat.js"
SLASH_JS = JS / "slashCommands.js"
KEYS_JS = JS / "keyboard-shortcuts.js"
INDEX_HTML = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the markup, read out of index.html ─────────────────────────────────────

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "source", "track", "wbr"}


class _Tree(HTMLParser):
    """`index.html` as nested dicts, for the node shim to rebuild."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "#root", "attrs": {}, "children": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": {k: (v or "") for k, v in attrs}, "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1]["children"].append(
            {"tag": tag, "attrs": {k: (v or "") for k, v in attrs}, "children": []})

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip() and self.stack[-1]["tag"] not in ("script", "style"):
            self.stack[-1]["children"].append({"tag": "#text", "text": data})


def _subtree(root, element_id):
    stack = [root]
    while stack:
        node = stack.pop()
        if node.get("attrs", {}).get("id") == element_id:
            return node
        stack.extend(node.get("children", []))
    raise AssertionError(f"#{element_id} is not in static/index.html")


def _markup():
    parser = _Tree()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    return {name: _subtree(parser.root, name) for name in
            ("search-overlay", "icon-rail", "sidebar", "settings-modal", "message")}


# ── the sandbox ────────────────────────────────────────────────────────────

def _slash_stub() -> str:
    """`slashCommands.js` with its REAL registry and recording handlers.

    `COMMANDS` and `LEGACY_ALIASES` are lifted out of the shipped file, so the
    palette is tested against the commands that exist rather than a list typed
    here. Every `_cmd*` handler the table names is replaced by a recorder:
    `globalThis.__ran` stays empty unless something ran a command.
    """
    src = SLASH_JS.read_text(encoding="utf-8")
    commands = js_binding(src, "COMMANDS")
    legacy = js_binding(src, "LEGACY_ALIASES")
    handlers = sorted(set(re.findall(r"\b(_cmd\w+)\b", commands)))
    lines = ["globalThis.__ran = globalThis.__ran || [];"]
    lines += [f"const {h} = (...a) => {{ globalThis.__ran.push('{h}'); return true; }};"
              for h in handlers]
    lines += [commands + ";", legacy + ";", "export { COMMANDS };"]
    return "\n".join(lines) + "\n"


_STUBS = dict(_DOCK_STUBS)
_STUBS.update({
    "toolWindowZOrder.js": (
        "export const TOOL_WINDOW_SELECTOR = '';\n"
        "export function nextToolWindowZ(){ return 1; }\n"
        "export function topPortalZ(){ return globalThis.__topPortalZ || 10031; }\n"
        "export function toolWindowZ(){ return NaN; }\n"  # `B1068`: `modalManager.js` imports it
    ),
    "sessions.js": (
        "globalThis.__selected = globalThis.__selected || [];\n"
        "export default { selectSession(id) { globalThis.__selected.push(id); return Promise.resolve(); } };\n"
    ),
    "settings.js": (
        "globalThis.__settingsOpened = globalThis.__settingsOpened || [];\n"
        "export default {\n"
        "  open(tab) { globalThis.__settingsOpened.push(tab === undefined ? null : tab); },\n"
        "  close() {},\n"
        "};\n"
    ),
    "appConfig.js": "export function getSettings(){ return Promise.resolve({}); }\n",
    # `P9-06`'s Skills window opens through `openSkillsWindow`; recorded here.
    "skills.js": (
        "globalThis.__skillsOpened = globalThis.__skillsOpened || [];\n"
        "export function openSkillsWindow(view) {\n"
        "  globalThis.__skillsOpened.push(view === undefined ? null : view); return Promise.resolve(true);\n"
        "}\n"
        "export default { openSkillsWindow };\n"
    ),
    # The palette no longer imports `ui.js` — it builds no markup, so it needs
    # no escaper — but the renderer it replaced did, and the red-on-the-old-tree
    # run loads that one. The shipped `esc`, per `B874`.
    "ui.js": ui_default_stub("showToast: () => {}, el: (id) => document.getElementById(id),"),
})

_SHIM = _DOCK_SHIM + r"""
// ── `P9-01` additions ──────────────────────────────────────────────────────
// A focus model: the shared shim records `focused` on the node and leaves
// `document.activeElement` alone, and the palette's whole Escape contract is
// about where focus goes.
Node.prototype.focus = function () { document.activeElement = this; };
Node.prototype.removeAttribute = function (k) {
  delete this.attrs[k];
  if (String(k).startsWith('data-')) {
    delete this.dataset[String(k).slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase())];
  }
};
globalThis.MutationObserver = class { observe() {} disconnect() {} };
// Every door the palette presses, in order, and what the stubs record. Set up
// here as well as in the stubs, because the renderer this row replaced loads
// none of them and a reading must still work against it.
globalThis.__clicked = [];
globalThis.__selected = globalThis.__selected || [];
globalThis.__settingsOpened = globalThis.__settingsOpened || [];
globalThis.__ran = globalThis.__ran || [];
globalThis.__skillsOpened = globalThis.__skillsOpened || [];
const _dockClick = Node.prototype.click;
Node.prototype.click = function () { globalThis.__clicked.push(this.id); _dockClick.call(this); };

const camel = (s) => s.replace(/-([a-z])/g, (m, c) => c.toUpperCase());
export function build(tree, parent) {
  for (const n of tree.children || []) {
    if (n.tag === '#text') { parent.appendChild(document.createTextNode(n.text)); continue; }
    const node = document.createElement(n.tag);
    for (const [k, v] of Object.entries(n.attrs || {})) {
      if (k === 'class') node.className = v;
      else if (k === 'id') node.id = v;
      else if (k === 'style') {
        for (const decl of v.split(';')) {
          const i = decl.indexOf(':');
          if (i > 0) node.style[camel(decl.slice(0, i).trim())] = decl.slice(i + 1).trim();
        }
      } else if (k.startsWith('data-')) {
        node.dataset[camel(k.slice(5))] = v;
      } else {
        node.setAttribute(k, v);
        if (k === 'placeholder') node.placeholder = v;
        if (k === 'title') node.title = v;
        if (k === 'hidden') node.hidden = true;
      }
    }
    parent.appendChild(node);
    build(n, node);
  }
}
export function mount(tree) {
  const holder = { children: [tree] };
  build(holder, document.body);
  return document.getElementById(tree.attrs.id);
}
const MARKUP = __MARKUP__;
for (const name of ['icon-rail', 'sidebar', 'settings-modal', 'message', 'search-overlay']) mount(MARKUP[name]);

// The chat lane's answers, per query.
globalThis.__fetches = [];
const answers = new Map();
export function answer(query, spec) { answers.set(query, spec); }
globalThis.fetch = async (url) => {
  const u = String(url);
  globalThis.__fetches.push(u);
  const m = u.match(/\/api\/search\?q=([^&]*)&limit=(\d+)$/);
  if (m) {
    const spec = answers.get(decodeURIComponent(m[1])) || { status: 200, body: [] };
    if (spec.gate) await spec.gate;
    if (spec.throws) throw new Error(spec.throws);
    return { ok: spec.status < 400, status: spec.status, statusText: spec.statusText || '',
             json: async () => spec.body };
  }
  return { ok: true, status: 200, json: async () => ({}) };
};

export function row(sessionId, sessionName, snippet, extra) {
  return Object.assign({ message_id: sessionId + ':' + snippet.length, session_id: sessionId,
    session_name: sessionName, role: 'user', content_snippet: snippet, timestamp: null }, extra || {});
}

export const $ = (id) => document.getElementById(id);
export const settle = (ms = 0) => new Promise((r) => setTimeout(r, ms));
/** Past the palette's 300 ms debounce and the answer's promise chain. */
export async function chatsArrive() { await settle(340); await settle(0); await settle(0); }

export function keydown(target, key, mods = {}) {
  const ev = {
    type: 'keydown', key, target, isComposing: false,
    ctrlKey: !!mods.ctrl, altKey: !!mods.alt, shiftKey: !!mods.shift, metaKey: !!mods.meta,
    getModifierState: () => false,
    defaultPrevented: false, propagationStopped: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this.propagationStopped = true; },
    stopImmediatePropagation() { this.propagationStopped = true; },
  };
  target.dispatchEvent(ev);
  return { prevented: ev.defaultPrevented, stopped: ev.propagationStopped };
}

export function type(text) {
  const input = $('search-input');
  input.value = text;
  input.dispatchEvent({ type: 'input', target: input });
}

/** The palette as a person — or a screen reader — would read it. */
export function read() {
  const overlay = $('search-overlay');
  const input = $('search-input');
  const results = $('search-results');
  const groups = results.children.map((g) => {
    const head = $(g.getAttribute('aria-labelledby') || '');
    const first = g.children.find((c) => c.getAttribute('role') === 'option');
    return {
      label: head ? head.textContent : null,
      kind: first ? first.dataset.paletteKind : null,
      role: g.getAttribute('role'),
      headHidden: head ? head.getAttribute('aria-hidden') : null,
      options: g.children.filter((c) => c.getAttribute('role') === 'option').map((o) => ({
        id: o.id,
        kind: o.dataset.paletteKind,
        selected: o.getAttribute('aria-selected'),
        session: o.dataset.session || null,
        label: o.querySelector('.search-palette-label') ? o.querySelector('.search-palette-label').textContent : null,
        detail: o.querySelector('.search-palette-detail') ? o.querySelector('.search-palette-detail').textContent : null,
        snippet: o.querySelector('.search-result-snippet') ? o.querySelector('.search-result-snippet').textContent : null,
        marks: o.querySelectorAll('mark').map((m) => m.textContent),
      })),
    };
  });
  const activeId = input.getAttribute('aria-activedescendant');
  const active = activeId ? $(activeId) : null;
  const markup = results._walk([]).filter((n) => n._html || n._writtenHtml).map((n) => n._html || n._writtenHtml);
  return {
    open: !overlay.classList.contains('hidden'),
    z: overlay.style.zIndex || '',
    focus: document.activeElement ? (document.activeElement.id || document.activeElement.tagName) : null,
    expanded: input.getAttribute('aria-expanded'),
    activeId,
    active: active ? active.readable : (activeId ? '!gone' : null),
    groups,
    labels: groups.map((g) => g.label),
    options: groups.flatMap((g) => g.options.map((o) => o.label || o.snippet)),
    selectedCount: groups.flatMap((g) => g.options).filter((o) => o.selected === 'true').length,
    status: $('search-status') ? $('search-status').textContent : null,
    markup,
    clicked: globalThis.__clicked.slice(),
    ran: (globalThis.__ran || []).slice(),
    settings: globalThis.__settingsOpened.slice(),
    skills: globalThis.__skillsOpened.slice(),
    selected: globalThis.__selected.slice(),
    fetches: globalThis.__fetches.slice(),
    message: $('message').value,
  };
}
"""


def _specifier(name: str) -> str:
    """The one specifier this tree imports `name` with.

    A module fetched under two URLs is two modules (`B58`), so a case that
    imports `modalManager.js` bare would register windows with a copy the
    palette never reads. `.pantheon/check-specifiers.py` holds the tree to one
    URL per module, so the first `static/js` import found is the one.
    """
    pattern = re.compile(r"from '\./(" + re.escape(name) + r"(?:\?[^']*)?)'")
    for path in sorted(JS.glob("*.js")):
        m = pattern.search(path.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    raise AssertionError(f"nothing in static/js imports {name}")


#: Real modules every sandbox carries whether or not the module under test
#: imports them: the registries the cases read, and the Ctrl+K dispatcher.
#: Brought in explicitly so the same cases can be run against the renderer this
#: row replaced, which imported none of them.
_REAL = ("modalManager.js", "slashAutocomplete.js", "settings/registry.js",
         "settings/search.js", "keyboard-shortcuts.js")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    stubs = dict(_STUBS)
    stubs["slashCommands.js"] = _slash_stub()
    shim = _SHIM.replace("__MARKUP__", json.dumps(_markup()))
    sandbox = _make_sandbox(tmp_path_factory.mktemp("palette"), SEARCH_JS, shim, stubs)
    for rel in _REAL:
        (sandbox / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, sandbox / rel)
        _copy_unstubbed_imports(sandbox, JS / rel, stubs)
    return sandbox


def _preamble() -> str:
    return (
        "import { $, answer, row, settle, chatsArrive, keydown, type, read, document } from './shim.js';\n"
        "const Search = await import('./search-chat.js');\n"
        f"const Modals = await import('./{_specifier('modalManager.js')}');\n"
        "Search.init('');\n"
        "const open = () => { $('message').focus(); Search.openSearch(); };\n"
        "const enter = () => keydown($('search-input'), 'Enter');\n"
    )


def _palette(sandbox, script):
    return _run(sandbox, _preamble(), script)


def _chats(groups):
    """The chat half of a reading. A Settings panel's harvested control text
    may legitimately match a word used here, so the chats are picked by kind,
    never by position."""
    return [g for g in groups if g["kind"] == "chat"]


# ── tools: `_AUTO_WIRE`, through the door a person would press ─────────────

def test_a_tool_is_found_by_its_name_and_opened_through_its_own_door(box):
    """`Calendar` is offered under `Tools`, highlighted, and Enter presses the
    rail button `_AUTO_WIRE` names for it — the same `openClosedWindow` the dock
    uses (`P9-11`) — then the overlay goes away."""
    out = _palette(box, """
        open(); type('calendar');
        const before = read();
        enter();
        console.log(JSON.stringify({ before, after: read() }));
    """)
    before, after = out["before"], out["after"]
    assert before["labels"][0] == "Tools"
    assert before["groups"][0]["options"][0]["label"] == "Calendar"
    # `B947` (d): the row also names the key that opens Calendar (the default
    # `open_calendar` binding), so the option reads with it.
    assert before["active"] == "Calendar Ctrl+Alt+C"
    assert after["clicked"] == ["rail-calendar"]
    assert after["open"] is False


def test_the_names_people_learned_still_find_the_tool(box):
    """The Forge's id keeps "cookbook" (`D-2026-09-18-04`) and the Brain's is
    `memory-modal`; someone who learned either word is not told it is gone."""
    out = _palette(box, """
        open(); type('cookbook'); const forge = read().groups[0];
        type('memory'); const brain = read().groups[0];
        console.log(JSON.stringify({ forge, brain }));
    """)
    assert out["forge"]["label"] == "Tools" and out["forge"]["options"][0]["label"] == "Forge"
    assert out["brain"]["label"] == "Tools" and out["brain"]["options"][0]["label"] == "Brain"


def test_a_tool_taken_away_is_not_offered_but_a_collapsed_sidebar_takes_nothing_away(box):
    """An admin's feature flag, a privilege gate and Customize UI all write
    `display: none` on the button itself; the palette offers what a person
    could press. A hidden sidebar or rail is not the button being hidden — it
    is when the palette is most needed."""
    out = _palette(box, """
        open(); type('gallery'); const shown = read().labels;
        $('rail-gallery').style.display = 'none';
        $('tool-gallery-btn').style.display = 'none';
        type('galler'); type('gallery'); const flagged = read().labels;
        $('rail-gallery').style.display = '';
        $('tool-gallery-btn').style.display = '';
        $('sidebar').classList.add('hidden');
        $('icon-rail').style.display = 'none';
        type('galler'); type('gallery'); const collapsed = read().labels;
        console.log(JSON.stringify({ shown, flagged, collapsed }));
    """)
    assert "Tools" in out["shown"]
    assert "Tools" not in out["flagged"]
    assert "Tools" in out["collapsed"]


def test_an_open_window_is_raised_and_a_minimized_one_restored_never_toggled_shut(box):
    """Most doors are toggles: pressing Calendar's button with Calendar up
    closes it. So a window that is already open is raised and nothing is
    pressed, and a minimized one is restored the way its dock chip would."""
    out = _palette(box, """
        const cal = document.createElement('div');
        cal.id = 'calendar-modal'; cal.className = 'modal';
        document.body.appendChild(cal);
        open(); type('calendar'); enter();
        const raised = { clicked: read().clicked, z: cal.style['z-index'] || '', hidden: cal.classList.contains('hidden') };

        const gal = document.createElement('div');
        gal.id = 'gallery-modal'; gal.className = 'modal';
        document.body.appendChild(gal);
        Modals.register('gallery-modal', { railBtnId: 'rail-gallery', sidebarBtnId: 'tool-gallery-btn' });
        Modals.minimize('gallery-modal');
        const minimized = gal.classList.contains('hidden');
        open(); type('gallery'); enter();
        const restored = { clicked: read().clicked, hidden: gal.classList.contains('hidden'),
                           minimized: Modals.isMinimized('gallery-modal') };
        console.log(JSON.stringify({ raised, minimized, restored }));
    """)
    assert out["raised"]["clicked"] == []
    assert out["raised"]["hidden"] is False
    assert out["raised"]["z"] != ""
    assert out["minimized"] is True
    assert out["restored"]["clicked"] == []
    assert out["restored"]["hidden"] is False
    assert out["restored"]["minimized"] is False


# ── settings: the registry's own search, and its admin rule ────────────────

def test_a_settings_panel_comes_from_the_registry_with_its_admin_rule(box):
    """`egress` is a keyword of Networks (`P9-02`), an admin-only panel. Not
    offered to anyone else — the same rule the Settings finder applies — and
    opened for an admin through `settingsModule.open('networks')`, the door
    `/settings networks` and `adminModule.open` use."""
    out = _palette(box, """
        open(); type('egress'); const member = read();
        Search.closeSearch();
        globalThis._isAdmin = true;
        open(); type('egress'); const admin = read();
        enter();
        console.log(JSON.stringify({ member, admin, after: read() }));
    """)
    assert "Settings" not in out["member"]["labels"]
    group = out["admin"]["groups"][out["admin"]["labels"].index("Settings")]
    assert group["options"][0]["label"] == "Networks"
    assert group["options"][0]["detail"] == "Administration"
    assert out["after"]["settings"] == ["networks"]
    assert out["after"]["open"] is False


def test_a_panel_is_found_by_the_words_on_its_controls(box):
    """The palette reads the Settings finder's harvested control text
    (`controlTextFor`, `H15`) rather than a list of its own, so the two find the
    same panels. "emoji" is in no label and no keyword — the registry alone
    finds nothing — and it is on one of Appearance's toggles, so Appearance is
    what comes back."""
    out = _palette(box, """
        const { searchSettingsPanels } = await import('./settings/registry.js');
        const registryAlone = searchSettingsPanels('emoji', { isAdmin: false }).map((p) => p.id);
        open(); type('emoji');
        console.log(JSON.stringify({ registryAlone, r: read() }));
    """)
    assert out["registryAlone"] == []
    group = out["r"]["groups"][out["r"]["labels"].index("Settings")]
    assert [o["label"] for o in group["options"]] == ["Appearance"]


def test_settings_itself_is_offered_and_opens_through_settings_open(box):
    """`_AUTO_WIRE` gives the Settings window a door no template renders
    (`tool-settings-btn`), so reading the map alone would leave Settings out.
    It is offered, and it opens through `settingsModule.open()` — what the cog
    and the rail gear call."""
    out = _palette(box, """
        open(); type('settings'); const found = read(); enter();
        console.log(JSON.stringify({ found, after: read() }));
    """)
    assert out["found"]["groups"][0]["label"] == "Tools"
    assert out["found"]["groups"][0]["options"][0]["label"] == "Settings"
    assert out["after"]["settings"] == [None]
    assert out["after"]["clicked"] == []


def test_a_minimized_settings_is_restored_not_opened_a_second_way(box):
    """`B943`. Settings opens through its door function — but a minimized one
    is restored, the way its chip and (now) its cog restore it. Opened through
    `settingsModule.open()` it showed the window and stayed marked minimized,
    its chip still in the dock."""
    out = _palette(box, """
        const modal = $('settings-modal');
        modal.classList.remove('hidden');
        Modals.minimize('settings-modal');
        const before = Modals.isMinimized('settings-modal');
        open(); type('settings'); enter();
        console.log(JSON.stringify({ before, after: read(), minimized: Modals.isMinimized('settings-modal'),
                                     hidden: modal.classList.contains('hidden') }));
    """)
    assert out["before"] is True
    assert out["minimized"] is False
    assert out["hidden"] is False
    assert out["after"]["settings"] == [], "settings.js was asked to open a minimized window"
    assert out["after"]["clicked"] == []


def test_the_skills_window_opens_through_its_own_door_and_not_the_brains(box):
    """`P9-06` gave Skills a window of its own with no rail or sidebar button
    (`_AUTO_WIRE` says `{ rail: null, sidebar: null }`). Every way in — the
    Brain's launcher card (`data-open-skills="browse"`), a chat's skills pill —
    calls `openSkillsWindow`; so does the palette. Pressing the Brain's button
    would open the Brain."""
    out = _palette(box, """
        open(); type('skills'); const found = read(); enter();
        console.log(JSON.stringify({ found, after: read() }));
    """)
    tools = out["found"]["groups"][0]
    assert tools["label"] == "Tools" and tools["options"][0]["label"] == "Skills"
    assert out["after"]["skills"] == ["browse"]
    assert out["after"]["clicked"] == []
    assert out["after"]["open"] is False


# ── commands: into the message box, never run ──────────────────────────────

def test_a_command_goes_into_the_message_box_and_nothing_runs_it(box):
    """Enter on `/rename` does what picking it from the composer's own `/`
    popup does: the box reads `/rename ` with the caret after it. No handler in
    the real `COMMANDS` table ran — the composer's submit path, with its own
    checks, is still the only thing that runs a command."""
    out = _palette(box, """
        open(); type('rename'); const found = read(); enter();
        console.log(JSON.stringify({ found, after: read() }));
    """)
    group = out["found"]["groups"][out["found"]["labels"].index("Commands")]
    assert group["options"][0]["label"] == "/rename"
    assert group["options"][0]["detail"] == "Rename current chat"
    after = out["after"]
    assert after["message"] == "/rename "
    assert after["focus"] == "message"
    assert after["open"] is False
    assert after["ran"] == []


def test_a_draft_in_the_message_box_is_never_overwritten(box):
    """Half-written words in the composer are the person's work. Choosing a
    command leaves them exactly as they were, keeps the palette open and says
    why nothing happened."""
    out = _palette(box, """
        $('message').value = 'half a thought about';
        open(); type('rename'); enter();
        console.log(JSON.stringify(read()));
    """)
    assert out["message"] == "half a thought about"
    assert out["open"] is True
    assert "draft" in out["status"]
    assert "/rename" in out["status"]


def test_only_commands_the_composer_offers_are_offered(box):
    """One catalogue (`slashCatalog`, the `/` popup's own list): hidden
    commands such as `/find` and `/help` and the easter eggs stay hidden, and
    every command the palette draws is one the popup would draw."""
    out = _palette(box, """
        const { slashCatalog } = await import('./slashAutocomplete.js');
        const catalog = slashCatalog().map((c) => c.token);
        const seen = new Set();
        for (const q of ['find', 'help', 'fortune', 'chats', 'toggle', 'memory', 'tour', 'setup']) {
          open(); type(q);
          for (const g of read().groups) if (g.label === 'Commands') g.options.forEach((o) => seen.add(o.label));
          Search.closeSearch();
        }
        console.log(JSON.stringify({ catalog, seen: [...seen] }));
    """)
    assert out["seen"], "no commands were offered at all"
    assert set(out["seen"]) <= set(out["catalog"])
    for hidden in ("/find", "/help", "/fortune", "/toggle"):
        assert hidden not in out["seen"]


def test_a_bare_slash_asks_for_the_commands(box):
    """`/` is how a command starts everywhere else in this product. Typed alone
    it names no tool and no panel, so it offers commands and nothing else —
    rather than every tool at once, which a word-start match of "nothing"
    would otherwise give."""
    out = _palette(box, """
        open(); type('/');
        console.log(JSON.stringify(read()));
    """)
    assert out["labels"] == ["Commands"]
    assert all(o.startswith("/") for o in out["options"])


def test_a_word_matches_the_start_of_a_word(box):
    """Measured first with substrings: "cal" offered `/setup` and `/usage`,
    whose help says "local". A typed word has to start a word of the entry."""
    out = _palette(box, """
        open(); type('cal');
        console.log(JSON.stringify(read()));
    """)
    offered = out["options"]
    assert "Calendar" in offered
    assert "/event" in offered
    assert "/setup" not in offered and "/usage" not in offered


# ── keyboard alone, and announced ──────────────────────────────────────────

def test_the_arrows_move_one_active_option_and_the_box_names_it(box):
    """The caret stays in the box; the highlighted option is the one
    `aria-activedescendant` names, exactly one is `aria-selected`, and the
    arrows stop at the ends rather than wrapping away."""
    out = _palette(box, """
        open(); type('cal');
        const trail = [];
        const snap = () => { const r = read(); trail.push({ active: r.active, activeId: r.activeId, count: r.selectedCount, focus: r.focus }); };
        snap(); keydown($('search-input'), 'ArrowDown'); snap();
        keydown($('search-input'), 'ArrowUp'); snap();
        keydown($('search-input'), 'ArrowUp'); snap();
        const n = read().groups.flatMap((g) => g.options).length;
        for (let i = 0; i < n + 3; i++) keydown($('search-input'), 'ArrowDown');
        snap();
        const last = read().groups.flatMap((g) => g.options).slice(-1)[0].id;
        console.log(JSON.stringify({ trail, last, expanded: read().expanded,
          roles: { input: $('search-input').getAttribute('role'), list: $('search-results').getAttribute('role'),
                   controls: $('search-input').getAttribute('aria-controls') },
          groups: read().groups.map((g) => [g.role, g.headHidden]) }));
    """)
    trail = out["trail"]
    calendar = "Calendar Ctrl+Alt+C"   # `B947` (d): the row names its key
    assert trail[0]["active"] == calendar
    assert trail[1]["active"] != calendar
    assert trail[2]["active"] == calendar and trail[3]["active"] == calendar
    assert trail[4]["activeId"] == out["last"]
    assert all(t["count"] == 1 and t["focus"] == "search-input" for t in trail)
    assert out["expanded"] == "true"
    assert out["roles"] == {"input": "combobox", "list": "listbox", "controls": "search-results"}
    assert all(g == ["group", "true"] for g in out["groups"])


def test_the_highlight_stays_put_when_the_chats_arrive(box):
    """The commands are drawn at once and the chats 300 ms later, below them.
    A person who has already arrowed to a row must still be on that row when
    the chats land — not thrown back to the top under their finger."""
    out = _palette(box, """
        answer('note', { status: 200, body: [row('s1', 'Journal', 'a note to self')] });
        open(); type('note');
        keydown($('search-input'), 'ArrowDown');
        const before = read().active;
        await chatsArrive();
        const after = read();
        console.log(JSON.stringify({ before, active: after.active, chats: after.groups.filter((g) => g.kind === 'chat').length }));
    """)
    assert out["chats"] == 1
    assert out["before"] and out["active"] == out["before"]


def test_escape_closes_hands_focus_back_and_goes_no_further(box):
    """Measured before this row: Escape left focus on `<body>`, and the same
    press bubbled on to `cancel: 'escape'` — `abortCurrentRequest()` — so looking
    something up stopped a reply that was streaming behind the box."""
    out = _palette(box, """
        open(); type('cal');
        const esc = keydown($('search-input'), 'Escape');
        console.log(JSON.stringify({ esc, after: read(),
          active: $('search-input').getAttribute('aria-activedescendant') }));
    """)
    assert out["esc"] == {"prevented": True, "stopped": True}
    after = out["after"]
    assert after["open"] is False
    assert after["focus"] == "message"
    assert after["groups"] == []
    assert out["active"] is None


def test_tab_stays_in_the_box(box):
    """The box is the one stop in this dialog; Tab walking into the page behind
    a full-screen backdrop would leave the person somewhere they cannot see."""
    out = _palette(box, """
        open(); type('cal');
        const tab = keydown($('search-input'), 'Tab');
        console.log(JSON.stringify({ tab, focus: read().focus, open: read().open }));
    """)
    assert out["tab"]["prevented"] is True
    assert out["focus"] == "search-input" and out["open"] is True


def test_the_status_line_says_what_was_found(box):
    """`#search-status` is `role="status"` in the markup and says how many
    results there are and which keys work — and, only once the chats have
    answered, that nothing matched."""
    out = _palette(box, """
        open(); type('cal'); const some = read().status;
        type('zzqx'); const pending = read().status;
        await chatsArrive(); const none = read().status;
        console.log(JSON.stringify({ some, pending, none, role: $('search-status').getAttribute('role'),
                                     live: $('search-status').getAttribute('aria-live') }));
    """)
    assert out["role"] == "status" and out["live"] == "polite"
    assert re.match(r"^\d+ results\. ", out["some"]) and "Esc to close" in out["some"]
    assert out["pending"] == ""
    assert out["none"] == "Nothing matches “zzqx”."


# ── text is text ───────────────────────────────────────────────────────────

def test_a_hostile_chat_title_and_snippet_arrive_as_characters(box):
    """A chat title and a message are text somebody — or a model — wrote. They
    reach the palette as characters: the heading reads the markup's own
    letters, and no node under `#search-results` was ever given `innerHTML`."""
    out = _palette(box, """
        answer('needle', { status: 200, body: [
          row('s-evil', '<img src=x onerror=globalThis.__pwned=1>', '<script>globalThis.__pwned=2</script> needle here'),
        ] });
        open(); type('needle'); await chatsArrive();
        console.log(JSON.stringify({ r: read(), pwned: globalThis.__pwned || null }))
    """)
    r = out["r"]
    chats = _chats(r["groups"])
    assert [g["label"] for g in chats] == ["<img src=x onerror=globalThis.__pwned=1>"]
    option = chats[0]["options"][0]
    assert option["snippet"] == "<script>globalThis.__pwned=2</script> needle here"
    assert option["marks"] == ["needle"]
    assert r["markup"] == []
    assert out["pwned"] is None


def test_the_highlight_marks_the_words_not_the_escaping(box):
    """The old renderer ran its highlight over the ESCAPED snippet, so a query
    of "amp" matched inside `&amp;` and the row printed the entity's letters.
    Built from text nodes, "Tom & Jerry" reads "Tom & Jerry" and "amp" marks
    nothing."""
    out = _palette(box, """
        answer('amp', { status: 200, body: [row('s1', 'Cartoons', 'Tom & Jerry')] });
        answer('jer', { status: 200, body: [row('s1', 'Cartoons', 'Tom & Jerry')] });
        open(); type('amp'); await chatsArrive(); const amp = read().groups;
        type('jer'); await chatsArrive(); const jer = read().groups;
        console.log(JSON.stringify({ amp, jer }));
    """)
    amp_row = _chats(out["amp"])[0]["options"][0]
    assert amp_row["snippet"] == "Tom & Jerry" and amp_row["marks"] == []
    assert _chats(out["jer"])[0]["options"][0]["marks"] == ["Jer"]


# ── the chat search, unchanged ─────────────────────────────────────────────

def test_the_chats_still_come_from_the_same_request_and_open_the_same_way(box):
    """The same `/api/search?q=…&limit=20`, once, after the debounce; hits
    grouped under their chat's title; choosing one calls
    `sessionModule.selectSession` and closes the box, as it always did."""
    out = _palette(box, """
        answer('invoice', { status: 200, body: [
          row('s1', 'Accounts', 'the invoice for March'),
          row('s1', 'Accounts', 'second invoice', { role: 'assistant' }),
          row('s2', 'Travel', 'hotel invoice'),
        ] });
        open(); type('invoice');
        const early = read().fetches.filter((u) => u.includes('/api/search'));
        await chatsArrive();
        const found = read();
        const second = found.groups.find((g) => g.kind === 'chat').options[1].id;
        $(second).dispatchEvent({ type: 'click', target: $(second) });
        console.log(JSON.stringify({ early, found, after: read() }));
    """)
    assert out["early"] == []
    found = out["found"]
    assert [u for u in found["fetches"] if "/api/search" in u] == ["/api/search?q=invoice&limit=20"]
    chats = _chats(found["groups"])
    assert [g["label"] for g in chats] == ["Accounts", "Travel"]
    assert [o["session"] for o in chats[0]["options"]] == ["s1", "s1"]
    assert out["after"]["selected"] == ["s1"]
    assert out["after"]["open"] is False


def test_a_late_answer_for_an_older_query_is_dropped(box):
    """The old handler drew whichever answer arrived last, so a slow reply for
    "abc" could land on top of the list for "abcd"."""
    out = _palette(box, """
        let release; const gate = new Promise((r) => { release = r; });
        answer('abc', { status: 200, body: [row('s-old', 'Old chat', 'abc old')], gate });
        answer('abcd', { status: 200, body: [row('s-new', 'New chat', 'abcd new')] });
        open(); type('abc'); await settle(340);
        type('abcd'); await chatsArrive();
        release(); await settle(20);
        console.log(JSON.stringify(read()));
    """)
    assert [g["label"] for g in _chats(out["groups"])] == ["New chat"]


def test_a_chat_search_that_fails_says_so(box):
    """It used to go to `console.error` and leave the list as it was."""
    out = _palette(box, """
        answer('boom', { status: 500, statusText: 'Internal Server Error', body: {} });
        open(); type('boom'); await chatsArrive();
        console.log(JSON.stringify(read()));
    """)
    assert out["status"].startswith("Couldn't search your chats (500 Internal Server Error).")


def test_the_box_draws_above_whatever_window_is_open(box):
    """Measured in the real app before this row: the overlay's stylesheet
    z-index is 300, and both window counters start above it — `ui.js` promotes
    every visible `.modal` from 1000, `modalManager` from 300 — so with
    Calendar open (z 1001) Ctrl+K put the caret in a box hidden behind it. The
    box takes its z from the live stack on every open (`topPortalZ`, `P3-18`);
    the real stack is measured in `test_the_command_palette_in_a_browser.py`."""
    out = _palette(box, """
        globalThis.__topPortalZ = 20077;
        open();
        console.log(JSON.stringify(read()));
    """)
    assert out["z"] == "20077"


# ── the callers ────────────────────────────────────────────────────────────

def test_ctrl_k_still_opens_and_closes_it_through_the_keybind_registry(box):
    """The palette has no key of its own. Ctrl+K was already the `search`
    keybind, already registered, already rebindable in Settings → Shortcuts and
    already opening this overlay; a second key for the same box would be a
    second way in (`Law 14`). Driven through the real dispatcher."""
    out = _palette(box, """
        const KS = await import('./keyboard-shortcuts.js');
        let aborted = 0;
        KS.initKeyboardShortcuts({
          el: (id) => $(id), Storage: {}, sessionModule: {}, uiModule: {},
          chatModule: { abortCurrentRequest() { aborted += 1; } },
          adminModule: {}, settingsModule: {}, searchChatModule: Search.default,
          _closeCompareIfActive: () => false, _deactivateIncognito: () => {}, API_BASE: '',
        });
        $('message').focus();
        keydown(document, 'k', { ctrl: true }); const opened = read();
        keydown(document, 'k', { ctrl: true }); const closed = read();
        console.log(JSON.stringify({ opened, closed, aborted,
          combo: KS.KEYBIND_DEFAULTS.search, label: KS.KEYBIND_LABELS.search }));
    """)
    assert out["opened"]["open"] is True and out["opened"]["focus"] == "search-input"
    assert out["closed"]["open"] is False and out["closed"]["focus"] == "message"
    assert out["combo"] == "ctrl+k"
    assert out["label"] == "Search chats and commands"
    assert out["aborted"] == 0


def test_find_is_not_a_caller_of_the_overlay_and_never_was(box):
    """The brief (and FORBIDDEN.md Part 1) list `/find` among the overlay's
    callers. It is not one: `_cmdSearch` asks `/api/search` itself and replies
    in the chat (`VERIFY-2026-08-27.md:224` said so). Cut out of
    `slashCommands.js` and run, it leaves all three ids exactly as they were."""
    src = SLASH_JS.read_text(encoding="utf-8")
    fn = js_definition(src, src.index("async function _cmdSearch("))
    out = _palette(box, esc_source() + f"""
        const replies = [];
        const slashReply = (t) => replies.push(t);
        const API_BASE = '';
        const _cmdSearch = eval({json.dumps('(' + fn + ')')});
        answer('needle', {{ status: 200, body: [row('s1', 'Accounts', 'a needle')] }});
        const before = read();
        await _cmdSearch(['needle'], {{ esc }});
        const after = read();
        console.log(JSON.stringify({{ before, after, replies,
          input: $('search-input').value, results: $('search-results').children.length }}));
    """)
    assert out["after"]["fetches"] == ["/api/search?q=needle&limit=20"]
    assert len(out["replies"]) == 1 and "Accounts" in out["replies"][0]
    assert out["after"]["open"] is False and out["before"]["open"] is False
    assert out["input"] == "" and out["results"] == 0
