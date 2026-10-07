# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-12`): a hidden tab stops polling; the two 1 s scans are gone.

Measured by the perf audit on `9560d50`: 90 s with the tab **hidden** = 11
requests (5 `research/active`, 3 `tasks/notifications`, 3 mail), and two
`setInterval(…, 1000)` DOM scans (`modalManager._scanAndWire`,
`app._syncRailDynamic`) woke the main thread 7,200 times an hour, hidden or not
— and a window built between two ticks went up to a second without its `_`.

Now: the research and mail polls skip a hidden tab and look once when it comes
back (if a look is due); the tasks poll keeps going while hidden only when the
browser may show a desktop notification — the one thing it can do there (a
task whose result goes to a notification); the scans are `MutationObserver`s.

The polls are driven under node with fake timers (each module's own functions,
cut out with `js_definition`); the observers in the real app in Chromium.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

_REPO = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

# Fake time and timers, a document whose visibility a script can change, and a
# fetch that records what was asked.
_PRELUDE = r"""
let now = 1_000_000;
const timers = [];
let seq = 0;
globalThis.Date = { now: () => now };
globalThis.setTimeout = (fn, ms) => { const id = ++seq; timers.push({ id, fn, at: now + (ms || 0) }); return id; };
globalThis.setInterval = (fn, ms) => { const id = ++seq; timers.push({ id, fn, at: now + ms, every: ms }); return id; };
globalThis.clearInterval = globalThis.clearTimeout = (id) => { const i = timers.findIndex(t => t.id === id); if (i >= 0) timers.splice(i, 1); };
const docListeners = {};
globalThis.document = {
  visibilityState: 'visible',
  addEventListener(type, fn) { (docListeners[type] ||= []).push(fn); },
  removeEventListener(type, fn) { docListeners[type] = (docListeners[type] || []).filter(f => f !== fn); },
  getElementById: () => null,
  querySelector: () => null,
};
globalThis.window = { addEventListener() {}, location: { hash: '' } };
const asked = [];
globalThis.fetch = (url) => { asked.push(String(url)); return Promise.resolve({ ok: false, json: async () => ({}) }); };
const setVisible = (v) => { document.visibilityState = v ? 'visible' : 'hidden'; (docListeners.visibilitychange || []).forEach(f => f()); };
const advance = async (ms) => {
  const end = now + ms;
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    const t = timers[0];
    if (!t || t.at > end) break;
    now = t.at;
    if (t.every) t.at += t.every; else timers.shift();
    t.fn();
    await Promise.resolve();
  }
  now = end;
};
const count = (part) => asked.filter(u => u.includes(part)).length;
"""


