# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B948` — Tab leaves the message box; Plan mode moves to Ctrl+Alt+P.

**What it was.** `initPlanToggle` in `static/app.js` listened for an unmodified
Tab on `#message`, called `preventDefault()` and flipped Plan mode. Measured in
Chromium 2026-09-27 and again on `integrate` for this change: three Tab presses
in the box flipped `#plan-toggle-btn`'s `aria-pressed` false → true → false →
true and the focus never moved, so every control after the box — the model
picker, More tools, Plan, Web, Shell, the context wheel, Agent/Chat, Send — and
anything appended to `<body>` after it, was unreachable by forward Tab. It also
flipped Plan mode when Tab was accepting a slash-command completion (`/sho` +
Tab gave `/shortcuts ` *and* switched Plan mode off), because both listeners sit
on the same element and the first one's `stopPropagation()` cannot stop the
second. The binding was in no Shortcuts panel and no `/shortcuts`.

**What it is.** The owner's decision: Plan mode moves to a modifier shortcut and
Tab moves the focus. The key is `plan_mode: 'ctrl+alt+p'` in the one keybind
registry (`static/js/keyboard-shortcuts.js`, `H19`), so the Shortcuts panel and
`/shortcuts` list it and Settings can rebind it; the dispatcher presses the Plan
button, so the key and the button are one door into `setPlanMode`. The button
names the live key in its title and `aria-keyshortcuts`. Someone who has used
Plan mode is told once, the first time a Tab really leaves the box.

Two halves. Under node, `syncPlanToggle`, `planModeCombo`, `setPlanMode` and
`initPlanToggle` are cut out of the real `app.js` with
`tests/helpers/js_source.js_definition` and run beside the real
`keyboard-shortcuts.js` and `platform.js` over a small DOM with focus, and a
Tab that nothing prevented moves the focus the way a browser's default action
does. In a real headless Chromium, the app is booted out of process (the
fixture `tests/test_the_command_palette_in_a_browser.py` owns) and driven with
real keys: where Tab lands is compared with the next focusable control in the
page's own document order, not with a name written here.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_binding, js_definition
from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_command_palette_in_a_browser import NODE as PW_NODE, _SKIP as PW_SKIP  # noqa: E402
from test_the_command_palette_in_a_browser import app_url  # noqa: E402,F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
APP_JS = ROOT / "static" / "app.js"
KEYS_JS = JS / "keyboard-shortcuts.js"
SETTINGS_JS = JS / "settings.js"

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
needs_browser = pytest.mark.skipif(PW_NODE is None, reason=PW_SKIP or "")

CHORD = {"key": "p", "code": "KeyP", "keyCode": 80, "ctrlKey": True, "altKey": True}
NOTICE = "Plan mode moved to Ctrl+Alt+P - Tab now moves to the next control"

# The four functions, in app.js order. One that a given tree does not have is
# left out rather than failing the cut, so the same cases run against the tree
# before this change and fail on what it did, not on a missing name.
_APP_FUNCTIONS = ("syncPlanToggle", "planModeCombo", "setPlanMode", "initPlanToggle")

