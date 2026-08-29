"""P6-18 — mid-run steering.

The queue holds the NEXT message; a steer redirects the one IN FLIGHT. The
backend limit that shapes the whole feature is that `stream_agent_loop` binds
one provider request per round and cannot interrupt a round that is already
streaming, so a steer is *pending* until the next round boundary and *applied*
at it. These tests pin both halves:

  * the inbox contract (`submit_steer` / `take_steers` / `clear_steers` /
    `consume_steers_for_round`), which is what an HTTP handler talks to; and
  * the structural claim that the loop consumes at the top of each round,
    before the per-round request is built, and that a round-1 steer is not
    silently dropped by the pre-built `request_messages` pin.

The second half is an AST assertion rather than a grep: the ordering *is* the
correctness condition, and a text search cannot tell "called before" from
"appears earlier in the file".
"""

import ast

from pathlib import Path

import pytest

from src.agent_loop import (
    STEER_MAX_CHARS,
    STEER_MAX_PENDING,
    clear_steers,
    consume_steers_for_round,
    pending_steers,
    steer_directive,
    stream_agent_loop,
    submit_steer,
    take_steers,
)

_SID = "sess-steer-test"


@pytest.fixture(autouse=True)
def _clean_inbox():
    clear_steers(_SID)
    clear_steers("other")
    yield
    clear_steers(_SID)
    clear_steers("other")


# ── inbox contract ──────────────────────────────────────────────────────────

def test_submit_returns_a_verdict_not_a_bool():
    # Law 10: three things can happen and the caller must tell them apart.
    ok = submit_steer(_SID, "use the staging database, not prod")
    assert ok["accepted"] is True
    assert ok["pending"] == 1
    assert ok["applies_at"] == "next_round"


def test_empty_and_whitespace_steers_are_refused_with_a_reason():
    for junk in ("", "   ", "\n\t "):
        verdict = submit_steer(_SID, junk)
        assert verdict["accepted"] is False
        assert verdict["reason"] == "empty"
    assert pending_steers(_SID) == []


def test_a_steer_with_no_session_is_refused():
    assert submit_steer("", "anything")["accepted"] is False
    assert submit_steer(None, "anything")["accepted"] is False


def test_oversized_steer_is_refused_and_names_the_limit():
    verdict = submit_steer(_SID, "x" * (STEER_MAX_CHARS + 1))
    assert verdict["accepted"] is False
    assert verdict["reason"] == "too_long"
    assert verdict["limit"] == STEER_MAX_CHARS
    assert pending_steers(_SID) == []


def test_pending_steers_are_capped_per_session():
    for i in range(STEER_MAX_PENDING):
        assert submit_steer(_SID, f"steer {i}")["accepted"] is True
    overflow = submit_steer(_SID, "one too many")
    assert overflow["accepted"] is False
    assert overflow["reason"] == "too_many"
    assert overflow["limit"] == STEER_MAX_PENDING
    assert len(pending_steers(_SID)) == STEER_MAX_PENDING


def test_steers_are_session_scoped():
    submit_steer(_SID, "mine")
    submit_steer("other", "not mine")
    assert pending_steers(_SID) == ["mine"]
    assert pending_steers("other") == ["not mine"]


def test_take_consumes_in_submission_order_and_leaves_the_inbox_empty():
    submit_steer(_SID, "first")
    submit_steer(_SID, "second")
    assert take_steers(_SID) == ["first", "second"]
    assert pending_steers(_SID) == []
    assert take_steers(_SID) == []


def test_clear_reports_what_it_dropped():
    submit_steer(_SID, "a")
    submit_steer(_SID, "b")
    assert clear_steers(_SID) == 2
    assert clear_steers(_SID) == 0


def test_pending_is_a_copy_so_a_caller_cannot_mutate_the_inbox():
    submit_steer(_SID, "a")
    snapshot = pending_steers(_SID)
    snapshot.append("smuggled")
    assert pending_steers(_SID) == ["a"]


# ── delivery ────────────────────────────────────────────────────────────────

def test_consume_appends_user_turns_and_reports_what_it_applied():
    submit_steer(_SID, "switch to the other repo")
    messages = [{"role": "user", "content": "do the thing"}]
    applied = consume_steers_for_round(_SID, messages)
    assert applied == ["switch to the other repo"]
    assert len(messages) == 2
    assert messages[-1]["role"] == "user"
    assert "switch to the other repo" in messages[-1]["content"]


def test_consume_is_a_no_op_when_nothing_is_pending():
    messages = [{"role": "user", "content": "do the thing"}]
    assert consume_steers_for_round(_SID, messages) == []
    assert len(messages) == 1


def test_consume_without_a_session_id_never_drains_another_session():
    submit_steer(_SID, "mine")
    messages = []
    assert consume_steers_for_round(None, messages) == []
    assert messages == []
    assert pending_steers(_SID) == ["mine"]


