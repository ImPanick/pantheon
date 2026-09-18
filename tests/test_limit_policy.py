# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P12` — the four layers a limit is resolved through, driven rather than read.

`FORBIDDEN.md` states the order — role profile → instance setting → environment
→ built-in default — and until `src/limit_policy.py` there was nowhere it was
written down as code. Every test here calls `resolve_int_limit` and asserts on
what came back, including **which layer answered**, because a limit that cannot
say where it came from is a 429 the operator cannot act on.

The role layer is empty (`P11-02` has not landed). It is still exercised here,
with a provider registered by the test, so that the seam is known to work on
the day roles arrive rather than discovered to be decorative (`Law 13`).
"""

import json

import pytest

import src.limit_policy as lp
import src.settings as settings


@pytest.fixture(autouse=True)
def _no_role_provider():
    lp.clear_role_limit_provider()
    yield
    lp.clear_role_limit_provider()


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """Point the settings store at a temp file and return a writer for it."""
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_FILE", str(path))

    def write(**values):
        path.write_text(json.dumps(values), encoding="utf-8")
        monkeypatch.setattr(settings, "_settings_cache", None)

    write()
    return write


# ── the bottom layer ─────────────────────────────────────────────────────────


def test_nothing_configured_gives_the_built_in_default(stored):
    got = lp.resolve_int_limit("upload_burst_limit", default=3)
    assert got.value == 3
    assert got.source == "default"


# ── the environment layer ────────────────────────────────────────────────────


def test_the_environment_beats_the_built_in_default(stored, monkeypatch):
    monkeypatch.setenv("PANTHEON_TEST_LIMIT", "7")
    got = lp.resolve_int_limit(
        "upload_burst_limit", default=3, env_name="PANTHEON_TEST_LIMIT",
    )
    assert (got.value, got.source) == (7, "env")


def test_a_limit_with_no_environment_variable_never_reads_one(stored, monkeypatch):
    # `events_retention_days` is settings-only on purpose. A resolver that
    # invented a variable name would make an undeclared knob appear to work.
    monkeypatch.setenv("PANTHEON_TEST_LIMIT", "7")
    got = lp.resolve_int_limit("upload_burst_limit", default=3, env_name=None)
    assert (got.value, got.source) == (3, "default")


def test_an_unparseable_environment_value_falls_through_rather_than_crashing(
    stored, monkeypatch,
):
    monkeypatch.setenv("PANTHEON_TEST_LIMIT", "lots")
    got = lp.resolve_int_limit(
        "upload_burst_limit", default=3, env_name="PANTHEON_TEST_LIMIT",
    )
    assert (got.value, got.source) == (3, "default")


# ── the settings layer ───────────────────────────────────────────────────────


def test_a_setting_a_person_typed_beats_the_environment(stored, monkeypatch):
    monkeypatch.setenv("PANTHEON_TEST_LIMIT", "7")
    stored(upload_burst_limit=11)
    got = lp.resolve_int_limit(
        "upload_burst_limit", default=3, env_name="PANTHEON_TEST_LIMIT",
    )
    assert (got.value, got.source) == (11, "setting")


def test_a_materialised_default_does_not_beat_the_environment(stored, monkeypatch):
    """The cost `setting_is_explicit` states out loud, pinned here.

    One admin save writes every shipped default into `settings.json`. If the
    settings layer asked *presence*, that save would mask the operator's
    environment permanently — which is `H06` / `B20`, the shape found dead
    three times. It asks presence AND a non-default value instead.
    """
    monkeypatch.setenv("PANTHEON_TEST_LIMIT", "7")
    stored(upload_burst_limit=3)          # the shipped default, materialised
    got = lp.resolve_int_limit(
        "upload_burst_limit", default=3, env_name="PANTHEON_TEST_LIMIT",
    )
    assert (got.value, got.source) == (7, "env")


# ── the role layer (`P11-02`) ────────────────────────────────────────────────


def test_a_role_profile_beats_every_layer_below_it(stored, monkeypatch):
    monkeypatch.setenv("PANTHEON_TEST_LIMIT", "7")
    stored(upload_burst_limit=11)
    lp.set_role_limit_provider(
        lambda key, owner: 25 if (key, owner) == ("upload_burst_limit", "ada") else None
    )
    got = lp.resolve_int_limit(
        "upload_burst_limit", default=3, env_name="PANTHEON_TEST_LIMIT", owner="ada",
    )
    assert (got.value, got.source) == (25, "role")


def test_an_owner_the_role_layer_says_nothing_about_falls_through(stored, monkeypatch):
    monkeypatch.setenv("PANTHEON_TEST_LIMIT", "7")
    lp.set_role_limit_provider(lambda key, owner: 25 if owner == "ada" else None)
    got = lp.resolve_int_limit(
        "upload_burst_limit", default=3, env_name="PANTHEON_TEST_LIMIT", owner="bob",
    )
    assert (got.value, got.source) == (7, "env")


def test_a_role_provider_that_throws_does_not_take_the_limit_down(stored):
    def boom(key, owner):
        raise RuntimeError("no role service")

    lp.set_role_limit_provider(boom)
    got = lp.resolve_int_limit("upload_burst_limit", default=3, owner="ada")
    assert (got.value, got.source) == (3, "default")


def test_the_role_layer_ships_empty(stored):
    """Stated rather than implied: nothing registers a provider today.

    `P12-06` and `P12-10` both say so on their rows. This asserts it, so the
    day `P11-02` wires one the row's sentence becomes false loudly instead of
    quietly.
    """
    assert lp.role_limit_provider() is None
    assert lp.role_limit("upload_burst_limit", "ada") is None


# ── clamping ─────────────────────────────────────────────────────────────────


def test_a_value_below_the_floor_is_raised_to_it_and_says_so(stored):
    stored(approval_timeout_seconds=0)
    got = lp.resolve_int_limit(
        "approval_timeout_seconds", default=600, minimum=30, maximum=86_400,
    )
    assert (got.value, got.source, got.clamped) == (30, "setting", True)


def test_a_value_above_the_ceiling_is_lowered_to_it(stored):
    stored(approval_timeout_seconds=10_000_000)
    got = lp.resolve_int_limit(
        "approval_timeout_seconds", default=600, minimum=30, maximum=86_400,
    )
    assert (got.value, got.source, got.clamped) == (86_400, "setting", True)


def test_a_value_inside_the_bounds_is_not_reported_as_clamped(stored):
    stored(approval_timeout_seconds=120)
    got = lp.resolve_int_limit(
        "approval_timeout_seconds", default=600, minimum=30, maximum=86_400,
    )
    assert got.clamped is False


# ── the coercion that bit before it was written ──────────────────────────────


def test_a_boolean_is_not_an_integer_limit(stored):
    # `bool` subclasses `int`, so `True` would otherwise resolve to 1 — a limit
    # of one upload per window, from a value nobody meant as a number.
    stored(upload_burst_limit=True)
    got = lp.resolve_int_limit("upload_burst_limit", default=3)
    assert (got.value, got.source) == (3, "default")


def test_a_number_typed_as_a_string_is_still_a_number(stored):
    stored(upload_burst_limit="11")
    got = lp.resolve_int_limit("upload_burst_limit", default=3)
    assert (got.value, got.source) == (11, "setting")
