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
reasoning, not decided quietly here. (`B1341` / `D-2026-10-17-01` since gave
Auto its one exception: a destructive call still asks, in a chat set to Auto.)

**`B1703` / `D-2026-10-30-01`: a lifted gate is a risk the person accepted, on
record.** *"Auto-Approve should be appropriately 'warned' and the user
accepting that risk by enabling it (or 'proceed to auto-approve') — then
that's on them."* Both ways a step stops being asked about — a chat set to Auto
and a hire whose *allow* effects run after outside content (`hire_lift_for`) —
are turned on only by an explicit acceptance of a warning, in this module's
words (`AUTO_WARNING`; a hire's is `hires.ALLOWED_AFTER_OUTSIDE`, which names
its effects): what the agent reads can steer what it does next, within what is
set to run unasked. The request carries the warning's id
(`check_acceptance`), the acceptance is recorded — who, when, which warning,
for which chat or hire (`core.database.AutoApproveAcceptance`) — and **no
acceptance on record is no lift**: `mode_for` reads a chat with none as Manual
approve, and `hire_lift_for` lifts nothing for a hire with none. So a chat set
to Auto before this change, or a privilege granted after a hire was made,
never lifts a gate nobody accepted: both ask until their person accepts.
Turning a gate back on never asks (`set_mode_for` to Manual withdraws the
acceptance). What this does not change, in the ruling's words: who may use Auto
(`can_auto_approve`), and what is validated either way.
"""

from __future__ import annotations

import hashlib
import logging
from enum import Enum
from typing import Any, Iterable, Optional

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

#: `B1703` / `D-2026-10-30-01`. The warning a person accepts before a chat
#: runs steps unasked — it was one sentence and a *Turn on* button
#: (`AUTO_TURN_ON_SENTENCE`) and recorded nothing. Short and plain (Doc 2 § 5:
#: not a wall), but it names the risk the ruling names: what the agent reads
#: can steer what it does next, within everything the chat can do. It says
#: what still asks, because that is true and a person deciding should know it
#: (`B1341`: a destructive call asks under Auto). The browser shows these
#: words from `GET …/approval-mode` and sends back their id (`warning_id`):
#: a copy in the page could drift, and an acceptance of words the server no
#: longer says is not an informed one.
AUTO_WARNING = (
    "In this chat, Pantheon will run tool steps without asking you — even after it has "
    "read a web page, a file or an email. What it reads there can steer what it does "
    "next, within everything this chat can do: writing files, running commands, sending "
    "mail. A step that deletes or overwrites something still asks."
)

#: The control that accepts it — the ruling's own words — and the one that
#: does not, which leaves the gate where it was.
PROCEED_LABEL = "Proceed to auto-approve"
KEEP_ASKING_LABEL = "Keep asking me"

#: `B1703`. Refusals, in the words of rule 7: what happened, then what to do.
AUTO_NOT_ACCEPTED_SENTENCE = (
    "Auto-approve turns on only when you accept its warning. Read it, and choose "
    f"“{PROCEED_LABEL}” if you accept the risk."
)
AUTO_WARNING_CHANGED_SENTENCE = (
    "The warning changed since you read it. Read it again, and choose "
    f"“{PROCEED_LABEL}” if you accept the risk."
)

#: What an acceptance is for — `AutoApproveAcceptance.subject`.
SUBJECT_CHAT = "chat"
SUBJECT_HIRE = "hire"

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


def warning_id(text: str) -> str:
    """`B1703`. A warning's id: the first 16 hex digits of the SHA-256 of its
    exact words. What a request names to say *I read this one*, and what the
    record keeps, so an acceptance names the words it was of — a release that
    rewords a warning gives it a new id, and a hire whose effects change gives
    its warning new words."""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:16]


def chat_warning() -> dict:
    """`B1703`. A chat's warning, as the route serves it and checks it."""
    return {"text": AUTO_WARNING, "id": warning_id(AUTO_WARNING)}


class AutoRefused(Exception):
    """`B1703`. A lifted gate this module will not record, and why."""

    def __init__(self, sentence: str, status: int = 400):
        super().__init__(sentence)
        self.sentence = sentence
        self.status = status


