# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression: builtin_actions heuristics must tolerate non-string input.

_result_has_work did `result.lower()` after a falsy-only guard, and
_classify_event_heuristic did `(summary or "").lower()`; a truthy non-string
(e.g. a dict) raised AttributeError. They now coerce/guard non-strings.

`B1983`. _result_has_work also read "nothing to" or "no new" anywhere in an
email pass's result as no work. A pass over several mailboxes joins one
"[name] …" result per mailbox, so a mailbox with nothing to do marked a run in
which another mailbox had done work "skipped" (and its on-success chain step
never ran); and the "Processed:" list under a summary quotes received subjects
and senders, so a subject reading "No new updates this week" did the same to
a one-mailbox run. A count of work in the pass's own summary lines now wins,
and the list is never read. After upstream Odysseus 84aa9a91.
"""
from src.builtin_actions import _result_has_work, _classify_event_heuristic


def test_result_has_work_non_string():
    assert _result_has_work({"x": 1}) is False
    assert _result_has_work(123) is False


def test_classify_event_heuristic_non_string():
    out = _classify_event_heuristic(123)
    assert isinstance(out, tuple)


def test_valid_inputs_unchanged():
    assert _result_has_work("Processed 0 emails") is False


# ── `B1983` ──────────────────────────────────────────────────────────────────

def test_a_mailbox_with_nothing_to_do_does_not_hide_another_mailboxs_work():
    assert _result_has_work(
        "[Work] Scanned 5 email(s) (summary) · processed 3 new · summarized 3\n"
        "[Home] Scanned 0 email(s) (summary) · nothing to do") is True
    assert _result_has_work(
        "[Work] Scanned 2 email(s) (reply) · processed 2 new · drafted 2 replies\n"
        "[Home] Nothing to do") is True
    # When no mailbox did anything, the run still did nothing.
    assert _result_has_work(
        "[A] Scanned 0 email(s) (summary) · nothing to do\n[B] Nothing to do") is False
    assert _result_has_work(
        "Scanned 4 email(s) (summary/reply) · summarized 0 · drafted 0 replies · "
        "4 already cached") is False


def test_a_received_subject_or_sender_is_never_read_as_the_runs_own_count():
    """The "Processed:" list quotes received mail, a folded subject over two
    lines; the next mailbox's "[name] …" line is read again."""
    assert _result_has_work(
        "Scanned 1 email(s) (summary) · processed 1 new · summarized 1\n\n"
        "Processed:\n- summary · INBOX#7 · No new updates this week — a@b.c") is True
    assert _result_has_work(
        "Scanned 1 email(s) (away) · 1 away failed · nothing to do\n\n"
        "Processed:\n- away reply failed · INBOX#7 · Invoice sent 2 days ago") is False
    assert _result_has_work(
        "Scanned 1 email(s) (away) · 1 away failed · nothing to do\n\n"
        "Processed:\n- away reply failed · INBOX#7 · Your invoice for October was\r\n"
        " sent 2 days ago") is False
    assert _result_has_work(
        "[Work] Scanned 1 email(s) (summary) · 1 summary failed\n\n"
        "Processed:\n- summary failed · INBOX#3 · Weekly digest — processed 9 new\r\n"
        " <news@x.org>\n"
        "[Home] Scanned 0 email(s) (summary) · nothing to do") is False
