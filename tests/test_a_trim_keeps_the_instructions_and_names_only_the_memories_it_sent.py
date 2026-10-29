# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1651` and `B1650` — what a trim keeps, and what the turn then says it used.

Both found while doing `B1572` (`D-2026-10-29-01` §4, *"Keep 24k, name the
cut"*), in the same measured turn: Agent mode, a model whose window nothing
proves, one saved memory, and 24,000 characters of attachments against the
6,000-token input budget.

**`B1651`, measured before:** `trim_for_context` cut the leading system message
— the agent's own instructions, its tool rules among them — from 7,173
characters to its first 2,045 while 14,478 characters of the attachments were
still sent, and nothing said the instructions were cut. Now the person's
message gives way first (it keeps its beginning and end, and says so to the
model), and the instructions are cut only when the message would have to keep
less than they would; when they are, the line says so (*the end of its
instructions*).

**`B1650`, measured before:** in a turn whose trim left out the saved memory,
the stream's `memories_used` frame and the saved reply's `memories_used` both
named the memory the model never received, so the pill under the reply said it
was used. Now the loop's `context_trimmed` notice names the memories no
request carried, and the route takes them off the turn's list — a second
`memories_used` frame live, and the saved reply — so no pill names it.

Driven (`Law 20`) as `B1572`'s turn is: `capture.Server` boots this checkout's
`app.py`, `demo_model.DemoModel` answers under a name no table knows and keeps
every request, the saved reply comes back through `GET /api/history/{id}`, and
the pill is the real `createMsgFooter` / `addMessage` under node, fed by the
live stream's own `memories_used` arm. The trim's order and the chat-mode doors
are driven through the real `trim_for_context`, `build_chat_context` and the
fallback chain's request factory.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from src.context_compactor import (
    PASTED_MESSAGE_CUT_NOTICE, PROMPT_CUT_NOTICE, trim_for_context, trim_left_out,
)
from src.model_context import estimate_tokens
from src.prompt_security import own_context_message
from test_an_agent_turn_trimmed_to_fit_says_what_it_left_out import MEMORY, MODEL, WORDS, world  # noqa: F401
from test_a_turns_pills_reach_its_footer_live import _between, _run, _run_turn, sandbox  # noqa: F401

import demo_model  # noqa: E402  (on the path the B1572 module put it on)
import seed  # noqa: E402

#: An input budget small enough that the instructions cannot stay whole.
TIGHT = 3000
INSTRUCTIONS_CUT = "the end of its instructions"
MESSAGE_CUT = "the middle of your message"


def _turn(world, *, files=0, budget=None):
    """One Agent-mode turn: its frames, the messages the model was first sent,
    and the saved reply's record. `budget` sets the agent input budget for the
    turn and puts the default back after."""
    client, ep, log = world
    if budget:
        seed._ok(client.post("/api/auth/settings", json={"agent_input_token_budget": budget}), "budget")
    try:
        sess = seed._ok(client.post("/api/session", data={"endpoint_id": ep, "model": MODEL}), "chat")
        sid = sess.get("session_id") or sess.get("id")
        form = {"message": WORDS, "session": sid, "mode": "agent", "plan_mode": "false",
                "selected_model": MODEL, "selected_endpoint_id": ep,
                "allow_bash": "false", "allow_web_search": "false"}
        if files:
            parts = [("files", (f"part{i}.txt", (f"FILE{i}:" + chr(65 + i) * 11_993).encode(), "text/plain"))
                     for i in range(files)]
            up = seed._ok(client.post("/api/upload", files=parts, data={"session_id": sid}), "upload")
            form["attachments"] = json.dumps([f["id"] for f in up["files"]])
        start = len(log)
        resp = client.post("/api/chat_stream", data=form)
        assert resp.status_code == 200, resp.text[:300]
    finally:
        if budget:
            seed._ok(client.post("/api/auth/settings", json={"agent_input_token_budget": 6000}), "budget")
    events = list(seed._sse_events(resp.text))
    asked = [e for e in log[start:] if e.get("stream")]
    assert asked, "the model was never asked"
    sent = [{"role": m.get("role"), "text": demo_model._text(m.get("content"))} for m in asked[0]["messages"]]
    history = seed._ok(client.get(f"/api/history/{sid}"), "history")["history"]
    [reply] = [h.get("metadata") or {} for h in history if h.get("role") == "assistant"]
    return events, sent, reply


