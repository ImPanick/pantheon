# SPDX-License-Identifier: AGPL-3.0-or-later
"""P7-02 — the assistant may take its own reach away, never give itself more.

`ui_control` moves the chat's own switches, and the browser applies whatever
comes back without asking. Before this row the gate treated "turn the shell on"
the way it treats "change the theme": unasked in every clean run at the default
rung, and unasked in a tainted run once a blanket approval was in hand.

Every test here drives the code — the gate, the executor, the dispatcher, the
approval store, the agent loop — and none reads a source file (`Law 20`). Most
use only names that existed before the row, so against the previous tree they
fail on their assertions and not on an import: evidence that they measure the
defect rather than the new code's vocabulary.
"""

import asyncio
import json
from collections import namedtuple

import pytest

import src.agent_tools  # noqa: F401  (break the agent_tools <-> tool_parsing import cycle)
from src.ai_interaction import do_ui_control
from src.tool_approvals import ToolApprovalStore, tool_approval_store
from src.tool_capabilities import (
    KNOWN_CAPABILITY_TOOLS,
    POST_EXTERNAL_BLOCKED_EFFECTS,
    RUNG_BLOCKED_EFFECTS,
    TOOL_CLASSIFICATION_RECOGNISED,
    ToolRunSecurityContext,
    TrustRung,
    capabilities_for_action,
    capabilities_for_tool,
    describe_effects,
    effect_severity,
)
from src.tool_parsing import parse_tool_blocks
from src.tool_policy import WEB_TOOL_NAMES
from src.tool_schemas import function_call_to_tool_block
from src.tool_security import is_public_blocked_tool

ToolBlock = namedtuple("ToolBlock", ["tool_type", "content"])


# ── The executor, asked directly ────────────────────────────────────────────

def _execute(content):
    return asyncio.run(do_ui_control(content))


def _execute_all(contents):
    async def _go():
        return [await do_ui_control(content) for content in contents]

    return asyncio.run(_go())


def _widens(result):
    """This file's statement of the rule, applied to what the executor returned.

    Off narrows, on widens — except Nobody mode, whose *on* takes memory and
    history away. Chat narrows, Agent widens. Nothing else moves a switch.
    """
    if result.get("ui_event") == "toggle":
        state = bool(result["state"])
        return (not state) if result["toggle_name"] == "incognito" else state
    if result.get("ui_event") == "set_mode":
        return result["mode"] == "agent"
    return False


def _executor_toggles():
    """The switches the executor accepts, learned by asking it — not a copy."""
    error = _execute("toggle not-a-switch on")["error"]
    return error.split("Valid: ", 1)[1].split(", ")


def _widening(switch):
    return f"toggle {switch} {'off' if switch == 'incognito' else 'on'}"


def _escalations():
    return [_widening(switch) for switch in _executor_toggles()] + ["set_mode agent"]


# What the card says for each switch. This file is the statement of that copy,
# and a switch the executor gains without words here fails the test below.
_WORDS = {
    "bash": "turn on Shell access",
    "web": "turn on Web search",
    "research": "turn on Deep Research",
    "rag": "turn on the RAG knowledge base",
    "document_editor": "turn on the Document Editor",
    "incognito": "turn off Nobody mode",
}
_AGENT_WORDS = "switch to Agent mode"


# ── Every widening asks, in a clean run at the default rung ─────────────────

def test_the_executor_really_does_widen_on_each_of_these():
    """The premise, measured: each command below switches something on."""
    for content in _escalations():
        assert _widens(_execute(content)), content


@pytest.mark.parametrize("content", [
    "toggle bash on",
    "toggle web on",
    "toggle rag on",
    "toggle research on",
    "toggle document_editor on",
    "toggle incognito off",
    "set_mode agent",
])
def test_a_clean_default_run_asks_before_the_assistant_widens_its_reach(content):
    decision = ToolRunSecurityContext().decision_for("ui_control", content)

    assert decision.allowed is False
    assert decision.classification == TOOL_CLASSIFICATION_RECOGNISED
    assert decision.reason.startswith("The assistant wants to ")
    # Nothing untrusted entered this run, and a sentence saying so would sit
    # over a card whose `gate.tainted` is false (`P4-04`).
    assert "untrusted" not in decision.reason.lower()
    assert "external" not in decision.reason.lower()
    assert decision.tripped_effects


