# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1203` (`CHAT-U-23`) — the Compare dialog's copy.

The audit asked to drop *"Select models to compare side-by-side. Send the same
prompt to all."* and to say *Mode* and *Type* where the dialog said *MODE:* and
*TYPE:*. The premise, corrected on the row (`Law 3`): the sentence and the
labels are `static/js/compare/selector.js`'s, written *Mode:* and *Type:* and
drawn in capitals by `.compare-section-label { text-transform: uppercase }`.

Now there is no lead sentence, the labels read *Mode* and *Type* as written,
and the colon is drawn only where the active choice follows the label (a
phone, where the toggles show icons alone).

Driven in headless Chromium (the `playwright` node package): the real
`showModelSelector` and the real `static/style.css`, served to a page whose
`/api/` answers are empty, at a desktop and a phone width; what is read is what
the page renders (`innerText`, which applies `text-transform`).
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

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const STATIC = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = {};
  for (const width of [1280, 400]) {
    const page = await browser.newPage({ viewport: { width, height: 860 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e.message || e)));
    await page.route('http://t.local/**', (route) => {
      const u = new URL(route.request().url());
      if (u.pathname === '/') return route.fulfill({ contentType: 'text/html',
        body: '<!doctype html><html><head><link rel="stylesheet" href="/static/style.css"></head>'
          + '<body><div id="chat-container"></div></body></html>' });
      if (u.pathname.startsWith('/api/')) return route.fulfill({ contentType: 'application/json', body: '{"models":[]}' });
      const file = path.join(STATIC, u.pathname.replace(/^\/static\//, ''));
      if (!file.startsWith(STATIC) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
      return route.fulfill({ contentType: file.endsWith('.css') ? 'text/css' : 'text/javascript',
                             body: fs.readFileSync(file) });
    });
    await page.goto('http://t.local/');
    out[width] = await page.evaluate(async () => {
      const sel = await import('/static/js/compare/selector.js');
      sel.showModelSelector();
      await new Promise((r) => setTimeout(r, 400));
      const ov = document.getElementById('compare-model-overlay');
      if (!ov) return null;
      return { body: ov.querySelector('.modal-body').innerText,
               labels: [...ov.querySelectorAll('.compare-section-label')].map((l) => l.innerText.trim()) };
    });
    out[width + 'errors'] = errors;
    await page.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def dialog(tmp_path_factory):
    d = tmp_path_factory.mktemp("b1203")
    (d / "run.cjs").write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(d / "run.cjs"), str(STATIC)], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_lead_sentence_is_gone(dialog):
    assert dialog["1280"], "the dialog did not open"
    assert dialog["1280errors"] == [], dialog["1280errors"]
    assert "Select models to compare" not in dialog["1280"]["body"]
    assert "Send the same prompt" not in dialog["1280"]["body"]


def test_the_labels_say_mode_and_type_as_written(dialog):
    """The row's ask: *Mode* and *Type*, not *MODE:* and *TYPE:*."""
    assert dialog["1280"]["labels"] == ["Mode", "Type"]


def test_on_a_phone_the_colon_comes_with_the_choice_it_introduces(dialog):
    mode, kind = dialog["400"]["labels"]
    assert mode.startswith("Mode: ") and "Parallel" in mode, mode
    assert kind.startswith("Type:"), kind
    assert "MODE" not in mode and "TYPE" not in kind
