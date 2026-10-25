# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-03` · The Agents hall, over HTTP.

    GET    /api/agents                         the catalogue, its sections, and my hires
                                               (?everyone=1: an admin's view of every hire)
    GET    /api/agents/{agent_id}              one agent, as this person would hire it
    POST   /api/agents/{agent_id}/hire         hire it
    GET    /api/agents/hires/{hire_id}         one hire: its runs and their reports
    PUT    /api/agents/hires/{hire_id}         change it, or {update: true} to its new version
    POST   /api/agents/hires/{hire_id}/status  {status: on | paused}
    DELETE /api/agents/hires/{hire_id}         fire it, and every task it made
    POST   /api/agents/{agent_id}/try          `P24-13`: Try it once — hired as a trial,
                                               its schedule off, and run now
    POST   /api/agents/teams/{team_id}/hire    `P24-21`: Hire all
    GET    /api/agents/{agent_id}/source       `P24-20`: its file, for *Customise*
    POST   /api/agents/own                     keep a file as my own ({dry: true}: only check it)
    DELETE /api/agents/own/{agent_id}          remove my own file (a shipped one is mine again)
    POST   /api/agents/draft                   *Describe it*: a sentence drafted into a file
    POST   /api/agents/interview               `P25-08`: build it by talking — one turn
    POST   /api/agents/suggest                 `P25-09`: an agent for what a message asks, or none

The two install-wide ceilings (`P24-10`: *Pause all agents*, how many run at
once) are settings, saved through `POST /api/auth/settings` like every other
admin setting, and read back here so the hall can say when everything is paused.

**What is reused, not added** (`Law 14`): *Run now* and *Stop* are the hire's
tasks' own routes (`POST /api/tasks/{id}/run`, `/stop`) and a run's step log is
`GET /api/tasks/{id}/runs`. A second door for either would be a second place
to keep the one-run-at-a-time rule.

**Everyone sees the whole catalogue and may hire any agent**
(`D-2026-10-22-01` §2). A hire is its person's: another person's is a 404 —
except to an admin, who may open, pause and fire any hire (`B1424`'s rule for
the workstation, the plan's § 6). **Only a person** hires, changes or fires
(`request_is_a_person`): an API token or the assistant's own loopback could
otherwise hire an agent with more reach than the turn that asked for it.

Every refusal is `{detail: "<sentence>"}` (`Law 15`); a body is read by hand,
under a ceiling, so a malformed one is answered in a sentence too.

**The route ceiling** (`check-unreachable.py --max-routes 60`): every path
here is spelled in `static/js/agents/agentsApi.js`, its one caller.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.database import SessionLocal
from src.auth_helpers import get_current_user, request_is_a_person
from src.agents import hires as H
from src.agents.catalogue import catalogue, get_agent
from src.agents.manifest import FAMILIES, SECTIONS

logger = logging.getLogger(__name__)

BODY_MAX_BYTES = 64 * 1024
ONLY_A_PERSON = ("Only a person signed in to Pantheon can summon, change or dismiss an agent — "
                 "not an API token or the assistant.")
NO_SUCH_AGENT = "There is no agent called that in the hall."
NO_SUCH_HIRE = "There is no such hire."
RUNS_SHOWN = 30


def _refused(sentence: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": sentence}, status_code=status)


async def _body(request: Request) -> Dict[str, Any]:
    try:
        declared = int(request.headers.get("content-length") or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared > BODY_MAX_BYTES:
        raise H.HireRefused("The request is larger than 64 KiB, so it was not read.", 413)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > BODY_MAX_BYTES:
            raise H.HireRefused("The request is larger than 64 KiB, so it was not read.", 413)
    if not bytes(raw).strip():
        return {}
    try:
        body = json.loads(bytes(raw))
    except (TypeError, ValueError):
        raise H.HireRefused("The request body must be JSON.") from None
    if not isinstance(body, dict):
        raise H.HireRefused("The request body must be a JSON object.")
    return body


def _is_admin(user: Optional[str]) -> bool:
    """May `user` open, pause and fire another person's hire? A hire is a
    bundle of that person's tasks, so this is the task routes' own question —
    may this owner act on someone else's tasks — asked through the same
    function (`Law 14`), not a further admin decision of the hall's own
    (`check-auth-map.py`'s ratchet)."""
    from src.task_action_policy import owner_has_admin_task_privileges
    return bool(user) and owner_has_admin_task_privileges(user)


def _hire_or_none(db, hire_id: str, user: Optional[str]):
    from core.database import AgentHire
    hire = db.query(AgentHire).filter(AgentHire.id == hire_id).first()
    if hire is None:
        return None
    if hire.owner != user and not _is_admin(user):
        return None
    return hire


def _runs(db, hire) -> list:
    from core.database import AgentRunReport, TaskRun
    ids = H.task_ids_of(db, hire.id)
    if not ids:
        return []
    runs = (db.query(TaskRun).filter(TaskRun.task_id.in_(ids))
            .order_by(TaskRun.started_at.desc()).limit(RUNS_SHOWN).all())
    reports = {r.run_id: r for r in db.query(AgentRunReport).filter(
        AgentRunReport.run_id.in_([r.id for r in runs])).all()} if runs else {}
    out = []
    for r in runs:
        rep = reports.get(r.id)
        try:
            report = json.loads(rep.report) if rep else None
        except ValueError:
            report = None
        out.append({
            "id": r.id, "task_id": r.task_id, "status": r.status,
            "started_at": r.started_at.isoformat() + "Z" if r.started_at else None,
            "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else None,
            "error": r.error, "model": r.model, "report": report,
            # A skipped or waiting run has no report and no error; its reason
            # is the engine's sentence in `result` (*all agents are paused*,
            # *waiting for your yes on …*).
            "said": (r.result or "")[:500] if r.status in ("skipped", "waiting") else None,
        })
    return out


def _projects(user: Optional[str]) -> list:
    """The folders directly in this person's projects folder — what a hire may
    be pinned to (`D-2026-10-22-01` §8)."""
    import os
    from src.tool_execution import projects_root
    try:
        root = projects_root(user, create=False)
        return sorted(e for e in os.listdir(root)
                      if not e.startswith(".") and os.path.isdir(os.path.join(root, e)))
    except OSError:
        return []


def _sample(manifest) -> Optional[Dict[str, Any]]:
    """`P24-17`. The sample report shipped beside an agent (`sample.json`),
    written by its evaluation's first case — so it is the report format the
    hall shows, from a scripted model, and says so."""
    import os
    path = os.path.join(os.path.dirname(manifest.path or ""), "sample.json") if manifest.path else ""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _template() -> str:
    from src.agents.workshop import TEMPLATE
    return TEMPLATE


def setup_agent_routes(task_scheduler=None) -> APIRouter:
    router = APIRouter(prefix="/api/agents", tags=["agents"])

    @router.get("")
    def list_agents(request: Request, everyone: int = 0):
        from core.database import AgentHire
        user = get_current_user(request)
        agents, broken = catalogue(user)
        db = SessionLocal()
        try:
            q = db.query(AgentHire)
            show_all = bool(everyone) and _is_admin(user)
            if not show_all:
                q = q.filter(AgentHire.owner == user)
            rows = q.order_by(AgentHire.created_at).all()
            by_id = {m.id: m for m in agents}
            hires = []
            for h in rows:
                m = by_id.get(h.agent_id) if h.owner == user else get_agent(h.owner, h.agent_id)
                hires.append(H.hire_to_dict(db, h, m))
        finally:
            db.close()
        from src.agents import runtime as R
        from src.agents.teams import teams as _teams, to_public as _team_public
        mine = {h["agent_id"] for h in hires if h["owner"] == user}
        found_teams, broken_teams = _teams(user, by_id.keys())
        # `P24-18`. Measured on the model this person's hires would run on.
        from src.agents.fit import _install_rows, model_for
        model = model_for(user)
        proofs = _install_rows()
        # `B1448`. What this person's route has, once, against each agent's needs.
        from src.agents.needs import check as _needs_check, owner_route_facts
        route = owner_route_facts(user)

        def _fit(m, model):
            from src.agents.fit import _shipped_rows, fit
            return {k: v for k, v in fit(m, model, rows=_shipped_rows(m) + proofs).items() if k != "row"}
        return {
            "teams": [_team_public(t, by_id, mine) for t in found_teams],
            "broken_teams": broken_teams,
            "projects": _projects(user),
            "ceilings": {"paused": R.agents_paused(), "max_concurrent": R.max_concurrent()},
            "families": [{"id": f, "label": label} for f, label in FAMILIES],
            "sections": [{"id": s, "label": label, "family": fam,
                          "count": sum(1 for m in agents if m.section == s)}
                         for s, label, fam in SECTIONS],
            "agents": [dict(m.to_public(), fit=_fit(m, model), needs_check=_needs_check(m, route))
                       for m in agents],
            "fit_model": model,
            "template": _template(),
            "broken": broken,
            "hires": hires,
            "everyone": show_all,
            "me": user,
            "is_admin": _is_admin(user),
        }

    @router.get("/hires/{hire_id}")
    def one_hire(request: Request, hire_id: str):
        user = get_current_user(request)
        db = SessionLocal()
        try:
            hire = _hire_or_none(db, hire_id, user)
            if hire is None:
                return _refused(NO_SUCH_HIRE, 404)
            m = get_agent(hire.owner, hire.agent_id)
            out = H.hire_to_dict(db, hire, m)
            out["runs"] = _runs(db, hire)
            out["agent"] = m.to_public() if m else None
            return out
        finally:
            db.close()

    @router.put("/hires/{hire_id}")
    async def change_hire(request: Request, hire_id: str):
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        user = get_current_user(request)
        try:
            body = await _body(request)
        except H.HireRefused as r:
            return _refused(r.sentence, r.status)
        db = SessionLocal()
        try:
            hire = _hire_or_none(db, hire_id, user)
            if hire is None or hire.owner != user:
                # Watching another person's hire is an admin's; changing it is not.
                return _refused(NO_SUCH_HIRE if hire is None else
                                "This agent was summoned by someone else. You can pause or dismiss it, not change it.",
                                404 if hire is None else 403)
            m = get_agent(hire.owner, hire.agent_id)
            if m is None:
                return _refused("This agent's file is gone or broken, so the hire cannot be changed. "
                                "Dismiss it, or put the file back.", 409)
            H.update_hire(db, hire, m, inputs=body.get("inputs"), grants=body.get("grants"),
                          tz_name=body["tz_name"] if "tz_name" in body else ...,
                          project=body["project"] if "project" in body else ...,
                          name=body.get("name"), to_version=bool(body.get("update")))
            if body.get("update") and hire.status == "attention":
                H.set_status(db, hire, m, "on")
            db.commit()
            return H.hire_to_dict(db, hire, m)
        except H.HireRefused as r:
            db.rollback()
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    @router.post("/hires/{hire_id}/status")
    async def hire_status(request: Request, hire_id: str):
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        user = get_current_user(request)
        try:
            body = await _body(request)
        except H.HireRefused as r:
            return _refused(r.sentence, r.status)
        db = SessionLocal()
        try:
            hire = _hire_or_none(db, hire_id, user)
            if hire is None:
                return _refused(NO_SUCH_HIRE, 404)
            # flag-spelling: not a yes/no. A hire's status is one word of
            # `HIRE_STATUSES` (`on`, `paused`, …), and `set_status` refuses
            # any other in a sentence; `1` or `yes` here is a refusal, not on.
            status = body.get("status")
            if status == "on" and hire.owner != user:
                return _refused("Only the person who summoned it can switch it back on.", 403)
            m = get_agent(hire.owner, hire.agent_id)
            if m is None:
                if status == "on":
                    return _refused("This agent's file is gone or broken, so it cannot run. "
                                    "Dismiss it, or put the file back.", 409)
                H.needs_attention(db, hire, "Paused by hand; its agent file is gone or broken.")
            else:
                if status == "on" and m.version != hire.version:
                    return _refused(f"{m.name} is at {m.version} now. Update the hire first.", 409)
                H.set_status(db, hire, m, status)
            if hire.owner != user:
                logger.info("[agents] %s set %s's hire %s to %s", user, hire.owner, hire.id, status)
            db.commit()
            return H.hire_to_dict(db, hire, m)
        except H.HireRefused as r:
            db.rollback()
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    @router.delete("/hires/{hire_id}")
    def fire_hire(request: Request, hire_id: str):
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        user = get_current_user(request)
        db = SessionLocal()
        try:
            hire = _hire_or_none(db, hire_id, user)
            if hire is None:
                return _refused(NO_SUCH_HIRE, 404)
            name, owner = hire.name, hire.owner
            gone = H.fire(db, hire)
            db.commit()
            if owner != user:
                logger.info("[agents] %s fired %s's hire %s", user, owner, hire_id)
            return {"ok": True, "fired": name, "tasks_removed": gone}
        finally:
            db.close()

    @router.post("/teams/{team_id}/hire")
    async def hire_team(request: Request, team_id: str):
        """`P24-21`. *Hire all*: one hire per member not already hired, every
        member checked before any is written."""
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        user = get_current_user(request)
        try:
            body = await _body(request)
        except H.HireRefused as r:
            return _refused(r.sentence, r.status)
        from src.agents.teams import get_team
        agents, _ = catalogue(user)
        by_id = {m.id: m for m in agents}
        team = get_team(user, team_id, by_id.keys())
        if team is None:
            return _refused("There is no team called that in the hall.", 404)
        db = SessionLocal()
        try:
            done = H.hire_team(db, owner=user, team=team, manifests=by_id,
                               inputs=body.get("inputs"), tz_name=body.get("tz_name"),
                               project=body.get("project"))
            db.commit()
            return {"team": team.name,
                    "hired": [H.hire_to_dict(db, h, by_id.get(h.agent_id)) for h in done["hired"]],
                    "kept": done["kept"]}
        except H.HireRefused as r:
            db.rollback()
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    @router.post("/{agent_id}/try")
    async def try_agent(request: Request, agent_id: str):
        """`P24-13`. *Try it once*: the hire is made as a `trial` — its
        schedule off — and its first task is run now, as *Run now* runs it.
        The hall then shows the run's report beside *Hire* and *Discard*."""
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        if task_scheduler is None:
            return _refused("Runs cannot be started from here right now.", 503)
        user = get_current_user(request)
        try:
            body = await _body(request)
        except H.HireRefused as r:
            return _refused(r.sentence, r.status)
        m = get_agent(user, agent_id)
        if m is None:
            return _refused(NO_SUCH_AGENT, 404)
        db = SessionLocal()
        try:
            hire = H.make_hire(db, owner=user, manifest=m, inputs=body.get("inputs"),
                               grants=body.get("grants"), tz_name=body.get("tz_name"),
                               project=body.get("project"), name=body.get("name"),
                               status="trial")
            db.commit()
            first = H.task_ids_of(db, hire.id)[0]
            out = H.hire_to_dict(db, hire, m)
        except H.HireRefused as r:
            db.rollback()
            return _refused(r.sentence, r.status)
        finally:
            db.close()
        from src.interactive_gate import STARTED_BY_PERSON
        started = await task_scheduler.run_task_now(first, force=True, started_by=STARTED_BY_PERSON)
        out["started"] = bool(started)
        return out

    @router.get("/{agent_id}")
    def one_agent(request: Request, agent_id: str):
        user = get_current_user(request)
        m = get_agent(user, agent_id)
        if m is None:
            return _refused(NO_SUCH_AGENT, 404)
        out = m.to_public()
        out["lacking"] = H.lacking_tools(m, user)
        out["effects"] = H.manifest_effects(m)
        # `P24-18` / `P24-17`. Its measurement on this person's model, how many
        # cases its evaluation set has, and its sample report.
        from src.agents.fit import fit, model_for
        out["fit"] = fit(m, model_for(user))
        # `B1448`. Whether that model has what the agent declared it needs.
        from src.agents.needs import check as _needs_check, owner_route_facts
        out["needs_check"] = _needs_check(m, owner_route_facts(user))
        out["sample"] = _sample(m)
        try:
            from src.agents.evals import load_evals
            out["eval_cases"] = len(load_evals(m))
        except Exception:
            out["eval_cases"] = 0
        return out

    @router.post("/{agent_id}/hire")
    async def hire_agent(request: Request, agent_id: str):
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        user = get_current_user(request)
        try:
            body = await _body(request)
        except H.HireRefused as r:
            return _refused(r.sentence, r.status)
        m = get_agent(user, agent_id)
        if m is None:
            return _refused(NO_SUCH_AGENT, 404)
        db = SessionLocal()
        try:
            hire = H.make_hire(db, owner=user, manifest=m, inputs=body.get("inputs"),
                               grants=body.get("grants"), tz_name=body.get("tz_name"),
                               project=body.get("project"), name=body.get("name"))
            db.commit()
            return H.hire_to_dict(db, hire, m)
        except H.HireRefused as r:
            db.rollback()
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    # ── `P24-20` · New agent, Describe it, Customise ────────────────────────
    # A person's own file, in their own layer. Writing one is the person's
    # act, never a token's or the assistant's: an agent is a standing grant.

    @router.get("/{agent_id}/source")
    def agent_source(request: Request, agent_id: str):
        from src.agents import workshop as WS
        m = get_agent(get_current_user(request), agent_id)
        if m is None:
            return _refused(NO_SUCH_AGENT, 404)
        return {"id": m.id, "source": m.source, "shadows": m.source == "own" and WS.shadows(m.id),
                "text": WS.source(m)}

    @router.post("/own")
    async def save_own(request: Request):
        from src.agents import workshop as WS
        from src.agents.manifest import ManifestRefused
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except H.HireRefused as r:
            return _refused(r.sentence, r.status)
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return _refused("There is no file to keep — write it, or describe it and draft one.")
        if isinstance(body.get("name"), str) and body["name"].strip():
            text = WS.rename(text, body["name"])   # `P25-08`: the name the person chose
        try:
            if body.get("dry"):
                m = WS.check(text)
                return {"ok": True, "id": m.id, "shadows": WS.shadows(m.id),
                        "sentence": "It passes its check."}
            m, shadows = WS.save(get_current_user(request), text)
        except ManifestRefused as refused:
            return _refused(refused.sentence, 422)
        return {"ok": True, "id": m.id, "shadows": shadows,
                "sentence": (f"Kept. Your copy of {m.name} is the one you see and summon; "
                             f"everyone else still has the shipped one.") if shadows
                else f"Kept. {m.name} is in the hall, for you."}

    @router.delete("/own/{agent_id}")
    def remove_own(request: Request, agent_id: str):
        from src.agents import workshop as WS
        from src.agents.manifest import ManifestRefused
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            WS.remove(get_current_user(request), agent_id)
        except ManifestRefused as refused:
            return _refused(refused.sentence, 404)
        return {"ok": True, "back_to_shipped": WS.shadows(agent_id)}

    @router.post("/interview")
    async def interview_agent(request: Request):
        """`P25-08`. One turn of building an agent by talking with the model."""
        from src.agents import workshop as WS
        from src.agents.manifest import ManifestRefused
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except H.HireRefused as r:
            return _refused(r.sentence, r.status)
        try:
            return await WS.interview(get_current_user(request), body.get("messages") or [],
                                      seed=str(body.get("seed") or ""), build_now=bool(body.get("build_now")))
        except ManifestRefused as refused:
            return _refused(refused.sentence)

    @router.post("/suggest")
    async def suggest_agent(request: Request):
        """`P25-09`. The agent a message is asking for, if one fits."""
        from src.agents.suggest import suggest
        try:
            body = await _body(request)
        except H.HireRefused as r:
            return _refused(r.sentence, r.status)
        user = get_current_user(request)
        agents, _broken = catalogue(user)
        got = suggest(str(body.get("text") or ""), agents,
                      skip=[str(x) for x in (body.get("skip") or []) if isinstance(x, str)][:200])
        return got or {}

    @router.post("/draft")
    async def draft_agent(request: Request):
        from src.agents import workshop as WS
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except H.HireRefused as r:
            return _refused(r.sentence, r.status)
        out = await WS.draft(get_current_user(request), body.get("description"))
        if not out["ok"] and not out["text"]:
            return _refused(out["sentence"], 503 if out["sentence"] == WS.NO_MODEL else 400)
        return out

    return router
