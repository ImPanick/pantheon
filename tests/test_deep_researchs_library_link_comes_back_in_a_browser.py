# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1274` in a real browser — Deep Research's Library link draws `← Research`.

Measured on `03f50081` (this file's script, before the fix): at 1400px and at
390px, Research → *Library → Research* opened the Library on Research with no
back button, and Research was gone — all three links (`static/js/research/
panel.js`) called `closePanel()` before `openLibrary({ tab: 'research', from:
'research-overlay' })`, and the back stack keeps an opener only while it is on
screen (`backStack._readPage`). The close was there "so the Library opens ABOVE
it on mobile"; measured with Research left open, the Library is the top window
at both widths (`document.elementFromPoint` at its middle lands in it).

`Verify:` Research → *Library → Research* → `← Research` → Research — and the
Library's ✖ lands on Research too.

Boots the app out of process exactly as
`tests/test_the_command_palette_in_a_browser.py` does (its `app_url` fixture,
imported) and skips, with the reason, where node, Playwright or Chromium is
absent.
"""

import json
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")


# `B1085`: `app_url` gives the server a database file of its own now, so
# the autouse fixture this file kept to point `DATABASE_URL` at one is gone.

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = {};
  const creds = { username: 'researcher', password: 'researcher-pass-1' };
  const widths = { desk: { viewport: { width: 1400, height: 800 } },
                   phone: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } };
  for (const [name, opts] of Object.entries(widths)) {
    const ctx = await browser.newContext(opts);
    await ctx.request.post(BASE + '/api/auth/setup', { data: creds });
    await ctx.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String((e && e.stack) || e)));
    const settle = (ms = 1300) => page.waitForTimeout(ms);
    const state = () => page.evaluate(() => {
      const open = (id) => { const m = document.getElementById(id);
        return !!m && !m.classList.contains('hidden') && getComputedStyle(m).display !== 'none'
          && !(m.querySelector('.modal-content.modal-closing')); };
      const lib = document.getElementById('doclib-modal');
      const back = lib && lib.querySelector('.modal-back-btn');
      const c = lib && lib.querySelector('.modal-content');
      let onTop = null;
      if (c) { const r = c.getBoundingClientRect();
        // The middle of the window: a first-boot toast sits over its header on a phone.
        const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        onTop = !!(el && lib.contains(el)) || (el ? (el.id || el.className || el.tagName) : 'nothing'); }
      return { research: open('research-overlay'), library: open('doclib-modal'), path: location.pathname,
        back: back && getComputedStyle(back).display !== 'none' ? back.textContent.trim() : null,
        libraryOnTop: onTop };
    });
    const visit = async (path) => {
      await page.goto(BASE + path, { waitUntil: 'load' });
      await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
      await settle(2000);
    };
    await visit('/research');
    out[name] = { start: await state() };
    await page.click('#research-overlay .research-library-link');
    await settle();
    out[name].library = await state();
    const back = await page.$('#doclib-modal .modal-back-btn');
    if (back && await back.isVisible()) { await back.click(); await settle(); }
    out[name].afterBack = await state();
    // The Library's own close comes back to Research as well (from Research,
    // reopened if the way back did not reach it, so this half is measured too).
    if (!(await state()).research) { await visit('/research'); }
    if ((await state()).library) { await page.click('#doclib-close'); await settle(); }
    await page.click('#research-overlay .research-library-link');
    await settle();
    await page.click('#doclib-close');
    await settle();
    out[name].afterClose = await state();
    out[name].errors = errors;
    await ctx.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("b1274-browser") / "drive.js"
    script.write_text(_SCRIPT)
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=480, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("width", ["desk", "phone"])
def test_research_library_back_comes_back_to_research(drive, width):
    run = drive[width]
    assert run["errors"] == []
    assert run["start"]["research"] is True and run["start"]["path"] == "/research"
    assert run["library"] == {"research": True, "library": True, "path": "/library/research",
                              "back": "← Deep Research", "libraryOnTop": True}, (
        "the Library opened from Research has no way back to it")
    assert run["afterBack"] == {"research": True, "library": False, "path": "/research",
                                "back": None, "libraryOnTop": None}
    assert run["afterClose"]["research"] is True and run["afterClose"]["library"] is False
