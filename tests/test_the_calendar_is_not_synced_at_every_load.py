# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-17`, the calendar half): a page load does not pull CalDAV.

Measured by the perf audit on `9560d50`: every load sent `POST
/api/calendar/sync` (and the calendar and event reads) with the Calendar window
closed. The pull's own guard says it is for the first open; the boot path that
fetches this month's events for the badge took it too, so once a remote
calendar is configured every reload reaches it. Now the boot fetch skips the
pull and the first open makes it. Driven in the real app in Chromium.
"""

import json
import os
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const creds = { username: 'helper', password: 'helper-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const asked = [];
  page.on('request', (r) => {
    const u = r.url().replace(BASE, '');
    if (u.startsWith('/api/calendar/')) asked.push(r.method() + ' ' + u.split('?')[0]);
  });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(4000);
  out.atLoad = asked.slice();
  asked.length = 0;
  await page.evaluate(() => {
    const b = document.getElementById('tool-calendar-btn') || document.getElementById('rail-calendar');
    if (b) b.click();
  });
  await page.waitForTimeout(2500);
  out.onOpen = asked.slice();
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def file_database(tmp_path_factory):
    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp_path_factory.mktemp("cal-db") / "app.db")
    yield
    if before is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = before


@pytest.fixture(scope="module")
def drive(file_database, app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("cal-pw") / "cal.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_a_page_load_does_not_pull_the_calendar(drive):
    assert "POST /api/calendar/sync" not in drive["atLoad"], drive["atLoad"]
    # The badge still has this month's events.
    assert "GET /api/calendar/events" in drive["atLoad"], drive["atLoad"]


def test_the_first_open_pulls_once(drive):
    assert drive["onOpen"].count("POST /api/calendar/sync") == 1, drive["onOpen"]


def test_no_page_error(drive):
    assert drive["errors"] == []
