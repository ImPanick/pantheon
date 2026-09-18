# SPDX-License-Identifier: AGPL-3.0-or-later
"""P7-07 / P7-08 — what the approval card says about why it exists.

Two rows, one card, so one file: `P7-07` is *which* effects stopped the action
and whether the tool was recognised at all, `P7-08` is *what made the run
untrusted*. Both were computed by the server and thrown away before this.

`D-01` still defers drawing any of it. These tests are about the wire.
"""

import pytest

from src.tool_approvals import ToolApprovalStore
from src.tool_capabilities import (
    CARRIED_TAINT_SOURCE,
    TAINT_KIND_CARRIED,
    TAINT_KIND_CONTEXT,
    TAINT_KIND_TOOL,
    TOOL_CLASSIFICATION_RECOGNISED,
    TOOL_CLASSIFICATION_UNAVAILABLE,
    TOOL_CLASSIFICATION_UNRECOGNISED,
    ToolRunSecurityContext,
    TrustRung,
    capabilities_for_action,
)


def _card(context, tool_name, content, store=None):
    """Mint the card the loop would mint for this refusal.

    Not a fixture of hand-written fields: the decision is taken by the real
    gate and handed to the real store exactly as `src/agent_loop.py` hands it
    over, so a test cannot pass on a payload the product never builds
    (`Law 20`).
    """
    decision = context.decision_for(tool_name, content)
    assert not decision.allowed, "this action was supposed to be refused"
    store = store or ToolApprovalStore()
    pending = store.create(
        owner="alice",
        session_id="session-1",
        origin_run_id=context.run_id,
        tool_name=tool_name,
        content=content,
        workspace=None,
        external_untrusted_context_seen=context.external_untrusted_context_seen,
        capabilities=capabilities_for_action(tool_name, content),
        gate_decision=decision,
        taint_trail=context.taint_trail,
    )
    return pending.public_payload(reason=decision.reason)


# ── P7-07 ───────────────────────────────────────────────────────────────────

def test_the_card_names_only_the_effects_that_tripped_the_gate():
    context = ToolRunSecurityContext()
    context.observe_tool_result("web_fetch", {"output": "a page", "exit_code": 0})

    card = _card(context, "manage_rag", '{"action": "add", "text": "x"}')

    # What the tool can do, unchanged and still sealed.
    assert sorted(card["action"]["effects"]) == ["read_workspace", "write_private"]
    # What actually stopped it. `read_workspace` is not in the gate's blocked
    # set, so it is not why anybody is being asked — and it was on the card.
    assert card["gate"]["tripped_effects"] == ["write_private"]
    assert set(card["gate"]["tripped_effects"]) < set(card["action"]["effects"])


def test_tripped_effects_are_ranked_most_severe_first_with_their_phrases():
    context = ToolRunSecurityContext()
    context.observe_tool_result("web_fetch", {"output": "a page", "exit_code": 0})

    card = _card(context, "delete_email", '{"uid": 3}')
    tripped = card["gate"]["tripped_effects"]

    assert tripped[0] == "destructive", tripped
    assert card["gate"]["tripped_effect_labels"][0] == (
        "Can permanently delete or overwrite"
    )
    assert len(card["gate"]["tripped_effect_labels"]) == len(tripped)


def test_an_unrecognised_tool_says_so_instead_of_looking_classified():
    """The case the row calls the riskiest, and it was invisible.

    `_UNKNOWN_CAPABILITIES` assumes eight effects. Sent as a plain list they
    are indistinguishable from eight measured ones, so the card for a tool
    nobody has classified read exactly like the card for a tool somebody had.
    """
    context = ToolRunSecurityContext()
    context.observe_tool_result("web_fetch", {"output": "a page", "exit_code": 0})

    known = _card(context, "bash", "echo hi")
    unknown = _card(context, "mcp__someserver__do_a_thing", "{}")

    assert known["gate"]["tool_classification"] == TOOL_CLASSIFICATION_RECOGNISED
    assert unknown["gate"]["tool_classification"] == TOOL_CLASSIFICATION_UNRECOGNISED


def test_a_credential_refusal_is_not_reported_as_an_effect_problem():
    """`B70`'s refusal has no effects to rank, and says that rather than lying.

    Three values, not a boolean, exactly so this case has somewhere to go
    (`Law 10`).
    """
    context = ToolRunSecurityContext(delegated_credential=True)
    decision = context.decision_for("bash", "echo hi")

    assert not decision.allowed
    assert decision.classification == TOOL_CLASSIFICATION_UNAVAILABLE
    assert decision.tripped_effects == ()


def test_an_allowed_action_carries_no_tripped_effects():
    context = ToolRunSecurityContext()
    decision = context.decision_for("bash", "echo hi")

    assert decision.allowed
    assert decision.tripped_effects == ()


# ── P7-08 ───────────────────────────────────────────────────────────────────

