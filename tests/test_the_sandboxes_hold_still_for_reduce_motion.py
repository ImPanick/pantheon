# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B663` — the two variant sandboxes hold still when the person asked for less motion.

`static/wave-variants.html` advanced its waves on a 170ms `setInterval` and
`static/whirlpool-variants.html` drew its four spirals on
`requestAnimationFrame`. Both are served (`/sandbox/<name>`, `B370`) and
neither asked whether the person wanted motion; the app's guard is CSS and a
script painting frames is the one thing CSS cannot stop, so
`tests/test_reduced_motion_guard.py` carried `wave-variants.html` as its one
excused page.

**Measured before the fix** (this file, against the tree at `9297d85a`): with
`reducedMotion: 'reduce'`, the wave preview changed on every sample and every
spiral canvas changed between two reads 600ms apart — the same as with no
preference at all.

**Now** each page imports `prefersReducedMotion` from `static/js/motion.js`
(the one copy of the query; `test_one_module_owns_the_media_query_string`) and
asks it on every tick, so:

  * with Reduce Motion on, nothing a person can see changes between samples;
  * with it off, both still animate — the page exists to compare moving shapes;
  * turning it on mid-run stops them without a reload.

Driven, not read (`Law 20`): the real pages in headless Chromium, with the
browser's own `prefers-reduced-motion` emulation. The two pages and
`motion.js` are served from disk through Playwright's router at the URLs the
app gives them, which is what checks the relative import resolves from
`/sandbox/<name>`; the CSP half (`B211`'s hash) is
`tests/test_a_developer_sandbox_is_not_a_public_page.py`'s.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const ROOT = process.argv[2];
const ORIGIN = 'http://sandbox.test';
const FILES = {
  '/sandbox/wave-variants': ['static/wave-variants.html', 'text/html'],
  '/sandbox/whirlpool-variants': ['static/whirlpool-variants.html', 'text/html'],
  '/static/js/motion.js': ['static/js/motion.js', 'text/javascript'],
};
// What a person sees, read the same way for both pages: every wave preview's
// markup, and every spiral canvas's pixels.
const SEEN = () => JSON.stringify({
  waves: [...document.querySelectorAll('.ascii')].map((n) => n.innerHTML),
  spirals: [...document.querySelectorAll('canvas')].map((c) => c.toDataURL()),
});
async function samples(page, n, gap) {
  const out = [];
  for (let i = 0; i < n; i++) { out.push(await page.evaluate(SEEN)); await page.waitForTimeout(gap); }
  return out;
}
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = {};
  for (const name of ['wave-variants', 'whirlpool-variants']) {
    for (const motion of ['reduce', 'no-preference']) {
      const context = await browser.newContext({ reducedMotion: motion, viewport: { width: 1200, height: 900 } });
      await context.route(ORIGIN + '/**', (route) => {
        const hit = FILES[new URL(route.request().url()).pathname];
        if (!hit) return route.fulfill({ status: 404, body: 'not here' });
        return route.fulfill({ status: 200, contentType: hit[1],
          body: fs.readFileSync(path.join(ROOT, hit[0]), 'utf-8') });
      });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(String(e)));
      page.on('requestfailed', (r) => errors.push('failed ' + r.url()));
      await page.goto(ORIGIN + '/sandbox/' + name, { waitUntil: 'load' });
      await page.waitForTimeout(500);
      const got = await samples(page, 4, 300);
      const row = { errors, distinct: new Set(got).size, painted: JSON.parse(got[0]) };
      if (motion === 'no-preference') {
        // The preference turned on mid-run, as a person does in system settings.
        await page.emulateMedia({ reducedMotion: 'reduce' });
        await page.waitForTimeout(400);
        row.after = new Set(await samples(page, 4, 300)).size;
      }
      out[name + ':' + motion] = row;
      await context.close();
    }
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    d = tmp_path_factory.mktemp("sandbox-motion")
    script = d / "motion.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), str(ROOT)], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("page", ["wave-variants", "whirlpool-variants"])
def test_with_reduce_motion_on_nothing_moves(measured, page):
    got = measured[page + ":reduce"]
    assert got["errors"] == [], got["errors"]
    # Something was drawn: a still page is not a blank one.
    painted = got["painted"]
    assert painted["waves"] or painted["spirals"], painted
    assert all(w for w in painted["waves"]) and all(painted["spirals"]), painted
    assert got["distinct"] == 1, f"{page} changed {got['distinct']} times in 4 samples with Reduce Motion on"


@pytest.mark.parametrize("page", ["wave-variants", "whirlpool-variants"])
def test_without_it_they_still_move_and_turning_it_on_stops_them(measured, page):
    got = measured[page + ":no-preference"]
    assert got["errors"] == [], got["errors"]
    assert got["distinct"] > 1, f"{page} stopped animating for everyone — the page exists to compare motion"
    assert got["after"] == 1, f"{page} kept moving after Reduce Motion was turned on"
