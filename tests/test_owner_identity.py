# SPDX-License-Identifier: AGPL-3.0-or-later
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("auth_enabled", [None, "true", "false", "0"])
def test_effective_storage_owner_matrix(monkeypatch, auth_enabled):
    """No owner is nobody's bucket, whatever `AUTH_ENABLED` says.

    Until `D-2026-10-07-02` §2 `AUTH_ENABLED=false` resolved ``None`` and ``""``
    to `DEFAULT_LOCAL_OWNER`, the no-login install's bucket. There is always
    authentication now, so the answer is the same with the variable set to
    anything as with it unset."""
    from src.owner_identity import effective_storage_owner

    if auth_enabled is None:
        monkeypatch.delenv("AUTH_ENABLED", raising=False)
    else:
        monkeypatch.setenv("AUTH_ENABLED", auth_enabled)
    assert effective_storage_owner(None) is None
    assert effective_storage_owner("") is None
    assert effective_storage_owner("alice") == "alice"
    for sentinel in ("api", "demo", "system", "internal-tool"):
        assert effective_storage_owner(sentinel) is None
        assert effective_storage_owner(f" {sentinel.upper()} ") is None


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


def test_storage_owner_for_request_is_nobody_when_nobody_is_signed_in(monkeypatch):
    """`AUTH_ENABLED=false` no longer files a signed-out request under the
    reserved local owner (`D-2026-10-07-02` §2): nobody signed in owns nothing."""
    from src.auth_helpers import storage_owner_for_request

    monkeypatch.setenv("AUTH_ENABLED", "false")
    request = SimpleNamespace(state=SimpleNamespace(current_user=None))

    assert storage_owner_for_request(request) is None


@pytest.mark.parametrize(
    "value,named",
    [
        (None, False),
        ("", False),
        ("true", False),
        ("yes", False),
        ("on", False),
        ("false", True),
        ("FALSE", True),
        (" false ", True),
        # `B96`. Until 2026-09-15 these five left authentication **on**,
        # because only the literal `false` turned it off; then they turned it
        # off. Since `D-2026-10-07-02` §2 none of them turns anything off —
        # there is always authentication — and each is named as ignored, once,
        # at start: an operator wrote it to turn sign-in off.
        ("0", True),
        ("no", True),
        ("off", True),
        ("NO", True),
        (" 0 ", True),
    ],
)
def test_auth_enabled_is_read_in_one_place_and_only_to_say_it_is_ignored(monkeypatch, value, named):
    """`AUTH_ENABLED` is read in one place, through the shared vocabulary, and
    only to say that it is ignored."""
    from src.owner_identity import ignored_auth_switches

    if value is None:
        monkeypatch.delenv("AUTH_ENABLED", raising=False)
    else:
        monkeypatch.setenv("AUTH_ENABLED", value)

    assert ("AUTH_ENABLED" in ignored_auth_switches()) is named


def test_an_unknown_spelling_is_not_named(monkeypatch):
    """A value nobody in the vocabulary recognises is a typo, not a request to
    turn sign-in off — it is not news, and it never opened anything."""
    from src.owner_identity import ignored_auth_switches

    for junk in ("banana", "1.5", "disabled", "-", "null"):
        monkeypatch.setenv("AUTH_ENABLED", junk)
        assert "AUTH_ENABLED" not in ignored_auth_switches(), junk


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
    assert effective_storage_owner(DEFAULT_LOCAL_OWNER) == DEFAULT_LOCAL_OWNER
    assert is_default_local_owner(f" {DEFAULT_LOCAL_OWNER.upper()} ")