@pytest.fixture(scope="module")
def crowded(world):
    return _turn(world, files=2)


@pytest.fixture(scope="module")
def tight(world, crowded):
    return _turn(world, files=2, budget=TIGHT)


def _trim(events):
    [trim] = [e for e in events if e.get("type") == "context_trimmed"]
    return trim["data"]


def _instructions(sent):
    return next(m["text"] for m in sent if m["role"] == "system")


def _persons(sent):
    return next(m["text"] for m in reversed(sent) if m["role"] == "user" and m["text"].startswith(WORDS))


def _memory_frames(events):
    return [e["data"] for e in events if e.get("type") == "memories_used"]


def _names_the_memory(memories):
    return any(MEMORY in str(m.get("text")) for m in memories or [])


# ── `B1651` · the instructions survive, the attachments give way ────────────

def test_on_an_unproven_window_the_attachments_give_way_and_the_instructions_survive(crowded, tight):
    """The row's `Verify:` — *on that turn the tool instructions survive and
    the attachments give way*. The instructions are the ones the tight turn's
    trim cuts (their first 2,000 characters are the same), and here they reach
    the model whole: the cut is the only thing that shortens them, and it says
    so where it cuts."""
    events, sent, reply = crowded
    rules = _instructions(sent)
    assert PROMPT_CUT_NOTICE.strip() not in rules
    assert len(rules) > 7000, len(rules)
    assert _instructions(tight[1])[:2000] == rules[:2000], "premise: the same instructions"
    theirs = _persons(sent)
    assert PASTED_MESSAGE_CUT_NOTICE.strip() in theirs, "the message says it was shortened"
    # Its beginning (the words and the first file) and its end (the second
    # file's last characters) are kept; the middle gave way.
    assert theirs.startswith(WORDS + "\n=== File: part0.txt ===") and "B" * 200 in theirs
    assert 2000 < len(theirs) < 14_478, len(theirs)
    trim = _trim(events)
    assert trim["left_out"] == [MESSAGE_CUT], trim
    assert reply.get("context_trim_left_out") == [MESSAGE_CUT]


def test_when_the_instructions_must_be_cut_the_line_says_so(tight):
    """The row's `Verify:`, its other half — *or the reply says the
    instructions were cut*: a budget the instructions cannot fit whole."""
    events, sent, reply = tight
    assert _instructions(sent).endswith(PROMPT_CUT_NOTICE.strip())
    trim = _trim(events)
    assert trim["left_out"] == [INSTRUCTIONS_CUT, "your saved memory", MESSAGE_CUT], trim
    assert reply.get("context_trim_left_out") == trim["left_out"]


# ── `B1650` · a memory the trim left out is not listed as used ──────────────

def test_a_memory_the_trim_left_out_is_not_listed_as_used(tight):
    events, sent, reply = tight
    assert MEMORY not in "\n".join(m["text"] for m in sent), "premise: the trim left the memory out"
    frames = _memory_frames(events)
    assert _names_the_memory(frames[0]), "premise: the turn named it before the loop trimmed"
    assert frames[-1] == [], frames
    trim = _trim(events)
    assert [m["text"] for m in trim["memories_left_out"]] == [
        f"The code word for the garden shed is {MEMORY}."], trim
    order = [e.get("type") for e in events]
    last_named = len(order) - 1 - order[::-1].index("memories_used")
    first_word = next(i for i, e in enumerate(events) if "delta" in e)
    assert order.index("context_trimmed") < last_named < first_word, "said before the reply it shaped"
    assert not _names_the_memory(reply.get("memories_used")), reply.get("memories_used")


def test_a_memory_that_was_sent_is_still_listed(crowded):
    events, sent, reply = crowded
    assert MEMORY in "\n".join(m["text"] for m in sent)
    assert _names_the_memory(_memory_frames(events)[-1])
    assert "memories_left_out" not in _trim(events)
    assert _names_the_memory(reply.get("memories_used"))


