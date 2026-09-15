# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B78` + `B84` — the six run statuses, derived once, and glossed before a
person reads them.

`B13` gave the six values one WORD table. This closes the other three things
derived from them — the tone, the dot class, and "is this run over" — and the
two surfaces that were still showing the stored value itself.

**Measured before the change** (`tests/harness/*`, recomputed 2026-09-15, not
quoted from the row)::

    run history      success → the word "success", no tooltip, dot #4caf50
                     skipped → the word "skipped", no tooltip, dot #888
                     aborted → the word "aborted", no tooltip, dot #888
                     running → the word "running", no tooltip, dot #888
                     queued  → the word "queued",  no tooltip, dot #888

Four of the six drew the same grey dot, so an aborted run and a queued one were
the same mark in the list whose only job is to say what happened; and every one
of the six printed the stored enum at the user, lowercase and unglossed.

    last-run badge   error   → "Failed (no detail)"
                     success → "Success (no output)"
                     skipped → "skipped (no detail)"      ← the stored value
                     aborted → "aborted (no detail)"      ← the stored value

    notifications    success → toast  "Task finished: A"
                     error   → ERROR  "Task failed: B"   + failure dot
                     skipped → ERROR  "Task failed: C"   + failure dot
                     aborted → ERROR  "Task failed: D"   + failure dot

    dot class        failed  → panel "info", Activity view "error"

**What the row got wrong, and it matters.** `B78` says the notification client
"announces a `skipped` or `aborted` llm task, which `_execute_task_locked` does
notify about, as a failure". Traced: it does NOT notify about either. Both
terminal branches in `src/task_scheduler.py` — `except asyncio.CancelledError`
(`aborted`) and `except TaskNoop` (`skipped`) — `return` before the notify block
at `:1255`, and the only other two callers pass the literal `"error"`. So the
lie was reachable-in-principle and not on screen, which is exactly the shape
`B07` left behind on purpose: it had to leave the admin-privilege refusal SILENT
because this line would have called it a failure. Making the client honest is
what lets that hole be closed later; a test below pins the third branch so it
cannot be quietly collapsed back into two.

**What does NOT change**, and is asserted here rather than hoped for: the
Completed tab's contents, the word every surface shows for a queued message, and
the two sentences the badge already had.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ROW = ROOT / "tests" / "harness" / "activity_row_status.js"
WORDS = ROOT / "tests" / "harness" / "queue_status_words.js"
WORDS_JS = ROOT / "static" / "js" / "runStatus.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

SIX = ["queued", "running", "success", "error", "skipped", "aborted"]


