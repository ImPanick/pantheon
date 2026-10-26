# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1228` — a page load asks each of its boot reads once.

Measured on the fx-ops branch with `cold_load.py` (three loads), and again here
on the tree before this row in headless Chromium: `GET /api/auth/status`
(`init.js` and `app.js`, plus Settings' and the admin panel's own copies),
`/api/auth/features` (`censor.js`, `app.js`), `/api/default-chat`,
`/api/notes`, `/api/chat/agent-limits` and `/api/tool-approval-grants/<chat>`
were each asked twice per load. `static/js/appConfig.js` already shared
`getSettings` and `getTools` this way; the six are its siblings now, and their
call sites read them from there.

Driven in the real app (booted as `tests/test_the_command_palette_in_a_browser.py`
boots it) with an admin signed in: one cold load, every `/api/` GET counted by
path. The row's `Verify:` is a count of one for each.
"""
import json
import os
import subprocess
from collections import Counter

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { asked: [], errors: [] };
  const admin = { username: 'boss', password: 'boss-pass-123' };
  const setup = await browser.newContext();
  await setup.request.post(BASE + '/api/auth/setup', { data: admin });
  await setup.close();
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    // Who asked: the stack of each boot read, so a failure names the call
    // sites rather than only the count.
    const real = window.fetch;
    window.__asked = [];
    window.fetch = function (input, init) {
      const url = String((input && input.url) || input);
      if (/\/api\/(auth\/(status|features|settings)|default-chat|notes|chat\/agent-limits|tool-approval-grants|tools)(\?|$|\/)/.test(url)
          && (!init || !init.method || init.method === 'GET')) {
        window.__asked.push({ url, stack: (new Error().stack || '').split('\n').slice(2, 5).join(' | ') });
      }
      return real.apply(this, arguments);
    };
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith('/api/') && r.method() === 'GET') out.asked.push(u.pathname);
  });
  out.login = (await page.request.post(BASE + '/api/auth/login', { data: { ...admin, remember: true } })).status();
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 }).catch(() => {});
  await page.waitForTimeout(6000);
  out.stacks = await page.evaluate(() => window.__asked || []);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def file_database(tmp_path_factory):
    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp_path_factory.mktemp("boot-db") / "app.db")
    yield
    if before is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = before


@pytest.fixture(scope="module")
def load(file_database, app_url, tmp_path_factory):  # noqa: F811
    if NODE is None:
        pytest.skip(_SKIP)
    script = tmp_path_factory.mktemp("boot-pw") / "boot.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=600)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _counts(load):
    counts = Counter()
    for path in load["asked"]:
        if path.startswith("/api/tool-approval-grants/"):
            path = "/api/tool-approval-grants/<chat>"
        counts[path] += 1
    return counts


def test_the_premise_the_page_loaded_signed_in(load):
    assert load["login"] == 200
    assert len(load["asked"]) > 10, load


@pytest.mark.parametrize("path", [
    "/api/auth/status", "/api/auth/features", "/api/default-chat", "/api/notes",
    "/api/chat/agent-limits", "/api/auth/settings", "/api/tools",
])
def test_each_boot_read_is_asked_once(load, path):
    counts = _counts(load)
    who = [s["stack"] for s in load["stacks"] if s["url"].split("?")[0].endswith(path)]
    assert counts[path] <= 1, f"{path} asked {counts[path]} times on one load, by: {who}"


def test_the_chats_grants_are_asked_once(load):
    counts = _counts(load)
    assert counts["/api/tool-approval-grants/<chat>"] <= 1, dict(counts)
