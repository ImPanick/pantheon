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
from src.apollo import conversations, knows, notebook, rhythm, spaces, trust, tasks, voice
from src.apollo.errors import ApolloRefused
from core.middleware import require_admin
from src.auth_helpers import get_current_user
from src.owner_identity import REQUEST_SENTINEL_OWNERS


class TaskIn(BaseModel):
    title: str
    space_id: Optional[str] = None
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
    space_id: Optional[str] = None


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


class SpaceIn(BaseModel):
    name: str
    parent_id: Optional[str] = None
    airgapped: bool = False


class NewConversationIn(BaseModel):
    space_id: Optional[str] = None


class SpacePatch(BaseModel):
    name: Optional[str] = None
    airgapped: Optional[bool] = None
    local_only: Optional[bool] = None


class GrantIn(BaseModel):
    source_id: str
    scope: str


class BriefingIn(BaseModel):
    id: Optional[str] = None
    time: str
    enabled: bool = True


class QuietIn(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


class VoiceIn(BaseModel):
    warmth: Optional[int] = None
    play: Optional[int] = None
    preset: Optional[str] = None


class OfferAnswer(BaseModel):
    answer: str


class RhythmIn(BaseModel):
    briefings: Optional[list[BriefingIn]] = None
    checkin_hours: Optional[int] = None
    quiet: Optional[QuietIn] = None


class ReviewNote(BaseModel):
    note: Optional[str] = None


class AgentText(BaseModel):
    text: str


class RollbackIn(BaseModel):
    version: str


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

    def _view(db, owner: str, space: Optional[str]):
        """`?space=`: `all` (or absent) is every space but the sealed ones;
        `top` is Apollo's own layer; anything else is one of the person's
        spaces, read on its own."""
        if space in (None, "", spaces.ALL):
            return spaces.ALL
        return spaces.resolve(db, owner, space)

    def _where(db, owner: str, space: Optional[str]):
        """The scope a What-Apollo-knows call stands in; None for the All view."""
        if space in (None, "", spaces.ALL):
            return None
        return spaces.scope(db, owner, spaces.resolve(db, owner, space), "memory")

    @router.get("/state")
    async def state(request: Request, space: Optional[str] = None):
        owner = _owner(request)

        def read(db) -> Dict[str, Any]:
            cap = B.admin_cap()
            view = _view(db, owner, space)
            out = {"name": APOLLO_NAME, "status": tasks.status(db, owner, space=view),
                   "goal_token_cap": cap, "space": None,
                   "open_loops": [notebook.to_dict(n) for n in notebook.list_for(
                       db, owner, kind="open_loop", state="open", limit=20, space=view)]}
            if view != spaces.ALL:
                out["children"] = spaces.children(db, owner, view)
                if view is not None:
                    out["space"] = spaces.to_dict(spaces.get(db, owner, view), spaces._all(db, owner))
            return out
        return await _call(read)

    def _led(owner: str, d, names: Optional[Dict[str, str]] = None):
        """`d` (a task as `tasks.to_dict` writes it) with `lead_name`: the
        lead's own name, so Apollo's deck can say who leads each goal without
        a lookup per card. A lead the catalogue no longer has keeps its id."""
        if not isinstance(d, dict) or "lead_agent" not in d:
            return d
        from src.apollo import fleet
        key = d.get("lead_agent") or ""
        names = {} if names is None else names
        if key not in names:
            names[key] = fleet._agent_name(owner, d.get("lead_agent"))
        d["lead_name"] = names[key]
        return d

    @router.get("/tasks")
    async def list_tasks(request: Request, state: Optional[str] = None, include_done: bool = True,
                         space: Optional[str] = None):
        owner = _owner(request)

        def read(db):
            cap = B.admin_cap()
            if state and state not in tasks.STATES:
                raise ApolloRefused(f"A task is one of: {', '.join(tasks.STATES)}.")
            names: Dict[str, str] = {}
            return {"tasks": [_led(owner, tasks.to_dict(t, budget_cap=cap), names) for t in tasks.list_for(
                db, owner, state=state, include_done=include_done, space=_view(db, owner, space))]}
        return await _call(read)

    @router.post("/tasks")
    async def create_task(request: Request, body: TaskIn):
        owner = _owner(request)
        holder: Dict[str, Any] = {}

        def write(db):
            t = tasks.create(db, owner, title=body.title, brief=body.brief, kind=body.kind,
                             parent_id=body.parent_id, lead_agent=body.lead_agent,
                             budget_tokens=body.budget_tokens, started_by="person",
                             space_id=body.space_id)
            if body.start and t.lead_agent:
                from src.apollo import runs
                holder["run"], _why = runs.prepare(db, owner, t,
                                                   auth_manager=getattr(request.app.state, "auth_manager", None))
            return t
        out = await _call(lambda db: _led(owner, tasks.to_dict(write(db), budget_cap=B.admin_cap())))
        if holder.get("run"):
            from src.apollo.tool import start_run
            if not await start_run(holder["run"]):
                out = await _not_started(owner, out["id"])
        return out

    async def _not_started(owner: str, task_id: str) -> Dict[str, Any]:
        """A run that was asked for and didn't start leaves the goal asking, not Working."""
        from src.apollo import runs
        out = await _call(lambda db: _led(owner, tasks.to_dict(runs.did_not_start(db, owner, task_id),
                                                              budget_cap=B.admin_cap())))
        if isinstance(out, dict):
            out["started"] = False
        return out

    @router.get("/tasks/{task_id}")
    async def get_task(request: Request, task_id: str):
        owner = _owner(request)
        return await _call(lambda db: _led(owner, tasks.to_dict(tasks.get(db, owner, task_id),
                                                                budget_cap=B.admin_cap())))

    @router.patch("/tasks/{task_id}")
    async def patch_task(request: Request, task_id: str, body: TaskPatch):
        owner = _owner(request)
        fields = body.model_dump(exclude_unset=True)
        return await _call(lambda db: tasks.to_dict(tasks.update(db, owner, task_id, fields),
                                                    budget_cap=B.admin_cap()))

    async def _start(request: Request, owner: str, task_id: str, before=None):
        holder: Dict[str, Any] = {}

        def write(db):
            from src.apollo import runs
            t = tasks.get(db, owner, task_id)
            if before is not None:
                t = before(db)
            moved = getattr(t, "_fleet_moved", None)
            if moved is not None:
                # A review the person answered: a pass moves the goal on
                # without running this task again; changes run its lead.
                holder["next"] = runs.prepare_all(db, owner, moved["start"], None)
            if t.lead_agent and (moved is None or moved["run_this"]):
                holder["run"], holder["why"] = runs.prepare(
                    db, owner, t, auth_manager=getattr(request.app.state, "auth_manager", None))
            return _led(owner, tasks.to_dict(t, budget_cap=B.admin_cap()))
        out = await _call(write)
        if isinstance(out, dict) and holder.get("next"):
            from src.apollo.tool import start_run
            for run in holder["next"]:
                await start_run(run)
        if isinstance(out, dict) and holder.get("run"):
            from src.apollo.tool import start_run
            if await start_run(holder["run"]):
                out["started"] = True
            else:
                out = await _not_started(owner, out["id"])
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

    @router.get("/tasks/{task_id}/team")
    async def task_team(request: Request, task_id: str):
        """Phase 5. Who is working on this task's goal and what they said to
        each other: the goal and every delegate under it, and the goal's log."""
        owner = _owner(request)
        from src.apollo import fleet as F
        return await _call(lambda db: F.team(db, owner, tasks.get(db, owner, task_id)))

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
    async def approvals(request: Request, space: Optional[str] = None):
        """What the person's leads are waiting on their OK for, run by run."""
        owner = _owner(request)
        from src.apollo import chat
        return await _call(lambda db: {"approvals": chat.waiting_approvals(
            db, owner, space=_view(db, owner, space))})

    @router.get("/notebook")
    async def list_notes(request: Request, kind: Optional[str] = None, state: Optional[str] = None,
                         space: Optional[str] = None):
        owner = _owner(request)
        return await _call(lambda db: {"notes": [notebook.to_dict(n) for n in notebook.list_for(
            db, owner, kind=kind, state=state, space=_view(db, owner, space))]})

    @router.patch("/notebook/{note_id}")
    async def set_note_state(request: Request, note_id: str, body: NoteState):
        owner = _owner(request)
        return await _call(lambda db: notebook.to_dict(notebook.set_state(db, owner, note_id, body.state)))

    @router.get("/knows")
    async def what_it_knows(request: Request, space: Optional[str] = None):
        owner = _owner(request)
        return await _call(lambda db: {"lines": knows.what_apollo_knows(owner, _where(db, owner, space))})

    @router.post("/knows")
    async def tell_it(request: Request, body: LineIn, space: Optional[str] = None):
        owner = _owner(request)
        # What a person types on the page is theirs by definition: stated.
        return await _call(lambda db: knows.remember(owner, body.text, basis="stated",
                                                     category=body.category,
                                                     where=_where(db, owner, space)))

    @router.post("/knows/{line_id}/confirm")
    async def confirm_line(request: Request, line_id: str, space: Optional[str] = None):
        owner = _owner(request)
        return await _call(lambda db: knows.confirm(owner, line_id, _where(db, owner, space)))

    @router.patch("/knows/{line_id}")
    async def edit_line(request: Request, line_id: str, body: LineEdit, space: Optional[str] = None):
        owner = _owner(request)
        return await _call(lambda db: knows.edit(owner, line_id, body.text, _where(db, owner, space)))

    @router.delete("/knows/{line_id}")
    async def forget_line(request: Request, line_id: str, space: Optional[str] = None):
        owner = _owner(request)
        return await _call(lambda db: {"forgotten": knows.forget(owner, line_id, _where(db, owner, space))})

    # -- spaces --------------------------------------------------------------

    @router.get("/spaces")
    async def list_spaces(request: Request):
        """Every space, parents before children, with what each holds open."""
        owner = _owner(request)

        def read(db):
            rows = spaces.tree(db, owner)
            kids: Dict[str, Any] = {}
            for parent in {r["parent_id"] for r in rows}:
                kids.update({k["id"]: k for k in spaces.children(db, owner, parent)})
            for r in rows:
                k = kids.get(r["id"], {})
                r["needs_you"] = k.get("needs_you")
                r["open"] = k.get("open")
            return {"spaces": rows}
        return await _call(read)

    @router.post("/spaces")
    async def make_space(request: Request, body: SpaceIn):
        owner = _owner(request)
        return await _call(lambda db: spaces.to_dict(
            spaces.create(db, owner, body.name, parent_id=body.parent_id, airgapped=body.airgapped),
            spaces._all(db, owner)))

    @router.patch("/spaces/{space_id}")
    async def change_space(request: Request, space_id: str, body: SpacePatch):
        """Rename, airgap on or off, local models only on or off."""
        owner = _owner(request)
        fields = body.model_dump(exclude_unset=True)

        def write(db):
            row = spaces.get(db, owner, space_id)
            if "name" in fields:
                spaces.rename(db, owner, row.id, fields["name"])
            if "airgapped" in fields:
                spaces.set_airgap(db, owner, row.id, bool(fields["airgapped"]))
            if "local_only" in fields:
                spaces.set_local_only(db, owner, row.id, bool(fields["local_only"]))
            return spaces.to_dict(row, spaces._all(db, owner))
        return await _call(write)

    @router.delete("/spaces/{space_id}")
    async def delete_space(request: Request, space_id: str):
        owner = _owner(request)

        def write(db):
            spaces.remove(db, owner, space_id)
            return {"deleted": True}
        return await _call(write)

    @router.get("/spaces/{space_id}/context")
    async def space_context(request: Request, space_id: str):
        """What the space reads from, what reads from it, and its grants' uses."""
        owner = _owner(request)
        return await _call(lambda db: spaces.context(db, owner, space_id))

    @router.post("/spaces/{space_id}/grants")
    async def give_grant(request: Request, space_id: str, body: GrantIn):
        """Let this space read another's memory or outcomes, one way, read only."""
        owner = _owner(request)
        return await _call(lambda db: {"grant_id": spaces.grant(
            db, owner, space_id, body.source_id, body.scope).id})

    @router.delete("/grants/{grant_id}")
    async def revoke_grant(request: Request, grant_id: str):
        owner = _owner(request)
        return await _call(lambda db: {"revoked": bool(spaces.revoke(db, owner, grant_id).revoked_at)})

    @router.post("/spaces/{space_id}/chat")
    async def space_chat(request: Request, space_id: str):
        """The space's own Apollo chat (`top` is Apollo's main chat), made the
        first time it's opened."""
        owner = _owner(request)
        return await _call(lambda db: {"session_id": spaces.chat_for(
            db, owner, spaces.resolve(db, owner, space_id))})

    @router.post("/conversations/new")
    async def new_conversation(request: Request, body: Optional[NewConversationIn] = None):
        """Start a new Apollo conversation. Tasks, the notebook, what Apollo
        knows and Spaces stay; the old chat is kept as an earlier one."""
        owner = _owner(request)
        space = body.space_id if body else None
        return await _call(lambda db: conversations.start_new(
            db, owner, spaces.resolve(db, owner, space) if space else None))

    @router.get("/conversations/earlier")
    async def earlier_conversations(request: Request):
        """The person's earlier Apollo conversations, newest first."""
        owner = _owner(request)
        return await _call(lambda db: {"conversations": conversations.earlier(db, owner)})

    @router.get("/rhythm")
    async def get_rhythm(request: Request):
        """When Apollo speaks unasked: the person's briefings, how often
        check-ins look, quiet hours, and when Apollo last spoke."""
        owner = _owner(request)
        return await _call(lambda db: rhythm.to_dict(db, owner))

    @router.put("/rhythm")
    async def set_rhythm(request: Request, body: RhythmIn):
        """Set any of the three. Briefings are the whole list, in any order;
        the earliest is First light."""
        owner = _owner(request)
        fields = body.model_dump(exclude_unset=True)
        return await _call(lambda db: rhythm.save(
            db, owner, briefings=fields.get("briefings"), checkin_hours=fields.get("checkin_hours"),
            quiet=fields.get("quiet") if "quiet" in fields else None))

    @router.get("/voice")
    async def get_voice(request: Request):
        """Apollo's dials, its presets, the nudges it made that still stand,
        and how its talk model held up when pushed to agree (`pushback.py`)."""
        owner = _owner(request)

        def read(db):
            out = voice.to_dict(db, owner)
            from src.apollo import pushback
            out["held"] = pushback.fit_for(db, owner)
            return out
        return await _call(read)

    @router.put("/voice")
    async def set_voice(request: Request, body: VoiceIn):
        owner = _owner(request)
        fields = body.model_dump(exclude_unset=True)
        return await _call(lambda db: voice.set_voice(db, owner, **fields))

    @router.post("/voice/undo/{change_id}")
    async def undo_voice(request: Request, change_id: str):
        """One tap: put a dial back where a change found it."""
        owner = _owner(request)
        return await _call(lambda db: voice.undo(db, owner, change_id))

    @router.get("/trust")
    async def get_trust(request: Request, space: Optional[str] = None, state: Optional[str] = None):
        """Per kind of work and action: Apollo asks, offers to just do it, or
        just does it, with the record behind each."""
        owner = _owner(request)
        return await _call(lambda db: {"trust": trust.list_for(db, owner, space=_view(db, owner, space),
                                                               state=state or None)})

    @router.post("/trust/{trust_id}")
    async def answer_offer(request: Request, trust_id: str, body: OfferAnswer):
        """Yes or not now to "just do it" for a kind. Yes needs the admin's
        ceiling, the privilege Auto mode is held to."""
        owner = _owner(request)
        said = (body.answer or "").strip().lower()
        if said not in ("yes", "no"):  # flag-spelling: the two answers an offer card sends, not a flag
            raise HTTPException(400, "The answer is yes or no.")
        if said == "yes":
            from src.approval_mode import may_use_auto
            auth = getattr(request.app.state, "auth_manager", None)
            ok = await asyncio.to_thread(may_use_auto, owner, auth_manager=auth)
        else:
            ok = False
        return await _call(lambda db: trust.answer(db, owner, trust_id, said == "yes", may_auto=ok))

    @router.delete("/trust/{trust_id}")
    async def take_back_trust(request: Request, trust_id: str):
        """Apollo asks again for this kind, and its record starts over."""
        owner = _owner(request)
        return await _call(lambda db: trust.take_back(db, owner, trust_id))

    # ── Phase 5b: a missing agent, drafted, proven and approved ─────────────

    @router.get("/agents/proposals")
    async def my_proposals(request: Request):
        """The agents being made for this person, and what became of each."""
        owner = _owner(request)
        from src.apollo import gaps as G
        return await _call(lambda db: {"proposals": G.list_for(db, owner)})

    @router.post("/agents/proposals/{pid}/retry")
    async def retry_proposal(request: Request, pid: str):
        owner = _owner(request)
        from src.apollo import gaps as G
        out = await _call(lambda db: G.to_dict(G.retry(db, owner, pid)))
        if isinstance(out, dict):
            G.start_build(pid)
        return out

    @router.get("/agents/review")
    async def review_agents(request: Request):
        """For an admin: every drafted agent waiting on a decision, with the
        tools and effects it asks for beside its proof, and every platform
        agent's versions."""
        require_admin(request)
        from src.apollo import gaps as G
        return await _call(lambda db: {"waiting": G.waiting(db), "published": G.published()})

    @router.post("/agents/review/{pid}/approve")
    async def approve_agent(request: Request, pid: str):
        require_admin(request)
        admin = _owner(request)
        from src.apollo import gaps as G
        return await _call(lambda db: G.approve(db, admin, pid))

    @router.post("/agents/review/{pid}/edit")
    async def edit_agent(request: Request, pid: str, body: AgentText):
        """An admin's edit is checked now, then proven again before it can be
        approved."""
        require_admin(request)
        admin = _owner(request)
        from src.apollo import gaps as G
        out = await _call(lambda db: G.edit(db, admin, pid, body.text))
        if isinstance(out, dict):
            G.start_build(pid, text=body.text)
        return out

    @router.post("/agents/review/{pid}/reject")
    async def reject_agent(request: Request, pid: str, body: ReviewNote):
        require_admin(request)
        admin = _owner(request)
        from src.apollo import gaps as G
        return await _call(lambda db: G.reject(db, admin, pid, body.note))

    @router.post("/agents/platform/{agent_id}/update")
    async def update_platform_agent(request: Request, agent_id: str, body: AgentText):
        """A new version of a published agent, proven before it can be
        approved, like a new one."""
        require_admin(request)
        admin = _owner(request)
        from src.apollo import gaps as G
        out = await _call(lambda db: G.to_dict(G.propose_update(db, admin, agent_id, body.text)))
        if isinstance(out, dict):
            G.start_build(out["id"], text=body.text)
        return out

    @router.post("/agents/platform/{agent_id}/rollback")
    async def rollback_platform_agent(request: Request, agent_id: str, body: RollbackIn):
        require_admin(request)
        from src.apollo import gaps as G
        return await _plain(lambda: G.rollback(agent_id, body.version))

    return router
