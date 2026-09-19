# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P2-09` / `B750` — `skill_max_injected` joins the other six budgets.

`P12-04` brought six of seven context budgets under one policy and said plainly
why it could not bring the seventh: its only consumer is `src/agent_loop.py`,
which that row did not own, and a key with no consumer is `Law 13`'s unwired
half. It is wired here, in the same change as its consumer.

**What was actually wrong**, measured 2026-09-19 at `src/agent_loop.py:3144`:

    _skill_max_injected = int(_prefs.get(
        "skill_max_injected", get_setting("skill_max_injected", 3)))
    _skill_max_injected = max(0, min(12, _skill_max_injected))

A per-user preference beat **every** other layer, so a role profile could never
lower it; and the ceiling of 12 was written here *and* as `max="12"` in the
markup, so raising the instance setting alone did nothing above 12.

**One of `B750`'s three defects is corrected rather than implemented.** It calls
`> 0` an off switch the other budgets deliberately do not have, and asks for
`minimum=1`. The input ships `min="0"` with the caption *"Set to 0 to disable
skill injection"* directly under it, so `minimum=1` would silently turn a
stored 0 into 1 for everybody who used that documented control — `Law 1`. Zero
survives as the **user's** sentinel; the policy layers keep a floor of 1, so
`role_limit_ranges`' *"the floor is 1 on every key"* stays true.

**This is not P2-09's auto-scale.** That is the half that was implemented once
and reverted, and it still needs the explicit affordance `D-2026-08-26-06`
asks for — a checkbox in `static/index.html`, which this wave does not own.
"""
import pytest

import src.settings as settings
from src.context_budget import (
    MAX_SKILL_INJECTION,
    MIN_SKILL_INJECTION,
    SKILL_INJECTION_DEFAULT,
    SKILL_INJECTION_LIMIT,
    resolve_skill_injection,
    resolve_skill_injection_detail,
)


@pytest.fixture(autouse=True)
def _no_stored_settings(monkeypatch):
    """Every layer answers from the arguments, not from this machine's disk."""
    monkeypatch.setattr(settings, "setting_is_explicit", lambda key: False)
    settings.clear_role_limit_provider()
    yield
    settings.clear_role_limit_provider()


def _role(mapping):
    settings.set_role_limit_provider(
        lambda key, owner: (mapping.get(owner) or {}).get(key))


# ── The resolver ───────────────────────────────────────────────────────────

def test_with_nothing_configured_it_is_the_shipped_default():
    detail = resolve_skill_injection_detail(None)
    assert detail.value == SKILL_INJECTION_DEFAULT == 3
    assert detail.source == "default"


def test_a_role_lowers_it_for_one_person_and_not_another():
    """`B750`'s own `Verify:` line, which the old code could not satisfy at all
    because the role layer was never consulted."""
    _role({"alice": {SKILL_INJECTION_LIMIT: 1}})
    assert resolve_skill_injection("alice") == 1
    assert resolve_skill_injection("bob") == SKILL_INJECTION_DEFAULT
    assert resolve_skill_injection_detail("alice").source == "role"


def test_a_role_beats_a_preference_that_asks_for_more():
    """The defect, stated as its own case: the preference used to win."""
    _role({"alice": {SKILL_INJECTION_LIMIT: 1}})
    detail = resolve_skill_injection_detail("alice", preference=12)
    assert detail.value == 1
    assert detail.source == "role"
    assert detail.clamped is True


def test_a_preference_below_the_role_is_still_the_persons_own_choice():
    _role({"alice": {SKILL_INJECTION_LIMIT: 8}})
    detail = resolve_skill_injection_detail("alice", preference=2)
    assert detail.value == 2
    assert detail.source == "user preference"
    assert detail.clamped is False


def test_the_built_in_default_is_not_a_ceiling_on_the_persons_own_choice():
    """`Law 1`. Nobody chose 3 — it is what the product shipped. A person who
    typed 12 into the `max="12"` input got 12 before this change and gets 12
    after it; resolving their preference against an unset default would have
    quietly taken nine skills away from them."""
    detail = resolve_skill_injection_detail(None, preference=12)
    assert detail.value == 12
    assert detail.source == "user preference"
    assert detail.clamped is False


