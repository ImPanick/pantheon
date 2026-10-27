# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-00` — acceptance: a page changed from notes, and a design taken to a
branch, driven against a real workstation.

The row's flow, at both sizes and in both palettes:

  * **rowan, 1440×900, dark**: the project (`~/projects/shop`, a git
    repository in his workstation) is the chat's workspace; its dev server is
    opened in the agent browser's window from the address bar; three notes are
    pinned to the page and an arrow drawn on one; *Send 3 notes*: the agent
    reads them, changes the file, reloads the page and closes each — the
    notes show done and the dev server is asked for the changed page;
  * **rowan, 1440×900, light**: *+ → Design › Mockup*, a brief with the
    project's design system; the agent writes the page in `design/<slug>/`;
    *Try variants* — two side by side, one kept; a *Tweak* moved, kept as a
    version; *sam* invited as a commenter;
  * **sam, 390×844, dark**: *Shared with me*, the design, a note added; there
    is nothing to edit with, and an edit sent anyway is refused by the server;
  * **rowan, 390×844, light**: *Build it* → *Make the branch*: `design/<slug>`
    with its brief, the design system's tokens and sam's note beside it, and
    the base branch where it was.

**Nothing in the flow failed on `f3a9150e`** once the + menu's own defects were
fixed (`P25-00`'s commit). What it found stands as a strict `xfail`: the agent's
questions — its write after reading the notes, a variant's write — land under
the window the person is working in. Two things the drive itself had to learn,
said so the next one need not: a model that states no window is budgeted 6,000
tokens and the notes message is cut in its middle (the scripted model here
states one, as vLLM, llama-server and Ollama do), and git lists a branch
checked out in a worktree with a `+`.

Driven (`Law 20`): this checkout's `app.py` out of process, headless Chromium,
the real workstation daemon with real account homes, real `git` and a real
headless Firefox over WebDriver BiDi (only the X display is a picture), the
project's dev server on this machine serving the project's own folder, and the
showcase's scripted model playing the agent's calls. The branch, its brief and
the base are read from git.
"""
from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
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
    pytest.mark.skipif(GIT is None, reason="git is needed"),
    pytest.mark.skipif(FIREFOX is None, reason="Firefox is not installed here: the agent browser is Firefox"),
]

NAME, EMAIL = "Rowan Hale", "rowan@bramblewick.example"
SLUG = "spring-menu"

# The dev server's page: three blocks at known places, so a note lands on each.
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Bramblewick</title>
<style>body{margin:0;font:20px/1.4 sans-serif}h1,p,a{display:block;box-sizing:border-box;margin:0;
height:140px;padding:40px}h1{background:#f3e6d3}p{background:#e8f0e3}a{background:#e3e8f0}</style></head>
<body><h1 id="title">Bramblewick</h1><p id="hours">Open most days.</p><a id="order" href="#order">Order</a></body></html>
"""
CHANGED = PAGE.replace("<title>Bramblewick</title>", "<title>Bramblewick — Spring menu</title>") \
              .replace(">Bramblewick</h1>", ">Bramblewick — Spring menu</h1>") \
              .replace("Open most days.", "Open Tue–Sun, 7–3.") \
              .replace(">Order</a>", ">Order a celebration cake</a>")
NOTES = [("Say it is the spring menu", 160, 70), ("Give the real hours", 160, 210),
         ("Say what can be ordered", 160, 350)]

MOCK = """<!doctype html><html><head><meta charset="utf-8"><title>Spring menu</title><style>
:root{--accent:#7a2e2a;--gap:16px;--radius:8px}
body{margin:0;font-family:Georgia,serif;background:#fffaf2;color:#3b2a1e}
header{background:var(--accent);color:#fff;padding:var(--gap)}
main{display:grid;grid-template-columns:1fr 1fr;gap:var(--gap);padding:var(--gap)}
section{border-radius:var(--radius);background:#fff;padding:var(--gap)}
</style></head><body><header><h1>Spring menu</h1></header><main>
<section><h2>Breads</h2><p>Sourdough · Rye · Fougasse</p></section>
<section><h2>Sweet</h2><p>Rhubarb tart · Cardamom bun · Lemon slice</p></section></main></body></html>
"""
TOKENS = {"palette": [{"name": "Ink", "value": "#3b2a1e", "role": "text"},
                      {"name": "Paper", "value": "#fffaf2", "role": "background"},
                      {"name": "Brick", "value": "#7a2e2a", "role": "accent"}],
          "type": {"heading": "Georgia", "body": "Georgia", "mono": "", "scale": [16, 20, 28]},
          "spacing": [8, 16], "radii": [8], "voice": "Warm and plain."}

NOTES_KEY = "For each, change what it asks. Read them with agent_browser notes"
WHAT = "The spring menu: three breads and three sweets"
VARIANTS_KEY = f"Make 2 variants of the design in design/{SLUG}/"
SAM_NOTE = "The prices could be bigger."


def _script(project: str):
    folder = f"{project}/design/{SLUG}"
    return [
        {"key": "notes", "title": "Notes", "turns": [{"user": NOTES_KEY, "steps": [
            {"call": "agent_browser", "args": {"action": "notes"}},
            {"call": "write_file", "args": {"path": f"{project}/index.html", "content": CHANGED}},
            {"call": "agent_browser", "args": {"action": "reload"}},
            {"call": "agent_browser", "args": {"action": "note_done", "notes": [1, 2, 3],
                                               "said": "Changed as asked."}},
            {"say": "Changed all three, and the page is reloaded."}]}]},
        {"key": "design", "title": "Design", "turns": [{"user": WHAT, "steps": [
            {"call": "write_file", "args": {"path": f"{folder}/index.html", "content": MOCK}},
            {"say": "The page is there."}]}]},
        {"key": "variants", "title": "Design", "turns": [{"user": VARIANTS_KEY, "steps": [
            {"call": "write_file", "args": {"path": f"{folder}/variants/1/index.html",
                                            "content": MOCK.replace("1fr 1fr", "1fr")}},
            {"call": "write_file", "args": {"path": f"{folder}/variants/2/index.html",
                                            "content": MOCK.replace("#7a2e2a", "#2a5a7a")}},
            {"say": "Both variants are there."}]}]},
    ]


_DRIVE = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const C = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = {};
const COLOURS = { dark: { bg: '#282c34', fg: '#9cdef2', panel: '#111111', border: '#355a66', red: '#e06c75' },
                  light: { bg: '#f0ebe3', fg: '#5a5248', panel: '#faf6f0', border: '#d4cdc2', red: '#c47d5a' } };

async function open(browser, who, size, theme) {
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
    { data: { username: who, password: C.passwords[who], remember: true } });
  if (!r.ok()) throw new Error('login ' + who + ' ' + r.status());
  const page = await ctx.newPage();
  page.__errors = [];
  page.on('pageerror', (e) => page.__errors.push(String(e.message || e)));
  await page.goto(C.base + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);
  return { ctx, page, phone };
}

