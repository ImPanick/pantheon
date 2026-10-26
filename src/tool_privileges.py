# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1191`, the owner's call (`D-2026-10-26-01` §5) — a Tools entry switched
off for one person.

*"A tool switched off for a person is hidden, its routes refused, and that
person's background work for it paused with a sentence saying why; nothing is
deleted."*

Brain, Deep Research, Gallery and the Library had a person's switch; eight
Tools entries had none — Assistant, Calendar, Compare, Email, Notes, Tasks,
Theme and Workbench. Each has one now, a privilege in `DEFAULT_PRIVILEGES`
(on, so nothing changes until an admin turns one off in Settings → Users), and
this module is the one place that says what each takes:

  * **the door** — `static/js/ui_visibility.js` (`TOOL_VISIBILITY`'s
    `privilege:`), the same table every door reads;
  * **the routes** — `tool_privilege(key)`, mounted on the tool's router as a
    dependency, so a window reached anyway (an old tab, a typed URL, a token)
    is refused in the sentence the door says;
  * **the agent** — `withheld_agent_tools`, the tools the chat withholds;
  * **background work** — `may_use_tool`, asked by each loop that works for
    a person without their window: their scheduled tasks and workflows and the
    Assistant's check-ins (`held_by_switch`), the actions that read their mail
    or calendar (`ACTION_TOOLS`), the inbox check, mail scheduled to send later,
    and note reminders. Each holds that person's work while the switch is off
    and says so; nothing is deleted, and turning it back on is all it takes.

A privilege store that cannot be read refuses (`B531`).

`B1488`, the owner's ruling: each of the eight also has a switch for
**everyone** — a key in `DEFAULT_FEATURES` (`TOOL_FEATURES` below), set in
Settings → Agent Tools, the shape Brain, Deep Research, Gallery and the Library
already have. Off for everyone outranks on for a person, as
`ui_visibility.toolOff` orders the columns: the door goes (`TOOL_VISIBILITY`'s
`feature:`), the routes refuse everyone (`everyone_switch`, `require_feature`
beside `tool_privilege` on each router), the agent's tools go
(`tool_security._FEATURE_TOOLS`, read from `TOOL_PRIVILEGES` here), and every
piece of background work above holds for everyone — `may_use_tool` asks the
everyone switch first — with the sentence that names that switch. Nothing is
deleted.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

_EMAIL_TOOLS = frozenset({
    "list_email_accounts", "list_emails", "read_email", "search_emails",
    "scan_email_unsubscribes", "unsubscribe_email", "send_email", "draft_email",
    "draft_email_reply", "ai_draft_email_reply", "reply_to_email", "bulk_email",
    "delete_email", "archive_email", "mark_email_read", "download_attachment",
})

#: privilege key → (the Tools entry's name, the agent tools it withholds)
TOOL_PRIVILEGES: Dict[str, tuple] = {
    "can_use_assistant": ("Assistant", frozenset()),
    "can_use_calendar": ("Calendar", frozenset({"manage_calendar"})),
    "can_use_compare": ("Compare", frozenset()),
    "can_use_email": ("Email", _EMAIL_TOOLS),
    "can_use_notes": ("Notes", frozenset({"manage_notes"})),
    "can_use_tasks": ("Tasks", frozenset({"manage_tasks"})),
    "can_use_theme": ("Theme", frozenset()),
    "can_use_workbench": ("Workbench", frozenset()),
}


#: `B1488`. privilege key → the `DEFAULT_FEATURES` key of the same Tools
#: entry's switch for everyone. `static/js/ui_visibility.js`'s
#: `TOOL_VISIBILITY` names both on each entry (`privilege:`, `feature:`).
TOOL_FEATURES: Dict[str, str] = {
    "can_use_assistant": "assistant",
    "can_use_calendar": "calendar",
    "can_use_compare": "compare",
    "can_use_email": "email",
    "can_use_notes": "notes",
    "can_use_tasks": "tasks",
    "can_use_theme": "theme",
    "can_use_workbench": "workbench",
}


