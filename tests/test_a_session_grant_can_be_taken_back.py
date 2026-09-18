# SPDX-License-Identifier: AGPL-3.0-or-later
"""P7-09 — the widest thing an approval card hands out, and how to undo it.

"Allow for this chat session" stops the gate asking for the rest of the
conversation. Nothing listed one and nothing took one back, so a person who
clicked it by mistake had no way to find out and no way to undo it short of
starting a new chat.

The grant is not a row anywhere: `core/models._history_grants_chat_session_approval`
re-derives it from the transcript every turn, and since `B70` it accepts only a
card carrying the server's own signature. So revoking is removing that
signature — the control that closed the forgery path is the same control that
makes the grant revocable, which is why this is not a second store.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.models import ChatMessage, Session  # noqa: E402
from src import tool_approval_scopes as scopes  # noqa: E402
from src.tool_capabilities import ToolRunSecurityContext  # noqa: E402

MARKER = scopes.CHAT_SESSION_APPROVAL_CONTEXT_MARKER
SIGNATURE = scopes.CHAT_SESSION_APPROVAL_SIGNATURE_FIELD


def _granted_card(session_id="session-1", approval_id="appr-1"):
    card = {
        "kind": "tool_approval",
        "approval_id": approval_id,
        "session_id": session_id,
        "resolved": scopes.CHAT_SESSION_APPROVAL_DECISION,
        "action": {"tool": "bash", "digest": "abc123"},
    }
    scopes.stamp_chat_session_grant(
        card, session_id, scopes.CHAT_SESSION_APPROVAL_DECISION
    )
    assert card.get(SIGNATURE), "fixture must start as a real server grant"
    return card


def _session(cards, session_id="session-1"):
    return Session(
        id=session_id,
        name="Chat",
        endpoint_url="http://example.invalid",
        model="test",
        history=[
            ChatMessage(
                "assistant",
                "approval requested",
                {"_db_id": 11, "tool_events": [{"ask_user": card} for card in cards]},
            ),
            ChatMessage("user", "carry on"),
        ],
    )


def _gate_is_bypassed(session) -> bool:
    """The question the product actually asks, driven end to end.

    Not "is the marker present": the marker is an intermediate. This runs the
    derivation, the projection onto the turn and the run security context that
    reads it, which is the path a revoke has to break.
    """
    context = ToolRunSecurityContext()
    context.observe_messages(session.get_context_messages())
    return context.approval_gate_bypassed


# ── the primitive ───────────────────────────────────────────────────────────


def test_a_revoked_grant_stops_bypassing_the_gate():
    card = _granted_card()
    session = _session([card])
    assert _gate_is_bypassed(session) is True

    assert scopes.revoke_chat_session_grant(card) is True

    assert _gate_is_bypassed(session) is False


def test_revoking_twice_reports_the_second_one_as_nothing_to_do():
    card = _granted_card()
    assert scopes.revoke_chat_session_grant(card) is True
    assert scopes.revoke_chat_session_grant(card) is False


def test_the_transcript_still_records_that_the_person_said_yes():
    """The history is a record of what happened. Erasing the approval would
    make it lie about the first half in order to tell the truth about the
    second."""
    card = _granted_card()
    scopes.revoke_chat_session_grant(card)

    assert card["resolved"] == scopes.CHAT_SESSION_APPROVAL_DECISION
    assert card[scopes.CHAT_SESSION_GRANT_REVOKED_FIELD] is True
    assert SIGNATURE not in card


def test_a_revoke_cannot_be_undone_by_writing_the_marker_back():
    """`B70` again, from the other side: the derivation accepts a signature
    only, and nothing a caller can write reinstates one."""
    card = _granted_card()
    scopes.revoke_chat_session_grant(card)
    card[scopes.CHAT_SESSION_GRANT_REVOKED_FIELD] = False
    card["_server_grant_restored"] = True

    assert _gate_is_bypassed(_session([card])) is False


# ── one live-grant predicate, shared with the listing ───────────────────────


def test_live_matches_what_the_gate_would_accept():
    live = _granted_card()
    unsigned = {
        "kind": "tool_approval",
        "approval_id": "appr-2",
        "session_id": "session-1",
        "resolved": scopes.CHAT_SESSION_APPROVAL_DECISION,
    }
    denied = _granted_card(approval_id="appr-3")
    denied["resolved"] = "deny"

    assert scopes.chat_session_grant_is_live(live, "session-1") is True
    assert scopes.chat_session_grant_is_live(unsigned, "session-1") is False
    assert scopes.chat_session_grant_is_live(denied, "session-1") is False
    assert scopes.chat_session_grant_is_live(live, "session-2") is False


# ── the route's half ────────────────────────────────────────────────────────


def _routes(monkeypatch, persisted=True):
    import routes.chat_routes as chat_routes

    monkeypatch.setattr(
        chat_routes,
        "_persist_message_metadata",
        lambda *a, **k: persisted,
    )
    return chat_routes


def test_revoking_takes_back_every_live_grant_in_the_chat(monkeypatch):
    """The whole chat, not one card. `_history_grants_chat_session_approval`
    stops at the first card it can verify, so leaving a second signed grant
    behind would revoke nothing a person could observe."""
    chat_routes = _routes(monkeypatch)
    session = _session([_granted_card("session-1", "a"), _granted_card("session-1", "b")])
    assert _gate_is_bypassed(session) is True

    assert chat_routes.revoke_chat_session_grants(session) == 2

    assert _gate_is_bypassed(session) is False
    assert chat_routes.revoke_chat_session_grants(session) == 0


def test_a_revoke_that_cannot_be_persisted_is_not_reported_as_done(monkeypatch):
    """Telling somebody a grant is gone when it will be back after a reload is
    worse than telling them it could not be taken back."""
    chat_routes = _routes(monkeypatch, persisted=False)
    session = _session([_granted_card()])

    assert chat_routes.revoke_chat_session_grants(session) == 0


def test_the_listing_distinguishes_never_granted_from_taken_back(monkeypatch):
    chat_routes = _routes(monkeypatch)
    session = _session([_granted_card()])

    assert [g["state"] for g in chat_routes.list_chat_session_grants(session)] == ["live"]

    chat_routes.revoke_chat_session_grants(session)
    listed = chat_routes.list_chat_session_grants(session)

    assert [g["state"] for g in listed] == ["revoked"]
    assert listed[0]["tool"] == "bash"
    assert listed[0]["approval_id"] == "appr-1"


def test_the_listing_leaves_another_chats_grant_alone(monkeypatch):
    chat_routes = _routes(monkeypatch)
    session = _session([_granted_card(session_id="session-2", approval_id="x")])

    assert chat_routes.list_chat_session_grants(session) == []
    assert chat_routes.revoke_chat_session_grants(session) == 0
