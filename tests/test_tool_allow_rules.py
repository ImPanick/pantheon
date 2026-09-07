# SPDX-License-Identifier: AGPL-3.0-or-later
"""P7-04 — the rule store behind the `allow_listed` rung, and its route layer.

The gate half (`src/tool_capabilities.py`) was already tested on its own; every
one of those tests injected a fake `allow_rule_lookup`. Nothing tested the real
store, which is the half that decides what the fake was standing in for.

What is load-bearing here, and has a test that fails loudly if it stops holding:

  * **Three match kinds, each matching and not matching.** A kind the matcher
    does not implement is the Law 13 defect this row exists to avoid, and a kind
    that matches too much is the Law 13 defect *inverted* — a control that reads
    as a restriction and is not one.
  * **A rule never crosses an owner.** `owner` is NOT NULL and every read filters
    on it in the WHERE clause. This is the single property whose failure turns a
    per-user convenience into a per-install one.
  * **Normalisation is `strip()` and nothing else.** Leading and trailing
    whitespace is noise from a form field; internal whitespace and case are the
    user's actual text. Widening either would grant more than the rule says.
  * **Revocation actually revokes.** Within `SNAPSHOT_TTL_SECONDS`, and not one
    run later — a grant that outlives its revocation is worse than no grant.
  * **A store that errors never allows.** Every failure path in this module ends
    at "no rule", so the gate refuses exactly as it would have.
"""

import sys
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

from tests.helpers.import_state import clear_fake_database_modules
from tests.helpers.sqlite_db import make_temp_sqlite

clear_fake_database_modules()

import core.database as cdb
from core.database import ToolAllowRule

from src import tool_allow_rules
from src.tool_allow_rules import (
    MATCH_ANY,
    MATCH_EXACT,
    MATCH_PREFIX,
    AllowRuleError,
    allow_rule_lookup_for,
    create_rule,
    delete_rule,
    list_rules,
)
from src.tool_capabilities import ToolRunSecurityContext, TrustRung

# Our own file-backed database rather than the suite's. `src.tool_allow_rules`
# resolves `core.database.SessionLocal` at CALL time (the import is inside
# `_database`), so a module-level `from ... import SessionLocal` here would
# diverge the moment any earlier test rebinds it.
_TS, _ENGINE, _TMPDB = make_temp_sqlite(cdb.Base.metadata)

ALICE = "alice-allowrules"
BOB = "bob-allowrules"


@pytest.fixture(autouse=True)
def _bind_temp_db(monkeypatch):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    parent = sys.modules.get("core")
    if parent is not None:
        monkeypatch.setattr(parent, "database", cdb, raising=False)
    monkeypatch.setattr(cdb, "SessionLocal", _TS)
    yield
    db = _TS()
    try:
        db.query(ToolAllowRule).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _lookup(owner, *, ttl=0.0):
    """A lookup that re-reads on every call, so a test sees the current rows.

    The TTL is the store's own caching, exercised on its own by the two tests
    that turn it up; everywhere else it would only make assertions depend on
    wall-clock timing.
    """
    tool_allow_rules.SNAPSHOT_TTL_SECONDS = ttl
    return allow_rule_lookup_for(owner=owner, session_id="sess-allowrules")


@pytest.fixture(autouse=True)
def _restore_ttl():
    original = tool_allow_rules.SNAPSHOT_TTL_SECONDS
    yield
    tool_allow_rules.SNAPSHOT_TTL_SECONDS = original


# ── the three match kinds ───────────────────────────────────────────────────


def test_any_matches_every_command_for_its_tool():
    create_rule(ALICE, "bash", MATCH_ANY)
    lookup = _lookup(ALICE)

    assert lookup("bash", "git status") is True
    assert lookup("bash", "rm -rf /") is True
    assert lookup("bash", "") is True


def test_any_does_not_reach_another_tool():
    create_rule(ALICE, "bash", MATCH_ANY)
    lookup = _lookup(ALICE)

    assert lookup("write_file", "git status") is False


def test_exact_matches_only_that_command():
    create_rule(ALICE, "bash", MATCH_EXACT, "git status")
    lookup = _lookup(ALICE)

    assert lookup("bash", "git status") is True
    assert lookup("bash", "git status --short") is False
    assert lookup("bash", "git") is False


