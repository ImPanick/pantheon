# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1499` — a skill whose required tool is switched off is not offered as a
slash command.

The row (the remainder of `B580`): `GET /api/skills/slash-catalog` and the
invoke check (`skill_injection.invokable_skill`, read by
`POST /api/skills/{name}/invoke` and by the turn that carries a `/name`) called
`index_for(owner)` with no `active_toolsets`, which `injectable_skills` reads as
*"the caller does not know"* and so skips `requires_toolsets`. Measured on
`ffaf6671` with `image_gen_enabled` off (its default — `generate_image` is then
withheld from every turn): a skill declaring `requires_toolsets:
[generate_image]` was out of `GET /api/skills/index` and every prompt, and was
listed by the slash catalog and accepted by `/invoke`.

All three read `skill_injection.invokable_index` now, gated on
`agent_loop.skill_toolsets_for_owner` — what the preview gates on. The other
half of the parameter is the control: with the tool on, all three carry it.

`Verify:` its slash entry follows `skill_toolsets_for_owner`.
"""
from __future__ import annotations

import textwrap

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import src.agent_loop as agent_loop
from routes.skills_routes import setup_skills_routes
from services.memory.skill_injection import invoked_skill_messages
from services.memory.skills import SkillsManager

OWNER = "alice"
NAME = "make-a-poster"


@pytest.fixture
def store(tmp_path):
    d = tmp_path / "skills" / "design" / NAME
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {NAME}
        description: a poster from a sentence
        category: design
        requires_toolsets: [generate_image]
        status: published
        confidence: 0.9
        owner: {OWNER}
        ---

        ## When to Use
        someone wants a poster

        ## Procedure
        1. call generate_image
        """), encoding="utf-8")
    return SkillsManager(str(tmp_path), library_root="")


def _client(sm, monkeypatch, image_on):
    settings = {"image_gen_enabled": image_on}
    monkeypatch.setattr(agent_loop, "get_setting",
                        lambda k, d=None: settings.get(k, d), raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    app = FastAPI()

    @app.middleware("http")
    async def _person(request: Request, call_next):
        request.state.current_user = OWNER
        return await call_next(request)

    app.include_router(setup_skills_routes(sm))
    return TestClient(app)


@pytest.mark.parametrize("image_on", [False, True])
def test_the_slash_list_the_invoke_and_the_turn_follow_the_preview(store, monkeypatch, image_on):
    client = _client(store, monkeypatch, image_on)
    active = agent_loop.skill_toolsets_for_owner(OWNER)
    assert ("generate_image" in active) is image_on, "the setting did not reach the gate"

    previewed = {e["name"] for e in client.get("/api/skills/index").json()["index"]}
    slash = {e["name"] for e in client.get("/api/skills/slash-catalog").json()["skills"]}
    invoked = client.post(f"/api/skills/{NAME}/invoke", json={"request": "a gig poster"})
    turn = invoked_skill_messages(store, OWNER, NAME)

    assert (NAME in previewed) is image_on
    assert (NAME in slash) is image_on, (
        "the slash catalog offers a skill every prompt withholds" if not image_on
        else "the slash catalog lost a skill the person can use")
    assert (invoked.status_code == 200) is image_on, invoked.text
    assert bool(turn) is image_on
