# SPDX-License-Identifier: AGPL-3.0-or-later
"""When the roster has a gap (phase 5b): a missing agent drafted, proven,
approved by an admin, and published for every account on the server.

The outline (*When the roster has a gap*):

1. The lead finds no agent fits a sub-task.
2. Apollo tells the person what's missing, why, and what it would take.
3. Models draft a full agent: `AGENT.md` plus an `evals.json`. The draft can
   only name tools that already exist and can't register MCP servers, so text
   an agent reads never becomes a program it runs.
4. It's proven before anyone sees it: the lint, then a proof run of its evals
   on the model it would run on, so it arrives with a fit badge.
5. An admin approves, edits or rejects it, seeing the tools and effects it
   asks for beside its results. Nothing ships without that.
6. Approved agents publish to a platform-wide layer every account can hire
   from, versioned so an update or rollback is one step.

Where things live:

    <data>/agent_platform/proposals/<proposal>/<agent id>/   the draft and its evals, staged
    <data>/agent_platform/live/<agent id>/                     what the catalogue reads
    <data>/agent_platform/versions/<agent id>/<version>/       every version ever approved

A proposal is the person's: they see its state. Only an admin approves,
edits, rejects or rolls back, and only an approved agent reaches anyone else.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.apollo.errors import ApolloRefused

logger = logging.getLogger(__name__)

STATES = ("drafting", "proving", "waiting", "published", "rejected", "failed")
OPEN_STATES = ("drafting", "proving", "waiting")
STATE_WORDS = {"drafting": "Drafting it", "proving": "Proving it on your model",
               "waiting": "Waiting on your admin", "published": "Ready to hire",
               "rejected": "Turned down", "failed": "Couldn't be made"}
OPEN_MAX = 3                 # a person's proposals open at once
PROOF_RUNS = 3               # each case, on the model it would run on
PROOF_TIMEOUT = 45 * 60      # seconds, the whole proof run
EVALS_MAX_TOKENS = 3000
NEED_MAX = 400
WHY_MAX = 600
NOTE_MAX = 600
#: Tools a drafted agent never names: the fleet is a lead's alone, given by
#: the runtime while its goal has room, and a drafted agent asks for nothing
#: beyond the job it was drafted for.
UPDATE_WHY = "An admin's update."
NOT_DRAFTED = frozenset({"fleet", "apollo"})
NO_MODEL = "No model is set up for scheduled work, so there's nothing to prove the agent on."


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clip(text: Any, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _root(data_dir: Optional[str] = None) -> str:
    from src.constants import DATA_DIR
    return os.path.join(data_dir or DATA_DIR, "agent_platform")


def _stage_dir(pid: str, agent_id: str, data_dir: Optional[str] = None) -> str:
    return os.path.join(_root(data_dir), "proposals", pid, agent_id)


def _version_dir(agent_id: str, version: str, data_dir: Optional[str] = None) -> str:
    return os.path.join(_root(data_dir), "versions", agent_id, version)


def _live_dir(agent_id: str, data_dir: Optional[str] = None) -> str:
    from src.agents.catalogue import platform_root
    return os.path.join(platform_root(data_dir), agent_id)


# ── the person's side ──────────────────────────────────────────────────────

def get(db, pid: str, *, owner: Optional[str] = None):
    from core.database import ApolloAgentProposal
    q = db.query(ApolloAgentProposal).filter(ApolloAgentProposal.id == str(pid or ""))
    if owner is not None:
        q = q.filter(ApolloAgentProposal.owner == owner)
    row = q.first()
    if row is None:
        raise ApolloRefused("That proposal isn't one of yours.", 404)
    return row


def propose(db, owner: str, *, need: Any, why: Any, task=None, from_agent: Optional[str] = None):
    """A gap a lead found. One open proposal per need; at most `OPEN_MAX`
    open at once. Answers `(proposal, made)`; `made` False when an open one
    for the same need was there already."""
    from core.database import ApolloAgentProposal
    need = _clip(need, NEED_MAX)
    why = _clip(why, WHY_MAX)
    if not need:
        raise ApolloRefused("Say what the missing agent would do.")
    if not why:
        raise ApolloRefused("Say why no agent in the roster fits it.")
    mine = (db.query(ApolloAgentProposal).filter(ApolloAgentProposal.owner == owner,
                                                 ApolloAgentProposal.state.in_(OPEN_STATES)).all())
    for row in mine:
        if row.need.lower() == need.lower():
            return row, False
    if len(mine) >= OPEN_MAX:
        raise ApolloRefused(f"{OPEN_MAX} new agents are already being made for this person. Do the work "
                            f"yourself for now, and say in your report what's missing.", 409)
    row = ApolloAgentProposal(id=str(uuid.uuid4()), owner=owner, need=need, why=why, state="drafting",
                              task_id=getattr(task, "id", None), from_agent=from_agent,
                              sentence="Drafting it.", created_at=_now(), updated_at=_now())
    db.add(row)
    if task is not None:
        from src.apollo import fleet as F
        F.log(db, owner, task, "gap", f"{need}\n\nWhy: {why}", from_agent=from_agent)
    db.flush()
    return row, True


def propose_update(db, admin: str, agent_id: Any, text: Any):
    """An admin's new version of a platform agent: a proposal of its own,
    proven before it can be approved. The version must be a new one."""
    from core.database import ApolloAgentProposal
    from src.agents.catalogue import MANIFEST_NAME
    from src.agents.manifest import ManifestRefused
    agent_id = str(agent_id or "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,47}", agent_id) or \
            not os.path.isfile(os.path.join(_live_dir(agent_id), MANIFEST_NAME)):
        raise ApolloRefused("That isn't a published platform agent.", 404)
    try:
        m = check_platform(str(text or ""))
    except ManifestRefused as refused:
        raise ApolloRefused(f"The new version doesn't pass its check: {refused.sentence}") from None
    if m.id != agent_id:
        raise ApolloRefused(f"A new version keeps the agent's id, {agent_id}.")
    if os.path.isdir(_version_dir(agent_id, m.version)):
        raise ApolloRefused(f"Version {m.version} is already published. Give the new one its own version.", 409)
    row = ApolloAgentProposal(id=str(uuid.uuid4()), owner=admin, need=_clip(f"A new version of {m.name}", NEED_MAX),
                              why=UPDATE_WHY, state="proving", agent_id=agent_id, agent_name=m.name,
                              version=m.version, reviewer=admin, sentence="Proving the new version.",
                              created_at=_now(), updated_at=_now())
    db.add(row)
    db.flush()
    return row


def _set(row, state: str, sentence: str) -> None:
    row.state = state
    row.sentence = _clip(sentence, 600)
    row.updated_at = _now()


def to_dict(row, *, full: bool = False) -> Dict[str, Any]:
    def iso(d):
        return d.isoformat() + "Z" if d else None
    out = {"id": row.id, "need": row.need, "why": row.why, "state": row.state,
           "state_words": STATE_WORDS.get(row.state, row.state), "sentence": row.sentence,
           "agent_id": row.agent_id, "agent_name": row.agent_name, "version": row.version,
           "badge": row.badge, "model": row.model, "task_id": row.task_id,
           "created_at": iso(row.created_at), "updated_at": iso(row.updated_at),
           "review_note": row.review_note}
    if full:
        out["owner"] = row.owner
        out["text"] = row.text
        out["evals"] = row.evals
        out["proof"] = json.loads(row.proof) if row.proof else None
        out["asks_for"] = asks_for(row.text) if row.text else None
    return out


def list_for(db, owner: str) -> List[Dict[str, Any]]:
    from core.database import ApolloAgentProposal
    rows = (db.query(ApolloAgentProposal).filter(ApolloAgentProposal.owner == owner)
            .order_by(ApolloAgentProposal.created_at.desc()).limit(20).all())
    return [to_dict(r) for r in rows]


def asks_for(text: str) -> Optional[Dict[str, Any]]:
    """What an admin weighs: the tools it names and its effects table."""
    from src.agents.manifest import ManifestRefused, parse_manifest
    try:
        m = parse_manifest(text or "", source="platform")
    except ManifestRefused as refused:
        return {"error": refused.sentence}
    return {"id": m.id, "name": m.name, "tagline": m.tagline, "version": m.version,
            "tools": list(m.tools), "effects": dict(m.effects)}


# ── drafting and proving ───────────────────────────────────────────────────

def _taken(agent_id: str, data_dir: Optional[str] = None) -> bool:
    from src.agents.catalogue import MANIFEST_NAME, SHIPPED_ROOT
    return os.path.isfile(os.path.join(SHIPPED_ROOT, agent_id, MANIFEST_NAME)) or \
        os.path.isfile(os.path.join(_live_dir(agent_id, data_dir), MANIFEST_NAME))


def _with_id(text: str, agent_id: str) -> str:
    return re.sub(r"(?m)^id:\s*.*$", f"id: {agent_id}", text, count=1)


def unique_id(text: str, agent_id: str, data_dir: Optional[str] = None) -> Tuple[str, str]:
    """A new agent never takes an id that's shipped or already published."""
    base, n, new = agent_id, 2, agent_id
    while _taken(new, data_dir):
        suffix = f"-{n}"
        new = base[: 48 - len(suffix)] + suffix
        n += 1
    return (_with_id(text, new) if new != agent_id else text), new