async function pick(page) {
  await page.evaluate(() => document.activeElement && document.activeElement.blur && document.activeElement.blur());
  try { await page.click('#model-picker-btn', { timeout: 4000 }); }
  catch (_) { await page.evaluate(() => document.getElementById('model-picker-btn').click()); }
  await page.waitForTimeout(900);
  await page.locator('.model-switch-item', { hasText: C.model }).first().click();
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

async function row(page, label) {
  await page.locator('.composer-submenu .composer-submenu-row', { hasText: label }).first().click();
  await page.waitForTimeout(800);
}

async function attachShop(page) { await plus(page); await submenu(page, 'git'); await row(page, 'shop'); }

const lastReply = (page) => page.evaluate(() => {
  const err = [...document.querySelectorAll('.reply-error-text')].pop();
  const body = [...document.querySelectorAll('.msg-ai .body')].pop();
  return (err ? 'ERROR ' + err.textContent : '') || (body ? body.textContent.trim() : '');
});

// Wait for the agent's reply, answering a card when one comes; a window lying
// over the card is lowered to reach it, and raised again afterwards.
async function reply(page, until, ms = 90000) {
  const t0 = Date.now();
  const covered = [];
  let asked = 0;
  while (Date.now() - t0 < ms) {
    await page.waitForTimeout(700);
    const card = page.locator('button[data-decision="approve_task"], button[data-decision="approve"]').first();
    if (await card.isVisible().catch(() => false)) {
      asked += 1;
      await page.waitForTimeout(300);
      const top = await card.evaluate((b) => { const r = b.getBoundingClientRect();
        const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        const win = at && at.closest('.modal'); return win ? win.id : ''; });
      if (top) { covered.push(top); await page.click(`#${top} .modal-minimize-btn`).catch(() => {}); await page.waitForTimeout(500); }
      await card.click({ timeout: 10000 });
      await page.waitForTimeout(1000);
      continue;
    }
    const said = await lastReply(page);
    if (until.test(said) || /^ERROR /.test(said)) break;
  }
  await page.waitForTimeout(800);
  return { reply: await lastReply(page), asked, covered };
}

async function sendText(page, text, until) {
  await page.fill('#message', text);
  const phone = await page.evaluate(() => window.matchMedia('(max-width: 768px)').matches);
  if (phone) await page.click('.send-btn'); else await page.press('#message', 'Enter');
  return reply(page, until);
}

const fitsIn = (page, sel) => page.evaluate((sel) => {
  const n = document.querySelector(sel);
  const r = n ? n.getBoundingClientRect() : null;
  return { there: !!r && r.width > 0, inside: !!r && r.left >= -1 && r.right <= window.innerWidth + 1
    && r.top >= -1 && r.bottom <= window.innerHeight + 1,
    rect: r ? [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)] : null,
    pageScrollsSideways: document.documentElement.scrollWidth > window.innerWidth + 1 };
}, sel);

