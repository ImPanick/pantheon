# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B874` — the stubs that stand in for `ui.js` under node, and what they lied about.

`B866`'s sweep found nineteen local escapers in `static/js/**`. The same
pattern is inside the suite and there it is worse, because **a stub that does
not escape makes a test asserting escaping pass**.

**Measured on this tree, 2026-09-19, before the fix.** Every `esc` written into
a JavaScript stub inside `tests/**`, found with `ast` over the Python string
constants (a text search would count this docstring), twenty definitions in
eighteen files:

    pass-through, `(s) => s` or `String(s == null ? '' : s)`      6
    `& < >` only, missing `"` and `'`                             4
    `& < > "` only, missing `'`                                   1
    the canonical five, hand-written again                        9

The row named ten of those files and called three of them pass-throughs. The
`ast` rule below finds eighteen, and the extra eight are why a rule is worth
more than a list: `test_trust_ladder_js.py:809` is a **second** stub in a file
the row already named, and it escaped three characters, which is exactly the
shape `B866` found inside `showMcpForm`.

**Why the pass-throughs matter more than the copies.**
`tests/test_tasks_activity_sources_js.py` answered `esc` with its own input,
and it is the file over `static/js/tasks.js` — the module `B611` is about, which
carried two escapers that disagreed about `'` and `"` for a fortnight with this
test green the whole time. It was green because `tasks.js` happened to keep its
own `.replace` calls: every assertion about escaping was really an assertion
about the module not delegating. The day a builder in it started calling
`uiModule.esc` instead, the test would have stayed green and the attribute
would have opened.

**The fix is the one `B866` gave the product.** There is one escaper and
everybody uses it. A node sandbox cannot import `static/js/ui.js` — it pulls six
modules — so it gets the shipped implementation as text, read out of
`static/js/util/escapeHtml.js` at test time by `tests/helpers/esc_stub.py`.
Delete a character from the product's escaper and ten test files go red.

