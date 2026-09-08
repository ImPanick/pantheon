# SPDX-License-Identifier: AGPL-3.0-or-later
"""P7-06: the ranked effect has to reach the client, on every emit site.

The taxonomy in ``src/tool_capabilities.py`` was correct and unused: a shell
command and a theme switch produced byte-identical cards. These tests pin the
wire, not the ranking.

CORRECTED 2026-08-29 after refutation. That sentence used to end "— the
ordering itself is covered beside the table it ranks", and there was no such
coverage: nothing anywhere imported ``effect_severity``, ``effect_band`` or
``describe_effects``, and five mutations to the ranking, the thresholds and the
phrasing walked through a green suite. A claim that some other file has the
tests is the most expensive kind of false comment, because it is read as a
reason not to look. The ordering is now covered, in
``tests/test_tool_capabilities_effects.py``, and this line is accurate as of
the commit that wrote it — which is the only honest way to make it.

What is easy to ship half-done, and what most of this file is about, is the
*post-approval replay* pair: the one path where the user was actually asked for
consent is a separate block of code from the main loop, so a fix applied only
to the main loop leaves consent cards blank.

The other half is persistence. A live event that never reaches the saved
``tool_events`` gives a card that is ranked while it streams and unranked after
a reload, which is the same defect P7-06 names with a refresh in front of it.
"""

import asyncio
import json

import pytest

import src.agent_loop as agent_loop
from src.tool_approvals import ToolApprovalStore
from src.tool_capabilities import capabilities_for_action


EFFECT_KEYS = frozenset(
    {
        "effects",
        "effect",
        "effect_label",
        "effect_labels",
        "effect_severity",
        "effect_band",
    }
)

# Read off the emit sites as they stood before P7-06. Asserting the difference
# against these, rather than eyeballing the new dicts, is what makes "add, never
# subtract" testable: a renamed or dropped key fails here even though every
# effect assertion still passes.
TOOL_START_BASE_KEYS = frozenset({"type", "tool", "command", "full_command", "round"})
# `P4-11` added `round` to both `tool_output` sites. It was already on both
# `tool_start` sites and on the persisted `tool_event`, so the streamed result
# card was the one event in the pair that could not say which round it belonged
# to — the card drew a round after a reload and none while it was live.
# `P4-09` added `full_command` to both `tool_output` sites and to the persisted
# `tool_event`. It was on `tool_start` and nowhere else, so the full arguments
# were live-only and one rewrite deep: the result event that redraws the card
# never carried them, and after a reload they did not exist at all.
TOOL_OUTPUT_BASE_KEYS = frozenset(
    {"type", "tool", "command", "full_command", "round", "output", "exit_code"})
APPROVED_START_BASE_KEYS = TOOL_START_BASE_KEYS | {"approved"}
APPROVED_OUTPUT_BASE_KEYS = TOOL_OUTPUT_BASE_KEYS | {"approved"}


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


def _patch(monkeypatch, model_replies, *, results=None, executed=None):
    """Canned model replies plus a stub dispatcher, as the gate tests do."""
    monkeypatch.setattr(
        agent_loop, "get_setting", lambda key, default=None: default, raising=False
    )
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(
        agent_loop, "estimate_tokens", lambda *args, **kwargs: 10, raising=False
    )
    monkeypatch.setattr(
        agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False
    )
    replies = iter(model_replies)

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *args, **kwargs):
        if executed is not None:
            executed.append((block.tool_type, block.content))
        return (
            block.tool_type,
            (results or {}).get(
                block.tool_type, {"output": "ok", "exit_code": 0}
            ),
        )

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)


def _run(monkeypatch, model_replies, **kwargs):
    _patch(monkeypatch, model_replies, results=kwargs.pop("results", None))
    return _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1",
            "small-local-model",
            [{"role": "user", "content": "do the thing"}],
            max_rounds=kwargs.pop("max_rounds", 2),
            **kwargs,
        )
    )


def _first(events, event_type):
    return next(event for event in events if event.get("type") == event_type)


