# SPDX-License-Identifier: AGPL-3.0-or-later
"""KaTeX and Mermaid must be vendored and fetched only on first real use.

They used to load from cdn.jsdelivr.net in every <head>, costing ~985 KB on the
wire per page load, breaking offline installs and announcing each session to a
third party. These tests pin the replacement contract: one fetch per library,
never before a formula or a ```mermaid fence actually shows up, and math still
renders once the library lands.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.helpers.markdown_harness import harness_import  # B882

_REPO = Path(__file__).resolve().parent.parent
_HAS_NODE = shutil.which("node") is not None

MERMAID_SRC = "/static/lib/mermaid.min.js"
KATEX_SRC = "/static/lib/katex/katex.min.js"
KATEX_CSS = "/static/lib/katex/katex.min.css"


def _module_const(rel, name):
    """The value of a `const <name> = '<literal>'` in a shipped module.

    Read, not retyped. These four tests spent a fortnight red because they
    asserted `ody-math-pending` while `static/js/markdown.js` had said
    `pan-math-pending` since `P0-04`'s rename — a fixture written to prove a
    contract, pinning the side of it that moved. A test that hardcodes a
    constant the module owns is testing its own copy (`P0-31`)."""
    src = (_REPO / rel).read_text(encoding="utf-8")
    match = re.search(rf"^const {name} = ['\"]([^'\"]+)['\"]", src, re.M)
    assert match, f"{rel} no longer defines a `const {name}` string"
    return match.group(1)


# `static/js/markdown.js` puts this on every formula it banks for later.
MATH_PENDING_CLASS = _module_const("static/js/markdown.js", "MATH_PENDING_CLASS")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _katex_fonts_block(sw_source: str) -> str:
    """The literal body of sw.js's KATEX_FONTS array."""
    match = re.search(r"const KATEX_FONTS = \[(.*?)\]", sw_source, re.S)
    assert match, "sw.js no longer defines a KATEX_FONTS array"
    return match.group(1)


# A DOM stub small enough to reason about: it records every <script>/<link> the
# module injects and lets the test decide when each one "loads", which is the
# only way to observe that a second call reuses the first fetch.
_HARNESS = harness_import("importMarkdown") + r"""
import fs from 'node:fs';
import vm from 'node:vm';

// The vendored KaTeX build itself, not a stand-in. A fake renderer that echoes
// its input cannot tell "a < b" from "a &lt; b" — real KaTeX reads the "&" as
// an alignment marker and returns a .katex-error span, which is the whole
// point of the entity tests below. renderToString needs no DOM, so a bare vm
// context is enough and keeps the library off the harness globals until a test
// installs it deliberately.
function loadRealKatex() {
  const context = { console };
  context.window = context;
  context.self = context;
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('./static/lib/katex/katex.min.js', 'utf8'), context);
  if (!context.katex) throw new Error('vendored katex.min.js did not define a katex global');
  return context.katex;
}

const injected = { scripts: [], links: [] };

function makeEl(tag) {
  return {
    tagName: String(tag).toUpperCase(),
    _listeners: {},
    classList: { remove() {} },
    addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); },
    fire(type) { (this._listeners[type] || []).forEach((fn) => fn()); },
  };
}

function makeTemplate() {
  return {
    _html: '',
    content: { querySelectorAll() { return []; } },
    set innerHTML(value) { this._html = value; },
    get innerHTML() { return this._html; },
  };
}

globalThis.window = { location: { origin: 'http://localhost' }, katex: null, mermaid: null };
globalThis.document = {
  readyState: 'complete',
  addEventListener() {},
  head: {
    appendChild(el) {
      if (el.tagName === 'SCRIPT') injected.scripts.push(el);
      else if (el.tagName === 'LINK') injected.links.push(el);
      return el;
    },
  },
  createElement(tag) {
    if (tag === 'template') return makeTemplate();
    return makeEl(tag);
  },
  querySelectorAll() { return []; },
};
globalThis.MutationObserver = class { observe() {} };

// `B872`. All three palette writers set `color-scheme` as an INLINE
// declaration on <html> (`theme.js:292` plus the two first-paint scripts), and
// `documentScheme()` reads it back off `.style`. This is the smallest thing
// that answers that read; `setScheme(null)` puts the document back to having
// never been told, which is what a first paint looks like.
globalThis.document.documentElement = {
  style: {
    _v: {},
    setProperty(k, v) { this._v[k] = String(v); },
    getPropertyValue(k) { return this._v[k] === undefined ? '' : this._v[k]; },
  },
};
function setScheme(value) {
  const st = globalThis.document.documentElement.style;
  if (value === null) delete st._v['color-scheme'];
  else st.setProperty('color-scheme', value);
}

// A mermaid stand-in that answers `getConfig()` the way the real bundle does:
// whatever theme it was last handed, with that theme's own ink. Without
// `mermaidAPI` there is nothing to read back and `applyMermaidTheme` stops at
// one call, which is the shape the older tests in this file exercise.
const THEME_INK = { dark: 'lightgrey', neutral: '#666' };
function fakeMermaid(record) {
  let current = {};
  return {
    initialize(cfg) { current = cfg; record.push(JSON.parse(JSON.stringify(cfg))); },
    run() {},
    mermaidAPI: {
      getConfig: () => ({
        theme: current.theme,
        themeVariables: Object.assign(
          { lineColor: THEME_INK[current.theme] || null }, current.themeVariables || {}),
      }),
    },
  };
}

const mod = await importMarkdown();

// A container whose querySelectorAll answers from a fixed element list, so a
// test can hand the renderer exactly the nodes it wants it to see.
function makeContainer(elements) {
  return {
    querySelectorAll(selector) {
      return (elements[selector] || []).slice();
    },
  };
}

const emit = (value) => console.log(JSON.stringify(value));
"""


