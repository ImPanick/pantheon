# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1086` — at phone width, Shift+Enter in the composer breaks the line.

Measured in Chromium at 390×844 on a fresh load, before this row: type
*hello*, press Shift+Enter — the value stayed *hello* and the caret went to
`<body>`; at 1400×860 the same keys inserted a newline and kept focus. Traced:

  * `app.js` turns a line-break INPUT into "queue this message" when the
    composer is ≤768 px wide and the chat counts as busy — a phone keyboard's
    Enter arrives as `beforeinput` `insertLineBreak` with no Enter keydown
    worth reading, so the input is the only place to catch it;
  * a hardware keyboard's Shift+Enter arrives as the same `insertLineBreak`,
    and the input listener could not see the Shift the keydown had carried —
    the keydown path (`_shouldQueueFromMobileEnter`) exempts Shift, the input
    path did not; so the newline was swallowed and the form submitted, which
    took the caret;
  * "busy" was true with nothing streaming, because `_isForegroundChatBusy`
    also reads the chat-priority window (`__pantheonChatBusyUntil`) that
    `startPantheonApp` opens for ten seconds at boot and that focusing or
    typing in the composer re-opens for fifteen — which is why the row saw it
    on the welcome screen and in a chat alike. (Filed separately: that window
    is there to hold background work back, not to say a reply is running.)

Driven in the real app (`Law 20`): Shift+Enter at 390×844 in the boot window
and while a reply is running, and the two queue paths that must keep working —
a plain Enter, and a phone keyboard's bare line break — still queue.
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
  const creds = { username: 'shift', password: 'shift-pass-1' };
  const boot = async (w, h) => {
    const context = await browser.newContext({ viewport: { width: w, height: h } });
    await context.addInitScript(() => {
      try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
      // A submit is recorded and stopped here, before the app's own handler:
      // the question is whether one was asked for, not what sending does.
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
    await page.waitForTimeout(600);
    return { context, page };
  };
  // `state`: how the chat counts as busy for this case.
  const press = async (page, state, keys) => {
    await page.evaluate((s) => {
      window.__submits = 0;
      window.__pantheonChatBusy = s === 'replying';
      window.__pantheonChatBusyUntil = s === 'boot-window' ? Date.now() + 60000 : 0;
      const m = document.getElementById('message');
      m.value = ''; m.dispatchEvent(new Event('input', { bubbles: true }));
    }, state);
    await page.click('#message');
    await page.keyboard.type('hello');
    const before = await page.evaluate(() => ({ until: (window.__pantheonChatBusyUntil || 0) - Date.now(), busy: !!window.__pantheonChatBusy,
      btn: [...document.querySelectorAll('.send-btn')].map(b => [b.dataset.mode, b.className, b.title]) }));
    if (keys === 'soft-line-break') {
      // A phone keyboard's Enter: the input event, with no Enter keydown.
      await page.evaluate(() => {
        const m = document.getElementById('message');
        const ev = new InputEvent('beforeinput', { inputType: 'insertLineBreak', bubbles: true, cancelable: true });
        if (m.dispatchEvent(ev)) {
          m.setRangeText('\n', m.selectionStart, m.selectionEnd, 'end');
          m.dispatchEvent(new InputEvent('input', { inputType: 'insertLineBreak', bubbles: true }));
        }
      });
    } else {
      await page.keyboard.press(keys);
    }
    await page.waitForTimeout(300);
    return page.evaluate(() => ({
      value: document.getElementById('message').value,
      focused: document.activeElement === document.getElementById('message'),
      active: document.activeElement ? (document.activeElement.id || document.activeElement.tagName) : null,
      submits: window.__submits,
    })).then((r) => Object.assign(r, { before }));
  };
  {
    const { context, page } = await boot(390, 844);
    // The premise the row was measured on: a fresh load counts as busy.
    out.freshLoadBusy = await page.evaluate(() => Date.now() < (window.__pantheonChatBusyUntil || 0));
    out.phone = {
      shiftBoot: await press(page, 'boot-window', 'Shift+Enter'),
      shiftReplying: await press(page, 'replying', 'Shift+Enter'),
      enterReplying: await press(page, 'replying', 'Enter'),
      softReplying: await press(page, 'replying', 'soft-line-break'),
      // Nothing running, the window closed — and then the person clicks and
      // types, as a person does.
      typed: await press(page, 'idle', 'Shift+Enter'),
    };
    await context.close();
  }
  {
    const { context, page } = await boot(1400, 860);
    out.desk = { shiftBoot: await press(page, 'boot-window', 'Shift+Enter') };
    await context.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("shift-enter")
    script = d / "shift.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_threw(measured):
    assert measured["errors"] == []


def test_the_premise_a_fresh_load_counts_as_busy(measured):
    assert measured["freshLoadBusy"] is True


@pytest.mark.parametrize("case", ["shiftBoot", "shiftReplying"])
def test_shift_enter_breaks_the_line_and_keeps_the_caret_at_390(measured, case):
    """The row's `Verify:` — in the boot window it was measured in, and while a
    reply is running, where the same swallow happened."""
    got = measured["phone"][case]
    assert got["value"] == "hello\n", got
    assert got["focused"], got
    assert got["submits"] == 0, got


def test_the_desk_was_never_affected(measured):
    got = measured["desk"]["shiftBoot"]
    assert got["value"] == "hello\n" and got["focused"] and got["submits"] == 0, got


def test_a_plain_enter_while_replying_still_queues_the_message(measured):
    got = measured["phone"]["enterReplying"]
    assert got["submits"] == 1 and got["value"] == "hello", got


def test_a_phone_keyboards_line_break_while_replying_still_queues_it(measured):
    """The case the input listener exists for: no Enter keydown, just the
    line break. Still queued, with no stray newline left behind."""
    got = measured["phone"]["softReplying"]
    assert got["submits"] == 1 and got["value"] == "hello", got


def test_the_premise_typing_holds_the_window_open(measured):
    """Why the row saw it in a chat as well as on the welcome screen: focusing,
    pressing and typing in the composer each re-open the chat-priority window
    for 15 s (`app.js`, `_bumpChatPriority`), so at ≤768 px the composer counts
    as busy whenever someone is typing in it — and Shift+Enter, with nothing
    running at all, was swallowed the same way. It is a line break now."""
    got = measured["phone"]["typed"]
    assert got["before"]["busy"] is False and got["before"]["until"] > 10000, got["before"]
    assert got["value"] == "hello\n" and got["focused"] and got["submits"] == 0, got
