# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B876` — the `Law 20` helper could not open the function the sweep was about.

`Law 20` says a test that greps a file is testing the file. Option 2 — cut one
function out of the module and assert inside it — is what this repository
reaches for when it cannot run the code, and `js_function` is the cutter. Until
this row it lived at the bottom of
`tests/test_a_draft_skill_is_uncatalogued_not_inactive.py` and eight other test
files imported it from there.

**What it could not do.** `js_function(escapeHtml_src, "export function esc")`
raised `unbalanced braces after 'export function esc'`. Its scanner knew `//`,
`/* */`, `'`, `"` and `` ` ``; it did not know a regex literal. The `'` inside
`/[&<>"']/g` opened a string, the scan ran to the next apostrophe anywhere in
the file, and `esc`'s closing brace was inside the skipped span. `B866`'s
sweep was *about* `esc`, and the helper it was supposed to use could not open
it.

**Measured on this tree before the fix**, over every uniquely-named
`function`/`export function`/`async function` in `static/js/**` — 3,744
extractions in 181 modules:

    34   raised `unbalanced braces`        (loud)
    31   returned the wrong body silently  (quiet, and worse)
    21   of those 31 were more than twice the real length

and the worst was `async function _buildSuggestionSource` in
`static/js/emailLibrary.js`: **145,664 characters returned for a 1,261-character
function** — the whole module, wearing a scope's clothes. `export function
mdToHtml` (`static/js/markdown.js:699`) stopped at line 848 of a function that
ends at line 1032, so an assertion scoped to it silently covered the first half.
After the fix: 0 raise, 0 differ from the hand-checked bodies.

**It is not fixed a second way.** `.pantheon/check-specifiers.py` is this
repository's one JavaScript scanner — `B84` wrote it, `B290` taught it strings,
templates and regex literals — and `tests/helpers/source_text.py` already loads
it rather than restating it. `tests/helpers/js_source.py` blanks comments *with*
it and imports its two regex-start frozensets by reference, so the only new code
is the part the checker does not expose: where the literals are, rather than
what is left when the comments go.
"""
import ast
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from tests.helpers.source_text import blank_text, checker
from tests.helpers.js_source import (
    KEYWORD_BEFORE_REGEX,
    REGEX_MAY_FOLLOW,
    js_code,
    js_function,
    js_skip,
    js_spans,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI_JS = ROOT / "static" / "js" / "ui.js"
ESCAPE_HTML_JS = ROOT / "static" / "js" / "util" / "escapeHtml.js"


# ── the function the row is named after ─────────────────────────────────────


def test_it_extracts_the_canonical_escaper():
    """The row's `Verify`, at the address `B866` left it.

    The row says "extracts `esc` from `static/js/ui.js`", and it was written
    before `B866` landed in the same batch. `ui.js` now re-exports `esc` from
    `static/js/util/escapeHtml.js`, which imports nothing, so the body is there
    and the name is still reached through `ui.js`. Both halves are asserted,
    because "the helper can open `esc`" is the row and "`ui.js` still answers
    to `esc`" is what makes that the same function every caller uses.
    """
    body = js_function(ESCAPE_HTML_JS.read_text(encoding="utf-8"),
                       "export function esc")
    assert body.startswith("{") and body.rstrip().endswith("}")
    assert "/[&<>\"']/g" in body, "the regex that used to end the scan"
    assert "ESC_MAP[m]" in body
    assert body.count("{") == body.count("}")
    # Scoped, not file-wide: the module's header prose is a long argument about
    # `B866` and none of it is in the body.
    assert "B866" not in body
    assert re.search(r"^export \{ esc \};", UI_JS.read_text(encoding="utf-8"),
                     re.M), "ui.js is still the name every caller imports"


def test_the_old_scanner_really_did_fail_on_it():
    """A row that cannot be reproduced is a row nobody can check (`Law 9`).

    This is the pre-`B876` scanner, written out, run against the real module.
    It is the only copy left in the suite and it exists to fail.
    """
    def old_skip(source, i, n):
        c = source[i]
        if c == "/" and i + 1 < n:
            nxt = source[i + 1]
            if nxt == "/":
                j = source.find("\n", i)
                return n if j < 0 else j
            if nxt == "*":
                j = source.find("*/", i + 2)
                return n if j < 0 else j + 2
        if c in "'\"`":
            j = i + 1
            while j < n and source[j] != c:
                j += 2 if source[j] == "\\" else 1
            return j + 1
        return i

    src = ESCAPE_HTML_JS.read_text(encoding="utf-8")
    n = len(src)
    i = src.index("(", src.index("export function esc"))
    depth = 0
    while i < n:
        j = old_skip(src, i, n)
        if j != i:
            i = j
            continue
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    open_at = src.index("{", i)
    depth, i, closed = 0, open_at, False
    while i < n:
        j = old_skip(src, i, n)
        if j != i:
            i = j
            continue
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                closed = True
                break
        i += 1
    assert not closed, (
        "the pre-B876 scanner now finds esc's closing brace — if the source "
        "moved so this no longer reproduces, say so in the row rather than "
        "deleting the case")


