# SPDX-License-Identifier: AGPL-3.0-or-later
"""Save a set of cases, run them against a configuration, get a number (`P14-03`).

Every prompt change, model swap, skill edit and retrieval tweak in this codebase
is currently evaluated by vibes. This is the thing that replaces the vibes.

It is small because two rows in front of it did the work: **a case is a receipt**
(`P4-25`) and **a run is a re-run** (`P4-26`). There is no case store, no
execution engine and no second copy of the configuration — a suite is a list of
`run_id`s plus what the operator expects, and running it is `replay()` in a loop.
`Law 14`, and it is the difference between a week and an afternoon.

THREE DECISIONS, AND THE THIRD IS THE ONE THAT MATTERS.

**1. The assertions are deterministic, and the operator writes them.**
`contains`, `not_contains`, `regex`, `max_tool_failures`. Not a judge model —
that is a real technique and a bigger decision (whose model? at what
temperature? paid for by whom?), and a harness whose *first* answer to "did that
change help" is itself non-deterministic has replaced vibes with dearer vibes.

**`P14-08` asked whether a judge earns its place here, and the answer is no**
(`D-2026-09-18-02`). Two things follow, and both are in this file rather than
only in the decision:

  * every result says **how it was graded** (`grading`), so a judge cannot
    arrive later and grade silently. A score whose method is not on it is the
    one thing this row's `Verify` line will not have;
  * a suite that **configures** a judge is refused, loudly, naming the
    decision — it is not accepted and then scored deterministically as if the
    judge had run, which is what this code did before the row was read.

**2. Structural facts come free and are always reported.** Whether it errored,
how many tool calls failed, how long it took, how much it cost. Those need no
assertion to be useful, and half the regressions anyone actually hits are
visible in them.

**3. A case that could not run is neither a pass nor a fail.** It is `skipped`,
counted separately, and it drags nothing into the score. Folding unrunnable
cases into *failed* makes a broken environment look like a regression and sends
someone hunting a bug that is not there; folding them into *passed* is worse,
because it is quiet. `P4-26`'s drift reporting is what makes this knowable at
all, and a suite that skipped half its cases says so in the headline rather than
in a field nobody reads.
"""
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# What an operator may assert. An allowlist, so a typo in a suite is a loud
# "unknown check" rather than a check that silently never ran — which would make
# a suite pass for the wrong reason, which is the only failure mode of an eval
# harness that actually costs anything.
CHECKS = ("contains", "not_contains", "regex", "max_tool_failures", "no_error")

# `P14-08` / `D-2026-09-18-02`. How this harness grades, on every result it
# returns. One word, because there is exactly one method — and it is written
# down precisely so that a second one cannot arrive without this field changing
# and every reader of a score noticing.
GRADING = "deterministic"

# Keys that mean "grade this with a model". Refused rather than ignored.
#
# Measured on the tree before this row: a suite carrying `{"judge": {"model":
# "gpt-4o"}}` validated clean, ran, and printed a pass rate computed entirely
# from the deterministic checks — the operator's judge was never called and
# nothing in the result said so. Silently scoring something a different way than
# the operator asked for is worse than refusing, because a pass is the one
# result nobody investigates.
JUDGE_KEYS = ("judge", "judge_model", "judge_prompt", "judge_endpoint",
              "llm_judge", "grader", "graded_by", "rubric")


def load_suites() -> List[Dict[str, Any]]:
    """Suites, from the `eval_suites` setting. Empty out of the box.

    Settings rather than a table, following `networks` (`P16-16`): a suite is a
    handful of ids and strings, edited rarely, and adding a table for it would
    be scaffolding ahead of a need. **`P14-06` is the row that decides the
    store** — when a suite outgrows a settings blob, that is the decision it was
    filed to make, not one to pre-empt here.
    """
    try:
        from src.settings import get_setting
        raw = get_setting("eval_suites", [])
    except Exception:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            logger.warning("eval_suites is not valid JSON; ignoring")
            return []
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw:
        if isinstance(entry, dict) and str(entry.get("name") or "").strip():
            out.append(entry)
    return out


