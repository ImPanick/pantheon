# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pantheon ships a core skill set, and the vendored library can be found again.

The owner, 2026-10-31: *"pre-ship some critical skills with the platform. Idk
what happened but we lost all of the skills… Agents are here though."*

Nothing had been deleted. Measured on `3e3df5b`: the Workshop's list for a
signed-in person and the model's catalogue held Pantheon's first-party layer
and the person's own skills. The 286 vendored skills are out of both by ruling
(`D-2026-10-26-01` §8, and `B1421`'s 3 s bound for the card list), and the
first-party layer was the workstation's four, each gated on `computer` — so
with the workstation off the model was offered no skill at all, and the Brain
counted four.

Three things change, each asserted through the path that reads it:

* **A core set ships published** under `library/pantheon/skills/`
  (`category: core`), read-only and offered to every person whose turn may call
  the tools it drives. Like the workstation's four, it lives in the repo, so an
  update brings new versions and a person's own copy of the same name still
  wins for them — nothing is seeded into `data/`, so nothing is overwritten.
* **The vendored library is a shelf**: `GET /api/skills/library` lists it as
  light rows, and `POST /api/skills/library/{name}/add` copies one into the
  person's own skills, published, so their model is offered it.
* **First-run setup claims skills already on disk**: boot re-assigns unclaimed
  skill files to the admin, but boot ran before the account existed.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import services.memory.skills as skills_mod
import src.constants as constants
from routes.skills_routes import setup_skills_routes
from services.memory.skill_lint import MAX_DESCRIPTION, lint_skill, unknown_toolsets
from services.memory.skills import SkillsManager, invalidate_skill_cache

REPO = Path(__file__).resolve().parent.parent
FIRST_PARTY = REPO / "library" / "pantheon" / "skills"
CORE = {
    "clarify-the-goal": ["ask_user"],
    "web-research": ["web_search", "web_fetch"],
    "browse-a-website": ["agent_browser"],
    "debug-a-failure": ["bash", "read_file", "grep", "edit_file"],
    "change-code-safely": ["read_file", "edit_file", "bash"],
    "review-code-changes": ["bash", "read_file"],
    "analyze-data": ["python"],
    "write-a-document": ["create_document", "edit_document"],
    "summarize-for-a-reader": [],
    "remember-what-matters": ["manage_memory"],
    "schedule-recurring-work": ["manage_tasks"],
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fresh install: an empty data dir and the libraries that ship."""
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    invalidate_skill_cache()
    yield SkillsManager(str(tmp_path))
    invalidate_skill_cache()


def _core_rows(sm):
    return {s["name"]: s for s in sm.load_all()
            if s.get("library") == "pantheon" and s.get("category") == "core"}


# ── 1. what ships ───────────────────────────────────────────────────────────

def test_the_core_set_ships_published_and_read_only(store):
    rows = _core_rows(store)
    assert set(rows) == set(CORE)
    for name, needs in CORE.items():
        assert rows[name]["status"] == "published", name
        assert (rows[name].get("requires_toolsets") or []) == needs, name
        assert rows[name]["bundled"] and rows[name]["editable"] is False, name


def test_every_tool_a_core_skill_needs_is_a_tool_pantheon_has():
    """A misspelt `requires_toolsets` hides a skill from every turn, silently."""
    for name, needs in CORE.items():
        assert unknown_toolsets(needs) == [], name


def test_a_core_skill_names_no_tool_it_does_not_require():
    """A body is pasted only where its `requires_toolsets` are allowed, so a
    tool it names beyond them can reach a turn that withholds that tool
    (`tests/test_the_tools_a_local_model_is_offered_reach_it.py`)."""
    import re
    from src.tool_policy import selectable_tool_names
    known = set(selectable_tool_names())
    for name, needs in CORE.items():
        body = (FIRST_PARTY / name / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[2]
        named = {t for t in known if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", body)
                 and "_" in t}
        assert named <= set(needs), (name, named - set(needs))


def test_each_core_skill_lints_clean_of_errors_and_fits_the_description_limit(store):
    rows = list(_core_rows(store).values())
    for s in rows:
        assert len(s["description"]) <= MAX_DESCRIPTION, s["name"]
        report = lint_skill(s, rows)
        errors = [i for i in (report.get("issues") or [])
                  if (i.get("level") or i.get("severity")) == "error"]
        assert errors == [], (s["name"], errors)


@pytest.mark.parametrize("owner", [None, "alice"])
def test_every_person_is_offered_the_core_set_when_its_tools_are_on(store, owner):
    tools = sorted({t for needs in CORE.values() for t in needs})
    got = {s["name"] for s in store.injectable_skills(owner=owner, active_toolsets=tools)}
    assert set(CORE) <= got


def test_a_core_skill_is_withheld_when_a_tool_it_drives_is_off(store):
    tools = sorted({t for needs in CORE.values() for t in needs} - {"web_fetch"})
    got = {s["name"] for s in store.injectable_skills(owner="alice", active_toolsets=tools)}
    assert "web-research" not in got
    assert "summarize-for-a-reader" in got, "needs no tool, so is always offered"


def test_a_persons_own_copy_wins_for_them_and_the_update_never_touches_it(store):
    d = Path(store.skills_root) / "core" / "web-research"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: web-research\ndescription: my own way\nstatus: published\nowner: alice\n---\n"
        "## Procedure\n1. my own way\n", encoding="utf-8")
    invalidate_skill_cache()
    mine = [s for s in store.load_visible(owner="alice") if s["name"] == "web-research"]
    assert [s["description"] for s in mine] == ["my own way"]
    theirs = [s for s in store.load_visible(owner="bob") if s["name"] == "web-research"]
    assert theirs and theirs[0]["bundled"] is True


# ── 2. the vendored library is a shelf ──────────────────────────────────────

def test_the_shelf_lists_the_vendored_library_and_not_the_first_party_layer(store):
    rows = store.library_catalogue(owner="alice")
    names = {r["name"] for r in rows}
    assert len(rows) >= 250
    assert not (names & set(CORE))
    assert all(set(r) == {"name", "description", "category", "tags", "added"} for r in rows)


def test_adding_from_the_shelf_makes_a_published_copy_the_model_is_offered(store):
    name = store.library_catalogue(owner="alice")[0]["name"]
    assert name not in {s["name"] for s in store.injectable_skills(owner="alice")}
    entry = store.adopt_library_skill(name, owner="alice")
    assert entry["name"] == name and entry["status"] == "published"
    invalidate_skill_cache()
    own = {s["name"]: s for s in store.load(owner="alice")}
    assert name in own and not own[name].get("bundled")
    assert name in {s["name"] for s in store.injectable_skills(owner="alice")}
    assert name not in {s["name"] for s in store.injectable_skills(owner="bob")}
    assert {r["name"]: r["added"] for r in store.library_catalogue(owner="alice")}[name] is True
    # A second add is the same copy, not another one.
    assert store.adopt_library_skill(name, owner="alice")["name"] == name
    assert [s["name"] for s in store.load(owner="alice")] == [name]


def test_a_second_person_adding_the_same_skill_never_overwrites_the_first(store):
    name = store.library_catalogue()[0]["name"]
    store.adopt_library_skill(name, owner="alice")
    other = store.adopt_library_skill(name, owner="bob")
    assert other["name"] == f"{name}-2"
    invalidate_skill_cache()
    assert [s["name"] for s in store.load(owner="alice")] == [name]


def test_the_routes(store):
    app = FastAPI()

    @app.middleware("http")
    async def _person(request: Request, call_next):
        request.state.current_user = "alice"
        return await call_next(request)

    app.include_router(setup_skills_routes(store))
    c = TestClient(app)
    listed = c.get("/api/skills/library").json()
    assert listed["count"] == len(listed["skills"]) >= 250
    name = listed["skills"][0]["name"]
    r = c.post(f"/api/skills/library/{name}/add")
    assert r.status_code == 200 and r.json()["skill"]["status"] == "published"
    assert name in {s["name"] for s in c.get("/api/skills").json()["skills"]}
    assert c.post("/api/skills/library/no-such-skill/add").status_code == 404
    # The core set is in the Workshop's own list, as cards.
    assert set(CORE) <= {s["name"] for s in c.get("/api/skills").json()["skills"]}


# ── 3. setup claims what is already on disk ─────────────────────────────────

def test_first_run_setup_claims_skills_left_by_the_old_account(tmp_path, monkeypatch):
    import routes.auth_routes as auth_routes
    from core.auth import AuthManager

    skills_dir = tmp_path / "skills"
    d = skills_dir / "general" / "my-old-skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: my-old-skill\ndescription: made before the reinstall\nstatus: published\n"
        "owner: admin\n---\n## Procedure\n1. it\n", encoding="utf-8")
    monkeypatch.setattr(auth_routes, "SKILLS_DIR", str(skills_dir))
    monkeypatch.setattr(skills_mod, "_first_party_library_root", lambda: "")
    monkeypatch.setenv("PANTHEON_SKILL_LIBRARY", "")
    auth = AuthManager(str(tmp_path / "auth.json"))
    app = FastAPI()
    app.include_router(auth_routes.setup_auth_routes(auth))
    r = TestClient(app).post("/api/auth/setup", json={"username": "panick",
                                                      "password": "a-long-enough-password-1"})
    assert r.status_code == 200, r.text
    invalidate_skill_cache()
    assert [s["name"] for s in SkillsManager(str(tmp_path)).load(owner="panick")] == ["my-old-skill"]


# ── 4. the core set arrives as a matched procedure, not a catalogue line ────

def test_the_core_set_is_not_catalogued_and_does_not_offer_the_skills_tool(store):
    """`B1426`, eleven times over: a catalogue line per core skill, and
    `manage_skills`' schema, in every turn — a note or a greeting included."""
    from src import agent_loop
    listed = {s["name"] for s in store.index_for(owner="alice", active_toolsets=None)}
    assert not (listed & set(CORE))
    counted = {s["name"] for s in agent_loop._skills_for_turn(store, "alice", {"computer"})}
    assert not (counted & set(CORE))


def test_a_turn_about_a_core_skill_is_handed_its_procedure(store):
    tools = sorted({t for needs in CORE.values() for t in needs})
    got = store.get_relevant_skills(
        "debug this failing test, the traceback shows an exception",
        skills=store.injectable_skills(owner="alice", active_toolsets=tools),
        threshold=0.25, max_items=3, min_confidence=0.85)
    assert "debug-a-failure" in {s["name"] for s in got}
