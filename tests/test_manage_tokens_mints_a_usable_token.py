# SPDX-License-Identifier: AGPL-3.0-or-later
"""B43 — the agent's `manage_tokens` minted credentials that could not work.

Three defects on one tool, all on the same path, all silent:

1. **No prefix.** `do_manage_tokens`'s `create` built `secrets.token_urlsafe(32)`
   with nothing in front of it, while the two mint sites that worked
   (`routes/api_token_routes.py`, `companion/pairing.py`) both prefixed it and
   the auth middleware only looks at Authorization headers whose credential
   carries that prefix. The token was returned to the caller and could never
   authenticate.
2. **The owner was dropped.** The impl takes `owner` — `_owner_adapter` threads
   it from the tool context — and wrote the row without it. `_refresh_token_cache`
   resolves every row's owner against the auth store and *skips* the ones it
   cannot place, logging a warning on every rebuild. So even with a prefix, the
   token would not have entered the cache.
3. **Nothing was invalidated.** Bearer auth serves from an in-memory map that
   rebuilds only when something flags it dirty; routes reach that flag through
   `request.app.state`, which a tool running inside the model loop does not have.
   `create` therefore produced a token that did not work until an unrelated
   token operation or a restart — and `delete` left a revoked token
   **authenticating** for exactly as long.

(3) is the one that matters. (1) and (2) fail closed; (3) fails open.

The literals moved into `core/api_tokens.py` in the same change, because a
fourth private copy of a protocol constant is a fourth chance to disagree, and
the disagreement is what this was.
"""
import ast
import asyncio
import json
import pathlib
from unittest.mock import MagicMock

import pytest

import core.api_tokens as api_tokens
from core.api_tokens import (
    ACCEPTED_TOKEN_PREFIXES,
    TOKEN_PREFIX,
    TOKEN_PREFIX_LEN,
    bearer_credential,
    mint_raw_token,
)
from src.agent_tools.admin_tools import do_manage_tokens

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def invalidations(monkeypatch):
    """Spy through the real registry, not a patched function.

    Registering the spy the way `app.py` registers the middleware's own setter
    is the point: it proves the hook the tool calls actually reaches something,
    which is the whole of defect (3). Patching `invalidate_token_cache` would
    prove only that the tool called a name."""
    calls = []
    monkeypatch.setattr(api_tokens, "_invalidators", [])
    api_tokens.register_cache_invalidator(lambda: calls.append(1))
    return calls


@pytest.fixture
def token_rows(monkeypatch):
    """Capture what `do_manage_tokens` writes, without a database."""
    import core.database as db_mod

    written = []

    class _FakeApiToken:
        # A class attribute, because `delete` filters on `ApiToken.id` and the
        # ORM reads that off the class, not off an instance.
        id = MagicMock(name="ApiToken.id")

        def __init__(self, **kw):
            self.__dict__.update(kw)
            written.append(kw)

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    monkeypatch.setattr(db_mod, "ApiToken", _FakeApiToken)
    monkeypatch.setattr(db_mod, "SessionLocal", lambda: session)
    return written, session


def _run(payload, owner):
    return asyncio.run(do_manage_tokens(json.dumps(payload), owner))


# --- the accept side -------------------------------------------------------


def test_bearer_credential_takes_every_prefix_this_build_accepts():
    """Adding a prefix to the tuple is the whole of the read-side migration.
    If this ever needs a second edit somewhere else, the tuple is a lie."""
    assert ACCEPTED_TOKEN_PREFIXES, "a build that accepts no prefix accepts no token"
    for prefix in ACCEPTED_TOKEN_PREFIXES:
        raw = prefix + "x" * 43
        assert bearer_credential(f"Bearer {raw}") == raw, prefix


def test_bearer_credential_refuses_what_is_not_one_of_ours():
    assert bearer_credential("") is None
    assert bearer_credential("Bearer " + "x" * 43) is None, (
        "a bare secret with no prefix is what B43's create action produced"
    )
    assert bearer_credential("Basic " + TOKEN_PREFIX + "x" * 43) is None
    assert bearer_credential(TOKEN_PREFIX + "x" * 43) is None, "no scheme at all"


def test_the_scheme_is_case_insensitive_and_the_prefix_is_not():
    raw = TOKEN_PREFIX + "x" * 43
    assert bearer_credential(f"bearer {raw}") == raw, "RFC 7235 §2.1"
    assert bearer_credential(f"BEARER {raw}") == raw
    assert bearer_credential("Bearer " + TOKEN_PREFIX.upper() + "x" * 43) is None


