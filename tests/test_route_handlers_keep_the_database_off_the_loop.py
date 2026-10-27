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
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import threading

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


#: `B1580`. The ceiling through helpers: 51 after `B1580`, from 107.
MAX_THROUGH_A_HELPER = 51

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


def through_a_helper(trees=None):
    """`[(file, line, handler, helper)]` — every async route handler that
    reaches a database session through a function it calls (`B1580`).

    `trees` is `{module: (path, tree)}`; by default every module in `_SCOPE`
    and `app.py`. A handler counted by `on_the_loop()` is counted here too."""
    if trees is None:
        trees = {}
        for top in _SCOPE:
            for path in sorted((ROOT / top).glob("**/*.py")):
                trees[_module_name(path)] = (path, ast.parse(path.read_text(encoding="utf-8")))
        trees["app"] = (ROOT / "app.py", ast.parse((ROOT / "app.py").read_text(encoding="utf-8")))
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
