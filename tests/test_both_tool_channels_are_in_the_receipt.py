# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-12` — there are two tool channels and the receipt described one.

`P17-08` ran the gap analysis against the owner's deployment and found the
number that opened this row: **`create_document` was called 19 times and in 17
of them was not in its own run's recorded offer**, against **0** mismatches for
every other called tool.

It is not a bug in the caller. `src/agent_loop.py` documents a **fenced tool
channel** — the agent writes a ```` ```create_document ```` block and
`execute_tool_block` runs it — alongside the function-calling channel, and
`_capture_run_config` fingerprints only the schemas. So
`run_config.detail.tools` answers *what schemas were sent* and is read as *what
the agent could do*, and those are different questions. `B66` already proved
that distinction expensive once: the prompt ordered the agent to use
`manage_rag` while the fence parser dropped every call with no error at all.

**THE CONSEQUENCE IS THAT NO GAP ANALYSIS BUILT ON THE OFFER COLUMN CAN BE
COMPLETE.** A tool reachable only by fence is neither offered nor missing. It
sits in neither column, and the most-used tool on the deployment was sitting
there.

Two things landed with it, both found by writing this down:

  * **`receipt()` replaced instead of merging.** A run writes its config from
    more than one place, because each field is captured where it is resolved —
    sampling and schemas inside `stream_llm`, skills and now the fenced list in
    the prompt builder. Assigning meant the last row won and every field only
    an earlier row carried vanished. A turn that injected skills *and* sent
    schemas could show one or the other, never both.
  * **An empty fenced list is a fact, not a blank.** The compact prompt tells
    the model *"do not write tool syntax in chat"*, so the channel is shut —
    which is a different thing from nobody having looked.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import agent_loop as al  # noqa: E402
from src import events as ev  # noqa: E402


def _db(monkeypatch):
    from core.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine)
    monkeypatch.setattr("core.database.SessionLocal", Factory)
    return Factory


# --------------------------------------------------------------------------
# The set itself
# --------------------------------------------------------------------------


def test_the_fenced_set_is_the_tools_the_prompt_names():
    every = set(al.TOOL_SECTIONS)
    fenced = al.fenced_tool_names(every)
    assert fenced, "the fenced channel is not empty on a full prompt"
    assert fenced <= every
    assert "create_document" in fenced, (
        "the tool that opened this row must be in the channel it arrived through"
    )


def test_a_disabled_tool_is_not_reachable_by_fence():
    """The disabled list closes both channels or it closes neither."""
    every = set(al.TOOL_SECTIONS)
    assert "bash" in al.fenced_tool_names(every)
    assert "bash" not in al.fenced_tool_names(every, {"bash"})


def test_the_compact_prompt_shuts_the_channel_and_says_so():
    """`H09`'s prompt: *only the tool schemas provided by the API are available…
    do not write tool syntax or tool instructions in chat.*

    Empty is the answer, not a gap — and it is recorded as `[]` rather than
    omitted, because a turn where one channel was deliberately closed is a
    different fact from one where nobody looked.
    """
    assert al.fenced_tool_names(set(al.TOOL_SECTIONS), compact=True) == frozenset()


def test_the_prompt_and_the_receipt_read_the_same_set():
    """`Law 13`. A receipt that disagrees with the prompt is worse than none.

    Behavioural rather than a grep: the prompt is built and every name the
    fenced set claims must appear in it as a tool section, and the whole point
    of the row is that these two answers were allowed to differ.
    """
    every = set(al.TOOL_SECTIONS)
    disabled = {"bash", "python"}
    prompt = al._assemble_prompt(every, disabled)
    fenced = al.fenced_tool_names(every, disabled)
    # Names that are actually in `TOOL_SECTIONS` — the fenced channel is
    # exactly that table, and `ls`/`grep` are schema-only tools with no prompt
    # section, which is the first thing this test taught me about the split.
    for name in ("create_document", "read_file", "web_fetch"):
        assert name in fenced
        assert name in prompt
    for name in disabled:
        assert name not in fenced


def test_narrowing_the_fenced_set_narrows_the_prompt(monkeypatch):
    """The coupling, not the value — and a mutation run is why this exists.

    Replacing the shared read with the inline expression it came from survived
    every other test in this file, because the two compute the same set today.
    That is not evidence the sharing is pointless; it is evidence the other
    tests pin the *value* and nothing pinned the *link*. A future narrowing of
    `fenced_tool_names` — a tool excluded from the channel for any reason —
    must reach the prompt, or the receipt starts describing a channel the
    prompt does not offer, which is this row's own defect pointing the other
    way.
    """
    every = set(al.TOOL_SECTIONS)
    monkeypatch.setattr(al, "fenced_tool_names",
                        lambda *a, **k: frozenset({"create_document"}))
    prompt = al._assemble_prompt(every, set())
    assert "create_document" in prompt
    for name in ("web_fetch", "web_search", "read_file"):
        assert name in every
        assert f"```{name}" not in prompt, (
            f"{name} is still rendered after the fenced set excluded it"
        )


