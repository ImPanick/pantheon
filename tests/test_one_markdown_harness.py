# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B882` — one loader for `markdown.js`, and it resolves imports it has never heard of.

Four test files each read `static/js/markdown.js`, stripped and inlined the
same five imports, base64'd the result into a `data:` URL and `import()`ed it.
Three were Python and the fourth, `tests/streaming/markdownHarness.mjs`, runs
under node's own test runner — which is why the count was three until the full
suite ran.

**The measured cost.** `B872` added ONE import line to `markdown.js`. Fourteen
tests went red across two files that have nothing to do with Mermaid, each
needing the same thirteen lines pasted in again, and the `.mjs` copy was missed
entirely: the whole streaming suite — 120 cases — failed at import with
`ERR_UNSUPPORTED_RESOLVE_REQUEST: Failed to resolve module specifier
"./markdown/mermaidTheme.js" from "data:text/javascript;base64,…"`. That file's
comments already recorded the same sentence twice, under `B250` and `P5-06`,
each time fixed by pasting in one more inline. Five inlines, four copies.

**What changed.** The old inlines were a *list*: five specifiers, five regexes,
five hand-written `export`-strippings, in four places. `tests/helpers/
markdownHarness.mjs` reads `markdown.js`'s import statements instead of naming
them, resolves each to the file it points at and inlines that file's real
source, recursively. A sixth import needs no edit. The test below proves that
by making one: a copy of `markdown.js` with an import of a module that has
never existed, loaded, called, and asked for the new module's value.

**Both callers reach one implementation.** The `.mjs` tests `import` it.
The Python tests run `node --input-type=module -e`, where a relative specifier
has no base to resolve from — the same error class the copies existed to dodge
— so `tests/helpers/markdown_harness.py` hands them an absolute `file://` URL.
One implementation, two spellings of the same `import`; no Python transcription
of a JavaScript job.

