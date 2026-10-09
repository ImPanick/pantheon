# SPDX-License-Identifier: AGPL-3.0-or-later
"""The owner's 2026-10-09 report: *"MCP's arent being properly reached or used.
Models jave MCP and tool capability but arent actually using them properly."*

Measured first, with the showcase harness (`scripts/showcase/`): this checkout's
`app.py` on a throwaway data directory, pointed at a recording
OpenAI-compatible server on loopback, one stdio MCP server registered through
`POST /api/mcp/servers`, and the owner's own question from
`/work/notes/owner-shots/2026-10-09-osrs-chat-export.md`. What the upstream
request body carried, on the tree at `99134cf`:

  * `local-unknown-1` — an endpoint added through the Settings form, so
    `supports_tools` is `None`: **`tools_sent=0`**, in Chat mode and in Agent
    mode, on the same log line as `relevant_tools=[…15 tools…]`. Not a tool
    refused; a tool selected and then dropped on the way to the request,
    because the decision was a list of model-name substrings.
  * `gemma-4-26b` — the name matches that list: 30 schemas and **`mcp=[]`**.
    Every MCP tool gone, because the schema filter asks the selected set and
    `ToolIndex.select_without_embeddings` — the selector that runs when there
    is no embedding backend, which on a native install is always — cannot see
    an MCP tool name at all.
  * both: the prompt backticked tool names the request did not carry, among
    them `trigger_research`. The model's own reasoning in the export: it wanted
    a `trigger_research` tool *"not explicitly in the tool list but implied by
    the system prompt's mention of 'Research X'"*.
  * ```mcp__{id}__{tool} did not parse. A bare `{"name","arguments"}` object
    did not parse unless the tool was `web_search` or `web_fetch`.
  * one MCP tool with a schema a strict server refuses took the whole request
    down with it (`HTTP 400`), every other tool included.
  * a registered server that was not running was named nowhere the model or the
    person could see, and a call to a server that had gone said
    `MCP server not connected: 47a5fba5`.

Driven through the real loop with a scripted model and a real `McpManager`
(`Law 20`); the seams are the model stream and, where a tool must run, nothing
— the dispatcher is the product's.
"""
import asyncio
import json
import re

import pytest

import src.agent_loop as al
from src.mcp_manager import McpManager
from src.tool_parsing import parse_tool_blocks, strip_tool_blocks
from src.tool_policy import ToolPolicy, known_tool_names
from src.tool_schemas import (
    FUNCTION_TOOL_SCHEMAS,
    sanitize_tool_parameters,
    strict_schema_problems,
)

# The owner's question, verbatim from the export.
OWNER_QUESTION = (
    "Research: Find out the ins and outs of the new Oldschool RuneScape Raids "
    "releasing on October 20th... its called the fractured archive. I mostly "
    "want to know, what are we going to expect to fight, and a strategy to "
    "defeat the mobs."
)
# A local OpenAI-compatible server that is not Ollama: llama.cpp's default port.
LOCAL = "http://127.0.0.1:8080/v1"
UNKNOWN_MODEL = "local-unknown-1"
BACKTICKED = re.compile(r"`([a-z][a-z0-9_]{2,40})`")


def _mcp_manager(*, down: bool = False, broken_schema: bool = False) -> McpManager:
    """A real manager holding one registered server's tools."""
    mgr = McpManager()
    mgr._connections["osrs"] = {"name": "osrs-wiki", "status": "connected"}
    tools = [{
        "name": "lookup_raid",
        "description": "Look up an Old School RuneScape raid: bosses, mechanics, strategy.",
        "input_schema": {"type": "object",
                         "properties": {"name": {"type": "string", "description": "The raid"}},
                         "required": ["name"]},
    }]
    if broken_schema:
        tools.append({
            "name": "broken_shape",
            "description": "A tool whose schema a strict server refuses.",
            "input_schema": {
                "properties": {"mixed": {"type": ["string", "null"]},
                               "bag": {"type": "array"}},
                "required": ["mixed", "absent"],
                "x_unsupported": {"nope": 1},
            },
        })
    mgr._tools["osrs"] = tools
    if down:
        mgr._connections["dead"] = {"name": "dead-wiki", "status": "error",
                                    "error": "Connection closed"}
        mgr._tools["dead"] = []
    return mgr


def _base(monkeypatch, mgr=None):
    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(al, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: mgr, raising=False)
    monkeypatch.setattr(al, "_load_mcp_disabled_map", lambda: {}, raising=False)


