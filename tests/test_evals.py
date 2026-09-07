# SPDX-License-Identifier: AGPL-3.0-or-later
"""Save a set of cases, run them against a configuration, get a number (`P14-03`).

Small, because two rows in front of it did the work: a case is a receipt
(`P4-25`) and a run is a re-run (`P4-26`). No case store, no execution engine.

The property these tests exist for is **the number has to be one you can stand
behind**. Three ways an eval harness lies, all tested:

  - a case that could not be reproduced counted as a pass (quiet), or as a fail
    (sends someone hunting a bug that is not there). It is `skipped`.
  - a pass rate computed over cases half of which never ran.
  - a typo'd assertion that silently never runs, so the suite passes for the
    wrong reason. That is the only failure mode of an eval harness that costs
    anything real, because it is the one nobody investigates.
"""
import asyncio
from pathlib import Path

import pytest

from src import evals as ev

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def suites(monkeypatch):
    def declare(*entries):
        monkeypatch.setattr(ev, "load_suites", lambda: list(entries))
    return declare


@pytest.fixture
def fake_replay(monkeypatch):
    """Stand in for `rerun_plan` + `replay` so scoring is tested on its own."""
    state = {"plans": {}, "outputs": {}, "errors": {}, "failures": {}, "calls": []}

    def plan(run_id):
        return state["plans"].get(run_id, {"runnable": True, "drift": []})

    async def replay(run_id, model=None):
        state["calls"].append((run_id, model))
        return {"run_id": f"replay-{run_id}", "output": state["outputs"].get(run_id),
                "error": state["errors"].get(run_id)}

    monkeypatch.setattr("src.replay.rerun_plan", plan)
    monkeypatch.setattr("src.replay.replay", replay)
    monkeypatch.setattr("src.events.receipt",
                        lambda rid: {"totals": {"tool_failures":
                                                state["failures"].get(rid, 0)}})
    return state


# --- the shipped state -----------------------------------------------------

def test_no_suites_ship():
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["eval_suites"] == []


# --- validation before it costs a model call -------------------------------

def test_an_unknown_check_refuses_the_suite(suites, fake_replay):
    """The only failure mode that really costs: a typo'd assertion silently
    never runs, the suite goes green, and nobody investigates a pass."""
    suites({"name": "s", "cases": [
        {"run_id": "r1", "expect": {"containz": ["hello"]}}]})
    result = asyncio.run(ev.run_suite("s"))
    assert result["problems"]
    assert "containz" in result["problems"][0]
    assert not fake_replay["calls"], "a model call was spent on an invalid suite"


def test_a_case_without_a_run_id_refuses_the_suite(suites, fake_replay):
    suites({"name": "s", "cases": [{"expect": {"contains": ["x"]}}]})
    result = asyncio.run(ev.run_suite("s"))
    assert any("run_id" in p for p in result["problems"])
    assert not fake_replay["calls"]


def test_an_empty_suite_refuses(suites):
    suites({"name": "s", "cases": []})
    assert asyncio.run(ev.run_suite("s"))["problems"]


def test_an_unknown_suite_says_so(suites):
    suites()
    result = asyncio.run(ev.run_suite("nope"))
    assert "no suite" in result["headline"]


# --- scoring ---------------------------------------------------------------

def test_contains_and_not_contains():
    s = ev.score_case("the deploy finished", {"contains": ["finished"],
                                              "not_contains": ["error"]})
    assert s["passed"] is True
    s = ev.score_case("the deploy failed", {"contains": ["finished"]})
    assert s["passed"] is False


def test_every_check_reports_its_own_verdict():
    """"8/10 → 7/10" is much less useful than "case 3 stopped containing the
    word the operator was watching for", and the second costs one field."""
    s = ev.score_case("abc", {"contains": ["a", "z"]})
    assert [c["passed"] for c in s["checks"]] == [True, False]
    assert [c["detail"] for c in s["checks"]] == ["a", "z"]


def test_a_bad_regex_is_the_suites_bug_not_the_runs():
    """Reporting it as a failed assertion would blame the model for the
    operator's typo."""
    s = ev.score_case("abc", {"regex": ["([unclosed"]})
    assert s["passed"] is False
    assert "invalid pattern" in s["checks"][0]["detail"]


def test_tool_failures_are_assertable():
    assert ev.score_case("x", {"max_tool_failures": 0}, tool_failures=0)["passed"]
    assert not ev.score_case("x", {"max_tool_failures": 0}, tool_failures=2)["passed"]