**And the escaper came with it.** `markdown.js` does `var escapeHtml =
uiModule.esc;`, and all four copies replaced that line with their own inlined
five-character escaper — copies eight, nine and ten of the thing `B874` is
about. `ui.js` still cannot be imported here, but since `B866` the escaper is
not in `ui.js`: it is `static/js/util/escapeHtml.js`, which imports nothing. The
harness builds `uiModule` out of that file, so the renderer under test escapes
with the function the browser uses and the three inlines are gone.
"""
import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.helpers.markdown_harness import HARNESS_MJS, harness_import

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_JS = ROOT / "static" / "js" / "markdown.js"
STREAMING_HARNESS = ROOT / "tests" / "streaming" / "markdownHarness.mjs"

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")


def _node(script: str, *args: str, cwd: Path = None):
    done = subprocess.run(["node", "--input-type=module", "-e",
                           textwrap.dedent(script), *args],
                          cwd=str(cwd or ROOT), capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# ── the loader loads the real renderer ──────────────────────────────────────


def test_the_harness_loads_the_renderer_and_it_renders():
    out = _node(harness_import("importMarkdown", "installMarkdownDom") + """
        installMarkdownDom();
        const mod = await importMarkdown();
        console.log(JSON.stringify({
          html: mod.mdToHtml('a **b** and `c`'),
          exports: Object.keys(mod).length,
        }));
    """)
    assert "<strong>b</strong>" in out["html"]
    assert "<code" in out["html"]
    assert out["exports"] > 10, "this is the module, not a stub of it"


def test_the_renderer_escapes_with_the_shipped_escaper():
    """`B874`, reached through `B882`. The four copies each replaced
    `var escapeHtml = uiModule.esc;` with their own five-character escaper.
    `uiModule` is now built from `static/js/util/escapeHtml.js`, so this is the
    browser's own function — including `'` → `&#39;`, which is the character
    `B611` was about and which a four-character copy would have dropped."""
    out = _node(harness_import("importMarkdown", "installMarkdownDom") + """
        installMarkdownDom();
        const mod = await importMarkdown();
        console.log(JSON.stringify({ html: mod.mdToHtml('`x\\' onerror=1 y=\"z`') }));
    """)
    assert "&#39;" in out["html"], out["html"]
    assert "&quot;" in out["html"], out["html"]


# ── the row's Verify: a new import needs no edit anywhere ───────────────────


def _farm(tmp_path: Path, extra_import: str, extra_module: str) -> Path:
    """A copy of `markdown.js` with one import the tree has never had.

    Its siblings are symlinked rather than copied, so the copy resolves the
    five real imports to the five real modules and the sixth to a file that
    exists only here. `static/js/markdown.js` itself is not touched — another
    agent is in it, and a test that has to edit the product to prove a point
    about the suite is not a test anybody can run twice.
    """
    farm = tmp_path / "farm"
    farm.mkdir()
    for entry in ("markdown", "emojiShortcodes.js", "icons.js", "langIcons.js",
                  "util"):
        os.symlink(ROOT / "static" / "js" / entry, farm / entry)
    (farm / "sixthThing.js").write_text(extra_module, encoding="utf-8")
    src = MARKDOWN_JS.read_text(encoding="utf-8")
    at = src.index("\nimport { splitTableRow }")
    (farm / "markdown.js").write_text(src[:at] + "\n" + extra_import + src[at:],
                                      encoding="utf-8")
    return farm / "markdown.js"


def test_a_sixth_import_needs_no_edit_to_any_test_file(tmp_path):
    """The row's `Verify`, executed.

    A copy of the renderer gains `import { sixthThing } from './sixthThing.js';`
    — a module that has never existed — and a call to it. The harness is not
    told about it, no file under `tests/` mentions it, and the renderer loads
    and answers. Under the four copies this was the moment fourteen tests went
    red and a fifth file went unnoticed.
    """
    entry = _farm(
        tmp_path,
        "import { sixthThing } from './sixthThing.js';",
        "export const sixthThing = () => 'the sixth module answered';\n"
        "export default { sixthThing };\n",
    )
    out = _node(harness_import("importMarkdown", "installMarkdownDom") + """
        installMarkdownDom();
        const mod = await importMarkdown(process.argv[1]);
        console.log(JSON.stringify({
          html: mod.mdToHtml('still **works**'),
          exports: Object.keys(mod).length,
        }));
    """, str(entry))
    assert "<strong>works</strong>" in out["html"]
    assert out["exports"] > 10

    # and the new module's own value is in scope inside the bundle
    bundled = _node(harness_import("bundle") + """
        console.log(JSON.stringify({ src: bundle(process.argv[1]) }));
    """, str(entry))["src"]
    assert "the sixth module answered" in bundled
    assert "./sixthThing.js" not in bundled, "the import was resolved, not kept"


def test_the_new_import_is_not_named_anywhere_in_the_suite():
    """The other half of "needs no edit": the proof above would be worthless if
    the harness had a list with `sixthThing.js` on it."""
    hits = subprocess.run(["git", "grep", "-l", "sixthThing"], cwd=ROOT,
                          capture_output=True, text=True).stdout.split()
    assert hits == ["tests/test_one_markdown_harness.py"], hits


def test_a_nested_import_is_resolved_too(tmp_path):
    """Recursive, not one level. An inlined module that imports a module of its
    own is the next shape of this row, and it does not need a sixth paste."""
    farm = tmp_path / "nested"
    farm.mkdir()
    for entry in ("markdown", "emojiShortcodes.js", "icons.js", "langIcons.js",
                  "util"):
        os.symlink(ROOT / "static" / "js" / entry, farm / entry)
    (farm / "leaf.js").write_text("export const leafValue = 'leaf reached';\n",
                                  encoding="utf-8")
    (farm / "branch.js").write_text(
        "import { leafValue } from './leaf.js';\n"
        "export const branchValue = () => leafValue;\n", encoding="utf-8")
    src = MARKDOWN_JS.read_text(encoding="utf-8")
    at = src.index("\nimport { splitTableRow }")
    (farm / "markdown.js").write_text(
        src[:at] + "\nimport { branchValue } from './branch.js';" + src[at:],
        encoding="utf-8")
    bundled = _node(harness_import("bundle") + """
        console.log(JSON.stringify({ src: bundle(process.argv[1]) }));
    """, str(farm / "markdown.js"))["src"]
    assert "leaf reached" in bundled
    assert "./leaf.js" not in bundled and "./branch.js" not in bundled


# ── both spellings reach one implementation ─────────────────────────────────


def test_the_mjs_caller_and_the_python_caller_get_the_same_bytes():
    """The part of this row that is not a refactor. `tests/streaming/*.test.mjs`
    imports the harness by relative path; the Python tests import it by
    `file://` URL because `node -e` has no base to resolve against. Same file,
    same bundle, byte for byte."""
    from_python = _node(harness_import("bundle") + """
        console.log(JSON.stringify({ n: bundle().length }));
    """)["n"]
    from_mjs = _node("""
        import { loadMarkdown } from './tests/streaming/markdownHarness.mjs';
        import { bundle } from './tests/helpers/markdownHarness.mjs';
        console.log(JSON.stringify({ n: bundle().length, load: typeof loadMarkdown }));
    """)
    assert from_mjs["load"] == "function", "the streaming name still resolves"
    assert from_python == from_mjs["n"]


def test_the_streaming_harness_still_answers_to_its_old_names():
    """`Law 1`. The streaming tests import `loadMarkdown` and `normalizeRender`
    from `tests/streaming/markdownHarness.mjs` and still do."""
    out = _node("""
        import { loadMarkdown, normalizeRender } from './tests/streaming/markdownHarness.mjs';
        const mod = await loadMarkdown();
        console.log(JSON.stringify({
          html: normalizeRender(mod.mdToHtml('# h\\n\\ntext')),
        }));
    """)
    assert "<h1" in out["html"] and "<p>text</p>" in out["html"]


# ── no fifth copy grows ─────────────────────────────────────────────────────


def _tracked(*roots) -> list:
    out = subprocess.run(["git", "ls-files", *roots], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    return [f for f in out if f.endswith((".py", ".mjs", ".js"))]


#: The specifier only a copy of this loader writes down. `markdown.js` imports
#: `./emojiShortcodes.js`; nothing else in the tree does, and a test file that
#: names it is rewriting `markdown.js`'s imports by hand.
_INLINED_SPECIFIER = "./emojiShortcodes.js"


def test_no_test_file_rewrites_markdown_js_imports_for_itself():
    """The half of this row that stops the fifth copy.

    Anything that wants the renderer under node imports
    `tests/helpers/markdownHarness.mjs`, or, from Python,
    `tests/helpers/markdown_harness.py`. Rewriting `markdown.js`'s imports by
    hand is how the fourth copy came to be broken for a day without anybody
    seeing it — and how it came to carry the eighth copy of `B874`'s escaper.

    The tell is the specifier: `./emojiShortcodes.js` appears in `markdown.js`
    and in a copy of this loader, and nowhere else in the tree. Two files under
    `tests/harness/` do read `markdown.js` and are *not* loaders — they lift the
    KaTeX options literal and the Mermaid config out of it, which their own
    comments justify as `Law 13` — so the rule is about the rewrite, not about
    the read.
    """
    offenders = [rel for rel in _tracked("tests")
                 if rel != "tests/helpers/markdownHarness.mjs"
                 and rel != "tests/test_one_markdown_harness.py"
                 and _INLINED_SPECIFIER in
                 (ROOT / rel).read_text(encoding="utf-8", errors="replace")]
    assert not offenders, (
        "a second `markdown.js` loader appeared in:\n  " + "\n  ".join(offenders)
        + "\n\nImport tests/helpers/markdownHarness.mjs. Four copies of this "
          "trick cost fourteen red tests and one silently broken suite; see B882.")


def test_the_data_url_trick_lives_in_one_place():
    """The `data:` URL is the mechanism, and the row is about how many places
    it is written in."""
    holders = [rel for rel in _tracked("tests")
               if rel != "tests/test_one_markdown_harness.py"
               and "data:text/javascript;base64" in
               (ROOT / rel).read_text(encoding="utf-8", errors="replace")]
    assert holders == ["tests/helpers/markdownHarness.mjs",
                       "tests/streaming/markdownHarness.mjs"], holders
    # and the second one only mentions it in the comment that records the row
    streaming = STREAMING_HARNESS.read_text(encoding="utf-8")
    code = "\n".join(line for line in streaming.splitlines()
                     if not line.lstrip().startswith("//"))
    assert "base64" not in code, code


def test_the_scan_is_not_a_tautology():
    assert len(_tracked("tests")) > 200
    assert HARNESS_MJS.exists()
    assert "importStatements" in HARNESS_MJS.read_text(encoding="utf-8")