def _drive(monkeypatch, rounds, *, message=OWNER_QUESTION, model=UNKNOWN_MODEL,
           url=LOCAL, relevant_tools=None, policy=None, max_rounds=None,
           dispatched=None, tool_output="ok"):
    """Run the real loop. Answers (events, [{tools, prompt}] per round).

    `dispatched`, when given, records every `ToolBlock` the loop handed the
    dispatcher — the seam is `execute_tool_block`, exactly as in
    `tests/test_an_ai_step_uses_only_its_tools.py`, because what is being
    measured here is whether a call the model wrote is parsed and dispatched.
    The approval gate downstream of it is `FORBIDDEN.md` Part 2 and is not
    stood down for a test.
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
        if isinstance(step, list):
            calls = [{"name": n, "arguments": json.dumps(a)} for n, a in step]
            yield "data: " + json.dumps({"type": "tool_calls", "calls": calls}) + "\n\n"
        else:
            yield "data: " + json.dumps({"delta": step}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", scripted)

    async def _run_tool(block, *a, **k):
        if dispatched is not None:
            dispatched.append(block)
        return block.tool_type, {"output": tool_output, "exit_code": 0}

    monkeypatch.setattr(al, "execute_tool_block", _run_tool)

    async def collect():
        return [c async for c in al.stream_agent_loop(
            url, model, [{"role": "user", "content": message}],
            max_rounds=max_rounds or len(rounds) + 1, owner="local",
            relevant_tools=relevant_tools,
            tool_policy=policy or ToolPolicy())]

    events = [json.loads(c[6:]) for c in asyncio.run(collect())
              if c.startswith("data: ") and not c.startswith("data: [DONE]")]
    return events, sent


# ── 1. what is in the request's `tools` array ────────────────────────────────

def test_an_unknown_model_name_is_not_a_reason_to_send_no_tools(monkeypatch):
    """`D-2026-10-07-02` §1. A name is not a capability, and unknown means
    offer the tools and let the server answer. The measurement this replaces:
    `tools_sent=0` for `local-unknown-1` with 15 tools selected."""
    _base(monkeypatch, _mcp_manager())
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           relevant_tools={"web_search", "web_fetch", "ask_user"})
    assert sent[0]["tools"], "a local OpenAI-compatible server was sent no tools at all"
    assert "web_search" in sent[0]["tools"]


def test_the_offer_ladder_only_says_no_where_something_reported():
    """The three answers, and which of them `fenced` is reserved for."""
    assert al.tool_schema_offer(True, LOCAL, UNKNOWN_MODEL) == "native"
    assert al.tool_schema_offer(False, LOCAL, UNKNOWN_MODEL) == "fenced"   # a person said so
    assert al.tool_schema_offer(None, "http://127.0.0.1:11434/v1", "qwen3:8b") == "fenced"
    assert al.tool_schema_offer(None, "http://127.0.0.1:11434/api/chat", "qwen3:8b") == "fenced"
    # Nobody reported: both channels, never neither.
    for name in (UNKNOWN_MODEL, "gemma-4-26b", "some-finetune-v2", "gpt-oss-20b"):
        assert al.tool_schema_offer(None, LOCAL, name) == "both"


def test_an_mcp_tool_is_in_the_request_even_when_retrieval_never_saw_it(monkeypatch):
    """`ToolIndex.select_without_embeddings` is built-in keyword hints and
    nothing else, so a set it produced says nothing about MCP. Filtering the
    MCP schemas by it dropped every one of them, which is the owner's report."""
    _base(monkeypatch, _mcp_manager())
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           relevant_tools={"web_search", "web_fetch", "ask_user"})
    assert "mcp__osrs__lookup_raid" in sent[0]["tools"], (
        "the MCP tool was filtered out by a selector that cannot see MCP names")


def test_the_mcp_tool_name_keeps_its_protected_shape(monkeypatch):
    """`FORBIDDEN.md` Part 1: `mcp__{server_id}__{tool_name}`, unchanged."""
    _base(monkeypatch, _mcp_manager())
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           relevant_tools={"web_search", "ask_user"})
    mcp = [n for n in sent[0]["tools"] if n.startswith("mcp__")]
    assert mcp == ["mcp__osrs__lookup_raid"]


# ── 2. the prompt promises only what the array carries ───────────────────────

def _promised_but_absent(prompt: str, offered) -> list:
    """Tool names the prompt backticks on a line that names no offered tool."""
    known = set(known_tool_names())
    offered = set(offered)
    out = set()
    for line in prompt.split("\n"):
        named = {n for n in BACKTICKED.findall(line) if n in known}
        if named and not (named & offered):
            out |= named - offered
    return sorted(out)


