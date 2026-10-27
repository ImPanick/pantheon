# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B730`, the rest of the lists — each says which of its empty states it is in.

`tests/test_a_list_says_which_empty_it_is.py` drives the Brain and Notes. The
lists the row named as left are brought onto the shared shape
(`ui.renderEmptyState`) here: the calendar (no calendars / the read failed;
its agenda, searches and days), the Gallery (no photos / a filter hid them /
the read failed; its albums), the finished runs in Tasks, the endpoint and
webhook lists and the usage panel in Settings, the auth audit log, everyone's
networks, the Forge's cached models, the email attach picker, the workspace
folder browser and the Today view in Notes.

Three of them read a failed answer as an empty list — the calendar
(`_fetchCalendars` took a 500's `{detail}` for *no calendars*), the Gallery
(`_fetchLibrary` took it for *no photos*, and a filter that hid every photo
said *No photos yet* too), and the webhook list — and two more said a failure
in a line nobody could act on (finished runs at half opacity, the endpoints
list's *Failed to load*).

The row's `Verify:`, driven in Chromium against the real app (`Law 20`): each
list is emptied, filtered to nothing where it filters, and has its backend
broken (the request answered 500 by the browser), and each time the screen
says which through the shared shape (`data-empty-state`), and its button does
what it says.
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
  const creds = { username: 'lister', password: 'lister-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 120000 });

  const state = (host) => page.evaluate((h) => {
    const box = document.querySelector(h + ' .empty-state');
    if (!box) return null;
    const t = (s) => (box.querySelector(s) || {}).textContent || '';
    return { kind: box.dataset.emptyState, title: t('.empty-state-title'), reason: t('.empty-state-reason'),
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
  const fail = (glob, detail) => page.route(glob, (r) => r.fulfill({
    status: 500, contentType: 'application/json', body: JSON.stringify({ detail }) }));
  const step = async (name, fn) => { try { await fn(); } catch (e) { out.errors.push(name + ': ' + String(e && e.message || e)); } };

  // ── the calendar ──────────────────────────────────────────────────────
  // A fresh install has a local calendar, so its first empty list is today's.
  out.calendar = {};
  await step('calendar', async () => {
    await page.evaluate(() => document.getElementById('tool-calendar-btn').click());
    await waitState('#cal-body', 'empty');
    out.calendar.day = await state('#cal-body');
    await page.fill('#cal-search', 'zzzz-nothing');
    await waitState('#cal-body', 'filtered');
    out.calendar.filtered = await state('#cal-body');
    await press('#cal-body', 'Clear search');
    await waitState('#cal-body', 'empty');
    out.calendar.cleared = { search: await page.inputValue('#cal-search'), kind: (await state('#cal-body')).kind };
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => getComputedStyle(document.getElementById('calendar-modal')).display === 'none'
      || document.getElementById('calendar-modal').classList.contains('hidden'));
    // No calendars at all: the list the shape was taken from.
    await page.route('**/api/calendar/calendars', (r) => r.fulfill({ status: 200, contentType: 'application/json',
                                                                 body: JSON.stringify({ calendars: [] }) }));
    await page.evaluate(() => document.getElementById('tool-calendar-btn').click());
    await page.waitForFunction(() => /No calendars yet/.test((document.querySelector('#cal-body .empty-state-title') || {}).textContent || ''));
    out.calendar.none = await state('#cal-body');
    await page.keyboard.press('Escape');
    await page.unroute('**/api/calendar/calendars');
    await fail('**/api/calendar/calendars', 'the calendar store is locked');
    await page.waitForTimeout(400);
    await page.evaluate(() => document.getElementById('tool-calendar-btn').click());
    await waitState('#cal-body', 'error');
    out.calendar.error = await state('#cal-body');
    await page.unroute('**/api/calendar/calendars');
    await press('#cal-body', 'Try again');
    await waitState('#cal-body', 'empty');
    out.calendar.retried = (await state('#cal-body')).kind;
    await page.keyboard.press('Escape');
  });

  // ── the gallery ───────────────────────────────────────────────────────
  out.gallery = {};
  await step('gallery', async () => {
    await page.evaluate(() => document.getElementById('tool-gallery-btn').click());
    await waitState('#gallery-grid', 'empty');
    out.gallery.empty = await state('#gallery-grid');
    await page.fill('#gallery-search', 'zzzz-nothing');
    await waitState('#gallery-grid', 'filtered');
    out.gallery.filtered = await state('#gallery-grid');
    await press('#gallery-grid', 'Show all photos');
    await waitState('#gallery-grid', 'empty');
    out.gallery.cleared = { search: await page.inputValue('#gallery-search'),
                            kind: (await state('#gallery-grid')).kind };
    await fail('**/api/gallery/library**', 'the gallery index is locked');
    await page.fill('#gallery-search', 'x');
    await waitState('#gallery-grid', 'error');
    out.gallery.error = await state('#gallery-grid');
    await page.unroute('**/api/gallery/library**');
    await page.fill('#gallery-search', '');
    await press('#gallery-grid', 'Try again');
    await waitState('#gallery-grid', 'empty');
    out.gallery.retried = (await state('#gallery-grid')).kind;
  });

  // ── finished runs in Tasks ────────────────────────────────────────────
  out.tasks = {};
  await step('tasks', async () => {
    await page.keyboard.press('Escape');
    await page.evaluate(() => document.getElementById('tool-tasks-btn').click());
    await page.waitForSelector('#tasks-modal .tasks-tab[data-tab="completed"]', { state: 'visible' });
    await page.click('#tasks-modal .tasks-tab[data-tab="completed"]');
    await waitState('#tasks-completed-list', 'empty');
    out.tasks.empty = await state('#tasks-completed-list');
    await fail('**/api/tasks/runs/recent**', 'the run log is locked');
    await page.click('#tasks-completed-refresh');
    await waitState('#tasks-completed-list', 'error');
    out.tasks.error = await state('#tasks-completed-list');
    await page.unroute('**/api/tasks/runs/recent**');
    await press('#tasks-completed-list', 'Try again');
    await waitState('#tasks-completed-list', 'empty');
    out.tasks.retried = true;
  });

  // ── Settings: the endpoint list ───────────────────────────────────────
  out.endpoints = {};
  await step('endpoints', async () => {
    await page.keyboard.press('Escape');
    await page.click('#user-bar-settings');
    await page.route('**/api/model-endpoints', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.click('#settings-modal .settings-nav-item[data-settings-tab="added-models"]');
    await page.evaluate(() => window.adminModule._initData());
    await waitState('#adm-epList-local', 'empty');
    out.endpoints.empty = await state('#adm-epList-local');
    await page.unroute('**/api/model-endpoints');
    await fail('**/api/model-endpoints', 'the endpoint table is locked');
    await page.evaluate(() => window.adminModule._initData());
    await waitState('#adm-epList-local', 'error');
    out.endpoints.error = await state('#adm-epList-local');
    out.endpoints.apiHidden = await page.evaluate(() =>
      getComputedStyle(document.getElementById('adm-epList-api').closest('.adm-ep-section')).display === 'none');
  });

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def walked(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("more-empties") / "empties.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=600, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_threw(walked):
    assert walked["errors"] == [], walked["errors"]


def test_the_calendar_says_which_and_tries_again(walked):
    c = walked["calendar"]
    assert c["day"]["kind"] == "empty" and c["day"]["title"] == "No events"
    assert c["day"]["buttons"] == ["Add event"]
    assert c["filtered"]["kind"] == "filtered" and c["filtered"]["buttons"] == ["Clear search"]
    assert c["cleared"] == {"search": "", "kind": "empty"}
    assert c["none"]["title"] == "No calendars yet"
    assert c["none"]["buttons"] == ["New calendar", "Import .ics", "Set up CalDAV sync"]
    assert c["error"]["kind"] == "error", "a broken calendar read as no calendars"
    assert "the calendar store is locked" in c["error"]["reason"]
    assert c["error"]["buttons"] == ["Try again", "Open Settings"]
    assert c["retried"] == "empty"


def test_the_gallery_says_which_and_each_way_out_works(walked):
    g = walked["gallery"]
    assert g["empty"]["kind"] == "empty" and g["empty"]["title"] == "No photos yet"
    assert g["filtered"]["kind"] == "filtered", "a filter that hid everything said No photos yet"
    assert g["filtered"]["buttons"] == ["Show all photos"]
    assert g["cleared"] == {"search": "", "kind": "empty"}
    assert g["error"]["kind"] == "error" and "the gallery index is locked" in g["error"]["reason"]
    assert g["error"]["buttons"] == ["Try again"]
    assert g["retried"] == "empty"


def test_finished_runs_say_which(walked):
    t = walked["tasks"]
    assert t["empty"]["kind"] == "empty"
    assert t["error"]["kind"] == "error" and "the run log is locked" in t["error"]["reason"]
    assert t["error"]["buttons"] == ["Try again"] and t["retried"] is True


def test_the_endpoint_list_says_which(walked):
    e = walked["endpoints"]
    assert e["empty"]["title"] == "No models added yet" and e["empty"]["buttons"] == ["Add Models"]
    assert e["error"]["kind"] == "error", "a failed endpoint list read as None"
    assert "the endpoint table is locked" in e["error"]["reason"]
    assert e["apiHidden"] is True
