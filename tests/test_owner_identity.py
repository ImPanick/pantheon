# SPDX-License-Identifier: AGPL-3.0-or-later
from types import SimpleNamespace

import pytest


def test_effective_storage_owner_matrix(monkeypatch):
    from src.owner_identity import DEFAULT_LOCAL_OWNER, effective_storage_owner

    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    assert effective_storage_owner(None) is None
    assert effective_storage_owner("") is None
    assert effective_storage_owner("alice") == "alice"
    for sentinel in ("api", "demo", "system", "internal-tool"):
        assert effective_storage_owner(sentinel) is None
        assert effective_storage_owner(f" {sentinel.upper()} ") is None

    monkeypatch.setenv("AUTH_ENABLED", "false")
    assert effective_storage_owner(None) == DEFAULT_LOCAL_OWNER
    assert effective_storage_owner("") == DEFAULT_LOCAL_OWNER
    assert effective_storage_owner("admin") == "admin"
    for sentinel in ("api", "demo", "system", "internal-tool"):
        assert effective_storage_owner(sentinel) is None


def test_storage_owner_for_request_uses_api_token_owner(monkeypatch):
    from src.auth_helpers import storage_owner_for_request

    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    request = SimpleNamespace(
        state=SimpleNamespace(
            current_user="api",
            api_token=True,
            api_token_owner="alice",
        )
    )

    assert storage_owner_for_request(request) == "alice"


@pytest.mark.parametrize("sentinel", ["api", "demo", "system", "internal-tool"])
def test_storage_owner_for_request_rejects_request_sentinel(monkeypatch, sentinel):
    from src.auth_helpers import storage_owner_for_request

    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    request = SimpleNamespace(
        state=SimpleNamespace(
            current_user=sentinel,
            api_token=sentinel == "api",
            api_token_owner=None,
        )
    )

    assert storage_owner_for_request(request) is None


def test_storage_owner_for_request_uses_default_local_when_auth_disabled(monkeypatch):
    from src.auth_helpers import storage_owner_for_request
    from src.owner_identity import DEFAULT_LOCAL_OWNER

    monkeypatch.setenv("AUTH_ENABLED", "false")
    request = SimpleNamespace(state=SimpleNamespace(current_user=None))

    assert storage_owner_for_request(request) == DEFAULT_LOCAL_OWNER


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, False),
        ("", False),
        ("true", False),
        ("yes", False),
        ("on", False),
        ("false", True),
        ("FALSE", True),
        (" false ", True),
        # `B96`. These five were `False` here until 2026-09-15 — an operator who
        # wrote `AUTH_ENABLED=0` got authentication left **on**, because the old
        # parser recognised the literal `false` and nothing else. The row is that
        # a switch meant the opposite of what the operator typed; this table is
        # where it was written down as correct. `env_flags.env_flag` reads the
        # whole off vocabulary now, so each of these turns auth off and says so
        # in the log once.
        ("0", True),
        ("no", True),
        ("off", True),
        ("NO", True),
        (" 0 ", True),
    ],
)
def test_auth_disabled_parser_is_centralized(monkeypatch, value, expected):
    """`AUTH_ENABLED` is read in one place and answers the whole vocabulary.

    The default is the safe one: unset, blank, or a word outside the vocabulary
    leaves authentication **enabled**, so a typo never opens the door. What
    changed in `B96` is that a word an operator plainly meant as *off* is now
    read as off instead of being silently discarded.
    """
    from src.owner_identity import auth_disabled

    if value is None:
        monkeypatch.delenv("AUTH_ENABLED", raising=False)
    else:
        monkeypatch.setenv("AUTH_ENABLED", value)

    assert auth_disabled() is expected


def test_an_unknown_spelling_leaves_authentication_on(monkeypatch):
    """The other half of `B96`, and the reason the widening is safe. A value
    nobody in the vocabulary recognises is not a guess toward off — `banana` is
    a typo, and a typo that disabled authentication would be the defect `B96`
    fixed, pointing the other way."""
    from src.owner_identity import auth_disabled

    for junk in ("banana", "1.5", "disabled", "-", "null"):
        monkeypatch.setenv("AUTH_ENABLED", junk)
        assert auth_disabled() is False, junk


def test_default_local_owner_is_reserved_auth_name_but_valid_storage_owner():
    from src.owner_identity import (
        DEFAULT_LOCAL_OWNER,
        REQUEST_SENTINEL_OWNERS,
        RESERVED_AUTH_USERNAMES,
        effective_storage_owner,
        is_default_local_owner,
    )

    assert DEFAULT_LOCAL_OWNER in RESERVED_AUTH_USERNAMES
    assert DEFAULT_LOCAL_OWNER not in REQUEST_SENTINEL_OWNERS
    assert effective_storage_owner(DEFAULT_LOCAL_OWNER, auth_is_disabled=False) == DEFAULT_LOCAL_OWNER
    assert effective_storage_owner(DEFAULT_LOCAL_OWNER, auth_is_disabled=True) == DEFAULT_LOCAL_OWNER
    assert is_default_local_owner(f" {DEFAULT_LOCAL_OWNER.upper()} ")
