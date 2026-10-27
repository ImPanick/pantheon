# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1558` — at ≤ 768 px, an idle composer is idle while it is being typed in.

`_isForegroundChatBusy` (`static/app.js`) decides whether the composer is
talking to a running reply: if so, at phone width Enter **queues** the message,
the keyboard's `enterkeyhint` says *send*, and a line break that arrives as an
input (a phone keyboard's Enter, a multi-line paste) is turned into a queued
submit. It read `__pantheonChatBusyUntil`, which is two facts in one global —
the run's own window (`chat.js` `_setForegroundChatBusy`) and the chat-priority
window `startPantheonApp` opens to hold background work back, for 10 s at boot
and 15 s again on every focus, press or keystroke in `#message`. So with
nothing running, typing *hello* and pressing Enter at 390×844 submitted.

Now the run's window is `__pantheonChatRunUntil`, written beside the other by
`_setForegroundChatBusy` and read by `_isForegroundChatBusy` and chatStream's
`_steerChatBusy`; the priority window still holds background work back.

Driven in the real app at 390×844 (`Law 20`): typing opens the priority window
(the premise), and then Enter, a phone keyboard's bare line break and a
multi-line paste each stay in the box; with a reply running, Enter queues.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const creds = { username: 'idlecomposer', password: 'idle-pass-1' };
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    // A submit is recorded and stopped before the app's own handler: the
    // question is whether one was asked for, not what sending does.
    window.__submits = 0;
    document.addEventListener('submit', (e) => {
      window.__submits += 1; e.preventDefault(); e.stopImmediatePropagation();
    }, true);
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForFunction(() => !!document.getElementById('message'), null, { timeout: 30000 });

  const press = async (replying, keys) => {
    await page.evaluate((r) => {
      window.__submits = 0;
      window.__pantheonChatBusy = r;
      const m = document.getElementById('message');
      m.value = ''; m.dispatchEvent(new Event('input', { bubbles: true }));
    }, replying);
    await page.click('#message');
    await page.keyboard.type('hello');
    const before = await page.evaluate(() => ({
      priority: (window.__pantheonChatBusyUntil || 0) - Date.now(),
      hint: document.getElementById('message').getAttribute('enterkeyhint'),
    }));
    if (keys === 'soft-line-break') {
      await page.evaluate(() => {
        const m = document.getElementById('message');
        const ev = new InputEvent('beforeinput', { inputType: 'insertLineBreak', bubbles: true, cancelable: true });
        if (m.dispatchEvent(ev)) {
          m.setRangeText('\n', m.selectionStart, m.selectionEnd, 'end');
          m.dispatchEvent(new InputEvent('input', { inputType: 'insertLineBreak', bubbles: true }));
        }
      });
    } else if (keys === 'paste') {
      await page.evaluate(() => {
        const m = document.getElementById('message');
        m.setRangeText(' line one\nline two', m.selectionStart, m.selectionEnd, 'end');
        m.dispatchEvent(new InputEvent('input', { inputType: 'insertFromPaste', bubbles: true }));
      });
    } else {
      await page.keyboard.press(keys);
    }
    // Long enough for the 300 ms double-submit guard and any deferred submit.
    await page.waitForTimeout(400);
    return page.evaluate(() => ({
      value: document.getElementById('message').value,
      submits: window.__submits,
    })).then((r) => Object.assign(r, { before }));
  };
  out.idleEnter = await press(false, 'Enter');
  out.idleSoft = await press(false, 'soft-line-break');
  out.idlePaste = await press(false, 'paste');
  out.replyingEnter = await press(true, 'Enter');
  await page.evaluate(() => { window.__pantheonChatBusy = false; });
  console.log(JSON.stringify(out));
  await context.close();
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("idle-composer")
    script = d / "idle.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_threw(measured):
    assert measured["errors"] == []


def test_the_premise_typing_opens_the_priority_window(measured):
    """Still true, on purpose: the window holds background work back while a
    person is about to chat. It just no longer says a reply is running."""
    assert measured["idleEnter"]["before"]["priority"] > 10000, measured["idleEnter"]


def test_enter_in_an_idle_composer_breaks_the_line(measured):
    """The row's `Verify:` — 390×844, nothing running, *hello*, Enter."""
    got = measured["idleEnter"]
    assert got["value"] == "hello\n" and got["submits"] == 0, got
    assert got["before"]["hint"] == "enter", got


@pytest.mark.parametrize("case", ["idleSoft", "idlePaste"])
def test_a_line_break_that_arrives_as_input_stays_in_an_idle_box(measured, case):
    got = measured[case]
    assert got["submits"] == 0, got
    assert "\n" in got["value"], got


def test_while_a_reply_runs_enter_still_queues(measured):
    got = measured["replyingEnter"]
    assert got["submits"] == 1 and got["value"] == "hello", got
    assert got["before"]["hint"] == "send", got