def test_the_minted_token_is_one_the_accept_side_takes():
    """The two halves are separate constants on purpose — which means nothing
    stops them drifting apart except this."""
    raw = mint_raw_token()
    assert bearer_credential(f"Bearer {raw}") == raw
    assert raw.startswith(TOKEN_PREFIX)
    assert len(raw) == len(TOKEN_PREFIX) + 43
    assert len(raw[:TOKEN_PREFIX_LEN]) == TOKEN_PREFIX_LEN
    assert mint_raw_token() != mint_raw_token()


# --- the tool --------------------------------------------------------------


def test_create_returns_a_token_the_middleware_would_accept(token_rows, invalidations):
    written, _ = token_rows
    res = _run({"action": "create", "name": "n8n"}, "alice")
    assert res["exit_code"] == 0, res
    assert bearer_credential("Bearer " + res["token"]) == res["token"], (
        "the token this tool hands back must be one the auth middleware will "
        "even look at — before B43 it was not"
    )
    assert written, "no row was written"
    assert written[0]["token_prefix"] == res["token"][:TOKEN_PREFIX_LEN]


def test_create_attributes_the_owner_it_was_handed(token_rows, invalidations):
    written, _ = token_rows
    res = _run({"action": "create", "name": "n8n"}, "alice")
    assert written[0]["owner"] == "alice", (
        "an ownerless row is skipped by _refresh_token_cache, so the token "
        "never enters the cache the middleware reads"
    )
    assert res["owner"] == "alice"


def test_create_stores_the_hash_and_not_the_secret(token_rows, invalidations):
    written, _ = token_rows
    res = _run({"action": "create", "name": "n8n"}, "alice")
    assert written[0]["token_hash"] != res["token"]
    assert res["token"] not in written[0]["token_hash"]
    assert written[0]["scopes"] == "chat", (
        "written down rather than left to the column default — the tool the "
        "model drives is not where a credential gets widened"
    )
    assert res["scopes"] == ["chat"]


def test_create_without_an_owner_refuses_instead_of_minting_a_dead_token(
    token_rows, invalidations
):
    written, _ = token_rows
    res = _run({"action": "create", "name": "n8n"}, None)
    assert res["exit_code"] == 1, res
    assert "owner" in res["error"].lower()
    assert not written, "refused, and still wrote a row"
    assert not invalidations


def test_create_invalidates_the_token_cache(token_rows, invalidations):
    _run({"action": "create", "name": "n8n"}, "alice")
    assert invalidations, (
        "a token nobody told the middleware about does not work until the "
        "next restart"
    )


def test_delete_invalidates_the_token_cache(token_rows, invalidations):
    _, session = token_rows
    session.query.return_value.filter.return_value.first.return_value = MagicMock(
        name="row", id="abc12345"
    )
    res = _run({"action": "delete", "token_id": "abc12345"}, "alice")
    assert res["exit_code"] == 0, res
    assert invalidations, (
        "this is the half that fails open: the row is gone and the cached "
        "copy went on authenticating until a restart"
    )


def test_a_delete_that_found_nothing_does_not_claim_to_have_revoked_anything(
    token_rows, invalidations
):
    res = _run({"action": "delete", "token_id": "nope"}, "alice")
    assert res["exit_code"] == 1
    assert "not found" in res["error"]


# --- the constant ----------------------------------------------------------


def _string_constants(path):
    """Every string literal in a module, docstrings excluded.

    Docstrings are prose: `core/api_tokens.py` explains the prefix in words and
    `app.py`'s comments discuss it, and a check that counted those would be
    testing the commentary rather than the code (`Law 20`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docstrings
    ]


MINT_SITES = (
    "routes/api_token_routes.py",
    "companion/pairing.py",
    "src/agent_tools/admin_tools.py",
    "app.py",
)


@pytest.mark.parametrize("rel", MINT_SITES)
def test_no_mint_site_spells_the_prefix_itself(rel):
    """`core/api_tokens.py` owns the literal. Three modules used to carry their
    own copy and the fourth carried none, which is exactly how they came to
    disagree."""
    literals = _string_constants(ROOT / rel)
    assert TOKEN_PREFIX not in literals, (
        f"{rel} hardcodes the token prefix; import it from core.api_tokens so "
        "the rename in P0-31 is one edit and not four"
    )
    for prefix in ACCEPTED_TOKEN_PREFIXES:
        assert f"Bearer {prefix}" not in literals, rel


def test_the_source_of_truth_does_spell_it():
    """Guards the check above from passing because the extractor broke."""
    literals = _string_constants(ROOT / "core" / "api_tokens.py")
    assert TOKEN_PREFIX in literals
