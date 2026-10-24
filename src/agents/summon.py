# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-26` · Summon an agent into a chat.

The owner (2026-10-24): *"we need a way to attach agents in agent mode"* — the
composer's `^` menu gains **Agents** beside Workspace and Prompt, and the
person picks one. That turn (and every turn after it, until the chip is
cleared) is the agent's: the chat's model follows its runbook on what the
person asked, with **exactly its tools** and its **effects table** — the same
kit a hired run gets (`P24-05`, `P24-07`), so an agent is one thing whether it
runs on a schedule or is summoned (`Law 7`).

What differs from a hired run, and why:

  * **A person is here.** Nothing about the chat's own gate moves: the trust
    ladder, Auto, cards — all as they are. `D-2026-10-24-01`/`-02` are for runs
    nobody watches and are not applied here.
  * **No report, no notebook, no contract.** The person reads the answer. The
    runbook's *Report* / *Carry forward* sections are not asked for.
  * **The person's own hire wins.** If they have hired this agent, its effects
    table is theirs (what they tightened stays tight); otherwise the file's.
  * **Its skills** go in whole, as for a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional


class SummonRefused(ValueError):
    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


NO_SUCH_AGENT = "There is no agent called that in the hall. Pick another from Agents."
AGENT_MODE_ONLY = "Summoning an agent works in Agent mode: its tools are what it is."


@dataclass
class Summoned:
    agent_id: str
    name: str
    tools: List[str]
    ask_effects: frozenset
    never_effects: frozenset
    messages: List[dict] = field(default_factory=list)
    skill_lines: List[str] = field(default_factory=list)

    def policy(self, base):
        """`base` (the turn's own policy) narrowed to the agent's kit and table."""
        allowed = frozenset(self.tools)
        if getattr(base, "allowed_tools", None) is not None:
            allowed = allowed & base.allowed_tools
        return replace(base, allowed_tools=allowed, allowed_owner="this agent's",
                       ask_effects=self.ask_effects, never_effects=self.never_effects)

    def into(self, messages: List[dict]) -> List[dict]:
        """The agent's brief and skills, after the leading system messages."""
        out = list(messages)
        at = 0
        while at < len(out) and out[at].get("role") == "system":
            at += 1
        out[at:at] = self.messages
        return out


def brief(manifest, owner: Optional[str]) -> str:
    who = owner or "the person"
    return "\n".join([
        f"{who} summoned {manifest.name} into this chat: {manifest.tagline}",
        "",
        "For this conversation you are that agent. Do its job, on what the person asks, the way "
        "its runbook below does it — the same steps, the same care, the same limits. Use only "
        "the tools you are given; if the person asks for something the runbook or the tools "
        "cannot do, say so plainly instead of trying another way. Where the runbook speaks of "
        "what you were hired with — topics, folders, people, times — use what the person tells "
        "you in this chat, and ask them if it is missing. Answer the person directly; you do not "
        "need the runbook's Report or Carry forward sections here.",
        "",
        "# Runbook",
        "",
        manifest.runbook.strip(),
    ])


def summon(owner: Optional[str], agent_id: str, *, mode: str = "agent", db=None) -> Summoned:
    """What a summoned agent brings into a turn, or a sentence why not."""
    from src.agents import hires as H
    from src.agents.catalogue import get_agent
    from src.agents.runtime import _skill_messages
    from src.prompt_security import own_context_message
    from src.tool_capabilities import capabilities_for_tool

    if mode != "agent":
        raise SummonRefused(AGENT_MODE_ONLY)
    manifest = get_agent(owner, str(agent_id or "").strip())
    if manifest is None:
        raise SummonRefused(NO_SUCH_AGENT)
    grants: Dict[str, str] = {}
    if db is not None:
        from core.database import AgentHire
        try:
            hire = (db.query(AgentHire).filter(AgentHire.owner == owner, AgentHire.agent_id == manifest.id)
                    .order_by(AgentHire.created_at.desc()).first())
        except Exception:
            hire = None      # no hires table yet: the file's own table
        if hire is not None:
            grants = H.hire_grants(hire)
    effects = H.effective_effects(manifest, grants)
    never = frozenset(e for e, r in effects.items() if r == "never")
    ask = frozenset(e for e, r in effects.items() if r == "ask")
    tools = [t for t in manifest.tools
             if not ({e.value for e in capabilities_for_tool(t).effects} & never)]
    msgs = [own_context_message(f"the agent you summoned: {manifest.name}", brief(manifest, owner))]
    lines: List[str] = []
    for skill in manifest.skills:
        m, line = _skill_messages(owner, skill)
        msgs.extend(m)
        lines.append(line)
    return Summoned(agent_id=manifest.id, name=manifest.name, tools=tools, ask_effects=ask,
                    never_effects=never, messages=msgs, skill_lines=lines)