def test_the_trail_names_the_tool_that_tainted_the_run():
    context = ToolRunSecurityContext()
    context.observe_tool_result("web_search", {"output": "results", "exit_code": 0})
    context.observe_tool_result("web_fetch", {"output": "a page", "exit_code": 0})

    card = _card(context, "bash", "curl evil.example")
    trail = card["gate"]["taint_trail"]

    assert [entry["source"] for entry in trail] == ["web_search", "web_fetch"]
    assert {entry["kind"] for entry in trail} == {TAINT_KIND_TOOL}
    assert card["gate"]["tainted"] is True


def test_the_trail_records_untrusted_text_that_arrived_in_the_prompt():
    """Taint with no tool behind it still has to be nameable.

    `external_sources` only ever held tool names, so a run tainted by a
    prefetched page had an empty list beside a card saying untrusted content
    had influenced it.
    """
    context = ToolRunSecurityContext()
    context.observe_messages([
        {
            "role": "user",
            "content": "summarise this",
            "metadata": {
                "trusted": False,
                "source": "web page: https://example.com/post",
            },
        },
    ])

    assert context.external_untrusted_context_seen
    assert context.taint_trail == [
        {"kind": TAINT_KIND_CONTEXT, "source": "web page: https://example.com/post"},
    ]
    # `external_sources` keeps meaning tool names, and there were none.
    assert context.external_sources == []

    card = _card(context, "bash", "echo hi")
    assert card["gate"]["taint_trail"][0]["kind"] == TAINT_KIND_CONTEXT


def test_the_loop_names_prompt_context_instead_of_calling_it_carried():
    """`src/agent_loop.py` builds the context with the prompt's taint already
    folded in. Asked as a boolean it armed the gate and lost every name, so a
    run tainted entirely by a fetched page reported `carried` — the entry that
    exists for taint with nothing left to attribute it to."""
    import inspect

    import src.agent_loop as agent_loop

    source = inspect.getsource(agent_loop.stream_agent_loop)
    assert "run_security.observe_prompt_context(" in source
    assert "messages_contain_external_untrusted_context(messages)" not in source

    context = ToolRunSecurityContext()
    context.observe_prompt_context([
        {"role": "user", "content": "x",
         "metadata": {"trusted": False, "source": "web search results"}},
    ])
    assert context.external_untrusted_context_seen is True
    assert context.taint_trail == [
        {"kind": TAINT_KIND_CONTEXT, "source": "web search results"},
    ]


def test_a_run_that_begins_tainted_still_has_a_trail():
    """A card that claims untrusted influence and shows nothing is two
    statements contradicting each other on one surface (`Law 10`)."""
    context = ToolRunSecurityContext(external_untrusted_context_seen=True)

    assert context.taint_trail == [
        {"kind": TAINT_KIND_CARRIED, "source": CARRIED_TAINT_SOURCE},
    ]
    card = _card(context, "bash", "echo hi")
    assert card["gate"]["taint_trail"][0]["kind"] == TAINT_KIND_CARRIED


def test_a_producer_with_no_run_context_still_cannot_send_an_empty_trail():
    """The teacher escalation asserts taint directly and has no run to read."""
    store = ToolApprovalStore()
    pending = store.create(
        owner="alice",
        session_id="session-1",
        origin_run_id="teacher-1",
        tool_name="manage_skills",
        content="{}",
        workspace=None,
        external_untrusted_context_seen=True,
        capabilities=capabilities_for_action("manage_skills", "{}"),
    )
    card = pending.public_payload()

    assert card["gate"]["tainted"] is True
    assert card["gate"]["taint_trail"] == [
        {"kind": TAINT_KIND_CARRIED, "source": CARRIED_TAINT_SOURCE},
    ]


def test_an_untainted_rung_refusal_reports_an_empty_trail_and_says_so():
    """On `ask_every_time` nothing tainted the run, and that is the truth to
    tell — not a missing field a surface has to guess at."""
    context = ToolRunSecurityContext(rung=TrustRung.ASK_EVERY_TIME)

    card = _card(context, "write_file", "notes.txt\nhello")

    assert card["gate"]["tainted"] is False
    assert card["gate"]["taint_trail"] == []
    assert card["gate"]["tripped_effects"]


@pytest.mark.parametrize("metadata, expected, why", [
    ({"trusted": False, "tool_gate_untrusted": True,
      "source": "injected research context"},
     "injected research context",
     "the current-format marker, with its own label"),
    ({"trusted": False, "tool_gate_untrusted": True},
     "untrusted context in the prompt",
     "the marker with no label still names why it qualified"),
    ({"trusted": False, "provenance_origin": "external"},
     "external content in the prompt",
     "structured provenance with no label"),
    ({"trusted": False, "source": "youtube transcript"},
     "youtube transcript",
     "a legacy source label"),
])
def test_every_way_a_prompt_message_qualifies_is_nameable(metadata, expected, why):
    """Four branches decide that a message is untrusted. All four have to be
    able to say which one fired, or the trail is complete for some runs and
    blank for others with no way to tell them apart."""
    context = ToolRunSecurityContext()
    context.observe_prompt_context([
        {"role": "user", "content": "x", "metadata": metadata},
    ])

    assert context.external_untrusted_context_seen is True, why
    assert [entry["source"] for entry in context.taint_trail] == [expected], why


