# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P25-00` — acceptance: from the + menu, without opening Settings mid-way.

The row's flow, driven, at both sizes and in both palettes:

  * **1440×900, dark**: *+ → Git ›* lists the repositories in the person's
    workstation; one picked is the chat's workspace; *+ → Git › Status*, then
    *Commit…*, each sent: the agent answers with the `git` tool, the commit
    carries the person's own name and email; *Push* follows the chat's trust
    rung like every other action — on the default rung, in this clean chat, it
    goes out unasked (`D-2026-10-29-01` §2) — over https with the person's own
    token for that host;
  * **390×844, light**: on a phone the same menu drills in — *Git ›* is a page
    of its own with a back row, and back is the menu again;
  * **1440×900, light**: *+ → Browser*; the agent is asked to find a page and
    opens and reads it in the person's own Firefox; the window shows the page;
    *Take over* gives it to the person (the agent's own call is refused while
    they hold it), *Hand back* returns it;
  * **390×844, dark**: *+ → Browser* on a phone, the window inside the screen.

Settings is opened by nothing in the drive: the identity and the host's token
are the person's own, set beforehand through `PUT /api/git` as Settings → Git
sets them.

**Found by this drive, on `f3a9150e`:** the + menu at 390 px ran 64 px past the
screen's right edge, and its *Git ›* page 7 px; *+ → Browser* left the menu
open over the chat (fixed; held in `tests/test_the_plus_menu_nests.py`). One
was the owner's to decide (`B1585`): a push in a clean chat on the default
trust rung went out without a card, though the menu said *it asks first*. The
owner ruled *change the words* (`D-2026-10-29-01` §2): a push follows the
rung, and the menu's Push now says only what it does. The other — the browser
window, open while the agent asks to open a page, lay over the chat's card —
is `B1586`'s: the window steps aside for the question and comes back.

