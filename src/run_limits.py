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

from contextvars import ContextVar
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
    # gate consults (`P7-12`) must not be the thing that ends a run, and for
    # `TypeError` / `ValueError` the answer is the one the route always gave.
    try:
        tool_calls = _read_tool_calls(get_setting(AGENT_MAX_TOOL_CALLS_KEY, 0))
    except Exception:
        tool_calls = 0
    try:
        rounds = _read_rounds(get_setting(AGENT_MAX_ROUNDS_KEY, default_rounds))
    except Exception:
        rounds = _read_rounds(None)
    return ConfiguredCaps(rounds, tool_calls)


def _read_rounds(raw) -> int:
    """A step cap as the chat route reads one: falsy or unparseable is
    `MAX_AGENT_ROUNDS`, and the result is clamped to `AGENT_MAX_ROUNDS_RANGE`."""
    default_rounds = _default_rounds()
    try:
        rounds = int(raw or default_rounds)
    except (TypeError, ValueError):
        rounds = default_rounds
    low, high = AGENT_MAX_ROUNDS_RANGE
    return max(low, min(rounds, high))


def _read_tool_calls(raw) -> int:
    """A tool-call cap as the chat route reads one: an integer, `0` for none."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


# ── The agent raising its own loop caps (`P7-12`) ──────────────────────────
#
# `D-2026-09-08-04`: *"the idea is to be able to allow full automation. Full
# automation only works if the LLM in agent mode can define its own parameters
# (with failsafes and safeguards.. a smarter 'loop detection' than PewDiePie put
# in)."* The caps stay writable by `manage_settings` (`_SELF_RESTRAINT_KEYS`
# does not grow), under three failsafes the decision names:
#
#   1. **A raise is scoped to the run that asked for it and never becomes the
#      stored default.** Measured before this row: `manage_settings set
#      agent_max_rounds 42` wrote 42 to `settings.json` — every later session
#      inherited the emergency, and the run that asked got nothing, because the
#      loop had already read its cap. Now the raise lands on the running loop
#      (`RunLimits`, below) and nothing is saved. A *lowering* is saved as it
#      always was (`Law 1`): standing yourself down is not the ratchet.
#   2. **A number the owner typed is not raised without them.** `setting_is_
#      explicit` — the pin `H08` honours — decides it, and a raise of a pinned
#      cap asks every time through `P7-02`'s one mechanism
#      (`self_escalation_for`), not a second one (`Law 14`).
#   3. **Loop detection lands with it.** `src/agent_loop.py`'s information
#      ledger stops a run that brings nothing new, so a cap raised to 200 is
#      not 200 rounds of a two-step cycle.
#
# The ceiling for a raise the agent grants itself is the range the settings
# route validates: a run can be given no more than a person could type.

#: The two keys, and the friendly names `manage_settings` accepts for them.
#: One map for the gate and the executor (`Law 7`): the executor's alias table
#: takes these, and the gate reads a call through `loop_cap_request`.
LOOP_CAP_KEYS = (AGENT_MAX_ROUNDS_KEY, AGENT_MAX_TOOL_CALLS_KEY)
LOOP_CAP_ALIASES = {
    "agent tool calls": AGENT_MAX_TOOL_CALLS_KEY,
    "max tool calls": AGENT_MAX_TOOL_CALLS_KEY,
    "tool call limit": AGENT_MAX_TOOL_CALLS_KEY,
    "max steps": AGENT_MAX_ROUNDS_KEY,
    "max rounds": AGENT_MAX_ROUNDS_KEY,
    "step limit": AGENT_MAX_ROUNDS_KEY,
    "steps per message": AGENT_MAX_ROUNDS_KEY,
    "max steps per message": AGENT_MAX_ROUNDS_KEY,
}

#: `RunLimits.round_limit_source` / `.tool_call_limit_source` for a cap the
#: agent raised for this run. The other sources are `P4-23`'s.
SOURCE_CONFIGURED = "configured"
SOURCE_RAISED_FOR_RUN = "raised_for_run"

#: Whose caps a run holds (`Law 10`: an enum). `settings`: the chat route's,
#: read from `agent_max_rounds` / `agent_max_tool_calls`, which is what a
#: `manage_settings` raise talks about. `caller`: a cap the caller chose — a
#: scheduled task's own Max steps, a skill test's 8, the teacher's 50 — which a
#: raise of the setting does not describe and does not move.
CAPS_FROM_SETTINGS = "settings"
CAPS_FROM_CALLER = "caller"

#: `raise_for_run` outcomes (`Law 10`).
RAISED = "raised"
ALREADY_ALLOWED = "already_allowed"
NOT_THIS_RUN = "not_this_run"
NO_RUN = "no_run"

_WHAT = {AGENT_MAX_ROUNDS_KEY: "step limit", AGENT_MAX_TOOL_CALLS_KEY: "tool-call limit"}


def cap_label(key: str) -> str:
    return _WHAT.get(key, key)


class LoopCapRequest(NamedTuple):
    """One `manage_settings` call that would set a loop cap. `requested` is
    the value as the chat route would read it (so a step cap is already within
    `AGENT_MAX_ROUNDS_RANGE`); `0` tool calls means none. `asked` is the number
    as written, so a reply can say it was cut down."""

    key: str
    requested: int
    asked: int


def _resolve_key(raw) -> str | None:
    """`manage_settings`' reading of a key, for these two keys only."""
    key = str(raw or "").strip().lower()
    if key in LOOP_CAP_KEYS:
        return key
    return LOOP_CAP_ALIASES.get(key)


