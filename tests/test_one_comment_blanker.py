# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B290` — one comment blanker, and nothing may grow a second one.

About twenty test files each carried their own copy of

    re.sub(r"/\*.*?\*/", "", src, flags=re.S)

and a `//` line substitution beside it. The first of those cannot tell a
comment from a string. `input.accept = 'image/*,video/*'` at
`static/js/gallery.js:1202` opens a "comment" that the next `*/` anywhere in
the file closes, and the substitution runs to it.

**Measured on this tree, 2026-09-16, for the five modules those censuses read**
— comparing the naive pair against `strip_comments`, line for line, with
whitespace preserved on both sides so the comparison is about content and not
about offsets:

    static/js/calendar.js   1,739 lines of live code blanked
    static/js/notes.js      1,718
    static/js/settings.js   1,112
    static/js/gallery.js    1,102
    static/js/document.js     971
                            ─────
                            6,642 lines invisible to every census built on it

and the defect runs the other way too: `static/index.html` has **274 lines of
comment that the naive forms leave standing**, so a census reading that file
was counting prose as code.

Over all of `static/js/**` the block substitution alone blanks **7,277 lines of
live code in 15 modules**. That is why `B83` closed on a false `Verify` — it
reported *"one play triangle, from one place"* while a play polygon at
`document.js:4986` and two stop squares at `notes.js:4517` and `:4586` sat
inside the blanked span, and counted the chevron at 45 when the tree held 54.

