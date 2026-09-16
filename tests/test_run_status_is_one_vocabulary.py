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
import sys
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
    """Measured before `B78`: `queued`, `running`, `skipped` and `aborted` all
    fell through `_statusDot`'s map to the same `#888`, so four of the six drew
    one mark. `B78` gave them four colours; `B110` replaced the colours with the
    sheet's own class, so the six now draw six distinct marks — `skipped` and
    `aborted` were sharing a grey only because an 8px inline span had no room
    for the dashed border `.task-log-status-aborted` declares."""
    dots = {r["status"]: r["dot"] for r in _h(ROW, "history", RUNS)}
    assert dots["queued"] == "queued" and dots["running"] == "running"
    assert dots["queued"] != dots["skipped"] and dots["running"] != dots["aborted"]
    assert dots["skipped"] != dots["aborted"], (
        "the sheet splits these two and the history row now uses the sheet"
    )
    assert len(set(dots.values())) == 6, dots


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


# ---------------------------------------------------------------------------
# `B110` — one palette, and it is the stylesheet
# ---------------------------------------------------------------------------

SHEET = ROOT / "static" / "style.css"


def _sheet_rules(prefix: str) -> set[str]:
    """The suffixes `style.css` declares for a `.<prefix>-*` family, read out of
    the sheet. Derived so a rule added or renamed there moves the test with it
    rather than leaving a hand-copied list behind."""
    css = re.sub(r"/\*.*?\*/", "", SHEET.read_text(encoding="utf-8"), flags=re.S)
    return set(re.findall(rf"\.{re.escape(prefix)}-([a-z]+)\s*[,{{ ]", css))


def test_the_history_dot_and_the_activity_dot_are_drawn_by_the_same_rule():
    """`B110`'s `Verify`, both halves in one assertion.

    Measured before: `_showRunHistory` emitted `<span style="…background:#fbbf24
    …">` from a map `tasks.js` held itself, while the Activity row emitted
    `<span class="task-log-status task-log-status-queued">` — the same colour,
    written twice, in two languages. A theme edit moved one of them.
    """
    history = {r["status"]: r["dot"] for r in _h(ROW, "history", RUNS)}
    activity = {}
    for status in SIX:
        row = _h(ROW, "row", json.dumps(
            {"status": status, "kind": "llm", "result": "out", "taskName": "T"}))
        activity[status] = row["dot"]
    assert history == activity, (
        "the same run draws a different mark in its own history than in Activity"
    )
    declared = _sheet_rules("task-log-status")
    for status, cls in history.items():
        assert cls in declared, (
            f"{status} asks for .task-log-status-{cls}, which the sheet does not declare"
        )


def test_tasks_js_no_longer_holds_a_colour_of_its_own():
    """The other half of the `Verify`. Comments are blanked first: this file and
    `tasks.js` both spell the old hex values out while explaining why they are
    gone, and a file-wide search would find the prose (`B87`, `Law 20`)."""
    src = _code("tasks.js")
    found = re.findall(r"#[0-9a-fA-F]{3,8}\b", src)
    assert found == [], f"tasks.js names colours again: {found}"
    assert "_RUN_DOT_COLORS" not in src, "the private palette is back"
    assert "task-log-status" in src, "the dot must take the shared class"
    assert "task-lastrun-" in src, "the last-run badge must take the shared classes"


def test_the_last_run_badges_three_variants_exist_in_the_sheet():
    """`B110` moved the badge's stripe, tint and glyph colour out of an inline
    style built in JS. The three variants have to land on rules that exist, or
    the badge loses its colour entirely — which a JS-only test cannot see."""
    declared = _sheet_rules("task-lastrun")
    assert {"ok", "error", "info"} <= declared, declared
    for status in SIX:
        out = _h(ROW, "badge", json.dumps({"last_run_status": status}))
        variant = out["cls"].split("task-lastrun-")[-1].strip()
        assert variant in declared, f"{status} → .task-lastrun-{variant} is not a rule"


def test_the_history_row_no_longer_calls_a_successful_run_active():
    """`_showRunHistory` passed the TASK status `'active'` to `_statusDot` for a
    successful RUN — the substitution that made the map look like it needed two
    vocabularies. The row's own status goes in now, and `active` is not one."""
    rows = _h(ROW, "history", RUNS)
    assert {r["status"]: r["dot"] for r in rows}["success"] == "ok"
    assert "active" not in {r["dot"] for r in rows}