def test_what_tripped_is_what_the_gate_treats_as_consequential():
    """`P7-07`'s meaning of `tripped_effects`, kept: the part of the grant the
    gate blocks, never "Asks you a question" — which Agent mode includes, and
    which is not why anybody is being asked."""
    blocked = {effect.value for effect in POST_EXTERNAL_BLOCKED_EFFECTS}
    for content in _escalations():
        tripped = ToolRunSecurityContext().decision_for("ui_control", content).tripped_effects
        assert tripped and set(tripped) <= blocked, (content, tripped)
    agent = ToolRunSecurityContext().decision_for("ui_control", "set_mode agent")
    assert "user_interaction" not in agent.tripped_effects
    assert agent.tripped_effects[0] == "destructive"


def test_every_switch_the_executor_accepts_has_its_own_words_on_the_card():
    for switch in _executor_toggles():
        reason = ToolRunSecurityContext().decision_for(
            "ui_control", _widening(switch)
        ).reason
        assert f"The assistant wants to {_WORDS[switch]}." in reason, (switch, reason)
    reason = ToolRunSecurityContext().decision_for("ui_control", "set_mode agent").reason
    assert f"The assistant wants to {_AGENT_WORDS}." in reason


# ── No spelling dodges it ───────────────────────────────────────────────────

_SPELLINGS = [
    # Every alias the executor takes.
    "toggle shell on", "toggle terminal on", "toggle search on",
    "toggle websearch on", "toggle web_search on", "toggle deepresearch on",
    "toggle deep_research on", "toggle documents on", "toggle doc on",
    "toggle docs on", "toggle private off",
    # Casing.
    "TOGGLE BASH ON", "Toggle Shell On", "toggle Web YES", "SET_MODE AGENT",
    "set_mode Agent",
    # Every spelling of yes the executor takes (`B97`).
    "toggle bash true", "toggle bash 1", "toggle bash yes", "toggle bash y",
    "toggle bash enable", "toggle bash enabled", "toggle bash  ON ",
    # Whitespace: tabs, runs, padding, line endings, and Unicode spaces
    # `str.split()` treats as separators.
    "toggle\tbash\ton", "toggle   bash   on", "  toggle bash on  ",
    "\n\ntoggle bash on\n", "toggle bash on\r\n", "toggle bash on",
    "toggle bash on", "toggle bash on\nand a second line", "set_mode\tagent",
    "set_mode agent please",
    # Nobody mode: anything that is not a yes is *off*, the widening direction.
    "toggle incognito no", "toggle incognito 0", "toggle private disable",
    "toggle incognito maybe later",
]


@pytest.mark.parametrize("content", _SPELLINGS)
def test_no_alias_casing_or_whitespace_gets_past_the_gate(content):
    # The spelling has to work on the executor, or it is not a dodge at all.
    assert _widens(_execute(content)), f"not a widening on the executor: {content!r}"
    assert ToolRunSecurityContext().decision_for("ui_control", content).allowed is False


_ARGUMENT_SHAPES = [
    ("ui_control", {"action": "toggle", "name": "bash", "value": "on"}),
    ("ui_control", {"action": "toggle", "name": "Shell", "value": "ON"}),
    # The value folded into the name — the converter joins them with a space.
    ("ui_control", {"action": "toggle", "name": "bash on", "value": ""}),
    ("ui_control", {"action": "toggle", "name": "incognito", "value": "off"}),
    ("ui_control", {"action": "set_mode", "value": "agent"}),
    ("ui_control", {"action": "set_mode", "name": "agent"}),
    # The converter's own tool-name aliases.
    ("ui", {"action": "toggle", "name": "web", "value": "true"}),
    ("control", {"action": "toggle", "name": "research", "value": "yes"}),
]


@pytest.mark.parametrize("name,arguments", _ARGUMENT_SHAPES)
def test_a_native_json_call_is_the_same_command_by_the_time_the_gate_sees_it(
    name, arguments
):
    block = function_call_to_tool_block(name, json.dumps(arguments))

    assert block is not None and block.tool_type == "ui_control"
    assert _widens(_execute(block.content)), block
    assert ToolRunSecurityContext().decision_for(
        block.tool_type, block.content
    ).allowed is False


