# SPDX-License-Identifier: AGPL-3.0-or-later
"""H08 — on the primary deployment, a cap the operator typed was overwritten.

`stream_agent_loop` lifts the agent's round limit to 100,000, generation length
to 1,000,000 and the per-round stream timeout to 24 hours whenever inference is
local — which is the default, for any localhost/LAN `/v1` endpoint. That lift is
deliberate and worth keeping: on your own GPU a 20-round ceiling costs you long
autonomous runs and saves you nothing.

What was wrong is that it did not distinguish a shipped default from a number a
person entered. `agent_max_rounds` is offered in the settings UI, validated to
1..200 by the admin endpoint, and re-clamped in `chat_routes.py` *with a comment
about defending against hand-edits* — and then replaced here. All three guards
were theatre, and an operator who set 5 rounds because their machine thrashes
got 100,000.

The tests are about the rule (`runtime_limits.lift_cap`) and the composition of
the rule with the real settings read, because that pair is the fix. Booting the
whole async generator to observe an integer would test the stream plumbing.
"""
import ast
import importlib
import pathlib

import pytest

from src.runtime_limits import lift_cap

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── the rule ──

def test_an_unpinned_default_is_lifted():
    assert lift_cap(20, 100_000, unlimited=True, pinned=False) == 100_000


def test_a_pinned_value_is_left_exactly_alone():
    """The defect, in one line."""
    assert lift_cap(5, 100_000, unlimited=True, pinned=True) == 5


def test_nothing_is_lifted_on_a_cloud_endpoint():
    """A metered API keeps its caps whether or not the operator pinned one."""
    assert lift_cap(20, 100_000, unlimited=False, pinned=False) == 20
    assert lift_cap(20, 100_000, unlimited=False, pinned=True) == 20


def test_a_falsy_cap_already_means_no_cap_and_is_not_given_one():
    """0 is "unlimited" in this codebase's settings vocabulary
    (`agent_max_tool_calls`, and `max_tokens=0` at `chat_routes.py:2930`).
    Raising it to a large finite number would be a cap where there was none."""
    assert lift_cap(0, 100_000, unlimited=True, pinned=False) == 0


def test_the_lift_never_lowers_a_value():
    """`max()`, not assignment. The original wrote `if value < lifted` on two
    of three sites and `max(...)` on the third; a caller cannot reason about a
    "lift" that sometimes reduces."""
    assert lift_cap(500_000, 100_000, unlimited=True, pinned=False) == 500_000


# ── the rule composed with the real settings read ──

@pytest.fixture
def datadir(tmp_path, monkeypatch):
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    import src.constants, src.settings
    importlib.reload(src.constants)
    importlib.reload(src.settings)
    yield tmp_path
    monkeypatch.delenv("PANTHEON_DATA_DIR", raising=False)
    importlib.reload(src.constants)
    importlib.reload(src.settings)


def _pinned(key):
    import src.agent_loop
    return src.agent_loop._setting_pinned(key)


def test_an_untouched_install_does_not_pin_the_round_cap(datadir):
    assert _pinned("agent_max_rounds") is False
    assert lift_cap(20, 100_000, unlimited=True,
                    pinned=_pinned("agent_max_rounds")) == 100_000


def test_a_materialised_default_does_not_pin_it_either(datadir):
    """One admin save writes all ~200 defaults to disk. If that counted as
    pinning, opening Settings once would quietly disable the lift for everyone
    — the mirror image of the bug being fixed, and just as invisible."""
    import src.settings as S
    S.save_settings(dict(S.DEFAULT_SETTINGS))
    S._invalidate_caches()
    assert _pinned("agent_max_rounds") is False


def test_a_value_the_operator_entered_pins_it(datadir):
    import src.settings as S
    S.save_settings(dict(S.DEFAULT_SETTINGS, agent_max_rounds=5))
    S._invalidate_caches()
    assert _pinned("agent_max_rounds") is True
    assert lift_cap(5, 100_000, unlimited=True,
                    pinned=_pinned("agent_max_rounds")) == 5


def test_the_stream_timeout_is_pinnable_the_same_way(datadir):
    import src.settings as S
    S.save_settings(dict(S.DEFAULT_SETTINGS, agent_stream_timeout_seconds=45))
    S._invalidate_caches()
    assert _pinned("agent_stream_timeout_seconds") is True
    assert lift_cap(45, 86_400, unlimited=True,
                    pinned=_pinned("agent_stream_timeout_seconds")) == 45


def test_pinning_rounds_does_not_also_pin_the_token_lift(datadir):
    """The de-nesting. `max_tokens` was lifted inside the `max_rounds` branch,
    so gating rounds on the pin would have silently gated tokens too."""
    import src.settings as S
    S.save_settings(dict(S.DEFAULT_SETTINGS, agent_max_rounds=5))
    S._invalidate_caches()
    assert lift_cap(4096, 1_000_000, unlimited=True, pinned=False) == 1_000_000


def test_an_unreadable_settings_module_falls_back_to_lifting(monkeypatch):
    """Fail toward the shipped behaviour: an import failure must not change
    what a chat does."""
    import src.agent_loop as A
    import builtins
    real = builtins.__import__

    def boom(name, *a, **k):
        if name == "src.settings":
            raise ImportError("simulated")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert A._setting_pinned("agent_max_rounds") is False


