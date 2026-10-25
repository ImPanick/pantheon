# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P25-06` — the agent browser's window, driven under node.

The real `static/js/browserWindow.js`, with the real `workstationScreen.js`
(whose `mapPoint`, `keyAction` and `wheelClicks` it reuses) and the real
`modalManager.js`, in the workstation screen window's harness, with a fetch
answering in `routes/workstation_routes.py`'s browser shapes.

What is pinned, and why each is a defect if it breaks:

  * **the page, its address and its tabs** are what the server last said;
  * **the address bar** opens what a person typed as their own act — a bare
    name as https, a machine on the network as http, and words that are not
    an address are refused here with a sentence: Pantheon picks no search
    engine for anyone;
  * **watching is not driving while the agent drives** — while a reply runs, a
    click or a key on the page does nothing until *Take over*; then a click
    lands at the page's own pixel, typing is text and Enter is a key, and *Hand
    back* gives it back;
  * **browsing it yourself** (`P25-10`) — while the agent is idle, a click on
    the page takes it and lands; sending a message hands it back; *Point at…*
    and *This page* put a line naming it into the composer, unsent;
  * **watching it think** (`P25-12`) — the reply's reasoning runs in a strip,
    the agent's *why* sits under its words, an inspection is outlined;
  * **nobody is left holding it** — closing the window while holding hands
    the browser back.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from test_the_workstation_screen_window_js import _SHIM as _SCREEN_SHIM, _STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "static" / "js" / "browserWindow.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = _SCREEN_SHIM + r"""
// ── `P25-06`: the browser's two routes ────────────────────────────────────
export const browser = { url: 'https://shop.example/', title: 'Shop', frame: 1,
  tabs: [{ tab: 1, url: 'https://shop.example/', current: true },
         { tab: 2, url: 'https://news.example/', current: false }], acts: [] };
