# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1223` — route handlers keep their database work off the event loop, and
the number that still do may only fall.

The row's count, re-measured with its own definition: an `async def` route
handler (decorated `@<router>.get/post/put/patch/delete/…`) whose **own body**
— not a nested function — calls `SessionLocal()` or `get_db_session()`. That
work runs on the event loop, where a held SQLite lock is a wait for every
request (`P23-07` bounds it at half a second and a 503). **143 on
`a16e7d75`** (document 24, gallery 23, task 18, calendar 10, email 8,
workflow 8, mcp 7, history 6, …).

A handler leaves the count by becoming a plain `def` — Starlette runs it in
its thread pool — or by handing its database work to `asyncio.to_thread`. The
ones a person meets first went first: chat send (the message write, the mode,
the active document, a summoned agent), document save, task edit. **143 → 54
on 2026-10-27 (`wave-x`), 54 → 0 the same day (`wave/z`)**: the rest keep
`async` — they await an upload, a model, a CalDAV push, an MCP connection, the
scheduler — and do their database steps in worker threads, in short sessions
either side of the await rather than one held across it. The ceiling is 0: a
new handler that opens a session on the event loop is listed by this file when
it fails (`Law 13`'s ratchet, in a test).

The behaviour is driven in
`tests/test_a_save_waits_for_a_held_lock_without_stalling_the_server.py`.

**`B1580` — and through the helpers it calls.** The count above sees a session
opened in a handler's own body, so a handler that called `record_auth_event`
— which calls `record_event`, which opens one — was not on it: 28 audit writes
in `routes/auth_routes.py` committed on the event loop. `through_a_helper()`
asks the same question of every function a handler calls by name — in its own
module, through `from x import f`, or as `module.f` — and of the functions
those call, to the bottom: **107** handlers on `f3a9150e`, with the own-body
count at 0. A call handed to `asyncio.to_thread(f, …)` names `f` as an
argument and is not followed, which is the way off the list; a method on an
object (`auth_manager.create_user`) is not resolved, so the number is a floor.

What `B1580` took off: every audit write (`auth_routes._audit`), every
`_verify_session_owner` in an async handler (19), the diagnostics readers, the
folder writes, the chat send's model and privilege checks, the event bus's
counting (`event_bus._count_event` — it ran on the loop for any event an async
caller fired, its session held across the scheduler hand-off), the inbox's
seen-mail claim, the upload's context measure, `resolve_endpoint` in the
handlers that name it. **107 → 51.** What is left is named by the list this
file prints, and nearly all of it is three chains: a model call
(`llm_call_async`, `stream_llm`) records its run configuration
(`_capture_run_config` → `record_run_config` → `record_event`) on the loop,
which only happens inside a chat turn; asks whether an endpoint is local
(`model_context._enabled_endpoint_rows`); and an outbound address is checked
against the person's own networks (`url_safety.check_outbound_url` →
`person_networks.for_run`) — the contacts, gallery and skill-import routes.

**`B1588` — the remainder, re-measured (`Law 3`).** The three chains were not
most of the 51: with the model call's own database work taken off the loop,
the list fell by four, because nearly every handler that calls a model also
resolves its endpoint (`resolve_task_endpoint`, `_resolve_vl_model`,
`resolve_utility_fallback_candidates`, `_resolve_audit_models`) on the loop
first. What `B1588` took off: the model call itself — `llm_call_async` and
`stream_llm` hand the endpoint-kind reads (`_carried_max_tokens`,
`_apply_local_profiles`, `get_context_length`, the local-model gate) and the
run-config write (`_capture_run_config_async`, whose latch stays on the loop)
to worker threads, and `reaches_a_session` holds both doors at no session;
the endpoint resolvers in the handlers that call a model; the context-length
reads (`context_info`, the context wheel, compaction); the vision calls in
the upload, Library and gallery routes; the memory import's file reader; the
skill import's link check; and the contacts router, whose ten handlers were
`async def` awaiting nothing and are plain `def` now. **51 → 25.** The rest
are async helpers (CalDAV, the agent workshop, replay, evals, the skill
tests, the workflow assist) whose own database steps need the same split.

