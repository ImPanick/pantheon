# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B661` — every row you can click in the email library is reached from a keyboard.

The row measured 130 elements built as a `<div>`/`<span>`/`<li>`/`<td>`/`<tr>`
and given a click handler, and named the email library and the document editor
as the two with no `a11y.js` coverage. Re-measured on `2760dbe1` with the row's
own scope: **140** across 38 modules, 21 in `emailLibrary.js` and 10 in
`document.js`.

Most of those are not controls. Read one by one, `document.js`'s ten are four
modal backdrops (click outside to close; Escape is the keyboard's way), a
popover and a choice menu that only stop a click's propagation, a PDF page that
places an annotation where the pointer lands, a contact suggestion that is a
listbox `option` driven by the arrow keys from its input, and a `row` the
module-wide name match borrowed from a `<button>` two thousand lines away. The
email library's real ones were three kinds, and each is a `<button>` now:

  * **the card itself** — the way to open an email. It holds buttons of its own
    (select box, done toggle, tags, the reader's arrows), so it cannot be one
    (`P10-02`); its subject is (`.email-card-open`), and pressing it is a click
    on the card, as `.skill-card-toggle` set the shape;
  * **the done toggle** (`.email-card-done`), a `<span>`, now with
    `aria-pressed`;
  * **ten menu items** in the reader's ⋮ menu, the bulk Actions menu and the
    Remind / Translate submenus.

The row's `Verify:`, driven in Chromium against the real app with the mail
server answered by the browser (`page.route`): Tab through the email library and
reach every row you can click, and press it.
"""

from __future__ import annotations

import json
import re
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
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    try {
      localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
      localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
    } catch (_) {}
  });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const json = (body) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  const EMAILS = [
    { uid: '101', subject: 'Harbour opens at six', from_name: 'Ada', from_address: 'ada@example.test',
      date: '2026-10-26T08:00:00Z', is_read: false, is_answered: false, folder: 'INBOX', account_id: 'acct1' },
    { uid: '102', subject: 'Rye loaf recipe', from_name: 'Bob', from_address: 'bob@example.test',
      date: '2026-10-25T08:00:00Z', is_read: true, is_answered: false, folder: 'INBOX', account_id: 'acct1' },
  ];
  await page.route('**/api/email/**', (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p.endsWith('/api/email/accounts')) return route.fulfill(json({ accounts: [
      { id: 'acct1', email: 'me@example.test', name: 'Me', is_default: true, can_send: true } ] }));
    if (p.endsWith('/api/email/list')) return route.fulfill(json({ emails: EMAILS, total: EMAILS.length, sync: {} }));
    if (p.includes('/api/email/read/')) {
      const uid = decodeURIComponent(p.split('/').pop());
      const em = EMAILS.find((e) => e.uid === uid) || EMAILS[0];
      return route.fulfill(json({ ...em, body: 'The harbour opens at six.', html: '', to: 'me@example.test',
                                  cc: '', attachments: [] }));
    }
    if (p.includes('/mark-answered/') || p.includes('/mark-read/') || p.includes('/clear-answered/')) {
      out.marked = (out.marked || []).concat([p.split('/api/email/')[1].split('/')[0]]);
      return route.fulfill(json({ ok: true }));
    }
    return route.fulfill(json({}));
  });
  const creds = { username: 'mailer', password: 'mailer-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 120000 });

  await page.evaluate(() => document.getElementById('rail-email').click());
  await page.waitForSelector('#email-lib-modal .doclib-card[data-uid="101"]');

  // What a keyboard reaches: Tab from the first card's subject through the
  // list, recording every focused element inside the cards.
  await page.focus('#email-lib-modal .doclib-card[data-uid="101"] .email-card-open');
  const reached = [];
  for (let i = 0; i < 30; i++) {
    const at = await page.evaluate(() => {
      const a = document.activeElement;
      const card = a && a.closest && a.closest('.doclib-card[data-uid]');
      return card ? { uid: card.dataset.uid, tag: a.tagName, cls: a.className } : null;
    });
    if (at) reached.push(at);
    await page.keyboard.press('Tab');
  }
  out.reached = reached;
  // Every element in a card that answers a click and is not a native control.
  out.unreachable = await page.evaluate(() => {
    const bad = [];
    for (const card of document.querySelectorAll('#email-lib-modal .doclib-card[data-uid]')) {
      for (const el of card.querySelectorAll('.email-card-done, .memory-item-title')) {
        if (el.tagName !== 'BUTTON') bad.push(el.className);
      }
    }
    return bad;
  });

  // Press the done toggle from the keyboard: it is a button that says its state.
  await page.focus('#email-lib-modal .doclib-card[data-uid="101"] .email-card-done');
  out.doneBefore = await page.getAttribute('#email-lib-modal .doclib-card[data-uid="101"] .email-card-done', 'aria-pressed');
  out.doneFocused = await page.evaluate(() => document.activeElement && document.activeElement.className);
  await page.keyboard.press(' ');
  await page.waitForFunction(() => document.querySelector('#email-lib-modal .doclib-card[data-uid="101"] .email-card-done').getAttribute('aria-pressed') === 'true');
  out.doneAfter = 'true';

  // Press the subject from the keyboard: the email opens.
  await page.focus('#email-lib-modal .doclib-card[data-uid="102"] .email-card-open');
  await page.keyboard.press('Enter');
  await page.waitForSelector('#email-lib-modal .doclib-card[data-uid="102"] .email-card-reader [data-act="more"]');
  out.opened = true;

  // The reader's ⋮ menu: every item in it is a button a keyboard can press.
  await page.focus('#email-lib-modal .doclib-card[data-uid="102"] [data-act="more"]');
  await page.keyboard.press('Enter');
  await page.waitForSelector('.dropdown-item-compact');
  out.menu = await page.evaluate(() => [...document.querySelectorAll('.dropdown-item-compact')]
    .filter((n) => n.offsetParent !== null).map((n) => ({ tag: n.tagName, text: n.textContent.trim() })));
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def walked(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("email-keys") / "email.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=600, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_threw(walked):
    assert walked["errors"] == [], walked["errors"]


def test_tab_reaches_every_email_and_its_done_toggle(walked):
    reached = walked["reached"]
    for uid in ("101", "102"):
        classes = [r["cls"] for r in reached if r["uid"] == uid]
        assert any("email-card-open" in c for c in classes), (uid, reached)
        assert any("email-card-done" in c for c in classes), (uid, reached)
    assert walked["unreachable"] == [], walked["unreachable"]


def test_pressing_the_subject_opens_the_email_and_space_marks_it_done(walked):
    assert walked["opened"] is True
    assert walked["doneBefore"] == "false" and walked["doneAfter"] == "true"
    assert "mark-answered" in (walked.get("marked") or []), walked.get("marked")


def test_the_readers_menu_is_buttons(walked):
    menu = walked.get("menu")
    assert menu, "the reader's menu did not open"
    assert all(item["tag"] == "BUTTON" for item in menu), menu


# ── the census, held ────────────────────────────────────────────────────────

#: The row's scope (`Law 5`): `const|let|var <name> = document.createElement(
#: 'div'|'span'|'li'|'td'|'tr')` followed anywhere in the same module by
#: `<name>.addEventListener('click'` or `<name>.onclick =`, over `static/**/*.js`
#: outside `static/lib/**`, comments blanked. 140 on `2760dbe1`; 129 after the
#: email library's eleven. Most of what is left is not a control (backdrops,
#: delegated containers, pointer surfaces) and the rest is `sessions.js` (under
#: `a11y.js`'s `#sidebar .list-item` shim), `documentLibrary.js` and
#: `chatRenderer.js` — the row's next cut. It may fall; it may not rise.
CEILING = 129

_DECL = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\.createElement\("
                   r"\s*['\"](?:div|span|li|td|tr)['\"]\s*\)")


def census() -> list[tuple[str, str]]:
    from tests.helpers.source_text import blank
    found = []
    for path in sorted((ROOT / "static").rglob("*.js")):
        if "static/lib/" in path.as_posix():
            continue
        text = blank(path)
        for m in _DECL.finditer(text):
            name = m.group(1)
            click = re.compile(r"\b" + re.escape(name)
                               + r"\s*\.\s*(?:addEventListener\(\s*['\"]click['\"]|onclick\s*=)")
            if click.search(text, m.end()):
                found.append((path.relative_to(ROOT).as_posix(), name))
    return found


def test_no_new_clickable_div():
    sites = census()
    assert len(sites) <= CEILING, (
        f"{len(sites)} non-native elements are given a click handler (ceiling {CEILING}). "
        "Build a clickable thing as a <button type=\"button\">; if it holds other "
        "controls, give it a button that is its name (P10-02) and say why in place.")


def test_the_email_library_keeps_its_buttons():
    email = [name for f, name in census() if f == "static/js/emailLibrary.js"]
    for gone in ("doneCheck", "cancelItem", "cancelIt", "customItem", "noteItem", "it"):
        assert gone not in email, f"emailLibrary.js builds {gone} as a non-native element again"
