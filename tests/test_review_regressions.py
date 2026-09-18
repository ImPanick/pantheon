# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression tests for issues found during code review."""

import importlib
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.preset_manager import PresetManager
from tests.helpers.fresh_import import drop_for_fresh_import


async def _execute_without_run_context(execute_tool_block, *args, **kwargs):
    from src.tool_execution import NO_TOOL_SECURITY_CONTEXT

    kwargs.setdefault("security_context", NO_TOOL_SECURITY_CONTEXT)
    return await execute_tool_block(*args, **kwargs)


class _FakeColumn:
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):
        return ("eq", self.name, value)


class _FakeModelEndpoint:
    id = _FakeColumn("id")
    is_enabled = _FakeColumn("is_enabled")
    owner = _FakeColumn("owner")


class _FakeDbSession:
    id = _FakeColumn("id")
    endpoint_url = _FakeColumn("endpoint_url")


class _FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *conditions):
        for condition in conditions:
            if isinstance(condition, tuple) and condition[0] == "eq":
                _, field, value = condition
                self.rows = [row for row in self.rows if getattr(row, field) == value]
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)


class _FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return _FakeQuery(self.rows)

    def close(self):
        pass


def _default_chat_endpoint():
    from routes.model_routes import setup_model_routes

    router = setup_model_routes(model_discovery=None)
    for route in router.routes:
        if getattr(route, "path", "") == "/api/default-chat":
            return route.endpoint
    raise AssertionError("/api/default-chat route not found")


_REAL_PACKAGE_PATHS: dict = {}


def _package_stub(name: str) -> types.ModuleType:
    """A stand-in package that does **not** hide the submodules nobody stubbed.

    `B202`. The three installers below each built `types.ModuleType("core")` and
    set `__path__ = []` — a package that contains nothing. While it sits in
    `sys.modules`, every `core.*` submodule the stub list does not name is
    unimportable, so this file's stubs silently decided which of the real
    package's modules exist. It cost three failures: `routes/model_routes.py:21`
    grew `from core.log_safety import redact_url`, and
    `test_providers_requires_admin_before_discovery_and_cache`,
    `test_default_chat_does_not_auto_pick_shared_endpoint_for_fresh_user` and
    `test_default_chat_uses_owned_endpoint_as_regular_user_last_resort` started
    failing with `ModuleNotFoundError: No module named 'core.log_safety'`
    without a line of this file changing.

    A stub list somebody has to remember is the defect class (`Law 13`), not the
    one missing name. Borrowing the real package's `__path__` means the
    submodules that are deliberately stubbed are stubbed — they are in
    `sys.modules` and win — and every other one still loads from disk.

    The path is read once and cached, and only from a module that has a
    `__file__`: a stub another test installed must never become the cached
    answer. The cache is seeded below at import time, while `core` in
    `sys.modules` is unquestionably the real package (`tests/conftest.py`
    imports `core.database` before any test module loads).
    """
    if name not in _REAL_PACKAGE_PATHS:
        real = sys.modules.get(name)
        if real is None:
            try:
                real = importlib.import_module(name)
            except Exception:  # pragma: no cover - the package is genuinely absent
                real = None
        _REAL_PACKAGE_PATHS[name] = (
            list(getattr(real, "__path__", None) or [])
            if getattr(real, "__file__", None) is not None
            else []
        )
    stub = types.ModuleType(name)
    stub.__path__ = list(_REAL_PACKAGE_PATHS[name])
    return stub


_package_stub("core")  # seed the cache while the real package is the one loaded


def _install_model_route_import_stubs(monkeypatch):
    core_mod = _package_stub("core")
    db_mod = types.ModuleType("core.database")
    db_mod.SessionLocal = lambda: _FakeDb([])
    db_mod.ModelEndpoint = _FakeModelEndpoint
    db_mod.Session = _FakeDbSession
    db_mod.Document = MagicMock()
    db_mod.DocumentVersion = MagicMock()
    db_mod.GalleryImage = MagicMock()
    middleware_mod = types.ModuleType("core.middleware")
    middleware_mod.require_admin = lambda request: None
    multipart_mod = types.ModuleType("python_multipart")
    multipart_mod.__version__ = "0.0.13"
    models_mod = types.ModuleType("core.models")
    models_mod.ChatMessage = MagicMock()
    exceptions_mod = types.ModuleType("core.exceptions")
    exceptions_mod.SessionNotFoundError = type("SessionNotFoundError", (Exception,), {})
    session_mgr_mod = types.ModuleType("core.session_manager")
    session_mgr_mod.SessionManager = MagicMock()

    drop_for_fresh_import(monkeypatch, "routes.model_routes")
    drop_for_fresh_import(monkeypatch, "routes.chat_routes")
    drop_for_fresh_import(monkeypatch, "routes.session_routes")
    monkeypatch.setitem(sys.modules, "core", core_mod)
    monkeypatch.setitem(sys.modules, "core.database", db_mod)
    monkeypatch.setitem(sys.modules, "core.middleware", middleware_mod)
    monkeypatch.setitem(sys.modules, "python_multipart", multipart_mod)
    monkeypatch.setitem(sys.modules, "core.models", models_mod)
    monkeypatch.setitem(sys.modules, "core.exceptions", exceptions_mod)
    monkeypatch.setitem(sys.modules, "core.session_manager", session_mgr_mod)


def _install_core_auth_stub(monkeypatch):
    """Install the narrow auth surface needed by tool-policy tests."""
    core_mod = _package_stub("core")
    auth_mod = types.ModuleType("core.auth")
    auth_mod.AuthManager = MagicMock()
    core_mod.auth = auth_mod
    monkeypatch.setitem(sys.modules, "core", core_mod)
    monkeypatch.setitem(sys.modules, "core.auth", auth_mod)
    return auth_mod


def _install_core_middleware_stub(monkeypatch):
    """Install the narrow middleware surface needed by loopback tool tests."""
    core_mod = _package_stub("core")
    middleware_mod = types.ModuleType("core.middleware")
    middleware_mod.INTERNAL_TOOL_HEADER = "X-Internal-Tool"
    middleware_mod.INTERNAL_TOOL_TOKEN = "test-token"
    core_mod.middleware = middleware_mod
    monkeypatch.setitem(sys.modules, "core", core_mod)
    monkeypatch.setitem(sys.modules, "core.middleware", middleware_mod)
    return middleware_mod


# The names three tests below used to hand a `MagicMock` whenever they were not
# already imported. They are a fallback now, not the normal path — see
# `_import_chat_helpers`.
_CHAT_HELPERS_FALLBACK_STUBS = (
    "starlette.middleware",
    "starlette.middleware.base",
    "core.models",
    "core.database",
    "routes.prefs_routes",
    "routes.research_routes",
    "src.llm_core",
    "src.context_compactor",
    "src.model_context",
    "src.auth_helpers",
)


def _import_chat_helpers(monkeypatch):
    return _import_without_mocks(monkeypatch, "routes.chat_helpers",
                                 _CHAT_HELPERS_FALLBACK_STUBS)


