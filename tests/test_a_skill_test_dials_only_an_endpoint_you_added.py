# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1818`. A skill test dialled whatever endpoint the request named, with the
request's own headers.

`POST /api/skills/{id}/test` and `/test-diff` run a skill against the person's
Utility or Default model (`_resolve_skill_test_model`). When neither resolves,
as on an install with no default model yet, the resolver took `endpoint_url`
from the request body as it came, and `headers` from the body too, asked that
URL for its model list and ran the agent loop against it. So anyone signed in
who owned a skill could make the server call loopback, the LAN or a cloud
metadata address with an `Authorization` header of their choosing. The session
routes have refused a raw endpoint URL for exactly that reason since `B541`.

Now the request can only name an endpoint the person has added: an enabled
one they may use, their own or a shared one, found by the matcher chats and
tasks use (`endpoint_matches_url`). The test runs at that endpoint's own chat
URL with that endpoint's own key, and the request's headers are never read.
Anything else is refused before a request leaves the server. The Workshop
sends the open chat's endpoint URL and no headers, so nothing it does changes.

Ported from upstream Odysseus 9ee614e2: its skill-test cases, rewritten for
Pantheon's resolver and a local SQLite file.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as database
import routes.skills_routes as skills_routes
import src.endpoint_resolver as resolver

LOCAL = "http://localhost:1234/v1"
LAN = "http://192.168.1.20:8000/v1"
SHARED = "http://127.0.0.1:11434/api"

NOT_ADDED = [
    "https://unregistered.example/v1",
    "http://169.254.169.254/latest/meta-data",
    "http://bob.example/v1",            # bob's endpoint, not alice's
    "http://disabled.example/v1",       # alice's, switched off
    "http://localhost:12345/v1",        # reads like LOCAL; another port
    "http://caller:secret@localhost:1234/v1",
    LOCAL + "?api_key=caller-secret",
    LOCAL + "#fragment",
    "not-a-url",
]
CALLER_HEADERS = {"Authorization": "Bearer attacker", "x-api-key": "attacker",
                  "Host": "169.254.169.254"}


def _request(body, owner="alice"):
    return SimpleNamespace(
        state=SimpleNamespace(current_user=owner),
        headers={},
        json=AsyncMock(return_value=body),
    )