# ── the wiring, which is the part that was actually broken ──
#
# The rule and the settings read were each testable on their own before this
# fix and each would have passed; what did not exist was anything asserting
# that the loop CONSULTS the pin. Two mutations proved it: replacing
# `_setting_pinned(...)` with a bare `False` at both call sites survived every
# test above. That is this project's recurring vacuous-test family — testing
# the ingredient rather than the recipe — so the wiring is a function now and
# these tests call it.

def test_the_resolver_lifts_an_untouched_install(datadir):
    import src.agent_loop as A
    rounds, tokens, timeout_pinned = A._resolve_local_lifts(20, 4096, unlimited=True)
    assert (rounds, tokens, timeout_pinned) == (100_000, 1_000_000, False)


def test_the_resolver_honours_a_pinned_round_cap(datadir):
    """The headline defect, along the path a real request takes.

    The resolver does not read the cap — `chat_routes` does, clamps it to
    1..200 and passes it in — so the value flowing in IS the operator's, and
    the resolver's whole job is to not overwrite it. Modelled here rather than
    asserted as a constant, because the first version of this test passed 20
    and expected 5, which is a contract nobody has."""
    import src.settings as S, src.agent_loop as A
    from src.agent_tools import MAX_AGENT_ROUNDS as DEFAULT
    S.save_settings(dict(S.DEFAULT_SETTINGS, agent_max_rounds=5))
    S._invalidate_caches()

    # exactly what routes/chat_routes.py does before calling the loop
    incoming = max(1, min(int(S.get_setting("agent_max_rounds", DEFAULT) or DEFAULT), 200))
    assert incoming == 5

    rounds, tokens, _ = A._resolve_local_lifts(incoming, 4096, unlimited=True)
    assert rounds == 5, "the operator's 5 must survive the lift"
    assert tokens == 1_000_000, "and must not drag the token lift down with it"


def test_an_unpinned_install_still_gets_the_lift_along_that_same_path(datadir):
    """The other half of the contract: with nothing configured, `chat_routes`
    passes the shipped 20 and the loop must still lift it — the fix must not
    quietly cost local deployments the thing the fork exists to give them."""
    import src.settings as S, src.agent_loop as A
    from src.agent_tools import MAX_AGENT_ROUNDS as DEFAULT
    incoming = max(1, min(int(S.get_setting("agent_max_rounds", DEFAULT) or DEFAULT), 200))
    assert A._resolve_local_lifts(incoming, 4096, unlimited=True)[0] == 100_000


def test_the_resolver_reports_a_pinned_timeout(datadir):
    import src.settings as S, src.agent_loop as A
    S.save_settings(dict(S.DEFAULT_SETTINGS, agent_stream_timeout_seconds=45))
    S._invalidate_caches()
    assert A._resolve_local_lifts(20, 4096, unlimited=True)[2] is True


def test_the_resolver_lifts_nothing_on_a_cloud_endpoint(datadir):
    import src.agent_loop as A
    assert A._resolve_local_lifts(20, 4096, unlimited=False)[:2] == (20, 4096)


def test_the_loop_uses_the_resolver_for_both_caps_and_the_timeout(datadir):
    """One line of `stream_agent_loop` is not reachable from a unit test — the
    call site itself. This pins it: the resolver's three outputs must all be
    bound there, or a later edit could keep the function and stop using it.

    Its limits, stated because this test already gave false confidence once: it
    matches SOURCE TEXT, so it passes on a call to a name that does not exist.
    That is exactly what happened — `pinned=_timeout_pinned` was present and
    `_lift_cap` was not in scope, a NameError on every request that this test
    was green for. `tests/test_agent_loop_names_resolve.py` is the check that
    catches that, and it is a general one rather than a rule about this line."""
    import inspect
    import src.agent_loop as A
    src = inspect.getsource(A.stream_agent_loop)
    assert "max_rounds, max_tokens, _timeout_pinned = _resolve_local_lifts(" in src
    assert "pinned=_timeout_pinned" in src


# ── the off-switch a person can find ──

def test_both_runtime_limit_env_vars_are_in_env_example():
    """Half of this row is that the only off-switch appeared NOWHERE outside
    the module that reads it — not `.env.example`, not compose, not the setup
    docs. An undiscoverable switch is not a switch."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "PANTHEON_UNLIMITED_LOCAL" in text
    assert "PANTHEON_FORCE_UNLIMITED" in text


def test_env_example_says_a_configured_limit_is_still_honoured():
    """The documentation has to describe the behaviour after the fix, or an
    operator reads "caps are lifted on local" and turns the whole thing off to
    get a cap they could simply have typed."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    section = text.split("Guardrail caps on local inference", 1)[1][:1400]
    assert "does NOT override a limit you set yourself" in section


def test_runtime_limits_still_imports_nothing_from_the_project():
    """Its docstring promises this so `src.tool_utils` — which forbids project
    imports to avoid cycles — can import it lazily. `lift_cap` takes `pinned`
    as an argument rather than reading settings for exactly this reason."""
    tree = ast.parse((ROOT / "src" / "runtime_limits.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        mod = None
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
        elif isinstance(node, ast.Import):
            mod = node.names[0].name
        if mod and (mod.startswith(("src.", "routes.", "core.", "services."))):
            raise AssertionError(f"project import in runtime_limits.py: {mod}")