def test_an_instance_setting_is_an_administrators_number_and_does_cap_it(monkeypatch):
    monkeypatch.setattr(settings, "setting_is_explicit",
                        lambda key: key == SKILL_INJECTION_LIMIT)
    monkeypatch.setattr(settings, "load_settings",
                        lambda: {SKILL_INJECTION_LIMIT: 2})
    assert resolve_skill_injection(None) == 2
    detail = resolve_skill_injection_detail(None, preference=12)
    assert detail.value == 2
    assert detail.source == "setting"
    assert detail.clamped is True


def test_zero_is_still_the_documented_off_switch():
    """The caption under the input says *"Set to 0 to disable skill
    injection"*, so 0 has to keep meaning that."""
    assert resolve_skill_injection(None, preference=0) == 0
    _role({"alice": {SKILL_INJECTION_LIMIT: 8}})
    assert resolve_skill_injection("alice", preference=0) == 0


def test_the_policy_layers_keep_a_floor_of_one():
    """A role cannot switch somebody's skills off through a limit — that is
    what `skills_enabled` is for, and `role_limit_ranges` promises a floor of 1
    on every key it carries."""
    assert MIN_SKILL_INJECTION == 1
    _role({"alice": {SKILL_INJECTION_LIMIT: 0}})
    assert resolve_skill_injection("alice") == 1
    assert settings.role_limit_ranges()[SKILL_INJECTION_LIMIT] == (
        MIN_SKILL_INJECTION, MAX_SKILL_INJECTION)


def test_the_ceiling_is_one_number_and_it_still_holds():
    assert MAX_SKILL_INJECTION == 12
    assert resolve_skill_injection(None, preference=999) == MAX_SKILL_INJECTION
    _role({"alice": {SKILL_INJECTION_LIMIT: 999}})
    assert resolve_skill_injection("alice") == MAX_SKILL_INJECTION


def test_an_unparseable_preference_falls_through_to_the_policy():
    assert resolve_skill_injection(None, preference="not a number") == 3
    assert resolve_skill_injection(None, preference=None) == 3


# ── The consumer ───────────────────────────────────────────────────────────

def test_the_prompt_builder_asks_the_resolver_and_honours_a_role(monkeypatch):
    """`Law 20` — the real path. `_build_system_prompt` is driven with a stub
    skills manager, so what is asserted is how many skills the product chose to
    show the model, not what a constant says."""
    import src.agent_loop as al
    import services.memory.skills as skills_mod

    seen = {}

    class _StubSkills:
        def __init__(self, *a, **k):
            pass

        def load(self, owner=None):
            return []

        def get_relevant_skills(self, text, skills=None, threshold=None,
                                max_items=None, min_confidence=None):
            seen["max_items"] = max_items
            return []

    monkeypatch.setattr(skills_mod, "SkillsManager", _StubSkills)
    # Alice has set a preference of 12; Bob has set nothing. Both matter.
    monkeypatch.setattr(
        "routes.prefs_routes._load_for_user",
        lambda owner: ({"skills_enabled": True, "skill_max_injected": 12}
                       if owner == "alice" else {"skills_enabled": True}),
        raising=False)
    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default,
                        raising=False)

    messages = [{"role": "user", "content": "how do I deploy this"}]

    # Nobody has set anything: the person's own 12 is honoured, as before.
    al._build_system_prompt(messages, "local-model", None, None, owner="alice")
    assert seen["max_items"] == 12

    # Their administrator puts them in a role capped at 1.
    _role({"alice": {SKILL_INJECTION_LIMIT: 1}})
    al._build_system_prompt(messages, "local-model", None, None, owner="alice")
    assert seen["max_items"] == 1

    # And it is per person, with no restart between the calls: Bob is in no
    # role and has set no preference, so he gets the shipped default.
    al._build_system_prompt(messages, "local-model", None, None, owner="bob")
    assert seen["max_items"] == SKILL_INJECTION_DEFAULT


def test_a_preference_of_zero_injects_nothing_through_the_real_path(monkeypatch):
    import src.agent_loop as al
    import services.memory.skills as skills_mod

    called = []

    class _StubSkills:
        def __init__(self, *a, **k):
            pass

        def load(self, owner=None):
            return []

        def get_relevant_skills(self, *a, **k):
            called.append(k.get("max_items"))
            return []

    monkeypatch.setattr(skills_mod, "SkillsManager", _StubSkills)
    monkeypatch.setattr("routes.prefs_routes._load_for_user",
                        lambda owner: {"skills_enabled": True,
                                       "skill_max_injected": 0},
                        raising=False)
    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default,
                        raising=False)
    al._build_system_prompt([{"role": "user", "content": "hi"}],
                            "local-model", None, None, owner="alice")
    assert called == []