def loop_cap_request(content) -> LoopCapRequest | None:
    """What a `manage_settings` call asks of a loop cap, or `None`.

    `set` with a value, or `reset` / `delete` (which write the shipped
    default). Read the way the executor reads it — `_parse_tool_args`, the
    same key aliases, the chat route's reading of the number — so the gate and
    the tool cannot disagree about what was asked. A value that will not parse
    is `None`: the executor refuses it, so there is nothing to raise.
    """
    try:
        from src.tool_utils import _parse_tool_args
        args = _parse_tool_args(content)
    except Exception:
        return None
    if not isinstance(args, dict):
        return None
    # Compared exactly, as `do_manage_settings` compares it.
    action = args.get("action", "list")
    key = _resolve_key(args.get("key"))
    if key is None:
        return None
    if action in ("reset", "delete"):
        try:
            from src.settings import DEFAULT_SETTINGS
            raw = DEFAULT_SETTINGS[key]
        except Exception:
            return None
    elif action == "set":
        raw = args.get("value")
        if isinstance(raw, bool):
            return None
        try:
            int(raw)
        except (TypeError, ValueError):
            return None
    else:
        return None
    requested = _read_rounds(raw) if key == AGENT_MAX_ROUNDS_KEY else _read_tool_calls(raw)
    return LoopCapRequest(key, requested, int(raw))


def raises(key: str, current: int, requested: int) -> bool:
    """Whether `requested` allows more than `current`. For tool calls, `0`
    (and below) is *no limit*, which is more than any number."""
    if key == AGENT_MAX_ROUNDS_KEY:
        return requested > current
    if current <= 0:
        return False
    return requested <= 0 or requested > current


def configured_cap(key: str) -> int:
    caps = configured_agent_caps()
    return caps.rounds if key == AGENT_MAX_ROUNDS_KEY else caps.tool_calls


def cap_is_owner_set(key: str) -> bool:
    """Whether a person typed this cap — `setting_is_explicit`, the pin `H08`
    honours. Unreadable counts as typed: the failure mode of this answer is a
    card that did not need to be asked, never a raise past a number someone
    meant."""
    try:
        from src.settings import setting_is_explicit
        return bool(setting_is_explicit(key))
    except Exception:
        return True


def owner_set_cap_raise(content) -> LoopCapRequest | None:
    """The request, when it would raise a cap the owner typed — the one raise
    that has to ask (`self_escalation_for`). `None` otherwise."""
    request = loop_cap_request(content)
    if request is None:
        return None
    if not raises(request.key, configured_cap(request.key), request.requested):
        return None
    return request if cap_is_owner_set(request.key) else None


def _number(n: int) -> str:
    return f"{n:,}"


def describe_cap(key: str, value: int) -> str:
    if key == AGENT_MAX_TOOL_CALLS_KEY and value <= 0:
        return "no tool-call limit"
    return f"{_number(value)} {'steps' if key == AGENT_MAX_ROUNDS_KEY else 'tool calls'}"


class RaiseOutcome(NamedTuple):
    outcome: str        # RAISED · ALREADY_ALLOWED · NOT_THIS_RUN · NO_RUN
    key: str
    limit: int | None   # the run's limit afterwards; None when there is no run
    words: str          # the tool's reply, which the model and the card read


