# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opaque exact-action approvals with explicit task and chat scopes.

The server still seals and claims the first displayed action exactly once. The
selected scope then bypasses only the automatic post-external-context approval
gate for the rest of the resumed task or chat session. Browser-visible fields
are display copies, never authority.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from src.tool_approval_scopes import (
    CHAT_SESSION_APPROVAL_DECISION,
    DENY_APPROVAL_DECISION,
    TASK_APPROVAL_DECISION,
    ToolApprovalScope,
    scope_for_decision,
)
from src.tool_capabilities import ToolCapabilities, capabilities_for_action, describe_effects

logger = logging.getLogger(__name__)


DEFAULT_APPROVAL_TTL_SECONDS = 10 * 60
DEFAULT_MAX_PENDING_APPROVALS = 2048

# ── `P12-10` · a prompt nobody answered closes as denied ─────────────────────
#
# **What the code did before this row**, driven rather than assumed, because the
# row asserted a behaviour nobody had written down:
#
#   * Nothing blocks. `agent_loop` creates the pending approval, emits the card
#     and returns with `exit_code: None`. There is no caller on a future, so
#     "does it block, get a default, get an error, or silently proceed" has a
#     fourth answer: the asker has already gone, and what is left is a record
#     in this dict and a card in a transcript.
#   * The record was dropped LAZILY. `_purge_expired_locked` runs only from
#     `create`, `consume`, `peek` and `retire_for_session`; there is no sweeper.
#     Measured: past its deadline and before any other store call, the pending
#     was still in `_pending` and no event had been written.
#   * The first store call after the deadline wrote exactly one events row,
#     `kind=approval outcome=expired`, and decided nothing.
#   * An explicit `deny` recorded **nothing at all** and reported itself through
#     the out-parameter as `bad_decision` — the value reserved for a decision
#     the card never offered.
#
# So expiry was counted and denial did not exist. Now expiry IS the denial: one
# row, one verdict, and the surfaces that hold the card are told so they can
# mark it. `Law 10` — `denied_timeout` cannot be misread the way `expired`
# could, because `expired` is a statement about a clock and says nothing about
# what was decided.
APPROVAL_DENIED_TIMEOUT = "denied_timeout"
APPROVAL_DENIED = "denied"
APPROVAL_CLAIMED = "claimed"

APPROVAL_TIMEOUT_SETTING = "approval_timeout_seconds"
APPROVAL_TIMEOUT_ENV = "PANTHEON_APPROVAL_TIMEOUT_SECONDS"

# `FORBIDDEN.md` Part 2 keeps the approval store's TTL. Making it settable is
# not lifting it; the floor is what keeps that true. `0` is not "never
# expires" — an approval that never expires is the seal with an off switch, and
# somebody will type `0` meaning "off" exactly once. The ceiling is sanity
# rather than policy: a card nobody has looked at for a day is not waiting for
# an answer.
MIN_APPROVAL_TTL_SECONDS = 30
MAX_APPROVAL_TTL_SECONDS = 24 * 60 * 60


def resolve_approval_ttl_seconds(owner: Any = None) -> int:
    """The operator's approval deadline, resolved through `P12`'s four layers.

    Read per card rather than per process, so a change takes effect on the next
    approval and not on the next restart (`P12-03`).
    """
    from src.limit_policy import resolve_int_limit

    return resolve_int_limit(
        APPROVAL_TIMEOUT_SETTING,
        default=DEFAULT_APPROVAL_TTL_SECONDS,
        env_name=APPROVAL_TIMEOUT_ENV,
        owner=owner,
        minimum=MIN_APPROVAL_TTL_SECONDS,
        maximum=MAX_APPROVAL_TTL_SECONDS,
    ).value


# ── who is told when a card lapses ───────────────────────────────────────────
#
# The store knows an approval died; it does not know where the card that asked
# for it is drawn. A listener is how the denial leaves this module without this
# module reaching into `routes/` — `routes/chat_routes.py` registers one in
# `setup_chat_routes` that marks the persisted card `resolved: "deny"`, which is
# the same field an answered card gets and the field `chatRenderer` reads to
# stop drawing a live card on reload.
#
# Listeners are notified OUTSIDE the store lock. They write to the database, and
# holding the lock across that would serialise every approval in the process
# behind a disk write — and a listener that reached back into the store would
# deadlock outright.
_expiry_listeners: list[Any] = []
_expiry_listeners_lock = threading.Lock()