def label(key: str) -> str:
    return TOOL_PRIVILEGES.get(key, (key, None))[0]


def off_for_everyone(key: str) -> bool:
    """`B1488`. Is this Tools entry switched off for everyone? Read the way
    every feature switch is read (`feature_gate.feature_enabled`: a features
    file that cannot be read leaves everything on, and the person's column
    still holds)."""
    feature = TOOL_FEATURES.get(key)
    if not feature:
        return False
    from src.feature_gate import feature_enabled
    return not feature_enabled(feature)


def everyone_switch(key: str):
    """`B1488`. A router dependency: the entry's switch for everyone, as
    `require_feature` refuses — every caller, an admin and a request naming
    nobody included — in the door's *everyone* words."""
    from src.feature_gate import require_feature
    return require_feature(TOOL_FEATURES[key], label=label(key))


def off_sentence(key: str) -> str:
    """The sentence a refused door says (`ui_visibility.toolRefusal`): the
    *everyone* one when the entry is off for everyone (`B1488`), else the
    person's — so the route and the page read alike."""
    if off_for_everyone(key):
        from src.feature_gate import feature_off_sentence
        return feature_off_sentence(label(key))
    return (f"{label(key)} is switched off for your account. An admin can turn it back on "
            "in Settings → Users.")


def paused_sentence(key: str) -> str:
    """What a paused piece of background work says — naming the switch that
    holds it (`B1488`: the one for everyone, when that is the one off)."""
    if off_for_everyone(key):
        return (f"Paused: {label(key)} is switched off for everyone. Nothing was deleted; an admin "
                "can turn it back on in Settings → Agent Tools, and it runs again from then.")
    return (f"Paused: {label(key)} is switched off for this account. Nothing was deleted; an admin "
            "can turn it back on in Settings → Users, and it runs again from then.")


def _auth_manager():
    from src.auth_manager_access import shared_auth_manager
    return shared_auth_manager()


def may_use_tool(owner: Optional[str], key: str, *, auth_manager: Any = None) -> bool:
    """Whether `owner` may use the Tools entry `key` names — for background
    work, which has no request. Off for everyone (`B1488`) holds everybody's,
    Pantheon's own and an admin's included. Otherwise nobody named (Pantheon's
    own work) may; an admin may; a store that cannot be read may not, said
    once (`B531`)."""
    if off_for_everyone(key):
        return False
    return _person_may(owner, key, auth_manager=auth_manager)


def _person_may(owner: Optional[str], key: str, *, auth_manager: Any = None) -> bool:
    """The person's column of `may_use_tool` (`B1191`)."""
    from src.owner_identity import is_request_sentinel_owner, normalize_owner
    name = normalize_owner(owner)
    if not name or is_request_sentinel_owner(name):
        return True
    try:
        mgr = auth_manager if auth_manager is not None else _auth_manager()
        if mgr is None or not getattr(mgr, "is_configured", False):
            return True
        if name not in (getattr(mgr, "users", None) or {}):
            return True    # a row from before sign-in, or a removed person: not this switch's question
        from src.auth_helpers import resolve_privilege
        privs = mgr.get_privileges(name) or {}
        return resolve_privilege(privs if isinstance(privs, dict) else {}, key) is not False
    except Exception as e:  # noqa: BLE001 — refused, never granted
        from src.log_once import log_once
        log_once(logger, logging.WARNING, f"tool-privilege-unreadable:{key}",
                 "could not read %s for %r (%s); that work is held until it can be read", key, owner, e)
        return False


def tool_privilege(key: str):
    """A router dependency: refuse every route of a tool switched off for the
    person asking. A request naming nobody is left to the route's own check;
    a token answers for the person who minted it."""
    def _check(request: Request) -> None:
        from src.auth_helpers import effective_user, privileges_or_refuse, resolve_privilege
        from src.owner_identity import is_request_sentinel_owner
        user = effective_user(request)
        if not user or is_request_sentinel_owner(user):
            return
        mgr = getattr(getattr(request.app, "state", None), "auth_manager", None)
        if mgr is None or not getattr(mgr, "is_configured", False):
            return
        privs = privileges_or_refuse(mgr, user)
        if resolve_privilege(privs, key) is False:
            raise HTTPException(403, off_sentence(key))

    _check.__name__ = f"require_{key}"
    return _check


