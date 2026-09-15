# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B90` / `B91` — one vocabulary for environment truthiness, and a stored `no`
that can beat it.

Two rows, one storage question. `B91` is *what does this string mean*: ten
incompatible answers across 38 sites, so `PANTHEON_STARTUP_WARMUPS=1` was on and
`IMAP_STARTTLS=1` was off in the same process. `B90` is *can the operator say
no at all*: three keys resolved as `bool(get_setting(K, False)) or <env truthy>`
and an `or` has no way to be told no.

Everything here drives a real resolver. Where a case needs a settings file it is
written through the real `save_settings`, so the materialisation that makes
`B90` is reproduced rather than described (`Law 20`, and the shape
`tests/test_env_layer_reachable.py` established for `H06`/`H07`/`B20`).
"""
import importlib
import json
import os
import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def datadir(tmp_path, monkeypatch):
    """A `DATA_DIR` of our own, by rebinding the two names that matter rather
    than reloading the modules that hold them.

    **The first draft reloaded `src.constants` and `src.settings`, and it broke
    five tests in two other files** — `B18`'s class, recurring. `SETTINGS_FILE`
    is imported BY VALUE in 41 modules, so reloading `src.constants` rebinds the
    name inside that module and leaves every one of those 41 holding the old
    string; reloading `src.settings` then replaced objects `src/llm_core.py`
    had closed over, and `test_llm_core_connect_timeout` and
    `test_kimi_code_user_agent` began monkeypatching a class nobody reads.

    **The teardown could not have saved it either**, and that is the part worth
    keeping: reloading a second time produces a *third* set of objects, not the
    originals. A reload is not undoable, so a fixture that reloads a module 41
    others import from has no correct teardown. `monkeypatch` does, and it is
    what this fixture uses now — it restores the exact objects it replaced.
    """
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    import src.constants
    import src.settings

    settings_file = os.path.join(str(tmp_path), "settings.json")
    features_file = os.path.join(str(tmp_path), "features.json")
    monkeypatch.setattr(src.constants, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(src.constants, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(src.constants, "FEATURES_FILE", features_file)
    # `src.settings` took its own copies at import; both have to move.
    monkeypatch.setattr(src.settings, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(src.settings, "FEATURES_FILE", features_file)
    yield tmp_path


# ── B91: the vocabulary ────────────────────────────────────────────────────

ON = ("1", "true", "yes", "on")
OFF = ("0", "false", "no", "off")


@pytest.mark.parametrize("raw", ON)
def test_every_on_token_reads_as_on(raw):
    from src.env_flags import env_truthy
    assert env_truthy(raw) is True


@pytest.mark.parametrize("raw", OFF)
def test_every_off_token_reads_as_off(raw):
    from src.env_flags import env_truthy
    assert env_truthy(raw) is False


@pytest.mark.parametrize("raw", ["TRUE", " true ", "\tYes\n", "ON", "Off", " 0 "])
def test_case_and_surrounding_space_do_not_change_the_answer(raw):
    """37 of the 38 sites already folded case and stripped. The one that did not
    was `src/constants.py`, where `CLEANUP_ENABLED=" true"` silently disabled
    cleanup — measured 2026-09-15 and asserted against the real constant below."""
    from src.env_flags import env_truthy
    assert env_truthy(raw) is (raw.strip().lower() in ON)


@pytest.mark.parametrize("raw", [None, "", "   ", "maybe", "enabled", "y", "n", "2"])
def test_anything_outside_the_vocabulary_is_a_third_answer_not_a_second_false(raw):
    """`None` is what lets `env_flag` reproduce a site's own default, and it is
    what `SECURE_COOKIES` needs to fall through to scheme auto-detection. A
    two-valued helper would have had to guess for both."""
    from src.env_flags import env_truthy
    assert env_truthy(raw) is None


def test_y_and_n_are_deliberately_outside_the_vocabulary():
    """`Law 1`, and the reason the set is derived rather than designed.

    No site in this tree accepted `y` on an environment variable, so admitting
    it would widen 38 sites on the strength of a preference. `n` is worse: the
    six `not in (...)` sites read an unrecognised word as ON, so admitting `n`
    would silently turn six switches off. The asymmetry with `yes` is the price
    and it is a smaller price than that."""
    from src.env_flags import ON_VALUES, OFF_VALUES, env_truthy
    assert "y" not in ON_VALUES and "n" not in OFF_VALUES
    assert env_truthy("y") is None and env_truthy("n") is None


def test_a_non_string_is_judged_by_truthiness_and_a_string_never_is():
    """The trap `B20` named: `bool("false")` is True. A stored bool arrives here
    typed and is believed; a string is judged on its spelling."""
    from src.env_flags import env_truthy
    assert env_truthy(False) is False
    assert env_truthy(True) is True
    assert bool("false") is True, "precondition: this is the trap being avoided"
    assert env_truthy("false") is False


def test_env_flag_answers_with_the_callers_default_when_the_environment_is_silent(monkeypatch):
    """Why adoption is nearly behaviour-preserving: a site spelled `== "true"` is
    *off unless true* and a site spelled `not in ("0","false","no")` is *on
    unless one of these*, so passing the site's own default reproduces its answer
    for every value it already recognised."""
    from src.env_flags import env_flag
    monkeypatch.delenv("_B91_PROBE", raising=False)
    assert env_flag("_B91_PROBE", False) is False
    assert env_flag("_B91_PROBE", True) is True
    monkeypatch.setenv("_B91_PROBE", "nonsense")
    assert env_flag("_B91_PROBE", True) is True
    assert env_flag("_B91_PROBE", False) is False
    monkeypatch.setenv("_B91_PROBE", "0")
    assert env_flag("_B91_PROBE", True) is False, "a recognised word beats the default"


def test_env_flag_ignores_the_process_default_when_the_variable_says_otherwise(monkeypatch):
    from src.env_flags import env_flag
    monkeypatch.setenv("_B91_PROBE", "on")
    assert env_flag("_B91_PROBE", False) is True


# ── B91: the disagreement the row is named for, driven ─────────────────────

def test_one_value_no_longer_means_opposite_things_in_one_process(monkeypatch):
    """The row's headline, driven through four real resolvers at once.

    Measured before the fix on 2026-09-15: `IMAP_STARTTLS=1` was off while
    `PANTHEON_STARTUP_WARMUPS=1` was on, and `CLEANUP_ENABLED=" true"` was off
    while `CLEANUP_ENABLED=true` was on — one host, one process, three answers.
    """
    import routes.email_helpers as E
    from src.env_flags import env_flag
    monkeypatch.setenv("IMAP_STARTTLS", "1")
    monkeypatch.setenv("PANTHEON_STARTUP_WARMUPS", "1")
    monkeypatch.setenv("CLEANUP_ENABLED", " 1 ")
    assert E._starttls(os.environ["IMAP_STARTTLS"]) is True
    assert env_flag("PANTHEON_STARTUP_WARMUPS", False) is True
    assert env_flag("CLEANUP_ENABLED", True) is True


def test_the_two_resolvers_of_imap_starttls_still_agree_on_every_spelling():
    """`B20` pinned this agreement against a transcription of the sibling's
    rule; it is pinned against the shared rule now, which is the point — the two
    cannot drift apart again because there is only one of them."""
    import mcp_servers.email_server  # noqa: F401  — the sibling resolver's module
    import routes.email_helpers as E
    from src.env_flags import env_flag

    for raw in ("true", "TRUE", " true ", "false", "1", "0", "yes", "on", "off", "", "x"):
        os.environ["IMAP_STARTTLS"] = raw
        try:
            assert E._starttls(raw) is env_flag("IMAP_STARTTLS", False), raw
        finally:
            os.environ.pop("IMAP_STARTTLS", None)


def test_the_cleanup_constant_survives_a_trailing_space(monkeypatch):
    """The one site of 38 that never stripped.

    Driven through `env_flag` — the function `src/constants.py:110` actually
    calls — rather than by reloading `src.constants`. **A reload here broke five
    tests in two other files**: 41 modules import from `src.constants` by value,
    so rebinding a name inside it leaves all 41 on the old object, and a second
    reload in teardown produces a third set rather than the originals. A reload
    is not undoable (`B18`).

    Asserting through the function also tests the thing that can be wrong. The
    constant is a *call* to `env_flag`, so a reload was exercising Python's
    import machinery to reach one line of arithmetic.
    """
    from src.env_flags import env_flag
    from src import constants

    monkeypatch.setenv("CLEANUP_ENABLED", " true")
    assert env_flag("CLEANUP_ENABLED", True) is True
    monkeypatch.setenv("CLEANUP_ENABLED", " false ")
    assert env_flag("CLEANUP_ENABLED", True) is False
    # And the constant really is that call, so the assertion above is about the
    # shipped value rather than about a helper nobody uses (`Law 20`).
    monkeypatch.delenv("CLEANUP_ENABLED", raising=False)
    assert constants.CLEANUP_ENABLED is env_flag("CLEANUP_ENABLED", True)


def test_the_held_sites_are_still_held_and_still_mean_what_they_meant(monkeypatch):
    """`Law 1`. Nine sites keep their own rule because adopting the shared one
    would loosen a control or flip a live deployment, and this asserts the
    direction rather than the exemption comment — a test that greps for
    `env-spelling` would be testing the comment (`Law 20`).

    `AUTH_ENABLED=0` must still leave authentication ENABLED. The value is wrong
    and correcting it is a release-note change; what must not happen is a host
    booting unauthenticated because of a sweep."""
    # No reload: `auth_disabled()` reads the environment at call time, so the
    # module object never needed replacing (`B18` — a reload is not undoable,
    # and this one was reaching for a value the function already re-reads).
    import src.owner_identity
    monkeypatch.setenv("AUTH_ENABLED", "0")
    assert src.owner_identity.auth_disabled() is False
    monkeypatch.setenv("AUTH_ENABLED", "no")
    assert src.owner_identity.auth_disabled() is False
    monkeypatch.setenv("AUTH_ENABLED", "false")
    assert src.owner_identity.auth_disabled() is True, "the one spelling that works"


def test_localhost_bypass_is_still_deaf_to_everything_but_true(monkeypatch):
    """`.pantheon/FORBIDDEN.md` Part 2 names this control. Widening it would turn
    an auth bypass ON for every host already carrying `LOCALHOST_BYPASS=1`."""
    import src.auth_helpers
    for raw in ("1", "yes", "on"):
        monkeypatch.setenv("LOCALHOST_BYPASS", raw)
        assert os.getenv("LOCALHOST_BYPASS", "false").lower() != "true"
    monkeypatch.setenv("LOCALHOST_BYPASS", "true")
    assert os.getenv("LOCALHOST_BYPASS", "false").lower() == "true"
    assert "env-spelling" in open(src.auth_helpers.__file__, encoding="utf-8").read(), (
        "and the hold carries its reason where a reader will find it"
    )


# ── B90: a stored False that beats a truthy environment ────────────────────

B90_KEYS = (
    ("metrics_enabled", "PANTHEON_METRICS_ENABLED"),
    ("searxng_widen_engines", "SEARXNG_WIDEN_ENGINES"),
    ("allow_model_download", "PANTHEON_ALLOW_MODEL_DOWNLOAD"),
)


def _resolvers(monkeypatch, env_value, stored=None):
    """Drive all three real resolvers in one state."""
    import src.settings as S
    for key, env in B90_KEYS:
        if env_value is None:
            monkeypatch.delenv(env, raising=False)
        else:
            monkeypatch.setenv(env, env_value)
    if stored is not None:
        S.save_settings(stored)
    S._invalidate_caches()
    S._warned_stored_no.clear()

    import services.search.providers as P
    import src.embedding_lanes as EL
    importlib.reload(P)
    importlib.reload(EL)
    return {
        "metrics_enabled": S.env_backed_flag(
            S.load_settings(), "metrics_enabled", "PANTHEON_METRICS_ENABLED"),
        "searxng_widen_engines": P._widen_engines_allowed(),
        "allow_model_download": EL.model_download_allowed(),
    }


def test_all_three_ship_tri_state_rather_than_false(datadir):
    """The storage-shape change, stated as a property. `False` and the shipped
    default were the same byte, which is why `setting_is_explicit` answers False
    for a deliberate `False` and cannot be the fix."""
    import src.settings as S
    for key, _ in B90_KEYS:
        assert key in S.DEFAULT_SETTINGS
        assert S.DEFAULT_SETTINGS[key] is None, key
        assert bool(S.DEFAULT_SETTINGS[key]) is False, (
            f"{key}: a reader doing bool() must see no change"
        )


def test_a_stored_false_beats_a_truthy_environment(datadir, monkeypatch):
    """The row. Measured 2026-09-15 before the fix: all three stored `False`,
    all three effective `True`."""
    import src.settings as S
    stored = dict(S.DEFAULT_SETTINGS, **{k: False for k, _ in B90_KEYS})
    assert _resolvers(monkeypatch, "1", stored) == {
        "metrics_enabled": False,
        "searxng_widen_engines": False,
        "allow_model_download": False,
    }


def test_a_truthy_environment_still_wins_when_nothing_was_stored(datadir, monkeypatch):
    """`Law 1`, the fresh-install half: an operator whose variable is winning
    today keeps it."""
    assert _resolvers(monkeypatch, "1") == {
        "metrics_enabled": True,
        "searxng_widen_engines": True,
        "allow_model_download": True,
    }


def test_a_materialising_admin_save_no_longer_manufactures_a_choice(datadir, monkeypatch):
    """`Law 1`, and the half that would otherwise have broken every Docker
    install. `POST /api/auth/settings` writes all 89 shipped defaults, so before
    this change one visit to the settings panel put a `False` on disk that
    nobody chose. It now writes `null`, and `null` is not a choice."""
    import src.settings as S
    materialised = dict(S.DEFAULT_SETTINGS)
    assert _resolvers(monkeypatch, "1", materialised) == {
        "metrics_enabled": True,
        "searxng_widen_engines": True,
        "allow_model_download": True,
    }
    on_disk = json.load(open(S.SETTINGS_FILE, encoding="utf-8"))
    for key, _ in B90_KEYS:
        assert on_disk[key] is None, f"{key} was materialised as a choice"
    assert S.is_setting_overridden("allow_model_download") is True, (
        "precondition: the key IS present after a save — presence was never the signal"
    )


def test_a_stored_true_is_honoured_with_no_environment_at_all(datadir, monkeypatch):
    stored_true = {k: True for k, _ in B90_KEYS}
    assert _resolvers(monkeypatch, None, dict(stored_true)) == {
        k: True for k, _ in B90_KEYS
    }


def test_nothing_anywhere_still_means_off(datadir, monkeypatch):
    """`Law 16`: the shipped answer for all three is no."""
    assert _resolvers(monkeypatch, None) == {k: False for k, _ in B90_KEYS}


def test_an_off_spelling_in_the_environment_is_not_permission(datadir, monkeypatch):
    assert _resolvers(monkeypatch, "0") == {k: False for k, _ in B90_KEYS}


def test_setting_is_explicit_still_cannot_answer_this_and_that_is_not_its_defect(datadir):
    """Why the fix had to be in the storage shape. `setting_is_explicit` is
    presence AND a non-default value; with `None` shipped, a stored `False`
    is now genuinely non-default, so it answers True — but it answered False
    while the default was `False`, and no caller change could have helped."""
    import src.settings as S
    S.save_settings(dict(S.DEFAULT_SETTINGS, allow_model_download=False))
    S._invalidate_caches()
    assert S.setting_is_explicit("allow_model_download") is True
    assert S.setting_is_explicit("allow_model_download", default=False) is False, (
        "and against the OLD shipped default it is False — the row, exactly"
    )


def test_the_override_is_announced_once_rather_than_silently(datadir, monkeypatch, caplog):
    """`Law 1`'s remaining cost, made visible. An install carrying a
    pre-2026-09-15 materialised `False` and a truthy variable changes behaviour
    at upgrade; this is the only case where it does, and it says so."""
    import logging
    import src.settings as S
    S.save_settings(dict(S.DEFAULT_SETTINGS, allow_model_download=False))
    S._invalidate_caches()
    S._warned_stored_no.clear()
    monkeypatch.setenv("PANTHEON_ALLOW_MODEL_DOWNLOAD", "1")
    with caplog.at_level(logging.WARNING, logger="src.settings"):
        assert S.env_backed_flag(S.load_settings(), "allow_model_download",
                                 "PANTHEON_ALLOW_MODEL_DOWNLOAD") is False
        assert S.env_backed_flag(S.load_settings(), "allow_model_download",
                                 "PANTHEON_ALLOW_MODEL_DOWNLOAD") is False
    said = [r for r in caplog.records if "PANTHEON_ALLOW_MODEL_DOWNLOAD" in r.getMessage()]
    assert len(said) == 1, "once per process, not once per request"
    assert "settings.json" in said[0].getMessage(), "and it says how to undo it"


def test_nothing_is_announced_when_the_environment_is_not_the_loser(datadir, monkeypatch, caplog):
    """A warning that fires on installs it does not apply to is noise, and noise
    is how the next real one gets missed."""
    import logging
    import src.settings as S
    S.save_settings(dict(S.DEFAULT_SETTINGS, allow_model_download=False))
    S._invalidate_caches()
    S._warned_stored_no.clear()
    monkeypatch.delenv("PANTHEON_ALLOW_MODEL_DOWNLOAD", raising=False)
    with caplog.at_level(logging.WARNING, logger="src.settings"):
        assert S.env_backed_flag(S.load_settings(), "allow_model_download",
                                 "PANTHEON_ALLOW_MODEL_DOWNLOAD") is False
    assert not [r for r in caplog.records
                if "PANTHEON_ALLOW_MODEL_DOWNLOAD" in r.getMessage()]


def test_env_backed_flag_judges_a_hand_edited_string_by_the_shared_vocabulary(datadir, monkeypatch):
    """Somebody editing `settings.json` by hand writes `"false"`, and
    `bool("false")` is True. The stored half needs the vocabulary too."""
    import src.settings as S
    monkeypatch.setenv("PANTHEON_ALLOW_MODEL_DOWNLOAD", "1")
    S._warned_stored_no.clear()
    assert S.env_backed_flag({"allow_model_download": "false"},
                             "allow_model_download",
                             "PANTHEON_ALLOW_MODEL_DOWNLOAD") is False
    assert S.env_backed_flag({"allow_model_download": "  "},
                             "allow_model_download",
                             "PANTHEON_ALLOW_MODEL_DOWNLOAD") is True, (
        "blank means unset, the rule `env_backed` already established"
    )


def test_the_metrics_endpoint_itself_refuses_when_the_operator_stored_no(datadir, monkeypatch):
    """The route, not the expression. `metrics_enabled` gates `GET /metrics`, and
    an operator who finds it open and turns it off in settings had it open."""
    import asyncio
    import types
    import routes.diagnostics_routes as D
    import src.settings as S
    from fastapi import HTTPException

    S.save_settings(dict(S.DEFAULT_SETTINGS, metrics_enabled=False))
    S._invalidate_caches()
    S._warned_stored_no.clear()
    monkeypatch.setenv("PANTHEON_METRICS_ENABLED", "1")
    importlib.reload(D)
    router = D.setup_diagnostics_routes(None, False, None)
    endpoint = next(r.endpoint for r in router.routes if r.path == "/metrics")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(endpoint(types.SimpleNamespace(state=types.SimpleNamespace())))
    assert caught.value.status_code == 404, (
        "404 and not 403: a disabled endpoint is indistinguishable from one that "
        "was never built, which is the property the route's own comment claims"
    )


def test_the_metrics_endpoint_still_opens_for_an_env_var_on_a_fresh_install(datadir, monkeypatch):
    """`Law 1`'s other side, at the route. Getting past the gate is the assertion
    — what it fails on next is the auth check, which is a different control and
    is deliberately not being tested here."""
    import asyncio
    import types
    import routes.diagnostics_routes as D
    import src.settings as S
    from fastapi import HTTPException

    assert not os.path.exists(S.SETTINGS_FILE), "precondition: nothing saved"
    S._invalidate_caches()
    monkeypatch.setenv("PANTHEON_METRICS_ENABLED", "1")
    importlib.reload(D)
    router = D.setup_diagnostics_routes(None, False, None)
    endpoint = next(r.endpoint for r in router.routes if r.path == "/metrics")
    with pytest.raises(Exception) as caught:
        asyncio.run(endpoint(types.SimpleNamespace(
            state=types.SimpleNamespace(), cookies={}, headers={})))
    assert not (isinstance(caught.value, HTTPException)
                and caught.value.status_code == 404), (
        "the gate let it through — what it died on next is `require_admin` "
        "reaching for a request this bare namespace does not have, which is a "
        "different control and is tested where it lives"
    )


# ── B91: adoption must not move a site's default ───────────────────────────
#
# This block exists because two mutations survived the first pass and both were
# the same one: invert the `default` argument at an adopted call site. Nothing
# noticed. That is the `Law 1` property the whole row rests on — `env_flag(name,
# default)` reproduces a site's behaviour *because the default passed is the
# site's own* — and it was the one property nothing measured. Every adopted
# resolver is driven here with its variable unset.


def _fresh(module, expr, env=None):
    """Evaluate `expr` against a FRESHLY IMPORTED `module`, in a subprocess.

    These assertions are about values computed at **import time** from the
    environment, so they need a fresh import — and `importlib.reload` is the
    wrong way to get one. It replaces the objects inside a module while every
    other module that imported from it by value keeps the old ones, and a
    second reload produces a third set rather than the originals: **a reload is
    not undoable** (`B18`).

    The first draft reloaded `src.llm_core` here and broke five tests in two
    other files. A subprocess gives the same fresh import with a blast radius of
    exactly one process, which is what a property about import-time evaluation
    actually needs. It costs ~200 ms per call and buys an assertion that cannot
    poison the session it runs in.
    """
    import json
    import os as _os
    import subprocess
    import sys as _sys

    script = (
        "import json, sys\n"
        "sys.path.insert(0, '.')\n"
        f"import {module} as M\n"
        f"print(json.dumps({expr}))\n"
    )
    run_env = dict(_os.environ)
    for name, value in (env or {}).items():
        if value is None:
            run_env.pop(name, None)
        else:
            run_env[name] = value
    out = subprocess.run([_sys.executable, "-c", script], cwd=str(_REPO),
                         capture_output=True, text=True, timeout=120, env=run_env)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture
def no_flags(monkeypatch):
    for name in (
        "PANTHEON_STARTUP_WARMUPS", "PANTHEON_MODEL_KEEPALIVE",
        "PANTHEON_INPROCESS_TASKS", "PANTHEON_INPROCESS_POLLERS",
        "IMAP_SSL", "IMAP_STARTTLS", "SMTP_STARTTLS", "SMTP_SSL",
        "CLEANUP_ENABLED", "PANTHEON_DISABLE_MCP",
        "PANTHEON_BROWSER_MCP_REQUIRE_CACHE", "PANTHEON_BROWSER_NO_SANDBOX",
        "BACKGROUND_TASK_FOREGROUND_GATE", "PANTHEON_LOCAL_MODEL_GATE",
        "PANTHEON_UNLIMITED_LOCAL", "PANTHEON_FORCE_UNLIMITED",
        "CARDDAV_BLOCK_PRIVATE_IPS", "EMBEDDING_BLOCK_PRIVATE_IPS",
        "IMAGE_BLOCK_PRIVATE_IPS", "INTEGRATION_API_BLOCK_PRIVATE_IPS",
        "REMINDER_WEBHOOK_BLOCK_PRIVATE_IPS",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def test_cleanup_still_runs_by_default(no_flags):
    """`CLEANUP_ENABLED` shipped `"True"` and must still ship on. A mutation
    inverting this survived the first pass: cleanup would silently stop."""
    assert _fresh("src.constants", "M.CLEANUP_ENABLED") is True


def test_the_local_inference_lift_is_still_on_and_the_force_switch_still_off(no_flags):
    """`PANTHEON_UNLIMITED_LOCAL` ships `"1"` and `PANTHEON_FORCE_UNLIMITED`
    ships `"0"` — one lifts caps on the user's own GPU, the other on every
    endpoint. Inverting either survived the first pass."""
    assert _fresh("src.runtime_limits", "M._LIFT_WHEN_LOCAL") is True
    assert _fresh("src.runtime_limits", "M._FORCE_UNLIMITED") is False


def test_the_two_gates_are_still_on_by_default(no_flags):
    assert _fresh("src.interactive_gate", "M._enabled()") is True
    assert _fresh("src.llm_core", "M._local_model_gate_enabled()") is True


def test_the_pollers_still_run_in_process_by_default(no_flags):
    assert _fresh("routes.email_pollers", "M._inprocess_pollers_enabled()") is True


def test_the_browser_mcp_defaults_are_unchanged(no_flags):
    """`PANTHEON_BROWSER_MCP_REQUIRE_CACHE` ships ON (`Law 16` — Pantheon does
    not fetch `@playwright/mcp@latest` uninvited) and `PANTHEON_DISABLE_MCP`
    ships OFF. `--no-sandbox` and `--isolated` are both still appended."""
    assert _fresh("src.builtin_mcp", "M.BROWSER_MCP_REQUIRE_CACHE") is True
    assert _fresh("src.builtin_mcp", "M.MCP_DISABLED") is False
    args = _fresh("src.builtin_mcp", "M._browser_mcp_args([])")
    assert "--no-sandbox" in args and "--isolated" in args


def test_the_mail_tls_defaults_are_unchanged(no_flags):
    """Two ship on and two ship off, and the pairing is not symmetric — IMAP
    defaults to STARTTLS and SMTP to implicit SSL. Inverting any one of the four
    is a plaintext socket or a failed handshake."""
    import mcp_servers.email_server as email_server
    # `_load_config` prefers an `email_accounts` row; with no database behind it
    # the lookup fails and it falls through to the env/legacy branch, which is
    # the one these four flags live on.
    email_server._ACCOUNT_CACHE.clear()
    try:
        cfg = email_server._load_config()
        assert (cfg["imap_ssl"], cfg["imap_starttls"]) == (False, True)
        assert (cfg["smtp_starttls"], cfg["smtp_ssl"]) == (False, True)
    finally:
        email_server._ACCOUNT_CACHE.clear()


@pytest.mark.parametrize("name", [
    "CARDDAV_BLOCK_PRIVATE_IPS", "EMBEDDING_BLOCK_PRIVATE_IPS",
    "IMAGE_BLOCK_PRIVATE_IPS", "INTEGRATION_API_BLOCK_PRIVATE_IPS",
    "REMINDER_WEBHOOK_BLOCK_PRIVATE_IPS",
])
def test_the_ssrf_switches_still_ship_permissive(no_flags, name):
    """`.env.example` says these ship `false` because a LAN integration is the
    primary use case. Adoption widened what turns them ON — it must not have
    changed what happens when nobody sets them."""
    from src.env_flags import env_flag
    assert env_flag(name, False) is False


@pytest.mark.parametrize("name,expected", [
    ("PANTHEON_STARTUP_WARMUPS", False),
    ("PANTHEON_MODEL_KEEPALIVE", False),
    ("PANTHEON_INPROCESS_TASKS", True),
])
def test_the_startup_switches_keep_their_documented_defaults(no_flags, name, expected):
    """These are read once inside `app.py`'s lifespan, which a test cannot enter
    without standing the whole app up — so the assertion is on the vocabulary
    with the site's own default, and the call sites are pinned by the source
    parity check below."""
    from src.env_flags import env_flag
    assert env_flag(name, expected) is expected


def test_every_adopted_call_site_passes_the_default_this_file_asserts():
    """The join between the two halves, and the reason the parametrised cases
    above are not circular.

    They prove `env_flag(name, D)` answers `D`. This proves the call sites in
    the tree actually pass `D` — parsed, because three of them run inside an
    ASGI lifespan and one is a module constant evaluated at import. Any site
    whose default moves without this table moving fails here, which is exactly
    the mutation that survived."""
    import ast
    import pathlib
    import subprocess

    expected = {
        "PANTHEON_STARTUP_WARMUPS": False, "PANTHEON_MODEL_KEEPALIVE": False,
        "PANTHEON_INPROCESS_TASKS": True, "PANTHEON_INPROCESS_POLLERS": True,
        "IMAP_SSL": False, "IMAP_STARTTLS": True,
        "SMTP_STARTTLS": False, "SMTP_SSL": True,
        "CLEANUP_ENABLED": True, "PANTHEON_DISABLE_MCP": False,
        "PANTHEON_BROWSER_MCP_REQUIRE_CACHE": True,
        "PANTHEON_BROWSER_NO_SANDBOX": True,
        "BACKGROUND_TASK_FOREGROUND_GATE": True, "PANTHEON_LOCAL_MODEL_GATE": True,
        "PANTHEON_UNLIMITED_LOCAL": True, "PANTHEON_FORCE_UNLIMITED": False,
        "CARDDAV_BLOCK_PRIVATE_IPS": False, "EMBEDDING_BLOCK_PRIVATE_IPS": False,
        "IMAGE_BLOCK_PRIVATE_IPS": False, "INTEGRATION_API_BLOCK_PRIVATE_IPS": False,
        "REMINDER_WEBHOOK_BLOCK_PRIVATE_IPS": False,
        "SEARXNG_WIDEN_ENGINES": False, "PANTHEON_ALLOW_MODEL_DOWNLOAD": False,
    }
    root = pathlib.Path(__file__).resolve().parent.parent
    tracked = subprocess.run(["git", "ls-files", "*.py"], cwd=root, check=True,
                             capture_output=True, text=True).stdout.split()
    seen = {}
    for rel in tracked:
        if rel.startswith(("tests/", ".pantheon/")):
            continue
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "env_flag" and len(node.args) == 2):
                continue
            name, default = node.args
            if not (isinstance(name, ast.Constant) and isinstance(default, ast.Constant)):
                continue
            seen.setdefault(name.value, set()).add((rel, node.lineno, default.value))

    for name, sites in sorted(seen.items()):
        assert name in expected, (
            f"{name} adopted env_flag at {sorted(sites)} and this table does not "
            f"record its default — add it, and assert the behaviour above"
        )
        for rel, line, default in sites:
            assert default is expected[name], (
                f"{rel}:{line} passes {default!r} for {name}; this file asserts "
                f"{expected[name]!r}. One of the two moved and the operator was "
                f"not told which"
            )
    assert len(seen) >= 20, f"only {len(seen)} adopted sites found — did the scan break?"
