# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-09` — the arguments behind a truncated command line, and the way back to them.

`command` is what the card has always shown, and for two kinds of action it is
not the action:

  * a **document tool** sends its first line, capped at 80 characters. A
    `create_document` card showed one line of a file it had just written.
  * the **approval replay** sends the first 240 characters of the sealed
    content — the action a person read and allowed by hand.

`full_command` existed for both, on `tool_start`, and nowhere else. So the whole
of it was reachable exactly once: live, before the result landed, and only if
you had the fold open at that moment. The `tool_output` that rewrites the card
never carried it, and the persisted event never carried it, so after a reload
the rest of a document write did not exist on the page at all.

The expansion is a `<details>` rather than a button, and that is not a style
choice: the fold handler is a single delegated listener bound to
`.agent-thread-header`, the command block sits inside `.agent-thread-content`,
and a listener of its own here is exactly the shape of `B56`. The output fold
beside it is already a `<details>`, so this is that form and not a second one.

The sharp edge is the **refused** approval. `command` is blanked when the sealed
binding does not match this run, because the replay is not entitled to show an
action it is about to block — and an expansion that showed the whole of it would
mean a refused action displayed *more* than an approved one.
"""

import asyncio
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _copy_unstubbed_imports  # noqa: E402

import src.agent_loop as agent_loop
from src.tool_approvals import ToolApprovalStore
from src.tool_capabilities import capabilities_for_action

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "agentThread.js"

_UI_STUB = """
const MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export default { esc: (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => MAP[c]) };
"""


# ── the expansion ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = tmp_path_factory.mktemp("fullcommand")
    (d / "ui.js").write_text(_UI_STUB, encoding="utf-8")
    shutil.copy(_MODULE, d / "agentThread.js")
    # `P5-04` added an import to `agentThread.js`, and a sandbox that copies one
    # file cannot see one. `_copy_unstubbed_imports` was written for exactly this
    # ("adding one import to a sandboxed module breaks every sandbox that copies
    # it") and is borrowed rather than re-implemented here (`Law 14`): `ui.js` keeps
    # its stub, everything else comes in for real, transitively.
    _copy_unstubbed_imports(d, _MODULE, {"ui.js"})
    return d


def _node(sandbox: Path, script: str):
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


def _card(sandbox: Path, opts: dict) -> str:
    return _node(sandbox, f"console.log(JSON.stringify(m.agentThreadNodeHtml({json.dumps(opts)})));")


def test_a_truncated_command_offers_the_rest(sandbox):
    html = _card(sandbox, {"tool": "create_document", "state": "done", "ok": True,
                           "command": "# Q3 report",
                           "fullCommand": "# Q3 report\nthe body nobody could reach"})
    assert "agent-thread-cmd-full" in html
    assert "the body nobody could reach" in html
    assert "# Q3 report" in html, "the short line the card has always shown is still there"


def test_the_summary_says_how_much_is_behind_it(sandbox):
    # Law 15. Someone deciding whether to open this deserves to know whether it
    # is four lines or four hundred — and when the backend had to cap it, the
    # length is where that shows.
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True,
                           "command": "x" * 240, "fullCommand": "x" * 4210})
    assert "4,210 characters" in html


def test_a_command_that_is_already_whole_offers_nothing(sandbox):
    # The overwhelming majority. A `<details>` holding a copy of the line above
    # it is a click that returns nothing.
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True,
                           "command": "printf hi", "fullCommand": "printf hi"})
    assert "agent-thread-cmd-full" not in html


def test_an_event_with_no_full_command_draws_the_card_it_always_did(sandbox):
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True,
                           "command": "printf hi"})
    assert "agent-thread-cmd-full" not in html
    assert "printf hi" in html


def test_the_expansion_binds_no_listener_of_its_own(sandbox):
    # `B56`. The fold handler is one delegated listener on
    # `.agent-thread-header`; this markup lives in `.agent-thread-content` and
    # must stay declarative, or clicking it toggles two things at once.
    html = _card(sandbox, {"tool": "create_document", "state": "done", "ok": True,
                           "command": "# Q3", "fullCommand": "# Q3\nbody"})
    assert "<details" in html and "<summary" in html
    assert "onclick" not in html.lower()


def test_a_diff_or_a_todo_still_suppresses_the_whole_command_block(sandbox):
    # `P4-01`'s rule, which the expansion must not sneak past: for a file edit
    # the "command" is the raw JSON arguments, redundant beside the diff.
    for extra in ({"diff": "<div>d</div>"}, {"todo": "<div>t</div>"}):
        html = _card(sandbox, {"tool": "edit_file", "state": "done", "ok": True,
                               "command": "{...}", "fullCommand": "{...the whole thing...}",
                               **extra})
        assert "agent-thread-cmd" not in html, f"{extra} no longer suppresses the command"


def test_the_expansion_cannot_be_written_by_the_event(sandbox):
    # The payload is *text*, so the word `onerror` legitimately appears in the
    # output — what must not appear is a tag. The escaping is the assertion, not
    # the absence of the word, and getting that wrong is how an XSS test passes
    # while escaping nothing.
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True,
                           "command": "ls",
                           "fullCommand": '</pre><img src=x onerror=alert(1)>'})
    assert "<img" not in html, "the expansion wrote a tag out of tool arguments"
    assert "</pre><img" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


# ── the wire ──────────────────────────────────────────────────────────────────


def _events(generator):
    async def _drain():
        return [chunk async for chunk in generator]

    events = []
    for chunk in asyncio.run(_drain()):
        if not chunk.startswith("data: ") or chunk.startswith("data: [DONE]"):
            continue
        try:
            events.append(json.loads(chunk[6:]))
        except json.JSONDecodeError:
            pass
    return events


def _patch(monkeypatch, model_replies, *, result=None):
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    replies = iter(model_replies)

    async def fake_stream(*a, **k):
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *a, **k):
        return (block.tool_type, dict(result or {"output": "ok", "exit_code": 0}))

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)


def _of_type(events, event_type):
    return [e for e in events if e.get("type") == event_type]


def _persisted(events):
    return next(e for e in events if e.get("type") == "metrics")["data"].get("tool_events") or []


DOC_BODY = "\n".join(["# Q3 report"] + [f"line {i}" for i in range(60)])


def test_a_document_write_keeps_its_body_on_every_event(monkeypatch):
    # The row's case. `command` is the first line at 80 characters; before this
    # the rest was on `tool_start` alone.
    _patch(monkeypatch, [f"```create_document\n{DOC_BODY}\n```"])
    events = _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "write it"}],
            max_rounds=2, relevant_tools={"create_document"},
        )
    )
    start = _of_type(events, "tool_start")[0]
    output = _of_type(events, "tool_output")[0]
    persisted = _persisted(events)[0]
    assert start["command"] == "# Q3 report"
    assert "line 59" not in start["command"], "the card was never the problem"
    for event, where in ((start, "tool_start"), (output, "tool_output"),
                         (persisted, "the persisted event")):
        assert "line 59" in event["full_command"], f"{where} lost the body"


def test_the_reloaded_card_can_reach_what_the_live_one_could(monkeypatch):
    # The invariant the row is really about: the same action, two surfaces, one
    # answer. `P4-11` closed this for the round; this closes it for the
    # arguments.
    _patch(monkeypatch, [f"```create_document\n{DOC_BODY}\n```"])
    events = _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "write it"}],
            max_rounds=2, relevant_tools={"create_document"},
        )
    )
    live = _of_type(events, "tool_output")[0]
    reloaded = _persisted(events)[0]
    assert live["full_command"] == reloaded["full_command"]
    assert live["command"] == reloaded["command"]


def test_an_enormous_argument_is_capped_and_says_so(monkeypatch):
    # The persisted event goes in the database on every message, so this reuses
    # the cap the tool *output* already carries rather than inventing a second
    # size policy — and that cap states the real length instead of trailing off.
    body = "x" * 40_000
    _patch(monkeypatch, [f"```create_document\n# t\n{body}\n```"])
    events = _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "write it"}],
            max_rounds=2, relevant_tools={"create_document"},
        )
    )
    full = _persisted(events)[0]["full_command"]
    assert len(full) < 20_000, "the whole 40k body went into the message metrics"
    assert "truncated" in full and "chars total" in full, (
        "the cap trailed off silently instead of stating the real length"
    )


def _approved_run(monkeypatch, *, content, workspace=None, result=None):
    store = ToolApprovalStore()
    pending = store.create(
        owner="alice", session_id="full-args", origin_run_id="run-1",
        tool_name="bash", content=content, workspace=None,
        external_untrusted_context_seen=True, requested_round=2,
        capabilities=capabilities_for_action("bash", content),
    )
    grant = store.consume(pending.approval_id, decision="approve",
                          owner="alice", session_id="full-args")
    assert grant is not None
    _patch(monkeypatch, ["Ran it."], result=result)
    return _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "yes, go ahead"}],
            max_rounds=1, owner="alice", session_id="full-args", workspace=workspace,
            relevant_tools=set(grant.pending.selected_tools), exact_approval=grant,
        )
    )


LONG_APPROVED = "echo " + "a" * 400


def test_an_approved_action_keeps_the_whole_of_what_was_approved(monkeypatch):
    # 240 characters is what the card shows. The thing the user read and allowed
    # was 405, and after a reload the other 165 were gone.
    events = _approved_run(monkeypatch, content=LONG_APPROVED)
    output = _of_type(events, "tool_output")[0]
    assert len(output["command"]) == 240
    assert output["full_command"] == LONG_APPROVED
    assert _of_type(events, "tool_start")[0]["full_command"] == LONG_APPROVED
    assert _persisted(events)[0]["full_command"] == LONG_APPROVED


def test_a_refused_binding_expands_to_nothing(monkeypatch):
    # The sharp edge. `command` is blanked because the replay is not entitled to
    # show an action it is about to block; an expansion holding the whole of it
    # would show *more* of a refused action than of an approved one.
    events = _approved_run(monkeypatch, content=LONG_APPROVED,
                           workspace="/a/different/workspace")
    output = _of_type(events, "tool_output")[0]
    assert output["command"] == ""
    assert "full_command" not in output, (
        "a blocked action leaked its arguments through the expansion"
    )
    assert "full_command" not in _persisted(events)[0]
    assert "a" * 400 not in json.dumps(_persisted(events)[0])


# ── the callers ───────────────────────────────────────────────────────────────


def _calls(text: str) -> list[str]:
    calls, rest = [], text
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
    return calls


@pytest.mark.parametrize("rel, source", [
    ("static/js/chat.js", "json.full_command"),
    ("static/js/chatRenderer.js", "ev.full_command"),
    ("static/js/compare/stream.js", "json.full_command"),
])
def test_every_card_that_shows_a_command_is_handed_the_whole_one(rel, source):
    for call in _calls((_REPO / rel).read_text(encoding="utf-8")):
        if "command:" not in call:
            continue  # the document writer's own card carries no command
        assert f"fullCommand: {source}" in call, (
            f"{rel} draws a command block with no way back to the arguments: {call}"
        )