_SHIM = r"""
export class Ev {
  constructor(type, init = {}) {
    Object.assign(this, { type, bubbles: true, cancelable: true, key: '', code: '', keyCode: 0,
      ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, isComposing: false,
      repeat: false, defaultPrevented: false, propagationStopped: false }, init);
  }
  preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
  stopPropagation() { this.propagationStopped = true; }
  stopImmediatePropagation() { this.propagationStopped = true; this.immediate = true; }
  getModifierState(m) { return !!(this.modifiers && this.modifiers[m]); }
}
class Target {
  constructor() { this._l = []; this.parentNode = null; }
  addEventListener(type, fn, o) { this._l.push({ type, fn, capture: o === true || !!(o && o.capture) }); }
  removeEventListener(type, fn, o) {
    const c = o === true || !!(o && o.capture);
    this._l = this._l.filter((l) => !(l.type === type && l.fn === fn && l.capture === c));
  }
  _fire(ev, phase) {
    for (const l of [...this._l]) {
      if (l.type !== ev.type || (phase === 'capture' && !l.capture) || (phase === 'bubble' && l.capture)) continue;
      ev.currentTarget = this;
      l.fn.call(this, ev);
      if (ev.immediate) return;
    }
  }
  dispatchEvent(ev) {
    ev.target = this;
    const path = [];
    for (let n = this.parentNode; n; n = n.parentNode) path.push(n);
    for (const n of [...path].reverse()) { n._fire(ev, 'capture'); if (ev.propagationStopped) return !ev.defaultPrevented; }
    this._fire(ev, 'target');
    if (ev.bubbles) for (const n of path) { if (ev.propagationStopped) break; n._fire(ev, 'bubble'); }
    return !ev.defaultPrevented;
  }
}
class ClassList {
  constructor() { this.s = new Set(); }
  add(...c) { c.forEach((x) => this.s.add(x)); }
  remove(...c) { c.forEach((x) => this.s.delete(x)); }
  contains(c) { return this.s.has(c); }
  toggle(c, force) { const on = force === undefined ? !this.s.has(c) : !!force; if (on) this.s.add(c); else this.s.delete(c); return on; }
}
export class El extends Target {
  constructor(tag, id = '', cls = '') {
    super();
    Object.assign(this, { tagName: tag.toUpperCase(), id, attrs: {}, children: [], hidden: false,
      title: '', style: {}, checked: false, disabled: false, value: '' });
    this.classList = new ClassList();
    if (cls) this.classList.add(cls);
  }
  append(child) { child.parentNode = this; this.children.push(child); return child; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  focus() { document.activeElement = this; }
  click() { if (!this.disabled) this.dispatchEvent(new Ev('click')); }
  closest() { return null; }
}
class Doc extends Target {
  constructor() { super(); this.body = new El('body'); this.body.parentNode = this; this.activeElement = this.body; }
  _all(n = this.body, out = []) { out.push(n); n.children.forEach((c) => this._all(c, out)); return out; }
  getElementById(id) { return this._all().find((n) => n.id === id) || null; }
  querySelector(sel) { return sel.startsWith('.') ? this._all().find((n) => n.classList.contains(sel.slice(1))) || null : null; }
  querySelectorAll(sel) {
    const m = /^\[id\$="([^"]+)"\]$/.exec(sel);
    return m ? this._all().filter((n) => n.id.endsWith(m[1])) : [];
  }
}
export const document = new Doc();
globalThis.window = globalThis;
globalThis.document = document;
// `B945`: `initKeyboardShortcuts` listens on `window` too (the stream stop
// decides last). A browser has the method; node's global does not.
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};

// The composer, in document order, as index.html draws it.
const bar = document.body.append(new El('div', '', 'chat-input-bar'));
export const TAB_ORDER = ['message', 'model-picker-btn', 'overflow-plus-btn', 'plan-toggle-btn', 'web-toggle-btn'];
bar.append(new El('textarea', 'message'));
bar.append(new El('button', 'model-picker-btn'));
bar.append(new El('button', 'overflow-plus-btn'));
const planBtn = bar.append(new El('button', 'plan-toggle-btn'));
planBtn.title = 'Plan mode';
planBtn.setAttribute('aria-pressed', 'false');
bar.append(new El('button', 'web-toggle-btn'));
bar.append(new El('input', 'plan-toggle'));
bar.append(new El('div', 'plan-mode-status'));
bar.append(new El('button', 'plan-mode-status-toggle'));
bar.append(new El('input', 'research-toggle'));

/** A key pressed on `target`, then the browser's own default action for Tab
 *  when nothing prevented it — which is exactly what the defect took away. */
export function press(target, init) {
  const ev = new Ev('keydown', init);
  target.dispatchEvent(ev);
  if (ev.key === 'Tab' && !ev.defaultPrevented) {
    const order = TAB_ORDER.map((id) => document.getElementById(id));
    const next = order[order.indexOf(document.activeElement) + (ev.shiftKey ? -1 : 1)];
    if (next) next.focus();
  }
  const a = document.activeElement;
  return { prevented: ev.defaultPrevented, stopped: ev.propagationStopped, focus: a && a.id };
}

let toggles = {};
export function setToggles(t) { toggles = JSON.parse(JSON.stringify(t)); }
export function loadToggleState() { return JSON.parse(JSON.stringify(toggles)); }
export function saveToggleState(s) { toggles = JSON.parse(JSON.stringify(s)); }
export const toasts = [];
export const uiModule = { showToast: (m) => toasts.push(m) };
"""