def get_suite(name: str) -> Optional[Dict[str, Any]]:
    for suite in load_suites():
        if suite.get("name") == name:
            return suite
    return None


def _judge_keys_in(obj: Any) -> List[str]:
    if not isinstance(obj, dict):
        return []
    return [k for k in JUDGE_KEYS if k in obj]


def _no_judge(where: str, obj: Any) -> List[str]:
    """`P14-08`. Say no where the operator wrote it, and say why.

    The refusal names the decision rather than the field, because *"judge is not
    a key"* reads like a typo and sends someone hunting for the right spelling.
    There is no right spelling; there is a decision.
    """
    return [
        f"{where} configures {k!r}: this harness grades deterministically and "
        f"has no judge model (`P14-08` / `D-2026-09-18-02`). Assert with "
        f"{', '.join(CHECKS)} instead, or read the decision for what a judge "
        f"would have to settle first."
        for k in _judge_keys_in(obj)
    ]


def validate_suite(suite: Dict[str, Any]) -> List[str]:
    """Problems with a suite, before it costs anybody a model call."""
    problems: List[str] = []
    problems += _no_judge("suite", suite)
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        problems.append("suite has no cases")
        return problems
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            problems.append(f"case {i} is not an object")
            continue
        if not str(case.get("run_id") or "").strip():
            problems.append(f"case {i} has no run_id")
        problems += _no_judge(f"case {i}", case)
        problems += _no_judge(f"case {i}'s expect", case.get("expect"))
        for key in (case.get("expect") or {}):
            if key not in CHECKS or key in JUDGE_KEYS:
                if key in JUDGE_KEYS:
                    continue          # already refused, by name, above
                problems.append(
                    f"case {i} asserts {key!r}, which is not a check "
                    f"({', '.join(CHECKS)})")
    return problems


def _as_list(value) -> List[str]:
    if value is None:
        return []
    return [str(value)] if isinstance(value, str) else [str(v) for v in value]


def score_case(output: Optional[str], expect: Dict[str, Any],
               *, error: Optional[str] = None,
               tool_failures: int = 0) -> Dict[str, Any]:
    """Run the assertions. Returns `{passed, checks}` with one entry per check.

    Every check reports its own verdict rather than collapsing to a boolean:
    *"the suite went from 8/10 to 7/10"* is much less useful than *"case 3 stopped
    containing the word the operator was watching for"*, and the second costs
    one extra field.
    """
    text = output or ""
    checks: List[Dict[str, Any]] = []

    def add(name, ok, detail):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    if expect.get("no_error") or error:
        add("no_error", error is None, error or "no error")

    for needle in _as_list(expect.get("contains")):
        add("contains", needle in text, needle)
    for needle in _as_list(expect.get("not_contains")):
        add("not_contains", needle not in text, needle)
    for pattern in _as_list(expect.get("regex")):
        try:
            add("regex", re.search(pattern, text) is not None, pattern)
        except re.error as e:
            # A bad pattern is the suite's bug, not the run's. Reporting it as a
            # failed assertion would blame the model for the operator's typo.
            add("regex", False, f"invalid pattern {pattern!r}: {e}")

    if "max_tool_failures" in expect:
        cap = int(expect["max_tool_failures"])
        add("max_tool_failures", tool_failures <= cap,
            f"{tool_failures} failure(s), cap {cap}")

    # `checks` is empty only when there were no assertions AND no error: an
    # error always adds a `no_error` check above, so the error case is decided
    # by the list rather than by a fallback. The first version read
    # `else error is None`, which looks like it handles the errored case and is
    # unreachable when it matters — a mutation to `else True` changed nothing.
    return {"passed": all(c["passed"] for c in checks) if checks else True,
            "checks": checks}