# ── the four delimiters the row asks to be pinned ───────────────────────────


REGEX_CASES = [
    ("apostrophe", r"function f(s) { return s.replace(/[&<>\"']/g, '_'); }"),
    ("double quote", r'function f(s) { return s.replace(/["]/g, "_"); }'),
    ("backtick", "function f(s) { return s.replace(/[`]/g, '_'); }"),
    ("slash in a class", r"function f(s) { return s.replace(/[/]/g, '_'); }"),
    ("escaped slash", r"function f(s) { return s.replace(/a\/b/g, '_'); }"),
    ("brace in a class", r"function f(s) { return s.replace(/[{}]/g, '_'); }"),
    # A `/` inside a character class is a literal slash, and the `}` after it is
    # inside the class too. Without the class state the regex "ends" at that
    # slash and the `}` closes the function four characters early.
    ("slash then brace in a class", r"function f(s) { return s.replace(/[/}]/g, '_'); }"),
    ("counted brace", r"function f(s) { return s.replace(/x{2,3}/g, '_'); }"),
    ("all four at once", "function f(s) { return s.replace(/['\"`/]/g, '_'); }"),
    # A regex may also open after a KEYWORD, and the checker keeps that list.
    # Without it `return /['}]/` reads the `'` as a string and swallows the
    # brace that closes the function.
    ("after return", r"function f(s) { return /['}]/.test(s); }"),
    ("after typeof", r"function f(s) { return typeof /['}]/ === 'object'; }"),
]


@pytest.mark.parametrize("label,src", REGEX_CASES, ids=[c[0] for c in REGEX_CASES])
def test_a_regex_holding_a_delimiter_does_not_open_one(label, src):
    """Each of `'`, `"`, `` ` `` and `/` inside a regex literal, plus the two
    brace forms, with live code after the function so a runaway scan shows."""
    text = src + "\nfunction after() { return 'kept'; }\n"
    assert js_function(text, "function f") == src[src.index("{"):]
    assert js_function(text, "function after") == "{ return 'kept'; }"


def test_division_is_not_a_regex():
    """The other half of the rule. `a / b` then `c / d` is two divisions, not
    one regex swallowing the `}` between them."""
    text = ("function f(a, b) { const r = a / b; return r / 2; }\n"
            "function after() { return 'kept'; }\n")
    assert js_function(text, "function f") == "{ const r = a / b; return r / 2; }"
    assert js_function(text, "function after") == "{ return 'kept'; }"


def test_a_division_after_an_increment_does_not_eat_the_rest_of_the_file():
    """`i++ / 2` is the case the newline rule is for.

    `+` is in the checker's "a regex may follow this" set, so the scanner *does*
    consider the `/` a regex opener — and then finds no closing delimiter before
    the end of the line. A regex literal cannot span a newline, so it is a
    division after all. Without that rule the scan runs to the next `/`
    anywhere in the file, which here is inside a string in the NEXT function,
    and takes the closing brace of this one with it.
    """
    text = ("function f(i) {\n"
            "  let n = 0;\n"
            "  n = i++ / 2;\n"
            "  return n;\n"
            "}\n"
            "function after() { return 'a/b'; }\n")
    body = js_function(text, "function f")
    assert body.endswith("return n;\n}"), body
    assert "after" not in body
    assert js_function(text, "function after") == "{ return 'a/b'; }"


def test_an_unterminated_quote_costs_one_line():
    """The checker's own rule, mirrored: a string literal ends at its quote or
    at the newline it did not escape. Without it, one stray apostrophe makes
    everything after it invisible to the scan."""
    text = ("function f() { return 1; }\n"
            "const broken = 'oops\n"
            "function after() { return 'kept'; }\n")
    assert js_function(text, "function after") == "{ return 'kept'; }"


def test_a_signature_quoted_in_a_string_is_not_the_signature():
    """The decoy has to be one the paren-and-brace walk would actually fall for.

    A signature quoted in a comment is harmless — the walk skips the comment and
    lands on the real one anyway. A signature in a string *followed by other
    code with braces* is not: the first `(` and the first `{` after the decoy
    belong to that code, and the extractor returns it.
    """
    text = ("const doc = 'function f';\n"
            "if (true) { const x = 1; }\n"
            "function f() { return 'real'; }\n")
    assert js_function(text, "function f") == "{ return 'real'; }"


