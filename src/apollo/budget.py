# SPDX-License-Identifier: AGPL-3.0-or-later
"""A goal's budget (settled call 9).

Each person sets a goal's budget under an admin cap, and **the cap applies only
to API-billed models**. A local model runs uncapped. The unit is tokens, in and
out, because every endpoint reports tokens and not every one reports money.

  * `apollo_goal_token_cap` (admin setting) — the most a goal may spend on
    API-billed models. 0 means no cap.
  * `ApolloTask.budget_tokens` — the person's budget for one goal, never above
    the cap. NULL means "the cap".
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from src.apollo.errors import ApolloRefused

CAP_KEY = "apollo_goal_token_cap"
CAP_DEFAULT = 2_000_000
CAP_RANGE = (0, 1_000_000_000)


def admin_cap(settings: Optional[dict] = None) -> int:
    """The admin's cap in tokens; 0 is no cap."""
    if settings is None:
        try:
            from src.settings import get_setting
            raw = get_setting(CAP_KEY, CAP_DEFAULT)
        except Exception:
            raw = CAP_DEFAULT
    else:
        raw = settings.get(CAP_KEY, CAP_DEFAULT)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return CAP_DEFAULT
    return max(CAP_RANGE[0], min(CAP_RANGE[1], value))


def billed(endpoint_url: Optional[str]) -> bool:
    """Is this endpoint API-billed? A local server (`is_local_endpoint`) is not.
    No endpoint at all is not billed either: nothing runs on it."""
    url = str(endpoint_url or "").strip()
    if not url:
        return False
    try:
        from src.model_context import is_local_endpoint
        return not is_local_endpoint(url)
    except Exception:
        return True      # unknown is treated as paid: the cautious side


def check_person_budget(value: Any, *, cap: Optional[int] = None) -> Optional[int]:
    """A person's budget for one goal, checked: `None` (use the cap) or a whole
    number of tokens no higher than the admin's cap."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ApolloRefused("A budget is a number of tokens.")
    try:
        tokens = int(value)
    except (TypeError, ValueError):
        raise ApolloRefused("A budget is a number of tokens.")
    if tokens < 0:
        raise ApolloRefused("A budget can't be below zero.")
    cap = admin_cap() if cap is None else cap
    if cap and tokens > cap:
        raise ApolloRefused(f"That's over the admin's cap of {cap:,} tokens a goal on paid models.")
    return tokens


def limit_for(task, *, cap: Optional[int] = None) -> Optional[int]:
    """The tokens this goal may spend on API-billed models, or `None` for no limit."""
    cap = admin_cap() if cap is None else cap
    own = getattr(task, "budget_tokens", None)
    if own is None:
        return cap or None
    return min(own, cap) if cap else own


def may_spend(task, endpoint_url: Optional[str], *, cap: Optional[int] = None) -> Tuple[bool, str]:
    """`(True, "")`, or `(False, sentence)` when the goal's budget on a paid
    model is used up. A local model always may."""
    if not billed(endpoint_url):
        return True, ""
    limit = limit_for(task, cap=cap)
    spent = int(getattr(task, "spent_tokens", 0) or 0)
    if limit is not None and spent >= limit:
        return False, (f"“{task.title}” has used its {limit:,} tokens on paid models. "
                       f"Raise its budget or move it to a local model to go on.")
    return True, ""


def charge(task, tokens: Any, endpoint_url: Optional[str]) -> int:
    """Count `tokens` against the goal when the endpoint is API-billed. Returns
    what was charged (0 for a local model)."""
    try:
        n = max(0, int(tokens or 0))
    except (TypeError, ValueError):
        n = 0
    if not n or not billed(endpoint_url):
        return 0
    task.spent_tokens = int(task.spent_tokens or 0) + n
    return n
