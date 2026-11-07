# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1996` in a real browser: a research report typesets its formulas.

`tests/test_a_research_report_typesets_its_formulas.py` shows that a report's
HTML keeps each formula for the renderer, and that the renderer typesets what
it is handed. This file opens real reports from the real app, under the CSP
`core/middleware.py` gives `/api/research/report/*`, in a headless Chromium at
1440px and at 390px:

  * a report with formulas, which KaTeX typesets in the body and, inline, in
    the table of contents, from the vendored files under /static, while the
    page loads nothing of the chat's (`ui.js`, `markdown.js`, `theme.js`,
    `/api/prefs/theme`, `/api/img/mode`) and keeps working: no page error, no
    CSP refusal, no sideways scroll, the export menu opens and Escape shuts it;
  * a report with no formula, which requests nothing under /static/lib/katex/
    or /static/js/markdown/;
  * the first report with KaTeX's script refused, where every formula stays
    as its readable source;
  * Download HTML, which saves each formula once, as the MathML a browser
    draws by itself, with no link to KaTeX's sheet or script.

Measured before the fix: no formula was typeset and nothing loaded KaTeX, so
every test here failed.

Boots the app out of process with the `app_url` fixture of
`tests/test_the_command_palette_in_a_browser.py`, writes the two reports into
its data directory as a finished Deep Research run leaves them, and skips, with
the reason, where node, Playwright or Chromium is absent.
"""

import json
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, SERVED, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

USER, PASSWORD = "reader", "reader-pass-1"
WIDTHS = [1440, 390]

#: A formula wider than a phone's column.
WIDE = (r"\sum_{i=1}^{n} \left( t_i - \bar{t} \right)^2 + \frac{\alpha + \beta + \gamma + \delta"
        r" + \epsilon + \zeta + \eta + \theta}{\iota + \kappa + \lambda + \mu + \nu + \xi + \pi"
        r" + \rho} + \int_0^\infty e^{-x^2}\,dx = \sigma^2 n")

MATH_REPORT = r"""# Ferry crossing times

## Formula $x_i$

The mean crossing is $\bar{t} = \frac{1}{n}\sum_{i=1}^{n} t_i$, and a fare of $5 to $10 stays as written.

$$__WIDE__$$

## Total \[n\]

With \(\alpha\) set, the two rows are

\[\begin{aligned} a &= b \\ c &= d \end{aligned}\]
""".replace("__WIDE__", WIDE)

PLAIN_REPORT = """# Ferry timetable

## Findings

