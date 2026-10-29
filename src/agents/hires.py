# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-03` / `P24-04` · A hire, and what it compiles to.

A hire is one `agent_hires` row. It compiles to one `scheduled_tasks` row per
trigger in its manifest, each tied back by `agent_hire_tasks`, so everything
the task engine already does — schedules in the person's zone, events, the
webhook URL, *Run now*, the one-run-at-a-time rule, retries, the run log, the
waiting list — an agent gets by being made of tasks (`Law 14`).

**What compiles is the trigger, never the job.** The task's prompt is one line;
what the model is told, what it may call and what it reads are assembled from
the hire and its manifest at the moment a run starts (`runtime.py`). So editing
the hire, or updating it to a new manifest version, changes the next run
without rewriting the task's history (`P22-05`'s split, for the same reason).

**Recompiling replaces like for like.** Trigger *n* of the manifest is task *n*
of the hire: it is updated in place, so its runs, its chat and its reports stay
with it; a trigger the manifest no longer has takes its task with it.

**Who may hire what** (`D-2026-10-22-01` §2): everyone, any agent. What a run
may call is still the hirer's own privileges, asked of the resolver every chat
asks (`tool_security.blocked_tools_for_owner`), and `lacking_tools` says which
of the agent's tools that leaves out, so the form can say so before the hire.
"""

from __future__ import annotations

import json
import re
import secrets
import uuid
from typing import Any, Dict, List, Optional

from src.agents.manifest import (
    EFFECT_RULES, Manifest, describe_trigger, describe_triggers, _INPUT_REF_RE, _TIME_RE,
)

#: `trial` is *Try it once* (`P24-13`): hired and run once, its schedule off,
#: until the person chooses *Hire* (→ `on`) or *Discard* (fired).
HIRE_STATUSES = ("on", "paused", "attention", "trial")
WORKSTATION_NOT_GRANTED = ("drives the workstation's screen, which your account has not been granted "
                           "(can_use_workstation); an admin can grant it in Settings → Users")
TASK_PROMPT = "Do the job your runbook describes, now, and finish with your report."
NAME_MAX = 60

# Effects a hire may carry out without asking unless its manifest says
# otherwise: reading, and asking the person. Everything else a tool can do —
# writing, running code, reaching out, changing settings — asks unless the
# manifest names it `allow` (`D-2026-10-22-01` §3: the cautious default).
QUIET_EFFECTS = frozenset({
    "read_public", "read_workspace", "read_private", "brokered_network_read",
    "user_interaction",
})

_RULE_RANK = {"allow": 0, "ask": 1, "never": 2}


class HireRefused(Exception):
    """A hire, or a change to one, that Pantheon will not make — and why."""

    def __init__(self, sentence: str, status: int = 400):
        super().__init__(sentence)
        self.sentence = sentence
        self.status = status

    def body(self) -> Dict[str, str]:
        return {"detail": self.sentence}


# ── Inputs, privileges, effects ────────────────────────────────────────────

def check_inputs(manifest: Manifest, raw: Any) -> Dict[str, Any]:
    """The hire form's values, checked against the manifest's inputs. Unknown
    keys are refused rather than kept, so nothing a run reads was never asked."""
    raw = raw if isinstance(raw, dict) else {}
    declared = {i["key"]: i for i in manifest.inputs}
    unknown = sorted(set(raw) - set(declared))
    if unknown:
        raise HireRefused(f"{manifest.name} does not ask for “{unknown[0]}”.")
    out: Dict[str, Any] = {}
    for key, spec in declared.items():
        label = spec["label"]
        value = raw.get(key, spec.get("default"))
        empty = value is None or (isinstance(value, (str, list)) and len(value) == 0)
        if empty:
            if not spec.get("optional"):
                raise HireRefused(f"“{label}” needs an answer.")
            continue
        kind = spec["kind"]
        if kind in ("text", "long_text", "email_account", "folder", "url"):
            if not isinstance(value, str):
                raise HireRefused(f"“{label}” is not text.")
            value = value.strip()
            limit = 4000 if kind == "long_text" else 300
            if len(value) > limit:
                raise HireRefused(f"“{label}” is longer than {limit} characters.")
            if kind == "url" and not re.match(r"^https?://\S+$", value):
                raise HireRefused(f"“{label}” is not a web address starting http:// or https://.")
            if kind == "folder" and (value.startswith("/") or ".." in value.split("/")):
                raise HireRefused(f"“{label}” is a folder inside your projects folder, like site/drafts.")
        elif kind == "list":
            if isinstance(value, str):
                value = [p.strip() for p in re.split(r"[,\n]", value) if p.strip()]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise HireRefused(f"“{label}” is not a list.")
            value = [v.strip()[:200] for v in value if v.strip()][:50]
            if not value and not spec.get("optional"):
                raise HireRefused(f"“{label}” needs an answer.")
        elif kind == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise HireRefused(f"“{label}” is not a number.")
            if value.is_integer():
                value = int(value)
        elif kind == "time":
            if not isinstance(value, str) or not _TIME_RE.match(value.strip()):
                raise HireRefused(f"“{label}” is not a time like 07:30.")
            value = value.strip()
        elif kind == "choice":
            if value not in (spec.get("choices") or []):
                raise HireRefused(f"“{label}” is one of: {', '.join(spec.get('choices') or [])}.")
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise HireRefused(f"“{label}” is yes or no.")
        out[key] = value
    return out


def lacking_tools(manifest: Manifest, owner: Optional[str]) -> List[Dict[str, str]]:
    """The agent's tools this person's runs will not have, each with the
    sentence the chat would give for it. Empty for an admin."""
    from src.tool_security import blocked_tool_reason, blocked_tools_for_owner
    blocked = blocked_tools_for_owner(owner)
    out = [{"tool": t, "reason": blocked_tool_reason(t) or "Your account cannot use it."}
           for t in manifest.tools if t in blocked]
    if "computer" in manifest.tools and "computer" not in blocked:
        # `P20-04`: the one tool whose privilege is its own, `can_use_workstation`.
        from src.workstation_access import may_use
        if not may_use(owner):
            out.append({"tool": "computer", "reason": WORKSTATION_NOT_GRANTED})
    return out


def tool_effects(tool: str) -> List[str]:
    """Every effect some call of `tool` can carry (`B1629`): a shell's `rm`
    carries `destructive` and a `manage_notes` list `read_private`, so a
    table read from the registration alone left both to nobody — no row on
    the hire form and, for `destructive`, no cautious default."""
    from src.tool_capabilities import widest_reach
    return sorted(e.value for e in widest_reach(tool))


def kit(manifest: Manifest, never) -> List[str]:
    """`B1619`. The tools a run of this agent gets under its `never`s — the
    one rule for a hired run (`runtime.plan_for_task`) and a summoned agent
    (`summon.summon`), so the two cannot differ (`Law 7`).

    A tool goes only when **every** call of it carries an effect the hire
    never allows (`tool_capabilities.least_reach`). One some of whose calls
    do stays, and the gate refuses just those calls in the hire's words: with
    `write_private: never`, Memory Auditor keeps `manage_memory` to list and
    search, and an `add`, `edit` or `delete` is refused. Filtering by the
    widest reach took the whole tool away, its reads with its writes."""
    from src.tool_capabilities import least_reach
    never = set(never or ())
    return [t for t in manifest.tools if not ({e.value for e in least_reach(t)} & never)]


def manifest_effects(manifest: Manifest) -> Dict[str, str]:
    """Every effect the agent's tools can have — including one only some of
    their calls carry (`B1629`) — with the manifest's rule for it, or the
    cautious default where the manifest is silent.

    `B1659`: and nothing else. A rule for an effect no call of its tools
    carries was copied in as well, so the hire form drew a row that never
    happens (*read public pages — without asking* for a `web_fetch` agent:
    only the agent browser's looking carries `read_public`), and a person
    could set it to *never* and nothing changed. The gate is the same either
    way — it asks a call's effects, and no call has that one. A person's file
    is told so when it is saved (`manifest.check_effects_carried`); one kept
    before — a Topic Watcher customised before `B1656`, whose table allows
    `read_public` — keeps its line, and runs, and the row is not drawn."""
    out: Dict[str, str] = {}
    for tool in manifest.tools:
        for eff in tool_effects(tool):
            out[eff] = manifest.effects.get(eff) or ("allow" if eff in QUIET_EFFECTS else "ask")
    return dict(sorted(out.items()))


def kit_reach(manifest: Manifest):
    """`B1659`. `(what some call of its tools can carry, what some call its
    run can make can carry)` — the second under the table's own `never`s, as
    a hired run gets its kit (`kit`, `tool_capabilities.reach_left`)."""
    from src.tool_capabilities import reach_left
    never = {e for e, r in manifest.effects.items() if r == "never"}
    tools = {e for t in manifest.tools for e in tool_effects(t)}
    run = {e.value for t in kit(manifest, never) for e in reach_left(t, never)}
    return tools, run


def effects_no_call_carries(manifest: Manifest) -> Dict[str, str]:
    """`B1659`. The rules the agent's table names that no call can trip —
    `B1656`'s rule, which every shipped table keeps: a `never` names what
    some call of its tools carries, so it refuses something; an `allow` or an
    `ask` names what some call its run can make carries, so it lets something
    through or asks something."""
    tools, run = kit_reach(manifest)
    return {e: r for e, r in manifest.effects.items() if e not in (tools if r == "never" else run)}


def check_grants(manifest: Manifest, raw: Any) -> Dict[str, str]:
    """A person's changes to the effects. Each may only tighten, except one
    loosening the owner allowed: `ask` → `allow` on their own hire (§3)."""
    raw = raw if isinstance(raw, dict) else {}
    base = manifest_effects(manifest)
    out: Dict[str, str] = {}
    for eff, rule in raw.items():
        if eff not in base:
            raise HireRefused(f"{manifest.name}'s tools never have the effect “{eff}”.")
        if rule not in EFFECT_RULES:
            raise HireRefused(f"“{eff}” can only be allow, ask or never.")
        was = base[eff]
        if rule == was:
            continue
        if _RULE_RANK[rule] < _RULE_RANK[was] and not (was == "ask" and rule == "allow"):
            raise HireRefused(f"{manifest.name} says “{eff}” is {was}; you can make that "
                              f"stricter, not looser.")
        out[eff] = rule
    return out


def effective_effects(manifest: Manifest, grants: Dict[str, str]) -> Dict[str, str]:
    eff = manifest_effects(manifest)
    eff.update({k: v for k, v in (grants or {}).items() if k in eff})
    return eff


#: `D-2026-10-29-01` §1 (`B1605`). What the hire form says before the hire,
#: to a person whose hire lifts the post-external gate: in plain words, that
#: *without asking* holds after the agent has read the web, and the cost.
ALLOWED_AFTER_OUTSIDE = (
    "What is set to “without asking” above runs without asking even after {name} has read a "
    "web page, an email or anything else from outside — so what it reads there can steer what "
    "it does with your data, within what you allow here. Each step it runs that way is marked "
    "on its run.")


def allowed_after_outside(manifest: Manifest, owner: Optional[str], grants: Any = None, *,
                          auth_manager: Any = None) -> Optional[str]:
    """The sentence the hire form shows before the hire, or `None`.

    `None` for a person whose hire would not lift the gate (no
    `can_auto_approve`, the one rule `approval_mode.hire_lift_for` asks), and
    for an agent none of whose *allow* effects the gate would ask about after
    outside content — reading the public web or asking a question never did,
    so there is nothing the sentence would be true of."""
    from src.approval_mode import hire_lift_for
    from src.tool_capabilities import POST_EXTERNAL_BLOCKED_EFFECTS
    if not hire_lift_for(owner, hired=True, auth_manager=auth_manager):
        return None
    gated = {e.value for e in POST_EXTERNAL_BLOCKED_EFFECTS}
    allowed = {e for e, r in effective_effects(manifest, grants or {}).items() if r == "allow"}
    return ALLOWED_AFTER_OUTSIDE.format(name=manifest.name) if allowed & gated else None


# ── Compile ─────────────────────────────────────────────────────────────────

_DOW = {"mon": "1", "tue": "2", "wed": "3", "thu": "4", "fri": "5", "sat": "6", "sun": "0"}
_DAYS = {"every": "*", "weekdays": "1-5", "weekends": "0,6"}


def trigger_task_fields(trigger: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    """What one manifest trigger is as a task's trigger columns."""
    on = trigger["on"]
    if on in ("daily", "weekly"):
        at = str(trigger.get("at") or "")
        ref = _INPUT_REF_RE.match(at)
        if ref:
            at = str(inputs.get(ref.group(1)) or "")
        if not _TIME_RE.match(at):
            raise HireRefused("The time this agent starts at is not set.")
        hh, mm = at.split(":")
        dow = _DAYS[trigger.get("days", "every")] if on == "daily" else _DOW[trigger["day"]]
        return {"trigger_type": "schedule", "schedule": "cron",
                "cron_expression": f"{int(mm)} {int(hh)} * * {dow}",
                "trigger_event": None, "trigger_count": None}
    if on == "cron":
        return {"trigger_type": "schedule", "schedule": "cron", "cron_expression": trigger["cron"],
                "trigger_event": None, "trigger_count": None}
    if on == "event":
        return {"trigger_type": "event", "schedule": None, "cron_expression": None,
                "trigger_event": trigger["event"], "trigger_count": int(trigger.get("every", 1))}
    # `webhook` and `hand`: the task engine's "fires when asked" — a webhook
    # task, which *Run now* also starts.
    return {"trigger_type": "webhook", "schedule": None, "cron_expression": None,
            "trigger_event": None, "trigger_count": None}


def _loads(text: Optional[str]) -> Dict[str, Any]:
    try:
        v = json.loads(text or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def hire_inputs(hire) -> Dict[str, Any]:
    return _loads(hire.inputs)


def hire_grants(hire) -> Dict[str, str]:
    return _loads(hire.grants)


def compile_hire(db, hire, manifest: Manifest) -> List[str]:
    """Make the hire's tasks match its manifest's triggers. Answers the task ids."""
    from core.database import AgentHireTask, ScheduledTask
    from src.task_scheduler import compute_next_run, _utcnow

    inputs = hire_inputs(hire)
    links = {l.trigger: l for l in db.query(AgentHireTask).filter(AgentHireTask.hire_id == hire.id).all()}
    tasks = {t.id: t for t in db.query(ScheduledTask).filter(
        ScheduledTask.id.in_([l.task_id for l in links.values()])).all()} if links else {}
    # `P24-13`. A trial runs only when asked: every task is the engine's
    # "fires when asked" with no token, so nothing — no schedule, no event, no
    # caller of a webhook — starts it but *Try it once* and *Run now*. *Hire*
    # compiles it again with its real triggers.
    trial = hire.status == "trial"
    paused = hire.status != "on" and not trial
    budget = manifest.budget
    ids: List[str] = []
    many = len(manifest.triggers) > 1
    for n, trig in enumerate(manifest.triggers):
        fields = trigger_task_fields(trig, inputs)
        if trial:
            fields = {"trigger_type": "webhook", "schedule": None, "cron_expression": None,
                      "trigger_event": None, "trigger_count": None}
        link = links.pop(n, None)
        task = tasks.get(link.task_id) if link else None
        if task is None:
            if link is not None:
                db.delete(link)
                db.flush()
            task = ScheduledTask(id=str(uuid.uuid4()), owner=hire.owner, task_type="llm",
                                 trigger_counter=0, run_count=0, output_target="session",
                                 notifications_enabled=True)
            db.add(task)
            db.flush()
            db.add(AgentHireTask(task_id=task.id, hire_id=hire.id, trigger=n))
        task.name = (f"{hire.name} · {describe_trigger(trig, inputs)}" if many else hire.name)[:120]
        task.prompt = TASK_PROMPT
        task.task_type = "llm"
        task.action = None
        task.max_steps = budget["max_steps"]
        task.timeout_seconds = budget["max_minutes"] * 60
        task.tz_name = hire.tz_name or None
        for k, v in fields.items():
            setattr(task, k, v)
        if fields["trigger_type"] == "webhook" and not trial:
            task.webhook_token = task.webhook_token or secrets.token_urlsafe(32)
        else:
            task.webhook_token = None
        if fields["trigger_type"] == "schedule":
            task.next_run = None if paused else compute_next_run(
                "cron", None, cron_expression=fields["cron_expression"], tz_name=hire.tz_name or None,
                after=_utcnow())
        else:
            task.next_run = None
        task.status = "paused" if paused else "active"
        ids.append(task.id)
    for leftover in links.values():
        gone = tasks.get(leftover.task_id)
        if gone is not None:
            db.delete(gone)
        db.delete(leftover)
    db.flush()
    return ids


def task_ids_of(db, hire_id: str) -> List[str]:
    from core.database import AgentHireTask
    return [l.task_id for l in db.query(AgentHireTask).filter(AgentHireTask.hire_id == hire_id)
            .order_by(AgentHireTask.trigger).all()]


def hire_for_task(db, task_id: Optional[str]):
    """The hire a task belongs to, or `None` for every task that is not an agent's."""
    if not task_id:
        return None
    from core.database import AgentHire, AgentHireTask
    link = db.query(AgentHireTask).filter(AgentHireTask.task_id == task_id).first()
    if link is None:
        return None
    return db.query(AgentHire).filter(AgentHire.id == link.hire_id).first()


def labels_for_tasks(db, task_ids) -> Dict[str, Dict[str, str]]:
    """`{task_id: {hire_id, name, agent_id}}` for the ones that are an agent's —
    one query, for the Tasks list's label (`P24-06`)."""
    from core.database import AgentHire, AgentHireTask
    ids = [t for t in task_ids if t]
    if not ids:
        return {}
    rows = (db.query(AgentHireTask, AgentHire)
            .join(AgentHire, AgentHire.id == AgentHireTask.hire_id)
            .filter(AgentHireTask.task_id.in_(ids)).all())
    return {link.task_id: {"hire_id": h.id, "name": h.name, "agent_id": h.agent_id}
            for link, h in rows}


def make_hire(db, *, owner: Optional[str], manifest: Manifest, inputs: Any = None,
              grants: Any = None, tz_name: Optional[str] = None, project: Optional[str] = None,
              name: Optional[str] = None, status: str = "on"):
    """Hire `manifest` for `owner`. Everything is checked before anything is
    written, so a refused hire leaves nothing behind."""
    from core.database import AgentHire
    checked = check_inputs(manifest, inputs)
    granted = check_grants(manifest, grants)
    tz = check_tz(tz_name)
    proj = check_project(owner, project)
    hire = AgentHire(id=str(uuid.uuid4()), owner=owner, agent_id=manifest.id,
                     version=manifest.version, name=check_name(name, manifest),
                     inputs=json.dumps(checked), grants=json.dumps(granted),
                     status=status if status in ("on", "trial") else "on",
                     tz_name=tz, project=proj)
    db.add(hire)
    db.flush()
    compile_hire(db, hire, manifest)
    return hire


def update_hire(db, hire, manifest: Manifest, *, inputs: Any = None, grants: Any = None,
                tz_name: Any = ..., project: Any = ..., name: Any = None,
                to_version: bool = False):
    """Change a hire. `to_version` moves it to the manifest's current version."""
    if to_version:
        hire.version = manifest.version
    elif manifest.version != hire.version:
        raise HireRefused(f"{manifest.name} is at {manifest.version} now and this hire is at "
                          f"{hire.version}. Update it first, then change it.", 409)
    if inputs is not None:
        hire.inputs = json.dumps(check_inputs(manifest, inputs))
    elif to_version:
        hire.inputs = json.dumps(check_inputs(manifest, hire_inputs(hire)))
    if grants is not None:
        hire.grants = json.dumps(check_grants(manifest, grants))
    elif to_version:
        hire.grants = json.dumps(check_grants(manifest, {
            k: v for k, v in hire_grants(hire).items() if k in manifest_effects(manifest)}))
    if tz_name is not ...:
        hire.tz_name = check_tz(tz_name)
    if project is not ...:
        hire.project = check_project(hire.owner, project)
    if name is not None:
        hire.name = check_name(name, manifest)
    compile_hire(db, hire, manifest)
    return hire


def set_status(db, hire, manifest: Manifest, status: str) -> None:
    if status not in ("on", "paused"):
        raise HireRefused("A hire is switched on or paused.")
    hire.status = status
    if status == "on":
        hire.attention = None
    compile_hire(db, hire, manifest)


def needs_attention(db, hire, sentence: str) -> None:
    """Stop a hire's schedule and say why, in the hire's own words."""
    from core.database import ScheduledTask
    hire.status = "attention"
    hire.attention = sentence[:500]
    for tid in task_ids_of(db, hire.id):
        t = db.query(ScheduledTask).filter(ScheduledTask.id == tid).first()
        if t is not None:
            t.status = "paused"
            t.next_run = None


def fire(db, hire) -> int:
    """Remove the hire and every task it made. Answers how many tasks went."""
    from core.database import ScheduledTask
    ids = task_ids_of(db, hire.id)
    gone = 0
    for tid in ids:
        t = db.query(ScheduledTask).filter(ScheduledTask.id == tid).first()
        if t is not None:
            db.delete(t)
            gone += 1
    db.delete(hire)
    db.flush()
    return gone


def check_name(name: Any, manifest: Manifest) -> str:
    if name is None or (isinstance(name, str) and not name.strip()):
        return manifest.name
    if not isinstance(name, str):
        raise HireRefused("A name is a line of text.")
    name = " ".join(name.split())
    if len(name) > NAME_MAX:
        raise HireRefused(f"A name is at most {NAME_MAX} characters.")
    return name


def check_tz(tz_name: Any) -> Optional[str]:
    if tz_name in (None, ""):
        return None
    from src.task_scheduler import valid_timezone
    tz = valid_timezone(str(tz_name).strip())
    if tz is None:
        raise HireRefused(f"Not a timezone this machine knows: {tz_name!r}. Use an IANA name "
                          f"such as 'Australia/Sydney' or 'UTC'.")
    return tz


def check_project(owner: Optional[str], project: Any) -> Optional[str]:
    """A project is a folder directly inside the person's own projects folder."""
    if project in (None, ""):
        return None
    if not isinstance(project, str) or not re.fullmatch(r"[^/\\]{1,120}", project.strip()) \
            or project.strip() in (".", ".."):
        raise HireRefused("A project is one folder inside your projects folder.")
    import os
    from src.tool_execution import projects_root
    if not os.path.isdir(os.path.join(projects_root(owner), project.strip())):
        raise HireRefused(f"There is no project called “{project.strip()}” in your projects folder.")
    return project.strip()


def hire_to_dict(db, hire, manifest: Optional[Manifest]) -> Dict[str, Any]:
    """A hire as the hall reads it."""
    from core.database import ScheduledTask, TaskRun
    ids = task_ids_of(db, hire.id)
    tasks = db.query(ScheduledTask).filter(ScheduledTask.id.in_(ids)).all() if ids else []
    by_id = {t.id: t for t in tasks}
    last = (db.query(TaskRun).filter(TaskRun.task_id.in_(ids))
            .order_by(TaskRun.started_at.desc()).first()) if ids else None
    nexts = [t.next_run for t in tasks if t.next_run]
    inputs = hire_inputs(hire)
    out = {
        "id": hire.id, "agent_id": hire.agent_id, "name": hire.name, "owner": hire.owner,
        "version": hire.version, "status": hire.status, "attention": hire.attention,
        "inputs": inputs, "grants": hire_grants(hire), "tz_name": hire.tz_name,
        "project": hire.project,
        "created_at": hire.created_at.isoformat() + "Z" if hire.created_at else None,
        "tasks": [{"id": tid, "trigger_type": by_id[tid].trigger_type,
                   "webhook_token": by_id[tid].webhook_token,
                   "session_id": by_id[tid].session_id} for tid in ids if tid in by_id],
        "next_run": min(nexts).isoformat() + "Z" if nexts else None,
        "last_run": ({"id": last.id, "status": last.status,
                      "started_at": last.started_at.isoformat() + "Z" if last.started_at else None,
                      "finished_at": last.finished_at.isoformat() + "Z" if last.finished_at else None}
                     if last else None),
        "notebook": hire.notebook or "",
    }
    if manifest is not None:
        out["starts_on"] = describe_triggers(manifest.triggers, inputs)
        out["icon"] = manifest.icon
        out["section"] = manifest.section
        out["update_to"] = manifest.version if manifest.version != hire.version else None
        out["effects"] = effective_effects(manifest, hire_grants(hire))
        out["lacking"] = lacking_tools(manifest, hire.owner)
    else:
        out["starts_on"] = ""
        out["missing"] = True
    return out


def task_belongs_to_agent(task_name: str, hire_name: str) -> str:
    """The Tasks window's sentence for a task an agent runs as."""
    return (f"“{task_name}” is how the agent {hire_name} runs. Change, pause or dismiss it in "
            f"Agents; Run now works here too.")


def hire_team(db, *, owner: Optional[str], team, manifests: Dict[str, Manifest],
              inputs: Any = None, tz_name: Optional[str] = None,
              project: Optional[str] = None) -> Dict[str, Any]:
    """`P24-21`. *Hire all*: one hire per member this person has not hired,
    each given the shared values for the keys it asks for. Every member is
    checked before any is written, so a refusal leaves nothing behind."""
    from core.database import AgentHire
    values = inputs if isinstance(inputs, dict) else {}
    already = {h.agent_id for h in db.query(AgentHire).filter(AgentHire.owner == owner).all()}
    tz = check_tz(tz_name)
    proj = check_project(owner, project)
    plan = []
    for mid in team.members:
        m = manifests.get(mid)
        if m is None:
            raise HireRefused(f"{team.name} names {mid}, which the hall does not have.", 409)
        if mid in already:
            continue
        from src.agents.teams import member_values
        mine = member_values(team, manifests, mid, values)
        try:
            check_inputs(m, mine)
        except HireRefused as refused:
            raise HireRefused(f"{m.name}: {refused.sentence}") from None
        plan.append((m, mine))
    made = []
    for m, mine in plan:
        made.append(make_hire(db, owner=owner, manifest=m, inputs=mine, tz_name=tz, project=proj))
    return {"hired": made, "kept": [mid for mid in team.members if mid in already]}