_TEXT_MODE_CALLS = [
    "```ui_control\ntoggle bash on\n```",
    '<tool_call>{"name": "ui_control", "arguments": '
    '{"action": "set_mode", "value": "agent"}}</tool_call>',
    '[TOOL_CALL]{tool => "ui_control", command => "toggle bash on"}[/TOOL_CALL]',
    '<tool_call><invoke name="ui_control"><parameter name="action">toggle'
    '</parameter><parameter name="name">shell</parameter><parameter '
    'name="value">on</parameter></invoke></tool_call>',
    '{"function":{"arguments":"{\\"action\\":\\"toggle\\",\\"name\\":\\"web\\",'
    '\\"value\\":\\"on\\"}","name":"ui_control"},"type":"function"}',
]


@pytest.mark.parametrize("text", _TEXT_MODE_CALLS)
def test_every_text_mode_call_shape_is_gated_too(text):
    blocks = parse_tool_blocks(text)

    assert [block.tool_type for block in blocks] == ["ui_control"], blocks
    assert _widens(_execute(blocks[0].content)), blocks
    assert ToolRunSecurityContext().decision_for(
        "ui_control", blocks[0].content
    ).allowed is False


def test_json_shaped_content_moves_nothing_so_there_is_nothing_to_ask_about():
    """A fence around raw JSON arrives as JSON-shaped *content*. The executor
    reads it as an unknown action and switches nothing on — which is why the
    gate lets it through, and the property test below is what would catch the
    day the executor learned to read it and the gate did not."""
    for content in (
        '{"action": "toggle", "name": "bash", "value": "on"}',
        '{"action":"set_mode","value":"agent"}',
    ):
        result = _execute(content)
        assert "ui_event" not in result and "error" in result, result


def _corpus():
    actions = ["toggle", "TOGGLE", "Toggle", "set_mode", "SET_MODE", "Set_Mode"]
    names = [
        "bash", "BASH", "shell", "Terminal", "web", "search", "WebSearch",
        "web_search", "rag", "RAG", "research", "deepresearch", "deep_research",
        "document_editor", "documents", "doc", "docs", "incognito", "private",
        "Private", "agent", "Agent", "chat", "CHAT", "bogus", "",
    ]
    values = [
        "on", "off", "ON", "Off", "true", "false", "1", "0", "yes", "no", "y",
        "enable", "enabled", "disable", "maybe", "on please", "",
    ]
    separators = [" ", "\t", "   ", " "]
    corpus = []
    for action in actions:
        for name in names:
            for value in values:
                for sep in separators:
                    corpus.append(sep.join(part for part in (action, name, value) if part))
    corpus += [
        '{"action": "toggle", "name": "bash", "value": "on"}',
        '{"action":"set_mode","value":"agent"}',
        "get_toggles", "clear_highlight", "highlight .x label", "open_panel notes",
        "open_email_reply 12 INBOX reply hello", "toggle", "set_mode",
    ]
    return corpus


def test_the_gate_asks_exactly_when_the_executor_would_widen():
    """The property, both directions, over every combination above.

    Asks for every command the executor would widen on — so no spelling it
    understands gets past — and for nothing else, so turning things off, Chat
    mode, Nobody mode on and every other `ui_control` action stay as unasked as
    they were. The executor's answer is the real one: `do_ui_control` runs.
    """
    corpus = _corpus()
    results = _execute_all(corpus)
    widened = 0
    for content, result in zip(corpus, results):
        decision = ToolRunSecurityContext().decision_for("ui_control", content)
        assert decision.allowed is (not _widens(result)), (content, result)
        widened += _widens(result)
    # Enough of both kinds that the property is about something.
    assert widened > 500 and len(corpus) - widened > 2000, (widened, len(corpus))


# ── At every rung, tainted or clean, and past every blanket yes ─────────────

@pytest.mark.parametrize("rung", list(TrustRung))
@pytest.mark.parametrize("tainted", [False, True])
@pytest.mark.parametrize("bypassed", [False, True])
def test_it_asks_at_every_rung_in_every_run_and_past_any_blanket_approval(
    rung, tainted, bypassed
):
    context = ToolRunSecurityContext(
        rung=rung,
        external_untrusted_context_seen=tainted,
        approval_gate_bypassed=bypassed,
    )
    for content in _escalations():
        assert context.decision_for("ui_control", content).allowed is False, content


