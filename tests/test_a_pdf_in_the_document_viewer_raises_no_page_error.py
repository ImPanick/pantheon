# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1288` — the PDF document viewer's sandboxed frame reads nothing it may not.

fx5-vision saw, attaching a PDF in Chromium: *"Failed to read the
'serviceWorker' property from 'Navigator': Service worker is disabled because
the context is sandboxed and lacks the 'allow-same-origin' flag."* Measured
2026-10-26: the sandboxed frame is the document viewer's HTML preview
(`#doc-html-preview`, `sandbox="allow-scripts allow-modals"`, `about:blank`),
and what reads `navigator.serviceWorker` in it is **the test harness, not
Pantheon** — the fx5 drive opens its browser context with Playwright's
`serviceWorkers: 'block'`, which injects a script into every frame that touches
`navigator.serviceWorker`; the error's stack is `<anonymous>`, not a Pantheon
URL. The same open in a context that leaves service workers to the page — a
person's browser — raises nothing. No product change: `allow-same-origin` is
not added to any sandbox (`FORBIDDEN.md` Part 2's spirit), and nothing in the
app reads the property in that frame.

Driven in the real app in headless Chromium (booted as
`tests/test_the_command_palette_in_a_browser.py` boots it): a PDF imported
through the route the composer uses, opened in the document viewer, with the
browser's service-worker policy the page's own.
"""
import json
import os
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = process.argv[2], PDF = process.argv[3];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [], frames: [] };
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  await ctx.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const creds = { username: 'ada', password: 'ada-pass-1234' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const sess = await (await page.request.post(BASE + '/api/session',
    { multipart: { name: 'pdf', skip_validation: 'true' } })).json();
  const imp = await page.request.post(BASE + '/api/documents/import-pdf', { multipart: {
    file: { name: 'report.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync(PDF) },
    session_id: sess.id } });
  out.imported = imp.status();
  const doc = await imp.json();
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 }).catch(() => {});
  await page.waitForTimeout(1500);
  out.opened = await page.evaluate(async (id) => {
    try { window.documentModule.openPanel && window.documentModule.openPanel();
          await window.documentModule.loadDocument(id); return true; }
    catch (e) { return String(e && e.message || e); }
  }, doc.id);
  await page.waitForTimeout(5000);
  for (const f of page.frames()) {
    let sandbox = null, id = null;
    try { const h = await f.frameElement(); sandbox = await h.getAttribute('sandbox'); id = await h.getAttribute('id'); } catch (_) {}
    out.frames.push({ id, sandbox });
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def file_database(tmp_path_factory):
    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp_path_factory.mktemp("pdfview-db") / "app.db")
    yield
    if before is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = before


@pytest.fixture(scope="module")
def drive(file_database, app_url, tmp_path_factory):  # noqa: F811
    from test_attachment_extension_registers import _minimal_pdf
    work = tmp_path_factory.mktemp("pdfview-pw")
    (work / "report.pdf").write_bytes(_minimal_pdf("MARKPDF1288"))
    script = work / "pdfview.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, str(work / "report.pdf")],
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_pdf_opened_in_the_viewer_beside_its_sandboxed_frame(drive):
    """Not vacuous: the import answered, the viewer opened the document, and
    the sandboxed preview frame the report named is in the page."""
    assert drive["imported"] == 200 and drive["opened"] is True, drive
    assert {"id": "doc-html-preview", "sandbox": "allow-scripts allow-modals"} in drive["frames"]


def test_a_persons_browser_sees_no_page_error(drive):
    assert drive["errors"] == [], drive["errors"]
