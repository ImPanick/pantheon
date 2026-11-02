# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1737` — the agent chooses its skills, and has QA and frontend ones to choose.

The owner, 2026-11-01: *"Skills Audit - We need to ensure the skills can be
selected by the LLM.. If it's entering a QA process, it needs to be able to call
on the "QA" Skills... If its designing frontend or web design things, it needs
to be able to call upon the skills itself."*

Measured on `afba99b` before this change, a turn reached a skill in exactly one
way the model did not choose: the request's words matched it
(`get_relevant_skills`, at most three, `skill_max_injected`). The catalogue
left out the eleven core skills (`B1715`) and every one of the 286 in the
bundled library (`D-2026-10-26-01` §8), the tool that opens a skill was
`manage_skills` — offered only to a person with skills of their own — and there
was no QA, testing, frontend or design skill in Pantheon's own layer at all.

So, each asserted through the path that reads it:

* **Six skills ship** under `library/pantheon/skills/`: `qa` (`qa-a-change`,
  `write-automated-tests`, `test-a-web-page`) and `frontend`
  (`design-a-web-interface`, `build-a-web-page`, `check-accessibility`).
* **The catalogue lists every skill a turn may use**, the core set included,
  and tells the model to open the one for the work it is starting.
* **`use_skill`** is how it does that: read-only, `name` to open, `query` to
  search the catalogue and the library together. It is offered whenever there
  is something to open; `manage_skills`, the editor, still rides only with the
  person's own skills (`B1426`).
* **The real loop, end to end**: on a QA request the model is offered
  `use_skill`, sees `qa-a-change` listed, searches, opens it and gets the
  procedure back from the real dispatcher.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest

import services.memory.skills as skills_mod
import src.constants as constants
from services.memory.skill_lint import MAX_DESCRIPTION, lint_skill, unknown_toolsets
from services.memory.skills import SkillsManager, invalidate_skill_cache

REPO = Path(__file__).resolve().parent.parent
FIRST_PARTY = REPO / "library" / "pantheon" / "skills"

