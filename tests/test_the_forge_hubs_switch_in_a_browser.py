# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1229` in a real browser, with a log of everything the server tried to reach.

`tests/test_the_forge_reaches_hugging_face_only_when_an_admin_says.py` drives the
gates one handler at a time. This boots the real app out of process on a fresh
data directory — every outbound proxy variable pointing at a proxy in this test
that writes down each `CONNECT` and refuses it — and drives it with headless
Chromium as a person would:

  * an admin opens the Forge on the fresh install: the Forge asks for its
    catalog refresh as it always did, the server answers `off`, the Forge says
    so in one line, and **the proxy saw nobody** — not huggingface.co, not
    ollama.com, nothing;
  * the line's door opens Settings on the Forge panel (with `← Forge`), the
    switch is off there; switching it on saves, and the open Forge drops its
    line without a reload; asking the Forge to rescan then **reaches
    huggingface.co** — the refresh happens, through the proxy, as before;
  * a person who is not an admin has no Forge door, no Forge panel, and a
    refused `POST` if they try the switch by hand.

Skipped, with the reason, where node, `playwright` or its Chromium is missing.
"""

import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402
from test_no_egress_on_boot import _is_local  # noqa: E402 — loopback, the LAN, `host.docker.internal`

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]


class _Refusing(socketserver.BaseRequestHandler):
    """Write down where a client wanted to go, then refuse it."""

    def handle(self):
        try:
            first = self.request.recv(4096).decode("latin-1").split("\r\n", 1)[0]
        except OSError:
            return
        parts = first.split()
        if len(parts) >= 2:
            target = parts[1]
            host = target.split("//", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0] \
                if parts[0] != "CONNECT" else target.rsplit(":", 1)[0]
            self.server.seen.append(host)
        try:
            self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        except OSError:
            pass


class _Proxy(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    proxy = _Proxy(("127.0.0.1", 0), _Refusing)
    proxy.seen = []
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"

    data = tmp_path_factory.mktemp("forge-hubs-app")
    port = _free_port()
    env = dict(os.environ, PANTHEON_DATA_DIR=str(data), APP_PORT=str(port),
               APP_BIND="127.0.0.1", PANTHEON_DISABLE_MCP="1",
               DATABASE_URL="sqlite:///" + str(data / "app.db"),
               NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        env[var] = proxy_url
    log = open(data / "app.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 120
        while True:
            if proc.poll() is not None:
                log.flush()
                pytest.fail("the app exited during start-up:\n"
                            + (data / "app.log").read_text(encoding="utf-8")[-3000:])
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(url + "/login", timeout=2) as res:
                    if res.status == 200:
                        break
            except (urllib.error.URLError, OSError):
                pass
            if time.monotonic() > deadline:
                pytest.fail("the app did not answer /login within 120 s")
            time.sleep(0.5)
        yield {"url": url, "proxy": proxy, "data": data}
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()
        proxy.shutdown()


_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const proxySeen = async () => JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const admin = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
  await admin.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await admin.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const creds = { username: 'ada', password: 'ada-pass-1234' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.request.post(BASE + '/api/auth/users', { data: { username: 'bob', password: 'bob-pass-1234', is_admin: false } });

  const refreshes = [];
  const libraries = [];
  page.on('response', async (r) => {
    const u = r.url().replace(BASE, '');
    try {
      if (u.startsWith('/api/hwfit/models') && u.includes('refresh_catalog=1')) {
        const body = await r.json();
        refreshes.push(body.catalog_refresh || null);
      } else if (u.startsWith('/api/cookbook/ollama/library')) {
        libraries.push((await r.json()).hubs_off === true);
      }
    } catch (_) {}
  });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);
  out.seenAtLoad = await proxySeen();

  // Open the Forge, as a person does.
  await page.evaluate(() => (document.getElementById('tool-cookbook-btn') || document.getElementById('rail-cookbook')).click());
  await page.waitForSelector('#cookbook-modal:not(.hidden) .forge-hubs-off', { timeout: 30000 });
  await page.waitForTimeout(8000);   // the fresh-install scan, and anything it starts
  out.offRefreshes = refreshes.slice();
  out.offLibraries = libraries.slice();
  out.line = await page.evaluate(() => {
    const p = document.querySelector('#cookbook-modal .forge-hubs-off');
    const r = p && p.getBoundingClientRect();
    return p && { text: p.textContent, role: p.getAttribute('role'), visible: !!(r && r.width && r.height) };
  });
  out.seenWithTheForgeOpen = await proxySeen();

  // Its door: Settings, on the Forge panel, with `← Forge`.
  await page.click('#cookbook-modal .forge-hubs-off-door');
  await page.waitForSelector('#settings-modal [data-settings-panel="forge"]:not(.hidden)', { timeout: 15000 });
  await page.waitForTimeout(600);
  out.panel = await page.evaluate(() => ({
    active: document.querySelector('#settings-modal [data-settings-tab].active')?.dataset?.settingsTab || null,
    checked: document.getElementById('set-forgeModelHubs').checked,
    back: document.querySelector('#settings-modal .modal-back-btn')?.getAttribute('data-back-to') || null,
    doors: [...document.querySelectorAll('#settings-modal [data-forge-door]')].map((b) => b.textContent.trim()),
  }));

  // Switch it on, from the panel.
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/auth/settings') && r.request().method() === 'POST');
  await page.click('#settings-modal [data-settings-panel="forge"] .admin-switch');
  out.saveStatus = (await saved).status();
  await page.waitForTimeout(400);
  out.msg = await page.evaluate(() => document.getElementById('set-forgeModelHubsMsg').textContent);
  out.stored = (await (await page.request.get(BASE + '/api/auth/settings')).json()).forge_model_hubs;
  out.lineAfterSwitch = await page.evaluate(() => !!document.querySelector('#cookbook-modal .forge-hubs-off'));

  // Back to the Forge, and ask it to rescan: the refresh goes out again.
  await page.click('#settings-modal .modal-back-btn');
  await page.waitForTimeout(800);
  const answeredBefore = refreshes.length;
  await page.evaluate(() => document.getElementById('hwfit-hw-refresh-btn').click());
  // Both halves of what this step measures: the rescan's answer read (the
  // `response` listener above) and the proxy hearing from huggingface.co. The
  // server starts the refresh's thread before it ranks the rows it answers
  // with (`P23-07`), so the proxy can hear first: waiting on the proxy alone
  // read `onRefreshes` as [] whenever the answer came more than ~0.1 s after
  // (fx5-green: measured 122 ms to spare on an idle machine; the full run
  // under load on `0345288` read []; the answer held 2 s reproduces it).
  const until = Date.now() + 60000;
  while (Date.now() < until) {
    const seen = await proxySeen();
    if (seen.includes('huggingface.co') && refreshes.length > answeredBefore) break;
    await page.waitForTimeout(500);
  }
  out.onRefreshes = refreshes.slice(out.offRefreshes.length);
  out.seenWithTheSwitchOn = await proxySeen();

  // Someone who is not an admin.
  const member = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  await member.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const bob = await member.newPage();
  bob.on('pageerror', (e) => out.errors.push('bob: ' + String((e && e.message) || e)));
  await bob.request.post(BASE + '/api/auth/login', { data: { username: 'bob', password: 'bob-pass-1234', remember: true } });
  await bob.goto(BASE + '/', { waitUntil: 'load' });
  await bob.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await bob.waitForTimeout(1500);
  // Settings opened, as bob would from his user bar: no Forge panel in his nav.
  await bob.evaluate(() => document.getElementById('rail-settings').click());
  await bob.waitForTimeout(800);
  out.bob = await bob.evaluate(() => {
    const tab = document.querySelector('#settings-modal [data-settings-tab="forge"]');
    return {
      forgeDoor: ['tool-cookbook-btn', 'rail-cookbook'].map((id) => document.getElementById(id))
        .some((el) => el && el.offsetParent !== null),
      forgeTab: !!tab && tab.offsetParent !== null,
    };
  });
  out.bobPost = (await bob.request.post(BASE + '/api/auth/settings', { data: { forge_model_hubs: true } })).status();
  out.storedAfterBob = (await (await page.request.get(BASE + '/api/auth/settings')).json()).forge_model_hubs;
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(world, tmp_path_factory):
    work = tmp_path_factory.mktemp("forge-hubs-pw")
    seen_file = work / "seen.json"
    stop = threading.Event()

    def mirror():   # the proxy's log, where the node script can read it
        while not stop.is_set():
            seen_file.write_text(json.dumps(sorted(set(world["proxy"].seen))))
            time.sleep(0.2)

    seen_file.write_text("[]")
    t = threading.Thread(target=mirror, daemon=True)
    t.start()
    script = work / "drive.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    env = dict(os.environ)
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(var, None)
    proc = subprocess.run([NODE, str(script), world["url"], str(seen_file)], capture_output=True,
                          text=True, timeout=420, cwd=str(work), env=env)
    stop.set()
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def _public(hosts):
    """`Law 16` is about the public internet: the LAN and the Docker host alias
    (the local model servers the app looks for) are the product's own job."""
    return [h for h in hosts if not _is_local(h)]