Driven (`Law 20`): this checkout's `app.py` out of process (`capture.Server`),
headless Chromium, the real workstation daemon (`workstation/agentd.py`, the
`tests/helpers/workstation_daemon` harness: a real account home, real `git`
and a real headless Firefox over WebDriver BiDi — only the X display is a
picture), a smart-HTTP git server over https behind basic auth
(`test_git_is_each_persons_own._SmartHTTP`), a page served on this machine,
and the showcase's scripted model playing the agent's tool calls. What the
remote received, and the commit's author there, are read from the remote.
"""
from __future__ import annotations

import json
import secrets
import shutil
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402
import seed  # noqa: E402

GIT = shutil.which("git")
FIREFOX = shutil.which("firefox")
pytestmark = [
    pytest.mark.skipif(NODE is None, reason=_SKIP or ""),
    pytest.mark.skipif(GIT is None or not shutil.which("openssl"), reason="git and openssl are needed"),
    pytest.mark.skipif(FIREFOX is None, reason="Firefox is not installed here: the agent browser is Firefox"),
]

NAME, EMAIL = "Rowan Hale", "rowan@bramblewick.example"
TOKEN_USER, TOKEN = "rowan", "tok_" + secrets.token_hex(8)
STATUS = "Show the git status of this repository: the branch, and what changed."
COMMIT = "Commit the changes in this repository, with a message that says what changed and why."
PUSH = "Push this branch to its remote."
FIND = "Find the opening hours on the Bramblewick page at "
HOURS = "Open Tue–Sun, 7–3."
MESSAGE = "Add the opening hours to the menu page"
AGAIN = "Read the Bramblewick page once more."

PAGE = (b"<!doctype html><html><head><meta charset='utf-8'><title>Bramblewick Bakery</title></head>"
        b"<body><h1>Bramblewick Bakery</h1><p>Spring menu</p><footer>Open Tue&ndash;Sun, 7&ndash;3.</footer>"
        b"<a href='/cakes'>Celebration cakes</a></body></html>")


class _Site(BaseHTTPRequestHandler):
    hits: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.hits.append(self.path)
        body = PAGE if self.path == "/" else b"<title>Cakes</title><p>Order two days ahead.</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _script(site: str):
    return [
        {"key": "status", "title": "Git", "turns": [{"user": STATUS, "steps": [
            {"call": "git", "args": {"action": "status"}},
            {"say": "On **main**, one file changed: `index.html`."}]}]},
        {"key": "commit", "title": "Git", "turns": [{"user": COMMIT, "steps": [
            {"call": "git", "args": {"action": "commit", "message": MESSAGE}},
            {"say": f"Committed: *{MESSAGE}*."}]}]},
        {"key": "push", "title": "Git", "turns": [{"user": PUSH, "steps": [
            {"call": "git", "args": {"action": "push"}},
            {"say": "Pushed **main** to origin."}]}]},
        {"key": "find", "title": "Browser", "turns": [{"user": FIND, "steps": [
            {"call": "agent_browser", "args": {"action": "open", "url": site + "/"}},
            {"call": "agent_browser", "args": {"action": "read"}},
            {"say": f"The page says: **{HOURS}**"}]}]},
        # Asked while the person holds the browser: the message hands it back,
        # and the call's own answer is what the reply carries, word for word.
        {"key": "again", "title": "Browser", "turns": [{"user": AGAIN, "steps": [
            {"call": "agent_browser", "args": {"action": "read"}},
            {"say": lambda ctx: "The browser answered: " + (ctx["results"][-1] if ctx["results"] else "")[:300]}]}]},
    ]


_DRIVE = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const C = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = {};
const COLOURS = { dark: { bg: '#282c34', fg: '#9cdef2', panel: '#111111', border: '#355a66', red: '#e06c75' },
                  light: { bg: '#f0ebe3', fg: '#5a5248', panel: '#faf6f0', border: '#d4cdc2', red: '#c47d5a' } };

async function open(browser, size, theme) {
  const phone = size[0] < 500;
  const ctx = await browser.newContext({ viewport: { width: size[0], height: size[1] }, isMobile: phone,
    hasTouch: phone, serviceWorkers: 'block' });
  await ctx.addInitScript((a) => {
    try {
      localStorage.setItem('pantheon-theme', a.theme);
      localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
      localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
      localStorage.setItem('pantheon-toggles', JSON.stringify({ mode: 'agent' }));
    } catch (_) {}
  }, { theme: JSON.stringify({ name: theme, colors: COLOURS[theme] }) });
  const r = await ctx.request.post(C.base + '/api/auth/login',
    { data: { username: C.user, password: C.password, remember: true } });
  if (!r.ok()) throw new Error('login ' + r.status());
  const page = await ctx.newPage();
  page.__errors = [];
  page.__settings = 0;
  page.on('pageerror', (e) => page.__errors.push(String(e.message || e)));
  await page.goto(C.base + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);
  // Settings is never opened: counted every time its window is in the page.
  await page.exposeFunction('__sawSettings', () => { page.__settings += 1; });
  await page.evaluate(() => {
    const seen = () => { const m = document.getElementById('settings-modal');
      if (m && !m.classList.contains('hidden') && getComputedStyle(m).display !== 'none') window.__sawSettings(); };
    new MutationObserver(seen).observe(document.body, { subtree: true, childList: true, attributes: true,
      attributeFilter: ['class', 'style'] });
  });
  return { ctx, page, phone };
}

async function pick(page, model) {
  await page.evaluate(() => document.activeElement && document.activeElement.blur && document.activeElement.blur());
  try { await page.click('#model-picker-btn', { timeout: 4000 }); }
  catch (_) { await page.evaluate(() => document.getElementById('model-picker-btn').click()); }
  await page.waitForTimeout(900);
  await page.locator('.model-switch-item', { hasText: model }).first().click();
  await page.waitForTimeout(900);
}

async function plus(page) {
  await page.click('#overflow-plus-btn');
  await page.waitForSelector('#overflow-menu:not(.hidden)', { timeout: 10000 });
  await page.waitForTimeout(300);
}

async function submenu(page, key) {
  await page.click(`#overflow-menu [data-submenu="${key}"]`);
  await page.waitForSelector('.composer-submenu .composer-submenu-row', { timeout: 15000 });
  await page.waitForTimeout(400);
}

const rows = (page) => page.evaluate(() => [...document.querySelectorAll('.composer-submenu .composer-submenu-row')]
  .map((r) => r.innerText.replace(/\s+/g, ' ').trim()));

async function row(page, label) {
  await page.locator('.composer-submenu .composer-submenu-row', { hasText: label }).first().click();
  await page.waitForTimeout(700);
}

const lastReply = (page) => page.evaluate(() => {
  const err = [...document.querySelectorAll('.reply-error-text')].pop();
  const body = [...document.querySelectorAll('.msg-ai .body')].pop();
  return (err ? 'ERROR ' + err.textContent : '') || (body ? body.textContent.trim() : '');
});

async function send(page, until, { allow = false, ms = 60000 } = {}) {
  const phone = await page.evaluate(() => window.matchMedia('(max-width: 768px)').matches);
  if (phone) await page.click('.send-btn'); else await page.press('#message', 'Enter');
  const t0 = Date.now();
  let asked = 0;
  const covered = [];
  const lowered = [];
  while (Date.now() - t0 < ms) {
    await page.waitForTimeout(700);
    if (allow) {
      const card = page.locator('button[data-decision="approve_task"], button[data-decision="approve"]').first();
      if (await card.isVisible().catch(() => false)) {
        asked += 1;
        await page.waitForTimeout(400);
        // `B1586`: what the card says about a window that stepped aside for it.
        lowered.push(...await page.evaluate(() => [...document.querySelectorAll('.ask-user-lowered-note')]
          .map((n) => n.textContent)));
        // What is on top where the person would press: the card, or a window over it.
        const top = await card.evaluate((b) => { const r = b.getBoundingClientRect();
          const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          const win = at && at.closest('.modal');
          return win ? win.id : ''; });
        if (top) {
          covered.push(top);
          await page.click(`#${top} .modal-minimize-btn, #${top} [data-action="minimize"]`).catch(() => {});
          await page.waitForTimeout(600);
        }
        await card.click({ timeout: 10000 });
        await page.waitForTimeout(1200);
        continue;
      }
    }
    const said = await lastReply(page);
    if (until.test(said) || /^ERROR /.test(said)) break;
  }
  await page.waitForTimeout(800);
  return { reply: await lastReply(page), asked, covered, lowered,
    tools: await page.evaluate(() => [...document.querySelectorAll('.msg-ai')].pop().innerText) };
}

const fitsIn = (page, sel) => page.evaluate((sel) => {
  const n = document.querySelector(sel);
  const r = n ? n.getBoundingClientRect() : null;
  return { there: !!r && r.width > 0, inside: !!r && r.left >= -1 && r.right <= window.innerWidth + 1
    && r.top >= -1 && r.bottom <= window.innerHeight + 1,
    rect: r ? [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)] : null,
    viewport: [window.innerWidth, window.innerHeight],
    pageScrollsSideways: document.documentElement.scrollWidth > window.innerWidth + 1 };
}, sel);

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });

  // ── 1440×900, dark: Git › — attach, status, commit, push ────────────────
  {
    const { ctx, page } = await open(browser, [1440, 900], 'dark');
    const o = {};
    try {
      await pick(page, C.model);
      await plus(page);
      await submenu(page, 'git');
      o.listed = await rows(page);
      o.fits = await fitsIn(page, '.composer-submenu');
      await row(page, 'shop');
      o.workspace = await page.evaluate(() => ({ shown: (document.getElementById('workspace-indicator-btn') || {}).style?.display !== 'none',
        name: (document.getElementById('workspace-indicator-name') || {}).textContent || '' }));
      await plus(page); await submenu(page, 'git');
      o.attachedRows = await rows(page);
      await row(page, 'Status');
      o.statusBox = await page.inputValue('#message');
      o.status = await send(page, /On \*\*main\*\*|On main/);
      await plus(page); await submenu(page, 'git'); await row(page, 'Commit');
      o.commit = await send(page, /Committed/);
      await plus(page); await submenu(page, 'git'); await row(page, 'Push');
      o.push = await send(page, /Pushed/, { allow: true, ms: 90000 });
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors; o.settingsOpened = page.__settings;
    out.git = o;
    await ctx.close();
  }

  // ── 390×844, light: the same menu drills in ─────────────────────────────
  {
    const { ctx, page } = await open(browser, [390, 844], 'light');
    const o = {};
    try {
      await plus(page);
      o.top = await page.evaluate(() => [...document.querySelectorAll('#overflow-menu .overflow-menu-item')]
        .filter((n) => n.offsetParent !== null).map((n) => n.innerText.replace(/\s+/g, ' ').trim()));
      await submenu(page, 'git');
      o.page = await page.evaluate(() => {
        const s = document.querySelector('.composer-submenu');
        return { isPage: s.classList.contains('composer-submenu-page'),
          back: !!s.querySelector('.composer-submenu-back'),
          backText: (s.querySelector('.composer-submenu-back') || {}).textContent || '' };
      });
      o.listed = await rows(page);
      o.fits = await fitsIn(page, '.composer-submenu');
      await page.click('.composer-submenu .composer-submenu-back');
      await page.waitForTimeout(500);
      o.afterBack = await page.evaluate(() => ({ submenu: !!document.querySelector('.composer-submenu'),
        menu: !document.getElementById('overflow-menu').classList.contains('hidden') }));
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors; o.settingsOpened = page.__settings;
    out.phoneMenu = o;
    await ctx.close();
  }

  // ── 1440×900, light: Browser — find a page, watch it, take over, hand back ──
  {
    const { ctx, page } = await open(browser, [1440, 900], 'light');
    const o = {};
    try {
      // A chat of its own: what the git chat read is not this one's business.
      await page.locator('#sidebar-new-chat-btn').first().click();
      await page.waitForTimeout(1200);
      await pick(page, C.model);
      await plus(page);
      await page.click('#overflow-menu [data-open-agent-browser]');
      await page.waitForSelector('#agent-browser-modal', { timeout: 15000 });
      await page.waitForTimeout(1500);
      await page.fill('#message', C.find);
      o.find = await send(page, /The page says/, { allow: true, ms: 90000 });
      if (o.find.covered.length) {
        // The window was lowered to reach the card under it; back it comes,
        // the way it was opened.
        await plus(page);
        await page.click('#overflow-menu [data-open-agent-browser]');
        await page.waitForTimeout(1500);
      }
      const t0 = Date.now();
      while (Date.now() - t0 < 30000) {
        await page.waitForTimeout(800);
        const at = await page.evaluate(() => (document.querySelector('#agent-browser-modal .abw-address') || {}).value || '');
        if (at.startsWith(C.site)) break;
      }
      const state = () => page.evaluate(() => {
        const m = document.getElementById('agent-browser-modal');
        const vis = (s) => { const n = m.querySelector(s); return !!n && !n.hidden && n.offsetParent !== null; };
        const img = m.querySelector('.abw-frame');
        return { address: (m.querySelector('.abw-address') || {}).value || '',
          take: vis('.abw-take'), give: vis('.abw-give'), frame: !!img && !img.hidden && img.naturalWidth > 0,
          tabs: [...m.querySelectorAll('.abw-tab')].map((t) => t.textContent) };
      });
      o.watching = await state();
      o.fits = await fitsIn(page, '#agent-browser-modal .modal-content');
      await page.click('#agent-browser-modal .abw-take');
      await page.waitForTimeout(1500);
      o.held = await state();
      await page.click('#agent-browser-modal .abw-give');
      await page.waitForTimeout(1500);
      o.handed = await state();
      // Taken over again, and a message sent while holding it: the hold goes
      // back with the message, so the agent can do what it asks.
      await page.click('#agent-browser-modal .abw-take');
      await page.waitForTimeout(1200);
      o.heldAgain = await state();
      await page.fill('#message', C.again);
      o.withAMessage = await send(page, /The browser answered/, { allow: true, ms: 60000 });
      if (o.withAMessage.covered.length) {
        await plus(page);
        await page.click('#overflow-menu [data-open-agent-browser]');
        await page.waitForTimeout(1500);
      }
      o.afterMessage = await state();
      o.windowSaid = await page.evaluate(() => [...document.querySelectorAll('#agent-browser-modal [role="status"], #agent-browser-modal .abw-note, #agent-browser-modal .abw-say')]
        .map((n) => n.textContent.trim()).filter(Boolean));
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors; o.settingsOpened = page.__settings;
    out.browser = o;
    await ctx.close();
  }

  // ── 390×844, dark: Browser on a phone ───────────────────────────────────
  {
    const { ctx, page } = await open(browser, [390, 844], 'dark');
    const o = {};
    try {
      await plus(page);
      await page.click('#overflow-menu [data-open-agent-browser]');
      await page.waitForSelector('#agent-browser-modal', { timeout: 15000 });
      await page.waitForTimeout(2500);
      o.fits = await fitsIn(page, '#agent-browser-modal .modal-content');
      o.address = await page.evaluate(() => (document.querySelector('#agent-browser-modal .abw-address') || {}).value || '');
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors; o.settingsOpened = page.__settings;
    out.phoneBrowser = o;
    await ctx.close();
  }

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(tmp_path_factory):
    import capture
    import httpx

    from src.workstation_client import account_for
    from tests.helpers.workstation_daemon import running_workstation
    from test_git_is_each_persons_own import _SmartHTTP

    work = tmp_path_factory.mktemp("p25-00")
    data = work / "data"
    data.mkdir()

    # The remote: a bare repository behind basic auth, over https.
    certs = work / "certs"
    certs.mkdir()
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
                    "-keyout", str(certs / "k.pem"), "-out", str(certs / "c.pem")],
                   check=True, capture_output=True)
    served = work / "served"
    served.mkdir()
    subprocess.run([GIT, "init", "-q", "--bare", "-b", "main", "shop.git"], cwd=served, check=True)
    _SmartHTTP.root, _SmartHTTP.expect, _SmartHTTP.seen = str(served), f"{TOKEN_USER}:{TOKEN}", []
    remote = ThreadingHTTPServer(("127.0.0.1", 0), _SmartHTTP)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certs / "c.pem", certs / "k.pem")
    remote.socket = tls.wrap_socket(remote.socket, server_side=True)
    threading.Thread(target=remote.serve_forever, daemon=True).start()
    host = f"localhost:{remote.server_address[1]}"
    origin = f"https://{host}/shop.git"

    site_srv = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=site_srv.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{site_srv.server_address[1]}"

    server = capture.Server(sys.executable, data, capture._free_port(),
                            extra_env={"PANTHEON_DISABLE_MCP": "1"})
    try:
        server.start(timeout=150)
    except RuntimeError as e:
        server.stop()
        remote.shutdown()
        site_srv.shutdown()
        pytest.fail(f"{e}\n{server.log_path.read_text(encoding='utf-8', errors='replace')[-3000:]}")
    log: list = []
    seen: dict = {}
    try:
        with running_workstation(work) as ws:
            client = httpx.Client(base_url=server.base, timeout=180)
            password = secrets.token_urlsafe(18)
            seed.setup_admin(client, password)
            seed._ok(client.post("/api/auth/settings", json={
                "workstation_url": ws.url, "workstation_token": ws.token,
                "workstation_enabled": True}), "workstation settings")
            state = seed._ok(client.post("/api/workstation/check"), "workstation check")
            assert state.get("state") == "up", state
            seed._ok(client.get("/api/workstation/screen", timeout=120), "first workstation frame")
            # The person's own git, as Settings → Git keeps it.
            seed._ok(client.put("/api/git", json={
                "identity": {"name": NAME, "email": EMAIL},
                "hosts": {host: {"username": TOKEN_USER, "token": TOKEN}}}), "git settings")
            # A repository in their workstation home, with a change to commit.
            home = ws.root / account_for(seed.PERSON["username"])
            repo = home / "projects" / "shop"
            repo.mkdir(parents=True)
            run = lambda *a: subprocess.run([GIT, *a], cwd=repo, check=True, capture_output=True, text=True)
            run("init", "-q", "-b", "main")
            (repo / "index.html").write_text("<h1>Bramblewick</h1>\n")
            run("add", "--all")
            run("-c", "user.name=Setup", "-c", "user.email=setup@example.org", "commit", "-q", "-m", "First page")
            run("remote", "add", "origin", origin)
            (repo / "index.html").write_text(f"<h1>Bramblewick</h1>\n<p>{HOURS}</p>\n")
            # The person's workstation trusts this machine's own certificate,
            # as an operator's trusts their own CA.
            (home / ".gitconfig").write_text(f"[http]\n\tsslCAInfo = {certs / 'c.pem'}\n")
            with demo_model.DemoModel(log=log, conversations=_script(site),
                                      model_id=seed.DEMO_MODEL_ID) as model:
                seed.register_demo_model(client, model.base_url)
                config = {"base": server.base, "user": seed.PERSON["username"], "password": password,
                          "model": seed.DEMO_MODEL_ID, "site": site, "find": FIND + site + "/",
                          "again": AGAIN}
                (work / "config.json").write_text(json.dumps(config))
                (work / "drive.cjs").write_text(_DRIVE)
                proc = subprocess.run([NODE, str(work / "drive.cjs"), str(work / "config.json")],
                                      capture_output=True, text=True, timeout=900, cwd=ROOT)
                assert proc.returncode == 0, proc.stderr[-3000:]
                seen = json.loads(proc.stdout.strip().splitlines()[-1])
            seen["remoteLog"] = subprocess.run(
                [GIT, "log", "-2", "--pretty=%an <%ae>|%s", "main"], cwd=served / "shop.git",
                capture_output=True, text=True).stdout.strip().splitlines()
            seen["auth"] = list(_SmartHTTP.seen)
            seen["repoConfig"] = (repo / ".git" / "config").read_text()
            seen["siteHits"] = list(_Site.hits)
            (work / "seen.json").write_text(json.dumps(seen, indent=1, default=str))
            ws.station.browsers.stop_all()
        yield {"seen": seen, "log": log, "token": TOKEN, "site": site}
    finally:
        server.stop()
        remote.shutdown()
        site_srv.shutdown()


def test_git_lists_the_workstations_repositories_and_attaches_one(drive):
    git = drive["seen"]["git"]
    assert not git.get("crash"), git.get("crash")
    assert any(r.startswith("shop") and "main" in r and "1 change" in r for r in git["listed"]), git["listed"]
    assert git["workspace"]["shown"] and "shop" in git["workspace"]["name"], git["workspace"]
    assert [r.split(" ")[0] for r in git["attachedRows"][:3]] == ["Status", "Commit…", "Pull"], git["attachedRows"]
    assert git["statusBox"] == STATUS


def test_status_and_a_commit_as_the_person(drive):
    seen = drive["seen"]
    git = seen["git"]
    assert "On **main**" in git["status"]["reply"] or "On main" in git["status"]["reply"], git["status"]
    assert "Committed" in git["commit"]["reply"], git["commit"]
    assert seen["remoteLog"][0] == f"{NAME} <{EMAIL}>|{MESSAGE}", seen["remoteLog"]


def test_the_push_follows_the_chats_rung_and_the_menu_promises_no_question(drive):
    """`B1585` / `D-2026-10-29-01` §2 — *change the words*. This was the
    strict xfail `test_the_push_asks_first`: on the default rung
    (`gate_on_untrusted`) nothing asks in a clean chat, a push included, while
    + → Git › Push said *it asks first*. A push follows the rung like every
    other action, so in this fresh chat it goes out with no card — and the
    menu's row says what it does and nothing about asking."""
    git = drive["seen"]["git"]
    assert git["push"]["asked"] == 0, "a clean chat on the default rung asks nothing, a push included"
    assert "Pushed" in git["push"]["reply"], git["push"]
    push_row = next(r for r in git["attachedRows"] if r.startswith("Push"))
    assert push_row == "Push Send your commits to the remote", push_row
    assert not any("asks first" in r for r in git["attachedRows"]), git["attachedRows"]


