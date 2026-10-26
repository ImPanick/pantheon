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

"Offline" is this file's own server stopped mid-drive (`B1423`, after
`test_a_kept_page_says_the_server_is_down.py`): Chromium's offline emulation
does not reach a service worker's own `fetch`, so it measured the live server.
"""

import json
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, SERVED, _SKIP, app_url  # noqa: F401,E402

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const SERVER_PGID = Number(process.argv[3]);
const wait = async (page, fn, ms) => {
  try { await page.waitForFunction(fn, null, { timeout: ms }); return true; } catch (_) { return false; }
};
const down = async () => {
  for (let i = 0; i < 100; i++) {
    try { await fetch(BASE + '/login'); } catch (_) { return true; }
    await new Promise(r => setTimeout(r, 200));
  }
  return false;
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

  out.onlineErrors = out.errors.slice();

  // Signed out, the server's redirect still wins over the cached app. Asked
  // while the server is up, and then signed back in for the offline half.
  await context.clearCookies();
  await page.goto(BASE + '/', { waitUntil: 'load' });
  out.signedOut = new URL(page.url()).pathname;
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await wait(page, () => window.__pantheonAppStarted === true, 90000);
  out.errors.length = out.onlineErrors.length;

  // Offline: the app draws from the cache, on `/` and on a window's URL.
  // `B1423`: the server is really stopped. `context.setOffline(true)` (and
  // `context.route` aborting everything) leave the worker's own `fetch`
  // untouched — measured, the worker fetched `/` from the live server — so
  // those two cases were answered by the server, not by the worker's fallback.
  // `fromWorker` and the kept-copy notice (which only the fallback adds) are
  // the proof it was the worker. A page error from here on is the app's own
  // requests failing with no server (recorded apart; the worker's job is that
  // the page runs at all).
  process.kill(-SERVER_PGID, 'SIGTERM');
  out.serverStopped = await down();
  out.offline = {};
  for (const path of ['/', '/tasks']) {
    try {
      const res = await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 20000 });
      out.offline[path] = {
        fromWorker: !!(res && res.fromServiceWorker()),
        keptCopyNotice: await page.evaluate(() => !!document.getElementById('kept-copy-notice')),
        drawn: await wait(page, () => !!document.getElementById('tool-workbench-btn'), 20000),
        // `B1508`: the page's JavaScript ran, not just its static HTML.
        started: await wait(page, () => window.__pantheonAppStarted === true, 20000),
      };
    } catch (e) {
      out.offline[path] = String(e && e.message || e).slice(0, 80);
    }
  }
  out.offlineErrors = out.errors.slice(out.onlineErrors.length);

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    # `B1085`: `app_url` gives the server a database file of its own now, so
    # the module fixture this file kept to point `DATABASE_URL` at one is gone.
    script = tmp_path_factory.mktemp("sw-pw") / "sw.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    # `B1423`: the drive stops this file's own server mid-way, by its group.
    proc = subprocess.run([NODE, str(script), app_url, str(SERVED[app_url].pgid)],
                          capture_output=True, text=True, timeout=300, cwd=str(script.parent))
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
    """`B1423`: with the server really down, so the worker's navigation
    fallback is what answers — the kept-copy notice is only ever its doing."""
    assert drive["serverStopped"] is True
    for path in ("/", "/tasks"):
        got = drive["offline"][path]
        assert isinstance(got, dict), (path, got)
        assert got["fromWorker"] is True, (path, got)
        assert got["keptCopyNotice"] is True, (path, got)
        assert got["drawn"] is True, (path, got)


def test_offline_the_apps_javascript_runs(drive):
    """`B1508`. `test_an_offline_reload_draws_the_app` passes on the static HTML's
    `#tool-workbench-btn` alone; this is the claim that the app itself ran.

    Measured with the server stopped before the fix: every module was in the
    worker's cache under its exact URL, stored with `Vary: Origin` (the CORS
    middleware's) by a precache `fetch` that sends no Origin, while a module
    request is CORS-mode and sends one — so the lookup honoured the Vary and
    missed (`net::ERR_FAILED`, 33 of 36 failed requests). `static/sw.js` now
    looks up with `{ ignoreVary: true }`."""
    for path in ("/", "/tasks"):
        assert drive["offline"][path]["started"] is True, (path, drive["offline"][path])


def test_a_signed_out_visit_still_lands_on_the_login_page(drive):
    assert drive["signedOut"] == "/login"


def test_the_drive_raised_no_page_error_online(drive):
    assert drive["onlineErrors"] == [], drive["onlineErrors"]


def test_offline_the_early_requests_raise_no_unhandled_error(drive):
    """`PERF-M-9`'s early fetch rejects with no network before any module
    awaits it; it is marked handled where it is made (the module that awaits it
    still sees the failure). Found by this drive: one `TypeError: Failed to
    fetch` per offline load, from the inline script.

    `B1423`: only meaningful on a page the worker drew — with no fallback the
    navigation is an error page that raises nothing, and this passed on that."""
    assert all(isinstance(v, dict) and v["drawn"] for v in drive["offline"].values()), drive["offline"]
    assert drive["offlineErrors"] == [], drive["offlineErrors"]
