# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1070` — the Brain says it is loading until it knows, and asks when it opens.

Measured by `showcase` on the seeded demo: the Brain read *"No memories yet"*
for 7.4 s after its door was pressed while eight memories existed, and the API
answers in 4 ms. Two causes, both in `static/js/memory.js`:

  * the list was drawn from a module variable that starts as `[]`, and only a
    load in flight said "loading" — before the first load the empty state was
    drawn, a false statement (`Law 10`);
  * the window never asked for its list. Its door (`app.js`) redrew what it
    had; the store was asked by `app.js`'s startup warmup (12 s after boot, then
    an idle callback) or by `sessions.js` 2.5 s after a chat loaded. The
    requests seen before it on the wire were other warmups and polls, not a
    chain it waited behind.

Two halves: the real `memory.js` under node (the workshop sandbox, its
MutationObserver stood in by one that records what the module watches), and
the real app in headless Chromium, the Brain opened a second after boot with
three memories in the store.
"""

import json
import shutil
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402
from test_the_workshop_surfaces_js import _SHIM, _STUBS, _index_ids, MEMORY_JS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub  # B874

_needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_LOADING_STUBS = dict(_STUBS)
# The empty state draws `ui.js`'s empty-state icon, which the workshop's stub
# does not carry; this one does, with the shipped `esc`.
_LOADING_STUBS["ui.js"] = ui_default_stub(
    "showToast: () => {}, showError: () => {}, styledConfirm: async () => true,"
    " copyToClipboard: () => {}, el: (id) => document.getElementById(id),"
    " debounce: (f) => f, emptyStateIcon: () => '',")
# The workshop's spinner stub has no loading row; the real one draws a row
# with its text, which is what a person reads.
_LOADING_STUBS["spinner.js"] = """
const row = (text) => { const n = globalThis.document.createElement('div');
  n.className = 'loading-row'; n.textContent = text; return n; };
export function createLoadingRow(text){ return row(text); }
export default { createLoadingRow: row,
  create: () => ({ createElement: () => globalThis.document.createElement('span'),
                   start(){}, destroy(){}, updateMessage(){} }) };
