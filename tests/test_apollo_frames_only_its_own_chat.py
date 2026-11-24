# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's frame, its name, and its tool.

* The frame (character, the person's stated rules, open tasks) goes on turns
  in the person's own Apollo chat and nowhere else, after the system messages.
* The Assistant becomes Apollo for people who already had one; a name they
  chose stays theirs.
* The `apollo` tool keeps nothing in Nobody mode, and answers in a sentence.
"""
import asyncio
import json

import pytest

from core.database import CrewMember, Session as DbSession
from src.apollo import frame, knows, seed
from src.apollo import tasks as T
from src.apollo import tool
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def brain(tmp_path, monkeypatch):
    from src.memory import MemoryManager
    monkeypatch.setattr(knows, "_manager", MemoryManager(str(tmp_path)))


def _apollo_chat(db, owner="ada", name="Apollo", session_id="s-apollo"):
    db.add(DbSession(id=session_id, name=name, owner=owner, folder="Assistant",
                     endpoint_url="", model=""))
    db.add(CrewMember(id=f"c-{owner}", owner=owner, name=name, session_id=session_id,
                      is_default_assistant=True,
                      enabled_tools=json.dumps(["manage_memory"])))
    db.commit()


def test_a_turn_in_the_persons_apollo_chat_carries_the_frame(apollo_db):
    db = apollo_db()
    _apollo_chat(db)
    knows.remember("ada", "Never book me before 10", category="rule")
    T.create(db, "ada", title="Book the dentist", pick=lambda o, x: None)
    db.commit()
    [msg] = frame.frame_messages(db, "ada", "s-apollo")
    text = msg["content"]
    assert "You are Apollo, ada's partner" in text
    assert "Push back" in text
    assert "Never book me before 10" in text
    assert "Book the dentist" in text


def test_no_other_chat_and_no_other_person_gets_it(apollo_db):
    db = apollo_db()
    _apollo_chat(db)
    assert frame.frame_messages(db, "ada", "some-other-chat") == []
    assert frame.frame_messages(db, "bob", "s-apollo") == []
    assert frame.frame_messages(db, None, "s-apollo") == []


def test_the_frame_goes_after_the_system_messages():
    msgs = [{"role": "system", "content": "a"}, {"role": "system", "content": "b"},
            {"role": "user", "content": "hi"}]
    out = frame.into(msgs, [{"role": "system", "content": "F"}])
    assert [m["content"] for m in out] == ["a", "b", "F", "hi"]
    assert frame.into(msgs, []) is msgs


def test_the_default_assistant_becomes_apollo_with_its_tool(apollo_db):
    db = apollo_db()
    _apollo_chat(db, name="Assistant")
    crew = db.query(CrewMember).filter(CrewMember.owner == "ada").one()
    assert seed.become_apollo(db, crew) is True
    db.commit()
    assert crew.name == "Apollo"
    assert db.query(DbSession).filter(DbSession.id == "s-apollo").one().name == "Apollo"
    assert "apollo" in json.loads(crew.enabled_tools)
    assert seed.become_apollo(db, crew) is False


def test_a_name_the_person_chose_stays_theirs(apollo_db):
    db = apollo_db()
    _apollo_chat(db, name="Jarvis")
    crew = db.query(CrewMember).filter(CrewMember.owner == "ada").one()
    seed.become_apollo(db, crew)
    assert crew.name == "Jarvis"
    assert db.query(DbSession).filter(DbSession.id == "s-apollo").one().name == "Jarvis"


def test_the_tool_takes_a_bare_action_word_or_json():
    assert tool.parse("status") == {"action": "status"}
    assert tool.parse('{"action": "note", "text": "x"}') == {"action": "note", "text": "x"}
    assert tool.parse("") == {}


def test_the_tool_keeps_nothing_in_nobody_mode(monkeypatch):
    monkeypatch.setattr("src.nobody_mode.keeps_nothing", lambda: True)
    out = asyncio.run(tool.apollo('{"action": "note", "text": "x"}', owner="ada"))
    assert out["exit_code"] == 1 and "Nobody" in out["error"]


def test_the_tool_refuses_an_unknown_action_in_a_sentence(apollo_db, monkeypatch):
    monkeypatch.setattr("src.nobody_mode.keeps_nothing", lambda: False)
    out = asyncio.run(tool.apollo("dance", owner="ada"))
    assert out["exit_code"] == 1 and out["error"].endswith(".")


def test_the_tool_notes_an_open_loop_for_its_person(apollo_db, monkeypatch):
    monkeypatch.setattr("src.nobody_mode.keeps_nothing", lambda: False)
    out = asyncio.run(tool.apollo(json.dumps({"action": "note", "kind": "open_loop",
                                              "text": "Owe Sam the slides"}), owner="ada"))
    assert out["exit_code"] == 0, out
    status = asyncio.run(tool.apollo("status", owner="bob"))
    assert "Owe Sam" not in status["output"]


# ── Apollo's tools are in reach on every turn in its chat ───────────────────
#
# Owner's test, 2026-11-24: a goal in Apollo's chat "just proceeds like any
# other ordinary chat" (no task, no lead, no delegation). The frame told Apollo
# to turn real work into a task, but a turn's tools are picked from its words
# and a goal names none of them. Measured on a local model's budget: the goal
# below was offered 4 of 95 tools, and not `apollo`, `fleet` or `ui_control`.

_GOAL = "Help me get the getpantheon.ai site live this week"


def _plan(pins):
    from src.agent_loop import plan_turn_tool_suite
    return plan_turn_tool_suite(_GOAL, endpoint_url="http://localhost:1234/v1",
                                model="qwen2.5-7b-instruct", pinned_tools=pins,
                                get_setting_fn=lambda *a, **k: None)


def test_a_goal_names_none_of_apollos_tools_so_the_words_alone_leave_them_out():
    assert not (frame.TOOLS & set(_plan(()).offered))


def test_pinned_apollos_tools_reach_a_goal_turn_on_a_local_model():
    suite = _plan(frame.TOOLS)
    assert frame.TOOLS <= set(suite.offered), suite.offered
    assert frame.TOOLS == {"apollo", "fleet", "ui_control"}


def test_the_chat_route_pins_them_in_an_apollo_chat_only():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "routes" / "chat_routes.py").read_text(encoding="utf-8")
    assert "pinned_tools=(set(_apollo.TOOLS) if _apollo_frame and not _summoned else None)," in src


def test_a_pin_survives_every_selection_path_and_is_capped_with_the_rest():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src" / "agent_loop.py").read_text(encoding="utf-8")
    union = src.index("_relevant_tools |= _turn_pinned_tools")
    # After the vector retrieval and the keyword fallback, before the cap.
    assert src.index("ToolIndex.select_without_embeddings(\n            _retrieval_query") < union
    assert union < src.index("_capped_out = sorted(set(_relevant_tools) - disabled_tools.allowed_among(_relevant_tools))")
