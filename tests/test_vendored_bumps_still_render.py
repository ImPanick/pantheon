# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B335` — the three user-visible paths through the libraries this wave bumped.

On 2026-09-17 KaTeX went 0.16.22 -> 0.18.7 (two semver-breaking 0.x minors),
Mermaid 11.16.1 -> 11.17.2 and Swagger UI 5.32.15 -> 5.33.0. None of the three
was for an advisory: OSV returns zero for every one of them at both the old and
the new version. They are currency, which makes `Law 1` the binding constraint —
**a bump that breaks a working feature is worse than being behind** — and a
currency bump with no feature test behind it is a change nobody measured.

So these tests do not check that a file changed. They run the shipped bundles
through the arguments the application actually passes, lifted out of
`static/js/markdown.js` rather than restated here (`Law 13`), and they assert on
what came back.

Three of them are differentials — an input the OLD bundle got wrong — which is
what makes this evidence rather than a green light (`Law 9`). Each is marked
with the version it fails on, measured by checking the previous bundle back out
and re-running the same harness.

**What is NOT covered, stated rather than implied.** Mermaid's `run()` and
`render()` rasterise through d3 and need a real SVG tree with `getBBox`; this
harness reaches `initialize()` and `parse()` and stops there. Swagger UI is a
React application and only its exported surface is reachable off a browser.
Those bounds are the reason `B423` files Mermaid 12.0.0 instead of taking it:
12.0.0's headline change is that ELK replaces dagre as the default layout for
seven diagram types, which is precisely the thing this file cannot see.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "harness"

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")