def _app_functions() -> str:
    src = APP_JS.read_text(encoding="utf-8")
    parts = []
    for name in _APP_FUNCTIONS:
        i = src.find(f"function {name}(")
        if i >= 0:
            parts.append(js_definition(src, i))
    return "\n".join(parts)


def _preamble() -> str:
    return (
        "import { document, Ev, press, setToggles, loadToggleState, saveToggleState,"
        " toasts, uiModule } from './shim.js';\n"
        "import * as KS from './keyboard-shortcuts.js';\n"
        "const { KEYBIND_DEFAULTS, formatKeybind, ariaKeyshortcuts } = KS;\n"
        "const el = (id) => document.getElementById(id);\n"
        "const _syncResearchIndicator = () => {};\n"
        + _app_functions() + "\n"
        "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
        "const plan = () => { const b = el('plan-toggle-btn'); return { pressed: b.getAttribute('aria-pressed'),"
        " title: b.title, keys: b.getAttribute('aria-keyshortcuts'), saved: loadToggleState().plan_mode ?? null }; };\n"
        "function boot(toggles = {}) {\n"
        "  setToggles(toggles);\n"
        "  initPlanToggle();\n"
        "  KS.initKeyboardShortcuts({ el, Storage: {}, sessionModule: null, uiModule, chatModule: null,\n"
        "    adminModule: null, settingsModule: null, searchChatModule: null,\n"
        "    _closeCompareIfActive: () => false, _deactivateIncognito: () => {}, API_BASE: '' });\n"
        "}\n"
        f"const CHORD = {json.dumps(CHORD)};\n"
    )


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    d = tmp_path_factory.mktemp("tabbox")
    (d / "shim.js").write_text(_SHIM, encoding="utf-8")
    (d / "appConfig.js").write_text(
        "export function getSettings() { return Promise.resolve({}); }\n", encoding="utf-8")
    shutil.copy(KEYS_JS, d / "keyboard-shortcuts.js")
    shutil.copy(JS / "platform.js", d / "platform.js")
    return d


def _drive(box: Path, script: str) -> dict:
    return _run(box, _preamble(), script)


# ── Tab ────────────────────────────────────────────────────────────────────

@needs_node
def test_tab_in_the_message_box_moves_on_and_leaves_plan_mode_alone(box):
    """The measurement, three presses. Before: prevented, focus on the box,
    `aria-pressed` false → true → false → true."""
    out = _drive(box, """
        boot();
        const before = plan();
        const presses = [];
        for (let i = 0; i < 3; i++) {
          el('message').focus();
          presses.push({ ...press(el('message'), { key: 'Tab' }), pressed: plan().pressed });
        }
        await tick();
        console.log(JSON.stringify({ before, presses, after: plan(), toasts }));
    """)
    assert out["before"]["pressed"] == "false"
    for p in out["presses"]:
        assert p["prevented"] is False, "Tab in the message box is still taken"
        assert p["stopped"] is False
        assert p["focus"] == "model-picker-btn", "the focus did not reach the next control"
        assert p["pressed"] == "false", "Tab still switches Plan mode"
    assert out["after"]["saved"] is None, "Tab wrote a Plan mode state"
    assert out["toasts"] == []


@needs_node
def test_a_tab_a_completion_keeps_is_not_a_plan_toggle(box):
    """`slashAutocomplete.js` and the ghost completion take Tab while a
    suggestion is up, and are registered after `initPlanToggle`, as in app.js.
    Before, the same press completed the command *and* switched Plan mode."""
    out = _drive(box, """
        boot({ plan_mode: false });
        el('message').addEventListener('keydown', (e) => { if (e.key === 'Tab') e.preventDefault(); });
        el('message').focus();
        const r = press(el('message'), { key: 'Tab' });
        await tick();
        console.log(JSON.stringify({ r, plan: plan(), toasts, told: !!loadToggleState().plan_key_told }));
    """)
    assert out["r"]["focus"] == "message"
    assert out["plan"]["pressed"] == "false", "accepting a completion switched Plan mode"
    assert out["plan"]["saved"] is False
    assert out["toasts"] == [], "a Tab that never left the box told the person Tab leaves it"
    assert out["told"] is False


