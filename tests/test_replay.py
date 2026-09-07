# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-run a receipt: same inputs, same configuration, new run (`P4-26`).

The only honest way to answer *"did that change help"*, and the prerequisite
`P14-03`'s eval harness has been waiting on — a case that cannot be re-run is
not a case.

The property that makes this worth having is **drift reporting**. "Same
configuration" is a claim, and between two runs a model can be gone, an endpoint
renamed, a skill edited. Substituting silently would make every answer this row
exists to give a lie, so the plan returns what it can reproduce alongside what
it cannot — and `P4-28` will then diff two receipts knowing which differences
were chosen and which were inflicted.
"""
import ast
import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as core_db
from core.database import Base, ChatMessage, Session as DBSession, utcnow_naive
from src import events as ev
from src import replay as rp

ROOT = Path(__file__).resolve().parent.parent
_maker = None


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/p.db",
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


def a_run(*, session_id="s1", with_messages=True, skills=None, model="qwen"):
    now = utcnow_naive()
    db = _maker()
    try:
        if session_id and with_messages:
            db.add(DBSession(id=session_id, name="t",
                             endpoint_url="http://localhost:8000", model=model))
            db.add(ChatMessage(id="m1", session_id=session_id, role="user",
                               content="hello", timestamp=now - timedelta(minutes=5)))
            db.add(ChatMessage(id="m2", session_id=session_id, role="assistant",
                               content="hi", timestamp=now - timedelta(minutes=4)))
        db.commit()
    finally:
        db.close()
    ev._turn_started.set(None)
    ev._run_id.set(None)
    ev.mark_turn_start()
    rid = ev.current_run_id()
    ev.record_run_config(sampling={"temperature": 0.7, "max_tokens": 2048},
                         skills=skills, session_id=session_id)
    ev.record_llm_round(session_id, {"input_tokens": 50, "output_tokens": 9,
                                     "model": model, "endpoint_label": "Local"})
    return rid


# --- the plan --------------------------------------------------------------

def test_a_plan_carries_the_inputs_and_the_configuration():
    plan = rp.rerun_plan(a_run())
    assert plan["runnable"] is True
    assert [m["role"] for m in plan["messages"]] == ["user", "assistant"]
    assert plan["model"] == "qwen"
    assert plan["sampling"] == {"temperature": 0.7, "max_tokens": 2048}


def test_only_messages_from_before_the_run_are_inputs():
    """Everything after is what the run PRODUCED. Replaying with it in the
    prompt is not a replay, it is a different conversation that happens to
    contain the answer."""
    rid = a_run()
    db = _maker()
    try:
        db.add(ChatMessage(id="m9", session_id="s1", role="assistant",
                           content="LATER", timestamp=utcnow_naive() + timedelta(hours=1)))
        db.commit()
    finally:
        db.close()
    plan = rp.rerun_plan(rid)
    assert all("LATER" not in m["content"] for m in plan["messages"])


def test_a_receipt_with_no_session_is_not_runnable_and_says_why():
    """The trade `P4-25` made: no message content, so a receipt exported to
    someone else can be READ but not re-run. Stated, not discovered."""
    plan = rp.rerun_plan(a_run(session_id=None, with_messages=False))
    assert plan["runnable"] is False
    assert any("no session" in d or "exported" in d for d in plan["drift"])


def test_a_deleted_conversation_is_not_runnable_and_says_why():
    rid = a_run()
    db = _maker()
    try:
        db.query(ChatMessage).delete()
        db.commit()
    finally:
        db.close()
    plan = rp.rerun_plan(rid)
    assert plan["runnable"] is False
    assert any("deleted" in d or "no messages" in d for d in plan["drift"])


def test_an_unknown_run_is_not_runnable():
    plan = rp.rerun_plan("nope")
    assert plan["runnable"] is False
    assert plan["drift"]


# --- drift is the product --------------------------------------------------

def test_a_vanished_skill_is_reported_as_drift(monkeypatch):
    monkeypatch.setattr(rp, "_skill_drift",
                        lambda rec: ["skill 'gone' no longer exists"] if rec else [])
    plan = rp.rerun_plan(a_run(skills=[{"name": "gone", "confidence": 0.8}]))
    assert any("no longer exists" in d for d in plan["drift"])


def test_a_changed_skill_confidence_is_reported():
    class _SM:
        def load_all(self):
            return [{"name": "deploy", "confidence": 0.5}]
    import services.memory.skills as sk
    real = sk.SkillsManager
    try:
        sk.SkillsManager = lambda *a, **k: _SM()
        drift = rp._skill_drift([{"name": "deploy", "confidence": 0.8}])
    finally:
        sk.SkillsManager = real
    assert any("0.8" in d and "0.5" in d for d in drift)


def test_skill_drift_does_not_disqualify_a_replay():
    """Re-running with today's skills against yesterday's configuration is
    often exactly the comparison someone wants. Refusing it would make the
    honest answer unavailable."""
    plan = rp.rerun_plan(a_run(skills=[{"name": "gone-forever", "confidence": 0.8}]))
    assert plan["runnable"] is True
    assert plan["drift"], "drift was silently dropped rather than reported"


def test_a_missing_run_config_is_reported_but_not_fatal():
    """Model and sampling can still be read off the round. Fatal would be
    pretending otherwise."""
    ev._turn_started.set(None)
    ev._run_id.set(None)
    db = _maker()
    try:
        db.add(DBSession(id="s2", name="t", endpoint_url="u", model="qwen"))
        db.add(ChatMessage(id="mm", session_id="s2", role="user", content="x",
                           timestamp=utcnow_naive() - timedelta(minutes=1)))
        db.commit()
    finally:
        db.close()
    ev.mark_turn_start()
    rid = ev.current_run_id()
    ev.record_llm_round("s2", {"input_tokens": 1, "output_tokens": 1, "model": "qwen"})
    plan = rp.rerun_plan(rid)
    assert plan["runnable"] is True
    assert any("run_config" in d for d in plan["drift"])


def test_describe_is_readable_before_spending_a_model_call():
    text = rp.describe(rp.rerun_plan(a_run()))
    assert "Re-run" in text and "qwen" in text and "message(s)" in text


# --- the replay ------------------------------------------------------------

def test_a_replay_gets_its_own_run_id_and_links_back(monkeypatch):
    original = a_run()

    async def fake_call(url, model, messages, **kw):
        return "replayed output"

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_call)
    monkeypatch.setattr(rp, "_endpoint_for", lambda m, o=None: ("http://x/v1", {}))
    result = asyncio.run(rp.replay(original))

    assert result["error"] is None, result["error"]
    assert result["output"] == "replayed output"
    assert result["run_id"] and result["run_id"] != original

    linked = ev.receipt(result["run_id"])
    replays = [e for e in linked["rounds"] + linked["tools"]] or []
    db = _maker()
    try:
        from core.database import Event
        rows = db.query(Event).filter(Event.run_id == result["run_id"],
                                      Event.kind == "replay").all()
        assert rows, "the replay recorded no link back"
        import json
        assert json.loads(rows[0].detail)["replay_of"] == original
    finally:
        db.close()


def test_a_replay_does_not_append_to_the_session(monkeypatch):
    """It is a diagnostic, not a conversation. Appending would change the thing
    being measured, and put a machine-generated turn in front of the person the
    next time they scrolled up."""
    original = a_run()

    async def fake_call(url, model, messages, **kw):
        return "replayed output"

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_call)
    monkeypatch.setattr(rp, "_endpoint_for", lambda m, o=None: ("http://x/v1", {}))

    db = _maker()
    before = db.query(ChatMessage).count()
    db.close()
    asyncio.run(rp.replay(original))
    db = _maker()
    after = db.query(ChatMessage).count()
    db.close()
    assert before == after, "the replay wrote into the conversation"


def test_a_model_override_is_recorded_as_deliberate(monkeypatch):
    """"Is the new model better" is the whole point, and `P4-28` must be able to
    tell a choice from an accident."""
    original = a_run()

    async def fake_call(url, model, messages, **kw):
        return f"ran on {model}"

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_call)
    monkeypatch.setattr(rp, "_endpoint_for", lambda m, o=None: ("http://x/v1", {}))
    result = asyncio.run(rp.replay(original, model="llama"))
    assert result["output"] == "ran on llama"

    import json
    db = _maker()
    try:
        from core.database import Event
        row = db.query(Event).filter(Event.run_id == result["run_id"],
                                     Event.kind == "replay").first()
        detail = json.loads(row.detail)
        assert any("requested" in d for d in detail["deliberate"])
    finally:
        db.close()


def test_a_replay_inside_an_existing_run_does_not_join_it(monkeypatch):
    """`mark_turn_start` only acts on an unset ContextVar, so without an
    explicit reset a replay would write its rows onto whichever receipt the
    calling request already had."""
    original = a_run()
    ev._turn_started.set(None)
    ev._run_id.set(None)
    ev.mark_turn_start()
    caller_run = ev.current_run_id()

    async def fake_call(url, model, messages, **kw):
        return "x"

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_call)
    monkeypatch.setattr(rp, "_endpoint_for", lambda m, o=None: ("http://x/v1", {}))
    result = asyncio.run(rp.replay(original))
    assert result["run_id"] != caller_run
    assert ev.receipt(caller_run)["totals"]["rounds"] == 0


def test_an_unrunnable_plan_costs_no_model_call(monkeypatch):
    called = []

    async def fake_call(*a, **k):
        called.append(1)
        return "x"

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_call)
    result = asyncio.run(rp.replay("nope"))
    assert result["error"]
    assert not called, "a model call was spent on a plan that could not run"


# --- the shape that keeps recurring ---------------------------------------

def test_replay_calls_functions_that_exist():
    """`B32`, third occurrence, generalised.

    The first draft of this module called `resolve_endpoint_for_model` and
    `SkillManager` — neither exists — inside `try/except` blocks that would have
    swallowed the ImportError and silently fallen back to a hardcoded host, or
    reported "skills could not be read" forever as though it were a property of
    the install.

    So: every name this module imports is resolved against its real module.
    """
    import importlib
    src = (ROOT / "src" / "replay.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith(("src.", "core.", "services.")):
            continue
        module = importlib.import_module(node.module)
        for alias in node.names:
            checked += 1
            assert hasattr(module, alias.name), \
                f"src/replay.py imports {alias.name!r} from {node.module}, which has no such name"
    assert checked, "no first-party imports found — the test would be vacuous"


def test_the_routes_exist_and_the_costly_one_is_a_post():
    src = (ROOT / "routes" / "diagnostics_routes.py").read_text(encoding="utf-8")
    assert '@router.get("/api/diagnostics/rerun/{run_id}")' in src
    assert '@router.post("/api/diagnostics/rerun/{run_id}")' in src, \
        "the run that spends a model call must not be a GET"