const say = (page, sel) => page.evaluate((sel) => [...document.querySelectorAll(sel)]
  .map((n) => n.textContent.trim()).filter(Boolean), sel);

// What the window says, once it says something matching `re` (a loaded box is slow).
async function heard(page, re, ms = 20000) {
  const t0 = Date.now();
  let got = [];
  while (Date.now() - t0 < ms) {
    got = (await say(page, '#design-modal [role="status"], #design-modal .design-note')).filter((t) => re.test(t));
    if (got.length) break;
    await page.waitForTimeout(400);
  }
  return got;
}

// A point on the page, in page pixels, where the window draws it.
async function onPage(page, ctx, x, y) {
  const f = await (await ctx.request.get(C.base + '/api/workstation/browser')).json();
  const r = await page.$eval('#agent-browser-modal .abw-frame', (n) => { const b = n.getBoundingClientRect();
    return { left: b.left, top: b.top, width: b.width, height: b.height }; });
  return { x: r.left + (x / f.width) * r.width, y: r.top + (y / f.height) * r.height };
}

async function openDesign(page, phone) {
  await plus(page);
  await submenu(page, 'design');
  await page.locator('.composer-submenu .composer-submenu-row, .composer-submenu .composer-submenu-foot',
    { hasText: 'Open Design' }).first().click();
  await page.waitForSelector('#design-modal .design-body, #design-modal .modal-body', { timeout: 20000 });
  await page.waitForTimeout(1200);
}

// The design, open in its window — raised from the dock if it was lowered.
async function theDesign(page) {
  if (!(await page.$('#design-modal .design-view-bar')) || !(await page.isVisible('#design-modal .design-view-bar').catch(() => false))) {
    await openDesign(page, false);
    if (!(await page.isVisible('#design-modal .design-view-bar').catch(() => false))) {
      await page.locator('#design-modal .design-design-card', { hasText: 'Spring menu' }).first().click();
      await page.waitForSelector('#design-modal .design-view-bar', { timeout: 20000 });
    }
    await page.waitForTimeout(1200);
  }
}

