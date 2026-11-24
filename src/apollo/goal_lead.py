# SPDX-License-Identifier: AGPL-3.0-or-later
"""A lead Apollo writes for one goal, made when the goal is made.

The owner's direction (2026-11-24): Apollo should work like Claude's Duet and
ChatGPT's Dot, with a team the way Grok runs one, "just not individual bots
assigned off rip — they can be dynamic". Until this, every goal was handed to
a saved agent picked from the roster by word match (`lead.pick_lead`), and a
goal no saved agent fit waited on a drafted agent an admin had to approve. He
was asked whether Apollo should instead write a lead for each goal that is
never saved, so it needs no approval, and said yes.

So a goal's lead is now written for that goal: a name, a one-line role, a
runbook of steps and a kit, from what Apollo says (`spec`) or from the goal
itself. It is the same file a person's own agent is (`AGENT.md`), checked by
the same rule (`workshop.check`), but it lives with the goal under
`<data>/apollo_goal_leads/<person>/<id>/`, never in the roster or the hall. It
stays with the goal as the record of who led it (a goal is closed, never
deleted). A saved agent still leads when one is named, the saved agent that
best fits the goal (`lead.pick_lead`) is named in the written lead's runbook
as the teammate to hand to, and a new saved agent still needs an admin
(`gaps.py`).

What a written lead may hold is narrower than what a person may write:
  * only tools a person could pick (`tool_policy.selectable_tool_names`), and
    never one that changes the server (`admin_change`);
  * every effect that writes, sends, runs code or reaches out is `ask`; only
    reads are `allow`;
  * a delegate is still cut to its parent's kit (`fleet.narrow`), so a lead
    Apollo writes never holds more than the goal above it.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

PREFIX = "goal-"
ROOT_NAME = "apollo_goal_leads"
NAME_MAX = 48
ROLE_MAX = 140
STEP_MAX = 400
STEPS_MAX = 12
TOOLS_MAX = 12

# A lead with no kit named gets the reading kit: look things up, read the
# workspace, keep a plan. Anything more is Apollo's to name for the goal.
DEFAULT_TOOLS = ("web_search", "web_fetch", "read_file", "ls", "update_plan")
ALLOWED_EFFECTS = frozenset({"read_private", "read_workspace", "brokered_network_read",
                             "user_interaction", "ui_side_effect"})
BARRED_EFFECTS = frozenset({"admin_change"})

DEFAULT_STEPS = (
    "Read the goal and its brief, and decide the few steps it takes to finish it.",
    "Do each step with the tools you have, and stop as soon as the goal is met.",
    "When a part needs something you can't do, hand it to a teammate with the fleet tool, "
    "with a brief that says what done looks like.",
    "When a decision or a yes is the person's, escalate it with the fleet tool and end the run.",
    "Never send, pay, delete or change settings without the person's yes.",
)

# Every written lead ends with these, whatever steps Apollo gave it.
KEEP_STEPS = DEFAULT_STEPS[-2:]

_ID_RE = re.compile(r"goal-[0-9a-f]{20}")   # a goal's uuid, so no named agent can collide


# Where every person's goal leads go when no data dir is passed; None is
# `<DATA_DIR>/apollo_goal_leads`. Tests give each test a folder of its own.
BASE_DIR: Optional[str] = None


def root(owner: Optional[str], data_dir: Optional[str] = None) -> str:
    """Where this person's goal leads live: beside, never inside, their roster."""
    from src.constants import DATA_DIR
    from src.workstation_access import workstation_owner
    from workstation.protocol import project_folder
    base = os.path.join(data_dir, ROOT_NAME) if data_dir else (BASE_DIR or os.path.join(DATA_DIR, ROOT_NAME))
    return os.path.join(base, project_folder(workstation_owner(owner)))


def lead_id(task_id: Any) -> str:
    """The lead's id for a goal: the goal's id, so one goal has one lead."""
    return PREFIX + re.sub(r"[^0-9a-f]", "", str(task_id or "").lower())[:20]


def is_goal_lead(agent_id: Any) -> bool:
    return bool(_ID_RE.fullmatch(str(agent_id or "")))


def _path(owner: Optional[str], agent_id: str, data_dir: Optional[str]) -> str:
    from src.agents.catalogue import MANIFEST_NAME
    return os.path.join(root(owner, data_dir), agent_id, MANIFEST_NAME)


