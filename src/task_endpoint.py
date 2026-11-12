# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared resolver for background-task AI endpoints."""

import contextvars
from contextlib import contextmanager

from src.endpoint_resolver import (
    resolve_endpoint,
    resolve_utility_fallback_candidates,
)
from src.llm_core import llm_call_async_with_fallback
from src.interactive_gate import wait_for_interactive_quiet


def resolve_task_endpoint(fallback_url=None, fallback_model=None, fallback_headers=None, owner=None):
    """Return (endpoint_url, model, headers) for background tasks.

    Reads task_endpoint_id / task_model from admin settings.
    Falls back to the provided values when the setting is empty or the
    endpoint cannot be resolved.
    """
    return resolve_endpoint("task", fallback_url, fallback_model, fallback_headers, owner=owner)


#: `B2100`. The model a built-in task picked, for the length of its run. The
#: task form offers Model for every task and the list shows it, but the ten
#: model-backed actions resolved their model here, with no per-task choice, so
#: the Background Tasks model always won. `TaskScheduler._execute_action` sets
#: this (after `_usable_route` has checked the pick is still listed) and every
#: action's call reaches it through `resolve_task_candidates`, the one resolver
#: they already share. A contextvar rather than a parameter: ten actions and a
#: dozen call sites inherit it without a signature changing.
_TASK_MODEL_PIN = contextvars.ContextVar("pantheon_task_model_pin", default=None)


@contextmanager
def task_model_pinned(url, model, headers=None):
    """Run the body with `(url, model)` as the only background-task candidate."""
    token = _TASK_MODEL_PIN.set((url, model, dict(headers or {})))
    try:
        yield
    finally:
        _TASK_MODEL_PIN.reset(token)


def resolve_task_candidates(
    fallback_url=None,
    fallback_model=None,
    fallback_headers=None,
    owner=None,
):
    """Return ordered background-task LLM candidates.

    Order:
    1. configured Background Tasks endpoint/model, or caller fallback
    2. Utility endpoint/model
    3. Default endpoint/model
    4. Utility fallback chain

    Inside `task_model_pinned` (`B2100`) the pinned model is the only
    candidate: a task that picked a model runs on it or not at all, never on
    the default (`D-2026-10-07-02` §1).
    """
    pinned = _TASK_MODEL_PIN.get()
    if pinned is not None:
        return [pinned]
    candidates = []

    def _append(url, model, headers):
        if not url or not model:
            return
        key = (url, model)
        if any((u, m) == key for u, m, _ in candidates):
            return
        candidates.append((url, model, headers or {}))

    _append(*resolve_task_endpoint(fallback_url, fallback_model, fallback_headers, owner=owner))
    _append(*resolve_endpoint("utility", owner=owner))
    _append(*resolve_endpoint("default", owner=owner))
    for url, model, headers in resolve_utility_fallback_candidates(owner=owner):
        _append(url, model, headers)
    return candidates


async def task_llm_call_async(
    messages,
    *,
    fallback_url=None,
    fallback_model=None,
    fallback_headers=None,
    owner=None,
    **kwargs,
):
    """Call the shared background-task LLM candidate chain."""
    candidates = resolve_task_candidates(
        fallback_url=fallback_url,
        fallback_model=fallback_model,
        fallback_headers=fallback_headers,
        owner=owner,
    )
    if not candidates:
        raise RuntimeError("No LLM endpoint available for background task")
    await wait_for_interactive_quiet("background task LLM")
    kwargs.setdefault("workload", "background")
    return await llm_call_async_with_fallback(candidates, messages=messages, **kwargs)
