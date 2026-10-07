# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-1`): the service worker controls the app, not `/static/`.

Measured on `32df791` against the seeded showcase install, Chromium with
service workers allowed: one registration, scope `/static/`;
`navigator.serviceWorker.controller` on `/` was `null`; registering with
`{scope: '/'}` was refused ("not under the max scope allowed"); a warm reload
made 188 requests and **0** came from the worker; an offline reload of `/` was
`net::ERR_INTERNET_DISCONNECTED`. The install still ran — every `CACHE_NAME`
bump re-downloaded the whole shell into a cache nothing read.

Driven in the real app in headless Chromium (booted as
`tests/test_the_command_palette_in_a_browser.py` boots it): an older client's
`/static/` registration is replaced, the worker controls `/`, a reload is
served through it, no `/api/` answer ever comes from it, an offline reload
draws the app, and a signed-out visit still lands on the login page.
"""

import json
import os
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const wait = async (page, fn, ms) => {
  try { await page.waitForFunction(fn, null, { timeout: ms }); return true; } catch (_) { return false; }
};
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, serviceWorkers: 'allow' });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const creds = { username: 'helper', password: 'helper-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });

  // An older client: the worker registered where the page used to put it. From
  // a static document, because `/login` sends a signed-in person on to `/`.
  await page.goto(BASE + '/static/manifest.json', { waitUntil: 'load' });
  out.legacyScope = await page.evaluate(async () => {
    const r = await navigator.serviceWorker.register('/static/sw.js');
    return new URL(r.scope).pathname;
  });

  await page.goto(BASE + '/', { waitUntil: 'load' });
  await wait(page, () => window.__pantheonAppStarted === true, 90000);
  out.controlled = await wait(page, () => !!navigator.serviceWorker.controller, 60000);
  out.scopes = await page.evaluate(async () =>
    (await navigator.serviceWorker.getRegistrations()).map(r => new URL(r.scope).pathname).sort());
  out.header = (await page.request.get(BASE + '/static/sw.js')).headers()['service-worker-allowed'] || null;

  // A reload through the worker.
  const seen = [];
  page.on('response', (r) => seen.push({ url: r.url().replace(BASE, ''), sw: r.fromServiceWorker() }));
  await page.reload({ waitUntil: 'load' });
  await wait(page, () => window.__pantheonAppStarted === true, 90000);
  await page.waitForTimeout(1500);
  out.reload = {
    total: seen.length,
    fromWorker: seen.filter(r => r.sw).length,
    apiFromWorker: seen.filter(r => r.sw && r.url.startsWith('/api/')).length,
    api: seen.filter(r => r.url.startsWith('/api/')).length,
  };

  // Offline: the app draws from the cache, on `/` and on a window's URL.
  await context.setOffline(true);
  out.offline = {};
  for (const path of ['/', '/tasks']) {
    try {
      await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 20000 });
      out.offline[path] = await wait(page, () => !!document.getElementById('tool-workbench-btn'), 20000);
    } catch (e) {
      out.offline[path] = String(e && e.message || e).slice(0, 80);
    }
  }
  await context.setOffline(false);

  // Signed out, the server's redirect still wins over the cached app.
  await context.clearCookies();
  await page.goto(BASE + '/', { waitUntil: 'load' });
  out.signedOut = new URL(page.url()).pathname;

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def file_database(tmp_path_factory):
    """A database file for the server `app_url` boots (`tests/conftest.py`'s
    in-memory default is one database per connection; see
    `test_the_assistant_has_a_sidebar_door.py`)."""
    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp_path_factory.mktemp("sw-db") / "app.db")
    yield
    if before is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = before


@pytest.fixture(scope="module")
def drive(file_database, app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("sw-pw") / "sw.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")


def test_the_worker_may_take_the_whole_origin(drive):
    assert drive["header"] == "/"


def test_the_worker_controls_the_app(drive):
    assert drive["controlled"] is True


def test_an_older_clients_static_registration_is_replaced(drive):
    assert drive["legacyScope"] == "/static/"
    assert drive["scopes"] == ["/"], drive["scopes"]


def test_a_reload_is_served_through_the_worker(drive):
    reload = drive["reload"]
    assert reload["fromWorker"] > 0, reload


def test_no_api_answer_comes_from_the_worker(drive):
    reload = drive["reload"]
    assert reload["api"] > 0, "the reload made no API call — the check below is vacuous"
    assert reload["apiFromWorker"] == 0, reload


def test_an_offline_reload_draws_the_app(drive):
    assert drive["offline"] == {"/": True, "/tasks": True}, drive["offline"]


def test_a_signed_out_visit_still_lands_on_the_login_page(drive):
    assert drive["signedOut"] == "/login"


def test_the_drive_raised_no_page_error(drive):
    assert drive["errors"] == [], drive["errors"]
