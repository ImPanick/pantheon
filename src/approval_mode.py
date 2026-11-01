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

#: `B1706`. The other mode's name, as this module has always called it.
MANUAL_LABEL = "Manual approve"

#: `B1706`. The setting's own name — the heading of the composer's mode menu
#: and the first words of its chip's accessible name.
SETTING_LABEL = "Approval mode"

#: `B1706`. The two modes as the composer's selector offers them, in the order
#: it lists them: the name in the menu, the one word on the chip (*"a compact
#: chip naming the current mode"*), and one line naming the consequence (Doc 2
#: § 5: a consequence, not a mechanism). Served by `GET …/approval-mode` as
#: `modes`, so the browser shows these words and holds no copy (`Law 7`,
#: `Law 10`). Auto's line ends where its warning ends, because it is true
#: (`B1341`) and the menu is where a person decides.
MODE_CHOICES = (
    {
        "mode": ApprovalMode.MANUAL.value,
        "label": MANUAL_LABEL,
        "short_label": "Manual",
        "description": "Pantheon stops and asks you before a step that needs your yes.",
    },
    {
        "mode": ApprovalMode.AUTO.value,
        "label": AUTO_LABEL,
        "short_label": "Auto",
        "description": (
            "Pantheon runs tool steps without asking you. "
            "A step that deletes or overwrites something still asks."
        ),
    },
)


def mode_choices() -> list:
    """`B1706`. `MODE_CHOICES` as the route serves them — fresh copies, so no
    caller can change the module's words in place."""
    return [dict(choice) for choice in MODE_CHOICES]


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
#: `B1725` / `D-2026-11-01-02`. A person's own workstation, run as a
#: computer the agent uses: its `subject_id` is the person (`owner_key`),
#: because a workstation is one person's (`workstation_access.account_of`).
SUBJECT_WORKSTATION = "workstation"
SUBJECTS = (SUBJECT_CHAT, SUBJECT_HIRE, SUBJECT_WORKSTATION)