def test_the_prompt_does_not_name_a_tool_the_request_withholds(monkeypatch):
    """The export's own defect: the prompt said *"'Research X' means
    `trigger_research`"* on a turn whose `tools` array had no such entry."""
    _base(monkeypatch, _mcp_manager())
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           relevant_tools={"web_search", "web_fetch", "ask_user"})
    assert "trigger_research" not in sent[0]["tools"]
    assert "trigger_research" not in sent[0]["prompt"]
    assert _promised_but_absent(sent[0]["prompt"], sent[0]["tools"]) == []


def test_the_research_rule_ships_when_its_tool_does(monkeypatch):
    """`Law 1`: the guidance is not lost, it is gated on its own tool."""
    _base(monkeypatch, _mcp_manager())
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           relevant_tools={"web_search", "trigger_research", "ask_user"})
    assert "trigger_research" in sent[0]["tools"]
    assert '"Research X" means `trigger_research`' in sent[0]["prompt"]


@pytest.mark.parametrize("available,absent", [
    ({"web_search", "web_fetch"}, "trigger_research"),
    ({"web_search"}, "trigger_research"),
])
def test_a_rule_line_naming_only_absent_tools_is_dropped(available, absent):
    prompt = al._assemble_prompt(set(available) | {"ask_user"}, set(), compact=True)
    assert absent not in prompt
    assert "web_search" in prompt            # the rest of the block survives


# ── 3. "on October" is not a machine ─────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    (OWNER_QUESTION, False),
    ("the raid releases on October 20th", False),
    ("remind me on Monday", False),
    ("the launch review is on Thursday 20th", False),
    ("serve minimax m2.7 on gpu-box", True),
    ("download the model on cybertooth", True),
    ("what is running on this machine", True),
    ("list the local files", True),
    ("tail the serve output from workstation", True),
])
def test_a_date_is_not_a_named_machine(text, expected):
    """The named-machine alternative matched any word after "on"/"from", so
    *"releasing on October 20th"* made the owner's question a local-machine
    task and the Terminus clamp replaced the turn's tools with its own set —
    which is where `trigger_research` went."""
    assert al._looks_like_local_computer_request(text) is expected


def test_the_owners_question_keeps_the_tool_it_selected(monkeypatch):
    """End of that chain: the deep-research tool the keyword selector picked
    for this question is still in the request."""
    _base(monkeypatch, _mcp_manager())
    _events, sent = _drive(monkeypatch, ["Nothing to do."])
    assert "trigger_research" in sent[0]["tools"], (
        "the Terminus clamp fired on a date and took the selected tool with it")


# ── 4. schemas a strict server can read ──────────────────────────────────────

def test_every_schema_in_the_register_is_servable():
    """llama.cpp, LM Studio and vLLM validate or compile the WHOLE `tools`
    array, so one unreadable schema costs the request. Four were unreadable:
    `api_call.body`, `app_api.body`, `app_api.query`, `manage_mcp.env` — an
    object with no `properties` and no `additionalProperties`, which a
    schema-to-grammar converter reads as *only `{}` is valid*."""
    offenders = {
        entry["function"]["name"]: strict_schema_problems(entry["function"].get("parameters"))
        for entry in FUNCTION_TOOL_SCHEMAS if entry.get("type") == "function"
    }
    assert {n: p for n, p in offenders.items() if p} == {}
    assert len(offenders) >= 70        # the register, not an empty list


def test_the_five_refusable_shapes_are_named():
    problems = strict_schema_problems({
        "properties": {"mixed": {"type": ["string", "null"]}, "bag": {"type": "array"}},
        "required": ["mixed", "absent"],
        "x_unsupported": {"nope": 1},
    })
    joined = " | ".join(problems)
    assert "unknown keyword 'x_unsupported'" in joined
    assert "union type" in joined
    assert "no 'items'" in joined
    assert "not a property" in joined
    assert "with no 'type'" in joined


def test_an_open_object_is_not_a_closed_one():
    """The normaliser only ever loosens: `manage_settings`' `value` really does
    take any JSON, and must not be narrowed to make a checker happy."""
    assert strict_schema_problems({"description": "any JSON"}) == []
    assert sanitize_tool_parameters({"description": "any JSON"}, _top=False) == {
        "description": "any JSON"}
    assert sanitize_tool_parameters({"type": "object"})["additionalProperties"] is True


