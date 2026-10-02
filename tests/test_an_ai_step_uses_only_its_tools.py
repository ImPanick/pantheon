# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-16` — an AI step is offered its own tools and refused every other.

A workflow's AI step names its tools from a list (`tools: [...]`) instead of
retrieval over its prompt. `ToolPolicy(allowed_tools=…)` carries the list;
`ToolPolicy.blocks` refuses any name outside it — including a name nobody has
heard of yet — and `stream_agent_loop` advertises only what is on it, on both
channels (native function schemas and the fenced prompt), after every widening
the loop does. An empty list stays empty: today an empty `relevant_tools`
means "everything" to the schema filter, so this cannot ride on it.

Driven through the real loop with a scripted model (`Law 20`); the one seam
per test is the model stream (and, where a tool must run, `execute_tool_block`).
"""
import asyncio
import json

import pytest

import src.agent_loop as al
from src.agent_tools import ToolBlock
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block
from src.tool_policy import ToolPolicy

STEP_TOOLS = {"web_search", "web_fetch"}


def _base(monkeypatch, *, native=True):
    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(al, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(al, "_agent_route_tool_mode",
                        lambda url, model, owner=None, headers=None: (native, False, False))


def _drive(monkeypatch, rounds, *, policy, message="Find three pages about tide tables and email me",
           relevant_tools=None, executed=None, max_rounds=None, model="scripted"):
    """Run the real loop. `rounds` is what the model does each round: a list of
    native tool calls `[(name, args)]`, or text. Answers (events, per-round
    request) where a request is `{tools, system}`."""
    sent = []
    script = iter(rounds)

    async def scripted(candidates, messages, **kwargs):
        sent.append({
            "tools": sorted((t.get("function") or {}).get("name") for t in (kwargs.get("tools") or [])),
            "system": "\n".join(m.get("content") or "" for m in messages
                                if m.get("role") == "system" and isinstance(m.get("content"), str)),
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

    async def run_tool(block, *a, **k):
        if executed is not None:
            executed.append(block.tool_type)
        return block.tool_type, {"output": "ok", "exit_code": 0}

    monkeypatch.setattr(al, "stream_llm_with_fallback", scripted)
    monkeypatch.setattr(al, "execute_tool_block", run_tool)

    async def collect():
        return [c async for c in al.stream_agent_loop(
            "http://local.test/v1", model, [{"role": "user", "content": message}],
            max_rounds=max_rounds or len(rounds) + 1, owner="local",
            relevant_tools=relevant_tools, tool_policy=policy)]

    events = [json.loads(c[6:]) for c in asyncio.run(collect())
              if c.startswith("data: ") and not c.startswith("data: [DONE]")]
    return events, sent


# ── the policy ────────────────────────────────────────────────────────────────

def test_a_list_refuses_every_name_outside_it_and_says_so():
    policy = ToolPolicy(allowed_tools=["web_search", "web_fetch"])
    assert isinstance(policy.allowed_tools, frozenset)
    assert not policy.blocks("web_search") and not policy.blocks("web_fetch")
    for name in ("bash", "python", "mcp__chat__send_message", "a_tool_added_tomorrow"):
        assert policy.blocks(name)
        assert policy.reason_for(name) == f"“{name}” is not one of this step's tools."


def test_an_empty_list_refuses_everything_and_no_list_refuses_nothing_new():
    assert ToolPolicy(allowed_tools=[]).blocks("web_search")
    assert ToolPolicy(allowed_tools=[]).blocks("ask_user")
    assert not ToolPolicy().blocks("bash")                     # Law 1: every existing caller
    assert ToolPolicy().outside_allowed("bash") is False


def test_an_email_tool_is_on_the_list_in_either_spelling():
    policy = ToolPolicy(allowed_tools=["list_emails"])
    assert not policy.blocks("list_emails")
    assert not policy.blocks("mcp__email__list_emails")
    assert policy.blocks("mcp__email__send_email")


@pytest.mark.asyncio
async def test_the_dispatcher_refuses_a_name_outside_the_list():
    desc, result = await execute_tool_block(
        ToolBlock("bash", "echo should-not-run"), owner="local",
        tool_policy=ToolPolicy(allowed_tools=STEP_TOOLS),
        security_context=NO_TOOL_SECURITY_CONTEXT)
    assert desc == "bash: BLOCKED" and result["exit_code"] == 1


# ── the loop advertises only the list ─────────────────────────────────────────

def test_the_model_is_offered_exactly_the_steps_tools(monkeypatch):
    _base(monkeypatch)
    # The caller's set and the turn's email/web domains would each widen it.
    _events, sent = _drive(monkeypatch, ["Nothing to do."], relevant_tools={"bash", "list_emails"},
                           policy=ToolPolicy(allowed_tools=STEP_TOOLS))
    assert sent[0]["tools"] == sorted(STEP_TOOLS)


def test_without_a_list_the_turn_is_selected_as_before(monkeypatch):
    _base(monkeypatch)
    _events, sent = _drive(monkeypatch, ["Nothing to do."], relevant_tools={"bash"},
                           policy=ToolPolicy())
    assert "bash" in sent[0]["tools"]                          # Law 1


def test_an_empty_list_offers_nothing_on_either_channel(monkeypatch):
    _base(monkeypatch)
    _events, sent = _drive(monkeypatch, ["Nothing to do."], policy=ToolPolicy(allowed_tools=[]))
    assert sent[0]["tools"] == []

    _base(monkeypatch, native=False)                           # the fenced prompt
    _events, sent = _drive(monkeypatch, ["Nothing to do."], policy=ToolPolicy(allowed_tools=[]))
    for name in ("bash", "web_search", "web_fetch", "python", "read_file"):
        assert f"```{name}\n" not in sent[0]["system"], name
    _events, control = _drive(monkeypatch, ["Nothing to do."], relevant_tools={"bash", "web_search"},
                              policy=ToolPolicy())
    assert "```bash\n" in control[0]["system"]                 # the probe can see a section


def test_an_empty_list_keeps_even_the_loop_primitives_out(monkeypatch):
    """The fenced prompt force-includes `ask_user` and `update_plan` for any
    selection; a step whose list is empty is given neither."""
    _base(monkeypatch, native=False)
    _events, control = _drive(monkeypatch, ["Nothing to do."], relevant_tools={"web_search"},
                              policy=ToolPolicy())
    assert "```ask_user```" in control[0]["system"]           # the probe can see one
    _events, sent = _drive(monkeypatch, ["Nothing to do."], policy=ToolPolicy(allowed_tools=[]))
    assert "```ask_user" not in sent[0]["system"]
    assert "```update_plan" not in sent[0]["system"]


def test_no_retrieval_runs_over_a_steps_prompt(monkeypatch):
    """The author's list is the selection: neither the tool index nor the
    keyword fallback is asked, even when the list is empty (where an empty
    selection would otherwise read as "nothing chosen yet")."""
    import src.tool_index as tool_index
    asked = []
    monkeypatch.setattr(tool_index, "get_tool_index", lambda: asked.append("index"))
    real_select = tool_index.ToolIndex.select_without_embeddings
    monkeypatch.setattr(tool_index.ToolIndex, "select_without_embeddings",
                        staticmethod(lambda *a, **k: asked.append("keywords") or real_select(*a, **k)))
    _base(monkeypatch)
    for allowed in ([], ["web_search"]):
        _drive(monkeypatch, ["Nothing to do."], policy=ToolPolicy(allowed_tools=allowed))
    assert asked == []
    _drive(monkeypatch, ["Nothing to do."], policy=ToolPolicy())
    assert asked                                               # the probe sees a turn that asks


def test_the_list_holds_when_the_known_names_come_back_short(monkeypatch):
    """`B830`: in a process that imports `tool_policy` before the loop,
    `known_tool_names` once answered two names short. The schemas a model is
    sent are still only the step's own, and a name the short list does not
    know (so it never joined the denylist) is still refused by the policy."""
    _base(monkeypatch)
    monkeypatch.setattr("src.tool_policy.known_tool_names", lambda: {"web_search"})
    _events, sent = _drive(monkeypatch, ["Nothing to do."], policy=ToolPolicy(allowed_tools=[]))
    assert sent[0]["tools"] == []
    executed = []
    events, _sent = _drive(monkeypatch, [[("bash", {"command": "id"})]], executed=executed,
                           policy=ToolPolicy(allowed_tools=STEP_TOOLS))
    blocked = [e for e in events if e.get("type") == "tool_blocked"]
    assert blocked and blocked[0]["reason"] == "“bash” is not one of this step's tools."
    assert executed == []

    # The fenced prompt too: the turn's email and web words would widen the
    # selection with tools the short list does not know to deny.
    _base(monkeypatch, native=False)
    monkeypatch.setattr("src.tool_policy.known_tool_names", lambda: {"web_search"})
    widening = "search the web for my latest emails and read the newest email"
    _events, control = _drive(monkeypatch, ["Nothing to do."], message=widening,
                              relevant_tools={"web_search"}, policy=ToolPolicy())
    assert "```list_emails" in control[0]["system"]           # the turn does widen
    _events, sent = _drive(monkeypatch, ["Nothing to do."], message=widening,
                           policy=ToolPolicy(allowed_tools={"web_search"}))
    assert "```web_search\n" in sent[0]["system"]
    for name in ("list_emails", "read_email", "web_fetch"):
        assert f"```{name}" not in sent[0]["system"], name


def test_a_finetunes_own_tools_never_lift_the_list(monkeypatch):
    """A `pantheon-qwen3` notes turn lifts the notes managers out of the
    denylist and past the per-call policy (its clamp). A step's list is not
    lifted with them: the call is refused with the step's reason."""
    _base(monkeypatch, native=False)
    executed = []
    events, _sent = _drive(monkeypatch, ['```manage_notes\n{"action": "add", "content": "milk"}\n```'],
                           message="add a note: buy milk", model="pantheon-qwen3-notes",
                           policy=ToolPolicy(allowed_tools=STEP_TOOLS), executed=executed)
    blocked = [e for e in events if e.get("type") == "tool_blocked"]
    assert [b["tool"] for b in blocked] == ["manage_notes"]
    assert blocked[0]["reason"] == "“manage_notes” is not one of this step's tools."
    assert executed == []