def test_a_fresh_install_reaches_nobody_at_load_or_when_the_forge_opens(drive):
    assert _public(drive["seenAtLoad"]) == [], drive["seenAtLoad"]
    assert _public(drive["seenWithTheForgeOpen"]) == [], drive["seenWithTheForgeOpen"]
    # The Forge still asked, as it always did; the server answered `off`.
    assert drive["offRefreshes"] and all(r == {"state": "off"} for r in drive["offRefreshes"]), drive["offRefreshes"]
    assert drive["offLibraries"] == [True], drive["offLibraries"]


def test_the_forge_says_so_in_one_line(drive):
    line = drive["line"]
    assert line["visible"] and line["role"] == "status"
    assert line["text"] == "Hugging Face and Ollama are off. Settings → Forge", line


def test_its_door_opens_the_switch_with_the_way_back(drive):
    panel = drive["panel"]
    assert panel["active"] == "forge" and panel["checked"] is False, panel
    assert panel["back"] == "cookbook-modal", "the Settings header does not lead back to the Forge"
    assert panel["doors"] == ["Forge › Settings", "Forge › Settings", "Forge › Launch",
                              "Tasks", "Added Models", "Agent Tools"], panel["doors"]


def test_switching_it_on_saves_and_the_open_forge_follows(drive):
    assert drive["saveStatus"] == 200 and drive["msg"] == "Saved."
    assert drive["stored"] is True
    assert drive["lineAfterSwitch"] is False, "the Forge kept saying off over a switch that is on"


def test_with_the_switch_on_the_refresh_reaches_hugging_face(drive):
    assert any(r and r.get("state") in ("running", "done", "failed") for r in drive["onRefreshes"]), drive["onRefreshes"]
    assert "huggingface.co" in drive["seenWithTheSwitchOn"], drive["seenWithTheSwitchOn"]


def test_someone_who_is_not_an_admin_has_no_forge_and_no_switch(drive):
    assert drive["bob"] == {"forgeDoor": False, "forgeTab": False}, drive["bob"]
    assert drive["bobPost"] == 403
    assert drive["storedAfterBob"] is True, "bob's refused POST changed the switch"


def test_no_page_error(drive):
    assert drive["errors"] == []