No formula here: a fare of $5 to $10 is a price.
"""

#: The source of each formula `MATH_REPORT` holds, in the body (the third,
#: fourth and sixth set on their own line) and in the table of contents.
BODY_SOURCES = ["x_i", r"\bar{t} = \frac{1}{n}\sum_{i=1}^{n} t_i", WIDE, "n", r"\alpha",
                r"\begin{aligned} a &= b \\ c &= d \end{aligned}"]
TOC_SOURCES = ["x_i", "n"]

#: What the chat's own page loads and the report page must not.
CHAT_ONLY = ["/static/js/ui.js", "/static/js/markdown.js", "/static/js/theme.js",
             "/api/prefs/theme", "/api/img/mode"]

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const [BASE, USER, PASSWORD, WIDTHS] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = {};
  const signIn = await browser.newContext();
  await signIn.request.post(BASE + '/api/auth/setup', { data: { username: USER, password: PASSWORD } });
  await signIn.request.post(BASE + '/api/auth/login', { data: { username: USER, password: PASSWORD, remember: true } });
  const storageState = await signIn.storageState();
  await signIn.close();
  for (const width of JSON.parse(WIDTHS)) {
    for (const mode of ['math', 'plain', 'blocked']) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, storageState, acceptDownloads: true });
      const page = await context.newPage();
      const errors = [];
      const requests = [];
      page.on('pageerror', (e) => errors.push(String((e && e.stack) || e)));
      page.on('request', (r) => requests.push(r.url()));
      await page.addInitScript(() => {
        window.__csp = [];
        document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));
      });
      if (mode === 'blocked') await page.route('**/static/lib/katex/katex.min.js', (route) => route.abort());
      const id = mode === 'plain' ? 'rp-plain' : 'rp-math';
      const res = await page.goto(BASE + '/api/research/report/' + id, { waitUntil: 'load' });
      if (mode === 'math') {
        await page.waitForFunction(() => !document.querySelector('.pan-math-pending'), null, { timeout: 20000 })
          .catch(() => null);
      }
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(300);
      const seen = await page.evaluate(() => {
        const all = (sel) => [...document.querySelectorAll(sel)];
        const root = document.documentElement;
        return {
          body: { katex: all('.content .katex').length, display: all('.content .katex-display').length,
                  errors: all('.content .katex-error').length },
          toc: { katex: all('.toc-sidebar nav a .katex').length, display: all('.toc-sidebar .katex-display').length,
                 labels: all('.toc-sidebar nav a').map((a) => a.getAttribute('href')) },
          pending: { body: all('.content .pan-math-pending').map((el) => el.textContent),
                     toc: all('.toc-sidebar .pan-math-pending').map((el) => el.textContent),
                     display: all('.content .pan-math-pending[data-display="true"]').length },
          text: document.querySelector('.content').textContent,
          overflow: Math.max(root.scrollWidth, document.body.scrollWidth) - root.clientWidth,
          scrollsInside: all('.content .katex-display').filter((el) => el.scrollWidth > el.clientWidth + 1).length,
          violations: window.__csp,
        };
      });
      await page.click('#btn-export');
      const menuOpened = await page.evaluate(() => document.getElementById('export-menu').classList.contains('open'));
      await page.keyboard.press('Escape');
      await page.waitForTimeout(150);
      const menuShut = await page.evaluate(() => !document.getElementById('export-menu').classList.contains('open'));
      const stayed = page.url() === BASE + '/api/research/report/' + id;
      let saved = null;
      if (mode === 'math') {
        await page.click('#btn-export');
        const [download] = await Promise.all([page.waitForEvent('download'), page.click('#btn-html')]);
        const html = fs.readFileSync(await download.path(), 'utf8');
        saved = await page.evaluate((text) => {
          const doc = new DOMParser().parseFromString(text, 'text/html');
          const count = (sel) => doc.querySelectorAll(sel).length;
          return {
            math: count('.content math') + count('.toc-sidebar math'),
            katexHtml: count('.katex-html'), pending: count('.pan-math-pending'),
            katexLinks: count('link[href*="katex"]'), katexScripts: count('script[src*="katex"]'),
          };
        }, html);
      }
      out[`${width}/${mode}`] = {
        status: res.status(), csp: res.headers()['content-security-policy'] || '',
        ...seen, errors, requests, menuOpened, menuShut, stayed, saved,
      };
      await context.close();
    }
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    folder = SERVED[app_url].data / "deep_research"
    folder.mkdir(parents=True, exist_ok=True)
    for rid, (query, report) in {"rp-math": ("ferry crossing times", MATH_REPORT),
                                 "rp-plain": ("ferry timetable", PLAIN_REPORT)}.items():
        (folder / f"{rid}.json").write_text(json.dumps({
            "id": rid, "owner": USER, "query": query, "status": "done",
            "raw_report": report, "sources": [], "stats": {},
        }), encoding="utf-8")
    script = tmp_path_factory.mktemp("b1996-browser") / "drive.js"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, USER, PASSWORD, json.dumps(WIDTHS)],
                          capture_output=True, text=True, timeout=300, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _paths(run, base):
    return [u[len(base):].split("?")[0] for u in run["requests"] if u.startswith(base)]


def _still_works(run):
    assert run["status"] == 200
    assert "script-src 'self' 'unsafe-inline'" in run["csp"], "not the report's CSP"
    assert run["errors"] == [], run["errors"]
    assert run["violations"] == [], f"the report's CSP refused {run['violations']}"
    assert run["overflow"] <= 1, f"the page scrolls sideways by {run['overflow']}px"
    assert run["menuOpened"] and run["menuShut"] and run["stayed"], "the export menu or Escape broke"


@pytest.mark.parametrize("width", WIDTHS)
def test_a_report_s_formulas_are_typeset_and_the_page_still_works(drive, width):
    run = drive[f"{width}/math"]
    assert run["pending"] == {"body": [], "toc": [], "display": 0}, "a formula was left untypeset"
    assert run["body"] == {"katex": 6, "display": 3, "errors": 0}
    assert run["toc"]["katex"] == 2 and run["toc"]["display"] == 0, "the table of contents sets a formula inline"
    assert run["toc"]["labels"] == ["#formula-xi", "#total-n"]
    assert "a fare of $5 to $10 stays as written" in run["text"]
    if width == 390:
        assert run["scrollsInside"] == 1, "the wide formula should scroll inside itself"
    _still_works(run)


@pytest.mark.parametrize("width", WIDTHS)
def test_only_a_report_with_a_formula_loads_the_renderer_and_never_the_chat(drive, app_url, width):  # noqa: F811
    math, plain = drive[f"{width}/math"], drive[f"{width}/plain"]
    loaded = _paths(math, app_url)
    for path in ("/static/js/markdown/math.js", "/static/lib/katex/katex.min.js",
                 "/static/lib/katex/katex.min.css"):
        assert path in loaded, f"{path} was not loaded"
    assert any(p.startswith("/static/lib/katex/fonts/") for p in loaded), "KaTeX drew without its fonts"
    for run in (math, plain):
        assert all(u.startswith(app_url) or u.startswith(("data:", "blob:")) for u in run["requests"]), (
            "the report reached past its own origin")
        assert not [p for p in _paths(run, app_url) if p in CHAT_ONLY], "the report loaded the chat's modules"
    assert not [p for p in _paths(plain, app_url)
                if p.startswith(("/static/lib/katex/", "/static/js/markdown/"))], (
        "a report with no formula loaded the renderer")
    assert plain["pending"] == {"body": [], "toc": [], "display": 0} and plain["body"]["katex"] == 0
    _still_works(plain)


@pytest.mark.parametrize("width", WIDTHS)
def test_a_report_whose_katex_is_refused_keeps_each_formula_readable(drive, width):
    run = drive[f"{width}/blocked"]
    assert run["pending"]["body"] == BODY_SOURCES
    assert run["pending"]["toc"] == TOC_SOURCES
    assert run["pending"]["display"] == 3, "a display formula lost its mark"
    assert run["body"]["katex"] == 0
    _still_works(run)


@pytest.mark.parametrize("width", WIDTHS)
def test_a_saved_report_shows_each_formula_once_as_mathml(drive, width):
    saved = drive[f"{width}/math"]["saved"]
    assert saved == {"math": 8, "katexHtml": 0, "pending": 0, "katexLinks": 0, "katexScripts": 0}
