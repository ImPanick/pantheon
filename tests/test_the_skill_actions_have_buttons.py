# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-23` — the skill actions only a terminal could reach, behind routes.

Draft from a description (`P8-14`), *Fix these with the model* (`P8-13`),
history and restore (`P8-11`) and download (`P8-16`) each existed only as a
`manage_skills` action; `draft_skill_from_description` had no caller at all
(design § 0.9). Each now has a route the Skills window calls, and every case
here hits the real route through `TestClient` on real skill files in a temp
folder (`Law 20`). The model is scripted at `src.llm_core.llm_call_async`, so
the real drafter and the real rewriter parse what it says.

The person is set the way the auth middleware sets one
(`request.state.current_user`), from a test header.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes.skills_routes import setup_skills_routes
from services.memory.skills import SkillsManager
from src.tools.system import do_manage_skills

DRAFT_REPLY = """Here is the skill.
```json
{"name": "clear-print-queue", "description": "Clear a jammed print queue and restart the spooler",
 "category": "ops", "when_to_use": "When the print queue jams",
 "procedure": ["Stop the spooler", "Delete the queued jobs", "Start the spooler"],
 "pitfalls": ["Jobs in flight are lost"], "verification": ["A test page prints"],
 "tags": ["printing", "spooler"]}
```"""

THIN = {"name": "rotate-logs", "description": "logs", "category": "general",
        "when_to_use": "sometimes", "procedure": ["rotate them"]}

IMPROVED = """---
name: rotate-logs
description: Rotate and prune nginx access logs when /var is full
category: ops
tags: [nginx, logrotate]
status: draft
confidence: 0.8
---

# Rotate logs

## When to Use
When /var/log has filled and nginx still holds the old handles.

## Procedure
1. Run logrotate -f /etc/logrotate.d/nginx
2. Confirm with lsof that nginx reopened

## Pitfalls
- Deleting the open file frees nothing until nginx reopens

## Verification
- df -h /var shows the space back
"""


def _app(sm: SkillsManager) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _person(request: Request, call_next):
        request.state.current_user = request.headers.get("x-user") or None
        return await call_next(request)

    app.include_router(setup_skills_routes(sm))
    return TestClient(app)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    sm = SkillsManager(str(tmp_path), library_root="")
    monkeypatch.setattr("routes.skills_routes._resolve_audit_models",
                        lambda owner=None: ("http://model.test", "scripted", {}, None))
    model = {"replies": [], "seen": []}

    async def _llm(url, model_id, messages, **kw):
        model["seen"].append({"url": url, "model": model_id, "messages": messages})
        return model["replies"].pop(0) if model["replies"] else ""

    monkeypatch.setattr("src.llm_core.llm_call_async", _llm)
    return {"sm": sm, "client": _app(sm), "model": model, "root": tmp_path}


def _skill_dirs(root: Path) -> list:
    return sorted(str(p.relative_to(root)) for p in root.rglob("SKILL.md"))


# ── draft from a description ────────────────────────────────────────────────