def test_the_fenced_prompt_names_only_the_steps_tools(monkeypatch):
    _base(monkeypatch, native=False)
    _events, sent = _drive(monkeypatch, ["Nothing to do."], relevant_tools={"bash"},
                           policy=ToolPolicy(allowed_tools=STEP_TOOLS))
    assert "```web_search\n" in sent[0]["system"]
    assert "```bash\n" not in sent[0]["system"]


def test_a_tool_outside_the_list_is_refused_with_its_reason(monkeypatch):
    _base(monkeypatch)
    executed = []
    events, _sent = _drive(monkeypatch, [[("bash", {"command": "cat /etc/passwd"})],
                                         [("web_search", {"query": "tides"})]],
                           policy=ToolPolicy(allowed_tools=STEP_TOOLS), executed=executed)
    blocked = [e for e in events if e.get("type") == "tool_blocked"]
    assert [b["tool"] for b in blocked] == ["bash"]
    assert blocked[0]["reason"] == "“bash” is not one of this step's tools."
    assert executed == ["web_search"]


def test_a_skill_the_model_opens_does_not_widen_the_list(monkeypatch):
    import services.memory.skills as skills_mod

    class _Skills:
        def __init__(self, *a, **k):
            pass

        def load(self, owner=None):
            return [{"name": "dig", "requires_toolsets": ["bash", "web_fetch"]}]

        def load_active(self, owner=None):
            return []

    monkeypatch.setattr(skills_mod, "SkillsManager", _Skills)
    _base(monkeypatch)
    events, sent = _drive(monkeypatch,
                          [[("manage_skills", {"action": "view", "name": "dig"})], "Read it."],
                          policy=ToolPolicy(allowed_tools={"manage_skills", "web_search"}))
    assert sent[1]["tools"] == ["manage_skills", "web_search"]


