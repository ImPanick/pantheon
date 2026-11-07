# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1821`. A scheduled run sent the stored key of whichever endpoint's address
its URL contained, and never refreshed a sign-in.

A scheduled agent task (and a workflow's AI step) and a scheduled research run
look up their headers in the task scheduler, after `_usable_route` has checked
that the run's URL is an enabled endpoint the owner may use. Both paths
(`_run_agent_loop`, `_execute_research_task`) then took the first enabled row
whose base was a substring of the URL, or the URL of the base, and sent that
row's stored key. Two things followed:

* A ChatGPT Subscription endpoint stores no key. Its credential is a sign-in,
  refreshed when it is used (`resolve_endpoint_runtime`), which a chat does and
  the scheduler never did, so every scheduled run on one went without a bearer
  and failed with a 401.
* Of two endpoints whose addresses contain one another, a run to one could
  send the other's key: `http://192.168.1.5:1143` is a substring of
  `http://192.168.1.5:11434/api/chat`, and `https://api.openai.co` of
  `https://api.openai.com/v1/chat/completions`.

Now both paths ask `registered_endpoint_for_url`, the matcher `_usable_route`
authorised the URL with, and send that endpoint's runtime credentials. A
refresh that fails, or a URL no usable endpoint answers to, sends none: never a
sign-in's stale stored key, never another endpoint's.

Ported from upstream Odysseus 9aa58b21, with its cases rewritten for Pantheon:
a local SQLite file stands in for its database helper, and the run keeps the
URL `_normalize_chat_endpoint` gave it (native Ollama's `/api` paths are kept
on purpose), so the headers are what is asserted.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as database
# Imported before the fixture stands in for `wait_for_interactive_quiet`, so the
# name this module binds when it is imported is the real one (`B271`).
import src.builtin_actions  # noqa: F401
import src.endpoint_resolver as resolver
import src.task_scheduler as task_scheduler
from src.task_scheduler import TaskScheduler

KINDS = ["agent", "research"]
PROVIDERS = [
    "https://api.openai.com",
    "https://api.anthropic.com/v1",
    "http://192.168.1.5:11434",
    "https://models.example.test/v1",
]
SIGN_IN = "https://chatgpt.com/backend-api/codex"


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    database.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(resolver, "resolve_url", lambda url: url)   # no DNS, no Tailscale
    # Which URL a run may use is `_usable_route`'s question, driven elsewhere;
    # this file asks which credentials go with the URL it was given.
    monkeypatch.setattr(TaskScheduler, "_usable_route", lambda self, db, task, url, model: (url, model))
    monkeypatch.setattr("src.task_endpoint.resolve_task_candidates", lambda **kwargs: [])
    monkeypatch.setattr("src.interactive_gate.wait_for_interactive_quiet", AsyncMock())
    monkeypatch.setattr("src.tool_index.get_tool_index", lambda: None)
    monkeypatch.setattr("src.research_handler.RESEARCH_DATA_DIR", tmp_path / "research")
    monkeypatch.setattr("src.event_bus.fire_event", lambda *args, **kwargs: None)
    sent = {}

    async def stream(**kwargs):
        sent["headers"] = kwargs["headers"]
        yield 'data: {"delta": "Complete"}\n\n'

    class _Researcher:
        findings = []

        def __init__(self, **kwargs):
            sent["headers"] = kwargs["llm_headers"]

        async def research(self, prompt):
            return "Complete"

        def get_stats(self):
            return {}

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", stream)
    monkeypatch.setattr("src.deep_research.DeepResearcher", _Researcher)

    def add(endpoint_id, base_url, *, owner="alice", api_key=None, enabled=True, auth_id=None):
        with factory() as db:
            db.add(database.ModelEndpoint(
                id=endpoint_id, name=endpoint_id, owner=owner, base_url=base_url,
                api_key=api_key, is_enabled=enabled, provider_auth_id=auth_id,
            ))
            db.commit()

    async def run(kind, url):
        sent.clear()
        task = SimpleNamespace(
            id="task", owner="alice", name="Scheduled", prompt="Look it up",
            task_type="research" if kind == "research" else "llm",
            endpoint_url=url, model="model", session_id="session", max_steps=1,
            crew_member_id=None, character_id=None,
        )
        scheduler = TaskScheduler(session_manager=None)
        if kind == "agent":
            # What `_execute_llm_task` hands the loop: the URL after `_usable_route`
            # and `_normalize_chat_endpoint`.
            result = await scheduler._run_agent_loop(
                task_scheduler._normalize_chat_endpoint(url), "model", task, "session")
        else:
            with factory() as db:
                result = await scheduler._execute_research_task(task, db)
        assert result == "Complete"
        return sent["headers"]

    yield SimpleNamespace(add=add, run=run)
    engine.dispose()


def _lookalike(base):
    """An address that is a substring of `base`'s and another endpoint:
    the same scheme, the host or port one character short."""
    parsed = urlparse(base)
    return f"{parsed.scheme}://{parsed.netloc[:-1]}"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("base", PROVIDERS)
@pytest.mark.parametrize("owner", ["alice", None])   # their own endpoint, or a shared one
async def test_a_scheduled_run_sends_the_key_of_the_endpoint_its_url_names_not_a_lookalikes(
        world, kind, base, owner):
    world.add("a-lookalike", _lookalike(base), api_key="lookalike-key")
    world.add("b-endpoint", base, owner=owner, api_key="server-secret")

    for url in (base, resolver.build_chat_url(base)):
        assert await world.run(kind, url) == resolver.build_headers(
            "server-secret", resolver.normalize_base(base)), url


@pytest.mark.parametrize("kind", KINDS)
async def test_a_scheduled_run_on_a_sign_in_endpoint_sends_a_fresh_token(world, monkeypatch, kind):
    world.add("subscription", SIGN_IN, auth_id="server-session")
    refresh = MagicMock(return_value={"base_url": SIGN_IN, "api_key": "refreshed-secret"})
    monkeypatch.setattr("src.chatgpt_subscription.resolve_runtime_credentials", refresh)

    headers = await world.run(kind, SIGN_IN)

    refresh.assert_called_once_with("server-session", owner="alice")
    assert headers == resolver.build_headers("refreshed-secret", SIGN_IN)
    assert headers["Authorization"] == "Bearer refreshed-secret"


@pytest.mark.parametrize("kind", KINDS)
async def test_a_scheduled_run_sends_no_credentials_it_cannot_vouch_for(world, monkeypatch, kind):
    world.add("subscription", SIGN_IN, api_key="stale-secret", auth_id="server-session")
    world.add("switched-off", "http://disabled.example/v1", api_key="server-secret", enabled=False)
    world.add("bobs", "http://bob.example/v1", owner="bob", api_key="server-secret")
    refresh = MagicMock(side_effect=ValueError("Session expired"))
    monkeypatch.setattr("src.chatgpt_subscription.resolve_runtime_credentials", refresh)
    runtime = MagicMock(wraps=resolver.resolve_endpoint_runtime)
    monkeypatch.setattr(resolver, "resolve_endpoint_runtime", runtime)

    # A sign-in whose refresh failed: not its stale stored key.
    headers = await world.run(kind, SIGN_IN)
    assert "Authorization" not in headers and "stale-secret" not in repr(headers)
    refresh.assert_called_once_with("server-session", owner="alice")
    assert headers == {}

    # An endpoint switched off, another person's, and one nobody added.
    runtime.reset_mock()
    for url in ("http://disabled.example/v1", "http://bob.example/v1", "http://nobody.example/v1"):
        assert await world.run(kind, url) == {}, url
    runtime.assert_not_called()