@pytest.fixture
def endpoints(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    database.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    with factory() as db:
        for endpoint_id, owner, url, enabled in [
            ("local", "alice", LOCAL + "/", True),
            ("lan", "alice", LAN, True),
            ("shared", None, SHARED, True),
            ("bob", "bob", "http://bob.example/v1", True),
            ("disabled", "alice", "http://disabled.example/v1", False),
        ]:
            db.add(database.ModelEndpoint(
                id=endpoint_id, name=endpoint_id, owner=owner, base_url=url,
                is_enabled=enabled, api_key="server-secret",
            ))
        db.commit()
    yield factory
    engine.dispose()


@pytest.fixture
def skill_test(endpoints, monkeypatch):
    """The real `POST /{skill_id}/test` on an install with no default model:
    the model list is a probe and the run a recorder, so nothing is dialled."""
    manager = SimpleNamespace(
        load=lambda owner=None, **_k: [{"name": "skill", "owner": "alice"}],
        read_skill_md=lambda name, owner=None, **_k: "# Skill",
    )
    monkeypatch.setattr(resolver, "resolve_endpoint", lambda *a, **k: (None, None, None))
    probe = MagicMock(return_value=["model"])
    monkeypatch.setattr("src.llm_core.list_model_ids", probe)
    run = AsyncMock()
    monkeypatch.setattr(skills_routes, "_run_skill_test_job", run)
    router = skills_routes.setup_skills_routes(manager)
    test = next(r.endpoint for r in router.routes
                if r.path == "/api/skills/{skill_id}/test" and "POST" in r.methods)
    skills_routes._skill_test_jobs.pop(("alice", "skill"), None)
    try:
        yield test, probe, run
    finally:
        skills_routes._skill_test_jobs.pop(("alice", "skill"), None)


@pytest.mark.parametrize("url", NOT_ADDED)
async def test_a_skill_test_refuses_an_endpoint_nobody_added_before_anything_is_dialled(
        skill_test, url):
    test, probe, run = skill_test
    with pytest.raises(HTTPException) as exc:
        await test(_request({"endpoint_url": url, "model": "model",
                             "headers": CALLER_HEADERS}), "skill")
    assert exc.value.status_code == 400
    assert "Settings" in exc.value.detail
    probe.assert_not_called()
    run.assert_not_called()
    assert ("alice", "skill") not in skills_routes._skill_test_jobs


@pytest.mark.parametrize("server_key", ["server-secret", None])
async def test_a_skill_test_on_an_added_endpoint_uses_its_key_and_never_the_requests_headers(
        skill_test, endpoints, server_key):
    with endpoints() as db:
        db.get(database.ModelEndpoint, "local").api_key = server_key
        db.commit()
    test, probe, run = skill_test

    await test(_request({"endpoint_url": LOCAL + "/chat/completions", "model": "model",
                         "headers": CALLER_HEADERS}), "skill")
    await asyncio.sleep(0)

    headers = {"Authorization": "Bearer server-secret"} if server_key else {}
    probe.assert_called_once_with(LOCAL + "/chat/completions", headers=headers)
    assert run.call_args.args[4:8] == (LOCAL + "/chat/completions", "model", headers, "alice")
    assert skills_routes._skill_test_jobs[("alice", "skill")][-1]["_run"]["headers"] == headers


@pytest.mark.parametrize("named, endpoint_base", [
    (LAN + "/chat/completions", LAN),
    (SHARED + "/chat", SHARED),                     # a shared endpoint is one alice may use
    (LOCAL + "/../../../admin", LOCAL + "/"),       # under LOCAL, but LOCAL's own URL is dialled
])
async def test_a_skill_test_dials_the_added_endpoints_own_chat_url(
        skill_test, named, endpoint_base):
    test, probe, run = skill_test

    await test(_request({"endpoint_url": named, "model": "model"}), "skill")
    await asyncio.sleep(0)

    chat_url = resolver.build_chat_url(resolver.normalize_base(endpoint_base))
    assert probe.call_args.args == (chat_url,)
    assert run.call_args.args[4] == chat_url
    assert probe.call_args.kwargs["headers"] == resolver.build_headers(
        "server-secret", resolver.normalize_base(endpoint_base))


def test_the_resolver_both_test_routes_share_prefers_utility_then_an_added_endpoint(
        endpoints, monkeypatch):
    """`/test` and the comparison's `/test-diff` (`P8-09`) both resolve through
    `_resolve_skill_test_model`, so one check covers both."""
    probe = MagicMock(return_value=["model"])
    monkeypatch.setattr("src.llm_core.list_model_ids", probe)
    resolve = skills_routes._resolve_skill_test_model

    # A Utility model is used first, and the request's URL and headers are not.
    monkeypatch.setattr(resolver, "resolve_endpoint",
                        lambda *a, **k: (LAN + "/chat/completions", "model", None))
    assert resolve("alice", {"endpoint_url": NOT_ADDED[1], "headers": CALLER_HEADERS}) == (
        LAN + "/chat/completions", "model", None)

    # Without one, an endpoint alice added is used, with its own key...
    monkeypatch.setattr(resolver, "resolve_endpoint", lambda *a, **k: (None, None, None))
    assert resolve("alice", {"endpoint_url": LOCAL, "model": "model",
                             "headers": CALLER_HEADERS}) == (
        LOCAL + "/chat/completions", "model", {"Authorization": "Bearer server-secret"})

    # ...and one nobody added is refused before it is asked for its models.
    probe.reset_mock()
    with pytest.raises(HTTPException) as exc:
        resolve("alice", {"endpoint_url": "http://169.254.169.254/latest/meta-data",
                          "model": "model", "headers": CALLER_HEADERS})
    assert exc.value.status_code == 400
    probe.assert_not_called()
