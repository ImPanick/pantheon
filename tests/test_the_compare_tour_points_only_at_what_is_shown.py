# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1346` — the Compare tour points only at controls that are rendered.

`static/js/slashCommands.js`'s Compare tour (`_cmdTourCompare`, its own
`_showStep`) resolved each step's target with `document.querySelector(sel)` and
gave up only when the node was absent — so a `display: none` target was
highlighted at a zero rect (the top-left corner, which its own comment records
once and worked around by scoping one selector) and, on a click-to-continue
step (`#cmp-eval-btn`), waited for a click that could not come. The first-run
tour's `showStep` filtered with `checkVisibility()` (`D-2026-10-09-01` §4).

Now one rule finds what any tour step points at (`_tourTargets` /
`_tourTarget`: the first rendered match of each selector), every step runner in
the file uses it, and the Compare tour passes over a step with nothing on screen
— forward, or back past it after ←.

Driven in headless Chromium (the `playwright` node package): the real
`_cmdTourCompare` and the two helpers, cut out of the module, run against a
page with the picker's controls — one of them hidden — and then the compare
panes, whose evaluation button is hidden. The tour is walked with its own →
and ← buttons.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_binding, js_definition
from tests.helpers.source_text import blank_text
from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
SLASH = (ROOT / "static" / "js" / "slashCommands.js").read_text(encoding="utf-8")


def _cut(signature: str) -> str:
    return js_definition(SLASH, blank_text(SLASH, "js").index(signature))


def _harness() -> str:
    return (
        "window.replies = [];\n"
        "const topPortalZ = () => 10031;\n"
        "const scrollBehavior = () => 'auto';\n"
        "const slashReply = (m) => window.replies.push(String(m));\n"
        "const typewriterReply = async (m) => { window.replies.push(String(m)); };\n"
        + _cut("function _tourTargets(") + "\n"
        + _cut("function _tourTarget(") + "\n"
        # `B1537`: every tour draws and walks through the one runner now.
        + js_binding(SLASH, "_TOUR_CSS") + "\n"
        + _cut("function _clearTourCommand(") + "\n"
        + _cut("function _tourSession(") + "\n"
        + _cut("async function _cmdTourCompare(") + "\n"
        "window.startTour = () => { window.tour = _cmdTourCompare([], {}); };\n"
    )


_PAGE = """<!doctype html><html><body>
<div id="compare-model-overlay" class="modal"><div class="modal-body" style="width:420px;height:260px">
  <button class="compare-blind-toggle" type="button">Blind</button>
  <button class="compare-parallel-toggle" type="button" style="display:none">Parallel</button>
  <button class="compare-dice-toggle" type="button">Shuffle</button>
  <button class="research-start-btn" type="button">Start</button>
</div></div>
</body></html>"""

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const [PAGE, HARNESS, BACK_AT] = [fs.readFileSync(process.argv[2], 'utf8'), fs.readFileSync(process.argv[3], 'utf8'), process.argv[4]];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.setContent(PAGE);
  await page.addScriptTag({ content: HARNESS });
  await page.evaluate(() => window.startTour());
  const out = { texts: [], zeroHalos: 0, done: false, backed: false };
  for (let n = 0; n < 40; n++) {
    await page.waitForTimeout(150);
    const seen = await page.evaluate(() => {
      const t = document.getElementById('tour-tooltip');
      const halos = [...document.querySelectorAll('.tour-halo')]
        .filter((h) => h.style.width === '8px' && h.style.height === '8px').length;
      return { text: t ? t.querySelector('.tour-text')?.textContent || '' : null, halos,
               done: window.replies.includes('That’s Compare.') };
    });
    out.zeroHalos += seen.halos;
    if (seen.done) { out.done = true; break; }
    if (seen.text == null) continue;
    if (out.texts[out.texts.length - 1] !== seen.text) out.texts.push(seen.text);
    if (seen.text.startsWith('Click Start')) {
      if (out.swapped) continue;
      out.swapped = true;
      // The picker closes and the panes come up; the evaluation button is hidden.
      await page.evaluate(() => {
        document.getElementById('compare-model-overlay').remove();
        for (const [id, hidden] of [['compare-add-btn', false], ['compare-shuffle-btn', false], ['cmp-eval-btn', true]]) {
          const b = document.createElement('button');
          b.id = id; b.type = 'button'; b.textContent = id;
          if (hidden) b.style.display = 'none';
          document.body.appendChild(b);
        }
      });
      continue;
    }
    if (BACK_AT && !out.backed && seen.text.startsWith(BACK_AT)) {
      out.backed = true;
      await page.click('#tour-tooltip [data-act="back"]');
      continue;
    }
    await page.click('#tour-tooltip [data-act="next"]');
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


def _walk(tmp_path, back_at: str = "") -> dict:
    (tmp_path / "page.html").write_text(_PAGE, encoding="utf-8")
    (tmp_path / "harness.js").write_text(_harness(), encoding="utf-8")
    (tmp_path / "run.cjs").write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(tmp_path / "run.cjs"), str(tmp_path / "page.html"),
                           str(tmp_path / "harness.js"), back_at],
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_hidden_control_is_passed_over_and_the_tour_ends(tmp_path):
    """The row's `Verify:` — a `display: none` target is not highlighted, and the
    click-to-continue step on a hidden button is not waited on."""
    out = _walk(tmp_path)
    assert out["done"], f"the tour never finished: {out['texts']}"
    assert out["zeroHalos"] == 0, "a step was highlighted at a zero rect"
    said = " | ".join(out["texts"])
    assert "Parallel" not in said, "the hidden Parallel switch was pointed at"
    assert "evaluation prompts" not in said, "the hidden evaluation button was waited on"
    assert out["texts"][0].startswith("Pick the kind of test")
    assert any(t.startswith("Blind Mode") for t in out["texts"])
    assert any(t.startswith("Shuffle picks models") for t in out["texts"])
    assert any(t.startswith("Shuffle puts them") for t in out["texts"])


def test_back_passes_over_the_hidden_step_too(tmp_path):
    """← from the step after a hidden one lands on the one before it."""
    out = _walk(tmp_path, back_at="Shuffle picks models")
    assert out["backed"] and out["done"], out
    i = next(n for n, t in enumerate(out["texts"]) if t.startswith("Shuffle picks models"))
    assert out["texts"][i + 1].startswith("Blind Mode"), out["texts"]
