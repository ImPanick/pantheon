# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1996`. A research report's formulas reached its page raw or mangled.

A Deep Research report is Markdown the model writes, with TeX for formulas.
`src.visual_report._md_to_html` ran it through Python-Markdown, which knows no
math: `$a*b*c$` came out as `$a<em>b</em>c$`, `\\(…\\)` and `\\[…\\]` lost
their backslashes to Markdown's escapes, `\\\\` row breaks went with them, and
the table of contents read a heading's `$x_i$` as `$xi$`. The page loaded no
math renderer at all, so nothing was typeset.

Now `src.report_math.ReportMathExtension` keeps each formula's source, as
text, in a placeholder of the class the chat's renderer typesets (a display
formula carries a second class, which the nh3 report sanitiser lets through
as it stands), and the page hands them to `renderMath` in
`static/js/markdown/math.js`: the chat's own renderer, over the vendored KaTeX,
moved into a module that does nothing at import.

Ported from upstream Odysseus 06c1e71f (#6929). The formula, code, currency,
attribute, link, sanitiser, heading and unclosed-`$$` cases are upstream's;
the code and currency cases each have a formula beside them here, so that
every test fails on the code before. The page itself, in a browser, is
`tests/test_a_research_report_typesets_its_formulas_in_a_browser.py`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.visual_report import _md_to_html, generate_visual_report
from tests.test_markdown_lazy_lib_loading_js import _module_const

ROOT = Path(__file__).resolve().parents[1]
MATH_JS = ROOT / "static" / "js" / "markdown" / "math.js"
FORMULA = "\n\nAnd the formula: $y^2$."


def _formulas(page: str) -> list:
    """Each formula placeholder in report HTML, as `(source, display)`."""
    from src.report_math import MATH_DISPLAY_CLASS, MATH_PENDING_CLASS
    soup = BeautifulSoup(page, "html.parser")
    return [(el.get_text(), MATH_DISPLAY_CLASS in el.get("class", []))
            for el in soup.select("." + MATH_PENDING_CLASS)]


@pytest.mark.parametrize("source,tex,display", [
    (r"Value $x_i^2$.", "x_i^2", False),
    (r"Value \(x_i^2\).", "x_i^2", False),
    (r"Value $$\sum_i x_i$$.", r"\sum_i x_i", True),
    (r"Value \[\sum_i x_i\].", r"\sum_i x_i", True),
    ("$$a_i\n\nb_i$$", "a_i\n\nb_i", True),
    ("\\[a_i\n\nb_i\\]", "a_i\n\nb_i", True),
    (r"Value $a*b*c$.", "a*b*c", False),
    (r"\[\begin{aligned} a &= b \\ c &= d \end{aligned}\]",
     r"\begin{aligned} a &= b \\ c &= d \end{aligned}", True),
])
def test_a_formula_reaches_the_page_as_the_source_that_was_written(source, tex, display):
    page = _md_to_html(source)
    assert _formulas(page) == [(tex, display)]
    assert BeautifulSoup(page, "html.parser").find("em") is None


@pytest.mark.parametrize("source,kept", [
    ("`$x_i$`", "$x_i$"),
    ("```text\n$x_i$\n```", "$x_i$"),
    ("~~~text\n$x_i$\n~~~", "$x_i$"),
    ("    $x_i$", "$x_i$"),
    ("<code>$x_i$</code>", "$x_i$"),
    ("<pre>$x_i$</pre>", "$x_i$"),
    ("Prices range from $5 to $10.", "Prices range from $5 to $10."),
    ("An escaped \\$5 costs less than $10.", "$5 costs less than $10."),
])
def test_code_and_prices_are_left_as_written(source, kept):
    page = _md_to_html(source + FORMULA)
    assert _formulas(page) == [("y^2", False)]
    assert kept in BeautifulSoup(page, "html.parser").get_text()


def test_a_tag_attribute_is_not_read_as_a_formula():
    soup = BeautifulSoup(_md_to_html('<a title="$literal$">Value $x_i$</a>'), "html.parser")
    assert soup.a["title"] == "$literal$"
    assert _formulas(str(soup.a)) == [("x_i", False)]


def test_a_link_address_stays_as_written_while_its_label_can_hold_a_formula():
    soup = BeautifulSoup(_md_to_html("[$x_i$](https://example.com/$literal$)"), "html.parser")
    assert soup.a["href"] == "https://example.com/$literal$"
    assert _formulas(str(soup.a)) == [("x_i", False)]


def test_a_formula_s_source_stays_inert_and_the_report_sanitiser_still_runs():
    page = _md_to_html(
        r'$\text{<img src=x onerror="alert(1)">}$'
        '\n\n<script>alert(2)</script><a href="javascript:alert(3)">link</a>'
        '\n\n<span data-display="true" onclick="alert(4)">typed in</span>'
    )
    assert _formulas(page) == [(r'\text{<img src=x onerror="alert(1)">}', False)]
    soup = BeautifulSoup(page, "html.parser")
    assert soup.find("img") is None and soup.find("script") is None
    assert not soup.select('a[href^="javascript:"]')
    # The allowlist is the one it was: a display formula is a class, and an
    # attribute typed into the report is still taken off.
    assert not soup.select("[data-display], [onclick]")


def test_a_heading_s_formula_is_set_in_the_body_and_inline_in_the_table_of_contents():
    page = generate_visual_report(
        "Formula report",
        "# Formula report\n\n## Formula $x_i$\n\nValue $x_i$.\n\n## Total \\[n\\]\n\nThe total.",
        session_id="rp-math",
    )
    soup = BeautifulSoup(page, "html.parser")
    links = soup.select(".toc-sidebar nav a")
    # The anchors are the ones a report always had.
    assert [a["href"] for a in links] == ["#formula-xi", "#total-n"]
    for link, tex, display in zip(links, ["x_i", "n"], [False, True]):
        heading = soup.find(id=link["href"][1:])
        assert heading.name == "h2"
        assert _formulas(str(heading)) == [(tex, display)]
        assert _formulas(str(link)) == [(tex, False)], "a link's formula is set inline"
    assert [a.get_text() for a in links] == ["Formula x_i", "Total n"]


def test_an_unclosed_display_formula_stays_readable_beside_a_closed_one():
    page = _md_to_html("$$unfinished\n\nA later paragraph with $z$.")
    assert _formulas(page) == [("z", False)]
    text = BeautifulSoup(page, "html.parser").get_text()
    assert "$$unfinished" in text and "A later paragraph with" in text


def test_the_report_marks_its_formulas_with_the_class_the_renderer_typesets():
    from src.report_math import MATH_PENDING_CLASS
    assert MATH_PENDING_CLASS == _module_const("static/js/markdown/math.js", "MATH_PENDING_CLASS")


_NODE_CASE = r"""
import fs from 'node:fs';
import vm from 'node:vm';

// Everything a module could reach for at import, each a trap that says so.
const touched = [];
const TRAPS = ['document', 'window', 'fetch', 'addEventListener', 'MutationObserver',
               'localStorage', 'setTimeout', 'setInterval', 'queueMicrotask'];
const real = {};
for (const name of TRAPS) {
  real[name] = globalThis[name];
  Object.defineProperty(globalThis, name, {
    configurable: true,
    get() { touched.push(name); return real[name]; },
  });
}
const math = await import(process.argv[2]);
const atImport = [...touched];
for (const name of TRAPS) {
  Object.defineProperty(globalThis, name, { configurable: true, writable: true, value: real[name] });
}

// The vendored KaTeX itself; renderToString needs no DOM.
function loadKatex() {
  const context = { console };
  context.window = context;
  context.self = context;
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('static/lib/katex/katex.min.js', 'utf8'), context);
  return context.katex;
}
const loaded = [];
function element(tag) {
  return {
    tagName: tag.toUpperCase(), listeners: {},
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
  };
}
globalThis.window = { katex: null };
globalThis.document = {
  createElement: element,
  head: {
    appendChild(el) {
      loaded.push(el.tagName === 'SCRIPT' ? el.src : el.href);
      setTimeout(() => {
        if (el.tagName === 'SCRIPT') window.katex = loadKatex();
        (el.listeners.load || []).forEach((fn) => fn());
      }, 0);
      return el;
    },
  },
};
function placeholder(tex, display) {
  return {
    textContent: tex, written: null,
    getAttribute: (name) => (name === 'data-display' && display ? 'true' : null),
    classList: { remove() {} },
    set outerHTML(html) { this.written = html; },
  };
}
const inline = placeholder('x_i^2', false);
const shown = placeholder('\\sum_{i=1}^{n} x_i', true);
const container = {
  querySelectorAll: (selector) => (selector === '.' + math.MATH_PENDING_CLASS
    ? [inline, shown].filter((el) => el.written === null) : []),
};
await math.renderMath(container);
console.log(JSON.stringify({
  atImport, loaded, inline: inline.written, shown: shown.written,
  sources: [math.KATEX_SRC, math.KATEX_CSS],
}));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_renderer_does_nothing_at_import_and_typesets_the_placeholders_it_is_handed(tmp_path):
    case = tmp_path / "case.mjs"
    case.write_text(_NODE_CASE, encoding="utf-8")
    proc = subprocess.run(["node", str(case), MATH_JS.as_uri()], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["atImport"] == [], f"importing the renderer reached for {out['atImport']}"
    assert out["loaded"] == out["sources"] == ["/static/lib/katex/katex.min.js",
                                               "/static/lib/katex/katex.min.css"]
    assert 'class="katex"' in out["inline"] and "katex-display" not in out["inline"]
    assert "katex-display" in out["shown"]
    assert "<math" in out["inline"] and "<math" in out["shown"]