def _persisted(events):
    """The tool events a session reload replays, off the metrics envelope.

    ``stream_agent_loop`` builds this list as it goes and hands it to the caller
    inside ``metrics``; ``routes/chat_routes.py`` saves it on the assistant
    message and ``chatRenderer.addMessage`` rebuilds the thread — and any
    unanswered approval card — out of it. Reading it here is what makes the
    reload path testable without a database.
    """
    return _first(events, "metrics")["data"].get("tool_events") or []


def _gated_run(monkeypatch, model_reply, *, tool):
    """Drive the approval gate itself, up to the card it puts on screen.

    ``external_untrusted_context_seen`` is what makes the security decision
    refuse: once untrusted text has influenced the run, an effectful tool needs
    a separate user-authorised action. That branch is where
    ``PendingToolApproval.public_payload()`` is called, so it is the only way to
    exercise the real card payload rather than a hand-built one.
    """
    _patch(monkeypatch, [model_reply])
    return _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1",
            "small-local-model",
            [{"role": "user", "content": "do the thing"}],
            max_rounds=1,
            owner="alice",
            session_id="session-1",
            workspace=None,
            relevant_tools={tool},
            external_untrusted_context_seen=True,
        )
    )


def _approved_run(monkeypatch, *, tool_name, content, results=None):
    """Drive the replay path the approval card resumes into.

    The grant has to be sealed from the same owner/session/workspace the loop is
    called with or ``approval_matches`` is False and the replay emits a blocked
    card instead — which is a real path, but not the one under test here.

    ``relevant_tools`` is not decoration: the resumed turn is a bare "yes", and
    without the sealed tool set the loop takes its low-signal shortcut and
    returns before it ever reaches the replay block. ``routes/chat_routes.py``
    passes ``pending.selected_tools`` here for the same reason.
    """
    store = ToolApprovalStore()
    pending = store.create(
        owner="alice",
        session_id="session-1",
        origin_run_id="run-1",
        tool_name=tool_name,
        content=content,
        workspace=None,
        external_untrusted_context_seen=True,
        capabilities=capabilities_for_action(tool_name, content),
    )
    grant = store.consume(
        pending.approval_id,
        decision="approve",
        owner="alice",
        session_id="session-1",
    )
    assert grant is not None
    _patch(monkeypatch, ["Ran it."], results=results)
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


def test_shell_and_ui_side_effect_no_longer_produce_the_same_card(monkeypatch):
    shell = _first(
        _run(
            monkeypatch,
            ["```bash\nrm -rf /tmp/scratch\n```"],
            relevant_tools={"bash"},
        ),
        "tool_start",
    )
    ui = _first(
        _run(
            monkeypatch,
            ['```ui_control\n{"action": "set_theme", "theme_name": "dark"}\n```'],
            relevant_tools={"ui_control"},
        ),
        "tool_start",
    )

    assert shell["effect"] == "execute_code"
    assert shell["effect_band"] == "notable"
    assert ui["effect"] == "ui_side_effect"
    assert ui["effect_band"] == "routine"
    for key in ("effect", "effect_band", "effect_label"):
        assert shell[key] != ui[key], f"{key} still identical across the two cards"
    assert shell["effect_severity"] > ui["effect_severity"]


def test_content_not_tool_name_decides_the_rank(monkeypatch):
    delete = _first(
        _run(
            monkeypatch,
            ["```manage_memory\ndelete\nproject-notes\n```"],
            relevant_tools={"manage_memory"},
        ),
        "tool_start",
    )
    read = _first(
        _run(
            monkeypatch,
            ["```manage_memory\nlist\n```"],
            relevant_tools={"manage_memory"},
        ),
        "tool_start",
    )

    assert delete["tool"] == read["tool"] == "manage_memory"
    assert delete["effect"] == "destructive"
    assert delete["effect_band"] == "serious"
    assert read["effect"] != "destructive"
    assert delete["effect_severity"] > read["effect_severity"]


def test_effect_travels_on_tool_output_too(monkeypatch):
    events = _run(
        monkeypatch,
        ["```bash\nrm -rf /tmp/scratch\n```"],
        relevant_tools={"bash"},
    )
    start = _first(events, "tool_start")
    output = _first(events, "tool_output")

    assert EFFECT_KEYS <= set(output)
    for key in EFFECT_KEYS:
        assert output[key] == start[key], f"{key} disagrees across the pair"


