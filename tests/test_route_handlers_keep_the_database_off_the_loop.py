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
the active document, a summoned agent), document save, task edit. What is left
is listed by this file when it fails, and `MAX_ON_THE_LOOP` is lowered with
each one moved — never raised (`Law 13`'s ratchet, in a test).

The behaviour is driven in
`tests/test_a_save_waits_for_a_held_lock_without_stalling_the_server.py`.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The ceiling. Lower it when a handler moves; a rise is a handler that put
#: its database work back on the loop.
MAX_ON_THE_LOOP = 58

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