**`B1598` — the 25, split.** Each helper hands its database step to a worker
thread and keeps its await on the loop: the workflow assistant's endpoint
(`workflow_assist._complete`, behind the agent workshop's interview and draft,
design extraction, the task parser and the workflow example writer, and the
*Why did this fail?* model name); the outbound check (`check_outbound_url` →
`person_networks.for_run`) in the integration call, the gallery's image
fetches and the reminder's webhook and ntfy sends, with the reminder's
synthesis endpoint and mail accounts; CalDAV's event loads, account reads,
address check and result write (`caldav_writeback._writeback_account`); the
chat's context build (model-id normalisation, the window, compaction's
utility endpoint), its foreground policy and candidates, the approval-card
mark and the post-reply jobs' endpoints; service health's inputs; replay's
plan and rows and the eval suite's receipts; the memory audit's faded sweep
and endpoint; the skill audit's and the skill tests' models; and the agent
loop's own reads — approval mode, run limits, the local-endpoint question,
the synthesis ceiling, the run-config and turn-outcome rows and the
teacher's endpoint. **25 → 1.** Left: `chat_endpoint` → `run_post_response_tasks`
→ `accumulate_token_usage`, a branch that handler never takes (it passes no
metrics); the stream's own call runs inside its generator, which this scan
does not follow, and moving the counters off the loop changes when a turn's
figures land, so it is a row of its own.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import threading

from test_the_qwen3_cap_guards_every_door import wire  # noqa: F401,E402  (`B1588`'s drive)

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The ceiling. 0 since `wave/z`: a rise is a handler that put its database
#: work back on the loop.
MAX_ON_THE_LOOP = 0

_METHODS = {"get", "post", "put", "delete", "patch", "api_route", "websocket", "head", "options"}
_DB_CALLS = {"SessionLocal", "get_db_session"}


def _is_route(fn) -> bool:
    return any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
               and d.func.attr in _METHODS for d in fn.decorator_list)


def _calls_the_database_itself(fn) -> bool:
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name in _DB_CALLS:
                return True
        stack.extend(ast.iter_child_nodes(node))
    return False


#: `B1580`. The ceiling through helpers: 51 after `B1580`, from 107; 25 after
#: `B1588`; 1 after `B1598`.
MAX_THROUGH_A_HELPER = 1

#: Where a helper a handler calls can live.
_SCOPE = ("routes", "src", "core", "services", "companion", "integrations")