def _run_node(tmp_path: Path, name: str, body: str) -> dict:
    script = tmp_path / f"{name}.cjs"
    script.write_text(_PRELUDE + body, encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def _cut(path: str, *signatures: str) -> str:
    src = (_REPO / path).read_text(encoding="utf-8")
    return "\n".join(js_definition(src, src.index(sig)).replace("export ", "", 1) for sig in signatures)


@pytest.fixture(scope="module")
def research(tmp_path_factory) -> dict:
    fn = _cut("static/js/research/jobs.js", "export function init(")
    body = r"""
let _apiBase = '', _activePollInterval = null, _lastActivePollAt = 0, _visibilityHooked = false;
const _ACTIVE_POLL_MS = 20000;
const _reconnectActive = () => { _lastActivePollAt = Date.now(); fetch('/api/research/active'); };
""" + fn + r"""
(async () => {
  init('');
  const out = { atLoad: count('research/active') };
  setVisible(false); await advance(90000); out.hidden90s = count('research/active') - out.atLoad;
  setVisible(true); out.onReturn = count('research/active') - out.atLoad - out.hidden90s;
  const before = count('research/active'); await advance(45000); out.visible45s = count('research/active') - before;
  setVisible(false); setVisible(true); out.quickReturn = count('research/active') - before - out.visible45s;
  console.log(JSON.stringify(out));
})();
"""
    return _run_node(tmp_path_factory.mktemp("research"), "research", body)


def test_research_does_not_poll_a_hidden_tab(research):
    assert research["atLoad"] == 1
    assert research["hidden90s"] == 0, research


def test_research_looks_once_when_the_tab_comes_back_and_polls_while_visible(research):
    assert research["onReturn"] == 1
    assert research["visible45s"] == 2
    assert research["quickReturn"] == 0, "a look that is not due yet was made"


def _tasks(tmp_path: Path, permission: str) -> dict:
    fns = _cut("static/js/tasks.js", "function _notificationPollMayRun(", "function _pollTaskNotificationsNow(",
               "function _onVisibleAgainPollTasks(", "function startNotificationPolling(",
               "function stopNotificationPolling(")
    body = (r"""
let _notifInterval = null, _lastNotifPollAt = 0;
const _NOTIF_POLL_MS = 30000;
globalThis.Notification = { permission: '__PERM__' };
const _pollTaskNotifications = () => fetch('/api/tasks/notifications');
const _offerWaitingDocumentPlans = () => {}, _offerWaitingWorkflowApprovals = () => {};
""".replace("__PERM__", permission) + fns + r"""
(async () => {
  startNotificationPolling();
  await advance(5000);
  const out = { atLoad: count('tasks/notifications') };
  setVisible(false); await advance(90000); out.hidden90s = count('tasks/notifications') - out.atLoad;
  const before = count('tasks/notifications'); setVisible(true); out.onReturn = count('tasks/notifications') - before;
  stopNotificationPolling(); const after = count('tasks/notifications');
  await advance(90000); setVisible(false); setVisible(true); out.afterStop = count('tasks/notifications') - after;
  console.log(JSON.stringify(out));
})();
""")
    return _run_node(tmp_path, "tasks", body)


def test_tasks_wait_in_a_hidden_tab_that_cannot_notify(tmp_path):
    out = _tasks(tmp_path, "default")
    assert out["atLoad"] == 1
    assert out["hidden90s"] == 0, out
    assert out["onReturn"] == 1, "coming back did not ask for what happened meanwhile"
    assert out["afterStop"] == 0, "stopNotificationPolling left a listener or a timer"


def test_tasks_keep_asking_in_a_hidden_tab_that_can_notify(tmp_path):
    """A task whose result goes to a notification raises a desktop notification
    from this poll — the reason a hidden tab still asks when it may show one."""
    out = _tasks(tmp_path, "granted")
    assert out["hidden90s"] == 3, out


@pytest.fixture(scope="module")
def mail(tmp_path_factory) -> dict:
    fns = _cut("static/js/emailInbox.js", "function _bindEvents(", "async function _refreshUnreadCount(")
    body = r"""
let _unreadCheckedAt = 0;
const API_BASE = '';
const emailApiUrl = (path) => path;
const noteMailboxSync = () => {};
const _maybeOpenFromHash = () => {}, openEmailLibrary = () => {}, markInboxAsSeen = () => {}, _composeNew = () => {};
""" + fns + r"""
(async () => {
  _bindEvents();
  await advance(15000);
  const out = { atLoad: count('unread-state') };
  setVisible(false); await advance(200000); out.hidden200s = count('unread-state') - out.atLoad;
  const before = count('unread-state'); setVisible(true); out.onReturn = count('unread-state') - before;
  const b2 = count('unread-state'); await advance(130000); out.visible130s = count('unread-state') - b2;
  setVisible(false); setVisible(true); out.quickReturn = count('unread-state') - b2 - out.visible130s;
  console.log(JSON.stringify(out));
})();
"""
    return _run_node(tmp_path_factory.mktemp("mail"), "mail", body)


def test_the_mail_dot_does_not_poll_a_hidden_tab(mail):
    assert mail["atLoad"] == 1
    assert mail["hidden200s"] == 0, mail


def test_the_mail_dot_looks_once_on_return_and_polls_while_visible(mail):
    assert mail["onReturn"] == 1
    assert mail["visible130s"] == 2
    assert mail["quickReturn"] == 0, mail


# ── the two scans, in the real app ──────────────────────────────────────────

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    window.__intervals = [];
    const real = window.setInterval;
    window.setInterval = function (fn, ms, ...rest) {
      window.__intervals.push({ ms: Number(ms) || 0, name: (fn && fn.name) || '', src: String(fn).slice(0, 60) });
      return real.call(this, fn, ms, ...rest);
    };
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const creds = { username: 'helper', password: 'helper-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(3000);
  out.secondTimers = await page.evaluate(() => window.__intervals.filter(t => t.ms > 0 && t.ms <= 1000));
  // A wired window built now: its `_` is there by the next task, not the next second.
  out.wiredAtOnce = await page.evaluate(async () => {
    const m = document.createElement('div');
    m.id = 'ge-shortcuts-modal';
    m.innerHTML = '<div class="modal-header"><span>Shortcuts</span><button class="close-btn">×</button></div>';
    document.body.appendChild(m);
    await new Promise(r => setTimeout(r, 0));
    const first = !!m.querySelector('.modal-header .modal-minimize-btn');
    // A tool that rebuilds its header drops the `_` with it.
    m.querySelector('.modal-header').innerHTML = '<span>Shortcuts</span><button class="close-btn">×</button>';
    await new Promise(r => setTimeout(r, 0));
    const rebuilt = !!m.querySelector('.modal-header .modal-minimize-btn');
    m.remove();
    return { first, rebuilt };
  });
  // The rail's doc icon follows the indicator, without a timer.
  out.rail = await page.evaluate(async () => {
    const ind = document.getElementById('doc-indicator-btn');
    const rail = document.getElementById('rail-documents');
    if (!ind || !rail) return null;
    const shown = () => rail.style.display !== 'none';
    const before = shown();
    ind.classList.add('visible');
    await new Promise(r => setTimeout(r, 0));
    const on = shown();
    ind.classList.remove('visible');
    await new Promise(r => setTimeout(r, 0));
    const off = shown();
    return { before, on, off };
  });
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def file_database(tmp_path_factory):
    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp_path_factory.mktemp("poll-db") / "app.db")
    yield
    if before is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = before


@pytest.fixture(scope="module")
def page(file_database, app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("poll-pw") / "poll.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_no_scan_runs_on_a_one_second_timer(page):
    names = {t["name"] for t in page["secondTimers"]}
    assert not names & {"_scanAndWire", "_syncRailDynamic"}, page["secondTimers"]


def test_a_window_gets_its_minimise_button_as_it_is_built(page):
    assert page["wiredAtOnce"] == {"first": True, "rebuilt": True}


def test_the_rail_doc_icon_follows_the_indicator(page):
    assert page["rail"] == {"before": False, "on": True, "off": False}, page["rail"]


def test_the_page_raised_no_error(page):
    assert page["errors"] == [], page["errors"]
