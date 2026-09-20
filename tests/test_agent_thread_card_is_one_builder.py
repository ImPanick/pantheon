# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-01` — one builder for the tool card, and the decisions that took.

There were six copies of this markup: two on the live path (`chat.js`, running
and done), one in history replay (`chatRenderer.js`), two in compare mode
(`compare/stream.js`), and one for document writing (`chat.js`). No two were
byte-identical. The row says the extraction is not mechanical — *"you must
decide which behaviour is correct"* — so what follows is what was decided, held
by execution rather than by assertion about the source.

  **the icon.** The live running card picks from a map and falls back to `▶`.
  Compare mode wrote `▶` as a literal, so the same `web_search` event showed a
  magnifier in chat and a triangle in compare. Decided: computed everywhere.

  **the diff.** Compare's finished card had no slot for one, so a file edit
  there could never show what changed. Decided: rendered wherever the caller
  has one, and the renderer itself extracted — it existed twice, identically.

  **the label, three ways.** 21 gerunds on the live running card, the **raw
  tool id** on every finished card in all three copies, and compare's own
  five-entry map of nouns — written out twice, once per handler. Decided:
  **two forms per tool, and that is not drift.** A running card sits under a
  moving wave and is a sentence about what is happening ("Searching"); a
  finished card is a noun naming what happened ("Web Search · done"). The
  defect was that nobody said there were two, and that the finished cards used
  neither.

  **the click handler (`B56`).** `chat.js` binds one delegated listener on
  `document.body` — its comment says per-node listeners were "the source of the
  needs-many-clicks bug". Compare bound one anyway, on top of it. Both fired
  for one click, the card toggled twice, and **clicking a tool card in compare
  mode did nothing at all.**
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402
from test_tool_effect_surfaces_js import _copy_unstubbed_imports  # noqa: E402

from tests.helpers.esc_stub import ui_default_stub  # B874

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "agentThread.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# `B874`. The shipped escaper, read out of `static/js/util/escapeHtml.js`
# at test time rather than restated here. Seven files held this same
# five-character copy and three more held one that escaped nothing.
_UI_STUB = ui_default_stub()


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("agentthread")
    (d / "ui.js").write_text(_UI_STUB, encoding="utf-8")
    shutil.copy(_MODULE, d / "agentThread.js")
    # `P5-04` added an import to `agentThread.js`, and a sandbox that copies one
    # file cannot see one. `_copy_unstubbed_imports` was written for exactly this
    # ("adding one import to a sandboxed module breaks every sandbox that copies
    # it") and is borrowed rather than re-implemented here (`Law 14`): `ui.js` keeps
    # its stub, everything else comes in for real, transitively.
    _copy_unstubbed_imports(d, _MODULE, {"ui.js"})
    return d


def _run(sandbox: Path, script: str):
    entry = sandbox / "case.mjs"
    entry.write_text(
        "const m = await import('./agentThread.js');\n" + textwrap.dedent(script),
        encoding="utf-8",
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"node produced no stdout\n{proc.stderr}"
    return json.loads(lines[-1])


def _html(sandbox: Path, opts: dict) -> str:
    return _run(sandbox, f"console.log(JSON.stringify(m.agentThreadNodeHtml({json.dumps(opts)})));")


# ── the icon ──────────────────────────────────────────────────────────────────


def test_a_web_search_shows_the_magnifier_while_it_runs(sandbox):
    # The divergence the row names first: compare mode could never show this.
    out = _html(sandbox, {"tool": "web_search", "state": "running"})
    assert "<svg" in out and "circle" in out, "the search glyph is gone"


def test_a_tool_with_no_icon_of_its_own_gets_the_triangle(sandbox):
    # This asked about `bash` until `P5-04`, which is when `bash` stopped being
    # a tool with no icon of its own — the map went from one entry to
    # twenty-one. The property is the fallback, not the tool, so the case moves
    # to a tool that genuinely has no entry rather than the assertion being
    # dropped.
    assert "▶" in _html(sandbox, {"tool": "some_new_tool", "state": "running"})


def test_every_tool_the_thread_can_name_it_can_also_draw(sandbox):
    """`P5-04`. One entry against 21 labels meant twenty of twenty-one running
    cards drew the same triangle — and seven of the running *labels* are shared
    (`bash` and `python` are both "Running"), so a card gave no way at all to
    tell which tool was running. A label without a glyph is that defect coming
    back one tool at a time."""
    out = _run(sandbox, """
        const missing = Object.keys(m.TOOL_LABELS).filter((t) => !m.TOOL_ICONS[t]);
        const wrong = Object.entries(m.TOOL_ICONS)
          .filter(([, svg]) => !/^<svg /.test(svg) || !svg.includes('currentColor'))
          .map(([tool]) => tool);
        console.log(JSON.stringify({
          labels: Object.keys(m.TOOL_LABELS).length, missing, wrong,
        }));
    """)
    assert out["labels"] == 21, out["labels"]
    assert out["missing"] == [], out["missing"]
    # Monochrome and inline, as the row asks: a glyph that names its own colour
    # is a glyph that is wrong on fifteen of the sixteen palettes.
    assert out["wrong"] == [], out["wrong"]


@pytest.mark.parametrize("ok, glyph", [(True, "✓"), (False, "✗")])
def test_a_finished_card_says_whether_it_worked(sandbox, ok, glyph):
    out = _html(sandbox, {"tool": "web_search", "state": "done", "ok": ok})
    assert glyph in out
    assert "<svg" not in out, "a finished card reports the outcome, not the tool"


# ── the label ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tool, running, done", [
    ("web_search", "Searching", "Web Search"),
    ("bash", "Running", "Terminal"),
    ("write_file", "Writing", "Write File"),
    ("deep_research", "Researching", "Deep Research"),
])
def test_a_tool_is_named_for_what_it_is_doing_then_for_what_it_did(sandbox, tool, running, done):
    # The decision, executed. Before this, the running card said "Searching"
    # and the finished one said `web_search`.
    assert running in _html(sandbox, {"tool": tool, "state": "running"})
    assert done in _html(sandbox, {"tool": tool, "state": "done", "ok": True})


