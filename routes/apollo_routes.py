# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's routes: the person's tasks, notebook and what Apollo knows.

Every route is the signed-in person's own. A task, a note or a line of what
Apollo knows that belongs to someone else answers 404, the same as one that
does not exist, so one person cannot learn whether another's exists.

The admin's per-goal cap is an ordinary install setting
(`apollo_goal_token_cap`, Settings), so there is no admin route here; `GET
/api/apollo/state` only reads it, so the pane can show a person what their own
budget sits under.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.database import SessionLocal
from src.apollo import APOLLO_NAME
from src.apollo import budget as B
from src.apollo import knows, notebook, tasks
from src.apollo.errors import ApolloRefused
from src.auth_helpers import get_current_user
from src.owner_identity import REQUEST_SENTINEL_OWNERS


class TaskIn(BaseModel):
    title: str
    brief: Optional[str] = None
    kind: Optional[str] = None
    parent_id: Optional[str] = None
    lead_agent: Optional[str] = None
    budget_tokens: Optional[int] = None
    start: bool = True


class TaskPatch(BaseModel):
    title: Optional[str] = None
    brief: Optional[str] = None
    kind: Optional[str] = None
    lead_agent: Optional[str] = None
    budget_tokens: Optional[int] = None
    next_step: Optional[str] = None
    state: Optional[str] = None
    question: Optional[str] = None
    outcome: Optional[str] = None


class AnswerIn(BaseModel):
    answer: str


class SaidIn(BaseModel):
    words: str


class NoteState(BaseModel):
    state: str


class LineIn(BaseModel):
    text: str
    basis: str = "stated"
    category: str = "fact"
    evidence: Optional[str] = None


class LineEdit(BaseModel):
    text: str


def _refused(err: ApolloRefused) -> JSONResponse:
    return JSONResponse(err.body(), status_code=err.status)