#: `B1725` / `D-2026-11-01-02`. **Computer Use**: no card for a step the
#: agent takes inside the person's own workstation, after outside content
#: too — the owner, verbatim: *"almost a full blown 'Computer Use' mode for
#: that VM specifically - with restrictions lifted because its sandboxed and
#: can be reset to zero again"*, and on the card, *"Full mode, no asks
#: inside"*. Turned on as every lift is (`D-2026-10-30-01`): only by a
#: person accepting these words, on record. They name what the ruling
#: names: what the agent reads can steer it inside the workstation, which
#: reaches the internet, so whatever is in it can be sent out — the projects
#: folder Pantheon shares with it among them; and what still asks: a command
#: that deletes or overwrites (`D-2026-10-17-01`'s one exception, kept,
#: because Reset does not bring the shared projects folder back), and
#: everything that is not the workstation.
WORKSTATION_LABEL = "Computer Use"
WORKSTATION_WARNING = (
    "On your workstation, Pantheon will click, type, run commands and install software "
    "without asking you — even after it has read a web page, a file or an email. What it "
    "reads can steer what it does next there, and the workstation reaches the internet, so "
    "a page could steer it into sending out anything the workstation holds: your projects "
    "folder, files you put there, and logins saved in its browser. A command that deletes "
    "or overwrites files still asks, because your projects folder is shared with Pantheon "
    "and Reset does not bring it back. Steps that touch Pantheon itself — memory, skills, "
    "messages, settings — still ask."
)
WORKSTATION_PROCEED_LABEL = "Turn on Computer Use"
WORKSTATION_NOT_ALLOWED_SENTENCE = (
    "Computer Use is held to the people who may use Auto-approve and the workstation. "
    "An admin grants both in Settings › Users."
)
WORKSTATION_NOT_ACCEPTED_SENTENCE = (
    "Computer Use turns on only when you accept its warning. Read it, and choose "
    f"“{WORKSTATION_PROCEED_LABEL}” if you accept the risk."
)
WORKSTATION_WARNING_CHANGED_SENTENCE = (
    "The warning changed since you read it. Read it again, and choose "
    f"“{WORKSTATION_PROCEED_LABEL}” if you accept the risk."
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


def workstation_warning() -> dict:
    """`B1725`. Computer Use's warning, as the route serves it and checks it."""
    return {"text": WORKSTATION_WARNING, "id": warning_id(WORKSTATION_WARNING)}


def check_acceptance(sent: Any, warning: dict) -> None:
    """`B1703`. Raise `AutoRefused` unless `sent` is the id of `warning` —
    the act of accepting the words the server says now.

    Nothing sent (or not a string) is no acceptance: 400, *accept its
    warning*. An id of other words — a page open since a release reworded it,
    a hire whose effects changed under the form — is 409, *the warning
    changed*: accepting what one no longer reads is not informed."""
    workstation = warning.get("id") == warning_id(WORKSTATION_WARNING)
    if not isinstance(sent, str) or not sent.strip():
        raise AutoRefused(WORKSTATION_NOT_ACCEPTED_SENTENCE if workstation
                          else AUTO_NOT_ACCEPTED_SENTENCE, 400)
    if sent.strip() != warning["id"]:
        raise AutoRefused(WORKSTATION_WARNING_CHANGED_SENTENCE if workstation
                          else AUTO_WARNING_CHANGED_SENTENCE, 409)


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


def open_acceptances(*, auth_manager: Any = None) -> list:
    """`B1705`. Every open acceptance, across chats and hires, for an admin.

    Each record (`core.database.open_auto_approve_acceptances`) carries
    `in_effect`: whether its person still holds `can_auto_approve` — the
    question `mode_for` and `hire_lift_for` ask at every run, so an
    acceptance whose person lost the privilege is on record and lifts
    nothing — and `effect_words`, a hire's effects in the hire form's words. A chat whose column was set back to Manual withdrew its
    acceptance (`set_mode_for`), so it is not here. Raises on a failed
    read, like the store."""
    from core.database import open_auto_approve_acceptances

    from src.agents.hires import EFFECT_WORDS

    records = open_auto_approve_acceptances()
    answers: dict = {}
    stations: dict = {}
    for record in records:
        by = record.get("by")
        if by not in answers:
            answers[by] = may_use_auto(by, auth_manager=auth_manager)
        record["in_effect"] = answers[by]
        if record.get("subject") == SUBJECT_WORKSTATION:
            # `B1725`. Computer Use is held to the workstation's people too,
            # and lifts only on the warning as it reads now.
            if by not in stations:
                stations[by] = may_use_computer_use(by, auth_manager=auth_manager)
            record["in_effect"] = bool(
                stations[by] and record.get("warning_id") == workstation_warning()["id"])
        # The hire form's words for what runs unasked (`Law 7`), not the ids.
        record["effect_words"] = [EFFECT_WORDS.get(e, e.replace("_", " "))
                                  for e in record.get("effects") or ()]
    return records


def withdraw_for(subject: Any, subject_id: Any) -> bool:
    """`B1705`. An admin turning someone's gate back on: a chat goes to
    Manual approve (which withdraws its acceptance, `set_mode_for`), a hire's
    acceptance is withdrawn so its runs ask after outside content again.
    Turning a gate back on never asks, so this needs no acceptance; it is
    the direction every refusal in this module already goes. Answers whether
    anything was open. Raises `AutoRefused` for a subject this module does
    not have, or when the write fails."""
    from core.database import current_auto_approve_acceptance, withdraw_auto_approve_acceptance

    sid = str(subject_id or "").strip()
    if subject not in SUBJECTS or not sid:
        raise AutoRefused("Name a chat, a hire or a workstation.", 400)
    if subject == SUBJECT_WORKSTATION:
        # `B1725`. A workstation's acceptance is keyed by its person.
        from src.owner_identity import owner_key

        sid = owner_key(sid) or sid
    was_open = current_auto_approve_acceptance(subject, sid) is not None
    try:
        if subject == SUBJECT_CHAT:
            if not set_mode_for(sid, ApprovalMode.MANUAL):
                raise AutoRefused("That did not save. Try again.", 500)
        else:
            withdraw_auto_approve_acceptance(subject, sid)
    except AutoRefused:
        raise
    except Exception as exc:  # noqa: BLE001 — refused in a sentence
        logger.warning("could not withdraw the Auto-approve acceptance of %s %s: %s",
                       subject, sid, exc)
        raise AutoRefused("That did not save. Try again.", 500) from None
    return was_open


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


# ── `B1725` / `D-2026-11-01-02` · Computer Use, on a person's own workstation ──


def workstation_acceptance(owner: Optional[str], *, db: Any = None):
    """`B1725`. This person's open acceptance of Computer Use's warning **as
    it reads now**, or None. One accepted before a release reworded the
    warning covers nothing — the words a person accepted are the risk they
    took, and a new risk is a new acceptance (`D-2026-10-30-01`)."""
    from src.owner_identity import owner_key

    key = owner_key(owner)
    if not key:
        return None
    record = acceptance_for(SUBJECT_WORKSTATION, key, owner, db=db)
    if record is None or record.get("warning_id") != workstation_warning()["id"]:
        return None
    return record


def may_use_computer_use(owner: Optional[str], *, auth_manager: Any = None) -> bool:
    """`B1725`. Whether this person may turn Computer Use on: held to the
    people Auto is held to (`can_auto_approve`, `D-2026-10-29-01`'s rule for
    every lift) **and** who may use the workstation (`can_use_workstation`),
    since it is their workstation it is about. Never raises."""
    if not may_use_auto(owner, auth_manager=auth_manager):
        return False
    try:
        from src.workstation_access import may_use

        return may_use(owner, auth_manager=auth_manager)
    except Exception:  # noqa: BLE001 — an unanswerable question is a no
        return False


def workstation_lift_for(
    owner: Optional[str],
    *,
    delegated_credential: bool = False,
    auth_manager: Any = None,
) -> bool:
    """`B1725` / `D-2026-11-01-02`. Whether a run's steps inside its person's
    workstation run without a card.

    All of, asked **per run** as `mode_for` asks Auto's (a privilege an admin
    takes away ends the lift at the next turn):

      1. a person, not a bearer token (`B70`: a token has nobody to have
         accepted anything);
      2. who may use Computer Use (`may_use_computer_use`);
      3. whose acceptance of the warning as it reads now is on record
         (`workstation_acceptance`) — none, and the gate asks as it always
         did.

    What the lift answers, and what it never does, is the gate's
    (`ToolRunSecurityContext._workstation_decision_for`): only a step that
    runs inside the workstation. Never raises."""
    if delegated_credential:
        return False
    if not may_use_computer_use(owner, auth_manager=auth_manager):
        return False
    try:
        return workstation_acceptance(owner) is not None
    except Exception:  # noqa: BLE001 — no record read is no lift
        logger.debug("Computer Use acceptance unreadable for %r", owner, exc_info=True)
        return False


def computer_use_state(owner: Optional[str], *, auth_manager: Any = None) -> dict:
    """`B1725`. What the Workstation window shows: whether Computer Use is on
    for this person, whether they may turn it on, its warning and labels,
    and the record of their acceptance when there is one."""
    allowed = may_use_computer_use(owner, auth_manager=auth_manager)
    record = workstation_acceptance(owner) if owner else None
    return {
        "label": WORKSTATION_LABEL,
        "on": bool(allowed and record is not None),
        "allowed": allowed,
        "not_allowed": None if allowed else WORKSTATION_NOT_ALLOWED_SENTENCE,
        "warning": workstation_warning(),
        "proceed_label": WORKSTATION_PROCEED_LABEL,
        "keep_asking_label": KEEP_ASKING_LABEL,
        "accepted": ({"by": record.get("by"), "at": record.get("at")} if record else None),
    }


def turn_computer_use_on(person: Optional[str], accepted_warning: Any, *,
                         auth_manager: Any = None) -> dict:
    """`B1725`. Turn Computer Use on for this person's workstation, on their
    acceptance of the warning as it reads now. Raises `AutoRefused` for
    someone who may not (403), without the acceptance (400 / 409), or when
    the record cannot be written — it is never on with nothing on record."""
    from core.database import record_auto_approve_acceptance
    from src.owner_identity import normalize_owner, owner_key

    by = normalize_owner(person)
    if not by or not may_use_computer_use(by, auth_manager=auth_manager):
        raise AutoRefused(WORKSTATION_NOT_ALLOWED_SENTENCE, 403)
    warning = workstation_warning()
    check_acceptance(accepted_warning, warning)
    try:
        record = record_auto_approve_acceptance(
            SUBJECT_WORKSTATION, owner_key(by), by, warning["id"], warning["text"])
    except Exception as exc:  # noqa: BLE001 — refused in a sentence, never on with no record
        logger.warning("could not record the Computer Use acceptance of %s: %s", by, exc)
        raise AutoRefused("That did not save. Try again.", 500) from None
    logger.info("[approval] %s accepted Computer Use's warning %s for their workstation",
                by, warning["id"])
    return record


def turn_computer_use_off(person: Optional[str]) -> bool:
    """`B1725`. Turn the gate back on for this person's workstation — which
    never asks. Answers whether it was on. Raises `AutoRefused` when the
    write fails."""
    from src.owner_identity import owner_key

    key = owner_key(person)
    if not key:
        return False
    return withdraw_for(SUBJECT_WORKSTATION, key)