def test_post_approval_replay_pair_carries_the_effect(monkeypatch):
    # The regression this row exists to prevent: the card that asked for consent
    # is emitted from the replay block, not the main loop.
    events = _approved_run(
        monkeypatch, tool_name="bash", content="rm -rf /tmp/scratch"
    )
    start = _first(events, "tool_start")
    output = _first(events, "tool_output")

    assert start["approved"] is True
    assert output["approved"] is True
    assert EFFECT_KEYS <= set(start)
    assert EFFECT_KEYS <= set(output)
    assert start["effect"] == output["effect"] == "execute_code"
    assert start["effect_band"] == output["effect_band"] == "notable"
    assert start["effect_label"] == "Runs code on this machine"


def test_post_approval_replay_ranks_a_destructive_action_above_a_read(monkeypatch):
    destructive = _approved_run(
        monkeypatch, tool_name="manage_memory", content="delete\nproject-notes"
    )
    read = _approved_run(monkeypatch, tool_name="manage_memory", content="list")

    start_destructive = _first(destructive, "tool_start")
    start_read = _first(read, "tool_start")

    assert start_destructive["effect"] == "destructive"
    assert start_destructive["effect_band"] == "serious"
    assert start_read["effect"] != "destructive"
    assert start_destructive["effect_severity"] > start_read["effect_severity"]


def test_unknown_tool_does_not_crash_and_does_not_claim_to_be_harmless(monkeypatch):
    # An unclassified MCP tool is the only way an unknown name reaches these
    # emits; every fence-parsable builtin is classified.
    events = _approved_run(
        monkeypatch,
        tool_name="mcp__someserver__do_something",
        content='{"target": "everything"}',
    )
    start = _first(events, "tool_start")
    output = _first(events, "tool_output")

    assert start["effects"], "an unknown tool must not resolve to no effects"
    assert start["effect_band"] == "serious"
    assert start["effect"] == "destructive"
    assert output["effect_band"] == "serious"
    assert any(event.get("type") == "metrics" for event in events), (
        "the stream must still reach its metrics event"
    )


def test_a_failing_resolver_cannot_kill_the_stream(monkeypatch):
    # These emits sit inside a live response. A raise here costs the user their
    # whole answer, so the fields are allowed to go missing and nothing else is.
    def explode(*args, **kwargs):
        raise RuntimeError("resolver blew up")

    monkeypatch.setattr(agent_loop, "capabilities_for_action", explode, raising=False)
    events = _run(
        monkeypatch,
        ["```bash\nprintf hi\n```"],
        relevant_tools={"bash"},
    )
    start = _first(events, "tool_start")
    output = _first(events, "tool_output")

    assert not EFFECT_KEYS & set(start)
    assert not EFFECT_KEYS & set(output)
    assert start["tool"] == "bash"
    assert output["output"] == "ok"
    assert any(event.get("type") == "metrics" for event in events)


def test_main_path_adds_the_effect_keys_and_nothing_else(monkeypatch):
    events = _run(
        monkeypatch,
        ["```bash\nprintf hi\n```"],
        relevant_tools={"bash"},
    )
    start = _first(events, "tool_start")
    output = _first(events, "tool_output")

    assert set(start) == TOOL_START_BASE_KEYS | EFFECT_KEYS
    assert set(output) == TOOL_OUTPUT_BASE_KEYS | EFFECT_KEYS
    assert start["type"] == "tool_start"
    assert start["tool"] == "bash"
    assert start["command"] == "printf hi"
    assert start["full_command"] == "printf hi"
    assert start["round"] == 1
    assert output["type"] == "tool_output"
    assert output["tool"] == "bash"
    assert output["command"] == "printf hi"
    assert output["full_command"] == "printf hi"
    assert output["output"] == "ok"
    assert output["exit_code"] == 0


