# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-20` · *New agent*, *Describe it*, *Customise* — a person's own agents.

An agent is one file (`P24-01`), so writing one is writing that file, checked
by the one rule (`manifest.lint`) before it is kept. Three doors, one store —
the person's own layer (`catalogue.own_root`, `P24-02`), where a file with a
shipped agent's id shadows it for that person only:

  * **New agent** — the hall's editor, starting from a short template;
  * **Describe it** — a sentence drafted into a whole file by the model, the
    way the Workbench drafts a workflow (`P22-19`, `workflow_assist.ask_for_json`:
    no tools, the answer is data). The draft is put in the editor and never
    kept until the person saves it — which is the person checking it;
  * **Customise** — a shipped agent's file copied into the editor; saved, it
    is the person's own and the shipped one stays as it is for everyone else.
    *Remove my copy* deletes the person's file and the shipped one is theirs
    again.

A saved file that changes `version` is offered to the person's hires as
*Update to* (`P24-04`); one that keeps it changes nothing a hire already runs —
its runs read the file at the moment they start.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple

from src.agents.catalogue import MANIFEST_NAME as AGENT_FILE  # one spelling of the file name
DESCRIBE_MAX_CHARS = 2000
DRAFT_MAX_TOKENS = 3000
NO_MODEL = "No model is set up to draft an agent. Write it by hand, or customise one from the hall."
DESCRIBE_EMPTY = "Say what the agent should do."
DESCRIBE_TOO_LONG = f"Say it in at most {DESCRIBE_MAX_CHARS:,} characters, then add the rest by hand."
NOT_YOURS = "That is not an agent of your own, so there is nothing of yours to remove."

TEMPLATE = """---
id: my-agent
name: My Agent
tagline: One sentence on the job it does, end to end.
section: personal-home
icon: bot
version: 1.0.0
wave: 1
inputs:
  - {key: topic, kind: text, label: What it works on}
triggers:
  - {on: daily, at: "08:00"}
tools: [web_search]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {brokered_network_read: allow}
budget: {runs_per_day: 2, max_steps: 15, max_minutes: 10}
memory: own
---
1. One numbered step per tool call, naming the tool and when to stop.
2. Spell out the answer's exact headings, so the check and the model aim at the same thing.
3. Say what to do when there is nothing to report, and what it must never do.
"""


# ── The file ────────────────────────────────────────────────────────────────

def check(text: str):
    """The one rule, for a person's own file. Answers the `Manifest`."""
    from src.agents.manifest import parse_manifest
    return parse_manifest(text or "", source="own")


def own_path(owner: Optional[str], agent_id: str, data_dir: Optional[str] = None) -> str:
    from src.agents.catalogue import own_root
    return os.path.join(own_root(owner, data_dir), agent_id, AGENT_FILE)


def save(owner: Optional[str], text: str, *, data_dir: Optional[str] = None):
    """Check, then keep. Answers `(manifest, shadows)` — `shadows` when it is a
    shipped agent's id, so the hall can say the person's copy is the one used."""
    m = check(text)
    path = own_path(owner, m.id, data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")
    os.replace(tmp, path)
    _forget(path)
    return m, shadows(m.id)


def source(manifest) -> str:
    with open(manifest.path, encoding="utf-8") as fh:
        return fh.read()


def remove(owner: Optional[str], agent_id: str, *, data_dir: Optional[str] = None) -> None:
    from src.agents.manifest import ManifestRefused
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,47}", agent_id or ""):
        raise ManifestRefused(NOT_YOURS)
    path = own_path(owner, agent_id, data_dir)
    if not os.path.isfile(path):
        raise ManifestRefused(NOT_YOURS)
    shutil.rmtree(os.path.dirname(path))
    _forget(path)


def shadows(agent_id: str) -> bool:
    """Is there a shipped agent with this id — so a person's file is a copy?"""
    from src.agents.catalogue import SHIPPED_ROOT
    return os.path.isfile(os.path.join(SHIPPED_ROOT, agent_id, AGENT_FILE))


