# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-05` — the workstation screen window, driven under node.

The real `static/js/workstationScreen.js`, against the real `modalManager.js`
(the minimized dock — loaded with `test_background_work_dock_js.py`'s shim, as
the palette's tests load it) and the real `workstation.js` (whose confirmation
and reset the window shares), with a recorded `fetch` answering in the shapes
`routes/workstation_routes.py` answers. Only `windowDrag.js` is a stub: it
measures layout a node shim does not have, and is covered by `P10-06`'s tests.

What is pinned, and why each is a defect if it breaks:

  * **frames only while somebody looks** — the window asks for frames while it
    is open and visible, never two at once, stops when the page is hidden, when
    it is minimized to the dock and when it is closed, and starts again when it
    is visible or restored; a frame it already has is asked for by its digest;
  * **coordinates** — a point on the drawn picture becomes the screen's own
    pixel, whatever size the picture is drawn at; off the picture is nothing;
  * **the controls** — *Take over* and *Hand back* drive `control` and swap;
    clicks, double clicks, drags, the right button, the wheel, keys and paste
    reach `input` in order and only while the person holds the screen; keys are
    the workstation's while the picture has the focus, and Shift+Escape gives
    them back; *Reset to clean* asks the panel's own question and does nothing
    on a no; closing while holding hands the screen back, and so does leaving
    the page;
  * **plain words when it cannot** — off, not permitted and down are the
    server's sentence, with no control that cannot work, and it asks again
    slowly until it can;
  * **the doors** — a `[data-open-workstation-screen]` control anywhere opens
    it without folding the card it sits on; the palette offers it; a
    workstation tool card draws the door, a card that ran here does not.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from test_background_work_dock_js import _SHIM as _DOCK_SHIM  # noqa: E402
from test_background_work_dock_js import _STUBS as _DOCK_STUBS  # noqa: E402
from test_the_search_box_is_the_command_palette_js import _palette, box  # noqa: E402,F401
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
MODULE = JS / "workstationScreen.js"
INDEX = ROOT / "static" / "index.html"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

WATCHING = "The agent has the mouse and keyboard. You are watching."
HOLDING = "You have the mouse and keyboard. The agent waits until you hand them back."
BACK = "The agent has the mouse and keyboard again."

_SHIM = _DOCK_SHIM + r"""
// ── `P20-05` additions ─────────────────────────────────────────────────────
globalThis.MutationObserver = class { observe() {} disconnect() {} };
Node.prototype.focus = function () { document.activeElement = this; this.focused = true; };
Node.prototype.closest = function (sel) {
  for (let n = this; n && n.tagName !== '#DOCUMENT'; n = n.parentNode) if (n.matches(sel)) return n;
  return null;
};
// `pagehide` is on `window`; node's global has no event target of its own.
const winListeners = {};
globalThis.addEventListener = (t, fn) => { (winListeners[t] = winListeners[t] || []).push(fn); };
export function fireWindow(type) { (winListeners[type] || []).forEach((fn) => fn({ type })); }

export function ev(type, extra) {
  return Object.assign({
    type, defaultPrevented: false, propagationStopped: false, button: 0, detail: 1,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this.propagationStopped = true; },
    stopImmediatePropagation() { this.propagationStopped = true; },
  }, extra || {});
}
export function fire(node, type, extra) { const e = ev(type, extra); node.dispatchEvent(e); return e; }

// ── a workstation, answering in the routes' shapes ─────────────────────────
export const server = {
  holder: 'agent', frame: 1, calls: [], refuse: null, resetOk: true,
};
const digest = () => String(server.frame).padStart(16, '0');
globalThis.fetch = async (url, opts = {}) => {
  const method = opts.method || 'GET';
  const body = opts.body ? JSON.parse(opts.body) : null;
  server.calls.push({ url, method, body, keepalive: !!opts.keepalive, at: Date.now() });
  const reply = (status, payload) => ({ ok: status >= 200 && status < 300, status,
                                         json: async () => payload });
  const path = String(url).split('?')[0];
  if (server.refuse && path !== '/api/workstation/reset') {
    return reply(server.refuse.status, { detail: server.refuse.detail });
  }
  if (path === '/api/workstation/screen') {
    const held = (String(url).split('if_none_match=')[1] || '');
    if (held === digest()) return reply(304, null);
    return reply(200, { mime: 'image/jpeg', data_b64: 'QUJD' + server.frame, width: 1280,
                        height: 800, digest: digest() });
  }
  if (path === '/api/workstation/control' && method === 'GET') {
    return reply(200, { holder: server.holder,
      sentence: server.holder === 'person' ? '__HOLDING__' : '__WATCHING__' });
  }
  if (path === '/api/workstation/control') {
    server.holder = body.holder;
    return reply(200, { holder: body.holder, since: 1,
      sentence: body.holder === 'person' ? '__HOLDING__' : '__BACK__' });
  }
  if (path === '/api/workstation/input') { server.frame += 1; return reply(200, { ok: true, action: body.action }); }
  if (path === '/api/workstation/reset') {
    server.holder = 'agent'; server.frame += 1;
    return server.resetOk ? reply(200, { ok: true, sentence: 'Your workstation home is back to a clean start.' })
                          : reply(503, { detail: 'The workstation did not answer.' });
  }
  return reply(404, { detail: 'no such route' });
};
export const sent = () => server.calls.filter((c) => c.url === '/api/workstation/input').map((c) => c.body);
export const frames = () => server.calls.filter((c) => c.url.startsWith('/api/workstation/screen'));
export const controls = () => server.calls.filter((c) => c.url === '/api/workstation/control' && c.method === 'POST');
export const settle = (ms = 30) => new Promise((r) => setTimeout(r, ms));

/** What a person reads off the window. */
export function read(mod) {
  const w = mod._test.win();
  if (!w) return { open: false, inBody: !!document.getElementById('workstation-screen-modal') };
  return {
    open: true,
    inBody: document.getElementById('workstation-screen-modal') === w.modal,
    count: document.querySelectorAll('.wsv-modal').length,
    state: w.status.dataset.state,
    status: w.statusText.textContent,
    take: !w.take.hidden, give: !w.give.hidden, reset: !w.reset.hidden,
    stage: !w.stage.hidden,
    hint: w.hint.hidden ? null : w.hint.textContent,
    src: w.img.src || '',
    role: w.screen.getAttribute('role'),
    holdingRing: w.screen.classList.contains('wsv-holding'),
    focus: document.activeElement === w.screen ? 'screen'
      : document.activeElement === w.give ? 'give'
      : document.activeElement === w.take ? 'take' : null,
  };
}
""".replace("__HOLDING__", HOLDING).replace("__WATCHING__", WATCHING).replace("__BACK__", BACK)

