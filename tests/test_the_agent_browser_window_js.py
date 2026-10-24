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
  * **watching is not driving** — a click or a key on the page does nothing
    until *Take over*; then a click lands at the page's own pixel, typing is
    text and Enter is a key, and *Hand back* gives it back;
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
  browser.frame += 1;
  return reply(200, { ok: true, action: body.action, url: browser.url, title: browser.title });
};
"""

_MODALS_SPEC = re.search(r"""['"](\./modalManager\.js[^'"]*)['"]""",
                         MODULE.read_text(encoding="utf-8")).group(1)

_PREAMBLE = (
    "import { document, fire, server, settle, browser, fireWindow } from './shim.js';\n"
    "const mod = await import('./browserWindow.js');\n"
    "Object.assign(mod._test.TIMING, { FRAME_MS: 15, HOLDER_MS: 40, RETRY_MS: 40,\n"
    "  AFTER_INPUT_MS: 5, TYPE_FLUSH_MS: 10, WHEEL_FLUSH_MS: 10 });\n"
    "const rect = { left: 100, top: 50, width: 640, height: 400, right: 740, bottom: 450 };\n"
    "const win = () => mod._test.win();\n"
    "const open = async () => { mod.openAgentBrowser(); win().img.getBoundingClientRect = () => rect;\n"
    "  await settle(80); };\n"
    "const acts = () => browser.acts.map((a) => a);\n"
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
        fire(w.page, 'click', { clientX: 420, clientY: 250 });
        fire(w.page, 'keydown', { key: 'a' }); await done();
        const watched = acts().length;
        await mod.takeOver(); await settle(20);
        fire(w.page, 'click', { clientX: 420, clientY: 250 });
        fire(w.page, 'keydown', { key: 'h' }); fire(w.page, 'keydown', { key: 'i' });
        await settle(40);
        fire(w.page, 'keydown', { key: 'Enter' });
        fire(w.page, 'keydown', { key: 'F5' }); await done();
        const held = acts();
        const ring = w.stage.classList.contains('abw-held');
        await mod.handBack(); await settle(20);
        out({ watched, held, ring, controls: server.calls.filter((c) => c.url === '/api/workstation/control'
              && c.method === 'POST').map((c) => c.body.holder), give: !w.give.hidden });
    """)
    assert out["watched"] == 0, "a click and a key while watching reach nothing"
    assert out["held"] == [{"action": "click", "x": 640, "y": 400}, {"action": "type", "text": "hi"},
                           {"action": "press", "keys": "enter"}], "F5 is not a key the browser route takes"
    assert out["ring"] is True and out["controls"] == ["person", "agent"] and out["give"] is False


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
