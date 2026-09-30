# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B921` — an agent turn's own compaction says how much, and a reload says so too.

When the foreground fallback policy is on, the chat route hands context shaping
to the agent loop (`defer_context_shaping`), and the loop compacts each
candidate's context itself (`maybe_compact`, in `_build_route_request_state`).
Its `compacted` notice, sent when a candidate commits output, carried
`context_length` alone, so the toast — live since `B904` — said *older messages
summarized* with no counts, where the route's own notice (`P4-13`) says how
many. And the route's `_apply_shaping_metrics` saw a context it had not
compacted, so the saved record never said the turn was compacted at all: the
reload said less than the live stream.

Now `maybe_compact` records what it measured in the plan it hands back, the
loop's notice carries those figures through the route's builder
(`compacted_frame`), the loop's metrics carry `context_compacted` and the
figures, and the notice is one of the turn's notes (`B915`'s `AgentNotes`), so
the reload draws it as a line where it happened, in the toast's words.

Everything here runs code (`Law 20`): the real `maybe_compact` (only the
summarising model is scripted), the real `stream_agent_loop`, the route and the
real save, the real `addMessage`, and the live arm cut out of `chat.js`.
"""

import asyncio
import json
import shutil
from types import SimpleNamespace

import pytest

import routes.chat_routes as chat_routes
import src.agent_loop as agent_loop
import src.context_compactor as context_compactor
from src.agent_stops import AgentNotes
from test_foreground_model_routing import (  # noqa: E402
    _COMPACTED_CONTEXT, _RouteRequest, _chat_stream_endpoint,
)
from test_a_reload_keeps_the_turns_notes import (  # noqa: E402,F401
    _page, _saved_through_route, sandbox,
)
from test_compaction_notice_js import _COMPACTED, _TRIMMED, _arm, _run as _run_arm  # noqa: E402

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _frames(chunks):
    out = []
    for chunk in chunks:
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                out.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    return out


def _conversation(n=8):
    """A conversation long enough to compact under the context set below."""
    return [
        {"role": "user" if i % 2 == 0 else "assistant",
         "content": f"Message {i}: " + "the build log says the linker failed again " * 6}
        for i in range(n)
    ]


def _compacting(monkeypatch):
    """The real `maybe_compact`, over a 200-token window, with the summarising
    model scripted. Returns what it was handed and what it returned, per call,
    so a case can hold the notice to what the compactor measured."""
    calls = []
    real = context_compactor.maybe_compact

    async def llm(*_a, **_k):
        return "The user is fixing a linker failure; the log was read twice."

    async def spy(*args, **kwargs):
        result = await real(*args, **kwargs)
        calls.append({"handed": list(args[3]), "returned": list(result[0]), "compacted": result[2]})
        return result

    monkeypatch.setattr(context_compactor, "get_context_length", lambda *_a, **_k: 200)
    monkeypatch.setattr(context_compactor, "llm_call_async", llm)
    monkeypatch.setattr(context_compactor, "resolve_endpoint", lambda *_a, **_k: (None, None, None))
    monkeypatch.setattr(agent_loop, "maybe_compact", spy)
    return calls


def _measured(call):
    """The four figures, counted the way the compactor counts them."""
    est = context_compactor.estimate_tokens
    return {
        "messages_before": len(call["handed"]), "messages_after": len(call["returned"]),
        "tokens_before": est(call["handed"]), "tokens_after": est(call["returned"]),
    }


def _loop(monkeypatch, *, answer=("delta", "The linker needs -lm."), max_rounds=1):
    """The real loop, shaping its own context (`defer_context_shaping`), with a
    scripted model: one round that answers, or one that fails after a token."""
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)

    async def fake_stream(candidates, messages, **kwargs):
        await kwargs["candidate_request_factory"](0, *candidates[0])
        yield f"data: {json.dumps({'delta': 'The linker '})}\n\n"
        if answer[0] == "error":
            yield f"event: error\ndata: {json.dumps({'status': 502})}\n\n"
            return
        yield f"data: {json.dumps({'delta': answer[1][len('The linker '):]})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    history = SimpleNamespace(history=list(_conversation()))

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model", _conversation(),
            history_session=history, max_rounds=max_rounds, relevant_tools={"bash"},
            defer_context_shaping=True, fallback_on_empty=False, _is_teacher_run=True)]

    return asyncio.run(drain())


# ── the compactor ───────────────────────────────────────────────────────────


def test_the_compactor_keeps_what_it_measured_in_the_plan_it_hands_back(monkeypatch):
    """The plan held the summary to apply, not the two lists it was measured
    between, so nothing downstream could say how much went."""
    _compacting(monkeypatch)
    state = {}
    handed = _conversation()
    returned, _, compacted = asyncio.run(context_compactor.maybe_compact(
        None, "http://local.test/v1", "m", handed, persist=False, compaction_state=state))
    assert compacted is True
    est = context_compactor.estimate_tokens
    assert {k: state[k] for k in context_compactor.SHAPING_FIGURES} == {
        "messages_before": 8, "messages_after": len(returned),
        "tokens_before": est(handed), "tokens_after": est(returned)}
    assert state["messages_after"] < state["messages_before"]
    assert state["tokens_after"] < state["tokens_before"]
    assert context_compactor.compaction_figures(state) == {
        k: state[k] for k in context_compactor.SHAPING_FIGURES}


# ── the loop ────────────────────────────────────────────────────────────────


def test_the_loops_notice_says_how_much_was_summarised(monkeypatch):
    """The row, live half: the notice the loop sends when the answering
    candidate commits carries what `maybe_compact` measured, in the shape the
    route's own notice has (`P4-13`)."""
    calls = _compacting(monkeypatch)
    frames = _frames(_loop(monkeypatch))
    assert [c["compacted"] for c in calls] == [True]
    [notice] = [f for f in frames if f.get("type") == "compacted"]
    assert set(notice) == {"type", "data", "context_length"}, notice
    assert notice["data"] == {"context_length": notice["context_length"], **_measured(calls[0])}
    kinds = [f.get("type") or "delta" for f in frames]
    assert kinds.index("compacted") < kinds.index("delta"), "the notice came after the answer began"


