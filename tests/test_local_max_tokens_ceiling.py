# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P3-21` — on local inference every preset's `max_tokens` was the same number.

Measured: Code Analyze ships 8000, Reason 6000, Brainstorm 4096
(`src/preset_manager.py`), and `_resolve_local_lifts` raised all three to a
hardcoded 1,000,000 whenever inference is local — which is the default for any
localhost/LAN endpoint. So the picker a user chooses between produced one
behaviour, which is `Law 15` and worse than an absent control: it is a control
that appears to do something.

`D-2026-09-08-02` settles it. The lift is right in kind — on your own GPU the
ceiling is what the box can serve — but the number describes the deployment and
the owner changes deployments: *"it can change if I put everything on stronger
hardware instead of my gaming pc."* So the 1,000,000 becomes a setting with
1,000,000 as its default, and the presets keep their numbers and are read as
FLOORS (`Law 1` — nothing is taken away).

The tests that carry the row are the two that show two presets resolving to two
different numbers, because that is the sentence the row is about. Everything
else here exists to prove the change costs no existing install anything.
"""
import importlib

import pytest

from src.runtime_limits import lift_cap

CODE_ANALYZE, REASON, BRAINSTORM = 8000, 6000, 4096


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


def _tokens(preset_max_tokens):
    """What one preset's `max_tokens` resolves to on a local endpoint."""
    import src.agent_loop as AL
    return AL._resolve_local_lifts(20, preset_max_tokens, unlimited=True)[1]


def _store(**kw):
    import src.settings as S
    S.save_settings(dict(S.DEFAULT_SETTINGS, **kw))
    S._invalidate_caches()


# ── the defect, in one test ──

def test_two_presets_resolve_to_two_numbers(datadir):
    """The row. With a ceiling of 5000, Brainstorm's 4096 is raised to the
    machine's number and Code Analyze's 8000 is not lowered to it — so the two
    presets differ, which before this change they could not."""
    _store(local_inference_max_tokens=5000)
    assert _tokens(BRAINSTORM) == 5000
    assert _tokens(CODE_ANALYZE) == CODE_ANALYZE
    assert _tokens(BRAINSTORM) != _tokens(CODE_ANALYZE)


def test_turning_the_lift_off_hands_every_preset_its_own_number(datadir):
    """0 is a reachable, documented value, not a disabled setting. This is the
    configuration in which the picker means exactly what it says."""
    _store(local_inference_max_tokens=0)
    assert [_tokens(v) for v in (CODE_ANALYZE, REASON, BRAINSTORM)] == \
        [CODE_ANALYZE, REASON, BRAINSTORM]


# ── the promise that nothing existing changes ──

def test_an_untouched_install_is_bit_for_bit_what_it_was(datadir):
    assert _tokens(CODE_ANALYZE) == 1_000_000
    assert _tokens(BRAINSTORM) == 1_000_000


def test_a_materialised_default_is_not_a_choice(datadir):
    """One admin save writes every shipped default to disk. If that counted as
    configuration the ceiling would still be 1,000,000 — the same answer — but
    the resolver would be reading a value nobody typed, which is exactly the
    reachability trap `B20`/`H06` cost the task concurrency cap. Assert the
    layer, not just the number."""
    import src.agent_loop as AL, src.settings as S
    _store()
    assert S.setting_is_explicit(AL.LOCAL_MAX_TOKENS_KEY) is False
    assert AL._local_max_tokens_ceiling() == AL.LOCAL_MAX_TOKENS_DEFAULT


def test_an_unset_key_is_never_read_through_the_merged_dict(datadir, monkeypatch):
    """The same claim, made non-vacuous. `get_setting` merges
    `DEFAULT_SETTINGS` on every read, so with today's layering it returns the
    same 1,000,000 either way and a resolver that skipped `setting_is_explicit`
    would look correct. It is not correct: the moment anything is added below
    the instance layer — an env var, a role profile — that merge makes the
    lower layer unreachable code, which is precisely what `B20`/`H06` found had
    happened to the task concurrency cap on every install from first boot.
    So: with the key unset, the merged read must not be what answers."""
    import src.agent_loop as AL, src.settings as S
    _store()
    monkeypatch.setattr(S, "get_setting", lambda *a, **k: 4242)
    assert AL._local_max_tokens_ceiling() == AL.LOCAL_MAX_TOKENS_DEFAULT
    _store(local_inference_max_tokens=777)
    assert AL._local_max_tokens_ceiling() == 4242, \
        "an explicit key must still go through the settings read"


def test_a_cloud_endpoint_never_gets_the_lift_at_all(datadir):
    import src.agent_loop as AL
    _store(local_inference_max_tokens=50_000)
    assert AL._resolve_local_lifts(20, BRAINSTORM, unlimited=False)[1] == BRAINSTORM


def test_the_round_cap_is_untouched_by_the_token_ceiling(datadir):
    """`H08` de-nested these two deliberately. A ceiling change must not move
    rounds, and the row that de-nested them is the reason to check."""
    import src.agent_loop as AL
    _store(local_inference_max_tokens=123)
    assert AL._resolve_local_lifts(20, BRAINSTORM, unlimited=True)[0] == 100_000


# ── resolution ──

def test_a_configured_ceiling_is_the_one_that_governs(datadir):
    import src.agent_loop as AL
    _store(local_inference_max_tokens=32_768)
    assert AL._local_max_tokens_ceiling() == 32_768
    assert _tokens(BRAINSTORM) == 32_768


def test_an_unreadable_value_falls_back_to_the_shipped_default(datadir):
    """A settings file with a string or a negative number in it must not
    silently narrow what the machine will generate."""
    import src.agent_loop as AL
    for bad in ("plenty", -1, None):
        _store(local_inference_max_tokens=bad)
        assert AL._local_max_tokens_ceiling() == AL.LOCAL_MAX_TOKENS_DEFAULT


def test_the_lift_is_a_floor_and_never_a_truncation(datadir):
    """`lift_cap` is `max()`. A preset asking for more than the machine's
    ceiling keeps its number — lowering it here would be taking a behaviour
    away to make the setting tidier (`Law 1`)."""
    assert lift_cap(CODE_ANALYZE, 4096, unlimited=True, pinned=False) == CODE_ANALYZE


# ── registration: a setting nothing can store is not a setting ──

def test_the_key_ships_with_the_number_it_replaced():
    import src.agent_loop as AL, src.settings as S
    assert S.DEFAULT_SETTINGS[AL.LOCAL_MAX_TOKENS_KEY] == 1_000_000
    assert AL.LOCAL_MAX_TOKENS_DEFAULT == 1_000_000


def test_the_admin_endpoint_clamps_it():
    """Unclamped, a hand-edit or a typo is an unbounded generation on someone
    else's GPU. `agent_max_rounds` is clamped in three places for this reason."""
    import pathlib, re
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "routes" / "auth_routes.py").read_text()
    assert re.search(r'"local_inference_max_tokens":\s*\(0,\s*10_?000_?000\)', src)


def test_the_number_is_no_longer_a_literal_in_the_loop():
    """The owner's complaint was that they could not answer *what does this box
    actually do* without editing source. Assert the literal is gone from the
    resolver rather than trusting that it is."""
    import inspect, src.agent_loop as AL
    body = inspect.getsource(AL._resolve_local_lifts)
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("#"))
    code = code.split('"""')[0] + code.split('"""')[-1]
    assert "1_000_000" not in code and "1000000" not in code
    assert "_local_max_tokens_ceiling()" in code
