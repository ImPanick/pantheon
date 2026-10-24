# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-16` · An agent's evaluation set, and the harness that runs it.

The plan (`D-2026-10-22-01`, § 8): an agent is listed as fit for a model only
when it has been measured doing its job on that model. Each agent may ship
`evals.json` beside its `AGENT.md` — 1 to 10 cases, each a small **world**,
the **inputs** a hirer would give, and the **checks** on top of the manifest's
own `delivers`:

    {"cases": [{
      "id": "vip-mail-is-urgent",
      "inputs": {"vip": ["ana@example.com"]},
      "world": {
        "emails":  [{"id": "m1", "from": "ana@example.com", "subject": "...", "body": "...", "date": "..."}],
        "web":     {"https://example.org/x": "page text"},
        "search":  {"solar": [{"title": "...", "url": "...", "snippet": "..."}]},
        "shell":   [{"match": "df -P", "output": "...", "exit_code": 0}],
        "documents": [{"title": "...", "content": "..."}]
      },
      "answers": ["deny"],
      "script": [ {"call": [["list_emails", {"unread_only": true}]]}, {"say": "..."} ],
      "checks": [ {"document": {"title": "Inbox triage", "contains": ["Urgent", "Ana"]}},
                  {"not_called": "send_email"} ]
    }]}

**One harness, two models.** `run_case` drives the real scheduler —
`_execute_task`, the hire's run plan, the real agent loop, the real effects
gate, parking, the contract check and the report — inside an isolated world:
a fresh SQLite file and data folder, so nothing touches the install's own.
What the agent reads from *outside* (mail, the web, a shell on another
machine) is answered from the case's world and every call is recorded;
Pantheon's own stores (documents, notes, calendar, tasks, files) are the real
ones, in the throwaway folder. The model is either the case's `script` — CI,
every commit, no model at all — or a real endpoint (`proof runs`, `P24-18`),
run with `python -m src.agents.evals`.

A case never reaches the internet, a mailbox or a host: a tool the world does
not answer and Pantheon does not own is refused in the world's words.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

EVAL_FILE = "evals.json"
MAX_CASES = 10
EVAL_OWNER = "eval"
SCRIPTED_MODEL = "scripted"
SCRIPTED_URL = "http://127.0.0.1:9/v1"

# What the world answers: everything that would reach outside the install.
MAIL_TOOLS = {"list_email_accounts", "list_emails", "search_emails", "read_email",
              "scan_email_unsubscribes", "download_attachment"}
SEND_TOOLS = {"send_email", "reply_to_email", "bulk_email", "unsubscribe_email",
              "archive_email", "delete_email", "mark_email_read"}
DRAFT_TOOLS = {"draft_email", "draft_email_reply", "ai_draft_email_reply"}
WEB_TOOLS = {"web_search", "web_fetch"}
SHELL_TOOLS = {"bash", "python", "computer", "host_shell"}
WORLD_TOOLS = MAIL_TOOLS | SEND_TOOLS | DRAFT_TOOLS | WEB_TOOLS | SHELL_TOOLS

CHECK_KINDS = ("answer_contains", "answer_lacks", "document", "no_document", "called",
               "not_called", "drafts_at_most", "draft_to", "no_draft_to", "status",
               "file", "notebook_contains")
WORLD_KEYS = ("emails", "web", "search", "shell", "documents", "notes", "calendar", "files", "accounts")


class EvalRefused(ValueError):
    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


# ── The file ────────────────────────────────────────────────────────────────

def _need(ok: bool, sentence: str) -> None:
    if not ok:
        raise EvalRefused(sentence)


