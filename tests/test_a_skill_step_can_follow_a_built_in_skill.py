# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1892` — a Skill step can follow a built-in skill, as a chat can.

The audit (`skill-step-ignores-builtins`): the palette greyed Skill with "No
skills yet. Make one in Skills." while the Skills tab of the same window listed
24 built-in skills, all published. `_own_skills` dropped every shipped skill,
and `skill_context` read only the person's own store — so no built-in
procedure could be a step, and a new person was told something that looked
false.

Now the palette offers the person's own skills, then the built-in ones the
chat would offer this person's model (`SkillsManager.index_for`, the list
`use_skill` reads), each saying `built_in`. The skill system's rules hold
unchanged: a skill in a group switched off for this person, one whose required
tools this person never has, and the vendored library are not offered — and
not read by name either. A built-in skill's text reaches the model exactly as
a person's own does: untrusted, the gate armed.

Driven (`Law 20`): the real palette route, a real `SkillsManager` over a
temporary data directory and the install's real shipped library, the real
document rule at save, and the real scheduler running the step over a real
SQLite file (`walker_harness`). The one seam is the tool list a person's turns
have (`agent_loop.skill_toolsets_for_owner`), set to say which tools are
withheld.
"""

import json

import pytest

from src.prompt_security import GUARD_OPEN
from src.tool_capabilities import ToolRunSecurityContext
from src.workflow_effects import NO_SKILLS_SENTENCE, StepRefused, skill_context
from tests.helpers.walker_harness import (
    app_for, client_for, make_db, records_of, recording_scheduler, runs_of, seed_workflow,
)

PERSON = {"x-test-user": "alice"}
CHART = "chart-the-numbers"          # shipped, needs no tool
DESKTOP = "workstation-desktop"      # shipped, needs `computer`
VENDORED = "accessibility"           # the vendored (ECC) library's


@pytest.fixture()
def store(monkeypatch, tmp_path):
    """A data directory with no skill of the person's own; the install's real
    shipped library; every tool on except `computer`."""
    from services.memory.skills import SkillsManager, invalidate_skill_cache
    import src.agent_loop as agent_loop
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("src.constants.DATA_DIR", str(data))
    invalidate_skill_cache()
    tools = sorted(t for t in BUILTIN_TOOL_DESCRIPTIONS if t != "computer")
    monkeypatch.setattr(agent_loop, "skill_toolsets_for_owner", lambda owner: list(tools))
    yield SkillsManager(str(data))
    invalidate_skill_cache()


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "skills.db")


async def _palette(factory, monkeypatch):
    app = app_for(factory, recording_scheduler(), monkeypatch)
    async with client_for(app) as client:
        res = await client.get("/api/workflows/palette", headers=PERSON)
    assert res.status_code == 200, res.text
    return res.json()


async def test_with_none_of_their_own_the_built_in_skills_are_offered(store, factory, monkeypatch):
    palette = await _palette(factory, monkeypatch)
    skill = next(k for k in palette["kinds"] if k["kind"] == "skill")
    assert (skill["available"], skill["why"]) == (True, ""), "not “No skills yet”"
    offered = {s["name"]: s for s in palette["skills"]}
    assert offered[CHART]["built_in"] is True and offered[CHART]["description"]
    assert NO_SKILLS_SENTENCE not in json.dumps(palette)


async def test_their_own_come_first_then_the_built_in_ones(store, factory, monkeypatch):
    store.add_skill(name="print-queue", description="Clear the print queue", owner="alice",
                    procedure=["x"], status="published")
    store.add_skill(name="bobs-skill", description="not hers", owner="bob",
                    procedure=["x"], status="published")
    palette = await _palette(factory, monkeypatch)
    names = [(s["name"], s["built_in"]) for s in palette["skills"]]
    assert names[0] == ("print-queue", False)
    assert all(built_in for _name, built_in in names[1:]) and (CHART, True) in names
    assert "bobs-skill" not in {name for name, _b in names}


async def test_the_skill_systems_rules_hold(store, factory, monkeypatch):
    """Off for this person, needing a tool they never have, or vendored: not
    offered, as the chat's catalogue does not offer them."""
    group = store.collections.create_group("alice", "Charts", [CHART])
    store.collections.update_group("alice", group["id"], enabled=False)
    names = {s["name"] for s in (await _palette(factory, monkeypatch))["skills"]}
    assert CHART not in names, "a skill in a group switched off for this person"
    assert DESKTOP not in names, "a skill needing `computer`, which this person never has"
    assert VENDORED not in names, "the vendored library is not shown to a model"
    assert "web-research" in names


def test_a_built_in_skill_is_read_as_untrusted_text_and_said_so(store):
    messages, line = skill_context("alice", CHART)
    assert line == f"Followed the built-in skill “{CHART}”."
    [msg] = messages
    assert msg["metadata"]["trusted"] is False and msg["metadata"]["tool_gate_untrusted"] is True
    assert f"Source: the skill “{CHART}”" in msg["content"].split(GUARD_OPEN, 1)[1]
    ctx = ToolRunSecurityContext()
    ctx.observe_prompt_context(messages)
    assert ctx.gate_is_armed is True


@pytest.mark.parametrize("name", [DESKTOP, VENDORED])
def test_a_skill_it_may_not_follow_is_not_read_by_name_either(store, name):
    with pytest.raises(StepRefused) as refused:
        skill_context("alice", name)
    assert refused.value.sentence.startswith(f"There is no skill named “{name}”")


async def test_a_workflow_following_a_built_in_skill_saves_and_runs(store, factory, monkeypatch):
    step = {"id": "chart", "kind": "skill", "label": "Chart it",
            "config": {"skill": CHART, "prompt": "Chart this week's sales."}}
    seed_workflow(factory, [step], [{"from": "start", "port": "success", "to": "chart"}])
    s = recording_scheduler()
    app = app_for(factory, s, monkeypatch)
    async with client_for(app) as client:
        got = (await client.get("/api/workflows/w-wf", headers=PERSON)).json()["workflow"]
        graph = got["graph"]
        graph["nodes"][0]["config"]["prompt"] = "Chart this week's sales, by day."
        res = await client.put("/api/workflows/w-wf", headers=PERSON,
                               json={"graph": graph, "base_version": got["version"]})
    assert res.status_code == 200, res.text

    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    [call] = s.calls
    said = "\n".join(m["content"] for m in call["slot_state"]["context_messages"])
    assert f"Source: the skill “{CHART}”" in said
    [rec] = records_of(factory, run["id"])
    assert any(st.get("detail") == f"Followed the built-in skill “{CHART}”."
               for st in rec["steps"]), rec["steps"]