def register_approval_expiry_listener(listener) -> None:
    """Call *listener* with each `PendingToolApproval` that lapses.

    Idempotent: registering the same callable twice calls it once. Route setup
    runs more than once in the test suite, and a listener invoked twice would
    write the same denial twice.
    """
    with _expiry_listeners_lock:
        if listener not in _expiry_listeners:
            _expiry_listeners.append(listener)


def unregister_approval_expiry_listener(listener) -> None:
    with _expiry_listeners_lock:
        if listener in _expiry_listeners:
            _expiry_listeners.remove(listener)


def clear_approval_expiry_listeners() -> None:
    with _expiry_listeners_lock:
        _expiry_listeners.clear()


def approval_expiry_listeners() -> tuple:
    with _expiry_listeners_lock:
        return tuple(_expiry_listeners)


def _normalized_owner(owner: Any) -> str:
    return str(owner or "").strip().casefold()


def _normalized_workspace(workspace: Any) -> str:
    if not isinstance(workspace, str) or not workspace.strip():
        return ""
    return os.path.realpath(os.path.expanduser(workspace))


_MAX_APPROVAL_SELECTED_TOOLS = 512
_MAX_APPROVAL_TOOL_NAME_CHARS = 512
_MAX_APPROVAL_CONTINUATION_QUERY_CHARS = 4000


def _normalized_selected_tools(
    selected_tools: Any,
    *,
    required_tool: Any = None,
) -> tuple[str, ...]:
    if isinstance(selected_tools, str):
        selected_tools = (selected_tools,)
    try:
        values = selected_tools or ()
        names = {
            name.strip()
            for name in values
            if (
                isinstance(name, str)
                and name.strip()
                and len(name.strip()) <= _MAX_APPROVAL_TOOL_NAME_CHARS
            )
        }
        required_name = str(required_tool or "").strip()
        if required_name and len(required_name) <= _MAX_APPROVAL_TOOL_NAME_CHARS:
            names.add(required_name)
        ordered = sorted(names)
        if len(ordered) <= _MAX_APPROVAL_SELECTED_TOOLS:
            return tuple(ordered)
        kept = ordered[:_MAX_APPROVAL_SELECTED_TOOLS]
        if required_name and required_name in names and required_name not in kept:
            kept[-1] = required_name
            kept.sort()
        return tuple(kept)
    except TypeError:
        return ()


