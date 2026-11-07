# SPDX-License-Identifier: AGPL-3.0-or-later
"""DOM-XSS regressions for email plain-text linkification helpers."""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent
_HELPER = _REPO / "static" / "js" / "emailLibrary" / "utils.js"
_HAS_NODE = shutil.which("node") is not None


def _run(js: str) -> str:
    proc = subprocess.run(
        ["node", "--input-type=module"],
        input=js,
        capture_output=True,
        text=True,
        cwd=str(_REPO),
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_plain_text_linkify_escapes_href_attribute_without_double_escaping():
    js = textwrap.dedent(
        f"""
        globalThis.document = {{
          createElement() {{
            return {{
              set textContent(v) {{
                this._t = String(v ?? '')
                  .replace(/&/g, '&amp;')
                  .replace(/</g, '&lt;')
                  .replace(/>/g, '&gt;')
                  .replace(/"/g, '&quot;')
                  .replace(/'/g, '&#39;');
              }},
              get innerHTML() {{ return this._t || ''; }}
            }};
          }}
        }};
        const {{ _escLinkify }} = await import('{_HELPER.as_posix()}');
        const out = _escLinkify('See https://example.test/path?a=1&b=2 and www.example.test/a`b');
        console.log(JSON.stringify(out));
        """
    )

    html = json.loads(_run(js))

    assert 'href="https://example.test/path?a=1&amp;b=2"' in html
    assert "amp;amp" not in html
    assert 'href="https://www.example.test/a&#96;b"' in html


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_email_url_scheme_checks_strip_embedded_controls(tmp_path):
    # `B866`. This used to load the transformed source from a
    # `data:text/javascript` URL, which has no base to resolve a relative
    # import against — so the module could only be driven here for as long as
    # it imported nothing at all. It imports the canonical escaper now
    # (`util/escapeHtml.js`, a leaf added precisely so it could), so the copy is
    # written to disk at the same depth as the real file with that one
    # dependency beside it. Still the real source, still the real functions.
    box = tmp_path / "emailLibrary"
    box.mkdir()
    (tmp_path / "util").mkdir()
    shutil.copy(_REPO / "static" / "js" / "util" / "escapeHtml.js", tmp_path / "util")
    copy = box / "utils.js"
    copy.write_text(
        _HELPER.read_text(encoding="utf-8")
        .replace("function _compactUrlSchemeValue", "export function _compactUrlSchemeValue")
        .replace("function _isDangerousUrl", "export function _isDangerousUrl")
        .replace("function _isDangerousSrcset", "export function _isDangerousSrcset"),
        encoding="utf-8",
    )
    js = textwrap.dedent(
        f"""
        const mod = await import('{copy.as_posix()}');
        const checks = {{
          compact: mod._compactUrlSchemeValue('java\\n script:\\talert(1)'),
          jsUrl: mod._isDangerousUrl('java\\n script:\\talert(1)'),
          vbUrl: mod._isDangerousUrl('vb\\rscript:msgbox(1)'),
          dataUrl: mod._isDangerousUrl(' data:text/html,<script>alert(1)</script>'),
          httpUrl: mod._isDangerousUrl('https://example.test/?q=javascript:alert(1)'),
          srcset: mod._isDangerousSrcset('https://safe.test/a.png 1x, java\\nscript:alert(1) 2x'),
        }};
        console.log(JSON.stringify(checks));
        """
    )

    checks = json.loads(_run(js))

    assert checks["compact"] == "javascript:alert(1)"
    assert checks["jsUrl"] is True
    assert checks["vbUrl"] is True
    assert checks["dataUrl"] is True
    assert checks["httpUrl"] is False
    assert checks["srcset"] is True


def test_email_html_sanitizer_runs_to_fixpoint():
    source = _HELPER.read_text(encoding="utf-8")

    assert "function _sanitizeHtmlOnce(html)" in source
    assert "for (let i = 0; i < 4; i++)" in source
    assert "const next = _sanitizeHtmlOnce(out);" in source
    assert "if (next === out) break;" in source


# ── `B1825`: one pass, so an anchor is never linked again ─────────────────
#
# `_escLinkify` escaped the whole text, linked its URLs, and then ran the
# address pattern over that result, the new anchors included. A URL carrying
# an address (`?email=jane@x`, `https://user@host`) got a `mailto:` anchor
# written inside its href: the link went to the wrong place, lost its
# `target`/`rel`, and spilled `" target="_blank" ...>` into the text. And the
# URL pattern read the escaped `&gt;` and `&#39;`, so `<https://x.test/a>`
# linked to `…/a&gt`. It reads the raw text once now, each piece escaped on
# its own (upstream Odysseus 71f6dc4e, #6912).

def _linkify(*texts):
    js = textwrap.dedent(
        f"""
        const {{ _escLinkify }} = await import('{_HELPER.as_posix()}');
        console.log(JSON.stringify({json.dumps(list(texts))}.map((t) => _escLinkify(t))));
        """
    )
    return json.loads(_run(js))


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_an_address_inside_a_url_stays_part_of_that_one_link():
    (out,) = _linkify("https://example.test/unsub?email=jane@example.test&next=1")
    assert out == ('<a href="https://example.test/unsub?email=jane@example.test&amp;next=1"'
                   ' target="_blank" rel="noopener noreferrer">'
                   'https://example.test/unsub?email=jane@example.test&amp;next=1</a>')


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_a_url_with_a_user_part_is_one_web_link():
    (out,) = _linkify("https://user@host.example.test/path")
    assert out.count("<a ") == 1 and "mailto:" not in out, out
    assert 'href="https://user@host.example.test/path"' in out


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_a_url_in_angle_brackets_or_quotes_links_to_itself():
    angled, quoted = _linkify("<https://example.test/reference>", "'https://example.test/a'")
    assert angled.startswith("&lt;<a ") and angled.endswith("</a>&gt;"), angled
    assert 'href="https://example.test/reference"' in angled
    assert quoted.startswith("&#39;<a ") and quoted.endswith("</a>&#39;"), quoted
    assert 'href="https://example.test/a"' in quoted


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_an_address_is_still_a_mail_link_and_markup_is_still_text():
    mail, markup = _linkify("Mail jane@example.test", "<img src=x onerror=alert(1)>")
    assert mail == 'Mail <a href="mailto:jane@example.test">jane@example.test</a>'
    assert markup == "&lt;img src=x onerror=alert(1)&gt;"


# Upstream's own test, in a real DOM: the text a person reads is the text that
# was written, every link goes where its text says, and nothing else is made.
# Upstream loads the module from a static server of its own; here the page
# fetches it from the repository through `page.route`.
_DOM_CASES = [
    ("See https://example.test/contact?email=jane@example.test&next=1 and bob@example.test.",
     ["https://example.test/contact?email=jane@example.test&next=1", "mailto:bob@example.test"]),
    ("https://alice@example.test/path", ["https://alice@example.test/path"]),
    ("www.example.test/?email=jane@example.test", ["https://www.example.test/?email=jane@example.test"]),
    ("<https://example.test/path> and \"jane@example.test\"",
     ["https://example.test/path", "mailto:jane@example.test"]),
    ("(https://example.test/path), jane@example.test!",
     ["https://example.test/path", "mailto:jane@example.test"]),
    ("https://example.test/?literal=&quot;&next=1", ["https://example.test/?literal=&quot;&next=1"]),
    ('<img src=x onerror="alert(1)"> jane@example.test', ["mailto:jane@example.test"]),
    ("No links\njust <plain> & text", []),
]

_DOM_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const STATIC = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage();
    await page.route('http://t.local/**', (route) => {
      const u = new URL(route.request().url());
      if (u.pathname === '/') return route.fulfill({ contentType: 'text/html', body: '<!doctype html><body></body>' });
      const file = path.join(STATIC, u.pathname.replace(/^\/static\//, ''));
      if (!file.startsWith(STATIC) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
      return route.fulfill({ contentType: 'text/javascript', body: fs.readFileSync(file) });
    });
    await page.goto('http://t.local/');
    const results = await page.evaluate(async (cases) => {
      const { _escLinkify } = await import('/static/js/emailLibrary/utils.js');
      return cases.map(([raw]) => {
        const div = document.createElement('div');
        div.innerHTML = _escLinkify(raw);
        return {
          text: div.textContent,
          hrefs: [...div.querySelectorAll('a')].map((a) => a.getAttribute('href')),
          otherElements: [...div.querySelectorAll('*')].map((e) => e.tagName).filter((t) => t !== 'A'),
          unsafeBlankLink: [...div.querySelectorAll('a[target="_blank"]')]
            .some((a) => !a.relList.contains('noopener') || !a.relList.contains('noreferrer')),
        };
      });
    }, JSON.parse(process.argv[1]));
    console.log(JSON.stringify(results));
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(NODE is None, reason=_SKIP or "")
def test_linkify_preserves_text_and_link_targets_in_a_real_dom():
    proc = subprocess.run(
        [NODE, "-e", _DOM_SCRIPT, json.dumps(_DOM_CASES), str(_REPO / "static")],
        cwd=str(_REPO), capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, proc.stderr
    results = json.loads(proc.stdout.strip().splitlines()[-1])
    for (raw, hrefs), actual in zip(_DOM_CASES, results, strict=True):
        assert actual == {"text": raw, "hrefs": hrefs, "otherElements": [], "unsafeBlankLink": False}, raw
