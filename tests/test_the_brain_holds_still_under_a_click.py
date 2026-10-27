# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1115` — the Brain holds still: nothing inside it can be scrolled sideways.

*"The Brain picture moves 4 px between captures, so a release-day capture
rewrites `brain-*.png` with nothing changed."* Measured 2026-10-27 in Chromium
on the showcase world (`scripts/showcase`, the Brain scene driven as
`scenes.scene_brain` drives it): the window itself settled at the same place
every time; what moved was its body. `.memory-tabs` bleeds 4px into each side
(`margin: -4px -4px 0`), and in the Brain it sits straight in
`.memory-modal-body`, which has no padding to bleed into and clips sideways —
so the body was 542px of content in a 538px box: a 4px scroll range nobody
could see. Playwright's click on the sort button, landing while the window was
still scaling in, scrolled it by that range in 3 of 8 runs, and every capture
that did was the whole Brain 4px to the left (2.7% of the picture's pixels;
the pipeline keeps a picture only under 0.4%). A person's focus or a
`scrollIntoView` can do the same.

Driven, not read (`Law 20`): the Brain's own markup from `static/index.html`
laid out by the real `static/style.css` in headless Chromium, then asked to
scroll every way a click, a focus or a script can.
"""
from __future__ import annotations

import json
import re
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, ROOT  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

INDEX = ROOT / "static" / "index.html"
STYLE = ROOT / "static" / "style.css"


def _brain_markup() -> str:
    """`#memory-modal` as `index.html` ships it, shown."""
    html = re.sub(r"<!--.*?-->", "", INDEX.read_text(encoding="utf-8"), flags=re.S)
    start = html.index('<div id="memory-modal"')
    depth, at = 0, start
    for tag in re.finditer(r"<(/?)div\b", html[start:]):
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            at = start + tag.end()
            break
    end = html.index(">", at) + 1
    fragment = html[start:end]
    assert fragment.count("<div") == fragment.count("</div"), "the Brain's markup did not close"
    return fragment.replace('class="modal hidden"', 'class="modal"', 1)


_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [page_path] = process.argv.slice(2);
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto('file://' + page_path);
  const out = await page.evaluate(() => {
    const body = document.querySelector('#memory-modal .memory-modal-body');
    const tabs = body.querySelector(':scope > .memory-tabs');
    const first = tabs.querySelector('.memory-tab');
    const last = [...tabs.querySelectorAll('button')].pop();
    const at = () => ({ scrollLeft: body.scrollLeft,
                        firstTab: Math.round(first.getBoundingClientRect().left - body.getBoundingClientRect().left),
                        card: Math.round(body.querySelector('.admin-card').getBoundingClientRect().left
                                         - body.getBoundingClientRect().left) });
    const before = at();
    const range = body.scrollWidth - body.clientWidth;
    last.scrollIntoView({ block: 'nearest', inline: 'end' });
    const afterScrollIntoView = at();
    last.focus();
    const afterFocus = at();
    body.scrollLeft = 50;
    const afterScript = at();
    return { range, before, afterScrollIntoView, afterFocus, afterScript };
  });
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def brain(tmp_path_factory):
    work = tmp_path_factory.mktemp("b1115")
    page = work / "brain.html"
    page.write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<link rel='stylesheet' href='{STYLE.as_uri()}'>"
        "<style>#memory-modal { display: flex; position: fixed; inset: 0;"
        " align-items: center; justify-content: center; }</style>"
        f"</head><body>{_brain_markup()}</body></html>", encoding="utf-8")
    script = work / "brain.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), str(page)], capture_output=True, text=True,
                          timeout=120, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_brain_body_has_nothing_to_scroll_sideways(brain):
    """The 4px range was the whole defect: with none, there is nothing for a
    click, a focus or a script to move."""
    assert brain["range"] == 0, brain


def test_nothing_a_click_focus_or_script_does_moves_the_brain(brain):
    """The row's `Verify:` at its root — what moved between two captures was
    this scroll, and every way to cause it leaves the Brain where it was."""
    still = {"scrollLeft": 0, "firstTab": brain["before"]["firstTab"],
             "card": brain["before"]["card"]}
    assert brain["before"]["scrollLeft"] == 0
    for step in ("afterScrollIntoView", "afterFocus", "afterScript"):
        assert brain[step] == still, (step, brain)


def test_the_tabs_sit_where_they_always_sat(brain):
    """Taking the bleed away moved nothing a person sees: the body clipped
    it, so the first tab starts at the body's left edge, as it did."""
    assert brain["before"]["firstTab"] == 0, brain