def test_an_unknown_tool_keeps_its_own_name(sandbox):
    # A name nobody chose beats a wrong one, and beats an empty header.
    for state in ("running", "done"):
        assert "some_new_tool" in _html(sandbox, {"tool": "some_new_tool", "state": state, "ok": True})


def test_a_card_that_is_not_a_tool_call_can_say_so(sandbox):
    # The document writer's own thread. It had a copy of this markup with the
    # word "Writing" hardcoded into it.
    out = _html(sandbox, {"tool": "", "state": "running", "label": "Writing"})
    assert "Writing" in out


def test_the_label_is_escaped(sandbox):
    out = _html(sandbox, {"tool": "", "state": "running", "label": "<img onerror=x>"})
    assert "<img" not in out
    assert "&lt;img" in out


# ── the content ───────────────────────────────────────────────────────────────


def test_a_diff_is_rendered_where_the_caller_has_one(sandbox):
    out = _html(sandbox, {"tool": "write_file", "state": "done", "ok": True,
                          "diff": "<details class='agent-tool-diff'>D</details>"})
    assert "agent-tool-diff" in out


@pytest.mark.parametrize("suppressor", ["diff", "todo"])
def test_the_raw_command_is_hidden_when_something_says_it_better(sandbox, suppressor):
    # For a file edit the "command" is the raw JSON arguments, redundant beside
    # the diff; for a todowrite it *is* the task list the card above formats.
    # The live path did this, history replay did this, compare did half of it.
    out = _html(sandbox, {"tool": "write_file", "state": "done", "ok": True,
                          "command": '{"path":"x"}', suppressor: "<div>rendered</div>"})
    assert "agent-thread-cmd" not in out
    assert "rendered" in out


def test_the_command_is_shown_when_nothing_else_says_it(sandbox):
    out = _html(sandbox, {"tool": "bash", "state": "done", "ok": True, "command": "ls -la"})
    assert "agent-thread-cmd" in out and "ls -la" in out


def test_the_command_is_escaped(sandbox):
    out = _html(sandbox, {"tool": "bash", "state": "running", "command": "<script>x</script>"})
    assert "<script>" not in out


def test_a_running_card_waves_and_a_finished_one_does_not(sandbox):
    running = _html(sandbox, {"tool": "bash", "state": "running"})
    done = _html(sandbox, {"tool": "bash", "state": "done", "ok": True})
    assert "agent-thread-wave" in running and "agent-thread-status" not in running
    assert "agent-thread-status" in done and "agent-thread-wave" not in done
    assert "agent-thread-chevron" in done


# ── the class, and the open state ─────────────────────────────────────────────