def check_acceptance(sent: Any, warning: dict) -> None:
    """`B1703`. Raise `AutoRefused` unless `sent` is the id of `warning` —
    the act of accepting the words the server says now.

    Nothing sent (or not a string) is no acceptance: 400, *accept its
    warning*. An id of other words — a page open since a release reworded it,
    a hire whose effects changed under the form — is 409, *the warning
    changed*: accepting what one no longer reads is not informed."""
    if not isinstance(sent, str) or not sent.strip():
        raise AutoRefused(AUTO_NOT_ACCEPTED_SENTENCE, 400)
    if sent.strip() != warning["id"]:
        raise AutoRefused(AUTO_WARNING_CHANGED_SENTENCE, 409)


def acceptance_for(subject: str, subject_id: Any, owner: Optional[str], *, db: Any = None):
    """`B1703`. The open acceptance of one chat or hire **by this person**, or
    None. Someone else's acceptance is not this person's: a chat's runs are its
    owner's, a hire's its hirer's, and an acceptance answers only for whoever
    made it. Never raises — `current_auto_approve_acceptance` reads a failure
    as none."""
    if not subject_id:
        return None
    from core.database import current_auto_approve_acceptance
    from src.owner_identity import owner_key

    record = current_auto_approve_acceptance(subject, str(subject_id), db=db)
    if record is None or not owner_key(owner) or owner_key(record.get("by")) != owner_key(owner):
        return None
    return record


def lifted_effects(allow_effects: Iterable[Any]) -> frozenset:
    """`B1703`. Of a hire's *allow* effects, the ones a lift answers — those
    the post-external gate asks about (`POST_EXTERNAL_BLOCKED_EFFECTS`). An
    allowed read of the public web was never asked about, so it is neither
    named in the warning nor needed in the acceptance."""
    from src.tool_capabilities import POST_EXTERNAL_BLOCKED_EFFECTS

    gated = {e.value for e in POST_EXTERNAL_BLOCKED_EFFECTS}
    return frozenset(str(getattr(e, "value", e)) for e in (allow_effects or ())) & gated


def hire_acceptance(hire_id: Any, owner: Optional[str], allow_effects: Iterable[Any], *,
                    db: Any = None):
    """`B1703`. This hire's person's acceptance of a warning naming every
    effect its table now lets run after outside content, or None. An
    acceptance of fewer — the hire was changed, or its agent's file, to allow
    more since — covers nothing: *changing which effects are allow re-asks*.
    Fewer now than accepted is still covered, because setting an effect back
    to ask is turning a gate back on, which never asks. Nothing to lift is
    None. The one rule, for the run (`hire_lift_for`) and the hire's page
    (`hires.auto_approve_state`) alike."""
    lifted = lifted_effects(allow_effects)
    if not lifted:
        return None
    record = acceptance_for(SUBJECT_HIRE, hire_id, owner, db=db)
    return record if record is not None and lifted <= set(record.get("effects") or ()) else None


def hire_accepted(hire_id: Any, owner: Optional[str], allow_effects: Iterable[Any], *,
                  db: Any = None) -> bool:
    """`B1703`. Whether `hire_acceptance` finds one."""
    return hire_acceptance(hire_id, owner, allow_effects, db=db) is not None


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
         privilege nobody has any more;
      4. `B1703`: this person's acceptance of the warning is on record for
         this chat. A chat set to Auto before acceptances were recorded, or
         one whose `approval_mode` column reached `auto` any other way, is
         Manual approve until its person accepts.

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
    if acceptance_for(SUBJECT_CHAT, session_id, owner) is None:
        # `B1703`. No acceptance on record, no lift — whatever the column says.
        logger.info(
            "[approval] chat %s is set to auto but %r has not accepted its warning; "
            "manual approve (B1703)", session_id, owner,
        )
        return DEFAULT_APPROVAL_MODE
    return ApprovalMode.AUTO