def _run_node(body: str, timeout: int = 20):
    # `__MATH_PENDING__` rather than an f-string: these blocks are full of JS
    # braces, and doubling every one of them to interpolate a single class name
    # would make the harness unreadable to buy nothing.
    script = (_HARNESS + textwrap.dedent(body)).replace(
        "__MATH_PENDING__", MATH_PENDING_CLASS
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO,
        capture_output=True,
        timeout=timeout,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"node failed:\nSTDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout}")
    return json.loads(result.stdout.splitlines()[-1])


def test_ensure_mermaid_shares_one_load_between_concurrent_callers(node_available):
    """Two callers before the library lands must not trigger two fetches."""
    out = _run_node(
        """
        const p1 = mod.ensureMermaid();
        const p2 = mod.ensureMermaid();
        const samePromise = p1 === p2;
        const srcs = injected.scripts.map((s) => s.src);

        let initializeCalls = 0;
        globalThis.window.mermaid = {
          initialize() { initializeCalls++; },
          run() {},
        };
        injected.scripts[0].fire('load');

        const [a, b] = await Promise.all([p1, p2]);
        emit({
          samePromise,
          scriptCount: injected.scripts.length,
          srcs,
          sameLibrary: a === b && a === globalThis.window.mermaid,
          initializeCalls,
        });
        """
    )
    assert out["samePromise"] is True
    assert out["scriptCount"] == 1
    assert out["srcs"] == [MERMAID_SRC]
    assert out["sameLibrary"] is True
    assert out["initializeCalls"] == 1


def test_ensure_mermaid_retries_after_a_failed_load(node_available):
    """A blocked first fetch must not poison every later diagram."""
    out = _run_node(
        """
        const first = mod.ensureMermaid();
        injected.scripts[0].fire('error');
        let firstError = null;
        try { await first; } catch (e) { firstError = e.message; }

        const second = mod.ensureMermaid();
        const retried = injected.scripts.length === 2;
        globalThis.window.mermaid = { initialize() {}, run() {} };
        injected.scripts[1].fire('load');
        await second;

        emit({ firstError, retried, differentPromise: first !== second });
        """
    )
    assert MERMAID_SRC in out["firstError"]
    assert out["retried"] is True
    assert out["differentPromise"] is True