def test_prefix_matches_what_starts_with_it_and_nothing_else():
    create_rule(ALICE, "bash", MATCH_PREFIX, "git log")
    lookup = _lookup(ALICE)

    assert lookup("bash", "git log --oneline -5") is True
    assert lookup("bash", "git log") is True
    assert lookup("bash", "cd /tmp && git log") is False, "prefix, not substring"


def test_a_prefix_rule_is_a_literal_prefix_and_the_widening_is_pinned():
    """`git s` covers `git shove-everything`. That is the decision, not a bug.

    A token-boundary rule would stop this match — and would stop `git s`
    matching `git status` too, because both continue mid-token. It separates
    nothing while making the control impossible to predict from its own name,
    and a control that is hard to aim gets aimed wide: the user who cannot make
    `git s` work writes `any` instead.

    The mitigation is that the pattern is stored verbatim, listed verbatim, and
    revocable in one call — not a matcher that quietly declines matches the
    stored string plainly covers.
    """
    create_rule(ALICE, "bash", MATCH_PREFIX, "git s")
    lookup = _lookup(ALICE)

    assert lookup("bash", "git status") is True
    assert lookup("bash", "git shove-everything") is True
    assert lookup("bash", "gitsomething") is False


def test_an_empty_prefix_is_not_a_wildcard():
    """`any` is the only way to say "any". An empty prefix must not be a synonym."""
    with pytest.raises(AllowRuleError):
        create_rule(ALICE, "bash", MATCH_PREFIX, "   ")

    # And a row that reached the table some other way still does not match.
    db = _TS()
    try:
        db.add(
            ToolAllowRule(
                id="smuggled-empty-prefix",
                owner=ALICE,
                tool_name="bash",
                match_kind=MATCH_PREFIX,
                pattern="",
            )
        )
        db.commit()
    finally:
        db.close()

    assert _lookup(ALICE)("bash", "rm -rf /") is False


def test_an_unknown_match_kind_is_refused_and_never_matches():
    with pytest.raises(AllowRuleError):
        create_rule(ALICE, "bash", "regex", "^git .*$")

    db = _TS()
    try:
        db.add(
            ToolAllowRule(
                id="smuggled-regex",
                owner=ALICE,
                tool_name="bash",
                match_kind="regex",
                pattern=".*",
            )
        )
        db.commit()
    finally:
        db.close()

    assert _lookup(ALICE)("bash", "anything at all") is False


# ── cross-owner isolation ───────────────────────────────────────────────────


def test_a_rule_never_matches_for_another_owner():
    create_rule(ALICE, "bash", MATCH_ANY)

    assert _lookup(ALICE)("bash", "git status") is True
    assert _lookup(BOB)("bash", "git status") is False


def test_listing_and_revocation_are_owner_scoped():
    alice_rule = create_rule(ALICE, "bash", MATCH_EXACT, "git status")
    create_rule(BOB, "bash", MATCH_EXACT, "git status")

    assert [r["id"] for r in list_rules(ALICE)] == [alice_rule["id"]]
    assert delete_rule(BOB, alice_rule["id"]) is False
    assert _lookup(ALICE)("bash", "git status") is True, "Bob must not revoke Alice's rule"


def test_a_rule_cannot_be_written_without_an_owner():
    with pytest.raises(AllowRuleError):
        create_rule("", "bash", MATCH_ANY)
    with pytest.raises(AllowRuleError):
        create_rule(None, "bash", MATCH_ANY)
    assert allow_rule_lookup_for(owner=None, session_id="s") is None


# ── normalisation: strip() and nothing more ─────────────────────────────────


def test_surrounding_whitespace_is_noise_on_both_sides():
    rule = create_rule(ALICE, "  bash  ", MATCH_EXACT, "  git status  ")
    assert rule["tool_name"] == "bash"
    assert rule["pattern"] == "git status"

    lookup = _lookup(ALICE)
    assert lookup("bash", "\n git status \t") is True