# ── the key ────────────────────────────────────────────────────────────────

@needs_node
def test_the_chord_is_the_plan_buttons_own_click(box):
    """Through the dispatcher, from inside the message box, and by clicking the
    button — so `setPlanMode`, its toast and its saved state are the button's.
    A held chord (`repeat`) flips once."""
    out = _drive(box, """
        boot();
        let clicks = 0;
        el('plan-toggle-btn').addEventListener('click', () => { clicks += 1; });
        el('message').focus();
        const r1 = press(el('message'), CHORD); const on = plan();
        const held = press(el('message'), { ...CHORD, repeat: true }); const stillOn = plan();
        const r2 = press(el('message'), CHORD); const off = plan();
        console.log(JSON.stringify({ r1, on, held, stillOn, r2, off, clicks, toasts }));
    """)
    assert out["r1"]["prevented"] is True
    assert out["r1"]["focus"] == "message", "the key moved the focus out of the box"
    assert out["on"]["pressed"] == "true" and out["on"]["saved"] is True
    assert out["held"]["prevented"] is True
    assert out["stillOn"]["pressed"] == "true", "a held chord flipped Plan mode back"
    assert out["off"]["pressed"] == "false" and out["off"]["saved"] is False
    assert out["clicks"] == 2, "the key did not go through the Plan button"
    # `P23-04` (CHAT-U-15): the lit chip says it; there is no toast.
    assert out["toasts"] == []


@needs_node
def test_the_button_names_its_key(box):
    out = _drive(box, """
        boot();
        const off = plan();
        el('plan-toggle-btn').click();
        console.log(JSON.stringify({ off, on: plan() }));
    """)
    # `P23-04` (CHAT-U-15): the control's name is its tooltip, on or off.
    assert out["off"]["title"] == "Plan (Ctrl+Alt+P)"
    assert out["off"]["keys"] == "Control+Alt+P"
    assert out["on"]["title"] == "Plan (Ctrl+Alt+P)"
    assert out["on"]["keys"] == "Control+Alt+P"


@needs_node
def test_a_rebound_key_is_the_one_that_works_and_the_one_the_button_names(box):
    """Settings → Shortcuts writes `window._pantheonKeybinds` on save; the
    saved table also arrives after the button is first drawn. The button reads
    the live table when it is pointed at or focused, and an unbound action
    names no key at all."""
    out = _drive(box, """
        boot();
        window._pantheonKeybinds = { ...window._pantheonKeybinds, plan_mode: 'ctrl+alt+l' };
        el('plan-toggle-btn').dispatchEvent(new Ev('pointerenter', { bubbles: false }));
        const named = plan();
        el('message').focus();
        const old = press(el('message'), CHORD); const afterOld = plan().pressed;
        const neu = press(el('message'), { ...CHORD, key: 'l', code: 'KeyL', keyCode: 76 });
        const afterNew = plan().pressed;
        window._pantheonKeybinds = { ...window._pantheonKeybinds, plan_mode: '' };
        el('plan-toggle-btn').dispatchEvent(new Ev('focus', { bubbles: false }));
        const unbound = plan();
        console.log(JSON.stringify({ named, old, afterOld, neu, afterNew, unbound }));
    """)
    assert out["named"]["title"] == "Plan (Ctrl+Alt+L)"
    assert out["named"]["keys"] == "Control+Alt+L"
    assert out["old"]["prevented"] is False and out["afterOld"] == "false"
    assert out["neu"]["prevented"] is True and out["afterNew"] == "true"
    assert out["unbound"]["title"] == "Plan"
    assert out["unbound"]["keys"] is None


# ── telling people ─────────────────────────────────────────────────────────

