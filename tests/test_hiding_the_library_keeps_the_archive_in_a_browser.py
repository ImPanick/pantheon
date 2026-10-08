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
    return { text: (t.querySelector('span') || t).textContent, button: b ? b.textContent.trim() : null,
      oneLine: b ? getComputedStyle(b).whiteSpace === 'nowrap' : null };
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
  // A link to the archive's URL opens the archive.
  await boot('/library/archive');
  out.reload = await state();
  // A reload of the entry the back stack wrote reopens it as it was — after
  // the switches are known (it came back with Documents before they were).
  asked.length = 0;
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await settle(2500);
  out.reloadEntry = await state();
  out.reloadAsked = asked.filter((p) => p.startsWith('/api/documents') || p === '/api/document-folders');
  await page.click('#doclib-close');
  await settle(800);
  // Ctrl+K: "library" offers the archive by its own name.
  await page.focus('#message');
  await page.keyboard.press('Control+k'); await settle(300);
  await page.keyboard.type('library'); await settle(700);
  out.palette = await page.evaluate(() => {
    const box = document.getElementById('search-results');
    return box ? box.textContent.replace(/\s+/g, ' ').trim() : null;
  });
  await page.keyboard.press('Enter'); await settle(1300);
  out.paletteOpened = await state();
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

  // A touch screen has no hover: *manage* — the archive's door — shows its word.
  {
    const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    await phone.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
    const pp = await phone.newPage();
    await pp.goto(BASE + '/', { waitUntil: 'load' });
    await pp.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await pp.waitForTimeout(2000);
    await pp.click('#hamburger-btn'); await pp.waitForTimeout(800);
    out.phoneManage = await pp.evaluate(() => {
      const b = document.getElementById('chats-library-btn');
      const l = b.querySelector('.list-item-plus-label');
      const r = l.getBoundingClientRect();
      return { word: l.textContent.trim(), width: Math.round(r.width), labelOpacity: getComputedStyle(l).opacity,
        buttonOpacity: getComputedStyle(b).opacity, section: !document.getElementById('sessions-section').classList.contains('hidden') };
    });
    await pp.click('#chats-library-btn'); await pp.waitForTimeout(1200);
    out.phoneOpened = await pp.evaluate(() => !!document.getElementById('doclib-modal'));
    await phone.close();
  }

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
    assert drive["reloadEntry"]["open"] is True and drive["reloadEntry"]["active"] == "archive"
    assert drive["reloadEntry"]["tabs"] == ["chats", "research", "archive"], (
        "a reload reopened the window before the switches were known")
    assert drive["reloadAsked"] == []


def test_the_palette_offers_the_archive_and_opens_it(drive):
    assert drive["palette"] and "Archived chats" in drive["palette"], drive["palette"]
    assert drive["paletteOpened"]["open"] is True and drive["paletteOpened"]["active"] == "archive"


def test_the_librarys_own_url_says_where_the_archive_is_and_its_button_goes_there(drive):
    assert drive["libraryLink"]["open"] is False
    assert drive["libraryToast"] == {
        "text": "Library is switched off for everyone. An admin can turn it back on in "
                "Settings → Agent Tools. " + GUIDE,
        "button": "Open archive",
        "oneLine": True,
    }
    assert drive["followed"]["open"] is True and drive["followed"]["active"] == "archive"
    assert drive["openArchive"]["open"] is True and drive["openArchive"]["active"] == "archive"


def test_on_a_touch_screen_manage_shows_its_word(drive):
    """No hover: *manage* was an empty 13px box at 35% opacity — the
    archive's only sidebar door with the Library off, named by the guide."""
    m = drive["phoneManage"]
    assert m["section"] is True and m["word"] == "manage"
    assert m["width"] > 20 and float(m["labelOpacity"]) == 1.0, m
    assert float(m["buttonOpacity"]) >= 0.7, m
    assert drive["phoneOpened"] is True


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