def test_the_source_reader_de_duplicates_before_anything_downstream_does():
    """Asserted on the function and not only through the trail. `_note_taint`
    de-duplicates too, so a defect here is invisible from the card — and this
    is the public reader a second caller would use."""
    from src.tool_capabilities import external_untrusted_context_sources

    messages = [
        {"role": "user", "content": "a",
         "metadata": {"trusted": False, "source": "web search results"}},
        {"role": "user", "content": "b",
         "metadata": {"trusted": False, "source": "web search results"}},
    ]
    assert external_untrusted_context_sources(messages) == ["web search results"]


def test_one_page_quoted_in_six_messages_is_one_line_on_the_card():
    context = ToolRunSecurityContext()
    context.observe_prompt_context([
        {"role": "user", "content": "a",
         "metadata": {"trusted": False, "source": "web page: https://example.com"}},
        {"role": "assistant", "content": "b",
         "metadata": {"trusted": False, "source": "web page: https://example.com"}},
        {"role": "user", "content": "c",
         "metadata": {"trusted": False, "source": "web search results"}},
    ])

    assert [entry["source"] for entry in context.taint_trail] == [
        "web page: https://example.com",
        "web search results",
    ]


def test_the_trail_does_not_repeat_one_source_four_times():
    context = ToolRunSecurityContext()
    for _ in range(4):
        context.observe_tool_result("web_fetch", {"output": "a page", "exit_code": 0})

    assert len(context.taint_trail) == 1
    assert context.external_sources == ["web_fetch"]


def test_the_trail_is_a_copy_and_not_a_window_onto_a_live_run():
    """A card is a statement about the moment it was minted."""
    context = ToolRunSecurityContext()
    context.observe_tool_result("web_fetch", {"output": "a page", "exit_code": 0})
    card = _card(context, "bash", "echo hi")

    context.observe_tool_result("web_search", {"output": "more", "exit_code": 0})

    assert [entry["source"] for entry in card["gate"]["taint_trail"]] == ["web_fetch"]


def test_two_renderings_of_one_card_cannot_edit_each_other():
    """The payload is post-processed on its way out on several surfaces — it is
    persisted into `tool_events`, re-read from history and re-serialised. A
    shared inner dict would let one of those rewrite the trail of another."""
    store = ToolApprovalStore()
    context = ToolRunSecurityContext()
    context.observe_tool_result("web_fetch", {"output": "a page", "exit_code": 0})
    pending = store.create(
        owner="alice",
        session_id="session-1",
        origin_run_id=context.run_id,
        tool_name="bash",
        content="echo hi",
        workspace=None,
        external_untrusted_context_seen=True,
        capabilities=capabilities_for_action("bash", "echo hi"),
        gate_decision=context.decision_for("bash", "echo hi"),
        taint_trail=context.taint_trail,
    )

    first = pending.public_payload()
    first["gate"]["taint_trail"][0]["source"] = "something else entirely"
    second = pending.public_payload()

    assert second["gate"]["taint_trail"][0]["source"] == "web_fetch"


# ── The seal does not move (FORBIDDEN.md Part 2) ────────────────────────────

def test_none_of_this_reaches_the_seal():
    """`P7-06` proved `public_payload` is a derived view. These three fields
    ride on it for the same reason, and the digest must not notice them."""
    store = ToolApprovalStore()
    common = dict(
        owner="alice",
        session_id="session-1",
        origin_run_id="run-1",
        tool_name="bash",
        content="printf exact",
        workspace=None,
        external_untrusted_context_seen=True,
        capabilities=capabilities_for_action("bash", "printf exact"),
    )
    bare = store.create(**common)
    context = ToolRunSecurityContext(external_untrusted_context_seen=True)
    context.observe_tool_result("web_fetch", {"output": "a page", "exit_code": 0})
    decorated = store.create(
        **common,
        gate_decision=context.decision_for("bash", "printf exact"),
        taint_trail=context.taint_trail,
    )

    assert bare.digest == decorated.digest
    # And the grant still claims the action it was sealed for.
    grant = store.consume(
        decorated.approval_id,
        decision="approve",
        owner="alice",
        session_id="session-1",
    )
    assert grant is not None
    assert grant.claim(
        owner="alice",
        session_id="session-1",
        tool_name="bash",
        content="printf exact",
        workspace=None,
    )