@pytest.mark.parametrize("state, ok, expected", [
    ("running", None, "agent-thread-node running"),
    ("done", True, "agent-thread-node"),
    ("done", False, "agent-thread-node error"),
])
def test_the_class_says_what_the_card_is(sandbox, state, ok, expected):
    out = _run(sandbox, f"console.log(JSON.stringify(m.nodeClassName({state!r}, {json.dumps(ok)})));")
    assert " ".join(out.split()) == expected


def test_expanding_a_running_tool_survives_the_result_landing(sandbox):
    # A running card the user opened is rewritten in place when the result
    # arrives. Losing `open` there collapses it under their cursor and they
    # have to click again — the live path rebuilt the className by hand to
    # avoid that, one caller out of six.
    out = _run(sandbox, """
        const node = { className: 'agent-thread-node running open',
                       classList: { contains: (c) => node.className.split(' ').includes(c) },
                       innerHTML: '' };
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'done', ok: true });
        console.log(JSON.stringify({ className: node.className }));
    """)
    assert "open" in out["className"].split()
    assert "running" not in out["className"].split()


def test_a_card_that_was_not_open_does_not_become_open(sandbox):
    out = _run(sandbox, """
        const node = { className: 'agent-thread-node running',
                       classList: { contains: (c) => node.className.split(' ').includes(c) },
                       innerHTML: '' };
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'done', ok: true });
        console.log(JSON.stringify({ className: node.className }));
    """)
    assert "open" not in out["className"].split()


# ── nobody kept a copy ────────────────────────────────────────────────────────


_CALLERS = [
    "static/js/chat.js",
    "static/js/chatRenderer.js",
    "static/js/compare/stream.js",
]


def test_no_module_builds_this_card_by_hand_any_more():
    # The rule, not a list: the markup lives in one file and every other file
    # goes through it. A seventh copy fails here on the day it is written.
    offenders = []
    for path in sorted((_REPO / "static").rglob("*.js")):
        if "/lib/" in path.as_posix() or path.name == "agentThread.js":
            continue
        text = path.read_text(encoding="utf-8")
        if 'class="agent-thread-dot"' in text or "class='agent-thread-dot'" in text:
            offenders.append(str(path.relative_to(_REPO)))
    assert offenders == [], f"these still write the card markup themselves: {offenders}"


@pytest.mark.parametrize("rel", _CALLERS)
def test_every_caller_goes_through_the_builder(rel):
    text = (_REPO / rel).read_text(encoding="utf-8")
    assert "applyAgentThreadNode" in text
    assert "agentThread.js" in text