// What each design frame on the page actually loaded.
const frames = (page) => Promise.all(page.frames().filter((f) => f.url().includes('/preview'))
  .map(async (f) => ({ url: f.url().replace(/^.*\/api/, '/api'),
    text: (await f.evaluate(() => document.body ? document.body.innerText.slice(0, 80) : '').catch((e) => 'ERR ' + e.message)),
    shell: await f.evaluate(() => !!document.getElementById('message')).catch(() => null) })));

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });

  // ── rowan, 1440×900, dark: notes on the dev server's page ────────────────
  {
    const { ctx, page } = await open(browser, 'rowan', [1440, 900], 'dark');
    const o = {};
    try {
      await pick(page);
      await attachShop(page);
      await plus(page);
      await page.click('#overflow-menu [data-open-agent-browser]');
      await page.waitForSelector('#agent-browser-modal .abw-address', { timeout: 15000 });
      await page.waitForTimeout(2500);
      await page.fill('#agent-browser-modal .abw-address', C.dev);
      await page.press('#agent-browser-modal .abw-address', 'Enter');
      const t0 = Date.now();
      while (Date.now() - t0 < 30000) {
        await page.waitForTimeout(800);
        const f = await (await ctx.request.get(C.base + '/api/workstation/browser')).json().catch(() => ({}));
        if ((f.url || '').startsWith(C.dev) && f.title) break;
      }
      await page.waitForTimeout(2000);
      for (const [words, x, y] of C.notes) {
        await page.click('#agent-browser-modal .abw-note-mode');
        await page.waitForTimeout(300);
        const at = await onPage(page, ctx, x, y);
        await page.mouse.click(at.x, at.y);
        await page.waitForSelector('#agent-browser-modal .abw-note-editor textarea', { timeout: 10000 });
        await page.fill('#agent-browser-modal .abw-note-editor textarea', words);
        await page.click('#agent-browser-modal .abw-note-editor button[type="submit"]');
        await page.waitForTimeout(1200);
      }
      o.pinned = await say(page, '#agent-browser-modal .abw-note-item .abw-note-text');
      // An arrow on the first note: Draw, then a drag over the page.
      await page.locator('#agent-browser-modal .abw-note-item').first()
        .locator('.abw-note-tool', { hasText: 'Draw' }).click();
      await page.waitForTimeout(400);
      const a = await onPage(page, ctx, 700, 110);
      const b = await onPage(page, ctx, 420, 70);
      await page.mouse.move(a.x, a.y); await page.mouse.down();
      await page.mouse.move((a.x + b.x) / 2, (a.y + b.y) / 2, { steps: 4 });
      await page.mouse.move(b.x, b.y, { steps: 4 }); await page.mouse.up();
      await page.waitForTimeout(1200);
      await page.locator('#agent-browser-modal .abw-note-item').first()
        .locator('.abw-note-tool', { hasText: 'Done drawing' }).click().catch(() => {});
      o.marks = await page.$$eval('#agent-browser-modal .abw-note-mark', (ns) => ns.length);
      o.sendLabel = (await say(page, '#agent-browser-modal .abw-notes-send'))[0] || '';
      o.fits = await fitsIn(page, '#agent-browser-modal .modal-content');
      await page.click('#agent-browser-modal .abw-notes-send');
      o.sent = await reply(page, /Changed all three/);
      o.message = await page.evaluate(() => { const u = [...document.querySelectorAll('.msg-user')].pop();
        return u ? u.innerText : ''; });
      if (o.sent.covered.length) {
        await plus(page);
        await page.click('#overflow-menu [data-open-agent-browser]');
      }
      await page.waitForTimeout(4000);
      o.after = await page.evaluate(() => ({
        done: document.querySelectorAll('#agent-browser-modal .abw-note-item.abw-note-done').length,
        said: [...document.querySelectorAll('#agent-browser-modal .abw-note-said')].map((n) => n.textContent),
        pinsDone: document.querySelectorAll('#agent-browser-modal .abw-note-pin.abw-note-done').length }));
      o.frame = await (await ctx.request.get(C.base + '/api/workstation/browser')).json().then((f) => ({ url: f.url, title: f.title }));
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors;
    out.notes = o;
    await ctx.close();
  }

  // ── rowan, 1440×900, light: a Mockup, two variants, a tweak, a commenter ──
  {
    const { ctx, page } = await open(browser, 'rowan', [1440, 900], 'light');
    const o = {};
    try {
      await page.locator('#sidebar-new-chat-btn').first().click();
      await page.waitForTimeout(1200);
      await pick(page);
      await attachShop(page);
      await plus(page);
      await submenu(page, 'design');
      await row(page, 'Mockup');
      await page.waitForSelector('#design-modal form.design-brief', { timeout: 20000 });
      const fields = page.locator('#design-modal form.design-brief .design-field');
      await fields.nth(0).locator('input').fill('Spring menu');
      await fields.nth(1).locator('input').fill("Customers on the bakery's site");
      await fields.nth(2).locator('textarea').fill(C.what);
      await fields.nth(3).locator('input').fill('The menu page');
      await fields.nth(4).locator('input').fill('Desktop 1440 wide');
      o.system = await page.$eval('#design-modal form.design-brief select', (s) => s.options[s.selectedIndex].textContent);
      await page.click('#design-modal form.design-brief button[type="submit"]');
      o.made = await reply(page, /The page is there/);
      await theDesign(page);
      await page.locator('#design-modal .design-view-bar button', { hasText: 'Refresh' }).first().click().catch(() => {});
      await page.waitForTimeout(2500);
      o.versions1 = await say(page, '#design-modal .design-version-pick');
      o.frames1 = await frames(page);
      const pv = await ctx.request.get(C.base + `/api/design/designs/${C.slug}/preview?project=${encodeURIComponent(C.project)}`);
      o.previewDirect = { status: pv.status(), type: pv.headers()['content-type'], csp: pv.headers()['content-security-policy'] || '',
        head: (await pv.text()).slice(0, 120) };
      await page.locator('#design-modal .design-view-bar button', { hasText: 'Try variants' }).click();
      o.variantsAsked = await reply(page, /Both variants are there/);
      await theDesign(page);
      await page.locator('#design-modal .design-view-bar button', { hasText: 'Refresh' }).first().click();
      await page.waitForTimeout(2500);
      o.sideBySide = await page.$$eval('#design-modal .design-variant', (ns) => ns.length);
      await page.locator('#design-modal .design-variant').nth(1).locator('button', { hasText: 'Keep this' }).click();
      o.keptNote = await heard(page, /Kept variant/);
      await page.waitForTimeout(800);
      o.versions2 = await say(page, '#design-modal .design-version-pick');
      await page.locator('#design-modal .design-view-bar button', { hasText: 'Tweaks' }).click();
      await page.waitForSelector('#design-modal .design-tweak input[type="range"]', { timeout: 15000 });
      o.tweaks = await say(page, '#design-modal .design-tweak > span');
      await page.$eval('#design-modal .design-tweak input[type="range"]', (i) => {
        i.value = String(Number(i.max)); i.dispatchEvent(new Event('input', { bubbles: true })); });
      o.tweaked = await heard(page, /Tweaked/);
      await page.waitForTimeout(800);
      o.versions3 = await say(page, '#design-modal .design-version-pick');
      await page.fill('#design-modal input[aria-label="Account to invite"]', 'sam');
      await page.click('#design-modal .design-share-form button[type="submit"]');
      await page.waitForTimeout(1500);
      o.shares = await say(page, '#design-modal .design-share-name');
      o.fits = await fitsIn(page, '#design-modal .modal-content');
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors;
    out.design = o;
    await ctx.close();
  }

  // ── sam, 390×844, dark: a commenter's note, and no edit ──────────────────
  {
    const { ctx, page, phone } = await open(browser, 'sam', [390, 844], 'dark');
    const o = {};
    try {
      await openDesign(page, phone);
      await page.locator('#design-modal .design-shared .design-design-card').first().click();
      await page.waitForSelector('#design-modal .design-view-bar', { timeout: 20000 });
      await page.waitForTimeout(2000);
      o.bar = await say(page, '#design-modal .design-view-bar > *');
      await page.fill('#design-modal textarea[aria-label="New note"]', C.samNote);
      await page.click('#design-modal .design-note-form button[type="submit"]');
      await page.waitForTimeout(1500);
      o.notes = await page.$$eval('#design-modal .design-note-item', (ns) => ns.map((n) => n.innerText));
      o.fits = await fitsIn(page, '#design-modal .modal-content');
      // An edit sent anyway, as sam: the server answers it.
      const shared = await (await ctx.request.get(C.base + '/api/design/shared')).json();
      const share = ((shared.designs || [])[0] || {}).share;
      const edit = await ctx.request.post(C.base + `/api/design/designs/${C.slug}/adjust`,
        { data: { share, selector: ':root', props: { '--gap': '40px' } } });
      o.edit = { status: edit.status(), body: await edit.text() };
      const keep = await ctx.request.post(C.base + `/api/design/designs/${C.slug}/versions`, { data: { share } });
      o.version = { status: keep.status() };
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors;
    out.commenter = o;
    await ctx.close();
  }

  // ── rowan, 390×844, light: Build it ─────────────────────────────────────
  {
    const { ctx, page, phone } = await open(browser, 'rowan', [390, 844], 'light');
    const o = {};
    try {
      await attachShop(page);
      await openDesign(page, phone);
      await page.locator('#design-modal .design-design-card', { hasText: 'Spring menu' }).first().click();
      await page.waitForSelector('#design-modal .design-view-bar', { timeout: 20000 });
      await page.waitForTimeout(1500);
      await page.locator('#design-modal .design-view-bar button', { hasText: 'Build it' }).click();
      await page.waitForSelector('#design-modal .design-build button', { timeout: 15000 });
      await page.fill('#design-modal .design-build textarea[aria-label="Acceptance"]', 'Works at 390px wide');
      await page.locator('#design-modal .design-build button', { hasText: 'Make the branch' }).click();
      o.said = await heard(page, /Made design\//, 30000);
      await page.waitForTimeout(1500);
      o.build = await say(page, '#design-modal .design-build .design-section-sub');
      o.fits = await fitsIn(page, '#design-modal .modal-content');
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors;
    out.build = o;
    await ctx.close();
  }

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


class _Dev(SimpleHTTPRequestHandler):
    hits: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        type(self).hits.append(self.path)
        return super().do_GET()


@pytest.fixture(scope="module")
def drive(tmp_path_factory):
    import capture
    import httpx

    from src.workstation_client import account_for
    from tests.helpers.workstation_daemon import running_workstation

    work = tmp_path_factory.mktemp("p26-00")
    data = work / "data"
    data.mkdir()
    server = capture.Server(sys.executable, data, capture._free_port(),
                            extra_env={"PANTHEON_DISABLE_MCP": "1"})
    try:
        server.start(timeout=150)
    except RuntimeError as e:
        server.stop()
        pytest.fail(f"{e}\n{server.log_path.read_text(encoding='utf-8', errors='replace')[-3000:]}")
    log: list = []
    seen: dict = {}
    dev_srv = None
    try:
        with running_workstation(work) as ws:
            client = httpx.Client(base_url=server.base, timeout=180)
            passwords = {"rowan": secrets.token_urlsafe(18), "sam": secrets.token_urlsafe(18)}
            seed.setup_admin(client, passwords["rowan"])
            seed._ok(client.post("/api/auth/users", json={"username": "sam", "password": passwords["sam"],
                                                          "is_admin": False}), "sam")
            seed._ok(client.post("/api/auth/settings", json={
                "workstation_url": ws.url, "workstation_token": ws.token,
                "workstation_enabled": True}), "workstation settings")
            assert seed._ok(client.post("/api/workstation/check"), "check").get("state") == "up"
            seed._ok(client.get("/api/workstation/screen", timeout=120), "first workstation frame")
            seed._ok(client.put("/api/git", json={"identity": {"name": NAME, "email": EMAIL}}), "git identity")
            home = ws.root / account_for(seed.PERSON["username"])
            repo = home / "projects" / "shop"
            repo.mkdir(parents=True)
            run = lambda *a: subprocess.run([GIT, *a], cwd=repo, check=True, capture_output=True, text=True)
            run("init", "-q", "-b", "main")
            (repo / "index.html").write_text(PAGE)
            run("add", "--all")
            run("-c", "user.name=Setup", "-c", "user.email=setup@example.org", "commit", "-q", "-m", "First page")
            base = run("rev-parse", "main").stdout.strip()
            _Dev.hits = []
            dev_srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Dev, directory=str(repo)))
            threading.Thread(target=dev_srv.serve_forever, daemon=True).start()
            dev = f"http://127.0.0.1:{dev_srv.server_address[1]}/"
            # The project's design system, made earlier, as a project's: its
            # tokens file is in the project.
            seed._ok(client.post("/api/design/systems", json={
                "name": "Bramblewick", "scope": "project", "project": str(repo), "tokens": TOKENS}),
                "design system")
            # A model that says its window, as vLLM, llama-server and Ollama do:
            # the notes and their three pictures are one message, and with no
            # window known Pantheon budgets 6,000 tokens and cuts its middle.
            with demo_model.DemoModel(log=log, conversations=_script(str(repo)),
                                      model_id=seed.DEMO_MODEL_ID, max_model_len=131072) as model:
                seed.register_demo_model(client, model.base_url)
                config = {"base": server.base, "passwords": passwords, "model": seed.DEMO_MODEL_ID,
                          "dev": dev, "notes": NOTES, "what": WHAT, "slug": SLUG, "samNote": SAM_NOTE,
                          "project": str(repo)}
                (work / "config.json").write_text(json.dumps(config))
                (work / "drive.cjs").write_text(_DRIVE)
                proc = subprocess.run([NODE, str(work / "drive.cjs"), str(work / "config.json")],
                                      capture_output=True, text=True, timeout=1200, cwd=ROOT)
                assert proc.returncode == 0, proc.stderr[-3000:]
                seen = json.loads(proc.stdout.strip().splitlines()[-1])
            seen["devHits"] = list(_Dev.hits)
            seen["modelSaw"] = [{"conv": e.get("conv"), "first": e.get("first"), "stream": e.get("stream"),
                                 "tools": e.get("tools"),
                                 "lastUser": next((str(m.get("content"))[:300] for m in reversed(e.get("messages") or [])
                                                   if m.get("role") == "user"), "")} for e in log]
            seen["page"] = (repo / "index.html").read_text()
            branch = subprocess.run([GIT, "-C", str(repo), "branch", "--list", f"design/{SLUG}"],
                                    capture_output=True, text=True).stdout.strip()
            seen["branch"] = branch
            seen["brief"] = subprocess.run([GIT, "-C", str(repo), "show", f"design/{SLUG}:design/{SLUG}/BUILD.md"],
                                           capture_output=True, text=True).stdout
            seen["baseNow"] = run("rev-parse", "main").stdout.strip()
            seen["base"] = base
            seen["tokensFile"] = (repo / "design" / "systems" / "bramblewick.tokens.json").exists()
            (work / "seen.json").write_text(json.dumps(seen, indent=1, default=str))
            ws.station.browsers.stop_all()
        yield {"seen": seen, "log": log}
    finally:
        if dev_srv is not None:
            dev_srv.shutdown()
        server.stop()


def test_three_notes_and_an_arrow_are_sent_as_one_message(drive):
    n = drive["seen"]["notes"]
    assert not n.get("crash"), n.get("crash")
    assert n["pinned"] == [w for w, _x, _y in NOTES], n["pinned"]
    assert n["marks"] >= 1, "the arrow is drawn over the page"
    assert n["sendLabel"] == "Send 3 notes"
    assert "I left 3 notes" in n["message"] and "[1 mark drawn]" in n["message"], n["message"]


def test_the_agent_changes_the_files_and_the_page_reloads_with_each_note_done(drive):
    seen = drive["seen"]
    n = seen["notes"]
    assert "Changed all three" in n["sent"]["reply"], n["sent"]
    assert seen["page"] == CHANGED, "the project's file is the agent's"
    assert seen["devHits"].count("/") >= 2, seen["devHits"]
    assert n["frame"]["title"] == "Bramblewick — Spring menu", n["frame"]
    assert n["after"]["done"] == 3 and n["after"]["said"] == ["Agent: Changed as asked."] * 3, n["after"]


def test_a_mockup_with_the_projects_design_system_two_variants_one_kept_and_a_tweak(drive):
    d = drive["seen"]["design"]
    assert not d.get("crash"), d.get("crash")
    assert d["system"] == "Bramblewick"
    assert "The page is there" in d["made"]["reply"]
    assert d["versions1"], "the agent's page is version 1"
    assert d["sideBySide"] == 2
    assert d["keptNote"], d
    assert len(d["versions2"]) > len(d["versions1"]), (d["versions1"], d["versions2"])
    assert d["tweaks"], "the page's own variables are offered as tweaks"
    assert d["tweaked"] and len(d["versions3"]) > len(d["versions2"]), (d["tweaked"], d["versions3"])
    assert d["shares"] == ["sam"]
    assert drive["seen"]["tokensFile"], "the project's design system is a file in the project"


def test_a_commenter_adds_a_note_and_cannot_edit(drive):
    c = drive["seen"]["commenter"]
    assert not c.get("crash"), c.get("crash")
    assert "You can comment" in c["bar"], c["bar"]
    assert not any(b in c["bar"] for b in ("Tweaks", "Try variants", "Build it", "Keep a version")), c["bar"]
    assert any(SAM_NOTE in t for t in c["notes"]), c["notes"]
    assert c["edit"]["status"] == 403 and c["version"]["status"] == 403, (c["edit"], c["version"])


def test_handed_off_it_lands_as_a_branch_with_the_notes_and_tokens_beside_it(drive):
    seen = drive["seen"]
    b = seen["build"]
    assert not b.get("crash"), b.get("crash")
    assert b["said"], b
    # `+`: git marks a branch that is checked out in a worktree.
    assert seen["branch"].strip("*+ ").strip() == f"design/{SLUG}", seen["branch"]
    brief = seen["brief"]
    assert SAM_NOTE in brief and "sam" in brief, brief[:2000]
    assert "#7a2e2a" in brief.lower() or "brick" in brief.lower(), brief[:2000]
    assert seen["baseNow"] == seen["base"], "nothing reached the base branch"


@pytest.mark.xfail(strict=True, reason=(
    "P26-00: after the notes are read, the agent's write asks, and so does a variant's — and at "
    "1440x900 the card lands under the window the person is working in (the browser window, the "
    "Design window): the press on Allow hits the window. The drive lowers the window to answer. "
    "The same finding as P25-00's; filed as one new row."))
def test_the_agents_questions_are_not_under_the_windows_they_are_asked_from(drive):
    seen = drive["seen"]
    assert seen["notes"]["sent"]["covered"] == [] and seen["design"]["variantsAsked"]["covered"] == [], (
        seen["notes"]["sent"]["covered"], seen["design"]["variantsAsked"]["covered"])


def test_every_size_and_palette_fits_and_nothing_threw(drive):
    seen = drive["seen"]
    for k in ("notes", "design", "commenter", "build"):
        o = seen[k]
        f = o["fits"]
        assert f["there"] and f["inside"] and not f["pageScrollsSideways"], (k, f)
        # Playwright's `serviceWorkers: 'block'` reaches into every frame, and in
        # a design's preview — sandboxed without allow-same-origin, by design —
        # its own read of `navigator.serviceWorker` throws. The harness's, not
        # the page's: the frames' own text is read in the drive.
        errors = [e for e in o["errors"] if "Failed to read the 'serviceWorker' property" not in e]
        assert errors == [], (k, errors)