const _screenFetch = globalThis.fetch;
export function fireWin(type, detail) { (winListeners[type] || []).forEach((fn) => fn({ type, detail })); }
globalThis.fetch = async (url, opts = {}) => {
  const path = String(url).split('?')[0];
  if (path !== '/api/workstation/browser') return _screenFetch(url, opts);
  const method = opts.method || 'GET';
  const reply = (status, payload) => ({ ok: status >= 200 && status < 300, status, json: async () => payload });
  server.calls.push({ url, method, body: opts.body ? JSON.parse(opts.body) : null, keepalive: !!opts.keepalive });
  if (method === 'GET') {
    const d = String(browser.frame).padStart(16, '0');
    if ((String(url).split('if_none_match=')[1] || '') === d) return reply(304, null);
    return reply(200, { mime: 'image/png', data_b64: 'UE5H' + browser.frame, width: 1280, height: 800,
                        digest: d, url: browser.url, title: browser.title, tabs: browser.tabs });
  }
  const body = JSON.parse(opts.body);
  browser.acts.push(body);
  if (body.action === 'open') { browser.url = body.url; browser.title = 'Opened'; }
  if (body.action === 'point') {
    return reply(200, { ok: true, action: 'point', url: browser.url, title: browser.title,
      pointed: body.page ? { url: browser.url, title: browser.title, page: true }
        : { url: browser.url, title: browser.title, page: false, tag: 'h1', text: 'Wool & Co', box: [10, 20, 300, 40] } });
  }
  browser.frame += 1;
  return reply(200, { ok: true, action: body.action, url: browser.url, title: browser.title });
};
"""

_MODALS_SPEC = re.search(r"""['"](\./modalManager\.js[^'"]*)['"]""",
                         MODULE.read_text(encoding="utf-8")).group(1)

_PREAMBLE = (
    "import { document, fire, server, settle, browser, fireWindow, fireWin } from './shim.js';\n"
    "const mod = await import('./browserWindow.js');\n"
    "Object.assign(mod._test.TIMING, { FRAME_MS: 15, HOLDER_MS: 40, RETRY_MS: 40,\n"
    "  AFTER_INPUT_MS: 5, TYPE_FLUSH_MS: 10, WHEEL_FLUSH_MS: 10 });\n"
    "const rect = { left: 100, top: 50, width: 640, height: 400, right: 740, bottom: 450 };\n"
    "const win = () => mod._test.win();\n"
    "const open = async () => { mod.openAgentBrowser(); win().img.getBoundingClientRect = () => rect;\n"
    "  await settle(80); };\n"
    # `P26-01`: the window also asks where the page's notes are (`notes`, a
    # read) — not an act on the page, so not counted among them.
    "const acts = () => browser.acts.filter((a) => a.action !== 'notes');\n"
    "const done = async () => { await settle(60); await mod._test.settled(); await settle(10); };\n"
    "const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = _make_sandbox(tmp_path_factory.mktemp("agent-browser"), MODULE, _SHIM, _STUBS)
    shutil.copy(ROOT / "static" / "js" / "workstationScreen.js", d / "workstationScreen.js")
    return d


def _window(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


@pytest.mark.parametrize("typed,address", [
    ("example.org", "https://example.org"), ("https://a.example/x", "https://a.example/x"),
    ("http://nas.lan:8080", "http://nas.lan:8080"), ("192.168.1.5:3000/app", "http://192.168.1.5:3000/app"),
    ("localhost:5173", "http://localhost:5173"), ("wool socks", ""), ("socks", ""), ("", ""),
    ("javascript:alert(1)", ""), ("file:///etc/passwd", "file:///etc/passwd"),  # the server refuses that one
])
def test_what_a_person_types_is_an_address_or_nothing(sandbox, typed, address):
    assert _window(sandbox, f"out({{ a: mod.addressOf({json.dumps(typed)}) }});")["a"] == address


@pytest.mark.parametrize("xdo,keys", [
    ("Return", "enter"), ("ctrl+l", "ctrl+l"), ("shift+Tab", "shift+tab"), ("BackSpace", "backspace"),
    ("super+c", "meta+c"), ("F5", None), ("ctrl+minus", None),
])
def test_a_key_is_named_as_the_browser_names_it(sandbox, xdo, keys):
    assert _window(sandbox, f"out({{ k: mod.browserKeys({json.dumps(xdo)}) }});")["k"] == keys


def test_the_window_draws_the_page_its_address_and_tabs(sandbox):
    out = _window(sandbox, """
        await open();
        const w = win();
        out({ src: w.img.src, address: w.address.value, title: w.title.textContent,
              tabs: w.tabs.querySelectorAll('.abw-tab-pick').map((b) => [b.textContent, b.getAttribute('aria-pressed')]),
              status: w.statusText.textContent, take: !w.take.hidden, give: !w.give.hidden,
              inBody: document.getElementById('agent-browser-modal') === w.modal });
    """)
    assert out["src"].startswith("data:image/png;base64,UE5H")
    assert out["address"] == "https://shop.example/" and out["title"] == "Shop"
    assert out["tabs"] == [["shop.example", "true"], ["news.example", "false"]]
    assert out["status"] == "Your browser, in your workstation." and out["take"] and not out["give"]
    assert out["inBody"] is True


def test_the_address_bar_and_the_buttons_are_the_persons_own_acts(sandbox):
    out = _window(sandbox, """
        await open();
        const w = win();
        w.address.value = 'wool socks';
        fire(w.address.parentNode, 'submit'); await done();
        const refused = w.statusText.textContent;
        w.address.value = 'example.org';
        fire(w.address.parentNode, 'submit'); await done();
        fire(w.back, 'click'); fire(w.reload, 'click'); await done();
        fire(w.tabs.querySelectorAll('.abw-tab-pick')[1], 'click');
        fire(w.tabs.querySelectorAll('.abw-tab-close')[1], 'click');
        fire(w.tabs.querySelectorAll('.abw-tab-new')[0], 'click'); await done();
        out({ refused, acts: acts(), address: w.address.value });
    """)
    assert out["refused"] == "That is not an address. Type one, like example.org."
    assert out["acts"] == [{"action": "open", "url": "https://example.org"}, {"action": "back"},
                           {"action": "reload"}, {"action": "tab_switch", "tab": 2},
                           {"action": "tab_close", "tab": 2}, {"action": "tab_new"}]
    assert out["address"] == "https://example.org", "the page moved, and its address is shown"


def test_watching_is_not_driving_and_taking_over_is(sandbox):
    out = _window(sandbox, """
        await open();
        const w = win();
        fireWin('pantheon:chat-busy-change', { active: true });
        fire(w.page, 'click', { clientX: 420, clientY: 250 });
        fire(w.page, 'keydown', { key: 'a' }); await done();
        const watched = acts().length;
        const busyHint = w.hint.textContent;
        await mod.takeOver(); await settle(20);
        fire(w.page, 'click', { clientX: 420, clientY: 250 });
        fire(w.page, 'keydown', { key: 'h' }); fire(w.page, 'keydown', { key: 'i' });
        await settle(40);
        fire(w.page, 'keydown', { key: 'Enter' });
        fire(w.page, 'keydown', { key: 'F5' }); await done();
        const held = acts();
        const ring = w.stage.classList.contains('abw-held');
        await mod.handBack(); await settle(20);
        out({ watched, busyHint, held, ring, controls: server.calls.filter((c) => c.url === '/api/workstation/control'
              && c.method === 'POST').map((c) => c.body.holder), give: !w.give.hidden });
    """)
    assert out["watched"] == 0, "a click and a key while the agent works reach nothing"
    assert "Take over or Stop" in out["busyHint"]
    assert out["held"] == [{"action": "click", "x": 640, "y": 400}, {"action": "type", "text": "hi"},
                           {"action": "press", "keys": "enter"}], "F5 is not a key the browser route takes"
    assert out["ring"] is True and out["controls"] == ["person", "agent"] and out["give"] is False


def test_browsing_it_yourself_while_the_agent_is_idle(sandbox):
    """`P25-10`. The owner: *"the user can navigate freely and tell the agent
    'This is the page I am talking about'."*"""
    out = _window(sandbox, """
        await open();
        const w = win();
        const idle = mod.agentIdle();
        fire(w.page, 'keydown', { key: 'a' }); await done();
        const keyFirst = acts().length;
        fire(w.page, 'click', { clientX: 420, clientY: 250 }); await done(); await settle(30);
        const clicked = acts();
        const holder = mod._test.state().holder;
        fireWin('pantheon:message-sent', { text: 'this one' }); await settle(60);
        const controls = server.calls.filter((c) => c.url === '/api/workstation/control'
              && c.method === 'POST').map((c) => c.body.holder);
        out({ idle, keyFirst, clicked, holder, controls, after: mod._test.state().holder });
    """)
    assert out["idle"] is True and out["keyFirst"] == 0, "a key alone takes nothing: a click does"
    assert out["clicked"] == [{"action": "click", "x": 640, "y": 400}], "the click that took it lands"
    assert out["holder"] == "person" and out["controls"] == ["person", "agent"] and out["after"] == "agent", \
        "sending a message hands the browser back"


