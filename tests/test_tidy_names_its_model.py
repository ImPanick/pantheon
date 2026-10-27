# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-09`, the tidy half — a tidy result names the model that produced it.

Provenance on everything a model produced: memories, skills, images, research
reports and calendar parses carried it; the two tidies did not.
`POST /api/sessions/auto-sort` filed chats into folders a model chose and
answered `{status, folders, updated, deleted_empty, deleted_throwaway,
unfiled_remaining}` with the model a local of the same handler (it logs
`using model=…`); `POST /api/memory/audit` had a model rewrite and merge the
person's memories and answered `{ok, before, after, removed, …}` with the model
in scope too. So the toast said *"Filed 5 into 2 folders"* and *"Tidied: 3
removed"* and never which model had done it.

Now both answers carry `model`, and `describeChatTidy` / `describeMemoryTidy`
— the one place each tidy's sentence is written — say it. Only where a model
was asked: the cleanup-only chat tidy, an unchanged memory set and an empty
one name nobody.

Driven (`Law 20`): the real auto-sort handler over a real SQLite file with its
model call answered by a stand-in; the real audit handler with the audit pass
answered by a stand-in in each of its result shapes; the real describers,
sliced out of the modules and run in node.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import ChatMessage as DbMessage
from core.database import Session as DbSession
from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
CHATS = {"ann-0001-aaaa": "Sourdough starter", "ann-0002-bbbb": "Rye loaf",
         "ann-0003-cccc": "Bike gears"}


# ── the chat tidy, through its route ───────────────────────────────────────

@pytest.fixture()
def tidy_app(monkeypatch, tmp_path):
    import core.session_manager as smod
    import routes.session_routes as session_routes
    import src.llm_core as llm_core
    import src.task_endpoint as task_endpoint

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (smod, session_routes, cdb):
        monkeypatch.setattr(mod, "SessionLocal", factory)
    db = factory()
    t = datetime(2026, 1, 1)
    for sid, name in CHATS.items():
        db.add(DbSession(id=sid, owner="ann", name=name, endpoint_url="x", model="m",
                         created_at=t, updated_at=t, last_accessed=t, last_message_at=t))
        for i in range(4):
            db.add(DbMessage(id=f"{sid}-{i}", session_id=sid,
                             role="user" if i % 2 == 0 else "assistant",
                             content=f"{name} {i}", timestamp=t))
    db.commit()
    db.close()

    def answer(url, model, messages, **_kw):
        return json.dumps({"folders": {"Baking": ["ann-0001", "ann-0002"],
                                       "Bikes": ["ann-0003"]}})

    monkeypatch.setattr(session_routes, "effective_user", lambda request: "ann")
    monkeypatch.setattr(task_endpoint, "resolve_task_endpoint",
                        lambda *a, **k: ("http://u/v1", "qwen3-utility-8b", {}))
    monkeypatch.setattr(llm_core, "llm_call", answer)
    app = FastAPI()
    app.include_router(session_routes.setup_session_routes(smod.SessionManager(), {}))
    return TestClient(app)


def test_the_chat_tidy_names_the_model_that_chose_the_folders(tidy_app):
    res = tidy_app.post("/api/sessions/auto-sort")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok" and body["updated"] == 3
    assert body["model"] == "qwen3-utility-8b"


def test_the_cleanup_only_tidy_names_no_model(tidy_app):
    # No model was asked, so naming one would be a guess.
    body = tidy_app.post("/api/sessions/auto-sort?skip_llm=true").json()
    assert body["status"] == "ok" and "model" not in body


# ── the memory tidy, through its route ──────────────────────────────────────

def _audit_route(monkeypatch, result: dict):
    import routes.memory_routes as mr

    async def fake_audit(*_a, **_kw):
        return dict(result)

    monkeypatch.setattr(mr, "resolve_task_endpoint",
                        lambda *a, **k: ("http://u/v1", "qwen3-utility-8b", {}))
    monkeypatch.setattr(mr, "audit_memories", fake_audit)
    router = mr.setup_memory_routes(MagicMock(), MagicMock(), MagicMock())
    for r in router.routes:
        if r.path == "/api/memory/audit" and "POST" in r.methods:
            request = SimpleNamespace(state=SimpleNamespace(current_user="ann"),
                                      app=SimpleNamespace(state=SimpleNamespace(auth_manager=None)))
            return asyncio.run(r.endpoint(request=request, session=None))
    raise AssertionError("no /api/memory/audit")


def test_the_memory_tidy_names_the_model_that_rewrote_them(monkeypatch):
    out = _audit_route(monkeypatch, {"before": 12, "after": 9, "superseded": 2})
    assert out["model"] == "qwen3-utility-8b"


@pytest.mark.parametrize("result, why", [
    ({"before": 12, "after": 12, "already_tidy": True, "archived": 0},
     "the set was unchanged since the last tidy, so the model was skipped"),
    ({"before": 0, "after": 0, "archived": 0}, "there was nothing to audit"),
])
def test_a_memory_tidy_that_asked_no_model_names_none(monkeypatch, result, why):
    assert _audit_route(monkeypatch, result)["model"] is None, why


# ── the two sentences ───────────────────────────────────────────────────────

pytestmark_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _describe(tmp_path, module: str, signature: str, name: str, cases: dict) -> dict:
    src = (ROOT / "static" / "js" / module).read_text(encoding="utf-8")
    body = js_function(src, signature)
    script = (f"function {name}(data) {body}\n"
              f"const cases = {json.dumps(cases)};\n"
              "const out = {}; for (const [k, v] of Object.entries(cases)) out[k] = "
              f"{name}(v);\nconsole.log(JSON.stringify(out));\n")
    case = tmp_path / "case.mjs"
    case.write_text(script)
    proc = subprocess.run(["node", str(case)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytestmark_node
def test_the_chat_tidy_sentence_names_the_model(tmp_path):
    out = _describe(tmp_path, "sessions.js", "export function describeChatTidy(",
                    "describeChatTidy", {
                        "named": {"status": "ok", "updated": 3, "folders": ["a", "b"],
                                  "deleted_empty": 1, "unfiled_remaining": 0,
                                  "model": "qwen3-utility-8b"},
                        "unnamed": {"status": "ok", "updated": 3, "folders": ["a"],
                                    "unfiled_remaining": 0},
                        "deletedOnly": {"status": "ok", "updated": 0, "folders": [],
                                        "deleted_throwaway": 2, "unfiled_remaining": 0,
                                        "model": "qwen3-utility-8b"},
                    })
    assert out["named"] == "Deleted 1 chat, filed 3 into 2 folders chosen by qwen3-utility-8b"
    assert out["unnamed"] == "Filed 3 into 1 folder"
    # The deletions are the route's own rules; the model filed nothing.
    assert "qwen3" not in out["deletedOnly"]


@pytestmark_node
def test_the_memory_tidy_sentence_names_the_model(tmp_path):
    out = _describe(tmp_path, "memory.js", "export function describeMemoryTidy(",
                    "describeMemoryTidy", {
                        "named": {"removed": 3, "before": 12, "after": 9,
                                  "model": "qwen3-utility-8b"},
                        "unnamed": {"removed": 3, "before": 12, "after": 9, "model": None},
                    })
    assert out["named"].startswith("Tidied by qwen3-utility-8b: 3 removed (12 → 9)")
    assert out["unnamed"].startswith("Tidied: 3 removed (12 → 9)")
