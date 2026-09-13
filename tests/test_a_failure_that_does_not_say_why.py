# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-13` — a failed tool call recorded that it failed and never why.

Measured, not imagined. `P17-08` ran the gap analysis against the owner's
running deployment and found **seven of eight failed `tool_call` rows carrying
an empty `detail`**; the eighth said `{"policy": "p"}`. One of three
`capability_gap` events recorded `{}` — the event fired and named nothing,
which is the one thing it exists to say.

**THE COST IS CONCRETE AND IT IS THE SHARPEST NUMBER IN THAT REPORT.**
`web_fetch` was offered 37 times, called 3, and failed 3. A 100% failure rate
on the tool the selector reaches for most often, and the rows cannot
distinguish a blocked host from a timeout from a parse failure from a dead URL.
Those are four different fixes, and `P14-02` wrote the outcome column and
stopped one field short of saying which.

**A CLASS AND A REDACTED LINE, NOT THE RAW ERROR.** The class is what a count
can be taken over; the line is what a person reads when the class is `unknown`.
The redaction is not decoration: a `web_fetch` failure can echo the request it
made, and a request can carry an `Authorization` header or a key in a query
string. It runs through the same `diagnostic_bundle.redact` the support bundle
uses — one redactor, not two that drift (`Law 14`).

**AND THE `capability_gap` ROW CAN NO LONGER BE EMPTY.** The cause was one
branch: `evaluate_turn_regex` builds three reason strings and only two contain
a `pattern` token, so `_known_pattern` returned `None` for the third and the
detail went in as `None`. The branch that fired is now recorded beside the
pattern, and it is source text either way — the promise that no conversation
reaches this table is unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import teacher_escalation as te  # noqa: E402
from src.tool_execution import _classify_failure, _failure_detail  # noqa: E402