# --------------------------------------------------------------------------
# What reaches the row
# --------------------------------------------------------------------------


def test_the_fenced_list_is_names_and_nothing_else(monkeypatch):
    """No schema to hash — a fenced tool is reached by writing its name."""
    written = []
    monkeypatch.setattr(ev, "record_event", lambda *a, **k: written.append(k) or True)
    ev.record_run_config(fenced=["b", "a", "a", ""])
    detail = written[0]["detail"]
    assert detail["fenced"] == ["a", "b"], "sorted and de-duplicated"


def test_an_empty_fenced_list_is_written_and_absent_is_not(monkeypatch):
    written = []
    monkeypatch.setattr(ev, "record_event", lambda *a, **k: written.append(k) or True)
    ev.record_run_config(fenced=[], sampling={"temperature": 0.1})
    assert written[0]["detail"]["fenced"] == []
    written.clear()
    ev.record_run_config(sampling={"temperature": 0.1})
    assert "fenced" not in written[0]["detail"]


def test_recording_the_channel_never_fails_a_run(monkeypatch):
    """Guarded, like every other capture. `P4-25`'s rule."""
    def _boom(**kwargs):
        raise RuntimeError("events table is gone")

    monkeypatch.setattr(ev, "record_run_config", _boom)
    al._record_fenced_channel(set(al.TOOL_SECTIONS), set(), False, "alice")


# --------------------------------------------------------------------------
# The receipt, which was losing half of what it was told
# --------------------------------------------------------------------------


def test_the_receipt_merges_the_two_halves_of_one_config(monkeypatch):
    """The loss, in the order it actually happened.

    The prompt builder writes skills and the fenced list; `stream_llm` writes
    sampling and the schemas. Both are `run_config` rows for one run, and the
    receipt used to keep whichever landed last.
    """
    from core.database import Event

    Factory = _db(monkeypatch)
    base = datetime.datetime(2026, 9, 13, 12, 0, 0)
    db = Factory()
    db.add(Event(kind="run_config", run_id="r1", ts=base,
                 detail=json.dumps({"fenced": ["create_document"],
                                    "skills": [{"name": "s", "confidence": 1, "source": "x"}]})))
    db.add(Event(kind="run_config", run_id="r1", ts=base + datetime.timedelta(seconds=1),
                 detail=json.dumps({"sampling": {"temperature": 0.7},
                                    "tools": [{"name": "web_search", "sha": "a"}]})))
    db.commit()
    db.close()

    config = ev.receipt("r1")["config"]
    assert [t["name"] for t in config["tools"]] == ["web_search"]
    assert config["fenced"] == ["create_document"], (
        "the fenced half was dropped by the row that wrote last"
    )
    assert config["skills"][0]["name"] == "s"
    assert config["sampling"]["temperature"] == 0.7


def test_a_later_row_still_supersedes_the_same_key(monkeypatch):
    """`P17-08`'s upgrade has to keep working through the merge."""
    from core.database import Event

    Factory = _db(monkeypatch)
    base = datetime.datetime(2026, 9, 13, 12, 0, 0)
    db = Factory()
    db.add(Event(kind="run_config", run_id="r2", ts=base,
                 detail=json.dumps({"tools": []})))
    db.add(Event(kind="run_config", run_id="r2", ts=base + datetime.timedelta(seconds=1),
                 detail=json.dumps({"tools": [{"name": "ls", "sha": "b"}]})))
    db.commit()
    db.close()
    assert [t["name"] for t in ev.receipt("r2")["config"]["tools"]] == ["ls"]