def test_a_blanket_approval_still_covers_everything_else_at_the_default_rung():
    """The bypass keeps doing what it did for every other action: a person who
    pressed "allow for this task" in a tainted run is not asked again about the
    next command — only about the assistant handing itself a switch."""
    context = ToolRunSecurityContext(
        external_untrusted_context_seen=True, approval_gate_bypassed=True
    )
    for tool_name, content in (
        ("bash", "curl https://example.com"),
        ("ui_control", "toggle bash off"),
        ("ui_control", "set_theme dark"),
        ("send_email", '{"to": "a@example.com"}'),
    ):
        assert context.decision_for(tool_name, content).allowed is True, tool_name
    assert context.decision_for("ui_control", "toggle bash on").allowed is False


def test_a_standing_allow_rule_does_not_cover_it():
    context = ToolRunSecurityContext(
        rung=TrustRung.ALLOW_LISTED, allow_rule_lookup=lambda *_: True
    )

    assert context.decision_for("ui_control", "toggle bash on").allowed is False
    # And the same rule still answers for the lowering, as before.
    assert context.decision_for("ui_control", "toggle bash off").allowed is True


def test_a_tainted_refusal_says_both_things_that_are_true():
    context = ToolRunSecurityContext()
    context.observe_tool_result("web_fetch", {"output": "a page", "exit_code": 0})

    reason = context.decision_for("ui_control", "toggle shell on").reason

    assert reason.startswith("External untrusted context has already influenced this run.")
    assert "turn on Shell access" in reason


def test_the_same_words_under_another_tool_are_not_a_switch():
    """`toggle bash on` typed into the shell is a shell command, and the gate
    treats it as one — at the default rung in a clean run, unasked."""
    assert ToolRunSecurityContext().decision_for("bash", "toggle bash on").allowed is True
    assert capabilities_for_action("bash", "set_mode agent") == capabilities_for_tool("bash")


# ── Everything else behaves exactly as before ───────────────────────────────
#
# Transcribed from the `decision_for` that shipped before this row, the way
# `tests/test_trust_rung_gate.py` pins `P7-03`: checked against something other
# than the code making the claim.

_ASKING_RUNGS = {TrustRung.ASK_EVERY_TIME, TrustRung.ALLOW_LISTED}


def _gate_before_p7_02(context, tool_name, content):
    if context.delegated_credential and is_public_blocked_tool(tool_name):
        return (
            False,
            f"Tool '{tool_name}' is not available to API-token callers. "
            "It requires an interactive session.",
        )
    if context.approval_gate_bypassed and context.rung not in _ASKING_RUNGS:
        return True, None
    tainted = context.external_untrusted_context_seen
    if not tainted and context.rung not in _ASKING_RUNGS:
        return True, None
    capabilities = capabilities_for_action(tool_name, content)
    blocked = capabilities.effects & (
        POST_EXTERNAL_BLOCKED_EFFECTS if tainted else RUNG_BLOCKED_EFFECTS
    )
    if capabilities.known and not blocked:
        return True, None
    if (
        context.rung is TrustRung.ALLOW_LISTED
        and not tainted
        and context.allow_rule_lookup is not None
        and context.allow_rule_lookup(tool_name, content)
    ):
        return True, None
    effects = ", ".join(sorted(effect.value for effect in blocked))
    if not capabilities.known:
        effects = "unknown/high-impact"
    why = (
        "External untrusted context has already influenced this run. "
        if tainted
        else "This conversation is set to confirm every effectful action. "
    )
    return False, (
        f"{why}Tool '{tool_name}' requires a separate user-authorized action "
        f"because it can cause {effects}."
    )


_UNCHANGED_CONTENTS = (
    None,
    "",
    "toggle bash off",
    "toggle incognito on",
    "set_mode chat",
    "open_panel notes",
    "set_theme dark",
    "switch_model some-model",
    "get_toggles",
    # The widening words, handed to tools that are not `ui_control`.
    "toggle bash on",
    "set_mode agent",
    '{"action":"list"}',
    '{"action":"delete"}',
)