# ---------------------------------------------------------------------------
# `B111` — a seventh status cannot be written unnoticed
# ---------------------------------------------------------------------------

CHECKER = ROOT / ".pantheon" / "check-run-statuses.py"


def _checker(tree: Path = ROOT, *args):
    proc = subprocess.run([sys.executable, str(tree / ".pantheon" / "check-run-statuses.py"),
                           *args], cwd=str(tree), capture_output=True, text=True, timeout=300)
    return proc.returncode, proc.stdout + proc.stderr


def test_the_checker_passes_on_this_tree():
    code, out = _checker()
    assert code == 0, out


def _worktree(tmp_path: Path) -> Path:
    """A copy of the tracked tree, so a mutation can be measured without
    editing the tree a suite run is reading (`Law 19`)."""
    # `--others --exclude-standard` as well as the index: the checker itself is
    # a new file on the branch that adds it, and a copy without it cannot run.
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120).stdout.split()
    dest = tmp_path / "tree"
    for rel in files:
        if not (rel.endswith(".py") or rel.endswith(".js")):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / rel).read_bytes())
    return dest


@pytest.mark.parametrize("where,old,new,expect", [
    # `B111`'s `Verify`, word for word: adding `run.status = "cancelled"` to
    # `src/task_scheduler.py` fails a check by name.
    ("src/task_scheduler.py", 'run.status = "skipped"',
     'run.status = "cancelled"', "cancelled"),
    # The other shape the row names: a value declared in one language only.
    ("static/js/runStatus.js", "'aborted'];", "'aborted', 'cancelled'];", "cancelled"),
    # And the one `B84` closed, re-armed: a status with no word to show for it.
    ("static/js/runStatus.js", "  aborted:  ['Stopped',  'Stopped'],\n", "", "aborted"),
])
def test_a_seventh_status_fails_the_checker_by_name(tmp_path, where, old, new, expect):
    tree = _worktree(tmp_path)
    assert _checker(tree)[0] == 0, "the copy must be clean before it is mutated"
    src = (tree / where).read_text(encoding="utf-8")
    assert old in src, f"anchor missing in {where}"
    (tree / where).write_text(src.replace(old, new, 1), encoding="utf-8")
    code, out = _checker(tree)
    assert code == 1, f"nothing failed:\n{out}"
    assert expect in out, out


# ---------------------------------------------------------------------------
# `B171` — a run that answered nothing does not get an assistant turn
# ---------------------------------------------------------------------------

def _open(entry: dict) -> dict:
    """Press *Open in chat* on `entry` and report what reached the session."""
    return _h(ROW, "open", json.dumps(entry))


def test_a_run_that_produced_no_answer_seeds_no_assistant_message():
    """`B171`'s `Verify`, driven: the real `_openResultInChat` runs against a
    stubbed session API and the injected payload is read back.

    The statuses are not typed out — they are the ones `runLeftNoAnswer` picks
    out of the vocabulary Python declares, so a seventh status that answers
    nothing is covered the day it is added."""
    from core.database import TASK_RUN_STATUSES

    no_answer = [s for s in TASK_RUN_STATUSES if _h(ROW, "tone")[s] in ("error", "info")]
    assert set(no_answer) == {"error", "skipped", "aborted"}, no_answer
    for status in no_answer:
        out = _open({"status": status, "kind": "llm", "taskName": "Nightly tidy",
                     "result": "ValueError: boom"})
        assert out["assistantSaid"] == [], (
            f"{status}: the run's text is still attributed to the assistant")
        assert out["roles"] == ["user"], f"{status}: {out['roles']}"
        body = out["messages"][0]["content"]
        # The text is still there — the row is about attribution, not about
        # hiding the error (`Law 1`).
        assert "ValueError: boom" in body
        # And the note says which outcome it was, in the shared table's word.
        word = {"error": "Failed", "skipped": "Skipped", "aborted": "Stopped"}[status]
        assert f"Run status: {word}" in body, body


