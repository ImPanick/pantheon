# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-04` — CHAT-M-4 and PERF-M-14: the context wheel says the window the
agent actually uses, and asking costs one read of the endpoint table.

**What was wrong** (measured on `9560d50`, re-measured on this branch's base):

  * **CHAT-M-4.** On an endpoint that reports no window (the showcase's
    `scripted-demo`; Ollama, LM Studio, llama.cpp without `/slots`), the agent
    loop trims every request to 6,000 tokens — the reviewed floor (#4122,
    tracker H18) — while `GET /api/session/{id}/context` used the 128K fallback:
    the wheel said "12% full, ~14.9K / 128K, Free space 113K" over a run whose
    log said `Trimming messages: 5002 tokens > 4976 budget (ctx=6000)`.
  * **PERF-M-14.** That route ran 11 statements per call on a warm chat, six of
    them `SELECT … FROM model_endpoints` (one context-length lookup asked the
    table through `_configured_endpoint_kind` ×4 and `_endpoint_auth_headers`
    ×2), and it runs on every chat open. After: one. The session reads left
    are `core/session_manager.get_session`'s (fx-ops' file) — filed.

**What is pinned.** `agent_input_budget` is the one computation the loop trims
to and the route reports; the route, driven over HTTP in Agent mode, reports
that budget as the window and the percentage against it; one context-length
lookup reads the endpoint table once; the wheel draws `window_tokens` and says
in one line why it is smaller than the model's window.
"""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.model_context as model_context
from src.chat_handler import ChatMessage
from src.context_budget import DEFAULT_BUDGET, agent_input_budget
from test_tool_effect_surfaces_js import _make_sandbox, _run

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"


def _settings(values=None):
    values = values or {}
    return lambda key, default=None: values.get(key, default)


def test_the_agent_budget_is_the_floor_when_the_window_is_unknown():
    assert agent_input_budget(0, _settings()) == DEFAULT_BUDGET == 6000
    assert agent_input_budget(128_000, _settings()) == int(128_000 * 0.85)
    assert agent_input_budget(0, _settings({"agent_input_token_budget": 0})) == 0
    assert agent_input_budget(128_000, _settings({"agent_input_token_budget": 9000})) == 9000


# ── the route ───────────────────────────────────────────────────────────────

class _Session:
    id = "s-1"
    endpoint_url = "http://127.0.0.1:47111/v1"
    model = "scripted-demo"

    def __init__(self, history):
        self.history = history

    def get_context_messages(self):
        return [m.to_dict() for m in self.history]


class _Manager:
    def __init__(self, session):
        self.session = session

    def get_session(self, session_id):
        return self.session


def _context(monkeypatch, *, mode, window=(128_000, False)):
    import routes.history_routes as history_routes
    import src.settings as settings
    monkeypatch.setattr(history_routes, "_verify_session_owner", lambda request, sid: None)
    monkeypatch.setattr(model_context, "get_context_length_known", lambda url, model: window)
    monkeypatch.setattr(settings, "get_setting", lambda key, default=None: default)
    app = FastAPI()
    history = [ChatMessage("user", "word " * 1200), ChatMessage("assistant", "ok")]
    app.include_router(history_routes.setup_history_routes(_Manager(_Session(history))))
    res = TestClient(app).get(f"/api/session/s-1/context?mode={mode}")
    assert res.status_code == 200, res.text
    return res.json()


def test_an_agent_chat_on_an_unknown_window_reports_the_6k_it_keeps(monkeypatch):
    out = _context(monkeypatch, mode="agent")
    assert out["context_length"] == 128_000          # the model's (fallback) window, kept
    assert out["window_known"] is False
    assert out["agent_budget"] == 6000 and out["window_tokens"] == 6000
    assert out["context_percent"] == round(out["used_tokens"] / 6000 * 100, 1)
    assert out["breakdown"]["context_percent"] == min(
        100.0, round(out["breakdown"]["used_tokens"] / 6000 * 100, 1))


def test_a_proven_window_is_held_to_the_loops_headroom(monkeypatch):
    out = _context(monkeypatch, mode="agent", window=(32_768, True))
    assert out["window_tokens"] == int(32_768 * 0.85)


def test_chat_mode_is_the_models_window(monkeypatch):
    out = _context(monkeypatch, mode="chat")
    assert out["agent_budget"] == 0 and out["window_tokens"] == 128_000


# ── PERF-M-14: one read of the endpoint table per lookup ────────────────────

def test_one_context_length_lookup_reads_the_endpoint_table_once(monkeypatch):
    import core.database as database
    reads = []
    row = SimpleNamespace(base_url="http://127.0.0.1:47111/v1", endpoint_kind="local",
                          api_key=None, owner=None, is_enabled=True)

    class _Query:
        def filter(self, *a, **k):
            return self

        def all(self):
            reads.append(1)
            return [row]

    class _Db:
        def query(self, *a, **k):
            return _Query()

        def close(self):
            pass

    monkeypatch.setattr(database, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(model_context.httpx, "get", lambda *a, **k: SimpleNamespace(is_success=False))
    model_context._context_cache.clear()
    ctx, known = model_context.get_context_length_known("http://127.0.0.1:47111/v1", "scripted-demo")
    assert (ctx, known) == (model_context.DEFAULT_CONTEXT, False)
    assert len(reads) == 1, f"the endpoint table was read {len(reads)} times for one lookup"
    # Outside a lookup every helper still reads for itself, as it always did.
    reads.clear()
    model_context.is_local_endpoint("http://127.0.0.1:47111/v1")
    model_context._configured_endpoint_kind("http://127.0.0.1:47111/v1")
    assert len(reads) == 2


# ── the wheel ───────────────────────────────────────────────────────────────

_SHIM = "import { installDom } from './dom.js';\nexport const document = installDom();\n"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("wheelwindow"), JS / "contextUsage.js", _SHIM, {})


def test_the_wheel_draws_the_agents_window_and_says_why(sandbox):
    payload = {"context_length": 128000, "window_tokens": 6000, "window_known": False, "mode": "agent",
               "agent_budget": 6000, "used_tokens": 3000, "context_percent": 50,
               "breakdown": {"used_tokens": 3000, "context_percent": 50, "categories": [], "source": "last_request"}}
    known = dict(payload, window_known=True, window_tokens=108800, agent_budget=108800, context_percent=2.8,
                 breakdown=dict(payload["breakdown"], context_percent=2.8))
    out = _run(sandbox, "import { document } from './shim.js';\nconst cu = await import('./contextUsage.js');\n", """
        const a = %s, b = %s;
        const pill = document.createElement('button');
        cu.renderPill(pill, a);
        const panel = cu.buildUsagePanel(document, a);
        const text = (n) => (n.textContent || '') + n.childNodes.map(text).join(' ');
        console.log(JSON.stringify({ total: cu.usageFigures(a).total, title: pill.title,
          note: cu.budgetNote(a), knownNote: cu.budgetNote(b), chatNote: cu.budgetNote(Object.assign({}, a, { mode: 'chat' })),
          panel: text(panel) }));
    """ % (json.dumps(payload), json.dumps(known)))
    assert out["total"] == 6000
    assert "of 6K tokens" in out["title"]
    assert out["note"] == "The model's window is unknown, so the agent keeps 6K."
    assert out["knownNote"] == "The agent keeps 109K of the model's 128K."
    assert out["chatNote"] == ""
    assert "The model's window is unknown, so the agent keeps 6K." in out["panel"]
    assert "Estimated from the last reply." in out["panel"]