def test_every_other_decision_is_the_one_the_gate_made_before_this_row():
    names = sorted(KNOWN_CAPABILITY_TOOLS) + ["not_a_tool_at_all"]
    compared = 0
    for tool_name in names:
        for content in _UNCHANGED_CONTENTS:
            if tool_name == "ui_control" and content in ("toggle bash on", "set_mode agent"):
                continue
            for rung in TrustRung:
                for tainted in (False, True):
                    for bypassed in (False, True):
                        for lookup in (None, lambda *_: True):
                            context = ToolRunSecurityContext(
                                rung=rung,
                                external_untrusted_context_seen=tainted,
                                approval_gate_bypassed=bypassed,
                                allow_rule_lookup=lookup,
                            )
                            decision = context.decision_for(tool_name, content)
                            assert (decision.allowed, decision.reason) == (
                                _gate_before_p7_02(context, tool_name, content)
                            ), (tool_name, content, rung, tainted, bypassed, lookup)
                            compared += 1
    assert compared > 20000, compared


def test_where_the_old_gate_already_refused_a_widening_it_still_refuses():
    """Tainted runs and the strict rungs asked before this row. The verdict is
    the same; only the sentence changed, to say what is being switched on."""
    for rung in TrustRung:
        for tainted in (False, True):
            context = ToolRunSecurityContext(
                rung=rung, external_untrusted_context_seen=tainted
            )
            for content in _escalations():
                before, _ = _gate_before_p7_02(context, "ui_control", content)
                if before is False:
                    assert context.decision_for("ui_control", content).allowed is False


# ── The card ────────────────────────────────────────────────────────────────

def _mint(context, tool_name, content, store):
    """Mint the card exactly as `src/agent_loop.py` does from a refusal."""
    decision = context.decision_for(tool_name, content)
    assert decision.allowed is False
    return store.create(
        owner="alice",
        session_id="p7-02",
        origin_run_id=context.run_id,
        tool_name=tool_name,
        content=content,
        workspace=None,
        external_untrusted_context_seen=context.external_untrusted_context_seen,
        capabilities=capabilities_for_action(tool_name, content),
        gate_decision=decision,
        taint_trail=context.taint_trail,
    ), decision


def test_the_card_says_what_it_wants_in_the_words_on_the_switch():
    store = ToolApprovalStore()
    pending, decision = _mint(ToolRunSecurityContext(), "ui_control", "toggle bash on", store)
    card = pending.public_payload(reason=decision.reason)

    assert card["description"] == (
        "The assistant wants to turn on Shell access. Only you can give it more "
        "access, so it asks every time — even after you have allowed other actions."
    )
    assert card["gate"]["tainted"] is False
    # "What this can do" names what the switch hands over, most severe first —
    # the shell switch governs the host shell too (`P17-11`).
    assert card["effect_labels"][:2] == [
        "Can permanently delete or overwrite",
        "Runs code on this machine",
    ]
    assert card["effect_band"] == "serious"
    assert card["gate"]["tripped_effects"] == ["destructive", "execute_code"]


def test_the_card_ranks_the_switch_by_what_it_hands_over():
    """Registered as a UI side effect alone, "turn on Shell access" drew the
    lowest band on the card — below the `bash` command it exists to enable,
    which is the inversion `P7-06` was written to end."""
    ui_side = capabilities_for_tool("ui_control").effects
    for content, tools in (
        ("toggle bash on", ["bash", "host_shell"]),
        ("toggle web on", sorted(WEB_TOOL_NAMES)),
        ("toggle research on", ["trigger_research"]),
        (
            "toggle document_editor on",
            ["create_document", "edit_document", "update_document", "suggest_document"],
        ),
    ):
        expected = ui_side.union(*(capabilities_for_tool(tool).effects for tool in tools))
        assert capabilities_for_action("ui_control", content).effects == expected, content

    shell_switch = describe_effects(capabilities_for_action("ui_control", "toggle bash on"))
    shell = describe_effects(capabilities_for_action("bash", "printf hello"))
    assert shell_switch["effect_severity"] >= shell["effect_severity"]
    # Lowering is still exactly a UI side effect.
    assert capabilities_for_action("ui_control", "toggle bash off").effects == ui_side


# ── Answering it: the sealed grant runs the one action, once ────────────────

def _approve(context, content, store, decision="approve_task"):
    pending, _ = _mint(context, "ui_control", content, store)
    grant = store.consume(
        pending.approval_id, decision=decision, owner="alice", session_id="p7-02"
    )
    assert grant is not None
    return grant


def _dispatch(block, context, grant=None):
    from src.tool_execution import execute_tool_block

    return asyncio.run(
        execute_tool_block(
            block,
            session_id="p7-02",
            owner="alice",
            security_context=context,
            exact_approval=grant,
        )
    )[1]


