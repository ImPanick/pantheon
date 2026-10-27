# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1589` — Compare's model picker is worked from a keyboard.

With five models or more, each Compare slot is a search box whose options drop
under it (`_buildSearchablePicker` in `static/js/compare/selector.js`). The
options were clickable `<div>`s with no role and no way in from the keyboard:
the search box's Enter took whichever option came first, so a keyboard could
pick the first model in the list or a model it typed the name of, and nothing
else. The last site in `B1576`'s census.

The picker is a combobox now — the shape the command palette and the chat's
own model picker have: the focus stays in the search box, ArrowDown/ArrowUp
move through the options (`aria-activedescendant` names the one they are on),
Enter picks it, Escape closes the list and not the window. Not a tab stop per
option; the row's `Verify:` said *Tab*, and the census note it came from said
what the shape should be — a list of forty models is forty Tabs to get past.

Driven in headless Chromium: the real `showModelSelector` and the real
`static/style.css`, served to a page whose `/api/models` lists six chat models.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

MODELS = ["alpha-chat", "bravo-chat", "charlie-chat", "delta-chat", "echo-chat", "foxtrot-chat"]

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const STATIC = process.argv[2];
const MODELS = JSON.parse(process.argv[3]);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String(e.message || e)));
  await page.route('http://t.local/**', (route) => {
    const u = new URL(route.request().url());
    if (u.pathname === '/') return route.fulfill({ contentType: 'text/html',
      body: '<!doctype html><html><head><link rel="stylesheet" href="/static/style.css"></head>'
        + '<body><div id="chat-container"></div></body></html>' });
    if (u.pathname === '/api/models') return route.fulfill({ contentType: 'application/json',
      body: JSON.stringify({ items: [{ url: 'http://127.0.0.1:9/v1', endpoint_id: 'e1', endpoint_name: 'Box', models: MODELS }] }) });
    if (u.pathname.startsWith('/api/')) return route.fulfill({ contentType: 'application/json', body: '{}' });
    const file = path.join(STATIC, u.pathname.replace(/^\/static\//, ''));
    if (!file.startsWith(STATIC) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
    return route.fulfill({ contentType: file.endsWith('.css') ? 'text/css' : 'text/javascript',
                           body: fs.readFileSync(file) });
  });
  await page.goto('http://t.local/');
  await page.evaluate(async () => {
    const sel = await import('/static/js/compare/selector.js');
    sel.showModelSelector();
  });
  // The search box, found by what it is rather than by the role this row gave it.
  const box = '#compare-model-overlay input.cmp-form-control[placeholder^="Search models"]';
  await page.waitForSelector(box, { timeout: 20000 });
  const state = () => page.evaluate((box) => {
    const input = document.querySelector(box);
    const list = document.getElementById(input.getAttribute('aria-controls') || '')
      || document.querySelector('.cmp-picker-dropdown');
    const activeId = input.getAttribute('aria-activedescendant');
    const active = activeId ? document.getElementById(activeId) : null;
    return {
      focused: document.activeElement === input,
      expanded: input.getAttribute('aria-expanded'),
      open: !!list && list.style.display !== 'none',
      listRole: list && list.getAttribute('role'),
      options: list ? [...list.children].map((o) => o.textContent) : [],
      active: active ? active.textContent : null,
      activeSelected: active ? active.getAttribute('aria-selected') : null,
      value: input.value,
      windowOpen: !!document.getElementById('compare-model-overlay'),
    };
  }, box);
  // Into the search box from the keyboard: Tab from the control before it.
  await page.evaluate((box) => {
    const input = document.querySelector(box);
    const before = document.createElement('button');
    before.id = 'b1589-before'; before.textContent = 'before';
    input.parentNode.insertBefore(before, input);
  }, box);
  await page.focus('#b1589-before');
  await page.keyboard.press('Tab');
  out.onFocus = await state();
  // ArrowDown walks every option, and wraps.
  out.walked = [];
  for (let i = 0; i < MODELS.length + 1; i++) {
    await page.keyboard.press('ArrowDown');
    const s = await state();
    out.walked.push([s.active, s.activeSelected]);
  }
  await page.keyboard.press('ArrowUp');
  await page.keyboard.press('ArrowUp');
  out.beforePick = await state();
  await page.keyboard.press('Enter');
  out.afterPick = await state();
  // Opened again from the keyboard, then Escape: the list closes, the window stays.
  await page.keyboard.press('ArrowDown');
  out.reopened = await state();
  await page.keyboard.press('Escape');
  out.afterEscape = await state();
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drove(tmp_path_factory):
    d = tmp_path_factory.mktemp("b1589")
    (d / "run.cjs").write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(d / "run.cjs"), str(STATIC), json.dumps(MODELS)],
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _label(model: str) -> str:
    return f"{model} (Box)"


def test_nothing_threw(drove):
    assert drove["errors"] == [], drove["errors"]


def test_tab_reaches_the_search_box_and_opens_the_list(drove):
    s = drove["onFocus"]
    assert s["focused"] and s["open"] and s["expanded"] == "true"
    assert s["listRole"] == "listbox"
    assert sorted(s["options"]) == sorted(_label(m) for m in MODELS)


def test_the_arrows_reach_every_option_and_say_which(drove):
    reached = [label for label, _sel in drove["walked"]]
    assert sorted(set(reached)) == sorted(_label(m) for m in MODELS), reached
    assert reached[-1] == reached[0], "ArrowDown past the last option comes back to the first"
    assert all(sel == "true" for _label_, sel in drove["walked"])


def test_enter_picks_the_option_the_arrows_are_on(drove):
    want = drove["beforePick"]["active"]
    assert want and want != drove["walked"][0][0]
    after = drove["afterPick"]
    assert after["value"] == want
    assert not after["open"] and after["expanded"] == "false"
    assert after["focused"], "picking from the keyboard left the focus nowhere"


def test_escape_closes_the_list_and_not_the_window(drove):
    assert drove["reopened"]["open"]
    after = drove["afterEscape"]
    assert not after["open"] and after["windowOpen"]
    assert after["value"] == drove["afterPick"]["value"]