def check_platform(text: str):
    """The workshop's check, plus the platform's own rule: only tools
    Pantheon has natively, never one an MCP server brings."""
    from src.agents import workshop as WS
    from src.agents.manifest import ManifestRefused
    m = WS.check(text)
    from src.tool_policy import selectable_tool_names
    native = selectable_tool_names() - NOT_DRAFTED
    for name in m.tools:
        if name not in native or "__" in name or name.startswith("mcp"):
            raise ManifestRefused(f"“{name}” isn't one of Pantheon's own tools. A drafted agent uses only "
                                  f"those, never one an MCP server brings.")
    return m


_EVALS_SYSTEM = """You write the evaluation set for a Pantheon agent: 2 or 3 small cases that show it
doing its job. Answer with ONE JSON object and nothing else: {"cases": [...]}.

Each case is {"id": "lower-case-words", "about": "one line", "inputs": {...}, "world": {...}, "checks": [...]}.
- "inputs" uses only the agent's input keys, with realistic values.
- "world" is what the agent reads from outside, with keys from: %(world)s. Make it small and concrete:
  emails as {"id","from","subject","body","date"}, web as {"url": "page text"}, search as
  {"query words": [{"title","url","snippet"}]}.
- "checks" are one-key objects from: %(checks)s. For example {"answer_contains": ["Ana"]},
  {"not_called": "send_email"}, {"document": {"title": "Inbox triage", "contains": ["Urgent"]}}.
  Check the result a person would look for, and that it never does what it must not do.
- No "script": the agent runs on a real model."""


