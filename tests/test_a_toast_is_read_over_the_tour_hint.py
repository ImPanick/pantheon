# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1056` — an error toast is fully readable while the first-run tour hint is up.

Measured on the merged tree (`verify-a`, `probe_toast.py`) at 1400×860: `#toast`
at (1024, 16)–(1384, 94) with z-index 9999, and the *"Pro tip: drag any
window's title bar…"* `.tour-hint` at (1134, 65)–(1374, 309) with z-index
**10031** — `tourHints.js` sets it inline from `toolWindowZOrder.js:topPortalZ()`,
`max(open windows, 10030) + 1`. The loop refusal's last line, *"Remove one of
those links to save it."*, was covered from x=1134.

Driven in headless Chromium (the `playwright` node package): the real
`static/style.css`, the real `#toast` element from `static/index.html` shown the
way `ui.js:showError` shows it (`show error`), and a hint with `tourHints.js`'s
class, at the measured place, with the z `topPortalZ()` gives it — and with a
higher one, since that value climbs as windows are raised. Every point of the
toast must be the toast's.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
ZORDER = ROOT / "static" / "js" / "toolWindowZOrder.js"

_SENTENCE = ("The chain loops back on itself: if “Cleanup” works it runs “Backup”, and if “Backup” fails it "
             "runs “Cleanup” again. Remove one of those links to save it.")

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const [CSS, TOAST, SENTENCE, ZS] = process.argv.slice(2).map((p, i) => i < 2 ? fs.readFileSync(p, 'utf8') : p);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1400, height: 860 } });
  await page.setContent('<!doctype html><html><head><style>' + CSS + '</style></head><body>' + TOAST + '</body></html>');
  const out = {};
  for (const z of JSON.parse(ZS)) {
    out[z] = await page.evaluate(([sentence, z]) => {
      document.querySelectorAll('.tour-hint').forEach((n) => n.remove());
      const t = document.getElementById('toast');
      t.textContent = sentence;
      t.classList.add('show', 'error');
      t.style.transition = 'none';
      // The toast takes no pointer (`pointer-events: none`), so hit-testing
      // skips it whatever is on top. Switched on here only to ask the browser
      // what is painted on top at each point; stacking does not change.
      t.style.pointerEvents = 'auto';
      const hint = document.createElement('div');
      hint.className = 'tour-hint tour-hint-in';
      hint.innerHTML = '<div class="tour-hint-text"><b>Pro tip:</b> drag any window’s title bar to a screen edge to snap it.</div>'
        + '<button class="tour-hint-dismiss" type="button">Got it</button>';
      hint.style.zIndex = String(z);
      hint.style.left = '1134px';
      hint.style.top = '65px';
      hint.style.transition = 'none';
      document.body.appendChild(hint);
      const r = t.getBoundingClientRect(), h = hint.getBoundingClientRect();
      let covered = 0, total = 0;
      for (let x = r.left + 2; x < r.right - 1; x += 8) {
        for (let y = r.top + 2; y < r.bottom - 1; y += 4) {
          total++;
          const at = document.elementFromPoint(x, y);
          if (!at || !(at === t || t.contains(at))) covered++;
        }
      }
      const overlap = !(h.left >= r.right || h.right <= r.left || h.top >= r.bottom || h.bottom <= r.top);
      return { covered, total, overlap, toastZ: getComputedStyle(t).zIndex };
    }, [SENTENCE, z]);
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


def _portal_floor() -> int:
    """`topPortalZ()` with no window raised: `DOCK_OVERLAY_FLOOR + 1`, read from
    the module rather than copied."""
    m = re.search(r"const DOCK_OVERLAY_FLOOR = (\d+);", ZORDER.read_text(encoding="utf-8"))
    assert m, "toolWindowZOrder.js's floor moved — re-read this test"
    return int(m.group(1)) + 1


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    d = tmp_path_factory.mktemp("toast-hint")
    html = INDEX.read_text(encoding="utf-8")
    toast = re.search(r'<div id="toast"[^>]*></div>', html)
    assert toast, "the toast moved out of index.html — re-read this test"
    (d / "style.css").write_text((ROOT / "static" / "style.css").read_text(encoding="utf-8"), encoding="utf-8")
    (d / "toast.html").write_text(toast.group(0), encoding="utf-8")
    (d / "run.cjs").write_text(_SCRIPT, encoding="utf-8")
    zs = [_portal_floor(), 25000]
    proc = subprocess.run([NODE, str(d / "run.cjs"), str(d / "style.css"), str(d / "toast.html"), _SENTENCE,
                           json.dumps(zs)], capture_output=True, text=True, timeout=120, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-3000:]
    return {int(k): v for k, v in json.loads(proc.stdout.strip().splitlines()[-1]).items()}, zs


def test_the_hint_lies_where_it_was_measured_over_the_toast(measured):
    """The premise (`Law 3`): placed as measured, the two overlap."""
    out, zs = measured
    assert zs[0] == 10031, "topPortalZ() with nothing raised was 10031 when this was measured"
    assert all(out[z]["overlap"] for z in zs)


def test_every_point_of_the_toast_is_the_toasts_while_the_hint_is_up(measured):
    out, zs = measured
    for z in zs:
        assert out[z]["covered"] == 0, (z, out[z])
        assert out[z]["total"] > 100, out[z]