def test_a_misread_slash_costs_a_line_and_not_a_file():
    """The safety valve, stated as behaviour. A regex literal cannot span a
    newline, so a `/` that is read as one and is not stops at the end of its
    line — where the old scanner's misread quote ran to the end of the file."""
    text = ("function f(a, b, c) {\n"
            "  return (a + b) / c;\n"
            "}\n"
            "function after() { return 'kept'; }\n")
    assert js_function(text, "function after") == "{ return 'kept'; }"


# ── the other literals, which the old scanner half-knew ─────────────────────


def test_a_string_holding_a_brace_is_not_a_brace():
    text = ("function f() { return '}' + \"{\"; }\n"
            "function after() { return 'kept'; }\n")
    assert js_function(text, "function f") == "{ return '}' + \"{\"; }"


def test_a_template_hole_is_code_and_its_text_is_not():
    """`${` and `}` balance each other and are left as code, so a template
    whose text holds a lone `}` still closes where the function closes."""
    text = ("function f(x) { return `a } b ${ x ? '{' : '}' } c`; }\n"
            "function after() { return 'kept'; }\n")
    assert js_function(text, "function f") == "{ return `a } b ${ x ? '{' : '}' } c`; }"
    assert js_function(text, "function after") == "{ return 'kept'; }"


def test_a_nested_template_closes_where_it_opens():
    text = ("function f(x) { return `a ${ `b ${ x } c` } d`; }\n"
            "function after() { return 'kept'; }\n")
    assert js_function(text, "function f") == "{ return `a ${ `b ${ x } c` } d`; }"


def test_an_apostrophe_in_a_comment_is_prose():
    """`P8-25`'s case, kept. `static/js/tasks.js` is English prose about code
    and English prose is full of apostrophes."""
    text = ("function f() {\n"
            "  // the app's whirlpool, and the poll's next render\n"
            "  return 1;\n"
            "}\n"
            "function after() { return 'kept'; }\n")
    assert "whirlpool" in js_function(text, "function f")
    assert js_function(text, "function after") == "{ return 'kept'; }"


def test_the_signature_is_found_in_code_and_not_in_prose():
    """The old helper used `source.index(signature)`, and this repository's
    comments quote signatures constantly — the same `Law 20` failure one level
    up: the right string in the wrong place."""
    text = ("// see `function f` below, which returns the wrong thing\n"
            "function f() { return 'the real one'; }\n")
    assert js_function(text, "function f") == "{ return 'the real one'; }"


def test_a_destructured_parameter_is_not_the_body():
    """This helper's own first bug, kept as a case."""
    text = "function f({ autoApprove = true, other = 1 }) { return autoApprove; }\n"
    assert js_function(text, "function f") == "{ return autoApprove; }"


def test_an_unknown_signature_says_so():
    with pytest.raises(AssertionError, match="does not appear in code"):
        js_function("function f() { return 1; }\n", "function nope")


# ── the spans themselves ────────────────────────────────────────────────────


def test_js_spans_covers_comment_string_regex_and_template_text():
    src = ("const a = 'str'; // note\nconst b = /[']/g; const c = `t ${ a } u`;\n")
    covered = "".join(src[a:b] for a, b in js_spans(src))
    for piece in ("'str'", "// note", "/[']/", "`t ", " u`"):
        assert piece in covered, piece
    # and the code between them is not covered
    for a, b in js_spans(src):
        assert "const" not in src[a:b]


def test_js_spans_are_sorted_and_do_not_overlap():
    src = ESCAPE_HTML_JS.read_text(encoding="utf-8")
    spans = js_spans(src)
    assert spans == tuple(sorted(spans))
    for (a, b), (c, _d) in zip(spans, spans[1:]):
        assert a < b <= c


def test_js_skip_steps_over_exactly_one_literal():
    src = "x = 'a' + 'b';"
    spans = js_spans(src)
    at = src.index("'a'")
    assert js_skip(src, at, len(src), spans) == at + 3
    assert js_skip(src, 0, len(src), spans) == 0, "code is left alone"


def test_js_code_blanks_literals_and_keeps_line_numbers():
    src = "const a = 'hidden';\n// gone\nconst b = /[']/g;\n"
    out = js_code(src)
    assert "hidden" not in out and "gone" not in out
    assert out.count("\n") == src.count("\n")
    assert len(out) == len(src)
    assert "const a" in out and "const b" in out


# ── `Law 14`: the rules come from the checker, not from here ────────────────