So there is one blanker — `strip_comments` in `.pantheon/check-specifiers.py`,
reached from the suite through `tests/helpers/source_text.py` — and this file
holds both halves of the fix: the behaviour the shared one must have, and a
rule that fails when a twenty-first copy appears.
"""
import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.source_text import blank, blank_text, mode_for

ROOT = Path(__file__).resolve().parent.parent


# ── the literals that broke the regex ────────────────────────────────────────


def test_a_string_containing_slash_star_does_not_open_a_comment():
    """The exact line from `static/js/gallery.js:1202`, and the code after it."""
    src = ("input.accept = 'image/*,video/*';\n"
           "const kept = 1;\n"
           "/* a real comment */\n"
           "const alsoKept = 2;\n")
    out = blank_text(src, "js")
    assert "input.accept = 'image/*,video/*';" in out
    assert "const kept = 1;" in out
    assert "const alsoKept = 2;" in out
    assert "a real comment" not in out


def test_a_regex_literal_holding_a_quote_does_not_open_a_string():
    """The other direction, and the one a string-only blanker gets wrong.

    `/["']/` is a pattern. A blanker that reads the `"` as opening a string
    stops blanking comments from there to the next `"` in the file, so a
    census reads commented-out code as live.
    """
    src = ('const q = /["\']/g;\n'
           '// this line is a comment\n'
           'const live = 3;\n')
    out = blank_text(src, "js")
    assert 'const q = /["\']/g;' in out
    assert "this line is a comment" not in out
    assert "const live = 3;" in out


def test_a_regex_containing_an_escaped_slash_ends_where_it_ends():
    src = "return /ab\\/c*/.test(s); /* gone */ const after = 4;\n"
    out = blank_text(src, "js")
    assert "/ab\\/c*/" in out and "gone" not in out and "const after = 4;" in out


def test_division_is_not_a_regex():
    src = "const half = (a + b) / 2; /* gone */ const after = 5;\n"
    out = blank_text(src, "js")
    assert "(a + b) / 2" in out and "gone" not in out and "const after = 5;" in out


def test_a_template_literal_keeps_its_body_and_blanks_inside_its_holes():
    src = "const t = `a ${ /* gone */ b } z`; const after = 6;\n"
    out = blank_text(src, "js")
    assert "`a ${" in out and "b } z`" in out
    assert "gone" not in out and "const after = 6;" in out


def test_two_slashes_in_a_css_url_are_not_a_comment():
    """`//` is a comment in JavaScript and is not one in CSS. Blanking from it
    eats the rest of `url(http://…)` and every declaration after it on the line.
    """
    src = "body { background: url(http://x/y.png); color: red; } /* gone */\n"
    out = blank_text(src, "css")
    assert "url(http://x/y.png)" in out and "color: red" in out
    assert "gone" not in out


def test_a_css_string_containing_a_comment_opener_is_not_a_comment():
    src = "p::after { content: '/*'; } .live { color: red }\n"
    out = blank_text(src, "css")
    assert "content: '/*';" in out and ".live { color: red }" in out


def test_an_apostrophe_in_html_prose_does_not_swallow_the_page():
    src = "<p>don't</p><!-- gone --><script src='a.js'></script>\n"
    out = blank_text(src, "html")
    assert "don't" in out and "gone" not in out and "src='a.js'" in out


def test_html_mode_reads_script_bodies_as_javascript():
    src = "<script>\n// gone\nimport('./x.js');\n</script>\n"
    out = blank_text(src, "html")
    assert "gone" not in out and "import('./x.js');" in out


def test_html_mode_can_be_told_to_leave_embedded_bodies_alone():
    """`tests/test_app_shell_csp_hashes.py` hashes those bytes for the CSP."""
    src = "<!-- gone --><script>\n// kept\nx = 1;\n</script>\n"
    out = blank_text(src, "html", embedded=False)
    assert "gone" not in out and "// kept" in out


def test_offsets_and_line_numbers_do_not_move():
    src = "a = 1;\n/* two\n   lines */\nb = 2;\n"
    out = blank_text(src, "js")
    assert len(out) == len(src)
    assert out.splitlines()[3] == "b = 2;"


def test_mode_is_chosen_from_the_file_name():
    assert mode_for("static/style.css") == "css"
    assert mode_for("static/index.html") == "html"
    assert mode_for("static/js/chat.js") == "js"
    assert mode_for("tests/harness/x.mjs") == "js"


# ── the tree, measured ───────────────────────────────────────────────────────


NAIVE_BLOCK = re.compile(r"/\*.*?\*/", re.S)


def _naive(text: str) -> str:
    """The copy this row removed, with whitespace preserved so the comparison
    below is about content rather than offsets — the copies in the tree mostly
    deleted instead, which is strictly worse."""
    return NAIVE_BLOCK.sub(
        lambda m: "".join("\n" if c == "\n" else " " for c in m.group(0)), text)


# `settings.js` 1000 -> 250 (2026-10-26): `B1193`'s token form and `B1196`'s
# shortcut layers moved which `/*`-bearing string opens the naive span; it still
# erases 267 lines of live code, which is the claim.
# `gallery.js` 1000 -> 900 (2026-10-26): `B1293` moved the editor's open
# sequence into the exported `openInEditor`; the naive span still erases 934
# lines of live code there.
@pytest.mark.parametrize("name,at_least", [
    ("calendar.js", 1500), ("notes.js", 1500), ("settings.js", 250),
    ("gallery.js", 900), ("document.js", 900),
])
def test_the_naive_form_really_does_blank_these_modules(name, at_least):
    """The measurement this row is about, re-run rather than quoted.

    Held as a floor rather than an exact figure: these modules are edited every
    wave and an exact count would be a second place the tree's size lives. If a
    number here ever falls to zero the naive form has become harmless for that
    module, and this parametrisation should lose the entry — with a note saying
    why, because that would mean the string literal that opens the span went.
    """
    path = ROOT / "static" / "js" / name
    good, bad = blank(path), _naive(path.read_text(encoding="utf-8"))
    erased = sum(1 for a, b in zip(good.splitlines(), bad.splitlines())
                 if a.strip() and not b.strip())
    assert erased >= at_least, (
        f"{name}: the naive blanker erases {erased} lines of live code, and this "
        f"row measured at least {at_least}")


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
@pytest.mark.parametrize("name", ["calendar.js", "notes.js", "settings.js",
                                  "gallery.js", "document.js"])
def test_the_blanked_module_is_still_javascript_and_the_naive_one_is_not(name, tmp_path):
    """Ground truth from a parser, not from a heuristic about what a line
    looks like. Blanking comments with spaces cannot make valid JavaScript
    invalid; eating 1,700 lines out of the middle of a file can, and does.

    **This is the assertion that fails on the tree as it stood before this
    row** (`Law 9`): the `naive` half is the substitution every census used,
    and `node --check` refuses its output for all five modules.
    """
    path = ROOT / "static" / "js" / name
    raw = path.read_text(encoding="utf-8")

    def parses(text: str) -> bool:
        f = tmp_path / "probe.mjs"
        f.write_text(text, encoding="utf-8")
        return subprocess.run(["node", "--check", str(f)],
                              capture_output=True, text=True).returncode == 0

    assert parses(raw), f"{name} does not parse before anything is blanked"
    assert parses(blank(path)), (
        f"{name}: the shared blanker produced source node will not parse — it "
        f"removed something that was not a comment")
    assert not parses(_naive(raw)), (
        f"{name}: the naive blanker's output still parses, so this module no "
        f"longer demonstrates the defect and the row's measurement has moved")


# ── nothing may grow a second one ────────────────────────────────────────────


# Files that still hold a copy, with the row that removes each. This list may
# only shrink: `test_the_allow_list_has_no_stale_entries` fails if an entry
# stops being true, so a fixed file cannot be left sitting here.
#
# `B410` emptied it: `check-attachment-language.py`, `check-fork-names.py` and
# `check-run-statuses.py` now blank through `ledger.source.strip_comments`,
# which loads the one in `check-specifiers.py`. Each checker's report was
# re-measured after the change and did not move (aliases 31 · prose 2 · names
# 179; 15 deliberate hits across 5 files; 138 status literals in 2,235 files).
STILL_COPIED: dict = {}

# `B415`. Not a copy of the defect — the one site that reads comments *as the
# answer* rather than blanking them to reach code.
#
# `check-licences.py:139` extracts **legal comments** from minified third-party
# bundles: `/*! … */` and blocks carrying `@license` or `@preserve`, which is
# exactly what Terser's `comments: "some"` keeps and therefore the only record
# of what a bundle contains. It never removes a comment to read the code around
# it, so `B290`'s failure mode — a string literal opening a comment that the
# next `*/` closes, erasing live code — cannot apply: there is no code being
# read. Blanking with the shared stripper would delete the input.
#
# This test found it, and finding it was right: the check asks "is there a
# hand-written comment regex here", and there is. What the check cannot see
# from a regex literal alone is which *direction* it runs. Recorded rather than
# silenced, with the residual risk named: a string literal containing `/*!
# @license Foo */` inside a bundle would be read as a notice for a package that
# is not there. That is a false *credit*, not erased code, and `B426` is the
# row for it.
READS_COMMENTS_AS_DATA = {
    ".pantheon/check-licences.py": "B415",
}

_COMMENT_PATTERN = re.compile(
    r"(?:/\\\*.*\\\*/)|(?://\.\*\$)|(?:<!--.*-->)")


def _naive_blankers(rel: str) -> list:
    """Every `re.*(<a comment pattern>, …)` call in one file, by line.

    Read with `ast`, not with a grep: this file and several of the census files
    *describe* the defect in their docstrings, and a text search would count the
    description as the thing described — which is `Law 20`, and the same trap
    that produced the row this test closes.
    """
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                and fn.value.id == "re"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        pattern = node.args[0].value
        if not isinstance(pattern, str):
            continue
        if _COMMENT_PATTERN.search(pattern):
            out.append((node.lineno, pattern))
    return out


def _tracked(*roots) -> list:
    out = subprocess.run(["git", "ls-files", *roots], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    return [f for f in out if f.endswith(".py")]


def test_no_new_naive_comment_blanker_appears():
    """The half of this row that stops it coming back a fourth time.

    `B87` fixed the checker, `B230` fixed one test file, `B310` was the same
    defect a third time. Each fix was correct and none of them stopped the next
    copy, because the copies are written from memory and a regex for
    `/* … */` looks obviously right. Anything that wants comments blanked
    imports `tests/helpers/source_text.py`.
    """
    offenders = []
    for rel in _tracked("tests", ".pantheon"):
        if (rel in STILL_COPIED or rel in READS_COMMENTS_AS_DATA
                or rel.endswith("test_one_comment_blanker.py")):
            continue
        for line, pattern in _naive_blankers(rel):
            offenders.append(f"{rel}:{line}  {pattern!r}")
    assert not offenders, (
        "a comment-blanking regex was written by hand:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse `from tests.helpers.source_text import blank, blank_text`. "
          "A regex cannot tell a comment from a string literal; see B290.")


def test_the_allow_list_has_no_stale_entries():
    """An allow-list that outlives its reason is a second place the tree's
    state lives. Each entry must still be true."""
    stale = [rel for rel in STILL_COPIED if not _naive_blankers(rel)]
    assert not stale, (
        f"{stale} no longer holds a hand-written comment blanker — delete the "
        f"entry from STILL_COPIED so the list stays a description of the tree.")
    # `B415`. The reads-as-data exemption is held to the same rule: it names a
    # real site or it goes. An exemption nobody can point at is how a suppression
    # outlives the thing it excused.
    gone = [rel for rel in READS_COMMENTS_AS_DATA if not _naive_blankers(rel)]
    assert not gone, (
        f"{gone} no longer reads comments as data — delete the entry from "
        f"READS_COMMENTS_AS_DATA.")


def test_the_scan_itself_is_not_a_tautology():
    """A rule that finds nothing because it looks at nothing is the failure mode
    of every census in this row. The allow-listed files must be *found*."""
    assert len(_tracked("tests", ".pantheon")) > 200
    for rel in list(STILL_COPIED) + list(READS_COMMENTS_AS_DATA):
        assert _naive_blankers(rel), f"{rel} was expected to hold one"


# ── the three checkers `B410` converted ──────────────────────────────────────


def _load_checker(name: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        f"_b410_{name.replace('-', '_')}", ROOT / ".pantheon" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: A module that defeats both naive rules: a `//` inside a string (the
#: unanchored rule blanks from it to the end of the line) and a `/*` inside a
#: string (the block rule runs from it to the next `*/` in the file).
_TRAP = ("const url = 'https://example.invalid/'; const keptAfterUrl = 1;\n"
         "input.accept = 'image/*,video/*';\n"
         "const alsoKept = 'kept-two';\n"
         "/* a real comment */ const after = 2;\n")


def test_check_fork_names_reads_the_code_a_string_used_to_hide():
    """`check-fork-names.py` carried the unanchored `//` rule as well as the
    block rule. Both identifiers below are code; the naive pair erased both."""
    mod = _load_checker("check-fork-names")
    code = mod._code_text("static/js/x.js", _TRAP)
    assert "keptAfterUrl" in code and "'kept-two'" in code, code
    assert "a real comment" not in code
    assert len(code) == len(_TRAP), "offsets moved, so reported lines would too"
    # HTML: a `<script>` body is JavaScript, and an HTML comment is blanked.
    html = "<!-- a gone note -->\n<script>\n" + _TRAP + "</script>\n"
    code = mod._code_text("static/x.html", html)
    assert "a gone note" not in code and "keptAfterUrl" in code and "'kept-two'" in code


def test_check_run_statuses_reads_the_code_a_string_used_to_hide():
    mod = _load_checker("check-run-statuses")
    code = mod._blank_comments(_TRAP)
    assert "keptAfterUrl" in code and "const alsoKept" in code, code
    assert "a real comment" not in code


def test_check_attachment_language_reads_its_table_through_the_one_blanker(monkeypatch, tmp_path):
    """`editor_languages()` reads `EDITOR_LANGUAGE` out of the JS. Driven over
    a module whose comment-looking string sits above the table: the naive
    block rule ran from `'*/*'`'s `/*` to the real comment's `*/` and the
    table's first entry went with it."""
    mod = _load_checker("check-attachment-language")
    js = tmp_path / "attachmentLanguage.js"
    js.write_text("const ACCEPT = 'text/*';\n"
                  "const EDITOR_LANGUAGE = {\n"
                  "  py: 'python', /* a note */\n"
                  "  js: 'javascript', // http://example.invalid\n"
                  "};\n", encoding="utf-8")
    monkeypatch.setattr(mod, "JS", js)
    assert mod.editor_languages() == {"py": "python", "js": "javascript"}


