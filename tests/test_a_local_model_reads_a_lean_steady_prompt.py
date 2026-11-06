# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1751`. A model served locally reads a lean prompt that stays the same.

The owner, 2026-11-05, with LM Studio logs from a local `qwen3.8-27b`: *"We
need to figure out why the LLM takes SOO long to process the prompt — is it
because we are absolutely BLASTING the LLM with tool shit before we even serve
the prompt? Looks like it sends the full tool inventory/instructions along
with EVERY prompt."* His context wheel for a three-message chat: ~35K tokens,
25.9K of them tool definitions (86 tools), at a prompt-processing speed of
68-167 tokens a second.

Two causes, both measured with the product's own loop and a recording server:

1. The suite's room was 40% of the window, so a 262K window shipped all of it.
   A local server pays for every token in time, so its room is also capped by
   `local_tool_budget_tokens` (8,000 by default; 0 switches it off).
2. On a narrowed turn the set was re-chosen from each message's words, so the
   system prompt and the tool block changed every turn and the server's cached
   prefix was thrown away. A conversation now keeps the set it was offered.

`find_tools` keeps the rest of the suite one call away, so nothing narrowed
here becomes unreachable.
"""
import asyncio
import json

import pytest

from src import context_budget as cb
from src.tool_index import FIND_TOOLS, SUITE_REASON_LOCAL, plan_tool_suite
from src.tools.system import find_tool_matches
from tests.helpers import tool_suite_probe as probe


def _settings(**data):
    return lambda key, default=None: data.get(key, default)


# ── the room ────────────────────────────────────────────────────────────────

def test_a_local_server_is_capped_at_the_local_budget():
    room = cb.tool_suite_room(262_144, _settings(), local=True)
    assert room["room"] == cb.DEFAULT_LOCAL_TOOL_BUDGET
    assert room["local_cap"] == cb.DEFAULT_LOCAL_TOOL_BUDGET


def test_a_remote_server_keeps_the_window_share():
    room = cb.tool_suite_room(262_144, _settings(), local=False)
    assert room["room"] == int(262_144 * cb.TOOL_SUITE_SHARE)
    assert room["local_cap"] == 0


def test_zero_switches_the_local_ceiling_off():
    room = cb.tool_suite_room(262_144, _settings(local_tool_budget_tokens=0), local=True)
    assert room["room"] == int(262_144 * cb.TOOL_SUITE_SHARE)
    assert room["local_cap"] == 0


def test_a_window_smaller_than_the_budget_still_rules():
    room = cb.tool_suite_room(8_192, _settings(), local=True)
    assert room["room"] == int(8_192 * cb.TOOL_SUITE_SHARE)
    assert room["local_cap"] == 0


# ── the plan ────────────────────────────────────────────────────────────────

_POOL = {f"tool_{i:02d}" for i in range(30)} | {FIND_TOOLS, "ask_user"}


def _plan(pinned=(), keep=(), room=1000, local_cap=1000):
    return plan_tool_suite(_POOL, cost=lambda n: 100, room=room, window=262_144,
                           pinned=pinned, keep=keep, local_cap=local_cap)


def test_a_partial_turn_always_carries_find_tools():
    plan = _plan(pinned={"ask_user"})
    assert plan.partial
    assert FIND_TOOLS in plan.offered
    assert plan.reason == SUITE_REASON_LOCAL


def test_a_conversation_keeps_its_set_when_nothing_new_is_named():
    first = _plan(pinned={"ask_user", "tool_25"})
    second = _plan(pinned={"ask_user"}, keep=first.offered)
    assert second.offered == first.offered


def test_a_newly_named_tool_joins_the_kept_set_and_nothing_else_moves():
    first = _plan(pinned={"ask_user"})
    second = _plan(pinned={"ask_user", "tool_29"}, keep=first.offered, room=2000)
    assert second.offered == first.offered | {"tool_29"}


def test_a_kept_set_that_no_longer_fits_is_planned_afresh():
    first = _plan(pinned={"ask_user"}, room=1500)
    second = _plan(pinned={"ask_user"}, keep=first.offered, room=500)
    assert len(second.offered) < len(first.offered)


def test_the_whole_suite_needs_no_find_tools_notice():
    plan = _plan(room=10_000, local_cap=0)
    assert not plan.partial


# ── find_tools' search ───────────────────────────────────────────────────────

@pytest.mark.parametrize("query,expected", [
    ("calendar events next week", "manage_calendar"),
    ("add a contact to my address book", "manage_contact"),
    ("list my notes", "manage_notes"),
    ("git commit", "git"),
    ("generate an image of a cat", "generate_image"),
])
def test_find_tools_ranks_the_tool_the_words_describe_first(query, expected):
    found = find_tool_matches(query, mcp_tools={})
    assert found and found[0]["name"] == expected, found


def test_find_tools_loads_by_name_and_never_finds_itself():
    found = [f["name"] for f in find_tool_matches("find tools", ["manage_tasks"], mcp_tools={})]
    assert found[0] == "manage_tasks"
    assert FIND_TOOLS not in found


def test_find_tools_searches_mcp_tools_too():
    found = find_tool_matches("osrs wiki lookup", mcp_tools={
        "mcp__osrs__lookup": "Look up an item in the OSRS wiki."})
    assert found[0]["name"] == "mcp__osrs__lookup"


# ── through the product's own loop ──────────────────────────────────────────

TURNS = [
    "Give me a couple business ideas that I can run through agents and get passive income with",
    "haha this is funny, now what is the weather like in Paris",
    "ok thanks, and what is 17 times 23?",
]


def _drive_conversation(scratch, budget):
    async def run():
        import src.agent_loop as al
        from src.tool_policy import ToolPolicy

        async with probe.probe_world(scratch, mcp_states=("absent",),
                                     local_tool_budget=budget) as world:
            history, bodies = [], []
            for text in TURNS:
                world.endpoint.clear()
                history.append({"role": "user", "content": text})
                async for _ in al.stream_agent_loop(
                        world.endpoint.url, probe.WINDOW_MODELS["large"], list(history),
                        max_rounds=2, owner=probe.ADMIN_USER, disabled_tools=set(),
                        tool_policy=ToolPolicy(),
                        context_length=probe.WINDOW_TOKENS["large"],
                        session_id=f"lean-{budget}"):
                    pass
                history.append({"role": "assistant", "content": "Nothing to do."})
                bodies.append(world.endpoint.recorded[0])
            return bodies

    return asyncio.run(run())


@pytest.fixture(scope="module")
def conversations(tmp_path_factory):
    return {
        "lean": _drive_conversation(str(tmp_path_factory.mktemp("lean")), 8000),
        "whole": _drive_conversation(str(tmp_path_factory.mktemp("whole")), 0),
    }


def _tool_chars(body):
    return len(json.dumps(body.get("tools") or []))


def test_a_local_model_is_sent_a_fraction_of_the_suite(conversations):
    lean, whole = conversations["lean"][0], conversations["whole"][0]
    assert len(lean["tools"]) < len(whole["tools"]) / 2
    assert _tool_chars(lean) < _tool_chars(whole) / 3
    assert FIND_TOOLS in {t["function"]["name"] for t in lean["tools"]}


def test_every_turn_of_a_local_conversation_sends_the_same_prefix(conversations):
    bodies = conversations["lean"]
    first = bodies[0]
    for body in bodies[1:]:
        assert body["messages"][0] == first["messages"][0]
        assert body["tools"] == first["tools"]


def test_find_tools_makes_a_withheld_tool_callable_next_round(tmp_path):
    async def run():
        async with probe.probe_world(str(tmp_path), mcp_states=("absent",),
                                     local_tool_budget=8000) as world:
            cell = probe.Cell(embeddings="down", mcp="absent", window="large", mode="chat")
            find = probe.reply_shapes(FIND_TOOLS, {"query": "add a contact to my address book"})
            call = probe.reply_shapes("manage_contact", {"action": "list"})
            return await probe.drive_turn(
                world, cell, "Please help me get things set up for the new client, Dana Ruiz.",
                script=[find["native"], call["native"], "Done."], dispatch="real")

    record = asyncio.run(run())
    assert "manage_contact" not in record.requests[0]["tools"]
    assert "manage_contact" in record.requests[1]["tools"]
    assert [name for name, _ in record.dispatched] == [FIND_TOOLS, "manage_contact"]
    loaded = next(ev for ev in record.events
                  if ev.get("type") == "tool_output" and ev.get("tool") == FIND_TOOLS)
    assert "manage_contact" in str(loaded.get("output"))


# ── side calls answer without a reasoning pass ───────────────────────────────

def test_a_side_call_asks_a_local_thinking_model_not_to_think(monkeypatch):
    from src import llm_core

    monkeypatch.setattr(llm_core, "_is_self_hosted_openai_compatible", lambda url: True)
    monkeypatch.setattr(llm_core, "_is_ollama_openai_compat_url", lambda url: False)
    payload = {}
    llm_core._turn_thinking_off(payload, "http://127.0.0.1:1234/v1")
    assert payload == {"chat_template_kwargs": {"enable_thinking": False}}


def test_a_cloud_api_is_never_sent_the_switch(monkeypatch):
    from src import llm_core

    monkeypatch.setattr(llm_core, "_is_self_hosted_openai_compatible", lambda url: False)
    monkeypatch.setattr(llm_core, "_is_ollama_openai_compat_url", lambda url: False)
    payload = {}
    llm_core._turn_thinking_off(payload, "https://api.openai.com/v1")
    assert payload == {}