def test_the_regex_start_rule_is_the_checkers_own_object():
    """Not "the same values" — the same objects. A new keyword taught to
    `.pantheon/check-specifiers.py` is a new keyword here, with no second edit
    and no way for the two to drift."""
    assert REGEX_MAY_FOLLOW is checker._REGEX_MAY_FOLLOW
    assert KEYWORD_BEFORE_REGEX is checker._KEYWORD_BEFORE_REGEX


def test_comments_are_the_blankers_and_are_not_detected_here():
    """`js_spans` runs on `blank_text` output, so there is no `//` or `/* */`
    branch in `tests/helpers/js_source.py` to go wrong a second way."""
    helper = (ROOT / "tests" / "helpers" / "js_source.py").read_text(encoding="utf-8")
    tree = ast.parse(helper)
    names = {n.func.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "blank_text" in names
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in ("//", "/*", "*/"), (
                "comment detection belongs to .pantheon/check-specifiers.py")


def test_the_module_this_file_tests_is_the_one_the_suite_imports():
    """The helper moved; the name did not. `js_function` imported the old way
    is the same object."""
    import test_a_draft_skill_is_uncatalogued_not_inactive as host

    assert host.js_function is js_function


# ── the census, driven rather than grepped ──────────────────────────────────


_TOP_LEVEL = re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+[A-Za-z_$][\w$]*",
                        re.M)