class RunLimits:
    """The two caps one agent run is held to, as the running loop holds them.

    `stream_agent_loop` builds one per run and binds it (`bind_run_limits`)
    inside each tool task, so `manage_settings` can raise a cap for *this* run
    and for nothing else. The loop reads its caps back from here after every
    tool call and sends a fresh `agent_budget` frame when one moved — so the
    meter, the `for` and the budget check keep reading one number (`P4-23`).
    """

    def __init__(self, *, round_limit: int, round_limit_source: str,
                 round_limit_configured: int, tool_call_limit: int,
                 caps_source: str = CAPS_FROM_CALLER):
        self.round_limit = int(round_limit)
        self.round_limit_source = round_limit_source
        self.round_limit_configured = int(round_limit_configured)
        self.tool_call_limit = int(tool_call_limit or 0)
        self.tool_call_limit_source = SOURCE_CONFIGURED
        self.caps_source = caps_source
        self.changed = False
        self._raised_rounds: int | None = None
        self._raised_tool_calls: int | None = None

    def limit(self, key: str) -> int:
        return self.round_limit if key == AGENT_MAX_ROUNDS_KEY else self.tool_call_limit

    def raise_for_run(self, key: str, requested: int, asked: int | None = None) -> RaiseOutcome:
        """Raise `key` for this run to `requested`, clamped to what a person
        could type. Never saves anything; says what happened in words.
        `asked` is the number as written, when it differs from `requested`."""
        what = cap_label(key)
        current = self.limit(key)
        if self.caps_source != CAPS_FROM_SETTINGS:
            return RaiseOutcome(NOT_THIS_RUN, key, current, (
                f"This run's {what} ({describe_cap(key, current)}) was set by what "
                f"started it, not by Settings, so it was not raised. Nothing was saved."))
        low, high = AGENT_MAX_ROUNDS_RANGE if key == AGENT_MAX_ROUNDS_KEY else AGENT_MAX_TOOL_CALLS_RANGE
        granted = requested if (key == AGENT_MAX_TOOL_CALLS_KEY and requested <= 0) else min(requested, high)
        clamped = granted != requested or (asked is not None and asked > high and granted == high)
        if not raises(key, current, granted):
            lifted = (key == AGENT_MAX_ROUNDS_KEY and self.round_limit_source not in
                      (SOURCE_CONFIGURED, SOURCE_RAISED_FOR_RUN))
            why = " (the limit is lifted for a local model)" if (
                lifted and self.round_limit_source == "local_lift") else (
                " (this server lifts it)" if lifted else "")
            return RaiseOutcome(ALREADY_ALLOWED, key, current, (
                f"This run can already go to {describe_cap(key, current)}{why}, so "
                f"nothing was raised. Nothing was saved."))
        if key == AGENT_MAX_ROUNDS_KEY:
            self.round_limit = granted
            self.round_limit_source = SOURCE_RAISED_FOR_RUN
            self._raised_rounds = granted
        else:
            self.tool_call_limit = granted
            self.tool_call_limit_source = SOURCE_RAISED_FOR_RUN
            self._raised_tool_calls = granted
        self.changed = True
        saved = configured_cap(key)
        cap_note = (f" — the most a run can be given is {describe_cap(key, high)}"
                    if clamped else "")
        now = ("Removed this run's tool-call limit" if granted <= 0 and key == AGENT_MAX_TOOL_CALLS_KEY
               else f"Raised this run's {what} to {describe_cap(key, granted)}")
        return RaiseOutcome(RAISED, key, granted, (
            f"{now}{cap_note}. Nothing was saved: the next message is held to "
            f"{describe_cap(key, saved)} again. Only a person can change that, in "
            f"Settings › Agent Tools."))

    def settle(self, lifted_round_limit: int, lifted_source: str) -> int:
        """Adopt the loop's own lift for the step cap — the loop resolves it
        once, and a raise granted before that (an approved card replayed at the
        top of the run) stays on top of it. Returns the step cap in force."""
        if self._raised_rounds is not None and self._raised_rounds > lifted_round_limit:
            self.round_limit = self._raised_rounds
            self.round_limit_source = SOURCE_RAISED_FOR_RUN
        else:
            self.round_limit = int(lifted_round_limit)
            self.round_limit_source = lifted_source
            self._raised_rounds = None
        return self.round_limit


_CURRENT: ContextVar[RunLimits | None] = ContextVar("pantheon_run_limits", default=None)


def bind_run_limits(limits: RunLimits | None) -> None:
    """Make `limits` the run a tool call in this task belongs to. The loop
    calls it at the top of each tool task, whose context is a copy of its own,
    so the binding lives exactly as long as the tool call."""
    _CURRENT.set(limits)


def current_run_limits() -> RunLimits | None:
    return _CURRENT.get()


def raise_for_current_run(request: LoopCapRequest) -> RaiseOutcome:
    """What `manage_settings` does with a raise: the bound run's, or none."""
    limits = current_run_limits()
    if limits is None:
        return RaiseOutcome(NO_RUN, request.key, None, (
            f"A higher {cap_label(request.key)} applies only to the agent run that "
            f"asks for it, and there is no run here to raise, so nothing was changed "
            f"or saved."))
    return limits.raise_for_run(request.key, request.requested, request.asked)


__all__ = [
    "AGENT_MAX_ROUNDS_KEY", "AGENT_MAX_ROUNDS_RANGE",
    "AGENT_MAX_TOOL_CALLS_KEY", "AGENT_MAX_TOOL_CALLS_RANGE",
    "ALREADY_ALLOWED", "CAPS_FROM_CALLER", "CAPS_FROM_SETTINGS",
    "ConfiguredCaps", "LOOP_CAP_ALIASES", "LOOP_CAP_KEYS", "LoopCapRequest",
    "NOT_THIS_RUN", "NO_RUN", "RAISED", "RaiseOutcome", "RunLimits",
    "SOURCE_CONFIGURED", "SOURCE_RAISED_FOR_RUN",
    "bind_run_limits", "cap_is_owner_set", "cap_label", "configured_agent_caps",
    "configured_cap", "current_run_limits", "describe_cap", "loop_cap_request",
    "owner_set_cap_raise", "raise_for_current_run", "raises",
]