def test_one_bad_mcp_schema_does_not_reach_the_request(monkeypatch):
    """The whole array went down with it: `HTTP 400 Invalid
    'tools[1].function.parameters'`, measured against a server that refuses."""
    mgr = _mcp_manager(broken_schema=True)
    _base(monkeypatch, mgr)
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           relevant_tools={"web_search", "ask_user"})
    by_name = {(s.get("function") or {}).get("name"): s for s in sent[0]["schemas"]}
    assert "mcp__osrs__broken_shape" in by_name, "the tool itself must still be offered"
    for name, schema in by_name.items():
        assert strict_schema_problems(schema["function"]["parameters"]) == [], name
    # The ordinary tool's own schema is untouched: the server's words stand.
    assert by_name["mcp__osrs__lookup_raid"]["function"]["parameters"] == {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The raid"}},
        "required": ["name"]}


# ── 5. a tool call in any shape a local server emits ─────────────────────────

MCP_CALL = {"name": "Fractured Archive"}


@pytest.mark.parametrize("shape", ["fenced", "tool_call_block", "bare_json",
                                   "function_wrapped", "tool_calls_array"])
def test_a_local_servers_tool_call_is_parsed_whatever_its_shape(shape):
    name = "mcp__osrs__lookup_raid"
    text = {
        "fenced": "```" + name + "\n" + json.dumps(MCP_CALL) + "\n```",
        "tool_call_block": "<tool_call>" + json.dumps(
            {"name": name, "arguments": MCP_CALL}) + "</tool_call>",
        "bare_json": json.dumps({"name": name, "arguments": MCP_CALL}),
        "function_wrapped": json.dumps(
            {"type": "function", "function": {"name": name,
                                              "arguments": json.dumps(MCP_CALL)}}),
        "tool_calls_array": json.dumps(
            {"tool_calls": [{"function": {"name": name,
                                          "arguments": json.dumps(MCP_CALL)}}]}),
    }[shape]
    blocks = parse_tool_blocks(text)
    assert [b.tool_type for b in blocks] == [name], shape
    assert json.loads(blocks[0].content) == MCP_CALL


def test_a_bare_json_call_to_a_builtin_is_parsed_too():
    """Measured before: this shape parsed for `web_search` (Pattern 6 knows the
    web tools) and returned `[]` for every other tool in the product."""
    blocks = parse_tool_blocks(json.dumps(
        {"name": "manage_notes", "arguments": {"action": "list"}}))
    assert [b.tool_type for b in blocks] == ["manage_notes"]


def test_an_ordinary_json_reply_is_not_a_tool_call():
    assert parse_tool_blocks(json.dumps({"name": "Rowan", "arguments": {"x": 1}})) == []
    assert parse_tool_blocks(json.dumps({"raid": "Fractured Archive"})) == []


def test_a_fenced_mcp_call_that_ran_is_not_also_shown():
    text = ("Looking it up.\n```mcp__osrs__lookup_raid\n"
            + json.dumps(MCP_CALL) + "\n```\nDone.")
    assert "mcp__osrs__lookup_raid" not in strip_tool_blocks(text)
    assert "mcp__osrs__lookup_raid" not in strip_tool_blocks(text, skip_fenced=True)


def test_a_malformed_mcp_fence_is_left_alone():
    """Not a call, so not executed and not stripped — the two decisions agree."""
    text = "```mcp__osrs__lookup_raid\nnot json\n```"
    assert parse_tool_blocks(text) == []
    assert "not json" in strip_tool_blocks(text)


# ── 6. a server that is not running says so ──────────────────────────────────

def test_a_registered_server_that_is_not_running_is_named_to_the_model():
    mgr = _mcp_manager(down=True)
    block = mgr.get_tool_descriptions_for_prompt({}, channel="both")
    assert "dead-wiki" in block
    assert "NOT answering" in block
    assert "Connection closed" in block
    assert "osrs-wiki" in block, "the servers that are up are still listed"


def test_a_down_server_is_named_even_when_it_is_the_only_one():
    mgr = McpManager()
    mgr._connections["dead"] = {"name": "dead-wiki", "status": "error",
                                "error": "Connection closed"}
    mgr._tools["dead"] = []
    block = mgr.get_tool_descriptions_for_prompt({}, channel="both")
    assert "dead-wiki" in block and "NOT answering" in block


def test_the_prompt_block_names_the_channel_this_turn_accepts():
    mgr = _mcp_manager()
    assert "native function calling" in mgr.get_tool_descriptions_for_prompt({}, channel="native")
    fenced = mgr.get_tool_descriptions_for_prompt({}, channel="fenced")
    assert "fenced code block" in fenced and "native function calling" not in fenced
    both = mgr.get_tool_descriptions_for_prompt({}, channel="both")
    assert "either" in both