def test_render_mermaid_does_not_fetch_when_no_diagram_is_present(node_available):
    """The whole point of the lazy load: no fence, no 3.5 MB download."""
    out = _run_node(
        """
        const container = makeContainer({});
        await mod.renderMermaid(container);
        emit({ scriptCount: injected.scripts.length });
        """
    )
    assert out["scriptCount"] == 0


def test_render_mermaid_fetches_once_a_diagram_is_present(node_available):
    out = _run_node(
        """
        const node = makeEl('pre');
        node.isConnected = true;
        const container = makeContainer({ 'pre.mermaid:not([data-processed])': [node] });

        const pending = mod.renderMermaid(container);
        const srcs = injected.scripts.map((s) => s.src);

        let ranWith = null;
        globalThis.window.mermaid = {
          initialize() {},
          run(opts) { ranWith = opts.nodes.length; },
        };
        injected.scripts[0].fire('load');
        await pending;

        emit({ srcs, ranWith });
        """
    )
    assert out["srcs"] == [MERMAID_SRC]
    assert out["ranWith"] == 1


def test_ensure_katex_loads_script_and_stylesheet_once(node_available):
    out = _run_node(
        """
        const p1 = mod.ensureKatex();
        const p2 = mod.ensureKatex();
        const samePromise = p1 === p2;
        const scriptSrcs = injected.scripts.map((s) => s.src);
        const linkHrefs = injected.links.map((l) => l.href);

        globalThis.window.katex = { renderToString: (src) => src };
        injected.scripts[0].fire('load');
        injected.links[0].fire('load');
        await Promise.all([p1, p2]);

        emit({ samePromise, scriptSrcs, linkHrefs });
        """
    )
    assert out["samePromise"] is True
    assert out["scriptSrcs"] == [KATEX_SRC]
    assert out["linkHrefs"] == [KATEX_CSS]


def test_md_to_html_defers_math_when_katex_is_not_loaded_yet(node_available):
    """Without KaTeX the source is banked verbatim, not dropped or mangled."""
    out = _run_node(
        """
        const html = mod.mdToHtml('Inline $x^2 + y_1$ and\\n\\n$$\\\\frac{a}{b}$$\\n');
        emit({ html, scriptCount: injected.scripts.length });
        """
    )
    html = out["html"]
    assert f'class="{MATH_PENDING_CLASS}" data-display="false"' in html
    assert f'class="{MATH_PENDING_CLASS}" data-display="true"' in html
    # The raw source survives the escaping passes — `y_1` must not become <em>.
    assert "x^2 + y_1" in html
    assert "<em>" not in html
    # Nothing is fetched during the synchronous render itself.
    assert out["scriptCount"] == 0


def test_deferred_math_schedules_a_katex_load(node_available):
    """Deferring is only safe if the follow-up actually fires.

    An earlier version scheduled this on requestAnimationFrame, which never runs
    in a headless browser and is throttled to a stop in a background tab — math
    then sat as plain source text until the tab was focused.
    """
    out = _run_node(
        """
        mod.mdToHtml('Inline $x^2$ here.');
        const duringRender = injected.scripts.length;
        await new Promise((r) => setTimeout(r, 0));
        emit({ duringRender, scriptSrcs: injected.scripts.map((s) => s.src) });
        """
    )
    assert out["duringRender"] == 0, "the synchronous render must not block on a fetch"
    assert out["scriptSrcs"] == [KATEX_SRC]