def test_a_steer_is_applied_once_not_every_round():
    submit_steer(_SID, "only once")
    messages = []
    assert consume_steers_for_round(_SID, messages) == ["only once"]
    assert consume_steers_for_round(_SID, messages) == []
    assert len(messages) == 1


def test_directive_is_a_user_turn_and_never_a_system_instruction():
    # Promoting user text into the system prompt is a prompt-injection shape,
    # and on the Anthropic path every `system` message is hoisted into it.
    submit_steer(_SID, "stop touching prod")
    messages = []
    consume_steers_for_round(_SID, messages)
    assert messages[0]["role"] == "user"


def test_directive_says_the_work_so_far_stands():
    # The honest round-boundary story has to reach the model, not only the UI:
    # a steer arrives after a round completed, so "restart from scratch" is the
    # wrong reading and the wrapper says so.
    text = steer_directive("use tabs")
    assert "use tabs" in text
    lower = text.lower()
    assert "do not restart" in lower
    assert "step boundary" in lower


# ── the loop actually consumes at a round boundary ──────────────────────────

_AGENT_LOOP_PY = Path(__file__).resolve().parents[1] / "src" / "agent_loop.py"


def _stream_agent_loop_def():
    """The `stream_agent_loop` definition, parsed from the module source."""
    tree = ast.parse(_AGENT_LOOP_PY.read_text())
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "stream_agent_loop":
            return node
    raise AssertionError("stream_agent_loop not found in src/agent_loop.py")


def _round_loop_body():
    """The `for round_num in range(...)` loop inside `stream_agent_loop`."""
    for node in _stream_agent_loop_def().body:
        if isinstance(node, ast.For) and getattr(node.target, "id", "") == "round_num":
            return node
    raise AssertionError("round loop not found in stream_agent_loop")


def _call_index(body, func_name):
    for i, stmt in enumerate(body):
        for node in ast.walk(stmt):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == func_name):
                return i
    return -1


def _assign_index(body, target_name):
    for i, stmt in enumerate(body):
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == target_name:
                    return i
    return -1


def test_loop_consumes_steers_before_it_builds_the_round_request():
    body = _round_loop_body().body
    consume_at = _call_index(body, "consume_steers_for_round")
    state_at = _assign_index(body, "_active_route_state")
    assert consume_at >= 0, "the round loop never consumes steers"
    assert state_at >= 0, "_active_route_state assignment not found"
    assert consume_at < state_at, (
        "steers must be appended to `messages` before the per-round request "
        "state is built, or they land a round late"
    )


def test_round_one_request_pin_is_skipped_when_a_steer_was_applied():
    # `_initial_route_request_messages` is built before the loop. Pinning it on
    # round 1 while a steer was just appended would send the pre-steer list and
    # drop the steer with no error anywhere.
    body = _round_loop_body().body
    guards = [
        stmt for stmt in body
        if isinstance(stmt, ast.If)
        and any(isinstance(n, ast.Name) and n.id == "_initial_route_request_messages"
                for n in ast.walk(stmt))
    ]
    assert guards, "round-1 request pin not found"
    names = {n.id for n in ast.walk(guards[0].test) if isinstance(n, ast.Name)}
    assert "_steers_applied" in names, (
        "the round-1 request pin must fall through when a steer was applied"
    )


def test_run_start_drops_stale_steers():
    # A steer submitted as the previous stream ended belongs to no run. Letting
    # it survive into the next one is the P6-01 bug class (an item outliving
    # what it was addressed to), so `stream_agent_loop` clears on entry.
    fn = _stream_agent_loop_def()
    loop_at = next(i for i, n in enumerate(fn.body)
                   if isinstance(n, ast.For) and getattr(n.target, "id", "") == "round_num")
    clear_at = _call_index(fn.body[:loop_at], "clear_steers")
    assert clear_at >= 0, "stream_agent_loop never clears stale steers at run start"


def test_run_end_drops_steers_that_missed_their_round_boundary():
    # A steer accepted in the run's last moments belongs to nothing once the
    # loop is over; leaving it would let it redirect whatever ran next.
    fn = _stream_agent_loop_def()
    loop_at = next(i for i, n in enumerate(fn.body)
                   if isinstance(n, ast.For) and getattr(n.target, "id", "") == "round_num")
    assert _call_index(fn.body[loop_at + 1:], "clear_steers") >= 0, (
        "stream_agent_loop never clears the inbox after the round loop"
    )


def test_docstring_advertises_the_steer_event():
    # The docstring is the SSE contract for every client of this generator.
    assert "steer_applied" in (stream_agent_loop.__doc__ or "")


def test_module_documents_the_round_boundary_limit():
    # Law 15 leans on this: the UI is only allowed to promise what the loop can
    # deliver, and the reason lives next to the code that enforces it.
    src = Path(__file__).resolve().parents[1].joinpath("src", "agent_loop.py").read_text()
    block = src.split("# ── Mid-run steering (P6-18)")[1].split("def submit_steer")[0]
    assert "TOP OF THE NEXT ROUND" in block
    assert "instant redirection" in block