def _h(harness: Path, *args):
    proc = subprocess.run(["node", str(harness), *args],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _code(name: str) -> str:
    """A JS file with its comments blanked. `Law 20`: a rule about code has to
    read code, and every file below documents the ladder it used to own — a
    file-wide substring search would find the words in the prose that explains
    why they are not there any more (`B87`, same trap, one day earlier)."""
    src = (ROOT / "static" / "js" / name).read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


# ---------------------------------------------------------------------------
# One vocabulary, two languages
# ---------------------------------------------------------------------------

def test_python_and_the_client_hold_the_same_six_values():
    """`B78`'s `Verify`: the six exist once and are derivable from that one
    place by Python and by the client. This is the check that was missing when
    `_pollTaskNotifications` came to know two of them and `_isFinishedRun`
    three."""
    from core.database import (
        TASK_RUN_STATUSES, TASK_RUN_ACTIVE_STATUSES, TASK_RUN_TERMINAL_STATUSES,
    )
    out = _h_eval()
    assert list(TASK_RUN_STATUSES) == SIX
    assert list(TASK_RUN_ACTIVE_STATUSES) == ["queued", "running"]
    assert out["six"] == list(TASK_RUN_STATUSES), "JS and Python disagree on the six"
    assert out["active"] == list(TASK_RUN_ACTIVE_STATUSES)
    # Derived, not re-typed: a seventh value lands in exactly one of the two.
    assert list(TASK_RUN_TERMINAL_STATUSES) == [
        s for s in TASK_RUN_STATUSES if s not in TASK_RUN_ACTIVE_STATUSES
    ]
    assert set(TASK_RUN_ACTIVE_STATUSES) & set(TASK_RUN_TERMINAL_STATUSES) == set()


def _h_eval():
    proc = subprocess.run(
        ["node", "--input-type=module", "--eval",
         "import { RUN_STATUSES, RUN_ACTIVE_STATUSES, runStatusDotClass, isRunFinished }"
         " from '%s';\n"
         "console.log(JSON.stringify({ six: RUN_STATUSES, active: RUN_ACTIVE_STATUSES,"
         " dots: Object.fromEntries(RUN_STATUSES.concat(['failed','nope'])"
         "   .map(s => [s, runStatusDotClass(s)])),"
         " finished: Object.fromEntries(RUN_STATUSES.map(s => [s, isRunFinished(s)])) }));"
         % WORDS_JS],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_queue_depth_metric_reads_the_constant_rather_than_retyping_it():
    """`src/metrics_export.py` re-typed `("queued", "running")` inline — the
    drift had started at the one place the guard rail was put. A metric named
    "queue depth" that learns a new in-flight status later than the scheduler
    does reports a number that is quietly wrong."""
    src = (ROOT / "src" / "metrics_export.py").read_text(encoding="utf-8")
    body = re.sub(r"#.*$", "", src, flags=re.M)
    assert "TASK_RUN_ACTIVE_STATUSES" in body
    assert '("queued", "running")' not in body, "the inline pair is back"


# ---------------------------------------------------------------------------
# One ladder, not two (`B78`, the `queuePanel` half)
# ---------------------------------------------------------------------------

def test_the_panel_and_the_activity_view_name_the_same_dot():
    """Measured before: `failed` was `info` in the docked panel and `error` in
    the Activity view, off one input, because the panel cannot import `tasks.js`
    and had written the ladder out by hand. Read off the emitted markup, because
    `buildRow` puts the class on the row AND the dot."""
    out = _h(WORDS, "classes")
    for status in SIX:
        assert out[status]["agree"], f"{status}: {out[status]}"
        assert out[status]["panel"] == out[status]["panelRow"], (
            f"{status}: the panel's row and its dot disagree with each other"
        )
    assert out["failed"]["panel"] == "error" == out["failed"]["activity"], (
        "legacy `failed` is what the two ladders disagreed about"
    )
    assert out["success"]["panel"] == "ok", "`.task-log-status-success` is not a rule"


def test_an_unknown_status_still_gets_two_different_answers_on_purpose():
    """The one divergence that stays, so nobody 'fixes' it into a third ladder:
    the Activity view text-scans the row's result, which is how rows written
    before the status column existed still get a colour, and the docked panel
    has no result text to scan and says `info`. The shared function answers `''`
    rather than picking one of the two for both (`Law 1` — choosing here would
    delete the text-scan fallback)."""
    assert _h_eval()["dots"]["nope"] == "", "the shared function must not guess"
    out = _h(WORDS, "classes")
    assert out["not-a-status"]["panel"] == "info"
    assert out["not-a-status"]["activity"] == "error", (
        "the stubbed text-scan says error for any text; the point is that it RAN"
    )


def test_neither_module_spells_the_status_ladder_for_itself_any_more():
    src = _code("queuePanel.js")
    assert "runStatusDotClass" in src, "the panel does not use the shared ladder"
    assert "'skipped'" not in src and "'aborted'" not in src, (
        "the panel is naming status values again"
    )
    tasks = _code("tasks.js")
    assert "function runStatusTone" not in tasks, (
        "the tone is defined in runStatus.js; a second definition here is the "
        "defect this row closed"
    )
    assert "export { runStatusTone }" in tasks, (
        "four call sites and two tests import it from here; taking the export "
        "away to move the function is a subtraction"
    )


# ---------------------------------------------------------------------------
# `B84` — no surface shows a person a stored value verbatim
# ---------------------------------------------------------------------------

RUNS = json.dumps([{"status": s, "result": "out", "started_at": "2026-09-15T10:00:00Z"}
                   for s in SIX])

HISTORY_WORDS = {"queued": "Queued", "running": "Running", "success": "Success",
                 "error": "Failed", "skipped": "Skipped", "aborted": "Stopped"}


def test_the_run_history_shows_a_word_and_not_the_stored_enum():
    """`_showRunHistory` printed `<span>${run.status}</span>` — *success*,
    *aborted*, lowercase and unglossed — to a person working out why a task did
    not do what they expected."""
    rows = _h(ROW, "history", RUNS)
    assert [r["status"] for r in rows] == SIX
    for r in rows:
        assert r["word"] == HISTORY_WORDS[r["status"]], r
        assert r["word"] != r["status"], "the raw value is still what is shown"


def test_the_stored_value_is_still_reachable_from_that_row():
    """`Law 1`. The gloss is added; the fact is not taken away. Somebody reads
    that word off the screen to match a log line, and a word they cannot map
    back to a row value would be a subtraction dressed as an improvement."""
    for r in _h(ROW, "history", RUNS):
        assert r["title"] == r["status"], r


def test_the_history_dot_separates_an_in_flight_run_from_a_finished_one():
    """Measured before: `queued`, `running`, `skipped` and `aborted` all fell
    through `_statusDot`'s map to the same `#888`, so four of the six drew one
    mark. The colours are the sheet's own `.task-log-status-*` values, so the
    same run cannot be amber in the Activity list and grey in its history."""
    dots = {r["status"]: r["dot"] for r in _h(ROW, "history", RUNS)}
    assert dots["queued"] == "#fbbf24" and dots["running"] == "#60a5fa"
    assert dots["queued"] != dots["skipped"] and dots["running"] != dots["aborted"]
    # `skipped` and `aborted` deliberately share the neutral: the sheet splits
    # them with a dashed border, which an 8px inline span has no room for.
    assert dots["skipped"] == dots["aborted"] == "#888"
    # Five distinct colours across the six, against three before the change.
    assert len(set(dots.values())) == 5, dots


BADGE_EMPTY = {
    "success": "Success (no output)",   # byte-identical to what shipped
    "error": "Failed (no detail)",      # byte-identical to what shipped
    "skipped": "Skipped (no detail)",   # was `skipped (no detail)`
    "aborted": "Stopped (no detail)",   # was `aborted (no detail)`
    "running": "Running (no detail)",
    "queued": "Queued (no detail)",
}


@pytest.mark.parametrize("status,sentence", sorted(BADGE_EMPTY.items()))
def test_the_last_run_badge_uses_one_register(status, sentence):
    """Three registers in six lines: *Failed (no detail)*, *Success (no
    output)*, and the raw `${task.last_run_status} (no detail)`. The first two
    are unchanged — they are the words the shared table's `job` column was
    filled FROM, so moving them cannot alter the string."""
    out = _h(ROW, "badge", json.dumps({"last_run_status": status}))
    assert sentence in out["html"], out["html"]


def test_the_badges_mark_and_colour_are_untouched():
    """`B07` decided these three outcomes. `B84` changes the words beside them
    and must not move the marks, or it has quietly reopened a closed row."""
    marks = {s: _h(ROW, "badge", json.dumps({"last_run_status": s}))
             for s in SIX}
    assert marks["success"]["mark"] == "✓" and marks["success"]["green"]
    assert marks["error"]["mark"] == "✗" and marks["error"]["red"]
    for s in ("skipped", "aborted", "queued", "running"):
        assert marks[s]["mark"] == "·", s
        assert not marks[s]["red"] and not marks[s]["green"], s


# ---------------------------------------------------------------------------
# `B78` — no consumer renders a non-failure as a failure
# ---------------------------------------------------------------------------

NOTES = json.dumps([{"status": s, "task_name": s.upper()} for s in
                    ("success", "error", "skipped", "aborted")])


def test_a_non_failure_is_not_announced_as_a_failure():
    """Measured before: `skipped` and `aborted` both produced a red
    `showError` reading *"Task failed: <name>"* and raised the failure dot.
    `core/database.py` is explicit that folding either into `error` corrupts
    every error-rate statistic; this was that corruption arriving through the
    notification channel."""
    out = _h(ROW, "notify", NOTES)
    by = {s["msg"].split(": ")[1]: s for s in out["said"]}
    assert by["SKIPPED"] == {"how": "toast", "msg": "Task skipped: SKIPPED"}
    assert by["ABORTED"] == {"how": "toast", "msg": "Task stopped: ABORTED"}
    assert "fail" not in by["SKIPPED"]["msg"].lower()
    assert "fail" not in by["ABORTED"]["msg"].lower()


def test_the_two_outcomes_that_already_worked_are_word_for_word_the_same():
    out = _h(ROW, "notify", NOTES)
    by = {s["msg"].split(": ")[1]: s for s in out["said"]}
    assert by["SUCCESS"] == {"how": "toast", "msg": "Task finished: SUCCESS"}
    assert by["ERROR"] == {"how": "error", "msg": "Task failed: ERROR"}


def test_only_a_real_failure_raises_the_failure_dot():
    """The half a message cannot show: whether the red dot on the Tasks button
    goes up. It went up for all three non-`success` statuses before."""
    quiet = _h(ROW, "notify", json.dumps(
        [{"status": s, "task_name": "T"} for s in ("success", "skipped", "aborted")]))
    assert quiet["failure"] is False, quiet
    loud = _h(ROW, "notify", json.dumps([{"status": "error", "task_name": "T"}]))
    assert loud["failure"] is True


def test_an_unrecognised_status_still_shouts():
    """`Law 1`. Quietening something we cannot name is the wrong direction to be
    wrong in: a status outside the six is a bug, and a bug should be loud. Only
    the two values `core/database.py` NAMES as non-failures are quieted."""
    out = _h(ROW, "notify", json.dumps([{"status": "weird", "task_name": "E"}]))
    assert out["said"] == [{"how": "error", "msg": "Task failed: E"}]
    assert out["failure"] is True


# ---------------------------------------------------------------------------
# `_isFinishedRun` — the claim the row got backwards
# ---------------------------------------------------------------------------

COMPLETED_CASES = json.dumps(
    [{"status": s, "kind": "llm", "result": "some output"} for s in SIX])


def test_finished_now_means_what_the_stored_vocabulary_says_it_means():
    """`B78` calls this a consumer that knows fewer than six. It had one caller,
    and for that caller the exclusion of `skipped` was RIGHT and the name was
    wrong — so the fix is the name, not the filter."""
    out = {r["status"]: r for r in _h(ROW, "completed", COMPLETED_CASES)}
    assert out["skipped"]["finished"] is True, "a terminal run is finished"
    for s in ("success", "error", "skipped", "aborted"):
        assert out[s]["finished"] is True, s
    for s in ("queued", "running"):
        assert out[s]["finished"] is False, s


def test_the_completed_tab_shows_exactly_what_it_showed_before():
    """`Law 1`, measured against the pre-change tree: success, error and aborted
    in; skipped, queued and running out. A skipped run's only text is the reason
    it did not run — *"Task no longer active (status=paused)"*, which
    `_runToActivityEntry` promotes into `result` — and that is not an output a
    person can open in a chat, whatever the tab's filter is named."""
    out = {r["status"]: r for r in _h(ROW, "completed", COMPLETED_CASES)}
    assert [s for s in SIX if out[s]["inCompletedTab"]] == ["success", "error", "aborted"]
