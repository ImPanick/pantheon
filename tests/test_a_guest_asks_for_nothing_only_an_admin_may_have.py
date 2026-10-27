# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1192` — a non-admin's page load and Settings open ask for nothing only an
admin may have.

Measured at `:8713` as `guest` after `P23-03`: page load asked
`GET /api/cookbook/state` (`cookbookRunning.js`) and `GET /api/skills/builtin`
(`skills.js`), and opening Settings asked the MCP & Integrations room's six
lists (`/api/auth/integrations`, `/api/contacts/config`, `/api/contacts/list`,
`/api/mcp/servers`, `/api/tokens`, `/api/vault/config`), each answered 403; a
tenth, `GET /api/personal` (`admin.js` `loadRag`), was measured by
fx4-archive. A 403 the page asked for is a request the page knew the answer to.

Now each of those asks first whether the viewer may administer
(`ui_visibility.viewerMayAdminister`, which waits for the status the page
already fetches) and a known non-admin skips it.

Driven in the real app in headless Chromium (booted as
`tests/test_the_command_palette_in_a_browser.py` boots it): an admin account
and a guest; the guest signs in, the page loads, Settings opens and its
integrations room is visited; every `/api/` answer is recorded. The row's
`Verify:` is that no answer is a 403.

`B1583`. This failed beside a full run and passed alone, with `GET
/api/personal` 403. Not the status wait: `app.js` warmed the knowledge index
nine seconds after boot (`runNonCriticalStartup`) without asking who was
looking, and the drive slept 4 + 3 + 3 s and closed — before the warmup fired
when the machine was quiet, after it when a full run slowed the boot. Measured
against a running app with the drive's window widened to 20 s: the warmup's
403 at 14.2 s, every time. The warmup asks the status now
(`viewerMayRunInstance`), and the drive waits on what it reads — the warmup
decided (`window.__pantheonKnowledgeWarmupDone`), Settings drawn, its rooms
mounted, the network quiet — not on a clock.
"""
import json
import os
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { refused: [], errors: [], asked: 0 };
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
  // `B1583`: loaded-machine timeouts on waits for named conditions (`B1521`).
  page.setDefaultTimeout(180000);
  page.setDefaultNavigationTimeout(180000);
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  page.on('response', (r) => {
    const u = new URL(r.url());
    if (!u.pathname.startsWith('/api/')) return;
    out.asked += 1;
    if (r.status() === 403) out.refused.push(r.request().method() + ' ' + u.pathname);
  });
  out.login = (await page.request.post(BASE + '/api/auth/login', { data: { ...guest, remember: true } })).status();
  await page.goto(BASE + '/', { waitUntil: 'load' });
  out.started = await page.waitForFunction(() => window.__pantheonAppStarted === true)
    .then(() => true, () => false);
  // The load's own asks include the warmups `app.js` runs after first paint;
  // the knowledge index's is the one that asked a guest for an operator's list.
  out.warmed = await page.waitForFunction(() => window.__pantheonKnowledgeWarmupDone === true)
    .then(() => true, () => false);
  await page.waitForLoadState('networkidle');
  out.afterLoad = out.refused.slice();
  // Settings, as a person opens it.
  await page.click('#user-bar-settings').catch((e) => out.errors.push('settings: ' + e.message));
  out.settings = await page.waitForFunction(() => {
    const m = document.getElementById('settings-modal');
    return !!m && !m.classList.contains('hidden');
  }).then(() => true, () => false);
  await page.waitForLoadState('networkidle');
  // The MCP & Integrations room, which mounts the integration lists.
  await page.evaluate(() => { try { window.settingsModule && window.settingsModule.open('integrations'); } catch (_) {} });
  await page.waitForLoadState('networkidle');
  // Which room Settings shows for a guest after that ask (the integrations room,
  // or the one a guest is given instead) — said, not assumed.
  out.room = await page.evaluate(() => {
    const p = [...document.querySelectorAll('#settings-modal [data-settings-panel]')]
      .find((n) => !n.classList.contains('hidden'));
    return p ? p.dataset.settingsPanel : null;
  });
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def file_database(tmp_path_factory):
    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp_path_factory.mktemp("guest-db") / "app.db")
    yield
    if before is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = before


@pytest.fixture(scope="module")
def drive(file_database, app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("guest-pw") / "guest.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=900)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_premise_a_guest_signed_in_and_the_page_asked_things(drive):
    assert drive["made"] == 200 and drive["login"] == 200, drive
    assert drive["asked"] > 10, drive
    # `B1583`: each condition the drive waited on, named, so a failure says
    # which one a loaded machine did not reach.
    for step in ("started", "warmed", "settings"):
        assert drive[step] is True, (step, drive)
    assert drive["room"], drive


def test_a_guests_load_and_settings_open_are_refused_nothing(drive):
    """The row's `Verify:`."""
    assert drive["refused"] == [], (
        f"the page asked for what only an admin may have: {drive['refused']} "
        f"(on load: {drive['afterLoad']})")
