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
    # `B1737`. The shipped layer is held out as the vendored one is: these
    # cases compare the preview with the injection for this store, and the
    # preview reads this person's standing withholds before the loop's are
    # stubbed, so a shipped skill that drives `bash` was in one and not the other.
    import services.memory.skills as _skills
    monkeypatch.setattr(_skills, "_first_party_library_root",
                        lambda: str(tmp_path / "no-shipped-skills"))
    return SkillsManager(str(tmp_path), library_root="")


def _no_trim(monkeypatch):
    """A budget of 0 — *no trimming*. `B751`: the loop reads the budget on the
    role chain (`context_budget.resolve_agent_input_budget_setting`) rather
    than through `agent_loop.get_setting`, so that is where 0 is set."""
    import src.context_budget as context_budget
    from src.limit_policy import ResolvedLimit

    monkeypatch.setattr(context_budget, "resolve_agent_input_budget_setting",
                        lambda owner=None: ResolvedLimit(value=0, source="setting"))


async def _block_the_loop_injects(monkeypatch):
    """The skills catalogue out of one real agent request, not a reconstruction."""
    # `B1425`: no trim. On an endpoint that reports no window the loop trims to
    # 6,000 tokens and sheds the skills block to keep the tools' prompt whole;
    # what this file compares is the text, not what survives a small window.
    _no_trim(monkeypatch)
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


# ── `B580` / `B1376` — the same list, and the same sentence, as the turn ─────

def _write_needing(root: Path, name: str, tool: str):
    d = root / "design" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: a procedure that needs {tool}
        version: 1.0.0
        category: design
        tags: [testing]
        requires_toolsets: [{tool}]
        status: published
        confidence: 0.9
        source: learned
        ---

        ## When to Use

        rotate and prune the application log files on the server

        ## Procedure

        1. call {tool}
        """), encoding="utf-8")


async def _injected_with(monkeypatch, settings: dict):
    """`_block_the_loop_injects`, with the install's settings as given."""
    def get_setting(k, d=None):
        return settings.get(k, d)

    _no_trim(monkeypatch)          # `B751`: where the budget is read now
    monkeypatch.setattr(agent_loop, "get_setting", get_setting, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    agent_loop._cached_base_prompt = None
    agent_loop._cached_base_prompt_key = None
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
@pytest.mark.parametrize("image_on", [False, True])
async def test_a_skill_needing_a_switched_off_tool_is_out_of_both_or_in_both(
        library, tmp_path, monkeypatch, image_on):
    """`B580`. `image_gen_enabled` ships off, so on a default install
    `generate_image` is withheld from every turn (`setting_disabled_tools`). A
    skill declaring `requires_toolsets: [generate_image]` was hidden from the
    prompt and listed by the endpoint, which called `index_for` with no
    `active_toolsets`. Red before: the endpoint listed it with the tool off.
    The other half of the parameter is the control — on, both carry it."""
    _write_needing(tmp_path / "skills", "make-a-poster", "generate_image")
    settings = {"image_gen_enabled": image_on}
    injected = await _injected_with(monkeypatch, settings)
    assert injected, "no catalogue reached the request, so this asserts nothing"

    router = setup_skills_routes(library)
    payload = await _handler(router, "/api/skills/index", "GET")(_request(None))
    listed = {e["name"] for e in payload["index"]}

    assert ("make-a-poster" in listed) is image_on
    assert ("`make-a-poster`" in injected) is image_on
    assert payload["prompt"].strip() in injected


@pytest.mark.asyncio
async def test_the_preview_without_the_tool_is_the_block_a_turn_without_it_gets(library):
    """`B1376`. The block's first sentence depends on whether `manage_skills` is
    callable on the turn; the preview had no turn and always rendered the
    fetchable form. `?can_fetch=false` renders the other form word for word —
    compared against the loop's own block on a turn with the tool disabled — and
    each answer says which it assumed."""
    from services.memory.skill_injection import (
        INDEX_ASSUMES_FETCH,
        INDEX_ASSUMES_NO_FETCH,
        INDEX_PREAMBLE_NO_FETCH,
    )

    router = setup_skills_routes(library)
    handler = _handler(router, "/api/skills/index", "GET")
    fetchable = await handler(_request(None))
    no_fetch = await handler(_request(None), can_fetch=False)
    assert (fetchable["can_fetch"], fetchable["assumes"]) == (True, INDEX_ASSUMES_FETCH)
    assert (no_fetch["can_fetch"], no_fetch["assumes"]) == (False, INDEX_ASSUMES_NO_FETCH)
    assert INDEX_PREAMBLE_NO_FETCH.split(".")[0] in no_fetch["prompt"]
    assert "manage_skills" not in no_fetch["prompt"]

    agent_loop._cached_base_prompt = None
    agent_loop._cached_base_prompt_key = None
    messages, _mcp = agent_loop._build_system_prompt(
        [{"role": "user", "content": REQUEST}], "gemma-4-26b", None, None,
        disabled_tools={"manage_skills"},
        relevant_tools={"ask_user", "update_plan", "web_search"},
        owner=None, context_report={},
    )
    block = next(str(m.get("content")) for m in messages
                 if "## Available skills" in str(m.get("content", "")))
    assert no_fetch["prompt"].strip() in block
    assert fetchable["prompt"].strip() not in block
