# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-08`'s API half — *Test this step*, with data you chose, and nothing
else runs (`/work/notes/SLICE-B-DESIGN.md` § 4).

**Measured before this file, on `5654cd4`:** there was no way to run one step
of anything on an input a person chose; `POST /api/workflows/{id}/nodes/
{node_id}/test` did not exist.

Driven through the real route: the step as it stands on the canvas (its
unsaved settings) is validated as a save validates it; its input is built from
the chosen source — the last real run's record, the pinned sample, the
person's own text, an example a model writes, or nothing — and a sample that
loses keys the step is never handed says which. A step whose effects notify,
touch a remote, delete, rewrite or run code, and every run-task step, answers
first with its dry plan and `outcome: "needs_confirmation"`; the same request
with `confirm: true` runs it (`outcome: "ran"`). The engine's
`test_workflow_node` is a recorder here (it is `wf-engine`'s, `C1`) — what
these cases hold is what the route hands it and that the route itself writes
no run row and no node record.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest

from core.database import ScheduledTask, TaskRun, utcnow_naive
from tests.helpers import workflow_contract as wc
from test_a_workflow_is_kept_as_one_document import (  # noqa: F401
    admins, call, client, graph, new, rows, save, sched, step, wf_db,
)

DOC = graph([step("n1", label="Summarise my inbox"),
             step("n2", "action", "Classify", action="classify_events"),
             step("n3", "action", "Tidy chats", action="tidy_sessions"),
             step("n4", "run_task", "Run the backup", task_id="bk")],
            [("n1", "success", "n2"), ("n2", "success", "n3"), ("n3", "success", "n4")])


@pytest.fixture()
def wf(client, wf_db):
    db = wf_db()
    try:
        db.add(ScheduledTask(id="bk", owner="alice", name="Backup", task_type="action",
                             action="tidy_documents", trigger_type="webhook", status="active"))
        db.commit()
    finally:
        db.close()
    res = save(client, new(client), DOC)
    assert res.status_code == 200, res.text
    out = res.json()["workflow"]
    # The start fires on mail: the entry step is handed an `email_received`.
    db = wf_db()
    try:
        start = db.query(ScheduledTask).filter(ScheduledTask.id == out["task_id"]).first()
        start.trigger_type, start.trigger_event = "event", "email_received"
        db.commit()
    finally:
        db.close()
    return out


def _test(client, wf, node, **body):
    return call(client, "POST", f"/api/workflows/{wf['id']}/nodes/{node['id']}/test",
                json=dict({"node": node}, **body))


def _nothing_written(factory):
    TaskRunNode = wc.models()[2]
    assert rows(factory, TaskRun) == [] and rows(factory, TaskRunNode) == []


def test_a_prompt_step_runs_on_your_text_as_it_stands_on_the_canvas(client, wf, sched, wf_db):
    unsaved = dict(DOC["nodes"][0], label="Summarise it shorter",
                   config={"prompt": "Two lines only."})
    res = _test(client, wf, unsaved, source="custom",
                input={"account": "work", "folder": "INBOX", "message_key": "42", "mood": "x"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["outcome"] == "ran"
    assert (out["status"], out["text"], out["data"]) == ("success", "The summary.", {"n": 3})
    assert out["dropped"] == ["mood"] and out["source"] == "custom"
    (called,) = sched.tests
    assert called["node"]["config"]["prompt"] == "Two lines only.", "the unsaved settings are tested"
    assert called["task_id"] == wf["task_id"] and called["workflow_name"] == wf["name"]
    assert called["input"]["data"] == {"account": "work", "folder": "INBOX", "message_key": "42"}
    assert out["input_used"] == called["input"]
    _nothing_written(wf_db)


def test_an_action_that_only_writes_runs_without_asking(client, wf, sched):
    res = _test(client, wf, DOC["nodes"][1], source="none")
    assert res.json()["outcome"] == "ran" and len(sched.tests) == 1
    assert sched.tests[0]["input"] is None


def test_an_action_that_deletes_shows_its_plan_and_asks_first(client, wf, sched, wf_db):
    from src.builtin_actions import EFFECT_SENTENCES
    res = _test(client, wf, DOC["nodes"][2], source="none")
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["outcome"] == "needs_confirmation"
    assert out["plan"] and all(isinstance(line, str) for line in out["plan"])
    assert EFFECT_SENTENCES["deletes"] in out["effects"]
    assert sched.tests == [], "nothing ran before the yes"
    _nothing_written(wf_db)
    again = _test(client, wf, DOC["nodes"][2], source="none", confirm=True)
    assert again.json()["outcome"] == "ran" and len(sched.tests) == 1


def test_a_run_task_step_always_asks_because_it_really_runs_a_task(client, wf, sched):
    res = _test(client, wf, DOC["nodes"][3], source="none")
    out = res.json()
    assert out["outcome"] == "needs_confirmation"
    assert out["plan"][0] == "Would run the task “Backup”."
    assert sched.tests == []


def test_the_last_input_is_the_last_real_runs_and_says_when_there_is_none(client, wf, sched, wf_db):
    TaskRunNode = wc.models()[2]
    node = DOC["nodes"][0]
    none_yet = _test(client, wf, node, source="last")
    assert none_yet.status_code == 400 and "has not run yet" in none_yet.json()["detail"]
    db = wf_db()
    try:
        for run_id, dry, subject, minutes in (("old", False, "Old", 2), ("new", False, "New", 1),
                                              ("plan", True, "Plan", 0)):
            at = utcnow_naive() - timedelta(minutes=minutes)
            db.add(TaskRun(id=run_id, task_id=wf["task_id"], status="success", started_at=at))
            db.flush()
            db.add(TaskRunNode(id=str(uuid.uuid4()), run_id=run_id, node_id="n1", seq=1, dry=dry,
                               status="success", started_at=at,
                               input=json.dumps({"source": "event", "event": "email_received",
                                                 "data": {"message_key": subject}})))
        db.commit()
    finally:
        db.close()
    res = _test(client, wf, node, source="last")
    assert res.status_code == 200, res.text
    assert sched.tests[-1]["input"]["data"] == {"message_key": "New"}, "the newest, never a dry run's"


def test_a_last_input_too_long_to_keep_is_refused_in_words(client, wf, wf_db):
    TaskRunNode = wc.models()[2]
    db = wf_db()
    try:
        db.add(TaskRun(id="r", task_id=wf["task_id"], status="success", started_at=utcnow_naive()))
        db.flush()
        db.add(TaskRunNode(id="x", run_id="r", node_id="n1", seq=1, dry=False, status="success",
                           started_at=utcnow_naive(),
                           input=json.dumps({"truncated": True, "chars": 50000, "preview": "…"})))
        db.commit()
    finally:
        db.close()
    res = _test(client, wf, DOC["nodes"][0], source="last")
    assert res.status_code == 400
    assert "too long to keep whole" in res.json()["detail"] and "50000" in res.json()["detail"]


def test_a_pinned_sample_is_what_the_test_is_handed(client, wf, sched):
    nothing = _test(client, wf, DOC["nodes"][0], source="pinned")
    assert nothing.status_code == 400 and "Nothing is pinned" in nothing.json()["detail"]
    pin = call(client, "PUT", f"/api/workflows/{wf['id']}",
               json={"pins": {"n1": {"account": "work", "message_key": "Pinned one"}}})
    assert pin.status_code == 200, pin.text
    res = _test(client, wf, DOC["nodes"][0], source="pinned")
    assert res.status_code == 200
    assert sched.tests[-1]["input"]["data"]["message_key"] == "Pinned one"


def test_an_example_is_written_by_a_model_for_the_fields_the_step_is_handed(client, wf, sched,
                                                                            monkeypatch):
    import src.endpoint_resolver as er
    import src.llm_core as llm
    asked = []
    monkeypatch.setattr(er, "resolve_endpoint", lambda role, owner=None: ("http://m", "util", {}))

    async def fake_call(**kwargs):
        asked.append(kwargs)
        return '```json\n{"account": "work", "folder": "INBOX", "message_key": "Invented"}\n```'
    monkeypatch.setattr(llm, "llm_call_async", fake_call)
    res = _test(client, wf, DOC["nodes"][0], source="example")
    assert res.status_code == 200, res.text
    from src.event_bus import EVENT_PAYLOAD_FIELDS
    fields = EVENT_PAYLOAD_FIELDS["email_received"]
    assert all(f in asked[0]["messages"][1]["content"] for f in fields)
    assert res.json()["input_used"]["data"]["message_key"] == "Invented"
    # A step handed nothing (a schedule's first step) has nothing to invent.
    plain = new(client, "Scheduled")
    plain = save(client, plain, graph([step("n1")])).json()["workflow"]
    res = _test(client, plain, step("n1"), source="example")
    assert res.status_code == 400 and "handed nothing" in res.json()["detail"]


def test_a_test_is_checked_as_a_save_is(client, wf, sched, admins):
    from src.task_action_policy import admin_refusal_message
    bad = _test(client, wf, step("n1", "llm", "No prompt", prompt=""), source="none")
    assert bad.status_code == 400 and bad.json()["detail"]
    risky = _test(client, wf, step("n3", "action", "Shell", action="run_local", prompt="ls"),
                  source="none")
    assert (risky.status_code, risky.json()) == (403, {"detail": admin_refusal_message("run_local")})
    mismatch = call(client, "POST", f"/api/workflows/{wf['id']}/nodes/n2/test",
                    json={"node": DOC["nodes"][0], "source": "none"})
    assert mismatch.status_code == 400
    odd = _test(client, wf, DOC["nodes"][0], source="yesterday")
    assert odd.status_code == 400 and "source must be one of" in odd.json()["detail"]
    assert sched.tests == []


def test_a_sample_typed_as_plain_text_goes_where_the_step_reads_text(client, wf, sched):
    """The person's own text, not only JSON (design § 4.1, *custom*). A step
    after another is handed what that step made, so plain text is its
    `result`; a step handed only ids and names (the first step here: an
    `email_received`) is asked for JSON with its own fields, named — never
    given a field it does not read."""
    res = _test(client, wf, DOC["nodes"][1], source="custom", input="Three mails, one urgent.")
    assert res.status_code == 200, res.text
    assert sched.tests[-1]["input"]["data"]["result"] == "Three mails, one urgent."
    as_json = _test(client, wf, DOC["nodes"][1], source="custom",
                    input=json.dumps({"result": "From JSON.", "status": "success"}))
    assert sched.tests[-1]["input"]["data"]["result"] == "From JSON."
    assert as_json.json()["dropped"] == []
    first = _test(client, wf, DOC["nodes"][0], source="custom", input="Three mails.")
    assert first.status_code == 400
    assert first.json()["detail"] == (
        "“Summarise my inbox” is handed account, folder, message_key. Paste the sample as JSON "
        "with those fields, for example {\"account\": \"…\"}.")
    assert len(sched.tests) == 2


def test_a_sample_the_engine_will_not_take_is_refused_in_its_words(client, wf_db):
    """`build_pin`'s refusals (`C1`) are a 400 with the engine's sentence and
    reason — at the pin door and the test door alike — never a 500: a sample
    on a first step that is handed nothing, and one that is not an object."""
    plain = save(client, new(client, "On a schedule"), graph([step("n1"), step("n2")],
                                                             [("n1", "success", "n2")]))
    plain = plain.json()["workflow"]
    url = f"/api/workflows/{plain['id']}"
    unused = call(client, "PUT", url, json={"pins": {"n1": {"result": "x"}}})
    assert unused.status_code == 400, unused.text
    assert unused.json()["reason"] == "pin_unused" and unused.json()["node_ids"] == ["n1"]
    not_an_object = call(client, "PUT", url, json={"pins": {"n2": ["a", "list"]}})
    assert not_an_object.status_code == 400 and not_an_object.json()["reason"] == "bad_pin"
    tested = _test(client, plain, step("n1"), source="custom", input='{"result": "x"}')
    assert tested.status_code == 400 and tested.json()["reason"] == "pin_unused"
    assert all(n["pinned"] is None for n in json.loads(
        rows(wf_db, wc.models()[0], id=plain["id"])[0].graph)["nodes"])
