# SPDX-License-Identifier: AGPL-3.0-or-later
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

def test_every_llm_entry_point_records_a_config():
    """The gap the first version shipped with, and the test that missed it.

    `record_run_config` lived only in `stream_llm`. `/api/chat` reaches the
    model through `llm_call_async_with_route_fallback` → `llm_call_async` and
    never streams, so **half the chat surface produced receipts with
    `config: null`** — silently, because a null config looks like a quiet turn.

    The old test grepped `llm_core.py` for the call, which one entry point
    satisfies. This one walks the AST and requires every entry point to capture,
    or to be named here with a reason.
    """
    import ast
    src = (ROOT / "src" / "llm_core.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Functions that actually reach a model on a user's behalf.
    entry_points = {"llm_call", "llm_call_async", "stream_llm"}
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name in entry_points:
            found[node.name] = any(
                isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_capture_run_config"
                for c in ast.walk(node))

    missing = sorted(n for n in entry_points if not found.get(n))
    assert not missing, (
        f"these reach a model without recording a run config: {missing}. "
        f"A receipt with config: null is indistinguishable from a quiet turn.")


def test_the_capture_is_one_implementation_not_three():
    """`Law 14`. Three entry points, one helper — three copies would drift, and
    the one that drifted would be the one nobody was looking at."""
    src = (ROOT / "src" / "llm_core.py").read_text(encoding="utf-8")
    assert src.count("def _capture_run_config(") == 1
    assert src.count("record_run_config(") == 1, \
        "record_run_config is called from more than one place; funnel it"


def test_the_non_stream_path_records_before_the_cache_check():
    """A turn answered from cache still HAD a configuration. A receipt that
    exists only for cache misses goes missing exactly when two runs of the same
    thing are being compared — which is what receipts are for."""
    import ast
    src = (ROOT / "src" / "llm_core.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "llm_call_async")
    capture = next(c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call)
                   and getattr(c.func, "id", "") == "_capture_run_config")
    cached = next(c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call)
                  and getattr(c.func, "id", "") == "_get_cached_response")
    assert capture < cached, "the cache short-circuits the receipt"


def test_omitting_tools_is_not_the_same_as_sending_none():
    """"No tools were sent" and "we did not look" are different facts, and a
    diff (`P4-28`) that cannot tell them apart reports a change nobody made."""
    ev.mark_turn_start()
    rid = ev.current_run_id()
    ev.record_run_config(sampling={"temperature": 0.1}, session_id="s")
    assert "tools" not in ev.receipt(rid)["config"]

    ev._turn_started.set(None)
    ev._run_id.set(None)
    ev.mark_turn_start()
    rid2 = ev.current_run_id()
    ev.record_run_config(sampling={"temperature": 0.1}, tools=[], session_id="s")
    assert ev.receipt(rid2)["config"]["tools"] == []


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


@pytest.mark.parametrize("module,func", [
    ("src/agent_loop.py", "record_run_config"),
    ("src/llm_core.py", "_capture_run_config"),
])
def test_every_capture_site_references_only_names_in_scope(module, func):
    """`B32`, twice, and the second time proved the first fix was too narrow.

    The skills capture passed `session_id` to a function that does not take one,
    and the `except Exception` around it swallowed the NameError — recording
    nothing, forever, silently. I wrote a test. It checked exactly that one call
    site. Then the correction pass added a capture to the SYNC `llm_call`, which
    also has no `session_id`, and the same bug shipped again in a different
    file — caught only because that call is not wrapped, so it raised.

    So the check is parameterised over every module that captures, and walks
    every call site in each. A test written to the shape of one bug catches one
    bug.
    """
    import ast
    src = (ROOT / module).read_text(encoding="utf-8")
    tree = ast.parse(src)

    checked = 0
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        if fn.args.vararg:
            params.add(fn.args.vararg.arg)
        if fn.args.kwarg:
            params.add(fn.args.kwarg.arg)
        # Names bound inside the function body count as in scope too.
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                params.add(node.id)
            elif isinstance(node, ast.alias):
                params.add((node.asname or node.name).split(".")[0])

        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call)
                    and getattr(call.func, "id", "") == func):
                continue
            checked += 1
            names = [a for a in call.args if isinstance(a, ast.Name)]
            names += [k.value for k in call.keywords if isinstance(k.value, ast.Name)]
            for n in names:
                assert n.id in params, (
                    f"{module}: {func}() in {fn.name}() references {n.id!r}, "
                    f"which is not in scope there")
    assert checked, f"no {func} call sites found in {module} — test is vacuous"


def test_the_route_serves_a_receipt():
    src = (ROOT / "routes" / "diagnostics_routes.py").read_text(encoding="utf-8")
    assert "/api/diagnostics/receipt/{run_id}" in src
    i = src.index("/api/diagnostics/receipt/{run_id}")
    assert "require_admin(request)" in src[i:i + 1500]