def test_replay_path_adds_the_effect_keys_and_nothing_else(monkeypatch):
    events = _approved_run(monkeypatch, tool_name="bash", content="printf hi")
    start = _first(events, "tool_start")
    output = _first(events, "tool_output")

    assert set(start) == APPROVED_START_BASE_KEYS | EFFECT_KEYS
    assert set(output) == APPROVED_OUTPUT_BASE_KEYS | EFFECT_KEYS
    assert start["type"] == "tool_start"
    assert start["tool"] == "bash"
    assert start["command"] == "printf hi"
    assert start["full_command"] == "printf hi"
    # `P4-11`. This grant was sealed with no `requested_round` — the shape a
    # pending record had before the field existed — so the replay falls back to
    # the honest floor rather than to the 0 it used to hardcode. A grant that
    # *does* carry its round is `test_the_round_reaches_the_card.py`.
    assert start["round"] == 1
    assert output["type"] == "tool_output"
    assert output["tool"] == "bash"
    assert output["command"] == "printf hi"
    assert output["full_command"] == "printf hi"
    assert output["output"] == "ok"
    assert output["exit_code"] == 0


def test_a_mismatched_grant_describes_nothing_because_it_shows_nothing(monkeypatch):
    # The replay blanks `command` when the sealed binding does not match this
    # run, and the dispatcher blocks the action outright. Effect keys are gated
    # the same way: no consequence occurred, and there is no action on screen
    # for a label to describe.
    store = ToolApprovalStore()
    pending = store.create(
        owner="alice",
        session_id="session-1",
        origin_run_id="run-1",
        tool_name="bash",
        content="rm -rf /tmp/scratch",
        workspace=None,
        external_untrusted_context_seen=True,
        capabilities=capabilities_for_action("bash", "rm -rf /tmp/scratch"),
    )
    grant = store.consume(
        pending.approval_id,
        decision="approve",
        owner="alice",
        session_id="session-1",
    )
    _patch(monkeypatch, ["Ran it."])
    events = _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1",
            "small-local-model",
            [{"role": "user", "content": "yes, go ahead"}],
            max_rounds=1,
            owner="mallory",
            session_id="session-1",
            workspace=None,
            relevant_tools=set(pending.selected_tools),
            exact_approval=grant,
        )
    )

    assert not any(event.get("type") == "tool_start" for event in events)
    output = _first(events, "tool_output")
    assert output["command"] == ""
    assert not EFFECT_KEYS & set(output)


@pytest.mark.parametrize(
    "phrase",
    ["effect_band", "effect_label", "effect_severity", "effect_labels"],
)
def test_the_wire_documents_its_own_new_fields(phrase):
    # A wire field no document mentions is how the previous handoffs went wrong.
    assert phrase in (agent_loop.stream_agent_loop.__doc__ or "")


# ── The approval card's own payload ─────────────────────────────────────────
#
# Refutation deleted the effect keys from the ask_user event and nothing failed.
# That mutation has since changed meaning, and the change is the point: the SSE
# event deliberately no longer carries its own copy. The presentation moved
# inside ``PendingToolApproval.public_payload()``, so every producer of an
# approval card gets it — the chat loop, the compare pane, the background
# monitor, the teacher escalation and a card rebuilt from history — rather than
# five sites each resolving it and three of them disagreeing, which is what
# refutation actually found. These rows assert against where it lives now.

_GATED_FETCH = "```web_fetch\nhttps://example.com\n```"


def test_the_approval_card_payload_carries_the_ranked_consequence(monkeypatch):
    events = _gated_run(monkeypatch, _GATED_FETCH, tool="web_fetch")
    payload = _first(events, "ask_user")["data"]

    assert payload["kind"] == "tool_approval"
    assert EFFECT_KEYS <= set(payload), (
        "the card that asks for consent is the one surface that cannot be "
        "allowed to describe the action in identifiers"
    )
    assert payload["effect"] == "network_egress"
    assert payload["effect_label"] == "Sends data out to the internet"
    assert payload["effect_band"] == "notable"
    assert payload["effect_labels"][0] == payload["effect_label"]


