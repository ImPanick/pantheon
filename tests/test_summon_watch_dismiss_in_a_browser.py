# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-00` — acceptance: summon one, watch it work, dismiss it, from the
sidebar and never opening Tasks.

The row's words are the hall's first ones: *hire* is **Summon** on the page now,
and *Fire* is **Dismiss…** (a trial's is *Discard…*). The flow is the row's:

  * **ann** (a member), 1440×900 dark: sidebar → *Agents* → the *Personal &
    Home* chip → *Morning Brief* → a time → **Summon** → **Run now**; the run
    ends with a report on the hire's own page that says what it read, what it
    was refused, and that it delivered (*Today*);
  * **sam** (a member), 390×844 light: the same catalogue, none of ann's
    summons; summons one of his own;
  * **rowan** (the admin), 1440×900 light: *Everyone* shows both of theirs;
  * **ann** again, 390×844 dark: her hire from the strip, **Pause** (its
    schedule stops: the task is paused with no next run), **Dismiss…** (every
    task it made is gone).

Driven (`Law 20`): this checkout's `app.py` booted out of process on a
throwaway data directory with authentication on (`capture.Server`), headless
Chromium doing what a person does, and the scheduler running the hire's real
task against the showcase's scripted model (`demo_model`), which plays the
Morning Brief's tool calls; Pantheon runs them, refuses what a member may not
use, and keeps the report. What the page says is read from the page; what the
schedule and the tasks are is read from the API, as the person's own.

**Found by this drive, on `f3a9150e`:** a refused call was two steps in the run's
log — the `tool_blocked`, and its refusal again as an `error` with no
arguments — and the report counted the second by the tool's whole reach: ann's
Morning Brief, refused the calendar, mail and tasks, reported *Wrote with:
manage_calendar, manage_tasks* and *Read with: list_emails, manage_notes*. It
read her notes and wrote nothing (`TaskScheduler._close_run_step`; unit-held in
`tests/test_a_hired_agent_runs_as_its_file_says.py`).
"""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402
import seed  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

#: What every hire's task is told (`src.agents.hires.TASK_PROMPT`): the
#: scripted model knows its turn by these words.
TASK_PROMPT = "Do the job your runbook describes, now, and finish with your report."
BRIEF = ("**Today** — nothing on the calendar.\n\n**Mail that needs you** — nothing.\n\n"
         "**Due** — nothing.\n\n**Overnight** — nothing.\n\n"
         "## Report\n- read the calendar, mail, notes and tasks\n\n## Carry forward\n- nothing")
SCRIPT = [{"key": "brief", "title": "Morning Brief", "turns": [{"user": TASK_PROMPT, "steps": [
    {"call": "manage_calendar", "args": {"action": "list_events"}},
    {"call": "list_emails", "args": {"unread_only": True, "limit": 20}},
    {"call": "manage_notes", "args": {"action": "list"}},
    {"call": "manage_tasks", "args": {"action": "list"}},
    {"say": BRIEF}]}]}]

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
    } catch (_) {}
  }, { theme: JSON.stringify({ name: theme, colors: COLOURS[theme] }) });
  const r = await ctx.request.post(C.base + '/api/auth/login',
    { data: { username: who, password: C.passwords[who], remember: true } });
  if (!r.ok()) throw new Error('login ' + who + ' ' + r.status());
  const page = await ctx.newPage();
  page.__errors = [];
  page.__asked = [];
  page.on('pageerror', (e) => page.__errors.push(String(e.message || e)));
  page.on('request', (q) => { const u = new URL(q.url()); if (u.pathname.startsWith('/api/')) page.__asked.push(q.method() + ' ' + u.pathname); });
  await page.goto(C.base + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);
  return { ctx, page, phone };
}

// The sidebar's Agents — through the drawer on a phone, as a thumb reaches it.
async function agents(page, phone) {
  if (phone) { await page.click('#hamburger-btn'); await page.waitForTimeout(700); }
  await page.click('#tool-agents-btn');
  await page.waitForSelector('#agents-modal .agents-chips', { timeout: 20000 });
  await page.waitForTimeout(500);
}

const fits = (page) => page.evaluate(() => {
  const m = document.querySelector('#agents-modal .modal-content');
  const r = m ? m.getBoundingClientRect() : null;
  return { pageScrollsSideways: document.documentElement.scrollWidth > window.innerWidth + 1,
           windowInside: !!r && r.left >= -1 && r.right <= window.innerWidth + 1,
           bodyScrollsSideways: !!m && [...m.querySelectorAll('.agents-body')].some((b) => b.scrollWidth > b.clientWidth + 1) };
});

const hall = (page) => page.evaluate(() => {
  const q = (s) => [...document.querySelectorAll(s)];
  return {
    stripTitle: (document.querySelector('#agents-modal .agents-strip .agents-h') || {}).textContent || '',
    summoned: (document.querySelector('#agents-modal .agents-count') || {}).textContent || '',
    hires: q('#agents-modal .agents-hire-card').map((c) => ({ name: c.querySelector('.agents-card-name').textContent,
      owner: (c.querySelector('.agents-card-tag') || {}).textContent || '', status: c.dataset.status })),
    search: (document.querySelector('#agents-modal .agents-search') || {}).placeholder || '',
    catalogue: q('#agents-modal .agents-catalogue [data-agent]').map((c) => c.dataset.agent).sort(),
    chips: q('#agents-modal .agents-chip').map((c) => c.textContent),
    everyone: !!document.querySelector('#agents-modal .agents-everyone'),
  };
});

const hirePage = (page) => page.evaluate(() => {
  const p = document.querySelector('#agents-modal .agents-page');
  if (!p) return null;
  const run = p.querySelector('.agents-run');
  if (run) run.open = true;
  return {
    name: (p.querySelector('.agents-page-name') || {}).textContent || '',
    status: (p.querySelector('.agents-status') || {}).textContent || '',
    meta: (p.querySelector('.agents-page-meta') || {}).textContent || '',
    buttons: [...p.querySelectorAll('.agents-actions button')].map((b) => b.textContent),
    runs: [...p.querySelectorAll('.agents-run')].map((r) => ({ cls: r.className, text: r.innerText })),
    note: (document.querySelector('#agents-modal .agents-note') || {}).textContent || '',
  };
});

async function press(page, label) {
  await page.locator('#agents-modal .agents-actions button', { hasText: label }).first().click();
  await page.waitForTimeout(900);
}

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });

  // ── ann, 1440×900, dark: summon, run now, read the report ────────────────
  {
    const { ctx, page, phone } = await open(browser, 'ann', [1440, 900], 'dark');
    const o = {};
    try {
      await agents(page, phone);
      o.hallBefore = await hall(page);
      await page.click('#agents-modal .agents-chip[data-section="personal-home"]');
      await page.waitForTimeout(400);
      o.inSection = await hall(page);
      await page.click('#agents-modal .agents-card[data-agent="morning-brief"]');
      await page.waitForSelector('#agents-modal .agents-form', { timeout: 15000 });
      o.lacking = await page.evaluate(() => (document.querySelector('#agents-modal .agents-lacking') || {}).innerText || '');
      await page.fill('#agents-modal .agents-form input[data-input="at"]', '06:45');
      await page.click('#agents-modal .agents-form button[type="submit"]');
      await page.waitForSelector('#agents-modal .agents-page .agents-status', { timeout: 15000 });
      await page.waitForTimeout(600);
      o.summoned = await hirePage(page);
      await press(page, 'Run now');
      const t0 = Date.now();
      while (Date.now() - t0 < 90000) {
        await page.waitForTimeout(1500);
        const h = await hirePage(page);
        if (h && h.runs.length && !/agents-run-(queued|running)/.test(h.runs[0].cls)) break;
      }
      await page.waitForTimeout(800);
      o.ran = await hirePage(page);
      o.fits = await fits(page);
      o.tasksOpened = await page.evaluate(() => !!document.getElementById('tasks-modal')
        && !document.getElementById('tasks-modal').classList.contains('hidden'));
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors;
    o.askedTasks = page.__asked.filter((a) => / \/api\/tasks(\/|$)/.test(a));
    out.ann = o;
    await ctx.close();
  }

  // ── sam, 390×844, light: the same catalogue, none of ann's; one of his own ──
  {
    const { ctx, page, phone } = await open(browser, 'sam', [390, 844], 'light');
    const o = {};
    try {
      await agents(page, phone);
      o.hall = await hall(page);
      o.fits = await fits(page);
      await page.click('#agents-modal .agents-card[data-agent="morning-brief"]');
      await page.waitForSelector('#agents-modal .agents-form', { timeout: 15000 });
      await page.click('#agents-modal .agents-form button[type="submit"]');
      await page.waitForSelector('#agents-modal .agents-page .agents-status', { timeout: 15000 });
      await page.waitForTimeout(600);
      o.summoned = await hirePage(page);
      o.fitsHire = await fits(page);
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors;
    out.sam = o;
    await ctx.close();
  }

  // ── rowan, 1440×900, light: Everyone ────────────────────────────────────────
  {
    const { ctx, page, phone } = await open(browser, 'rowan', [1440, 900], 'light');
    const o = {};
    try {
      await agents(page, phone);
      o.own = await hall(page);
      await page.click('#agents-modal .agents-everyone input');
      await page.waitForTimeout(1500);
      o.everyone = await hall(page);
      o.fits = await fits(page);
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors;
    out.rowan = o;
    await ctx.close();
  }

  // ── ann, 390×844, dark: Pause, then Dismiss ─────────────────────────────────
  {
    const { ctx, page, phone } = await open(browser, 'ann', [390, 844], 'dark');
    const o = {};
    try {
      await agents(page, phone);
      const hireId = await page.evaluate(() => document.querySelector('#agents-modal .agents-hire-card').dataset.hire);
      await page.click('#agents-modal .agents-hire-card');
      await page.waitForSelector('#agents-modal .agents-page .agents-status', { timeout: 15000 });
      await page.waitForTimeout(600);
      o.before = await hirePage(page);
      await press(page, 'Pause');
      await page.waitForTimeout(600);
      o.paused = await hirePage(page);
      // The schedule, as the API answers ann (not a page request: Tasks stays shut).
      const api = async (path) => (await ctx.request.get(C.base + path)).json();
      o.pausedHire = await api('/api/agents/hires/' + hireId);
      o.pausedTasks = ((await api('/api/tasks')).tasks || []).filter((t) => (t.name || '').includes('Morning Brief'))
        .map((t) => ({ id: t.id, status: t.status, next_run: t.next_run }));
      o.fits = await fits(page);
      await press(page, 'Dismiss');
      await page.waitForSelector('#styled-confirm-ok', { timeout: 10000 });
      o.question = await page.evaluate(() => (document.getElementById('styled-confirm-overlay') || {}).innerText || '');
      await page.click('#styled-confirm-ok');
      await page.waitForTimeout(1500);
      o.after = await hall(page);
      o.note = await page.evaluate(() => (document.querySelector('#agents-modal .agents-note') || {}).textContent || '');
    } catch (e) { o.crash = String(e && e.stack || e); }
    o.errors = page.__errors;
    o.askedTasks = page.__asked.filter((a) => / \/api\/tasks(\/|$)/.test(a));
    out.annAgain = o;
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

    work = tmp_path_factory.mktemp("p24-00")
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
    try:
        admin = httpx.Client(base_url=server.base, timeout=120)
        passwords = {"rowan": secrets.token_urlsafe(18), "ann": secrets.token_urlsafe(18),
                     "sam": secrets.token_urlsafe(18)}
        seed.setup_admin(admin, passwords["rowan"])
        with demo_model.DemoModel(log=log, conversations=SCRIPT, model_id=seed.DEMO_MODEL_ID) as model:
            seed.register_demo_model(admin, model.base_url)
            for who in ("ann", "sam"):
                seed._ok(admin.post("/api/auth/users", json={"username": who, "password": passwords[who],
                                                             "is_admin": False}), who)
            people = {}
            for who in ("ann", "sam"):
                people[who] = httpx.Client(base_url=server.base, timeout=120)
                seed._ok(people[who].post("/api/auth/login", json={"username": who, "password": passwords[who]}),
                         f"{who} signs in")
            config = {"base": server.base, "passwords": passwords}
            (work / "config.json").write_text(json.dumps(config))
            (work / "drive.cjs").write_text(_DRIVE)
            proc = subprocess.run([NODE, str(work / "drive.cjs"), str(work / "config.json")],
                                  capture_output=True, text=True, timeout=900, cwd=ROOT)
            assert proc.returncode == 0, proc.stderr[-3000:]
            seen = json.loads(proc.stdout.strip().splitlines()[-1])
            seen["annHires"] = people["ann"].get("/api/agents").json().get("hires")
            seen["annTasks"] = [t for t in (people["ann"].get("/api/tasks").json().get("tasks") or [])
                                if "Morning Brief" in (t.get("name") or "")]
            seen["samHires"] = people["sam"].get("/api/agents").json().get("hires")
        yield {"seen": seen, "log": log, "server": server}
    finally:
        server.stop()


def _lines(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def test_summoned_from_the_sidebar_with_a_time(drive):
    ann = drive["seen"]["ann"]
    assert not ann.get("crash"), ann.get("crash")
    assert ann["hallBefore"]["summoned"] == "0 summoned"
    assert "morning-brief" in ann["inSection"]["catalogue"]
    assert any(c.startswith("Personal & Home") for c in ann["inSection"]["chips"])
    s = ann["summoned"]
    assert s["name"].startswith("Morning Brief") and s["status"] == "On"
    assert "Starts on daily at 06:45" in s["meta"], s["meta"]
    assert "Run now" in s["buttons"] and "Pause" in s["buttons"]


def test_run_now_ends_with_a_report_on_the_agents_own_page(drive):
    ann = drive["seen"]["ann"]
    run = ann["ran"]["runs"][0]
    assert "agents-run-success" in run["cls"], run
    text = run["text"]
    assert "Today" in text, text
    # What it read and what it was refused — and not what it never did.
    assert "Read with: manage_notes" in _lines(text), text
    assert not any(ln.startswith("Wrote with") for ln in _lines(text)), text
    for tool in ("manage_calendar", "list_emails", "manage_tasks"):
        assert any(ln.startswith(f"Refused {tool}") for ln in _lines(text)), (tool, text)
    assert "✓ It answered, with Today." in text, text
    # The agent's page said beforehand which tools a member's runs lack.
    for tool in ("manage_calendar", "list_emails", "manage_tasks"):
        assert tool in ann["lacking"], ann["lacking"]
    assert [e["conv"] for e in drive["log"]].count("brief") >= 5, "the scripted model played the brief"


def test_tasks_was_never_opened(drive):
    for who in ("ann", "annAgain"):
        o = drive["seen"][who]
        assert not o.get("tasksOpened"), who
        # *Run now* is the task's own route, and the hall's questions waiting
        # on a person are the task engine's list; the app shell polls its
        # notifications. Nothing else of Tasks — not its list, not a task.
        assert all(a.endswith("/run") for a in o["askedTasks"] if a.startswith("POST")), o["askedTasks"]
        shell = ("GET /api/tasks/waiting", "GET /api/tasks/notifications")
        assert not [a for a in o["askedTasks"] if a.startswith("GET") and a not in shell], o["askedTasks"]


def test_a_second_person_sees_the_same_catalogue_and_none_of_the_firsts(drive):
    seen = drive["seen"]
    sam, ann = seen["sam"], seen["ann"]
    assert not sam.get("crash"), sam.get("crash")
    assert sam["hall"]["search"] == ann["hallBefore"]["search"]
    assert sam["hall"]["summoned"] == "0 summoned" and sam["hall"]["hires"] == []
    assert not sam["hall"]["everyone"], "a member has no Everyone"
    assert sam["summoned"]["status"] == "On"
    assert [h["owner"] for h in seen["samHires"]] == ["sam"]


def test_an_admin_sees_both_under_everyone(drive):
    rowan = drive["seen"]["rowan"]
    assert not rowan.get("crash"), rowan.get("crash")
    assert rowan["own"]["hires"] == [] and rowan["own"]["everyone"]
    assert rowan["everyone"]["stripTitle"] == "Everyone's agents"
    assert sorted(h["owner"] for h in rowan["everyone"]["hires"]) == ["ann", "sam"]


def test_pause_stops_its_schedule_and_dismiss_removes_every_task_it_made(drive):
    seen = drive["seen"]
    again = seen["annAgain"]
    assert not again.get("crash"), again.get("crash")
    assert again["before"]["status"] == "On"
    assert again["paused"]["status"] == "Paused", again["paused"]
    assert "Switch on" in again["paused"]["buttons"] and "Run now" not in again["paused"]["buttons"]
    assert again["pausedHire"]["status"] == "paused" and again["pausedHire"]["next_run"] is None
    assert [(t["status"], t["next_run"]) for t in again["pausedTasks"]] == [("paused", None)], again["pausedTasks"]
    assert "Its tasks, runs and reports go with it" in again["question"], again["question"]
    assert "dismissed; 1 task removed" in again["note"], again["note"]
    assert again["after"]["hires"] == [] and again["after"]["summoned"] == "0 summoned"
    assert seen["annHires"] == [] and seen["annTasks"] == [], (seen["annHires"], seen["annTasks"])


def test_every_size_and_palette_fits_and_nothing_threw(drive):
    seen = drive["seen"]
    for who, keys in (("ann", ("fits",)), ("sam", ("fits", "fitsHire")), ("rowan", ("fits",)),
                      ("annAgain", ("fits",))):
        for k in keys:
            f = seen[who][k]
            assert f["windowInside"] and not f["pageScrollsSideways"] and not f["bodyScrollsSideways"], (who, k, f)
        assert seen[who]["errors"] == [], (who, seen[who]["errors"])
