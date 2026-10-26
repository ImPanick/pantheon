# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1096` — *What it was handed*, between two steps of a workflow, says where
it came from and what it said, in words; a failed action's sentence carries
no stream label.

**Measured before this file** (`integrate-c`, drive run 5, and here through
the real walker): the second step's *What it was handed* read "Continued from
Summarise my inbox — task=Summarise my inbox, task_id=e7d344c8-…,
run_id=dda70f7a-…, status=success, result=Five things in your inbox this
morning: …" — `trigger_summary` printing the hand-off envelope's keys, two of
them internal ids, and calling a step a task. A failed `run_local` step whose
command wrote only to stderr made the run say "“Copy to the shared drive”
failed: STDERR: The shared drive … is not mounted."

Driven (`Law 20`): the real scheduler walks a real workflow on a real SQLite
file (the model is the harness's recorder), the real `_run_subprocess` runs a
real shell command, and what is asserted is what the Runs view reads
(`input_summary`) and the run's `error`.
"""
from __future__ import annotations

import asyncio
import shutil

import pytest

from tests.helpers.walker_harness import (
    arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow,
)

from src import workflow_runs as wr  # noqa: E402
from src.builtin_actions import NodeResult, _run_subprocess, failure_words  # noqa: E402
from src.event_bus import build_task_handoff, trigger_summary  # noqa: E402

SAID = "Five things in your inbox this morning: two bills, a letter from Ana."
DRIVE = "The shared drive /mnt/team is not mounted."


def _handoff(status="success", result=SAID, payload=None):
    return build_task_handoff(task_name="Summarise my inbox", task_id="e7d344c8-0000",
                              run_id="dda70f7a-0000", status=status, result=result,
                              payload=payload)


def test_a_hand_off_says_where_it_came_from_and_what_it_said_with_no_ids():
    line = trigger_summary(_handoff())
    assert line == f"From “Summarise my inbox” (it worked): {SAID}"
    for internal in ("task_id", "run_id", "e7d344c8", "dda70f7a", "task=", "status="):
        assert internal not in line, f"{internal!r} is not for a person: {line}"


def test_a_failed_step_s_hand_off_says_it_failed():
    assert trigger_summary(_handoff(status="error", result=DRIVE)) == (
        f"From “Summarise my inbox” (it failed): {DRIVE}")


def test_the_data_is_still_under_it():
    """The line is for a person; the envelope a panel shows under it, and a
    reference reads, keeps every field."""
    envelope = _handoff(payload={"bills": 2})
    assert envelope["data"] == {"task": "Summarise my inbox", "task_id": "e7d344c8-0000",
                                "run_id": "dda70f7a-0000", "status": "success",
                                "result": SAID, "data": {"bills": 2}}


def test_a_hand_off_with_only_data_says_the_data():
    line = trigger_summary(_handoff(result="", payload={"bills": 2}))
    assert line == 'From “Summarise my inbox” (it worked): {"bills": 2}'


@pytest.mark.skipif(not shutil.which("bash"), reason="needs a shell")
def test_a_command_that_failed_on_stderr_alone_says_the_error_without_a_label():
    out, ok = asyncio.run(_run_subprocess(["bash", "-c", f"echo '{DRIVE}' >&2; exit 1"]))
    assert (out, ok) == (DRIVE, False)


@pytest.mark.skipif(not shutil.which("bash"), reason="needs a shell")
def test_a_command_that_printed_both_keeps_both_and_its_sentence_says_the_error():
    out, ok = asyncio.run(_run_subprocess(
        ["bash", "-c", f"echo 'copying 3 files'; echo '{DRIVE}' >&2; exit 1"]))
    assert not ok
    assert out == f"copying 3 files\nSTDERR: {DRIVE}", "the raw output keeps both streams"
    assert failure_words(out) == DRIVE


@pytest.mark.asyncio
async def test_a_step_s_what_it_was_handed_and_the_run_s_failure_read_like_words(
        monkeypatch, tmp_path):
    factory = make_db(monkeypatch, tmp_path / "handed.db")
    seed_workflow(factory, [
        node("n1", "Summarise my inbox"),
        node("n2", "Copy to the shared drive", "action", action="run_local",
             prompt="cp summary.txt /mnt/team/"),
    ], [arrow("n1", "n2")], owner="root")   # `run_local` is an admin's action
    # What `run_local` answers when the drive is missing, made by the real
    # runner — the step's far end is the only thing recorded.
    failed, _ = await _run_subprocess(
        ["bash", "-c", f"echo 'copying 1 file'; echo '{DRIVE}' >&2; exit 1"])
    s = recording_scheduler({
        "Morning digest · Summarise my inbox": SAID,
        "Morning digest · Copy to the shared drive": NodeResult("error", payload=failed),
    })
    await s._execute_task("wf")

    [run] = runs_of(factory, "wf")
    assert run["status"] == "error"
    assert run["error"] == f"“Copy to the shared drive” failed: {DRIVE}"
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["n2"]["input_summary"] == f"From “Summarise my inbox” (it worked): {SAID}"
    assert by["n2"]["input"]["data"]["run_id"], "the ids are still in the data under it"
    # The step's own output keeps both streams (it is raw output).
    assert "STDERR:" in by["n2"]["output"]["text"]
    # The Runs view's own words for a stored record are the same line.
    assert wr.input_summary(by["n2"]["input"]) == by["n2"]["input_summary"]