def _line(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _kit(asked: Any) -> List[str]:
    """The tools a written lead may hold, from what Apollo asked for."""
    from src.agents.hires import tool_effects
    from src.tool_policy import selectable_tool_names
    known = set(selectable_tool_names())
    names = asked if isinstance(asked, (list, tuple)) and asked else DEFAULT_TOOLS
    kit: List[str] = []
    for name in names:
        name = str(name or "").strip()
        if name in known and name not in kit and not (set(tool_effects(name)) & BARRED_EFFECTS):
            kit.append(name)
    return kit[:TOOLS_MAX]


def _effects(kit: List[str]) -> Dict[str, str]:
    from src.agents.hires import tool_effects
    table: Dict[str, str] = {}
    for name in kit:
        for eff in tool_effects(name):
            table[eff] = "allow" if eff in ALLOWED_EFFECTS else "ask"
    return table


def _steps(asked: Any) -> List[str]:
    if isinstance(asked, str):
        asked = [s for s in re.split(r"\n+", asked)]
    steps = [_line(re.sub(r"^\s*\d+[.)]\s*", "", str(s)), STEP_MAX) for s in (asked or []) if str(s or "").strip()]
    steps = [s for s in steps if s][:STEPS_MAX]
    return steps or list(DEFAULT_STEPS)


def _fit_line(fit: Any) -> Optional[str]:
    """A step naming the saved agent that best fits the goal, for the lead to hand to."""
    if not isinstance(fit, dict) or not fit.get("id"):
        return None
    name = _line(fit.get("name") or fit["id"], NAME_MAX)
    return _line(f"{name} ({fit['id']}) is a saved agent that fits this goal; hand it the part it does "
                 f"well with the fleet tool rather than doing that part yourself.", STEP_MAX)


def fields(task_id: Any, *, title: Any, brief: Any = None, spec: Any = None, fit: Any = None) -> Dict[str, Any]:
    """The lead's fields, from Apollo's `spec` ({name, role, steps, tools}) and
    the goal. `fit` is the saved agent that best fits it (`lead.pick_lead`),
    named in the runbook as the teammate to hand to."""
    spec = spec if isinstance(spec, dict) else {}
    title = _line(title, 200) or "this goal"
    name = _line(spec.get("name"), NAME_MAX) or _line(f"Lead: {title}", NAME_MAX)
    role = _line(spec.get("role"), ROLE_MAX) or _line(f"Leads the goal “{title}” to done.", ROLE_MAX)
    kit = _kit(spec.get("tools"))
    return {"id": lead_id(task_id), "name": name, "tagline": role, "section": "personal-home",
            "icon": "bot", "inputs": [], "triggers": [{"on": "hand"}], "tools": kit,
            "delivers": [{"kind": "answer"}], "effects": _effects(kit),
            "budget": {"runs_per_day": 24, "max_steps": 30, "max_minutes": 20},
            "memory": "own", "runbook": _runbook(spec.get("steps"), fit)}


def _runbook(asked: Any, fit: Any) -> List[str]:
    """Apollo's steps (or the plain ones), the saved agent to hand to, and
    always the two that keep a yes the person's."""
    steps = _steps(asked)
    tail = [line for line in (_fit_line(fit), *KEEP_STEPS) if line and line not in steps]
    return steps[:STEPS_MAX - len(tail)] + tail


def _best_fit(owner: Optional[str], title: Any, brief: Any) -> Optional[Dict[str, Any]]:
    """The saved agent that best fits the goal, or None. A roster that can't
    be read leaves the lead to work alone; it never stops the goal."""
    try:
        from src.apollo.lead import pick_lead
        return pick_lead(owner, " ".join(x for x in (_line(title, 200), _line(brief, 2000)) if x))
    except Exception:
        return None


def write(owner: Optional[str], task_id: Any, *, title: Any, brief: Any = None, spec: Any = None,
          data_dir: Optional[str] = None):
    """Write the goal's lead and answer its manifest, or None when even the
    plain lead can't be written (the goal then starts led by Apollo)."""
    from src.agents import workshop
    from src.agents.manifest import ManifestRefused
    text = None
    m = None
    fit = _best_fit(owner, title, brief)
    for attempt in (spec, None):            # what Apollo asked for, then the plain lead
        try:
            text = workshop.render(fields(task_id, title=title, brief=brief, spec=attempt, fit=fit))
            m = workshop.check(text)
            break
        except ManifestRefused:
            text = m = None
    if m is None:
        return None
    path = _path(owner, m.id, data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    workshop._forget(path)
    return get(owner, m.id, data_dir=data_dir)


def get(owner: Optional[str], agent_id: Any, *, data_dir: Optional[str] = None):
    """This person's goal lead by id, or None."""
    if not is_goal_lead(agent_id):
        return None
    from src.agents.catalogue import _read
    from src.agents.manifest import Manifest
    got = _read(_path(owner, str(agent_id), data_dir), "own")
    return got if isinstance(got, Manifest) and got.id == agent_id else None