def test_the_push_goes_out_as_the_persons_own(drive):
    seen = drive["seen"]
    push = seen["git"]["push"]
    assert "Pushed" in push["reply"], push
    import base64
    users = {base64.b64decode(a.split()[-1]).decode().split(":")[0] for a in seen["auth"] if a}
    assert users == {TOKEN_USER}, users
    assert drive["token"] not in seen["repoConfig"], "nothing of the token is written to the repository"
    assert drive["token"] not in json.dumps(push), "the token is not said back"


def test_on_a_phone_the_same_menu_drills_in(drive):
    phone = drive["seen"]["phoneMenu"]
    assert not phone.get("crash"), phone.get("crash")
    assert any(t.startswith("Git") for t in phone["top"]), phone["top"]
    assert phone["page"]["isPage"] and phone["page"]["back"], phone["page"]
    assert any(r.startswith("shop") for r in phone["listed"]), phone["listed"]
    assert phone["afterBack"] == {"submenu": False, "menu": True}, phone["afterBack"]


def test_the_browser_finds_a_page_is_watched_taken_over_and_handed_back(drive):
    seen = drive["seen"]
    b = seen["browser"]
    assert not b.get("crash"), b.get("crash")
    assert "Open Tue–Sun, 7–3." in b["find"]["reply"], b["find"]
    assert "/" in seen["siteHits"], "the person's Firefox fetched the page"
    assert b["watching"]["address"].startswith(drive["site"]), b["watching"]
    assert b["watching"]["frame"] and b["watching"]["take"] and not b["watching"]["give"], b["watching"]
    assert b["held"]["give"] and not b["held"]["take"], b["held"]
    assert b["handed"]["take"] and not b["handed"]["give"], b["handed"]
    # A message sent while holding it hands it back with the message.
    assert b["heldAgain"]["give"], b["heldAgain"]
    assert "Page: Bramblewick Bakery" in b["withAMessage"]["reply"], b["withAMessage"]
    assert b["afterMessage"]["take"] and not b["afterMessage"]["give"], b["afterMessage"]


