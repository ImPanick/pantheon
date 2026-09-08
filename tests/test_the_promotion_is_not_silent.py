# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-18` — the turn you typed in chat mode, answered in agent mode.

Six places in `chat_routes` promote a chat turn to agent mode: a notes or
calendar intent, web search being switched on, an explicit web request, a
contextual web follow-up, a browser follow-up, and a message naming a path.
Every one of them said so to a **log file**. The person who typed the message
saw an agent thread appear and was told nothing.

The row calls it *"silent in both directions"*, and the second direction is the
sharper one. A light promotion **withholds** `bash`, `python`, `read_file`,
`write_file` and the browser tools, on the reasoning that a model asked for a
reminder should not shell its way through it. That is a good rule. But when the
model then cannot do something because a tool was taken away, nothing said a
tool had been taken away — so it reads as a model that could not work out how.

The structural half of the fix is that setting the flag and recording the reason
are now **one expression**. Six sites each wrote `auto_escalated = True` and a
`logger.info` beside it, and a seventh site would have been one line away from
recording the promotion without saying why.
"""

import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_ROUTES = (_REPO / "routes" / "chat_routes.py").read_text(encoding="utf-8")


# ── the flag and the reason cannot drift ──────────────────────────────────────


def test_no_site_promotes_a_turn_without_saying_why():
    # `Law 13`, made structural rather than remembered: the assignment *is* the
    # recording. A bare `auto_escalated = True` is the shape this row removed.
    assert "auto_escalated = True" not in _ROUTES
    assert _ROUTES.count("auto_escalated = _escalate(") == 6, (
        "a promotion site was added or removed — check it records a reason"
    )


def test_the_recorder_returns_the_flag_it_records():
    # One expression does both. Returning False would silently stop the six
    # call sites promoting; not appending would silently stop them explaining.
    from routes.chat_helpers import note_escalation
    reasons: list = []
    assert note_escalation(reasons, "because the message asks for the web") is True
    assert reasons == ["because the message asks for the web"]
    assert note_escalation(reasons, "and again") is True
    assert reasons == ["because the message asks for the web", "and again"]


@pytest.mark.parametrize("kwargs, expected, why", [
    (dict(promoted=True, workspace_intent=False, allow_browser=False),
     ["bash", "browser_click", "python", "read_file", "write_file"],
     "the light promotion, named in full"),
    (dict(promoted=True, workspace_intent=False, allow_browser=True),
     ["bash", "python", "read_file", "write_file"],
     "a web turn keeps the browser it was promoted for"),
    (dict(promoted=True, workspace_intent=True, allow_browser=False), [],
     "a promotion that grants the shell takes nothing away"),
    (dict(promoted=False, workspace_intent=False, allow_browser=False), [],
     "an unpromoted turn withholds nothing"),
])
def test_what_a_promotion_takes_away_is_a_list_of_names(kwargs, expected, why):
    # Named, not counted. A number would not tell the reader whether the thing
    # they asked for was possible this turn.
    from routes.chat_helpers import escalation_withholds
    assert escalation_withholds(browser_tools={"browser_click"}, **kwargs) == expected, why


def test_the_route_withholds_exactly_what_it_reports():
    # The list is computed once and used for both, so the tools taken away and
    # the tools reported cannot be two different sets — which is the shape of
    # every defect this phase has been closing.
    assert "_escalation_withheld = escalation_withholds(" in _ROUTES
    assert "disabled_tools.update(_escalation_withheld)" in _ROUTES


@pytest.mark.parametrize("phrase", [
    "web search is switched on for this chat",
    "the message asks for something on the web",
    "a follow-up to something already open in the browser",
])
def test_the_reasons_are_written_for_a_person(phrase):
    # These strings go on screen. "explicit web intent" and "contextual
    # browser/form follow-up" were log lines, and reading like log lines is how
    # a UI ends up explaining nothing (Law 15).
    assert phrase in _ROUTES


# ── the payload ───────────────────────────────────────────────────────────────


def _payload_source() -> str:
    start = _ROUTES.index("_auto_escalation_payload = {")
    return _ROUTES[start:_ROUTES.index("}", start) + 1]


def test_the_payload_carries_both_directions():
    body = _payload_source()
    assert '"type": "auto_escalated"' in body
    assert '"reasons": list(_escalations)' in body
    assert '"withheld": list(_escalation_withheld)' in body


def test_the_promotion_is_streamed_and_saved():
    assert "if auto_escalated:" in _ROUTES
    assert "yield f\"data: {json.dumps(_auto_escalation_payload)}" in _ROUTES
    assert _ROUTES.count(
        "auto_escalation=_auto_escalation_payload if auto_escalated else None,") == 3, (
        "a save path stopped carrying the promotion, so a reload would lose it"
    )


class _FakeSession:
    """The two methods `save_assistant_response` uses, and nothing else."""

    def __init__(self):
        self.messages = []
        self.model = "small-local-model"

    def add_message(self, message):
        self.messages.append(message)


class _FakeManager:
    def __init__(self):
        self.saved = 0

    def save_sessions(self):
        self.saved += 1


def _save(monkeypatch, **kwargs):
    """Call the real saver with the database held off.

    `save_assistant_response` calls `update_session_last_accessed`, which writes
    to the real sqlite file. A unit test that touches it passes alone and fails
    inside the suite — and, worse, leaves state behind: an earlier session in
    this project lost half an hour to a stray `data/` write that survived a
    `git stash` and looked exactly like a regression. The write is stubbed and
    counted, so the test is not quietly asserting that the saver stopped
    calling it either.
    """
    import core.database as database
    from routes.chat_helpers import save_assistant_response
    touched = []
    monkeypatch.setattr(database, "update_session_last_accessed",
                        lambda sid: touched.append(sid), raising=False)
    sess, manager = _FakeSession(), _FakeManager()
    save_assistant_response(sess, manager, "promotion-test", "the answer",
                            {"model": "m"}, **kwargs)
    assert sess.messages, "nothing was saved, so this asserts nothing"
    assert touched == ["promotion-test"], "the saver stopped touching the session"
    assert manager.saved == 1
    return sess.messages[-1].metadata


def test_a_promoted_turn_is_saved_with_its_reasons(monkeypatch):
    # Executed rather than read: this is the half that decides whether a
    # reloaded thread can explain its own shape.
    md = _save(monkeypatch, auto_escalation={
        "type": "auto_escalated",
        "reasons": ["web search is switched on for this chat"],
        "withheld": ["bash", "python"],
    })
    assert md["auto_escalated"]["reasons"] == [
        "web search is switched on for this chat"]
    assert md["auto_escalated"]["withheld"] == ["bash", "python"]


def test_an_unpromoted_turn_saves_no_promotion(monkeypatch):
    # Every ordinary chat turn goes through the same call with `None`, and a
    # key present-but-empty would put a pill on every message in the product.
    assert "auto_escalated" not in _save(monkeypatch)
    assert "auto_escalated" not in _save(monkeypatch, auto_escalation=None)


def test_a_turn_nobody_promoted_carries_nothing():
    from routes.chat_helpers import save_assistant_response
    import inspect
    sig = inspect.signature(save_assistant_response)
    assert sig.parameters["auto_escalation"].default is None
    body = inspect.getsource(save_assistant_response)
    assert 'if auto_escalation:\n        md["auto_escalated"] = auto_escalation' in body, (
        "an unpromoted turn would save an empty promotion record"
    )


# ── the pill ──────────────────────────────────────────────────────────────────


_RENDERER = (_REPO / "static" / "js" / "chatRenderer.js").read_text(encoding="utf-8")
_CHAT = (_REPO / "static" / "js" / "chat.js").read_text(encoding="utf-8")


def test_both_surfaces_feed_the_pill():
    # Live over SSE, reloaded off the saved metadata — the same pill either way,
    # which is the invariant every row in this phase has needed.
    assert "json.type === 'auto_escalated'" in _CHAT
    assert "holder._autoEscalated = json;" in _CHAT
    assert _RENDERER.count("_autoEscalated = metadata.auto_escalated") == 2


def test_the_pill_goes_through_the_one_popover():
    # `Law 14`. Three pills now share the fifty lines of viewport arithmetic
    # that `P4-16` extracted; a fourth copy of it is the thing that extraction
    # exists to prevent.
    assert "bindFooterPopover(pill, 'promoted-detail'" in _RENDERER
    assert _RENDERER.count("export function bindFooterPopover") == 1


def test_the_pill_says_when_something_was_withheld():
    block = _RENDERER[_RENDERER.index("const promotion = msgElement._autoEscalated;"):]
    block = block[:block.index("footer.appendChild(actions);")]
    assert "Promoted to Agent · tools withheld" in block
    assert "Promoted to Agent" in block
    assert "Withheld for this turn: " in block


def test_the_reasons_are_escaped_before_they_reach_the_page():
    # The reasons interpolate a workspace path and a classifier's own text.
    block = _RENDERER[_RENDERER.index("const promotion = msgElement._autoEscalated;"):]
    block = block[:block.index("footer.appendChild(actions);")]
    assert "esc(" in block, "the pill label is interpolated without escaping"
    for line in block.splitlines():
        if "textContent" in line or "detail.appendChild" in line:
            assert "innerHTML" not in line
    # The rows are built with `textContent`, which cannot be markup at all —
    # stronger than escaping and the reason this is asserted rather than hoped.
    assert "why.textContent =" in block
    assert "held.textContent =" in block
