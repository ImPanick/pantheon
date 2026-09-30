# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who may use the workstation, and the one call every tool makes to reach it
— `P20-02`, `D-2026-09-30-03`.

Three conditions, all of them, in this order, and a sentence for each that
fails — because a tool that silently runs somewhere else is the one outcome
this phase exists to prevent (`P20-03`: *a turn is never silently moved*):

  1. an admin switched the workstation on (`workstation_enabled`);
  2. it has an address (the setting, or the overlay's environment);
  3. the person may use it: an admin, the single-user owner, or anyone whose
     privileges resolve `can_use_workstation` true (`src.auth_helpers.
     resolve_privilege` — one resolver for every privilege, `Law 13`).

`routes_tools(owner)` is the question `P20-03` asks before a shell or file tool
runs: is this turn's work done in the workstation? It is the three conditions
plus the admin's `workstation_route_tools` switch.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from src import workstation_client as wc
from src.workstation_client import WorkstationClient, WorkstationError

logger = logging.getLogger(__name__)

PRIVILEGE = "can_use_workstation"


def may_use(owner: Optional[str]) -> bool:
    """The privilege, resolved the way every privilege is."""
    try:
        from src.tool_security import owner_is_admin_or_single_user
        if owner_is_admin_or_single_user(owner):
            return True
        if not owner:
            return False
        from core.auth import AuthManager
        from src.auth_helpers import resolve_privilege
        privs = AuthManager().get_privileges(owner) or {}
        return bool(resolve_privilege(privs if isinstance(privs, dict) else {}, PRIVILEGE))
    except Exception as e:  # noqa: BLE001 — an unanswerable question is a no
        logger.warning("could not resolve %s for %r: %s", PRIVILEGE, owner, e)
        return False


def workstation_for(owner: Optional[str]) -> Tuple[WorkstationClient, str]:
    """`(client, account)` for this person, or a `WorkstationError` saying which
    condition failed and who can change it."""
    if not wc.enabled():
        raise WorkstationError("off", "The workstation is switched off. An admin turns it on in "
                                      "Settings → Workstation.")
    client = wc.from_settings()
    if client is None:
        raise WorkstationError("unconfigured", "The workstation is on but has no address. Start "
                                               "it with the workstation overlay, or set its "
                                               "address in Settings → Workstation.")
    if not may_use(owner):
        raise WorkstationError("not_permitted", "Your account may not use the workstation. An "
                                                "admin can allow it in Settings → Users.")
    return client, wc.account_for(owner)


def routes_tools(owner: Optional[str]) -> bool:
    """Does this person's shell and file work run in the workstation?

    True when the workstation is on, has an address, the admin has not
    switched routing off, and the person may use it. When the workstation is
    on but DOWN this is still true — the tool then reports it down rather than
    running in Pantheon's container instead."""
    try:
        from src.settings import get_setting
        if get_setting("workstation_route_tools", True) is False:
            return False
    except Exception:  # noqa: BLE001
        pass
    return wc.enabled() and wc.configured_base() is not None and may_use(owner)


__all__ = ["PRIVILEGE", "may_use", "routes_tools", "workstation_for"]
