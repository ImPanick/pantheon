# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pantheon ships its own skills for driving the workstation — `B1419`/`B1420`.

The owner, 2026-10-22: *"custom skills inside of this platform itself, delivery
by default… that can be used by the llm to perfectly control the vm in the
workspace… all aspects including navigating the mouse, clicking, pulling up
applications, running the shell etc."*

Four procedures under `library/pantheon/skills/`, published, read before the
vendored ECC layer, and gated on the tools they drive (`requires_toolsets`), so
they reach a turn exactly when the workstation would answer it. Every command
in them was run on a live Xvfb + JWM + xdotool + Firefox desktop built from the
workstation's own `.jwmrc` and Firefox policy before it was written down, and
the desktop's lines again on XFCE built from the skeleton's `.config` when it
replaced JWM (`D-2026-10-31-02`).

Three things had to change for "by default" to be true, and each is asserted
here through the path the model actually takes:

* **A signed-in person saw no shipped skill at all.** `load(owner)` is a
  person's *own* store, and `load_active` — what the model may be shown — was
  built from it, so the whole read-only library existed only for installs with
  sign-in off.
* **The model could not open a shipped skill it had been told about** (`B590`):
  `manage_skills action=view` read the person's store only.
* **An execution turn matched skills against "yes, go ahead"** (`B1420`), not
  the approved plan that holds the work — the same blindness `B1414` fixed for
  tool selection.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from services.memory import skills as skills_mod
from services.memory.skills import SkillsManager, invalidate_skill_cache
from src import agent_loop, constants
from src.agent_tools import computer_tools
from workstation import protocol as P

REPO = Path(__file__).resolve().parent.parent
FIRST_PARTY = REPO / "library" / "pantheon" / "skills"
SHIPPED = {
    "workstation-desktop": ["computer"],
    "workstation-apps-and-windows": ["computer", "bash"],
    "workstation-shell": ["computer", "bash"],
    "workstation-self-test": ["computer", "bash"],
}
BUILD_REQUEST = "Create a website for my bakery and make sure it works"
GO_AHEAD = "Yes, go ahead."
PLAN = ("1. Create a project folder for the bakery site\n"
        "2. Write index.html with a hero section, menu and contact form\n"
        "3. Serve it locally and check it renders in the browser\n"
        "4. Fix any layout issues")


@pytest.fixture
def store(tmp_path, monkeypatch):
    """An empty data dir with the shipped library under it, as a fresh install."""
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(agent_loop, "_cached_base_prompt", None, raising=False)
    monkeypatch.setattr(agent_loop, "_cached_base_prompt_key", None, raising=False)
    invalidate_skill_cache()
    yield SkillsManager(str(tmp_path))
    invalidate_skill_cache()


def _names(rows):
    return {r.get("name") for r in rows}


def _own_skill(store, name, owner, text="my own way"):
    """A person's file under the shipped name — what an import or a hand-made
    folder produces (`add_skill` itself suffixes a taken name)."""
    d = Path(store.skills_root) / "workstation" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {text}\nstatus: published\nowner: {owner}\n---\n"
        f"## Procedure\n1. {text}\n", encoding="utf-8")
    invalidate_skill_cache()


# ── 1. what ships ───────────────────────────────────────────────────────────

def test_four_skills_ship_published_and_gated_on_the_tools_they_drive(store):
    # The workstation's four; the core set beside them is
    # `tests/test_the_core_skills_ship_switched_on.py`'s.
    dirs = {d.name for d in FIRST_PARTY.iterdir() if d.is_dir() and d.name.startswith("workstation-")}
    assert dirs == set(SHIPPED)
    rows = {s["name"]: s for s in store.load_all()
            if s.get("library") == "pantheon" and s.get("category") == "workstation"}
    assert set(rows) == set(SHIPPED)
    for name, needs in SHIPPED.items():
        assert rows[name]["status"] == "published", name
        assert rows[name]["requires_toolsets"] == needs, name
        assert rows[name]["bundled"] and rows[name]["editable"] is False


def test_the_vendored_library_is_still_there_beside_them(store):
    ecc = [s for s in store.load_all() if s.get("library") == "ecc"]
    assert len(ecc) >= 250


def test_a_named_library_root_still_isolates(tmp_path):
    """How every other test keeps the shipped library out: unchanged."""
    assert SkillsManager(str(tmp_path), library_root="").load_all() == []