def test_a_successful_run_still_opens_exactly_as_it_did():
    """`Law 1`. The success path is the one case where the stored text really is
    the assistant's turn, and nothing about it moves."""
    out = _open({"status": "success", "kind": "llm", "taskName": "Nightly tidy",
                 "result": "All clear."})
    assert out["roles"] == ["user", "assistant"]
    assert out["assistantSaid"] == ["All clear."]
    assert out["messages"][0]["content"] == (
        'Here is the latest run of my scheduled task "Nightly tidy". '
        "Let's review it.")


def test_a_backticked_traceback_cannot_break_out_of_its_quote():
    """The text being quoted is the kind that contains backticks. A fixed three
    would let a fenced block inside a traceback close the quote early and put
    the tail back into the prose the model reads as instructions."""
    out = _open({"status": "error", "kind": "llm", "taskName": "T",
                 "result": "boom\n```\ninner\n```\ntail"})
    body = out["messages"][0]["content"]
    fence = body.split("\n\n", 1)[1].split("\n", 1)[0]
    assert len(fence) >= 4 and set(fence) == {"`"}, body
    assert body.rstrip().endswith(fence)
    assert body.count(fence) == 2, "the quote opens and closes exactly once"


def test_both_surfaces_describe_the_open_control_the_same_way():
    """`Law 13`. The Activity row and the Completed tab each build this button,
    and before this row one said *Open in chat* and the other *Open chat* while
    both promised a result to read on a run that had none. The two renderers are
    run and their markup compared — not the expression that built it."""
    row = _h(ROW, "row", json.dumps(
        {"status": "error", "kind": "llm", "taskName": "A", "result": "boom"}))
    tab = _h(ROW, "tab", json.dumps(
        [{"status": "error", "task_type": "llm", "task_name": "A", "error": "boom"}]))
    assert tab["rows"], tab
    assert row["openLabel"] == tab["rows"][0]["openLabel"] == "Ask about this"
    assert row["openTitle"] == tab["rows"][0]["openTitle"]
    assert "no answer" in row["openTitle"]
    ok_row = _h(ROW, "row", json.dumps(
        {"status": "success", "kind": "llm", "taskName": "A", "result": "done"}))
    ok_tab = _h(ROW, "tab", json.dumps(
        [{"status": "success", "task_type": "llm", "task_name": "A", "result": "done"}]))
    assert ok_row["openLabel"] == ok_tab["rows"][0]["openLabel"] == "Open in chat"
    assert ok_row["openTitle"] == ok_tab["rows"][0]["openTitle"]


def test_a_source_row_keeps_its_own_sentence():
    """`Law 1`. A queued composer message has no run status and no result; its
    button goes wherever the source says, and `B171` must not take that over."""
    out = _h(ROW, "row", json.dumps(
        {"status": "queued", "kind": "llm", "taskName": "Queued message",
         "result": "", "onOpen": None, "openTitle": "Go to that chat"}))
    # `onOpen` cannot survive JSON, so assert the shape that does reach the
    # renderer: a queued row with no result draws no open control at all, which
    # is the pre-existing rule this row did not touch.
    assert out["openLabel"] is None


# ---------------------------------------------------------------------------
# `B170` — and raw SQL, which the ORM walk cannot see
# ---------------------------------------------------------------------------

_MIGRATION_SQL = "UPDATE task_runs SET status = 'skipped' "
_MIGRATION_WHERE = "WHERE status = 'error' AND error LIKE :pat"


def test_the_raw_sql_status_write_in_the_tree_is_found_and_classified():
    """The measurement, driven rather than asserted: the detector is imported
    and run over the real tree, and what it finds is compared with the register.

    `B170` said there were two candidates, `core/database.py` and the test that
    asserts against it. Re-measured, there is ONE: the test's SQL is
    ``SELECT COUNT(*) FROM task_runs WHERE error LIKE :pat``, which names the
    table and never the column, so it is not a status site at all."""
    checker = _load_checker()
    sites = {
        (rel, fn): lits
        for rel in checker._python_files()
        if rel != checker.SELF
        for _line, fn, lits in checker.raw_sql_status_sites(ROOT / rel)
    }
    assert set(sites) == set(checker.RAW_SQL_STATUS_SITES), (
        "the register and the tree disagree about which raw-SQL statements "
        f"touch task_runs.status: {sorted(sites)}")
    live = {k: v for k, v in sites.items()
            if checker.RAW_SQL_STATUS_SITES[k][0] == checker.LIVE}
    assert live == {("core/database.py", "_migrate_reclassify_admin_refusals"):
                    ["error", "skipped"]}
    # Every `fixture` is in this file, which is the only honest reason to
    # classify a status write as not-a-write: it is the material this checker
    # is fed to prove it fails.
    for rel, _fn in set(sites) - set(live):
        assert rel == "tests/test_run_status_is_one_vocabulary.py", rel
    for kind, why in checker.RAW_SQL_STATUS_SITES.values():
        assert kind in (checker.LIVE, checker.FIXTURE), kind
        assert len(why.split()) >= 10, f"the reason is not a reason: {why!r}"