def test_internal_whitespace_is_not_collapsed():
    create_rule(ALICE, "bash", MATCH_EXACT, "git status")
    lookup = _lookup(ALICE)

    assert lookup("bash", "git  status") is False


def test_case_is_not_folded():
    create_rule(ALICE, "bash", MATCH_EXACT, "git status")
    lookup = _lookup(ALICE)

    assert lookup("bash", "GIT STATUS") is False
    assert lookup("bash", "Git Status") is False


def test_tool_names_are_not_folded_either():
    create_rule(ALICE, "bash", MATCH_ANY)
    lookup = _lookup(ALICE)

    assert lookup("BASH", "git status") is False


def test_owners_are_not_folded_either():
    """The third of these three normalisation rows, and the one that was missing.

    Making `normalize_owner` casefold survives every other test in this file,
    because `core/auth.py` folds usernames to lowercase at creation and nothing
    else reaches this store — so the two owners a fold would merge never appear
    together. That is a property of a *different* module. The contract this
    module states is exact match on `owner`, and it is pinned here directly
    rather than left resting on an upstream convention; the row below pins the
    convention as well, so a change there is visible instead of silent.

    The direction that matters is the merge: two owners that fold together get
    one rule list, which turns a per-user grant into a per-install one.
    """
    create_rule("Alice-AllowRules", "bash", MATCH_ANY)

    assert _lookup("Alice-AllowRules")("bash", "git status") is True
    assert _lookup(ALICE)("bash", "git status") is False
    # The `WHERE owner = ...` half too, not just the in-Python match: a column
    # collation that folded would reopen the same hole one layer down.
    assert list_rules(ALICE) == []


def test_the_owner_this_store_is_handed_has_already_been_lowercased(tmp_path):
    """The upstream convention the exact match above is safe under.

    Exact matching is *sufficient* today only because every username reaching
    this store has already been folded by `core/auth.py`, so a sign-in as
    `Alice` and the rules `alice` wrote are the same owner. Nothing in this
    module would notice that changing — the symptom would be an owner whose own
    rules are invisible to them, which reads as "allow rules do not work"
    rather than as an auth change.
    """
    from core.auth import AuthManager

    manager = AuthManager(auth_path=str(tmp_path / "auth.json"))
    assert manager.create_user("Alice-AllowRules", "correct horse battery staple")

    assert list(manager.users) == ["alice-allowrules"]


# ── revocation, listing, and the bookkeeping that justifies keeping a rule ──


def test_revocation_stops_the_match():
    rule = create_rule(ALICE, "bash", MATCH_ANY)
    lookup = _lookup(ALICE)
    assert lookup("bash", "git status") is True

    assert delete_rule(ALICE, rule["id"]) is True

    assert lookup("bash", "git status") is False
    assert list_rules(ALICE) == []


def test_a_revoked_rule_is_gone_within_the_snapshot_ttl():
    """The snapshot is a cache, not a grant. It must expire on its own."""
    rule = create_rule(ALICE, "bash", MATCH_ANY)
    tool_allow_rules.SNAPSHOT_TTL_SECONDS = 0.05
    lookup = allow_rule_lookup_for(owner=ALICE, session_id="sess")
    assert lookup("bash", "git status") is True

    delete_rule(ALICE, rule["id"])
    time.sleep(0.06)

    assert lookup("bash", "git status") is False


def test_a_match_records_that_the_rule_is_still_in_use():
    """Recency, not a count: the gate evaluates each action twice.

    `agent_loop` asks before rendering the approval card and `execute_tool_block`
    asks again on dispatch, so a counter fed from this lookup would report about
    double. A timestamp is idempotent under that duplication.
    """
    rule = create_rule(ALICE, "bash", MATCH_ANY)
    lookup = _lookup(ALICE)

    lookup("bash", "git status")

    stored = next(r for r in list_rules(ALICE) if r["id"] == rule["id"])
    assert stored["last_used_at"] is not None
    assert stored["created_at"] is not None


def test_a_rule_that_never_matches_is_visibly_unused():
    """The state a revoke decision turns on: created, never once matched."""
    rule = create_rule(ALICE, "bash", MATCH_EXACT, "git status")
    _lookup(ALICE)("bash", "rm -rf /")

    stored = next(r for r in list_rules(ALICE) if r["id"] == rule["id"])
    assert stored["last_used_at"] is None
    assert stored["created_at"] is not None


