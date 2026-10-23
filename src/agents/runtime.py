# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-05` / `P24-06` / `P24-07` · A run of a hire, and what it leaves.

A hire's task runs through the task engine's own `_execute_llm_task`, which
asks `plan_for_task` first. For every task that is not an agent's the answer is
`None` and nothing changes (`Law 1`). For an agent's it is the run's whole
assembly, built from the hire and its manifest at the moment the run starts:

* **the system prompt** — who the agent is, the runbook, and the report shape;
* **the tools** — exactly the manifest's, minus any whose effects the hire
  says `never` (the slot's `allowed_tools`, `P22-16`'s closed list, so no
  retrieval guess adds or drops one — `B1414`/`B1416`);
* **the effects** that ask before running, per call (`ToolPolicy.ask_effects`,
  answered by `ToolRunSecurityContext` before the trust ladder, so a chat's
  Auto never skips what a hire said to ask about);
* **its skills**, followed whole with keyword injection suppressed;
* **its inputs** and **its notebook** — what the hirer filled in, and what the
  last runs carried forward — as context messages.

After the run, `record_report` keeps what it left: the answer, what it read
and wrote, what it was refused, and the *Carry forward* section, which becomes
the notebook the next run reads (`memory: own`). How the run ended stays
`task_runs.status`, the one answer (`Law 7`).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional

NOTEBOOK_MAX_CHARS = 4000
ANSWER_MAX_CHARS = 20_000

REPORT_HEADING = "## Report"
CARRY_HEADING = "## Carry forward"


from src.builtin_actions import TaskDeferred, TaskNoop  # noqa: E402

#: `P24-10`. How long a run that found the install at its limit of agent runs
#: waits before it asks again — the task engine's own deferral (`TaskDeferred`:
#: no run row, the task's next time moved), not a failure.
CAPACITY_RETRY_SECONDS = 120
#: `P24-09`. A delivery that fails its checks gets exactly this many repair
#: passes, the failed checks named, and then the hire is flagged.
REPAIR_PASSES = 1
ALL_PAUSED = ("An admin has paused all agents (Settings → Agents), so this run did not "
              "start. Nothing is lost: it runs on its next time once they are switched back on.")


class AgentRunRefused(TaskNoop):
    """A run of a hire that does not start, and the sentence its log says.

    A `TaskNoop`, so the task engine records the run `skipped` with this
    sentence (`_execute_task_locked`) — it is the hire's state, not a failure
    of the run, and must not count toward three failures in a row."""

    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


class AgentDidNotDeliver(RuntimeError):
    """A run whose delivery failed its checks after its repair pass. Raised
    after the report is kept, so the run ends `error` with this sentence."""

    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


@dataclass
class RunPlan:
    hire_id: str
    agent_id: str
    name: str
    system_prompt: str
    tools: List[str]
    ask_effects: frozenset
    never_effects: frozenset
    context_messages: List[dict] = field(default_factory=list)
    skill_lines: List[str] = field(default_factory=list)
    delivers: tuple = ()
    owner: Optional[str] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    project: Optional[str] = None
    memory: str = "own"


def _person(owner: Optional[str]) -> str:
    return owner or "the person who hired you"


def system_prompt(manifest, hire, *, owner: Optional[str]) -> str:
    lines = [
        f"You are {hire.name}, an agent {_person(owner)} hired in Pantheon to do one job: "
        f"{manifest.tagline}",
        "",
        "The job is the runbook below. Follow it in order. Use only the tools you are "
        "given, and do nothing the runbook does not ask for. If something you need is "
        "missing or a step cannot be done, say so plainly in your report rather than "
        "guessing.",
        "",
        "When you are done, your last message is your answer, and it ends with these "
        "sections:",
        "",
        f"{REPORT_HEADING}",
        "- what you did and what you left behind, a line each",
    ]
    if manifest.memory != "none":
        lines += [
            "",
            f"{CARRY_HEADING}",
            "- only what your next run needs to remember (or the single word: nothing)",
        ]
    if hire.project:
        lines += ["", f"You work in the project folder “{hire.project}” inside the person's "
                      f"projects folder (in the workstation: $PANTHEON_PROJECTS/{hire.project})."]
    lines += ["", "# Runbook", "", manifest.runbook.strip()]
    return "\n".join(lines)


