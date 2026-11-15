# SPDX-License-Identifier: AGPL-3.0-or-later
"""An Agent turn sends what the request needs, once, and says why it went again.

`B2113`, `B2114`, `B2115`, `B2116`. Measured on the owner's desktop
(2026-11-15, a 27B model on LM Studio, 262,144-token window, effort Low): the
same short question cost 830 input tokens in Chat and 12,008 in Agent mode,
193 s of prefill, and then a **second** request of 12,094 tokens after the
answer was already finished, because the reply ended "Want me to …?" and the
question-instead-of-work supervisor pushed it back. The turn took 453 s.

The model is a test subject, not the target: every check below drives the
real loop against a loopback OpenAI-compatible server (`tool_suite_probe`),
whatever model name it answers to.
"""
import asyncio
import json
import tempfile

import pytest

from tests.helpers import tool_suite_probe as probe

CAT = "What's a good name for a grey cat?"
OFFER = "Here are three: Miso, Pixel and Juniper. Want me to suggest more?"


def _estimate(body: dict) -> int:
    """Characters over four, the estimator the owner's figures line up with."""
    return (len(json.dumps(body.get("messages") or []))
            + len(json.dumps(body.get("tools") or []))) // 4


def _drive(prompt, reply, *, usage=None, timings=None, max_rounds=6):
    async def go():
        scratch = tempfile.mkdtemp()
        async with probe.probe_world(scratch, mcp_states=("absent",),
                                     local_tool_budget=8000) as world:
            world.endpoint._srv.reply = reply
            world.endpoint._srv.usage = usage
            world.endpoint._srv.timings = timings
            cell = probe.Cell(embeddings="down", mcp="absent", window="large", mode="agent")
            record = await probe.drive_turn(world, cell, prompt, wire=True,
                                            max_rounds=max_rounds)
            return list(world.endpoint.recorded), record
    return asyncio.run(go())


def _buckets(record):
    for event in record.events:
        if isinstance(event, dict) and event.get("usage_buckets"):
            return event["usage_buckets"]
        if not isinstance(event, dict):
            continue
        for key in ("data", "metrics"):
            metrics = event.get(key)
            if isinstance(metrics, dict) and metrics.get("usage_buckets"):
                return metrics["usage_buckets"]
    return []


# ── a finished answer is one request ─────────────────────────────────────────

def test_a_finished_answer_that_offers_more_is_one_request():
    """Red on dev: two requests, the second only the supervisor's note."""
    bodies, _record = _drive(CAT, OFFER)
    assert len(bodies) == 1, [b["messages"][-1] for b in bodies]


def test_an_offer_of_a_tool_step_the_person_asked_for_is_still_pushed():
    """`B1327` stands: the person asked for a look, the reply offered one."""
    bodies, _record = _drive(
        "check the server logs and tell me why it crashed",
        "It may be the config. Do you want me to check the logs?")
    assert len(bodies) >= 2


def test_a_push_keeps_the_request_prefix_the_server_already_read():
    """Red on dev: the note was folded into the system prompt, so the first
    bytes of the second request differed and its whole prefix was re-read."""
    bodies, _record = _drive(
        "check the server logs and tell me why it crashed",
        "It may be the config. Do you want me to check the logs?", max_rounds=2)
    assert len(bodies) == 2
    first, second = bodies[0]["messages"], bodies[1]["messages"]
    assert second[0] == first[0], "the system prompt changed between rounds"
    assert second[:len(first)] == first
    added = second[len(first):]
    assert [m["role"] for m in added] == ["assistant", "user"], added
    assert added[0]["content"].startswith("It may be the config.")
    assert added[1]["content"].startswith("APPLICATION NOTE\n")
    assert "instead of doing it" in added[1]["content"]


# ── every request says why it ran ────────────────────────────────────────────

def test_each_request_records_why_it_ran_and_what_it_carried():
    _bodies, record = _drive(
        "check the server logs and tell me why it crashed",
        "It may be the config. Do you want me to check the logs?", max_rounds=2)
    buckets = _buckets(record)
    assert len(buckets) == 2, buckets
    first, second = (b["request"] for b in buckets)
    assert first["continuation_reason"] == "first"
    assert second["continuation_reason"] == "supervisor:handback"
    assert first["prefix_fingerprint"] == second["prefix_fingerprint"]
    assert first["fingerprint"] != second["fingerprint"]
    assert first["request_id"] != second["request_id"]
    assert first["turn_id"] == second["turn_id"]
    assert {"system", "tools", "skills", "conversation"} <= set(first["sections"])


def test_the_server_s_finish_reason_and_cached_prompt_are_kept():
    """LM Studio and llama.cpp report usage after the last delta; the round
    keeps why the server stopped and how much of the prompt it had cached."""
    _bodies, record = _drive(
        CAT, "Miso.",
        usage={"prompt_tokens": 900, "completion_tokens": 3,
               "prompt_tokens_details": {"cached_tokens": 640}},
        timings={"prompt_n": 260, "cache_n": 640, "prompt_ms": 410.0})
    (bucket,) = _buckets(record)
    assert bucket["input_tokens"] == 900
    assert bucket["request"]["finish_reason"] == "stop"
    assert bucket["request"]["prompt_cached_tokens"] == 640


# ── the first request is proportional to the request ─────────────────────────