_STUBS = dict(_DOCK_STUBS)
_STUBS.update({
    "windowDrag.js": (
        "globalThis.__drag = [];\n"
        "export function makeWindowDraggable(modal, o) { globalThis.__drag.push({ id: modal.id,\n"
        "  header: !!o.header, content: !!o.content }); }\n"
    ),
    "ui.js": ui_default_stub(
        "styledConfirm: async (message, opts) => {\n"
        "    (globalThis.__confirms = globalThis.__confirms || []).push({ message, opts });\n"
        "    return globalThis.__confirmAnswer !== false;\n"
        "  },\n"
        "  copyToClipboard: (t) => { (globalThis.__copied = globalThis.__copied || []).push(t); },\n"
        "  showToast: () => {}, showError: () => {},"),
    "appConfig.js": "export function invalidateSettings() {}\n",
})

# The specifier the window itself imports `modalManager.js` by, read from the
# module — so the harness shares that one module instance, and a cache-buster
# bump does not break this file (a test that names a buster tests the buster).
_MODALS_SPEC = re.search(r"""['"](\./modalManager\.js[^'"]*)['"]""",
                         (ROOT / "static" / "js" / "workstationScreen.js").read_text(
                             encoding="utf-8")).group(1)

_PREAMBLE = (
    "import { document, fire, ev, server, sent, frames, controls, settle, read, fireWindow }"
    " from './shim.js';\n"
    "const mod = await import('./workstationScreen.js');\n"
    f"const Modals = await import('{_MODALS_SPEC}');\n"
    "Object.assign(mod._test.TIMING, { FRAME_MS: 15, HOLDER_MS: 60, RETRY_MS: 40,\n"
    "  AFTER_INPUT_MS: 5, CLICK_SETTLE_MS: 25, TYPE_FLUSH_MS: 10, WHEEL_FLUSH_MS: 10 });\n"
    "const ID = 'workstation-screen-modal';\n"
    "const rect = { left: 100, top: 50, width: 640, height: 400, right: 740, bottom: 450 };\n"
    "const drawn = () => { mod._test.win().img.getBoundingClientRect = () => rect; };\n"
    "const open = async () => { mod.openWorkstationScreen(); drawn(); await settle(60); };\n"
    "const take = async () => { await mod.takeOver(); await settle(20); };\n"
    "const screen = () => mod._test.win().screen;\n"
    "const click = (x, y) => { fire(screen(), 'pointerdown', { clientX: x, clientY: y });\n"
    "  fire(screen(), 'pointerup', { clientX: x, clientY: y }); };\n"
    "const key = (k, mods = {}) => fire(screen(), 'keydown', { key: k, ctrlKey: !!mods.ctrl,\n"
    "  altKey: !!mods.alt, shiftKey: !!mods.shift, metaKey: !!mods.meta });\n"
    # Past the click, typing and wheel timers (25/10/10 ms here), then the sends
    # they queued — twice, so a send queued while the first wait ran is in too.
    "const done = async () => { await settle(120); await mod._test.settled();\n"
    "  await settle(10); await mod._test.settled(); };\n"
    # The window polls on a timer for as long as it is open, so a case ends the
    # process once it has said what it saw (stdout to a pipe is synchronous on
    # Linux, so the line is written first).
    "const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("workstation-screen"), MODULE, _SHIM, _STUBS)


def _window(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


# ── coordinates and keys: the pure parts ─────────────────────────────────────

@pytest.mark.parametrize("client,expected", [
    ((100, 50), {"x": 0, "y": 0}),            # the picture's top-left corner
    ((420, 250), {"x": 640, "y": 400}),        # its middle is the screen's middle
    ((739.9, 449.9), {"x": 1279, "y": 799}),   # the last pixel
    ((740, 450), {"x": 1279, "y": 799}),       # the far edge stays on the screen
    ((101, 51), {"x": 2, "y": 2}),             # one drawn pixel is two screen pixels here
    ((99, 60), None), ((300, 49), None), ((741, 60), None), ((300, 451), None),
])
def test_a_point_on_the_drawn_picture_is_the_screens_own_pixel(sandbox, client, expected):
    out = _window(sandbox, f"""
        out({{ p: mod.mapPoint({client[0]}, {client[1]}, rect, 1280, 800) }});
    """)
    assert out["p"] == expected


def test_the_mapping_follows_the_drawn_size_and_the_frames_size(sandbox):
    out = _window(sandbox, """
        out({
          full: mod.mapPoint(640, 400, { left: 0, top: 0, width: 1280, height: 800 }, 1280, 800),
          big: mod.mapPoint(1280, 800, { left: 0, top: 0, width: 2560, height: 1600 }, 1280, 800),
          other: mod.mapPoint(50, 50, { left: 0, top: 0, width: 100, height: 100 }, 1024, 768),
          none: mod.mapPoint(1, 1, { left: 0, top: 0, width: 0, height: 0 }, 1280, 800),
          noRect: mod.mapPoint(1, 1, null, 1280, 800),
        });
    """)
    assert out == {"full": {"x": 640, "y": 400}, "big": {"x": 640, "y": 400},
                   "other": {"x": 512, "y": 384}, "none": None, "noRect": None}


@pytest.mark.parametrize("event,expected", [
    ({"key": "a"}, {"action": "type", "text": "a"}),
    ({"key": "A", "shiftKey": True}, {"action": "type", "text": "A"}),
    ({"key": "é"}, {"action": "type", "text": "é"}),
    ({"key": " "}, {"action": "type", "text": " "}),
    ({"key": "Enter"}, {"action": "key", "keys": "Return"}),
    ({"key": "Backspace"}, {"action": "key", "keys": "BackSpace"}),
    ({"key": "Tab"}, {"action": "key", "keys": "Tab"}),
    ({"key": "Tab", "shiftKey": True}, {"action": "key", "keys": "shift+Tab"}),
    ({"key": "Escape"}, {"action": "key", "keys": "Escape"}),
    ({"key": "ArrowLeft"}, {"action": "key", "keys": "Left"}),
    ({"key": "PageDown"}, {"action": "key", "keys": "Next"}),
    ({"key": "F5"}, {"action": "key", "keys": "F5"}),
    ({"key": "l", "ctrlKey": True}, {"action": "key", "keys": "ctrl+l"}),
    ({"key": "T", "ctrlKey": True, "shiftKey": True}, {"action": "key", "keys": "ctrl+shift+t"}),
    ({"key": "Tab", "altKey": True}, {"action": "key", "keys": "alt+Tab"}),
    ({"key": "-", "ctrlKey": True}, {"action": "key", "keys": "ctrl+minus"}),
    ({"key": "c", "metaKey": True}, {"action": "key", "keys": "super+c"}),
    ({"key": "@", "ctrlKey": True, "altKey": True, "altGraph": True}, {"action": "type", "text": "@"}),
    ({"key": "Shift", "shiftKey": True}, None),
    ({"key": "Control", "ctrlKey": True}, None),
    ({"key": "Dead"}, None),
    ({"key": "a", "isComposing": True}, None),
    ({"key": "MediaPlayPause"}, None),
])
def test_a_key_is_the_protocols_input(sandbox, event, expected):
    alt_graph = event.pop("altGraph", False)
    out = _window(sandbox, f"""
        const e = Object.assign({json.dumps(event)},
          {{ getModifierState: (m) => m === 'AltGraph' && {json.dumps(alt_graph)} }});
        out({{ a: mod.keyAction(e) }});
    """)
    assert out["a"] == expected
    if expected and expected["action"] == "key":
        # The daemon's key syntax (`agentd._KEYS_RE`), so nothing is refused for its shape.
        assert re.fullmatch(r"[A-Za-z0-9_+\-]{1,64}", expected["keys"])


@pytest.mark.parametrize("delta,mode,clicks", [
    (100, 0, 1), (250, 0, 2), (-300, 0, -3), (30, 0, 1), (-1, 0, -1), (0, 0, 0),
    (3, 1, 1), (9, 1, 3), (1, 2, 3), (99999, 0, 50), (-99999, 0, -50),
])
def test_a_wheel_turn_is_whole_clicks_within_the_bound(sandbox, delta, mode, clicks):
    assert _window(sandbox, f"out({{ c: mod.wheelClicks({delta}, {mode}) }});")["c"] == clicks


# ── opening, and frames only while somebody looks ────────────────────────────

def test_opening_builds_one_window_in_the_dock_and_shows_the_screen(sandbox):
    out = _window(sandbox, """
        await open();
        const first = read(mod);
        mod.openWorkstationScreen();     // a second press raises; it builds nothing
        await settle(30);
        out({ first, again: read(mod), registered: Modals.isRegistered(ID),
              drag: globalThis.__drag, urls: frames().map((c) => c.url).slice(0, 3),
              minimize: !!mod._test.win().header.querySelector('.modal-minimize-btn') });
    """)
    first = out["first"]
    assert first["inBody"] and first["count"] == 1
    assert first["state"] == "up" and first["status"] == WATCHING
    assert first["src"].startswith("data:image/jpeg;base64,QUJD")
    assert (first["take"], first["give"], first["reset"], first["stage"]) == (True, False, True, True)
    assert first["hint"].startswith("Take over to use the mouse and keyboard")
    assert first["role"] == "img"
    assert out["again"]["count"] == 1
    assert out["registered"] is True and out["minimize"] is True
    assert out["drag"] == [{"id": "workstation-screen-modal", "header": True, "content": True}]
    # The first frame is asked for whole; the next by the digest it already has.
    assert out["urls"][0] == "/api/workstation/screen"
    assert out["urls"][1] == "/api/workstation/screen?if_none_match=0000000000000001"


def test_frames_stop_while_the_page_is_hidden_and_start_again_when_it_is_seen(sandbox):
    out = _window(sandbox, """
        await open();
        await settle(150);
        const running = frames().length;
        document.hidden = true;
        await settle(40);
        const atHide = frames().length;
        await settle(150);
        const whileHidden = frames().length;
        document.hidden = false;
        fire(document, 'visibilitychange');
        await settle(80);
        out({ running, atHide, whileHidden, after: frames().length });
    """)
    assert out["running"] >= 3, "frames were not asked for a few times a second"
    assert out["whileHidden"] == out["atHide"], "frames were asked for while nobody could see"
    assert out["after"] > out["whileHidden"]


def test_frames_stop_while_minimized_and_start_again_when_restored(sandbox):
    out = _window(sandbox, """
        await open();
        Modals.minimize(ID);
        await settle(40);
        const atMin = frames().length;
        await settle(150);
        const whileMin = frames().length;
        const chip = !!document.querySelector('.minimized-dock-chip');
        Modals.restore(ID);
        await settle(80);
        out({ atMin, whileMin, after: frames().length, chip, state: read(mod).state });
    """)
    assert out["chip"] is True, "minimized, it is not on the dock"
    assert out["whileMin"] == out["atMin"], "frames were asked for while minimized"
    assert out["after"] > out["whileMin"] and out["state"] == "up"


def test_never_two_frames_at_once(sandbox):
    """A slow workstation is waited for, not stacked up behind."""
    out = _window(sandbox, """
        let open_ = 0, most = 0;
        const real = globalThis.fetch;
        globalThis.fetch = async (url, o) => {
          if (!String(url).startsWith('/api/workstation/screen')) return real(url, o);
          open_ += 1; most = Math.max(most, open_);
          await settle(25);
          try { return await real(url, o); } finally { open_ -= 1; }
        };
        await open();
        for (let i = 0; i < 4; i++) { await mod._test.tick(); }
        await settle(120);
        out({ most });
    """)
    assert out["most"] == 1


def test_closing_stops_the_frames_and_removes_the_window(sandbox):
    out = _window(sandbox, """
        await open();
        mod._test.win().header.querySelector('.close-btn').dispatchEvent(
          { type: 'click', preventDefault() {} });
        await settle(40);
        const atClose = frames().length;
        await settle(120);
        out({ read: read(mod), registered: Modals.isRegistered(ID), atClose,
              after: frames().length, handedBack: controls().length });
    """)
    assert out["read"] == {"open": False, "inBody": False}
    assert out["registered"] is False
    assert out["after"] == out["atClose"]
    assert out["handedBack"] == 0, "nothing was held, so nothing is handed back"


# ── take over, hand back ─────────────────────────────────────────────────────

def test_take_over_and_hand_back_drive_control_and_swap_the_buttons(sandbox):
    out = _window(sandbox, """
        await open();
        await take();
        const held = read(mod);
        await mod.handBack();
        await settle(20);
        out({ held, back: read(mod), controls: controls().map((c) => c.body) });
    """)
    held, back = out["held"], out["back"]
    assert out["controls"] == [{"holder": "person"}, {"holder": "agent"}]
    assert (held["take"], held["give"], held["status"]) == (False, True, HOLDING)
    assert held["role"] == "application" and held["holdingRing"] is True
    assert held["focus"] == "screen", "after taking over, typing goes straight to the picture"
    assert held["hint"].startswith("Your keys go to the workstation")
    assert "Shift+Esc" in held["hint"]
    assert (back["take"], back["give"], back["status"]) == (True, False, BACK)
    assert back["role"] == "img" and back["holdingRing"] is False
    assert back["focus"] == "take"


def test_someone_who_took_over_elsewhere_is_seen_here(sandbox):
    """Who holds it is read again on its own — another tab can take over."""
    out = _window(sandbox, """
        await open();
        server.holder = 'person';
        await settle(150);
        out(read(mod));
    """)
    assert out["give"] is True and out["take"] is False and out["status"] == HOLDING


def test_closing_while_holding_hands_the_screen_back(sandbox):
    out = _window(sandbox, """
        await open();
        await take();
        mod.closeWorkstationScreen();
        await settle(30);
        out({ last: controls().slice(-1)[0], holder: server.holder });
    """)
    assert out["last"]["body"] == {"holder": "agent"} and out["last"]["keepalive"] is True
    assert out["holder"] == "agent"


def test_a_person_who_held_it_through_an_outage_still_hands_it_back(sandbox):
    out = _window(sandbox, """
        await open();
        await take();
        server.refuse = { status: 503, detail: 'The workstation did not answer.' };
        await settle(80);
        const down = read(mod);
        server.refuse = null;
        mod.closeWorkstationScreen();
        await settle(30);
        out({ down, last: controls().slice(-1)[0], holder: server.holder });
    """)
    assert out["down"]["state"] == "down"
    assert out["last"]["body"] == {"holder": "agent"} and out["holder"] == "agent"


def test_leaving_the_page_while_holding_hands_the_screen_back(sandbox):
    out = _window(sandbox, """
        await open();
        fireWindow('pagehide');
        await settle(10);
        const idle = controls().length;
        await take();
        fireWindow('pagehide');
        await settle(10);
        out({ idle, last: controls().slice(-1)[0] });
    """)
    assert out["idle"] == 0, "the screen was handed back by someone who did not hold it"
    assert out["last"]["body"] == {"holder": "agent"} and out["last"]["keepalive"] is True


# ── the person's mouse and keyboard ──────────────────────────────────────────

def test_nothing_is_sent_while_the_agent_has_the_screen(sandbox):
    out = _window(sandbox, """
        await open();
        click(420, 250);
        const k = key('a');
        const w = fire(screen(), 'wheel', { clientX: 420, clientY: 250, deltaY: 300 });
        const m = fire(screen(), 'contextmenu', { clientX: 420, clientY: 250 });
        await done();
        out({ sent: sent(), keyKept: !k.defaultPrevented && !k.propagationStopped,
              wheelKept: !w.defaultPrevented, menuKept: !m.defaultPrevented });
    """)
    assert out["sent"] == []
    assert out["keyKept"] and out["wheelKept"] and out["menuKept"], "the page lost its own input"


def test_a_click_reaches_the_screen_at_the_point_under_the_pointer(sandbox):
    out = _window(sandbox, """
        await open(); await take();
        click(420, 250);
        await done();
        click(739, 449);
        await done();
        click(50, 50);              // off the picture: nothing
        await done();
        out({ sent: sent() });
    """)
    assert out["sent"] == [{"action": "click", "x": 640, "y": 400},
                           {"action": "click", "x": 1278, "y": 798}]


def test_two_quick_clicks_are_a_double_click_three_a_triple_and_a_drag_is_a_drag(sandbox):
    out = _window(sandbox, """
        await open(); await take();
        click(420, 250); click(420, 250);
        await done();
        click(200, 100); click(200, 100); click(200, 100);
        await done();
        fire(screen(), 'pointerdown', { clientX: 120, clientY: 60 });
        fire(screen(), 'pointerup', { clientX: 420, clientY: 250 });
        await done();
        out({ sent: sent() });
    """)
    assert out["sent"] == [
        {"action": "double_click", "x": 640, "y": 400},
        {"action": "triple_click", "x": 200, "y": 100},
        {"action": "drag", "x": 40, "y": 20, "to_x": 640, "to_y": 400},
    ]


def test_the_right_and_middle_buttons_and_the_wheel(sandbox):
    out = _window(sandbox, """
        await open(); await take();
        const m = fire(screen(), 'contextmenu', { clientX: 420, clientY: 250 });
        fire(screen(), 'auxclick', { button: 1, clientX: 100, clientY: 50 });
        const w1 = fire(screen(), 'wheel', { clientX: 420, clientY: 250, deltaY: 200, deltaX: 0, deltaMode: 0 });
        fire(screen(), 'wheel', { clientX: 420, clientY: 250, deltaY: 100, deltaX: 0, deltaMode: 0 });
        await done();
        out({ sent: sent(), menuStopped: m.defaultPrevented, wheelStopped: w1.defaultPrevented });
    """)
    assert out["sent"] == [
        {"action": "right_click", "x": 640, "y": 400},
        {"action": "middle_click", "x": 0, "y": 0},
        {"action": "scroll", "x": 640, "y": 400, "dx": 0, "dy": 3},
    ]
    assert out["menuStopped"] and out["wheelStopped"], "the page's own menu or scroll ran too"


def test_keys_reach_the_workstation_in_order_and_not_the_page(sandbox):
    out = _window(sandbox, """
        await open(); await take();
        const keys = [key('l', { ctrl: true }), key('l'), key('s'), key(' '), key('-'),
                      key('l'), key('a'), key('Tab'), key('Enter')];
        await done();
        out({ sent: sent(), allKept: keys.every((k) => k.defaultPrevented && k.propagationStopped) });
    """)
    assert out["sent"] == [
        {"action": "key", "keys": "ctrl+l"},
        {"action": "type", "text": "ls -la"},
        {"action": "key", "keys": "Tab"},
        {"action": "key", "keys": "Return"},
    ]
    assert out["allKept"], "a key reached the page as well as the workstation"


def test_shift_escape_gives_the_keyboard_back_and_sends_nothing(sandbox):
    out = _window(sandbox, """
        await open(); await take();
        key('x');
        const e = key('Escape', { shift: true });
        await done();
        out({ sent: sent(), stopped: e.defaultPrevented, read: read(mod) });
    """)
    assert out["sent"] == [{"action": "type", "text": "x"}], "typed text was lost or Escape sent"
    assert out["stopped"] and out["read"]["focus"] == "give"
    assert out["read"]["hint"].startswith("Click the picture, then type")


def test_a_paste_is_typed(sandbox):
    out = _window(sandbox, """
        await open(); await take();
        const e = fire(screen(), 'paste', { clipboardData: { getData: (t) => t === 'text/plain' ? 'echo hi\\n' : '' } });
        await done();
        out({ sent: sent(), stopped: e.defaultPrevented });
    """)
    assert out["sent"] == [{"action": "type", "text": "echo hi\n"}] and out["stopped"]


def test_a_refused_input_is_said_in_the_servers_words(sandbox):
    out = _window(sandbox, """
        await open(); await take();
        const real = globalThis.fetch;
        globalThis.fetch = async (url, o) => (url === '/api/workstation/input'
          ? { ok: false, status: 400, json: async () => ({ detail: 'At most 20,000 characters at a time.' }) }
          : real(url, o));
        key('z');
        await done();
        out(read(mod));
    """)
    assert out["status"] == "At most 20,000 characters at a time."


# ── reset ────────────────────────────────────────────────────────────────────

def test_reset_asks_the_panels_own_question_and_does_nothing_on_a_no(sandbox):
    out = _window(sandbox, """
        await open();
        globalThis.__confirmAnswer = false;
        const no = await mod.resetToClean();
        const afterNo = server.calls.filter((c) => c.url === '/api/workstation/reset').length;
        globalThis.__confirmAnswer = true;
        server.holder = 'person';
        await take();
        const yes = await mod.resetToClean();
        await settle(80);
        const panel = await import('./workstation.js');
        globalThis.__confirmAnswer = false;
        await panel.confirmAndResetMine();
        out({ no, afterNo, yes, read: read(mod), confirms: globalThis.__confirms,
              resets: server.calls.filter((c) => c.url === '/api/workstation/reset').length });
    """)
    assert out["no"] is False and out["afterNo"] == 0
    assert out["yes"] is True and out["resets"] == 1
    assert len(out["confirms"]) == 3
    window_q, panel_q = out["confirms"][0], out["confirms"][2]
    assert window_q == panel_q, "the window asks something other than the panel"
    assert "Nobody else's home is touched" in window_q["message"]
    assert window_q["opts"]["danger"] is True
    # The daemon forgot who held it: the window reads it again and shows the agent.
    assert out["read"]["take"] is True and out["read"]["give"] is False


def test_a_reset_that_fails_is_said(sandbox):
    out = _window(sandbox, """
        await open();
        server.resetOk = false;
        const ok = await mod.resetToClean();
        out({ ok, status: read(mod).status });
    """)
    assert out["ok"] is False and out["status"] == "The workstation did not answer."


# ── when it cannot ───────────────────────────────────────────────────────────

def test_a_workstation_that_stops_answering_takes_its_last_picture_with_it(sandbox):
    out = _window(sandbox, """
        await open();
        const up = read(mod);
        server.refuse = { status: 503, detail: 'The workstation did not answer.' };
        await settle(80);
        const down = read(mod);
        server.refuse = null;
        mod._test.TIMING.RETRY_MS = 20;
        await settle(150);
        out({ up, down, back: read(mod) });
    """)
    assert out["up"]["stage"] is True
    assert out["down"]["stage"] is False and out["down"]["status"] == "The workstation did not answer."
    assert out["back"]["stage"] is True and out["back"]["status"] == WATCHING


@pytest.mark.parametrize("status,state,detail", [
    (403, "not_permitted", "Your account may not use the workstation. An admin can allow it in "
                           "Settings → Users."),
    (409, "off", "The workstation is switched off. An admin turns it on in Settings → Workstation."),
    (503, "down", "The workstation at http://workstation:7040 did not answer (ConnectError). "
                  "Is it running?"),
])
def test_when_it_cannot_it_says_so_plainly_offers_nothing_and_asks_again_slowly(
        sandbox, status, state, detail):
    out = _window(sandbox, f"""
        mod._test.TIMING.RETRY_MS = 150;
        server.refuse = {{ status: {status}, detail: {json.dumps(detail)} }};
        await open();
        const refused = read(mod);
        await settle(400);
        const asked = frames().map((c) => c.at);
        server.refuse = null;
        await settle(260);
        out({{ refused, asked, recovered: read(mod) }});
    """)
    refused = out["refused"]
    assert refused["state"] == state and refused["status"] == detail
    assert (refused["take"], refused["give"], refused["reset"], refused["stage"]) == (
        False, False, False, False)
    assert refused["hint"] is None
    # Start to start, a refusal is asked again no sooner than `RETRY_MS` (150 in
    # the case; a frame is 15). A timer can fire late under load, never early.
    gaps = [b - a for a, b in zip(out["asked"], out["asked"][1:])]
    assert len(out["asked"]) >= 2 and min(gaps) >= 140, ("a refusal was asked again at the "
                                                         f"frame rate: {gaps}")
    assert out["recovered"]["state"] == "up" and out["recovered"]["status"] == WATCHING


# ── the doors ────────────────────────────────────────────────────────────────

def _open_screen_button() -> dict:
    """The Settings panel's door, as `index.html` ships it."""
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r"<button\b[^>]*\bid=\"ws-open-screen\"[^>]*>", html)
    assert m, "Settings → Workstation lost its door to the screen"
    return {k: v for k, v in re.findall(r'\s([a-z-]+)(?:="([^"]*)")?', m.group(0)[7:-1])}


def test_any_door_opens_it_without_folding_the_card_it_sits_on(sandbox):
    attrs = _open_screen_button()
    assert "data-open-workstation-screen" in attrs
    out = _window(sandbox, f"""
        const attrs = {json.dumps(attrs)};
        // A tool card's header, as the chat draws it, with its door.
        const card = document.body.appendChild(document.createElement('div'));
        card.className = 'agent-thread-header';
        const door = card.appendChild(document.createElement('button'));
        door.setAttribute('data-open-workstation-screen', '');
        const e = fire(document, 'click', {{ target: door, detail: 0 }});
        await settle(40);
        const fromCard = read(mod);
        const handle = !!mod._test.win();
        mod.closeWorkstationScreen();
        // The Settings panel's button, with the attributes the page gives it.
        const btn = document.body.appendChild(document.createElement('button'));
        for (const [k, v] of Object.entries(attrs)) btn.setAttribute(k, v);
        const e2 = fire(document, 'click', {{ target: btn }});
        await settle(40);
        const fromPanel = read(mod);
        // A click on anything else is not a door.
        mod.closeWorkstationScreen();
        const e3 = fire(document, 'click', {{ target: card }});
        await settle(20);
        out({{ fromCard, stopped: e.propagationStopped, focus: fromCard.focus, handle,
              fromPanel, stopped2: e2.propagationStopped, other: read(mod),
              otherStopped: e3.propagationStopped }});
    """)
    assert out["fromCard"]["open"] and out["stopped"], "the card's fold would have run too"
    assert out["fromCard"]["focus"] == "take", "opened from the keyboard, the focus stayed behind"
    assert out["fromPanel"]["open"] and out["stopped2"]
    assert out["other"]["open"] is False and out["otherStopped"] is False


def test_the_palette_offers_it_and_opens_it_through_its_own_door(box):
    """Found under *Tools* by its name, from `_AUTO_WIRE`/`_LABELS` (the dock's
    own table, `P9-01`), and opened through `openWorkstationScreen` — the
    palette's real sandbox, with the window module standing in as a recorder."""
    sandbox = box
    (sandbox / "workstationScreen.js").write_text(
        "export function openWorkstationScreen() {\n"
        "  globalThis.__wsOpened = (globalThis.__wsOpened || 0) + 1; return true;\n}\n")
    out = _palette(sandbox, """
        open(); type('workstation screen');
        const before = read();
        keydown($('search-input'), 'Enter');
        await settle(20);
        console.log(JSON.stringify({ before, opened: globalThis.__wsOpened || 0, after: read() }));
    """)
    tools = [g for g in out["before"]["groups"] if g["label"] == "Tools"]
    assert tools and tools[0]["options"][0]["label"] == "Workstation screen"
    assert out["opened"] == 1 and out["after"]["open"] is False


# ── the door on a tool card ──────────────────────────────────────────────────

def _door(html: str):
    """The door inside the card's header, if there is one, and its words."""
    # `P23-04` (CHAT-U-4): the header carries `role`, `tabindex` and
    # `aria-expanded` now, so its opening tag is matched, not spelled.
    header = re.split(r'<div class="agent-thread-header"[^>]*>', html, maxsplit=1)[1].split(
        '<div class="agent-thread-content">', 1)[0]
    m = re.search(r'<button type="button" class="agent-thread-ws-door" '
                  r'data-open-workstation-screen title="([^"]*)">.*?</svg>([^<]*)</button>', header)
    return (m.group(1), m.group(2)) if m else None


def test_a_workstation_card_draws_the_door_and_a_card_that_ran_here_does_not(tmp_path):
    from test_the_agents_hands_are_in_the_workstation import _node
    from test_tool_effect_surfaces_js import _copy_unstubbed_imports
    d = tmp_path / "card"
    d.mkdir()
    (d / "ui.js").write_text(ui_default_stub("scrollHistory: () => {},"), encoding="utf-8")
    shutil.copy(JS / "agentThread.js", d / "agentThread.js")
    shutil.copy(JS / "agentTurn.js", d / "agentTurn.js")
    (d / "spinner.js").write_text("export default { create: () => ({}) };\n", encoding="utf-8")
    (d / "chatRenderer.js").write_text(
        "export function buildDiffHtml() { return ''; }\n"
        "export function buildTodoCard() { return ''; }\n"
        "export function demoteSupersededTodoCards() {}\n"
        "export function safeToolScreenshotSrc() { return ''; }\n", encoding="utf-8")
    _copy_unstubbed_imports(d, JS / "agentThread.js", {"ui.js"})
    out = _node(d, """
        const card = (o) => thread.agentThreadNodeHtml(Object.assign({ state: 'done', ok: true }, o));
        console.log(JSON.stringify({
          ranThere: card({ tool: 'bash', ranIn: 'workstation', ranAs: 'pw-ann-1a2b3c4d' }),
          file: card({ tool: 'read_file', ranIn: 'workstation' }),
          computer: card({ tool: 'computer' }),
          computerRunning: card({ tool: 'computer', state: 'running' }),
          ranHere: card({ tool: 'bash' }),
          lookalike: card({ tool: 'bash', ranIn: 'Workstation' }),
          truthy: card({ tool: 'bash', ranIn: true }),
          other: card({ tool: 'web_fetch' }),
        }));
    """)
    title = "Watch the workstation screen, or take it over"
    for key in ("ranThere", "file", "computer", "computerRunning"):
        assert _door(out[key]) == (title, "View screen"), key
    for key in ("ranHere", "lookalike", "truthy", "other"):
        assert "data-open-workstation-screen" not in out[key], key
    # Beside the *workstation* label, which is unchanged.
    assert out["ranThere"].index("agent-thread-where") < out["ranThere"].index("agent-thread-ws-door")


# ── the door in Settings → Workstation ───────────────────────────────────────

@pytest.fixture(scope="module")
def panel_sandbox(tmp_path_factory):
    from test_the_workstation_panel_js import _SHIM as PANEL_SHIM, _panel_nodes
    shim = PANEL_SHIM.replace("__NODES__", json.dumps(_panel_nodes()))
    stubs = {"ui.js": ui_default_stub("styledConfirm: async () => true,\n"
                                      "  showToast: () => {}, showError: () => {},"),
             "appConfig.js": "export function invalidateSettings() {}\n"}
    return _make_sandbox(tmp_path_factory.mktemp("panel-door"), JS / "workstation.js", shim, stubs)


def _panel_status():
    from test_the_workstation_panel_js import NOT_PERMITTED, UP
    return [(UP, True), ({**UP, "state": "down"}, False), ({**UP, "may_use": False}, False),
            (NOT_PERMITTED, False)]


@pytest.mark.parametrize("case", range(4))
def test_the_panels_door_is_offered_on_the_terms_reset_is(panel_sandbox, case):
    """A person who may use it, while it answers — the same two halves as
    *Reset my workstation*, because a door that cannot open is a control left
    dangling (`P20-02`'s rule)."""
    from test_the_workstation_panel_js import _PREAMBLE as PANEL_PREAMBLE, _serving
    status, shown = _panel_status()[case]
    out = _run(panel_sandbox, PANEL_PREAMBLE + f"const st = {json.dumps(status)};\n",
               _serving("st") + """
        await mod.open();
        console.log(JSON.stringify({ door: !byId('ws-open-screen').hidden,
                                     reset: !byId('ws-reset').hidden }));
    """)
    assert out["door"] is shown and out["door"] == out["reset"]

