# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's frame, its name, and its tool.

* The frame (character, the person's stated rules, open tasks) goes on turns
  in the person's own Apollo chat and nowhere else: what holds still after the
  system messages, what moves just before the newest message, so a local
  server's cached prefix survives a task changing.
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
    head, tail = frame.frame_messages(db, "ada", "s-apollo")
    text = head["content"] + tail["content"]
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


# ── The frame keeps the cached prefix (issue #2927) ─────────────────────────
#
# A local server reuses the KV cache of a request's prefix while its bytes
# match. The frame is rebuilt every turn; when all of it sat after the system
# prompt, a task created between two turns changed bytes ahead of the whole
# history and the model read the conversation again.

def _turn(db, history):
    msgs = ([{"role": "system", "content": "You are helpful."}] + history)
    return frame.into(msgs, frame.frame_messages(db, "ada", "s-apollo"))


def _shared_prefix(a, b):
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n


def test_a_task_changing_between_turns_leaves_the_history_ahead_of_it_untouched(apollo_db):
    db = apollo_db()
    _apollo_chat(db)
    knows.remember("ada", "Never book me before 10", category="rule")
    db.commit()
    first = [{"role": "user", "content": "plan my week"}]
    one = _turn(db, first)
    T.create(db, "ada", title="Book the dentist", pick=lambda o, x: None)
    db.commit()
    second = first + [{"role": "assistant", "content": "Done: three blocks."},
                      {"role": "user", "content": "and the dentist?"}]
    two = _turn(db, second)
    # Everything turn one sent ahead of its frame's tail is sent again, byte
    # for byte, ahead of turn two's: system, head, and the first message.
    cached = one.index(next(m for m in one if "what is open right now" in str(m.get("content"))))
    assert _shared_prefix(one, two) >= cached
    assert two[:cached] == one[:cached]
    assert "Book the dentist" not in "".join(str(m.get("content")) for m in two[:cached + 2])
    # The tail, with the new task, sits right before the newest message.
    assert "Book the dentist" in str(two[-2]["content"])
    assert two[-1] == {"role": "user", "content": "and the dentist?"}


def test_the_head_is_what_holds_still_and_the_tail_is_what_moves(apollo_db):
    db = apollo_db()
    _apollo_chat(db)
    knows.remember("ada", "Never book me before 10", category="rule")
    T.create(db, "ada", title="Book the dentist", pick=lambda o, x: None)
    db.commit()
    head, tail = frame.build_parts(db, "ada")
    assert "Push back" in head and "Never book me before 10" in head
    assert "Book the dentist" not in head
    assert "Book the dentist" in tail
    assert frame.build(db, "ada") == head + "\n\n" + tail


def test_a_tail_goes_before_the_newest_message_and_never_ahead_of_the_head():
    sys_ = {"role": "system", "content": "a"}
    head, tail = {"role": "system", "content": "H"}, {"role": "system", "content": "T"}
    hi = {"role": "user", "content": "hi"}
    out = frame.into([sys_, {"role": "assistant", "content": "x"}, hi], [head, tail])
    assert [m["content"] for m in out] == ["a", "H", "x", "T", "hi"]
    # No history yet: the tail still comes after the head.
    assert [m["content"] for m in frame.into([sys_, hi], [head, tail])] == ["a", "H", "T", "hi"]
    # A list that does not end on the person's message gets the tail last.
    assert [m["content"] for m in frame.into([sys_], [head, tail])] == ["a", "H", "T"]