@pytest.mark.parametrize("rel, source", [
    ("static/js/chat.js", "json.diff"),
    ("static/js/chatRenderer.js", "ev.diff"),
    ("static/js/compare/stream.js", "json.diff"),
])
def test_every_caller_passes_its_diff_through(rel, source):
    # Extracting the renderer is worth nothing if a caller stops handing it the
    # diff. Compare mode is the one that never did — its card had no slot — so
    # this is the assertion that says the slot is now filled from all three.
    text = (_REPO / rel).read_text(encoding="utf-8")
    assert f"buildDiffHtml({source})" in text, (
        f"{rel} no longer renders the diff it receives"
    )
    # …and hands the result to the builder. Every call is checked rather than
    # the first, because the first one in chat.js is the *running* card, which
    # correctly has no diff — asserting on it would have been an assertion
    # about argument order.
    calls = []
    rest = text
    while "applyAgentThreadNode(" in rest:
        i = rest.index("applyAgentThreadNode(")
        depth, j = 0, i + len("applyAgentThreadNode")
        while j < len(rest):
            if rest[j] == "(":
                depth += 1
            elif rest[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        calls.append(rest[i:j + 1])
        rest = rest[j + 1:]
    assert any("diff:" in c for c in calls), (
        f"{rel} builds every card without passing a diff; calls were {calls}"
    )


def test_the_diff_renderer_returns_nothing_for_nothing():
    # Callers pass `json.diff` straight in, and most events have none. A
    # renderer that produced an empty <details> for that would put a fold with
    # no content under every tool card in the product.
    src = (_REPO / "static" / "js" / "chatRenderer.js").read_text(encoding="utf-8")
    body = src[src.index("export function buildDiffHtml("):]
    body = body[:body.index("\n}\n") + 3]
    assert "if (!d.text) return '';" in body


def test_compare_mode_binds_no_click_listener_of_its_own():
    # `B56`. `chat.js` binds one delegated listener on document.body that
    # covers compare-mode nodes too; a second one here fired alongside it, the
    # card toggled twice, and clicking it did nothing.
    text = (_REPO / "static" / "js" / "compare" / "stream.js").read_text(encoding="utf-8")
    assert "agent-thread-header').addEventListener" not in text
    assert 'agent-thread-header").addEventListener' not in text


def test_the_delegated_listener_is_still_the_one_that_binds():
    text = (_REPO / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    assert "document.body.addEventListener('click'" in text
    assert "__pantheon_thread_click_bound" in text


def test_the_diff_renderer_is_not_duplicated_either():
    # It existed twice — identically, so extracting it needed no decision —
    # and compare mode had no copy at all, which is why a file edit there could
    # never show what changed.
    hits = [
        str(path.relative_to(_REPO))
        for path in sorted((_REPO / "static").rglob("*.js"))
        if "/lib/" not in path.as_posix()
        and 'class="diff-summary-stats"' in path.read_text(encoding="utf-8")
    ]
    assert hits == ["static/js/chatRenderer.js"], f"more than one diff renderer: {hits}"


def test_the_label_vocabulary_is_not_duplicated_either():
    # compare/stream.js carried its own five-entry map twice, once per handler.
    hits = [
        str(path.relative_to(_REPO))
        for path in sorted((_REPO / "static").rglob("*.js"))
        if "/lib/" not in path.as_posix()
        and "'Searching'" in path.read_text(encoding="utf-8")
    ]
    assert hits == ["static/js/agentThread.js"], f"a second label vocabulary: {hits}"


# ── `P5-02` · the fold has one grid item ─────────────────────────────────────


def test_the_card_body_is_one_box_that_can_be_animated(sandbox):
    """`P5-02` opens the card on `grid-template-rows: 0fr -> 1fr`, and that
    only works while `.agent-thread-content` has exactly **one** child: a
    second lands in an implicit `auto` row and stays visible while the card is
    shut. Three callers in `chat.js` append to this box after the card is
    built — the screenshot pane, the image progress row and the streaming tail
    — so the wrapper is the contract between them and the CSS."""
    html = _html(sandbox, {
        "tool": "bash", "state": "done", "ok": True, "command": "ls",
        "output": "<div class='out'>x</div>",
    })
    body = html[html.index('<div class="agent-thread-content">'):]
    assert body.startswith(
        '<div class="agent-thread-content"><div class="agent-thread-content-inner">'
    ), body[:140]
    assert body.count('class="agent-thread-content-inner"') == 1


def test_a_caller_is_handed_the_box_it_should_append_to(sandbox):
    """The helper, not the class name, is the thing callers use — so the next
    person adding a pane cannot append into the animating box by accident."""
    out = _run(sandbox, """
        const node = { querySelector: (sel) => ({ sel }) };
        const bare = { querySelector: (sel) =>
          (sel === '.agent-thread-content-inner' ? null : { sel }) };
        console.log(JSON.stringify({
          preferred: m.agentThreadContent(node).sel,
          fallback: m.agentThreadContent(bare).sel,
          nothing: m.agentThreadContent(null),
        }));
    """)
    assert out["preferred"] == ".agent-thread-content-inner"
    # A card built by an older cached module still gets somewhere to put a pane.
    assert out["fallback"] == ".agent-thread-content"
    assert out["nothing"] is None


# ── `P5-08` · arguments a person can read ────────────────────────────────────


def test_a_minified_argument_blob_is_laid_out_before_it_is_shown(sandbox):
    out = _run(sandbox, """
        console.log(JSON.stringify({
          obj: m.prettyJson('{"path":"/etc/hosts","mode":"append"}'),
          arr: m.prettyJson('[{"a":1},{"b":2}]'),
        }));
    """)
    assert out["obj"] == '{\n  "path": "/etc/hosts",\n  "mode": "append"\n}'
    assert out["arr"].startswith("[\n")


@pytest.mark.parametrize("text", [
    "/var/log/syslog",                       # a path
    "ls -la /tmp",                           # a command
    'SELECT * FROM t WHERE a = "{"',         # a query that merely contains a brace
    '{"path":"/etc/hosts","content":"aaa',   # truncated at 80 chars by the backend
    '"just a string"',                       # valid JSON, not an argument object
    "42",
    "",
])
def test_nothing_that_is_not_an_argument_object_is_treated_as_one(sandbox, text):
    """`P5-07` kept highlighting to two languages because guessing a language
    paints a filename in string-literal green and a wrong colour reads as a
    bug. This row does not reopen that: the text either parses as a JSON
    object or array or it is left exactly as it was. The truncated case is the
    one that matters — the document tools send the first 80 characters and the
    approval replay the first 240."""
    out = _run(sandbox, "console.log(JSON.stringify({ v: m.prettyJson(%s) }));"
               % json.dumps(text))
    assert out["v"] is None


def test_a_blob_that_arrived_laid_out_is_still_named_json(sandbox):
    """Found by mutation: an early return when the pretty form matched the
    input left the highlight depending on how the sender happened to format
    the arguments. Two identical objects, one minified and one not, came out
    of the card looking like different kinds of thing."""
    out = _run(sandbox, """
        const already = '{\\n  "path": "/etc/hosts"\\n}';
        console.log(JSON.stringify({
          pretty: m.prettyJson(already),
          html: m.commandBlockHtml(already, '', 'write_file'),
        }));
    """)
    assert out["pretty"] == '{\n  "path": "/etc/hosts"\n}'
    assert 'class="language-json"' in out["html"]


def test_the_command_block_shows_the_laid_out_form_and_says_it_is_json(sandbox):
    out = _run(sandbox, """
        console.log(JSON.stringify({
          json: m.commandBlockHtml('{"path":"/etc/hosts","mode":"append"}', '', 'write_file'),
          path: m.commandBlockHtml('/etc/hosts', '', 'write_file'),
          bash: m.commandBlockHtml('ls -la', '', 'bash'),
        }));
    """)
    assert 'class="language-json"' in out["json"]
    assert "&quot;path&quot;: &quot;/etc/hosts&quot;" in out["json"]
    # A path keeps the plain `<pre>` every card had before `P5-07`.
    assert "language-" not in out["path"]
    # And the two languages `P5-07` chose on purpose are undisturbed.
    assert 'class="language-bash"' in out["bash"]


def test_the_arguments_behind_the_fold_are_laid_out_too(sandbox):
    """The full arguments are the ones most likely to be a wall of JSON — that
    is why they are behind a fold in the first place."""
    out = _run(sandbox, """
        console.log(JSON.stringify({ html: m.commandBlockHtml(
          '/etc/hosts', '{"path":"/etc/hosts","content":"127.0.0.1 localhost"}', 'write_file') }));
    """)
    html = out["html"]
    assert 'class="agent-thread-cmd-full"' in html
    assert html.count('class="language-json"') == 1, "the summary line is not JSON"
    assert "&quot;content&quot;: " in html


def test_the_output_a_person_wants_most_can_be_copied(sandbox):
    """Every other block of text in this thread can be copied — the command
    since `P5-07`, a code block in the reply since long before that — and the
    one people actually want, the traceback, could only be selected by dragging
    inside a fold."""
    out = _run(sandbox, """
        console.log(JSON.stringify({ html: m.toolOutputPanesHtml({
          output: 'ok', stdout: 'ok', stderr: 'Traceback…', exit_code: 1 }) }));
    """)
    html = out["html"]
    # One per pane, and inside the `<summary>` so it is reachable without
    # opening the pane at all.
    assert html.count('class="agent-tool-output-copy"') == 2
    for pane in html.split("<details")[1:]:
        summary = pane[pane.index("<summary>"):pane.index("</summary>")]
        assert 'class="agent-tool-output-copy"' in summary
    assert 'aria-label="Copy output"' in html
    assert 'aria-label="Copy error output"' in html


def test_the_output_copy_button_does_not_fold_the_pane_it_belongs_to():
    """It sits inside a `<summary>`, where a click toggles the `<details>`.
    Without `preventDefault` the copy also shuts the pane, which reads as the
    button having done something else entirely."""
    # `Law 20` option 2, and the anchor matters: `js_function` steps over a
    # parameter list and then looks for the body brace, so handing it the
    # `closest(...)` call walked past the whole listener and returned a
    # 40-line block from further down the file. Anchoring on the arrow's own
    # parameter list, found by searching backwards from the selector, resolves
    # the 15 lines that are actually this handler. The length check below is
    # not decoration — it is what caught the wrong anchor.
    src = (_REPO / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    start = src.rindex("(e) => {", 0, src.index(".agent-tool-output-copy'"))
    handler = js_function(src[start:], "(e)")
    assert len(handler.splitlines()) < 25, (
        f"scope resolved to {len(handler.splitlines())} lines — that is not one handler"
    )
    assert ".agent-tool-output-copy" in handler
    assert "e.preventDefault()" in handler
    assert "copyToClipboard" in handler
