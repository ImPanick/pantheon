# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1030` — `set agent_max_rounds 0` meant two numbers depending on the cap.

`P7-12`'s gate read a requested step cap the way the chat route reads a STORED
value, where a falsy 0 is the loop's default (`MAX_AGENT_ROUNDS`, 50), while
both writers store a 0 as 1 (`B931`'s clamp). Measured on the tree before this
row, with a run bound and the cap saved:

    saved cap 20    a raise to 50 for the run, nothing saved
    saved cap 100   a lowering, saved as 1, "…clamped to 1"

One request, two numbers (`Law 7`). Now the gate reads the request through the
writer's clamp, so 0 is a lowering to 1 under any cap: the same stored value,
the same reply, no raise and no card. Driven through the real
`manage_settings` and the real gate (`Law 20`).
"""
from __future__ import annotations

import pytest

import src.agent_tools  # noqa: F401
from src.tool_capabilities import self_escalation_for
from test_the_agent_raises_its_own_limits_for_the_run import (  # noqa: E402,F401
    _manage, _run_limits, _set, stored,
)


@pytest.mark.parametrize("saved", [20, 100, None], ids=["cap-20", "cap-100", "unset"])
def test_a_step_limit_of_zero_does_the_same_thing_under_any_saved_cap(stored, saved):
    settings = stored({} if saved is None else {"agent_max_rounds": saved})
    cap = 20 if saved is None else saved
    limits = _run_limits(round_limit=cap, configured=cap)
    content = _set("agent_max_rounds", 0)

    # The gate: a lowering never needs a card, whoever typed the cap.
    assert self_escalation_for("manage_settings", content) is None

    result = _manage(content, limits)

    assert "run_limit" not in result, result          # not a raise for the run
    assert settings.load_settings()["agent_max_rounds"] == 1
    assert result["response"] == (
        "Set agent_max_rounds = 1. 0 is outside the range Settings allows "
        "(1 to 200), so it was clamped to 1, as Settings does.")
    assert (limits.round_limit, limits.changed) == (cap, False)


def test_the_gate_and_the_writer_read_zero_as_the_same_number():
    from src.run_limits import loop_cap_request
    from src.settings import clamp_int_setting

    request = loop_cap_request(_set("agent_max_rounds", 0))
    assert request.requested == clamp_int_setting("agent_max_rounds", 0) == 1