NEW = {
    "qa-a-change": ("qa", ["bash", "read_file"]),
    "write-automated-tests": ("qa", ["bash", "read_file", "edit_file"]),
    "test-a-web-page": ("qa", ["agent_browser"]),
    "design-a-web-interface": ("frontend", []),
    "build-a-web-page": ("frontend", ["read_file", "edit_file"]),
    "check-accessibility": ("frontend", []),
}
EVERY_TOOL = sorted({t for _, needs in NEW.values() for t in needs}
                    | {"web_search", "web_fetch", "ask_user", "python", "grep",
                       "create_document", "edit_document", "manage_memory",
                       "manage_tasks", "computer"})


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fresh install: an empty data dir and the libraries that ship."""
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    invalidate_skill_cache()
    yield SkillsManager(str(tmp_path))
    invalidate_skill_cache()


def _run(coro):
    return asyncio.run(coro)


def _call(tool_fn, args, owner="alice"):
    return _run(tool_fn(json.dumps(args), owner=owner))


# ── 1. what ships ───────────────────────────────────────────────────────────

def test_the_qa_and_frontend_skills_ship_published(store):
    rows = {s["name"]: s for s in store.load_all() if s.get("library") == "pantheon"}
    for name, (category, needs) in NEW.items():
        assert name in rows, name
        assert rows[name]["status"] == "published", name
        assert rows[name]["category"] == category, name
        assert sorted(rows[name].get("requires_toolsets") or []) == sorted(needs), name


def test_every_tool_they_need_is_a_tool_pantheon_has():
    for name, (_, needs) in NEW.items():
        assert unknown_toolsets(needs) == [], name


def test_a_new_skill_names_no_tool_it_does_not_require():
    """The body is pasted or opened only where its `requires_toolsets` are
    allowed, so a tool it names beyond them can reach a turn without it."""
    from src.tool_policy import selectable_tool_names
    known = set(selectable_tool_names())
    for name, (_, needs) in NEW.items():
        body = (FIRST_PARTY / name / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[2]
        named = {t for t in known if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", body)
                 and "_" in t}
        assert named <= set(needs), (name, named - set(needs))


def test_each_new_skill_lints_clean_and_fits_the_description_limit(store):
    rows = [s for s in store.load_all() if s.get("name") in NEW]
    assert len(rows) == len(NEW)
    for s in rows:
        assert len(s["description"]) <= MAX_DESCRIPTION, s["name"]
        report = lint_skill(s, rows)
        errors = [i for i in (report.get("issues") or [])
                  if (i.get("level") or i.get("severity")) == "error"]
        assert errors == [], (s["name"], errors)


# ── 2. the catalogue lists them, the core set included ──────────────────────

def test_the_catalogue_lists_the_core_set_and_the_new_families(store):
    """Red before: `index_for` skipped the core set (`B1715`), and there was no
    `qa` or `frontend` category to list."""
    listed = {s["name"]: s["category"]
              for s in store.index_for(owner="alice", active_toolsets=EVERY_TOOL)}
    for name, (category, _) in NEW.items():
        assert listed.get(name) == category, name
    for core in ("debug-a-failure", "web-research", "write-a-document"):
        assert listed.get(core) == "core", core


def test_a_skill_whose_tool_is_off_is_not_listed(store):
    listed = {s["name"] for s in store.index_for(
        owner="alice", active_toolsets=[t for t in EVERY_TOOL if t != "agent_browser"])}
    assert "test-a-web-page" not in listed
    assert "design-a-web-interface" in listed, "needs no tool, so is always listed"


def test_the_catalogue_tells_the_model_to_choose_and_to_search(store):
    from services.memory.skill_injection import render_skill_index_block
    block = render_skill_index_block(
        store.index_for(owner="alice", active_toolsets=EVERY_TOOL), budget_chars=20000)
    assert "**qa**" in block and "**frontend**" in block
    assert "`qa-a-change`" in block and "`design-a-web-interface`" in block
    assert "`use_skill` name=<name>" in block
    assert "`use_skill` query=" in block
    assert "QA" in block and "frontend" in block


# ── 3. `use_skill`, read-only, opens and searches ───────────────────────────

def test_use_skill_opens_a_skill_by_name(store):
    from src.tools.system import do_use_skill
    out = _call(do_use_skill, {"name": "qa-a-change"})
    assert "## Procedure" in out["results"]
    assert "acceptance list" in out["results"]
    assert out.get("skill") == "qa-a-change"


def test_opening_is_counted_as_an_open(store):
    from src.tools.system import do_use_skill
    _call(do_use_skill, {"name": "design-a-web-interface"})
    invalidate_skill_cache()
    rows = SkillsManager(constants.DATA_DIR).load_active(owner="alice")
    row = {s["name"]: s for s in rows}["design-a-web-interface"]
    assert int(row.get("opens") or 0) >= 1


def test_a_library_skill_opens_with_a_note_that_it_was_written_elsewhere(store):
    from src.tools.system import USE_SKILL_LIBRARY_NOTE, do_use_skill
    out = _call(do_use_skill, {"name": "browser-qa"})
    assert out["results"].startswith(USE_SKILL_LIBRARY_NOTE)
    assert "Browser QA" in out["results"]
    out = _call(do_use_skill, {"name": "qa-a-change"})
    assert USE_SKILL_LIBRARY_NOTE not in out["results"]


def test_an_unknown_name_says_so_and_names_the_closest(store):
    from src.tools.system import do_use_skill
    out = _call(do_use_skill, {"name": "qa-the-change"})
    assert out.get("exit_code") == 1
    assert "qa-a-change" in out["error"]


@pytest.mark.parametrize("query,wants", [
    ("QA", "qa-a-change"),
    ("QA this feature before release", "qa-a-change"),
    ("write unit tests", "write-automated-tests"),
    ("test the web app in the browser", "test-a-web-page"),
    ("design a landing page", "design-a-web-interface"),
    ("frontend web design", "design-a-web-interface"),
    ("build a react component", "build-a-web-page"),
    ("accessibility audit", "check-accessibility"),
    ("debug a crash", "debug-a-failure"),
])
def test_a_search_by_the_kind_of_work_finds_the_skill_for_it(store, query, wants):
    rows = store.find_skills(query, owner="alice", active_toolsets=EVERY_TOOL)
    names = [r["name"] for r in rows]
    assert wants in names[:3], (query, names)


def test_a_search_reaches_the_bundled_library_and_marks_it(store):
    from src.tools.system import do_use_skill
    rows = store.find_skills("python testing pytest", owner="alice", active_toolsets=EVERY_TOOL)
    by_name = {r["name"]: r for r in rows}
    assert by_name.get("python-testing", {}).get("source") == "library"
    out = _call(do_use_skill, {"query": "python testing pytest"})
    assert "`python-testing` (library)" in out["results"]


def test_a_search_with_nothing_to_find_says_so(store):
    from src.tools.system import do_use_skill
    out = _call(do_use_skill, {"query": "zzzz qqqq"})
    assert "No skill fits" in out["results"]


def test_no_arguments_lists_the_catalogue_and_the_library(store):
    from src.tools.system import do_use_skill
    out = _call(do_use_skill, {})
    # Gated on the tools every turn of this person may call: a member with
    # no shell is not listed `qa-a-change`, and needs no tool for this one.
    assert "`design-a-web-interface`" in out["results"]
    assert "bundled library" in out["results"]


def test_use_skill_writes_nothing_and_does_not_taint_the_run():
    """Read-only, and opened skills are the person's own material
    (`D-2026-10-09-01` §1): no write effect, no post-external gate."""
    from src.tool_capabilities import TOOL_CAPABILITIES, ResultIntegrity, ToolEffect
    from src.tool_security import PLAN_MODE_READONLY_TOOLS
    caps = TOOL_CAPABILITIES["use_skill"]
    assert caps.effects == frozenset({ToolEffect.READ_PRIVATE})
    assert caps.result_integrity == ResultIntegrity.SYSTEM
    assert "use_skill" in PLAN_MODE_READONLY_TOOLS


# ── 4. what the turn is offered ─────────────────────────────────────────────

def test_a_fresh_install_has_skills_to_open_and_no_reason_for_the_editor(store):
    from src import agent_loop
    assert agent_loop._skills_to_open(store, "alice", set()) is True
    assert agent_loop._skills_for_turn(store, "alice", set()) == []


def test_the_web_only_turn_and_incognito_withhold_it_as_they_withhold_the_editor():
    text = (REPO / "routes" / "chat_routes.py").read_text(encoding="utf-8")
    web = text[text.index("if _explicit_web_intent:"):text.index("if _search_enabled:")]
    assert '"use_skill"' in web and '"manage_skills"' in web
    inc = text[text.index("if incognito:\n            _withholds.deny({"):]
    inc = inc[:inc.index("}, WITHHELD_BY_POLICY)")]
    assert '"use_skill"' in inc


# ── 5. the real loop, end to end ────────────────────────────────────────────

QA_REQUEST = ("We just changed the sign-up form. QA it properly before we ship: "
              "check it works, try the edge cases, and tell me what passed.")


@pytest.fixture
def scratch(tmp_path):
    return str(tmp_path)


@pytest.mark.parametrize("window", ["large", "small"])
def test_on_a_qa_request_the_model_finds_and_opens_the_qa_skill_itself(scratch, window):
    """Nothing stubbed but the model: the product's own loop, prompt, tool
    selection and dispatcher. The model is offered `use_skill`, sees the QA
    skills listed, searches for QA, opens `qa-a-change` and the procedure comes
    back from the real dispatcher."""
    from tests.helpers import tool_suite_probe as probe

    async def go():
        # The admin: on this test install a member has no shell, and
        # `qa-a-change` drives one, so a member is (rightly) not listed it.
        # `small` is an 8K window the whole suite does not fit, so the tool
        # reaches it through selection and not as part of everything.
        cell = probe.Cell(embeddings="down", mcp="absent", mode="agent",
                          privilege="admin", window=window)
        async with probe.probe_world(os.path.join(scratch, "qa"), mcp_states=("absent",)) as world:
            invalidate_skill_cache()
            search = probe.reply_shapes("use_skill", {"query": "QA a change"})["native"]
            open_ = probe.reply_shapes("use_skill", {"name": "qa-a-change"})["native"]
            record = await probe.drive_turn(
                world, cell, QA_REQUEST, script=[search, open_, "Following qa-a-change."],
                dispatch="real", max_rounds=4)
            first = record.first
            assert "use_skill" in first["tools"], first["tools"]
            assert "`qa-a-change`" in first["prompt"]
            assert "`use_skill` name=<name>" in first["prompt"]
            assert [t for t, _ in record.dispatched] == ["use_skill", "use_skill"]
            outputs = [str(e.get("output") or "") for e in record.events
                       if e.get("type") == "tool_output"]
            assert any("`qa-a-change`" in o and "Skills for" in o for o in outputs), outputs
            assert any("acceptance list" in o for o in outputs), outputs
        invalidate_skill_cache()

    _run(go())


def test_a_greeting_is_not_offered_it(scratch):
    """`B1426`'s complaint stays closed where it was about: no catalogue and
    no skills tool on a turn with no request in it."""
    from tests.helpers import tool_suite_probe as probe

    async def go():
        cell = probe.Cell(embeddings="down", mcp="absent", mode="agent", privilege="user")
        async with probe.probe_world(os.path.join(scratch, "hi"), mcp_states=("absent",)) as world:
            record = await probe.drive_turn(world, cell, "hey there", script=["Hi!"],
                                            dispatch="boundary", max_rounds=1)
            assert "use_skill" not in (record.first.get("tools") or [])
            assert "`use_skill`" not in (record.first.get("prompt") or "")

    _run(go())
