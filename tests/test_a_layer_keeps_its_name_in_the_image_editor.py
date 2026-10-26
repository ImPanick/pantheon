# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1218` — the image editor's Layers row keeps the layer's name, and Quick Edit sits on the canvas.

**Measured before the fix** (Chromium, this tree at `9297d85a`, 1440×900, the
Gallery at 820×828, a new 1024×1024 canvas): the Layers panel is 200 px wide
and each row holds a drag handle, the eye, the name, a 70 px opacity slider
and four or five buttons (84 px) — about 245 px of content. The name, the only
thing in the row that says which layer it is, was squeezed to **0 px** ("Edit
(empty)" drew nothing; the row that filed this saw "F"), and the last button
ran past the panel's edge and was clipped.

**Now** the name never goes under six characters and the row is laid out from
that: when the panel cannot hold everything on one line, the buttons take a
second line, right-aligned, so the name reads and every button is inside the
panel. A panel dragged wide enough holds the row on one line, as before.

**Quick Edit was already where the row asked for it.** The row said
`.ge-ai-command` was centred on `.ge-editor-body`, tool column and Layers panel
included. Measured on this tree it is a child of `.ge-canvas-area`
(`galleryEditor.js` appends it there) and that is `position: relative`, so it
is centred on the canvas: at 820×828 its centre and the canvas area's agree to
the pixel. It is pinned here, at that size and a narrower one, so it stays so.

Driven, not read (`Law 20`): the real app, the Gallery opened from its sidebar
row, the editor opened from its own template picker, the real layer panel.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402
from test_a_skill_card_keeps_its_name_beside_its_pills import (  # noqa: F401,E402
    PASSWORD, USER, app_url,
)

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, USER, PASSWORD] = process.argv.slice(2);
const MEASURE = () => {
  const box = (n) => { const r = n.getBoundingClientRect(); return { left: r.left, right: r.right, w: r.width }; };
  const panel = document.querySelector('.ge-layers-list');
  const rows = [...document.querySelectorAll('.ge-layers-list .ge-layer-item')].map((row) => {
    const name = row.querySelector('.ge-layer-name');
    // Six characters of this row's own font, measured rather than assumed.
    const probe = document.createElement('span');
    probe.textContent = '000000';
    probe.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;font:' + getComputedStyle(name).font;
    document.body.appendChild(probe);
    const six = probe.getBoundingClientRect().width;
    probe.remove();
    const r = box(row);
    const kids = [...row.children].filter((k) => k.offsetParent).map((k) => ({ cls: k.className, ...box(k) }));
    return { text: name.textContent, name: box(name).w, six,
             outside: kids.filter((k) => k.right > r.right + 0.5 || k.left < r.left - 0.5).map((k) => k.cls) };
  });
  const quick = document.querySelector('.ge-ai-command');
  const area = document.querySelector('.ge-canvas-area');
  const tools = document.querySelector('.ge-toolbar');
  const q = box(quick), a = box(area), t = box(tools);
  return { rows, panelRight: box(panel).right,
           quick: { parent: quick.parentElement.className, centre: (q.left + q.right) / 2,
                    areaCentre: (a.left + a.right) / 2, inside: q.left >= a.left - 0.5 && q.right <= a.right + 0.5,
                    clearOfTools: q.left >= t.right - 0.5 } };
};
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  await (await browser.newContext()).request.post(BASE + '/api/auth/setup',
    { data: { username: USER, password: PASSWORD } });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  await context.request.post(BASE + '/api/auth/login', { data: { username: USER, password: PASSWORD, remember: true } });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String(e)));
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(900);
  await page.evaluate(() => document.getElementById('tool-gallery-btn').click());
  await page.waitForSelector('#gallery-modal .gallery-tab[data-tab="editor"]', { state: 'visible', timeout: 30000 });
  for (const [label, w] of [['820', 820], ['560', 560]]) {
    await page.evaluate((w) => { const m = document.querySelector('#gallery-modal .modal-content');
      m.style.width = w + 'px'; m.style.maxWidth = w + 'px'; m.style.minWidth = '0';
      m.style.height = '828px'; m.style.maxHeight = '828px'; }, w);
    if (label === '820') {
      await page.click('#gallery-modal .gallery-tab[data-tab="editor"]');
      await page.waitForSelector('#gallery-editor-template', { timeout: 30000 });
      await page.selectOption('#gallery-editor-template', { index: 1 });
      await page.waitForSelector('.ge-layers-list .ge-layer-item', { timeout: 30000 });
    }
    await page.waitForTimeout(900);
    out[label] = await page.evaluate(MEASURE);
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("ge-layers")
    script = d / "layers.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, USER, PASSWORD], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("gallery", ["820", "560"])
def test_every_layer_row_shows_at_least_six_characters_of_its_name(measured, gallery):
    assert measured["errors"] == []
    rows = measured[gallery]["rows"]
    assert len(rows) >= 2, rows   # a new canvas: its background and its first layer
    for row in rows:
        assert row["name"] >= row["six"] - 0.5, (
            f"{row['text']!r} is drawn in {row['name']:.0f}px, under six characters "
            f"({row['six']:.0f}px)")   # before: 0px


@pytest.mark.parametrize("gallery", ["820", "560"])
def test_nothing_in_a_layer_row_runs_past_the_panel(measured, gallery):
    for row in measured[gallery]["rows"]:
        assert row["outside"] == [], (row["text"], row["outside"])


@pytest.mark.parametrize("gallery", ["820", "560"])
def test_quick_edit_is_centred_on_the_canvas_not_on_the_editor(measured, gallery):
    q = measured[gallery]["quick"]
    assert q["parent"].split()[0] == "ge-canvas-area", q
    assert abs(q["centre"] - q["areaCentre"]) <= 1, q
    assert q["inside"] and q["clearOfTools"], q
