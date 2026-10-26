# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1525` — Settings opened before the sign-in status arrives asks for nothing
only an admin may have.

The remainder of `B1192`. `admin.js` `_initData` returned only when the table's
state said `isAdmin === false`, and before `/api/auth/status` has answered that
state is `null` — so Settings opened in that window ran every admin loader
(users, endpoints, tools, webhooks, `/api/personal`, features, logs, …), each a
403 for a guest. Now `_initData` asks `ui_visibility.viewerMayAdminister`, which
waits for the status the page has said it asked for.

Driven under node in the admin sandbox `tests/test_the_admin_panels_that_never_
rendered.py` builds (its shim, stubs and runner, imported rather than copied),
with the real `ui_visibility.js` beside the real `admin.js`: the page notes it
asked for the status, Settings opens, and every request is recorded before and
after the status answers.
"""
import json
import shutil
import subprocess

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_workshop_surfaces_js import _index_ids  # noqa: E402
from test_the_admin_panels_that_never_rendered import (  # noqa: E402
    ADMIN_JS, _ADMIN_SHIM, _ADMIN_STUBS, _PREAMBLE, _store, _wh_event_values,
)

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_ADMIN_ONLY = ("/api/auth/users", "/api/personal", "/api/webhooks", "/api/auth/features",
               "/api/tools", "/api/endpoints", "/api/logs")


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    shim = (_ADMIN_SHIM
            .replace("__IDS__", json.dumps(_index_ids()))
            .replace("__WH_EVENTS__", json.dumps(_wh_event_values())))
    return _make_sandbox(tmp_path_factory.mktemp("b1525"), ADMIN_JS, shim, _ADMIN_STUBS)


def _open_early(sandbox, status):
    """The page has asked for the status; Settings opens; then `status` answers."""
    return _run(sandbox, _PREAMBLE + "import * as V from './ui_visibility.js';\n", _store() + """
        V.applyToolVisibility({ features: {} }, null);   // features answer first, as on the page
        V.noteStatusAsked();
        const pending = adminModule._initData();
        const again = adminModule._initData();           // a second open while it waits
        await tick();
        const before = calls.fetch.map((c) => c.url);
        V.applyToolVisibility(%s, null);
        await pending;
        await again;
        await tick();
        console.log(JSON.stringify({ before, after: calls.fetch.map((c) => c.url),
                                     same: pending === again, initialized: adminModule._initialized }));
    """ % json.dumps(status))


def test_a_guest_who_opens_settings_early_is_asked_nothing(sandbox):
    """The row's `Verify:`: no request the server would answer 403."""
    out = _open_early(sandbox, {"isAdmin": False, "auth": True})
    assert out["before"] == [], f"loaders ran before the status said who this is: {out['before']}"
    assert out["after"] == [], f"a guest was asked for admin lists: {out['after']}"
    assert out["initialized"] is False


def test_an_admin_who_opens_settings_early_gets_the_lists_once_the_status_says_so(sandbox):
    """The other half: waiting must not hide an admin's own panels."""
    out = _open_early(sandbox, {"isAdmin": True, "auth": True})
    assert out["before"] == [], out["before"]
    asked = out["after"]
    for path in ("/api/auth/users", "/api/personal", "/api/webhooks", "/api/auth/features"):
        assert any(u.endswith(path) or (path + "?") in u for u in asked), (path, asked)
    assert out["same"] is True, "a second open while waiting started a second set of loaders"
    assert asked.count("/api/webhooks") == 1, asked
    assert out["initialized"] is True


def test_a_status_that_never_answers_does_not_hide_an_admins_lists(sandbox):
    """Unknown asks (`SET-M-8`'s rule): with no status asked for, nothing waits."""
    out = _run(sandbox, _PREAMBLE + "import * as V from './ui_visibility.js';\n", _store() + """
        await adminModule._initData();
        await tick();
        console.log(JSON.stringify({ asked: calls.fetch.map((c) => c.url) }));
    """)
    assert any(u.endswith("/api/webhooks") for u in out["asked"]), out


# ── The row's `Verify:`, in the real app ────────────────────────────────────
#
# Settings' own admin-only inits (`settings.js` `initAll`: the default chat,
# utility, research, search… cards — sixteen loaders) had the same check as
# `_initData` and ran on an unknown status too. Driven as `B1192`'s test drives
# the page (the real app, a guest signed in, headless Chromium), with
# `/api/auth/status` held back so Settings opens before it answers.

from test_a_guest_asks_for_nothing_only_an_admin_may_have import file_database  # noqa: E402,F401
from test_the_command_palette_in_a_browser import NODE as _BROWSER, _SKIP, app_url  # noqa: E402,F401

_SLOW_STATUS = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { refused: [], errors: [], asked: 0, statusAt: null, settingsAt: null };
  const admin = { username: 'boss', password: 'boss-pass-123' };
  const guest = { username: 'guest', password: 'guest-pass-123' };
  const setup = await browser.newContext();
  await setup.request.post(BASE + '/api/auth/setup', { data: admin });
  await setup.request.post(BASE + '/api/auth/login', { data: { ...admin, remember: true } });
  out.made = (await setup.request.post(BASE + '/api/auth/users', { data: { ...guest, is_admin: false } })).status();
  await setup.close();

  const context = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  page.on('response', (r) => {
    const u = new URL(r.url());
    if (!u.pathname.startsWith('/api/')) return;
    out.asked += 1;
    if (r.status() === 403) out.refused.push(r.request().method() + ' ' + u.pathname);
  });
  // The status is slow: held for six seconds, so Settings opens first.
  await page.route('**/api/auth/status', async (route) => {
    await new Promise((r) => setTimeout(r, 6000));
    out.statusAt = Date.now();
    await route.continue();
  });
  out.login = (await page.request.post(BASE + '/api/auth/login', { data: { ...guest, remember: true } })).status();
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#user-bar-settings', { state: 'attached', timeout: 60000 });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 60000 }).catch(() => {});
  await page.evaluate(() => document.getElementById('user-bar-settings').click());
  out.settingsAt = Date.now();
  await page.waitForTimeout(9000);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def slow_status(file_database, app_url, tmp_path_factory):  # noqa: F811
    if _BROWSER is None:
        pytest.skip(_SKIP or "no browser")
    script = tmp_path_factory.mktemp("b1525-pw") / "slow.cjs"
    script.write_text(_SLOW_STATUS, encoding="utf-8")
    proc = subprocess.run([_BROWSER, str(script), app_url], capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_guest_who_opens_settings_before_the_status_answers_gets_no_403(slow_status):
    """The row's `Verify:`."""
    out = slow_status
    assert out["made"] == 200 and out["login"] == 200, out
    assert out["statusAt"] and out["settingsAt"] and out["settingsAt"] < out["statusAt"], (
        "the premise: Settings opened before the status answered")
    assert out["refused"] == [], f"asked for what only an admin may have: {out['refused']}"
