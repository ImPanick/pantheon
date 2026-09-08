# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-20` — the call the policy refused, which used to leave nothing behind.

`tool_start` is the only event that **creates** a card. A call the policy
refuses never runs, so it never gets one — and its result then arrived as a
`tool_output` with nowhere to go. Two things happened, and the second is worse
than the row's own summary:

  * with no card open, the refusal **vanished from the thread entirely**;
  * with an earlier card still open in the same round, it **overwrote that
    one** — a command that had actually run and succeeded silently turned into
    a blocked one, and the successful call disappeared with it.

The second is what the row means by "the thread's state pointer goes stale".
`currentToolBubble` was cleared only at a round boundary, so within a round it
outlived the card it pointed at, and *any* event with no card of its own — a
policy refusal, an approval request, both of which skip `tool_start` — was
handed somebody else's node. `compare/stream.js` has always cleared it at the
end of a result; the main path had not.

A refusal is not a failure, and the card says so. A failed command was
attempted; this one was not.
"""

import asyncio
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

import src.agent_loop as agent_loop

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "agentThread.js"

_UI_STUB = """
const MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export default { esc: (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => MAP[c]) };
"""


# ── the event ─────────────────────────────────────────────────────────────────


def _refusing_policy(tool: str, reason: str):
    """The real `ToolPolicy`, not a stand-in.

    A hand-rolled double got as far as `blocks` and `reason_for` and then hit
    `all_disabled_names`, which is the loop's own reminder that this object has
    a contract: a double that satisfies the two methods a test happens to think
    about is a double that will diverge.
    """
    from src.tool_policy import ToolPolicy
    return ToolPolicy(
        disabled_tools=frozenset({tool}),
        reasons={tool: reason},
    )


def _events(chunks):
    out = []
    for chunk in chunks:
        if not chunk.startswith("data: ") or chunk.startswith("data: [DONE]"):
            continue
        try:
            out.append(json.loads(chunk[6:]))
        except json.JSONDecodeError:
            pass
    return out


def _run(monkeypatch, *, replies, policy=None):
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(),
                        raising=False)
    it = iter(replies)

    async def fake_stream(*a, **k):
        yield f"data: {json.dumps({'delta': next(it, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *a, **k):
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "run the command"}],
            max_rounds=2, relevant_tools={"bash", "python"}, tool_policy=policy,
        )]

    return _events(asyncio.run(drain()))


def _of_type(events, kind):
    return [e for e in events if e.get("type") == kind]


REFUSED = _refusing_policy("bash", "The shell is switched off for this chat.")


def test_a_refused_call_gets_an_event_of_its_own(monkeypatch):
    # The row, stated as the thing that was missing: `tool_start` never fired,
    # and `tool_start` is the only event that creates a card.
    events = _run(monkeypatch, replies=["```bash\nrm -rf /tmp/x\n```"], policy=REFUSED)
    assert _of_type(events, "tool_start") == [], (
        "a refused call must not claim to have started"
    )
    blocked = _of_type(events, "tool_blocked")
    assert blocked, "the refusal still leaves nothing to draw a card from"
    assert blocked[0]["tool"] == "bash"
    assert blocked[0]["command"] == "rm -rf /tmp/x"
    assert blocked[0]["reason"] == "The shell is switched off for this chat."
    assert blocked[0]["round"] == 1


def test_a_call_that_runs_gets_no_refusal_event(monkeypatch):
    events = _run(monkeypatch, replies=["```bash\nprintf hi\n```"])
    assert _of_type(events, "tool_blocked") == []
    assert _of_type(events, "tool_start")


def test_the_refusal_survives_a_reload_as_a_refusal(monkeypatch):
    # A refused call and a failed one both arrive as a non-zero exit code and
    # nothing else, so after a reload they were the same card.
    events = _run(monkeypatch, replies=["```bash\nrm -rf /tmp/x\n```"], policy=REFUSED)
    persisted = next(e for e in events
                     if e.get("type") == "metrics")["data"]["tool_events"]
    assert persisted[0]["blocked"] is True
    assert persisted[0]["policy"] == "current_tool_policy"


def test_a_call_that_ran_is_not_marked_blocked(monkeypatch):
    events = _run(monkeypatch, replies=["```bash\nprintf hi\n```"])
    persisted = next(e for e in events
                     if e.get("type") == "metrics")["data"]["tool_events"]
    assert "blocked" not in persisted[0]


def test_the_refusal_carries_the_same_fields_a_card_needs(monkeypatch):
    # It draws a card, so it needs what a card needs: the round (`P4-11`), the
    # command and its full form (`P4-09`), and the effect ranking (`P7-06`).
    events = _run(monkeypatch, replies=["```bash\nrm -rf /tmp/x\n```"], policy=REFUSED)
    blocked = _of_type(events, "tool_blocked")[0]
    for key in ("round", "command", "full_command", "effect"):
        assert key in blocked, f"a refused call's card has no {key}"


# ── the stale pointer ─────────────────────────────────────────────────────────


_CHAT = (_REPO / "static" / "js" / "chat.js").read_text(encoding="utf-8")


def test_a_finished_result_releases_the_card_it_finished():
    # The correctness half. `currentToolBubble` was cleared only at a round
    # boundary, so it outlived the card it pointed at and any later event with
    # no card of its own was handed that node.
    branch = _CHAT[_CHAT.index("} else if (json.type === 'tool_output') {"):]
    branch = branch[:branch.index("} else if (json.type === 'doc_stream_open') {")]
    assert "currentToolBubble = null;" in branch, (
        "the pointer survives the card, which is how a refusal came to rewrite "
        "a call that actually happened"
    )


def test_the_refusal_does_not_take_the_open_card_either():
    branch = _CHAT[_CHAT.index("} else if (json.type === 'tool_blocked') {"):]
    branch = branch[:branch.index("} else if (json.type === 'auto_escalated') {")]
    assert "currentToolBubble = null;" in branch
    assert "applyAgentThreadNode(bNode, blockedCardOptions(json));" in branch
    # Whole-line comments stripped first: the comment above this branch names
    # `currentToolBubble` to explain why it is not used, and matching prose
    # instead of code is how a test comes to describe a file (Law 20). It
    # failed that way first.
    before = "\n".join(
        line for line in branch.split("applyAgentThreadNode")[0].splitlines()
        if not line.strip().startswith("//")
    )
    assert "currentToolBubble" not in before, (
        "the refusal reaches for the open card before drawing its own"
    )


def test_compare_mode_had_this_right_all_along():
    # Cited in the fix's comment, so it is checked rather than remembered: the
    # main path adopted what compare mode already did.
    compare = (_REPO / "static" / "js" / "compare" / "stream.js").read_text(encoding="utf-8")
    assert "currentToolBlock = null;" in compare


# ── the card ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = tmp_path_factory.mktemp("blockedcard")
    (d / "ui.js").write_text(_UI_STUB, encoding="utf-8")
    shutil.copy(_MODULE, d / "agentThread.js")
    return d


def _card(sandbox: Path, event: dict) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text(
        "const m = await import('./agentThread.js');\n"
        + textwrap.dedent(f"""
        const opts = m.blockedCardOptions({json.dumps(event)});
        console.log(JSON.stringify({{ html: m.agentThreadNodeHtml(opts), opts }}));
        """),
        encoding="utf-8",
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_the_card_says_what_was_refused_and_why(sandbox):
    out = _card(sandbox, {"tool": "bash", "round": 2, "command": "rm -rf /tmp/x",
                          "reason": "The shell is switched off for this chat."})
    assert "Terminal" in out["html"], "the card does not name the tool"
    assert "blocked" in out["html"]
    assert "rm -rf /tmp/x" in out["html"]
    assert "The shell is switched off for this chat." in out["html"]


def test_a_refusal_does_not_read_as_a_success(sandbox):
    out = _card(sandbox, {"tool": "bash", "round": 1, "command": "x", "reason": "no"})
    assert out["opts"]["ok"] is False
    assert "✓" not in out["html"]


def test_the_card_carries_its_round_like_every_other_one(sandbox):
    out = _card(sandbox, {"tool": "bash", "round": 3, "command": "x", "reason": "no"})
    assert 'title="Agent round 3"' in out["html"]


def test_a_refusal_with_no_reason_still_says_something(sandbox):
    # The reason comes from the policy and a policy can decline to give one.
    out = _card(sandbox, {"tool": "bash", "round": 1, "command": "x"})
    assert "refused by the current tool policy" in out["html"]


def test_the_reason_cannot_be_written_by_the_policy(sandbox):
    out = _card(sandbox, {"tool": "bash", "round": 1, "command": "x",
                          "reason": "<img src=x onerror=alert(1)>"})
    assert "<img" not in out["html"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in out["html"]


def test_the_full_command_is_still_reachable_on_a_refusal(sandbox):
    # `P4-09`. What was refused is exactly the thing a reader wants in full.
    out = _card(sandbox, {"tool": "bash", "round": 1, "command": "x" * 240,
                          "full_command": "x" * 400, "reason": "no"})
    assert "agent-thread-cmd-full" in out["html"]