def _import_without_mocks(monkeypatch, target, fallback_stubs):
    """Import `target` without leaving mocks baked into it.

    `B202`, and the same shape as `B18`/`B130`/`B131`. Three tests here opened
    with `if mod_name not in sys.modules: monkeypatch.setitem(sys.modules,
    mod_name, MagicMock())` over ten names and then imported
    `routes.chat_helpers`. `monkeypatch` puts `sys.modules` back at the end of
    the test — but `routes.chat_helpers` is not something it patched, so the
    module object it *created* under those mocks stays in `sys.modules` for the
    rest of the process, and that module binds four of them **by value**:

        from src.context_compactor import maybe_compact, trim_for_context
        from src.model_context import estimate_tokens, get_context_length
        from src.auth_helpers import effective_user
        from routes.prefs_routes import _load_for_user as load_prefs_for_user

    Measured on this tree: running `tests/test_review_regressions.py` alone
    leaves `routes.chat_helpers.maybe_compact`, `.trim_for_context`,
    `.effective_user` and `.load_prefs_for_user` as `MagicMock`s. The one that
    matters is `effective_user` — `_enforce_chat_privileges` reads it to decide
    *who is asking*, so every later test in that process exercises the chat
    privilege gate against a mock that answers truthily to anything, and
    `tests/test_chat_helpers.py` is four assertions about exactly that gate.
    The full suite never shows it because some file that imports
    `routes.chat_helpers` for real sorts earlier, which makes all ten guards
    dead code; any subset run re-arms them (`B18`, same sentence).

    The fix is to stop creating that module in the first place: import it for
    real, and fall back to the mocks only if the real import genuinely fails.
    On this tree the fallback never fires, so no mock is ever bound; if a
    dependency does become unimportable the old behaviour is still there.
    """
    try:
        return importlib.import_module(target)
    except Exception:
        for mod_name in fallback_stubs:
            if mod_name not in sys.modules:
                monkeypatch.setitem(sys.modules, mod_name, MagicMock())
        return importlib.import_module(target)


def test_providers_requires_admin_before_discovery_and_cache(monkeypatch):
    _install_model_route_import_stubs(monkeypatch)
    import routes.model_routes as model_routes

    class _Discovery:
        def __init__(self):
            self.calls = 0

        def get_providers(self):
            self.calls += 1
            return {"providers": [{"host": "internal.example"}]}

    discovery = _Discovery()
    router = model_routes.setup_model_routes(discovery)
    endpoint = next(
        route.endpoint
        for route in router.routes
        if getattr(route, "path", "") == "/api/providers"
    )
    request = SimpleNamespace()

    assert endpoint(request, refresh=True) == {"providers": [{"host": "internal.example"}]}
    assert discovery.calls == 1

    def deny_admin(_request):
        raise PermissionError("admin required")

    monkeypatch.setattr(model_routes, "require_admin", deny_admin)

    with pytest.raises(PermissionError):
        endpoint(request, refresh=True)
    with pytest.raises(PermissionError):
        endpoint(request, refresh=False)
    assert discovery.calls == 1


def test_default_chat_does_not_auto_pick_shared_endpoint_for_fresh_user(monkeypatch):
    _install_model_route_import_stubs(monkeypatch)
    import routes.model_routes as model_routes
    import routes.prefs_routes as prefs_routes

    shared_ep = SimpleNamespace(
        id="shared",
        base_url="http://localhost:11434",
        is_enabled=True,
        owner=None,
        cached_models='["shared-model"]',
    )

    def scoped_owner_filter(query, model_cls, user, *, include_shared=True):
        query.rows = [
            row for row in query.rows
            if row.owner == user or (include_shared and row.owner is None)
        ]
        return query

    monkeypatch.setattr(model_routes, "ModelEndpoint", _FakeModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: _FakeDb([shared_ep]))
    monkeypatch.setattr(model_routes, "_load_settings", lambda: {})
    monkeypatch.setattr(model_routes, "owner_filter", scoped_owner_filter)
    monkeypatch.setattr(model_routes, "_normalize_base", lambda base: base.rstrip("/"))
    monkeypatch.setattr(model_routes, "build_chat_url", lambda base: f"{base}/chat/completions")
    monkeypatch.setattr(prefs_routes, "_load_for_user", lambda user: {})

    request = SimpleNamespace(
        state=SimpleNamespace(current_user="fresh"),
        app=SimpleNamespace(state=SimpleNamespace(
            auth_manager=SimpleNamespace(is_admin=lambda user: False)
        )),
    )

    assert _default_chat_endpoint()(request) == {
        "endpoint_id": "",
        "endpoint_url": "",
        "model": "",
    }


def test_default_chat_uses_owned_endpoint_as_regular_user_last_resort(monkeypatch):
    _install_model_route_import_stubs(monkeypatch)
    import routes.model_routes as model_routes
    import routes.prefs_routes as prefs_routes

    owned_ep = SimpleNamespace(
        id="owned",
        base_url="http://localhost:11434",
        is_enabled=True,
        owner="fresh",
        cached_models='["owned-model"]',
    )

    def scoped_owner_filter(query, model_cls, user, *, include_shared=True):
        query.rows = [
            row for row in query.rows
            if row.owner == user or (include_shared and row.owner is None)
        ]
        return query

    monkeypatch.setattr(model_routes, "ModelEndpoint", _FakeModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: _FakeDb([owned_ep]))
    monkeypatch.setattr(model_routes, "_load_settings", lambda: {})
    monkeypatch.setattr(model_routes, "owner_filter", scoped_owner_filter)
    monkeypatch.setattr(model_routes, "_normalize_base", lambda base: base.rstrip("/"))
    monkeypatch.setattr(model_routes, "build_chat_url", lambda base: f"{base}/chat/completions")
    monkeypatch.setattr(prefs_routes, "_load_for_user", lambda user: {})

    request = SimpleNamespace(
        state=SimpleNamespace(current_user="fresh"),
        app=SimpleNamespace(state=SimpleNamespace(
            auth_manager=SimpleNamespace(is_admin=lambda user: False)
        )),
    )

    assert _default_chat_endpoint()(request) == {
        "endpoint_id": "owned",
        "endpoint_url": "http://localhost:11434/chat/completions",
        "model": "owned-model",
    }


def test_preset_manager_persists_inject_fields(tmp_path):
    manager = PresetManager(str(tmp_path))

    ok = manager.update_custom(
        temperature=0.7,
        max_tokens=2048,
        system_prompt="Be useful.",
        name="Custom",
        enabled=True,
        inject_prefix="PREFIX",
        inject_suffix="SUFFIX",
    )

    assert ok is True
    assert manager.presets["custom"]["inject_prefix"] == "PREFIX"
    assert manager.presets["custom"]["inject_suffix"] == "SUFFIX"

    reloaded = PresetManager(str(tmp_path))
    assert reloaded.presets["custom"]["inject_prefix"] == "PREFIX"
    assert reloaded.presets["custom"]["inject_suffix"] == "SUFFIX"


def test_preset_manager_default_custom_preset_starts_disabled(tmp_path):
    manager = PresetManager(str(tmp_path))

    custom = manager.presets["custom"]

    assert custom["enabled"] is False
    assert custom["system_prompt"] == ""
    assert custom["temperature"] == 1.0
    assert custom["max_tokens"] == 0