def test_an_mcp_tool_on_the_list_is_offered_and_its_neighbour_is_not(monkeypatch):
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._connections["chat"] = {"name": "Chat", "status": "connected"}
    mgr._tools["chat"] = [
        {"name": "send_message", "description": "Post to a channel",
         "input_schema": {"type": "object", "properties": {"channel": {"type": "string"},
                                                           "text": {"type": "string"}}}},
        {"name": "delete_channel", "description": "Delete a channel",
         "input_schema": {"type": "object", "properties": {"channel": {"type": "string"}}}},
    ]
    _base(monkeypatch)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: mgr, raising=False)
    monkeypatch.setattr(al, "_load_mcp_disabled_map", lambda: {})
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           policy=ToolPolicy(allowed_tools={"mcp__chat__send_message", "web_search"}))
    assert sent[0]["tools"] == ["mcp__chat__send_message", "web_search"]

    # The fenced channel's MCP block, too: it lists what the server offers,
    # less what is switched off — and less what is not on the step's list.
    _base(monkeypatch, native=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: mgr, raising=False)
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           policy=ToolPolicy(allowed_tools={"mcp__chat__send_message"}))
    assert "mcp__chat__send_message" in sent[0]["prompt"]
    assert "mcp__chat__delete_channel" not in sent[0]["prompt"]