def test_the_raw_sql_scan_reads_statements_and_not_prose():
    """`Law 20` from the other side. `core/database.py`'s migration spells its
    own statement out in a docstring, this roadmap's rows quote it, and this
    checker's diagnostics name the table and the column — so a scan that read
    every string in a file would report all three. Only strings reachable from
    a call or an assignment are read; a docstring and a comment are neither."""
    checker = _load_checker()
    prose = ROOT / "tests" / "__b170_prose_only.py"
    prose.write_text(
        '"""Re-files rows with UPDATE task_runs SET status = \'cancelled\'."""\n'
        "# UPDATE task_runs SET status = 'cancelled' WHERE status = 'error'\n"
        "def f():\n"
        '    """UPDATE task_runs SET status = \'cancelled\'"""\n'
        "    return 1\n", encoding="utf-8")
    try:
        assert checker.raw_sql_status_sites(prose) == []
    finally:
        prose.unlink()
    # And the statement form IS found, in the same file shape, so the test above
    # is not passing because the detector is broken.
    live = ROOT / "tests" / "__b170_statement.py"
    live.write_text(
        "def g(conn):\n"
        "    return conn.execute(\"UPDATE task_runs SET status = 'cancelled'\")\n",
        encoding="utf-8")
    try:
        found = checker.raw_sql_status_sites(live)
        assert [(fn, lits) for _l, fn, lits in found] == [("g", ["cancelled"])]
    finally:
        live.unlink()


@pytest.mark.parametrize("old,new,expect", [
    # `B170`'s `Verify`, word for word: the migration's literal moved outside
    # the six fails `check-run-statuses` by name. Before this row the checker
    # exited 0 on exactly this tree.
    (_MIGRATION_SQL, "UPDATE task_runs SET status = 'cancelled' ", "cancelled"),
    # The chain the row is actually about: a SECOND migration written the same
    # way. It is `skipped` here, which is IN the vocabulary — so what has to
    # fail is the absence of a decision about it, not the value.
    ("def _migrate_reclassify_admin_refusals():",
     "def _repair_stuck_runs():\n"
     "    with engine.connect() as conn:\n"
     "        conn.execute(text(\"UPDATE task_runs SET status = 'skipped' "
     "WHERE status = 'running'\"))\n\n\n"
     "def _migrate_reclassify_admin_refusals():",
     "_repair_stuck_runs"),
])
def test_a_raw_sql_status_write_fails_the_checker_by_name(tmp_path, old, new, expect):
    tree = _worktree(tmp_path)
    assert _checker(tree)[0] == 0, "the copy must be clean before it is mutated"
    src = (tree / "core" / "database.py").read_text(encoding="utf-8")
    assert old in src, "anchor missing in core/database.py"
    (tree / "core" / "database.py").write_text(src.replace(old, new, 1), encoding="utf-8")
    code, out = _checker(tree)
    assert code == 1, f"nothing failed:\n{out}"
    assert expect in out, out


def test_the_raw_sql_register_stays_a_description_of_the_tree(tmp_path):
    """`check-config-writes.py`'s other half, and the reason a register is not
    just a comment: an entry that no longer matches anything is a decision about
    code that is gone, and it is how a register rots into a list nobody trusts."""
    tree = _worktree(tmp_path)
    src = (tree / "core" / "database.py").read_text(encoding="utf-8")
    whole = _MIGRATION_SQL + '"\n                    "' + _MIGRATION_WHERE
    assert whole in src, "the migration statement is not spelled the way this cuts it"
    (tree / "core" / "database.py").write_text(
        src.replace(whole, "SELECT 1 FROM task_runs WHERE error LIKE :pat", 1),
        encoding="utf-8")
    code, out = _checker(tree)
    assert code == 1, f"nothing failed:\n{out}"
    assert "RAW_SQL_STATUS_SITES classifies" in out, out


