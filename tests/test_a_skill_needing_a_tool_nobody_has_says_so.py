# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1490` — a skill whose `requires_toolsets` names a tool no register knows
says so, instead of being dropped in silence.

The row (the remainder of `B1381`): `skill_toolset_blocker(["no_such_tool"]) ==
["no_such_tool"]`, and `SkillsManager.add_skill` accepted it, so the skill was
saved, listed, never indexed, and nothing logged or flagged why. Measured on
`ffaf6671`: the lint said nothing about the field, `POST /api/skills/add`
answered `ok` with no word about it, `manage_skills action=add` said *Created*,
and the Skills preview listed neither the skill nor a reason.

Now one register answers "is this a tool" — `selectable_tool_names()`, the one
the gate itself reads (`skill_lint.unknown_toolsets`) — and every save path
names the entry: the lint (the Add form draws it before and after the save, and
the card editor through the same panel), the add route's answer, the tool
channel's result, and the preview's list of skills that are not shown.

`Verify:` saving such a skill names the unknown entry, or the Skills window
marks it.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import src.agent_loop as agent_loop
from routes.skills_routes import setup_skills_routes
from services.memory.skill_lint import lint_skill, unknown_toolsets
from services.memory.skills import SkillsManager
from tests.helpers import tool_suite_probe as probe

OWNER = "alice"
DRAFT = {"name": "sweep-files", "description": "sweep the files",
         "when_to_use": "when the disk is full", "procedure": ["list them", "remove them"],
         "requires_toolsets": ["no_such_tool", "read_file"]}


def _client(sm, monkeypatch):
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    app = FastAPI()

    @app.middleware("http")
    async def _person(request: Request, call_next):
        request.state.current_user = OWNER
        return await call_next(request)

    app.include_router(setup_skills_routes(sm))
    return TestClient(app)


def test_the_register_that_calls_it_unknown_is_the_gates_own():
    """The harness's own blocker and the new helper agree: one fact."""
    assert probe.skill_toolset_blocker(["no_such_tool"]) == ["no_such_tool"]
    assert unknown_toolsets(["no_such_tool", "read_file", "ls"]) == ["no_such_tool"]


def test_the_lint_names_the_entry_and_the_spelling_it_meant():
    found = {f["code"]: f for f in lint_skill(DRAFT, [])["findings"]}
    assert "unknown-required-tool" in found, sorted(found)
    f = found["unknown-required-tool"]
    assert f["severity"] == "problem" and f["field"] == "requires_toolsets"
    # `read_file` is a real tool and is not reported; the entry that is, is.
    assert f["message"].startswith("Required tools names `no_such_tool`, which is not a tool"), \
        f["message"]
    assert "never shown" in f["message"]
    near = lint_skill(dict(DRAFT, requires_toolsets=["web-search"]), [])
    msg = next(x["message"] for x in near["findings"] if x["code"] == "unknown-required-tool")
    assert "did you mean `web_search`" in msg, msg
    clean = lint_skill(dict(DRAFT, requires_toolsets=["read_file"]), [])
    assert not [x for x in clean["findings"] if "tool" in x["code"]]


def test_saving_it_names_the_entry_in_the_answer_and_the_log(tmp_path, monkeypatch, caplog):
    sm = SkillsManager(str(tmp_path), library_root="")
    client = _client(sm, monkeypatch)
    with caplog.at_level(logging.INFO, logger="services.memory.skills"):
        r = client.post("/api/skills/add", json={**DRAFT, "status": "published"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unknown_toolsets"] == ["no_such_tool"]
    assert "`no_such_tool`" in body["warning"] and "Required tools" in body["warning"]
    assert any("no_such_tool" in rec.getMessage() for rec in caplog.records), \
        "nothing logged the skill that will never be shown"
    # The lint the Add form draws beside the save, through the route.
    lint = client.post("/api/skills/lint", json=DRAFT).json()
    assert "unknown-required-tool" in {f["code"] for f in lint["findings"]}


def test_the_preview_lists_it_with_why(tmp_path, monkeypatch):
    """The Skills window's half: the skill is not in the block, and the list of
    what is not shown names the entry."""
    sm = SkillsManager(str(tmp_path), library_root="")
    client = _client(sm, monkeypatch)
    client.post("/api/skills/add", json={**DRAFT, "status": "published"})
    idx = client.get("/api/skills/index").json()
    assert "sweep-files" not in {e["name"] for e in idx["index"]}
    row = next(r for r in idx["not_shown"] if r["name"] == "sweep-files")
    assert row["gate"] == "requires" and row["unknown"] == ["no_such_tool"]
    assert "`no_such_tool`" in row["why"] and "Fix the name" in row["why"]


def test_the_tool_channel_says_it_too(tmp_path, monkeypatch):
    """`manage_skills action=add` — the path a model takes, and the one most
    likely to invent a tool name."""
    import src.constants as constants
    from src.tools.system import do_manage_skills

    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr("services.memory.skills._default_library_root", lambda: "")
    monkeypatch.setattr("services.memory.skills._first_party_library_root", lambda: "")
    out = asyncio.run(do_manage_skills(
        json.dumps({"action": "add", **DRAFT, "source": "user", "status": "published"}),
        owner=OWNER))
    text = out.get("results") or ""
    assert "Created skill `sweep-files`" in text, out
    assert "`no_such_tool`" in text and "never shown" in text, text
