# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2098` — the agent cannot publish a skill it wrote.

A published skill is the person's own context in every later turn
(`D-2026-10-09-01` §1). Before this, `manage_skills add` created a skill
`published` whenever `auto_approve_skills` was on and took `status` from its own
arguments; `manage_skills publish` flipped any draft; an `edit` or `patch` whose
frontmatter said `status: published` published it; and the generic `app_api`
loopback reached `PUT /api/skills/{id}` and `POST /api/skills/add` as the owner.

The owner's ruling: custom-built skills — the agent's included — are drafts
until a person publishes them after a dry run or a review. Each door is driven
here: the tool through `do_manage_skills`, the routes through an ASGI client
carrying the internal-tool header the loopback carries.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.prefs_routes as prefs_routes
import routes.skills_routes as SR
import src.constants as constants
from core.middleware import INTERNAL_TOOL_HEADER
from services.memory.skills import SkillsManager
from src.tools.system import do_manage_skills

OWNER = "ada"

SKILL = {
    "name": "purge-old-builds",
    "description": "Delete build artifacts older than a week",
    "when_to_use": "When the build disk is nearly full",
    "procedure": ["List the build folders", "Delete the ones older than seven days"],
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """The store `do_manage_skills` opens (`SkillsManager(DATA_DIR)`), with
    auto-publish on — the default the old `add` published under."""
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr("services.memory.skills._default_library_root", lambda: "")
    monkeypatch.setattr("services.memory.skills._first_party_library_root", lambda: "")
    monkeypatch.setattr(prefs_routes, "_load_for_user", lambda owner: {"auto_approve_skills": True})
    return SkillsManager(str(tmp_path))


def _tool(**args):
    return asyncio.run(do_manage_skills(json.dumps(args), owner=OWNER))


def _skill(store, name="purge-old-builds"):
    return next(s for s in store.load(owner=OWNER) if s["name"] == name)


def _shown(store):
    return {s["name"] for s in store.injectable_skills(owner=OWNER)}


# ── the tool ─────────────────────────────────────────────────────────────────

def test_what_the_agent_adds_is_a_draft_with_auto_publish_on(store):
    out = _tool(action="add", **SKILL)
    assert "Created skill" in out.get("results", ""), out
    assert _skill(store)["status"] == "draft"
    assert "purge-old-builds" not in _shown(store)


def test_asking_for_published_still_saves_a_draft_and_says_so(store):
    out = _tool(action="add", status="published", **SKILL)
    assert _skill(store)["status"] == "draft"
    assert "DRAFT, not published" in out["results"], out


def test_the_publish_action_publishes_nothing(store):
    _tool(action="add", **SKILL)
    out = _tool(action="publish", name="purge-old-builds", confidence=1.0)
    assert out.get("exit_code") == 1, out
    assert "person" in out["error"] and "Skills window" in out["error"]
    after = _skill(store)
    assert after["status"] == "draft"
    assert float(after["confidence"]) != 1.0
    assert "purge-old-builds" not in _shown(store)


def test_an_edit_whose_frontmatter_says_published_keeps_the_draft(store):
    _tool(action="add", **SKILL)
    md = store.read_skill_md("purge-old-builds", owner=OWNER)
    rewritten = md.replace("status: draft", "status: published").replace(
        "source: learned", "source: teacher-escalation")
    assert "status: published" in rewritten
    out = _tool(action="edit", name="purge-old-builds", content=rewritten)
    assert "Edited skill" in out.get("results", ""), out
    after = _skill(store)
    assert after["status"] == "draft" and after["source"] == "learned"
    assert "purge-old-builds" not in _shown(store)


def test_a_patch_to_the_status_line_keeps_the_draft(store):
    _tool(action="add", **SKILL)
    out = _tool(action="patch", name="purge-old-builds",
                old_string="status: draft", new_string="status: published")
    assert "Patched skill" in out.get("results", ""), out
    assert _skill(store)["status"] == "draft"


def test_restoring_an_earlier_published_copy_is_not_a_publish(store):
    """A person published it once and then sent it back; the agent putting the
    published copy back leaves it where the person left it."""
    _tool(action="add", **SKILL)
    store.update_skill("purge-old-builds", {"status": "published"}, owner=OWNER)
    store.update_skill("purge-old-builds", {"description": "Delete old build folders"}, owner=OWNER)
    store.update_skill("purge-old-builds", {"status": "draft"}, owner=OWNER)
    versions = store.list_versions("purge-old-builds", owner=OWNER)
    published_copy = next(v for v in versions
                          if "status: published" in (store.read_version(
                              "purge-old-builds", v["id"], owner=OWNER) or ""))
    out = _tool(action="restore", name="purge-old-builds", version_id=published_copy["id"])
    assert "Restored" in out.get("results", ""), out
    assert _skill(store)["status"] == "draft"


# ── the loopback ─────────────────────────────────────────────────────────────

def _client(sm, *, agent):
    app = FastAPI()

    @app.middleware("http")
    async def _owner(request: Request, call_next):
        request.state.current_user = OWNER
        return await call_next(request)

    app.include_router(SR.setup_skills_routes(sm))
    client = TestClient(app)
    if agent:
        client.headers[INTERNAL_TOOL_HEADER] = "loopback-token"
    return client


def test_the_loopback_cannot_publish_through_the_cards_route(store):
    _tool(action="add", **SKILL)
    res = _client(store, agent=True).put("/api/skills/purge-old-builds", json={"status": "published"})
    assert res.status_code == 403, res.text
    assert _skill(store)["status"] == "draft"
    # A person's press of *Publish* is the same request without the header.
    res = _client(store, agent=False).put("/api/skills/purge-old-builds", json={"status": "published"})
    assert res.status_code == 200 and _skill(store)["status"] == "published"


def test_the_loopback_cannot_add_a_published_skill(store):
    res = _client(store, agent=True).post("/api/skills/add", json={**SKILL, "status": "published"})
    assert res.status_code == 403, res.text
    assert not [s for s in store.load(owner=OWNER) if s["name"] == "purge-old-builds"]
    res = _client(store, agent=True).post("/api/skills/add", json=SKILL)
    assert res.status_code == 200 and _skill(store)["status"] == "draft"


def test_the_loopback_cannot_publish_through_a_markdown_save(store):
    _tool(action="add", **SKILL)
    md = store.read_skill_md("purge-old-builds", owner=OWNER)
    res = _client(store, agent=True).post(
        "/api/skills/purge-old-builds/markdown",
        json={"markdown": md.replace("status: draft", "status: published")})
    assert res.status_code == 403, res.text
    assert _skill(store)["status"] == "draft"
