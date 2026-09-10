# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B68`. `manage_settings set` refuses every structured setting and used to
offer `reset` as the alternative, because `reset` writes `DEFAULT_SETTINGS[key]`
and restoring a default is safe.

That holds for exactly one of the nine structured settings. The other eight ship
**empty** — `networks`, `search_fallback_chain`, `tool_path_extra_roots`,
`eval_suites`, the two OTLP maps and the two model-fallback lists — and for those
"restore the default" is not restoring anything. It is deleting what the operator
wrote, in one call, in response to a sentence in a chat.

**This is durability, not escalation, and the distinction is load-bearing.**
`src/networks.py` fails *closed*: a run scoped to a network name that no longer
exists refuses every host, including the operator's own subnets. So an agent that
empties `networks` narrows its own reach rather than widening it. Recording the
wrong reason here is how the protection gets removed later by someone who checks
the security claim, finds it false, and deletes the guard with it.
"""
import asyncio
import json
import os
import tempfile

import pytest

from src.settings import DEFAULT_SETTINGS, RETIRED_SETTING_KEYS


def _structured():
    return {k: v for k, v in DEFAULT_SETTINGS.items()
            if isinstance(v, (dict, list)) and k not in RETIRED_SETTING_KEYS}


@pytest.fixture
def settings_file(monkeypatch):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "settings.json")
    import src.settings as S
    monkeypatch.setattr(S, "SETTINGS_FILE", path, raising=False)
    import src.constants as C
    monkeypatch.setattr(C, "SETTINGS_FILE", path, raising=False)

    def fresh():
        S._cache = None
        S._cache_time = 0

    fresh()
    yield S, fresh
    fresh()


def _call(payload, owner="alice"):
    from src.agent_tools.admin_tools import do_manage_settings
    return asyncio.run(do_manage_settings(json.dumps(payload), owner=owner))


def test_the_population_this_row_is_about_is_still_mostly_empty():
    """If a future default fills these in, the rule below stops applying to them
    and this test says so rather than passing quietly."""
    structured = _structured()
    assert len(structured) >= 8, "the structured settings have shrunk; re-derive this row"
    empty = {k for k, v in structured.items() if not v}
    assert "networks" in empty
    assert len(empty) >= 7, (
        f"only {len(empty)} structured settings ship empty now — the reasoning "
        "in the fix names eight")


@pytest.mark.parametrize("action", ["reset", "delete"])
def test_the_agent_cannot_delete_a_declared_network(settings_file, action):
    S, fresh = settings_file
    declared = [{"name": "lab", "cidrs": ["10.9.0.0/16"], "trust": "limited"}]
    cfg = S.load_settings()
    cfg["networks"] = declared
    S.save_settings(cfg)
    fresh()

    out = _call({"action": action, "key": "networks"})
    fresh()
    assert out["exit_code"] == 0, "the refusal is an answer, not an error"
    assert S.get_setting("networks", []) == declared, (
        f"manage_settings {action} deleted the operator's declared networks")


def test_the_refusal_says_why_rather_than_just_no(settings_file):
    out = _call({"action": "reset", "key": "networks"})
    said = out["response"].lower()
    assert "empty" in said and "settings" in said, (
        "a refusal that does not say where to go is a refusal the person works "
        f"around: {out['response']!r}")


def test_a_structured_setting_with_a_real_default_still_resets(settings_file):
    """The negative half. `keybinds` ships with content, so restoring it really
    is restoring — refusing that would be over-broad."""
    S, fresh = settings_file
    cfg = S.load_settings()
    cfg["keybinds"] = {"search": "ctrl+shift+p"}
    S.save_settings(cfg)
    fresh()

    out = _call({"action": "reset", "key": "keybinds"})
    fresh()
    assert out["exit_code"] == 0
    assert S.get_setting("keybinds", {}) == DEFAULT_SETTINGS["keybinds"]


def test_a_scalar_setting_still_resets(settings_file):
    S, fresh = settings_file
    key = next(k for k, v in DEFAULT_SETTINGS.items()
               if isinstance(v, bool) and k not in RETIRED_SETTING_KEYS
               and k not in ("agent_email_confirm", "agent_verifier_subagent"))
    cfg = S.load_settings()
    cfg[key] = not DEFAULT_SETTINGS[key]
    S.save_settings(cfg)
    fresh()

    _call({"action": "reset", "key": key})
    fresh()
    assert S.get_setting(key, None) == DEFAULT_SETTINGS[key]


def test_every_empty_structured_setting_is_protected_not_just_networks(settings_file):
    """The rule is computed from `DEFAULT_SETTINGS`, not a list, so a ninth empty
    structured setting is covered the day it is added. A per-key list would need
    someone to remember, which is the failure mode `Law 13` names."""
    S, fresh = settings_file
    for key, default in sorted(_structured().items()):
        if default:
            continue
        written = ["operator-authored"] if isinstance(default, list) else {"k": "v"}
        cfg = S.load_settings()
        cfg[key] = written
        S.save_settings(cfg)
        fresh()
        _call({"action": "reset", "key": key})
        fresh()
        assert S.get_setting(key, None) == written, f"reset deleted {key}"


def test_the_set_refusal_no_longer_offers_a_reset_that_would_delete(settings_file):
    """The offer was the bug's delivery mechanism: `set` said no and pointed at
    `reset`, and `reset` was the destructive one."""
    out = _call({"action": "set", "key": "networks", "value": "[]"})
    assert "reset it to default here" not in out["response"].lower()
    keeps = _call({"action": "set", "key": "keybinds", "value": "{}"})
    assert "reset it to default here" in keeps["response"].lower(), (
        "the offer is still correct for a structured setting that ships with "
        "content, and removing it there would be over-correction")


def test_emptying_networks_narrows_rather_than_widens(settings_file):
    """The claim the fix's comment makes, tested rather than asserted — because
    if it were an escalation the guard would belong in `_SELF_RESTRAINT_KEYS`
    instead, and someone will check."""
    S, fresh = settings_file
    import src.networks as N

    cfg = S.load_settings()
    cfg["networks"] = [{"name": "lab", "cidrs": ["10.9.0.0/16"]}]
    S.save_settings(cfg)
    fresh()
    with N.scoped_to(["lab"]):
        assert N.host_allowed("10.9.0.5") is True

    cfg = S.load_settings()
    cfg["networks"] = []
    S.save_settings(cfg)
    fresh()
    with N.scoped_to(["lab"]):
        assert N.host_allowed("10.9.0.5") is False, "clearing the list opened a scope"
        assert N.host_allowed("8.8.8.8") is False