def test_pointing_puts_a_line_in_the_composer_unsent(sandbox):
    out = _window(sandbox, """
        await open();
        const w = win();
        const box = document.body.appendChild(document.createElement('textarea'));
        box.id = 'message'; box.value = 'make ours like this';
        fire(w.point, 'click'); await settle(10);
        const pointing = mod._test.state().pointing && w.page.classList.contains('abw-pointing');
        fire(w.page, 'click', { clientX: 420, clientY: 250 }); await done(); await settle(30);
        const first = box.value;
        await mod.pointAt({ page: true }); await settle(20);
        const pts = browser.acts.filter((a) => a.action === 'point');
        out({ pointing, first, second: box.value, pts, clicks: acts().filter((a) => a.action === 'click').length,
              sent: server.calls.some((c) => String(c.url).includes('/api/chat')) });
    """)
    assert out["pointing"] is True
    assert out["pts"] == [{"action": "point", "x": 640, "y": 400}, {"action": "point", "page": True}]
    assert out["clicks"] == 0, "a click while pointing points; it does not click the page"
    assert out["first"].startswith("[In the browser I am pointing at <h1> “Wool & Co” on “Shop” (https://shop.example/)")
    assert "agent_browser inspect with pointed: true" in out["first"] and out["first"].endswith("\nmake ours like this")
    assert out["second"].startswith("[In the browser I am pointing at this page, “Shop”")
    assert out["second"].count("[In the browser") == 1, "a second point replaces the first line"
    assert out["sent"] is False


def test_the_agents_thinking_and_why_beside_the_page(sandbox):
    out = _window(sandbox, """
        await open();
        const w = win();
        fireWin('pantheon:chat-busy-change', { active: true });
        fireWin('pantheon:live-thinking', { text: 'The hero uses a serif; I will check its size.' });
        const live = { shown: !w.thinking.hidden, text: w.thinkingText.textContent, head: w.thinkingHead.textContent };
        mod.applyActivity([{ id: 9, seq: 9, who: 'agent', action: 'inspect', phase: 'doing',
          label: 'Inspecting <h1> “Wool & Co” — Georgia 32px #333333', why: 'To match the heading type.',
          x: 160, y: 40, box: [10, 20, 300, 40] }]);
        const cap = w.caption.textContent;
        const outlined = !w.outline.hidden;
        const feed = mod._test.state().feed[0];
        fireWin('pantheon:chat-busy-change', { active: false });
        const after = w.thinkingHead.textContent;
        fireWin('pantheon:message-sent', { text: 'next' });
        out({ live, cap, outlined, why: feed.why, after, cleared: w.thinking.hidden,
              tail: mod.thinkingTail('x'.repeat(50) + ' ' + 'y'.repeat(30), 40) });
    """)
    assert out["live"] == {"shown": True, "text": "The hero uses a serif; I will check its size.",
                           "head": "The agent is thinking"}
    assert "To match the heading type." in out["cap"] and out["outlined"] is True
    assert out["why"] == "To match the heading type." and out["after"] == "What the agent was thinking"
    assert out["cleared"] is True and out["tail"].startswith("…") and len(out["tail"]) <= 41