def test_a_call_to_a_server_that_is_gone_names_the_server():
    """It said `MCP server not connected: 47a5fba5` — an id this module mints
    (`B870`) that appears on no surface a person reads."""
    mgr = _mcp_manager(down=True)
    result = asyncio.run(mgr.call_tool("mcp__dead__anything", {}))
    assert result["exit_code"] == 1
    assert "dead-wiki" in result["error"]
    assert "Connection closed" in result["error"]
    assert "dead" not in result["error"].replace("dead-wiki", "")   # not the bare id


# ── 7. the owner's turn, end to end ──────────────────────────────────────────

@pytest.mark.parametrize("emitted", [
    "```mcp__osrs__lookup_raid\n{\"name\": \"Fractured Archive\"}\n```",
    "<tool_call>{\"name\": \"mcp__osrs__lookup_raid\", "
    "\"arguments\": {\"name\": \"Fractured Archive\"}}</tool_call>",
    "{\"name\": \"mcp__osrs__lookup_raid\", "
    "\"arguments\": {\"name\": \"Fractured Archive\"}}",
])
def test_the_owners_turn_reaches_the_mcp_tool_and_answers(monkeypatch, emitted):
    """The owner's situation, end to end: a local OpenAI-compatible model on
    Auto, an MCP server registered, a question that needs its tool. The schema
    reaches the model; the call the model writes — in each shape a local server
    emits it — is parsed and dispatched with the right arguments; the tool's
    answer is in the stream the person reads.

    Measured before the change, with the live harness on port 8772: the request
    carried no MCP schema at all for this model, and two of these three shapes
    produced no `tool_output` event of any kind.
    """
    dispatched = []
    mgr = _mcp_manager()
    # The one seam, and the reason: wrapping the MCP tool list in
    # `untrusted_context_message` arms the post-external approval gate
    # (`messages_contain_external_untrusted_context` returns True for that block
    # alone, measured), so in the product the FIRST tool call of any turn with
    # an MCP server registered waits for the person's click. That gate is
    # `FORBIDDEN.md` Part 2 and is not stood down; this test is about whether
    # the call is parsed and dispatched at all, so the block is empty here and
    # `test_a_parsed_call_reaches_the_approval_gate_not_the_floor` below covers
    # the gated shape with the block in place.
    mgr.get_tool_descriptions_for_prompt = lambda *a, **k: ""
    _base(monkeypatch, mgr)
    events, sent = _drive(
        monkeypatch,
        [emitted, "The Archivist and the Index Warden."],
        message="Look up the Fractured Archive raid with the osrs-wiki tools.",
        relevant_tools={"web_search", "ask_user"},
        dispatched=dispatched,
        tool_output=json.dumps({"bosses": ["The Archivist", "Index Warden"]}),
    )
    assert "mcp__osrs__lookup_raid" in sent[0]["tools"], "the schema never reached the model"
    assert [b.tool_type for b in dispatched] == ["mcp__osrs__lookup_raid"], (
        "the call was dropped on the floor")
    assert json.loads(dispatched[0].content) == {"name": "Fractured Archive"}
    outputs = [e for e in events if e.get("type") == "tool_output"]
    assert outputs, "the tool ran and the stream said nothing about it"
    assert any("Archivist" in str(e.get("output")) for e in outputs), (
        "the tool's answer did not reach the turn")
    # And the model's next round sees the result, so it can answer from it.
    assert "Archivist" in sent[1]["prompt"]


def test_a_parsed_call_reaches_the_approval_gate_not_the_floor(monkeypatch):
    """The product's real shape with an MCP server registered: the MCP tool
    list is wrapped as external untrusted context, which arms the post-external
    gate (`FORBIDDEN.md` Part 2), so the call waits for the person. What this
    pins is that it waits **as that tool, with those arguments** — before this
    row a fenced MCP call reached nothing at all, so there was no card either.
    """
    _base(monkeypatch, _mcp_manager())
    events, _sent = _drive(
        monkeypatch,
        ["```mcp__osrs__lookup_raid\n" + json.dumps(MCP_CALL) + "\n```", "Done."],
        message="Look up the Fractured Archive raid with the osrs-wiki tools.",
        relevant_tools={"web_search", "ask_user"},
    )
    held = [e for e in events if e.get("type") == "tool_output"
            and e.get("tool") == "mcp__osrs__lookup_raid"]
    assert held, "the fenced MCP call reached neither the tool nor the gate"
    assert json.loads(held[0]["command"]) == MCP_CALL
    cards = [e for e in events if e.get("type") == "ask_user"
             and (e.get("data") or {}).get("kind") == "tool_approval"]
    assert cards, "a held call with no card is a turn that stops in silence"
    assert "mcp__osrs__lookup_raid" in str(cards[0]["data"].get("description") or "")
