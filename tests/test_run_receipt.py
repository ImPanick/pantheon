"""A receipt per agent run (`P4-25`).

The row's premise was corrected on 2026-08-27: *"all on the wire, none kept" is
wrong in both directions*. Measured again on 2026-09-02, after `P14-01` and
`P14-02` landed, **five of the eight items persist and two more now do** —
approvals and tool outcomes arrived with the loop instrumentation. The remainder
is exactly three:

    resolved sampling parameters · the tool schemas actually sent ·
    which skills were injected, and at what confidence

Between them those are most of the reason two runs of "the same thing" differ,
and none of them was written down anywhere.

**A receipt is a range scan, not a store** (`Law 14`): every row sharing a
`run_id`. `P4-25` adds one row per turn holding the three missing items; the
rest was already being written.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as core_db
from core.database import Base, Event
from src import events as ev

ROOT = Path(__file__).resolve().parent.parent
_maker = None


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/r.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    monkeypatch.setattr(ev, "_last_prune", 0.0)
    ev._turn_started.set(None)
    ev._run_id.set(None)
    global _maker
    _maker = maker
    yield maker
    engine.dispose()


def a_turn():
    ev.mark_turn_start()
    rid = ev.current_run_id()
    ev.record_run_config(
        sampling={"temperature": 0.7, "max_tokens": 4096},
        tools=[{"function": {"name": "shell", "parameters": {"type": "object"}}},
               {"function": {"name": "read_file", "parameters": {}}}],
        skills=[{"name": "deploy-checklist", "confidence": 0.82, "source": "user"}],
        session_id="s1", owner="alice")
    ev.record_llm_round("s1", {"input_tokens": 900, "output_tokens": 120,
                               "model": "qwen", "endpoint_label": "Local"})
    ev.record_event("tool_call", name="shell", outcome="ok", duration_ms=40)
    ev.record_event("tool_call", name="read_file", outcome="error", duration_ms=3)
    ev.record_event("approval", name="shell", outcome="claimed")
    return rid


# --- identity --------------------------------------------------------------

def test_a_turn_gets_one_run_id_and_every_row_carries_it():
    rid = a_turn()
    assert rid
    db = _maker()
    try:
        rows = db.query(Event).all()
        assert len(rows) == 5
        assert all(r.run_id == rid for r in rows), "an event escaped the run"
    finally:
        db.close()


def test_marking_twice_does_not_split_the_receipt():
    """A retry inside one request must not produce two half-receipts."""
    ev.mark_turn_start()
    first = ev.current_run_id()
    ev.mark_turn_start()
    assert ev.current_run_id() == first


def test_two_turns_get_different_ids():
    first = a_turn()
    ev._turn_started.set(None)
    ev._run_id.set(None)
    second = a_turn()
    assert first != second
    assert ev.receipt(first)["totals"]["rounds"] == 1
    assert ev.receipt(second)["totals"]["rounds"] == 1


def test_run_ids_do_not_leak_between_async_turns():
    import asyncio

    async def one(seen, key):
        ev._turn_started.set(None)
        ev._run_id.set(None)
        ev.mark_turn_start()
        await asyncio.sleep(0)
        seen[key] = ev.current_run_id()

    async def main():
        seen = {}
        await asyncio.gather(one(seen, "a"), one(seen, "b"))
        return seen

    seen = asyncio.run(main())
    assert seen["a"] and seen["b"] and seen["a"] != seen["b"]


# --- the three that were missing ------------------------------------------

def test_the_receipt_carries_resolved_sampling_parameters():
    r = ev.receipt(a_turn())
    assert r["config"]["sampling"] == {"temperature": 0.7, "max_tokens": 4096}


def test_the_receipt_carries_the_tool_schemas_as_names_and_hashes():
    """Full schemas are kilobytes each and dozens per turn. The point is to make
    a CHANGE visible, and a stable hash does that at a hundredth of the size —
    `P4-28`'s diff reads a changed hash exactly as well as a changed blob."""
    r = ev.receipt(a_turn())
    tools = r["config"]["tools"]
    assert [t["name"] for t in tools] == ["read_file", "shell"]
    assert all(len(t["sha"]) == 16 for t in tools)
    assert "parameters" not in json.dumps(tools), "the full schema was stored"


def test_a_changed_tool_schema_changes_its_hash():
    """Otherwise the fingerprint records nothing worth having."""
    before = ev._tool_fingerprints([{"function": {"name": "shell", "parameters": {"a": 1}}}])
    after = ev._tool_fingerprints([{"function": {"name": "shell", "parameters": {"a": 2}}}])
    assert before[0]["name"] == after[0]["name"]
    assert before[0]["sha"] != after[0]["sha"]


def test_tool_order_does_not_change_the_receipt():
    """A tool list that arrives in a different order is not a different
    configuration, and a diff that says it is will be ignored."""
    a = ev._tool_fingerprints([{"function": {"name": "b"}}, {"function": {"name": "a"}}])
    b = ev._tool_fingerprints([{"function": {"name": "a"}}, {"function": {"name": "b"}}])
    assert a == b


