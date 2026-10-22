# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1422`: when Pantheon's server is down, the page says so.

The owner, 2026-10-22: *"I can't even login and when visiting the page it sent
me in a generic 'user' profile — automatically. Logging out gave zero
functionality to login under admin alias."*

Reproduced the same day by signing in, stopping the server, and visiting the
app again: the service worker answers a navigation from its kept copy when the
network fails (`P23-07`), so the person got the whole app with nobody signed in
— the sidebar's placeholder name **"User"**, chats that never load, a Log out
that reaches nothing — and a sign-in page whose submit said **"Failed to
fetch"**. Every one of those reads as an account problem. It was the server.

The server here is really stopped, mid-drive. Chromium's offline emulation and
request routing both leave a service worker's own `fetch` untouched (measured:
with the context offline the worker still fetched `/` from the live server), so
neither can stand in for a server that is down.
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
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, serviceWorkers: 'allow' });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await context.newPage();
  const out = {};
  const creds = { username: 'helper', password: 'helper-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });

  // Up: the worker takes the app and keeps its copies.
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await wait(page, () => window.__pantheonAppStarted === true, 90000);
  await wait(page, () => !!navigator.serviceWorker.controller, 60000);
  await page.reload({ waitUntil: 'load' });
  await wait(page, () => window.__pantheonAppStarted === true, 90000);
  out.noticeWhileUp = await page.evaluate(() => !!document.getElementById('kept-copy-notice'));
  out.nameWhileUp = await page.evaluate(() => (document.getElementById('user-bar-name') || {}).textContent);

  // The sign-in page, while the server is up, so the worker has it too.
  const anon = await browser.newContext({ serviceWorkers: 'allow' });
  const login = await anon.newPage();
  await login.goto(BASE + '/login', { waitUntil: 'load' });
  await wait(login, () => !!navigator.serviceWorker.controller, 60000);
  await login.reload({ waitUntil: 'load' });

  // Down.
  process.kill(-SERVER_PGID, 'SIGTERM');
  out.serverStopped = await down();

  const res = await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  out.fromWorker = !!(res && res.fromServiceWorker());
  out.notice = await page.evaluate(() => {
    const n = document.getElementById('kept-copy-notice');
    return n ? { text: n.textContent, role: n.getAttribute('role'),
                 href: (n.querySelector('a') || {}).getAttribute && n.querySelector('a').getAttribute('href') } : null;
  });

  await login.fill('#username', 'helper');
  await login.fill('#password', 'helper-pass-1');
  await login.click('#submitBtn');
  await wait(login, () => (document.getElementById('error') || {}).textContent, 20000);
  out.loginError = await login.evaluate(() => document.getElementById('error').textContent);

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(tmp_path_factory):
    data = tmp_path_factory.mktemp("kept-copy-app")
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
        script = tmp_path_factory.mktemp("kept-copy-pw") / "kept.cjs"
        script.write_text(_SCRIPT, encoding="utf-8")
        run = subprocess.run([NODE, str(script), url, str(proc.pid)], capture_output=True,
                             text=True, timeout=300, cwd=str(script.parent))
        assert run.returncode == 0, run.stderr[-4000:]
        lines = [ln for ln in run.stdout.splitlines() if ln.strip()]
        yield json.loads(lines[-1])
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        log.close()


def test_the_premise_the_server_really_stopped_and_the_worker_answered(drive):
    assert drive["serverStopped"] is True
    assert drive["fromWorker"] is True


def test_the_live_app_carries_no_notice(drive):
    assert drive["noticeWhileUp"] is False
    assert drive["nameWhileUp"] == "helper"


def test_the_kept_copy_says_the_server_is_not_answering(drive):
    notice = drive["notice"]
    assert notice, "the kept copy came back with no notice — a 'User' with nothing behind it"
    assert "server isn't answering" in notice["text"]
    assert "copy of the page your browser kept" in notice["text"]
    assert "no one is signed in" in notice["text"]
    assert notice["role"] == "alert"
    assert notice["href"] == "/"


def test_a_sign_in_with_no_server_says_the_password_is_not_the_problem(drive):
    text = drive["loginError"]
    assert "server isn't answering" in text, text
    assert "password is not the problem" in text
    assert "Failed to fetch" not in text