# ── which tools a person may pick from (`ai_tool_choices`) ────────────────────

@pytest.fixture
def chat_mcp(monkeypatch):
    """A real `McpManager` holding a chat server's two tools, one switched off
    in a real (temporary) database, as an operator switches one off."""
    from core.database import Base, McpServer
    from src.mcp_manager import McpManager
    from tests.helpers.sqlite_db import make_temp_sqlite

    SessionLocal, engine, tmp = make_temp_sqlite(Base.metadata)
    monkeypatch.setattr("core.database.SessionLocal", SessionLocal)
    db = SessionLocal()
    db.add(McpServer(id="chat", name="Chat", transport="stdio", command="chat-mcp",
                     disabled_tools=json.dumps(["delete_channel"])))
    db.commit()
    db.close()
    mgr = McpManager()
    mgr._connections["chat"] = {"name": "Chat", "status": "connected"}
    mgr._tools["chat"] = [{"name": "send_message", "description": "Post", "input_schema": {}},
                          {"name": "delete_channel", "description": "Delete", "input_schema": {}}]
    monkeypatch.setattr("src.tool_execution.get_mcp_manager", lambda: mgr)
    yield mgr
    engine.dispose()


def test_an_admin_picks_from_the_built_ins_and_the_switched_on_mcp_tools(monkeypatch, chat_mcp):
    from src.workflow_effects import ai_tool_choices
    monkeypatch.setenv("AUTH_ENABLED", "false")
    choices = {c["name"]: c for c in ai_tool_choices("local")}
    assert choices["web_search"] == {"name": "web_search", "label": "web search", "kind": "builtin"}
    assert "bash" in choices
    assert choices["mcp__chat__send_message"] == {
        "name": "mcp__chat__send_message", "label": "Chat · send_message", "kind": "mcp"}
    assert "mcp__chat__delete_channel" not in choices


def test_a_tool_switched_off_for_everyone_is_not_offered(monkeypatch, chat_mcp):
    import src.settings as settings
    from src.workflow_effects import ai_tool_choices
    monkeypatch.setenv("AUTH_ENABLED", "false")
    real = settings.get_setting
    monkeypatch.setattr(settings, "get_setting", lambda key, default=None: (
        ["web_fetch", "mcp__chat__send_message"] if key == "disabled_tools" else real(key, default)))
    names = {c["name"] for c in ai_tool_choices("local")}
    assert "web_fetch" not in names and "mcp__chat__send_message" not in names
    assert "web_search" in names


def test_a_person_who_is_not_an_admin_is_offered_what_their_agent_reaches(monkeypatch, chat_mcp):
    from src.tool_security import NON_ADMIN_BLOCKED_TOOLS
    from src.workflow_effects import ai_tool_choices
    monkeypatch.setattr("src.tool_security.owner_is_admin_or_single_user", lambda owner: False)
    names = {c["name"] for c in ai_tool_choices("bob")}
    assert "web_search" in names
    assert "bash" not in names and not (names & set(NON_ADMIN_BLOCKED_TOOLS))
    assert not any(n.startswith("mcp__") for n in names)