def _skill_messages(owner, name: str):
    """First-party skills (`library/pantheon/skills`) and the person's own are
    the person's side of the line, so they do not arm the gate; a vendored
    skill is someone else's text and does, as a workflow's Skill step does."""
    from services.memory.skills import SkillsManager
    from src.constants import DATA_DIR
    from src.prompt_security import own_context_message, untrusted_context_message
    sm = SkillsManager(DATA_DIR)
    md = sm.read_skill_md(name, owner, include_library=True)
    if md is None:
        return [], f"The skill “{name}” is not there any more, so this run went without it."
    path = sm._readable_skill_path(name, owner, include_library=True) or ""
    first_party = os.sep + os.path.join("library", "pantheon", "skills") + os.sep in path
    own = sm._find_skill_path(name, owner) is not None
    if first_party or own:
        return [own_context_message(f"the skill “{name}”", md)], f"Followed the skill “{name}”."
    return [untrusted_context_message(f"the skill “{name}”", md)], f"Followed the skill “{name}”."


def runs_today(db, task_ids: List[str]) -> int:
    from core.database import TaskRun
    from src.task_scheduler import _utcnow
    if not task_ids:
        return 0
    since = _utcnow() - timedelta(hours=24)
    return (db.query(TaskRun).filter(TaskRun.task_id.in_(task_ids), TaskRun.started_at >= since,
                                     TaskRun.status.in_(("running", "success", "error", "waiting")))
            .count())


def agents_paused() -> bool:
    """`P24-10`. The admin's *Pause all agents* (`agents_paused`)."""
    from src.settings import get_setting
    return get_setting("agents_paused", False) is True


def max_concurrent() -> int:
    from src.settings import get_setting
    try:
        return max(1, int(get_setting("agents_max_concurrent", 2) or 2))
    except (TypeError, ValueError):
        return 2


def agent_runs_running(db, *, besides: Optional[str] = None) -> int:
    """How many runs of any hire are going now, this one apart."""
    from core.database import AgentHireTask, TaskRun
    q = (db.query(TaskRun.id).join(AgentHireTask, AgentHireTask.task_id == TaskRun.task_id)
         .filter(TaskRun.status == "running"))
    if besides:
        q = q.filter(TaskRun.id != besides)
    return q.count()


