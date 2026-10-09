# SPDX-License-Identifier: AGPL-3.0-or-later
"""A chat's approval mode — `D-2026-10-09-01` §2.

The owner, verbatim: *"Yes, and if the user enabled full automation; it will
skip asking and just run the command. These should be per-chat session scoped.
Much like your 'permission' - with Auto and manual approve."*

Two settings, in the chat the person is in:

  **Manual approve** — today's ladder (`src/tool_capabilities.py`'s
  `TRUST_LADDER`). A stop condition raises a card and the step waits.

  **Auto** — the step runs without asking, and the run records that it ran
  under Auto.

**Scope is one chat, and that is the whole shape of this module.** The mode
lives on the `sessions` row, beside `mode` ('agent'/'chat'/'research'), which is
the existing per-chat column and the precedent this follows (`Law 14`). A new
chat has no row value, which reads as the install default, so Auto is never
inherited from another chat, never global and never what a new chat starts at.

**The install default is a constant, not a setting.** `DEFAULT_APPROVAL_MODE` is
`MANUAL` and there is no `approval_mode_default` in `data/settings.json` on
purpose: a setting whose other value is Auto *is* the install-wide default the
ruling forbids (*"Auto is never a default, never install-wide, and never
inherited by a new chat"*). What an admin decides is **who may turn it on** —
`can_auto_approve` in `core/auth.py`'s `DEFAULT_PRIVILEGES`, off for non-admins,
resolved through the one resolver every privilege uses
(`src.auth_helpers.resolve_privilege`). Turning it off for every account is how
an admin forbids it install-wide for everyone but admins; `ADMIN_PRIVILEGES` is
every declared privilege, so an admin cannot be locked out of their own install
by this module, which is the same answer `can_use_workstation` gives and is
filed for the owner rather than decided here.

**What Auto gives up, in the ruling's own words.** *"With Auto on, in that chat,
a privileged effect that follows outside content runs without a person seeing it
first. That is the trade the owner is making deliberately and per chat, and it
is the only control this decision moves."* So this module changes **whether a
person is asked** and nothing else. Untouched, and asserted untouched by
`tests/test_a_chat_decides_whether_it_asks.py`: the approval store's seal, TTL,
single-use consumption and owner binding; the MCP command/arg/env validation;
the five SSRF validators and the pinned-IP transports; `OutboundHostLimiter`;
`require_admin`; the `app_api` blocklist; and every effect is still recorded
where effects are recorded today.

**Two things Auto is refused to, and both are tightenings rather than
exceptions:**

  * **a bearer token (`B70`).** A delegated run has no human in the chat, so it
    cannot pick up a mode a person set in their browser — the same reason
    `ToolRunSecurityContext.observe_messages` drops a chat-session grant for a
    token. `mode_for` answers `MANUAL` for one.
  * **the agent itself.** Turning Auto on is a person's act. The route requires
    `request_is_a_person` (`B1005`), so the agent's own loopback and a token are
    both refused, and `app_api`'s blocklist carries the path as well — because
    an assistant that could switch its own gate off is the plainest
    self-escalation there is (`P7-02`).

There is deliberately **no exception list of effects that still ask**. The brief
is explicit — *"do not half-build it by keeping some asks 'to be safe'"* — so a
destructive effect under Auto runs. Where that should not hold (mass deletion is
the example the owner gave), it is filed as a row for the owner with the
reasoning, not decided quietly here.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ApprovalMode(str, Enum):
    """How this chat answers a stop condition.

    A `str` enum, like `TrustRung`, so the stored column, the wire value and
    the code are one spelling (`Law 7`).
    """

    MANUAL = "manual"
    AUTO = "auto"


#: The install default, and the only one a new chat can start at
#: (`D-2026-10-09-01` §2). A constant rather than a setting — see the module
#: docstring.
DEFAULT_APPROVAL_MODE = ApprovalMode.MANUAL

#: The privilege an admin grants before a person may turn Auto on at all.
#: Declared in `core/auth.py`'s `DEFAULT_PRIVILEGES` (off), labelled in
#: `static/js/admin.js`, resolved here.
PRIVILEGE = "can_auto_approve"


# ── the words a person reads ────────────────────────────────────────────────
#
# Doc 2 § 5: a control's name is its tooltip; help is one line naming a
# consequence, not a mechanism; no lecture. One sentence for the deliberate act,
# two words on the chip, and an error that says what happened and who can change
# it (rule 7).

#: The chip and the header badge. The same two words in both places, so the
#: chat is saying one thing (`Law 7`, Doc 2 § 5 rule 1).
AUTO_LABEL = "Auto-approve"

#: The one plain sentence the person reads before turning it on. Not a wall of
#: warning, and not a silent toggle either.
AUTO_TURN_ON_SENTENCE = (
    "In this chat, Pantheon runs tool steps without asking you first — "
    "including after it has read a web page or an email. Turn on Auto-approve?"
)

#: What the header badge says it is. Short, and it names the scope, because the
#: scope is the thing a person has to be able to see.
AUTO_BADGE_TITLE = "This chat runs steps without asking"

#: `require_privilege`'s refusal, in the words of rule 7: what happened, then
#: who can change it, naming the control by its label.
AUTO_NOT_ALLOWED_SENTENCE = (
    "Auto-approve is not turned on for your account. An admin grants it in "
    "Settings › Users."
)


def coerce_approval_mode(value: Any) -> ApprovalMode:
    """Resolve a stored or supplied mode, failing **closed**.

    Anything unreadable — a null column, a typo, a value from a future version
    — is `MANUAL`. That is the opposite direction from `coerce_trust_rung`,
    which answers an unreadable rung with the *default* rather than the
    strictest, and the difference is the point: a corrupt rung is a setting we
    can only guess at, while a corrupt approval mode has exactly one safe
    reading, and "Manual approve" is also the install default, so failing
    closed and failing to the default are the same answer here.
    """
    if isinstance(value, ApprovalMode):
        return value
    try:
        return ApprovalMode(str(value).strip().casefold())
    except (ValueError, AttributeError, TypeError):
        return DEFAULT_APPROVAL_MODE


def may_use_auto(owner: Optional[str], *, auth_manager: Any = None) -> bool:
    """Whether this person may turn Auto on, resolved the way every privilege
    is — `src.workstation_access.may_use`'s shape, for the same reasons.

    `auth_manager` is the app's own when a route asks
    (`request.app.state.auth_manager`); the agent loop asks without one and
    gets the shared manager over the auth file.

    An unanswerable question is a **no**: an auth store that cannot be read, a
    pre-setup install where nobody is an admin yet, or an owner spelling that
    normalises to nothing all resolve to False, so the chat stays on Manual
    approve rather than silently running steps.
    """
    try:
        from src.owner_identity import normalize_owner

        name = normalize_owner(owner)
        if not name:
            return False
        if auth_manager is None:
            from src.auth_manager_access import shared_auth_manager

            auth_manager = shared_auth_manager()
        if not getattr(auth_manager, "is_configured", False):
            return False
        from src.auth_helpers import resolve_privilege

        privs = auth_manager.get_privileges(name) or {}
        return resolve_privilege(privs if isinstance(privs, dict) else {}, PRIVILEGE) is True
    except Exception as exc:  # noqa: BLE001 — an unanswerable question is a no
        logger.warning("could not resolve %s for %r: %s", PRIVILEGE, owner, exc)
        return False


def mode_for(
    session_id: Any,
    owner: Optional[str] = None,
    *,
    delegated_credential: bool = False,
    auth_manager: Any = None,
) -> ApprovalMode:
    """The approval mode one run answers to, for this chat and this caller.

    Three conditions, all of them, and each one can only lower the answer to
    `MANUAL`:

      1. the chat's own stored mode (null → the install default);
      2. the caller is a person, not a bearer token (`B70`);
      3. the person still holds `can_auto_approve` — asked **per run**, so an
         admin revoking it takes effect on the next turn of a chat that is
         already set to Auto, rather than leaving a chat switched on by a
         privilege nobody has any more.

    Never raises: a database that cannot answer is `MANUAL`.
    """
    if delegated_credential:
        # `B70`. A token's run has no human in the chat to have set this, and a
        # mode the owner set in their own browser must not become a token's
        # authority. The same rule `observe_messages` applies to a chat-session
        # grant, for the same reason.
        return DEFAULT_APPROVAL_MODE
    if not session_id:
        return DEFAULT_APPROVAL_MODE
    try:
        from core.database import get_session_approval_mode

        stored = coerce_approval_mode(get_session_approval_mode(str(session_id)))
    except Exception:  # noqa: BLE001
        logger.debug("approval mode unreadable for session %r", session_id, exc_info=True)
        return DEFAULT_APPROVAL_MODE
    if stored is not ApprovalMode.AUTO:
        return stored
    if not may_use_auto(owner, auth_manager=auth_manager):
        logger.info(
            "[approval] chat %s is set to auto but %r may not use it; manual approve",
            session_id, owner,
        )
        return DEFAULT_APPROVAL_MODE
    return ApprovalMode.AUTO


def set_mode_for(session_id: Any, mode: Any) -> bool:
    """Persist one chat's approval mode. Best-effort, like `set_session_mode`.

    The privilege is checked by the caller (the route), not here: this is the
    store's door, and a second copy of the privilege question would be a second
    place for it to be answered differently (`Law 7`).
    """
    from core.database import set_session_approval_mode

    return set_session_approval_mode(str(session_id), coerce_approval_mode(mode).value)