@needs_node
def test_someone_who_used_plan_mode_is_told_once_when_tab_first_leaves(box):
    out = _drive(box, """
        boot({ mode: 'chat', plan_mode: false });
        el('message').focus();
        const r1 = press(el('message'), { key: 'Tab' });
        await tick();
        const first = [...toasts];
        el('message').focus();
        press(el('message'), { key: 'Tab' });
        await tick();
        console.log(JSON.stringify({ r1, first, all: toasts, state: loadToggleState() }))
    """)
    assert out["r1"]["prevented"] is False and out["r1"]["focus"] == "model-picker-btn"
    assert out["first"] == [NOTICE]
    assert out["all"] == [NOTICE], "the notice came twice"
    assert out["state"]["plan_key_told"] is True
    assert out["state"]["plan_mode"] is False, "telling someone changed their Plan mode"


@needs_node
def test_someone_who_never_used_plan_mode_is_not_told(box):
    out = _drive(box, """
        boot({ mode: 'chat' });
        el('message').focus();
        const r = press(el('message'), { key: 'Tab' });
        await tick();
        console.log(JSON.stringify({ r, toasts, state: loadToggleState() }))
    """)
    assert out["r"]["focus"] == "model-picker-btn"
    assert out["toasts"] == []
    assert "plan_key_told" not in out["state"] and "plan_mode" not in out["state"]


# ── the matcher, the formatters and the registry ───────────────────────────

_MATCH_CASES = [
    # (name, event, combo, is_mac, expected)
    ("linux", {"ctrlKey": True, "altKey": True, "key": "p", "keyCode": 80}, "ctrl+alt+p", False, True),
    # Option composes on a Mac; with Control held nothing is typed.
    ("mac control+option", {"ctrlKey": True, "altKey": True, "key": "π", "keyCode": 80}, "ctrl+alt+p", True, True),
    # Cmd+Option+P is Chrome's Page Setup on a Mac and stays the browser's.
    ("mac cmd+option", {"metaKey": True, "altKey": True, "key": "π", "keyCode": 80}, "ctrl+alt+p", True, False),
    # Option alone types its character.
    ("mac option", {"altKey": True, "key": "π", "keyCode": 80}, "alt+p", True, False),
    # The layout's letter, not the QWERTY position: Dvorak's P key reads L.
    ("mac dvorak", {"ctrlKey": True, "altKey": True, "key": "¬", "keyCode": 76, "code": "KeyP"}, "ctrl+alt+p", True, False),
    ("mac dvorak l", {"ctrlKey": True, "altKey": True, "key": "¬", "keyCode": 76, "code": "KeyP"}, "ctrl+alt+l", True, True),
    ("not a mac", {"ctrlKey": True, "altKey": True, "key": "π", "keyCode": 80}, "ctrl+alt+p", False, False),
    # Windows AltGr (US-International AltGr+P types ö) is still not a shortcut.
    ("altgr", {"ctrlKey": True, "altKey": True, "key": "ö", "keyCode": 80, "altgr": True}, "ctrl+alt+p", False, False),
    ("plain tab", {"key": "Tab", "keyCode": 9}, "ctrl+alt+p", False, False),
]


@needs_node
@pytest.mark.parametrize("name,event,combo,is_mac,expected", _MATCH_CASES, ids=[c[0] for c in _MATCH_CASES])
def test_the_matcher_reads_the_key_a_person_pressed(box, name, event, combo, is_mac, expected):
    ev = {k: v for k, v in event.items() if k != "altgr"}
    out = _drive(box, f"""
        const ev = {{ ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, ...{json.dumps(ev)},
          getModifierState: (m) => m === 'AltGraph' && {json.dumps(bool(event.get("altgr")))} }};
        console.log(JSON.stringify({{ hit: KS._matchesCombo(ev, {json.dumps(combo)}, {json.dumps(is_mac)}) }}));
    """)
    assert out["hit"] is expected


@needs_node
def test_the_key_is_written_the_way_a_person_and_a_screen_reader_read_it(box):
    out = _drive(box, """
        console.log(JSON.stringify({
          text: [KS.formatKeybind('ctrl+alt+p'), KS.formatKeybind('alt+shift+t'), KS.formatKeybind('escape'),
                 KS.formatKeybind(''), KS.formatKeybind(undefined)],
          aria: [KS.ariaKeyshortcuts('ctrl+alt+p'), KS.ariaKeyshortcuts('alt+shift+t'), KS.ariaKeyshortcuts('escape'),
                 KS.ariaKeyshortcuts('ctrl+,'), KS.ariaKeyshortcuts('')],
        }));
    """)
    assert out["text"] == ["Ctrl+Alt+P", "Alt+Shift+T", "Esc", "", ""]
    assert out["aria"] == ["Control+Alt+P", "Alt+Shift+T", "Escape", "Control+,", ""]


