# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P12`'s four layers, under the vocabulary the limit call sites use.

**There is one implementation of the chain and it is `src/settings.py`.** This
module is the adapter, not a second resolver.

Both existed for about an hour on 2026-09-18: two agents working the `P12` rows
in parallel each built the resolution order the phase specifies — role profile →
instance setting → environment → built-in default — one as
`settings.resolve_limit` and one as `limit_policy.resolve_int_limit`. That is
`Law 14` produced by the orchestration rather than by either author, and it is
filed as `B570`. `settings.resolve_limit` won the merge on three grounds: it
lives in the module that already owns settings, it had already absorbed
`task_scheduler.resolve_task_concurrency_cap`'s hand-written copy of the same
chain, and its source vocabulary is the one `P6-08` has been returning since it
shipped.

What survives here is the part that was better: a **verdict object** rather than
a tuple, so a caller can ask whether the number it got was clamped without
unpacking three values it does not want, and short source names for call sites
that log them.

`Law 1` — nothing was deleted. `resolve_int_limit` is the same signature it
shipped with, and the role-provider registry moved into `src/settings.py` so
that *both* names reach one registry. Re-exported here so the call sites and
tests that import it from this module keep working.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from src.settings import (  # noqa: F401 — re-exported on purpose, see above
    RoleLimitProvider,
    clear_role_limit_provider,
    role_limit,
    role_limit_provider,
    set_role_limit_provider,
)

logger = logging.getLogger(__name__)

# The four layers, in the order they are consulted. `Law 10`: a verdict that
# says which of several unlike things happened beats one that says a number.
#
# `settings.resolve_limit` spells the same four "role profile", "instance
# setting", the environment variable's own name, and "built-in default". The
# map between them is `_SHORT_SOURCE` below and it is one-way on purpose: a
# caller that has to translate between two vocabularies will eventually
# translate one of them wrong, so only this file ever does it.
LIMIT_SOURCES = ("role", "setting", "env", "default")


@dataclass(frozen=True)
class ResolvedLimit:
    """A limit, and the layer that decided it."""

    value: int
    source: str
    clamped: bool = False

    def __int__(self) -> int:  # pragma: no cover - convenience only
        return self.value


def _coerce_int(value: Any) -> Optional[int]:
    """An integer a person could have meant, or `None`.

    `bool` is rejected explicitly. It is an `int` subclass, so `True` would
    otherwise resolve a limit to `1` — which is `Law 10`'s polarity incident in
    a different costume: a value whose type can be read two ways, read both.

    `settings._coerce_limit` makes the same judgement for the same reason and is
    what actually runs; this one is kept because it is the readable statement of
    the rule and three tests drive it directly.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if float(value).is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text, 10)
        except ValueError:
            return None
    return None


def _short_source(source: str, env_name: Optional[str]) -> str:
    if source == "role profile":
        return "role"
    if source == "instance setting":
        return "setting"
    if env_name and source == env_name:
        return "env"
    return "default"


def resolve_int_limit(
    key: str,
    *,
    default: int,
    env_name: Optional[str] = None,
    owner: Any = None,
    minimum: int = 1,
    maximum: Optional[int] = None,
) -> ResolvedLimit:
    """Resolve one integer limit through all four layers.

    `key` is the `DEFAULT_SETTINGS` key **and** the role-profile key, on
    purpose: one name for one limit (`Law 7`). `env_name` may be `None` for a
    limit that deliberately has no environment variable — a settings-only knob,
    which `events_retention_days` already is and says why.
    """
    default_value = _coerce_int(default)
    if default_value is None:
        raise ValueError(f"{key}: built-in default must be an integer")

    from src.settings import resolve_limit_detail

    value, source, clamped = resolve_limit_detail(
        key, default_value, env_name=env_name, owner=owner,
        minimum=minimum, maximum=maximum, label=key,
    )
    return ResolvedLimit(value=value, source=_short_source(source, env_name),
                         clamped=clamped)
