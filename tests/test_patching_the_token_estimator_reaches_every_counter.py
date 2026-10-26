# SPDX-License-Identifier: AGPL-3.0-or-later
"""A test that patches the token estimator patches every counter, or is told which it missed.

`B743`. Four production modules bind `src.model_context.estimate_tokens` by
name at import (`src/agent_loop.py`, `src/context_compactor.py`,
`routes/chat_routes.py`, `routes/chat_helpers.py`), and three more import it
inside a function at five sites (`routes/history/history_routes.py`,
`src/context_budget.py`, `services/memory/memory_extractor.py`). `tests/test_foreground_model_routing.py` patched
`chat_routes.estimate_tokens` and `routes/chat_helpers.shaping_stats` went on
measuring with the real estimator. `tests/helpers/patch_estimator.py` is the
one way to patch it; these cases drive the counters themselves.
"""
import importlib

import pytest

from tests.helpers.patch_estimator import import_time_binders, patch_estimator


def _fake(messages, *args, **kwargs):
    return len(messages) * 100


def test_one_patch_reaches_every_counter_on_the_chat_path(monkeypatch):
    import routes.chat_helpers as chat_helpers
    import routes.chat_routes as chat_routes
    import src.agent_loop as agent_loop
    import src.context_compactor as context_compactor

    patched = patch_estimator(monkeypatch, _fake)

    # The counter `P4-13` lost half an hour to, driven rather than inspected.
    stats = chat_helpers.shaping_stats([{"role": "user"}] * 10, [{"role": "user"}] * 6)
    assert (stats["tokens_before"], stats["tokens_after"]) == (1000, 600), stats
    for module in (chat_routes, agent_loop, context_compactor):
        assert module.estimate_tokens is _fake, module.__name__
    # A function-local `from src.model_context import estimate_tokens` reads
    # the module attribute at call time.
    assert importlib.import_module("src.model_context").estimate_tokens is _fake
    assert "src.model_context.estimate_tokens" in patched
    assert "routes.chat_helpers.estimate_tokens" in patched


def test_the_real_estimator_is_back_for_the_next_test():
    import routes.chat_helpers as chat_helpers
    from src import model_context

    real = model_context.estimate_tokens
    assert real is not _fake and real.__module__ == "src.model_context"
    assert chat_helpers.estimate_tokens is real


def test_the_binders_are_found_from_the_source_not_listed():
    """The four measured on `9cb99344` are a floor: a fifth is found the day
    someone writes it, which is the point of finding them."""
    found = {module for module, _ in import_time_binders()}
    assert {"src.agent_loop", "src.context_compactor",
            "routes.chat_routes", "routes.chat_helpers"} <= found, found


def test_a_stand_in_the_caller_set_is_left_as_the_caller_set_it(monkeypatch):
    """A test sets its own estimator on `agent_loop`, then calls a shared helper
    that patches the rest — the shape twelve cases of
    `test_an_agent_fallback_is_sent_its_own_length.py` met when this helper
    first failed on any binding that was not its own stand-in. Nothing is left
    on the real estimator, and the caller's choice stands."""
    import routes.chat_helpers as chat_helpers
    import src.agent_loop as agent_loop

    def mine(messages, *a, **k):
        return 7

    monkeypatch.setattr(agent_loop, "estimate_tokens", mine)
    patch_estimator(monkeypatch, _fake)
    assert agent_loop.estimate_tokens is mine
    assert chat_helpers.estimate_tokens is _fake


def test_a_counter_left_on_the_real_estimator_is_named(monkeypatch):
    """A binder the sweep cannot reach — here one outside the trees it walks —
    still holding the real function is a failure that says which module."""
    import sys
    import types

    import tests.helpers.patch_estimator as helper
    from src import model_context

    outside = types.ModuleType("b743_outside")
    outside.estimate_tokens = model_context.estimate_tokens
    monkeypatch.setitem(sys.modules, "b743_outside", outside)
    found = helper.import_time_binders()
    monkeypatch.setattr(helper, "import_time_binders",
                        lambda: found + (("b743_outside", "estimate_tokens"),))
    with pytest.raises(AssertionError, match=r"b743_outside\.estimate_tokens"):
        patch_estimator(monkeypatch, _fake)