def test_an_errored_run_fails_even_with_no_assertions():
    """And it fails via an actual `no_error` CHECK, not a fallback.

    The first version decided this in an `else` clause that was unreachable
    whenever an error existed — mutating it to `else True` changed nothing,
    which is how you learn a defence is decorative.
    """
    scored = ev.score_case(None, {}, error="connection refused")
    assert scored["passed"] is False
    assert [c["check"] for c in scored["checks"]] == ["no_error"], \
        "the error was not turned into a check; something else decided this"
    assert ev.score_case("fine", {})["passed"] is True
    assert ev.score_case("fine", {})["checks"] == []


# --- the number ------------------------------------------------------------

def test_a_suite_runs_every_case_and_counts(suites, fake_replay):
    suites({"name": "s", "cases": [
        {"run_id": "r1", "expect": {"contains": ["ok"]}},
        {"run_id": "r2", "expect": {"contains": ["ok"]}}]})
    fake_replay["outputs"] = {"r1": "ok", "r2": "nope"}
    result = asyncio.run(ev.run_suite("s"))
    assert (result["passed"], result["failed"], result["skipped"]) == (1, 1, 0)
    assert result["pass_rate"] == 0.5


def test_an_unreproducible_case_is_skipped_not_failed(suites, fake_replay):
    """Folding it into `failed` makes a broken environment look like a
    regression and sends someone hunting a bug that is not there. Folding it
    into `passed` is worse, because it is quiet."""
    suites({"name": "s", "cases": [
        {"run_id": "gone", "expect": {"contains": ["ok"]}},
        {"run_id": "r2", "expect": {"contains": ["ok"]}}]})
    fake_replay["plans"]["gone"] = {"runnable": False,
                                    "drift": ["no messages survive for that session"]}
    fake_replay["outputs"] = {"r2": "ok"}
    result = asyncio.run(ev.run_suite("s"))
    assert (result["passed"], result["failed"], result["skipped"]) == (1, 0, 1)
    assert result["pass_rate"] == 1.0, "a skipped case was folded into the rate"
    assert "skipped" in result["headline"]


def test_a_skipped_case_costs_no_model_call(suites, fake_replay):
    suites({"name": "s", "cases": [{"run_id": "gone", "expect": {}}]})
    fake_replay["plans"]["gone"] = {"runnable": False, "drift": ["gone"]}
    asyncio.run(ev.run_suite("s"))
    assert not fake_replay["calls"]


def test_a_suite_where_nothing_ran_refuses_to_print_a_rate(suites, fake_replay):
    """A pass rate over zero executed cases reads like evidence and is not."""
    suites({"name": "s", "cases": [{"run_id": "gone", "expect": {}}]})
    fake_replay["plans"]["gone"] = {"runnable": False, "drift": ["gone"]}
    result = asyncio.run(ev.run_suite("s"))
    assert result["pass_rate"] is None
    assert "nothing ran" in result["headline"]


def test_drift_is_counted_and_surfaced_in_the_headline(suites, fake_replay):
    """A case that ran but could not reproduce its configuration still counts —
    and the headline says so, because the number means less."""
    suites({"name": "s", "cases": [{"run_id": "r1", "expect": {"contains": ["ok"]}}]})
    fake_replay["plans"]["r1"] = {"runnable": True,
                                  "drift": ["skill 'x' no longer exists"]}
    fake_replay["outputs"] = {"r1": "ok"}
    result = asyncio.run(ev.run_suite("s"))
    assert result["drift_cases"] == 1
    assert result["passed"] == 1
    assert "drift" in result["headline"]


def test_a_model_override_reaches_every_case(suites, fake_replay):
    """"Is the new model better" is the question the harness exists for."""
    suites({"name": "s", "cases": [{"run_id": "r1", "expect": {}},
                                   {"run_id": "r2", "expect": {}}]})
    asyncio.run(ev.run_suite("s", model="llama"))
    assert [m for _, m in fake_replay["calls"]] == ["llama", "llama"]


def test_the_limit_is_a_cap_not_a_suggestion(suites, fake_replay):
    suites({"name": "s", "cases": [{"run_id": f"r{i}", "expect": {}} for i in range(10)]})
    result = asyncio.run(ev.run_suite("s", limit=3))
    assert result["total"] == 3
    assert len(fake_replay["calls"]) == 3


def test_tool_failures_come_from_the_replays_own_receipt(suites, fake_replay):
    """Not the original's. The whole point is what happened THIS time."""
    suites({"name": "s", "cases": [
        {"run_id": "r1", "expect": {"max_tool_failures": 0}}]})
    fake_replay["outputs"] = {"r1": "ok"}
    fake_replay["failures"] = {"replay-r1": 3}
    result = asyncio.run(ev.run_suite("s"))
    assert result["failed"] == 1
    assert result["cases"][0]["tool_failures"] == 3


