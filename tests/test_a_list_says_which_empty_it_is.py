# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B730` — a list says which of three empty states it is in, and offers the way
out of it.

`P9-07` wrote the one shared shape (`ui.renderEmptyState`: *nothing yet*,
*nothing matched*, *it broke*) and brought the Library's four tabs onto it; the
rest of the product's empty states were ad-hoc lines, inventoried on the row.
Two of the lists a person reads most are on it now:

  * **the Brain's memories** (`memory.js` `renderMemoryList`) — told the three
    apart already, but in three different shapes: a failed load was a line of
    text with no retry, and *No matches.* had no way to clear what hid them;
  * **notes** (`notes.js`) — a failed read set the list to `[]`, so a broken
    server read *No notes yet.*, and a search or chip that hid every note read
    *No notes yet.* too.

The row's `Verify:`, driven in Chromium against the real app (`Law 20`): each
list is emptied, filtered to nothing, and has its backend broken (the request
answered 500 by the browser), and each time the screen says which, through the
shared shape (`data-empty-state`), and its button does what it says.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    try {
      localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
      localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
    } catch (_) {}
  });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const creds = { username: 'emptier', password: 'emptier-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 120000 });

  // What the list's empty state says, read as a person reads it.
  const state = (host) => page.evaluate((h) => {
    const box = document.querySelector(h + ' .empty-state');
    if (!box) return null;
    const t = (s) => (box.querySelector(s) || {}).textContent || '';
    return { kind: box.dataset.emptyState, cls: box.className, title: t('.empty-state-title'),
             reason: t('.empty-state-reason'),
             buttons: [...box.querySelectorAll('.empty-state-action')].map((b) => b.textContent) };
  }, host);
  const waitState = (host, kind) => page.waitForFunction(([h, k]) => {
    const box = document.querySelector(h + ' .empty-state');
    return !!box && box.dataset.emptyState === k;
  }, [host, kind], { timeout: 60000 });
  const press = (host, label) => page.evaluate(([h, l]) => {
    const b = [...document.querySelectorAll(h + ' .empty-state .empty-state-action')].find((x) => x.textContent === l);
    if (b) b.click();
    return !!b;
  }, [host, label]);

  // ── the Brain ──────────────────────────────────────────────────────────
  out.brain = {};
  await page.evaluate(() => document.getElementById('tool-memory-btn').click());
  await waitState('#memory-list', 'empty');
  out.brain.empty = await state('#memory-list');
  out.brain.addPressed = await press('#memory-list', 'Add one');
  await page.waitForSelector('#memory-tab-add.active');
  out.brain.toAdd = true;
  await page.request.post(BASE + '/api/memory/add', { data: { text: 'The harbour opens at six', category: 'fact' } });
  await page.evaluate(() => window.memoryModule.loadMemories());
  await page.click('#memory-tab-browse');
  await page.waitForSelector('#memory-list .memory-item');
  await page.fill('#memory-search', 'zzzz-nothing');
  await waitState('#memory-list', 'filtered');
  out.brain.filtered = await state('#memory-list');
  await press('#memory-list', 'Clear filters');
  await page.waitForSelector('#memory-list .memory-item');
  out.brain.cleared = { search: await page.inputValue('#memory-search'),
                        items: await page.$$eval('#memory-list .memory-item', (n) => n.length) };
  await page.route('**/api/memory', (r) => r.fulfill({ status: 500, contentType: 'application/json',
                                                       body: JSON.stringify({ detail: 'boom' }) }));
  await page.evaluate(() => window.memoryModule.loadMemories());
  await waitState('#memory-list', 'error');
  out.brain.error = await state('#memory-list');
  await page.unroute('**/api/memory');
  await press('#memory-list', 'Try again');
  await page.waitForSelector('#memory-list .memory-item');
  out.brain.retried = await page.$$eval('#memory-list .memory-item', (n) => n.length);
  await page.click('#close-memory-modal');
  await page.waitForFunction(() => document.getElementById('memory-modal').classList.contains('hidden'));

  // ── notes ──────────────────────────────────────────────────────────────
  const pane = '#notes-pane .notes-pane-body';
  out.notes = {};
  // The cockpit's rail is the desktop door to Notes (its Tools list lives in the phone drawer).
  await page.click('#rail-notes');
  await waitState(pane, 'empty');
  out.notes.empty = await state(pane);
  await press(pane, 'Take a note');
  out.notes.focused = await page.evaluate(() => document.activeElement && document.activeElement.className);
  await page.request.post(BASE + '/api/notes', { data: { title: 'Harbour', content: 'opens at six', note_type: 'note' } });
  await page.click('#notes-close-btn');
  await page.click('#rail-notes');
  await page.waitForSelector('.note-card');
  await page.fill('#notes-search', 'zzzz-nothing');
  await waitState(pane, 'filtered');
  out.notes.filtered = await state(pane);
  await press(pane, 'Show all notes');
  await page.waitForSelector('.note-card');
  out.notes.cleared = { search: await page.inputValue('#notes-search'),
                        cards: await page.$$eval('.note-card', (n) => n.length) };
  await page.click('#notes-archive-toggle');
  await waitState(pane, 'empty');
  out.notes.archive = await state(pane);
  await press(pane, 'Back to notes');
  await page.waitForSelector('.note-card');
  out.notes.back = await page.$$eval('.note-card', (n) => n.length);
  await page.click('#notes-close-btn');
  await page.route('**/api/notes', (r) => r.fulfill({ status: 500, contentType: 'application/json',
                                                      body: JSON.stringify({ detail: 'the notes store is locked' }) }));
  await page.click('#rail-notes');
  await waitState(pane, 'error');
  out.notes.error = await state(pane);
  await page.unroute('**/api/notes');
  await press(pane, 'Try again');
  await page.waitForSelector('.note-card');
  out.notes.retried = await page.$$eval('.note-card', (n) => n.length);

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def walked(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("empties") / "empties.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=600, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_threw(walked):
    assert walked["errors"] == [], walked["errors"]


def test_the_brain_says_which_empty_and_each_way_out_works(walked):
    b = walked["brain"]
    assert b["empty"]["kind"] == "empty" and b["empty"]["title"] == "No memories yet."
    assert "memory-empty" in b["empty"]["cls"] and b["empty"]["buttons"] == ["Add one"]
    assert b["addPressed"] and b["toAdd"]
    assert b["filtered"]["kind"] == "filtered" and b["filtered"]["title"] == "No matches."
    assert b["filtered"]["buttons"] == ["Clear filters"]
    assert b["cleared"] == {"search": "", "items": 1}
    assert b["error"]["kind"] == "error"
    assert "Could not load memories" in b["error"]["reason"] and "500" in b["error"]["reason"]
    assert b["error"]["buttons"] == ["Try again"]
    assert b["retried"] == 1


def test_notes_say_which_empty_and_each_way_out_works(walked):
    n = walked["notes"]
    assert n["empty"]["kind"] == "empty" and n["empty"]["title"] == "No notes yet."
    assert n["empty"]["buttons"] == ["Take a note"]
    assert "notes-quick-input" in (n["focused"] or "")
    assert n["filtered"]["kind"] == "filtered" and n["filtered"]["buttons"] == ["Show all notes"]
    assert n["cleared"] == {"search": "", "cards": 1}
    assert n["archive"]["title"] == "Nothing archived." and n["archive"]["buttons"] == ["Back to notes"]
    assert n["back"] == 1
    assert n["error"]["kind"] == "error"
    assert "the notes store is locked" in n["error"]["reason"], "a broken server read as an empty list"
    assert n["retried"] == 1
