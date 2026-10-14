# SPDX-License-Identifier: AGPL-3.0-or-later
"""The owner's 2026-10-14 report: *"The LLM's use of tools is still very much
intermittent... even with its own MCP's provided. Ensure its capable of using
Pantheon's entire suite of tooling and skills etc."*

**The measurement, re-taken here with the product's own estimator** (`Law 3`,
and `FIX-2026-10-14.md`'s own instruction not to divide by four):
`src/tool_schemas.FUNCTION_TOOL_SCHEMAS` on `0bd089d` is **74 tools, 73,280
characters** of JSON and **21,830 tokens** by `model_context.estimate_tokens` —
19% more than a chars/4 estimate gives. `src/tool_index.ALWAYS_AVAILABLE` is
**three**. Everything else — all sixteen email tools, calendar, notes, tasks,
documents, files, shell, web, research, skills **and every registered MCP
tool** — reached a turn only by winning a **top-8 vector retrieval** inside a
**1.5s** timeout, with a keyword selector as the fallback. So about eleven of
seventy-four were offered and *which* eleven depended on whether an embedding
backend answered. Driven on `0bd089d` with the product on port 8801 against a
recording OpenAI-compatible server and a real stdio MCP server, the same
question twenty times across embeddings up/down, MCP up/down, 128k/32k/8k
windows, Chat and Agent: the `tools` array **varied**. That variation is the
owner's "intermittent".

What is pinned here: the whole suite is offered when it fits the model's proven
window with working room left; when it does not fit, the narrowing is
deterministic, says so, and never drops a tool the request named. Nothing about
what may be *run* is in this file — `disabled_tools` still decides that and a
case asserts it.

Driven through the real loop and the real planner wherever the question is
behavioural (`Law 20`); the seams are the model stream and the window lookup.
"""
import asyncio
import json
import random
import re
import time

import pytest

import src.agent_loop as al
import src.tool_index as ti
from src.context_budget import (
    DEFAULT_BUDGET,
    TOOL_SUITE_SHARE,
    agent_input_budget,
    measure_request_segments,
    tool_schema_tokens,
    tool_suite_room,
)
from src.mcp_manager import McpManager
from src.tool_index import (
    SUITE_REASON_WHOLE,
    SUITE_REASON_WINDOW,
    SUITE_REASON_WINDOW_UNKNOWN,
    ToolIndex,
    names_the_request_pins,
    plan_tool_suite,
    suite_priority_order,
)
from src.tool_policy import ToolPolicy, known_tool_names
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

# The owner's own question, from `/work/notes/owner-shots/2026-10-09-osrs-chat-export.md`.
OWNER_QUESTION = (
    "Research: Find out the ins and outs of the new Oldschool RuneScape Raids "
    "releasing on October 20th... its called the fractured archive. I mostly "
    "want to know, what are we going to expect to fight, and a strategy to "
    "defeat the mobs."
)
LOCAL = "http://127.0.0.1:8080/v1"
UNKNOWN_MODEL = "local-unknown-1"
BACKTICKED = re.compile(r"`([a-z][a-z0-9_]{2,40})`")

W128K, W32K, W8K = 128_000, 32_000, 8_192


def _settings(overrides=None):
    data = dict(overrides or {})

    def get_setting(key, default=None):
        return data.get(key, default)

    return get_setting


def _mcp_manager(tools=2) -> McpManager:
    """A real manager holding one registered server's tools."""
    mgr = McpManager()
    mgr._connections["osrs"] = {"name": "osrs-wiki", "status": "connected"}
    mgr._tools["osrs"] = [
        {"name": f"lookup_{i}",
         "description": f"Look up thing {i} in the wiki.",
         "input_schema": {"type": "object",
                          "properties": {"name": {"type": "string"}},
                          "required": ["name"]}}
        for i in range(tools)
    ]
    return mgr