def test_the_loops_metrics_say_the_turn_was_compacted(monkeypatch):
    """The row, saved half: the record the reply is saved from."""
    calls = _compacting(monkeypatch)
    frames = _frames(_loop(monkeypatch))
    [metrics] = [f["data"] for f in frames if f.get("type") == "metrics"]
    m = _measured(calls[0])
    assert metrics["context_compacted"] is True
    assert (metrics["context_messages_before_compact"], metrics["context_messages_after_compact"],
            metrics["context_tokens_before_compact"], metrics["context_tokens_after_compact"]) == (
        m["messages_before"], m["messages_after"], m["tokens_before"], m["tokens_after"])


def test_a_turn_that_fails_after_compacting_is_saved_saying_so(monkeypatch):
    """A turn that ends in `agent_terminal` is saved from that frame's record,
    not from the final metrics."""
    calls = _compacting(monkeypatch)
    frames = _frames(_loop(monkeypatch, answer=("error", None)))
    [terminal] = [f["data"] for f in frames if f.get("type") == "agent_terminal"]
    assert terminal["context_compacted"] is True
    assert terminal["context_tokens_after_compact"] == _measured(calls[0])["tokens_after"]


def test_a_turn_the_loop_did_not_compact_claims_nothing(monkeypatch):
    monkeypatch.setattr(context_compactor, "get_context_length", lambda *_a, **_k: 1_000_000)
    frames = _frames(_loop(monkeypatch))
    assert not [f for f in frames if f.get("type") == "compacted"]
    [metrics] = [f["data"] for f in frames if f.get("type") == "metrics"]
    assert not [k for k in metrics if "compact" in k], metrics


# ── the route and the save ──────────────────────────────────────────────────


def test_the_loops_compaction_is_saved_with_the_reply(monkeypatch):
    """Through `/api/chat_stream` and the real `save_assistant_response`: the
    notice is kept as one of the turn's notes, before the first round, and the
    metrics keep the figures — `_apply_shaping_metrics` no longer has the last
    word on a context it did not shape."""
    calls = _compacting(monkeypatch)
    chunks = _loop(monkeypatch)
    [saved] = _saved_through_route(monkeypatch, chunks)
    m = _measured(calls[0])
    [note] = saved["agent_notes"]
    assert note["type"] == "compacted" and note["round"] == 0, note
    assert {k: note["data"][k] for k in m} == m
    assert saved["context_compacted"] is True
    assert saved["context_messages_after_compact"] == m["messages_after"]


def test_the_routes_own_compaction_of_an_agent_turn_is_saved_too(monkeypatch):
    """Without the fallback policy the route compacts before the loop starts
    (`ctx.was_compacted`), and its notice is drawn live (`P4-13`). Kept here as
    well, or a reload would say it for one policy and not the other."""
    import core.database as database
    from routes.chat_helpers import save_assistant_response

    captured = {}
    chunks = [
        'data: {"delta": "Done."}\n\n',
        'data: {"type": "metrics", "data": {"round_texts": ["Done."]}}\n\n',
        "data: [DONE]\n\n",
    ]
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured, agent_chunks=chunks,
                                     context_overrides=dict(_COMPACTED_CONTEXT))
    monkeypatch.setattr(chat_routes, "save_assistant_response", save_assistant_response)
    monkeypatch.setattr(database, "update_session_last_accessed", lambda sid: None, raising=False)

    async def go():
        response = await endpoint(_RouteRequest("agent"))
        return [c async for c in response.body_iterator]

    out = _frames(asyncio.run(go()))
    [live] = [f for f in out if f.get("type") == "compacted"]
    [saved] = [msg.metadata for msg in captured["added_messages"]]
    assert saved["agent_notes"] == [dict(live, round=0)]
    assert live["data"]["messages_before"] == 40 and live["data"]["tokens_after"] == 6400