def test_preset_manager_migrates_legacy_default_custom_preset_disabled(tmp_path):
    presets_file = tmp_path / "presets.json"
    presets_file.write_text(
        json.dumps({
            "custom": {
                "name": "Custom",
                "temperature": 0.7,
                "max_tokens": 4096,
                "system_prompt": "You are a helpful, balanced assistant. Match your response style to the user's needs.",
            }
        }),
        encoding="utf-8",
    )

    manager = PresetManager(str(tmp_path))
    custom = manager.presets["custom"]

    assert custom["enabled"] is False
    assert custom["system_prompt"] == ""
    assert custom["temperature"] == 1.0
    assert custom["max_tokens"] == 0


def test_normalize_thinking_handles_lowercase_thinking_process(monkeypatch):
    chat_helpers = _import_chat_helpers(monkeypatch)

    text = (
        "Thinking process:\n"
        "Analyze the Request: The user is explicitly instructing me to use the tag.\n\n"
        "hi"
    )

    normalized = chat_helpers._normalize_thinking(text)

    assert normalized == (
        "<think>Analyze the Request: The user is explicitly instructing me to use the tag.</think>\n\n"
        "hi"
    )


@pytest.mark.asyncio
async def test_build_chat_context_incognito_does_not_duplicate_current_user_message(monkeypatch):
    chat_helpers = _import_chat_helpers(monkeypatch)
    chat_helpers._INCOGNITO_CONTEXTS.clear()

    async def fake_preprocess(chat_handler, message, att_ids, sess, **kwargs):
        # **kwargs absorbs auto_opened_docs (added when PDF imports auto-create
        # docs) and any other future preprocess kwargs without the test fixture
        # having to be updated each time.
        return chat_helpers.PreprocessedMessage(
            enhanced_message=message,
            user_content=message,
            text_for_context=message,
            youtube_transcripts=[],
            attachment_meta=[],
        )

    def fake_extract_preset(chat_handler, preset_id):
        return chat_helpers.PresetInfo(
            temperature=0.7,
            max_tokens=1024,
            system_prompt=None,
            character_name=None,
        )

    def fake_add_user_message(sess, chat_handler, preprocessed, incognito=False):
        sess.messages.append({"role": "user", "content": preprocessed.user_content})

    async def fake_maybe_compact(sess, endpoint_url, model, messages, headers, owner=None):
        return messages, 123, False

    monkeypatch.setattr(chat_helpers, "preprocess", fake_preprocess)
    monkeypatch.setattr(chat_helpers, "extract_preset", fake_extract_preset)
    monkeypatch.setattr(chat_helpers, "add_user_message", fake_add_user_message)
    monkeypatch.setattr(chat_helpers, "load_prefs_for_user", lambda user: {})
    monkeypatch.setattr(chat_helpers, "effective_user", lambda request: "tester")
    monkeypatch.setattr(chat_helpers, "normalize_model_id", lambda endpoint_url, model, **kwargs: None)
    monkeypatch.setattr(chat_helpers, "maybe_compact", fake_maybe_compact)
    monkeypatch.setattr(chat_helpers, "trim_for_context", lambda messages, context_length: messages)

    sess = SimpleNamespace(
        endpoint_url="http://localhost:8000/v1",
        model="test-model",
        headers={},
        messages=[],
        get_context_messages=lambda: list(sess.messages),
    )
    request = SimpleNamespace()
    chat_handler = SimpleNamespace()
    chat_processor = SimpleNamespace(
        build_context_preface=lambda **kwargs: ([], [], []),
    )

    ctx = await chat_helpers.build_chat_context(
        sess=sess,
        request=request,
        chat_handler=chat_handler,
        chat_processor=chat_processor,
        message="hello",
        session_id="s1",
        incognito=True,
    )

    user_messages = [m for m in ctx.messages if m.get("role") == "user" and m.get("content") == "hello"]
    assert len(user_messages) == 1


@pytest.mark.asyncio
async def test_build_chat_context_incognito_ignores_saved_session_history(monkeypatch):
    chat_helpers = _import_chat_helpers(monkeypatch)
    chat_helpers._INCOGNITO_CONTEXTS.clear()

    async def fake_preprocess(chat_handler, message, att_ids, sess, **kwargs):
        return chat_helpers.PreprocessedMessage(
            enhanced_message=message,
            user_content=message,
            text_for_context=message,
            youtube_transcripts=[],
            attachment_meta=[],
        )

    async def fake_maybe_compact(sess, endpoint_url, model, messages, headers, owner=None):
        return messages, 123, False

    monkeypatch.setattr(chat_helpers, "preprocess", fake_preprocess)
    monkeypatch.setattr(chat_helpers, "extract_preset", lambda *_args, **_kwargs: chat_helpers.PresetInfo(0.7, 1024, None, None))
    monkeypatch.setattr(chat_helpers, "load_prefs_for_user", lambda user: {})
    monkeypatch.setattr(chat_helpers, "effective_user", lambda request: "tester")
    monkeypatch.setattr(chat_helpers, "normalize_model_id", lambda endpoint_url, model, **kwargs: None)
    monkeypatch.setattr(chat_helpers, "maybe_compact", fake_maybe_compact)
    monkeypatch.setattr(chat_helpers, "trim_for_context", lambda messages, context_length: messages)

    sess = SimpleNamespace(
        endpoint_url="http://localhost:8000/v1",
        model="test-model",
        headers={},
        get_context_messages=lambda: [{"role": "user", "content": "older non-incognito secret"}],
    )
    chat_processor = SimpleNamespace(build_context_preface=lambda **kwargs: ([], [], []))

    ctx = await chat_helpers.build_chat_context(
        sess=sess,
        request=SimpleNamespace(),
        chat_handler=SimpleNamespace(),
        chat_processor=chat_processor,
        message="fresh incognito turn",
        session_id="s-incog",
        incognito=True,
    )

    assert {"role": "user", "content": "fresh incognito turn"} in ctx.messages
    assert all(m.get("content") != "older non-incognito secret" for m in ctx.messages)


@pytest.mark.asyncio
async def test_admin_agent_tools_require_admin(monkeypatch):
    auth_mod = _install_core_auth_stub(monkeypatch)
    from src.tool_execution import execute_tool_block

    class FakeAuth:
        is_configured = True

        def is_admin(self, username):
            return False

    monkeypatch.setattr(auth_mod, "AuthManager", lambda: FakeAuth())

    for tool_name in ("manage_tokens", "app_api", "serve_preset"):
        desc, result = await _execute_without_run_context(
            execute_tool_block,
            SimpleNamespace(tool_type=tool_name, content='{"action":"create","name":"bad"}'),
            owner="regular-user",
        )

        assert desc == f"{tool_name}: BLOCKED"
        assert result["exit_code"] == 1
        assert "requires an admin" in result["error"]


@pytest.mark.asyncio
async def test_app_api_blocks_shell_routes_before_loopback(monkeypatch):
    import httpx
    from src.tool_implementations import do_app_api

    class UnexpectedAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("app_api should block shell routes before loopback")

    monkeypatch.setattr(httpx, "AsyncClient", UnexpectedAsyncClient)

    for path in ("/api/shell/exec", "api/shell/stream"):
        result = await do_app_api(
            json.dumps(
                {
                    "action": "call",
                    "method": "POST",
                    "path": path,
                    "body": {"command": "echo should-not-run"},
                }
            ),
            owner="admin",
        )

        assert result["exit_code"] == 1
        assert "Path blocked for safety" in result["error"]
        assert "Sensitive endpoints" in result["error"]