def test_the_first_party_layer_shadows_a_vendored_skill_of_the_same_name(tmp_path, monkeypatch):
    mine, theirs = tmp_path / "pantheon", tmp_path / "ecc"
    for root, text in ((mine, "first party"), (theirs, "vendored")):
        (root / "dup").mkdir(parents=True)
        (root / "dup" / "SKILL.md").write_text(
            f"---\nname: dup\ndescription: {text}\nstatus: published\n---\n", encoding="utf-8")
    monkeypatch.setattr(skills_mod, "_first_party_library_root", lambda: str(mine))
    monkeypatch.setattr(skills_mod, "_default_library_root", lambda: str(theirs))
    invalidate_skill_cache()
    rows = [s for s in SkillsManager(str(tmp_path / "data")).load_all() if s["name"] == "dup"]
    assert [(r["description"], r["library"]) for r in rows] == [("first party", "pantheon")]


# ── 2. who sees them ────────────────────────────────────────────────────────

@pytest.mark.parametrize("owner", [None, "alice"])
def test_every_person_is_offered_them_when_the_workstation_is(store, owner):
    """Red before `B1419` for `alice`: `load_active(owner)` held her own store only."""
    got = _names(store.injectable_skills(owner=owner, active_toolsets=["computer", "bash"]))
    assert set(SHIPPED) <= got


def test_without_the_workstations_screen_none_of_them_is_offered(store):
    got = _names(store.injectable_skills(owner="alice", active_toolsets=["bash", "read_file"]))
    assert not (set(SHIPPED) & got)


def test_with_the_screen_but_no_shell_only_the_screen_skill_is_offered(store):
    got = _names(store.injectable_skills(owner="alice", active_toolsets=["computer"]))
    assert set(SHIPPED) & got == {"workstation-desktop"}


def test_a_persons_own_skill_of_the_same_name_wins_for_them_only(store):
    _own_skill(store, "workstation-desktop", "alice")
    alice = [s for s in store.load_active(owner="alice") if s["name"] == "workstation-desktop"]
    bob = [s for s in store.load_active(owner="bob") if s["name"] == "workstation-desktop"]
    assert [s.get("owner") for s in alice] == ["alice"]
    assert [s.get("library") for s in bob] == ["pantheon"]


def test_the_persons_editable_store_is_unchanged(store):
    """`load(owner)` is what the Workshop edits and the routes guard; it stays theirs."""
    assert store.load(owner="alice") == []


# ── 3. the model can open what it was told about (`B590`) ──────────────────

@pytest.fixture
def tool_store(store, monkeypatch):
    monkeypatch.setattr("services.memory.skills.SkillsManager",
                        lambda *a, **k: SkillsManager(constants.DATA_DIR))
    return store


@pytest.mark.asyncio
async def test_the_model_opens_a_shipped_skill_by_name(tool_store):
    from src.tools.system import do_manage_skills
    out = await do_manage_skills(json.dumps({"action": "view", "name": "workstation-shell"}),
                                 owner="alice")
    assert "## Procedure" in out.get("results", ""), out


@pytest.mark.asyncio
async def test_the_model_opens_a_shipped_skills_reference(tool_store):
    from src.tools.system import do_manage_skills
    out = await do_manage_skills(json.dumps({"action": "view_ref", "name": "workstation-desktop",
                                             "path": "references/keys.md"}), owner="alice")
    assert "ctrl+shift+k" in out.get("results", ""), out


@pytest.mark.asyncio
async def test_a_shipped_skill_is_never_handed_to_a_write(tool_store):
    from src.tools.system import do_manage_skills
    path = FIRST_PARTY / "workstation-shell" / "SKILL.md"
    before = path.read_bytes()
    out = await do_manage_skills(json.dumps({"action": "patch", "name": "workstation-shell",
                                             "old_string": "Procedure", "new_string": "X"}),
                                 owner="alice")
    assert out.get("exit_code") == 1
    assert path.read_bytes() == before
    assert tool_store.read_skill_md("workstation-shell", owner="alice") is None


@pytest.mark.asyncio
async def test_a_shipped_skills_card_shows_its_source(store):
    from routes.skills_routes import setup_skills_routes
    router = setup_skills_routes(store)
    handler = next(r.endpoint for r in router.routes
                   if r.path == "/api/skills/{skill_id}/markdown" and "GET" in r.methods)

    class _Req:
        class state:
            current_user = None

    out = await handler(_Req(), "workstation-desktop")
    assert out["markdown"].startswith("---\nname: workstation-desktop")


