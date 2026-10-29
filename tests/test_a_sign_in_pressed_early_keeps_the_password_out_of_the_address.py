# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1665` — a Sign In pressed before the page is ready keeps the password out
of the address, and is not lost.

`static/login.html` attached its submit handler only after `/api/version`,
`/api/auth/status` and `/api/auth/policy` had answered. Until then the form was
the browser's own: `<form id="authForm">` with no method, its inputs named
`username` and `password`, so a press of Sign In was a GET to
`/login?username=…&password=…` — the password in the address bar, the
browser's history and the server's access log. On a busy server that window is
seconds long, and a person who types their name and password and presses Enter
falls into it. Found by `B1664`: the kept-page drive pressed Sign In on a
loaded machine and its page had become Chromium's error page for exactly that
address.

Driven (`Law 20`): the real app out of process and a real Chromium, with the
status check held as a slow server holds it.
"""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from test_the_command_palette_in_a_browser import NODE, ROOT, _SKIP, _free_port  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

PASSWORD = "helper-pass-1"

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const creds = { username: 'helper', password: process.argv[3] };
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = {};
  const setup = await browser.newContext();
  out.setup = (await setup.request.post(BASE + '/api/auth/setup', { data: creds })).status();
  await setup.close();

  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  page.setDefaultNavigationTimeout(120000);
  const addresses = [];
  page.on('request', (req) => addresses.push(req.url()));
  // The status check held, as a slow or busy server holds it.
  const held = [];
  let release = false;
  await page.route('**/api/auth/status', (route) => {
    if (release) route.continue(); else held.push(route);
  });
  await page.goto(BASE + '/login', { waitUntil: 'load' });
  await page.fill('#username', creds.username);
  await page.fill('#password', creds.password);
  await page.click('#submitBtn', { noWaitAfter: true });
  await page.waitForTimeout(1500);
  out.heldStatusChecks = held.length;
  out.pathWhileHeld = new URL(page.url()).pathname;
  out.searchWhileHeld = new URL(page.url()).search;

  release = true;
  for (const route of held) { try { await route.continue(); } catch (_) {} }
  try {
    await page.waitForURL((u) => new URL(u).pathname === '/', { timeout: 120000 });
  } catch (_) {}
  out.finalPath = new URL(page.url()).pathname;
  out.addressesWithThePassword = addresses.filter((u) => u.includes(creds.password));
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(tmp_path_factory):
    data = tmp_path_factory.mktemp("early-press-app")
    port = _free_port()
    env = dict(os.environ, PANTHEON_DATA_DIR=str(data), APP_PORT=str(port),
               APP_BIND="127.0.0.1", PANTHEON_DISABLE_MCP="1",
               DATABASE_URL="sqlite:///" + str(data / "app.db"))
    log = open(data / "app.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 120
        while True:
            if proc.poll() is not None:
                pytest.fail("the app exited during start-up:\n"
                            + (data / "app.log").read_text(encoding="utf-8")[-3000:])
            try:
                with urllib.request.urlopen(url + "/login", timeout=2) as res:
                    if res.status == 200:
                        break
            except (urllib.error.URLError, OSError):
                pass
            if time.monotonic() > deadline:
                pytest.fail("the app did not answer /login within 120 s")
            time.sleep(0.5)
        script = tmp_path_factory.mktemp("early-press-pw") / "early.cjs"
        script.write_text(_SCRIPT, encoding="utf-8")
        run = subprocess.run([NODE, str(script), url, PASSWORD], capture_output=True,
                             text=True, timeout=600, cwd=str(script.parent))
        assert run.returncode == 0, run.stderr[-4000:]
        lines = [ln for ln in run.stdout.splitlines() if ln.strip()]
        yield json.loads(lines[-1])
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        log.close()


def test_the_premise_the_press_came_while_the_status_check_was_held(drive):
    assert drive["setup"] == 200
    assert drive["heldStatusChecks"] >= 1, "the status check was never held"


def test_an_early_press_puts_the_password_in_no_address(drive):
    assert drive["addressesWithThePassword"] == []
    assert drive["pathWhileHeld"] == "/login"
    assert drive["searchWhileHeld"] == ""


def test_the_early_press_is_not_lost(drive):
    assert drive["finalPath"] == "/", "the press made while the page was not ready was dropped"


def test_with_no_script_the_form_still_sends_no_password_in_an_address():
    """The page's own fallback, if its script never runs: a form with no
    method is a GET, so it says `post`."""
    html = (ROOT / "static" / "login.html").read_text(encoding="utf-8")
    assert '<form id="authForm" method="post"' in html