async def draft_evals(owner: Optional[str], manifest) -> Tuple[Optional[Dict[str, Any]], str]:
    from src.agents.evals import CHECK_KINDS, WORLD_KEYS, EvalRefused, lint_evals
    from src.workflow_assist import NoModelSetUp, ask_for_json
    system = _EVALS_SYSTEM % {"world": ", ".join(WORLD_KEYS), "checks": ", ".join(CHECK_KINDS)}
    about = {"id": manifest.id, "name": manifest.name, "tagline": manifest.tagline,
             "inputs": [dict(i) for i in manifest.inputs], "tools": list(manifest.tools),
             "delivers": [dict(d) for d in manifest.delivers], "runbook": manifest.runbook[:4000]}
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": "The agent:\n" + json.dumps(about, default=str)}]
    sentence = ""
    for _round in range(2):
        try:
            obj, problem = await ask_for_json(owner, messages, max_tokens=EVALS_MAX_TOKENS)
        except NoModelSetUp:
            return None, NO_MODEL
        if obj is None:
            return None, getattr(problem, "sentence", str(problem))
        try:
            lint_evals(obj, manifest)
            return obj, ""
        except EvalRefused as refused:
            sentence = refused.sentence
            messages = messages + [{"role": "assistant", "content": json.dumps(obj)},
                                   {"role": "user", "content": f"That set doesn't pass its check: {sentence} "
                                                               f"Answer the whole object again."}]
    return None, f"The evaluation set didn't pass its check: {sentence}"


def _describe(row) -> str:
    return (f"An agent any person on this server could hire for this job: {row.need}\n"
            f"It's needed because: {row.why}\n"
            f"Keep it to one job, done end to end, and use only the tools it needs.")


