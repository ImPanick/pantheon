# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B19` — the strict rungs asked permission to read the user's own notes.

`ask_every_time` and `allow_listed` gated on `POST_EXTERNAL_BLOCKED_EFFECTS`,
which is the set for *after* untrusted content has entered the run. The two
questions are different: post-external asks "could this act on what a stranger
told the model"; an untainted strict rung asks "is this about to change or send
something". Reading your own notes is neither.

Measured on the tree that had it: 74 of 83 registry tools gated on a clean run,
**17 solely by `read_private`**, plus 30 multiplexed read actions. So the
strictest rungs stopped to ask before the agent read back a note it had written
itself — which is how a security control gets switched off.

**The row's own "correction" was false and is withdrawn.** It claimed
`manage_notes` and `manage_memory` "also carry `write_private` and would stay
gated anyway". `capabilities_for_action` **replaces** a tool's base
capabilities for a read action rather than unioning them, so at the gate those
actions carry `read_private` and nothing else — they are freed, which is what
the row's `Verify` line asked for.

Nothing is relaxed. `POST_EXTERNAL_BLOCKED_EFFECTS` is untouched, and
`FORBIDDEN.md` Part 2's post-external gate applies in full the moment a run is
tainted.
"""
import pytest

from src.agent_tools import TOOL_TAGS  # noqa: F401 — resolves the import cycle
from src.tool_capabilities import (
    POST_EXTERNAL_BLOCKED_EFFECTS,
    RUNG_BLOCKED_EFFECTS,
    ToolEffect,
    ToolRunSecurityContext,
    capabilities_for_action,
)

STRICT = ("ask_every_time", "allow_listed")

PRIVATE_READS = [
    ("manage_memory", '{"action": "list"}'),
    ("manage_memory", '{"action": "search", "text": "kettle"}'),
    ("manage_notes", '{"action": "list"}'),
    ("read_email", '{"uid": "7"}'),
    ("list_emails", '{}'),
    ("manage_calendar", '{"action": "list"}'),
]

STILL_GATED = [
    ("write_file", '{"path": "a.txt", "content": "x"}'),
    ("bash", "ls"),
    ("send_email", '{"to": "a@b.c", "subject": "s", "body": "b"}'),
    ("delete_email", '{"uid": "7"}'),
]


def test_the_two_sets_differ_by_exactly_one_effect():
    assert POST_EXTERNAL_BLOCKED_EFFECTS - RUNG_BLOCKED_EFFECTS == frozenset(
        {ToolEffect.READ_PRIVATE}
    )
    assert not RUNG_BLOCKED_EFFECTS - POST_EXTERNAL_BLOCKED_EFFECTS


def test_the_post_external_set_is_not_relaxed():
    """`FORBIDDEN.md` Part 2. The fix narrows a *different* set."""
    assert ToolEffect.READ_PRIVATE in POST_EXTERNAL_BLOCKED_EFFECTS
    assert len(POST_EXTERNAL_BLOCKED_EFFECTS) == 9


@pytest.mark.parametrize("rung", STRICT)
@pytest.mark.parametrize("tool,content", PRIVATE_READS)
def test_a_clean_run_reads_its_own_things_without_asking(rung, tool, content):
    ctx = ToolRunSecurityContext(rung=rung)
    assert ctx.decision_for(tool, content).allowed is True


@pytest.mark.parametrize("rung", STRICT)
@pytest.mark.parametrize("tool,content", STILL_GATED)
def test_a_clean_run_still_asks_before_it_changes_or_sends_anything(rung, tool, content):
    ctx = ToolRunSecurityContext(rung=rung)
    assert ctx.decision_for(tool, content).allowed is False


@pytest.mark.parametrize("rung", STRICT + ("gate_on_untrusted",))
@pytest.mark.parametrize("tool,content", PRIVATE_READS)
def test_a_tainted_run_asks_about_private_reads_exactly_as_before(rung, tool, content):
    """The half that must not move. Once anything from outside has entered the
    run, the full post-external set applies at every rung."""
    ctx = ToolRunSecurityContext(rung=rung)
    ctx.external_untrusted_context_seen = True
    assert ctx.decision_for(tool, content).allowed is False


def test_the_rows_correction_was_false_and_this_is_why():
    """`capabilities_for_action` REPLACES rather than unions for a read action.

    The row claimed these tools keep `write_private` at the gate and would stay
    gated regardless. They do not — and a test that asserted the row's version
    would have blocked the fix on a premise nobody measured.
    """
    for tool in ("manage_memory", "manage_notes"):
        caps = capabilities_for_action(tool, '{"action": "list"}')
        assert caps.effects == frozenset({ToolEffect.READ_PRIVATE}), (tool, caps.effects)
        assert ToolEffect.WRITE_PRIVATE not in caps.effects, tool


def test_the_first_private_read_still_arms_the_gate():
    """This is what keeps the fix from being a hole: a clean run stops asking
    about the FIRST private read, and that read taints the run, so everything
    after it is back under the full set. The read to exfiltrate path is exactly
    as closed as it was."""
    from src.tool_capabilities import tool_result_should_arm_gate

    for tool, content in PRIVATE_READS:
        assert tool_result_should_arm_gate(
            tool, {"exit_code": 0, "output": "…"}, content
        ) is True, tool