# --- P14-04: a result is a diff -------------------------------------------

def test_a_failing_case_says_what_changed(suites, fake_replay, monkeypatch):
    """"Case 3 failed" sends someone to read a transcript. "Case 3 failed, and
    the tool schema changed" is the answer."""
    suites({"name": "s", "cases": [{"run_id": "r1", "expect": {"contains": ["ok"]}}]})
    fake_replay["outputs"] = {"r1": "nope"}
    monkeypatch.setattr("src.receipt_diff.diff_receipts", lambda a, b: {
        "headline": "1 unasked-for change(s): tool:shell",
        "differences": [{"kind": "inflicted", "what": "tool:shell",
                         "before": "a", "after": "b", "note": "the schema changed"},
                        {"kind": "outcome", "what": "input_tokens",
                         "before": 1, "after": 2, "note": ""}]})
    result = asyncio.run(ev.run_suite("s"))
    case = result["cases"][0]
    assert case["status"] == "failed"
    assert "tool:shell" in case["why"]
    assert [c["what"] for c in case["changed"]] == ["tool:shell"], \
        "the outcome entry was included; it is a consequence, not a cause"


def test_a_passing_case_costs_no_diff(suites, fake_replay, monkeypatch):
    """Running it on passes too would double the cost of a green suite to
    produce something nobody opens."""
    calls = []
    suites({"name": "s", "cases": [{"run_id": "r1", "expect": {"contains": ["ok"]}}]})
    fake_replay["outputs"] = {"r1": "ok"}
    monkeypatch.setattr("src.receipt_diff.diff_receipts",
                        lambda a, b: calls.append(1) or {"headline": "", "differences": []})
    result = asyncio.run(ev.run_suite("s"))
    assert result["cases"][0]["status"] == "passed"
    assert not calls, "a diff was computed for a passing case"


def test_the_diff_compares_the_original_to_its_own_replay(suites, fake_replay, monkeypatch):
    seen = []
    suites({"name": "s", "cases": [{"run_id": "r1", "expect": {"contains": ["ok"]}}]})
    fake_replay["outputs"] = {"r1": "nope"}
    monkeypatch.setattr("src.receipt_diff.diff_receipts",
                        lambda a, b: seen.append((a, b)) or {"headline": "", "differences": []})
    asyncio.run(ev.run_suite("s"))
    assert seen == [("r1", "replay-r1")]


def test_a_broken_diff_does_not_break_the_suite(suites, fake_replay, monkeypatch):
    """The score is the deliverable; the explanation is a bonus, and a bonus
    must never cost the deliverable."""
    suites({"name": "s", "cases": [{"run_id": "r1", "expect": {"contains": ["ok"]}}]})
    fake_replay["outputs"] = {"r1": "nope"}
    monkeypatch.setattr("src.receipt_diff.diff_receipts",
                        lambda a, b: (_ for _ in ()).throw(RuntimeError("boom")))
    result = asyncio.run(ev.run_suite("s"))
    assert result["failed"] == 1


# --- Law 14 ----------------------------------------------------------------

def test_the_harness_builds_no_case_store_and_no_runner():
    """A case is a receipt, a run is a re-run. Three copies of the
    configuration would be three things to keep in step."""
    src = (ROOT / "src" / "evals.py").read_text(encoding="utf-8")
    assert "from src.replay import replay" in src
    assert "from src.events import receipt" in src
    for invented in ("class Case", "class Runner", "__tablename__", "CREATE TABLE"):
        assert invented not in src, f"{invented} — a second scaffolding appeared"


def test_evals_imports_resolve():
    """`B32`'s shape, third file. Every first-party import checked against its
    real module."""
    import ast, importlib
    tree = ast.parse((ROOT / "src" / "evals.py").read_text(encoding="utf-8"))
    checked = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module \
                and node.module.startswith(("src.", "core.", "services.")):
            module = importlib.import_module(node.module)
            for alias in node.names:
                checked += 1
                assert hasattr(module, alias.name), \
                    f"src/evals.py imports {alias.name!r} from {node.module}, which has no such name"
    assert checked, "no first-party imports found — vacuous"


def test_the_run_route_is_a_post():
    src = (ROOT / "routes" / "diagnostics_routes.py").read_text(encoding="utf-8")
    assert '@router.post("/api/diagnostics/evals/{name}/run")' in src
    assert '@router.get("/api/diagnostics/evals")' in src