def hire_lift_for(
    owner: Optional[str],
    *,
    hired: bool,
    hire_id: Any = None,
    allow_effects: Iterable[Any] = (),
    delegated_credential: bool = False,
    auth_manager: Any = None,
) -> bool:
    """`D-2026-10-29-01` §1 (`B1605`). Whether a run's hire lifts the
    post-external gate for the actions its table allows.

    *"Lifting it is held to the people Auto is held to"* — so it is this
    module's question, asked of `may_use_auto` and nothing else (`Law 7`):
    a hired agent's run (`ToolPolicy.hired`, set by the task engine for a
    hire's task and for nothing else), not a bearer token's (`B70`), whose
    person holds `can_auto_approve` — asked **per run**, so an admin taking the
    privilege away takes the lift away at the hire's next run. Every other run
    answers False, and for it the gate is exactly as it was. Never raises.

    `B1703` / `D-2026-10-30-01`: **and whose person accepted the warning
    naming what the lift runs unasked** (`hire_accepted`, of `hire_id` and the
    run's `allow_effects`). A hire with no acceptance on record — every hire
    made before acceptances were recorded, a hire made by someone granted
    `can_auto_approve` later — lifts nothing until its person accepts.
    """
    if not hired or delegated_credential:
        return False
    if not may_use_auto(owner, auth_manager=auth_manager):
        return False
    if not hire_accepted(hire_id, owner, allow_effects):
        if lifted_effects(allow_effects):
            logger.info(
                "[approval] hire %s allows %s after outside content only once %r accepts its "
                "warning; asking (B1703)", hire_id, ", ".join(sorted(lifted_effects(allow_effects))),
                owner,
            )
        return False
    return True


def set_mode_for(session_id: Any, mode: Any) -> bool:
    """Persist one chat's approval mode. Best-effort, like `set_session_mode`.

    The privilege is checked by the caller (the route), not here: this is the
    store's door, and a second copy of the privilege question would be a second
    place for it to be answered differently (`Law 7`).

    `B1703`: setting **Manual** also withdraws the chat's acceptance — turning
    a gate back on never asks, and it ends what was accepted, so Auto turned on
    again is a new acceptance of the warning as it reads then. Setting **Auto**
    here records nothing, and a chat set to Auto with nothing on record reads
    as Manual (`mode_for`): the one way on is `turn_auto_on`.
    """
    from core.database import set_session_approval_mode, withdraw_auto_approve_acceptance

    resolved = coerce_approval_mode(mode)
    saved = set_session_approval_mode(str(session_id), resolved.value)
    if resolved is ApprovalMode.MANUAL:
        try:
            withdraw_auto_approve_acceptance(SUBJECT_CHAT, str(session_id))
        except Exception as exc:  # noqa: BLE001 — the gate is back on either way
            logger.warning("could not withdraw the Auto-approve acceptance of chat %s: %s",
                           session_id, exc)
    return saved


def turn_auto_on(session_id: Any, person: Optional[str], accepted_warning: Any) -> dict:
    """`B1703`. Turn one chat to Auto on its person's acceptance, and answer
    the record. Raises `AutoRefused` without an acceptance of the warning as
    it reads now (`check_acceptance`) or when either write fails — nothing is
    turned on with nothing on record.

    The privilege and who is asking are the route's questions (as for
    `set_mode_for`); this is the one door that records the acceptance and
    sets the column, in that order, so a chat is never Auto with no record.
    """
    from core.database import record_auto_approve_acceptance, withdraw_auto_approve_acceptance
    from src.owner_identity import normalize_owner

    warning = chat_warning()
    check_acceptance(accepted_warning, warning)
    by = normalize_owner(person)
    if not by:
        raise AutoRefused(AUTO_NOT_ALLOWED_SENTENCE, 403)
    try:
        record = record_auto_approve_acceptance(
            SUBJECT_CHAT, str(session_id), by, warning["id"], warning["text"])
    except Exception as exc:  # noqa: BLE001 — refused in a sentence, never on with no record
        logger.warning("could not record the Auto-approve acceptance of chat %s: %s", session_id, exc)
        raise AutoRefused("That did not save. Try again.", 500) from None
    from core.database import set_session_approval_mode

    if not set_session_approval_mode(str(session_id), ApprovalMode.AUTO.value):
        try:
            withdraw_auto_approve_acceptance(SUBJECT_CHAT, str(session_id))
        except Exception:  # noqa: BLE001
            logger.warning("could not withdraw the acceptance of chat %s after a failed save",
                           session_id)
        raise AutoRefused("That did not save. Try again.", 500)
    logger.info("[approval] %s accepted Auto-approve's warning %s for chat %s",
                by, warning["id"], session_id)
    return record
