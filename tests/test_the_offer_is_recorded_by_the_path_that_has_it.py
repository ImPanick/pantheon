# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-08` — the run receipt's tool list, and the bias a live deployment exposed.

`P17-06` asked for a gap analysis *"derived from what the agent is actually
asked to do rather than from imagination"*. `P17-07` built the instrumentation.
Running it against the owner's deployment found a latent bug in it — and the
first explanation of that bug was wrong, which is the more useful half.

`_capture_run_config` has three call sites and one latch: first call in a run
wins. Only `stream_llm` passes `tools`. So a turn that makes a non-streaming
call first — tool selection, a preflight, a titler — writes its `run_config`
with no tool list and then suppresses the one that has it. That much is
readable in the source and is what these tests pin.

**WHAT IT IS NOT IS THE EXPLANATION FOR THE ODD NUMBER THAT LED HERE.**
`create_document` was called nineteen times while appearing in one offer
fingerprint, and I wrote that the latch was why. Measuring it said otherwise:
39 of 40 runs recorded a tool list. The real cause is the fenced tool channel,
which `run_config` does not describe at all (`P17-12`). The bug is real,
reachable and unproven in the wild — fixed because the cost is one ContextVar
and the failure mode is a receipt that quietly under-reports, not because the
data showed it happening.

The fix is one more ContextVar rather than a schema, because `events.receipt()`
already orders by timestamp and takes the **last** `run_config` for a run — so
a second, richer row supersedes the first with no reader change.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import events as ev  # noqa: E402
from src import llm_core as lc  # noqa: E402

TOOLS = [
    {"type": "function", "function": {"name": "web_search", "parameters": {}}},
    {"type": "function", "function": {"name": "create_document", "parameters": {}}},
]


@pytest.fixture()
def captured(monkeypatch):
    """Collect `record_run_config` calls instead of writing rows."""
    calls = []

    def _record(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(ev, "record_run_config", _record)
    monkeypatch.setattr(ev, "current_run_id", lambda: "run-1")
    lc._run_config_recorded.set(False)
    lc._run_config_had_tools.set(False)
    yield calls
    lc._run_config_recorded.set(False)
    lc._run_config_had_tools.set(False)


def _names(call):
    return [t["name"] for t in ev._tool_fingerprints(call.get("tools") or [])]


# --------------------------------------------------------------------------
# The defect, in the order it actually happens
# --------------------------------------------------------------------------


def test_a_toolless_call_first_no_longer_swallows_the_tool_list(captured):
    """The exact sequence a real turn takes, and the one that was losing.

    `llm_call_async` runs first for tool selection and passes no tools;
    `stream_llm` runs second and has them. Before this, the first call took the
    latch and the tool list was never recorded for that run.
    """
    lc._capture_run_config(0.7, 100, "s1")
    lc._capture_run_config(0.7, 100, "s1", tools=TOOLS)
    assert len(captured) == 2, "the tools-bearing capture was suppressed"
    assert captured[0].get("tools") is None
    assert _names(captured[1]) == ["create_document", "web_search"]


def test_the_upgrade_happens_exactly_once(captured):
    """A ten-round stream must not write ten rows (`P4-25`)."""
    lc._capture_run_config(0.7, 100, "s1")
    for _ in range(10):
        lc._capture_run_config(0.7, 100, "s1", tools=TOOLS)
    assert len(captured) == 2


def test_a_toolless_capture_after_a_tooled_one_is_still_suppressed(captured):
    """The other order. A later tools-less call must not overwrite the list.

    `receipt()` takes the last `run_config` row, so letting this through would
    blank a tool list that had already been recorded correctly — turning the
    fix into the same defect pointing the other way.
    """
    lc._capture_run_config(0.7, 100, "s1", tools=TOOLS)
    lc._capture_run_config(0.7, 100, "s1")
    lc._capture_run_config(0.7, 100, "s1")
    assert len(captured) == 1
    assert _names(captured[0]) == ["create_document", "web_search"]


def test_repeated_toolless_calls_still_write_once(captured):
    lc._capture_run_config(0.7, 100, "s1")
    lc._capture_run_config(0.7, 100, "s1")
    lc._capture_run_config(0.7, 100, "s1")
    assert len(captured) == 1


def test_an_empty_tool_list_is_not_an_upgrade(captured):
    """`tools=[]` means *this path sends no tools*, which the first row said.

    Distinct from `tools=None` — "none were sent" and "we did not look" are
    different facts — but neither is new information once a row exists.
    """
    lc._capture_run_config(0.7, 100, "s1")
    lc._capture_run_config(0.7, 100, "s1", tools=[])
    assert len(captured) == 1


def test_no_run_id_means_no_row(captured, monkeypatch):
    monkeypatch.setattr(ev, "current_run_id", lambda: None)
    lc._capture_run_config(0.7, 100, "s1", tools=TOOLS)
    assert captured == []


# --------------------------------------------------------------------------
# The reader, which is why one more row is safe
# --------------------------------------------------------------------------


def test_the_receipt_takes_the_last_run_config_for_a_run(monkeypatch):
    """The whole reason this fix is a ContextVar and not a schema change.

    Run against the real assembler with two rows in a real table, not read out
    of the source: descending order or a list instead of an assignment would
    each break the supersede, and only one of those is visible in a grep.
    """
    import datetime as _dt
    import json

    from core.database import Base, Event
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine)
    db = Factory()
    base = _dt.datetime(2026, 9, 13, 12, 0, 0)
    db.add(Event(kind="run_config", run_id="r1", ts=base,
                 detail=json.dumps({"sampling": {"temperature": 0.7}})))
    db.add(Event(kind="run_config", run_id="r1", ts=base + _dt.timedelta(seconds=1),
                 detail=json.dumps({"sampling": {"temperature": 0.7},
                                    "tools": [{"name": "web_search", "sha": "abc"}]})))
    db.commit()
    db.close()

    monkeypatch.setattr("core.database.SessionLocal", Factory)
    config = ev.receipt("r1")["config"]
    assert config is not None
    assert [t["name"] for t in config.get("tools", [])] == ["web_search"], (
        "the richer row must supersede the one written first"
    )


def test_the_once_per_turn_guard_is_still_a_contextvar():
    """`P4-25`. A module global would let one turn suppress another's receipt."""
    source = (ROOT / "src" / "llm_core.py").read_text(encoding="utf-8")
    for name in ("_run_config_recorded", "_run_config_had_tools"):
        i = source.index(name)
        assert "ContextVar" in source[i:i + 400], name


# --------------------------------------------------------------------------
# The analysis that found it
# --------------------------------------------------------------------------


def test_the_gap_analysis_refuses_to_open_a_database_read_write():
    """It is pointed at a copy of a live file that another process is writing."""
    source = (ROOT / ".pantheon" / "gap-analysis.py").read_text(encoding="utf-8")
    assert "mode=ro" in source
    assert "uri=True" in source


def test_the_gap_analysis_prints_no_message_content():
    """Every figure is a count or a name, so the report can be argued with."""
    source = (ROOT / ".pantheon" / "gap-analysis.py").read_text(encoding="utf-8")
    assert "select content from" not in source
    assert "role='user'" not in source or "count(*)" in source


def test_the_gap_analysis_says_what_it_cannot_see():
    """A tool never offered leaves no row. A limitation stated is not a silent one."""
    source = (ROOT / ".pantheon" / "gap-analysis.py").read_text(encoding="utf-8")
    assert "never offered" in source