def plan_for_task(db, task, run_id: Optional[str] = None) -> Optional[RunPlan]:
    """`None` for a task that is not an agent's. Raises `AgentRunRefused` (the
    run is recorded `skipped` with the sentence) for a hire that cannot run now
    — parking the hire with the reason where the reason is the hire's — and
    `TaskDeferred` when the install is at its limit of agent runs."""
    from src.agents import hires as H
    from src.agents.catalogue import get_agent
    from src.prompt_security import own_context_message
    from src.tool_capabilities import capabilities_for_tool

    hire = H.hire_for_task(db, getattr(task, "id", None))
    if hire is None:
        return None
    if agents_paused():
        raise AgentRunRefused(ALL_PAUSED)
    if agent_runs_running(db, besides=run_id) >= max_concurrent():
        raise TaskDeferred(f"{max_concurrent()} agent runs are going already, the most this "
                           f"install allows at once; {hire.name} runs when one finishes.",
                           delay_seconds=CAPACITY_RETRY_SECONDS)
    manifest = get_agent(hire.owner, hire.agent_id)
    if manifest is None:
        sentence = (f"{hire.name}'s agent file is gone or no longer passes its check, so it "
                    f"stopped. Open Agents to fire it or put the file back.")
        H.needs_attention(db, hire, sentence)
        db.commit()
        raise AgentRunRefused(sentence)
    if manifest.version != hire.version:
        sentence = (f"{manifest.name} was updated to {manifest.version} (this hire is at "
                    f"{hire.version}). It is paused until you open it in Agents and choose Update.")
        H.needs_attention(db, hire, sentence)
        db.commit()
        raise AgentRunRefused(sentence)
    ids = H.task_ids_of(db, hire.id)
    # The run being started is already counted as `running`.
    if runs_today(db, ids) > manifest.budget["runs_per_day"]:
        # `P24-10`. A budget hit parks the hire with the reason — the plan's
        # rule — so a trigger that fires all day stops asking.
        sentence = (f"{hire.name} has already run {manifest.budget['runs_per_day']} times in the "
                    f"last 24 hours, its limit, so it is paused. Switch it back on in Agents.")
        H.needs_attention(db, hire, sentence)
        db.commit()
        raise AgentRunRefused(sentence)

    effects = H.effective_effects(manifest, H.hire_grants(hire))
    never = frozenset(e for e, r in effects.items() if r == "never")
    ask = frozenset(e for e, r in effects.items() if r == "ask")
    tools = [t for t in manifest.tools
             if not ({e.value for e in capabilities_for_tool(t).effects} & never)]

    msgs: List[dict] = []
    inputs = H.hire_inputs(hire)
    if inputs:
        labels = {i["key"]: i["label"] for i in manifest.inputs}
        body = "\n".join(
            f"{labels.get(k, k)}: {', '.join(v) if isinstance(v, list) else v}"
            for k, v in inputs.items())
        msgs.append(own_context_message("what you were hired with", body))
    if manifest.memory != "none" and (hire.notebook or "").strip():
        # The agent's own words from its last run — but those words may quote
        # mail or a page it read, so they stay data, never instructions.
        from src.prompt_security import untrusted_context_message
        msgs.append(untrusted_context_message("your notebook (what your last run carried forward)",
                                              hire.notebook, arm_tool_gate=False))
    lines: List[str] = []
    for skill in manifest.skills:
        m, line = _skill_messages(hire.owner, skill)
        msgs.extend(m)
        lines.append(line)
    return RunPlan(hire_id=hire.id, agent_id=manifest.id, name=hire.name,
                   system_prompt=system_prompt(manifest, hire, owner=hire.owner), tools=tools,
                   ask_effects=ask, never_effects=never, context_messages=msgs,
                   skill_lines=lines, memory=manifest.memory, delivers=manifest.delivers,
                   owner=hire.owner, inputs=inputs, project=hire.project)


# ── The report ──────────────────────────────────────────────────────────────

def _section(text: str, heading: str) -> str:
    """The body under `heading`, up to the next `## ` heading."""
    pattern = re.compile(rf"^{re.escape(heading)}\s*$", re.M | re.I)
    m = pattern.search(text or "")
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return (rest[:nxt.start()] if nxt else rest).strip()


def carried_forward(answer: str) -> str:
    body = _section(answer, CARRY_HEADING)
    if body.strip().strip("-* .").lower() in ("", "nothing", "none"):
        return ""
    return body[:NOTEBOOK_MAX_CHARS]


def _effect_bucket(tool: str, detail: str = "") -> str:
    """`read` or `wrote`, by what this call did — `manage_calendar` listing
    events reads, creating one writes — and by the tool's whole reach when the
    call's arguments are not on the step (`capabilities_for_action`)."""
    from src.tool_capabilities import capabilities_for_action, capabilities_for_tool
    caps = capabilities_for_tool(tool)
    if isinstance(detail, str) and detail.lstrip().startswith("{"):
        try:
            caps = capabilities_for_action(tool, detail)
        except Exception:
            pass
    effs = {e.value for e in caps.effects}
    if effs & {"write_workspace", "write_private", "external_side_effect", "destructive",
               "execute_code", "admin_change", "ui_side_effect"}:
        return "wrote"
    return "read"