def _forget(path: str) -> None:
    """The catalogue reads by mtime; a save in the same tick is read afresh."""
    from src.agents import catalogue as C
    with C._lock:
        C._cache.pop(path, None)


# ── Describe it ─────────────────────────────────────────────────────────────

def _q(s: Any) -> str:
    s = str(s)
    if not s or any(c in s for c in ',:{}[]#"\'') or s != s.strip():
        return '"' + s.replace('"', "'") + '"'
    return s


def _flow(d: Dict[str, Any]) -> str:
    parts = []
    for k, v in d.items():
        if isinstance(v, bool):
            parts.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            parts.append(f"{k}: {v}")
        elif isinstance(v, list):
            parts.append(f"{k}: [{', '.join(_q(x) for x in v)}]")
        else:
            parts.append(f"{k}: {_q(v)}")
    return "{" + ", ".join(parts) + "}"


def render(fields: Dict[str, Any]) -> str:
    """A whole `AGENT.md` from a drafted object. Every value is written by
    this function's own spelling, so a draft cannot smuggle a field nothing
    reads — the lint then decides whether it is a good file."""
    fields = dict(fields, version=fields.get("version") or "1.0.0")
    lines = ["---"]
    for key in ("id", "name", "tagline", "section", "icon", "version"):
        if fields.get(key) not in (None, ""):
            lines.append(f"{key}: {_q(fields[key])}")
    lines.append("wave: 1")
    inputs = [i for i in (fields.get("inputs") or []) if isinstance(i, dict)]
    lines.append("inputs:" if inputs else "inputs: []")
    lines += [f"  - {_flow({k: v for k, v in i.items() if k in ('key', 'kind', 'label', 'optional', 'default', 'choices')})}"
              for i in inputs]
    lines.append("triggers:")
    lines += [f"  - {_flow({k: v for k, v in t.items() if k in ('on', 'at', 'day', 'days', 'cron', 'event', 'every', 'label')})}"
              for t in (fields.get("triggers") or [{"on": "hand"}]) if isinstance(t, dict)]
    lines.append(f"tools: [{', '.join(str(t) for t in (fields.get('tools') or []))}]")
    lines.append("needs: {connectors: [], min_context: 16000, native_tools: preferred}")
    lines.append("delivers:")
    lines += [f"  - {_flow({k: v for k, v in d.items() if k in ('kind', 'title', 'must_contain', 'max')})}"
              for d in (fields.get("delivers") or [{"kind": "answer"}]) if isinstance(d, dict)]
    effects = fields.get("effects") if isinstance(fields.get("effects"), dict) else {}
    lines.append(f"effects: {_flow(effects)}" if effects else "effects: {}")
    b = fields.get("budget") if isinstance(fields.get("budget"), dict) else {}
    lines.append("budget: " + _flow({"runs_per_day": b.get("runs_per_day", 2), "max_steps": b.get("max_steps", 20),
                                     "max_minutes": b.get("max_minutes", 10)}))
    lines.append(f"memory: {fields.get('memory') if fields.get('memory') in ('own', 'shared', 'none') else 'own'}")
    lines.append("---")
    runbook = fields.get("runbook")
    if isinstance(runbook, list):
        runbook = "\n".join(f"{n}. {s}" for n, s in enumerate(runbook, start=1))
    lines.append(str(runbook or "").strip())
    return "\n".join(lines) + "\n"


def palette() -> Dict[str, Any]:
    """What a draft may use: Pantheon's own tools with their effects, the
    sections, input kinds, triggers and events — Pantheon's facts only."""
    from src.agents.manifest import DELIVER_KINDS, INPUT_KINDS, SECTIONS, TRIGGER_KINDS
    from src.tool_capabilities import capabilities_for_tool
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS
    from src.tool_policy import selectable_tool_names
    from src.event_bus import EVENT_NAMES
    tools = []
    for name in sorted(selectable_tool_names()):
        caps = capabilities_for_tool(name)
        tools.append({"name": name, "effects": sorted(e.value for e in caps.effects),
                      "does": (BUILTIN_TOOL_DESCRIPTIONS.get(name) or "")[:160]})
    return {"tools": tools, "sections": [s for s, _l, _f in SECTIONS], "input_kinds": list(INPUT_KINDS),
            "triggers": list(TRIGGER_KINDS), "events": list(EVENT_NAMES), "delivers": list(DELIVER_KINDS)}


