# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-11` — the agent round, from the loop to the badge on the card.

The number was on the wire from the first version of the agent loop and never
reached a card. Every `json.round` read in `chat.js` belonged to Deep Research
progress instead, so a thread of nine tool cards gave the reader no way to see
that it was three passes of three rather than one pass of nine.

Three things were wrong underneath the missing badge, and each has a test here
that fails without its fix:

  **the streamed result card had no round at all.** `tool_start` carried one and
  the *persisted* `tool_event` carried one, but the `tool_output` between them
  did not — the same event answered the question after a reload and refused to
  answer it live.

  **the approved action claimed round 0.** Four sites hardcoded it: the
  continuation's `tool_start`, its `tool_progress`, its result card and its
  persisted twin. An action the user personally authorised is the one card in
  the thread most worth locating, and it named a round no other card has.

  **the one-shot image path sent no round.** It never enters the agent loop, so
  there was nothing to send; its round is 1 and stays 1, stated rather than
  omitted so its card carries the same badge as every other tool card.

The badge itself is `roundBadgeHtml` in the one builder (`P4-01`), so it is one
change rather than six — and the tests below drive that builder with `node`
rather than reading the file, because a test that greps a file is testing the
file (Law 20).
"""

import asyncio
import json
import re
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


# ── the badge ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = tmp_path_factory.mktemp("roundbadge")
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


def test_a_card_shows_the_round_it_belongs_to(sandbox):
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True, "round": 3})
    assert 'class="agent-thread-round"' in html
    assert ">3<" in html


def test_the_badge_says_out_loud_what_the_number_means(sandbox):
    # Law 15. A bare integer floating beside a tool name is a puzzle; the
    # tooltip is the whole of the explanation this badge gets, so it has to be
    # there. The owner left a competitor over exactly this kind of gap.
    html = _card(sandbox, {"tool": "bash", "state": "running", "round": 7})
    assert 'title="Agent round 7"' in html


def test_a_card_with_no_round_draws_no_badge(sandbox):
    # The document writer's own card is not a tool call and has no round.
    html = _card(sandbox, {"tool": "", "state": "running", "label": "Writing"})
    assert "agent-thread-round" not in html


@pytest.mark.parametrize("value", [0, -1, "", None, "three", 2.5, [], {}])
def test_nothing_that_is_not_a_round_becomes_a_badge(sandbox, value):
    # `0` is the one that matters: it is what four sites used to hardcode, and
    # rendering it would have turned a wrong number into a visible one.
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True, "round": value})
    assert "agent-thread-round" not in html, f"{value!r} drew a badge"


def test_a_round_arriving_as_a_string_still_reads_as_that_round(sandbox):
    # JSON from a future emit site, or a hand-built replay event. `3` and `"3"`
    # are the same round and must not disagree on screen.
    assert ">3<" in _card(sandbox, {"tool": "bash", "state": "done", "ok": True, "round": "3"})


def test_a_running_card_keeps_its_round_when_the_result_lands(sandbox):
    # The card is built twice — once from `tool_start`, once from `tool_output`
    # — so letting the second event decide the badge means the badge can vanish
    # the moment the tool finishes. Same class of bug as losing `open`.
    out = _node(sandbox, """
        const node = { className: '', innerHTML: '',
                       classList: { contains: (c) => node.className.split(' ').includes(c) } };
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'running', round: 4 });
        const running = node.innerHTML;
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'done', ok: true });
        console.log(JSON.stringify({ running, done: node.innerHTML }));
    """)
    assert ">4<" in out["running"]
    assert ">4<" in out["done"], "the badge disappeared when the tool finished"


def test_a_later_event_may_still_correct_the_round(sandbox):
    # Remembering the round must not freeze it: an event that brings a round
    # wins over the one the card was opened with.
    out = _node(sandbox, """
        const node = { className: '', innerHTML: '',
                       classList: { contains: (c) => node.className.split(' ').includes(c) } };
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'running', round: 4 });
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'done', ok: true, round: 5 });
        console.log(JSON.stringify({ html: node.innerHTML }));
    """)
    assert ">5<" in out["html"] and ">4<" not in out["html"]


def test_the_badge_cannot_be_written_by_the_event(sandbox):
    # `roundBadgeHtml` interpolates without escaping, so it may only ever
    # receive a number it has already proved is a number.
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True,
                           "round": '1"><img src=x onerror=alert(1)>'})
    assert "<img" not in html and "onerror" not in html


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


def _patch(monkeypatch, model_replies, *, progress=()):
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default,
                        raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(),
                        raising=False)
    replies = iter(model_replies)

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *args, **kwargs):
        cb = kwargs.get("progress_cb")
        if cb is not None:
            for payload in progress:
                await cb(dict(payload))
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)


def _of_type(events, event_type):
    return [e for e in events if e.get("type") == event_type]


def _persisted(events):
    metrics = next(e for e in events if e.get("type") == "metrics")
    return metrics["data"].get("tool_events") or []


def _approved_run(monkeypatch, *, requested_round, progress=()):
    """Drive the continuation a user's approval click resumes into."""
    store = ToolApprovalStore()
    pending = store.create(
        owner="alice",
        session_id="session-1",
        origin_run_id="run-1",
        tool_name="bash",
        content="printf hi",
        workspace=None,
        external_untrusted_context_seen=True,
        requested_round=requested_round,
        capabilities=capabilities_for_action("bash", "printf hi"),
    )
    grant = store.consume(pending.approval_id, decision="approve",
                          owner="alice", session_id="session-1")
    assert grant is not None
    _patch(monkeypatch, ["Ran it."], progress=progress)
    return _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1",
            "small-local-model",
            [{"role": "user", "content": "yes, go ahead"}],
            max_rounds=1,
            owner="alice",
            session_id="session-1",
            workspace=None,
            relevant_tools=set(pending.selected_tools),
            exact_approval=grant,
        )
    )