# --------------------------------------------------------------------------
# The four fixes that looked alike
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Connection timed out after 30s", "timeout"),
        ("Read timeout on https://x.test", "timeout"),
        ("Blocked by outbound policy", "blocked"),
        ("host resolves to a private address", "blocked"),
        ("HTTP 403 Forbidden", "permission"),
        ("Permission denied", "permission"),
        ("404 Not Found", "not_found"),
        ("no such file or directory", "not_found"),
        ("Unknown action 'frobnicate'", "not_found"),
        ("429 Too Many Requests", "rate_limit"),
        ("Expecting value: line 1 column 1 (char 0)", "parse"),
        ("JSONDecodeError: bad input", "parse"),
        ("Could not resolve host", "network"),
        ("SSL certificate verify failed", "network"),
        ("response too large", "too_large"),
        ("the flux capacitor is misaligned", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_the_four_fixes_are_four_different_classes(text, expected):
    """`web_fetch` failed three times out of three and the rows said nothing.

    Every string here is one a caller in this codebase can produce. Written
    first from imagination, and `Expecting value: line 1 column 1` — which is
    `json.JSONDecodeError`'s own text and contains none of the obvious words —
    came out `unknown` until the classifier was run over the messages the code
    actually emits rather than the ones it seemed like it would.
    """
    assert _classify_failure(text) == expected


def test_blocked_outranks_permission():
    """An SSRF refusal says *not allowed*, which is also what a 403 says.

    Ordering, not cleverness: the two are indistinguishable by keyword and the
    distinction matters — one is this app refusing, the other is the far end.
    """
    assert _classify_failure("not allowed: 403 blocked by policy") == "blocked"


def test_timeout_outranks_network():
    """A timeout is a network error with its own fix."""
    assert _classify_failure("connection timed out") == "timeout"


# --------------------------------------------------------------------------
# What is stored, and what is not
# --------------------------------------------------------------------------


def test_a_successful_result_still_records_no_detail():
    """`Law 1`. A row that used to be empty for a good reason stays empty."""
    assert _failure_detail({"ok": True}) is None
    assert _failure_detail({"error": None}) is None
    assert _failure_detail({}) is None
    assert _failure_detail(None) is None
    assert _failure_detail("not a dict") is None


def test_a_credential_in_the_error_does_not_reach_the_events_table():
    """The reason redaction is here and not a nicety.

    A `web_fetch` failure echoes the request it made, and a request carries
    headers. This table has a 90-day prune and rides diagnostic bundles.
    """
    detail = _failure_detail({
        "error": "GET https://api.example.com/v1/x?api_key=sk-abcdefghijklmnopqrst failed: timed out",
    })
    assert detail["class"] == "timeout"
    assert "sk-abcdefghijklmnopqrst" not in detail["error"]
    assert "api_key" not in detail["error"]


def test_a_bearer_token_in_the_error_does_not_survive():
    detail = _failure_detail({"error": "401 with Authorization: Bearer ghp_aaaabbbbccccddddeeee"})
    assert "ghp_aaaabbbbccccddddeeee" not in detail["error"]


def test_only_the_first_line_and_only_two_hundred_characters():
    """A traceback in an events row is a log file in a database."""
    detail = _failure_detail({"error": "first line\nsecond line\nthird line"})
    assert detail["error"] == "first line"
    # A realistic long message, not `"x" * 500` — that came back as
    # `<redacted>` because the redactor treats a 32-character run of
    # alphanumerics as an opaque credential, which is correct of it and made
    # the first version of this assertion test the wrong thing.
    long = "failed to open " + " ".join(["some/path/segment"] * 40)
    detail = _failure_detail({"error": long})
    assert len(detail["error"]) == 200


def test_an_exit_code_alone_is_still_a_reason():
    """A process that fails silently with status 2 said something."""
    detail = _failure_detail({"exit_code": 2})
    assert detail == {"exit_code": 2, "class": "exit_code"}


def test_a_zero_exit_code_is_not_a_failure():
    assert _failure_detail({"exit_code": 0}) is None


def test_the_policy_field_is_kept():
    """`Law 1`. It was the one thing the old detail carried."""
    detail = _failure_detail({"error": "denied", "policy": "disabled_tools"}, "disabled_tools")
    assert detail["policy"] == "disabled_tools"


def test_a_redactor_that_throws_drops_the_line_and_keeps_the_class(monkeypatch):
    """Failing open here would put the unredacted string in the table.

    The class is derived before redaction and survives; the line does not.
    """
    import src.diagnostic_bundle as db

    def _boom(_text):
        raise RuntimeError("nope")

    monkeypatch.setattr(db, "redact", _boom)
    detail = _failure_detail({"error": "timed out talking to https://secret.internal?k=abcdef123456"})
    assert detail["class"] == "timeout"
    assert "error" not in detail, "an unredacted error reached the detail column"


# --------------------------------------------------------------------------
# The capability_gap row that named nothing
# --------------------------------------------------------------------------


def test_every_branch_of_the_classifier_has_a_name():
    """Three reason shapes, and only two carried a `pattern` token."""
    tool_error = te.evaluate_turn_regex([{"error": "boom"}], "")[1]
    assert te._reason_kind(tool_error) == "tool_error_field"
    assert te._known_pattern(tool_error) is None, (
        "this is the branch that produced the empty row"
    )

    give_up = te.evaluate_turn_regex([], "I don't have a tool for that")[1]
    assert te._reason_kind(give_up) == "reply_give_up_pattern"
    assert te._known_pattern(give_up)


def test_an_unrecognised_reason_is_named_rather_than_dropped():
    assert te._reason_kind("something a future branch writes") == "unclassified"
    assert te._reason_kind(None) == "unclassified"
    assert te._reason_kind("") == "unclassified"


def test_the_recorded_detail_is_never_empty(monkeypatch):
    """The whole row, in one assertion, against the real recorder."""
    import src.events as ev

    written = []
    monkeypatch.setattr(ev, "record_event", lambda *a, **k: written.append(k) or True)
    signal = te.note_turn_outcome(
        tool_results=[{"error": "boom"}], agent_reply="", session_id="s", owner="o")
    assert signal == "tool_error"
    assert len(written) == 1
    detail = written[0]["detail"]
    assert detail, "a capability_gap row with no detail says a gap happened and not which"
    assert detail["signal"] == "tool_error_field"
    assert detail["pattern"] == ""


def test_no_conversation_reaches_the_capability_gap_row(monkeypatch):
    """The promise `note_turn_outcome`'s docstring makes, with a real payload.

    Both stored fields are compared against fixed source text — a prefix list
    and a pattern allowlist — so neither can carry the tool's words through.
    """
    import json

    import src.events as ev

    written = []
    monkeypatch.setattr(ev, "record_event", lambda *a, **k: written.append(k) or True)
    secret = "PATIENT-RECORD-8891-Jane-Doe"
    te.note_turn_outcome(
        tool_results=[{"error": f"failed to read {secret}"}], agent_reply="", session_id="s")
    blob = json.dumps(written[0]["detail"])
    assert secret not in blob
    assert "Jane" not in blob


def test_a_pattern_bearing_branch_still_records_its_pattern(monkeypatch):
    import src.events as ev

    written = []
    monkeypatch.setattr(ev, "record_event", lambda *a, **k: written.append(k) or True)
    te.note_turn_outcome(
        tool_results=[], agent_reply="I don't have a tool for that", session_id="s")
    detail = written[0]["detail"]
    assert detail["signal"] == "reply_give_up_pattern"
    assert detail["pattern"], "the pattern is still the most useful field"


# --------------------------------------------------------------------------
# The rule that keeps holding
# --------------------------------------------------------------------------


def test_instrumentation_never_changes_the_answer(monkeypatch):
    """`P14-02`'s rule. A recorder that raises must not fail the tool call."""
    import src.events as ev

    def _boom(*a, **k):
        raise RuntimeError("events table is gone")

    monkeypatch.setattr(ev, "record_event", _boom)
    assert te.note_turn_outcome(
        tool_results=[{"error": "boom"}], agent_reply="", session_id="s") is None