def _normalized_continuation_query(value: Any) -> str:
    # The query is server-derived from the interrupted run and already lives in
    # session history. Keep the pending copy bounded because approvals are held
    # in memory until consumed or expired.
    return str(value or "").strip()[:_MAX_APPROVAL_CONTINUATION_QUERY_CHARS]


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _coerced_round(value: Any) -> int:
    """`P4-11`. A round is a positive integer or nothing. Anything else — a
    string, a float, a negative — becomes 0, which the reader treats as
    "unknown" rather than showing a badge nobody can explain."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def document_content_digest(content: Any) -> str:
    """Return the stable server-side fingerprint used to seal a document."""
    return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


def _binding_payload(
    *,
    owner: Any,
    session_id: Any,
    origin_run_id: Any,
    tool_name: Any,
    content: Any,
    workspace: Any,
    document_id: Any,
    document_version: Any,
    document_digest: Any,
    external_untrusted_context_seen: bool,
    selected_tools: Any,
    continuation_query: Any,
    effects: tuple[str, ...],
    result_integrity: str,
) -> dict[str, Any]:
    return {
        "owner": _normalized_owner(owner),
        "session_id": str(session_id or ""),
        "origin_run_id": str(origin_run_id or ""),
        "tool_name": str(tool_name or ""),
        "content": str(content or ""),
        "workspace": _normalized_workspace(workspace),
        "document_id": str(document_id or ""),
        "document_version": (
            int(document_version) if document_version is not None else None
        ),
        "document_digest": str(document_digest or "").strip().lower(),
        "external_untrusted_context_seen": bool(external_untrusted_context_seen),
        "selected_tools": list(
            _normalized_selected_tools(selected_tools, required_tool=tool_name)
        ),
        "continuation_query": _normalized_continuation_query(continuation_query),
        "effects": list(effects),
        "result_integrity": str(result_integrity),
    }


@dataclass(frozen=True)
class PendingToolApproval:
    approval_id: str
    owner: str
    session_id: str
    origin_run_id: str
    tool_name: str
    content: str
    workspace: str
    document_id: str
    document_version: int | None
    document_digest: str
    external_untrusted_context_seen: bool
    effects: tuple[str, ...]
    result_integrity: str
    digest: str
    created_at: float
    expires_at: float
    # Server-only continuation state. Both fields are digest-bound and never
    # exposed in the browser payload.
    selected_tools: tuple[str, ...] = ()
    continuation_query: str = ""
    # `P4-11`. The agent round this action was requested in, so the card that
    # reports the approved run can carry the same number as the card the user
    # clicked approve on. Deliberately **outside** `_binding_payload` and so
    # outside the digest: it is a display integer with no bearing on what runs,
    # and widening the seal for a badge would mean changing the seal's meaning
    # for a cosmetic reason. Nothing reads it to make a decision.
    requested_round: int = 0

    def public_payload(self, *, reason: str | None = None) -> dict[str, Any]:
        return {
            "kind": "tool_approval",
            "approval_id": self.approval_id,
            # The browser already owns this chat id. Persisting it with the
            # resolved card lets history-derived session grants remain bound to
            # this exact chat and prevents inheritance by a forked session.
            "session_id": self.session_id,
            "question": "Allow this task to continue?",
            "description": reason or (
                "Untrusted context influenced this run, so continuing with "
                "otherwise-gated actions needs your explicit approval."
            ),
            "options": [
                {
                    "label": "Allow for this task",
                    "value": TASK_APPROVAL_DECISION,
                    "description": (
                        "Execute the sealed action and allow every otherwise-gated "
                        "action needed to finish this request. Current tool, account, "
                        "workspace, and sandbox restrictions still apply."
                    ),
                },
                {
                    "label": "Allow for this chat session",
                    "value": CHAT_SESSION_APPROVAL_DECISION,
                    "description": (
                        "Execute the sealed action and stop asking at this gate for "
                        "later requests in this chat. Current tool, account, workspace, "
                        "and sandbox restrictions still apply."
                    ),
                },
                {
                    "label": "Deny",
                    "value": DENY_APPROVAL_DECISION,
                    "description": "Do not execute the proposed action.",
                },
            ],
            "action": {
                "tool": self.tool_name,
                # Show the complete sealed input so approval never hides
                # trailing lines.  This is not read back as authority.
                "content": self.content,
                "digest": self.digest[:16],
                "effects": list(self.effects),
                "workspace": self.workspace or None,
                "document_id": self.document_id or None,
                "document_version": self.document_version,
            },
            # P7-06. Ranked, plain-language consequence, resolved here because
            # this payload is what *every* producer of an approval card hands to
            # the renderer — the chat loop, the compare pane, the background
            # monitor, the teacher escalation, and a card rebuilt from history.
            # Resolving it at each of those five instead would be five copies of
            # one answer, and refutation found three of them already disagreeing.
            #
            # It sits beside `action` rather than inside it because `action` is
            # the sealed input shown verbatim; this is a rendering of it. Safe to
            # add: `_canonical_digest` seals `_binding_payload`, a separate
            # server-side dict, and this view is never read back as authority.
            # `self.effects` stays alphabetical inside `action` for that reason —
            # it is the sealed value — while `effects` here is severity-ranked.
            **describe_effects(self.effects),
            # `P4-21`. The ten-minute TTL was computed on every card and sent on
            # none, so the card stopped working with no warning and no
            # explanation — a button that silently becomes a 409. Absolute
            # rather than a remaining-seconds count, because a card can be
            # rebuilt from history minutes after it was made and a countdown
            # baked in at render time would start again from ten minutes.
            "expires_at": self.expires_at,
            "ttl_seconds": max(0, int(round(self.expires_at - self.created_at))),
        }


@dataclass
class ExactToolApproval:
    """A consumed exact first action plus an explicit continuation scope."""

    pending: PendingToolApproval
    scope: ToolApprovalScope = ToolApprovalScope.TASK
    # The seam consumed by agent_loop. Both chat-card allow choices cover the
    # complete resumed task, because one-action scope there immediately
    # re-entered the same gate on the next round. Callers with no resumable
    # chat still get SINGLE_ACTION, which leaves the gate armed behind the
    # sealed action.
    allow_remaining_actions: bool = True
    _claimed: bool = field(default=False, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def grants_chat_session(self) -> bool:
        return self.scope is ToolApprovalScope.CHAT_SESSION

    def _matches_unlocked(
        self,
        *,
        owner: Any,
        session_id: Any,
        tool_name: Any,
        content: Any,
        workspace: Any,
    ) -> bool:
        if self._claimed:
            return False
        capabilities = capabilities_for_action(tool_name, content)
        effects = tuple(sorted(effect.value for effect in capabilities.effects))
        result_integrity = capabilities.result_integrity.value
        if (
            effects != self.pending.effects
            or result_integrity != self.pending.result_integrity
        ):
            return False
        expected = _binding_payload(
            owner=owner,
            session_id=session_id,
            origin_run_id=self.pending.origin_run_id,
            tool_name=tool_name,
            content=content,
            workspace=workspace,
            document_id=self.pending.document_id,
            document_version=self.pending.document_version,
            document_digest=self.pending.document_digest,
            external_untrusted_context_seen=(
                self.pending.external_untrusted_context_seen
            ),
            selected_tools=self.pending.selected_tools,
            continuation_query=self.pending.continuation_query,
            effects=effects,
            result_integrity=result_integrity,
        )
        return _canonical_digest(expected) == self.pending.digest

    def matches(
        self,
        *,
        owner: Any,
        session_id: Any,
        tool_name: Any,
        content: Any,
        workspace: Any,
    ) -> bool:
        with self._lock:
            return self._matches_unlocked(
                owner=owner,
                session_id=session_id,
                tool_name=tool_name,
                content=content,
                workspace=workspace,
            )

    def claim(
        self,
        *,
        owner: Any,
        session_id: Any,
        tool_name: Any,
        content: Any,
        workspace: Any,
    ) -> bool:
        with self._lock:
            if not self._matches_unlocked(
                owner=owner,
                session_id=session_id,
                tool_name=tool_name,
                content=content,
                workspace=workspace,
            ):
                return False
            self._claimed = True
            # P14-02 — approval outcomes. A claim is a human saying yes to a
            # specific tool on a specific payload; "how often is the ladder
            # asking, and does anyone answer" is not visible anywhere else.
            _record_approval(APPROVAL_CLAIMED, tool_name, owner, session_id)
            return True


def _record_approval(outcome: str, tool_name, owner, session_id) -> None:
    """P14-02 — approval outcomes. Guarded; approval logic never fails over
    instrumentation, because the failure mode there is a tool running that
    should not have."""
    try:
        from src.events import record_event
        record_event("approval", name=str(tool_name or "")[:200] or None,
                     owner=str(owner) if owner else None,
                     session_id=str(session_id) if session_id else None,
                     outcome=outcome)
    except Exception:
        pass


class ToolApprovalStore:
    """Thread-safe pending approval registry with destructive consumption."""

    def __init__(
        self,
        *,
        ttl_seconds: int | None = None,
        max_pending: int = DEFAULT_MAX_PENDING_APPROVALS,
    ):
        # `P12-10`. `None` means "ask the operator's setting on every card", so
        # a change to `approval_timeout_seconds` reaches the next approval
        # rather than the next restart — the module singleton below is built at
        # import and lives for the process.
        #
        # An explicit number is a caller saying *this one*, and a setting must
        # not move a deadline a caller chose on purpose. Scope, measured
        # 2026-09-18 over tracked `.py`: every `ttl_seconds=` call site is a
        # test (`test_the_approval_says_when_it_lapses`, `test_tool_approvals`,
        # `test_loop_instrumentation`, `test_an_unanswered_approval_closes_denied`).
        # No production caller pins one, so on a real install this is always the
        # resolved value.
        self._ttl_seconds = None if ttl_seconds is None else max(1, int(ttl_seconds))
        self._max_pending = max(1, int(max_pending))
        self._pending: dict[str, PendingToolApproval] = {}
        self._lock = threading.Lock()

    def ttl_seconds(self, owner: Any = None) -> int:
        """The deadline this store will stamp on the next card."""
        if self._ttl_seconds is not None:
            return self._ttl_seconds
        return resolve_approval_ttl_seconds(owner)

    def _purge_expired_locked(self, now: float) -> list[PendingToolApproval]:
        """Drop every lapsed approval and return them, for announcing.

        Returns rather than announces: the caller holds `self._lock`, and a
        listener writes to the database.
        """
        expired_ids = [
            approval_id
            for approval_id, pending in self._pending.items()
            if pending.expires_at <= now
        ]
        expired: list[PendingToolApproval] = []
        for approval_id in expired_ids:
            pending = self._pending.pop(approval_id, None)
            if pending is None:
                continue
            expired.append(pending)
            # P14-02 / `P12-10`. A question nobody answered is the outcome most
            # worth counting — a ladder that asks often and is answered rarely
            # is a ladder people have learned to ignore. It is recorded as a
            # DENIAL and not as a clock reading: the action did not run, and
            # `expired` was a word that left that unsaid.
            _record_approval(APPROVAL_DENIED_TIMEOUT,
                             getattr(pending, "tool_name", None),
                             getattr(pending, "owner", None),
                             getattr(pending, "session_id", None))
        return expired

    def _announce_expired(self, expired) -> None:
        """Tell every listener, outside the lock, never raising.

        Guarded for the same reason `_record_approval` is: approval logic must
        not fail over something downstream of the decision, because the failure
        mode there is a tool running that should not have.
        """
        if not expired:
            return
        for listener in approval_expiry_listeners():
            for pending in expired:
                try:
                    listener(pending)
                except Exception:  # pragma: no cover - defensive
                    logger.warning(
                        "approval expiry listener failed for %s",
                        getattr(pending, "approval_id", "?"),
                        exc_info=True,
                    )

    def create(
        self,
        *,
        owner: Any,
        session_id: Any,
        origin_run_id: Any,
        tool_name: Any,
        content: Any,
        workspace: Any,
        document_id: Any = None,
        document_version: Any = None,
        document_digest: Any = None,
        selected_tools: Any = None,
        continuation_query: Any = None,
        requested_round: Any = 0,
        external_untrusted_context_seen: bool,
        capabilities: ToolCapabilities,
    ) -> PendingToolApproval:
        now = time.time()
        effects = tuple(sorted(effect.value for effect in capabilities.effects))
        result_integrity = capabilities.result_integrity.value
        payload = _binding_payload(
            owner=owner,
            session_id=session_id,
            origin_run_id=origin_run_id,
            tool_name=tool_name,
            content=content,
            workspace=workspace,
            document_id=document_id,
            document_version=document_version,
            document_digest=document_digest,
            external_untrusted_context_seen=external_untrusted_context_seen,
            selected_tools=selected_tools,
            continuation_query=continuation_query,
            effects=effects,
            result_integrity=result_integrity,
        )
        pending = PendingToolApproval(
            approval_id=secrets.token_urlsafe(32),
            owner=payload["owner"],
            session_id=payload["session_id"],
            origin_run_id=payload["origin_run_id"],
            tool_name=payload["tool_name"],
            content=payload["content"],
            workspace=payload["workspace"],
            document_id=payload["document_id"],
            document_version=payload["document_version"],
            document_digest=payload["document_digest"],
            external_untrusted_context_seen=payload[
                "external_untrusted_context_seen"
            ],
            effects=effects,
            result_integrity=result_integrity,
            digest=_canonical_digest(payload),
            created_at=now,
            expires_at=now + self.ttl_seconds(owner),
            selected_tools=tuple(payload["selected_tools"]),
            continuation_query=payload["continuation_query"],
            requested_round=_coerced_round(requested_round),
        )
        with self._lock:
            expired = self._purge_expired_locked(now)
            # The chat UI exposes one pending card per session, so supersede an
            # older action there. Headless/manual-test callers use an empty
            # session id; keep independent origin runs separate so two skill
            # tests owned by the same user cannot invalidate each other.
            superseded = [
                approval_id
                for approval_id, existing in self._pending.items()
                if (
                    existing.owner == pending.owner
                    and existing.session_id == pending.session_id
                    and (
                        bool(pending.session_id)
                        or existing.origin_run_id == pending.origin_run_id
                    )
                )
            ]
            for approval_id in superseded:
                self._pending.pop(approval_id, None)
            while len(self._pending) >= self._max_pending:
                oldest_id = min(
                    self._pending,
                    key=lambda approval_id: self._pending[approval_id].created_at,
                )
                self._pending.pop(oldest_id, None)
            self._pending[pending.approval_id] = pending
        self._announce_expired(expired)
        return pending

    def consume(
        self,
        approval_id: Any,
        *,
        decision: Any,
        owner: Any,
        session_id: Any,
        allow_continuation: bool = True,
        outcome: dict[str, Any] | None = None,
    ) -> ExactToolApproval | None:
        """Consume a pending approval.

        ``allow_continuation`` is the caller's assertion that it owns a
        resumable conversation the granted scope can apply to. Callers without
        one (the skill tester, unattended audits) pass ``False`` and get the
        original one-use grant, so a button labelled "Allow once" cannot widen
        into a run-long bypass just because the chat card reuses the same wire
        value.

        `outcome`, when given, is filled in with `{"reason": ...}` saying which
        of the four ways this returned `None` happened (`P4-21`): `expired`,
        `unknown`, `not_yours`, `bad_decision`. It is an out-parameter so the
        four existing callers are untouched and the return type still says
        exactly what it said. Before it, a card that lapsed after ten minutes
        and a card belonging to somebody else produced the same `None` and the
        same "could not be consumed" — and only one of those is fixable by
        asking again.

        `expired` is reported **only to the owner of the pending action**, for
        the reason the ownership check below already exists: a bare id must not
        become an oracle for whether it was ever real.
        """
        now = time.time()
        expired: list[PendingToolApproval] = []
        try:
            with self._lock:
                approval_key = str(approval_id or "")
                # Read before the purge, so "it lapsed" can be told apart from
                # "it never existed" — the purge is what erased that difference.
                lapsed = self._pending.get(approval_key)
                expired = self._purge_expired_locked(now)
                pending = self._pending.get(approval_key)
                if pending is None:
                    if outcome is not None:
                        owned = (
                            lapsed is not None
                            and lapsed.owner == _normalized_owner(owner)
                            and lapsed.session_id == str(session_id or "")
                        )
                        outcome["reason"] = "expired" if owned else "unknown"
                    return None
                if (
                    pending.owner != _normalized_owner(owner)
                    or pending.session_id != str(session_id or "")
                ):
                    # Authentication is checked before destructive consumption
                    # so a leaked/guessed opaque id cannot be used to invalidate
                    # another owner's pending action.
                    if outcome is not None:
                        outcome["reason"] = "not_yours"
                    return None
                self._pending.pop(approval_key, None)
            normalized_decision = str(decision or "").strip().lower()
            scope = scope_for_decision(normalized_decision)
            if scope is None:
                if outcome is not None:
                    # `P12-10`. A `deny` is one of the three decisions this card
                    # offers, and it reported itself as `bad_decision` — the
                    # value reserved for a decision the card never listed.
                    # `scope_for_decision` returns `None` for both because
                    # neither grants a continuation, which is a true statement
                    # about scope and was being read as one about validity.
                    outcome["reason"] = (
                        APPROVAL_DENIED
                        if normalized_decision == DENY_APPROVAL_DECISION
                        else "bad_decision"
                    )
                if normalized_decision == DENY_APPROVAL_DECISION:
                    # The other half of `P12-10`: a denial is recorded whoever
                    # made it. `src/task_scheduler.py` auto-denies every card a
                    # scheduled run produces, because no interactive surface can
                    # answer one, and not a single row said so.
                    _record_approval(APPROVAL_DENIED, pending.tool_name,
                                     pending.owner, pending.session_id)
                return None
            if not allow_continuation:
                return ExactToolApproval(
                    pending,
                    scope=ToolApprovalScope.SINGLE_ACTION,
                    allow_remaining_actions=False,
                )
            return ExactToolApproval(
                pending,
                scope=scope,
                allow_remaining_actions=True,
            )
        finally:
            self._announce_expired(expired)

    def peek(self, approval_id: Any) -> PendingToolApproval | None:
        now = time.time()
        with self._lock:
            expired = self._purge_expired_locked(now)
            found = self._pending.get(str(approval_id or ""))
        self._announce_expired(expired)
        return found

    def retire_for_session(self, *, owner: Any, session_id: Any) -> bool:
        """Discard pending actions superseded by an ordinary user turn.

        Returns whether any retired action carried external provenance, so the
        caller can preserve that security state without treating the new user
        message as an approval continuation.
        """
        now = time.time()
        normalized_owner = _normalized_owner(owner)
        normalized_session = str(session_id or "")
        if not normalized_session:
            return False
        with self._lock:
            expired = self._purge_expired_locked(now)
            retired_ids = [
                approval_id
                for approval_id, pending in self._pending.items()
                if (
                    pending.owner == normalized_owner
                    and pending.session_id == normalized_session
                )
            ]
            carried_taint = any(
                self._pending[approval_id].external_untrusted_context_seen
                for approval_id in retired_ids
            )
            for approval_id in retired_ids:
                self._pending.pop(approval_id, None)
        self._announce_expired(expired)
        return carried_taint


tool_approval_store = ToolApprovalStore()
