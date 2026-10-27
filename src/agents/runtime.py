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
    sealed: bool = False
    blind: bool = False
    workspace: Optional[str] = None
    #: `P24-09`. What the agent is for, in its file's words — the judge reads it.
    tagline: str = ""


#: `D-2026-10-24-01`. A tool with any of these effects can carry data out of
#: the install — the network, a search or fetch, sending, a shell, settings.
#: A kit with none of them is *sealed*.
SEALING_EFFECTS = frozenset({"network_egress", "brokered_network_read", "external_side_effect",
                             "execute_code", "admin_change"})


def workspace_for(owner: Optional[str], project: Optional[str]) -> Optional[str]:
    """`B1434`. The folder a hire's run works in: its project inside the
    person's projects folder, or the whole projects folder with none — so a
    relative path a runbook writes (`site/index.html`) lands there, and an
    input that names a folder "inside your projects folder" resolves. `None`
    where this person's tools run in their workstation: there the tools start
    in the workstation home, whose `/projects` is the same folder
    (`D-2026-10-01-01`)."""
    try:
        from src.workstation_access import routes_tools
        if routes_tools(owner):
            return None
    except Exception:
        pass
    from src.tool_execution import projects_root, vet_workspace
    root = projects_root(owner, create=True)
    if project:
        path = os.path.join(root, project)
        os.makedirs(path, exist_ok=True)
        return vet_workspace(path)
    return vet_workspace(root)


#: `D-2026-10-24-02`. A tool with any of these effects can read the person's
#: private data: a shell reads anything, settings hold secrets, and a tool
#: that writes notes, documents or files is one call from reading them
#: (`manage_documents` is classed `write_private` and also lists and reads).
#: A kit with none of them is *blind*.
PRIVATE_READ_EFFECTS = frozenset({"read_private", "read_workspace", "write_private", "write_workspace",
                                  "execute_code", "admin_change"})


#: Tools that write something new and cannot read back what is there.
WRITE_ONLY_TOOLS = frozenset({"create_document", "draft_email", "write_file"})


def is_blind(tools) -> bool:
    """Whether a kit cannot read any of the person's private data."""
    from src.tool_capabilities import capabilities_for_tool
    return bool(tools) and all(
        capabilities_for_tool(t).known
        and (t in WRITE_ONLY_TOOLS
             or not ({e.value for e in capabilities_for_tool(t).effects} & PRIVATE_READ_EFFECTS))
        for t in tools)


def is_sealed(tools) -> bool:
    """Whether a kit cannot carry data out of the install."""
    from src.tool_capabilities import capabilities_for_tool
    return all(not ({e.value for e in capabilities_for_tool(t).effects} & SEALING_EFFECTS)
               and capabilities_for_tool(t).known for t in tools)


def _person(owner: Optional[str]) -> str:
    return owner or "the person who summoned you"


def system_prompt(manifest, hire, *, owner: Optional[str]) -> str:
    lines = [
        f"You are {hire.name}, an agent {_person(owner)} summoned in Pantheon to do one job: "
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
                    f"stopped. Open Agents to dismiss it or put the file back.")
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
                   owner=hire.owner, inputs=inputs, project=hire.project,
                   sealed=is_sealed(tools), blind=is_blind(tools), workspace=workspace_for(hire.owner, hire.project),
                   tagline=manifest.tagline)


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
        tool = _bare(s.get("tool")) or "?"
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


def _bare(tool) -> str:
    """`B1433`. The loop records the built-in mail tools under their MCP
    spelling (`mcp__email__draft_email_reply`); a count by the bare name
    found none, so a hire's draft limit was never enforced."""
    tool = str(tool or "")
    return tool[len("mcp__email__"):] if tool.startswith("mcp__email__") else tool
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
                       and _bare(st.get("tool")) in DRAFT_TOOLS and st.get("status") in ("ok", None))
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


# ── `P24-09` · the judge, second and optional ───────────────────────────────
#
# After the code's checks pass, a model may read the delivery against what the
# file promises — opt-in (`agents_judge`, Settings → Agents, off as shipped),
# and only through the person's own background-task chain (`task_llm_call_async`
# with the run's own endpoint as its fallback): no new destination (`Law 16`).
# Its verdict is an enum, never a yes/no a reader can flip (`Law 10`):
#
# * `delivered` — it agrees; the check is ✓.
# * `not_delivered` — it says what is missing; the check is ✗, and it feeds the
#   same single repair pass the code's misses do.
# * `unread` — it gave no usable reading (no model answered, or not JSON). The
#   code's checks are the contract, so this does not fail a run that passed
#   them — and the report says plainly that only they counted.

JUDGE_VERDICTS = ("delivered", "not_delivered", "unread")
JUDGE_CHECK = "a second reading"
JUDGE_ANSWER_CHARS = 12_000
_JUDGE_REASONS = 5
_JUDGE_REASON_CHARS = 300


def judge_enabled() -> bool:
    """`P24-09`. Has an admin asked for the judge? Read as `is True`, so a
    string stored by hand turns nothing on."""
    from src.settings import get_setting
    return get_setting("agents_judge", False) is True