def test_entity_math_reaches_katex_as_characters_not_entities(node_available):
    """"$a &lt; b$" and "$a < b$" must typeset the same, with no parse error.

    mdToHtml escapes the source before the math pass, so a typed "<" arrives at
    the delimiters as "&lt;" and a typed "&lt;" arrives as "&amp;lt;". KaTeX
    has no entity syntax and treats the "&" as an alignment marker, so anything
    still spelled as an entity comes back as a red .katex-error instead of a
    formula. Both spellings have to be decoded to the character itself, in one
    pass — decoding "&amp;" first and "&lt;" after would let the second pass eat
    what the first produced, which is the double-unescape CodeQL flags.
    """
    out = _run_node(
        """
        const katex = loadRealKatex();
        globalThis.window.katex = katex;
        globalThis.katex = katex;
        emit({
          entity: mod.mdToHtml('Math: $a &lt; b$ done.'),
          typed: mod.mdToHtml('Math: $a < b$ done.'),
          ampersandEntity: mod.mdToHtml('Math: $x &gt; y$ done.'),
        });
        """
    )
    assert "katex-error" not in out["entity"]
    assert "katex-error" not in out["typed"]
    assert "katex-error" not in out["ampersandEntity"]
    # Same formula, same markup, whichever way the author spelled the operator.
    assert out["entity"] == out["typed"]
    assert 'class="katex"' in out["entity"]


def test_deferred_entity_math_banks_the_decoded_source(node_available):
    """The placeholder has to hold the same source the inline path would use.

    renderMath() feeds the span's textContent straight to KaTeX, so an entity
    left in the bank is a .katex-error that only appears on a cold page — the
    exact case the lazy load made common.
    """
    out = _run_node(
        """
        emit({
          entity: mod.mdToHtml('Math: $a &lt; b$ done.'),
          typed: mod.mdToHtml('Math: $a < b$ done.'),
        });
        """
    )
    assert f'class="{MATH_PENDING_CLASS}"' in out["entity"]
    assert out["entity"] == out["typed"]
    # Escaped once for transport, so the span's textContent is "a < b".
    assert "a &lt; b</span>" in out["entity"]


def test_detached_container_math_typesets_with_the_real_renderer(node_available):
    """The PDF export renders into a container it never attaches to the page.

    mdToHtml defers math to a document-scoped flush, which cannot reach a
    detached node, so the export has to typeset its own container before
    handing it to html2pdf. This is that container: pending spans in, real
    KaTeX markup out, no .katex-error and nothing left pending.
    """
    out = _run_node(
        """
        const katex = loadRealKatex();
        const html = mod.mdToHtml('Formula $E = mc^2$ here.');

        const el = makeEl('span');
        el.textContent = 'E = mc^2';
        el.getAttribute = (name) => (name === 'data-display' ? 'false' : null);
        let written = null;
        Object.defineProperty(el, 'outerHTML', { set(v) { written = v; } });
        const container = makeContainer({ '.__MATH_PENDING__': [el] });

        const pending = mod.renderMath(container);
        globalThis.window.katex = katex;
        injected.scripts[0].fire('load');
        injected.links[0].fire('load');
        await pending;

        emit({ html, written });
        """
    )
    # Cold page: mdToHtml could not typeset, so the export HTML starts pending.
    assert f'class="{MATH_PENDING_CLASS}"' in out["html"]
    # After the export's own render pass it is real KaTeX markup.
    assert 'class="katex"' in out["written"]
    assert "katex-error" not in out["written"]
    assert MATH_PENDING_CLASS not in out["written"]


def test_pdf_export_typesets_its_container_before_html2pdf():
    """Ordering in a call site, so pin the call site. No node needed."""
    source = (_REPO / "static/js/document.js").read_text(encoding="utf-8")
    match = re.search(r"\n  async function exportAsPdf\(\) \{(.*?)\n  \}\n", source, re.S)
    assert match, "exportAsPdf not found"
    body = match.group(1)

    render = "await markdownModule.renderMath(container);"
    assert render in body, "the export never typesets its detached container"
    assert body.index("container.innerHTML = html;") < body.index(render)
    assert body.index(render) < body.index("window.html2pdf()")