def test_recreating_a_rule_returns_the_one_that_exists():
    """A twin makes revocation look broken: delete the one you see, still allowed."""
    first = create_rule(ALICE, "bash", MATCH_PREFIX, "git log")
    second = create_rule(ALICE, "bash", MATCH_PREFIX, " git log ")

    assert second["id"] == first["id"]
    assert len(list_rules(ALICE)) == 1


def test_an_owner_cannot_store_unbounded_rules(monkeypatch):
    monkeypatch.setattr(tool_allow_rules, "MAX_RULES_PER_OWNER", 2)
    create_rule(ALICE, "bash", MATCH_EXACT, "one")
    create_rule(ALICE, "bash", MATCH_EXACT, "two")

    with pytest.raises(AllowRuleError):
        create_rule(ALICE, "bash", MATCH_EXACT, "three")


# ── a store that errors must never become a store that allows ───────────────


class _BrokenSessionLocal:
    def __call__(self):
        raise RuntimeError("database is unreachable")


def test_a_broken_store_answers_no_rather_than_yes(monkeypatch):
    create_rule(ALICE, "bash", MATCH_ANY)
    lookup = _lookup(ALICE)

    monkeypatch.setattr(cdb, "SessionLocal", _BrokenSessionLocal())

    assert lookup("bash", "git status") is False


def test_a_broken_store_does_not_serve_the_last_snapshot_that_worked(monkeypatch):
    """A stale grant is least visible exactly when the database is down."""
    create_rule(ALICE, "bash", MATCH_ANY)
    tool_allow_rules.SNAPSHOT_TTL_SECONDS = 0.05
    lookup = allow_rule_lookup_for(owner=ALICE, session_id="sess")
    assert lookup("bash", "git status") is True

    monkeypatch.setattr(cdb, "SessionLocal", _BrokenSessionLocal())
    time.sleep(0.06)

    assert lookup("bash", "git status") is False


def test_a_lookup_that_raises_leaves_the_gate_refusing():
    """The gate defends against this too; both halves have to hold."""
    def _explode(tool_name, content=None):
        raise RuntimeError("rule store on fire")

    context = ToolRunSecurityContext(
        rung=TrustRung.ALLOW_LISTED,
        allow_rule_lookup=_explode,
    )

    assert context.decision_for("bash", "git status").allowed is False


def test_a_real_rule_reaches_the_real_gate():
    """The seam itself: store → callable → `decision_for`, with nothing faked."""
    create_rule(ALICE, "bash", MATCH_EXACT, "git status")
    context = ToolRunSecurityContext(
        rung=TrustRung.ALLOW_LISTED,
        allow_rule_lookup=_lookup(ALICE),
    )

    assert context.decision_for("bash", "git status").allowed is True
    assert context.decision_for("bash", "rm -rf /").allowed is False


def test_a_real_rule_stops_answering_once_untrusted_content_arrives():
    """A standing yes covers a *routine* action, and a run carrying someone
    else's text is not routine. Refutation's case, with the real store behind
    it: an "anything starting with git" rule let `git push --force origin main`
    run with no prompt in a run that had already pulled in a web page — which
    the default rung stops. The strict rungs may only ever ask *more* often.
    """
    create_rule(ALICE, "bash", MATCH_PREFIX, "git ")
    lookup = _lookup(ALICE)

    clean = ToolRunSecurityContext(
        rung=TrustRung.ALLOW_LISTED, allow_rule_lookup=lookup
    )
    tainted = ToolRunSecurityContext(
        rung=TrustRung.ALLOW_LISTED,
        external_untrusted_context_seen=True,
        allow_rule_lookup=lookup,
    )

    # Not dead — the rule still answers in the run it was written for.
    assert clean.decision_for("bash", "git push --force origin main").allowed is True
    assert tainted.decision_for("bash", "git push --force origin main").allowed is False


# ── the table reaches an install that already exists ────────────────────────


