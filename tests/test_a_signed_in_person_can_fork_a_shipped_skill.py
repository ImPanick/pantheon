# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1421` — signed in, a shipped skill has a card, can be forked, and the copy
is what the model is shown.

`B1419` gave the model every shipped skill (`load_active`), but the Workshop
listed `load(owner)` and the fork route checked `load(owner)` — the person's own
store — so with sign-in on a person had no card for a shipped procedure and no
way to make their own copy, the one way to change one. With sign-in off both
worked, because `load(None)` holds everything.

Now the Workshop lists `load_visible` (the person's own skills and the shipped
ones, read-only), the card's source route reads a shipped entry, the fork route
accepts one, and a copy of a shipped skill replaces it in what that person's
model is shown (`SkillCollections.replace_with_copy` — off wins; deleting the
copy brings the shipped one back). Another person still gets the shipped one.

Driven through the real router, the real store and the real
`_build_system_prompt`, with a throwaway first-party library.
"""
from __future__ import annotations

import textwrap

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import src.agent_loop as agent_loop
import src.constants as constants
import services.memory.skills as skills_mod
from routes.skills_routes import setup_skills_routes
from services.memory.skills import SkillsManager, invalidate_skill_cache

SHIPPED = textwrap.dedent("""\
    ---
    name: workstation-shell
    description: How this install runs a command on the workstation shell
    category: workstation
    tags: [shell]
    status: published
    confidence: 0.95
    ---

    ## When to Use
    the person asks to run a command on the workstation shell

    ## Procedure
    1. use the shipped way of running a workstation shell command
    """)

QUESTION = "Run a command on the workstation shell for me, please."


@pytest.fixture()
def install(tmp_path, monkeypatch):
    first = tmp_path / "first-party"
    (first / "workstation-shell").mkdir(parents=True)
    (first / "workstation-shell" / "SKILL.md").write_text(SHIPPED, encoding="utf-8")
    monkeypatch.setattr(skills_mod, "_first_party_library_root", lambda: str(first))
    vendored = tmp_path / "vendored"
    (vendored / "laravel-patterns").mkdir(parents=True)
    (vendored / "laravel-patterns" / "SKILL.md").write_text(
        SHIPPED.replace("workstation-shell", "laravel-patterns"), encoding="utf-8")
    monkeypatch.setenv("PANTHEON_SKILL_LIBRARY", str(vendored))
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(constants, "DATA_DIR", str(data), raising=False)
    invalidate_skill_cache()
    sm = SkillsManager(str(data))
    yield sm
    invalidate_skill_cache()


def _client(sm, who: str) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _person(request: Request, call_next):
        request.state.current_user = who
        return await call_next(request)

    app.include_router(setup_skills_routes(sm))
    return TestClient(app)


def _skills_block(owner: str) -> str:
    agent_loop._cached_base_prompt = None
    agent_loop._cached_base_prompt_key = None
    messages, _ = agent_loop._build_system_prompt(
        [{"role": "user", "content": QUESTION}], "gemma-4-26b", None, None,
        disabled_tools=set(), relevant_tools={"ask_user", "update_plan", "manage_skills"},
        owner=owner, context_report={})
    return "\n".join(str(m.get("content") or "") for m in messages
                     if "Source: skills" in str(m.get("content") or ""))


def test_signed_in_the_shipped_skill_is_a_card_whose_source_opens(install):
    alice = _client(install, "alice")
    listed = {s["name"]: s for s in alice.get("/api/skills").json()["skills"]}
    assert "workstation-shell" in listed, "no card for the shipped skill"
    assert listed["workstation-shell"]["bundled"] is True
    assert listed["workstation-shell"]["editable"] is False
    md = alice.get("/api/skills/workstation-shell/markdown")
    assert md.status_code == 200 and "shipped way" in md.json()["markdown"]
    # Still read-only: every write path refuses it.
    assert alice.post("/api/skills/workstation-shell/markdown",
                      json={"markdown": SHIPPED}).status_code == 404
    assert alice.delete("/api/skills/workstation-shell").status_code == 404
    # The vendored library is not drawn as cards in a signed-in list, as it
    # never was (the Brain test measured what 286 of them cost), and is still
    # readable by name.
    assert "laravel-patterns" not in listed
    assert alice.get("/api/skills/laravel-patterns/markdown").status_code == 200


def test_fork_edit_and_the_copy_reaches_the_next_turn_instead(install, monkeypatch):
    """The row's `Verify:`, end to end."""
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    alice = _client(install, "alice")
    assert "`workstation-shell`" in _skills_block("alice"), "the premise: it ships to her turns"

    forked = alice.post("/api/skills/workstation-shell/fork", json={})
    assert forked.status_code == 200, forked.text
    copy = forked.json()["skill"]["name"]
    assert copy == "workstation-shell-fork"

    edited = SHIPPED.replace("name: workstation-shell", f"name: {copy}").replace(
        "use the shipped way", "use alice's own way")
    assert alice.post(f"/api/skills/{copy}/markdown", json={"markdown": edited}).status_code == 200

    block = _skills_block("alice")
    assert f"`{copy}`" in block
    assert "`workstation-shell`" not in block, "the shipped one still reaches her turn"
    assert "alice's own way" in block and "the shipped way" not in block
    # The card says why the shipped one is off.
    off = alice.get("/api/skills/collections").json()["off"]
    assert any("your copy" in w and copy in w for w in off.get("workstation-shell", []))

    # Another person on the install still has the shipped procedure.
    assert "`workstation-shell`" in _skills_block("bob")

    # And deleting the copy gives it back.
    assert alice.delete(f"/api/skills/{copy}").status_code == 200
    assert "`workstation-shell`" in _skills_block("alice")