def test_closing_while_holding_hands_it_back(sandbox):
    out = _window(sandbox, """
        await open();
        await mod.takeOver(); await settle(20);
        mod.closeAgentBrowser(); await settle(20);
        const last = server.calls.filter((c) => c.url === '/api/workstation/control' && c.method === 'POST').pop();
        out({ last: last.body.holder, keepalive: last.keepalive, open: !!win(),
              inBody: !!document.getElementById('agent-browser-modal') });
    """)
    assert out == {"last": "agent", "keepalive": True, "open": False, "inBody": False}


# ── `P25-07`: the agent's hand, its words, its trail, and the stop ─────────

def test_the_agents_hand_glides_to_where_it_acts_and_says_what_it_does(sandbox):
    out = _window(sandbox, """
        await open();
        const w = win();
        w.page.getBoundingClientRect = () => ({ left: 90, top: 40, width: 660, height: 420, right: 750, bottom: 460 });
        mod.applyActivity([
          { id: 1, seq: 1, who: 'agent', action: 'open', label: 'Opening https://shop.example/', phase: 'done' },
          { id: 2, seq: 2, who: 'agent', action: 'click', label: 'Clicking “Add to basket”', phase: 'doing', x: 640, y: 400 },
        ]);
        const doing = { caption: w.caption.textContent, phase: w.caption.dataset.phase, hidden: w.caption.hidden,
                        hand: w.hand.style.transform, handHidden: w.hand.hidden };
        mod.applyActivity([{ id: 2, seq: 3, who: 'agent', action: 'click', label: 'Clicking “Add to basket”',
                             phase: 'done', x: 640, y: 400 }]);
        const ripples = w.page.querySelectorAll('.abw-ripple').length;
        mod.applyActivity([{ id: 3, seq: 4, who: 'person', action: 'back', label: 'Going back', phase: 'done' }]);
        out({ doing, ripples, caption: w.caption.textContent, since: mod._test.state().since,
              feed: mod._test.state().feed.map((f) => [f.id, f.phase, f.who]),
              busy: w.modal.classList.contains('abw-agent-busy') });
    """)
    assert out["doing"] == {"caption": "Clicking “Add to basket”", "phase": "doing", "hidden": False,
                            "hand": "translate(330px, 210px)", "handHidden": False}, \
        "the hand is at the frame's pixel, drawn where the picture is"
    assert out["ripples"] == 1, "a finished click ripples where it landed"
    assert out["caption"] == "Clicking “Add to basket”", "the person's own step does not speak for the agent"
    assert out["feed"] == [[3, "done", "person"], [2, "done", "agent"], [1, "done", "agent"]]
    assert out["since"] == 4 and out["busy"] is True


def test_the_window_asks_only_for_what_it_has_not_seen(sandbox):
    out = _window(sandbox, """
        await open();
        mod.applyActivity([{ id: 9, seq: 7, who: 'agent', action: 'read', label: 'Reading the page', phase: 'done' }]);
        await settle(60);
        const last = server.calls.filter((c) => String(c.url).startsWith('/api/workstation/browser') && c.method === 'GET').pop();
        out({ url: last.url });
    """)
    assert "since=7" in out["url"]


def test_stop_takes_the_browser_and_stops_the_reply(sandbox):
    out = _window(sandbox, """
        let stops = 0;
        document.addEventListener('pantheon-stop-reply', () => { stops += 1; });
        await open();
        const w = win();
        const shown = !w.stop.hidden;
        fire(w.stop, 'click'); await settle(60);
        const after = { stops, holder: server.holder, status: w.statusText.textContent, stopHidden: w.stop.hidden,
                        give: !w.give.hidden, stopped: mod._test.state().stopped };
        await mod.handBack(); await settle(20);
        out({ shown, after, back: { holder: server.holder, stopped: mod._test.state().stopped } });
    """)
    assert out["shown"] is True
    assert out["after"] == {"stops": 1, "holder": "person",
                            "status": "Stopped. The agent cannot use the browser until you hand it back.",
                            "stopHidden": True, "give": True, "stopped": True}
    assert out["back"] == {"holder": "agent", "stopped": False}