def setup_apollo_routes() -> APIRouter:
    from fastapi import Depends as _Depends
    from src.tool_privileges import everyone_switch as _everyone_switch, tool_privilege as _tool_privilege
    # Apollo is the Assistant, so the Assistant's switches are its switches.
    router = APIRouter(prefix="/api/apollo", tags=["apollo"],
                       dependencies=[_Depends(_everyone_switch("can_use_assistant")),
                                     _Depends(_tool_privilege("can_use_assistant"))])

    def _owner(request: Request) -> str:
        owner = get_current_user(request)
        if not owner or owner in REQUEST_SENTINEL_OWNERS:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return owner

    def _in_db(fn):
        db = SessionLocal()
        try:
            out = fn(db)
            db.commit()
            return out
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _call(fn) -> Any:
        try:
            return await asyncio.to_thread(_in_db, fn)
        except ApolloRefused as err:
            return _refused(err)

    async def _plain(fn) -> Any:
        try:
            return await asyncio.to_thread(fn)
        except ApolloRefused as err:
            return _refused(err)

    @router.get("/state")
    async def state(request: Request):
        owner = _owner(request)

        def read(db) -> Dict[str, Any]:
            cap = B.admin_cap()
            return {"name": APOLLO_NAME, "status": tasks.status(db, owner),
                    "goal_token_cap": cap,
                    "open_loops": [notebook.to_dict(n) for n in notebook.list_for(
                        db, owner, kind="open_loop", state="open", limit=20)]}
        return await _call(read)

    @router.get("/tasks")
    async def list_tasks(request: Request, state: Optional[str] = None, include_done: bool = True):
        owner = _owner(request)

        def read(db):
            cap = B.admin_cap()
            if state and state not in tasks.STATES:
                raise ApolloRefused(f"A task is one of: {', '.join(tasks.STATES)}.")
            return {"tasks": [tasks.to_dict(t, budget_cap=cap) for t in tasks.list_for(
                db, owner, state=state, include_done=include_done)]}
        return await _call(read)

    @router.post("/tasks")
    async def create_task(request: Request, body: TaskIn):
        owner = _owner(request)
        holder: Dict[str, Any] = {}

        def write(db):
            t = tasks.create(db, owner, title=body.title, brief=body.brief, kind=body.kind,
                             parent_id=body.parent_id, lead_agent=body.lead_agent,
                             budget_tokens=body.budget_tokens, started_by="person")
            if body.start and t.lead_agent:
                from src.apollo import runs
                holder["run"], _why = runs.prepare(db, owner, t,
                                                   auth_manager=getattr(request.app.state, "auth_manager", None))
            return t
        out = await _call(lambda db: tasks.to_dict(write(db), budget_cap=B.admin_cap()))
        if holder.get("run"):
            from src.apollo.tool import start_run
            await start_run(holder["run"])
        return out

    @router.get("/tasks/{task_id}")
    async def get_task(request: Request, task_id: str):
        owner = _owner(request)
        return await _call(lambda db: tasks.to_dict(tasks.get(db, owner, task_id),
                                                    budget_cap=B.admin_cap()))

    @router.patch("/tasks/{task_id}")
    async def patch_task(request: Request, task_id: str, body: TaskPatch):
        owner = _owner(request)
        fields = body.model_dump(exclude_unset=True)
        return await _call(lambda db: tasks.to_dict(tasks.update(db, owner, task_id, fields),
                                                    budget_cap=B.admin_cap()))

    async def _start(request: Request, owner: str, task_id: str, before=None):
        holder: Dict[str, Any] = {}

        def write(db):
            t = tasks.get(db, owner, task_id)
            if before is not None:
                t = before(db)
            if t.lead_agent:
                from src.apollo import runs
                holder["run"], holder["why"] = runs.prepare(
                    db, owner, t, auth_manager=getattr(request.app.state, "auth_manager", None))
            return tasks.to_dict(t, budget_cap=B.admin_cap())
        out = await _call(write)
        if isinstance(out, dict) and holder.get("run"):
            from src.apollo.tool import start_run
            out["started"] = await start_run(holder["run"])
        elif isinstance(out, dict):
            out["started"] = False
            if holder.get("why"):
                out["why"] = holder["why"]
        return out

    @router.post("/tasks/{task_id}/start")
    async def start_task(request: Request, task_id: str):
        owner = _owner(request)
        return await _start(request, owner, task_id)

    @router.post("/tasks/{task_id}/answer")
    async def answer_task(request: Request, task_id: str, body: AnswerIn):
        owner = _owner(request)
        # The answer goes on the task, then its lead runs again with it.
        return await _start(request, owner, task_id,
                            before=lambda db: tasks.answer(db, owner, task_id, body.answer))

    @router.get("/tasks/{task_id}/chat")
    async def task_chat(request: Request, task_id: str):
        """The chat bound to this task's lead: the one its runs write into."""
        owner = _owner(request)
        from src.apollo import chat
        return await _call(lambda db: chat.task_chat(db, owner, task_id))

    @router.post("/tasks/{task_id}/said")
    async def task_said(request: Request, task_id: str, body: SaidIn):
        """The person spoke to the task's lead in its chat: Apollo's chat gets
        one line about it, never the conversation itself."""
        owner = _owner(request)
        from src.apollo import chat

        def line(db):
            found = chat.task_chat(db, owner, task_id)
            task = tasks.get(db, owner, task_id)
            return chat.said_line(task, body.words, lead=found["lead"])
        out = await _call(line)
        if not isinstance(out, str):
            return out
        posted = await asyncio.to_thread(
            chat.post_line, getattr(request.app.state, "session_manager", None), owner, out,
            {"source": "apollo", "apollo_task_id": task_id, "kind": "task_chat"})
        return {"line": out, "posted": posted}

    @router.get("/approvals")
    async def approvals(request: Request):
        """What the person's leads are waiting on their OK for, run by run."""
        owner = _owner(request)
        from src.apollo import chat
        return await _call(lambda db: {"approvals": chat.waiting_approvals(db, owner)})

    @router.get("/notebook")
    async def list_notes(request: Request, kind: Optional[str] = None, state: Optional[str] = None):
        owner = _owner(request)
        return await _call(lambda db: {"notes": [notebook.to_dict(n) for n in notebook.list_for(
            db, owner, kind=kind, state=state)]})

    @router.patch("/notebook/{note_id}")
    async def set_note_state(request: Request, note_id: str, body: NoteState):
        owner = _owner(request)
        return await _call(lambda db: notebook.to_dict(notebook.set_state(db, owner, note_id, body.state)))

    @router.get("/knows")
    async def what_it_knows(request: Request):
        owner = _owner(request)
        return await _plain(lambda: {"lines": knows.what_apollo_knows(owner)})

    @router.post("/knows")
    async def tell_it(request: Request, body: LineIn):
        owner = _owner(request)
        # What a person types on the page is theirs by definition: stated.
        return await _plain(lambda: knows.remember(owner, body.text, basis="stated",
                                                   category=body.category))

    @router.post("/knows/{line_id}/confirm")
    async def confirm_line(request: Request, line_id: str):
        owner = _owner(request)
        return await _plain(lambda: knows.confirm(owner, line_id))

    @router.patch("/knows/{line_id}")
    async def edit_line(request: Request, line_id: str, body: LineEdit):
        owner = _owner(request)
        return await _plain(lambda: knows.edit(owner, line_id, body.text))

    @router.delete("/knows/{line_id}")
    async def forget_line(request: Request, line_id: str):
        owner = _owner(request)
        return await _plain(lambda: {"forgotten": knows.forget(owner, line_id)})

    return router