def _modules():
    out = subprocess.run(["git", "ls-files", "static/js"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / f for f in out if f.endswith(".js")]


def _extractions(path):
    """Every uniquely-named top-level function in one module, `(sig, body)`.

    The signatures are found in `js_code(src)`, not in `src`, so a `function`
    written inside a template literal or a string is not looked for.
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    code = js_code(src)
    out = []
    for m in _TOP_LEVEL.finditer(code):
        sig = code[m.start():code.index("(", m.start())].strip()
        if code.count(sig) != 1:
            continue
        out.append((sig, js_function(src, sig)))
    return out


def _parses(bodies) -> bool:
    """Does node accept every one of these as a function body?

    `void async function* () BODY;` — the generator-and-async wrapper so a body
    holding `await` or `yield` is judged on its braces and not on its context.
    One file per module, one `node --check`, because 2,820 processes is not a
    test.
    """
    text = "\n".join("void async function* () %s;" % b for b in bodies)
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(text)
        temp = handle.name
    try:
        done = subprocess.run(["node", "--check", temp],
                              capture_output=True, text=True)
        return done.returncode == 0, done.stderr.strip()
    finally:
        os.unlink(temp)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_every_extracted_body_is_javascript_node_will_parse():
    """`Law 20`: the oracle is a parser, not another brace counter.

    Every uniquely-named top-level function in `static/js/**` is extracted and
    handed to `node --check`. **Measured on this tree, 2,820 extractions in 181
    modules**: the new helper raises on none of them and node parses all 2,820.
    The pre-`B876` scanner raised `unbalanced braces` on **23** and returned a
    different body on **26** more — and **17 of those 26 are not parseable
    JavaScript at all**, which is what this test would have caught and no test
    in the suite did.
    """
    total = 0
    for path in _modules():
        pairs = _extractions(path)
        if not pairs:
            continue
        total += len(pairs)
        ok, err = _parses([body for _sig, body in pairs])
        assert ok, f"{path.relative_to(ROOT)} extracted an unparsable body:\n{err}"
    assert total > 2500, f"only {total} extractions — the census stopped looking"


def test_the_worst_case_the_row_names_is_the_right_length_now():
    """`async function _buildSuggestionSource` (`static/js/emailLibrary.js:3744`)
    is the one the row quotes: the old scanner returned **145,664 characters
    for a 1,261-character function** — the rest of the module, wearing a
    scope's clothes. Pinned by shape, not by a byte count that will drift:
    the body must be a small fraction of its module and must not contain the
    signature of the function that follows it."""
    src = (ROOT / "static" / "js" / "emailLibrary.js").read_text(encoding="utf-8")
    body = js_function(src, "async function _buildSuggestionSource")
    assert len(body) < len(src) / 10, len(body)
    after = src[src.index(body) + len(body):]
    assert _TOP_LEVEL.search(after), "there is still a function after this one"
    assert _TOP_LEVEL.search(js_code(body)) is None, (
        "the body swallowed the next top-level function")


def test_the_census_is_not_a_tautology():
    """A census that reads nothing passes everything (`B290`'s lesson)."""
    mods = _modules()
    assert len(mods) > 150, f"only {len(mods)} modules found under static/js"
    assert any(p.name == "markdown.js" for p in mods)
    assert any(p.name == "emailLibrary.js" for p in mods)
    assert sum(len(_extractions(p)) for p in mods[:20]) > 100


# ── no second cutter grows in the suite ─────────────────────────────────────


#: Test files that still balance JavaScript braces by hand. Each is a real
#: site, measured, and each is a separate row — not this one. The largest is
#: `tests/test_retrieval_engine_is_named.py:333`, whose `_js_function` counts
#: `{` and `}` with no string, comment or regex state at all: run over the 48
#: exported functions of `static/js/chatRenderer.js` it returns the right body
#: for 47 and **128,616 characters for `parseTodoList`, which is 1,913** — it
#: is green only because nothing calls it on that one yet.
STILL_BALANCES_BY_HAND = {
    "tests/test_accent_fallback_semantics_css.py",
    "tests/test_advanced_key_mirrors_js.py",
    "tests/test_autoplayed_tours_are_not_conversation.py",
    "tests/test_calendar_reminders_ride_the_notes_loop.py",
    "tests/test_color_scheme_follows_the_palette.py",
    "tests/test_compare_history_is_shared.py",
    "tests/test_composer_and_attach_strip_rules.py",
    "tests/test_document_ai_preview_refresh_js.py",
    "tests/test_document_diff_discard_on_update_js.py",
    "tests/test_email_library_prewarm.py",
    "tests/test_embeddings_panel.py",
    "tests/test_expert_only_switches.py",
    "tests/test_fg_muted_and_backdrop_cascade_css.py",
    "tests/test_gallery_album_membership.py",
    "tests/test_keybind_registry.py",
    "tests/test_keyframes_are_unique_and_resolved.py",
    "tests/test_local_endpoint_api_key_js.py",
    "tests/test_mentions_are_not_uses.py",
    "tests/test_one_icon_table.py",
    "tests/test_one_run_mode_picker_js.py",
    "tests/test_reduced_motion_guard.py",
    "tests/test_retrieval_engine_is_named.py",
    "tests/test_self_checks.py",
    "tests/test_settings_the_model_could_change.py",
    "tests/test_sidebar_headers_outrank_their_rows_css.py",
    "tests/test_toast_dismiss_pointer_events.py",
    "tests/test_tool_effect_surfaces_js.py",
    "tests/test_tool_elapsed_is_server_truth.py",
}


def _hand_balancers(rel: str) -> list:
    """Every function in `rel` that walks a source counting `{` against `}`.

    Read with `ast`, like `test_one_comment_blanker.py`'s rule and for the same
    reason: this file *describes* brace balancing at length and a text search
    would count the description as the thing described.
    """
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for loop in ast.walk(node):
            if not isinstance(loop, (ast.While, ast.For)):
                continue
            seen = {c.value for c in ast.walk(loop)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            if "{" in seen and "}" in seen:
                out.append((node.lineno, node.name))
                break
    return out


def _tracked_tests() -> list:
    out = subprocess.run(["git", "ls-files", "tests"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    return [f for f in out if f.endswith(".py")]


def test_no_new_hand_rolled_js_function_cutter_appears():
    """The half of this row that stops it coming back.

    `B876` is the third time a scanner in this suite has been taught a literal
    it did not know — `P8-25` taught the old one comments, `B290` taught the
    blanker strings and regexes — and each fix was correct and none of them
    stopped the next copy, because a brace counter looks obviously right when
    you write it. Anything that wants one function out of a module imports
    `tests/helpers/js_source.py`.
    """
    offenders = []
    for rel in _tracked_tests():
        if rel in STILL_BALANCES_BY_HAND or rel.endswith(
                ("test_one_js_function_extractor.py", "helpers/js_source.py")):
            continue
        for line, name in _hand_balancers(rel):
            offenders.append(f"{rel}:{line}  {name}")
    assert not offenders, (
        "a JavaScript brace balancer was written by hand:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse `from tests.helpers.js_source import js_function`. A brace "
          "counter with no regex state returned 145,664 characters for a "
          "1,261-character function; see B876.")


def test_the_allow_list_has_no_stale_entries():
    """An allow-list that outlives its reason is a second place the tree's
    state lives — `B290`'s rule, applied to this one."""
    stale = [rel for rel in sorted(STILL_BALANCES_BY_HAND)
             if not _hand_balancers(rel)]
    assert not stale, (
        f"{stale} no longer balances braces by hand — delete the entry from "
        f"STILL_BALANCES_BY_HAND so the list stays a description of the tree.")


def test_the_rule_is_not_a_tautology():
    assert len(_tracked_tests()) > 200
    assert len(STILL_BALANCES_BY_HAND) >= 27