@needs_node
def test_plan_mode_is_in_the_registry_and_the_shortcuts_panel_draws_it(box):
    """The registry is the one table (`H19`): a label, a default, and bound by
    the dispatcher rather than left to a surface. The Shortcuts panel draws only
    actions in one of its categories, so the category is part of being listed."""
    settings = SETTINGS_JS.read_text(encoding="utf-8")
    tables = js_binding(settings, "SHORTCUT_CATEGORIES") + "\n" + js_binding(settings, "SHORTCUT_ICONS")
    out = _drive(box, tables + """
        console.log(JSON.stringify({
          combo: KS.KEYBIND_DEFAULTS.plan_mode ?? null, label: KS.KEYBIND_LABELS.plan_mode ?? null,
          localOnly: KS.KEYBIND_LOCAL_ONLY.has('plan_mode'),
          category: (SHORTCUT_CATEGORIES.find((c) => c.keys.includes('plan_mode')) || {}).name || null,
          icon: /^<svg[\\s\\S]*<\\/svg>$/.test(SHORTCUT_ICONS.plan_mode || ''),
          clash: Object.entries(KS.KEYBIND_DEFAULTS).filter(([a, c]) => a !== 'plan_mode' && c === 'ctrl+alt+p').map(([a]) => a),
        }));
    """)
    assert out["combo"] == "ctrl+alt+p"
    assert out["label"] == "Toggle Plan mode"
    assert out["localOnly"] is False
    assert out["category"] == "Tools"
    assert out["icon"] is True
    assert out["clash"] == []