def test_a_run_with_one_config_row_is_unchanged(monkeypatch):
    """`Law 1`. The merge must not alter the common case."""
    from core.database import Event

    Factory = _db(monkeypatch)
    db = Factory()
    db.add(Event(kind="run_config", run_id="r3", ts=datetime.datetime(2026, 9, 13, 12, 0, 0),
                 detail=json.dumps({"sampling": {"temperature": 0.2}})))
    db.commit()
    db.close()
    assert ev.receipt("r3")["config"] == {"sampling": {"temperature": 0.2}}


# --------------------------------------------------------------------------
# The analysis, which is what noticed
# --------------------------------------------------------------------------


def _run_analysis(tmp_path, rows):
    import sqlite3
    import subprocess

    path = tmp_path / "snap.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "create table events (id integer primary key, ts timestamp, kind text, "
        "session_id text, run_id text, owner text, name text, model text, "
        "endpoint text, input_tokens int, output_tokens int, duration_ms int, "
        "outcome text, detail text);"
        "create table sessions (id text primary key, message_count int);"
        "create table chat_messages (id integer primary key, role text, "
        "content text, metadata text);"
    )
    for row in rows:
        conn.execute(
            "insert into events (ts,kind,run_id,name,outcome,detail) values (?,?,?,?,?,?)",
            row,
        )
    conn.commit()
    conn.close()
    out = subprocess.run(
        [sys.executable, str(ROOT / ".pantheon" / "gap-analysis.py"), str(path)],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_a_fenced_call_stops_reading_as_called_out_of_nowhere(tmp_path):
    """The column this row exists to empty, for the right reason.

    Before the fenced half was recorded, every fenced call landed in *called
    without being offered* — a real finding the first time and noise forever
    after. A genuinely unoffered call must still land there.
    """
    base = datetime.datetime(2026, 9, 13, 10, 0, 0)
    output = _run_analysis(tmp_path, [
        (base, "run_config", "rA", None, None,
         json.dumps({"fenced": ["create_document"],
                     "tools": [{"name": "read_file", "sha": "a"}]})),
        (base, "tool_call", "rA", "create_document", "ok", None),
        (base, "tool_call", "rA", "read_file", "ok", None),
        (base, "run_config", "rB", None, None, json.dumps({"tools": [], "fenced": []})),
        (base, "tool_call", "rB", "mystery_tool", "ok", None),
    ])
    section = output[output.index("## Called without being offered"):]
    section = section[: section.index("## What the agent")]
    # Only the listed rows, not the prose under them. Written first as a
    # substring check over the whole section, which failed because `ls`
    # appears inside the word "channels" one paragraph down — a test of the
    # right thing, looking in the wrong place.
    listed = {line.split()[0] for line in section.splitlines()
              if line.startswith("   ") and "called" in line}
    assert "mystery_tool" in listed
    assert "create_document" not in listed, (
        "a fenced call is still being reported as unoffered"
    )
    assert "read_file" not in listed


def test_the_two_halves_of_one_run_are_merged_by_the_analysis_too(tmp_path):
    """The script reads a config the way `receipt()` assembles one."""
    base = datetime.datetime(2026, 9, 13, 10, 0, 0)
    output = _run_analysis(tmp_path, [
        (base, "run_config", "rA", None, None, json.dumps({"fenced": ["create_document"]})),
        (base + datetime.timedelta(seconds=1), "run_config", "rA", None, None,
         json.dumps({"tools": [{"name": "ls", "sha": "a"}]})),
        (base, "tool_call", "rA", "create_document", "ok", None),
    ])
    assert "1 runs recorded a config" in output, (
        "two rows for one run were counted as two runs"
    )
    section = output[output.index("## Called without being offered"):]
    section = section[: section.index("## What the agent")]
    listed = {line.split()[0] for line in section.splitlines()
              if line.startswith("   ") and "called" in line}
    assert "create_document" not in listed