def test_the_receipt_carries_injected_skills_with_confidence():
    r = ev.receipt(a_turn())
    assert r["config"]["skills"] == [
        {"name": "deploy-checklist", "confidence": 0.82, "source": "user"}]


# --- what it must not carry ------------------------------------------------

def test_no_prompt_or_message_content_reaches_the_receipt():
    """A receipt you cannot hand to someone is not portable (`P4-27`), and a
    receipt containing the conversation is one nobody can hand over."""
    ev.mark_turn_start()
    rid = ev.current_run_id()
    ev.record_run_config(
        sampling={"temperature": 0.7, "prompt": "SECRETPROMPT",
                  "messages": [{"role": "user", "content": "SECRETMESSAGE"}]},
        session_id="s1")
    blob = json.dumps(ev.receipt(rid))
    assert "SECRETPROMPT" not in blob
    assert "SECRETMESSAGE" not in blob


def test_only_known_sampling_knobs_are_kept():
    """An allowlist, not a denylist — the same reason `P16-14`'s settings are."""
    ev.mark_turn_start()
    rid = ev.current_run_id()
    ev.record_run_config(sampling={"temperature": 0.5, "api_key": "sk-LEAK",
                                   "unknown_future_field": "x"}, session_id="s")
    config = ev.receipt(rid)["config"]
    assert config["sampling"] == {"temperature": 0.5}


# --- assembly --------------------------------------------------------------

def test_the_receipt_totals_what_the_turn_did():
    r = ev.receipt(a_turn())
    assert r["totals"] == {"rounds": 1, "input_tokens": 900, "output_tokens": 120,
                           "tool_calls": 2, "tool_failures": 1, "approvals": 1}


def test_the_receipt_is_a_range_scan_not_a_second_store():
    """`Law 14`. Everything except the config row was already being written by
    `P14-01` and `P14-02`; a receipt reads them."""
    tables = set(Base.metadata.tables)
    assert "events" in tables
    assert not any("receipt" in name for name in tables), \
        "a second store appeared where a range scan was asked for"
    src = (ROOT / "src" / "events.py").read_text(encoding="utf-8")
    i = src.index("def receipt(")
    assert "Event.run_id ==" in src[i:i + 2000]


def test_an_unknown_run_id_is_empty_not_an_error():
    r = ev.receipt("nope")
    assert r["totals"]["rounds"] == 0 and "error" not in r


def test_a_missing_run_id_says_so():
    assert "error" in ev.receipt("")


def test_the_receipt_survives_a_broken_database(monkeypatch):
    monkeypatch.setattr(core_db, "SessionLocal",
                        lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    assert "error" in ev.receipt("anything")


# --- the capture sites -----------------------------------------------------

def test_sampling_and_tools_are_captured_where_they_are_resolved():
    """Not at the caller. Defaults are merged and caps applied inside
    `_stream_llm`, so a receipt built from what the caller intended records the
    wrong thing on every path that adjusts either — and several do."""
    src = (ROOT / "src" / "llm_core.py").read_text(encoding="utf-8")
    assert "record_run_config(" in src
    i = src.index("record_run_config(")
    block = src[max(0, i - 600):i + 400]
    assert "_run_config_recorded" in block, "no once-per-run guard"
    assert "tools=tools" in block


def test_the_run_config_is_written_once_per_turn_not_once_per_round():
    """A turn that streams ten rounds should not write ten copies of the same
    configuration."""
    src = (ROOT / "src" / "llm_core.py").read_text(encoding="utf-8")
    assert "contextvars.ContextVar(" in src
    i = src.index("_run_config_recorded")
    assert "ContextVar" in src[i:i + 400], \
        "a module global would let one turn suppress another's receipt"


def test_injected_skills_are_captured_after_selection():
    """What a receipt needs is what the model was SHOWN — the threshold and
    max_items are applied at the injection site, not at the matcher."""
    src = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")
    i = src.index("record_run_config(skills=relevant_skills")
    assert src.index("relevant_skills = sm.get_relevant_skills(") < i


def test_the_skills_capture_references_only_names_in_scope():
    """The first draft passed `session_id`, which `_build_system_prompt` does
    not take — and the `except Exception` around it swallowed the NameError.
    Guarded code that never runs and never says so is worse than code that
    fails."""
    import ast
    src = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_build_system_prompt")
    params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
    call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "record_run_config")
    for kw in call.keywords:
        if isinstance(kw.value, ast.Name):
            assert kw.value.id in params or kw.value.id == "relevant_skills", \
                f"{kw.value.id} is not in scope at the capture site"


def test_the_route_serves_a_receipt():
    src = (ROOT / "routes" / "diagnostics_routes.py").read_text(encoding="utf-8")
    assert "/api/diagnostics/receipt/{run_id}" in src
    i = src.index("/api/diagnostics/receipt/{run_id}")
    assert "require_admin(request)" in src[i:i + 1500]