@pytest.mark.asyncio
async def test_app_api_blocks_cookbook_host_control_routes_before_loopback(monkeypatch):
    import httpx
    from src.tool_implementations import do_app_api

    class UnexpectedAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("app_api should block host-control routes before loopback")

    monkeypatch.setattr(httpx, "AsyncClient", UnexpectedAsyncClient)

    blocked_calls = (
        (
            "api/cookbook/packages/install",
            {"pip": "hf_transfer"},
            "package installation is host code execution",
        ),
        (
            "/api/cookbook/rebuild-engine",
            {"engine": "llamacpp"},
            "engine rebuild mutates local or remote host state",
        ),
        (
            "/api/cookbook/kill-pid",
            {"pid": 12345, "signal": "TERM"},
            "process signalling is host control",
        ),
    )

    for path, body, error_text in blocked_calls:
        result = await do_app_api(
            json.dumps(
                {
                    "action": "call",
                    "method": "POST",
                    "path": path,
                    "body": body,
                }
            ),
            owner="admin",
        )

        assert result["exit_code"] == 1
        assert error_text in result["error"]


@pytest.mark.asyncio
async def test_app_api_blocks_search_route_before_loopback(monkeypatch):
    import httpx
    from src.tool_implementations import do_app_api

    class UnexpectedAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("app_api should block search routes before loopback")

    monkeypatch.setattr(httpx, "AsyncClient", UnexpectedAsyncClient)

    result = await do_app_api(
        json.dumps(
            {
                "action": "call",
                "method": "GET",
                "path": "/api/search",
                "query": {"q": "crow box designs"},
            }
        ),
        owner="admin",
    )

    assert result["exit_code"] == 1
    assert "use the `web_search` tool" in result["error"]


@pytest.mark.asyncio
async def test_app_api_endpoint_discovery_hides_shell_routes(monkeypatch):
    _install_core_middleware_stub(monkeypatch)
    import httpx
    from src.tool_implementations import do_app_api

    class FakeResponse:
        def json(self):
            return {
                "paths": {
                    "/api/shell/exec": {"post": {"summary": "Execute Shell Command"}},
                    "/api/shell/stream": {"post": {"summary": "Stream Shell Command"}},
                    "/api/auth/settings": {"get": {"summary": "Auth Settings"}},
                    "/api/cookbook/gpus": {"get": {"summary": "List GPUs"}},
                }
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = await do_app_api(json.dumps({"action": "endpoints"}), owner="admin")

    assert result["exit_code"] == 0
    paths = {(endpoint["method"], endpoint["path"]) for endpoint in result["endpoints"]}
    assert ("GET", "/api/cookbook/gpus") in paths
    assert ("POST", "/api/shell/exec") not in paths
    assert ("POST", "/api/shell/stream") not in paths
    assert ("GET", "/api/auth/settings") not in paths
    assert all(not endpoint["path"].startswith("/api/shell") for endpoint in result["endpoints"])


@pytest.mark.asyncio
async def test_app_api_endpoint_discovery_hides_cookbook_host_control_routes(monkeypatch):
    _install_core_middleware_stub(monkeypatch)
    import httpx
    from src.tool_implementations import do_app_api

    class FakeResponse:
        def json(self):
            return {
                "paths": {
                    "/api/cookbook/packages": {"get": {"summary": "List Cookbook Packages"}},
                    "/api/cookbook/packages/install": {"post": {"summary": "Install Package"}},
                    "/api/cookbook/rebuild-engine": {"post": {"summary": "Rebuild Engine"}},
                    "/api/cookbook/kill-pid": {"post": {"summary": "Kill Process"}},
                    "/api/cookbook/gpus": {"get": {"summary": "List GPUs"}},
                }
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = await do_app_api(json.dumps({"action": "endpoints", "filter": "cookbook"}), owner="admin")

    assert result["exit_code"] == 0
    paths = {(endpoint["method"], endpoint["path"]) for endpoint in result["endpoints"]}
    assert ("GET", "/api/cookbook/packages") in paths
    assert ("GET", "/api/cookbook/gpus") in paths
    assert ("POST", "/api/cookbook/packages/install") not in paths
    assert ("POST", "/api/cookbook/rebuild-engine") not in paths
    assert ("POST", "/api/cookbook/kill-pid") not in paths


@pytest.mark.asyncio
async def test_public_agent_policy_blocks_sensitive_tools(monkeypatch):
    auth_mod = _install_core_auth_stub(monkeypatch)
    from src.tool_execution import execute_tool_block

    class FakeAuth:
        is_configured = True

        def is_admin(self, username):
            return False

    monkeypatch.setattr(auth_mod, "AuthManager", lambda: FakeAuth())

    # Every bare email tool name is spelled out (not imported from
    # BUILTIN_EMAIL_TOOLS) so accidentally dropping one from that set fails
    # here instead of silently shrinking the blocklist.
    bare_email_tools = (
        "list_email_accounts", "list_emails", "read_email", "search_emails",
        "scan_email_unsubscribes", "unsubscribe_email",
        "send_email", "reply_to_email", "draft_email", "draft_email_reply",
        "ai_draft_email_reply", "archive_email", "delete_email",
        "mark_email_read", "bulk_email", "download_attachment",
    )
    for tool_name in bare_email_tools + ("read_file", "mcp__email__send_email"):
        desc, result = await _execute_without_run_context(
            execute_tool_block,
            SimpleNamespace(tool_type=tool_name, content="{}"),
            owner="regular-user",
        )
        assert desc == f"{tool_name}: BLOCKED"
        assert result["exit_code"] == 1
        assert "restricted to admin users" in result["error"]


@pytest.mark.asyncio
async def test_disabled_qualified_email_tool_blocks_bare_alias(monkeypatch):
    """A bare email fence is an alias for its mcp__email__ form. Plan mode and
    the MCP settings toggle write the QUALIFIED name into disabled_tools, so
    the gate must block the bare spelling too — and never reach the MCP
    manager (PR #3681 review follow-up)."""
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    def fail_get_mcp_manager():
        raise AssertionError("blocked email tool must not reach the MCP manager")

    monkeypatch.setattr(tool_execution, "get_mcp_manager", fail_get_mcp_manager)

    for bare, disabled in (
        # qualified denylist entry blocks the bare alias…
        ("list_emails", {"mcp__email__list_emails"}),
        ("download_attachment", {"mcp__email__download_attachment"}),
        # …and a bare denylist entry blocks the qualified spelling.
        ("mcp__email__delete_email", {"delete_email"}),
    ):
        desc, result = await _execute_without_run_context(
            execute_tool_block,
            SimpleNamespace(tool_type=bare, content="{}"),
            owner="admin-user",
            disabled_tools=disabled,
        )
        assert desc == f"{bare}: BLOCKED"
        assert result["exit_code"] == 1
        assert "disabled by user" in result["error"]


@pytest.mark.asyncio
async def test_tool_policy_qualified_email_block_covers_bare_alias(monkeypatch):
    """Same aliasing rule for the turn ToolPolicy denylist."""
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block
    from src.tool_policy import ToolPolicy

    def fail_get_mcp_manager():
        raise AssertionError("blocked email tool must not reach the MCP manager")

    monkeypatch.setattr(tool_execution, "get_mcp_manager", fail_get_mcp_manager)

    policy = ToolPolicy(disabled_tools=frozenset({"mcp__email__send_email"}))
    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="send_email", content="{}"),
        owner="admin-user",
        tool_policy=policy,
    )
    assert desc == "send_email: BLOCKED"
    assert result["exit_code"] == 1