def test_a_compaction_is_placed_before_the_round_it_shaped():
    """Sent when a candidate commits output — at the start of the round whose
    request it shaped — so it is drawn after the round before, or before the
    first. A teacher's record puts the student's and the teacher's first-round
    compactions before the teacher's rounds, in the order they happened."""
    frame = {"type": "compacted", "data": {"context_length": 8192}, "context_length": 8192}
    notes = AgentNotes()
    for f in (frame, {"type": "agent_step", "round": 2}, dict(frame, context_length=4096)):
        notes.observe(f)
    assert [(n["round"], n["context_length"]) for n in notes.saved()] == [(0, 8192), (1, 4096)]

    taken = AgentNotes()
    for f in (frame, {"type": "teacher_takeover", "teacher_model": "big"},
              dict(frame, teacher=True, context_length=4096),
              {"type": "metrics", "teacher": True, "data": {}}):
        taken.observe(f)
    assert [(n["type"], n["round"]) for n in taken.saved()] == [
        ("compacted", 0), ("teacher_takeover", 0), ("compacted", 0)]


# ── the browser ─────────────────────────────────────────────────────────────

#: `B915`'s page, with a compaction's line said as `compacted:<its words>`.
_SHAPE = """
const shapeC = () => shape().map((s, i) => (s === 'context-compacted-note'
  ? 'compacted:' + text(history.children[i]) : s));
"""


def _pageC(sandbox, body: str) -> dict:
    return _page(sandbox, _SHAPE + body)


@node_only
def test_the_loops_notice_draws_the_counts_live():
    """The live arm, cut out of `chat.js` and run over the loop's real notice:
    the toast says how much, as the route's always has."""
    frame = context_compactor.compacted_frame(8192, {
        "messages_before": 8, "messages_after": 5, "tokens_before": 1480, "tokens_after": 560})
    [toast] = _run_arm(_arm(_COMPACTED, _TRIMMED), [[frame, False]])
    assert toast == "Context compacted — older messages summarized (5/8 messages kept, 1,480 → 560 tokens)"


@node_only
def test_a_reload_draws_the_compaction_where_it_happened(monkeypatch, sandbox):
    """The row's `Verify:`, end to end: the real loop compacts, the route saves
    the reply, and the real `addMessage` draws the counts above the answer."""
    calls = _compacting(monkeypatch)
    [saved] = _saved_through_route(monkeypatch, _loop(monkeypatch))
    m = _measured(calls[0])
    out = _pageC(sandbox, """
        addMessage('assistant', 'The linker needs -lm.', 'small-local-model', %s);
        const notes = history.children.filter((n) => String(n.className).includes('context-compacted-note'));
        console.log(JSON.stringify({ shape: shapeC(), note: notes.map(text),
                                     role: notes.map((n) => n.getAttribute('role')),
                                     errors: globalThis.errors }));
    """ % json.dumps(saved))
    assert out["errors"] == []
    expected = (f"Context compacted — older messages summarized ({m['messages_after']}/"
                f"{m['messages_before']} messages kept, {m['tokens_before']:,} → "
                f"{m['tokens_after']:,} tokens)")
    assert out["note"] == [expected], out
    assert out["role"] == ["note"]
    assert out["shape"] == ["compacted:" + expected, "msg:The linker needs -lm."], out["shape"]


@node_only
def test_a_compaction_in_a_later_round_is_drawn_between_the_rounds(sandbox):
    out = _pageC(sandbox, """
        addMessage('assistant', 'reply', 'm', {
          round_texts: ['Reading the log.', 'It needs -lm.'],
          tool_events: [{ round: 1, tool: 'bash', command: 'cat build.log', output: 'ld: error', exit_code: 0 }],
          agent_notes: [{ type: 'compacted', context_length: 8192, round: 1,
                          data: { context_length: 8192, messages_before: 12, messages_after: 6,
                                  tokens_before: 7000, tokens_after: 2100 } }],
        });
        console.log(JSON.stringify({ shape: shapeC() }));
    """)
    assert out["shape"] == [
        "msg:Reading the log.", "thread",
        "compacted:Context compacted — older messages summarized (6/12 messages kept, 7,000 → 2,100 tokens)",
        "msg:It needs -lm.",
    ], out["shape"]


@node_only
def test_a_direct_reply_saved_with_only_the_note_keeps_its_text(sandbox):
    """An agent turn answered before any step ran — a one-line direct reply —
    is saved with no rounds. Its note sends the reload down the branch that
    draws rounds, which drew the note and dropped the reply."""
    out = _pageC(sandbox, """
        addMessage('assistant', 'You are welcome.', 'm', {
          direct_low_signal: true,
          agent_notes: [{ type: 'compacted', context_length: 8192, round: 0, data: { context_length: 8192 } }],
        });
        console.log(JSON.stringify({ shape: shapeC() }));
    """)
    assert out["shape"] == [
        "compacted:Context compacted — older messages summarized",
        "msg:You are welcome.",
    ], out["shape"]
