# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1062` — Activity's row for a stopped run says it stopped, and why.

**Measured by `wb-runs` in Chromium on 2026-10-01** (`/tmp/scratch-wb-runs/
shots/*-04-activity.png`): the pre-empted *Webhook digest* row read only its
name and "just now". A skipped row says "skipped — <why>" and a failed one
"(failed)"; a stopped (`aborted`) run's reason — "Paused because Pantheon
became active", "Stopped by user" — was in the row's body, which a compact row
does not show, one click away in History.

**Now** the row's head says it, from the text History shows for the run
(`result`, else `error`, which `_runToActivityEntry` already carries), in
`runStatus.js`'s word for the status: "stopped — Paused because Pantheon became
active"; a reason that already says it stopped is said alone ("Stopped by
user"); a run that left no reason says so rather than nothing. Every other row
is drawn as before (`Law 1`).

Driven: the real `_runToActivityEntry` and `_renderActivityEntry` in the Tasks
sandbox the Activity row's other cases use (`Law 14`), on the run rows the
scheduler writes — its own two stop sentences, imported, not typed again.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

from test_the_palette_moves_to_the_server_js import tasks_sandbox, _tasks  # noqa: E402,F401


def _rows(sandbox, runs):
    out = _tasks(sandbox, """
        const runs = %s;
        console.log(JSON.stringify({ rows: runs.map((r) => __t._renderActivityEntry(__t._runToActivityEntry(r))) }));
    """ % json.dumps(runs))
    return out["rows"]


def _head(row: str) -> str:
    """The row's head — what a compact row shows — as markup."""
    return row.split('class="task-log-row-body"')[0]


def _stopped(row: str):
    m = re.search(r'<span class="task-log-stopped-reason">(.*?)</span>', _head(row), re.S)
    return html.unescape(m.group(1)) if m else None


def _run(status, **kw):
    return {"task_id": "t1", "task_name": "Webhook digest", "task_type": "llm", "status": status,
            "started_at": "2026-10-01T09:00:00Z", "finished_at": "2026-10-01T09:00:03Z", **kw}


def test_a_pre_empted_run_says_it_stopped_and_why(tasks_sandbox):
    from src.task_scheduler import FOREGROUND_TAKEOVER
    (row,) = _rows(tasks_sandbox, [_run("aborted", error=FOREGROUND_TAKEOVER)])
    assert _stopped(row) == f"stopped — {FOREGROUND_TAKEOVER}"
    head = _head(row)
    assert head.index("task-log-name") < head.index("task-log-stopped-reason") < head.index("task-log-time"), \
        "beside the name, before the time — where a skipped row says why"


def test_a_reason_that_says_it_stopped_is_said_once(tasks_sandbox):
    from src.task_scheduler import STOPPED_BY_USER
    (row,) = _rows(tasks_sandbox, [_run("aborted", result=STOPPED_BY_USER)])
    assert _stopped(row) == STOPPED_BY_USER


def test_a_stopped_run_with_no_reason_says_so(tasks_sandbox):
    (row,) = _rows(tasks_sandbox, [_run("aborted")])
    assert _stopped(row) == "stopped — no reason was recorded"


def test_the_reason_is_text_and_its_first_line(tasks_sandbox):
    hostile = '<img src=x onerror="alert(1)"> took too long\nTraceback (most recent call last):'
    (row,) = _rows(tasks_sandbox, [_run("aborted", error=hostile)])
    assert "<img" not in _head(row)
    assert _stopped(row) == 'stopped — <img src=x onerror="alert(1)"> took too long'


def test_every_other_row_is_drawn_as_before(tasks_sandbox):
    rows = _rows(tasks_sandbox, [
        _run("success", result="Done"), _run("error", error="RuntimeError: boom"),
        _run("skipped", result="no pings due"), _run("running"), _run("queued"),
    ])
    assert [_stopped(r) for r in rows] == [None] * 5
    assert "(failed)" in _head(rows[1]) and "skipped — no pings due" in rows[2]