def run_harness(script: str, *args, timeout: int = 180) -> dict:
    """Run a harness and parse its one line of JSON."""
    entry = HARNESS / script
    assert entry.is_file(), f"missing harness {entry}"
    proc = subprocess.run(
        ["node", str(entry), *args], cwd=ROOT,
        capture_output=True, text=True, timeout=timeout,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    assert lines, (
        f"{script} printed no JSON.\nexit={proc.returncode}\n"
        f"stdout tail: {proc.stdout[-600:]}\nstderr tail: {proc.stderr[-600:]}"
    )
    return json.loads(lines[-1])


# ── KaTeX: math in a chat message ──────────────────────────────────────────

@pytest.fixture(scope="module")
def katex():
    return run_harness("katex_math_render.js")


def test_katex_still_typesets(katex):
    """The feature. `markdown.js:804` turns `$...$` in a message into KaTeX's
    HTML, and `static/style.css` hangs two rules off `.katex` and
    `.katex-display`.

    KaTeX 0.18.0's breaking change is a CSS class rename — `base` ->
    `katex-base`, `strut` -> `katex-strut` — and its release notes say outright
    that anyone targeting the internal classes must update their selectors.
    Pantheon targets neither; it targets the two below, which are the ones an
    application is supposed to use. Asserting them is what makes that reading a
    measurement.
    """
    assert katex["ok"], katex
    assert katex["version"] == "0.18.7", katex
    simple = katex["render"]["simple"]
    assert simple["katex"] and not simple["error"], simple
    assert katex["render"]["display"]["display"], katex["render"]["display"]
    assert not katex["render"]["aligned"]["error"], katex["render"]["aligned"]


def test_the_katex_options_come_from_the_one_call_site(katex):
    """`Law 13`. The flags this file feeds KaTeX are read out of `markdown.js`,
    so the two cannot drift; asserting their values here is what makes the
    reading visible to somebody changing them.

    `throwOnError: false` is the load-bearing one. Math in a chat message is
    written by a model or pasted by somebody else, so an unparseable formula is
    an ordinary event. With the flag, it comes back as an error span inside the
    message. Without it, `renderToString` throws inside `mdToHtml` and the whole
    message fails to render.
    """
    assert katex["callSiteOptions"]["throwOnError"] is False, katex
    assert "displayMode" in katex["callSiteOptions"], katex


def test_a_formula_katex_cannot_parse_comes_back_as_an_error_span(katex):
    """The behaviour `throwOnError: false` buys, driven rather than read."""
    broken = katex["render"]["broken"]
    assert "threw" not in broken, (
        "an unparseable formula threw instead of returning an error span — "
        f"that takes the whole message down with it: {broken}"
    )
    assert broken["error"], broken


def test_katex_renders_a_braced_delimiter_argument(katex):
    """`B335`'s differential. **Fails on KaTeX 0.16.22**, the version shipped
    until 2026-09-17.

    `\\bigl{(} x \\bigr{)}` is valid LaTeX — braces around a delimiter argument
    are how you write one that TeX would otherwise read as part of the macro —
    and 0.16.22 answers it with a red `.katex-error` reading *"Invalid delimiter
    type 'ordgroup'"*. KaTeX 0.16.47/0.18.3 (#4255) accepts it.

    Measured by checking the 0.16.22 bundle back out and running this same
    harness: `bracedDelimiter` comes back `error: true` there and `error: false`
    here. It is a formula somebody writes and the renderer refuses, which is a
    user-visible break in the direction that matters — the message still
    renders, so nobody gets an error report, they just get a red box.
    """
    braced = katex["render"]["bracedDelimiter"]
    assert "threw" not in braced, braced
    assert not braced["error"], (
        "\\bigl{(} x \\bigr{)} rendered as a .katex-error — that is KaTeX "
        f"0.16.22's answer: {braced}"
    )


def test_katex_renders_sout_in_text_mode(katex):
    """`B335`'s second differential. **Fails on KaTeX 0.16.22.**

    `\\text{\\sout{x}}` — strike-through inside text mode — is `ulem`'s and
    LaTeX takes it. 0.16.22 returns a `.katex-error`; 0.16.41 (#4173) fixed it.
    Same shape as the one above: valid input, red box, no error anywhere a
    developer would see it.
    """
    sout = katex["render"]["soutInText"]
    assert "threw" not in sout, sout
    assert not sout["error"], (
        "\\text{\\sout{x}} rendered as a .katex-error — that is KaTeX "
        f"0.16.22's answer: {sout}"
    )


# ── Mermaid: a diagram in a chat message ───────────────────────────────────

@pytest.fixture(scope="module")
def mermaid():
    return run_harness("mermaid_diagram_parse.js")


def test_mermaid_still_loads_and_publishes_its_api(mermaid):
    """The feature's first step. `markdown.js:90` injects the bundle as a
    `<script>` and then checks `window.mermaid`; `markdown.js:1002` calls
    `mermaid.run({ nodes })`.

    The harness evaluates the file the way a `<script>` tag does rather than
    with `require`, because mermaid's bundle publishes itself off a top-level
    `var` — under `require` that is module-local and the last line of the file
    throws. A bundle that stopped publishing `window.mermaid` would be a chat
    where every diagram stays a `<pre>` forever.
    """
    assert mermaid["ok"], mermaid
    assert mermaid["api"]["initialize"] == "function", mermaid["api"]
    assert mermaid["api"]["run"] == "function", mermaid["api"]
    assert mermaid["api"]["parse"] == "function", mermaid["api"]


def test_the_mermaid_config_is_understood_and_not_merely_stored(mermaid):
    """`Law 13` plus the `B334` trick: read the option back.

    The config is produced by the module that produces it —
    `markdown/mermaidTheme.js:applyMermaidTheme`, the function `ensureMermaid`
    calls — and then `mermaidAPI.getConfig()` is asked what mermaid did with
    it. The keys coming back unchanged is what proves they were honoured; a key
    a major quietly stopped reading comes back as its default instead of as an
    error.

    `B872` changed the shape of `callSiteConfig` here: it was
    `{startOnLoad, theme: 'dark', securityLevel}` and the theme name was
    written into `markdown.js`, which is the bug that row fixed. It is now the
    dark scheme's computed config, and it carries a `themeVariables.nodeBorder`
    read back out of mermaid's own answer for that theme. The per-palette
    legibility claim is asserted where it belongs, in
    `tests/test_every_palette_gets_a_legible_diagram_js.py`; this file's job is
    still whether the vendored bundle honours what it is handed.

    `layout` and `look` are asserted too, and neither is set by Pantheon. They
    are mermaid's own defaults, and they are here because **Mermaid 12.0.0
    changes them** — `layout` becomes `elk` for seven diagram types and the
    default look moves to `neo`, which the release notes describe as "this
    changes how existing diagrams look". This assertion is what turns that from
    a changelog sentence into something this repository measures, and it is the
    evidence behind `B423`.
    """
    assert mermaid["callSiteConfig"]["startOnLoad"] is False, mermaid["callSiteConfig"]
    assert mermaid["callSiteConfig"]["theme"] == "dark", mermaid["callSiteConfig"]
    assert mermaid["callSiteConfig"]["securityLevel"] == "loose", mermaid["callSiteConfig"]
    # The stroke override is not decoration: the node outline is the only thing
    # that says where a box is (`mainBkg` measures 1.00-1.10:1 against the
    # panel), and `strokeOverrides` sets it to the theme's own `lineColor`.
    assert mermaid["callSiteConfig"]["themeVariables"]["nodeBorder"] == (
        mermaid["schemes"]["dark"]["ink"]["lineColor"]
    ), mermaid["callSiteConfig"]
    cfg = mermaid["config"]
    assert cfg["theme"] == "dark", cfg
    assert cfg["securityLevel"] == "loose", cfg
    assert cfg["startOnLoad"] is False, cfg
    assert cfg["layout"] == "dagre", (
        "mermaid's default layout is no longer dagre. Mermaid 12.0.0 makes it "
        "elk, which re-lays-out every flowchart, state, class, ER, requirement, "
        "use-case and agentflow diagram already in somebody's chat history. "
        f"See B423 before taking this: {cfg}"
    )
    assert cfg["look"] == "classic", cfg


def test_mermaid_parses_the_diagram_kinds_a_message_can_contain(mermaid):
    """The grammars, driven. A diagram type that stopped parsing renders as an
    error box in the middle of a conversation."""
    assert mermaid["parse"]["flowchart"]["diagramType"] == "flowchart-v2", mermaid["parse"]
    assert mermaid["parse"]["sequence"]["ok"], mermaid["parse"]["sequence"]
    assert mermaid["parse"]["er"]["ok"], mermaid["parse"]["er"]


def test_mermaid_rejects_a_diagram_it_cannot_parse(mermaid):
    """The other half. `markdown.js` relies on a rejected promise here — a
    parser that started accepting nonsense would render an empty diagram."""
    assert mermaid["parse"]["broken"]["ok"] is False, mermaid["parse"]["broken"]


def test_mermaid_knows_the_shapes_added_in_11_17(mermaid):
    """`B335`'s differential. **Fails on Mermaid 11.16.1**, the version shipped
    until 2026-09-17.

    `A@{ shape: person }` and the `folder` and `browser` shapes arrived in
    11.17.0. On 11.16.1 `mermaid.parse` rejects each of them with
    *"No such shape: person."* — measured by checking the 11.16.1 bundle back
    out and running this same harness — so a diagram written against current
    mermaid documentation fails in the chat with a parse error.

    This is a deliberately modest differential and it is the honest one. The
    reason to take 11.17.2 is the pile behind it: 11.17.0 fixes a
    `RangeError: Invalid array length` crash on certain edges, and 11.17.2
    restores the `edgePaths` class that the flowchart, block and journey
    stylesheets hang off. Neither is reachable from a shim, and asserting a
    parse result that is true is better than asserting a render that is not.
    """
    for shape in ("personShape", "folderShape", "browserShape"):
        got = mermaid["parse"][shape]
        assert got["ok"], (
            f"mermaid refused {shape} — that is 11.16.1's answer "
            f"('No such shape'): {got}"
        )
        assert got["diagramType"] == "flowchart-v2", got


# ── Swagger UI: the API browser at /docs ───────────────────────────────────

@pytest.fixture(scope="module")
def swagger():
    return run_harness("swagger_ui_bundle.js")


def test_the_swagger_bundle_still_publishes_what_the_docs_page_calls(swagger):
    """`app.py:1120` points FastAPI's generated `/docs` page at the vendored
    bundle rather than at `cdn.jsdelivr.net` (`B212`). That page calls
    `SwaggerUIBundle({...presets: [SwaggerUIBundle.presets.apis, ...]})`, and a
    bump that moved either symbol turns `/docs` into a blank page with a console
    error — which nobody is watching, because nobody reloads `/docs` after a
    dependency bump.
    """
    assert swagger["ok"], swagger
    assert swagger["bundle"] == "function", swagger
    assert swagger["apisPreset"], swagger
    assert "apis" in (swagger["presets"] or []), swagger


def test_the_standalone_preset_is_still_absent_on_purpose(swagger):
    """Not a regression — a recorded decision, asserted so it stays one.

    `scripts/fetch-swagger-ui.py` ships two files out of a package that unpacks
    to 11.7 MB, and `swagger-ui-standalone-preset.js` is deliberately not among
    them. FastAPI's generated HTML names `SwaggerUIBundle.SwaggerUIStandalonePreset`
    anyway, and it is `undefined` against upstream's own jsDelivr copy too.
    Vendoring did not narrow what worked. If this ever becomes defined, somebody
    added a 1.4 MB file and should say why.
    """
    assert swagger["standalonePreset"] == "undefined", swagger