# ── `B1515`: a hand-written SCANNER is a copy too ───────────────────────────


#: The one walk that may compare against `//` and `/*` itself.
THE_BLANKER = ".pantheon/check-specifiers.py"


def _hand_scanners(rel: str) -> list:
    """Every function in one file that walks text for comment openers itself:
    both `"//"` and `"/*"` compared against (`==`, `in`) or searched for
    (`.startswith`, `.find`, `.index`).

    `B1515`. `_naive_blankers` asks about regexes, and `check-wiring.py`'s
    `code_only` was a character scanner — the second blanker `B410` was meant to
    have removed, invisible to the rule that exists to find it. Read with `ast`
    for the reason `_naive_blankers` is: the files describing the defect quote
    both openers in prose."""
    return _scanners_in((ROOT / rel).read_text(encoding="utf-8"))


def _scanners_in(source: str) -> list:
    out = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        seen = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Compare):
                for side in (node.left, *node.comparators):
                    if isinstance(side, ast.Constant) and isinstance(side.value, str):
                        seen.add(side.value)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr in ("startswith", "find", "index")):
                seen |= {a.value for a in node.args
                         if isinstance(a, ast.Constant) and isinstance(a.value, str)}
        if "//" in seen and "/*" in seen:
            out.append((fn.lineno, fn.name))
    return out


