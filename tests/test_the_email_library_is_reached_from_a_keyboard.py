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
#: 'div'|'span'|'li'|'td'|'tr')` followed by `<name>.addEventListener('click'`
#: or `<name>.onclick =`, over `static/**/*.js` outside `static/lib/**`,
#: comments blanked. 140 on `2760dbe1`; 129 after the email library's eleven.
#:
#: `B1576` sharpened the scan and read every site:
#:
#:   * **the click is looked for in the declaration's own block**, not the whole
#:     module. The module-wide name match counted 18 sites whose click belongs
#:     to another variable of the same name — a `row` two thousand lines on, a
#:     `card` a `querySelectorAll` callback names. 129 -> 111 is the scan
#:     improving, not the product (`Law 13`'s note on a widened checker);
#:   * a site the keyboard reaches **in place** is not counted: focusable and
#:     pressed by `a11y.js`'s delegated activation (`data-a11y-activatable`),
#:     or focusable with its own `keydown`;
#:   * a site in `NOT_COUNTED` is not counted, with why — a backdrop, a
#:     container that only routes or stops a click, a pointer surface, or a
#:     control the keyboard reaches another way.
#:
#: What was left was one real control still a mouse's alone: Compare's model
#: picker (`compare/selector.js`), whose options dropped under a text input with
#: no arrow-key way into them. `B1589` made it a combobox (arrows, Enter,
#: `aria-activedescendant`; `tests/test_compares_model_picker_is_worked_from_a_keyboard.py`),
#: so it is in `NOT_COUNTED` with the other two pickers and the ceiling is 0.
#: It may not rise.
CEILING = 0

_DECL = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\.createElement\("
                   r"\s*['\"](?:div|span|li|td|tr)['\"]\s*\)")

_BACKDROP = "a backdrop: a click outside the window closes it, and Escape is the keyboard's way"
_ROUTES = "a container: it routes a click to the buttons inside it, or stops one"

#: `(module, name)` -> why the keyboard needs nothing from this element.
NOT_COUNTED = {
    ("static/js/assistant.js", "modal"): _BACKDROP,
    ("static/js/calendar.js", "overlay"): _BACKDROP + "; its choices are buttons",
    ("static/js/chatRenderer.js", "overlay"): _BACKDROP,
    ("static/js/compare/scoreboard.js", "overlay"): _BACKDROP,
    ("static/js/cookbookRunning.js", "overlay"): _BACKDROP,
    ("static/js/cookbookServe.js", "ov"): _BACKDROP + "; its choices are buttons",
    ("static/js/document.js", "overlay"): _BACKDROP,
    ("static/js/documentLibrary.js", "modal"): _BACKDROP,
    ("static/js/editor/fx/adj-popup.js", "backdrop"): _BACKDROP,
    ("static/js/editor/wire-import.js", "overlay"): _BACKDROP,
    ("static/js/emailLibrary.js", "modal"): _BACKDROP,
    ("static/js/emailLibrary.js", "overlay"): _BACKDROP,
    ("static/js/gallery.js", "modal"): _BACKDROP,
    ("static/js/galleryEditor.js", "overlay"): _BACKDROP,
    ("static/js/notes.js", "backdrop"): _BACKDROP,
    ("static/js/research/panel.js", "overlay"): _BACKDROP,
    ("static/js/sidebar-layout.js", "mobileBackdrop"): _BACKDROP + " (the phone's sidebar)",
    ("static/js/tasks.js", "modal"): _BACKDROP,
    ("static/js/chat.js", "nav"): _ROUTES + " (a reply's variant arrows)",
    ("static/js/chatRenderer.js", "nav"): _ROUTES + " (a reply's variant arrows)",
    ("static/js/compare/index.js", "grid"): _ROUTES + " (each pane's vote buttons)",
    ("static/js/editor/fx/adj-popup.js", "menu"): _ROUTES + " (its items are buttons)",
    ("static/js/document.js", "popover"): _ROUTES,
    ("static/js/document.js", "menu"): _ROUTES + " (the reply choices are buttons)",
    ("static/js/emailLibrary.js", "tagWrap"): _ROUTES + " (each tag is a button)",
    ("static/js/emailLibrary.js", "navArrows"): _ROUTES + " (the arrows are buttons)",
    ("static/js/emailLibrary.js", "reader"): _ROUTES,
    ("static/js/emailLibrary.js", "menu"): _ROUTES + " (the reply choices are buttons)",
    ("static/js/emailLibrary.js", "customRow"): _ROUTES + " (it holds an input and its Go button)",
    ("static/js/sessions.js", "sub"): _ROUTES + " (the folder submenu; its items are buttons)",
    ("static/js/sessions.js", "dropdown"): _ROUTES + " (a chat's menu; its items are buttons)",
    ("static/js/slashCommands.js", "tooltip"): _ROUTES + " (the tour's Back, Skip and Next buttons)",
    ("static/js/document.js", "pageWrap"):
        "a PDF page: in drop mode a click places an annotation where the pointer lands",
    ("static/js/document.js", "item"):
        "a contact suggestion: a listbox option the arrow keys reach from the address input",
    ("static/js/search-chat.js", "row"):
        "a command-palette option: the arrow keys reach it from the search box (aria-activedescendant)",
    ("static/js/modelPicker.js", "row"):
        "a model in the picker: the arrow keys and Enter reach it from the picker's search box",
    ("static/js/compare/selector.js", "item"):
        "a model in Compare's picker: the arrow keys and Enter reach it from the picker's "
        "search box (`B1589`, aria-activedescendant)",
    ("static/js/sessions.js", "div"):
        "a chat in the sidebar list: a listbox option the arrow keys move between; "
        "one row is the list's tab stop (`B1576`, roving tabindex)",
    ("static/js/sessions.js", "icon"):
        "a chat's favourite bookmark: a mouse shortcut for its menu's Unfavorite (and Ctrl+Alt+F)",
    ("static/js/documentLibrary.js", "card"):
        "a Library card or row: it holds its own controls, and its title is its button "
        "(`.doclib-card-open`, `B1576`), whose press is a click on it",
    ("static/js/emailLibrary.js", "card"):
        "an email card: its subject is its button (`.email-card-open`, `B661`)",
    ("static/js/skills.js", "card"):
        "a skill card: its name is its button (`.skill-card-toggle`, `P10-06`)",
    ("static/js/modalManager.js", "chip"):
        _ROUTES + " (a minimised window: its Restore and Close are buttons, `P23-01`)",
    ("static/js/notes.js", "addRow"):
        _ROUTES + " (a wider target for its + Add button, which is the control)",
    ("static/js/memory.js", "item"):
        "a memory in select mode: its checkbox is the control; the row is a wider target for it",
}


