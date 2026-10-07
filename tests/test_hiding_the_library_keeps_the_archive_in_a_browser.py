# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1194` in a real browser — the Library switched off, the archive reached.

`tests/test_hiding_the_library_keeps_the_archive_js.py` drives each module on
its own. What only the assembled app shows: the *manage* door wired in
`app.js`' initialiser, the Library window's tab in the URL (`app.js` gives the
back stack its tab hooks), Back and a reload landing on the archive, and the
toast a hidden Library's door says, with its button.

`D-2026-10-07-02` §3: hiding the Library takes documents away, not the chat
archive; the archive keeps a door of its own, and a hidden Library reached
anyway says where archived chats are.

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

GUIDE = "Archived chats are under Chats → manage."

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1400, height: 800 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String((e && e.stack) || e)));
  const asked = [];
  page.on('request', (r) => { const u = new URL(r.url()); if (u.pathname.startsWith('/api/')) asked.push(u.pathname); });
  const out = { errors };
  const creds = { username: 'archivist', password: 'archivist-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const settle = (ms = 700) => page.waitForTimeout(ms);
  const boot = async (path) => {
    await page.goto(BASE + path, { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await settle(2000);
  };
  const state = () => page.evaluate(() => {
    const m = document.getElementById('doclib-modal');
    const open = !!m && !m.classList.contains('hidden') && getComputedStyle(m).display !== 'none'
      && !(m.querySelector('.modal-content') || { classList: { contains: () => false } }).classList.contains('modal-closing');
    const row = document.getElementById('tool-library-btn');
    return {
      open, path: location.pathname,
      tabs: m ? [...m.querySelectorAll('[data-doclib-tab]')].map((b) => b.dataset.doclibTab) : null,
      active: m ? ((m.querySelector('.lib-tab.active') || {}).dataset || {}).doclibTab || null : null,
      documentsPanel: !!(m && m.querySelector('[data-doclib-panel="documents"]')),
      libraryRow: row ? getComputedStyle(row).display !== 'none' : null,
    };
  });
  const toast = () => page.evaluate(() => {
    const t = document.getElementById('toast');
    if (!t || !t.classList.contains('show')) return null;
    const b = [...t.querySelectorAll('button')].find((x) => !x.classList.contains('toast-close-btn'));
    return { text: (t.querySelector('span') || t).textContent, button: b ? b.textContent.trim() : null };
  });
  const manage = async () => {
    await page.hover('#sessions-section .section-header-flex');
    await page.click('#chats-library-btn');
    await settle(1200);
  };

  // ── switched off for everyone ──────────────────────────────────────────
  out.off = (await page.request.post(BASE + '/api/auth/features', { data: { document_editor: false } })).status();
  await boot('/');
  out.start = await state();
  asked.length = 0;
  await manage();
  out.manage = await state();
  await page.click('#doclib-modal [data-doclib-tab="archive"]');
  await settle(1200);
  out.archive = await state();
  out.archiveAsked = asked.filter((p) => p.startsWith('/api/session') || p.startsWith('/api/document') || p.startsWith('/api/research'));
  // Back: the archive closes, the URL is the chat's again.
  await page.goBack();
  await settle(1200);
  out.back = await state();
  // A reload of the archive's URL reopens the archive.
  await boot('/library/archive');
  out.reload = await state();
  await page.click('#doclib-close');
  await settle(800);
  // The Library's own URL: refused, with the guide and its door.
  await boot('/library');
  out.libraryLink = await state();
  out.libraryToast = await toast();
  if (out.libraryToast && out.libraryToast.button) {
    await page.click('#toast button:not(.toast-close-btn)');
    await settle(1200);
  }
  out.followed = await state();
  await page.click('#doclib-close');
  await settle(800);
  // `/open archive` in the chat.
  await page.fill('#message', '/open archive');
  await page.press('#message', 'Enter');
  await settle(1500);
  out.openArchive = await state();
  await page.click('#doclib-close');
  await settle(800);
  // Settings: each switch's line says documents go and where the archive is.
  const line = (sel) => page.evaluate((sel) => {
    const chk = document.querySelector(sel);
    const row = chk && chk.closest('.vis-row, .admin-toggle-row');
    const sub = row && row.querySelector('.vis-keeps, .admin-toggle-sub');
    return sub ? sub.textContent : null;
  }, sel);
  // Agent Tools by its nav: a link to an admin panel followed at load lands on
  // Account before the admin check answers (filed with `B1194`'s note).
  await boot('/');
  await page.click('#user-bar-settings'); await settle(800);
  await page.click('#settings-modal [data-settings-tab="tools"]');
  await page.waitForSelector('#adm-featureToggles [data-adm-feature="document_editor"]', { state: 'attached', timeout: 30000 })
    .catch(async () => { out.debugTools = await page.evaluate(() => ({ path: location.pathname,
      html: (document.getElementById('adm-featureToggles') || {}).innerHTML })); });
  out.everyoneLine = await line('#adm-featureToggles [data-adm-feature="document_editor"]');
  await boot('/settings/appearance');
  out.browserLine = await line('#settings-modal [data-ui-key="tool-library"]');

  // ── back on: the Library as before ─────────────────────────────────────
  out.on = (await page.request.post(BASE + '/api/auth/features', { data: { document_editor: true } })).status();
  await boot('/');
  asked.length = 0;
  out.onStart = await state();
  await manage();
  out.onManage = await state();
  await page.click('#doclib-modal [data-doclib-tab="documents"]');
  await settle(1000);
  out.onDocuments = await state();
  out.onAsked = asked.filter((p) => p.startsWith('/api/document'));

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("b1194-browser") / "drive.js"
    script.write_text(_SCRIPT)
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=480, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_manage_opens_the_chat_archive_with_the_library_switched_off(drive):
    assert drive["off"] == 200
    assert drive["start"]["libraryRow"] is False, "the Library's sidebar row is still drawn"
    assert drive["manage"]["open"] is True, "*manage* was refused with the Library switched off"
    assert drive["manage"]["tabs"] == ["chats", "research", "archive"]
    assert drive["manage"]["active"] == "chats"
    assert drive["manage"]["documentsPanel"] is False
    assert drive["archive"]["active"] == "archive"
    assert drive["archive"]["path"] == "/library/archive", "the archive has no URL of its own"
    assert "/api/sessions/archived" in drive["archiveAsked"]
    # The window's own document requests: the list, its folders, the archived
    # ones. (`/api/document-folders/plans` is the Tasks poller's page-load
    # check for a waiting Documents Tidy plan, not this window — filed.)
    asked = [p for p in drive["archiveAsked"] if p.startswith("/api/document")
             and p != "/api/document-folders/plans"]
    assert not asked, drive["archiveAsked"]


def test_back_closes_the_archive_and_a_reload_of_its_url_reopens_it(drive):
    assert drive["back"]["open"] is False
    assert drive["back"]["path"] == "/"
    assert drive["reload"]["open"] is True
    assert drive["reload"]["active"] == "archive"
    assert drive["reload"]["tabs"] == ["chats", "research", "archive"]


def test_the_librarys_own_url_says_where_the_archive_is_and_its_button_goes_there(drive):
    assert drive["libraryLink"]["open"] is False
    assert drive["libraryToast"] == {
        "text": "Library is switched off for everyone. An admin can turn it back on in "
                "Settings → Agent Tools. " + GUIDE,
        "button": "Open archive",
    }
    assert drive["followed"]["open"] is True and drive["followed"]["active"] == "archive"
    assert drive["openArchive"]["open"] is True and drive["openArchive"]["active"] == "archive"


def test_settings_says_the_switches_hide_documents_and_where_the_archive_is(drive):
    assert drive["everyoneLine"] == ("Off hides documents and the Document editor button. " + GUIDE), (
        drive.get("debugTools"))
    assert drive["browserLine"] == "Off hides documents. " + GUIDE


def test_switched_back_on_the_library_is_as_before(drive):
    assert drive["on"] == 200
    assert drive["onStart"]["libraryRow"] is True
    assert drive["onManage"]["tabs"] == ["chats", "documents", "research", "archive"]
    assert drive["onDocuments"]["documentsPanel"] is True
    assert drive["onDocuments"]["path"] == "/library/documents"
    assert "/api/documents/library" in drive["onAsked"]
    assert drive["errors"] == []
