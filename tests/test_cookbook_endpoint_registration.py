# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COOKBOOK_RUNNING = ROOT / "static" / "js" / "cookbookRunning.js"


def _source() -> str:
    return COOKBOOK_RUNNING.read_text(encoding="utf-8")


def test_cookbook_marks_local_endpoint_registration_as_container_local():
    src = _source()
    assert "function _appendCookbookEndpointScope" in src
    assert "fd.append('container_local', 'true')" in src
    assert src.count("_appendCookbookEndpointScope(fd,") >= 3


def test_cookbook_does_not_use_local_as_endpoint_hostname():
    src = _source()
    assert "function _connectHostFromRemote" in src
    assert "if (!host || host === 'local') return fallback;" in src
    assert "const rawHost = task.remoteHost || 'localhost';" not in src


def test_cookbook_advertised_bind_urls_keep_connectable_host():
    src = _source()
    assert "function _endpointFromAdvertisedUrl" in src
    assert "_isAnyBindHost(u.hostname) ? currentHost" in src
    assert "host = u.hostname || host;" not in src


# ── B1930: a serve command of many OLLAMA_HOST= assignments is read without stalling ──
#
# The Forge reads an Ollama serve's port from `OLLAMA_HOST=host:port`, with a
# pattern that, from every `OLLAMA_HOST=` in the command, scanned to the end of
# the word for a colon. A command of many assignments, which the serve
# validator admits, took quadratic time, and the registration runs inside
# `/api/model/serve` on the event loop, so every request waited behind it. The
# agent's own port guess (`_infer_serve_port`, src/tools/cookbook.py) has the
# same scan. Both now look at most 253 characters ahead, the longest DNS name,
# so every host that can be named still matches. Ported from upstream Odysseus
# 1844b084 (#7031), without its move of the registration into a package.

MANY_ASSIGNMENTS = "OLLAMA_HOST=" * 8000 + " ollama serve"


@pytest.fixture
def endpoint_db(monkeypatch):
    """The Forge's registration over a temp database; nothing answers a probe."""
    import core.database as database
    import routes.model_routes as model_routes
    from tests.helpers.sqlite_db import make_temp_sqlite

    factory, engine, tmpfile = make_temp_sqlite(database.Base.metadata)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(model_routes, "_probe_endpoint", lambda *a, **k: None)
    yield factory
    engine.dispose()
    os.unlink(tmpfile.name)


def _registration():
    """`_auto_register_llm_endpoint`, as the real `/api/model/serve` handler holds it."""
    from routes.cookbook_routes import setup_cookbook_routes

    serve = next(r.endpoint for r in setup_cookbook_routes().routes
                 if getattr(r, "path", "") == "/api/model/serve")
    return serve.__closure__[serve.__code__.co_freevars.index("_auto_register_llm_endpoint")].cell_contents


def _base_url(factory, ep_id):
    from core.database import ModelEndpoint

    assert ep_id
    with factory() as db:
        return db.get(ModelEndpoint, ep_id).base_url


def test_a_serve_command_of_many_ollama_host_assignments_registers_without_stalling(endpoint_db):
    from routes.cookbook_helpers import ServeRequest

    register = _registration()
    started = time.perf_counter()
    ep_id = register(ServeRequest(repo_id="library/qwen3", cmd=MANY_ASSIGNMENTS), None)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"registration took {elapsed:.2f}s"
    assert _base_url(endpoint_db, ep_id) == "http://localhost:11434/v1"
    # The bound keeps every host that can be named: 253 characters is the longest.
    longest = register(ServeRequest(repo_id="library/qwen3", cmd=f"OLLAMA_HOST={'h' * 253}:11435 ollama serve"), None)
    assert _base_url(endpoint_db, longest) == "http://localhost:11435/v1"


def test_the_agents_port_guess_for_a_command_of_many_ollama_host_assignments_returns_without_stalling():
    from src.tools.cookbook import _infer_serve_port

    started = time.perf_counter()
    port = _infer_serve_port(MANY_ASSIGNMENTS)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"the port guess took {elapsed:.2f}s"
    assert port == 11434
