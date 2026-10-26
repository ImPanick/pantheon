# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1213` — the sidebar's Email title can be reached and pressed from the
keyboard.

It was a `<span class="section-title">` with a pointer cursor and the title
*Open email inbox* (`DOCS-U-17`): a mouse could press it, Tab walked past it,
and the first control the keyboard reached in the section was *Compose*. The
row's premise that its click collapses the section is out of date: the Email
section does not collapse (`section-management.js` skips it) — the header's
click opens the inbox (`emailInbox.js` `_bindEvents`), which is what the title
says. So the title is a `<button type="button" class="section-title">`, with
the global `button` rules taken off in `static/style.css`.

Driven in headless Chromium (the `playwright` node package): the real
`static/style.css`, the Email section cut out of `static/index.html`, and the
real `_bindEvents` cut out of `emailInbox.js` with its inbox opener and
compose counted. Tab reaches the title before *Compose*; Enter and Space open
the inbox; the button draws as the other section titles do.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_function
from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
STYLE = ROOT / "static" / "style.css"
INBOX = ROOT / "static" / "js" / "emailInbox.js"


def _section() -> str:
    html = INDEX.read_text(encoding="utf-8")
    start = html.index('<div class="section" id="email-section">')
    end = html.index('<div class="section" id="tools-section">', start)
    return html[start:end]


def _harness() -> str:
    body = js_function(INBOX.read_text(encoding="utf-8"), "function _bindEvents")
    return (
        "window.opened = 0; window.composed = 0;\n"
        "const openEmailLibrary = () => { window.opened += 1; };\n"
        "const markInboxAsSeen = () => {};\n"
        "const _composeNew = () => { window.composed += 1; };\n"
        "const _refreshUnreadCount = () => {};\n"
        "const _maybeOpenFromHash = () => {};\n"
        "let _unreadCheckedAt = 0;\n"
        + body + "\n_bindEvents();\n"
    )


_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const [CSS, SECTION, HARNESS] = process.argv.slice(2).map((p) => fs.readFileSync(p, 'utf8'));
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.setContent('<!doctype html><html><head><style>' + CSS + '</style></head><body>'
    + '<nav id="sidebar"><div class="sidebar-inner">' + SECTION + '</div></nav></body></html>');
  await page.addScriptTag({ content: HARNESS });
  const out = { order: [] };
  for (let i = 0; i < 2; i++) {
    await page.keyboard.press('Tab');
    out.order.push(await page.evaluate(() => document.activeElement && document.activeElement.id));
  }
  // Back to the title, then press it the two ways a button is pressed.
  await page.focus('#email-section-title').catch(() => {});
  out.focused = await page.evaluate(() => document.activeElement && document.activeElement.id);
  await page.keyboard.press('Enter');
  await page.keyboard.press('Space');
  out.opened = await page.evaluate(() => window.opened);
  out.composed = await page.evaluate(() => window.composed);
  out.look = await page.evaluate(() => {
    const t = document.getElementById('email-section-title');
    const s = getComputedStyle(t);
    const sib = document.createElement('span');
    sib.className = 'section-title';
    t.parentNode.appendChild(sib);
    const ref = getComputedStyle(sib);
    const look = { tag: t.tagName, type: t.getAttribute('type'), bg: s.backgroundColor,
                   border: s.borderTopWidth, padding: s.paddingLeft, height: t.getBoundingClientRect().height,
                   font: [s.fontSize, s.fontWeight], spanFont: [ref.fontSize, ref.fontWeight],
                   label: t.textContent.trim(), title: t.getAttribute('title') };
    sib.remove();
    return look;
  });
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(tmp_path_factory):
    d = tmp_path_factory.mktemp("b1213")
    files = {"css": STYLE.read_text(encoding="utf-8"), "section": _section(), "harness": _harness()}
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")
    (d / "run.cjs").write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(d / "run.cjs"), str(d / "css"), str(d / "section"), str(d / "harness")],
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_tab_reaches_the_email_title_before_compose(drive):
    assert drive["order"] == ["email-section-title", "email-compose-btn"], drive["order"]


def test_enter_and_space_open_the_inbox(drive):
    """The row's `Fix:` asked what it does: it opens the inbox, as its title says."""
    assert drive["focused"] == "email-section-title"
    assert drive["opened"] == 2, drive
    assert drive["composed"] == 0, "the keyboard landed on Compose instead"


def test_the_button_draws_as_a_section_title(drive):
    look = drive["look"]
    assert look["tag"] == "BUTTON" and look["type"] == "button"
    assert look["bg"] in ("rgba(0, 0, 0, 0)", "transparent"), look
    assert look["border"] == "0px" and look["padding"] == "0px", look
    assert look["height"] < 32, "the global button height is still on it"
    assert look["font"] == look["spanFont"], "it no longer reads like the other section titles"
    assert look["label"] == "Email" and look["title"] == "Open email inbox"
