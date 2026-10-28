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

`B1595`. Still red in a full run after `B1567`'s waits; reproduced with the
server held 90% of each 100 ms (`starve.py`) and with the browser held too,
three ways, none of them the product's: the signed-out visit raced the app's
own redirect to `/login` (the page still running, its requests answering 401
once the cookie went) and was aborted; the old `/static/` registration was
read before the page's unregister had settled; and a start-up from the
worker's cache took longer than the 90 s the offline half allowed. Each is a
wait on its condition now, and a server that goes on answering after SIGTERM
says what it answered and what its signal state was.
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
// `B1595`. Asked from here, again and again, so a navigation or a slow
// evaluation in the page is one more try rather than the end of the wait.
const until = async (page, fn, ms) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { if (await page.evaluate(fn)) return true; } catch (_) { /* asked again */ }
    await new Promise(r => setTimeout(r, 500));
  }
  return false;
};
// `B1567`, `B1521`'s way: every wait is for the condition the next step needs,
// named, with room for a machine running the whole suite beside this drive.
// In such a run `serverStopped` came back false: the server took longer than
// the 20 s this loop allowed to stop answering after SIGTERM. The condition is
// a refused connection, for up to a minute; a request that merely times out is
// a busy server, not a stopped one, so it is asked again rather than counted.
// (Not the process group's exit: the server is the pytest process's child, and
// a child nobody has reaped yet still answers signal 0.)
// `B1595`: what it saw is kept beside the answer, so a failure says whether
// the server went on answering or only went on timing out.
const downSeen = { answered: 0, timedOut: 0, ms: 0, last: '' };
// Each try on a connection of its own (`agent: false`): `fetch` kept one alive
// and asked on it 300 times, and a connection a stopping server still holds
// is not the question "would it take a new one" (`app.py`'s
// `GRACEFUL_SHUTDOWN_SECONDS` is the product's half of that finding).
const probe = () => new Promise((resolve, reject) => {
  const req = require('http').get(BASE + '/login', { agent: false, timeout: 5000 }, (res) => {
    res.resume(); resolve(res.statusCode);
  });
  req.on('timeout', () => { const e = new Error('timeout'); e.name = 'TimeoutError'; req.destroy(e); });
  req.on('error', reject);
});
const down = async () => {
  const t0 = Date.now();
  for (let i = 0; i < 300; i++) {
    try {
      const status = await probe();
      downSeen.answered += 1; downSeen.last = 'HTTP ' + status;
    } catch (e) {
      if (!e || e.name !== 'TimeoutError') { downSeen.ms = Date.now() - t0; downSeen.last = String(e && e.code); return true; }
      downSeen.timedOut += 1; downSeen.last = e.name;
    }
    await new Promise(r => setTimeout(r, 200));
  }
  downSeen.ms = Date.now() - t0;
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
  page.setDefaultNavigationTimeout(180000);
  page.setDefaultTimeout(180000);
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
  await wait(page, () => window.__pantheonAppStarted === true, 180000);
  out.controlled = await wait(page, () => !!navigator.serviceWorker.controller, 240000);
  // `B1595`. The page registers `/` and then unregisters the old `/static/`
  // one; the new worker can take the page before that second promise settles,
  // and on a loaded machine the list was read in between (`['/', '/static/']`).
  // Wait for the replacement, and read whatever it came to.
  out.legacyGone = await until(page, async () => (await navigator.serviceWorker.getRegistrations())
    .every(r => new URL(r.scope).pathname !== '/static/'), 120000);
  out.scopes = await page.evaluate(async () =>
    (await navigator.serviceWorker.getRegistrations()).map(r => new URL(r.scope).pathname).sort());
  out.header = (await page.request.get(BASE + '/static/sw.js')).headers()['service-worker-allowed'] || null;

  // A reload through the worker.
  const seen = [];
  page.on('response', (r) => seen.push({ url: r.url().replace(BASE, ''), sw: r.fromServiceWorker() }));
  await page.reload({ waitUntil: 'load' });
  await wait(page, () => window.__pantheonAppStarted === true, 180000);
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
  // `B1595`: off the app first. Still running, the page's own requests answer
  // 401 once the cookie is gone and it sends itself to `/login` — which, on a
  // loaded machine, landed in the middle of this navigation and aborted it
  // (`net::ERR_ABORTED`). The app doing that is right; racing it is not.
  await page.goto('about:blank');
  await context.clearCookies();
  await page.goto(BASE + '/', { waitUntil: 'load' });
  out.signedOut = new URL(page.url()).pathname;
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await wait(page, () => window.__pantheonAppStarted === true, 180000);
  out.errors.length = out.onlineErrors.length;
  // The kept copy the offline half depends on, asked for rather than assumed.
  out.kept = await wait(page, async () => !!(await caches.match('/')), 120000);

  // Offline: the app draws from the cache, on `/` and on a window's URL.
  // `B1423`: the server is really stopped. `context.setOffline(true)` (and
  // `context.route` aborting everything) leave the worker's own `fetch`
  // untouched — measured, the worker fetched `/` from the live server — so
  // those two cases were answered by the server, not by the worker's fallback.
  // `fromWorker` and the kept-copy notice (which only the fallback adds) are
  // the proof it was the worker. A page error from here on is the app's own
  // requests failing with no server (recorded apart; the worker's job is that
  // the page runs at all).
  // What the server's signal state was either side of the SIGTERM, kept for
  // the assertion's message: a server that goes on answering says whether the
  // signal was pending, caught, or never arrived.
  const signals = () => {
    try {
      return require('fs').readFileSync('/proc/' + SERVER_PGID + '/status', 'utf8').split('\n')
        .filter(l => /^(State|SigPnd|ShdPnd|SigCgt)/.test(l)).join(' | ');
    } catch (e) { return String((e && e.code) || e); }
  };
  downSeen.before = signals();
  process.kill(-SERVER_PGID, 'SIGTERM');
  out.serverStopped = await down();
  downSeen.after = signals();
  out.downSeen = downSeen;
  out.offline = {};
  // `B1595`: what failed to load offline, kept for the assertions' messages —
  // a page that does not start says which request the worker could not answer.
  out.offlineFailed = [];
  page.on('requestfailed', (r) => out.offlineFailed.push(
    r.url().replace(BASE, '') + ' ' + ((r.failure() || {}).errorText || '')));
  for (const path of ['/', '/tasks']) {
    try {
      // `B1595`: the online half's room (180 s) offline too — a start-up from
      // the worker's cache on a machine running the whole suite took longer
      // than 90 s on `/tasks`, and the drive called that "did not start".
      const res = await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 180000 });
      out.offline[path] = {
        fromWorker: !!(res && res.fromServiceWorker()),
        keptCopyNotice: await page.evaluate(() => !!document.getElementById('kept-copy-notice')),
        drawn: await wait(page, () => !!document.getElementById('tool-workbench-btn'), 180000),
        // `B1508`: the page's JavaScript ran, not just its static HTML.
        started: await wait(page, () => window.__pantheonAppStarted === true, 180000),
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
                          capture_output=True, text=True, timeout=900, cwd=str(script.parent))
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
    assert drive["scopes"] == ["/"], (drive["scopes"], "the old registration was still there after 120 s"
                                      if not drive.get("legacyGone") else "")


def test_a_reload_is_served_through_the_worker(drive):
    reload = drive["reload"]
    assert reload["fromWorker"] > 0, reload


def test_no_api_answer_comes_from_the_worker(drive):
    reload = drive["reload"]
    assert reload["api"] > 0, "the reload made no API call — the check below is vacuous"
    assert reload["apiFromWorker"] == 0, reload


def test_an_offline_reload_draws_the_app(drive):
    """`B1423`: with the server really down, so the worker's navigation
    fallback is what answers — the kept-copy notice is only ever its doing.
    `B1567`: what that rests on, each said, so a failure names it."""
    assert drive["controlled"] is True, "the worker never took the page"
    assert drive["kept"] is True, "the worker holds no copy of the shell"
    assert drive["serverStopped"] is True, ("the server still answered after SIGTERM", drive.get("downSeen"))
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
        assert drive["offline"][path]["started"] is True, (path, drive["offline"][path],
                                                            drive.get("offlineFailed"))


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
