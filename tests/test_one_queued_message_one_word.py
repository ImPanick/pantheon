# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B13` — one queued message, one word, on every surface that shows it.

`tests/harness/queue_status_words.js` runs the three real renderers over the
row the real source emits, and reports the word each one prints.

**The row says two vocabularies. There were three.** Measured on the tree
before this change::

    queuePanel.js  docked row      Waiting  Sending  Sent  Failed  Skipped  Stopped
    tasks.js       Activity row    Queued   Running  —     —       —        —
    chat.js        transcript bubble  Queued

The bubble is the one the row does not name, and it is the one a person is most
likely to be looking at: it sits in the transcript, under the message they just
typed, while the docked panel sits three inches below it saying a different
word about the same item. The tooltip on that bubble said "Queued" too, so the
disagreement survived a hover.

**And the two surfaces do not merely use different words — they disagree about
whether there is a word at all.** The Activity row replaces the label with a
relative time once a run is terminal, so it has no wording for four of the six
values. That is why the shared table has a `job` column of two entries rather
than six: a column filled past its consumers is the drift `Law 13` names.

**What did not change.** A task run still reads *Queued* and *Running*. The row
asks for the panel's wording *for the composer's queue*, because *Waiting /
Sending* describes a message and *Queued / Running* describes a job — so the
subject picks the column, and a row declares its own subject rather than the
renderer guessing from a source id. Nothing persisted is touched: the six
status *values* are stored in rows and pinned by `FORBIDDEN.md`, and this file
asserts they are still exactly those six.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "harness" / "queue_status_words.js"
WORDS_JS = ROOT / "static" / "js" / "runStatus.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

SIX = ["queued", "running", "success", "error", "skipped", "aborted"]


def run(mode: str):
    proc = subprocess.run(["node", str(HARNESS), mode],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# The row's own `Verify`
# ---------------------------------------------------------------------------


def test_one_queued_item_reads_the_same_on_every_surface():
    """*One queued item, both surfaces visible, one word.*

    Built by the real `getQueueActivityEntries`, so this is the same object the
    panel and the Activity view each render — not three fixtures that happen to
    agree.
    """
    out = run("together")
    assert out["rows"] == 1, "the queue source stopped emitting the row"
    words = out["words"]
    assert out["count"] == 1, (
        f"the same message is called {out['distinct']} on different surfaces"
    )
    assert words["panel"] == words["activity"] == words["bubble"] == "Waiting"
    # The restored bubble keeps its extra instruction and loses the second
    # vocabulary: the word in front of it is the same word.
    assert words["bubbleRestored"].startswith("Waiting")
    assert "click to send" in words["bubbleRestored"], (
        "a queue restored across a reload must still say it is clickable"
    )


def test_the_row_declares_its_own_subject():
    """The discriminator is a field on the row, set where the row is built.

    Keying off `sourceId == 'chat-queue'` in the renderer would put the rule in
    the file that must not have to learn what a queue is, and every new source
    would have to be added there (`Law 10`: one reading per field).
    """
    out = run("together")
    assert out["subject"] == "message"


# ---------------------------------------------------------------------------
# What the two surfaces say, value by value
# ---------------------------------------------------------------------------


def test_the_panel_still_speaks_the_panels_words():
    """The fix moved the vocabulary; it did not rewrite it."""
    v = run("vocabularies")
    assert [v[s]["panel"] for s in SIX] == [
        "Waiting", "Sending", "Sent", "Failed", "Skipped", "Stopped",
    ]


def test_a_task_run_still_reads_as_a_job():
    """`Law 1`. Nothing about the Tasks list changed, and a row that does not
    say what it is about is a job — which every task run is."""
    v = run("vocabularies")
    assert v["queued"]["activityJob"] == "Queued"
    assert v["running"]["activityJob"] == "Running"


def test_a_message_row_reads_as_a_message_in_the_activity_view():
    v = run("vocabularies")
    assert v["queued"]["activityMessage"] == "Waiting"
    assert v["running"]["activityMessage"] == "Sending"


def test_a_row_that_has_been_in_flight_too_long_says_so_in_its_own_vocabulary():
    """The staleness warning reads out of the same label slot, so it is part of
    the same vocabulary. It said "Still running" for a message too, which is a
    job's word on a message's row — the defect one branch deeper. Keeping it is
    `Law 1`: a 40-minute-old row must still tell the user it looks stuck."""
    v = run("vocabularies")
    assert v["running"]["activityStaleJob"] == "Still running"
    assert v["running"]["activityStaleMessage"] == "Still sending"
    # Queued is never stale — nothing has started, so there is nothing to warn
    # about, and the word does not change.
    assert v["queued"]["activityStaleJob"] == "Queued"
    assert v["queued"]["activityStaleMessage"] == "Waiting"


def test_the_activity_view_still_shows_a_time_rather_than_a_word_when_a_run_ends():
    """The asymmetry that decides the table's shape: four of the six values
    have no `job` word because that surface shows elapsed time instead. If a
    later pass gives terminal rows a label, this fails and says the table needs
    those four entries — which is the honest order to do it in."""
    v = run("vocabularies")
    for status in ("success", "error", "skipped", "aborted"):
        assert v[status]["activityJob"] is None
        assert v[status]["activityMessage"] is None
        assert v[status]["activityStaleJob"] is None


# ---------------------------------------------------------------------------
# The vocabulary itself
# ---------------------------------------------------------------------------


def test_the_words_module_covers_exactly_the_six_stored_values():
    """`FORBIDDEN.md` pins the run-status enum. A seventh word here would mean
    someone had invented a seventh status in the only place that would not
    fail loudly."""
    proc = subprocess.run(
        ["node", "--input-type=module", "--eval",
         "import { RUN_STATUSES, runStatusLabel } from '%s';\n"
         "console.log(JSON.stringify({ six: RUN_STATUSES,"
         " legacy: runStatusLabel('failed', 'message'),"
         " unknown: runStatusLabel('', 'message'),"
         " defaulted: runStatusLabel('queued') }));" % WORDS_JS],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["six"] == SIX
    # Older rows carry `failed`; printing what the row says beats printing
    # nothing, and `runStatusTone` already accepts it for the same reason.
    assert out["legacy"] == "failed"
    assert out["unknown"] == ""
    # The default subject is the one that was already on screen everywhere.
    assert out["defaulted"] == "Queued"


def test_no_surface_spells_the_words_for_itself_any_more():
    """Scoped to code, not prose: `runStatus.js` and the three renderers all
    *document* the words they used to own, and a file-wide substring would find
    them there (`Law 20`)."""
    import re
    block = re.compile(r"/\*.*?\*/", re.S)
    line = re.compile(r"^\s*//.*$", re.M)
    for name in ("queuePanel.js", "tasks.js", "chat.js"):
        src = (ROOT / "static" / "js" / name).read_text(encoding="utf-8")
        code = line.sub("", block.sub("", src))
        for word in ("'Waiting'", '"Waiting"', "'Sending'", "'Sent'"):
            assert word not in code, f"{name} still owns the word {word}"
        assert "runStatusLabel" in code, f"{name} does not use the shared words"
