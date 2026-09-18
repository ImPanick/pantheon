# SPDX-License-Identifier: AGPL-3.0-or-later
r"""A throttled service is visible to the person using it (`P15-11`).

`OutboundHostLimiter.snapshot()` has returned per-host cooldowns, the
consecutive-429 count, requests made and seconds waited since `P15-01`. Measured
on the tree before this row, its readers were:

    src/metrics_export.py      a Prometheus scrape       operator, if configured
    src/diagnostic_bundle.py   a support bundle          operator, after the fact
    src/self_checks.py         Settings -> System        ADMIN ONLY, if they look

— and nothing at all in front of the person watching a feature do nothing.

The mail path is the sharpest case, and it was already half built for this row:
`routes/email_routes.py` answers the 60-second unread poll with
`sync.source: "unavailable"` and a `retry_in` when a mailbox is in backoff
(`P15-12` put it there, saying in its own closure *"so `P15-11` has something
true to show"*). Both clients dropped the whole `sync` object:

    emailInbox.js  `_refreshUnreadCount` read `unread_count` and `max_uid`; a
                   mailbox Pantheon had deliberately stopped calling reported
                   zero unread, every 60 seconds, in every tab.
    emailLibrary.js `_libSyncStatus` STORED `source` and `_renderEmailSyncStatus`
                   printed only "Last updated: 2d ago" — the sentence that makes
                   somebody sit and wait for mail that is not coming.

Harness output on that tree, for `{"source": "unavailable", "retry_in": 240}`::

    "Last updated: 1d ago"

and after::

    "This mailbox is paused — retrying in 4 min · Last updated: 1d ago"

`Law 13` is the constraint the row states: six places in the product already
know what a throttle is, and the fix is a READER, not a seventh. The client's
words live in `static/js/runStatus.js` — the single vocabulary — and the
renderers call it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.source_text import blank

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "harness" / "email_sync_throttle.js"
WORDS_JS = ROOT / "static" / "js" / "runStatus.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")


def _h(mode: str, payload: dict) -> dict:
    proc = subprocess.run(["node", str(HARNESS), mode, json.dumps(payload)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _eval(expr: str):
    proc = subprocess.run(
        ["node", "--input-type=module", "--eval",
         f"import * as R from '{WORDS_JS}';\nconsole.log(JSON.stringify({expr}));"],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# What a person reads
# ---------------------------------------------------------------------------

def test_a_throttled_mailbox_says_so_and_says_when_it_clears():
    out = _h("line", {"source": "unavailable", "retry_in": 240,
                      "updated_at": "2026-09-16T10:00:00Z",
                      "detail": "This mailbox is not answering."})
    assert "paused" in out["line"]
    assert "4 min" in out["line"]           # the time it clears — the row's Verify
    assert out["visibility"] == "visible"
    # The server's own sentence is kept, out of the way, rather than thrown out
    # or pasted into a one-line status.
    assert out["title"] == "This mailbox is not answering."


def test_the_freshness_line_is_still_there_beside_it():
    """`Law 1`. The notice is added; "Last updated" is not replaced by it."""
    out = _h("line", {"source": "unavailable", "retry_in": 240,
                      "updated_at": "2026-09-16T10:00:00Z"})
    assert "Last updated" in out["line"]
    assert out["line"].index("paused") < out["line"].index("Last updated"), (
        "the reason is behind the timestamp that makes it look like nothing "
        "has arrived")


def test_a_healthy_mailbox_reads_exactly_as_it_did():
    out = _h("line", {"source": "index", "updated_at": "2026-09-18T05:00:00Z"})
    assert "paused" not in out["line"]
    assert out["line"].startswith("Last updated")
    assert out["title"] == ""


def test_the_unread_poll_is_what_learns_it():
    """The poll runs every 60 seconds whether the library is open or not, so it
    is also what makes the line right the instant somebody opens it."""
    out = _h("poll", {"updated_at": "2026-09-16T10:00:00Z",
                      "polls": [{"source": "unavailable", "retry_in": 900,
                                 "detail": "Could not reach this mailbox."}]})
    assert "paused" in out["line"] and "15 min" in out["line"]


def test_a_mailbox_that_comes_back_stops_saying_it_is_paused():
    """A stale countdown ticking beside a list that is plainly updating again is
    the same defect pointing the other way."""
    out = _h("poll", {"updated_at": "2026-09-16T10:00:00Z",
                      "polls": [{"source": "unavailable", "retry_in": 900},
                                {"source": "index"}]})
    assert "paused" not in out["line"]


def test_the_poll_does_not_claim_the_list_was_refreshed():
    """It asks about INBOX unread and the library may be showing another
    folder, so it must not write a freshness timestamp."""
    out = _h("poll", {"polls": [{"source": "index", "updated_at":
                                 "2026-09-18T05:00:00Z"}]})
    assert "Last updated" not in out["line"]


# ---------------------------------------------------------------------------
# One vocabulary, not a seventh place (`Law 13`)
# ---------------------------------------------------------------------------

def test_the_words_come_from_the_one_vocabulary_module():
    """The renderers must not spell the sentence themselves.

    Comments are blanked first (`Law 20`, `B290`): both files now EXPLAIN in
    prose why the words are not written there, and a plain substring search
    would find the explanation and pass.
    """
    for name in ("emailLibrary.js", "emailInbox.js"):
        code = blank(ROOT / "static" / "js" / name)
        assert "is paused" not in code, f"{name} spells the throttle sentence itself"
        assert "paused — retrying" not in code
    assert "is paused" in (ROOT / "static" / "js" / "runStatus.js").read_text()


def test_the_renderer_asks_the_vocabulary_rather_than_testing_the_string():
    code = blank(ROOT / "static" / "js" / "emailLibrary.js")
    assert "throttleNotice" in code and "isThrottledSource" in code
    assert "'unavailable'" not in code, (
        "the renderer knows a server-side source value by heart; "
        "THROTTLED_SOURCES is where that list lives")


def test_a_throttle_is_not_a_seventh_run_status():
    """`RUN_STATUSES` are values stored in `task_runs.status` and pinned by
    `FORBIDDEN.md`. A cooldown is a property of a destination, has no row, and
    can be true while a run is queued, running or finished."""
    out = _eval("{six: R.RUN_STATUSES, active: R.RUN_ACTIVE_STATUSES}")
    assert out["six"] == ["queued", "running", "success", "error", "skipped",
                          "aborted"]
    assert out["active"] == ["queued", "running"]


# ---------------------------------------------------------------------------
# The vocabulary itself
# ---------------------------------------------------------------------------

def test_a_countdown_rounds_up_so_it_never_reads_zero():
    out = _eval("[R.clearsInLabel(1), R.clearsInLabel(89), R.clearsInLabel(91),"
                " R.clearsInLabel(240), R.clearsInLabel(7200)]")
    assert out == ["in 1s", "in 89s", "in 2 min", "in 4 min", "in 2 h"]


def test_no_countdown_is_said_as_no_countdown():
    """A protocol with no `Retry-After` gives an escalating local cooldown and
    not a promise. An invented "in 0s" would be a worse answer than none."""
    assert _eval("[R.clearsInLabel(0), R.clearsInLabel(null), "
                 "R.clearsInLabel('later')]") == ["", "", ""]
    notice = _eval("R.throttleNotice({source: 'unavailable'})")
    assert "paused" in notice and "retrying" not in notice


def test_the_notice_says_this_is_deliberate():
    """Without it a pause reads as a fault, and what a person does about a
    fault is press the button again — which is what deepens a rate limit."""
    notice = _eval("R.throttleNotice({source: 'unavailable', retryIn: 300, "
                   "what: 'GitHub'})")
    assert notice.startswith("GitHub is paused")
    assert "retrying in 5 min" in notice


def test_nothing_is_said_about_a_service_that_is_answering():
    assert _eval("R.throttleNotice({source: 'index', retryIn: 300})") == ""
    assert _eval("R.throttleNotice({})") == ""


def test_a_throttled_row_is_not_painted_as_an_error():
    """Being told to wait is not a failure, and colouring it red teaches people
    to ignore red."""
    tone = _eval("R.runStatusTone(R.throttleDotClass())")
    assert tone == "info"


# ---------------------------------------------------------------------------
# It counts DOWN, which is the half a single render cannot see
# ---------------------------------------------------------------------------

def _seq(*steps):
    return _h_seq({"steps": list(steps)})["lines"]


def _h_seq(payload):
    proc = subprocess.run(["node", str(HARNESS), "seq", json.dumps(payload)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_countdown_counts_down():
    """A notice that prints "in 15 min" once and then says it for ever is a
    countdown in appearance only, and a survived mutation proved every
    single-render test here could not tell the two apart."""
    lines = _seq({"sync": {"source": "unavailable", "retry_in": 900}},
                 {"advance": 300},
                 {"advance": 540})
    assert "15 min" in lines[0]
    assert "10 min" in lines[1]
    assert "60s" in lines[2]


def test_a_new_throttle_with_no_countdown_does_not_inherit_the_old_one():
    """The sequence the clear branch exists for: a mailbox recovers, then goes
    quiet again on a protocol that gives no `Retry-After`. Carrying the old
    fifteen minutes over would be a number invented from a previous outage."""
    lines = _seq({"sync": {"source": "unavailable", "retry_in": 900}},
                 {"poll": {"source": "index"}},
                 {"sync": {"source": "unavailable"}})
    assert "15 min" in lines[0]
    assert "paused" not in lines[1]
    assert "paused" in lines[2] and "min" not in lines[2]
