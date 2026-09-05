"""What changed between the run that worked and the one that did not (`P4-28`).

The question receipts were built for. `P4-25` captured the configuration,
`P4-26` proved it round-trips, `P14-03` scores a set — none of which says *why*
case 3 went from green to red.

**The classification is the product, not the completeness.** Two receipts differ
in dozens of ways that mean nothing, and a diff that lists them all is one
nobody reads twice — which is worse than no diff, because it was paid for. So
every difference is `chosen`, `inflicted`, `outcome` or `noise`, and the tests
below are almost entirely about that line being drawn in the right place.
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as core_db
from core.database import Base
from src import events as ev
from src.receipt_diff import CHOSEN, INFLICTED, NOISE, OUTCOME, diff_receipts

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/d.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    monkeypatch.setattr(ev, "_last_prune", 0.0)
    yield maker
    engine.dispose()


def make_run(*, model="qwen", endpoint="Local", tools=None, skills=None,
             sampling=None, in_tokens=900, tool_failures=0,
             replay_of=None, deliberate=None, drift=None):
    ev._turn_started.set(None)
    ev._run_id.set(None)
    ev.mark_turn_start()
    rid = ev.current_run_id()
    ev.record_run_config(sampling=sampling or {"temperature": 0.7},
                         tools=tools, skills=skills, session_id="s1")
    ev.record_llm_round("s1", {"input_tokens": in_tokens, "output_tokens": 20,
                               "model": model, "endpoint_label": endpoint})
    for _ in range(tool_failures):
        ev.record_event("tool_call", name="shell", outcome="error")
    if replay_of:
        ev.record_event("replay", name=model,
                        detail={"replay_of": replay_of,
                                "deliberate": deliberate or [],
                                "drift": drift or []})
    return rid


def kinds(result, what):
    return [d["kind"] for d in result["differences"] if d["what"] == what]


# --- chosen vs inflicted: the whole point ---------------------------------

def test_a_requested_model_change_is_chosen_not_a_finding():
    """It is the experiment, not the answer. `P4-26` records an override as
    `deliberate`, which is what lets this be told rather than guessed."""
    a = make_run(model="qwen")
    b = make_run(model="llama", replay_of=a,
                 deliberate=["model qwen → llama (requested)"])
    assert kinds(diff_receipts(a, b), "model") == [CHOSEN]


def test_an_unrequested_model_change_is_inflicted():
    """Same difference, opposite meaning. Nobody asked, so it is almost
    certainly the answer to "why did it change"."""
    a = make_run(model="qwen")
    b = make_run(model="llama")
    result = diff_receipts(a, b)
    assert kinds(result, "model") == [INFLICTED]
    assert "nobody asked" in [d["note"] for d in result["differences"]
                              if d["what"] == "model"][0]


def test_the_headline_leads_with_what_nobody_chose():
    """Ordering is the argument. Putting outcome first buries the cause under
    numbers that are its consequences."""
    a = make_run(model="qwen", skills=[{"name": "deploy", "confidence": 0.8}])
    b = make_run(model="llama", skills=[], replay_of=a,
                 deliberate=["model qwen → llama (requested)"], tool_failures=2)
    headline = diff_receipts(a, b)["headline"]
    assert headline.index("unasked-for") < headline.index("chosen")
    assert headline.index("unasked-for") < headline.index("outcome")


# --- what counts as inflicted ---------------------------------------------

def test_a_changed_tool_schema_is_inflicted():
    """The hash is the entire reason `P4-25` stores one — the name alone would
    have said nothing had changed."""
    a = make_run(tools=[{"function": {"name": "shell", "parameters": {"a": 1}}}])
    b = make_run(tools=[{"function": {"name": "shell", "parameters": {"a": 2}}}])
    result = diff_receipts(a, b)
    assert kinds(result, "tool:shell") == [INFLICTED]
    assert "schema changed" in [d["note"] for d in result["differences"]
                                if d["what"] == "tool:shell"][0]


def test_a_removed_tool_says_the_model_can_no_longer_call_it():
    a = make_run(tools=[{"function": {"name": "shell"}}])
    b = make_run(tools=[])
    entry = [d for d in diff_receipts(a, b)["differences"] if d["what"] == "tool:shell"][0]
    assert entry["kind"] == INFLICTED
    assert entry["before"] == "present" and entry["after"] == "absent"


def test_a_vanished_skill_is_inflicted():
    a = make_run(skills=[{"name": "deploy", "confidence": 0.8}])
    b = make_run(skills=[])
    assert kinds(diff_receipts(a, b), "skill:deploy") == [INFLICTED]


def test_a_moved_skill_confidence_is_inflicted():
    a = make_run(skills=[{"name": "deploy", "confidence": 0.8}])
    b = make_run(skills=[{"name": "deploy", "confidence": 0.4}])
    result = diff_receipts(a, b)
    entry = [d for d in result["differences"]
             if d["what"] == "skill:deploy.confidence"][0]
    assert (entry["before"], entry["after"]) == (0.8, 0.4)


def test_sampling_changes_are_inflicted():
    a = make_run(sampling={"temperature": 0.7})
    b = make_run(sampling={"temperature": 0.2})
    assert kinds(diff_receipts(a, b), "sampling.temperature") == [INFLICTED]


def test_the_replays_own_drift_is_carried_into_the_diff():
    """`P4-26` reports what could not be reproduced. That is a difference, and
    it belongs beside the ones the diff computes itself."""
    a = make_run()
    b = make_run(replay_of=a, drift=["skill 'x' no longer exists"])
    entries = [d for d in diff_receipts(a, b)["differences"] if d["what"] == "drift"]
    assert entries and entries[0]["kind"] == INFLICTED


# --- outcome is not a cause -----------------------------------------------

def test_outcome_changes_are_labelled_outcome_not_inflicted():
    """What the run produced is not why. Presenting it as a cause is how a diff
    sends somebody to fix the symptom."""
    a = make_run(tool_failures=0)
    b = make_run(tool_failures=3)
    assert kinds(diff_receipts(a, b), "tool_failures") == [OUTCOME]


# --- noise is suppressed, not hidden --------------------------------------

def test_a_small_token_wobble_is_noise():
    """Counts move on identical inputs. A diff that reports every one is a diff
    nobody reads twice."""
    a = make_run(in_tokens=900)
    b = make_run(in_tokens=905)
    result = diff_receipts(a, b)
    assert not [d for d in result["differences"] if d["what"] == "input_tokens"]
    assert result["noise_count"] >= 1


def test_a_large_token_change_is_not_noise():
    """Suppression has to have a floor, or the diff quietly stops reporting the
    thing it exists for."""
    a = make_run(in_tokens=900)
    b = make_run(in_tokens=4000)
    assert kinds(diff_receipts(a, b), "input_tokens") == [OUTCOME]


def test_noise_is_counted_so_suppression_is_visible():
    a = make_run(in_tokens=900)
    b = make_run(in_tokens=902)
    result = diff_receipts(a, b)
    assert result["noise_count"] >= 1
    assert "noise" in result["headline"] or result["differences"]


def test_two_identical_runs_diff_to_nothing():
    a = make_run()
    b = make_run()
    result = diff_receipts(a, b)
    assert not [d for d in result["differences"] if d["kind"] == INFLICTED]


# --- it must not fall over ------------------------------------------------

def test_an_unknown_run_is_an_error_not_a_crash():
    a = make_run()
    result = diff_receipts(a, "nope")
    assert result["error"] and "recorded nothing" in result["error"]


def test_a_run_with_no_config_still_diffs_what_it_has():
    """A receipt from before `P4-25` has rounds and no config. Refusing would
    make the oldest runs — the ones most worth comparing against — undiffable."""
    ev._turn_started.set(None)
    ev._run_id.set(None)
    ev.mark_turn_start()
    a = ev.current_run_id()
    ev.record_llm_round("s1", {"input_tokens": 900, "output_tokens": 20,
                               "model": "qwen"})
    b = make_run(model="llama")
    result = diff_receipts(a, b)
    assert result["error"] is None
    assert kinds(result, "model") == [INFLICTED]


# --- plumbing -------------------------------------------------------------

def test_receipt_surfaces_replay_rows():
    """`P4-26` wrote these and nothing read them: the link back was recorded
    and then dropped on the way out of the only API that reads receipts."""
    a = make_run()
    b = make_run(replay_of=a, deliberate=["model x → y (requested)"])
    assert ev.receipt(b)["replays"], "replay rows are recorded but unreadable"


def test_receipt_diff_imports_resolve():
    import ast, importlib
    tree = ast.parse((ROOT / "src" / "receipt_diff.py").read_text(encoding="utf-8"))
    checked = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module \
                and node.module.startswith(("src.", "core.", "services.")):
            module = importlib.import_module(node.module)
            for alias in node.names:
                checked += 1
                assert hasattr(module, alias.name), \
                    f"imports {alias.name!r} from {node.module}, which has no such name"
    assert checked


def test_the_route_exists():
    src = (ROOT / "routes" / "diagnostics_routes.py").read_text(encoding="utf-8")
    assert '/api/diagnostics/diff/{before_id}/{after_id}' in src