async def run_suite(name: str, *, model: Optional[str] = None,
                    limit: int = 50) -> Dict[str, Any]:
    """Replay every case and score it. Returns the number, and how to read it."""
    from src.events import receipt
    from src.replay import replay, rerun_plan

    started = time.monotonic()
    result: Dict[str, Any] = {
        "suite": name, "model": model, "cases": [],
        "passed": 0, "failed": 0, "skipped": 0, "total": 0,
        "pass_rate": None, "drift_cases": 0, "problems": [], "headline": "",
        # `P14-08`. Set here, on every path out of this function including the
        # two refusals, because a score that does not say how it was graded is
        # exactly what this row asked us not to ship. Today there is one answer;
        # the field exists so a second one cannot be quiet.
        "grading": GRADING,
    }

    suite = get_suite(name)
    if suite is None:
        result["problems"].append(f"no suite named {name!r}")
        result["headline"] = result["problems"][0]
        return result

    problems = validate_suite(suite)
    if problems:
        # Refused rather than run: a suite with a typo'd check would otherwise
        # pass for the wrong reason, and a green number nobody can trust is
        # worse than a red one.
        result["problems"] = problems
        result["headline"] = f"{name} not run: " + "; ".join(problems)
        return result

    cases = (suite.get("cases") or [])[:max(1, limit)]
    result["total"] = len(cases)

    for case in cases:
        run_id = case["run_id"]
        expect = case.get("expect") or {}
        entry: Dict[str, Any] = {"run_id": run_id, "label": case.get("label") or run_id}

        plan = rerun_plan(run_id)
        entry["drift"] = plan.get("drift") or []
        if entry["drift"]:
            result["drift_cases"] += 1
        if not plan.get("runnable"):
            # Neither a pass nor a fail. See the module docstring.
            entry.update(status="skipped", reason="; ".join(entry["drift"]) or "not runnable")
            result["skipped"] += 1
            result["cases"].append(entry)
            continue

        run = await replay(run_id, model=model)
        new_run = run.get("run_id")
        tool_failures = 0
        if new_run:
            tool_failures = (receipt(new_run).get("totals") or {}).get("tool_failures", 0)

        scored = score_case(run.get("output"), expect,
                            error=run.get("error"), tool_failures=tool_failures)
        entry.update(status="passed" if scored["passed"] else "failed",
                     checks=scored["checks"], replay_run_id=new_run,
                     error=run.get("error"), tool_failures=tool_failures,
                     output_chars=len(run.get("output") or ""))

        # `P14-04` — a result is a diff. Attached only to FAILURES, and only
        # the unasked-for half.
        #
        # "Case 3 failed" sends someone to read a transcript. "Case 3 failed,
        # and the tool schema changed" is the answer. Running it on passes too
        # would double the cost of a green suite to produce something nobody
        # opens, and printing the chosen and outcome entries here would bury the
        # cause under its own consequences — `P4-28` already ranks them, so this
        # takes the top of that ranking rather than re-deciding it.
        if not scored["passed"] and new_run:
            try:
                from src.receipt_diff import diff_receipts, INFLICTED
                d = diff_receipts(run_id, new_run)
                entry["why"] = d.get("headline")
                entry["changed"] = [x for x in d.get("differences", [])
                                    if x["kind"] == INFLICTED]
            except Exception as e:
                logger.debug("diff for failed case %s: %s", run_id, e)
        result["passed" if scored["passed"] else "failed"] += 1
        result["cases"].append(entry)

    scored_count = result["passed"] + result["failed"]
    result["pass_rate"] = (result["passed"] / scored_count) if scored_count else None
    result["seconds"] = round(time.monotonic() - started, 2)
    result["headline"] = _headline(result)
    return result


def _headline(result: Dict[str, Any]) -> str:
    """One line, and it refuses to print a rate it cannot stand behind.

    `x/y` over the cases that RAN, with skipped and drifted called out beside it
    — never folded in. A pass rate computed over cases half of which never
    executed is a number that reads like evidence and is not.
    """
    scored = result["passed"] + result["failed"]
    if not scored:
        return (f"{result['suite']}: nothing ran — {result['skipped']} case(s) "
                f"could not be reproduced")
    line = f"{result['suite']}: {result['passed']}/{scored} passed"
    if result["skipped"]:
        line += f" · {result['skipped']} skipped (could not be reproduced)"
    if result["drift_cases"]:
        line += f" · {result['drift_cases']} ran with drift"
    return line