@pytest.mark.asyncio
async def test_disable_tool_email_covers_full_builtin_set(monkeypatch):
    """The friendly `disable_tool email` toggle must cover every built-in
    email tool, in BOTH spellings — bare names (function-schema hiding,
    bare-fence dispatch) and mcp__email__* (MCP schema hiding, runtime
    qualified blocks). Hand-picking a subset left tools like delete_email
    and download_attachment enabled (PR #3681 review follow-up)."""
    # Import first so the module loads against the real core package; only
    # the call-time SessionLocal import below sees the stub.
    from src.tool_implementations import do_manage_settings
    import src.settings as settings_mod

    db_mod = types.ModuleType("core.database")

    class _Db:
        def close(self):
            pass

    db_mod.SessionLocal = lambda: _Db()
    monkeypatch.setitem(sys.modules, "core.database", db_mod)

    store = {}

    def fake_load_settings():
        return dict(store)

    def fake_save_settings(s):
        store.clear()
        store.update(s)

    monkeypatch.setattr(settings_mod, "load_settings", fake_load_settings)
    monkeypatch.setattr(settings_mod, "save_settings", fake_save_settings)

    result = await do_manage_settings(
        '{"action": "disable_tool", "tool": "email"}', owner="admin"
    )

    assert result["exit_code"] == 0
    disabled = set(store["disabled_tools"])
    # Spelled out (not imported from BUILTIN_EMAIL_TOOLS) so dropping a name
    # from the constant fails here instead of silently shrinking the toggle.
    bare_email_tools = (
        "list_email_accounts", "list_emails", "read_email", "search_emails",
        "scan_email_unsubscribes", "unsubscribe_email",
        "send_email", "reply_to_email", "draft_email", "draft_email_reply",
        "ai_draft_email_reply", "archive_email", "delete_email",
        "mark_email_read", "bulk_email", "download_attachment",
    )
    for tool_name in bare_email_tools:
        assert tool_name in disabled, tool_name
        assert f"mcp__email__{tool_name}" in disabled, tool_name

    # enable_tool email must remove the full set again.
    result = await do_manage_settings(
        '{"action": "enable_tool", "tool": "email"}', owner="admin"
    )
    assert result["exit_code"] == 0
    assert store["disabled_tools"] == []


def _install_admin_auth_stub(monkeypatch):
    auth_mod = _install_core_auth_stub(monkeypatch)

    class FakeAdminAuth:
        is_configured = True

        def is_admin(self, username):
            return True

    monkeypatch.setattr(auth_mod, "AuthManager", lambda: FakeAdminAuth())


class _FakeMcpManager:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return {"output": "ok", "exit_code": 0}


@pytest.mark.asyncio
async def test_bare_email_dispatch_rejects_non_object_json_args(monkeypatch):
    """The fence parser accepts JSON arrays as inline args, but email tools
    take objects — a correctable error must come back instead of a silent
    empty-args call (same class as #3966)."""
    _install_admin_auth_stub(monkeypatch)
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    mcp = _FakeMcpManager()
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="bulk_email", content='["10", "11"]'),
        owner="admin-user",
    )
    assert result["exit_code"] == 1
    assert "JSON object" in result["error"]
    assert mcp.calls == [], "non-object args must never reach the MCP server"


@pytest.mark.asyncio
async def test_bare_email_dispatch_rejects_invalid_json_body(monkeypatch):
    """The classic tag/body form reaches execution unvalidated (only INLINE
    args are JSON-checked by the parser). A non-JSON-object body must return a
    correctable parse error — silently becoming {} args would read the DEFAULT
    mailbox instead of the one the model meant. Covers both the brace-looking
    `{account: "work"}` and the bare `account: work` shapes."""
    _install_admin_auth_stub(monkeypatch)
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    for bad_body in ('{account: "work"}', "account: work"):
        mcp = _FakeMcpManager()
        monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)
        desc, result = await _execute_without_run_context(
            execute_tool_block,
            SimpleNamespace(tool_type="list_emails", content=bad_body),
            owner="admin-user",
        )
        assert result["exit_code"] == 1, bad_body
        assert "not valid JSON" in result["error"], bad_body
        assert mcp.calls == [], f"malformed args must never reach MCP: {bad_body!r}"


@pytest.mark.asyncio
async def test_legacy_mcp_tools_decode_inline_json_args(monkeypatch):
    """The relaxed parser accepts inline JSON for non-code tags, but the legacy
    line-based arg builders (web_search/web_fetch/read_file/write_file/
    generate_image) would wrap the whole JSON string as the query/path/prompt.
    A JSON object carrying the tool's primary key must be used directly."""
    import src.tool_execution as tool_execution
    from src.tool_execution import _build_mcp_args

    cases = {
        "web_search": ('{"query": "pantheon pr 3681"}', {"query": "pantheon pr 3681"}),
        "web_fetch": ('{"url": "https://example.com"}', {"url": "https://example.com"}),
        "read_file": ('{"path": "/tmp/x.txt"}', {"path": "/tmp/x.txt"}),
        "write_file": ('{"path": "/tmp/x", "content": "hi"}', {"path": "/tmp/x", "content": "hi"}),
        "generate_image": ('{"prompt": "a cat"}', {"prompt": "a cat"}),
    }
    for tool, (content, expected) in cases.items():
        assert _build_mcp_args(tool, content) == expected, tool

    # Freeform (non-JSON) content keeps the line-based behavior.
    assert _build_mcp_args("web_search", "latest python release") == {"query": "latest python release"}
    # A JSON object WITHOUT the tool's primary key is not args — fall back
    # (write_file content the model happened to write as a bare object).
    assert _build_mcp_args("write_file", '{"config": "value"}') == {
        "path": '{"config": "value"}', "content": "",
    }


def test_mcp_json_primary_keys_are_all_live():
    """Every _MCP_JSON_PRIMARY_KEYS entry must be reachable: _build_mcp_args is
    only called from _call_mcp_tool, which only runs for _MCP_TOOL_MAP tools.
    An entry outside _MCP_TOOL_MAP is dead code whose inline-JSON decode never
    executes — manage_memory was exactly that (it routes through
    dispatch_ai_tool), and a unit test on _build_mcp_args passed on the dead
    path while the real call still corrupted. This pins it so it can't recur."""
    from src.tool_execution import _MCP_JSON_PRIMARY_KEYS, _MCP_TOOL_MAP

    dead = set(_MCP_JSON_PRIMARY_KEYS) - set(_MCP_TOOL_MAP)
    assert not dead, f"dead JSON-primary entries (never reach _build_mcp_args): {sorted(dead)}"