def test_the_live_result_card_names_the_same_round_the_reloaded_one_does(monkeypatch):
    # The defect, stated as the invariant it breaks: `tool_output` had no round
    # while `tool_start` and the persisted `tool_event` both did, so the same
    # action answered "which round?" differently depending on whether you were
    # watching it or coming back to it.
    _patch(monkeypatch, ["```bash\nprintf hi\n```"])
    events = _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "do the thing"}],
            max_rounds=2, relevant_tools={"bash"},
        )
    )
    start = _of_type(events, "tool_start")[0]
    output = _of_type(events, "tool_output")[0]
    persisted = _persisted(events)[0]
    assert start["round"] == output["round"] == persisted["round"] == 1


def test_an_approved_action_carries_the_round_it_was_asked_for(monkeypatch):
    # The user clicked approve on a card that said round 6. The card reporting
    # what happened has to say 6 too, or the two do not read as one action.
    events = _approved_run(monkeypatch, requested_round=6)
    assert _of_type(events, "tool_start")[0]["round"] == 6
    assert _of_type(events, "tool_output")[0]["round"] == 6
    assert _persisted(events)[0]["round"] == 6


def test_an_approved_action_reports_progress_from_the_same_round(monkeypatch):
    events = _approved_run(monkeypatch, requested_round=6,
                           progress=[{"message": "working"}])
    progress = _of_type(events, "tool_progress")
    assert progress, "the progress relay produced nothing to check"
    assert all(e["round"] == 6 for e in progress)


def test_no_approved_event_claims_round_zero(monkeypatch):
    # The literal that was there. A round below 1 is not a round, and this is
    # the assertion that fails if any of the four sites regrows the hardcode.
    events = _approved_run(monkeypatch, requested_round=6,
                           progress=[{"message": "working"}])
    streamed = [e for e in events
                if e.get("type") in {"tool_start", "tool_progress", "tool_output"}]
    assert streamed
    for event in streamed + _persisted(events):
        assert event.get("round", 0) >= 1, event


def test_a_grant_sealed_before_the_field_existed_still_names_a_round(monkeypatch):
    # `requested_round` defaults to 0, and the store is in memory, so this is
    # the shape of a pending approval created by a build that predates it. The
    # fallback is 1: something ran, and no run has a round below 1.
    events = _approved_run(monkeypatch, requested_round=0)
    assert _of_type(events, "tool_start")[0]["round"] == 1
    assert _persisted(events)[0]["round"] == 1


# ── the record that carries it ────────────────────────────────────────────────


def _pending(**kwargs):
    store = ToolApprovalStore()
    return store, store.create(
        owner="alice",
        session_id="session-1",
        origin_run_id="run-1",
        tool_name="bash",
        content="printf hi",
        workspace=None,
        external_untrusted_context_seen=False,
        capabilities=capabilities_for_action("bash", "printf hi"),
        **kwargs,
    )


def test_the_requested_round_survives_the_seal_and_the_consume(monkeypatch):
    store, pending = _pending(requested_round=9)
    assert pending.requested_round == 9
    grant = store.consume(pending.approval_id, decision="approve",
                          owner="alice", session_id="session-1")
    assert grant.pending.requested_round == 9


@pytest.mark.parametrize("value, expected", [
    (0, 0), (None, 0), (-3, 0), ("", 0), ("nine", 0), (2.9, 2), ("4", 4), (True, 1),
])
def test_only_a_positive_integer_survives_as_a_round(value, expected):
    _, pending = _pending(requested_round=value)
    assert pending.requested_round == expected


def test_the_round_is_outside_the_seal_on_purpose():
    # It is a display integer with no bearing on what runs. Widening the digest
    # for a badge would change the seal's meaning for a cosmetic reason, so the
    # binding check must be indifferent to it — and this is the test that says
    # that was a decision rather than an oversight.
    store, pending = _pending(requested_round=9)
    grant = store.consume(pending.approval_id, decision="approve",
                          owner="alice", session_id="session-1")
    assert grant.matches(owner="alice", session_id="session-1",
                         tool_name="bash", content="printf hi", workspace=None)

    _, plain = _pending(requested_round=0)
    assert plain.digest == pending.digest, (
        "the round changed the binding digest — it must not"
    )


