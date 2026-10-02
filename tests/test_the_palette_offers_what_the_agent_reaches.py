# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-13` … `P22-18` — the palette offers a person only what their agent reaches.

`workflow_effects.build_palette(owner)` is `GET /api/workflows/palette`'s body
(contract C-W; the route is wf-walker's). `D-2026-10-01-05`'s minor call: a
kind the person may not use is listed greyed with the sentence that says why —
HTTP and MCP for anyone who is not an admin, Code with the workstation's own
sentence. Every setting's mapping comes from `workflow_slots` (the one place
that decides, `Law 7`); an MCP tool's arguments are classified from its schema.
An Integration's key and base URL never appear in it (`P22-13`'s Verify:
"never seeing the key").

`workflow_resources(owner)` is the same facts in `WorkflowResources`' shape,
for `validate_document` at save and at run.

Driven for real where the facts live on this branch — the integration store
(seam: `load_integrations`), a real `McpManager` and SQLite for the disabled
list, a real `SkillsManager`, the real workstation settings and auth. C-R and
wf-walker's limit readers are the real ones (`workflow_runs`; `integrate-d` removed the stand-ins).
"""
import json
from typing import Any, Dict

import pytest

from src import integrations as integrations_mod
from src import workflow_effects as fx
from src.workstation_access import NOT_PERMITTED_SENTENCE, OFF_SENTENCE

KEY = "sekret-api-key-123"
BASE = "http://feeds.lan:8080"


@pytest.fixture
def world(monkeypatch, tmp_path):
    """One admin's world: two Integrations (one off), a chat MCP server with a
    switched-off tool, a skill, and the workstation switched on."""
    import src.settings as S
    from core.database import Base, McpServer
    from services.memory.skills import SkillsManager, invalidate_skill_cache
    from src.mcp_manager import McpManager
    from tests.helpers.sqlite_db import make_temp_sqlite

    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setattr(integrations_mod, "load_integrations", lambda: [
        {"id": "intg-1", "name": "Miniflux", "enabled": True, "base_url": BASE, "auth_type": "header",
         "api_key": KEY, "preset": "miniflux", "description": "My feeds"},
        {"id": "intg-2", "name": "Gitea", "enabled": False, "base_url": "http://git.lan",
         "api_key": "other-key", "preset": "gitea", "description": ""},
    ])

    SessionLocal, engine, _tmp = make_temp_sqlite(Base.metadata)
    monkeypatch.setattr("core.database.SessionLocal", SessionLocal)
    db = SessionLocal()
    db.add(McpServer(id="chat", name="Chat", transport="stdio", command="chat-mcp",
                     disabled_tools=json.dumps(["delete_channel"])))
    db.commit()
    db.close()
    mgr = McpManager()
    mgr._connections["chat"] = {"name": "Chat", "status": "connected"}
    mgr._tools["chat"] = [
        {"name": "send_message", "description": "Post to a channel",
         "annotations": {"readOnlyHint": False},
         "input_schema": {"type": "object", "properties": {
             "channel": {"type": "string"}, "text": {"type": "string"},
             "link": {"type": "string", "format": "uri"}, "blocks": {"type": "array"}}}},
        {"name": "delete_channel", "description": "Delete", "input_schema": {}},
    ]
    monkeypatch.setattr("src.tool_execution.get_mcp_manager", lambda: mgr)

    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    invalidate_skill_cache()
    sm = SkillsManager(str(tmp_path))
    sm.add_skill(name="print-queue", description="Clear the print queue", procedure=["x"],
                 status="published")
    sm.add_skill(name="bobs-skill", description="not hers", procedure=["x"], owner="bob",
                 status="published")

    values: Dict[str, Any] = {"workstation_enabled": True, "workstation_url": "http://127.0.0.1:9",
                              "workstation_token": "t"}
    real = S.get_setting
    monkeypatch.setattr(S, "get_setting",
                        lambda key, default=None: values[key] if key in values else real(key, default))
    yield type("World", (), {"settings": values, "mgr": mgr})
    engine.dispose()
    invalidate_skill_cache()


def _kinds(palette):
    return {k["kind"]: k for k in palette["kinds"]}


def test_every_kind_is_listed_once_with_its_words_and_ports(world):
    from src.workflow_document import NODE_KINDS
    palette = fx.build_palette(None)
    kinds = _kinds(palette)
    assert [k["kind"] for k in palette["kinds"]] == list(NODE_KINDS)
    assert (kinds["llm"]["word"], kinds["llm"]["hint"]) == (
        "Prompt", "Ask a model to read, write or decide something.")
    assert kinds["if"]["ports"] == ["then", "otherwise"]
    assert kinds["http"]["ports"] == ["success", "error"]
    assert kinds["set"]["ports"] == ["success"]
    assert all(k["word"] and k["hint"] and k["group"] for k in palette["kinds"])


def test_an_integrations_key_and_address_never_reach_the_palette(world):
    palette = fx.build_palette(None)
    text = json.dumps(palette)
    assert KEY not in text and "other-key" not in text
    assert BASE not in text and "feeds.lan" not in text
    assert palette["integrations"] == [
        {"id": "intg-1", "name": "Miniflux", "preset": "miniflux", "description": "My feeds"}]
    assert _kinds(palette)["http"]["available"] is True


def test_with_no_integration_switched_on_http_is_greyed_and_says_where(world, monkeypatch):
    monkeypatch.setattr(integrations_mod, "load_integrations", lambda: [])
    http = _kinds(fx.build_palette(None))["http"]
    assert (http["available"], http["why"]) == (False, fx.NO_INTEGRATIONS_SENTENCE)


def test_an_mcp_tools_arguments_are_classified_from_its_schema(world):
    tools = {t["qualified_name"]: t for t in fx.build_palette(None)["mcp_tools"]}
    assert list(tools) == ["mcp__chat__send_message"]          # the switched-off one is not offered
    args = tools["mcp__chat__send_message"]["args"]
    assert args["text"]["mapping"] == "value"
    for name in ("channel", "link", "blocks"):
        assert args[name]["mapping"] == "never" and args[name]["why"], name
    tool = tools["mcp__chat__send_message"]
    assert tool["is_readonly"] is False and tool["readonly_source"] == "annotation"
    assert tool["server_name"] == "Chat" and tool["input_schema"]["properties"]["channel"]


def test_each_setting_says_whether_another_step_may_fill_it(world):
    from src import workflow_slots as ws
    kinds = _kinds(fx.build_palette(None))
    assert kinds["llm"]["slots"]["prompt"]["mapping"] == "value"
    assert kinds["llm"]["slots"]["model"] == {"mapping": "never", "why": ws.WHY_WHAT}
    assert kinds["http"]["slots"]["path"]["mapping"] == "never"
    assert kinds["http"]["slots"]["query[].value"] == {"mapping": "never", "why": ws.WHY_NOT_TEXT}
    assert kinds["action"]["slots"]["prompt"] == {"mapping": "never", "why": ws.WHY_WHAT}
    assert kinds["set"]["slots"]["fields[].value"]["mapping"] == "value"
    assert "args.*" not in kinds["mcp"]["slots"]                 # answered per tool
    assert "step.config" not in kinds["foreach"]["slots"]        # answered by the inner kind
    for kind in kinds.values():
        for slot in kind["slots"].values():
            assert slot["mapping"] in ("value", "never")
            assert slot["mapping"] == "value" or slot["why"]


def test_a_person_who_is_not_an_admin_is_offered_what_their_agent_reaches(world, monkeypatch):
    monkeypatch.setattr("src.tool_security.owner_is_admin_or_single_user", lambda owner: False)
    # With the workstation off nothing is lifted into it (`B985`), so the
    # non-admin blocklist is what this person's agent is refused.
    world.settings["workstation_enabled"] = False
    palette = fx.build_palette("bob")
    kinds = _kinds(palette)
    for kind in ("http", "mcp"):
        assert kinds[kind]["available"] is False and kinds[kind]["why"] == fx._ADMIN_ONLY_WHY[kind]
    assert palette["integrations"] == [] and palette["mcp_tools"] == []
    assert "bash" not in {t["name"] for t in palette["ai_tools"]}
    assert kinds["llm"]["available"] is True


def test_code_is_greyed_with_the_workstations_own_sentence(world, monkeypatch):
    assert _kinds(fx.build_palette(None))["code"]["available"] is True
    assert fx.build_palette(None)["workstation"] == {"available": True, "why": ""}

    world.settings["workstation_enabled"] = False
    palette = fx.build_palette(None)
    assert (_kinds(palette)["code"]["available"], _kinds(palette)["code"]["why"]) == (False, OFF_SENTENCE)
    assert palette["workstation"] == {"available": False, "why": OFF_SENTENCE}

    import core.auth
    import src.auth_helpers

    class _Auth:
        is_configured = True

        def is_admin(self, u):
            return False

        def get_privileges(self, u):
            return {"can_use_workstation": False}

    world.settings["workstation_enabled"] = True
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(src.auth_helpers, "_auth_disabled", lambda: False)
    monkeypatch.setattr(core.auth, "AuthManager", _Auth)
    assert _kinds(fx.build_palette("bob"))["code"]["why"] == NOT_PERMITTED_SENTENCE


def test_the_skills_offered_are_the_persons_own(world):
    palette = fx.build_palette(None)
    assert palette["skills"] == [{"name": "print-queue", "description": "Clear the print queue"}]
    assert _kinds(palette)["skill"]["available"] is True


def test_with_no_skill_the_skill_step_is_greyed(world):
    from services.memory.skills import SkillsManager
    import src.constants as constants
    SkillsManager(constants.DATA_DIR).delete_skill("print-queue")
    skill = _kinds(fx.build_palette(None))["skill"]
    assert (skill["available"], skill["why"]) == (False, fx.NO_SKILLS_SENTENCE)


def test_the_limits_and_the_operators_are_the_walkers_and_the_rules(world):
    from src import workflow_runs
    from src.workflow_logic import OPERATORS, OPERATOR_WORDS
    palette = fx.build_palette(None)
    assert palette["limits"] == {"foreach_max_items": workflow_runs.foreach_max_items(None),
                                 "wait_max_hours": workflow_runs.wait_max_hours(),
                                 "parallel_steps": workflow_runs.WORKFLOW_PARALLEL_STEPS}
    assert palette["operators"] == [{"op": op, "word": OPERATOR_WORDS[op]} for op in OPERATORS]


def test_the_resources_a_document_is_checked_against(world):
    from src.workflow_document import WorkflowResources
    res = fx.workflow_resources(None)
    assert isinstance(res, WorkflowResources)
    assert set(res.integrations) == {"intg-1", "intg-2"}
    assert res.integrations["intg-2"]["enabled"] is False
    assert KEY not in json.dumps(res.integrations)
    assert set(res.mcp_tools) == {"mcp__chat__send_message"}
    assert res.mcp_tools["mcp__chat__send_message"]["input_schema"]["properties"]["text"]
    assert res.skills == frozenset({"print-queue"})
    assert {"web_search", "mcp__chat__send_message"} <= res.ai_tools
    assert res.workstation_why is None

    world.settings["workstation_enabled"] = False
    assert fx.workflow_resources(None).workstation_why == OFF_SENTENCE


def test_a_person_who_is_not_an_admin_reaches_no_integration_and_no_mcp_tool(world, monkeypatch):
    monkeypatch.setattr("src.tool_security.owner_is_admin_or_single_user", lambda owner: False)
    res = fx.workflow_resources("bob")
    assert res.integrations == {} and res.mcp_tools == {}
