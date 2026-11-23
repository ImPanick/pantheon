# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Assistant becomes Apollo for people who already had one.

Only the old default name moves. A name the person typed in Apollo settings is
theirs and stays. The `apollo` tool is added to the crew member's kit when the
kit is an explicit list, so their Apollo chat can keep tasks and the notebook.
"""

from __future__ import annotations

import json
from typing import Any

from src.apollo import APOLLO_NAME

OLD_NAME = "Assistant"


def become_apollo(db, crew: Any) -> bool:
    """Rename the default-named Assistant (and its chat) to Apollo and give it
    the `apollo` tool. Returns whether anything changed; the caller commits."""
    changed = False
    if (crew.name or "").strip() in ("", OLD_NAME):
        crew.name = APOLLO_NAME
        changed = True
    raw = getattr(crew, "enabled_tools", None)
    if raw:
        try:
            tools = json.loads(raw)
        except (TypeError, ValueError):
            tools = None
        if isinstance(tools, list) and "apollo" not in tools:
            tools.append("apollo")
            crew.enabled_tools = json.dumps(tools)
            changed = True
    if getattr(crew, "session_id", None):
        from core.database import Session as DbSession
        sess = db.query(DbSession).filter(DbSession.id == crew.session_id).first()
        if sess is not None and (sess.name or "").strip() in ("", OLD_NAME):
            sess.name = APOLLO_NAME
            changed = True
    return changed