_MEMORIES_ARM = ("} else if (json.type === 'memories_used') {", "} else if (json.type === 'skills_injected') {")


def _pill(sandbox, events, reply):  # noqa: F811
    """The pill under the reply: live, with the stream's own `memories_used`
    arm fed this turn's frames and the end-of-stream footer; and after a reload,
    `addMessage` with the saved record."""
    arm = _between(*_MEMORIES_ARM)
    footer = _between("const footerTarget =", "if (_generatedImagesForTurn.length", keep_opening=True)
    frames = [e for e in events if e.get("type") == "memories_used"]
    live = _run_turn(sandbox, """
        const _isBg = false;
        for (const json of %s) { for (const _ of [0]) { %s } }
        %s
        console.log(JSON.stringify({ pills: pills(second) }));
    """ % (json.dumps(frames), arm, footer))
    reloaded = _run(sandbox, "", """
        import { history } from './shim.js';
        const { addMessage } = await import('./chatRenderer.js');
        addMessage('assistant', 'OK.', %s, %s);
        const last = history.children[history.children.length - 1];
        const f = last.querySelector('.msg-footer');
        console.log(JSON.stringify({ pill: !!(f && f.querySelector('.memory-used-pill')) }));
    """ % (json.dumps(MODEL), json.dumps(reply)))
    return "memory-used-pill" in live["pills"], reloaded["pill"]


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="node binary not on PATH")
def test_the_pill_is_drawn_only_for_a_memory_that_was_sent(crowded, tight, sandbox):  # noqa: F811
    """The row's `Verify:` — *shows no pill for it* — live and after a reload,
    with the turn that sent it as the control."""
    assert _pill(sandbox, crowded[0], crowded[2]) == (True, True)
    assert _pill(sandbox, tight[0], tight[2]) == (False, False)


# ── the trim's order, through the real `trim_for_context` ───────────────────

#: Instructions of the measured length, a memory block shaped as the chat
#: builds it, and the person's message with 24,000 characters attached.
RULES = "TOOLS: " + ("call a tool like this. " * 311) + "END-OF-TOOLS"
MINE = WORDS + "\n=== File: part0.txt ===\n" + "A" * 12_000 + "\n=== File: part1.txt ===\n" + "B" * 12_000


def _measured(*extra):
    memory = own_context_message("saved memory: retrieved context", f"- The code word is {MEMORY}.")
    return [{"role": "system", "content": RULES}, memory, *extra, {"role": "user", "content": MINE}]


def test_the_persons_message_gives_way_before_the_instructions():
    assert 7000 < len(RULES) < 7300, "premise: the measured instructions' length"
    before = _measured()
    after = trim_for_context(before, 6000, reserve_tokens=1024)
    assert after[0] is before[0], "the instructions, untouched"
    assert after[1] is before[1], "the memory keeps the trimmer's old rule (`B1425`)"
    assert PASTED_MESSAGE_CUT_NOTICE in after[-1]["content"]
    assert estimate_tokens(after) <= 6000 - 1024
    assert trim_left_out(before, after) == [MESSAGE_CUT]


def test_in_a_later_round_the_persons_message_still_gives_way_first():
    """After a tool call the person's message is no longer the last one; it is
    still theirs that is shortened, and not dropped."""
    call = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]}
    result = {"role": "tool", "tool_call_id": "c1", "content": "file text"}
    before = [*_measured(), call, result]
    after = trim_for_context(before, 6000, reserve_tokens=1024)
    assert after[0] is before[0]
    assert [m.get("role") for m in after][-2:] == ["assistant", "tool"]
    shortened = next(m for m in after if m.get("role") == "user" and str(m.get("content")).startswith(WORDS))
    assert PASTED_MESSAGE_CUT_NOTICE in shortened["content"]


def test_the_message_keeps_at_least_what_the_instructions_would_and_then_the_cut_is_named():
    """A budget where the message would have to keep under 2,000 characters
    for the instructions to stay whole: the instructions are cut, as before,
    and the line names it first."""
    before = _measured()
    budget = estimate_tokens(before[:2]) + 400
    after = trim_for_context(before, budget, reserve_tokens=0)
    assert after[0]["content"].endswith(PROMPT_CUT_NOTICE)
    assert trim_left_out(before, after)[0] == INSTRUCTIONS_CUT