def _module_name(path: pathlib.Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def _own_calls(fn):
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Call):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _imports(tree, module: str):
    """`({name: (module, function)}, {alias: module})` from every import in
    the file, function-local ones included — this codebase imports late."""
    names, modules = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            base = node.module
            if node.level:
                base = ".".join(module.split(".")[:-node.level] + [node.module])
            for a in node.names:
                names[a.asname or a.name] = (base, a.name)
                modules[a.asname or a.name] = f"{base}.{a.name}"
        elif isinstance(node, ast.Import):
            for a in node.names:
                modules[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
    return names, modules


def _every_tree():
    trees = {}
    for top in _SCOPE:
        for path in sorted((ROOT / top).glob("**/*.py")):
            trees[_module_name(path)] = (path, ast.parse(path.read_text(encoding="utf-8")))
    trees["app"] = (ROOT / "app.py", ast.parse((ROOT / "app.py").read_text(encoding="utf-8")))
    return trees


def _call_graph(trees):
    """`(defs, resolve, reaches)` over `trees` — the question `B1580` asks of
    a handler, askable of any module-level function (`B1588`)."""
    defs = {(m, n.name): n for m, (_p, t) in trees.items() for n in t.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    scope = {m: _imports(t, m) for m, (_p, t) in trees.items()}

    def resolve(call, module):
        names, modules = scope[module]
        f = call.func
        if isinstance(f, ast.Name):
            if (module, f.id) in defs:
                return (module, f.id)
            return names.get(f.id)
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in modules:
            return (modules[f.value.id], f.attr)
        return None

    memo = {}

    def reaches(key, seen=()):
        if key in memo:
            return memo[key]
        if key in seen:
            return False
        fn = defs[key]
        hit = _calls_the_database_itself(fn) or any(
            target in defs and reaches(target, seen + (key,))
            for target in (resolve(c, key[0]) for c in _own_calls(fn)) if target)
        memo[key] = hit
        return hit

    return defs, resolve, reaches


def reaches_a_session(module: str, function: str, trees=None) -> bool:
    """`B1588`. Does `module.function`, called on the loop, open a database
    session — itself, or through anything it calls by name?"""
    defs, _resolve, reaches = _call_graph(trees if trees is not None else _every_tree())
    return reaches((module, function))


def through_a_helper(trees=None):
    """`[(file, line, handler, helper)]` — every async route handler that
    reaches a database session through a function it calls (`B1580`).

    `trees` is `{module: (path, tree)}`; by default every module in `_SCOPE`
    and `app.py`. A handler counted by `on_the_loop()` is counted here too."""
    if trees is None:
        trees = _every_tree()
    defs, resolve, reaches = _call_graph(trees)

    out = []
    for module, (path, tree) in trees.items():
        if not (module.startswith("routes") or module == "app"):
            continue
        for fn in ast.walk(tree):
            if not (isinstance(fn, ast.AsyncFunctionDef) and _is_route(fn)):
                continue
            if _calls_the_database_itself(fn):
                out.append((str(path.relative_to(ROOT)), fn.lineno, fn.name, "its own body"))
                continue
            for call in _own_calls(fn):
                target = resolve(call, module)
                if target in defs and reaches(target):
                    out.append((str(path.relative_to(ROOT)), fn.lineno, fn.name, ".".join(target)))
                    break
    return out


def on_the_loop():
    """`[(file, line, handler)]` — every route still doing its own database
    work on the event loop."""
    out = []
    for path in sorted(ROOT.glob("routes/**/*.py")) + [ROOT / "app.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if isinstance(fn, ast.AsyncFunctionDef) and _is_route(fn) and _calls_the_database_itself(fn):
                out.append((str(path.relative_to(ROOT)), fn.lineno, fn.name))
    return out


def test_the_count_only_falls():
    found = on_the_loop()
    listed = "\n".join(f"  {f}:{line} {name}" for f, line, name in found)
    assert len(found) <= MAX_ON_THE_LOOP, (
        f"{len(found)} async route handlers do their own database work on the event "
        f"loop; the ceiling is {MAX_ON_THE_LOOP}. Make the new one a plain `def`, or "
        f"move its database work into `asyncio.to_thread`:\n{listed}")


def test_the_scan_sees_what_it_says_it_counts():
    """A ratchet that counts nothing passes forever (`Law 20`): the scan finds a
    handler of the shape in a source it is handed, and passes over the two
    shapes that are off the loop."""
    tree = ast.parse(
        "@router.get('/a')\nasync def a():\n    db = SessionLocal()\n"
        "@router.get('/b')\ndef b():\n    db = SessionLocal()\n"
        "@router.get('/c')\nasync def c():\n    def work():\n        db = SessionLocal()\n"
        "    return await asyncio.to_thread(work)\n")
    caught = [fn.name for fn in ast.walk(tree)
              if isinstance(fn, ast.AsyncFunctionDef) and _is_route(fn) and _calls_the_database_itself(fn)]
    assert caught == ["a"]


def test_the_count_through_helpers_only_falls():
    found = through_a_helper()
    listed = "\n".join(f"  {f}:{line} {name} → {helper}" for f, line, name, helper in found)
    assert len(found) <= MAX_THROUGH_A_HELPER, (
        f"{len(found)} async route handlers reach a database session through a "
        f"function they call; the ceiling is {MAX_THROUGH_A_HELPER}. Hand the call "
        f"to `asyncio.to_thread`, or make the handler a plain `def`:\n{listed}")


def test_the_helper_scan_follows_a_chain_and_stops_at_a_thread():
    """`Law 20` for the second scan: the row's own shape — a handler calling
    `record_auth_event`, which calls `record_event`, which opens the session —
    is caught two modules away, and the three ways off are passed over."""
    events = ast.parse(
        "def record_event(kind):\n    db = SessionLocal()\n"
        "def record_auth_event(action):\n    return record_event('auth')\n")
    routes = ast.parse(
        "import asyncio\nfrom src.events import record_auth_event\nfrom src import events\n"
        "@router.post('/login')\nasync def login():\n    record_auth_event('login')\n"
        "@router.post('/logout')\nasync def logout():\n    events.record_event('logout')\n"
        "@router.post('/a')\nasync def a():\n    await asyncio.to_thread(record_auth_event, 'a')\n"
        "@router.post('/b')\ndef b():\n    record_auth_event('b')\n"
        "@router.post('/c')\nasync def c():\n    def work():\n        record_auth_event('c')\n"
        "    await asyncio.to_thread(work)\n")
    found = through_a_helper({"src.events": (ROOT / "src" / "events.py", events),
                              "routes.x": (ROOT / "routes" / "x.py", routes)})
    assert [(name, helper) for _f, _l, name, helper in found] == [
        ("login", "src.events.record_auth_event"), ("logout", "src.events.record_event")]


def test_a_model_call_opens_no_session_on_the_loop():
    """`B1588`. The two async doors to a model reach no database session on
    the event loop — their endpoint reads and their run-config row are made
    on worker threads — so a handler that calls a model is not on the list
    for the call. The sync door (`llm_call`) runs in a thread already."""
    trees = _every_tree()
    for door in ("llm_call_async", "stream_llm", "llm_call_async_with_fallback",
                 "llm_call_async_with_route_fallback", "_local_model_slot"):
        assert not reaches_a_session("src.llm_core", door, trees), (
            f"src.llm_core.{door} opens a database session on the event loop")
    # And the scan is not blind there: the sync door does reach one.
    assert reaches_a_session("src.llm_core", "llm_call", trees)


def test_no_audit_write_is_on_the_loop():
    """The row's example: every auth route that writes the audit trail, and
    `admin_create_user` by name."""
    found = through_a_helper()
    assert [(name, helper) for _f, _l, name, helper in found
            if helper.startswith("src.events.record_")] == []
    audited = {"first_run_setup", "signup", "login", "logout", "admin_create_user",
               "update_user_privileges", "upsert_role", "remove_role", "set_user_role",
               "set_user_admin", "admin_delete_user"}
    assert [name for f, _l, name, _h in found
            if f == "routes/auth_routes.py" and name in audited] == []


def _sessions_by_thread(monkeypatch, maker):
    import core.database as core_db

    opened = []

    def spy(*a, **kw):
        opened.append(threading.get_ident())
        return maker(*a, **kw)

    monkeypatch.setattr(core_db, "SessionLocal", spy)
    return opened


def test_an_admin_making_an_account_writes_its_audit_row_off_the_loop(tmp_path, monkeypatch):
    """Driven: the real `admin_create_user` with a real `AuthManager` on a real
    `auth.json` and a real SQLite events table. Every session it opens is
    opened on a worker thread, and the row is in the table when the handler
    returns — awaited, not fired and forgotten."""
    import importlib
    import json as _json
    from types import SimpleNamespace

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.database import Base, Event
    from src import events as ev

    engine = create_engine(f"sqlite:///{tmp_path}/audit.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    opened = _sessions_by_thread(monkeypatch, sessionmaker(bind=engine))
    monkeypatch.setattr(ev, "_last_prune", 0.0)
    auth_mod = importlib.import_module("core.auth")
    monkeypatch.setattr(auth_mod, "_hash_password", lambda password: f"hash:{password}")
    monkeypatch.setattr(auth_mod, "_verify_password", lambda p, h: h == f"hash:{p}")
    mgr = auth_mod.AuthManager(str(tmp_path / "auth.json"))
    mgr.create_user("admin", "pw-123456", is_admin=True)

    from routes.auth_routes import CreateUserRequest, setup_auth_routes
    create = next(r.endpoint for r in setup_auth_routes(mgr).routes
                  if getattr(r, "path", "") == "/api/auth/users" and "POST" in r.methods)
    request = SimpleNamespace(cookies={}, client=SimpleNamespace(host="127.0.0.1"), headers={},
                              url=SimpleNamespace(scheme="http"),
                              state=SimpleNamespace(current_user="admin"),
                              app=SimpleNamespace(state=SimpleNamespace(auth_manager=mgr)))

    async def drive():
        loop_thread = threading.get_ident()
        out = await create(body=CreateUserRequest(username="cora", password="pw-123456"),
                           request=request)
        return loop_thread, out

    loop_thread, out = asyncio.run(drive())
    assert out == {"ok": True}
    assert opened and loop_thread not in opened, "a session was opened on the event loop"
    db = sessionmaker(bind=engine)()
    try:
        rows = db.query(Event).filter(Event.kind == ev.AUTH_EVENT_KIND).all()
    finally:
        db.close()
        engine.dispose()
    assert [(r.name, r.owner, _json.loads(r.detail)["subject"]) for r in rows] == [
        ("user_create", "admin", "cora")]


def test_an_event_is_counted_off_the_loop_and_still_wakes_its_task(tmp_path, monkeypatch):
    """`B1580`: the event bus counted on the loop for every event an async
    caller fired, its session open across the scheduler hand-off. Driven with a
    real `ScheduledTask` row at its threshold and a scheduler that records."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import src.event_bus as bus
    from core.database import Base, ScheduledTask

    engine = create_engine(f"sqlite:///{tmp_path}/tasks.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(bind=engine)
    db = maker()
    db.add(ScheduledTask(id="t1", name="On save", owner="alice", status="active",
                         trigger_type="event", trigger_event="document_updated",
                         trigger_count=1, trigger_counter=0, prompt="x"))
    db.commit()
    db.close()
    opened = _sessions_by_thread(monkeypatch, maker)
    woken = []

    class Scheduler:
        async def run_task_now(self, task_id, trigger=None):
            woken.append((task_id, threading.get_ident(), (trigger or {}).get("event")))

    monkeypatch.setattr(bus, "_task_scheduler", Scheduler())
    monkeypatch.setattr(bus, "_resolve_event_owner", lambda owner: owner)

    async def drive():
        await bus._handle_event("document_updated", "alice", {"document_id": "d1"})
        return threading.get_ident()

    loop_thread = asyncio.run(drive())
    assert opened and loop_thread not in opened, "the event was counted on the event loop"
    assert [(t, th == loop_thread) for t, th, _e in woken] == [("t1", True)]
    db = maker()
    try:
        task = db.get(ScheduledTask, "t1")
        assert task.pending_trigger and task.next_run is not None
    finally:
        db.close()
        engine.dispose()


def test_the_writes_a_person_makes_first_are_off_the_loop():
    left = {(f, name) for f, _line, name in on_the_loop()}
    for f, name in [("routes/chat_routes.py", "chat_stream"),
                    ("routes/document/document_routes.py", "create_document"),
                    ("routes/document/document_routes.py", "update_document"),
                    ("routes/document/document_routes.py", "patch_document"),
                    ("routes/task/task_routes.py", "update_task")]:
        assert (f, name) not in left, f"{name} is back on the loop"


def test_an_event_a_plain_route_fires_is_handled_on_the_apps_loop(monkeypatch):
    """`fire_event` from a `def` route runs in Starlette's thread pool, where no
    loop runs. It ran the handler there under `asyncio.run` — a second loop,
    beside the app's, while the scheduler it reaches lives on the app's. It is
    handed to the app's loop now, and the route does not wait for it."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import src.event_bus as bus

    seen = {}
    handled = threading.Event()

    async def handle(event_name, owner, payload, origin=None):
        seen["loop"] = id(asyncio.get_running_loop())
        seen["event"] = event_name
        handled.set()

    monkeypatch.setattr(bus, "_handle_event", handle)
    app = FastAPI()

    @app.get("/loop")
    async def the_apps_loop():
        return {"loop": id(asyncio.get_running_loop())}

    @app.post("/save")
    def save():
        bus.fire_event("document_updated", owner="alice")
        return {"thread": threading.current_thread().name}

    with TestClient(app) as client:
        app_loop = client.get("/loop").json()["loop"]
        assert client.post("/save").status_code == 200
        assert handled.wait(5), "the event was never handled"
    assert seen == {"loop": app_loop, "event": "document_updated"}


def test_a_model_call_reads_and_writes_the_database_off_the_loop(tmp_path, monkeypatch, wire):
    """`B1588`, driven: `llm_call_async` and `stream_llm` against a local
    MiniMax endpoint the endpoint table names as local, inside a run, with only
    the socket faked (`wire`). Every session either opens — the endpoint-kind
    reads, the context window, the run-config row — is opened on a worker
    thread; the row is in the table when the call returns (awaited, not fired
    and forgotten); and the payload still carries the local profile, so the
    reads that moved still decided what was sent."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import src.llm_core as llm_core
    from core.database import Base, Event, ModelEndpoint
    from src import events as ev

    engine = create_engine(f"sqlite:///{tmp_path}/model.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine, tables=[Event.__table__, ModelEndpoint.__table__])
    maker = sessionmaker(bind=engine)
    db = maker()
    db.add(ModelEndpoint(id="ep1", name="Box", base_url="http://models.lan:8091/v1",
                         endpoint_kind="local", is_enabled=True))
    db.commit()
    db.close()
    opened = _sessions_by_thread(monkeypatch, maker)
    monkeypatch.setattr(ev, "_last_prune", 0.0)
    url = "http://models.lan:8091/v1/chat/completions"
    model = "example-org/MiniMax-M2.7-BF16-mlx-4Bit"

    async def drive():
        loop_thread = threading.get_ident()
        for door in ("call", "stream"):
            ev._turn_started.set(None)
            ev._run_id.set(None)
            llm_core._run_config_recorded.set(False)
            llm_core._run_config_had_tools.set(False)
            ev.mark_turn_start()
            if door == "call":
                await llm_core.llm_call_async(url, model, [{"role": "user", "content": "hi"}],
                                              session_id="s1")
            else:
                async for _chunk in llm_core.stream_llm(url, model, [{"role": "user", "content": "hi"}],
                                                        session_id="s1"):
                    pass
        return loop_thread

    loop_thread = asyncio.run(drive())
    assert opened, "nothing read the endpoint table — the drive is not measuring the row"
    assert loop_thread not in opened, "a session was opened on the event loop"
    db = maker()
    try:
        rows = db.query(Event).filter(Event.kind == "run_config").count()
    finally:
        db.close()
        engine.dispose()
    assert rows == 2, f"one run-config row per door, written before the call returned; got {rows}"
    assert [payload.get("temperature") for _url, payload in wire.sent] == [0.2, 0.2], (
        "the local profile was not applied — the endpoint read that moved decided nothing")


def test_the_helpers_b1598_split_reach_no_session_on_the_loop():
    """`B1598`. The async helpers the 25 handlers awaited reach no database
    session on the event loop — their reads and writes are handed to threads —
    and the scan is not blind there: the sync parts they hand off still do."""
    trees = _every_tree()
    split = [("src.workflow_assist", "ask_for_json"), ("src.caldav_writeback", "writeback_event"),
             ("src.caldav_sync", "sync_caldav_direction"), ("src.service_health", "collect_service_health"),
             ("src.replay", "replay"), ("src.evals", "run_suite"), ("src.integrations", "execute_api_call"),
             ("src.teacher_escalation", "evaluate_turn_llm"), ("src.context_compactor", "maybe_compact"),
             ("routes.chat_helpers", "build_chat_context"), ("routes.chat_helpers", "auto_name_session"),
             ("routes.note.note_routes", "dispatch_reminder"), ("src.agent_loop", "stream_agent_loop"),
             ("services.memory.skill_improve", "improve_from_lint")]
    on_loop = [f"{m}.{f}" for m, f in split if reaches_a_session(m, f, trees)]
    assert on_loop == [], f"these open a database session on the event loop: {on_loop}"
    for m, f in [("src.workflow_assist", "_endpoint"), ("src.caldav_writeback", "_writeback_account"),
                 ("src.service_health", "_gather_inputs"), ("src.replay", "rerun_plan")]:
        assert reaches_a_session(m, f, trees), f"{m}.{f} — the scan no longer sees the work it moved"


def test_the_workflow_assistant_reads_its_endpoint_off_the_loop(tmp_path, monkeypatch):
    """Driven: `ask_for_json` — the door the agent workshop, design extraction,
    the task parser and the workflow example writer share — over a real SQLite
    endpoint table, the model call stood in for. Its session opens on a worker
    thread, and the answer is the one the endpoint row decides."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import src.llm_core as llm_core
    from core.database import Base, ModelEndpoint
    from src import workflow_assist

    engine = create_engine(f"sqlite:///{tmp_path}/assist.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine, tables=[ModelEndpoint.__table__])
    maker = sessionmaker(bind=engine)
    db = maker()
    db.add(ModelEndpoint(id="ep1", name="Box", base_url="http://models.lan:8091/v1",
                         endpoint_kind="local", is_enabled=True, model_type="chat",
                         cached_models='["util-model"]'))
    db.commit()
    db.close()
    import src.endpoint_resolver as resolver
    # The settings name the endpoint; everything after that is the real
    # resolver over the real table.
    monkeypatch.setattr(resolver, "_configured_entry",
                        lambda prefix, owner=None, has_fallback=False: ("ep1", "util-model"))
    asked = []

    async def model(url=None, model=None, messages=None, **kw):
        asked.append((url, model))
        return '{"ok": true}'

    monkeypatch.setattr(llm_core, "llm_call_async", model)
    opened = _sessions_by_thread(monkeypatch, maker)
    # The resolver holds its own binding of the session factory.
    monkeypatch.setattr(resolver, "SessionLocal", __import__("core.database").database.SessionLocal)

    async def drive():
        return threading.get_ident(), await workflow_assist.ask_for_json(
            "alice", [{"role": "user", "content": "x"}], max_tokens=10)

    loop_thread, (found, problem) = asyncio.run(drive())
    engine.dispose()
    assert asked == [("http://models.lan:8091/v1/chat/completions", "util-model")], (asked, problem)
    assert found == {"ok": True} and problem is None
    assert opened and loop_thread not in opened, "the endpoint was read on the event loop"


def test_a_caldav_push_reads_and_writes_its_rows_off_the_loop(tmp_path, monkeypatch):
    """Driven: `writeback_event` with two CalDAV accounts (so the calendar's
    row is read to choose one), the network push stood in for, and the real
    result write — every session on a worker thread, the event's pending flag
    cleared when it returns."""
    import datetime as dt

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import src.caldav_sync as caldav_sync
    import src.caldav_writeback as wb
    from core.database import Base, CalendarCal, CalendarDeletedEvent, CalendarEvent

    engine = create_engine(f"sqlite:///{tmp_path}/cal.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine, tables=[CalendarCal.__table__, CalendarEvent.__table__,
                                                  CalendarDeletedEvent.__table__])
    maker = sessionmaker(bind=engine)
    db = maker()
    db.add(CalendarCal(id="cal1", owner="alice", name="Work", source="caldav", account_id="acc2"))
    start = dt.datetime(2026, 11, 3, 9, 0)
    db.add(CalendarEvent(uid="ev1", calendar_id="cal1", summary="Standup", dtstart=start,
                         dtend=start + dt.timedelta(minutes=15), caldav_sync_pending="update"))
    db.commit()
    db.close()
    accounts = [{"id": "acc1", "url": "https://one.example/dav", "username": "a", "password": "x"},
                {"id": "acc2", "url": "https://two.example/dav", "username": "b", "password": "y"}]
    monkeypatch.setattr(caldav_sync, "_load_caldav_accounts", lambda owner: accounts)
    monkeypatch.setattr(caldav_sync, "validate_caldav_url", lambda url: url)
    monkeypatch.setattr("src.secret_storage.decrypt", lambda value: value)
    pushed = []

    def push(cal, ev, delete, url, user, pw, owner, acc_id):
        pushed.append((url, acc_id))
        return {"ok": True, "remote_href": "/two/ev1.ics"}

    monkeypatch.setattr(wb, "_writeback_blocking", push)
    opened = _sessions_by_thread(monkeypatch, maker)

    async def drive():
        return threading.get_ident(), await wb.writeback_event("alice", "caldav", "cal1", {"uid": "ev1"})

    loop_thread, out = asyncio.run(drive())
    assert out.get("ok") and pushed == [("https://two.example/dav", "acc2")], (out, pushed)
    assert opened and loop_thread not in opened, "a session was opened on the event loop"
    db = maker()
    try:
        ev = db.query(CalendarEvent).filter(CalendarEvent.uid == "ev1").one()
        assert ev.caldav_sync_pending is None and ev.remote_href == "/two/ev1.ics"
    finally:
        db.close()
        engine.dispose()