_SYSTEM = """You write agents for Pantheon, a self-hosted assistant. An agent is a job done end to end
on a schedule or a trigger by a small local model following a runbook. A person describes the job;
you answer with ONE JSON object and nothing else.

{"id": "lower-case words joined by dashes", "name": "Title Case, at most 48 characters",
 "tagline": "one sentence, at most 140 characters, on the whole job",
 "section": "one section id from the palette",
 "inputs": [{"key": "short_name", "kind": "an input kind", "label": "what the person is asked"}],
 "triggers": [{"on": "daily", "at": "HH:MM"} | {"on": "weekly", "day": "mon", "at": "HH:MM"} |
              {"on": "cron", "cron": "m h dom mon dow"} | {"on": "event", "event": "an event", "every": 1} |
              {"on": "webhook"} | {"on": "hand"}],
 "tools": ["tool names from the palette, the fewest the job needs"],
 "delivers": [{"kind": "answer", "must_contain": ["a heading the answer must have"]}],
 "effects": {"each effect of each tool you chose": "allow" | "ask" | "never"},
 "budget": {"runs_per_day": 1-96, "max_steps": 1-60, "max_minutes": 1-60},
 "memory": "own" | "none",
 "runbook": ["step 1", "step 2", "..."]}

Rules:
- Use only tools the palette lists, by their exact names. Name every effect of every tool you
  chose in "effects". Anything that sends, posts, pays, deletes or changes settings is "ask".
- The runbook is for a small model: one numbered step per tool call, naming the tool and when to
  stop; the answer's exact headings; what to do when there is nothing to report; what it must
  never do. Refer to inputs as "the <label> you were hired with". 4 to 12 steps.
- Never invent a tool, an event or a section."""


async def draft(owner: Optional[str], description: str) -> Dict[str, Any]:
    """`{text, sentence, ok}`: a whole file drafted from a sentence, checked by
    the lint. `ok` False with the lint's sentence when the second answer still
    does not pass — the person fixes it in the editor; nothing is kept."""
    from src.agents.manifest import ManifestRefused
    from src.workflow_assist import NoModelSetUp, ask_for_json

    text = str(description or "").strip()
    if not text:
        return {"ok": False, "text": "", "sentence": DESCRIBE_EMPTY}
    if len(text) > DESCRIBE_MAX_CHARS:
        return {"ok": False, "text": "", "sentence": DESCRIBE_TOO_LONG}
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": "The palette:\n" + json.dumps(palette()) +
                 "\n\nThe job, in the person's words:\n" + text}]
    last = ""
    for _round in range(2):
        try:
            obj, problem = await ask_for_json(owner, messages, max_tokens=DRAFT_MAX_TOKENS)
        except NoModelSetUp:
            return {"ok": False, "text": "", "sentence": NO_MODEL}
        if obj is None:
            return {"ok": False, "text": last, "sentence": getattr(problem, "sentence", str(problem))}
        last = render(obj)
        try:
            check(last)
            return {"ok": True, "text": last, "sentence": "Drafted. Read every field, then save it."}
        except ManifestRefused as refused:
            messages = messages + [{"role": "assistant", "content": json.dumps(obj)},
                                   {"role": "user", "content": f"That file does not pass its check: "
                                                               f"{refused.sentence} Answer the whole object again."}]
            sentence = refused.sentence
    return {"ok": False, "text": last, "sentence": f"The draft does not pass its check yet: {sentence} "
                                                   f"Fix it below, then save."}