def test_an_approval_minted_in_a_quiet_run_can_be_answered_and_runs_once():
    """The card is answerable. `P7-03` shipped a rung whose cards were not,
    because the replay guard asked the *run* whether its gate was armed — and a
    clean run at the default rung is not. This card is minted in exactly that
    run, so asking the run alone would refuse every answer to it."""
    store = ToolApprovalStore()
    grant = _approve(ToolRunSecurityContext(), "toggle bash on", store)
    resumed = ToolRunSecurityContext(approval_gate_bypassed=grant.allow_remaining_actions)
    assert resumed.gate_is_armed is False, "the premise: this run's gate is quiet"

    result = _dispatch(ToolBlock("ui_control", "toggle bash on"), resumed, grant)

    assert result.get("ui_event") == "toggle", result
    assert (result["toggle_name"], result["state"]) == ("bash", True)

    # Spent. Asked from a fresh clean run, because the one above is tainted now
    # — a `ui_control` result is registered `external_untrusted` — and that
    # refusal would answer first and prove nothing about the claim.
    again = _dispatch(ToolBlock("ui_control", "toggle bash on"), ToolRunSecurityContext(), grant)
    assert again.get("blocked") is True
    assert again["error"] == "The exact-action approval did not match this tool request."


def test_the_grant_covers_its_one_action_and_not_the_next_widening():
    store = ToolApprovalStore()
    grant = _approve(ToolRunSecurityContext(), "toggle bash on", store)
    resumed = ToolRunSecurityContext(approval_gate_bypassed=grant.allow_remaining_actions)

    other = _dispatch(ToolBlock("ui_control", "toggle web on"), resumed, grant)

    assert other.get("blocked") is True and "ui_event" not in other


def test_a_quiet_run_still_refuses_to_replay_anything_else():
    """The guard asks about the action now, and for every other action the
    answer is the one it always gave."""
    store = ToolApprovalStore()
    pending = store.create(
        owner="alice", session_id="p7-02", origin_run_id="r", tool_name="bash",
        content="printf hi", workspace=None, external_untrusted_context_seen=False,
        capabilities=capabilities_for_action("bash", "printf hi"),
    )
    grant = store.consume(
        pending.approval_id, decision="approve_task", owner="alice", session_id="p7-02"
    )

    refused = _dispatch(ToolBlock("bash", "printf hi"), ToolRunSecurityContext(), grant)

    assert refused.get("blocked") is True
    assert refused["error"] == "Exact-action approval requires an armed run security context."


def test_a_yes_given_before_taint_is_still_not_spent_after_it():
    store = ToolApprovalStore()
    grant = _approve(ToolRunSecurityContext(), "toggle bash on", store)
    tainted = ToolRunSecurityContext(
        external_untrusted_context_seen=True, approval_gate_bypassed=True
    )

    refused = _dispatch(ToolBlock("ui_control", "toggle bash on"), tainted, grant)

    assert refused.get("blocked") is True
    assert "before untrusted content entered" in refused["error"]


def test_the_gate_answers_for_the_action_not_only_the_run():
    context = ToolRunSecurityContext()

    assert context.gate_is_armed is False  # unchanged, and still about the run
    assert context.asks_for("ui_control", "toggle bash on") is True
    assert context.asks_for("ui_control", "toggle bash off") is False
    assert context.asks_for("bash", "toggle bash on") is False


# ── Through the real agent loop ─────────────────────────────────────────────