def _load_checker():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_check_run_statuses", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_stored_status_survives_the_whole_client_derivation():
    """`Law 20` — the checker reads the two tables, this drives the four
    functions that read them. The chain `B111` names is `runStatusTone`
    answering `null` for a value nobody declared, which then loses the dot, the
    word and the notification wording; so every status the DATABASE declares is
    pushed through all four, and the six are never typed out here."""
    from core.database import TASK_RUN_STATUSES

    proc = subprocess.run(
        ["node", "--input-type=module", "--eval",
         "import { runStatusTone, runStatusDotClass, runStatusLabel, RUN_SUBJECTS }"
         " from '%s';\n"
         "const s = JSON.parse(process.argv[1]);\n"
         "console.log(JSON.stringify(Object.fromEntries(s.map(x => [x, {"
         "  tone: runStatusTone(x), dot: runStatusDotClass(x),"
         "  words: RUN_SUBJECTS.map(sub => runStatusLabel(x, sub)) }]))));"
         % WORDS_JS, "--", json.dumps(list(TASK_RUN_STATUSES))],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    for status, got in out.items():
        assert got["tone"], f"{status}: no tone — the Errors chip cannot score it"
        assert got["dot"], f"{status}: no dot class — the row draws the neutral"
        assert all(w and w != status for w in got["words"]), (
            f"{status}: a subject shows the stored value at the user: {got['words']}")


# ---------------------------------------------------------------------------
# `B112` — which outcomes are worth telling the owner about, stated once
# ---------------------------------------------------------------------------

def test_every_status_has_a_notification_decision_and_a_reason():
    """`B112`'s `Verify`, first half. The answer used to be three `return`s: two
    terminal branches left `_execute_task_locked` before the notify block, so
    nothing said whether the silence was a decision. Every status carries an
    entry now, so a seventh cannot default to a silent no."""
    from core.database import TASK_RUN_NOTIFY, TASK_RUN_STATUSES, TASK_RUN_NOTIFY_STATUSES

    assert set(TASK_RUN_NOTIFY) == set(TASK_RUN_STATUSES)
    for status, (notify, why) in TASK_RUN_NOTIFY.items():
        assert isinstance(notify, bool), status
        assert len(why.split()) >= 8, f"{status}: the reason is not a reason: {why!r}"
    # Derived, not re-typed.
    assert TASK_RUN_NOTIFY_STATUSES == tuple(
        s for s in TASK_RUN_STATUSES if TASK_RUN_NOTIFY[s][0])
    # The decision this row made, so changing it is a deliberate edit here.
    assert TASK_RUN_NOTIFY_STATUSES == ("success", "error", "skipped")


def test_no_status_is_in_flight_and_notifiable_at_once():
    from core.database import TASK_RUN_ACTIVE_STATUSES, TASK_RUN_NOTIFY_STATUSES

    assert not set(TASK_RUN_ACTIVE_STATUSES) & set(TASK_RUN_NOTIFY_STATUSES)


def test_the_scheduler_reads_the_policy_rather_than_naming_statuses():
    """`Law 13`. Every terminal branch calls `_notify_run_outcome`, including the
    `aborted` one that stays quiet — the silence has to be the policy's answer,
    or flipping an entry in the table changes a comment and nothing else."""
    src = (ROOT / "src" / "task_scheduler.py").read_text(encoding="utf-8")
    body = re.sub(r"#.*$", "", src, flags=re.M)
    body = re.sub(r'"""(?:.|\n)*?"""', "", body)
    assert body.count("_notify_run_outcome(") >= 5, (
        "every terminal branch calls it, plus the definition")
    assert "TASK_RUN_NOTIFY" in body, "the success/error gate must read the policy too"
    assert 'aborted"' in body and '_notify_run_outcome(task, "aborted"' in body, (
        "the aborted branch must ASK and be told no, not simply return")


def test_an_abort_stays_quiet_and_says_where_that_is_decided():
    """The decision `B112` made in the other direction. A restart sweep aborts
    every in-flight run on every boot; toasting that is the noise the row exists
    to avoid, and the reason has to be on the tree rather than in a commit."""
    from core.database import TASK_RUN_NOTIFY

    notify, why = TASK_RUN_NOTIFY["aborted"]
    assert notify is False
    assert "restart" in why.lower()


# ---------------------------------------------------------------------------
# `B113` — the Completed tab's caption and its filter say the same thing
# ---------------------------------------------------------------------------

TAB_RUNS = json.dumps([
    {"status": "success", "task_type": "llm", "task_name": "S", "result": "the answer"},
    {"status": "error", "task_type": "llm", "task_name": "E", "error": "ValueError: boom"},
    {"status": "aborted", "task_type": "research", "task_name": "A",
     "error": "Stopped by user"},
    {"status": "skipped", "task_type": "llm", "task_name": "K",
     "error": "Task no longer active (status=paused)"},
    {"status": "queued", "task_type": "llm", "task_name": "Q"},
])


def test_the_caption_no_longer_promises_only_outputs():
    """Measured before: *"Completed assistant/research outputs you can open in
    chat"*, over a list admitting `error` and `aborted` — an exception message
    and the sentence *"Stopped by user"*, both offered as outputs. The list is
    unchanged (taking rows off a screen a person uses is a subtraction, `Law 1`);
    the caption is what was false."""
    out = _h(ROW, "tab", TAB_RUNS)
    caption = out["caption"].lower()
    assert "output" in caption
    assert "error" in caption or "failed" in caption
    assert "stop" in caption
    assert "completed assistant/research outputs you can open in chat" not in caption


def test_the_caption_accounts_for_every_status_the_filter_admits():
    """The `Verify` in assertion form: whatever the filter lets through, the
    caption has to have named. Derived from the render, not from a list here."""
    out = _h(ROW, "tab", TAB_RUNS)
    admitted = {r["titled"] for r in out["rows"]}
    assert admitted == {"Success", "Failed", "Stopped"}, admitted
    caption = out["caption"].lower()
    for word, promised in [("Success", "output"), ("Failed", "error"), ("Stopped", "stop")]:
        if word in admitted:
            assert promised in caption, f"{word} runs are listed and unnamed by the caption"


def test_a_run_that_completed_nothing_says_so_on_its_own_row():
    """The rows were identical: an assistant chat bubble with a task name and a
    time, whether the text was an answer, an exception or *"Stopped by user"*.
    The dot is the Activity row's shared `.task-log-status` and the word is the
    shared table's — the addition that makes the caption checkable per row."""
    rows = {r["titled"]: r for r in _h(ROW, "tab", TAB_RUNS)["rows"]}
    assert rows["Failed"]["word"] == "Failed"
    assert rows["Stopped"]["word"] == "Stopped"
    # A success is what the tab is for; labelling every row *Success* is noise,
    # so the word is dropped there and the dot still carries it.
    assert rows["Success"]["word"] is None
    assert rows["Success"]["titled"] == "Success"
    assert {r["dot"] for r in rows.values()} == {"ok", "error", "aborted"}


def test_the_statuses_the_tab_shows_are_unchanged():
    """`Law 1`, measured against the pre-change tree: `success`, `error` and
    `aborted` in; `skipped`, `queued` and `running` out. `B113` settled the
    caption, not the contents."""
    out = _h(ROW, "tab", TAB_RUNS)
    assert [r["name"] for r in out["rows"]] == ["S", "E", "A"]
    assert out["empty"] is None


def test_the_skipped_exclusion_has_a_reason_on_the_tree():
    """`B78` left `skipped` out and `aborted` in with nothing saying why, which
    is the half of `B113` that is not about the caption. The reason is the
    vocabulary's own — a skipped run never ran, so it left nothing behind — and
    it has to be written where the filter is, not in a roadmap row."""
    src = (ROOT / "static" / "js" / "tasks.js").read_text(encoding="utf-8")
    block = src[src.index("function _isChatResultRun"):]
    before = src[:src.index("function _isChatResultRun")]
    reason = before[before.rindex("// `B113`"):]
    assert "never started" in reason or "never ran" in reason, reason[-400:]
    assert "Activity" in reason, "it has to say where a skipped run IS visible"
    assert "entry.status !== 'skipped'" in block[:400]


def test_the_empty_state_matches_the_caption():
    """*"No completed task outputs yet"* under a list that is not only outputs
    was the same false promise in the empty case (`Law 15` — the first thing a
    new owner reads)."""
    out = _h(ROW, "tab", "[]")
    assert out["rows"] == []
    assert out["empty"] and "output" not in out["empty"].lower(), out["empty"]


@pytest.mark.parametrize("status", SIX)
def test_the_one_reader_of_the_policy_emits_exactly_what_it_says(status):
    """`Law 20`. The three tests above read the table; this drives the function
    every terminal branch calls, over every status the table declares, and
    compares what came out against the table rather than against a list here.

    It is the guard on the shape `B112` chose: the scheduler used to spell its
    own two-clause gate beside three branches that emitted nothing and said
    nothing about why, so there was no single place a mutation could be caught.
    """
    from types import SimpleNamespace

    from core.database import TASK_RUN_NOTIFY
    from src.task_scheduler import TaskScheduler

    sched = TaskScheduler.__new__(TaskScheduler)
    sched._pending_notifications = []
    task = SimpleNamespace(id="t1", name="Nightly tidy", owner="alice",
                           task_type="llm", notifications_enabled=True)

    emitted = sched._notify_run_outcome(task, status, body="why", task_id="t1")
    assert emitted is TASK_RUN_NOTIFY[status][0], (
        f"{status}: the table says {TASK_RUN_NOTIFY[status][0]} and the scheduler did "
        f"{emitted}")
    assert len(sched._pending_notifications) == (1 if emitted else 0)
    if emitted:
        assert sched._pending_notifications[0]["status"] == status


def test_an_action_task_stays_quiet_on_the_outcomes_that_are_not_failures():
    """The quiet gate that already shipped, kept: housekeeping actions do not
    toast on success, and `B112` must not have made them start. `error` is the
    one that overrides it, and that is asserted in
    `test_admin_refusal_is_not_a_failure.py` against the real scheduler."""
    from types import SimpleNamespace

    from src.task_scheduler import TaskScheduler

    sched = TaskScheduler.__new__(TaskScheduler)
    sched._pending_notifications = []
    action = SimpleNamespace(id="t1", name="tidy_sessions", owner="alice",
                             task_type="action", notifications_enabled=True)
    assert sched._notify_run_outcome(action, "success", quiet_for_actions=True) is False
    assert sched._pending_notifications == []
    # …and the same task with the gate off — the privilege refusal's path — is
    # told, because that one is about the task stopping rather than a tick.
    assert sched._notify_run_outcome(action, "skipped", body="refused") is True


def test_the_skip_notification_carries_the_reason_the_server_sent():
    """`B112` again, one surface later. The server sends the skip's own sentence
    in `body`; the client only showed a body for `success`, so the toast read
    *Task skipped: Nightly tidy* and a person still had to open Activity to find
    out that the task had been paused for want of a privilege. Closing the
    notification gap without this would have replaced silence with a shrug."""
    out = _h(ROW, "notify", json.dumps([
        {"status": "skipped", "task_name": "Nightly tidy",
         "body": "Action 'run_local' requires admin privileges"},
        {"status": "aborted", "task_name": "Backup", "body": "Stopped by user"},
    ]))
    said = {s["msg"].split(":")[0].replace("Task ", ""): s for s in out["said"]}
    assert said["skipped"]["msg"].endswith(
        "— Action 'run_local' requires admin privileges"), said["skipped"]
    assert said["stopped"]["msg"].endswith("— Stopped by user"), said["stopped"]
    assert out["failure"] is False, "a reason is not a failure"


def test_a_notification_with_no_reason_reads_exactly_as_it_did():
    """`Law 1`. The body is optional and most notifications have none; adding
    the reason must not have added a dangling dash to every other toast."""
    out = _h(ROW, "notify", json.dumps([
        {"status": "skipped", "task_name": "T"},
        {"status": "success", "task_name": "U"},
    ]))
    assert {s["msg"] for s in out["said"]} == {"Task skipped: T", "Task finished: U"}
