# SPDX-License-Identifier: AGPL-3.0-or-later
"""What Apollo is told at the top of every turn in its own chat.

The behaviour lives in Pantheon, and this frame is how the model hears it:
who it is, how it speaks, the person's stated rules, what is open right now,
and what it may and may not do with what it only inferred. It is built fresh
per turn from the server's own records, so it is the same for every model.

The character (`CHARACTER`) is short on purpose: a small local model reads all
of it. It holds the one rule no dial turns off: Apollo pushes back.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.apollo import APOLLO_NAME

CHARACTER = (
    "You are {name}, {who}'s partner in Pantheon: a colleague who drives the work and reports "
    "back, not a chatbot waiting for instructions.\n"
    "- Lead with the point. Short, plain sentences. No filler, no flattery, no \"great question\".\n"
    "- Push back. When a plan has a hole or {who} is wrong, say so with the evidence. Agreeing "
    "to be pleasant is a failure.\n"
    "- Real work leaves the chat: anything longer than a quick answer becomes a task with the "
    "`apollo` tool (action create_task), led by an agent from the roster, and you say one line "
    "about it. Never claim work is done that a task hasn't reported done.\n"
    "- When you need {who}'s decision, ask one question. When a task is stuck on them, mark it "
    "with action ask.\n"
    "- Remember what {who} tells you about how they work with action remember (basis stated). "
    "A pattern you only noticed is basis inferred, with the evidence, and you may voice it as a "
    "question; it never changes what you do until they confirm it.\n"
    "- Keep your notebook: action note for something owed or promised (open_loop) and for a "
    "thing already talked through (talked_through), so you never bring settled things back as news.\n"
    "- Outward acts (sending, deleting, paying, posting) wait for {who}'s yes on Pantheon's "
    "approval card. Make the call; never ask permission in words."
)


def character(owner: Optional[str], name: Optional[str] = None) -> str:
    return CHARACTER.format(name=name or APOLLO_NAME, who=owner or "the person")


def _task_line(t) -> str:
    bits = [f"[{t.state}] {t.title}"]
    if t.state == "needs_you" and t.question:
        bits.append(f"asks: {t.question}")
    elif t.next_step:
        bits.append(f"next: {t.next_step}")
    if t.lead_agent:
        bits.append(f"lead: {t.lead_agent}")
    return " — ".join(bits) + f" (id {t.id})"


def build(db, owner: str, *, name: Optional[str] = None, knows=None, notebook=None,
          tasks=None) -> str:
    """The frame for one turn: character, rules, open tasks, notebook, hunches."""
    if knows is None:
        from src.apollo import knows
    if notebook is None:
        from src.apollo import notebook
    if tasks is None:
        from src.apollo import tasks
    parts: List[str] = [character(owner, name)]
    try:
        rules = knows.stated_rules(owner)
    except Exception:
        rules = []
    if rules:
        parts.append("Rules and preferences they stated (follow these):\n"
                     + "\n".join(f"- {r}" for r in rules))
    open_tasks = tasks.list_for(db, owner, include_done=False, limit=12)
    if open_tasks:
        parts.append("Open tasks:\n" + "\n".join(f"- {_task_line(t)}" for t in open_tasks))
    else:
        parts.append("Open tasks: none.")
    loops = notebook.list_for(db, owner, kind="open_loop", state="open", limit=10)
    if loops:
        parts.append("Open loops (owed or promised):\n" + "\n".join(f"- {n.text}" for n in loops))
    talked = notebook.list_for(db, owner, kind="talked_through", limit=10)
    if talked:
        parts.append("Already talked through (not news):\n"
                     + "\n".join(f"- {n.text} [{n.state}]" for n in talked))
    try:
        hunches = knows.open_hunches(owner, limit=3)
    except Exception:
        hunches = []
    if hunches:
        parts.append("Hunches not yet confirmed (ask, don't act):\n"
                     + "\n".join(f"- {h['text']} (because: {h['evidence']}; id {h['id']})"
                                 for h in hunches))
    return "\n\n".join(parts)


def apollo_session_for(db, owner: Optional[str], session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """`{name}` when `session_id` is `owner`'s Apollo chat, else `None`."""
    if not owner or not session_id:
        return None
    from core.database import CrewMember
    crew = (db.query(CrewMember)
            .filter(CrewMember.owner == owner,
                    CrewMember.is_default_assistant == True,  # noqa: E712
                    CrewMember.session_id == session_id).first())
    if crew is None:
        return None
    return {"name": crew.name or APOLLO_NAME, "crew_id": crew.id}


def frame_messages(db, owner: Optional[str], session_id: Optional[str]) -> List[Dict[str, Any]]:
    """The context message for a turn in `owner`'s Apollo chat, or `[]`."""
    found = apollo_session_for(db, owner, session_id)
    if found is None:
        return []
    from src.prompt_security import own_context_message
    return [own_context_message("Apollo, your partner role", build(db, owner, name=found["name"]))]


def into(messages: List[Dict[str, Any]], extra: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """`extra` after the leading system messages, as a summoned agent's brief goes."""
    if not extra:
        return messages
    out = list(messages)
    at = 0
    while at < len(out) and out[at].get("role") == "system":
        at += 1
    out[at:at] = extra
    return out