@pytest.mark.asyncio
async def test_write_file_inline_json_args(monkeypatch):
    """write_file has no MCP server, so it runs via _direct_fallback ->
    WriteFileTool, NOT _build_mcp_args. Inline JSON must therefore be decoded
    by the handler itself: drive the LIVE path (execute_tool_block, no MCP) and
    assert the file is written to the intended path with the intended content,
    not a file literally named with the JSON blob. A _build_mcp_args unit test
    can't catch this — it's on the dead MCP path for write_file."""
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda t: False)
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: None)

    captured = {}
    import src.agent_tools.filesystem_tools as fst

    def fake_resolve(p):
        captured["path"] = p
        raise ValueError("probe-stop-before-disk")

    monkeypatch.setattr(tool_execution, "_resolve_tool_path", fake_resolve)

    from src.tool_parsing import parse_tool_blocks
    blocks = parse_tool_blocks('```write_file {"path": "/tmp/wf.txt", "content": "hi"}\n```')
    for b in blocks:
        await _execute_without_run_context(execute_tool_block, b, owner="admin")

    assert captured.get("path") == "/tmp/wf.txt", (
        f"write_file did not decode inline JSON args; got path {captured.get('path')!r}"
    )


@pytest.mark.asyncio
async def test_plan_mode_blocks_mutating_email_aliases_without_mcp_inventory(monkeypatch):
    """Plan-mode safety for bare email aliases must hold from the STATIC
    partition alone — no MCP read-only inventory involved: mutators (the
    draft/download tools included) are blocked before dispatch, while the
    explicitly read-only search_emails goes through."""
    _install_admin_auth_stub(monkeypatch)
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block
    from src.tool_security import plan_mode_disabled_tools

    mcp = _FakeMcpManager()
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)
    denied = plan_mode_disabled_tools()

    for tool_name in ("draft_email", "draft_email_reply", "ai_draft_email_reply",
                      "download_attachment", "send_email", "delete_email", "unsubscribe_email"):
        desc, result = await _execute_without_run_context(
            execute_tool_block,
            SimpleNamespace(tool_type=tool_name, content="{}"),
            owner="admin-user",
            disabled_tools=denied,
        )
        assert result["exit_code"] == 1, tool_name
        assert mcp.calls == [], f"{tool_name} reached the MCP server in plan mode"

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="search_emails", content='{"query": "x"}'),
        owner="admin-user",
        disabled_tools=denied,
    )
    assert result["exit_code"] == 0
    assert mcp.calls == [
        ("mcp__email__search_emails", {"query": "x", "_pantheon_owner": "admin-user"}),
    ]

    mcp.calls.clear()
    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="scan_email_unsubscribes", content='{"limit": 1}'),
        owner="admin-user",
        disabled_tools=denied,
    )
    assert result["exit_code"] == 0
    assert mcp.calls == [
        ("mcp__email__scan_email_unsubscribes", {"limit": 1, "_pantheon_owner": "admin-user"}),
    ]


@pytest.mark.asyncio
async def test_bare_email_dispatch_empty_content_calls_with_empty_args(monkeypatch):
    """An empty fence (```list_email_accounts``` with no body) dispatches with
    {} args — the no-arg call shape local models really emit."""
    _install_admin_auth_stub(monkeypatch)
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    mcp = _FakeMcpManager()
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="list_email_accounts", content=""),
        owner="admin-user",
    )
    assert result["exit_code"] == 0
    assert mcp.calls == [
        ("mcp__email__list_email_accounts", {"_pantheon_owner": "admin-user"}),
    ]


@pytest.mark.asyncio
async def test_email_mcp_non_object_args_fail_before_dispatch(monkeypatch):
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    class FakeMcp:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, args):
            self.calls.append((name, args))
            return {"output": "called", "exit_code": 0}

    fake = FakeMcp()
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: fake)

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="mcp__email__list_emails", content='["INBOX"]'),
        owner="alice",
    )

    assert desc == "mcp: mcp__email__list_emails"
    assert result["exit_code"] == 1
    assert "JSON object" in result["error"]
    assert fake.calls == []


@pytest.mark.asyncio
async def test_email_mcp_dispatch_includes_hidden_owner(monkeypatch):
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    class FakeMcp:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, args):
            self.calls.append((name, args))
            return {"output": "called", "exit_code": 0}

    fake = FakeMcp()
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: fake)

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="mcp__email__list_emails", content='{"folder":"INBOX"}'),
        owner="alice",
    )

    assert desc == "mcp: mcp__email__list_emails"
    assert result["exit_code"] == 0
    assert fake.calls == [
        ("mcp__email__list_emails", {"folder": "INBOX", "_pantheon_owner": "alice"}),
    ]


@pytest.mark.asyncio
async def test_bare_email_mcp_dispatch_includes_hidden_owner(monkeypatch):
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    fake = _FakeMcpManager()
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: fake)

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="list_emails", content='{"folder":"INBOX"}'),
        owner="alice",
    )

    assert desc == "email: list_emails"
    assert result["exit_code"] == 0
    assert fake.calls == [
        ("mcp__email__list_emails", {"folder": "INBOX", "_pantheon_owner": "alice"}),
    ]


def test_public_agent_policy_hides_sensitive_tools(monkeypatch):
    auth_mod = _install_core_auth_stub(monkeypatch)
    from src.tool_security import blocked_tools_for_owner

    class FakeAuth:
        is_configured = True

        def is_admin(self, username):
            return False

    monkeypatch.setattr(auth_mod, "AuthManager", lambda: FakeAuth())

    blocked = blocked_tools_for_owner("regular-user")

    assert "send_email" in blocked
    assert "read_file" in blocked
    assert "app_api" in blocked
    assert "serve_preset" in blocked
    assert "manage_tasks" in blocked


def test_presetup_does_not_grant_admin_tools_when_auth_enabled(monkeypatch):
    """Pre-setup window: auth is enabled but no admin user exists yet.

    This must NOT be treated as single-user/admin at the tool layer — the
    server-execution tools (bash/python) stay blocked as defense-in-depth so
    an unauthenticated caller that slips past the auth middleware (e.g. via a
    loopback bypass) can't reach an RCE before setup completes.
    """
    monkeypatch.delenv("AUTH_ENABLED", raising=False)  # default: enabled
    auth_mod = _install_core_auth_stub(monkeypatch)

    class FakeAuth:
        is_configured = False

        def is_admin(self, username):
            return False

    monkeypatch.setattr(auth_mod, "AuthManager", lambda: FakeAuth())

    from src.tool_security import (
        blocked_tools_for_owner,
        owner_is_admin_or_single_user,
    )

    assert owner_is_admin_or_single_user(None) is False
    blocked = blocked_tools_for_owner(None)
    assert "bash" in blocked
    assert "python" in blocked


