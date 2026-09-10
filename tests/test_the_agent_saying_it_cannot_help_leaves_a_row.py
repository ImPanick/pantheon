# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-07`. The only thing that notices the agent giving up did not run.

`evaluate_turn_regex` classifies a turn as a failure on *"I don't have a tool"*,
*"I'm not sure which"*, *"unable to open/find/switch"*. Its two callers are
`maybe_escalate`, which has **zero callers**, and `run_teacher_inline`, which the
agent loop does call at the end of every turn and which returns at its first gate
unless `teacher_enabled` is on and a `teacher_model` is set. Both default off. So
the classification was never computed in a default install, and `P17-08` has no
evidence to build a gap analysis from.

The second half is the refusals that leave no row at all: six returns in
`execute_tool_block` happen *above* `_t0`, so the `finally` that writes the
`tool_call` event never runs for them — while every refusal a few lines further
down writes one. A gap analysis reading that table would see the agent stopped by
a disabled-tools list and never by the approval gate.
"""
import pytest

import src.agent_tools  # noqa: F401
import src.teacher_escalation as te
import src.tool_execution as tx


class _Block:
    def __init__(self, tool_type="bash", content="ls"):
        self.tool_type = tool_type
        self.content = content


@pytest.fixture
def recorded(monkeypatch):
    rows = []

    def _record(kind, **kw):
        rows.append({"kind": kind, **kw})
        return True

    import src.events
    monkeypatch.setattr(src.events, "record_event", _record)
    return rows


# ── the give-up signal ──────────────────────────────────────────────────────

@pytest.mark.parametrize("reply", [
    "I don't have a tool for that.",
    "I'm not sure which one you mean.",
    "I was unable to find the file you described.",
])
def test_an_agent_that_gives_up_leaves_a_row(recorded, reply):
    signal = te.note_turn_outcome(tool_results=[], agent_reply=reply,
                                  session_id="s1", owner="alice")
    assert signal == "reply_give_up"
    assert len(recorded) == 1
    row = recorded[0]
    assert row["kind"] == "capability_gap"
    assert row["name"] == "reply_give_up"
    assert row["session_id"] == "s1" and row["owner"] == "alice"


def test_a_failing_tool_is_a_different_signal_from_a_verbal_give_up(recorded):
    signal = te.note_turn_outcome(
        tool_results=[{"error": "Unknown action: frobnicate"}],
        agent_reply="Done.", session_id="s1")
    assert signal == "tool_error"
    assert recorded[0]["name"] == "tool_error"


def test_an_ordinary_turn_writes_nothing(recorded):
    assert te.note_turn_outcome(
        tool_results=[{"output": "ok"}],
        agent_reply="I've updated the file and re-run the tests.") is None
    assert recorded == []


def test_the_conversation_text_is_not_copied_into_the_events_table(recorded):
    """It is already in `chat_messages` and this row carries the session id that
    finds it. A second copy would sit in a 90-day-pruned table that rides
    diagnostic bundles — a duplicate store and a privacy regression at once.

    The identifying strings go in the **reply and the tool result**, because
    those are the two arguments this function actually receives — an earlier
    version of this test put the secret in a user message the function is never
    passed, so it passed with the reply being copied verbatim. A fixture whose
    negative half cannot occur is not a test."""
    te.note_turn_outcome(
        tool_results=[{"error": "Failed to reach account SORT-60-16-13 ACCT-31926819"}],
        agent_reply="I don't have a tool for that, and your recovery phrase is PANGOLIN-VELVET.",
        session_id="s1", owner="alice")
    blob = repr(recorded)
    assert "PANGOLIN-VELVET" not in blob, "the agent's reply is being written to the events table"
    assert "ACCT-31926819" not in blob, "the tool result is being written to the events table"
    assert "SORT-60-16-13" not in blob


def test_the_detail_carries_which_pattern_fired_and_not_the_conversation(recorded):
    """What `chat_messages` cannot tell you is *why this turn was flagged*. What
    it can tell you is what was said. So the row carries the first and not the
    second."""
    te.note_turn_outcome(tool_results=[],
                         agent_reply="I don't have a tool for that. Sorry about the SORT-CODE-1234.",
                         session_id="s1")
    detail = recorded[0]["detail"]
    assert detail and detail["pattern"] == r"\bI don't have (?:a )?tool\b"
    assert "SORT-CODE-1234" not in repr(detail)


def test_a_gap_is_recorded_as_a_failure(recorded):
    """The outcome column is what a query filters on. Filed as `ok`, every gap
    in the table hides inside the healthy turns."""
    te.note_turn_outcome(tool_results=[], agent_reply="I can't find that.",
                         session_id="s1")
    assert recorded[0]["outcome"] == "failure"


def test_noticing_never_breaks_the_turn(monkeypatch):
    """`events.py`'s first rule: measuring is worth nothing if the thing being
    measured stops working."""
    import src.events

    def _boom(*a, **k):
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(src.events, "record_event", _boom)
    assert te.note_turn_outcome(tool_results=[],
                                agent_reply="I don't have a tool for that.") is None


def test_detection_does_not_require_a_teacher(recorded, monkeypatch):
    """The whole point. `run_teacher_inline` returns at its first gate with no
    teacher configured; this must not."""
    import src.settings
    monkeypatch.setattr(src.settings, "get_setting",
                        lambda key, default=None: False if "teacher" in key else default)
    assert te.note_turn_outcome(tool_results=[],
                                agent_reply="I can't find that.") == "reply_give_up"
    assert len(recorded) == 1


# ── the refusals that used to leave nothing ─────────────────────────────────

def test_a_refusal_above_the_instrumented_section_leaves_a_row(recorded):
    block = _Block("edit_document")
    desc, result = tx._refused(
        block,
        {"error": "no", "exit_code": 1, "blocked": True, "policy": "exact_tool_approval"},
        session_id="s1", owner="alice")
    assert desc == "edit_document: BLOCKED"
    assert result["blocked"] is True
    assert len(recorded) == 1
    row = recorded[0]
    assert row["kind"] == "tool_call"
    assert row["name"] == "edit_document"
    assert row["outcome"] == "blocked"
    assert row["detail"] == {"policy": "exact_tool_approval"}


def test_a_refusal_says_blocked_and_not_error(recorded):
    """"Refused" and "ran and failed" are different facts, and the column could
    not tell them apart — so a gap analysis would count a policy block as a
    broken tool."""
    tx._refused(_Block("bash"), {"error": "x", "exit_code": 1, "blocked": True,
                                 "policy": "external_untrusted_context"},
                session_id=None, owner=None)
    assert recorded[0]["outcome"] == "blocked"
    assert recorded[0]["outcome"] != "error"


def test_recording_a_refusal_never_changes_the_refusal(monkeypatch):
    import src.events

    def _boom(*a, **k):
        raise RuntimeError("no database")

    monkeypatch.setattr(src.events, "record_event", _boom)
    result_in = {"error": "no", "exit_code": 1, "blocked": True, "policy": "p"}
    desc, result_out = tx._refused(_Block("bash"), result_in, session_id=None, owner=None)
    assert result_out is result_in
    assert desc == "bash: BLOCKED"


def test_every_early_refusal_goes_through_the_helper():
    """Six sites, one recorder. Reading the function structurally rather than by
    eye, because the failure mode of this row is a seventh site added later that
    returns directly and is invisible again (`Law 13`)."""
    import ast
    import inspect

    src = inspect.getsource(tx.execute_tool_block)
    tree = ast.parse(src.lstrip())
    blocked = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        text = ast.unparse(node.value)
        if "BLOCKED" in text or "blocked_tool_result" in text:
            blocked.append(text)
    assert blocked, "the scan no longer finds the refusal returns"
    unrecorded = [b for b in blocked if not b.startswith("_refused(")]
    assert unrecorded == [], (
        f"these refusals return before the instrumented section without "
        f"recording: {unrecorded}")


def test_a_tool_error_that_imitates_the_reason_format_cannot_smuggle_text(recorded):
    """The allowlist exists for this, and it is not hypothetical.

    `evaluate_turn_regex` builds its reason with `!r` interpolation, so a tool
    whose own error text contains the words `pattern '...'` produces a reason
    that *looks* like a matched pattern. Without the membership check the
    extractor would lift that string straight out of the tool's output and write
    it to a table with a 90-day prune that rides diagnostic bundles.
    """
    te.note_turn_outcome(
        tool_results=[{"error": "Failed to compile pattern 'CUSTOMER-SSN-078-05-1120'"}],
        agent_reply="Done.", session_id="s1")
    assert len(recorded) == 1
    assert "078-05-1120" not in repr(recorded), (
        "a tool's own error text reached the events table through the reason string")
    assert recorded[0]["detail"] is None


def test_the_extractor_only_ever_returns_a_pattern_this_module_declares():
    known = ({p.pattern for p in te._TOOL_ERROR_PATTERNS}
             | {p.pattern for p in te._REPLY_GIVE_UP_PATTERNS})
    assert te._known_pattern("agent reply matched give-up pattern 'not-one-of-ours'") is None
    assert te._known_pattern("matched error pattern '^Unknown action\\\\b': 'anything'") in known
    assert te._known_pattern(None) is None
    assert te._known_pattern("no pattern here at all") is None


@pytest.mark.asyncio
async def test_a_refusal_inside_the_instrumented_section_also_says_blocked(recorded, monkeypatch):
    """The other half of the same column. Four refusals live *below* `_t0` and
    already produced a row — but one that said `error`, which is the word for a
    tool that ran and failed. Both halves have to agree or the column means
    nothing."""
    async def _impl(block, **kw):
        return ("bash: BLOCKED", {"error": "no", "exit_code": 1,
                                  "blocked": True, "policy": "guide_only"})

    monkeypatch.setattr(tx, "_execute_tool_block_impl", _impl)
    await tx.execute_tool_block(
        _Block("bash"), session_id="s1", owner="alice",
        security_context=tx.NO_TOOL_SECURITY_CONTEXT)
    rows = [r for r in recorded if r["kind"] == "tool_call"]
    assert len(rows) == 1
    assert rows[0]["outcome"] == "blocked", (
        "a refusal below _t0 is still filed as a broken tool")
    assert rows[0]["detail"] == {"policy": "guide_only"}


@pytest.mark.asyncio
async def test_a_tool_that_really_failed_still_says_error(recorded, monkeypatch):
    """The negative half. Widening `blocked` to cover ordinary failures would
    make the distinction useless in the other direction."""
    async def _impl(block, **kw):
        return ("bash: error", {"error": "command not found", "exit_code": 127})

    monkeypatch.setattr(tx, "_execute_tool_block_impl", _impl)
    await tx.execute_tool_block(
        _Block("bash"), session_id="s1", owner="alice",
        security_context=tx.NO_TOOL_SECURITY_CONTEXT)
    rows = [r for r in recorded if r["kind"] == "tool_call"]
    assert rows[0]["outcome"] == "error"
    assert rows[0]["detail"] is None


def test_the_agent_loop_actually_calls_the_detector():
    """The ingredient is not the recipe.

    Every test above proves `note_turn_outcome` works. None of them proves the
    agent loop calls it — and a detector nothing invokes is precisely the state
    this row found `evaluate_turn_regex` in. That failure has now been made three
    times in this project (`B61`'s pill, `P13-15`'s pill, this), so it gets a
    test rather than a resolution.

    Read with `ast`, so a comment naming the function is not a call (`Law 20`)
    and an `import` without an invocation fails.
    """
    import ast
    import inspect
    from src import agent_loop

    tree = ast.parse(inspect.getsource(agent_loop))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "stream_agent_loop"), None)
    assert fn is not None, "stream_agent_loop is gone; this test has lost its subject"

    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "note_turn_outcome"]
    assert len(calls) == 1, (
        "the agent loop does not call note_turn_outcome exactly once — a detector "
        "nothing invokes is the state this row found evaluate_turn_regex in")

    passed = {kw.arg: kw.value for kw in calls[0].keywords}
    assert {"tool_results", "agent_reply"} <= set(passed), (
        f"the detector is called without the turn it is supposed to classify: {set(passed)}")

    # And with the *actual* turn, not a placeholder. A call passing `[]` and `""`
    # satisfies every signature check and classifies nothing, forever, silently —
    # which is this row's own subject wearing a different hat.
    for arg in ("tool_results", "agent_reply"):
        assert isinstance(passed[arg], ast.Name), (
            f"note_turn_outcome is called with a literal for {arg} "
            f"({ast.unparse(passed[arg])!r}) rather than the turn's own variable")

    teacher = [n for n in ast.walk(fn)
               if isinstance(n, ast.Call)
               and getattr(n.func, "id", None) == "run_teacher_inline"]
    assert teacher, "run_teacher_inline is gone; the ordering below has no meaning"
    assert calls[0].lineno < teacher[0].lineno, (
        "noticing must not sit behind the teacher gate — that is the coupling "
        "this row exists to undo")