This file holds both halves: the stub is driven (`Law 20` — the assertion is
`node` running it, not a substring), and a rule fails when a twenty-first copy
appears.
"""
import ast
import json
import re
import shutil
import subprocess
import sys
import textwrap
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.helpers.esc_stub import ESCAPE_HTML_JS, esc_source, ui_default_stub

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")

HOSTILE = [
    'x" onerror=BOOM y="',
    "x' onerror=BOOM y='",
    "<script>alert(1)</script>",
    "a&amp;b",
    "plain",
]

#: The stub that was in three of these files, kept as a control. It is the
#: thing the row is about, so it is run beside the real one rather than
#: described.
PASS_THROUGH = "\nexport default { esc: (s) => String(s == null ? '' : s) };\n"


def _drive(tmp_path: Path, stub_source: str, probes=HOSTILE) -> list:
    """Import the stub as a module under node and call its `esc`.

    The sandbox's own shape: a file called `ui.js`, imported by specifier, its
    default export read as `uiModule`. Nothing here reimplements escaping to
    compare against — the comparison is against the product's own file, and the
    running is node's.
    """
    (tmp_path / "ui.js").write_text(stub_source, encoding="utf-8")
    entry = tmp_path / "case.mjs"
    entry.write_text(
        "import uiModule from './ui.js';\n"
        "const probes = %s;\n"
        "console.log(JSON.stringify(probes.map((p) => String(uiModule.esc(p)))));\n"
        % json.dumps(probes), encoding="utf-8")
    done = subprocess.run(["node", str(entry)], capture_output=True, text=True,
                          timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


class _Attrs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))


def _attrs_of(markup: str):
    parser = _Attrs()
    parser.feed(markup)
    assert parser.tags, markup
    return parser.tags[0][1]


# ── the stub is the shipped escaper, not a copy of it ───────────────────────


def test_the_stub_carries_the_product_s_own_bytes():
    """Not "the same five characters" — the same text, read at test time.

    If `esc` grows a sixth character tomorrow, every sandbox gets it with no
    edit anywhere in `tests/`.
    """
    shipped = ESCAPE_HTML_JS.read_text(encoding="utf-8")
    lifted = esc_source()
    assert "const ESC_MAP = { '&': '&amp;'" in lifted
    body = lifted[lifted.index("function esc(s)"):]
    assert body.strip()[len("function esc(s) "):] in shipped
    assert lifted.count("replace") == 1
    # and the table is the shipped one character for character
    table = lifted[:lifted.index("\n")]
    assert table.rstrip(";") in shipped


def test_the_stub_is_a_module_the_sandboxes_can_import(tmp_path):
    out = _drive(tmp_path, ui_default_stub("showToast: () => {},"))
    assert out[-1] == "plain"


# ── driven, not read ────────────────────────────────────────────────────────


def test_the_stub_escapes_all_five_characters(tmp_path):
    double, single, tag, amped, _plain = _drive(tmp_path, ui_default_stub())
    assert "&quot;" in double and '"' not in double
    assert "&#39;" in single and "'" not in single
    assert tag.startswith("&lt;") and "<" not in tag and ">" not in tag
    assert amped == "a&amp;amp;b", (
        "`&` must be escaped first, or `&amp;` typed by a person comes back "
        "out of the page as a bare `&`")


def test_the_stub_s_output_is_one_attribute(tmp_path):
    """`B866`'s exact shape. A description from a third-party MCP server, an
    image prompt, a mail tag — anything a person or a server chose — goes
    through this and into `alt="…"`."""
    double, single = _drive(tmp_path, ui_default_stub(),
                            ['x" onerror=BOOM y="', "x' onerror=BOOM y='"])
    assert [n for n, _ in _attrs_of('<img alt="%s">' % double)] == ["alt"]
    assert [n for n, _ in _attrs_of("<img alt='%s'>" % single)] == ["alt"]


def test_the_old_pass_through_stub_opens_three_attributes(tmp_path):
    """The control, and the whole of the row in one assertion.

    This is what `tests/test_context_meter_js.py:159`,
    `tests/test_trust_ladder_js.py:318` and
    `tests/test_tasks_activity_sources_js.py:43` answered `esc` with until this
    change. Run through the same sandbox and the same parser, it puts
    `onerror` on the element.
    """
    double, = _drive(tmp_path, PASS_THROUGH, ['x" onerror=BOOM y="'])
    assert double == 'x" onerror=BOOM y="', "the control is the identity"
    got = [n for n, _ in _attrs_of('<img alt="%s">' % double)]
    assert got == ["alt", "onerror", "y"], got


def test_the_three_character_stub_leaves_the_quote(tmp_path):
    """`tests/test_trust_ladder_js.py:809` before this change, and the second
    stub in a file the row counted once. `& < >` is the `B866` escaper, and it
    was standing in for `ui.js` under the card that prints a tool name and an
    argument value into an attribute."""
    three = ("\nconst esc = (s) => String(s == null ? '' : s)\n"
             "  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');\n"
             "export default { esc };\n")
    double, = _drive(tmp_path, three, ['x" onerror=BOOM y="'])
    assert double == 'x" onerror=BOOM y="', "three characters leave the quote"
    got = [n for n, _ in _attrs_of('<img alt="%s">' % double)]
    assert got == ["alt", "onerror", "y"], got


def test_a_non_string_goes_through_the_product_s_own_coercion(tmp_path):
    """The stubs were also *more generous* than the shipped escaper, and that
    hid a real rule.

    `esc` is `(s || '')`, so `esc(0)` is the empty string — which is why `B611`
    put `String(…)` in front of it at all 54 call sites. The stubs wrote
    `String(s == null ? '' : s)`, so `esc(0)` was `"0"` and a builder that
    forgot the `String(…)` looked correct under test and dropped a zero in the
    browser. The stub now behaves the way the product behaves.
    """
    zero, empty, false = _drive(tmp_path, ui_default_stub(), [0, None, False])
    assert (zero, empty, false) == ("", "", "")


# ── the rule: no test writes its own escaper into a stub ────────────────────


#: Test files that still define an `esc` inside a JavaScript stub. Each entry is
#: a measurement, not a shrug: what that copy escapes, and therefore what a
#: test in that file cannot prove. They are separate rows — this one covers the
#: ten `B874` names plus `test_trust_ladder_js.py`'s second stub.
STILL_WRITE_THEIR_OWN = {
    # pass-throughs: an assertion about escaping in these files is an assertion
    # about the module not delegating to `uiModule.esc`.
    "tests/test_autoplayed_tours_are_not_conversation.py": "93 `esc: (s) => s`",
    "tests/test_empty_states_js.py": "393 and 477 `_esc = (s) => String(s)`",
    # `& < >` only — `B866`'s escaper, the one that loses the attribute.
    "tests/test_chat_steer_js.py": "187 three characters",
    "tests/test_message_stats_surface_js.py": "200 three characters",
    "tests/test_tool_effect_surfaces_js.py": "342 three characters",
    # `& < > "` — closer, still not `'`.
    "tests/test_the_workshop_surfaces_js.py": "61 four characters",
    # correct today, and a copy to drift.
    "tests/test_the_round_reaches_the_card.py": "53 the canonical five",
    "tests/test_web_search_tool_icon_js.py": "24 the canonical five",
    # `B882`'s three loaders were here and are gone: the one markdown harness
    # holds the single `escapeHtml` inline now, so the entries went with them.
    # The list stays a description of the tree, which the next test enforces.
}

_JS_ESC_DEF = re.compile(
    r"(?:^|[^\w$.])(?P<name>_?esc|_?escHtml|escapeHtml|_attrEsc)\s*[:=]\s*"
    r"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
    r"|function\s+(?P<fname>_?esc|escapeHtml)\s*\(")


def _js_escapers(rel: str) -> list:
    """Every `esc` defined inside a JavaScript string constant in one file.

    Read with `ast` over the string literals, like
    `tests/test_one_comment_blanker.py`'s rule and for the same reason: this
    file quotes four of these definitions in its own prose, and a text search
    would count the quotation as the thing quoted. That is `Law 20` turned on
    the rule itself.
    """
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))

    # A docstring is a `Constant` str like any other, and this rule's own
    # explanations quote the shape it looks for — as does
    # `tests/helpers/js_source.py`, whose docstring spells out
    # `const _esc = (s) => …` in order to say why the sweep has to read two
    # shapes. Prose about a stub is not a stub. Same lesson as `B866`'s
    # comment-blanking and `B851`'s allowlist test: a detector that reads a
    # mention as a definition is measuring the file, not the code.
    docstrings = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            docstrings.add(id(body[0].value))

    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstrings:
            continue
        if "=>" not in node.value and "function" not in node.value:
            continue
        for m in _JS_ESC_DEF.finditer(node.value):
            # A definition that CALLS the canonical `esc` is delegation, which
            # is the thing this rule is asking for. Only a body that does the
            # replacing itself is a copy.
            tail = node.value[m.end():m.end() + 120]
            body_end = min((i for i in (tail.find("\n"), tail.find(";"))
                            if i != -1), default=len(tail))
            if "esc(" in tail[:body_end] and ".replace(" not in tail[:body_end]:
                continue
            line = node.lineno + node.value[:m.start()].count("\n")
            out.append((line, m.group("name") or m.group("fname")))
    return sorted(set(out))


def _tracked_tests() -> list:
    out = subprocess.run(["git", "ls-files", "tests"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    return [f for f in out if f.endswith(".py")]


def test_no_test_file_writes_its_own_esc_into_a_stub():
    """The half of this row that stops it coming back an eleventh time.

    A sandbox that needs `esc` imports `tests/helpers/esc_stub.py`. Writing the
    five characters again is how three of these came to escape none of them.
    """
    offenders = []
    for rel in _tracked_tests():
        if rel in STILL_WRITE_THEIR_OWN or rel.endswith("test_one_esc_stub_js.py"):
            continue
        for line, name in _js_escapers(rel):
            offenders.append(f"{rel}:{line}  {name}")
    assert not offenders, (
        "an HTML escaper was written into a JavaScript stub:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse `from tests.helpers.esc_stub import ui_default_stub`. Three "
          "of these returned their input, and the tests over them asserted "
          "escaping; see B874.")


def test_the_ten_files_the_row_names_are_fixed():
    """`Law 9`: the row's claim, checked against the tree rather than asserted.

    Each of these now builds its stub from the shipped escaper, so none of them
    may contain a definition of its own.
    """
    named = [
        "tests/test_context_meter_js.py",
        "tests/test_trust_ladder_js.py",
        "tests/test_tasks_activity_sources_js.py",
        "tests/test_a_refused_call_leaves_a_trace.py",
        "tests/test_agent_thread_card_is_one_builder.py",
        "tests/test_the_approved_action_looks_approved.py",
        "tests/test_the_command_is_copyable.py",
        "tests/test_the_error_stream_survives.py",
        "tests/test_the_full_arguments_are_reachable.py",
        "tests/test_the_independent_check_is_visible.py",
    ]
    for rel in named:
        assert not _js_escapers(rel), (rel, _js_escapers(rel))
        assert "esc_stub import ui_default_stub" in (
            ROOT / rel).read_text(encoding="utf-8"), rel


def test_the_allow_list_has_no_stale_entries():
    """An allow-list that outlives its reason is a second place the tree's
    state lives — `B290`'s rule, applied to this one."""
    stale = [rel for rel in sorted(STILL_WRITE_THEIR_OWN)
             if not _js_escapers(rel)]
    assert not stale, (
        f"{stale} no longer writes its own escaper — delete the entry from "
        f"STILL_WRITE_THEIR_OWN so the list stays a description of the tree.")


def test_the_rule_is_not_a_tautology():
    """A rule that finds nothing because it looks at nothing is the failure
    mode of every census in this fortnight."""
    assert len(_tracked_tests()) > 200
    for rel in STILL_WRITE_THEIR_OWN:
        assert _js_escapers(rel), f"{rel} was expected to hold one"