# ── in a real browser ──────────────────────────────────────────────────────

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, serviceWorkers: 'block' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String((e && e.stack) || e)));
  const creds = { username: 'tabkeys', password: 'tab-keys-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.evaluate(() => {
    window.__toasts = [];
    const t = document.getElementById('toast');
    new MutationObserver(() => { const s = t.textContent.trim(); if (s) window.__toasts.push(s); })
      .observe(t, { childList: true, subtree: true, characterData: true });
  });
  const out = { errors };
  const focusId = () => page.evaluate(() => { const a = document.activeElement; return a ? (a.id || a.tagName) : null; });
  const pressed = () => page.evaluate(() => document.getElementById('plan-toggle-btn').getAttribute('aria-pressed'));
  // The next control in the page's own order: focusable, rendered, no positive tabindex.
  out.expectedNext = await page.evaluate(() => {
    const all = [...document.querySelectorAll('a[href],button,input,select,textarea,[tabindex],[contenteditable="true"],summary')]
      .filter((e) => !e.disabled && e.tabIndex >= 0 && !e.closest('[inert]') && e.getClientRects().length
        && getComputedStyle(e).visibility !== 'hidden');
    const n = all[all.indexOf(document.getElementById('message')) + 1];
    return {
      id: n ? n.id : null,
      positive: [...document.querySelectorAll('[tabindex]')].filter((e) => e.tabIndex > 0).length,
    };
  });
  out.button = await page.evaluate(() => {
    const b = document.getElementById('plan-toggle-btn');
    return { title: b.title, keys: b.getAttribute('aria-keyshortcuts') };
  });
  // Tab, three times from the box.
  await page.focus('#message');
  out.tabs = [];
  for (let i = 0; i < 3; i++) { await page.keyboard.press('Tab'); out.tabs.push({ focus: await focusId(), pressed: await pressed() }); }
  out.fromTheBox = [];
  for (let i = 0; i < 3; i++) {
    await page.focus('#message');
    await page.keyboard.press('Tab');
    out.fromTheBox.push({ focus: await focusId(), pressed: await pressed() });
  }
  await page.waitForTimeout(200);
  out.toastsBeforePlan = [...await page.evaluate(() => window.__toasts)];
  // The key, from inside the box.
  await page.focus('#message');
  await page.keyboard.press('Control+Alt+KeyP');
  out.chordOn = { pressed: await pressed(), focus: await focusId() };
  await page.keyboard.press('Control+Alt+KeyP');
  out.chordOff = { pressed: await pressed(), focus: await focusId() };
  // Told once: two Tabs out of the box after using Plan mode.
  for (let i = 0; i < 2; i++) {
    await page.focus('#message');
    await page.keyboard.press('Tab');
    await page.waitForTimeout(300);
  }
  out.toasts = await page.evaluate(() => window.__toasts);
  // A completion keeps its Tab.
  await page.fill('#message', '');
  await page.focus('#message');
  await page.keyboard.type('/sho');
  await page.waitForTimeout(600);
  const before = await pressed();
  await page.keyboard.press('Tab');
  await page.waitForTimeout(200);
  out.completion = { before, after: await pressed(), value: await page.inputValue('#message'), focus: await focusId() };
  // /shortcuts lists it.
  await page.fill('#message', '/shortcuts');
  await page.keyboard.press('Escape');
  await page.focus('#message');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => /Toggle Plan mode/.test(document.getElementById('chat-history').innerText),
                             null, { timeout: 20000 }).catch(() => {});
  out.slash = await page.evaluate(() => document.getElementById('chat-history').innerText
    .split('\n').filter((l) => /Toggle Plan mode/.test(l)).map((l) => l.trim()));
  // The Shortcuts panel draws it, in Tools.
  await page.click('#user-bar-settings');
  await page.waitForTimeout(500);
  await page.click('[data-settings-tab="shortcuts"]');
  await page.waitForTimeout(800);
  out.panel = await page.evaluate(() => {
    const r = document.querySelector('#shortcuts-list .shortcut-row[data-action="plan_mode"]');
    if (!r) return null;
    let c = r.previousElementSibling;
    while (c && !c.classList.contains('shortcut-category')) c = c.previousElementSibling;
    return { label: r.querySelector('.shortcut-label').textContent.trim(),
             keys: [...r.querySelectorAll('.shortcut-key kbd')].map((k) => k.textContent), category: c && c.textContent };
  });
  console.log(JSON.stringify(out));
  if (process.env.TAB_PW_SHOT) await page.screenshot({ path: process.env.TAB_PW_SHOT });
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def run(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("tab-pw") / "tab.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([PW_NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=240, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


@needs_browser
def test_in_a_browser_tab_from_the_message_box_lands_on_the_next_control(run):
    expected = run["expectedNext"]
    assert expected["positive"] == 0, "a positive tabindex makes document order the wrong yardstick"
    assert expected["id"], "the control after the message box has no id to compare"
    for step in run["fromTheBox"]:
        assert step["focus"] == expected["id"], "Tab from the message box did not land on the next control"
        assert step["pressed"] == "false", "Tab switched Plan mode"
    walked = [t["focus"] for t in run["tabs"]]
    assert walked[0] == expected["id"] and len(set(walked)) == 3, f"Tab did not walk on: {walked}"
    assert all(t["pressed"] == "false" for t in run["tabs"])
    assert run["toastsBeforePlan"] == [], "someone who never used Plan mode was told about it"
    assert run["errors"] == []


@needs_browser
def test_in_a_browser_ctrl_alt_p_toggles_the_plan_button(run):
    assert run["button"] == {"title": "Plan (Ctrl+Alt+P)", "keys": "Control+Alt+P"}
    assert run["chordOn"] == {"pressed": "true", "focus": "message"}
    assert run["chordOff"] == {"pressed": "false", "focus": "message"}


@needs_browser
def test_in_a_browser_the_move_is_told_once(run):
    told = [t for t in run["toasts"] if NOTICE in t]
    assert len(told) == 1, run["toasts"]


@needs_browser
def test_in_a_browser_a_completion_keeps_its_tab(run):
    c = run["completion"]
    assert c["value"] == "/shortcuts "
    assert c["focus"] == "message"
    assert c["after"] == c["before"], "accepting a completion switched Plan mode"


@needs_browser
def test_in_a_browser_shortcuts_and_the_panel_list_it(run):
    assert any(line.startswith("Ctrl+Alt+P") and line.endswith("Toggle Plan mode") for line in run["slash"]), run["slash"]
    assert run["panel"] == {"label": "Toggle Plan mode", "keys": ["Ctrl", "Alt", "P"], "category": "Tools"}