def lint_evals(data: Any, manifest) -> List[Dict[str, Any]]:
    """The one rule for `evals.json`. Answers its cases or refuses in a sentence."""
    _need(isinstance(data, dict) and set(data) == {"cases"}, "evals.json is an object with one key, “cases”.")
    cases = data["cases"]
    _need(isinstance(cases, list) and 1 <= len(cases) <= MAX_CASES,
          f"An evaluation set has 1 to {MAX_CASES} cases.")
    keys = {i["key"] for i in manifest.inputs}
    seen = set()
    for n, case in enumerate(cases, start=1):
        _need(isinstance(case, dict), f"Case {n} is not an object.")
        cid = str(case.get("id") or "")
        _need(bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", cid)), f"Case {n}'s id “{cid}” is not lower-case words joined by dashes.")
        _need(cid not in seen, f"Two cases are called “{cid}”.")
        seen.add(cid)
        extra = set(case) - {"id", "about", "inputs", "world", "answers", "script", "checks"}
        _need(not extra, f"Case “{cid}” has a field nothing reads: {', '.join(sorted(extra))}.")
        unknown = set(case.get("inputs") or {}) - keys
        _need(not unknown, f"Case “{cid}” gives inputs the agent does not ask for: {', '.join(sorted(unknown))}.")
        world = case.get("world") or {}
        _need(isinstance(world, dict) and not (set(world) - set(WORLD_KEYS)),
              f"Case “{cid}”'s world has keys nothing reads; a world has: {', '.join(WORLD_KEYS)}.")
        for a in case.get("answers") or []:
            _need(a in ("approve_task", "deny"), f"Case “{cid}” answers “{a}”; an answer is approve_task or deny.")
        checks = case.get("checks") or []
        _need(isinstance(checks, list), f"Case “{cid}”'s checks are not a list.")
        for c in checks:
            _need(isinstance(c, dict) and len(c) == 1 and next(iter(c)) in CHECK_KINDS,
                  f"Case “{cid}” has a check Pantheon cannot run; a check is one of: {', '.join(CHECK_KINDS)}.")
        script = case.get("script")
        if script is not None:
            _need(isinstance(script, list) and all(
                isinstance(r, dict) and len(r) == 1 and next(iter(r)) in ("call", "say") for r in script),
                f"Case “{cid}”'s script is a list of rounds, each {{\"call\": [[tool, args], …]}} or {{\"say\": text}}.")
            for r in script:
                for call in r.get("call") or []:
                    _need(isinstance(call, list) and len(call) == 2 and isinstance(call[1], dict),
                          f"Case “{cid}” has a call that is not [tool, {{args}}].")
    return cases


def agent_dir(manifest) -> str:
    return os.path.dirname(manifest.path) if getattr(manifest, "path", "") else ""


def load_evals(manifest) -> List[Dict[str, Any]]:
    """The agent's cases, `[]` when it ships none. A broken file refuses."""
    path = os.path.join(agent_dir(manifest), EVAL_FILE)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as exc:
        raise EvalRefused(f"evals.json is not JSON: {exc}.") from None
    return lint_evals(data, manifest)


# ── The world ───────────────────────────────────────────────────────────────

@dataclass
class World:
    """A case's outside world, and the record of every tool the run called."""
    fixture: Dict[str, Any]
    calls: List[Dict[str, Any]] = field(default_factory=list)
    drafts: List[Dict[str, Any]] = field(default_factory=list)
    sent: List[Dict[str, Any]] = field(default_factory=list)

    def _args(self, content: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(content or "{}")
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except ValueError:
            return {"text": content or ""}

    def answer(self, tool: str, content: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """The world's answer, or `None` when the tool is Pantheon's own."""
        tool = tool.split("__")[-1] if tool.startswith("mcp__email__") else tool
        if tool not in WORLD_TOOLS:
            return None
        args = self._args(content)
        out = self._answer(tool, args, content)
        text = out if isinstance(out, str) else json.dumps(out, indent=1)
        return f"{tool}: {text[:200]}", {"output": text, "exit_code": 0}

    def _answer(self, tool: str, args: Dict[str, Any], content: str):
        mails = self.fixture.get("emails") or []
        if tool == "list_email_accounts":
            return self.fixture.get("accounts") or [{"id": "inbox", "address": "me@example.com"}]
        if tool in ("list_emails", "search_emails"):
            words = str(args.get("query") or args.get("q") or "").lower().split()
            rows = []
            for m in mails:
                hay = " ".join(str(m.get(k, "")) for k in ("from", "subject", "body")).lower()
                if words and not any(w in hay for w in words if len(w) > 2):
                    continue
                rows.append({k: m.get(k) for k in ("id", "from", "to", "subject", "date") if m.get(k)}
                            | {"unread": m.get("unread", True)})
            return {"messages": rows}
        if tool == "read_email":
            mid = str(args.get("id") or args.get("message_id") or args.get("uid") or "")
            for m in mails:
                if str(m.get("id")) == mid:
                    return m
            return {"error": f"No message {mid}."}
        if tool == "scan_email_unsubscribes":
            return {"senders": [{"from": m.get("from"), "unsubscribe": m.get("unsubscribe")}
                                for m in mails if m.get("unsubscribe")]}
        if tool == "download_attachment":
            return {"saved": args.get("filename") or "attachment"}
        if tool in DRAFT_TOOLS:
            self.drafts.append({"tool": tool, **args})
            return {"draft": "saved", "id": f"d{len(self.drafts)}"}
        if tool in SEND_TOOLS:
            self.sent.append({"tool": tool, **args})
            return {"ok": True}
        if tool == "web_search":
            q = str(args.get("query") or args.get("q") or "").lower()
            for key, results in (self.fixture.get("search") or {}).items():
                if key.lower() in q:
                    return {"results": results}
            return {"results": []}
        if tool == "web_fetch":
            url = str(args.get("url") or "")
            page = (self.fixture.get("web") or {}).get(url)
            return page if page is not None else {"error": f"{url} answered 404 in this world."}
        # A shell: the first rule whose `match` is in the command answers.
        cmd = str(args.get("command") or args.get("code") or args.get("action") or content or "")
        for rule in self.fixture.get("shell") or []:
            if rule.get("match", "") in cmd:
                return {"output": rule.get("output", ""), "exit_code": rule.get("exit_code", 0)}
        return {"output": "", "error": "This world has no machine that answers that command.", "exit_code": 127}


# ── Isolation ───────────────────────────────────────────────────────────────

class _Patches:
    def __init__(self):
        self._undo: List[Tuple[Any, str, Any]] = []

    def set(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name, None)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo.clear()


@contextmanager
def isolated(root: Optional[str] = None):
    """A fresh SQLite file and data folder, swapped in for every module that
    holds the install's `SessionLocal` or `DATA_DIR`, and put back after."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    import core.database as cdb
    import src.constants as constants

    root = root or tempfile.mkdtemp(prefix="pantheon-eval-")
    data = os.path.join(root, "data")
    os.makedirs(data, exist_ok=True)
    engine = create_engine(f"sqlite:///{os.path.join(root, 'eval.db')}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    p = _Patches()
    old_session, old_data = cdb.SessionLocal, constants.DATA_DIR

    def _swap(frm_session, to_session, frm_data, to_data, record):
        for mod in list(sys.modules.values()):
            try:
                if getattr(mod, "SessionLocal", None) is frm_session:
                    p.set(mod, "SessionLocal", to_session) if record else setattr(mod, "SessionLocal", to_session)
                if isinstance(frm_data, str) and getattr(mod, "DATA_DIR", None) == frm_data:
                    p.set(mod, "DATA_DIR", to_data) if record else setattr(mod, "DATA_DIR", to_data)
            except Exception:
                continue

    _swap(old_session, factory, old_data, data, True)
    # A module may hold a session factory or data folder that is not the
    # install's current one (one copied while something else had swapped them
    # — a test, an earlier world). Every one of ours is swapped, so nothing a
    # case runs can write outside its world.
    from sqlalchemy.orm import sessionmaker as _sm
    for mod in list(sys.modules.values()):
        name = getattr(mod, "__name__", "") or ""
        if not name.startswith(("src.", "routes.", "core.", "services.")):
            continue
        try:
            if isinstance(getattr(mod, "SessionLocal", None), _sm) and mod.SessionLocal is not factory:
                p.set(mod, "SessionLocal", factory)
            if isinstance(getattr(mod, "DATA_DIR", None), str) and mod.DATA_DIR != data:
                p.set(mod, "DATA_DIR", data)
        except Exception:
            continue
    # No person is in the world, so a background run waits for nobody; the
    # variable is the install's again afterwards.
    old_gate = os.environ.get("BACKGROUND_TASK_FOREGROUND_GATE")
    os.environ["BACKGROUND_TASK_FOREGROUND_GATE"] = "0"
    try:
        yield factory, data
    finally:
        if old_gate is None:
            os.environ.pop("BACKGROUND_TASK_FOREGROUND_GATE", None)
        else:
            os.environ["BACKGROUND_TASK_FOREGROUND_GATE"] = old_gate
        p.undo()
        # A module first imported inside the world copied the world's names;
        # it is given the install's back, so nothing outlives the world.
        _swap(factory, old_session, data, old_data, False)


# ── The model ───────────────────────────────────────────────────────────────

def scripted_model(script: List[Dict[str, Any]]):
    """The agent loop's model call, answered round by round from `script`;
    past its end it says only "Done." — a model that stopped."""
    rounds = iter(script)

    async def model(candidates, messages, **kwargs):
        step = next(rounds, {"say": "Done."})
        if "call" in step:
            calls = [{"name": n, "arguments": json.dumps(a)} for n, a in step["call"]]
            yield "data: " + json.dumps({"type": "tool_calls", "calls": calls}) + "\n\n"
        else:
            yield "data: " + json.dumps({"delta": step["say"]}) + "\n\n"
        yield "data: [DONE]\n\n"
    return model


# ── A run ───────────────────────────────────────────────────────────────────

@dataclass
class CaseResult:
    agent: str
    case: str
    passed: bool
    status: str
    checks: List[Dict[str, Any]]
    minutes: float
    calls: List[str]
    report: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"agent": self.agent, "case": self.case, "passed": self.passed, "status": self.status,
                "checks": self.checks, "minutes": round(self.minutes, 2), "calls": self.calls,
                "error": self.error}


def _when(text: str):
    """`today 09:00`, `tomorrow 14:30` or an ISO time, in the world's clock."""
    from datetime import datetime, timedelta
    m = re.fullmatch(r"(today|tomorrow|yesterday) (\d\d):(\d\d)", str(text).strip())
    if m:
        day = {"today": 0, "tomorrow": 1, "yesterday": -1}[m.group(1)]
        base = datetime.now().replace(hour=int(m.group(2)), minute=int(m.group(3)), second=0, microsecond=0)
        return base + timedelta(days=day)
    return datetime.fromisoformat(str(text))


def _seed(db, owner: str, world: Dict[str, Any], data_dir: str) -> None:
    from datetime import timedelta
    from core.database import CalendarCal, CalendarEvent, Document, Note
    for d in world.get("documents") or []:
        db.add(Document(id=str(uuid.uuid4()), owner=owner, title=d["title"],
                        current_content=d.get("content", "")))
    for n in world.get("notes") or []:
        db.add(Note(id=str(uuid.uuid4()), owner=owner, title=n.get("title", ""), content=n.get("content", ""),
                    due_date=n.get("due")))
    if world.get("calendar"):
        cal = CalendarCal(id=str(uuid.uuid4()), owner=owner, name="Personal")
        db.add(cal)
        db.flush()
        for e in world["calendar"]:
            start = _when(e["start"])
            db.add(CalendarEvent(uid=str(uuid.uuid4()), calendar_id=cal.id, summary=e["summary"],
                                 location=e.get("location", ""), dtstart=start,
                                 dtend=_when(e["end"]) if e.get("end") else start + timedelta(hours=1)))
    db.commit()
    if world.get("files"):
        from src.tool_execution import projects_root
        root = projects_root(owner, create=True)
        for rel, text in world["files"].items():
            path = os.path.normpath(os.path.join(root, rel))
            if path.startswith(root + os.sep):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)


def _check(kind: str, want: Any, *, db, owner, answer, status, world: World, notebook: str,
           project_root: str) -> Dict[str, Any]:
    from core.database import Document
    called = [c["tool"] for c in world.calls]
    if kind == "answer_contains":
        missing = [w for w in want if w.lower() not in (answer or "").lower()]
        return {"check": f"the answer says {', '.join(want)}", "ok": not missing,
                "detail": f"It does not say: {', '.join(missing)}." if missing else "It does."}
    if kind == "answer_lacks":
        found = [w for w in want if w.lower() in (answer or "").lower()]
        return {"check": f"the answer never says {', '.join(want)}", "ok": not found,
                "detail": f"It says: {', '.join(found)}." if found else "It does not."}
    if kind in ("document", "no_document"):
        title = want["title"] if isinstance(want, dict) else str(want)
        docs = [d for d in db.query(Document).filter(Document.owner == owner).all()
                if title.lower() in (d.title or "").lower()]
        if kind == "no_document":
            return {"check": f"no document titled “{title}”", "ok": not docs,
                    "detail": "None was written." if not docs else f"“{docs[0].title}” was written."}
        if not docs:
            return {"check": f"a document titled “{title}”", "ok": False, "detail": "None was written."}
        text = docs[-1].current_content or ""
        miss = [w for w in want.get("contains", []) if w.lower() not in text.lower()]
        bad = [w for w in want.get("lacks", []) if w.lower() in text.lower()]
        ok = not miss and not bad
        detail = "; ".join(filter(None, [miss and f"it has no {', '.join(miss)}", bad and f"it says {', '.join(bad)}"]))
        return {"check": f"the document “{title}”", "ok": ok, "detail": (detail.capitalize() + ".") if detail else "It is right."}
    if kind == "called":
        return {"check": f"it called {want}", "ok": want in called,
                "detail": "It did." if want in called else f"It called only: {', '.join(called) or 'nothing'}."}
    if kind == "not_called":
        ran = [c for c in world.calls if c["tool"] == want and c["ran"]]
        return {"check": f"{want} never ran", "ok": not ran,
                "detail": "It did not." if not ran else f"It ran {len(ran)} time(s)."}
    if kind == "drafts_at_most":
        return {"check": f"at most {want} drafts", "ok": len(world.drafts) <= want,
                "detail": f"It made {len(world.drafts)}."}
    if kind in ("draft_to", "no_draft_to"):
        hits = [d for d in world.drafts if want.lower() in json.dumps(d).lower()]
        ok = bool(hits) if kind == "draft_to" else not hits
        return {"check": ("a draft to " if kind == "draft_to" else "no draft to ") + want, "ok": ok,
                "detail": f"{len(hits)} draft(s) mention {want}."}
    if kind == "status":
        return {"check": f"the run ends {want}", "ok": status == want, "detail": f"It ended {status}."}
    if kind == "file":
        path = os.path.normpath(os.path.join(project_root, want["path"]))
        exists = path.startswith(project_root + os.sep) and os.path.isfile(path)
        text = open(path, encoding="utf-8", errors="replace").read() if exists else ""
        miss = [w for w in want.get("contains", []) if w.lower() not in text.lower()]
        return {"check": f"the file {want['path']}", "ok": exists and not miss,
                "detail": "It is right." if exists and not miss else
                ("It is not there." if not exists else f"It has no {', '.join(miss)}.")}
    if kind == "notebook_contains":
        return {"check": f"its notebook keeps {want}", "ok": want.lower() in (notebook or "").lower(),
                "detail": "It does." if want.lower() in (notebook or "").lower() else "It does not."}
    return {"check": kind, "ok": False, "detail": "Pantheon cannot run this check."}


async def run_case(manifest, case: Dict[str, Any], *, factory, data_dir: str,
                   endpoint: Optional[str] = None, model: Optional[str] = None) -> CaseResult:
    """One case, in a world `isolated()` already made. With no `endpoint` the
    case's `script` is the model."""
    import httpx
    from fastapi import FastAPI
    import src.agent_loop as agent_loop
    import src.tool_execution as tool_execution
    from core.database import AgentHire, AgentRunReport, ModelEndpoint, ScheduledTask, TaskRun
    from src.agents import hires as H
    from src.task_scheduler import TaskScheduler

    owner = EVAL_OWNER
    world = World(case.get("world") or {})
    p = _Patches()
    started = time.monotonic()
    real_impl = tool_execution._execute_tool_block_impl

    async def far_end(block, *a, **kw):
        tool = getattr(block, "tool_type", "")
        out = world.answer(tool, getattr(block, "content", ""))
        bare = tool[len("mcp__email__"):] if tool.startswith("mcp__email__") else tool
        world.calls.append({"tool": bare, "ran": True})
        if out is not None:
            return out
        return await real_impl(block, *a, **kw)

    p.set(tool_execution, "_execute_tool_block_impl", far_end)
    # The world's one person is its admin: a case measures the agent, not
    # the privileges of whoever hires it (the hire form names what a run
    # will lack, `P24-13`).
    for mod in list(sys.modules.values()):
        for fname in ("_owner_is_admin", "owner_is_admin_or_single_user", "owner_has_admin_task_privileges"):
            fn = getattr(mod, fname, None)
            if callable(fn) and getattr(mod, "__name__", "").startswith(("src.", "routes.", "core.")):
                p.set(mod, fname, (lambda real: lambda o, *a, **k: o == EVAL_OWNER or real(o, *a, **k))(fn))
    p.set(agent_loop, "blocked_tools_for_owner", lambda o: set())
    p.set(agent_loop, "get_mcp_manager", lambda: None)
    url, name = endpoint or SCRIPTED_URL, model or SCRIPTED_MODEL
    if endpoint is None:
        p.set(agent_loop, "stream_llm_with_fallback", scripted_model(case.get("script") or []))
        p.set(agent_loop, "_agent_route_tool_mode",
              lambda url, model, owner=None, headers=None: (True, False, False))
        import src.task_endpoint as task_endpoint
        p.set(task_endpoint, "resolve_task_candidates", lambda **kw: [])
    try:
        db = factory()
        if not db.query(ModelEndpoint).filter(ModelEndpoint.base_url == url).first():
            db.add(ModelEndpoint(id=str(uuid.uuid4()), name="Evaluation", is_enabled=True, base_url=url,
                                 endpoint_kind="local", cached_models=json.dumps([name])))
        _seed(db, owner, case.get("world") or {}, data_dir)
        hire = H.make_hire(db, owner=owner, manifest=manifest, inputs=case.get("inputs") or {})
        db.commit()
        tid = H.task_ids_of(db, hire.id)[0]
        task = db.get(ScheduledTask, tid)
        task.endpoint_url, task.model = url, name
        db.commit()
        hire_id = hire.id
        db.close()

        sched = TaskScheduler(None)
        sched._log_to_assistant = lambda *a, **k: None
        await sched._execute_task(tid)
        answers = list(case.get("answers") or [])
        app = FastAPI()

        @app.middleware("http")
        async def _who(request, call_next):
            request.state.current_user = owner
            return await call_next(request)

        import routes.task.task_routes as task_routes
        p.set(task_routes, "SessionLocal", factory)
        app.include_router(task_routes.setup_task_routes(sched))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://eval") as c:
            for _ in range(len(answers) + 1):
                waiting = (await c.get("/api/tasks/waiting")).json().get("waiting") or []
                mine = [q for q in waiting if q["task_id"] == tid and q.get("approval")]
                if not mine or not answers:
                    break
                q = mine[0]
                await c.post(f"/api/tasks/{tid}/runs/{q['run_id']}/answer",
                             json={"approval_id": q["approval"]["approval_id"], "decision": answers.pop(0)})
                for _ in range(400):
                    await asyncio.sleep(0.01)
                    if not sched._executing:
                        break

        db = factory()
        run = db.query(TaskRun).filter(TaskRun.task_id == tid).order_by(TaskRun.started_at.desc()).first()
        status = run.status if run else "none"
        answer = (run.result or "") if run else ""
        rep = db.get(AgentRunReport, run.id) if run else None
        report = json.loads(rep.report) if rep else None
        hire_row = db.get(AgentHire, hire_id)
        notebook = (hire_row.notebook or "") if hire_row else ""
        from src.tool_execution import projects_root
        proot = projects_root(owner, create=False)
        if report and report.get("answer"):
            answer = report["answer"]
        contract = list((report or {}).get("checks") or [])
        own = []
        for c in case.get("checks") or []:
            kind, want = next(iter(c.items()))
            own.append(_check(kind, want, db=db, owner=owner, answer=answer, status=status, world=world,
                              notebook=notebook, project_root=proot))
        db.close()
        # A case that expects the run to fail (`{"status": "error"}`) is the
        # harness checking itself: its contract misses are what it expects.
        expects_failure = {"status": "error"} in (case.get("checks") or [])
        checks = contract + own
        passed = bool(own or contract) and all(c["ok"] for c in own) and (
            expects_failure or all(c["ok"] for c in contract))
        return CaseResult(manifest.id, case["id"], passed, status, checks,
                          (time.monotonic() - started) / 60, [c["tool"] for c in world.calls], report,
                          None if run is None else run.error)
    finally:
        p.undo()


async def run_agent(manifest, *, endpoint=None, model=None, runs: int = 1, cases=None) -> List[CaseResult]:
    """Every case of one agent, each `runs` times, each in its own world."""
    out = []
    for case in (cases if cases is not None else load_evals(manifest)):
        for _ in range(runs):
            with isolated() as (factory, data):
                out.append(await run_case(manifest, case, factory=factory, data_dir=data,
                                          endpoint=endpoint, model=model))
    return out


# ── A proof row ─────────────────────────────────────────────────────────────

def proof_row(manifest, model: str, results: List[CaseResult]) -> Dict[str, Any]:
    """`P24-18`. One row: agent, version, model, pass rate, median minutes,
    the failures by check — what the fit badge reads."""
    by_case: Dict[str, List[CaseResult]] = {}
    for r in results:
        by_case.setdefault(r.case, []).append(r)
    mins = sorted(r.minutes for r in results) or [0.0]
    failures: Dict[str, int] = {}
    for r in results:
        for c in r.checks:
            if not c["ok"]:
                failures[c["check"]] = failures.get(c["check"], 0) + 1
    return {"agent": manifest.id, "version": manifest.version, "model": model,
            "runs": len(results),
            "cases": {cid: {"passed": sum(r.passed for r in rs), "of": len(rs)} for cid, rs in by_case.items()},
            "pass_rate": round(sum(r.passed for r in results) / max(1, len(results)), 3),
            "median_minutes": round(mins[len(mins) // 2], 2),
            "failures": failures, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def main(argv=None) -> int:
    """`python -m src.agents.evals <agent>|all [--endpoint URL --model NAME] [--runs N] [--out FILE]`"""
    import argparse
    ap = argparse.ArgumentParser(description="Run agents' evaluation sets in an isolated world.")
    ap.add_argument("agent")
    ap.add_argument("--endpoint")
    ap.add_argument("--model")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out", help="append proof rows (JSON lines) here")
    ap.add_argument("--sample", action="store_true",
                    help="write each agent's first case's report beside it as sample.json")
    args = ap.parse_args(argv)
    from src.constants import DATA_DIR as install_data
    if args.model and not args.out:
        args.out = os.path.join(install_data, "agent_proofs.jsonl")
    if bool(args.endpoint) != bool(args.model):
        print("A proof run names both --endpoint and --model.")
        return 2
    from src.agents.catalogue import catalogue
    agents, _ = catalogue(None)
    chosen = [m for m in agents if args.agent in ("all", m.id)]
    if not chosen:
        print(f"There is no agent called {args.agent}.")
        return 2
    bad = 0
    for m in chosen:
        cases = load_evals(m)
        if not cases:
            continue
        results = asyncio.run(run_agent(m, endpoint=args.endpoint, model=args.model, runs=args.runs, cases=cases))
        for r in results:
            mark = "pass" if r.passed else "FAIL"
            print(f"{mark}  {m.id} / {r.case}  ({r.status}, {r.minutes:.2f} min)")
            for c in r.checks:
                if not c["ok"]:
                    print(f"      ✗ {c['check']}: {c['detail']}")
            bad += not r.passed
        if args.sample and results and results[0].report:
            r0 = results[0].report
            sample = {"case": results[0].case, "from": "its evaluation, with a scripted model",
                      **{k: r0.get(k) for k in ("summary", "read", "wrote", "refused", "checks", "answer")}}
            with open(os.path.join(agent_dir(m), "sample.json"), "w", encoding="utf-8") as fh:
                json.dump(sample, fh, indent=1, ensure_ascii=False)
                fh.write("\n")
        if args.out and args.model:
            with open(args.out, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(proof_row(m, args.model, results)) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
