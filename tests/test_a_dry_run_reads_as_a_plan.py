# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P23-05` — a dry run reads as a plan, in words a person uses.

Three findings of the audit (`Doc1-Mechanism-report.md`, `Doc2-UIUX-audit.md`
§ 5 *Workbench and Tasks*), all on the one plan a dry run writes:

* **WB-M-12.** Tasks › Activity listed a dry run as *skipped* with *Run again*
  — a plan is not a run that was skipped, and *Run again* on it runs the task
  for real. The row now says the plan's own first words (*Dry run — …*) and
  offers no *Run again*; a row that really was skipped reads as before.
* **WB-M-11.** The plan printed the model's endpoint URL (*Model: scripted-demo
  at http://127.0.0.1:41521/v1/chat/completions*) and called a workflow step
  "this task". The model is named, never its address, and a step is a step.
* **COPY-M-13.** *Where the result would go: session* printed a stored key as a
  place. It reads *Result goes to: a chat* (*your email*, *a document*).

Driven: `dry_run_plan` and `dry_run_lines` in Python, and the real
`_runToActivityEntry` / `_renderActivityEntry` in the Tasks sandbox the
Activity row's other cases use (`Law 14`), on the result the scheduler writes.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_the_palette_moves_to_the_server_js import tasks_sandbox, _tasks  # noqa: E402,F401

_needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _task(**kw):
    base = dict(task_type="llm", action=None, prompt="Summarise my inbox", owner="alice",
                model="scripted-demo", endpoint_url="http://127.0.0.1:41521/v1/chat/completions",
                output_target="session", status="active", schedule=None, trigger_type="schedule")
    base.update(kw)
    return SimpleNamespace(**base)


# ── the plan's words ──────────────────────────────────────────────────────────


def test_a_plan_names_the_model_and_never_its_address():
    from src.builtin_actions import dry_run_plan
    lines = dry_run_plan(task_type="llm", action=None, prompt="x", model="scripted-demo",
                         endpoint_url="http://127.0.0.1:41521/v1/chat/completions")
    assert "Model: scripted-demo" in lines
    assert not [ln for ln in lines if "http" in ln], lines
    bare = dry_run_plan(task_type="llm", action=None, prompt="x",
                        endpoint_url="http://10.0.0.5:8000/v1")
    assert "Model: the default." in bare and not [ln for ln in bare if "http" in ln], bare


def test_a_workflow_step_is_called_a_step():
    from src.builtin_actions import dry_run_plan
    from src.workflow_document import plan_lines
    assert "Would send this task's prompt to a model, with tools." in dry_run_plan(
        task_type="llm", action=None, prompt="x")
    lines = plan_lines({"id": "n1", "kind": "llm", "label": "Summarise",
                        "config": {"prompt": "Summarise it"}})
    assert "Would send this step's prompt to a model, with tools." in lines, lines
    assert not [ln for ln in lines if "this task" in ln], lines


@pytest.mark.parametrize("target,place", [
    ("session", "a chat"), (None, "a chat"), ("email", "your email"),
    ("document", "a document"), ("mcp__slack__send_message", "the tool slack › send_message"),
])
def test_the_result_goes_to_a_place_not_a_key(target, place):
    from src.task_scheduler import DRY_RUN_HEADLINE, dry_run_lines
    lines = dry_run_lines(_task(output_target=target))
    assert lines[0] == DRY_RUN_HEADLINE
    assert f"Result goes to: {place}" in lines
    assert not [ln for ln in lines if "would go: session" in ln]


# ── the Activity row ─────────────────────────────────────────────────────────


def _rows(sandbox, runs):
    out = _tasks(sandbox, """
        const runs = %s;
        console.log(JSON.stringify({ rows: runs.map((r) => __t._renderActivityEntry(__t._runToActivityEntry(r))) }));
    """ % json.dumps(runs))
    return out["rows"]


def _reason(row: str):
    m = re.search(r'<span class="task-log-skipped-reason">(.*?)</span>', row, re.S)
    return html.unescape(m.group(1)) if m else None


def _run(status, **kw):
    return {"task_id": "t1", "task_name": "Morning inbox brief", "task_type": "llm", "status": status,
            "started_at": "2026-10-01T09:00:00Z", "finished_at": "2026-10-01T09:00:03Z", **kw}


@_needs_node
def test_activity_says_dry_run_and_offers_no_run_again(tasks_sandbox):
    from src.task_scheduler import dry_run_lines
    plan = "\n".join(dry_run_lines(_task()))
    dry, skipped = _rows(tasks_sandbox, [_run("skipped", result=plan),
                                         _run("skipped", result="no pings due")])
    assert _reason(dry).startswith("Dry run — nothing ran"), _reason(dry)
    assert not _reason(dry).startswith("skipped"), "a plan is not a skipped run"
    assert "task-log-run-again" not in dry, "Run again on a plan would run the task for real"
    # A row that really was skipped is drawn as before (`Law 1`).
    assert _reason(skipped) == "skipped — no pings due"
    assert "task-log-run-again" in skipped


# ── WB-U-11: a schedule as a person says it ──────────────────────────────────


@_needs_node
def test_a_tasks_card_says_its_schedule_in_words(tasks_sandbox):
    """The built-in cards read *Cron: 0 */2 * * ** and *Every 5 × session
    created*. The housekeeping schedules (`task_scheduler.HOUSEKEEPING_DEFAULTS`)
    are read out of the registry, not typed again, and every one reads as words;
    a shape with no words is shown as written (`Law 1`)."""
    from src.task_scheduler import HOUSEKEEPING_DEFAULTS
    crons = sorted({d["cron_expression"] for d in HOUSEKEEPING_DEFAULTS.values()
                    if d.get("schedule") == "cron"})
    cases = [{"trigger_type": "schedule", "schedule": "cron", "cron_expression": c} for c in crons] + [
        {"trigger_type": "event", "trigger_event": "session_created", "trigger_count": 5},
        {"trigger_type": "event", "trigger_event": "document_created", "trigger_count": 5},
        {"trigger_type": "event", "trigger_event": "memory_added", "trigger_count": 1},
        {"trigger_type": "event", "trigger_event": "something_new", "trigger_count": 3},
        {"trigger_type": "schedule", "schedule": "cron", "cron_expression": "0 9 * * 1-5"},
        {"trigger_type": "schedule", "schedule": "cron", "cron_expression": "15 3 1 * *"},
    ]
    out = _tasks(tasks_sandbox, """
        console.log(JSON.stringify({ labels: %s.map((t) => __t._scheduleLabel(t)) }));
    """ % json.dumps(cases))
    said = dict(zip([c.get("cron_expression") or f"{c['trigger_event']}x{c['trigger_count']}" for c in cases],
                    out["labels"]))
    assert said["0 */2 * * *"] == "Every 2 hours"
    assert said["0 6,18 * * *"] == "At 06:00 and 18:00"
    assert said["0 * * * *"] == "Every hour"
    assert not [c for c in crons if said[c].startswith("Cron:")], said
    assert said["session_createdx5"] == "Every 5 new chats"
    assert said["document_createdx5"] == "Every 5 new documents"
    assert said["memory_addedx1"] == "Every new memory"
    assert said["something_newx3"] == "Every 3 something new"
    assert said["0 9 * * 1-5"] == "Weekdays at 09:00"
    assert said["15 3 1 * *"] == "Cron: 15 3 1 * *", "a shape with no words is shown as written"