def stage(row, text: str, evals: Dict[str, Any], data_dir: Optional[str] = None):
    """Write the draft where a proof run can read it. Answers its manifest."""
    from src.agents.catalogue import MANIFEST_NAME
    from src.agents.evals import EVAL_FILE
    from src.agents.manifest import parse_manifest
    m0 = parse_manifest(text, source="platform")
    folder = _stage_dir(row.id, m0.id, data_dir)
    shutil.rmtree(os.path.dirname(folder), ignore_errors=True)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, MANIFEST_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")
    with open(os.path.join(folder, EVAL_FILE), "w", encoding="utf-8") as fh:
        json.dump(evals, fh, indent=1, ensure_ascii=False)
    return parse_manifest(text, source="platform", path=path)


async def prove(manifest, *, endpoint: str, model: str, runs: int = PROOF_RUNS,
                timeout: float = PROOF_TIMEOUT) -> Tuple[Optional[Dict[str, Any]], str]:
    """A proof run of the staged agent, in its own process so its isolated
    world never touches this server's. Answers `(proof row, "")` or
    `(None, sentence)`."""
    out = os.path.join(os.path.dirname(manifest.path), "proof.jsonl")
    try:
        os.remove(out)
    except OSError:   # an old proof file may not be there; the run writes a fresh one
        pass
    cmd = [sys.executable, "-m", "src.agents.evals", manifest.id, "--file", manifest.path,
           "--endpoint", endpoint, "--model", model, "--runs", str(runs), "--out", out]
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=here, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
    except OSError as exc:
        return None, f"The proof run couldn't start: {exc.__class__.__name__}."
    try:
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return None, f"The proof run took longer than {int(timeout // 60)} minutes and was stopped."
    try:
        with open(out, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    except (OSError, ValueError):
        rows = []
    if not rows:
        return None, "The proof run finished without a result."
    return rows[-1], ""


def _badge(manifest, row: Dict[str, Any]) -> str:
    from src.agents.fit import verdict
    return verdict(row, manifest.budget.get("max_minutes", 10))


def _on_row(pid: str, fn):
    """Run `fn(row)` in a short session of its own and commit: every
    database step of a build, handed to a worker thread so the event loop
    never holds a session across a model call or a proof run."""
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        out = fn(get(db, pid))
        db.commit()
        return out
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _fail(pid: str, sentence: str, state: str = "failed") -> str:
    def go(row):
        _set(row, state, sentence)
        return row.state
    return _on_row(pid, go)


def _start(pid: str, endpoint: Optional[str], model: Optional[str]) -> Dict[str, Any]:
    """Who it's for, what to describe, and the model it'll be proven on."""
    def go(row):
        ep, mo = endpoint, model
        if ep is None or mo is None:
            try:
                from src.task_endpoint import resolve_task_endpoint
                ep, mo, _h = resolve_task_endpoint(owner=row.owner)
            except Exception:
                ep, mo = None, None
        if not ep or not mo:
            _set(row, "failed", NO_MODEL)
        return {"owner": row.owner, "describe": _describe(row), "endpoint": ep, "model": mo,
                "agent_id": row.agent_id, "had_text": bool(row.text), "state": row.state}
    return _on_row(pid, go)


async def build(pid: str, *, data_dir: Optional[str] = None, endpoint: Optional[str] = None,
                model: Optional[str] = None, text: Optional[str] = None) -> Optional[str]:
    """Draft (unless `text` is given, an admin's edit), check, write evals,
    stage, prove. Leaves the proposal `waiting` for an admin, or `failed`
    with the sentence. Answers the final state. Each database step runs in a
    worker thread (`_on_row`)."""
    from src.agents import workshop as WS
    from src.agents.manifest import ManifestRefused
    try:
        start = await asyncio.to_thread(_start, pid, endpoint, model)
    except ApolloRefused:
        return None
    if start["state"] == "failed":
        return "failed"
    owner, endpoint, model = start["owner"], start["endpoint"], start["model"]
    try:
        if text is None:
            drafted = await WS.draft(owner, start["describe"])
            if not drafted.get("ok"):
                return await asyncio.to_thread(_fail, pid, drafted.get("sentence") or
                                               "The draft didn't pass its check.")
            text = drafted["text"]
        try:
            m = check_platform(text)
            if start["agent_id"] and start["agent_id"] != m.id:
                raise ManifestRefused(f"An edit keeps the agent's id, {start['agent_id']}.")
            if not start["agent_id"]:
                text, _new = unique_id(text, m.id, data_dir)
                m = check_platform(text)
        except ManifestRefused as refused:
            return await asyncio.to_thread(_fail, pid, refused.sentence,
                                           "waiting" if start["had_text"] else "failed")
        evals, why = await draft_evals(owner, m)
        if evals is None:
            return await asyncio.to_thread(_fail, pid, why)

        def drafted_row(row):
            row.text, row.agent_id, row.agent_name, row.version = text, m.id, m.name, m.version
            row.evals = json.dumps(evals)
            row.model = model
            staged = stage(row, text, evals, data_dir)
            _set(row, "proving", f"Proving it on {model}.")
            return staged
        staged = await asyncio.to_thread(_on_row, pid, drafted_row)
        proof, why = await prove(staged, endpoint=endpoint, model=model)
        if proof is None:
            return await asyncio.to_thread(_fail, pid, why)

        def proven(row):
            from src.agents.fit import WORDS
            row.proof = json.dumps(proof)
            row.badge = _badge(staged, proof)
            _set(row, "waiting", f"Proven on {model}: {WORDS.get(row.badge, row.badge)}. Waiting on an admin.")
            return row.state
        return await asyncio.to_thread(_on_row, pid, proven)
    except Exception:
        logger.warning("Could not build the proposed agent %s", pid, exc_info=True)
        try:
            return await asyncio.to_thread(_fail, pid, "Something went wrong making it. Try again.")
        except Exception:
            return "failed"


def start_build(pid: str, **kw) -> None:
    """Build in the background on the running loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(build(pid, **kw))


def retry(db, owner: str, pid: str):
    row = get(db, pid, owner=owner)
    if row.state != "failed":
        raise ApolloRefused("Only one that couldn't be made can be tried again.", 409)
    if row.why == UPDATE_WHY:
        raise ApolloRefused("An update is tried again by sending the new version again.", 409)
    _set(row, "drafting", "Drafting it again.")
    row.text = row.evals = row.proof = row.badge = None
    row.agent_id = row.agent_name = row.version = row.model = None
    db.flush()
    return row


# ── the admin's side ───────────────────────────────────────────────────────

def waiting(db) -> List[Dict[str, Any]]:
    from core.database import ApolloAgentProposal
    rows = (db.query(ApolloAgentProposal).filter(ApolloAgentProposal.state.in_(OPEN_STATES))
            .order_by(ApolloAgentProposal.created_at).all())
    return [to_dict(r, full=True) for r in rows]


def _copy(src: str, dst: str) -> None:
    tmp = dst + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp)
    shutil.rmtree(dst, ignore_errors=True)
    os.replace(tmp, dst)


def _forget(agent_id: str, data_dir: Optional[str] = None) -> None:
    from src.agents import catalogue as C
    with C._lock:
        C._cache.pop(os.path.join(_live_dir(agent_id, data_dir), C.MANIFEST_NAME), None)


def approve(db, admin: str, pid: str, *, data_dir: Optional[str] = None) -> Dict[str, Any]:
    """Publish a proven draft as it stands. Answers the proposal."""
    from src.agents.catalogue import MANIFEST_NAME, SHIPPED_ROOT
    row = get(db, pid)
    if row.state != "waiting":
        raise ApolloRefused("Only a proven draft waiting on an admin can be approved.", 409)
    if not row.text or not row.proof:
        raise ApolloRefused("It hasn't been proven yet, so it can't be approved.", 409)
    m = check_platform(row.text)
    if os.path.isfile(os.path.join(SHIPPED_ROOT, m.id, MANIFEST_NAME)):
        raise ApolloRefused(f"{m.id} is a shipped agent's id, and the platform never replaces one.", 409)
    vdir = _version_dir(m.id, m.version, data_dir)
    if os.path.isdir(vdir):
        raise ApolloRefused(f"Version {m.version} of {m.id} is already published. Edit the version, then "
                            f"approve it.", 409)
    staged = _stage_dir(row.id, m.id, data_dir)
    if not os.path.isfile(os.path.join(staged, MANIFEST_NAME)):
        raise ApolloRefused("Its staged files are gone. Edit it to stage and prove it again.", 409)
    with open(os.path.join(staged, "proofs.json"), "w", encoding="utf-8") as fh:
        json.dump([json.loads(row.proof)], fh, indent=1)
    meta = {"proposal": row.id, "approved_by": admin, "approved_at": _now().isoformat() + "Z",
            "badge": row.badge, "model": row.model}
    with open(os.path.join(staged, "published.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    try:
        os.remove(os.path.join(staged, "proof.jsonl"))
    except OSError:   # nothing staged to clear: the edit is proven from scratch either way
        pass
    os.makedirs(os.path.dirname(vdir), exist_ok=True)
    _copy(staged, vdir)
    os.makedirs(os.path.dirname(_live_dir(m.id, data_dir)), exist_ok=True)
    _copy(vdir, _live_dir(m.id, data_dir))
    _forget(m.id, data_dir)
    row.reviewer = admin
    _set(row, "published", f"{m.name} {m.version} is published. Anyone on this server can hire it.")
    db.flush()
    return to_dict(row, full=True)


def edit(db, admin: str, pid: str, text: Any) -> Dict[str, Any]:
    """An admin's edit: checked now, then staged and proven again before it
    can be approved. Answers the proposal, back to proving."""
    from src.agents.manifest import ManifestRefused
    row = get(db, pid)
    if row.state != "waiting":
        raise ApolloRefused("Only a draft waiting on an admin can be edited.", 409)
    text = str(text or "")
    try:
        m = check_platform(text)
    except ManifestRefused as refused:
        raise ApolloRefused(f"The edit doesn't pass its check: {refused.sentence}") from None
    if m.id != row.agent_id:
        raise ApolloRefused(f"An edit keeps the agent's id, {row.agent_id}.")
    row.reviewer = admin
    _set(row, "proving", "Edited. Proving it again.")
    db.flush()
    return to_dict(row, full=True)


def reject(db, admin: str, pid: str, note: Any = None) -> Dict[str, Any]:
    row = get(db, pid)
    if row.state not in OPEN_STATES and row.state != "failed":
        raise ApolloRefused("That one is already settled.", 409)
    row.reviewer = admin
    row.review_note = _clip(note, NOTE_MAX) or None
    _set(row, "rejected", "Turned down by an admin." + (f" {row.review_note}" if row.review_note else ""))
    db.flush()
    return to_dict(row, full=True)


def published(data_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every platform agent: its live version and every version approved."""
    from src.agents.catalogue import MANIFEST_NAME
    from src.agents.manifest import ManifestRefused, parse_manifest
    root = os.path.join(_root(data_dir), "versions")
    out = []
    for agent_id in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        live = None
        try:
            with open(os.path.join(_live_dir(agent_id, data_dir), MANIFEST_NAME), encoding="utf-8") as fh:
                live = parse_manifest(fh.read(), source="platform")
        except (OSError, ManifestRefused):   # no live copy yet, or one the catalogue would refuse: nothing to compare
            pass
        versions = []
        for v in sorted(os.listdir(os.path.join(root, agent_id))):
            meta = {}
            try:
                with open(os.path.join(root, agent_id, v, "published.json"), encoding="utf-8") as fh:
                    meta = json.load(fh)
            except (OSError, ValueError):   # a version folder with no readable record is listed without one
                pass
            versions.append({"version": v, "approved_by": meta.get("approved_by"),
                             "approved_at": meta.get("approved_at"), "badge": meta.get("badge")})
        versions.sort(key=lambda x: str(x.get("approved_at") or ""))
        out.append({"id": agent_id, "name": live.name if live else agent_id,
                    "live": live.version if live else None, "versions": versions})
    return out


def rollback(agent_id: Any, version: Any, *, data_dir: Optional[str] = None) -> Dict[str, Any]:
    """Make an earlier approved version the live one. Hires read the file
    when each run starts, and a version change is offered to them as usual."""
    agent_id, version = str(agent_id or ""), str(version or "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,47}", agent_id) or not re.fullmatch(r"[0-9A-Za-z.+-]{1,32}", version):
        raise ApolloRefused("There's no such version to go back to.", 404)
    vdir = _version_dir(agent_id, version, data_dir)
    if not os.path.isdir(vdir):
        raise ApolloRefused("There's no such version to go back to.", 404)
    _copy(vdir, _live_dir(agent_id, data_dir))
    _forget(agent_id, data_dir)
    return next(a for a in published(data_dir) if a["id"] == agent_id)