def build_report(answer: str, steps: List[dict]) -> Dict[str, Any]:
    read: List[str] = []
    wrote: List[str] = []
    refused: List[Dict[str, str]] = []
    for s in steps or ():
        if s.get("kind") != "tool":
            continue
        tool = str(s.get("tool") or "?")
        if s.get("status") == "blocked":
            refused.append({"tool": tool, "reason": str(s.get("output") or "")[:300]})
            continue
        bucket = read if _effect_bucket(tool, str(s.get("detail") or "")) == "read" else wrote
        if tool not in bucket:
            bucket.append(tool)
    return {
        "answer": (answer or "")[:ANSWER_MAX_CHARS],
        "summary": _section(answer, REPORT_HEADING)[:2000],
        "read": read, "wrote": wrote, "refused": refused,
        "carried": carried_forward(answer),
    }


# ── `P24-09` · the contract check ───────────────────────────────────────────
#
# `delivers` is checked by code: a model saying "done" counts for nothing. Each
# check is `{check, ok, detail}` in a person's words; the run report keeps them.

DRAFT_TOOLS = ("draft_email", "draft_email_reply", "ai_draft_email_reply")
_REF_RE = re.compile(r"\{([a-z][a-z0-9_]{0,31})\}")


def _fill(text: str, inputs: Dict[str, Any]) -> str:
    """`{key}` → the hire's input; any other `{…}` (a date, say) is dropped,
    so a title is matched on its fixed words."""
    def sub(m):
        v = inputs.get(m.group(1))
        return "" if v is None or isinstance(v, (list, dict)) else str(v)
    return _REF_RE.sub(sub, text or "").strip()


def _missing_words(text: str, words) -> List[str]:
    low = (text or "").lower()
    return [w for w in (words or ()) if str(w).lower() not in low]


def run_started_at(db, run_id: Optional[str]):
    from core.database import TaskRun
    if not run_id:
        return None
    row = db.query(TaskRun.started_at).filter(TaskRun.id == run_id).first()
    return row[0] if row else None


def check_contract(db, plan: "RunPlan", answer: str, steps: List[dict], *,
                   since=None) -> List[Dict[str, Any]]:
    """Every `delivers` entry, checked. Empty when the manifest declares none."""
    out: List[Dict[str, Any]] = []
    for d in plan.delivers or ():
        kind = d.get("kind")
        words = d.get("must_contain") or []
        if kind == "answer":
            missing = _missing_words(answer, words)
            if not (answer or "").strip():
                out.append({"check": "an answer", "ok": False, "detail": "The run ended without an answer."})
            elif missing:
                out.append({"check": "the answer's sections", "ok": False,
                            "detail": f"The answer does not say: {', '.join(missing)}."})
            else:
                out.append({"check": "the answer", "ok": True,
                            "detail": "It answered" + (f", with {', '.join(words)}." if words else ".")})
        elif kind == "document":
            from core.database import Document
            title = _fill(str(d.get("title") or ""), plan.inputs)
            q = db.query(Document).filter(Document.owner == plan.owner)
            if since is not None:
                q = q.filter(Document.updated_at >= since - timedelta(seconds=5))
            docs = [doc for doc in q.all() if not title or title.lower() in (doc.title or "").lower()]
            what = f"a document titled “{title}”" if title else "a document"
            if not docs:
                out.append({"check": what, "ok": False,
                            "detail": f"No {what[2:] if what.startswith('a ') else what} was written in this run."})
                continue
            best = max(docs, key=lambda doc: doc.updated_at or doc.created_at)
            missing = _missing_words(best.current_content, words)
            if missing:
                out.append({"check": what, "ok": False,
                            "detail": f"“{best.title}” has no {', '.join(missing)}."})
            else:
                out.append({"check": what, "ok": True, "detail": f"“{best.title}” is there."})
        elif kind == "email_draft":
            made = sum(1 for st in steps or () if st.get("kind") == "tool"
                       and st.get("tool") in DRAFT_TOOLS and st.get("status") in ("ok", None))
            cap = d.get("max")
            if isinstance(cap, int) and made > cap:
                out.append({"check": f"at most {cap} drafts", "ok": False,
                            "detail": f"It made {made} drafts; its limit is {cap}."})
            else:
                out.append({"check": "drafts" if cap is None else f"at most {cap} drafts", "ok": True,
                            "detail": f"It made {made} draft{'' if made == 1 else 's'}."})
        elif kind == "file":
            rel = _fill(str(d.get("title") or ""), plan.inputs)
            from src.tool_execution import projects_root
            base = projects_root(plan.owner, create=False)
            if plan.project:
                base = os.path.join(base, plan.project)
            path = os.path.normpath(os.path.join(base, rel))
            inside = path == base or path.startswith(base + os.sep)
            if not rel or not inside or not os.path.exists(path):
                out.append({"check": f"the file {rel or '(unnamed)'}", "ok": False,
                            "detail": f"There is no {rel or 'file'} in the projects folder."})
                continue
            text = ""
            if words and os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        text = fh.read(512 * 1024)
                except OSError:
                    text = ""
            missing = _missing_words(text, words)
            out.append({"check": f"the file {rel}", "ok": not missing,
                        "detail": (f"{rel} has no {', '.join(missing)}." if missing else f"{rel} is there.")})
    return out