def test_the_round_cannot_smuggle_a_different_action_past_the_binding():
    # The other half of "outside the seal": being outside it must not make the
    # seal weaker. Content still decides.
    store, pending = _pending(requested_round=9)
    grant = store.consume(pending.approval_id, decision="approve",
                          owner="alice", session_id="session-1")
    assert not grant.matches(owner="alice", session_id="session-1",
                            tool_name="bash", content="rm -rf /", workspace=None)


# ── the callers ───────────────────────────────────────────────────────────────


def _calls(text: str) -> list[str]:
    """Every `applyAgentThreadNode(...)` call in `text`, source and all."""
    calls, rest = [], text
    needle = "applyAgentThreadNode("
    while needle in rest:
        i = rest.index(needle)
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


# A call whose options come from a named `*CardOptions` builder is exempt: the
# builder is a pure function with its own tests, and those assert the round and
# the approval it produces. Naming the exempt builders one at a time meant this
# list needed editing on every new card kind — three times in one day — which is
# a rule stated in the wrong place.
_OPTIONS_BUILDER = re.compile(r"\b\w+CardOptions\(")


@pytest.mark.parametrize("rel, expected", [
    ("static/js/chat.js", 5),
    ("static/js/chatRenderer.js", 2),
    ("static/js/compare/stream.js", 2),
])
def test_every_card_built_from_an_event_is_handed_that_event_s_round(rel, expected):
    # The builder can only draw a badge it is given. `P4-01` left six call
    # sites; five render a tool event and must pass its round, and the sixth is
    # the document writer's own card, which is not a tool call and has none.
    calls = _calls((_REPO / rel).read_text(encoding="utf-8"))
    assert len(calls) == expected, f"{rel} has {len(calls)} calls, expected {expected}"
    for call in calls:
        if _OPTIONS_BUILDER.search(call):
            continue
        if "tool: ''" in call or 'tool: ""' in call:
            assert "round:" not in call, (
                f"{rel}: the document writer's card has no round to name"
            )
            continue
        assert "round:" in call, (
            f"{rel} builds a card from an event without passing its round: {call}"
        )
        value = call.split("round:", 1)[1].split(",")[0].strip()
        assert not value.rstrip("}").strip().isdigit(), (
            f"{rel} passes a hardcoded round {value!r}; it must come from the event"
        )


# ── the whole round trip ──────────────────────────────────────────────────────


def _gate_at_round_two(monkeypatch, session_id):
    """Drive the real gate until it asks, on round 2 rather than round 1.

    Round 1 reads a file — `read_workspace` alone, which the gate lets past even
    with untrusted context in the run — and round 2 asks for a shell, which it
    does not. Reaching round 2 is the whole point: a run gated on round 1 cannot
    tell a carried round from a hardcoded 1, which is exactly the mutation that
    survived until this test existed.
    """
    _patch(monkeypatch, ["```read_file\nnotes.txt\n```", "```bash\nrm -rf /tmp/x\n```"])
    return _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "do the thing"}],
            max_rounds=3, owner="alice", session_id=session_id, workspace=None,
            relevant_tools={"read_file", "bash"},
            external_untrusted_context_seen=True,
        )
    )


def test_the_gate_records_the_round_it_asked_in(monkeypatch):
    from src.tool_approvals import tool_approval_store

    events = _gate_at_round_two(monkeypatch, "round-trip-1")
    ask = next(e for e in events if e.get("type") == "ask_user")
    pending = tool_approval_store._pending[ask["data"]["approval_id"]]
    assert pending.requested_round == 2, (
        "the gate sealed a round that is not the one it interrupted"
    )


def test_the_card_that_asked_and_the_card_that_answers_name_one_round(monkeypatch):
    # The user story, end to end. They were shown a card in round 2 and clicked
    # approve; the continuation is a separate run whose own loop starts at 1,
    # and every card it writes about that action has to keep saying 2.
    from src.tool_approvals import tool_approval_store

    asked = _gate_at_round_two(monkeypatch, "round-trip-2")
    ask = next(e for e in asked if e.get("type") == "ask_user")
    blocked = [e for e in asked
               if e.get("type") == "tool_output" and e.get("tool") == "bash"]
    assert blocked and blocked[0]["round"] == 2

    grant = tool_approval_store.consume(
        ask["data"]["approval_id"], decision="approve",
        owner="alice", session_id="round-trip-2",
    )
    assert grant is not None
    _patch(monkeypatch, ["Ran it."])
    resumed = _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "yes, go ahead"}],
            max_rounds=1, owner="alice", session_id="round-trip-2", workspace=None,
            relevant_tools=set(grant.pending.selected_tools),
            exact_approval=grant,
        )
    )
    assert _of_type(resumed, "tool_start")[0]["round"] == 2
    assert _of_type(resumed, "tool_output")[0]["round"] == 2
    assert _persisted(resumed)[0]["round"] == 2