def refuse_unless(request: Any, key: str) -> None:
    """The same checks, called from inside a route (a router shared with an
    auth-exempt path, or a bridge that calls another router's endpoint): the
    switch for everyone first (`B1488`), then the person's."""
    everyone_switch(key)()
    tool_privilege(key)(request)


def withheld_agent_tools(privs: Dict[str, Any]) -> Set[str]:
    """The agent tools a person's switched-off Tools entries take with them."""
    from src.auth_helpers import resolve_privilege
    out: Set[str] = set()
    for key, (_label, tools) in TOOL_PRIVILEGES.items():
        if tools and resolve_privilege(privs, key) is False:
            out |= set(tools)
    return out


#: A built-in action's work, by the Tools entries it reaches into: held while
#: any of them is switched off for the task's owner.
ACTION_TOOLS: Dict[str, tuple] = {
    "summarize_emails": ("can_use_email",),
    "draft_email_replies": ("can_use_email",),
    "email_auto_translate": ("can_use_email",),
    "learn_sender_signatures": ("can_use_email",),
    "check_email_urgency": ("can_use_email",),
    "extract_email_events": ("can_use_email", "can_use_calendar"),
    "classify_events": ("can_use_calendar",),
    "daily_brief": ("can_use_assistant",),
}


def _is_assistant_check_in(db, task) -> bool:
    crew_id = getattr(task, "crew_member_id", None)
    if not crew_id:
        return False
    try:
        from core.database import CrewMember
        row = db.query(CrewMember.is_default_assistant).filter(CrewMember.id == crew_id).first()
        return bool(row and row[0])
    except Exception:
        return False


def held_by_switch(db, task) -> Optional[str]:
    """The privilege a scheduled task waits on, or None to run it: the
    Workbench for a workflow, the Assistant for its check-ins, Tasks for any
    other task — and an action's own Tools entries (`ACTION_TOOLS`)."""
    owner = getattr(task, "owner", None)
    kind = (getattr(task, "task_type", None) or "llm")
    key = ("can_use_workbench" if kind == "workflow"
           else "can_use_assistant" if _is_assistant_check_in(db, task)
           else "can_use_tasks")
    for need in (key,) + ACTION_TOOLS.get(getattr(task, "action", None) or "", ()):
        if not may_use_tool(owner, need):
            return need
    return None


def withheld_for_owner(owner: Optional[str], *, auth_manager: Any = None) -> Set[str]:
    """`withheld_agent_tools` for a person by name — what `agent_loop` asks for
    every run, a chat's or a scheduled one's."""
    out: Set[str] = set()
    for key, (_label, tools) in TOOL_PRIVILEGES.items():
        # The person's column only: the everyone column reaches the same set
        # as a feature (`tool_security.feature_disabled_tools`, `B1488`), so a
        # tool it takes is recorded as withheld by the feature, not by them.
        if tools and not _person_may(owner, key, auth_manager=auth_manager):
            out |= set(tools)
    return out


def feature_tools() -> Dict[str, Set[str]]:
    """`B1488`. Each everyone switch's agent tools, read from `TOOL_PRIVILEGES`
    so the person's column and everyone's take one list
    (`tool_security._FEATURE_TOOLS` folds these in)."""
    return {TOOL_FEATURES[key]: set(tools) for key, (_label, tools) in TOOL_PRIVILEGES.items() if tools}


__all__ = ["ACTION_TOOLS", "TOOL_FEATURES", "TOOL_PRIVILEGES", "everyone_switch", "feature_tools",
           "held_by_switch", "label", "may_use_tool", "off_for_everyone", "off_sentence",
           "paused_sentence", "refuse_unless", "tool_privilege", "withheld_agent_tools",
           "withheld_for_owner"]
