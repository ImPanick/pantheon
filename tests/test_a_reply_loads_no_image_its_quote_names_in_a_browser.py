# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1903`. Opening a reply, or saving its draft, loaded the images its quote named.

The reply editor turns the quoted message into text, and the save, send and
local-draft paths turn the body into text once more, by setting `innerHTML`
on a `<div>` made by the page's own `document`. That is a live parse: an
`<img>` in the markup is fetched as it is parsed, while the element is still
detached. Mail's text is the sender's, so a sender who wrote
`<img src="/api/img?u=…">` in a message got a request when the reply opened,
and one escaped as `&lt;img …&gt;` (text in the quote, a tag again once read
back) got another when the draft was saved. In the default `ask` mode the
image proxy then fetched the sender's URL from the server. Measured with this
file's script on `62c93ba2`: both requests went out.

Both helpers now parse into an element of `document.implementation
.createHTMLDocument('')`, a document with no browsing context, which fetches
nothing and runs nothing. It keeps the `<div>` parsing context, so the quoted
history reads as it did; only a `<noscript>`'s content now reads as markup.
Upstream Odysseus 232249eb used a `<template>`, which reads the text around a
stray table tag differently.

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

# Ordinary quotes, and the text the quoted history shows for each, as it did
# before `B1903` (`innerText` of the history block).
_QUOTES = {
    "> Hi <b>Ann</b> &amp; team,\n> see <a href=\"https://example.com/plan\">the plan</a>.\n":
        "---------- Previous message ----------\nOn Mon, Alice  wrote:\n> Hi Ann & team,\n> see the plan.",
    "> Lunch at 1 < 2 pm? 3 > 2.\n> &lt;b&gt;not bold&lt;/b&gt;\n":
        "---------- Previous message ----------\nOn Mon, Alice  wrote:\n> Lunch at 1 < 2 pm? 3 > 2.\n> <b>not bold</b>",
    "> <p>One</p><p>Two</p>\n> <ul><li>a</li><li>b</li></ul>\n":
        "---------- Previous message ----------\nOn Mon, Alice  wrote:\n> OneTwo\n> ab",
}

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const QUOTES = JSON.parse(process.argv[3]);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  // No service worker between the page and the routes below.
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, serviceWorkers: 'block' });
  const creds = { username: 'editor', password: 'editor-pass-1' };
  await ctx.request.post(BASE + '/api/auth/setup', { data: creds });
  await ctx.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const page = await ctx.newPage();
  const out = { errors: [], hits: {} };
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  // Each request the page makes for the image proxy, by its `k`, answered 404:
  // a request here is the server fetching the sender's URL.
  await page.route((url) => url.pathname === '/api/img', (r) => {
    const k = new URL(r.request().url()).searchParams.get('k') || '?';
    out.hits[k] = (out.hits[k] || 0) + 1;
    return r.fulfill({ status: 404, body: '' });
  });
  // No mail account here: the draft is answered as saved.
  await page.route(BASE + '/api/email/draft', (r) => r.fulfill({ status: 200,
    contentType: 'application/json', body: JSON.stringify({ success: true }) }));
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);
  const mk = async (data) => (await (await page.request.post(BASE + '/api/document', { data })).json()).id;
  const open = async (id) => {
    await page.evaluate(async (id) => { await window.documentModule.loadDocument(id); }, id);
    await page.waitForFunction((id) => !!document.querySelector(`.doc-tab.active[data-doc-id="${id}"]`),
      id, { timeout: 30000 });
    await page.waitForTimeout(800);
  };
  const reply = (quote) => 'To: alice@example.com\nSubject: Re: Plans\nIn-Reply-To: <abc@example.com>\n---\n'
    + 'Thanks, see you then.\n\n---------- Previous message ----------\n'
    + 'On Mon, Alice <alice@example.com> wrote:\n' + quote;
  const img = (k) => '/api/img?u=https%3A%2F%2Ft.example%2Fp.gif&k=' + k;

  const beacon = await mk({ title: 'Re: Plans', language: 'email', content: reply(
    '> hi <img src="' + img('open') + '">\n'
    + '> &lt;img src="' + img('save').replace('&', '&amp;') + '"&gt;\n') });
  await open(beacon);
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.getElementById('doc-email-draft-btn').click());
  await page.waitForTimeout(2000);
  // The control: the same image on the live page is requested, and counted.
  // It goes out last, so by the time it is counted the others would have been.
  await page.evaluate((src) => { const i = document.createElement('img'); i.src = src; document.body.appendChild(i); },
    img('control'));
  for (let i = 0; i < 300 && !out.hits.control; i++) await page.waitForTimeout(100);

  out.quotes = {};
  for (const quote of QUOTES) {
    await open(await mk({ title: 'Re: Plans', language: 'email', content: reply(quote) }));
    out.quotes[quote] = await page.evaluate(() => {
      const q = document.querySelector('#doc-email-richbody .email-quoted-history');
      return q ? q.innerText : null;
    });
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("reply-quote-browser")
    script = d / "drive.js"
    script.write_text(_SCRIPT)
    proc = subprocess.run([NODE, str(script), app_url, json.dumps(list(_QUOTES))], capture_output=True,
                          text=True, timeout=480, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_opening_a_reply_requests_no_image_its_quote_names(drive):
    # The count is live: the same image on the page itself is requested.
    assert drive["hits"].get("control", 0) >= 1, drive["hits"]
    assert "open" not in drive["hits"], drive["hits"]
    # And the quoted history reads as it did.
    assert drive["quotes"] == _QUOTES, drive["quotes"]


def test_saving_a_reply_requests_no_image_its_quote_names(drive):
    # Only the save reads `&lt;img …&gt;` back as a tag.
    assert "save" not in drive["hits"], drive["hits"]
    # Playwright's `serviceWorkers: 'block'` reads `navigator.serviceWorker`
    # in every frame and throws in a sandboxed one: the harness's error, not
    # the page's (`B1288`). Every other page error fails.
    errors = [e for e in drive["errors"] if "Failed to read the 'serviceWorker' property" not in e]
    assert errors == [], errors