def test_no_hand_written_comment_scanner_appears():
    offenders = []
    for rel in _tracked("tests", ".pantheon"):
        if (rel == THE_BLANKER or rel in READS_COMMENTS_AS_DATA
                or rel.endswith("test_one_comment_blanker.py")):   # the rule itself
            continue
        for line, name in _hand_scanners(rel):
            offenders.append(f"{rel}:{line}  {name}()")
    assert not offenders, (
        "a comment scanner was written by hand:\n  " + "\n  ".join(offenders)
        + "\n\nBlank through `ledger.source.strip_comments` (a checker) or "
          "`tests/helpers/source_text.py` (a test) — see B290, B1515.")


def test_the_scanner_rule_finds_the_one_blanker_and_the_copy_it_replaced(tmp_path):
    """Not a tautology: the walk this file allows is found, and so is the shape
    `check-wiring.py` carried until `B1515`."""
    assert [name for _l, name in _hand_scanners(THE_BLANKER)] == ["strip_comments"]
    copy = ("def code_only(text):\n"
            "    i = 0\n"
            "    while i < len(text):\n"
            "        two = text[i:i + 2]\n"
            "        if two == '//':\n"
            "            i = text.find('\\n', i)\n"
            "        elif two == '/*':\n"
            "            i = text.find('*/', i)\n"
            "        i += 1\n")
    assert _scanners_in(copy) == [(1, "code_only")]


def test_check_wiring_reads_a_template_nested_in_a_hole_as_one_literal():
    """`B1515`'s defect in `check-wiring.py`'s own brace matcher: it scanned a
    template to the next backtick, so a template inside a `${…}` hole ended the
    outer one early and the `}` in the hole's text closed the collection — the
    ids after it were never read. Through the one walk's `literals` the
    collection is read whole."""
    mod = _load_checker("check-wiring")
    js = ("const PANES = {\n"
          "  head: `<b>${ok ? `a ${'}'} b` : ''}</b>`,\n"
          "  first: 'pane-first-id',\n"
          "  second: 'pane-second-id',\n"
          "};\n"
          "PANES.forEach((id) => el(id));\n")
    ids = mod.collection_ids(mod.code_only(js))
    assert ids == {"PANES": {"pane-first-id", "pane-second-id"}}, ids
    assert "strip_comments" in mod.code_only.__code__.co_names, \
        "check-wiring blanks through the one blanker"
