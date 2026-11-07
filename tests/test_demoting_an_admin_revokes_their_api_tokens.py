# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1819`. Demoting an admin left their API tokens working, and nobody could
revoke them.

Only an admin mints an API token (Settings, a phone pairing, the agent's
`manage_tokens`), and only the token's owner may revoke or narrow it, while
they are an admin (`routes/api_token_routes.py`). A demotion took the role away
and left every token the person had minted in the bearer map, and a token
keeps whatever its scopes reach. `cookbook:*` and `metrics:read` are scope
gates for a token but operator gates for a browser
(`codex_routes._require_cookbook_scope`, `diagnostics_routes`), so a demoted
admin's integration or paired phone kept the host list, the task logs and the
serve controls their own browser had just lost, and no admin could revoke it.

Now the demotion deletes the person's API tokens before the flag flips, and
tells the bearer cache to rebuild. If the token store fails, the demotion
fails with it and the person is still an admin, as `delete_user` fails closed.
A promotion and a refused demotion touch no token.

This cannot be undone: the tokens are deleted, a phone pairing's included,
and promoting the person again does not bring them back.

Ported from upstream Odysseus c21980f5 (#6831, #6832). The cases are
upstream's, gathered so each one fails on the code before the fix, plus the
cache.
"""
import contextlib
import sys
import types

import pytest

from tests.test_delete_user_revokes_api_tokens import (
    _auth_module,
    _FakeApiToken,
    _FakeSession,
)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    auth_mod = _auth_module()
    monkeypatch.setattr(auth_mod, "_hash_password", lambda password: f"hash:{password}")
    monkeypatch.setattr(
        auth_mod, "_verify_password", lambda password, hashed: hashed == f"hash:{password}"
    )
    mgr = auth_mod.AuthManager(str(tmp_path / "auth.json"))
    assert mgr.create_user("admin", "secret-admin-pw", is_admin=True)
    assert mgr.create_user("adm2", "secret-adm2-pw", is_admin=True)
    assert mgr.create_user("bob", "secret-bob-pw", is_admin=False)
    return mgr


def _token_store(monkeypatch, session_factory):
    db_stub = types.ModuleType("core.database")
    db_stub.get_db_session = session_factory
    db_stub.ApiToken = _FakeApiToken
    monkeypatch.setitem(sys.modules, "core.database", db_stub)


@pytest.fixture
def deletes(monkeypatch):
    calls = []

    @contextlib.contextmanager
    def _fake_db_session():
        yield _FakeSession(calls)

    _token_store(monkeypatch, _fake_db_session)
    return calls


@pytest.fixture
def cache_rebuilds(monkeypatch):
    """What `app.py` registers with `core.api_tokens`: the bearer map's
    dirty flag. A recorder stands in for it."""
    from core import api_tokens

    fired = []
    monkeypatch.setattr(api_tokens, "_invalidators", [lambda: fired.append("dirty")])
    return fired


def test_demoting_an_admin_deletes_their_api_tokens_and_nothing_else_does(
        manager, deletes, cache_rebuilds):
    assert manager.set_admin("adm2", False, "bob").value == "not_authorized"
    assert deletes == [] and cache_rebuilds == []

    assert manager.set_admin("adm2", False, "admin").value == "ok"
    assert manager.is_admin("adm2") is False
    assert deletes == [[("owner ==", "adm2")]]
    assert cache_rebuilds == ["dirty"]

    # The last admin is refused, and a promotion deletes nothing either.
    assert manager.set_admin("admin", False, "admin").value == "last_admin"
    assert manager.set_admin("bob", True, "admin").value == "ok"
    assert deletes == [[("owner ==", "adm2")]]
    assert cache_rebuilds == ["dirty"]


def test_a_demotion_whose_token_purge_fails_leaves_them_an_admin(
        manager, monkeypatch, cache_rebuilds):
    assert manager.set_admin("bob", True, "admin").value == "ok"

    @contextlib.contextmanager
    def _failing_db_session():
        raise RuntimeError("database unavailable")
        yield  # pragma: no cover

    _token_store(monkeypatch, _failing_db_session)

    with pytest.raises(RuntimeError):
        manager.set_admin("bob", False, "admin")

    assert manager.is_admin("bob") is True
    assert "privileges_before_admin" in manager.users["bob"]
    assert cache_rebuilds == []
    # Nothing was written: the file still says admin.
    assert type(manager)(manager.auth_path).is_admin("bob") is True
