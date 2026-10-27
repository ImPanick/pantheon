# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B662` — after the outline-suppression sweep the focus ring is the one ring, everywhere.

`P10-01` put one armoured `:focus-visible` ring over a hundred `outline: none`
declarations and kept them all, because *dead in the cascade* is not *dead in
the file*. `B662` asked for the sweep in three separable steps and for this as
its `Verify`: *the ring looks identical on every surface named in `P10-01`'s
own `Verify` line, on all sixteen themes* (twenty-three now). Steps (a) — the
47 suppressions scoped to no focus state — and (b) — the 45 scoped to
`:focus` — are done; `tests/test_one_focus_ring_css.py` holds the census and
the cascade argument. Step (c), the eight rules that draw a substitute ring on
`:focus-visible`, is a judgement by eye and is left to the redesign.

This drives the claim instead of reasoning about it (`Law 20`): the real app in
Chromium at 1440×900, every shipped palette applied by the real
`applyColors()`, and on each of `P10-01`'s surfaces — the composer, the model
picker, a sidebar row, a settings input, a settings select and the document
editor (each of which carried one of the deleted suppressions, or sits beside
one; the editor's was one of the two `!important` ones) —

  * keyboard focus draws a solid ring of `--focus-ring-width` at
    `--focus-ring-offset`, in `--focus-ring`, which is the palette's own red;
  * a mouse press on a control that is not a text field draws none.

`P10-01`'s fifth surface, *a note's checkbox*, is not here because it is not a
control: a checklist item is a `<div>` with a `<span>` dot (`notes.js`), no
`tabindex` and no role, so Tab never lands on it and there is no ring to
compare. That is a keyboard defect of its own, filed from this pass.
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

SURFACES = ["#message", "#model-picker-btn", "#tool-agents-btn", "#set-agentMaxTools", "#set-agentBudgetMode"]

_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, USER, PASSWORD, SURFACES] = process.argv.slice(2);
// Every shipped palette applied by the real `applyColors()`, and each surface
// focused under it: the ring it draws, and the ring the palette asks for.
const THEMES = async (surfaces) => {
  const tm = await import('/static/js/theme.js');
  const probe = document.createElement('i');
  probe.style.cssText = 'position:absolute;color:var(--focus-ring)';
  document.body.appendChild(probe);
  const res = {};
  for (const name of Object.keys(tm.THEMES)) {
    tm.applyColors(tm.THEMES[name]);
    const root = getComputedStyle(document.documentElement);
    const want = { color: getComputedStyle(probe).color,
                   width: root.getPropertyValue('--focus-ring-width').trim(),
                   offset: root.getPropertyValue('--focus-ring-offset').trim() };
    res[name] = { want, got: {} };
    for (const sel of surfaces) {
      const el = document.querySelector(sel);
      el.focus();
      const cs = getComputedStyle(el);
      res[name].got[sel] = { visible: el.matches(':focus-visible'), style: cs.outlineStyle,
                             width: cs.outlineWidth, offset: cs.outlineOffset, color: cs.outlineColor };
      el.blur();
    }
  }
  probe.remove();
  return res;
};
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [], themes: {} };
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
  // A mouse press on a sidebar row and on the model picker: focus, and no
  // ring. First, while nothing covers them.
  out.mouse = {};
  for (const sel of ['#tool-agents-btn', '#model-picker-btn']) {
    const box = await page.locator(sel).boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    out.mouse[sel] = await page.evaluate((s) => { const el = document.querySelector(s);
      return { focused: document.activeElement === el, style: getComputedStyle(el).outlineStyle }; }, sel);
    await page.mouse.move(2, 890);
    await page.mouse.up();
    await page.evaluate(() => document.activeElement && document.activeElement.blur());
  }
  // Settings, open on Agent Tools, as a person opens it.
  await page.keyboard.press('Control+k');
  await page.waitForSelector('#search-input', { state: 'visible' });
  await page.keyboard.type('Settings', { delay: 20 });
  await page.waitForTimeout(800);
  await page.keyboard.press('Enter');
  await page.waitForSelector('#settings-modal:not(.hidden) .settings-nav-item', { timeout: 30000 });
  await page.evaluate(() => document.querySelector('#settings-modal .settings-nav-item[data-settings-tab="tools"]').click());
  await page.waitForSelector('#set-agentMaxTools', { state: 'visible' });
  await page.keyboard.press('Shift');   // the last interaction is the keyboard's
  out.themes = await page.evaluate(THEMES, JSON.parse(SURFACES));
  // The document editor, in a page of its own so its pane sits over nothing
  // measured above: `.doc-editor-textarea:hover/:focus/:active` carried one of
  // the two `!important` suppressions (a) deleted.
  const chat = await context.request.post(BASE + '/api/session', { multipart: {
    name: 'Ring check', endpoint_url: 'http://127.0.0.1:9/v1', model: 'demo-model', skip_validation: 'true' } });
  if (!chat.ok()) throw new Error('could not make a chat: ' + chat.status());
  const doc = await context.request.post(BASE + '/api/document', {
    data: { session_id: (await chat.json()).id, title: 'Ring check', content: 'One line to focus.' } });
  if (!doc.ok()) throw new Error('could not make a document: ' + doc.status());
  const docId = (await doc.json()).id;
  const docPage = await context.newPage();
  docPage.on('pageerror', (e) => out.errors.push(String(e)));
  await docPage.goto(BASE + '/', { waitUntil: 'load' });
  await docPage.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await docPage.evaluate(async (id) => { await window.documentModule.loadDocument(id); }, docId);
  await docPage.waitForSelector('#doc-editor-textarea', { state: 'visible', timeout: 30000 });
  await docPage.keyboard.press('Shift');
  out.docThemes = await docPage.evaluate(THEMES, ['#doc-editor-textarea']);
  await docPage.close();
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("focus-ring")
    script = d / "ring.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, USER, PASSWORD, json.dumps(SURFACES)],
                          capture_output=True, text=True, timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_every_palette_was_measured(measured):
    assert measured["errors"] == []
    assert len(measured["themes"]) == 23, sorted(measured["themes"])


def test_keyboard_focus_draws_the_one_ring_on_every_surface_and_palette(measured):
    wrong = []
    for name, row in measured["themes"].items():
        want = row["want"]
        for sel, got in row["got"].items():
            ok = (got["visible"] and got["style"] == "solid" and got["width"] == want["width"]
                  and got["offset"] == want["offset"] and got["color"] == want["color"])
            if not ok:
                wrong.append((name, sel, got, want))
    assert not wrong, json.dumps(wrong[:6], indent=1)


def test_the_document_editor_draws_the_one_ring_on_every_palette(measured):
    docs = measured["docThemes"]
    assert len(docs) == 23, sorted(docs)
    wrong = [(name, row["got"]["#doc-editor-textarea"], row["want"]) for name, row in docs.items()
             if not (row["got"]["#doc-editor-textarea"]["visible"]
                     and row["got"]["#doc-editor-textarea"]["style"] == "solid"
                     and all(row["got"]["#doc-editor-textarea"][k] == row["want"][k]
                             for k in ("width", "offset", "color")))]
    assert not wrong, json.dumps(wrong[:6], indent=1)


def test_the_ring_is_each_palettes_own_red_not_one_colour(measured):
    colours = {row["want"]["color"] for row in measured["themes"].values()}
    assert len(colours) >= 15, colours


@pytest.mark.parametrize("sel", ["#tool-agents-btn", "#model-picker-btn"])
def test_a_mouse_press_draws_no_ring(measured, sel):
    got = measured["mouse"][sel]
    assert got["focused"] and got["style"] == "none", got