def _reached_in_place(body: str, name: str) -> bool:
    n = re.escape(name)
    if re.search(n + r"\s*\.\s*dataset\.a11yActivatable\s*=|"
                 + n + r"\s*\.\s*setAttribute\(\s*['\"]data-a11y-activatable", body):
        return True
    focus = re.search(n + r"\s*\.\s*tabIndex\s*=\s*0\b|"
                      + n + r"\s*\.\s*setAttribute\(\s*['\"]tabindex['\"]\s*,\s*['\"]0['\"]", body)
    keys = re.search(n + r"\s*\.\s*addEventListener\(\s*['\"]keydown['\"]", body)
    return bool(focus and keys)


def sites() -> list[tuple[str, str, bool]]:
    """`(module, name, reached in place)` for every site in the scope."""
    from tests.helpers.js_source import js_block_end, js_spans
    from tests.helpers.source_text import blank
    found = []
    for path in sorted((ROOT / "static").rglob("*.js")):
        if "static/lib/" in path.as_posix():
            continue
        text = blank(path)
        spans = js_spans(text)
        for m in _DECL.finditer(text):
            name = m.group(1)
            # Where the block the declaration sits in closes — the shared
            # walk, which steps over strings and templates (`B876`).
            end = js_block_end(text, m.end(), spans)
            click = re.compile(r"\b" + re.escape(name)
                               + r"\s*\.\s*(?:addEventListener\(\s*['\"]click['\"]|onclick\s*=)")
            if click.search(text, m.end(), end):
                found.append((path.relative_to(ROOT).as_posix(), name,
                              _reached_in_place(text[m.end():end], name)))
    return found


def census() -> list[tuple[str, str]]:
    """The sites still a mouse's alone."""
    return [(f, n) for f, n, kb in sites() if not kb and (f, n) not in NOT_COUNTED]


def test_no_new_clickable_div():
    left = census()
    assert len(left) <= CEILING, (
        f"{len(left)} non-native elements are given a click handler (ceiling {CEILING}): "
        f"{left}. Build a clickable thing as a <button type=\"button\">; if it holds other "
        "controls, give it a button that is its name (P10-02), or make it focusable and "
        "mark it data-a11y-activatable, and say why in place.")


def test_every_entry_in_the_register_is_a_site_that_exists():
    """A register entry for a site that is gone is a hole the next site of the
    same name walks through unread."""
    present = {(f, n) for f, n, _kb in sites()}
    assert set(NOT_COUNTED) <= present, sorted(set(NOT_COUNTED) - present)


def test_the_chat_list_and_the_library_and_the_transcript_are_off_the_census():
    """`B1576`'s cut, held: the sidebar's menus, the Library's menus and cards,
    and the transcript's attachments, images, memory and skill rows and timings."""
    left = {f for f, _n in census()}
    for module in ("static/js/sessions.js", "static/js/documentLibrary.js",
                   "static/js/chatRenderer.js", "static/js/chat.js", "static/js/chatStream.js"):
        assert module not in left, (module, [s for s in census() if s[0] == module])


def test_the_email_library_keeps_its_buttons():
    email = [name for f, name in census() if f == "static/js/emailLibrary.js"]
    for gone in ("doneCheck", "cancelItem", "cancelIt", "customItem", "noteItem", "it"):
        assert gone not in email, f"emailLibrary.js builds {gone} as a non-native element again"
