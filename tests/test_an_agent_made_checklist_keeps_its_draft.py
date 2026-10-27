# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1560` — an agent-made checklist's unsaved draft comes back as a checklist.

The note form autosaves a draft to `localStorage` as it is edited, and
reopening the note restores the draft over it (`_applyDraftToNote`), so a lost
connection or a closed tab does not lose the edit. `_collectFormDraft` took the
draft's type from the lit type pill — and the form has pills for Note, Todo and
Draw only. `checklist` is the type the agent's note tool writes
(`src/tool_schemas.py`), so on an agent-made list no pill was lit, the draft
was recorded as `note_type: 'note'` with empty content and no items, and
reopening restored *that*: the list came back as an empty text note.

Now the form keeps its own type (`data-note-type`, beside the `currentType`
Save reads) and the draft records it.

Driven in Chromium against the real app (`Law 20`), the row's `Verify:`: a
`checklist` note made through the API, edited in the form, the page reloaded
without saving, the note reopened.
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
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await context.newPage();
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  const creds = { username: 'drafter', password: 'drafter-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const r = await page.request.post(BASE + '/api/notes', { data: { title: 'Packing', note_type: 'checklist',
    items: [{ id: 'p1', text: 'Socks', done: false }, { id: 'p2', text: 'Charger', done: false }] } });
  if (!r.ok()) throw new Error('could not make the note: ' + r.status());
  const id = (await r.json()).id;

  const openForm = async () => {
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await page.click('#tool-notes-btn');
    const card = `.note-card[data-note-id="${id}"] .note-card-title`;
    await page.waitForSelector(card, { state: 'visible', timeout: 30000 });
    await page.click(card);
    await page.waitForSelector('.note-form', { state: 'visible', timeout: 10000 });
  };
  const formState = () => page.evaluate(() => {
    const f = document.querySelector('.note-form');
    return {
      rows: [...f.querySelectorAll('.note-cl-row .note-cl-text')].map((t) => t.value || t.textContent),
      textNote: !!f.querySelector('.note-form-content'),
    };
  });

  await openForm();
  out.opened = await formState();
  // An edit, as a person makes one: into the first item's text.
  await page.click('.note-form .note-cl-row .note-cl-text');
  await page.keyboard.press('End');
  await page.keyboard.type(' (wool)');
  // The autosave is debounced 600 ms; wait for the draft itself to exist.
  await page.waitForFunction((k) => !!localStorage.getItem(k), 'pantheon-note-draft-' + id, { timeout: 10000 });
  out.draft = await page.evaluate((k) => JSON.parse(localStorage.getItem(k)), 'pantheon-note-draft-' + id);
  // Closed without saving: the page goes away with the form open.
  await openForm();
  out.reopened = await formState();
  out.server = await page.evaluate(async (nid) => {
    const all = await (await fetch('/api/notes')).json();
    const n = (Array.isArray(all) ? all : (all.notes || [])).find((x) => x.id === nid) || {};
    return { note_type: n.note_type, items: (n.items || []).map((i) => i.text) };
  }, id);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("checklist-draft")
    script = d / "draft.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_threw(measured):
    assert measured["errors"] == []


def test_the_form_opens_the_checklist_as_a_list(measured):
    assert measured["opened"] == {"rows": ["Socks", "Charger"], "textNote": False}


def test_the_draft_is_recorded_as_a_checklist_with_its_items(measured):
    draft = measured["draft"]
    assert draft["note_type"] == "checklist", draft
    assert [i["text"] for i in draft["items"]] == ["Socks (wool)", "Charger"], draft


def test_reopened_it_is_still_a_checklist_with_its_items(measured):
    """The row's `Verify:` — the unsaved edit comes back, as a list."""
    assert measured["reopened"] == {"rows": ["Socks (wool)", "Charger"], "textNote": False}
    # Nothing was saved: the draft is the only place the edit lives.
    assert measured["server"] == {"note_type": "checklist", "items": ["Socks", "Charger"]}