def test_short_instructions_are_never_cut_so_nothing_changes_for_them():
    before = [{"role": "system", "content": "You are helpful."}, *_measured()[1:]]
    after = trim_for_context(before, 1500, reserve_tokens=0)
    assert after[0] is before[0]
    assert INSTRUCTIONS_CUT not in trim_left_out(before, after)


# ── `B1650` on the chat-mode doors ──────────────────────────────────────────

def test_two_memories_with_one_text_are_told_apart_by_id():
    from src.agent_loop import memories_not_sent, memories_sent

    a = {"id": "m1", "text": "Prefers tea."}
    b = {"id": "m2", "text": "Prefers tea."}
    assert memories_not_sent([a, b], [a]) == [b], "matched by id, never by a shared text"
    assert memories_not_sent([{"id": None, "text": "Prefers tea."}], [a]) == []
    used = [{"id": "m1", "text": "Prefers tea.", "engine": "keyword"},
            {"id": "m2", "text": "Prefers tea.", "engine": "keyword"}]
    assert memories_sent(used, [b]) == used[:1]
    assert memories_sent(used, []) == used


class _KeepRealTrim:
    """`test_the_person_s_words_are_their_own_message._turn`'s monkeypatch,
    which lets the real trim and a small window stand."""

    def __init__(self, monkeypatch):
        self._mp = monkeypatch

    def setattr(self, target, name, value, *a, **k):
        if name in ("trim_for_context", "get_context_length", "maybe_compact"):
            return None
        return self._mp.setattr(target, name, value, *a, **k)


def test_a_chat_turn_trimmed_in_its_context_does_not_name_the_memory_it_left_out(monkeypatch):
    """Chat mode trims while it builds the turn, before the frame is sent."""
    from routes import chat_helpers
    from test_the_person_s_words_are_their_own_message import _turn as chat_turn

    pinned = "The code word for the garden shed is " + MEMORY + "."

    async def small_window(sess, endpoint_url, model, messages, headers, owner=None):
        return messages, 1500, False

    monkeypatch.setattr(chat_helpers, "maybe_compact", small_window)
    monkeypatch.setattr(chat_helpers, "get_context_length", lambda u, m: 1500)
    _msgs, ctx = chat_turn(_KeepRealTrim(monkeypatch), pinned=(pinned,), person_said="x" * 6000)
    assert ctx.context_trimmed and "your saved memory" in ctx.context_trim_left_out, \
        "premise: the trim left the memory out"
    assert not _names_the_memory(ctx.used_memories), ctx.used_memories
    _msgs, roomy = chat_turn(monkeypatch, pinned=(pinned,))
    assert _names_the_memory(roomy.used_memories), "control: a turn with room names it"


def test_a_fallback_candidates_trim_records_the_memory_it_left_out(monkeypatch):
    """With a fallback chain the trim happens per candidate, at request time;
    the candidate that answers says which memories its request left out, and
    the route takes them off before it saves the reply (`memories_sent`)."""
    import routes.chat_routes as chat_routes
    from src.chat_processor import _attach_memory_facts

    memory = _attach_memory_facts(
        own_context_message("saved memory: pinned context", f"- The code word is {MEMORY}."),
        [{"id": "m1", "text": f"The code word is {MEMORY}."}])
    messages = [{"role": "system", "content": "You are helpful."}, memory,
                {"role": "user", "content": "x" * 6000}]

    async def no_compaction(session, url, model, msgs, headers=None, **kw):
        return msgs, 1500, False

    monkeypatch.setattr(chat_routes, "maybe_compact", no_compaction)
    factory, state = chat_routes._chat_candidate_request_factory(messages, 1500, session=None, owner="ana")
    asyncio.run(factory(0, "http://box/v1", "m", {}))
    stats = state["trim_stats"][0]
    assert "your saved memory" in stats["left_out"], "premise: the trim left the memory out"
    assert stats["memories_left_out"] == [{"id": "m1", "text": f"The code word is {MEMORY}."}]
