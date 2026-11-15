# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2135` — APIs and the vault are put in front of the model only when needed.

Owner ruling 2026-11-15: "add API's and Vault items - ensure they're only
called/used when needed". Measured on `fix/agent-lean-turn` before the fix:

- the integrations list (`get_integrations_prompt`: every enabled integration
  with its whole description) went into the prompt on every turn, also turns
  whose request carried no `api_call` and so could not call one;
- the MCP block named every registered MCP tool on every turn, also the ones the
  turn's tool set held back.

The vault already waited for a call: its tools (`connections`,
`shell_with_login`, `agent_browser` login) are offered only when the words ask
for them, nothing of the vault is in the prompt, and the gate's lookup opens
the vault only for a call that names a login. The last tests pin that.
"""
from __future__ import annotations

import json

import pytest

from src import agent_loop


class _Integrations:
    def __init__(self, monkeypatch):
        rows = [{"id": "miniflux-home", "name": "Miniflux", "enabled": True,
                 "description": "MARKINTEGQ7 Feed reader. GET /v1/entries lists entries."},
                {"id": "off-one", "name": "Paperless", "enabled": False, "description": "x"}]
        import src.integrations as I
        monkeypatch.setattr(I, "agent_integrations_for", lambda owner: rows)


def _prompt(relevant_tools, words="Suggest a name for my new cat.", mcp_mgr=None):
    msgs = [{"role": "system", "content": "You are Pantheon."}, {"role": "user", "content": words}]
    out, _ = agent_loop._build_system_prompt(msgs, "m", None, mcp_mgr, relevant_tools=relevant_tools,
                                             owner="tester")
    return "\n".join(str(m.get("content") or "") for m in out)


def test_the_integrations_list_goes_only_with_api_call(monkeypatch):
    _Integrations(monkeypatch)
    assert "MARKINTEGQ7" not in _prompt({"ask_user", "find_tools"})
    assert "MARKINTEGQ7" in _prompt({"ask_user", "find_tools", "api_call"})
    # The whole suite offers `api_call`.
    assert "MARKINTEGQ7" in _prompt(None)


def test_naming_an_integration_names_it(monkeypatch):
    _Integrations(monkeypatch)
    from src.integrations import integrations_named_in
    assert integrations_named_in("tester", "what's new on Miniflux today?") == ["miniflux-home"]
    assert integrations_named_in("tester", "check miniflux-home") == ["miniflux-home"]
    assert integrations_named_in("tester", "suggest a name for my cat") == []
    assert integrations_named_in("tester", "open paperless") == [], "a disabled one is not callable"


class _MCP:
    """Only what `_build_system_prompt` asks of a manager."""

    def get_all_openai_schemas(self, disabled_map=None):
        return []

    def is_builtin(self, server_id):
        return False

    def get_tool_descriptions_for_prompt(self, disabled_map=None, channel="native", only=None):
        tools = ["mcp__probe__echo", "mcp__probe__inventory"]
        names = tools if only is None else [t for t in tools if t in set(only)]
        return "\n".join(f"  - {n}: a tool" for n in names)


def test_the_mcp_block_names_the_tools_the_turn_offers():
    text = _prompt({"ask_user", "mcp__probe__echo"}, mcp_mgr=_MCP())
    assert "mcp__probe__echo" in text and "mcp__probe__inventory" not in text
    text = _prompt(None, mcp_mgr=_MCP())
    assert "mcp__probe__echo" in text and "mcp__probe__inventory" in text


def test_the_real_mcp_block_honours_only():
    from src.mcp_manager import McpManager
    mgr = McpManager.__new__(McpManager)
    tools = [
        {"server_id": "probe", "server_name": "probe", "qualified_name": "mcp__probe__echo",
         "description": "Echo.", "input_schema": {}},
        {"server_id": "probe", "server_name": "probe", "qualified_name": "mcp__probe__inventory",
         "description": "Inventory.", "input_schema": {}},
    ]
    mgr._tools = {t["qualified_name"]: t for t in tools}
    mgr._generation = 0
    mgr._cached_prompt_desc = None
    mgr._cached_prompt_desc_key = None
    mgr._connections = {}
    mgr.get_all_tools = lambda disabled_map=None, **k: tools
    mgr._servers_not_answering = lambda: []
    mgr.reaches_model_channels = lambda sid: True
    some = mgr.get_tool_descriptions_for_prompt({}, only={"mcp__probe__echo"})
    assert "mcp__probe__echo" in some and "mcp__probe__inventory" not in some
    every = mgr.get_tool_descriptions_for_prompt({})
    assert "mcp__probe__echo" in every and "mcp__probe__inventory" in every


@pytest.mark.parametrize("tool,content", [
    ("web_search", {"query": "x"}),
    ("agent_browser", {"action": "open", "url": "https://example.org"}),
    ("bash", {"command": "ls"}),
])
def test_the_vault_is_not_opened_for_a_call_that_names_no_login(monkeypatch, tool, content):
    import src.vault as V
    opened = []
    monkeypatch.setattr("core.database.SessionLocal", lambda: opened.append(1))
    assert V.asks_before("tester", "s", tool, json.dumps(content)) is None
    assert opened == []


def test_a_plain_turn_is_offered_no_vault_tool():
    suite = agent_loop.plan_turn_tool_suite(
        "Suggest a name for my new cat.", endpoint_url="http://127.0.0.1:1/v1", model="m")
    assert not {"connections", "shell_with_login", "agent_browser"} & set(suite.offered)
    asked = agent_loop.plan_turn_tool_suite(
        "Use my vault login to check the Grafana API.", endpoint_url="http://127.0.0.1:1/v1", model="m")
    assert {"connections", "shell_with_login"} <= set(asked.offered)