@pytest.mark.asyncio
async def test_a_shipped_skill_runs_as_a_slash_command(store, monkeypatch):
    from fastapi import HTTPException

    from routes.skills_routes import setup_skills_routes
    router = setup_skills_routes(store)
    handler = next(r.endpoint for r in router.routes
                   if r.path.endswith("/invoke") and "POST" in r.methods)

    class _Req:
        class state:
            current_user = "alice"

        async def json(self):
            return {"request": "open firefox"}

    # `B1499`. The invoke check follows the tool gates now, as every prompt
    # does: this skill requires `computer` and `bash`, and `alice` — no account
    # in this store, so a non-admin with no workstation — has no `bash`. Her
    # prompts never carried it, and `/workstation-apps-and-windows` is refused
    # to her too. A person who has the tools (here, nothing withheld) runs it.
    with pytest.raises(HTTPException) as refused:
        await handler(_Req(), "workstation-apps-and-windows")
    assert refused.value.status_code == 404
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(),
                        raising=False)
    out = await handler(_Req(), "workstation-apps-and-windows")
    # `B1374` moved this. The answer was one string with the SKILL.md inside it,
    # sent as the person's own message, and this case pinned that by finding
    # "BEGIN SKILL" in it. Now the message is the person's words and the skill
    # rides beside it by name; the turn reads the shipped source and frames it.
    assert out["skill"] == "workstation-apps-and-windows"
    assert out["message"] == "open firefox"
    assert "BEGIN SKILL" not in json.dumps(out)
    from services.memory.skill_injection import invoked_skill_messages
    framed, note = invoked_skill_messages(store, "alice", "workstation-apps-and-windows")
    assert "name: workstation-apps-and-windows" in framed["content"]
    assert "/workstation-apps-and-windows" in note["content"]


# ── 4. they reach the prompt on the turns that need them ────────────────────

def _skills_block(question, *, disabled=(), owner="alice", approved_plan=None):
    agent_loop._cached_base_prompt = None
    agent_loop._cached_base_prompt_key = None
    messages, _ = agent_loop._build_system_prompt(
        [{"role": "user", "content": question}], "gemma-4-26b", None, None,
        disabled_tools=set(disabled), owner=owner, context_report={},
        approved_plan=approved_plan,
    )
    return "\n".join(str(m.get("content") or "") for m in messages
                     if isinstance(m, dict) and "Source: skills" in str(m.get("content") or ""))


def test_a_build_request_gets_the_self_test_procedure(store):
    block = _skills_block(BUILD_REQUEST)
    assert "### workstation-self-test" in block
    assert "ctrl+shift+k" in block, "the procedure's steps, not only its name"


def test_a_turn_without_the_workstation_gets_none_of_them(store):
    block = _skills_block(BUILD_REQUEST, disabled={"computer"})
    assert not any(name in block for name in SHIPPED), block[:2000]


def test_an_execution_turn_is_matched_against_its_plan(store):
    assert "### workstation-self-test" not in _skills_block(GO_AHEAD), \
        "premise: 'go ahead' alone does not name the work"
    assert "### workstation-self-test" in _skills_block(GO_AHEAD, approved_plan=PLAN)


def test_the_skill_query_is_the_message_alone_without_a_plan():
    assert agent_loop._skill_query("hi") == "hi"
    assert agent_loop._skill_query("hi", "   ") == "hi"
    assert agent_loop._skill_query("hi", "x" * 5000) == "hi\n" + "x" * 3000


def _loop_prompt(monkeypatch, message, *, plan=None, workstation=True):
    """The system messages the real loop built for one turn, and the plan it
    handed the builder. The workstation's availability is the loop's own
    question (`_computer_unavailable_reason`), answered here."""
    import asyncio

    built, plans = [], []
    real = agent_loop._build_system_prompt

    def spy(*a, **k):
        plans.append(k.get("approved_plan"))
        out = real(*a, **k)
        built.extend(out[0])
        return out

    async def _stream(_candidates, messages, **kwargs):
        yield 'data: {"delta": "Done."}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "_build_system_prompt", spy)
    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", _stream, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(agent_loop, "_computer_unavailable_reason",
                        lambda *a, **k: None if workstation else "The workstation is off.")

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://x/v1", "m", [{"role": "user", "content": message}],
            max_rounds=1, approved_plan=plan, owner="alice")]

    asyncio.run(drain())
    text = "\n".join(str(m.get("content") or "") for m in built if isinstance(m, dict))
    return text, plans


