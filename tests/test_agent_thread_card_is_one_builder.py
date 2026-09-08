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

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "agentThread.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_UI_STUB = """
const MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export default { esc: (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => MAP[c]) };
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("agentthread")
    (d / "ui.js").write_text(_UI_STUB, encoding="utf-8")
    shutil.copy(_MODULE, d / "agentThread.js")
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
    assert "▶" in _html(sandbox, {"tool": "bash", "state": "running"})


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
