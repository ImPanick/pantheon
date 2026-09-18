# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared wire values and scope markers for tool approval continuations."""

from __future__ import annotations

import hmac
import logging
from enum import Enum
from hashlib import sha256

logger = logging.getLogger(__name__)


# Keep the existing wire values so the current route and no-build frontend do
# not need a second protocol migration. ``approve`` no longer means one action;
# it now selects chat-session scope.
TASK_APPROVAL_DECISION = "approve_task"
CHAT_SESSION_APPROVAL_DECISION = "approve"
DENY_APPROVAL_DECISION = "deny"

# Session.get_context_messages() adds this server-owned marker only when the
# session history contains a matching, resolved chat-session approval.
CHAT_SESSION_APPROVAL_CONTEXT_MARKER = "_tool_approval_chat_session_granted"

# ── B70: the server's proof that IT resolved this approval ─────────────────
#
# Backported from upstream's advisory fix. The grant above is derived by
# `core/models._history_grants_chat_session_approval`, which walks the
# transcript looking for `metadata.tool_events[].ask_user` with `kind`,
# `resolved` and `session_id` — **all three of which a caller can write**,
# because `POST /api/sessions/{id}/messages` persists a caller-supplied
# metadata blob verbatim. So the shape of a resolved approval could be written
# into a transcript and read back as authority: a confused deputy, on an
# ordinary authenticated route, needing no API token.
#
# Only the server can produce this signature, so only the server can produce a
# grant. Two controls rather than one, and the order matters: the signature is
# what closes the path, and `sanitize_client_message_metadata` keeps the state
# out of the transcript in the first place so nothing has to be trusted twice.
CHAT_SESSION_APPROVAL_SIGNATURE_FIELD = "_server_grant"

# Message-metadata keys the server writes and a caller never should. Both are
# read back as authority: `tool_events` carries the approval cards, and the
# context marker is projected onto a turn once a grant is found.
_SERVER_OWNED_METADATA_KEYS = (
    "tool_events",
    CHAT_SESSION_APPROVAL_CONTEXT_MARKER,
)




def _grant_key() -> bytes | None:
    """Key material for grant signatures, or None when it is unavailable.

    Reuses the persistent application key so a grant survives a restart the way
    the transcript holding it does. Imported inside the call because
    `secret_storage` is heavier than this module and most callers never sign.
    """
    try:
        from src.secret_storage import _load_or_create_key

        return _load_or_create_key()
    except Exception as exc:
        logger.warning("Tool approval grant key unavailable: %s", exc)
        return None


def sign_chat_session_grant(
    session_id: object,
    approval_id: object,
    decision: object,
) -> str | None:
    """Return the server's signature for one resolved chat-session grant."""
    key = _grant_key()
    if key is None:
        return None
    payload = "\x00".join(
        (
            str(session_id or ""),
            str(approval_id or ""),
            str(decision or "").strip().lower(),
        )
    )
    return hmac.new(key, payload.encode("utf-8"), sha256).hexdigest()


def verify_chat_session_grant(
    signature: object,
    session_id: object,
    approval_id: object,
    decision: object,
) -> bool:
    """Whether *signature* is this server's grant for that exact approval.

    **Fails CLOSED**: an absent, malformed or unverifiable signature is not a
    grant. Binding both ids into the payload means a signature lifted from one
    chat cannot be replayed into another, and one lifted from a different
    approval in the same chat cannot be reused either.
    """
    # `compare_digest` accepts only ASCII strings, and this value comes out of
    # arbitrary persisted metadata — so require the exact representation we
    # produce rather than handing it whatever was stored. Without these, a
    # signature of `"é" * 64` is an unhandled `TypeError` (a 500) instead of
    # *not a grant*.
    #
    # **The length check is belt-and-braces and a mutation run proved it.**
    # Removing it changes no outcome the hex check does not already produce: a
    # short or long all-hex string still fails `compare_digest`, and a
    # non-ASCII one is already refused above it. Kept because it states the
    # shape, and recorded as behaviourally equivalent rather than covered by a
    # test that could not tell the difference.
    if (
        not isinstance(signature, str)
        or len(signature) != sha256().digest_size * 2
        or any(character not in "0123456789abcdef" for character in signature)
    ):
        return False
    expected = sign_chat_session_grant(session_id, approval_id, decision)
    if expected is None:
        return False
    return hmac.compare_digest(signature, expected)