"""

# A MutationObserver that records what it is asked to watch, so a case can
# play the browser's part: change the class, then deliver the record.
_PREAMBLE = """
import { document, calls, mockFetch, res, fire, ready, byId, tick } from './shim.js';
// The browser's `CSS.escape`, which the sort picker calls on DOMContentLoaded;
// the shim has no `CSS`.
globalThis.CSS = globalThis.CSS || { escape: (s) => String(s).replace(/["\\\\]/g, '\\\\$&') };
// `window` is `globalThis` in the shim, which has no event target of its own;
// the module listens for `memory-refresh` on it.
if (typeof globalThis.addEventListener !== 'function') globalThis.addEventListener = () => {};
const observers = [];
globalThis.MutationObserver = class {
  constructor(cb) { this.cb = cb; }
  observe(target, opts) { observers.push({ target, opts, cb: this.cb }); }
  disconnect() {}
};
const notify = (el) => observers.filter((o) => o.target === el).forEach((o) => o.cb([{ type: 'attributes' }]));
const mem = (await import('./memory.js')).default;
const list = () => byId('memory-list').readable;
// `P23-02` (`COPY-U-15`): the count is said once, on the tab; the header is bare.
const count = () => byId('memory-count').textContent;
const gets = () => calls.fetch.filter((c) => c.method === 'GET' && /\\/api\\/memory$/.test(c.url)).length;
const ROWS = [
  { id: 'a', text: 'Rowan prefers tea to coffee', category: 'preference', source: 'manual', timestamp: 1 },
  { id: 'b', text: 'The launch is on the 14th', category: 'fact', source: 'manual', timestamp: 2 },
];
const STYLE = { profile: null, observed: 3, needed: 20 };
const openBrain = async () => {
  const m = byId('memory-modal'); m.classList.add('hidden'); notify(m);
  m.classList.remove('hidden'); notify(m); await tick();
};
"""


@pytest.fixture(scope="module")
def brain(tmp_path_factory):
    shim = _SHIM.replace("__IDS__", json.dumps(_index_ids()))
    return _make_sandbox(tmp_path_factory.mktemp("brainload"), MEMORY_JS, shim, _LOADING_STUBS)


def _brain(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


@_needs_node
def test_before_the_store_answers_the_brain_says_it_is_loading(brain):
    out = _brain(brain, """
        mockFetch(() => res(200, {}));
        ready(); await tick();
        mem.renderMemoryList(); mem.updateMemoryCount();   // what the door did
        console.log(JSON.stringify({ list: list(), count: count() }));
    """)
    assert "No memories yet" not in out["list"]
    assert "Loading memories" in out["list"]
    assert out["count"] == "..."


@_needs_node
def test_opening_the_brain_asks_for_its_list_and_draws_it(brain):
    out = _brain(brain, """
        let release;
        const gate = new Promise((r) => { release = r; });
        mockFetch(async (url) => {
          if (/\\/api\\/memory$/.test(url)) { await gate; return res(200, { memory: ROWS, style: STYLE }); }
          return res(200, {});
        });
        ready(); await tick();
        const before = gets();
        await openBrain();
        const asked = gets();
        const whileWaiting = list();
        release(); await tick();
        const drawn = list();
        await openBrain();                    // a second open keeps what it knows
        console.log(JSON.stringify({ before, asked, whileWaiting, drawn,
                                     again: gets(), count: count() }));
    """)
    assert out["before"] == 0
    assert out["asked"] == 1, "opening the Brain did not ask for its list"
    assert "Loading memories" in out["whileWaiting"]
    assert "No memories yet" not in out["whileWaiting"]
    assert "Rowan prefers tea to coffee" in out["drawn"]
    assert out["again"] == 1
    assert out["count"] == "2"


@_needs_node
def test_a_failed_load_says_so_and_the_next_open_asks_again(brain):
    out = _brain(brain, """
        let fail = true;
        mockFetch((url) => {
          if (/\\/api\\/memory$/.test(url)) return fail ? res(500, {}) : res(200, { memory: ROWS, style: STYLE });
          return res(200, {});
        });
        ready(); await tick();
        await openBrain();
        const failed = list();
        fail = false;
        await openBrain();
        console.log(JSON.stringify({ failed, retried: list(), gets: gets() }));
    """)
    assert "No memories yet" not in out["failed"]
    assert "Could not load memories" in out["failed"] and "500" in out["failed"]
    assert out["gets"] == 2
    assert "The launch is on the 14th" in out["retried"]


@_needs_node
def test_an_empty_store_still_says_it_is_empty(brain):
    out = _brain(brain, """
        mockFetch((url) => res(200, /\\/api\\/memory$/.test(url) ? { memory: [], style: STYLE } : {}));
        ready(); await tick();
        await openBrain();
        console.log(JSON.stringify({ list: list(), count: count() }));
    """)
    assert "No memories yet" in out["list"]
    assert out["count"] == "0"


# ── the real app ───────────────────────────────────────────────────────────

_MEMORIES = ["Rowan prefers tea to coffee", "The launch is on the 14th",
             "Quillfeather's kickoff is in Lisbon"]

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const MEMORIES = JSON.parse(process.argv[3]);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  for (const [name, size] of [['desk', { width: 1400, height: 860 }], ['phone', { width: 390, height: 844 }]]) {
    const context = await browser.newContext({ viewport: size, serviceWorkers: 'block' });
    await context.addInitScript(() => {
      try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    });
    const page = await context.newPage();
    page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
    const creds = { username: 'brain', password: 'brain-pass-1' };
    await page.request.post(BASE + '/api/auth/setup', { data: creds });
    await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
    if (name === 'desk') {
      for (const text of MEMORIES) {
        await page.request.post(BASE + '/api/memory/add', { data: { text, category: 'fact' } });
      }
    }
    const asked = [];
    page.on('request', (r) => { if (/\/api\/memory$/.test(r.url())) asked.push(Date.now()); });
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await page.waitForTimeout(500);
    // The Brain's door, pressed long before any warmup would have asked.
    const clicked = Date.now();
    await page.evaluate(() => document.getElementById('tool-memory-btn').click());
    const seen = new Set();
    let arrived = null;
    for (let i = 0; i < 80 && arrived === null; i++) {
      const text = await page.evaluate(() => (document.getElementById('memory-list') || {}).innerText || '');
      if (text.includes('No memories yet')) seen.add('empty');
      if (text.includes('Loading memories')) seen.add('loading');
      if (text.includes(MEMORIES[0])) arrived = Date.now() - clicked;
      await page.waitForTimeout(50);
    }
    out[name] = { seen: [...seen], arrivedMs: arrived,
                  askedMs: asked.length ? asked.find((t) => t >= clicked) - clicked : null };
    await context.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def opened(app_url, tmp_path_factory):  # noqa: F811
    if NODE is None:
        pytest.skip(_SKIP or "")
    script = tmp_path_factory.mktemp("brain-pw") / "brain.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, json.dumps(_MEMORIES)], capture_output=True,
                          text=True, timeout=300, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


@pytest.mark.parametrize("size", ["desk", "phone"])
def test_in_a_browser_the_brain_never_calls_a_full_store_empty(opened, size):
    assert "empty" not in opened[size]["seen"], f"{size}: 'No memories yet' while memories existed"


@pytest.mark.parametrize("size", ["desk", "phone"])
def test_in_a_browser_the_brain_asks_when_it_opens(opened, size):
    got = opened[size]
    assert got["askedMs"] is not None and got["askedMs"] < 1500, got
    assert got["arrivedMs"] is not None and got["arrivedMs"] < 3000, got


def test_in_a_browser_nothing_threw(opened):
    assert opened["errors"] == []