def _base(monkeypatch, mgr=None, window=W128K, settings=None):
    monkeypatch.setattr(al, "get_setting", settings or _settings(), raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(al, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: mgr, raising=False)
    monkeypatch.setattr(al, "_load_mcp_disabled_map", lambda: {}, raising=False)
    monkeypatch.setattr("src.model_context.budget_context_for_model",
                        lambda url, model, fallback=0: window)


def _drive(monkeypatch, rounds, *, message=OWNER_QUESTION, model=UNKNOWN_MODEL,
           url=LOCAL, relevant_tools=None, policy=None, history=True):
    """Run the real loop. Answers (events, [{tools, prompt}] per round).

    `history=True` sends a prior exchange, because a FIRST turn with no
    recognised domain is `_direct_low_signal` and answers with no tools at all
    — a different path, and not the one this file measures.
    """
    sent = []
    script = iter(rounds)

    async def scripted(candidates, messages, **kwargs):
        sent.append({
            "tools": sorted((t.get("function") or {}).get("name")
                            for t in (kwargs.get("tools") or [])),
            "schemas": list(kwargs.get("tools") or []),
            "prompt": "\n".join(m.get("content") for m in messages
                                if isinstance(m.get("content"), str)),
        })
        step = next(script, "All done.")
        yield "data: " + json.dumps({"delta": step}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", scripted)

    async def _run_tool(block, *a, **k):
        return block.tool_type, {"output": "ok", "exit_code": 0}

    monkeypatch.setattr(al, "execute_tool_block", _run_tool)

    msgs = []
    if history:
        msgs += [{"role": "user", "content": "Hello, I play Old School RuneScape."},
                 {"role": "assistant", "content": "Good to know."}]
    msgs.append({"role": "user", "content": message})

    async def collect():
        return [c async for c in al.stream_agent_loop(
            url, model, msgs, max_rounds=len(rounds) + 1, owner="local",
            relevant_tools=relevant_tools, tool_policy=policy or ToolPolicy())]

    events = [json.loads(c[6:]) for c in asyncio.run(collect())
              if c.startswith("data: ") and not c.startswith("data: [DONE]")]
    return events, sent


# ── 1. the measurement, with the product's own counter ───────────────────────

def test_the_whole_builtin_set_costs_what_the_measurement_says():
    """74 tools, 73,280 chars, 21,830 tokens on `0bd089d`. Pinned as a band
    rather than three literals so adding a tool does not redden the file, and
    as the relationship the brief's number got wrong: a chars/4 estimate is
    more than 15% low against the product's own estimator."""
    chars = len(json.dumps(FUNCTION_TOOL_SCHEMAS))
    tokens = tool_schema_tokens(FUNCTION_TOOL_SCHEMAS)
    assert len(FUNCTION_TOOL_SCHEMAS) >= 74
    assert 60_000 <= chars <= 120_000, chars
    assert 18_000 <= tokens <= 40_000, tokens
    quarter = chars / 4
    assert tokens > quarter * 1.15, (
        f"chars/4 estimates {quarter:.0f} against the real {tokens}; the brief's "
        "~18,300 was that estimate")


def test_offering_a_tool_costs_its_schema_and_its_prose():
    """Offering a tool spends the window twice — the schema in the `tools`
    array and the `TOOL_SECTIONS` block in the prompt — and budgeting only the
    schemas was measured wrong: a real turn against a 9,000-token window was
    sent a prompt that left no room for the reply
    (`tests/test_a_local_vllm_is_asked_for_what_it_can_serve.py`)."""
    schemas = al._builtin_schema_token_costs()
    prose = al._suite_prompt_token_costs()
    assert sum(prose.values()) > 5_000, "the prompt sections cost something real"
    for name in ("manage_calendar", "list_emails", "bash"):
        assert prose.get(name, 0) > 0, name
    # `generate_image` was the last built-in with real prose and no schema
    # (`P17-06` counted seven of these; `B1356` closed one and `B1357` /
    # `D-2026-10-14-01` §1 closed the remaining six). So it is now the clearest
    # example of this case's own thesis rather than the exception to it: a tool
    # offered on both channels is charged on both.
    assert "generate_image" in prose, sorted(prose)[:5]
    assert "generate_image" in schemas, sorted(schemas)[:5]
    assert schemas["generate_image"] > 0 and prose["generate_image"] > 0
    # And no section is charged prose while costing no schema, which is what
    # being on one channel only looked like in the budget.
    prose_only = sorted(n for n in prose if n not in schemas and n in al.TOOL_SECTIONS)
    assert prose_only == [], prose_only


def test_the_context_wheel_and_the_planner_count_a_schema_the_same_way():
    """`Law 7`. The meter the person reads and the arithmetic the selector does
    are one computation; a selector that disagreed with the wheel would make
    the wheel a second opinion about its own subject."""
    some = FUNCTION_TOOL_SCHEMAS[:5]
    wheel = {c["key"]: c for c in measure_request_segments([], tools=some)["categories"]}
    assert wheel["tools"]["tokens"] == tool_schema_tokens(some)
    assert wheel["tools"]["count"] == len(some)


def test_always_available_was_three_tools_of_seventy_four():
    """The denominator of the owner's complaint, pinned so the defect's size
    stays legible."""
    assert len(ti.ALWAYS_AVAILABLE) == 3
    assert set(ti.ALWAYS_AVAILABLE) == {"manage_memory", "ask_user", "update_plan"}
    always = [s for s in FUNCTION_TOOL_SCHEMAS
              if (s.get("function") or {}).get("name") in ti.ALWAYS_AVAILABLE]
    assert tool_schema_tokens(always) < tool_schema_tokens(FUNCTION_TOOL_SCHEMAS) / 10


# ── 2. the window, read the way Pantheon reads it ────────────────────────────

def test_a_128k_window_carries_the_whole_suite():
    room = tool_suite_room(W128K, _settings())
    assert room["window_known"] and room["basis"] == "proven_window"
    assert room["room"] >= tool_schema_tokens(FUNCTION_TOOL_SCHEMAS)
    assert room["budget"] == agent_input_budget(W128K, _settings())


@pytest.mark.parametrize("window", [W32K, W8K])
def test_a_small_window_does_not(window):
    room = tool_suite_room(window, _settings())
    assert room["window_known"]
    assert room["room"] < tool_schema_tokens(FUNCTION_TOOL_SCHEMAS)


def test_an_unknown_window_takes_the_conservative_branch_and_says_so():
    """#4122's rule: a fallback 128K is not proof a model holds 128K, so the
    room is scaled off the conservative default the trimmer uses, and `basis`
    names the branch (`Law 10`)."""
    room = tool_suite_room(0, _settings())
    assert room["window_known"] is False
    assert room["basis"] == "window_unknown"
    assert room["room"] == int(DEFAULT_BUDGET * TOOL_SUITE_SHARE)
    assert room["room"] < tool_suite_room(W128K, _settings())["room"]


def test_an_explicit_input_budget_is_honoured_by_the_rooms_budget():
    """`CHAT-M-4`'s computation is the one that answers, not a second one."""
    gs = _settings({"agent_input_token_budget": 9000})
    assert tool_suite_room(W128K, gs)["budget"] == 9000


# ── 3. the plan: the whole suite, or a deterministic part ────────────────────

def _cost_of(name):
    for schema in FUNCTION_TOOL_SCHEMAS:
        if (schema.get("function") or {}).get("name") == name:
            return tool_schema_tokens(schema)
    return 0


ALL_NAMES = sorted((s.get("function") or {}).get("name") for s in FUNCTION_TOOL_SCHEMAS)


def test_the_whole_suite_is_offered_when_it_fits():
    plan = plan_tool_suite(ALL_NAMES, cost=_cost_of,
                           room=tool_suite_room(W128K, _settings())["room"],
                           window=W128K, pinned=ti.ALWAYS_AVAILABLE)
    assert plan.partial is False
    assert plan.reason == SUITE_REASON_WHOLE
    assert plan.offered == frozenset(ALL_NAMES)
    assert plan.withheld == ()


def test_the_same_input_gives_the_same_tools_every_time():
    """The whole of the owner's report. Twenty plans over a shuffled candidate
    iterable, on a window too small for the suite: one answer."""
    room = tool_suite_room(W8K, _settings())["room"]
    answers = set()
    for seed in range(20):
        shuffled = list(ALL_NAMES)
        random.Random(seed).shuffle(shuffled)
        plan = plan_tool_suite(shuffled, cost=_cost_of, room=room, window=W8K,
                               pinned=ti.ALWAYS_AVAILABLE,
                               keyword_picks={"web_search", "web_fetch"},
                               domains=["web"], domain_map=al._DOMAIN_TOOL_MAP)
        answers.add((tuple(sorted(plan.offered)), plan.withheld))
    assert len(answers) == 1, "the narrowed set depended on the input's order"


def test_a_narrowed_set_is_filled_by_a_declared_order_not_a_score():
    """Rule 3. The order is the tiers, and nothing in it is a number a vector
    lane produced."""
    order = suite_priority_order(
        ALL_NAMES, pinned={"ask_user"}, mcp=set(),
        keyword_picks={"trigger_research"}, domains=["email"],
        domain_map=al._DOMAIN_TOOL_MAP)
    assert order[0] == "ask_user"
    assert order[1] == "trigger_research"
    email = set(al._DOMAIN_TOOL_MAP["email"])
    first_email = min(order.index(n) for n in email if n in order)
    cookbook = set(al._DOMAIN_TOOL_MAP["cookbook"])
    first_cookbook = min(order.index(n) for n in cookbook if n in order)
    assert first_email < first_cookbook
    assert sorted(order) == sorted(set(order)) == ALL_NAMES


def test_an_mcp_tool_is_in_the_suite_before_the_rest_of_the_builtins():
    """Rule 5. A person who registered a server registered it to be reached."""
    order = suite_priority_order(
        set(ALL_NAMES) | {"mcp__osrs__lookup_raid"},
        pinned={"ask_user"}, mcp={"mcp__osrs__lookup_raid"},
        keyword_picks=set(), domain_map=al._DOMAIN_TOOL_MAP)
    assert order[1] == "mcp__osrs__lookup_raid"


def test_a_tool_the_request_names_is_never_withheld():
    """Rule 4, on a room that fits almost nothing."""
    pinned = set(ti.ALWAYS_AVAILABLE) | names_the_request_pins(
        "use web search and then manage_calendar", ALL_NAMES)
    plan = plan_tool_suite(ALL_NAMES, cost=_cost_of, room=1, window=W8K, pinned=pinned)
    assert "web_search" in plan.offered
    assert "manage_calendar" in plan.offered
    assert plan.partial and plan.over_room


def test_a_domain_the_request_names_is_never_withheld():
    """Rule 4's second half: a domain, through the map the loop already has."""
    pinned = set(ti.ALWAYS_AVAILABLE) | set(al._DOMAIN_TOOL_MAP["email"])
    plan = plan_tool_suite(ALL_NAMES, cost=_cost_of, room=200, window=W8K, pinned=pinned)
    assert set(al._DOMAIN_TOOL_MAP["email"]) <= plan.offered


def test_an_mcp_server_the_person_names_pins_its_tools():
    pins = names_the_request_pins(
        "ask my osrs-wiki server about the raid", ALL_NAMES,
        mcp_tools={"osrs-wiki": {"mcp__osrs__lookup_raid"},
                   "osrs": {"mcp__osrs__lookup_raid"}})
    assert "mcp__osrs__lookup_raid" in pins


def test_a_fully_qualified_mcp_name_in_the_request_is_matched_not_rewritten():
    """`FORBIDDEN.md` Part 1: the name shape is read and handed back as it is."""
    pins = names_the_request_pins("call mcp__osrs__lookup_raid please",
                                  {"mcp__osrs__lookup_raid"})
    assert pins == {"mcp__osrs__lookup_raid"}


def test_a_word_that_is_not_a_tool_pins_nothing():
    assert names_the_request_pins("what is the weather like", ALL_NAMES) == set()


def test_the_withheld_list_is_sorted_and_the_record_is_stable():
    room = tool_suite_room(W8K, _settings())["room"]
    plan = plan_tool_suite(ALL_NAMES, cost=_cost_of, room=room, window=W8K,
                           pinned=ti.ALWAYS_AVAILABLE)
    assert plan.partial
    assert list(plan.withheld) == sorted(plan.withheld)
    record = plan.as_record()
    assert record["candidates"] == len(ALL_NAMES)
    assert record["offered"] == len(plan.offered)
    assert record["reason"] == SUITE_REASON_WINDOW
    assert record["window"] == W8K and record["window_known"] is True


def test_an_unknown_window_narrows_under_its_own_reason():
    room = tool_suite_room(0, _settings())
    plan = plan_tool_suite(ALL_NAMES, cost=_cost_of, room=room["room"],
                           window=room["window"], window_known=room["window_known"],
                           pinned=ti.ALWAYS_AVAILABLE)
    assert plan.partial and plan.reason == SUITE_REASON_WINDOW_UNKNOWN


def test_a_skipped_tool_does_not_stop_the_walk():
    """First-fit by priority, not stop-at-first-miss: a cheap tool *after* an
    expensive one is still offered, which is strictly more tools for the same
    determinism. The expensive one is named so it comes FIRST in the order,
    which is the only arrangement that can tell the two rules apart."""
    cost = {"aa_expensive": 1000, "bb_cheap": 10, "cc_cheap": 10}
    plan = plan_tool_suite(list(cost), cost=cost.get, room=100, window=W8K,
                           keyword_picks=list(cost))
    assert plan.offered == frozenset({"bb_cheap", "cc_cheap"})
    assert plan.withheld == ("aa_expensive",)


# ── 4. the turn: the real planner, through the real loop ─────────────────────

def test_a_turn_offers_every_tool_the_person_may_use(monkeypatch):
    _base(monkeypatch, _mcp_manager())
    _events, sent = _drive(monkeypatch, ["Nothing to do."])
    offered = set(sent[0]["tools"])
    assert len(offered) > 60, sorted(offered)
    # Every family, not a top-8's worth of one.
    for name in ("list_emails", "manage_calendar", "manage_notes", "manage_tasks",
                 "manage_documents", "read_file", "trigger_research", "manage_skills",
                 "manage_memory", "ask_user", "update_plan"):
        assert name in offered, name


def test_every_registered_mcp_tool_is_in_the_request(monkeypatch):
    _base(monkeypatch, _mcp_manager(tools=3))
    _events, sent = _drive(monkeypatch, ["Nothing to do."])
    mcp = sorted(n for n in sent[0]["tools"] if n.startswith("mcp__"))
    assert mcp == ["mcp__osrs__lookup_0", "mcp__osrs__lookup_1", "mcp__osrs__lookup_2"]


def test_the_set_does_not_change_when_the_vector_index_is_gone(monkeypatch):
    """The owner's "intermittent", as one assertion. The index answers, then
    raises, then hangs past the 1.5s selection timeout: one `tools` array."""
    seen = []
    for broken in ("ok", "raise", "hang"):
        def get_tool_index(_broken=broken):
            if _broken == "raise":
                raise RuntimeError("No embedding lanes available")
            if _broken == "hang":
                time.sleep(al._TOOL_SELECTION_TIMEOUT_SECONDS + 0.5)
            return None
        monkeypatch.setattr(ti, "get_tool_index", get_tool_index, raising=False)
        _base(monkeypatch, _mcp_manager())
        _events, sent = _drive(monkeypatch, ["Nothing to do."])
        seen.append(tuple(sent[0]["tools"]))
    assert len(set(seen)) == 1, "the offered set depended on the embedding backend"


def test_the_same_question_twenty_times_offers_the_same_tools(monkeypatch):
    arrays = set()
    for _ in range(20):
        _base(monkeypatch, _mcp_manager())
        _events, sent = _drive(monkeypatch, ["Nothing to do."])
        arrays.add(tuple(sent[0]["tools"]))
    assert len(arrays) == 1


def test_a_tool_the_person_may_not_use_is_still_not_offered(monkeypatch):
    """`FORBIDDEN.md` Part 2's neighbourhood: this row widens what is *offered*
    and nothing about what may be run. `disabled_tools` still decides, and it
    is where `blocked_tools_for_owner`, the delegated-credential cap, the
    feature flags, plan mode and the tool policy all land."""
    _base(monkeypatch, _mcp_manager())
    monkeypatch.setattr(al, "blocked_tools_for_owner",
                        lambda owner: {"bash", "python", "read_file"}, raising=False)
    _events, sent = _drive(monkeypatch, ["Nothing to do."])
    offered = set(sent[0]["tools"])
    assert not ({"bash", "python", "read_file"} & offered)
    assert "manage_calendar" in offered


def test_a_non_admin_turn_is_offered_no_mcp_tool(monkeypatch):
    """Unchanged: `blocked_tools_for_owner` non-empty means `mcp_mgr = None`,
    because MCP names cannot be enumerated for a public user."""
    _base(monkeypatch, _mcp_manager())
    monkeypatch.setattr(al, "blocked_tools_for_owner", lambda owner: {"bash"}, raising=False)
    _events, sent = _drive(monkeypatch, ["Nothing to do."])
    assert not [n for n in sent[0]["tools"] if n.startswith("mcp__")]


def test_a_small_window_narrows_the_turn_and_keeps_what_it_named(monkeypatch):
    _base(monkeypatch, _mcp_manager(), window=W8K)
    _events, sent = _drive(monkeypatch, ["Nothing to do."])
    offered = set(sent[0]["tools"])
    whole = {(s.get("function") or {}).get("name") for s in FUNCTION_TOOL_SCHEMAS}
    assert (offered & whole) < whole, "an 8k window was sent the whole suite"
    assert "trigger_research" in offered, (
        "the request says \"Research:\" and the keyword selector names this tool")
    assert {"ask_user", "update_plan", "manage_memory"} <= offered


def test_a_word_the_product_maps_to_a_tool_is_the_request_naming_it(monkeypatch):
    """Rule 4's third form. `_KEYWORD_HINTS` is the product's own word-to-tool
    table, so *"Research: find out…"* naming `trigger_research` is the request
    naming a tool and not a ranking of it — pinned, not a tier below. Measured
    on the tightest room there is: an endpoint that reports no window."""
    _base(monkeypatch, _mcp_manager(), window=0)
    _events, sent = _drive(monkeypatch, ["Nothing to do."])
    offered = set(sent[0]["tools"])
    assert "trigger_research" in offered, (
        "the tool the keyword selector picked for this question by name was "
        "budgeted away")
    _base(monkeypatch, _mcp_manager(), window=0)
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           message="check my inbox and archive what I have read")
    offered = set(sent[0]["tools"])
    assert {"list_emails", "archive_email"} <= offered, sorted(offered)


def test_a_workflow_step_still_gets_only_its_own_tools(monkeypatch):
    """`P22-16`. The step's own list is the selection; the suite never widens
    past it."""
    _base(monkeypatch, _mcp_manager())
    policy = ToolPolicy(allowed_tools=["manage_notes"])
    _events, sent = _drive(monkeypatch, ["Nothing to do."], policy=policy)
    assert sent[0]["tools"] == ["manage_notes"]


# ── 5. a partial turn says so, and names no tool ─────────────────────────────

def test_a_partial_turn_tells_the_model_the_set_is_partial(monkeypatch):
    _base(monkeypatch, _mcp_manager(), window=W8K)
    _events, sent = _drive(monkeypatch, ["Nothing to do."])
    assert "tool set is partial" in sent[0]["prompt"]
    assert "say in one sentence what you need" in sent[0]["prompt"]


def test_a_whole_suite_turn_says_nothing_about_being_partial(monkeypatch):
    _base(monkeypatch, _mcp_manager(), window=W128K)
    _events, sent = _drive(monkeypatch, ["Nothing to do."])
    assert "tool set is partial" not in sent[0]["prompt"]


def test_the_partial_notice_names_no_tool():
    """`B1304`'s lesson: a prompt that backticks a tool the request withholds
    sends the model looking for it. The notice says a count and a reason."""
    notice = al._partial_suite_notice(11, 74, "window")
    named = set(BACKTICKED.findall(notice)) & known_tool_names()
    assert not named, named
    assert "11" in notice and "74" in notice
    assert al._partial_suite_notice(74, 74, "whole_suite") == ""


def test_the_notice_says_which_branch_narrowed_it():
    assert "context window" in al._partial_suite_notice(5, 74, "window")
    assert "did not report" in al._partial_suite_notice(5, 74, "window_unknown")
    assert "its task needs" in al._partial_suite_notice(5, 74, "route")


def test_a_route_that_narrowed_after_the_plan_reports_its_own_count():
    """A clamp between the plan and the prompt is a narrowing too, and the
    numerator is what the route really ships (`Law 10`)."""
    suite = ti.ToolSuite(candidates=frozenset(ALL_NAMES),
                         offered=frozenset(ALL_NAMES), reason=SUITE_REASON_WHOLE)
    notice = al._suite_notice_for(suite, {"manage_notes", "ask_user"}, set())
    assert "2 of your" in notice
    assert "its task needs" in notice


# ── 6. the receipt says what it withheld ─────────────────────────────────────

def test_the_run_records_what_it_withheld_and_why(monkeypatch):
    written = []
    from src import events as ev
    monkeypatch.setattr(ev, "record_event",
                        lambda kind, **kw: written.append((kind, kw)) or True)
    assert ev.record_run_config(suite={
        "offered": 11, "candidates": 74, "withheld": ["manage_tasks", "bash"],
        "reason": "window", "room_tokens": 3276, "cost_tokens": 3100,
        "window": 8192, "window_known": True, "over_room": False}, owner="local")
    kind, kw = written[-1]
    assert kind == "run_config"
    suite = kw["detail"]["suite"]
    assert suite["offered"] == 11 and suite["candidates"] == 74
    assert suite["withheld"] == ["bash", "manage_tasks"]
    assert suite["reason"] == "window" and suite["window"] == 8192


def test_the_turn_writes_the_receipt_through_the_real_loop(monkeypatch):
    written = []
    from src import events as ev
    real = ev.record_run_config

    def spy(**kw):
        if kw.get("suite") is not None:
            written.append(kw["suite"])
        return real(**kw)

    monkeypatch.setattr(ev, "record_run_config", spy)
    _base(monkeypatch, _mcp_manager(), window=W8K)
    _drive(monkeypatch, ["Nothing to do."])
    assert written, "the turn narrowed and recorded nothing"
    assert written[0]["withheld"], written[0]
    assert written[0]["candidates"] > written[0]["offered"]


# ── 7. `B1330` — the index-init timeout kept the keyword selector ────────────

def test_the_index_init_timeout_leaves_the_keyword_selector_to_run(monkeypatch):
    """`B1330`. The branch set `_relevant_tools = set(ALWAYS_AVAILABLE)`, and a
    non-empty `_relevant_tools` makes the deterministic keyword fallback skip —
    so under CPU pressure the turn lost the tool the selector would have picked
    by name. Driven with retrieval put back in front of the turn, which is the
    only configuration where that branch can run at all."""
    monkeypatch.setattr(al, "_TOOL_RETRIEVAL_SELECTS_THE_TURN", True)

    def slow_get_tool_index():
        time.sleep(al._TOOL_SELECTION_TIMEOUT_SECONDS + 0.4)
        return None

    monkeypatch.setattr(ti, "get_tool_index", slow_get_tool_index, raising=False)
    # The branch is reachable only when the suite planner did not answer — the
    # two configurations being `_TOOL_RETRIEVAL_SELECTS_THE_TURN` and a planner
    # that raised. Both are driven: the planner raises here so the retrieval
    # block runs, which is what `B1330` is about.
    def _planner_down(*a, **k):
        raise RuntimeError("no window to read")

    monkeypatch.setattr(al, "plan_turn_tool_suite", _planner_down)
    _base(monkeypatch, _mcp_manager())
    _events, sent = _drive(monkeypatch, ["Nothing to do."])
    offered = set(sent[0]["tools"])
    assert "trigger_research" in offered, (
        "the index-init timeout threw away the keyword selector's own pick")
    assert set(ti.ALWAYS_AVAILABLE) <= offered | {"manage_memory"}


# ── 8. `B1343` — the index's text and its fingerprint ────────────────────────

def test_changing_a_description_moves_the_index_fingerprint():
    """`B1343`. The hash was `sha256(sorted(BUILTIN_TOOL_DESCRIPTIONS.keys()))` —
    the keys and nothing else — so by its own value an edited description was
    the same index as the one before it."""
    base = ti.builtin_index_fingerprint()
    moved = ti.builtin_index_fingerprint({**ti.schema_descriptions(),
                                          "ask_user": "something else entirely"})
    assert base != moved
    descs = dict(ti.BUILTIN_TOOL_DESCRIPTIONS)
    try:
        ti.BUILTIN_TOOL_DESCRIPTIONS["bash"] = descs["bash"] + " and one more thing"
        assert ti.builtin_index_fingerprint() != base
    finally:
        ti.BUILTIN_TOOL_DESCRIPTIONS.clear()
        ti.BUILTIN_TOOL_DESCRIPTIONS.update(descs)
    assert ti.builtin_index_fingerprint() == base


def test_the_indexed_text_is_derived_from_the_schema_description():
    """`B1343`'s open question, answered: the schema's words are in the text
    retrieval embeds, so an edit to what the model reads reaches the index."""
    schema_desc = ti.schema_descriptions()
    assert schema_desc, "no schema descriptions were readable"
    for name in ("ask_user", "update_plan", "manage_calendar"):
        text = ti.builtin_index_text(name)
        assert schema_desc[name][:60] in text, name
        assert text.startswith(f"Tool: {name}")


def test_the_index_text_keeps_the_retrieval_words_too():
    """`Law 1`. `BUILTIN_TOOL_DESCRIPTIONS` carries retrieval-shaped hints the
    schema has no business carrying; deriving must not drop them."""
    text = ti.builtin_index_text("list_served_models")
    assert "what's running" in text or "show my forge" in text


def test_a_tool_with_no_schema_still_has_index_text():
    """Seven entries are fenced-channel only (`P17-06`)."""
    assert ti.builtin_index_text("draft_email").startswith("Tool: draft_email")
    assert len(ti.builtin_index_text("draft_email")) > 40


def test_the_fingerprint_is_read_and_not_only_written():
    """It gated nothing before, which is why the row's own stated consequence
    could not happen and why the key could be wrong without anyone noticing."""
    calls = []

    class Lane:
        name = "fastembed"

        class collection:
            @staticmethod
            def get(**kw):
                return {"ids": []}

            @staticmethod
            def delete(**kw):
                pass

            @staticmethod
            def upsert(**kw):
                calls.append(len(kw.get("ids") or []))

        @staticmethod
        def encode(docs):
            return [[0.0] for _ in docs]

        @staticmethod
        def count():
            return 1

    index = ToolIndex.__new__(ToolIndex)
    index._lanes = [Lane()]
    index._healthy = True
    index.index_builtin_tools()
    index.index_builtin_tools()
    assert len(calls) == 1, "a second call re-encoded an index that had not moved"


# ── 9. `Law 1` — nothing the earlier waves built is gone ─────────────────────

def test_the_keyword_selector_still_answers_the_same_set():
    """`P17-14`'s one selector, still one, still deterministic."""
    picked = ToolIndex.select_without_embeddings(
        "check my inbox for the latest mail", set(ti.ALWAYS_AVAILABLE))
    assert "list_emails" in picked and "read_email" in picked
    # Issue #1707, pinned where `P17-14` left it: "unread" is a substring of
    # "unreadable" and a raw-substring match force-included the whole email
    # family. Word boundaries, so it includes nothing.
    assert ToolIndex.select_without_embeddings("this document is unreadable",
                                               set()) == set()
    assert ToolIndex.select_without_embeddings(
        "visit https://example.com and tell me the title",
        set()) == {"web_search", "web_fetch"}


def test_get_tools_for_query_is_still_there_for_the_assistant_path():
    """`src/task_scheduler.py`'s check-ins and `app.py`'s warmup call it; the
    vector lane is off for the turn's offer, not removed (`Law 1`)."""
    assert callable(ToolIndex.get_tools_for_query)
    assert callable(ti.get_tool_index)
    assert callable(ToolIndex.retrieve)


def test_a_withheld_mcp_tool_is_not_in_the_request_either(monkeypatch):
    """The plan enumerates MCP names itself, so when it narrows, an MCP tool it
    left out is a decision and the schema filter has to honour it — otherwise
    the prompt and the request disagree about the same turn (`Law 13`)."""
    _base(monkeypatch, _mcp_manager(tools=40), window=W8K)
    _events, sent = _drive(monkeypatch, ["Nothing to do."])
    mcp = [n for n in sent[0]["tools"] if n.startswith("mcp__")]
    assert 0 < len(mcp) < 40, (
        f"{len(mcp)} of 40 MCP schemas reached an 8k request")
    assert "mcp__osrs__lookup_0" in mcp, "the narrowing was not the declared order"


def test_the_mcp_schema_filter_still_ships_every_tool_when_no_selector_saw_them(monkeypatch):
    """`fx6-tools`' `B1302`, unchanged: a caller-provided set says nothing
    about MCP, so the MCP schemas are not filtered by it."""
    _base(monkeypatch, _mcp_manager())
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           relevant_tools={"web_search", "ask_user"})
    assert "mcp__osrs__lookup_0" in sent[0]["tools"]