def test_a_question_that_needs_no_tool_is_not_sent_the_suite():
    """Red on dev: 23 tool schemas and ~10.8K estimated tokens; now 6 and ~5.4K."""
    bodies, _record = _drive(CAT, "Miso.")
    (body,) = bodies
    offered = {t["function"]["name"] for t in body.get("tools") or []}
    # The loop's two primitives (`ask_user`, `update_plan`), the way to the
    # rest (`find_tools`), and what the probe's own skill brings (`B1426`,
    # `B1737`); none of the 17 that only filled the room.
    assert offered <= {"ask_user", "update_plan", "find_tools", "manage_memory",
                       "use_skill", "manage_skills"}, offered
    assert "find_tools" in offered
    assert _estimate(body) < 6000, _estimate(body)


def test_a_partial_suite_offers_what_was_asked_and_nothing_to_fill_the_room():
    from src.tool_index import plan_tool_suite
    pool = {f"tool_{i}" for i in range(40)} | {"find_tools", "ask_user", "web_search"}
    suite = plan_tool_suite(pool, cost=lambda _n: 100, room=2000,
                            pinned={"ask_user"}, keyword_picks={"web_search"},
                            local_cap=2000)
    assert suite.partial
    assert set(suite.offered) == {"ask_user", "find_tools", "web_search"}
    # The room is still the room when a caller asks for it to be used.
    filled = plan_tool_suite(pool, cost=lambda _n: 100, room=2000,
                             pinned={"ask_user"}, keyword_picks={"web_search"},
                             local_cap=2000, fill=True)
    assert len(filled.offered) == 20
    # A connected MCP server is the person asking for its tools.
    with_mcp = plan_tool_suite(pool | {"mcp__tracker__file_issue"}, cost=lambda _n: 100,
                               room=2000, pinned={"ask_user"}, keyword_picks={"web_search"},
                               mcp={"mcp__tracker__file_issue"}, local_cap=2000)
    assert "mcp__tracker__file_issue" in with_mcp.offered


# ── everything stays reachable ───────────────────────────────────────────────

def test_every_tool_is_listed_by_area_with_no_cutoff():
    from src.tool_policy import selectable_tool_names
    from src.tools.system import tool_area_listing
    mcp = {"mcp__tracker__file_issue": "File an issue in the tracker."}
    index = tool_area_listing("", mcp_tools=mcp)
    areas = [line[2:].rsplit(" (", 1)[0] for line in index.splitlines()
             if line.startswith("- ")]
    listed = set()
    for area in areas:
        listed |= {line[2:].split(" — ")[0] for line in
                   tool_area_listing(area, mcp_tools=mcp).splitlines()
                   if line.startswith("- ")}
    missing = (set(selectable_tool_names()) | set(mcp)) - listed - {"find_tools"}
    assert not missing, sorted(missing)


def test_a_rare_tool_is_found_by_exact_name_and_by_words_without_embeddings():
    from src.tools.system import find_tool_matches
    mcp = {"mcp__tracker__file_issue": "File an issue in the bug tracker."}
    by_name = find_tool_matches("", ["mcp__tracker__file_issue"], mcp_tools=mcp)
    assert [m["name"] for m in by_name] == ["mcp__tracker__file_issue"]
    by_words = find_tool_matches("file a bug tracker issue", [], mcp_tools=mcp)
    assert "mcp__tracker__file_issue" in [m["name"] for m in by_words]
    for name in ("unsubscribe_email", "list_cookbook_servers", "vault_unlock"):
        assert [m["name"] for m in find_tool_matches("", [name], mcp_tools={})] == [name]


def test_find_tools_with_an_area_lists_and_loads_nothing():
    from src.tools.system import do_find_tools
    result = asyncio.run(do_find_tools(json.dumps({"area": "Email"})))
    assert result["found"] == []
    assert "send_email" in result["output"] and "unsubscribe_email" in result["output"]


# ── the effort setting says what it does ─────────────────────────────────────

LMSTUDIO = "http://localhost:1234/v1"


def test_a_qwen3_hybrid_can_switch_thinking_off():
    """Red on dev: "off" normalized to Auto, and Low turned thinking ON."""
    from src import reasoning_effort as effort
    model = "qwen3.8-27b"
    assert effort.normalize_level("off") == effort.OFF
    ids = [lvl["id"] for lvl in effort.effort_support(LMSTUDIO, model)["levels"]]
    assert ids[0] == effort.OFF
    payload = {"model": model, "messages": []}
    effort.apply_to_payload(payload, LMSTUDIO, model, effort.OFF)
    assert payload["chat_template_kwargs"]["enable_thinking"] is False
    messages = effort.apply_to_messages(
        [{"role": "system", "content": "Be brief."}], LMSTUDIO, model, effort.OFF)
    assert messages[0]["content"].endswith("/no_think")


def test_low_on_a_switch_with_no_depth_says_it_is_only_words():
    from src import reasoning_effort as effort
    rows = {r["id"]: r for r in effort.effort_support(LMSTUDIO, "qwen3.8-27b")["levels"]}
    assert "only a written note" in rows["low"]["how"]
    payload = {"model": "qwen3.8-27b", "messages": []}
    effort.apply_to_payload(payload, LMSTUDIO, "qwen3.8-27b", "low")
    assert payload["chat_template_kwargs"]["enable_thinking"] is True


def test_off_is_not_offered_where_nothing_reads_it():
    from src import reasoning_effort as effort
    for url, model in (("https://api.openai.com/v1", "gpt-5.1"),
                       ("https://api.anthropic.com", "claude-opus-5-5"),
                       (LMSTUDIO, "openai/gpt-oss-20b")):
        ids = [lvl["id"] for lvl in effort.effort_support(url, model)["levels"]]
        assert effort.OFF not in ids, (url, model, ids)
