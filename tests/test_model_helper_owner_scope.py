# SPDX-License-Identifier: AGPL-3.0-or-later
"""Model-assisted route helpers must resolve endpoints with owner scope."""

import ast
from pathlib import Path


def _function_source(path: str, name: str) -> str:
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{name} not found in {path}")


def test_document_ai_tidy_resolves_with_owner_scope():
    body = _function_source("routes/document/document_routes.py", "ai_tidy_documents")
    assert "resolve_task_endpoint(owner=user or None)" in body
    assert 'resolve_endpoint("default", owner=user or None)' in body


def test_calendar_quick_parse_resolves_with_owner_scope():
    body = _function_source("routes/calendar_routes.py", "quick_parse")
    assert "owner = _require_user(request)" in body
    assert 'resolve_endpoint("utility", owner=owner or None)' in body
    assert 'resolve_endpoint("default", owner=owner or None)' in body


def test_task_parse_resolves_with_owner_scope(monkeypatch):
    """`P22-19` (wb-assist) re-pointed `parse_task`'s model call to
    `workflow_assist.ask_for_json`, which the drafter and the example writer
    ask too, so the resolution moved out of this function's body. Driven
    rather than read (`Law 20`): the real route, the caller named, and every
    `resolve_endpoint` it makes recorded — utility first, then default, each
    with the caller as owner."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.task.task_routes as task_routes
    import src.endpoint_resolver as er
    import src.llm_core as llm_core

    asked = []

    def resolve(prefix, *args, owner=None, **kw):
        asked.append((prefix, owner))
        return (None, None, None) if prefix == "utility" else ("http://m", "m-1", {})

    async def call(**kw):
        return '{"prompt": "Research the AI news", "schedule": "daily"}'

    monkeypatch.setattr(er, "resolve_endpoint", resolve)
    monkeypatch.setattr(llm_core, "llm_call_async", call)
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = "alice"
        return await call_next(request)

    app.include_router(task_routes.setup_task_routes(None))
    res = TestClient(app).post("/api/tasks/parse", json={"description": "daily AI news"})
    assert res.json()["success"] is True, res.text
    assert asked == [("utility", "alice"), ("default", "alice")]


def test_history_compact_resolves_with_owner_scope():
    body = _function_source("routes/history/history_routes.py", "compact_session")
    assert "owner = effective_user(request)" in body
    assert 'resolve_endpoint("utility", owner=owner or None)' in body


def test_note_reminder_synthesis_resolves_with_owner_scope():
    body = _function_source("routes/note/note_routes.py", "dispatch_reminder")
    assert 'resolve_endpoint("utility", owner=owner or None)' in body
    assert 'resolve_endpoint("default", owner=owner or None)' in body
