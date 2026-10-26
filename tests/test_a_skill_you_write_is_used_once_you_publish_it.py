# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B581` — a skill written in the Add form, a message that plainly matches it,
and either it is used or the product has said what to do.

Measured against this tree, not the row's: the row blamed the form's 0.8
confidence against the 0.85 floor. Since `B1361`, `injectable_skills` — the one
list the catalogue and the matched bodies read — leaves out every draft a person
wrote, at any confidence (`tests/test_the_whole_skill_suite_reaches_the_model.py
::test_a_half_written_draft_is_not_pasted_in_as_a_proven_procedure` pins that),
and the form saves a draft. So the form's skill reached no turn, and the
surfaces said otherwise: the draft pill promised a match past the confidence
bar, the Settings hint said "a new skill starts at 80%", and the save said only
"Skill added (draft)".

The product now says what is true and offers the step: the toast after the save
says the model is not shown it until it is published and carries **Publish**
(`tests/test_the_skills_window_says_what_the_server_says_js.py`). This file is
the server half of that promise — the form's own request, then the toast's own
request (`PUT /api/skills/{name}` with `status: published`), and the turn
before and after — through the real routes and the real `_build_system_prompt`.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.agent_loop as agent_loop
import src.constants as constants
from routes.skills_routes import setup_skills_routes
from services.memory.skills import SkillsManager, invalidate_skill_cache

QUESTION = "The print queue on the office printer is jammed again, clear the print queue please."

#: What `addSkill()` posts (`static/js/skills.js`), field for field.
FORM = {
    "name": "clear-print-queue",
    "description": "Clear a jammed office print queue",
    "category": "office",
    "when_to_use": "the office printer's print queue is jammed",
    "procedure": ["Stop the print spooler", "Delete the stuck jobs", "Start the spooler"],
    "tags": ["printer", "print queue"],
    "pitfalls": [], "verification": [], "platforms": [], "requires_toolsets": [],
    "status": "draft",
}


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("services.memory.skills._first_party_library_root",
                        lambda: str(tmp_path / "no-shipped"))
    monkeypatch.setenv("PANTHEON_SKILL_LIBRARY", str(tmp_path / "no-vendored"))
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    invalidate_skill_cache()
    sm = SkillsManager(str(tmp_path))
    app = FastAPI()
    app.include_router(setup_skills_routes(sm))
    yield TestClient(app)
    invalidate_skill_cache()


def _skills_text() -> str:
    agent_loop._cached_base_prompt = None
    agent_loop._cached_base_prompt_key = None
    messages, _ = agent_loop._build_system_prompt(
        [{"role": "user", "content": QUESTION}], "gemma-4-26b", None, None,
        disabled_tools=set(), relevant_tools={"ask_user", "update_plan", "manage_skills"},
        owner=None, context_report={})
    return "\n".join(str(m.get("content") or "") for m in messages
                     if "Source: skills" in str(m.get("content") or ""))


def test_the_forms_draft_is_not_used_and_publishing_it_is_what_makes_it_used(world):
    added = world.post("/api/skills/add", json=FORM)
    assert added.status_code == 200, added.text
    assert added.json()["skill"]["status"] == "draft"
    assert "Stop the print spooler" not in _skills_text(), (
        "a person's draft reached the turn — `B1361`'s rule moved, and the toast "
        "that says it will not is now wrong")

    # The toast's Publish, exactly as `_setSkillStatus` sends it.
    assert world.put("/api/skills/clear-print-queue", json={"status": "published"}).status_code == 200
    text = _skills_text()
    assert "`clear-print-queue`" in text
    assert "Stop the print spooler" in text
