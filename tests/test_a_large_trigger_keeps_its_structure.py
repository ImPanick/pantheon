# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1861` — a webhook's or an event's payload over 2,000 characters stays
structured, and a run that goes on after a Wait still reads all of it.

`build_trigger` clipped every field of the envelope with `clip_field` at
`TRIGGER_FIELD_MAX_CHARS` (2,000) when it BUILT it, so a JSON body over that
reached the run as one truncated string: `{{ steps.start.data.json.issue.title
}}` read null and the run said success. The same clip flattened a step's
structured output in the hand-off to the next step. And a parked run going on
read its trigger back from its first step's record, which keeps the envelope
only up to `workflow_node_record_max_chars` — past it, no trigger at all.

Now the envelope is kept whole up to `trigger_payload_max_chars` (256 KB), the
per-field clip applies only to the text a model is shown (byte-identical to
before), and a workflow run keeps its trigger on its row
(`TaskRun.trigger_envelope`) for the resumed run to read. Driven through the
real webhook route, the real walker, the real sweeper and a second scheduler
over the same SQLite file.
"""

import json
import sqlite3

import pytest

from src import event_bus as bus
from src.event_bus import (
    TASK_HANDOFF_FIELDS, TRIGGER_CUT_KEY, TRIGGER_FIELD_MAX_CHARS, TRIGGER_MAX_CHARS,
    TRIGGER_PAYLOAD_MAX_CHARS_DEFAULT, TRIGGER_PAYLOAD_MAX_CHARS_SETTING,
    TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger, clip_field,
    trigger_as_text, trigger_context_message, trigger_summary,
)
from src.task_scheduler import TaskScheduler
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, records_of, recording_scheduler, runs_of,
    seed_workflow, settle, skip_ahead,
)


def _issue(size: int) -> dict:
    return {"issue": {"title": "Printer on fire", "body": "x" * size, "labels": ["urgent"]}}


def _webhook(body: dict) -> dict:
    text = json.dumps(body)
    return build_trigger(TRIGGER_SOURCE_WEBHOOK, TRIGGER_SOURCE_WEBHOOK,
                         {"body": text, "json": body}, fields=WEBHOOK_PAYLOAD_FIELDS)


def _set_reads_title():
    return node("s1", "Read title", "set",
                fields=[{"name": "title", "value": "{{ steps.start.data.json.issue.title }}"}])


# ── the envelope ───────────────────────────────────────────────────────────

def test_a_json_body_over_the_old_field_clip_stays_a_dict():
    envelope = _webhook(_issue(6000))
    assert isinstance(envelope["data"]["json"], dict), envelope["data"]["json"].__class__
    assert envelope["data"]["json"]["issue"]["title"] == "Printer on fire"
    assert len(envelope["data"]["json"]["issue"]["body"]) == 6000
    assert TRIGGER_CUT_KEY not in envelope


def test_a_steps_structured_output_is_handed_on_structured():
    payload = {"items": [{"n": i, "text": "y" * 40} for i in range(100)]}   # ~5,000 chars
    envelope = bus.build_task_handoff(task_name="Fetch", task_id="t1", run_id="r1",
                                      status="success", result="100 items", payload=payload)
    assert envelope["data"]["data"] == payload
    assert set(envelope["data"]) <= set(TASK_HANDOFF_FIELDS)


def test_text_is_still_stripped_as_the_clip_stripped_it():
    envelope = build_trigger(TRIGGER_SOURCE_WEBHOOK, TRIGGER_SOURCE_WEBHOOK,
                             {"body": "  hello  "}, fields=WEBHOOK_PAYLOAD_FIELDS)
    assert envelope["data"]["body"] == "hello"


def test_over_the_cap_the_text_copy_is_cut_first_and_the_line_says_so(monkeypatch):
    """Past `trigger_payload_max_chars` the envelope keeps what fits: the
    webhook's `body` (its `json` again, as text) is cut to today's field clip,
    the parsed `json` stays whole, and the run's first line names both the cut
    field and the setting."""
    monkeypatch.setattr(bus, "trigger_payload_max_chars", lambda: 20_000)
    envelope = _webhook(_issue(15_000))
    assert envelope[TRIGGER_CUT_KEY] == ["body"]
    assert len(envelope["data"]["body"]) <= TRIGGER_FIELD_MAX_CHARS + 1
    assert envelope["data"]["json"]["issue"]["title"] == "Printer on fire"
    assert len(json.dumps(envelope)) <= 20_000
    line = trigger_summary(envelope)
    assert "body was cut short" in line and TRIGGER_PAYLOAD_MAX_CHARS_SETTING in line


def test_an_envelope_that_fits_has_no_cut_line():
    assert "cut short" not in trigger_summary(_webhook(_issue(6000)))


def test_the_setting_ships_the_default_and_is_held_to_its_range():
    from src import settings
    assert settings.DEFAULT_SETTINGS[TRIGGER_PAYLOAD_MAX_CHARS_SETTING] == TRIGGER_PAYLOAD_MAX_CHARS_DEFAULT
    assert settings.int_setting_ranges()[TRIGGER_PAYLOAD_MAX_CHARS_SETTING] == \
        bus.TRIGGER_PAYLOAD_MAX_CHARS_RANGE
    assert bus.trigger_payload_max_chars() == TRIGGER_PAYLOAD_MAX_CHARS_DEFAULT


# ── what a model is shown: the same bytes as before ────────────────────────

def _as_the_model_was_shown_it_before(envelope: dict) -> str:
    """`trigger_as_text` of the envelope `build_trigger` used to build: every
    field clipped by `clip_field`, then the whole block capped."""
    old = dict(envelope)
    old["data"] = {k: clip_field(v) for k, v in envelope["data"].items()}
    text = json.dumps(old, indent=2, default=str, sort_keys=True)
    if len(text) > TRIGGER_MAX_CHARS:
        text = text[:TRIGGER_MAX_CHARS].rstrip() + "\n… (truncated)"
    return text


@pytest.mark.parametrize("size", [10, 1500, 6000, 40_000])
def test_a_model_is_shown_exactly_what_it_was_shown_before(size):
    envelope = _webhook(_issue(size))
    assert trigger_as_text(envelope) == _as_the_model_was_shown_it_before(envelope)
    message = trigger_context_message(envelope)
    assert message is not None
    # Never more than today's caps, however big the envelope it keeps.
    assert len(trigger_as_text(envelope)) <= TRIGGER_MAX_CHARS + len("\n… (truncated)")


# ── the run ────────────────────────────────────────────────────────────────

@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "big_trigger.db")


@pytest.mark.asyncio
async def test_a_big_webhook_through_the_route_reads_its_title(factory, monkeypatch):
    """Over the old field clip (2,000) and over the route's old body cap
    (8,000, past which the body was not even parsed)."""
    seed_workflow(factory, [_set_reads_title()], [arrow("start", "s1")],
                  trigger_type="webhook", webhook_token="tok")
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/tasks/wf/webhook/tok", json=_issue(20_000))
        assert res.status_code == 200, res.text
    await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    [rec] = records_of(factory, run["id"])
    assert rec["output"]["data"] == {"title": "Printer on fire"}, rec["output"]


@pytest.mark.asyncio
async def test_a_run_that_goes_on_after_a_wait_still_reads_the_whole_trigger(factory, monkeypatch):
    """The trigger is over the step record's cap (16,000), so the first step's
    stored input is a cut marker; the run goes on in a SECOND scheduler over
    the same file, and the step after the Wait still reads the title."""
    seed_workflow(factory, [
        _set_reads_title(),
        node("w", "Wait a minute", "wait", mode="for", minutes=1),
        node("s2", "Read it again", "set",
             fields=[{"name": "again", "value": "{{ steps.start.data.json.issue.title }}"},
                     {"name": "labels", "value": "{{ steps.start.data.json.issue.labels }}"}]),
    ], [arrow("start", "s1"), arrow("s1", "w"), arrow("w", "s2")], trigger_type="webhook")
    first = recording_scheduler()
    await first._execute_task("wf", trigger=_webhook(_issue(30_000)))
    [run] = runs_of(factory, "wf")
    assert run["status"] == "waiting", run
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["s1"]["output"]["data"] == {"title": "Printer on fire"}
    assert by["s1"]["input"].get("truncated") is True, "the record keeps only a preview"

    second = recording_scheduler(scheduler=TaskScheduler(None))
    second._sweep_runs_left_by_a_restart()
    skip_ahead(monkeypatch, 61)
    assert await second._resume_due_waits() == 1
    await settle(second)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["s2"]["output"]["data"] == {"again": "Printer on fire", "labels": ["urgent"]}, \
        by["s2"]["output"]


@pytest.mark.asyncio
async def test_a_prompt_step_after_a_structured_step_is_handed_the_structure(factory):
    items = [{"n": i, "text": "y" * 40} for i in range(100)]
    seed_workflow(factory, [
        node("s1", "Make items", "set", fields=[{"name": "items", "value": items}]),
        node("brief", "Brief me"),
    ], [arrow("start", "s1"), arrow("s1", "brief")])
    s = recording_scheduler()
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    [call] = [c for c in s.calls if c["name"] == "Morning digest · Brief me"]
    assert call["trigger"]["data"]["data"] == {"items": items}


# ── the column, on an install from before it ──────────────────────────────

def test_an_old_task_runs_table_gains_the_column(tmp_path, monkeypatch):
    import core.database as cdb
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE task_runs (id VARCHAR NOT NULL, task_id VARCHAR NOT NULL, "
                 "started_at DATETIME NOT NULL, finished_at DATETIME, status VARCHAR, "
                 "result TEXT, error TEXT, steps TEXT, model TEXT, PRIMARY KEY (id))")
    conn.execute("INSERT INTO task_runs (id, task_id, started_at, status) "
                 "VALUES ('r-old', 't', '2026-01-01 00:00:00', 'success')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    cdb._migrate_add_task_run_trigger_column()
    cdb._migrate_add_task_run_trigger_column()          # a second start is a no-op
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(task_runs)")]
    old = conn.execute("SELECT trigger_envelope FROM task_runs WHERE id = 'r-old'").fetchone()
    conn.close()
    assert cols.count("trigger_envelope") == 1
    assert old == (None,), "a run from before the column keeps no trigger"