def _drive(monkeypatch, *, rounds):
    """The real loop, the real dispatcher and the real `do_ui_control`, with
    only the model scripted — so the event a browser would apply is the one
    under test."""
    import src.agent_loop as agent_loop

    monkeypatch.setattr(
        agent_loop, "get_setting",
        lambda key, default=None: "gate_on_untrusted" if key == "trust_rung" else default,
        raising=False,
    )
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    scripted = iter(rounds)

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'delta': next(scripted, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    return agent_loop


def _events(agent_loop, *, session_id, max_rounds=2, exact_approval=None, message="go"):
    async def _collect():
        return [
            chunk
            async for chunk in agent_loop.stream_agent_loop(
                "http://local.test/v1",
                "small-local-model",
                [{"role": "user", "content": message}],
                max_rounds=max_rounds,
                relevant_tools={"ui_control"},
                owner="alice",
                session_id=session_id,
                exact_approval=exact_approval,
            )
        ]

    out = []
    for chunk in asyncio.run(_collect()):
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                out.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    return out


def _switch_events(events):
    return [
        (event["data"].get("toggle_name") or event["data"].get("mode"), event["data"].get("state"))
        for event in events
        if event.get("type") == "ui_control"
    ]


def _cards(events):
    return [
        event["ask_user"]
        for event in events
        if event.get("type") == "tool_output"
        and (event.get("ask_user") or {}).get("kind") == "tool_approval"
    ]


def test_through_the_loop_nothing_reaches_the_browser_until_the_person_says_yes(monkeypatch):
    session = "p7-02-loop"
    loop = _drive(monkeypatch, rounds=["```ui_control\ntoggle shell on\n```", "Done."])
    first = _events(loop, session_id=session)

    assert _switch_events(first) == [], "a switch event reached the browser unasked"
    cards = _cards(first)
    assert [card["action"]["content"] for card in cards] == ["toggle shell on"]
    assert "turn on Shell access" in cards[0]["description"]

    grant = tool_approval_store.consume(
        cards[0]["approval_id"], decision="approve_task", owner="alice", session_id=session
    )
    loop = _drive(monkeypatch, rounds=["```ui_control\ntoggle web on\n```", "Done."])
    resumed = _events(loop, session_id=session, exact_approval=grant, message="approved")

    # The approved action ran, once, and reached the browser as the event that
    # moves the switch.
    assert _switch_events(resumed) == [("bash", True)]
    # "Allow for this task" is in hand for the rest of the run, and the next
    # widening still asks.
    later = _cards(resumed)
    assert [card["action"]["content"] for card in later] == ["toggle web on"]
    tool_approval_store.consume(
        later[0]["approval_id"], decision="deny", owner="alice", session_id=session
    )


def test_through_the_loop_switching_something_off_is_still_unasked(monkeypatch):
    loop = _drive(monkeypatch, rounds=["```ui_control\ntoggle shell off\n```", "Done."])
    events = _events(loop, session_id="p7-02-lower")

    assert _cards(events) == []
    assert _switch_events(events) == [("bash", False)]


# ── The allow-rule chooser cannot save a rule the gate will never read ──────

class _ReachedTheStore(Exception):
    pass


def test_an_exact_rule_for_a_widening_is_refused_in_words(monkeypatch):
    from src import tool_allow_rules

    def _no_database():
        raise _ReachedTheStore()

    monkeypatch.setattr(tool_allow_rules, "_database", _no_database)

    with pytest.raises(tool_allow_rules.AllowRuleError) as refused:
        tool_allow_rules.create_rule("alice", "ui_control", "exact", "  toggle shell ON ")
    assert str(refused.value) == (
        "Pantheon asks every time the assistant wants more access, so this "
        "cannot be saved as a rule. Your approval still covers this one action."
    )
    # Everything a rule can still do goes on to the store as it always did.
    for kind, pattern in (
        ("exact", "toggle bash off"),
        ("exact", "set_theme dark"),
        ("prefix", "toggle"),
        ("any", ""),
    ):
        with pytest.raises(_ReachedTheStore):
            tool_allow_rules.create_rule("alice", "ui_control", kind, pattern)
    with pytest.raises(_ReachedTheStore):
        tool_allow_rules.create_rule("alice", "bash", "exact", "toggle bash on")


# ── One reading, shared by the executor and the gate (`Law 7`) ──────────────

def test_an_alias_added_in_one_place_is_learned_by_both(monkeypatch):
    """The executor and the gate read the command through one module. Teach it
    a new alias and both understand it at once; a second map anywhere would be
    a spelling the gate did not know."""
    from types import MappingProxyType

    import src.ui_switches as ui_switches

    widened = dict(ui_switches.TOGGLE_ALIASES)
    widened["zsh"] = "bash"
    monkeypatch.setattr(ui_switches, "TOGGLE_ALIASES", MappingProxyType(widened))

    assert _execute("toggle zsh on")["toggle_name"] == "bash"
    assert ToolRunSecurityContext().decision_for("ui_control", "toggle zsh on").allowed is False


def test_the_executor_answers_through_the_shared_reading():
    from src.ui_switches import switch_request

    for content in _corpus():
        if content.split(None, 1)[0].lower() in ("toggle", "set_mode"):
            assert _execute(content) == switch_request(content), content