def test_md_to_html_renders_inline_once_katex_is_loaded(node_available):
    """After the first load mdToHtml goes back to typesetting synchronously."""
    out = _run_node(
        """
        globalThis.window.katex = {
          renderToString: (src, opts) => `<span class="katex" data-display="${!!(opts && opts.displayMode)}">${src}</span>`,
        };
        globalThis.katex = globalThis.window.katex;
        const html = mod.mdToHtml('Inline $x^2$ here.');
        emit({ html });
        """
    )
    assert '<span class="katex" data-display="false">x^2</span>' in out["html"]
    assert MATH_PENDING_CLASS not in out["html"]


def test_render_math_typesets_deferred_placeholders(node_available):
    out = _run_node(
        """
        const el = makeEl('span');
        el.textContent = 'x^2';
        el.getAttribute = (name) => (name === 'data-display' ? 'false' : null);
        let written = null;
        Object.defineProperty(el, 'outerHTML', { set(v) { written = v; } });

        const container = makeContainer({ '.__MATH_PENDING__': [el] });
        const pending = mod.renderMath(container);
        const scriptSrcs = injected.scripts.map((s) => s.src);

        globalThis.window.katex = {
          renderToString: (src, opts) => `<span class="katex" data-display="${!!(opts && opts.displayMode)}">${src}</span>`,
        };
        injected.scripts[0].fire('load');
        injected.links[0].fire('load');
        await pending;

        emit({ scriptSrcs, written });
        """
    )
    assert out["scriptSrcs"] == [KATEX_SRC]
    assert out["written"] == '<span class="katex" data-display="false">x^2</span>'


def test_render_math_does_not_fetch_without_placeholders(node_available):
    out = _run_node(
        """
        await mod.renderMath(makeContainer({}));
        emit({ scriptCount: injected.scripts.length, linkCount: injected.links.length });
        """
    )
    assert out["scriptCount"] == 0
    assert out["linkCount"] == 0


def test_vendored_assets_exist_and_index_html_has_no_cdn_reference():
    """Guards the offline/privacy half: no node needed, so it always runs."""
    for rel in (
        "static/lib/mermaid.min.js",
        "static/lib/katex/katex.min.js",
        "static/lib/katex/katex.min.css",
    ):
        path = _REPO / rel
        assert path.is_file(), f"{rel} is not vendored"
        assert path.stat().st_size > 1024, f"{rel} looks truncated"

    # KaTeX's stylesheet resolves fonts relative to itself; a missing font
    # degrades silently to fallback glyphs, so resolve every woff2 the vendored
    # CSS actually asks for. (.woff/.ttf are listed too but never requested by a
    # browser that supports woff2, which is what static/fonts/ already assumes.)
    css_dir = _REPO / "static/lib/katex"
    css = (css_dir / "katex.min.css").read_text(encoding="utf-8")
    wanted = sorted(set(re.findall(r"url\((fonts/KaTeX_[\w-]+\.woff2)\)", css)))
    assert len(wanted) == 20, f"expected 20 woff2 references in the CSS, found {len(wanted)}"
    missing = [ref for ref in wanted if not (css_dir / ref).is_file()]
    assert missing == [], f"KaTeX stylesheet references fonts that are not vendored: {missing}"

    # Everything the CSS needs must also survive an offline install: the font
    # names have to be in KATEX_FONTS and that array has to reach PRECACHE.
    sw = (_REPO / "static/sw.js").read_text(encoding="utf-8")
    assert "...KATEX_FONTS," in sw, "KATEX_FONTS is defined but never spread into PRECACHE"
    precached = {
        f"fonts/KaTeX_{name}.woff2"
        for name in re.findall(r"'([\w-]+)',", _katex_fonts_block(sw))
    }
    assert precached >= set(wanted), f"not precached: {sorted(set(wanted) - precached)}"

    # The shell must fetch no resource from a third party. Scoped to the tags
    # that actually load something — an <a href> to an external page is fine,
    # and the comment explaining the move can keep naming the CDN it left.
    index = (_REPO / "static/index.html").read_text(encoding="utf-8")
    remote_loads = re.findall(r"<(?:script|link)\b[^>]*\b(?:src|href)=\"https?://[^\"]+", index)
    assert remote_loads == [], f"index.html loads remote resources: {remote_loads}"

    sw = (_REPO / "static/sw.js").read_text(encoding="utf-8")
    assert KATEX_SRC in sw
    assert KATEX_CSS in sw