def failed(checks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [c for c in checks or () if not c.get("ok")]


def repair_prompt(checks: List[Dict[str, Any]]) -> str:
    lines = "\n".join(f"- {c['detail']}" for c in failed(checks))
    return ("Your run is not finished: what it had to leave behind is not all there.\n"
            f"{lines}\n"
            "Do what is missing now, using your tools, then give your whole answer again, "
            "ending with your Report section.")


def answer_so_far(answer: str) -> dict:
    """The first pass's answer, handed to the repair pass as data: it may
    quote mail or a page the run read, so it never arms the gate and is never
    an instruction."""
    from src.prompt_security import untrusted_context_message
    return untrusted_context_message("your answer so far (this run)", (answer or "")[:ANSWER_MAX_CHARS],
                                     arm_tool_gate=False)


def undelivered_sentence(name: str, checks: List[Dict[str, Any]]) -> str:
    first = failed(checks)[0]["detail"] if failed(checks) else "its checks failed"
    return (f"{name} did not deliver, even after one more try: {first} It is paused until "
            f"you look; switch it back on in Agents.")


def record_report(db, task, run_id: Optional[str], answer: str, steps: List[dict], *,
                  checks: Optional[List[Dict[str, Any]]] = None,
                  repaired: bool = False) -> Optional[dict]:
    """Keep what a finished run left, and move its carry-forward into the
    hire's notebook. Answers the report, or `None` for a task that is not an
    agent's or a run with no record."""
    from core.database import AgentRunReport, TaskRun
    from src.agents import hires as H
    hire = H.hire_for_task(db, getattr(task, "id", None))
    if hire is None or not run_id:
        return None
    if db.query(TaskRun.id).filter(TaskRun.id == run_id).first() is None:
        return None
    report = build_report(answer, steps)
    report["checks"] = list(checks or [])
    report["repaired"] = bool(repaired)
    row = db.query(AgentRunReport).filter(AgentRunReport.run_id == run_id).first()
    if row is None:
        row = AgentRunReport(run_id=run_id, hire_id=hire.id, report=json.dumps(report))
        db.add(row)
    else:
        row.report = json.dumps(report)
    if report["carried"]:
        hire.notebook = report["carried"]
    db.commit()
    return report