def test_single_user_mode_keeps_full_tool_access_when_auth_disabled(monkeypatch):
    """Intentional single-user mode (AUTH_ENABLED=false) keeps full tool
    access even with no admin user — this is the default local/self-host UX
    and must not regress."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    auth_mod = _install_core_auth_stub(monkeypatch)

    class FakeAuth:
        is_configured = False

        def is_admin(self, username):
            return False

    monkeypatch.setattr(auth_mod, "AuthManager", lambda: FakeAuth())

    from src.tool_security import (
        blocked_tools_for_owner,
        owner_is_admin_or_single_user,
    )

    assert owner_is_admin_or_single_user(None) is True
    assert blocked_tools_for_owner(None) == set()


def test_auth_disabled_configured_mode_keeps_full_tool_access(monkeypatch):
    """AUTH_ENABLED=false is still intentional single-user mode after setup.

    Once an admin account exists, AuthManager.is_configured becomes true. The
    tool gate must still honor explicit auth-disabled mode before requiring an
    owner/admin match, otherwise agent mode hides email/MCP/local tools from the
    operator.
    """
    monkeypatch.setenv("AUTH_ENABLED", "false")
    auth_mod = _install_core_auth_stub(monkeypatch)

    class FakeAuth:
        is_configured = True

        def is_admin(self, username):
            return False

    monkeypatch.setattr(auth_mod, "AuthManager", lambda: FakeAuth())

    from src.tool_security import (
        blocked_tools_for_owner,
        owner_is_admin_or_single_user,
    )

    assert owner_is_admin_or_single_user(None) is True
    assert blocked_tools_for_owner(None) == set()


@pytest.mark.asyncio
async def test_webhook_tool_reuses_private_url_validation():
    class FakeDb:
        def close(self):
            pass

    fake_core_db = types.ModuleType("core.database")
    fake_core_db.SessionLocal = lambda: FakeDb()
    fake_core_db.Webhook = object
    fake_src_db = types.ModuleType("src.database")
    fake_src_db.SessionLocal = fake_core_db.SessionLocal
    fake_src_db.Webhook = object
    # Importing do_manage_webhooks below re-executes src.webhook_manager bound to
    # the faked src.database, whose Webhook is plain `object`. Save BOTH the
    # sys.modules entry AND the parent-package attribute (src.webhook_manager) so
    # the real module can be restored afterwards. Without this the polluted
    # module leaks into the cache and breaks sibling tests that call
    # WebhookManager._deliver (which evaluates `Webhook.id == webhook_id`).
    _ABSENT = object()
    _wm_saved_module = sys.modules.get("src.webhook_manager", _ABSENT)
    _src_pkg = sys.modules.get("src")
    _wm_saved_attr = (
        getattr(_src_pkg, "webhook_manager", _ABSENT) if _src_pkg is not None else _ABSENT
    )

    # Drop both bindings so the import re-executes against the fake src.database,
    # still exercising the intended import path.
    sys.modules.pop("src.webhook_manager", None)
    if _src_pkg is not None and hasattr(_src_pkg, "webhook_manager"):
        delattr(_src_pkg, "webhook_manager")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setitem(sys.modules, "core.database", fake_core_db)
    monkeypatch.setitem(sys.modules, "src.database", fake_src_db)

    from src.agent_tools.admin_tools import do_manage_webhooks

    try:
        result = await do_manage_webhooks(
            '{"action":"add","url":"http://127.0.0.1:8000/hook","events":"chat.completed"}',
            owner="admin",
        )
    finally:
        monkeypatch.undo()
        # Restore src.webhook_manager to its exact pre-test state at BOTH the
        # sys.modules and parent-package attribute level.
        if _wm_saved_module is _ABSENT:
            sys.modules.pop("src.webhook_manager", None)
        else:
            sys.modules["src.webhook_manager"] = _wm_saved_module
        if _src_pkg is not None:
            if _wm_saved_attr is _ABSENT:
                if hasattr(_src_pkg, "webhook_manager"):
                    delattr(_src_pkg, "webhook_manager")
            else:
                setattr(_src_pkg, "webhook_manager", _wm_saved_attr)

    assert result["exit_code"] == 1
    assert "private/internal" in result["error"]


def test_default_chat_skips_hidden_first_model(monkeypatch):
    """get_default_chat picks first visible model when default_model is empty
    and the first cached model is hidden."""
    _install_model_route_import_stubs(monkeypatch)
    import routes.model_routes as model_routes
    import routes.prefs_routes as prefs_routes

    ep = SimpleNamespace(
        id="ep1",
        base_url="http://localhost:11434",
        is_enabled=True,
        owner="fresh",
        cached_models='["hidden-model", "visible-model"]',
        hidden_models='["hidden-model"]',
    )

    monkeypatch.setattr(model_routes, "ModelEndpoint", _FakeModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: _FakeDb([ep]))
    monkeypatch.setattr(model_routes, "_load_settings", lambda: {})
    monkeypatch.setattr(model_routes, "owner_filter", lambda q, m, u, **kw: q)
    monkeypatch.setattr(model_routes, "_normalize_base", lambda base: base.rstrip("/"))
    monkeypatch.setattr(model_routes, "build_chat_url", lambda base: f"{base}/chat/completions")
    monkeypatch.setattr(prefs_routes, "_load_for_user", lambda user: {})

    request = SimpleNamespace(
        state=SimpleNamespace(current_user="fresh"),
        app=SimpleNamespace(state=SimpleNamespace(
            auth_manager=SimpleNamespace(is_admin=lambda user: False)
        )),
    )

    result = _default_chat_endpoint()(request)
    assert result["model"] == "visible-model", f"Expected visible-model, got {result['model']!r}"


def test_default_chat_admin_skips_hidden_first_model(monkeypatch):
    """Admin user with global defaults also skips hidden models in fallback."""
    _install_model_route_import_stubs(monkeypatch)
    import routes.model_routes as model_routes

    ep = SimpleNamespace(
        id="ep1",
        base_url="http://localhost:11434",
        is_enabled=True,
        owner=None,
        cached_models='["hidden-model", "visible-model"]',
        hidden_models='["hidden-model"]',
    )

    monkeypatch.setattr(model_routes, "ModelEndpoint", _FakeModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: _FakeDb([ep]))
    monkeypatch.setattr(model_routes, "_load_settings", lambda: {})
    monkeypatch.setattr(model_routes, "owner_filter", lambda q, m, u, **kw: q)
    monkeypatch.setattr(model_routes, "_normalize_base", lambda base: base.rstrip("/"))
    monkeypatch.setattr(model_routes, "build_chat_url", lambda base: f"{base}/chat/completions")

    request = SimpleNamespace(
        state=SimpleNamespace(current_user="admin"),
        app=SimpleNamespace(state=SimpleNamespace(
            auth_manager=SimpleNamespace(is_admin=lambda user: True)
        )),
    )

    result = _default_chat_endpoint()(request)
    assert result["model"] == "visible-model"


def test_default_chat_all_models_hidden_returns_empty_model(monkeypatch):
    """When all cached models are hidden, get_default_chat returns model: ''."""
    _install_model_route_import_stubs(monkeypatch)
    import routes.model_routes as model_routes

    ep = SimpleNamespace(
        id="ep1",
        base_url="http://localhost:11434",
        is_enabled=True,
        owner=None,
        cached_models='["hidden-a", "hidden-b"]',
        hidden_models='["hidden-a", "hidden-b"]',
    )

    monkeypatch.setattr(model_routes, "ModelEndpoint", _FakeModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: _FakeDb([ep]))
    monkeypatch.setattr(model_routes, "_load_settings", lambda: {})
    monkeypatch.setattr(model_routes, "owner_filter", lambda q, m, u, **kw: q)
    monkeypatch.setattr(model_routes, "_normalize_base", lambda base: base.rstrip("/"))
    monkeypatch.setattr(model_routes, "build_chat_url", lambda base: f"{base}/chat/completions")

    request = SimpleNamespace(
        state=SimpleNamespace(current_user="admin"),
        app=SimpleNamespace(state=SimpleNamespace(
            auth_manager=SimpleNamespace(is_admin=lambda user: True)
        )),
    )

    result = _default_chat_endpoint()(request)
    assert result["model"] == "", f"Expected empty model, got {result['model']!r}"


def test_visible_models_filters_hidden_first(monkeypatch):
    """_visible_models removes hidden models from the list."""
    from routes.model_routes import _visible_models

    result = _visible_models(
        '["hidden-model", "visible-model"]',
        '["hidden-model"]',
    )
    assert result == ["visible-model"]


def test_visible_models_all_hidden_returns_empty(monkeypatch):
    """_visible_models returns [] when all models are hidden."""
    from routes.model_routes import _visible_models

    result = _visible_models(
        '["hidden-a", "hidden-b"]',
        '["hidden-a", "hidden-b"]',
    )
    assert result == []


def test_visible_models_no_hidden_returns_all(monkeypatch):
    """_visible_models returns full list when no hidden_models."""
    from routes.model_routes import _visible_models

    result = _visible_models(
        '["model-a", "model-b"]',
        None,
    )
    assert result == ["model-a", "model-b"]


def test_visible_models_empty_cached_returns_empty(monkeypatch):
    """_visible_models returns [] for empty cached list."""
    from routes.model_routes import _visible_models

    result = _visible_models([], None)
    assert result == []


# ── `B202`: this file's own shared mutable state, and the two shapes it took ──


def test_a_core_submodule_no_stub_names_still_imports(monkeypatch):
    """The failure this row was filed for, reduced to one line.

    `_install_model_route_import_stubs` used to put a `core` package with
    `__path__ = []` in `sys.modules`, which makes every `core.*` module the
    stub list does not name unimportable. `routes/model_routes.py:21` imports
    `core.log_safety`, which is in no stub list, and on the tree before this
    change these three failed with `ModuleNotFoundError: No module named
    'core.log_safety'`:

        test_providers_requires_admin_before_discovery_and_cache
        test_default_chat_does_not_auto_pick_shared_endpoint_for_fresh_user
        test_default_chat_uses_owned_endpoint_as_regular_user_last_resort

    Naming `core.log_safety` in the stub list would have fixed those three and
    left the next `core.*` import to be found the same way (`Law 13`). This
    asserts the property instead: a module the stubs did not decide to replace
    is still the real one.
    """
    # Ask the import system, not the cache: `routes/chat_routes.py` imports
    # `core.log_safety` too, so by the time this runs in a full file it is
    # usually already in `sys.modules` and the empty `__path__` never gets a
    # vote. `monkeypatch` puts the original module object back afterwards; the
    # one imported here is a leaf of pure functions that nothing binds by value
    # during this test.
    drop_for_fresh_import(monkeypatch, "core.log_safety")
    _install_model_route_import_stubs(monkeypatch)

    log_safety = importlib.import_module("core.log_safety")

    assert getattr(log_safety, "__file__", None) is not None
    assert callable(log_safety.redact_url)
    # ...and what the stubs DID name is still stubbed, or they would not work.
    assert sys.modules["core.database"].ModelEndpoint is _FakeModelEndpoint


def test_no_stub_installer_hides_the_real_core_package(monkeypatch):
    """All three, because one fixed installer is not a fixed defect class.

    `_install_core_auth_stub` and `_install_core_middleware_stub` carried the
    identical `__path__ = []`. Neither has cost a failure yet — the modules
    their tests import happen not to reach an unstubbed `core.*` — which is
    exactly the argument for pinning the property rather than the symptom.
    """
    import core as real_core

    real_path = list(real_core.__path__)
    assert real_path, "the real core package has no __path__ — probe drift?"

    for install in (_install_model_route_import_stubs,
                    _install_core_auth_stub,
                    _install_core_middleware_stub):
        with pytest.MonkeyPatch.context() as mp:
            install(mp)
            stub = sys.modules["core"]
            assert stub is not real_core, f"{install.__name__} stopped stubbing core"
            assert list(stub.__path__) == real_path, (
                f"{install.__name__} installs a core package that contains "
                "nothing, so every core.* submodule it did not name is "
                "unimportable while it is in sys.modules"
            )


def test_the_import_helper_never_binds_a_mock_into_the_module_it_returns(
        monkeypatch, tmp_path):
    """`B18`'s shape, driven on a tree built for it.

    The mechanism is the one that poisoned `routes.chat_helpers`: a module that
    binds a name **by value** from a dependency, imported at the moment that
    dependency is a `MagicMock`. `monkeypatch` restores `sys.modules`; it does
    not restore a module object that was *created* while it was patched, and
    that object stays for the rest of the process.

    Driven here on two throwaway modules rather than on `routes.chat_helpers`,
    and the reason is the row itself. Popping the real module to re-import it
    means there are briefly two of it, and `import_module` rebinds the child on
    the parent package as well as in `sys.modules` —
    `monkeypatch.setattr("routes.chat_helpers.effective_user", …)` resolves its
    target by walking attributes from `routes`, so a test that restored only
    `sys.modules` would hand `tests/test_chat_helpers.py` a different module
    object from the one its `from routes.chat_helpers import
    _enforce_chat_privileges` is closed over, and its four privilege tests
    would fail with `DID NOT RAISE` while patching a module nobody reads. That
    was reproduced on the way to writing this — a test for `B202` that was
    itself an instance of `B202`. A synthetic pair has no such second reader.
    """
    (tmp_path / "_b202_dep.py").write_text("thing = 'the real one'\n", encoding="utf-8")
    (tmp_path / "_b202_target.py").write_text(
        "from _b202_dep import thing\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("_b202_dep", "_b202_target"):
        drop_for_fresh_import(monkeypatch, name)

    module = _import_without_mocks(monkeypatch, "_b202_target", ("_b202_dep",))

    assert module.thing == "the real one", (
        "the helper stubbed a dependency that imports perfectly well, and the "
        "module it returned has that mock baked in by value")
    assert not isinstance(module.thing, MagicMock)
    assert not isinstance(sys.modules["_b202_dep"], MagicMock)

    # The fallback still exists, and still does what it used to: a dependency
    # that genuinely cannot be imported is stood in for rather than fatal
    # (`Law 1` — the old behaviour is the floor, not the normal path).
    (tmp_path / "_b202_broken.py").write_text(
        "from _b202_missing import nothing\n", encoding="utf-8")
    for name in ("_b202_broken", "_b202_missing"):
        drop_for_fresh_import(monkeypatch, name)

    broken = _import_without_mocks(monkeypatch, "_b202_broken", ("_b202_missing",))

    assert isinstance(broken.nothing, MagicMock)


def test_the_chat_privilege_gate_still_reads_the_real_effective_user():
    """The consequence, asserted where it lands.

    `tests/test_chat_helpers.py` has four tests that assert
    `_enforce_chat_privileges` raises `HTTPException` — and it returns early
    when `effective_user(request)` is falsy or raises. With a `MagicMock` in
    that slot the gate is being measured against a stand-in that answers
    truthily to anything, so the four either fail with `DID NOT RAISE` or pass
    for the wrong reason depending on which module object each side is holding.

    This runs last in file order, after the three tests that import
    `routes.chat_helpers`, and it is the assertion that whatever they did to
    `sys.modules` did not survive them.
    """
    import src.auth_helpers
    import routes.chat_helpers as chat_helpers

    assert chat_helpers.effective_user is src.auth_helpers.effective_user
    for name in ("maybe_compact", "trim_for_context", "load_prefs_for_user"):
        assert not isinstance(getattr(chat_helpers, name), MagicMock), name
