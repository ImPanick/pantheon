# SPDX-License-Identifier: AGPL-3.0-or-later
"""A judge is refused, not ignored, and every score says how it was graded.

`P14-08` asked for model-graded scoring *"if it earns its place"*, and
`D-2026-09-18-02` is the measurement that says it does not. The decision is only
worth anything if the code follows it, and on the tree before this row it did
not follow it in the one direction that matters:

    validate_suite({"name": "s", "judge": {"model": "gpt-4o"},
                    "cases": [{"run_id": "r", "expect": {"contains": "x"}}]})
    -> []          # clean. The suite then ran and printed a pass rate computed
                   # entirely from the deterministic checks, with the operator's
                   # judge never called and nothing in the result saying so.

That is `P14-08`'s `Verify` clause failing in the direction nobody investigates:
a suite **silently scored some other way**, and scored green.
"""
import asyncio

import pytest

from src import evals


def _suite(**extra):
    base = {"name": "regression", "cases": [{"run_id": "abc123",
                                             "expect": {"contains": "hello"}}]}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Refused, by name, before a model call
# ---------------------------------------------------------------------------

# Spelled out rather than taken from `evals.JUDGE_KEYS`, so this file collects
# and FAILS on a tree that has no such constant instead of erroring at import —
# a collection error is a worse piece of evidence than a red test (`Law 9`).
JUDGE_SPELLINGS = ("judge", "judge_model", "judge_prompt", "judge_endpoint",
                   "llm_judge", "grader", "graded_by", "rubric")


@pytest.mark.parametrize("key", JUDGE_SPELLINGS)
def test_a_suite_that_configures_a_judge_is_refused(key):
    problems = evals.validate_suite(_suite(**{key: {"model": "gpt-4o"}}))
    assert problems, f"{key!r} was accepted and would have been silently ignored"
    assert any(key in p for p in problems)


def test_every_spelling_the_module_knows_is_one_of_these():
    """The parametrised list above and the module's own must not drift apart."""
    assert set(evals.JUDGE_KEYS) == set(JUDGE_SPELLINGS)


def test_the_refusal_names_the_decision_not_the_spelling():
    """*'judge is not a key'* reads like a typo and sends someone hunting for
    the right spelling. There is no right spelling; there is a decision."""
    problems = evals.validate_suite(_suite(judge="gpt-4o"))
    assert any("D-2026-09-18-02" in p and "P14-08" in p for p in problems)
    assert any("deterministic" in p for p in problems)


def test_a_judge_on_a_case_is_refused_too():
    suite = {"name": "s", "cases": [
        {"run_id": "r1", "expect": {"contains": "x"}},
        {"run_id": "r2", "judge_model": "local-llm", "expect": {"contains": "y"}},
    ]}
    problems = evals.validate_suite(suite)
    assert any("case 1" in p for p in problems)


def test_a_judge_inside_expect_is_refused_as_a_judge_not_as_a_typo():
    """`expect: {judge: ...}` already failed the allowlist — with the wrong
    reason. *'not a check'* invites the operator to go looking for the right
    check name, and there is not one."""
    problems = evals.validate_suite(
        _suite(cases=[{"run_id": "r", "expect": {"judge": "is it better?"}}]))
    assert problems
    assert any("D-2026-09-18-02" in p for p in problems)
    assert not any("which is not a check" in p for p in problems)


def test_an_ordinary_typo_still_reads_as_a_typo():
    """The judge refusal must not swallow the allowlist message it sits beside."""
    problems = evals.validate_suite(
        _suite(cases=[{"run_id": "r", "expect": {"containss": "x"}}]))
    assert any("which is not a check" in p for p in problems)
    assert not any("D-2026-09-18-02" in p for p in problems)


def test_a_clean_suite_is_still_clean():
    """`Law 1`. The refusal is an addition, and adds nothing to a good suite."""
    assert evals.validate_suite(_suite()) == []


# ---------------------------------------------------------------------------
# Every score says how it was graded
# ---------------------------------------------------------------------------

def test_a_run_reports_its_grading_method(monkeypatch):
    monkeypatch.setattr(evals, "load_suites", lambda: [_suite()])

    monkeypatch.setitem(__import__("sys").modules, "src.replay",
                        _fake_replay_module(runnable=False))
    result = asyncio.run(evals.run_suite("regression"))
    assert result["grading"] == "deterministic"
    assert result["skipped"] == 1          # nothing ran; the field is there anyway


def test_a_refused_suite_still_says_how_it_would_have_been_graded(monkeypatch):
    """Both refusal paths out of `run_suite` carry it.

    A result dict whose shape depends on which way it failed is a result dict
    every caller has to defend against.
    """
    monkeypatch.setattr(evals, "load_suites", lambda: [_suite(judge="gpt-4o")])
    refused = asyncio.run(evals.run_suite("regression"))
    assert refused["grading"] == "deterministic"
    assert refused["problems"] and "D-2026-09-18-02" in " ".join(refused["problems"])
    assert refused["pass_rate"] is None    # refused, never scored

    missing = asyncio.run(evals.run_suite("no-such-suite"))
    assert missing["grading"] == "deterministic"


def test_a_judge_suite_is_not_scored_at_all(monkeypatch):
    """The whole defect, end to end: it used to return a green pass rate."""
    monkeypatch.setattr(evals, "load_suites", lambda: [_suite(judge={"model": "x"})])
    monkeypatch.setitem(__import__("sys").modules, "src.replay",
                        _fake_replay_module(runnable=True))
    result = asyncio.run(evals.run_suite("regression"))
    assert result["passed"] == 0 and result["failed"] == 0
    assert result["pass_rate"] is None
    assert "not run" in result["headline"]


# ---------------------------------------------------------------------------
# The baseline the decision was measured against
# ---------------------------------------------------------------------------

def test_the_deterministic_scorer_answers_identically_every_time():
    """`D-2026-09-18-02`'s first measurement, kept as a test.

    This is what a judge would have to beat: one verdict, every time, for no
    model calls. A judge on this stack runs at `replay`'s default
    `temperature=0.2` and cannot promise it.
    """
    expect = {"contains": ["nginx"], "not_contains": ["password"],
              "regex": [r"tool calls: \d+"], "max_tool_failures": 2, "no_error": True}
    out = "restarted nginx; tool calls: 3"
    verdicts = {str(evals.score_case(out, expect, error=None, tool_failures=1))
                for _ in range(500)}
    assert len(verdicts) == 1


def _fake_replay_module(*, runnable: bool):
    """A stand-in for `src.replay`, so these never make a model call.

    `run_suite` imports it inside the function, which is the seam.
    """
    import types

    mod = types.ModuleType("src.replay")

    def rerun_plan(run_id):
        return {"runnable": runnable, "drift": [] if runnable else ["receipt is gone"]}

    async def replay(run_id, model=None):
        return {"run_id": "new-" + run_id, "output": "hello there", "error": None}

    mod.rerun_plan = rerun_plan
    mod.replay = replay
    return mod