def test_ensure_mermaid_themes_from_the_palette_rather_than_a_pinned_literal(node_available):
    """`B872`. `markdown.js:94` was
    `initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'loose' })`
    — one theme for all sixteen palettes, four of which are light.

    Driven, not read (`Law 20`): the module is loaded for real and the object
    it hands `initialize` is captured. Two calls, and the second is the point —
    it carries the node outline read back out of the theme's own `lineColor`,
    because on a light panel `neutral`'s default `#999` outline measures
    2.23-2.46:1 and the node fill measures 1.00-1.10:1, so nothing would say
    where a box ends.
    """
    out = _run_node(
        """
        setScheme('light');
        const seen = [];
        const pending = mod.ensureMermaid();
        globalThis.window.mermaid = fakeMermaid(seen);
        injected.scripts[0].fire('load');
        await pending;
        emit({ seen });
        """
    )
    assert [c["theme"] for c in out["seen"]] == ["neutral", "neutral"], out["seen"]
    assert out["seen"][0].get("themeVariables") is None, out["seen"][0]
    assert out["seen"][1]["themeVariables"] == {"nodeBorder": "#666"}, out["seen"][1]
    assert out["seen"][1]["securityLevel"] == "loose", out["seen"][1]
    assert out["seen"][1]["startOnLoad"] is False, out["seen"][1]


def test_a_document_that_has_not_said_still_gets_the_shipped_default(node_available):
    """First paint, before any palette has been applied. `theme.js:35` ships
    `dark`, so a diagram drawn in that window has to come out dark rather than
    fall through to mermaid's own default, which is light."""
    out = _run_node(
        """
        setScheme(null);
        const seen = [];
        const pending = mod.ensureMermaid();
        globalThis.window.mermaid = fakeMermaid(seen);
        injected.scripts[0].fire('load');
        await pending;
        emit({ themes: seen.map((c) => c.theme) });
        """
    )
    assert out["themes"] == ["dark", "dark"], out["themes"]


def test_a_palette_switched_after_the_load_reaches_the_next_diagram(node_available):
    """The library is loaded and initialised once, and a person changes palette
    hours later. `renderMermaid` re-applies before it runs — but only when the
    scheme actually moved, so the steady state is no `initialize` at all."""
    out = _run_node(
        """
        setScheme('dark');
        const seen = [];
        const node = makeEl('pre');
        node.isConnected = true;
        const container = makeContainer({ 'pre.mermaid:not([data-processed])': [node] });

        const first = mod.renderMermaid(container);
        globalThis.window.mermaid = fakeMermaid(seen);
        injected.scripts[0].fire('load');
        await first;
        const afterLoad = seen.map((c) => c.theme);

        await mod.renderMermaid(container);
        const afterSameScheme = seen.map((c) => c.theme);

        setScheme('light');
        await mod.renderMermaid(container);
        emit({ afterLoad, afterSameScheme, afterSwitch: seen.map((c) => c.theme) });
        """
    )
    assert out["afterLoad"] == ["dark", "dark"], out["afterLoad"]
    # Same palette, second diagram: nothing re-initialises.
    assert out["afterSameScheme"] == out["afterLoad"], out["afterSameScheme"]
    assert out["afterSwitch"] == ["dark", "dark", "neutral", "neutral"], out["afterSwitch"]