def test_the_table_is_created_on_a_database_that_predates_it():
    """`init_db()`'s `create_all` is the whole migration, so prove it is enough."""
    from sqlalchemy import inspect as sa_inspect

    with _ENGINE.begin() as conn:
        conn.exec_driver_sql("DROP TABLE tool_allow_rules")
    assert "tool_allow_rules" not in sa_inspect(_ENGINE).get_table_names()

    cdb.Base.metadata.create_all(_ENGINE)

    inspector = sa_inspect(_ENGINE)
    assert "tool_allow_rules" in inspector.get_table_names()
    index_names = {ix["name"] for ix in inspector.get_indexes("tool_allow_rules")}
    assert "ix_tool_allow_rules_identity" in index_names


# ── the route layer ─────────────────────────────────────────────────────────


@pytest.fixture()
def client(monkeypatch):
    """The chat router on a real app, with the auth shim the middleware provides."""
    monkeypatch.setenv("AUTH_ENABLED", "true")

    from routes import chat_routes

    # `api_token` is what the auth middleware stamps for an API-token bearer
    # caller, and `require_user` reads it before anything else. Carried on the
    # fixture so a test can be that caller without a second app.
    signed_in = {"user": ALICE, "api_token": False, "api_token_owner": None}
    app = FastAPI()

    @app.middleware("http")
    async def _authenticate(request, call_next):
        request.state.current_user = signed_in["user"]
        request.state.api_token = signed_in["api_token"]
        request.state.api_token_owner = signed_in["api_token_owner"]
        return await call_next(request)

    app.include_router(
        chat_routes.setup_chat_routes(
            SimpleNamespace(),  # session_manager
            SimpleNamespace(),  # chat_handler
            SimpleNamespace(),  # chat_processor
            SimpleNamespace(),  # memory_manager
            SimpleNamespace(),  # research_handler
            SimpleNamespace(),  # upload_handler
        )
    )
    test_client = TestClient(app)
    test_client.signed_in = signed_in
    yield test_client


def test_route_creates_lists_and_revokes(client):
    created = client.post(
        "/api/tool-allow-rules",
        json={"tool_name": "bash", "match_kind": MATCH_PREFIX, "pattern": "git log"},
    )
    assert created.status_code == 200, created.text
    rule_id = created.json()["id"]

    listed = client.get("/api/tool-allow-rules")
    assert [r["id"] for r in listed.json()["rules"]] == [rule_id]
    # The chooser's vocabulary comes from the store, not from a second copy of
    # the three strings in the frontend.
    assert listed.json()["match_kinds"] == [MATCH_ANY, MATCH_EXACT, MATCH_PREFIX]
    assert _lookup(ALICE)("bash", "git log --oneline") is True

    revoked = client.delete(f"/api/tool-allow-rules/{rule_id}")
    assert revoked.status_code == 200
    assert client.get("/api/tool-allow-rules").json()["rules"] == []
    assert _lookup(ALICE)("bash", "git log --oneline") is False


def test_route_refuses_a_rule_for_someone_elses_owner(client):
    response = client.post(
        "/api/tool-allow-rules",
        json={
            "tool_name": "bash",
            "match_kind": MATCH_ANY,
            "owner": BOB,
        },
    )

    assert response.status_code == 403
    assert list_rules(BOB) == []
    assert list_rules(ALICE) == [], "and it must not land in the caller's list either"


def test_route_never_lists_or_revokes_another_owners_rule(client):
    bobs = create_rule(BOB, "bash", MATCH_ANY)

    assert client.get("/api/tool-allow-rules").json()["rules"] == []
    assert client.delete(f"/api/tool-allow-rules/{bobs['id']}").status_code == 404
    assert _lookup(BOB)("bash", "git status") is True, "Bob's rule survives"


def test_route_refuses_a_rule_it_cannot_describe(client):
    for body in (
        {"tool_name": "bash", "match_kind": "regex", "pattern": ".*"},
        {"tool_name": "bash", "match_kind": MATCH_PREFIX, "pattern": "   "},
        {"tool_name": "   ", "match_kind": MATCH_ANY},
    ):
        response = client.post("/api/tool-allow-rules", json=body)
        assert response.status_code == 400, body
    assert list_rules(ALICE) == []