def test_the_agents_question_is_not_under_the_window_it_is_watched_in(drive):
    """`B1586`. With the browser window open the agent's open asks (the window's
    page is in the turn's context), and at 1440x900 the 1040x780 window lay over
    the chat's card: Chromium reported the window's page intercepting the press
    on Allow. The window manager lowers a window that lies over the agent's
    question and brings it back when the question is answered
    (`modalManager.questionAsked`), and the card says so."""
    b = drive["seen"]["browser"]
    assert b["find"]["asked"] >= 1
    assert b["find"]["covered"] == [], b["find"]["covered"]
    assert any("is lowered so you can answer this" in n for n in b["find"]["lowered"]), b["find"]
    # It came back when the question was answered: the rest of this drive
    # watches, takes over and hands back in that window.
    assert b["watching"]["frame"], b["watching"]


def test_every_size_and_palette_fits_settings_stays_shut_and_nothing_threw(drive):
    seen = drive["seen"]
    for k in ("git", "phoneMenu", "browser", "phoneBrowser"):
        o = seen[k]
        assert not o.get("crash"), (k, o.get("crash"))
        f = o["fits"]
        assert f["there"] and f["inside"] and not f["pageScrollsSideways"], (k, f)
        assert o["settingsOpened"] == 0, (k, "Settings opened mid-way")
        assert o["errors"] == [], (k, o["errors"])
