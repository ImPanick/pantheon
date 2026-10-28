# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-27` — a promised file is delivered only when this run wrote it.

Found bringing Dashboard Builder to the bar. A `document` deliverable counts
only a document written since the run began (`since`); a `file` deliverable
counted any file at its path. So a run that rightly wrote nothing — the
person's own `dashboard/index.html` was there, and the runbook says never to
overwrite it — was recorded as having delivered the dashboard, and a run that
wrote nothing at all passed whenever last week's file was still there.

Now, when the run's start is known, the file must have been written since it
began (the same five seconds' grace a document has); without a start — a
runbook's example checked on its own — the path is enough, as before.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

from src.agents import evals as E
from src.agents import runtime as R
from src.agents.catalogue import get_agent


def _plan(rel="dashboard/index.html", words=()):
    return R.RunPlan(hire_id="", agent_id="x", name="X", system_prompt="", tools=[], ask_effects=frozenset(),
                     never_effects=frozenset(), owner="alice",
                     delivers=({"kind": "file", "title": rel, "must_contain": list(words)},))


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_a_file_from_before_the_run_is_not_its_delivery(monkeypatch, tmp_path):
    import src.tool_execution as te
    monkeypatch.setattr(te, "projects_root", lambda owner, create=False: str(tmp_path))
    page = tmp_path / "dashboard" / "index.html"
    page.parent.mkdir()
    page.write_text("<h1>Ana's own page</h1>")
    old = time.time() - 3600
    os.utime(page, (old, old))
    (check,) = R.check_contract(None, _plan(), "", [], since=_now())
    assert check["ok"] is False, check
    assert check["detail"] == "dashboard/index.html was not written in this run.", check
    # Written during the run: delivered.
    page.write_text("<h1>Sales</h1>")
    (check,) = R.check_contract(None, _plan(words=["Sales"]), "", [], since=_now() - timedelta(seconds=30))
    assert check["ok"] is True, check


def test_without_a_start_the_path_is_enough(monkeypatch, tmp_path):
    """A runbook's example, checked on its own, has no run: as before."""
    import src.tool_execution as te
    monkeypatch.setattr(te, "projects_root", lambda owner, create=False: str(tmp_path))
    (tmp_path / "index.html").write_text("<h1>Hello</h1>")
    old = time.time() - 3600
    os.utime(tmp_path / "index.html", (old, old))
    (check,) = R.check_contract(None, _plan("index.html", ["Hello"]), "", [])
    assert check["ok"] is True, check


def test_a_run_that_writes_nothing_does_not_deliver_a_file_already_there():
    """Through the real harness and the real scheduler: the person's page is
    in the world before the run, the agent rightly leaves it alone — and the
    run must not be recorded as having written the dashboard."""
    m = get_agent(None, "dashboard-builder")
    said = ("**Dashboard**\n- not written: dashboard/index.html is yours\n\n**Answered**\n- nothing\n\n"
            "**Could not answer**\n- all: the page was not written\n\n## Report\n- wrote nothing")
    case = {"id": "a-page-already-there", "inputs": {"file": "shop/sales.csv", "questions": "Sales by month?"},
            "world": {"files": {"dashboard/index.html": "<html><body>Ana's own page</body></html>"}},
            "script": [{"call": [["read_file", {"path": "dashboard/index.html"}]]}, {"say": said}, {"say": said}],
            "checks": [{"not_called": "write_file"}]}
    (r,) = asyncio.run(E.run_agent(m, cases=[case]))
    assert r.status == "error", (r.status, r.report)
    assert any("was not written in this run" in (c.get("detail") or "") for c in r.report["checks"]), r.report["checks"]