def stamp_chat_session_grant(
    ask_user: dict,
    session_id: object,
    decision: object,
) -> None:
    """Record the server's grant on a card it has just resolved.

    Call this only from the server-side resolve path. A decision that does not
    grant chat-session scope leaves **no** signature behind, so editing a
    `deny` into an `approve` in the transcript does not carry a usable one.
    """
    if not isinstance(ask_user, dict):
        return
    if str(decision or "").strip().lower() != CHAT_SESSION_APPROVAL_DECISION:
        ask_user.pop(CHAT_SESSION_APPROVAL_SIGNATURE_FIELD, None)
        return
    signature = sign_chat_session_grant(
        session_id,
        ask_user.get("approval_id"),
        CHAT_SESSION_APPROVAL_DECISION,
    )
    if signature:
        ask_user[CHAT_SESSION_APPROVAL_SIGNATURE_FIELD] = signature


# ── P7-09: taking a session-wide grant back ────────────────────────────────
#
# A chat-session grant is not a row anywhere. It is *derived*, every turn, by
# `core/models._history_grants_chat_session_approval` walking the transcript for
# a resolved card that carries the server's signature. So revoking one is not a
# delete from a store — it is removing the thing the derivation needs, and the
# derivation already fails closed without it (`B70`).
#
# That is why this is three lines and not a second grant store: the control that
# closed the forgery path is the same control that makes revocation possible,
# and building a separate "revoked grants" table beside it would be a second
# source of truth for one fact (`Law 7`, `Law 14`).
#
# The card itself is left resolved and a marker is written beside it, because
# the transcript is a record of what happened: the person did approve, and then
# took it back. Erasing the first half would make the history lie.
CHAT_SESSION_GRANT_REVOKED_FIELD = "_grant_revoked"

# Written by the server on the revoke path only. It needs no entry in
# `_SERVER_OWNED_METADATA_KEYS` below because it lives *inside* `tool_events`,
# which that filter already drops wholesale from a caller-supplied blob — and
# writing it is only ever a tightening in any case.


def revoke_chat_session_grant(ask_user: dict) -> bool:
    """Take back one resolved chat-session grant. Returns whether one was there.

    `P7-09`. Removes the server signature, which is the only thing
    `_history_grants_chat_session_approval` accepts as authority, and marks the
    card revoked for whatever draws it. Idempotent: a card with no signature was
    never a live grant, so revoking it again answers `False` rather than
    reporting a second success.
    """
    if not isinstance(ask_user, dict):
        return False
    had_grant = bool(ask_user.pop(CHAT_SESSION_APPROVAL_SIGNATURE_FIELD, None))
    if had_grant:
        ask_user[CHAT_SESSION_GRANT_REVOKED_FIELD] = True
    return had_grant


def chat_session_grant_is_live(ask_user: object, session_id: object) -> bool:
    """Whether this resolved card is, right now, a usable session-wide grant.

    The same four conditions `core/models._history_grants_chat_session_approval`
    applies, asked of one card so a listing and the gate cannot disagree about
    what counts (`Law 7`). Kept here rather than in `core/models` because this
    module already owns every other fact about the grant's shape.
    """
    if not isinstance(ask_user, dict):
        return False
    if ask_user.get("kind") != "tool_approval":
        return False
    if ask_user.get("resolved") != CHAT_SESSION_APPROVAL_DECISION:
        return False
    if str(ask_user.get("session_id") or "") != str(session_id or ""):
        return False
    return verify_chat_session_grant(
        ask_user.get(CHAT_SESSION_APPROVAL_SIGNATURE_FIELD),
        session_id,
        ask_user.get("approval_id"),
        CHAT_SESSION_APPROVAL_DECISION,
    )


def sanitize_client_message_metadata(metadata):
    """Drop server-owned keys from a caller-supplied message metadata blob.

    Routes that persist a message on the caller's behalf accept this blob
    verbatim, which is what let a caller write the shape of a resolved approval
    into its own transcript. The signature check is the control that closes
    that path; this keeps the state out of the transcript at all. Anything else
    in the blob is left alone — this is a filter, not a schema.
    """
    if not isinstance(metadata, dict):
        return metadata
    if not any(key in metadata for key in _SERVER_OWNED_METADATA_KEYS):
        return metadata
    return {
        key: value
        for key, value in metadata.items()
        if key not in _SERVER_OWNED_METADATA_KEYS
    }


class ToolApprovalScope(str, Enum):
    # Surfaces without a resumable chat (the skill tester, unattended audits)
    # keep the original one-use meaning: the sealed action runs and the gate
    # re-arms immediately for anything after it.
    SINGLE_ACTION = "single_action"
    TASK = "task"
    CHAT_SESSION = "chat_session"


def scope_for_decision(decision: object) -> ToolApprovalScope | None:
    normalized = str(decision or "").strip().lower()
    if normalized == TASK_APPROVAL_DECISION:
        return ToolApprovalScope.TASK
    if normalized == CHAT_SESSION_APPROVAL_DECISION:
        return ToolApprovalScope.CHAT_SESSION
    return None
