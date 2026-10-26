# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1513` — the document type picker shows a derived language it has no option for.

`attachment_language` names a language for any suffix that reads like one
(`kotlin`, `log`, `diff`, `perl`, `powershell`, `lua`, `swift`, …), and since
`B1233` the document keeps it — but `#doc-language-select` is a fixed list, and
a `<select>` set to a value it has no option for shows blank. Now the picker's
value setter adds the option first (`document.js` `ensureLanguageOption`), so
it shows what the document is, and the custom menu lists it.

Driven in the real app in headless Chromium (`app_url`, as
`test_a_document_prints_as_text_and_names_its_type_in_a_browser.py` boots it):
a `.kt` file goes through the Library's own import (`importFileAsDocuments`),
the document is opened, and the picker is read.
"""

import json
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const creds = { username: 'kotlin', password: 'kotlin-pass-1' };
  await ctx.request.post(BASE + '/api/auth/setup', { data: creds });
  await ctx.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const page = await ctx.newPage();
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1000);
  const pick = () => page.evaluate(() => {
    const s = document.getElementById('doc-language-select');
    const trigger = document.getElementById('doc-langpicker-trigger');
    const rows = [...document.querySelectorAll('#doc-langpicker-menu .doc-langpicker-item')].map((r) => r.dataset.value);
    return { value: s.value, shown: s.selectedIndex >= 0 ? s.options[s.selectedIndex].textContent : null,
             trigger: trigger ? trigger.textContent.trim() : null, inMenu: rows };
  });
  const open = async (id) => {
    await page.evaluate(async (id) => { await window.documentModule.loadDocument(id); }, id);
    await page.waitForFunction((id) => !!document.querySelector(`.doc-tab.active[data-doc-id="${id}"]`),
      id, { timeout: 30000 });
    await page.waitForTimeout(500);
  };
  const imported = await page.evaluate(async () => {
    const lib = await import('/static/js/documentLibrary.js');
    const file = new File(['fun main() {\n    println("hi")\n}\n'], 'Main.kt', { type: '' });
    const made = await lib.importFileAsDocuments(file);
    const doc = Array.isArray(made) ? made[0] : made;
    return { id: doc && (doc.id || (doc.document && doc.document.id)), language: doc && doc.language };
  });
  out.imported = imported;
  await open(imported.id);
  out.kotlin = await pick();
  const mdId = (await (await page.request.post(BASE + '/api/document',
    { data: { title: 'notes', language: 'markdown', content: '# hi' } })).json()).id;
  await open(mdId);
  out.md = await pick();
  await open(imported.id);
  out.kotlinAgain = await pick();
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("doc-picker-browser")
    script = d / "drive.js"
    script.write_text(_SCRIPT)
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_an_imported_kt_file_shows_kotlin_in_the_picker(drive):
    assert drive["imported"]["language"] == "kotlin", drive["imported"]
    assert drive["kotlin"]["value"] == "kotlin"
    assert drive["kotlin"]["shown"] == "kotlin", "the picker showed blank for kotlin"
    assert "kotlin" in drive["kotlin"]["trigger"]
    assert "kotlin" in drive["kotlin"]["inMenu"], "the menu does not list the document's language"


def test_moving_away_and_back_keeps_it_kotlin(drive):
    assert drive["md"]["value"] == "markdown"
    assert drive["kotlinAgain"]["value"] == "kotlin" and drive["kotlinAgain"]["shown"] == "kotlin"
    assert drive["kotlinAgain"]["inMenu"].count("kotlin") == 1, "the option was added twice"
    assert drive["errors"] == []
