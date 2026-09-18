# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-06` — the preview is the prompt, not a drawing of it.

`GET /api/skills/index` exists to answer *"what does the model actually have
access to?"* and returned only the **list**. The text the model is shown was
assembled inline in `agent_loop._build_base_prompt` and nowhere else, so anything
wanting to display it had to write the header, the preamble, the category
grouping and the `*(draft)*` badge a second time — and a second copy of a prompt
string is a copy that is wrong the first time somebody edits the original
(`Law 7`).

These tests do not check that a shared function *exists*. They take the block the
agent loop puts into a real request and the `prompt` the endpoint returns for the
same library, and require them to be the same characters. A re-implementation
that is merely very similar fails here, which is the only property worth pinning.
"""

import json
import textwrap
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.datastructures import State

import src.agent_loop as agent_loop
import src.constants as constants
from routes.skills_routes import setup_skills_routes
from services.memory.skill_injection import (
    INJECTED_FIELDS,
    WITHHELD_FIELDS,
    render_skill_index_block,
)
from services.memory.skills import SkillsManager


# The same wording `tests/test_the_skill_index_is_injected_once.py` uses. The
# loop has its own low-signal read — a short instruction pulls no catalogue —
# so the request has to be one that genuinely would.
REQUEST = ("Please rotate and prune the application log files on the server, "
           "then summarise what you removed.")


def _write_skill(root: Path, name: str, *, category="general", status="published",
                 description="a test procedure"):
    d = root / category / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: {description}
        version: 1.0.0
        category: {category}
        tags: [testing]
        status: {status}
        confidence: 0.9
        source: learned
        created: 2026-01-01T00:00:00Z
        ---

        ## When to Use

        when the test says so

        ## Procedure

        1. do the thing

        ## Pitfalls

        - it may not work

        ## Verification

        - check that it worked
        """), encoding="utf-8")


def _request(user):
    scope = {"type": "http", "app": type("App", (), {"state": State()})(),
             "state": {"current_user": user}, "headers": []}
    return Request(scope=scope)


def _handler(router, path: str, method: str):
    return next(r.endpoint for r in router.routes
                if r.path == path and method in r.methods)


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    _write_skill(root, "tidy-logs", category="ops")
    _write_skill(root, "write-release-notes", category="docs")
    _write_skill(root, "half-baked", category="ops", status="draft")
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(agent_loop, "_cached_base_prompt", None, raising=False)
    monkeypatch.setattr(agent_loop, "_cached_base_prompt_key", None, raising=False)
    return SkillsManager(str(tmp_path), library_root="")


async def _block_the_loop_injects(monkeypatch):
    """The skills catalogue out of one real agent request, not a reconstruction."""
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    seen = {}

    async def capture(*a, **k):
        factory = k.get("candidate_request_factory")
        if factory is not None:
            req = await factory(0, "http://local.test/v1", "small-local-model", None)
            seen["messages"] = (req or {}).get("messages") or []
        yield f"data: {json.dumps({'delta': 'Done.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", capture, raising=False)

    async for _ in agent_loop.stream_agent_loop(
        "http://local.test/v1", "small-local-model",
        [{"role": "user", "content": REQUEST}],
        max_rounds=1, relevant_tools={"bash"},
    ):
        pass

    for m in seen.get("messages") or []:
        content = str(m.get("content", ""))
        if "## Available skills" in content:
            return content
    return ""


@pytest.mark.asyncio
async def test_the_endpoint_returns_the_characters_the_prompt_carries(library, monkeypatch):
    # The headline. One renderer, so the preview cannot drift from the prompt —
    # and the way to prove that is not to look for a shared import but to put
    # the two strings side by side.
    router = setup_skills_routes(library)
    payload = await _handler(router, "/api/skills/index", "GET")(_request(None))

    injected = await _block_the_loop_injects(monkeypatch)
    assert injected, "no skills catalogue reached the request, so this asserts nothing"
    assert payload["prompt"], "the endpoint returned no prompt text"
    assert payload["prompt"].strip() in injected, (
        "the endpoint's preview is not the text the loop injects.\n"
        f"--- endpoint ---\n{payload['prompt']!r}\n--- prompt ---\n{injected!r}"
    )


@pytest.mark.asyncio
async def test_the_preview_says_what_it_leaves_out(library):
    # `P8-07`'s finding, stated by the thing that knows: the procedure, the
    # pitfalls and the verification never reach a prompt line, and a preview
    # that showed them would be telling the user the model has read something
    # it has not.
    router = setup_skills_routes(library)
    payload = await _handler(router, "/api/skills/index", "GET")(_request(None))

    assert set(payload["injected_fields"]) == set(INJECTED_FIELDS)
    for field in ("procedure", "pitfalls", "verification", "when_to_use"):
        assert field in payload["withheld_fields"], f"{field} is claimed as injected"
    assert "check that it worked" not in payload["prompt"]
    assert "do the thing" not in payload["prompt"]
    assert "it may not work" not in payload["prompt"]


@pytest.mark.asyncio
async def test_the_count_and_the_text_describe_the_same_library(library):
    router = setup_skills_routes(library)
    payload = await _handler(router, "/api/skills/index", "GET")(_request(None))
    assert payload["count"] == len(payload["index"])
    assert payload["prompt_chars"] == len(payload["prompt"])
    for entry in payload["index"]:
        assert f"`{entry['name']}`" in payload["prompt"], (
            f"{entry['name']} is counted but not shown"
        )


def test_an_empty_library_renders_nothing_rather_than_a_heading():
    # A heading with no entries under it is an instruction to consult a
    # catalogue that does not exist.
    assert render_skill_index_block([]) == ""
    assert render_skill_index_block(None) == ""
    assert render_skill_index_block([{"description": "no name"}]) == ""


def test_the_draft_badge_is_the_only_thing_status_contributes():
    published = render_skill_index_block(
        [{"name": "a", "description": "d", "category": "c", "status": "published"}])
    draft = render_skill_index_block(
        [{"name": "a", "description": "d", "category": "c", "status": "draft"}])
    assert "*(draft)*" in draft
    assert "*(draft)*" not in published
    assert "published" not in published, "the status value itself is not printed"


def test_withheld_is_derived_from_the_schema_not_restated():
    # A field added to `Skill` has to show up as withheld without anyone
    # remembering to add it here — that is the whole reason it is derived.
    from services.memory.skill_format import Skill
    schema_keys = set(Skill(name="probe").to_dict())
    covered = set(INJECTED_FIELDS) | set(WITHHELD_FIELDS) | {"id", "path",
                                                             "title", "problem",
                                                             "solution", "steps"}
    assert schema_keys <= covered, f"unclassified skill fields: {schema_keys - covered}"