def test_the_sealed_action_keeps_its_own_order_beside_the_ranked_one(monkeypatch):
    # `action` is the sealed input, sorted for a stable digest; the ranked list
    # is a rendering of it. `web_fetch` is the case where the two disagree, so
    # a card reading the wrong one leads with the lesser of the two effects.
    events = _gated_run(monkeypatch, _GATED_FETCH, tool="web_fetch")
    payload = _first(events, "ask_user")["data"]

    assert payload["action"]["effects"] == ["brokered_network_read", "network_egress"]
    assert payload["effects"] == ["network_egress", "brokered_network_read"]
    assert not EFFECT_KEYS & (set(payload["action"]) - {"effects"}), (
        "the presentation sits beside `action`, not inside it — `action` is the "
        "sealed input shown verbatim"
    )


def test_the_ask_user_event_adds_no_second_copy_of_the_presentation(monkeypatch):
    # The event is an envelope around the payload and nothing else. A copy here
    # would be one more place for the same answer to drift, and the producers
    # that never pass through this emit would still not have it.
    event = _first(_gated_run(monkeypatch, _GATED_FETCH, tool="web_fetch"), "ask_user")
    assert set(event) == {"type", "data"}
    assert EFFECT_KEYS <= set(event["data"])


# ── Persistence: the same card after a reload ───────────────────────────────


def test_the_persisted_tool_event_carries_the_effect(monkeypatch):
    events = _run(
        monkeypatch,
        ["```bash\nrm -rf /tmp/scratch\n```"],
        relevant_tools={"bash"},
    )
    saved = _persisted(events)
    assert len(saved) == 1
    assert EFFECT_KEYS <= set(saved[0]), (
        "a card ranked while it streamed and unranked after a refresh is the "
        "same defect with a reload in front of it"
    )
    start = _first(events, "tool_start")
    for key in EFFECT_KEYS:
        assert saved[0][key] == start[key], f"{key} disagrees with the live event"


def test_the_persisted_approved_tool_event_carries_the_effect(monkeypatch):
    events = _approved_run(
        monkeypatch, tool_name="bash", content="rm -rf /tmp/scratch"
    )
    saved = _persisted(events)
    assert len(saved) == 1
    assert saved[0]["approved"] is True
    assert EFFECT_KEYS <= set(saved[0]), (
        "the replay block builds its own event; a fix to the main path does "
        "not reach it"
    )
    assert saved[0]["effect"] == "execute_code"
    assert saved[0]["effect_band"] == "notable"
    assert saved[0]["effect_label"] == "Runs code on this machine"


def test_the_persisted_approval_card_reloads_dressed(monkeypatch):
    # `chatRenderer.addMessage` rebuilds an unanswered approval out of this
    # nested payload. It is the same `public_payload()` the live event carried,
    # which is why the reloaded card reads identically to the live one.
    saved = _persisted(_gated_run(monkeypatch, _GATED_FETCH, tool="web_fetch"))
    assert len(saved) == 1
    card = saved[0]["ask_user"]
    assert EFFECT_KEYS <= set(card)
    assert card["effect_label"] == "Sends data out to the internet"
    assert card["effect_band"] == "notable"
    assert card["approval_id"], "a card with no approval id cannot be answered"
    assert not card.get("resolved"), "an unanswered card is what the reload restores"


def test_a_mismatched_grant_persists_no_effect_claim(monkeypatch):
    # The saved half of `test_a_mismatched_grant_describes_nothing_...`: the
    # action was refused, so there is nothing on screen for a label to describe
    # and nothing in history to reconstruct one from either.
    store = ToolApprovalStore()
    pending = store.create(
        owner="alice",
        session_id="session-1",
        origin_run_id="run-1",
        tool_name="bash",
        content="rm -rf /tmp/scratch",
        workspace=None,
        external_untrusted_context_seen=True,
        capabilities=capabilities_for_action("bash", "rm -rf /tmp/scratch"),
    )
    grant = store.consume(
        pending.approval_id,
        decision="approve",
        owner="alice",
        session_id="session-1",
    )
    _patch(monkeypatch, ["Ran it."])
    events = _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1",
            "small-local-model",
            [{"role": "user", "content": "yes, go ahead"}],
            max_rounds=1,
            owner="mallory",
            session_id="session-1",
            workspace=None,
            relevant_tools=set(pending.selected_tools),
            exact_approval=grant,
        )
    )

    saved = _persisted(events)
    assert saved, "the refusal is still recorded"
    for event in saved:
        assert not EFFECT_KEYS & set(event)