def describe_deliverable(d: Dict[str, Any], inputs: Optional[Dict[str, Any]] = None) -> str:
    """One `delivers` entry in a person's words — what the judge is asked about."""
    if d.get("label"):
        return str(d["label"])
    words = d.get("must_contain") or []
    say = f", which says: {', '.join(words)}" if words else ""
    kind = d.get("kind")
    if kind == "answer":
        return "An answer" + say
    if kind == "document":
        title = _fill(str(d.get("title") or ""), inputs or {})
        return (f"A document titled “{title}”" if title else "A document") + (
            f", with the sections: {', '.join(words)}" if words else "")
    if kind == "email_draft":
        cap = d.get("max")
        return "Email drafts" + (f", at most {cap}" if isinstance(cap, int) else "")
    if kind == "file":
        return f"The file {_fill(str(d.get('title') or ''), inputs or {})} in the projects folder" + say
    return str(kind or "something")


def judge_messages(plan: "RunPlan", answer: str, checks: List[Dict[str, Any]]) -> List[dict]:
    """What the judge is handed: the promises, what the code found, and the
    answer — the answer as data, since it may quote mail or a page the run
    read and must not instruct the judge."""
    from src.prompt_security import untrusted_context_message
    promises = "\n".join(f"- {describe_deliverable(d, plan.inputs)}" for d in plan.delivers or ())
    found = "\n".join(f"- {c.get('detail')}" for c in checks or () if c.get("check") != JUDGE_CHECK)
    system = (
        "You check whether an agent's run delivered what its file promises. You are not the "
        "agent and you do no work: you read and decide.\n"
        f"The agent: {plan.name}" + (f" — {plan.tagline}" if plan.tagline else "") + "\n"
        f"It promises to leave:\n{promises}\n"
        f"Code has already checked, and found:\n{found or '- nothing to check'}\n"
        "Read the answer below and decide whether it really does what is promised — not "
        "just that the words appear, but that it is the thing a person would expect.\n"
        'Reply with JSON only, nothing else: {"verdict": "delivered" or "not_delivered", '
        '"reasons": ["one short sentence each, at most five"]}. When it is not delivered, '
        "say exactly what is missing, as the agent would need to hear it to fix it."
    )
    return [
        {"role": "system", "content": system},
        untrusted_context_message("the agent's answer (this run)",
                                  (answer or "")[:JUDGE_ANSWER_CHARS], arm_tool_gate=False),
        {"role": "user", "content": "Your verdict, as JSON only."},
    ]


def read_verdict(text: str) -> Optional[Dict[str, Any]]:
    """The judge's reply → `{verdict, reasons}`, or `None` when it is not the
    JSON it was asked for. A reasoning model's thinking is stripped first."""
    try:
        from src.text_helpers import strip_think
        text = strip_think(text or "", prose=False) or text
    except Exception:
        pass
    raw = str(text or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("verdict") not in ("delivered", "not_delivered"):
        return None
    reasons = data.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    if not isinstance(reasons, list):
        reasons = []
    reasons = [str(r).strip()[:_JUDGE_REASON_CHARS] for r in reasons if str(r).strip()][:_JUDGE_REASONS]
    return {"verdict": data["verdict"], "reasons": reasons}


async def judge_delivery(plan: "RunPlan", answer: str, checks: List[Dict[str, Any]],
                         call) -> Dict[str, Any]:
    """Ask the judge once; answer its check, in the shape the report keeps.

    `call(messages)` is the person's own model chain (the scheduler hands
    `task_llm_call_async` bound to the run's endpoint and owner)."""
    try:
        reply = await call(judge_messages(plan, answer, checks))
        verdict = read_verdict(reply)
        why = "its reply was not the verdict it was asked for" if verdict is None else ""
    except Exception as exc:
        verdict, why = None, f"no model answered: {str(exc)[:160]}"
    if verdict is None:
        return {"check": JUDGE_CHECK, "ok": True, "verdict": "unread", "reasons": [],
                "detail": f"The judge model gave no reading ({why}), so only the checks above count."}
    reasons = verdict["reasons"]
    if verdict["verdict"] == "delivered":
        return {"check": JUDGE_CHECK, "ok": True, "verdict": "delivered", "reasons": reasons,
                "detail": "The judge model read it and agrees it delivers"
                          + (f": {reasons[0]}" if reasons else ".")}
    said = " ".join(r if r.endswith((".", "!", "?")) else r + "." for r in reasons) \
        or "It did not say why."
    return {"check": JUDGE_CHECK, "ok": False, "verdict": "not_delivered", "reasons": reasons,
            "detail": f"The judge model read it and says it does not deliver: {said}"}


async def checks_for_run(db, plan: "RunPlan", answer: str, steps: List[dict], *,
                         since=None, judge=None) -> List[Dict[str, Any]]:
    """The code's checks, then — only when they all pass, the plan promises
    something, and `judge` is given (the scheduler gives it only when
    `judge_enabled()`) — the judge's reading beside them."""
    checks = check_contract(db, plan, answer, steps, since=since)
    if judge is not None and plan.delivers and not failed(checks):
        checks.append(await judge_delivery(plan, answer, checks, judge))
    return checks


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
