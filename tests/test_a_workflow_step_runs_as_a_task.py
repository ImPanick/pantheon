# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-05` — a workflow step runs through the executors that exist, as a
stand-in that carries exactly the task fields they read, and no others.

The walker does not write a fourth executor (`Law 14`): a Prompt, Research or
Action step is handed to `_execute_llm_task`, `_execute_research_task` or
`_execute_action` as a `WorkflowNodeTask` — a class with `__slots__ =
STAND_IN_FIELDS`, so reading any other attribute raises instead of quietly
answering `None`, as a namespace would. Whether that is ENOUGH is a fact about
those functions, so it is proved twice (`SLICE-B-DESIGN` § 2.2):

  1. **Driven** (`Law 20`, option 1): each executor and deliverer is called
     with a real stand-in, its I/O stubbed at the edge (the model, SMTP, MCP,
     the research pipeline), on a real SQLite file. No `AttributeError`.
  2. **Scope-resolved AST** (option 2): every `task.<attr>` and
     `getattr(task, "<literal>")` inside each of those functions — resolved by
     function, never by grepping the file — is in `STAND_IN_FIELDS`.

Removing a field from the tuple reddens both (the mutation evidence is in the
handoff note).
"""

import ast
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.task_scheduler as ts  # noqa: E402
from core.database import ChatMessage, ScheduledTask  # noqa: E402
from src import workflow_document as wd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# The functions a stand-in reaches, and the name it has inside each.
SCHEDULER_READERS = {
    "_execute_action": "task", "_execute_llm_task": "task", "_execute_checkin": "task",
    "_run_agent_loop": "task", "_execute_research_task": "task",
    "_deliver_task_result": "task", "_deliver_via_email": "task", "_deliver_via_mcp": "task",
    "_deliver_node_result": "stand_in", "_keep_workflow_chat": "stand_in",
}
MODULE_READERS = {("src/task_scheduler.py", "_resolve_task_timezone"): "task",
                  ("core/session_manager.py", "ensure_task_session"): "task",
                  # `B1114`: the name of the chat `_execute_llm_task` and
                  # `_deliver_task_result` make, read off the stand-in.
                  ("src/task_scheduler.py", "task_chat_name"): "task"}


def _reads(fn: ast.AST, name: str) -> set:
    found = set()
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) \
                and sub.value.id == name:
            found.add(sub.attr)
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                and sub.func.id in ("getattr", "setattr", "hasattr") and len(sub.args) >= 2
                and isinstance(sub.args[0], ast.Name) and sub.args[0].id == name
                and isinstance(sub.args[1], ast.Constant)):
            found.add(sub.args[1].value)
    return found


def _functions(rel: str) -> dict:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_every_field_an_executor_reads_is_a_stand_in_field():
    sched = _functions("src/task_scheduler.py")
    seen = {}
    for name, param in SCHEDULER_READERS.items():
        assert name in sched, f"{name} moved; re-read what the walker calls"
        seen[name] = _reads(sched[name], param)
    for (rel, name), param in MODULE_READERS.items():
        seen[f"{rel}:{name}"] = _reads(_functions(rel)[name], param)
    extra = {where: attrs - set(wd.STAND_IN_FIELDS) for where, attrs in seen.items()}
    assert not any(extra.values()), {k: v for k, v in extra.items() if v}
    # And the measurement is not vacuous: together they read every field.
    assert set().union(*seen.values()) >= set(wd.STAND_IN_FIELDS) - {"tz_name"} | {"session_id"}
    assert "tz_name" in seen["src/task_scheduler.py:_resolve_task_timezone"]


# ── driven ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    engine = create_engine(f"sqlite:///{tmp_path / 'stand.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    import src.tool_index as tool_index
    monkeypatch.setattr(tool_index, "get_tool_index", lambda: None)
    # Wave D's C-R / C-E halves are the real ones (`integrate-d`): this fails
    # naming a missing half and stands nothing in.
    from tests.helpers import workflow_contract
    workflow_contract.install(monkeypatch)
    db = factory()
    db.add(ScheduledTask(id="wf", owner="alice", name="Morning", task_type="workflow",
                         tz_name="Europe/London"))
    db.commit()
    yield db
    db.close()


def _stand_in(db, kind="llm", **config):
    trigger = db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first()
    if kind != "action":
        config.setdefault("model", "m")
        config.setdefault("endpoint_url", "http://127.0.0.1:9/v1")
        config.setdefault("prompt", "Summarise my inbox.")
    return wd.node_stand_in(trigger, "Morning", {"id": "n1", "kind": kind, "label": "Step",
                                                "config": config})


@pytest.mark.asyncio
async def test_an_action_step_runs_through_the_action_executor(task_db, monkeypatch):
    from src import builtin_actions

    got = {}

    async def run_local(owner, **kwargs):
        got.update(owner=owner, **kwargs)
        return "ran", True
    monkeypatch.setitem(builtin_actions.BUILTIN_ACTIONS, "run_local", run_local)
    s = ts.TaskScheduler(None)
    out = await s._execute_action(_stand_in(task_db, "action", action="run_local", prompt="ls -l"),
                                  run_id="r:n1")
    assert out.ok and out.text == "ran"
    assert (got["owner"], got["task_name"], got["script"]) == ("alice", "Morning · Step", "ls -l")


@pytest.mark.asyncio
async def test_a_prompt_step_runs_through_the_prompt_executor(task_db):
    s = ts.TaskScheduler(None)
    seen = {}

    async def agent_loop(endpoint_url, model, task, session_id, **kw):
        seen.update(name=task.name, steps=task.max_steps, session=session_id)
        return "Three bills."
    s._run_agent_loop = agent_loop
    stand_in = _stand_in(task_db, character_id="socrates", max_steps=4)
    assert await s._execute_llm_task(stand_in, task_db, run_id="r:n1") == "Three bills."
    assert seen["name"] == "Morning · Step" and seen["steps"] == 4
    assert stand_in.session_id == seen["session"], "the chat it made is on the stand-in"
    assert s.run_model("r:n1") == "m"
    assert ts._resolve_task_timezone(task_db, stand_in) == "Europe/London"


@pytest.mark.asyncio
async def test_a_research_step_runs_through_the_research_executor(task_db, monkeypatch, tmp_path):
    import src.deep_research as deep_research
    import src.research_handler as research_handler

    class Researcher:
        def __init__(self, **kw):
            self.findings = []

        async def research(self, question):
            return f"Report on {question}"

        def get_stats(self):
            return {}
    monkeypatch.setattr(deep_research, "DeepResearcher", Researcher)
    monkeypatch.setattr(research_handler, "RESEARCH_DATA_DIR", tmp_path / "research")
    import src.event_bus as event_bus
    monkeypatch.setattr(event_bus, "fire_event", lambda *a, **k: None)
    s = ts.TaskScheduler(None)
    stand_in = _stand_in(task_db, "research", prompt="What changed?")
    assert stand_in.session_id is None
    out = await s._execute_research_task(stand_in, task_db, run_id="r:n1")
    assert out == "Report on What changed?"
    saved = json.loads((tmp_path / "research" / f"{stand_in.session_id}.json").read_text())
    assert (saved["task_id"], saved["task_name"]) == ("wf", "Morning · Step")


@pytest.mark.asyncio
async def test_each_delivery_takes_a_stand_in(task_db, monkeypatch):
    s = ts.TaskScheduler(None)
    # To the workflow's chat, raw write (no session manager).
    chat = _stand_in(task_db, output_target="session")
    await s._deliver_task_result(chat, "Three bills.", task_db, model="m")
    assert [m.content for m in task_db.query(ChatMessage).all()] == [
        "Summarise my inbox.", "Three bills."]
    # By email.
    import routes.email_helpers as email_helpers
    import routes.email_routes as email_routes
    sent = []
    monkeypatch.setattr(email_routes, "_resolve_send_config",
                        lambda account_id=None, owner="": {"from_address": "me@example.com"})
    monkeypatch.setattr(email_helpers, "_send_smtp_message",
                        lambda cfg, frm, to, raw, timeout=30: sent.append((to, raw)))
    await s._deliver_task_result(_stand_in(task_db, output_target="email"), "Hi", task_db)
    assert sent and sent[0][0] == ["me@example.com"] and "X-Pantheon-Ref: wf" in sent[0][1]
    # Through an MCP tool.
    import src.tool_utils as tool_utils
    calls = []

    class Mcp:
        async def call_tool(self, name, args):
            calls.append((name, args["subject"]))
            return {"exit_code": 0, "stdout": "sent"}
    monkeypatch.setattr(tool_utils, "get_mcp_manager", lambda: Mcp())
    monkeypatch.setattr(email_helpers, "_get_email_config", lambda: {})
    await s._deliver_task_result(_stand_in(task_db, output_target="mcp__mail__send"), "Hi", task_db)
    assert calls == [("mcp__mail__send", "[Task] Morning · Step")]


def test_the_session_manager_writes_the_stand_in_s_chat():
    from core.session_manager import SessionManager

    manager = SessionManager.__new__(SessionManager)
    manager.sessions = {}
    manager.create_session = lambda *a, **k: object()
    stand_in = wd.WorkflowNodeTask(id="wf", owner="alice", name="Morning · Step")
    SessionManager.ensure_task_session(manager, "chat-9", "[Task] x", "e", "m",
                                       owner="alice", task=stand_in)
    assert stand_in.session_id == "chat-9"
