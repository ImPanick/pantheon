# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B17` — a deeply nested tool argument ended the run and discarded the reply.

`_action_from_content` wrapped `json.loads` in `except (TypeError, ValueError)`.
`json.loads` recurses per nesting level and raises **`RecursionError`**, which
is a `RuntimeError` and is named by neither — so the exception escaped this
function and six unguarded call sites (`decision_for`, `observe_tool_result`,
`capabilities_for_action` in `agent_loop`, `_append_tool_results` twice, and
`tool_approvals._matches_unlocked`) and was caught only by `agent_runs.py`'s
outer handler, which ends the run.

Two consequences, one of which the row did not state: the user got a generic
*"Agent run failed before completion."*, and because `save_assistant_response`
is **inside** the `async for` body in `routes/chat_routes.py`, the turn's
partial reply was discarded.

The threshold was never a Pantheon constant. Measured, the first failing
nesting depth is `sys.getrecursionlimit() - frames_at_call - 4`, so the row's
"1,984 characters" is exactly `2 x (1000 - 4 - 4)` at the stock limit from a
bare call — it moves with the ambient stack.
"""
import json
import sys

import pytest

from src.agent_tools import TOOL_TAGS  # noqa: F401 — resolves the import cycle
from src.tool_capabilities import (
    _MAX_ACTION_JSON_DEPTH,
    _action_from_content,
    _json_depth_exceeds,
    capabilities_for_action,
)

DEEP = "[" * 1100 + "]" * 1100


def test_a_pathological_argument_does_not_escape_the_classifier():
    """The whole row in one line: nothing propagates out."""
    capabilities_for_action("manage_notes", DEEP)  # must not raise


def test_it_fails_high_rather_than_guessing_low():
    """`None` would fall through to the tool's base capabilities, which is the
    silent degradation that makes an approval card lie. `known=False` is the
    vocabulary the codebase already has for *we cannot classify this*, and
    `decision_for` renders it as "unknown/high-impact"."""
    caps = capabilities_for_action("manage_notes", DEEP)
    assert caps.known is False
    assert len(caps.effects) >= 8


def test_the_gate_never_dies_on_it_at_any_rung():
    """The row's actual claim: it killed the run *at every rung*. Nothing here
    may raise. What each rung then decides is a separate question."""
    from src.tool_capabilities import ToolRunSecurityContext

    for rung in ("ask_every_time", "allow_listed", "gate_on_untrusted"):
        for tainted in (False, True):
            ctx = ToolRunSecurityContext(rung=rung)
            ctx.external_untrusted_context_seen = tainted
            ctx.decision_for("manage_notes", DEEP)  # must not raise


def test_it_is_refused_wherever_the_gate_classifies_at_all():
    """The default rung on a clean run early-exits *before* classifying, and
    that is deliberate — `tests/test_trust_rung_gate.py` pins its every verdict
    against a transcription of the pre-`P7-03` gate, so it must not change
    here. A malformed argument on that path is rejected by the tool, not by the
    gate. Every path that does classify refuses."""
    from src.tool_capabilities import ToolRunSecurityContext

    classifying = [
        ("ask_every_time", False), ("allow_listed", False),
        ("ask_every_time", True), ("allow_listed", True),
        ("gate_on_untrusted", True),
    ]
    for rung, tainted in classifying:
        ctx = ToolRunSecurityContext(rung=rung)
        ctx.external_untrusted_context_seen = tainted
        decision = ctx.decision_for("manage_notes", DEEP)
        assert decision.allowed is False, (rung, tainted)
        assert "unknown" in (decision.reason or "").lower(), decision.reason


def test_a_large_but_flat_argument_still_works():
    """`Law 1`. The bound is on DEPTH, not length — a 50 KB note body is a
    legitimate argument and a length cap would have broken it."""
    payload = json.dumps({"action": "add", "text": "a" * 50_000})
    assert _action_from_content("manage_notes", payload) == "add"


@pytest.mark.parametrize("text", [
    "[" * 200,                        # brackets inside a string literal
    "{nested: looking}" * 40,         # braces inside a string literal
    'he said "hi" ' + "[" * 200,      # after a quote the encoder will escape
    "\\" * 50 + "[" * 200,             # backslashes before the brackets
])
def test_brackets_inside_a_string_are_not_nesting(text):
    """Built with `json.dumps`, so the escaping is real rather than hand-rolled
    — the first draft of this test hand-wrote a payload that was not valid JSON
    and proved nothing about the scanner."""
    payload = json.dumps({"action": "add", "text": text})
    assert _action_from_content("manage_notes", payload) == "add"


def test_the_depth_scan_does_not_itself_recurse():
    """A recursive depth check would be the same defect in a new function.

    Proved by shrinking the interpreter's own limit far below the input's
    nesting: a recursive implementation could not survive this.
    """
    original = sys.getrecursionlimit()
    sys.setrecursionlimit(60)
    try:
        assert _json_depth_exceeds("[" * 500 + "]" * 500, _MAX_ACTION_JSON_DEPTH)
    finally:
        sys.setrecursionlimit(original)


def test_the_bound_is_far_above_any_real_argument():
    assert _MAX_ACTION_JSON_DEPTH >= 32
    deepest_real = json.dumps({"action": "add", "body": {"a": [{"b": [1, 2]}]}})
    assert not _json_depth_exceeds(deepest_real, _MAX_ACTION_JSON_DEPTH)


def test_recursion_error_is_caught_even_if_the_bound_is_bypassed():
    """Belt and braces. The depth bound should make this unreachable, but a
    parse path that recurses some other way must not be able to end a run."""
    import src.tool_capabilities as tc

    original = tc._MAX_ACTION_JSON_DEPTH
    tc._MAX_ACTION_JSON_DEPTH = 10 ** 9  # disable the bound
    try:
        assert _action_from_content("manage_notes", DEEP) is None
    finally:
        tc._MAX_ACTION_JSON_DEPTH = original