def test_route_refuses_an_unauthenticated_caller(client):
    """All three verbs, because revoke is a verb too.

    This row used to cover `GET` and `POST` only, so the revoke route's
    authentication gate could be replaced by a bare owner lookup without the
    suite noticing — the caller would fall through to a 404 for "not your rule"
    instead of a 401 for "you are not anybody".
    """
    rule = create_rule(ALICE, "bash", MATCH_ANY)
    client.signed_in["user"] = None

    assert client.get("/api/tool-allow-rules").status_code == 401
    assert client.post(
        "/api/tool-allow-rules",
        json={"tool_name": "bash", "match_kind": MATCH_ANY},
    ).status_code == 401
    assert client.delete(f"/api/tool-allow-rules/{rule['id']}").status_code == 401
    assert [r["id"] for r in list_rules(ALICE)] == [rule["id"]]


def test_route_refuses_a_bearer_api_token_on_every_verb(client):
    """The 403 the route's own comment promises, which nothing pinned.

    No token scope grants the right to lower an owner's confirmation gate, and
    the token here is the owner's own — so a route that resolved the owner and
    skipped `require_user` would serve every one of these happily.
    """
    rule = create_rule(ALICE, "bash", MATCH_EXACT, "git status")
    client.signed_in["api_token"] = True
    client.signed_in["api_token_owner"] = ALICE

    assert client.get("/api/tool-allow-rules").status_code == 403
    assert client.post(
        "/api/tool-allow-rules",
        json={"tool_name": "bash", "match_kind": MATCH_ANY},
    ).status_code == 403
    assert client.delete(f"/api/tool-allow-rules/{rule['id']}").status_code == 403

    # Nothing written, nothing revoked.
    assert [r["id"] for r in list_rules(ALICE)] == [rule["id"]]


# ── the run and the route have to mean the same owner ───────────────────────


@pytest.fixture()
def no_login_client(monkeypatch):
    """The explicit no-login deployment: `AUTH_ENABLED=false`, nobody signed in.

    `require_user` lets the request through with `""`, and the owner is then
    whatever `storage_owner_for_request` resolves — which is the reserved local
    bucket, not the legacy NULL one.
    """
    monkeypatch.setenv("AUTH_ENABLED", "false")

    from routes import chat_routes

    app = FastAPI()

    @app.middleware("http")
    async def _anonymous(request, call_next):
        request.state.current_user = None
        request.state.api_token = False
        return await call_next(request)

    app.include_router(
        chat_routes.setup_chat_routes(
            SimpleNamespace(),  # session_manager
            SimpleNamespace(),  # chat_handler
            SimpleNamespace(),  # chat_processor
            SimpleNamespace(),  # memory_manager
            SimpleNamespace(),  # research_handler
            SimpleNamespace(),  # upload_handler
        )
    )
    yield TestClient(app)


@pytest.mark.parametrize("run_owner", [None, ""])
def test_a_rule_written_in_no_login_mode_is_the_rule_the_run_reads(
    no_login_client, run_owner
):
    """The two halves have to name the same owner, and refutation found them
    not doing so: a run carried `owner=None` while the route filed rules under
    the reserved local bucket, so every rule was written, listed, and reported
    saved — and never once read. Nothing tested that they agree, which is the
    only reason that shipped.
    """
    import src.agent_loop as agent_loop
    from src.owner_identity import DEFAULT_LOCAL_OWNER

    created = no_login_client.post(
        "/api/tool-allow-rules",
        json={"tool_name": "bash", "match_kind": MATCH_PREFIX, "pattern": "git log"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["owner"] == DEFAULT_LOCAL_OWNER

    lookup = agent_loop._resolve_allow_rule_lookup(run_owner, "sess-no-login")

    assert lookup is not None, "the run found no rules the route had just written"
    assert lookup("bash", "git log --oneline") is True
    # And through the gate, which is the only reader that matters.
    context = ToolRunSecurityContext(
        rung=TrustRung.ALLOW_LISTED, allow_rule_lookup=lookup
    )
    assert context.decision_for("bash", "git log --oneline").allowed is True