def test_the_loop_gives_a_build_turn_the_procedure_when_the_workstation_answers(store, monkeypatch):
    text, _ = _loop_prompt(monkeypatch, BUILD_REQUEST)
    assert "### workstation-self-test" in text


def test_the_loop_gives_it_nothing_when_the_workstation_is_off(store, monkeypatch):
    text, _ = _loop_prompt(monkeypatch, BUILD_REQUEST, workstation=False)
    assert not any(name in text for name in SHIPPED)


def test_the_loop_hands_the_builder_its_approved_plan(store, monkeypatch):
    text, plans = _loop_prompt(monkeypatch, GO_AHEAD, plan=PLAN)
    assert plans and all(p == PLAN for p in plans), plans
    assert "### workstation-self-test" in text


def test_all_four_bodies_fit_the_default_budget_uncut(store):
    from services.memory.skill_injection import render_matched_skills_block
    rows = [s for s in store.injectable_skills(owner="alice", active_toolsets=["computer", "bash"])
            if s["name"] in SHIPPED]
    report: dict = {}
    render_matched_skills_block(rows, owner="alice", report=report)
    assert report["skill_bodies_truncated"] is False
    assert report["skill_bodies_omitted"] == 0
    assert not report["skill_bodies_shortened"]


# ── 5. what they say is what the workstation is (`Law 7`) ───────────────────

def _text(name):
    return (FIRST_PARTY / name / "SKILL.md").read_text(encoding="utf-8")


def test_the_screen_size_is_the_protocols():
    assert f"{P.SCREEN_WIDTH}×{P.SCREEN_HEIGHT}" in _text("workstation-desktop")


def test_every_action_the_computer_tool_has_is_taught():
    """"Literally everything possible": no action is left undescribed."""
    text = _text("workstation-desktop")
    missing = [a for a in computer_tools.ACTIONS if f"`{a}`" not in text]
    assert not missing, missing


def test_every_action_the_skill_names_is_one_the_tool_has():
    text = _text("workstation-desktop")
    named = set(re.findall(r"`computer` action `(\w+)`", text))
    assert named and named <= set(computer_tools.ACTIONS)


def test_the_limits_it_quotes_are_the_protocols():
    text = _text("workstation-desktop")
    assert f"{P.MAX_TYPE_CHARS:,}" in text
    assert f"{P.MAX_WAIT_MS:,}" in text
    assert f"at most {P.MAX_SCROLL_CLICKS}" in text


def test_the_projects_folder_it_names_is_the_protocols():
    """`B1424`: each person's own folder, by the variable the daemon sets —
    never the shared root, which nobody but an admin may list."""
    for name in ("workstation-shell", "workstation-self-test"):
        assert f"${P.PROJECTS_ENV}/<" in _text(name), name
        assert f"{P.PROJECTS_DIR}/<" not in _text(name), name


def test_no_skill_tells_the_model_to_use_a_background_job_the_workstation_refuses():
    for name in SHIPPED:
        for line in _text(name).splitlines():
            if "#!bg" in line:
                assert "refused" in line, (name, line)


# ── `B1426`: a shipped skill puts `manage_skills` in a turn only where it shows ─

def test_the_vendored_drafts_do_not_put_the_skills_tool_in_every_turn(store):
    """286 drafts nobody is shown, and four procedures gated on the screen: on a
    turn without the workstation, none of them is a reason to offer the tool."""
    rows = agent_loop._skills_for_turn(store, "alice", {"computer"})
    assert rows == []
    assert agent_loop._skill_body_tool_offered(
        BUILD_REQUEST, suppress_skills=False, owner="alice",
        data_dir=constants.DATA_DIR, disabled_tools={"computer"}) is False


def test_a_turn_that_can_show_them_offers_the_tool_to_open_them(store):
    rows = agent_loop._skills_for_turn(store, "alice", set())
    assert {r["name"] for r in rows} == set(SHIPPED)
    assert agent_loop._skill_body_tool_offered(
        BUILD_REQUEST, suppress_skills=False, owner="alice",
        data_dir=constants.DATA_DIR, disabled_tools=set()) is True


def test_a_persons_own_drafts_still_count(store):
    _own_skill(store, "half-done", "alice")
    store.update_skill("half-done", {"status": "draft"}, owner="alice")
    names = {r["name"] for r in agent_loop._skills_for_turn(store, "alice", {"computer"})}
    assert names == {"half-done"}
