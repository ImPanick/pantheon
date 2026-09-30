# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two limits one agent run is held to, read one way. `P7-10`.

`agent_max_rounds` (steps per message) and `agent_max_tool_calls` (tool calls
per message, `0` meaning none) are two settings, and until `P7-10` they were
read in exactly one place: inline in `chat_stream`, a few lines above the call
that starts the agent loop. That was fine while nothing else needed to know the
numbers. `P7-10` needs the browser to know them *before* a run starts — "how far
can it run unattended" was a settings tab away from the moment of deciding — and
a second reading written for the browser is the second copy `Law 7` forbids: the
chat route clamps the step cap to 1..200 and falls back to `MAX_AGENT_ROUNDS` on
a falsy value, and a copy that forgot either would promise one number while the
loop enforced another.

So the reading lives here and both callers ask it: the chat route when it
starts a run, and `GET /api/chat/agent-limits` when the composer asks what a run
would be held to. The local-inference lift is *not* here — it is a property of
the endpoint, not of the settings, and `src/agent_loop.agent_run_limits` applies
it with the loop's own helpers.

A leaf: standard library only at import time. The settings store and
`MAX_AGENT_ROUNDS` are imported inside the call, the way the chat route always
imported them, because both pull in far more than a module the approval gate
may one day read should carry.
"""
from __future__ import annotations

from typing import NamedTuple

AGENT_MAX_ROUNDS_KEY = "agent_max_rounds"
AGENT_MAX_TOOL_CALLS_KEY = "agent_max_tool_calls"

#: The range the admin settings route validates each cap to. The chat route has
#: always clamped the step cap into the first one on read, "in case settings.json
#: was hand-edited"; the tool-call cap it reads unclamped, and that is kept.
AGENT_MAX_ROUNDS_RANGE = (1, 200)
AGENT_MAX_TOOL_CALLS_RANGE = (0, 1000)   # 0 = no tool-call limit


class ConfiguredCaps(NamedTuple):
    """What the chat route hands `stream_agent_loop` as `max_rounds` and
    `max_tool_calls`. Before any lift: the lift belongs to the endpoint."""

    rounds: int
    tool_calls: int


def _default_rounds() -> int:
    try:
        from src.agent_tools import MAX_AGENT_ROUNDS
        return int(MAX_AGENT_ROUNDS)
    except Exception:  # pragma: no cover — the loop cannot run without it either
        return 50


def configured_agent_caps() -> ConfiguredCaps:
    """The two caps, exactly as `chat_stream` has always read them. Never raises.

    `agent_max_tool_calls`: an integer, and anything that will not parse is `0`
    — no limit — because a hand-edited `"unlimited"` must not take the stream
    down (`tests/test_agent_tool_budget_nonnumeric.py`). Not clamped, as the
    route never clamped it; a negative number reads as no limit in the loop.

    `agent_max_rounds`: a falsy value means the loop's own default,
    `MAX_AGENT_ROUNDS` (the `or` the route always had), anything that will not
    parse means the same, and the result is clamped to `AGENT_MAX_ROUNDS_RANGE`.
    """
    default_rounds = _default_rounds()
    try:
        from src.settings import get_setting
    except Exception:  # pragma: no cover — defensive, like every reader here
        return ConfiguredCaps(default_rounds, 0)
    # `Exception` rather than the two the route named: a reader the approval
    # gate may consult (`P7-12`) must not be the thing that ends a run, and for
    # `TypeError` / `ValueError` the answer is the one the route always gave.
    try:
        tool_calls = int(get_setting(AGENT_MAX_TOOL_CALLS_KEY, 0))
    except Exception:
        tool_calls = 0
    try:
        rounds = int(get_setting(AGENT_MAX_ROUNDS_KEY, default_rounds) or default_rounds)
    except Exception:
        rounds = default_rounds
    low, high = AGENT_MAX_ROUNDS_RANGE
    return ConfiguredCaps(max(low, min(rounds, high)), tool_calls)


__all__ = [
    "AGENT_MAX_ROUNDS_KEY", "AGENT_MAX_ROUNDS_RANGE",
    "AGENT_MAX_TOOL_CALLS_KEY", "AGENT_MAX_TOOL_CALLS_RANGE",
    "ConfiguredCaps", "configured_agent_caps",
]
