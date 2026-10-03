# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared helpers used across tool implementation domains.

Extracted from tool_implementations.py as part of slice 1 (#4082/#4071).
Domain modules under src/tools/ import from here.
"""
from typing import Dict, Optional

from core.constants import internal_api_base
from src.tool_utils import _parse_tool_args  # noqa: F401 — single source of the tool-arg parser; tool_utils is a leaf module (imports nothing from src)


# In-process loopback base for agent tools that call Pantheon's own API
# (cookbook state, model serve, gallery, email, calendar). We ride the
# per-process internal token so require_admin lets us through. See
# core/middleware.py. Resolution (override / APP_PORT / 7000) lives in
# core.constants.internal_api_base().
_INTERNAL_BASE = internal_api_base()


def _internal_headers(owner: Optional[str] = None) -> Dict[str, str]:
    """The loopback's headers: the internal-tool token, and the person the
    request acts for as `X-Pantheon-Owner`.

    `B1179`. A caller that names nobody gets the person the running tool call
    acts for (`tool_execution.get_tool_person`, bound by the dispatcher), so a
    tool's loopback is asked what its person's own request is asked
    (`core.middleware.require_admin`, `B1175`) wherever in the tool it is made.
    Outside a tool call nothing is bound and the loopback names nobody:
    Pantheon itself, as the scheduler's actions and the Forge lifecycle loop
    call (each with headers of its own).
    """
    from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
    headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
    if not owner:
        from src.tool_execution import get_tool_person
        owner = get_tool_person()
    if owner:
        headers["X-Pantheon-Owner"] = owner
    return headers
