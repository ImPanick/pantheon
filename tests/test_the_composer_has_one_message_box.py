# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1073` — after typing, the composer still has one `#message`.

`static/js/ui.js:autoResize()` measures the composer with a hidden copy made by
`textarea.cloneNode(false)` and appended beside it — and `cloneNode` copies
every attribute: `id="message"`, `required`, `autofocus`, `aria-label`.
Measured by `showcase` after load: two `textarea#message` in
`.chat-input-top`, the second hidden. `getElementById` still found the first,
so nothing visible broke; `querySelectorAll('#message')`, a strict Playwright
locator (it broke the showcase's first GIF run) and an HTML validator did not.

Driven in the real app in headless Chromium (booted as
`tests/test_the_command_palette_in_a_browser.py` boots it), through real keys:
the clone is found by what `autoResize` keeps on the element
(`_resizeClone`), so the test does not depend on the clone's attributes to
find it. The resize itself is checked to still work — the copy is still a
faithful measure.
"""

import json
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  for (const [name, size] of [['desk', { width: 1400, height: 860 }], ['phone', { width: 390, height: 844 }]]) {
    const context = await browser.newContext({ viewport: size, serviceWorkers: 'block' });
    await context.addInitScript(() => {
      try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    });
    const page = await context.newPage();
    page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
    const creds = { username: 'composer', password: 'composer-pass-1' };
    await page.request.post(BASE + '/api/auth/setup', { data: creds });
    await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await page.waitForTimeout(400);
    // The composer's height eases (a CSS transition), so each reading waits
    // for it to settle.
    const box = async () => { await page.waitForTimeout(450); return page.evaluate(() => {
      const ta = document.getElementById('message');
      const clone = ta && ta._resizeClone;
      return {
        ids: document.querySelectorAll('#message').length,
        textareas: document.querySelectorAll('.chat-input-top textarea').length,
        clone: clone ? {
          inDom: document.contains(clone),
          id: clone.id, attrs: clone.getAttributeNames(),
          labelled: clone.hasAttribute('aria-label'), hidden: clone.getAttribute('aria-hidden'),
          tabIndex: clone.tabIndex,
        } : null,
        height: ta ? ta.getBoundingClientRect().height : null,
      };
    }); };
    await page.click('#message');
    await page.keyboard.type('hello');
    const typed = await box();
    // Enough words to wrap onto several lines at either width (Shift+Enter is
    // not used: at phone width it is not a line break in this composer).
    await page.keyboard.type(' the quick brown fox jumps over the lazy dog'.repeat(12));
    const tall = await box();
    await page.keyboard.press('Control+A'); await page.keyboard.press('Backspace');
    await page.keyboard.type('x');
    const short = await box();
    // `getElementById` and a strict locator both answer the real composer.
    const strict = await page.locator('#message').count();
    const focused = await page.evaluate(() => document.activeElement && document.activeElement.id);
    out[name] = { typed, tall, short, strict, focused };
    await context.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def typed(app_url, tmp_path_factory):  # noqa: F811
    if NODE is None:
        pytest.skip(_SKIP or "")
    script = tmp_path_factory.mktemp("composer-pw") / "composer.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True, timeout=300,
                          cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


@pytest.mark.parametrize("size", ["desk", "phone"])
def test_after_typing_exactly_one_element_is_message(typed, size):
    got = typed[size]
    # The measuring copy exists and is in the page — the case is not vacuous.
    assert got["typed"]["clone"] and got["typed"]["clone"]["inDom"], got["typed"]
    assert got["typed"]["textareas"] == 2
    assert got["typed"]["ids"] == 1, got["typed"]
    assert got["strict"] == 1
    assert got["focused"] == "message"


@pytest.mark.parametrize("size", ["desk", "phone"])
def test_the_copy_carries_no_id_requirement_focus_or_label(typed, size):
    clone = typed[size]["typed"]["clone"]
    assert clone["id"] == ""
    for attr in ("id", "name", "required", "autofocus", "aria-label"):
        assert attr not in clone["attrs"], f"the measuring copy still carries {attr}: {clone['attrs']}"
    # Out of the accessibility tree and the tab order.
    assert clone["hidden"] == "true"
    assert clone["tabIndex"] == -1


@pytest.mark.parametrize("size", ["desk", "phone"])
def test_the_composer_still_grows_and_shrinks(typed, size):
    got = typed[size]
    assert got["tall"]["height"] > got["typed"]["height"] + 20, got
    assert got["short"]["height"] < got["tall"]["height"] - 20, got
    assert got["tall"]["ids"] == 1 and got["short"]["ids"] == 1


def test_nothing_threw(typed):
    assert typed["errors"] == []