def test_a_sentence_comes_back_as_the_nine_fields_and_nothing_is_written(world):
    world["model"]["replies"].append(DRAFT_REPLY)
    before = _skill_dirs(world["root"])
    res = world["client"].post("/api/skills/draft", json={
        "description": "when the print queue jams I clear it and restart the spooler"})
    assert res.status_code == 200, res.text
    draft = res.json()["draft"]
    assert draft["name"] == "clear-print-queue"
    assert draft["procedure"] == ["Stop the spooler", "Delete the queued jobs", "Start the spooler"]
    assert draft["pitfalls"] == ["Jobs in flight are lost"]
    assert draft["verification"] == ["A test page prints"]
    assert set(draft) >= {"name", "description", "category", "when_to_use", "procedure",
                          "pitfalls", "verification", "tags"}
    assert res.json()["model"] == "scripted"
    # The person's words are the user turn; the system turn is our schema.
    messages = world["model"]["seen"][0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "print queue jams" in messages[1]["content"]
    assert "print queue" not in messages[0]["content"]
    assert _skill_dirs(world["root"]) == before, "drafting wrote a skill"


def test_a_draft_says_why_when_it_cannot(world, monkeypatch):
    client = world["client"]
    empty = client.post("/api/skills/draft", json={"description": "   "})
    assert empty.status_code == 400 and "one sentence" in empty.json()["detail"]
    long = client.post("/api/skills/draft", json={"description": "x" * 2001})
    assert long.status_code == 400 and "under 2,000" in long.json()["detail"]
    world["model"]["replies"].append("I would rather not.")
    garbage = client.post("/api/skills/draft", json={"description": "clear the print queue"})
    assert garbage.status_code == 422 and "Nothing was saved" in garbage.json()["detail"]

    def _none(owner=None):
        raise ValueError("No model configured")
    monkeypatch.setattr("routes.skills_routes._resolve_audit_models", _none)
    nomodel = client.post("/api/skills/draft", json={"description": "clear the print queue"})
    assert nomodel.status_code == 503 and "Write it by hand" in nomodel.json()["detail"]
    assert _skill_dirs(world["root"]) == []


# ── fix these with the model ────────────────────────────────────────────────

def test_improve_through_the_route_and_through_manage_skills_write_the_same_text(tmp_path, monkeypatch):
    """One body, two doors (`services/memory/skill_improve`): the same skill,
    the same scripted rewrite, byte-identical SKILL.md either way."""
    monkeypatch.setattr("routes.skills_routes._resolve_audit_models",
                        lambda owner=None: ("http://model.test", "scripted", {}, None))

    async def _llm(*a, **k):
        return IMPROVED
    monkeypatch.setattr("src.llm_core.llm_call_async", _llm)

    route_root, tool_root = tmp_path / "route", tmp_path / "tool"
    route_sm = SkillsManager(str(route_root), library_root="")
    tool_sm = SkillsManager(str(tool_root), library_root="")
    for sm in (route_sm, tool_sm):
        sm.add_skill(source="user", owner=None, status="draft", **THIN)

    res = _app(route_sm).post("/api/skills/rotate-logs/improve")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["outcome"] == "rewrote" and body["findings"] >= 2
    assert body["after"]["problem"] < body["before"]["problem"] or \
        body["after"]["advisory"] < body["before"]["advisory"]

    monkeypatch.setattr("services.memory.skills.SkillsManager",
                        lambda *a, **k: SkillsManager(str(tool_root), library_root=""))
    monkeypatch.setattr("src.constants.DATA_DIR", str(tool_root))
    said = await_tool(do_manage_skills(json.dumps({"action": "improve", "name": "rotate-logs"}), owner=None))
    assert said.get("results", "").startswith("Rewrote `rotate-logs`"), said

    def _text(sm):
        return sm.read_skill_md("rotate-logs", owner=None)
    assert _text(route_sm) == _text(tool_sm)
    assert "logrotate -f /etc/logrotate.d/nginx" in _text(route_sm)


def await_tool(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_improve_says_nothing_to_fix_and_no_model_in_its_own_words(world, monkeypatch):
    sm, client = world["sm"], world["client"]
    sm.add_skill(source="user", owner=None, status="draft", **THIN)

    def _none(owner=None):
        raise ValueError("No model configured")
    monkeypatch.setattr("routes.skills_routes._resolve_audit_models", _none)
    res = client.post("/api/skills/rotate-logs/improve")
    assert res.status_code == 503 and "Fix the findings by hand" in res.json()["detail"]

    monkeypatch.setattr("routes.skills_routes._resolve_audit_models",
                        lambda owner=None: ("http://model.test", "scripted", {}, None))
    before = sm.read_skill_md("rotate-logs", owner=None)
    world["model"]["replies"].append("   ")
    blank = client.post("/api/skills/rotate-logs/improve")
    assert blank.status_code == 422 and "Nothing was written" in blank.json()["detail"]
    assert sm.read_skill_md("rotate-logs", owner=None) == before
    assert client.post("/api/skills/no-such-skill/improve").status_code == 404


# ── history and restore ─────────────────────────────────────────────────────

def _edit(client, name, md):
    res = client.post(f"/api/skills/{name}/markdown", json={"markdown": md})
    assert res.status_code == 200, res.text


def test_history_lists_views_and_puts_an_earlier_copy_back(world):
    sm, client = world["sm"], world["client"]
    sm.add_skill(source="user", owner=None, status="draft", **THIN)
    original = sm.read_skill_md("rotate-logs", owner=None)
    _edit(client, "rotate-logs", IMPROVED)

    rows = client.get("/api/skills/rotate-logs/versions").json()["versions"]
    assert len(rows) == 1
    vid = rows[0]["id"]
    view = client.get(f"/api/skills/rotate-logs/versions/{vid}")
    assert view.status_code == 200 and view.json()["markdown"] == original

    put = client.post(f"/api/skills/rotate-logs/versions/{vid}/restore")
    assert put.status_code == 200, put.text
    assert put.json()["restored"] == vid
    live = sm.read_skill_md("rotate-logs", owner=None)
    assert "rotate them" in live and "logrotate -f" not in live
    assert put.json()["markdown"] == live
    # What it replaced was kept, so putting it back is undoable.
    again = client.get("/api/skills/rotate-logs/versions").json()["versions"]
    assert len(again) == 2


# A bare `..` segment is folded away by the client before any route sees it (a
# browser does the same), so the dot-dot shapes here are the encoded ones.
@pytest.mark.parametrize("bad", [
    ".%2E", "%2e%2e", "SKILL", "..%2F..%2FSKILL", "0001-x%2F..%2F..%2FSKILL",
    "0001-1.0.0%00", "....%2F%2F", "%2Fetc%2Fpasswd",
])
def test_a_version_id_that_is_a_path_is_not_found(world, bad):
    sm, client = world["sm"], world["client"]
    sm.add_skill(source="user", owner=None, status="draft", **THIN)
    live = sm.read_skill_md("rotate-logs", owner=None)
    assert client.get(f"/api/skills/rotate-logs/versions/{bad}").status_code == 404
    assert client.post(f"/api/skills/rotate-logs/versions/{bad}/restore").status_code in (404, 405)
    assert sm.read_skill_md("rotate-logs", owner=None) == live


# ── download ────────────────────────────────────────────────────────────────

def test_download_is_an_attachment_without_history_or_a_symlinked_file(world, tmp_path):
    sm, client = world["sm"], world["client"]
    sm.add_skill(source="user", owner=None, status="draft", **THIN)
    _edit(client, "rotate-logs", IMPROVED)      # makes a versions/ entry
    folder = Path(sm._find_skill_path("rotate-logs", None)).parent
    (folder / "notes.md").write_text("kept", encoding="utf-8")
    secret = tmp_path / "id_rsa"
    secret.write_text("-----BEGIN OPENSSH PRIVATE KEY-----", encoding="utf-8")
    os.symlink(secret, folder / "planted.md")

    res = client.get("/api/skills/rotate-logs/export")
    assert res.status_code == 200
    assert res.headers["content-disposition"] == 'attachment; filename="rotate-logs.json"'
    payload = res.json()
    assert payload["skill"] == "rotate-logs"
    assert set(payload["files"]) == {"SKILL.md", "notes.md"}
    assert "OPENSSH" not in res.text
    assert not any(k.startswith("versions/") for k in payload["files"])


def test_every_action_is_the_owners_alone(world):
    sm, client = world["sm"], world["client"]
    sm.add_skill(source="user", owner="alice", status="draft", **THIN)
    bob = {"x-user": "bob"}
    for method, path in (("post", "/api/skills/rotate-logs/improve"),
                         ("get", "/api/skills/rotate-logs/versions/0001-1.0.0"),
                         ("post", "/api/skills/rotate-logs/versions/0001-1.0.0/restore"),
                         ("get", "/api/skills/rotate-logs/export")):
        assert getattr(client, method)(path, headers=bob).status_code == 404, path
    assert client.get("/api/skills/rotate-logs/export", headers={"x-user": "alice"}).status_code == 200
