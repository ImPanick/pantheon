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
    "- When {who}'s reactions show your voice doesn't suit them (they keep cutting replies short, "
    "or ask for more warmth), move one dial one step with action nudge_voice and the reason, and "
    "say so in a line; they can undo it.\n"
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
          tasks=None, space_id: Optional[str] = None) -> str:
    """The frame for one turn in a space (None is the top layer): character,
    where it is, rules, open tasks and loops of the space and its parents,
    what its grants let it read (each read logged), a count of what is under
    it, and hunches. Nothing from a space it may not read is ever in it."""
    if knows is None:
        from src.apollo import knows
    if notebook is None:
        from src.apollo import notebook
    if tasks is None:
        from src.apollo import tasks
    from src.apollo import spaces as S
    sc = S.scope(db, owner, space_id, "memory")
    own = [i for i in sc.reads if sc.via(i) is None]
    parts: List[str] = [character(owner, name)]
    try:
        from src.apollo import voice
        parts.append("Voice:\n" + "\n".join(f"- {v}" for v in voice.lines(db, owner)))
    except Exception:
        from src.apollo.voice import PUSHBACK
        parts.append(f"Voice:\n- {PUSHBACK}")
    if space_id is not None:
        row = S.get(db, owner, space_id)
        path = S.to_dict(row, S._all(db, owner))["path"]
        where = f"You are in the space “{path}”. What you make here (tasks, notes, lines) stays in it."
        if sc.edge:
            where += (" It is airgapped: nothing outside it reaches in and nothing in it goes out, "
                      "and you can't ask or hand work across its edge.")
        if sc.local_only:
            where += " It keeps to local models."
        parts.append(where)
    try:
        rules = knows.stated_rules(owner, where=sc)
    except Exception:
        rules = []
    if rules:
        parts.append("Rules and preferences they stated (follow these):\n"
                     + "\n".join(f"- {r}" for r in rules))

    def label(t):
        there = (t.space_id or None)
        return _task_line(t) + ("" if there == space_id else f" (in {sc.names.get(there, 'Apollo')})")
    open_tasks = tasks.list_for(db, owner, include_done=False, limit=12, space=own)
    if open_tasks:
        parts.append("Open tasks:\n" + "\n".join(f"- {label(t)}" for t in open_tasks))
    else:
        parts.append("Open tasks: none.")
    loops = notebook.list_for(db, owner, kind="open_loop", state="open", limit=10, space=own)
    if loops:
        parts.append("Open loops (owed or promised):\n" + "\n".join(f"- {n.text}" for n in loops))
    talked = notebook.list_for(db, owner, kind="talked_through", limit=10, space=own)
    if talked:
        parts.append("Already talked through (not news):\n"
                     + "\n".join(f"- {n.text} [{n.state}]" for n in talked))
    parts.extend(_granted(db, owner, sc, knows, tasks, S))
    kids = S.children(db, owner, space_id)
    if kids:
        rows = []
        for k in kids:
            if k["sealed"]:
                if k["needs_you"]:
                    rows.append(f"- “{k['name']}” (airgapped): something there needs them.")
            else:
                rows.append(f"- “{k['name']}”: {k['open']} open, {k['needs_you']} need them.")
        if rows:
            parts.append("Spaces under this one (counts only; open one to see inside):\n" + "\n".join(rows))
    try:
        hunches = knows.open_hunches(owner, limit=3, where=sc)
    except Exception:
        hunches = []
    if hunches:
        parts.append("Hunches not yet confirmed (ask, don't act):\n"
                     + "\n".join(f"- {h['text']} (because: {h['evidence']}; id {h['id']})"
                                  for h in hunches))
    return "\n\n".join(parts)


def _granted(db, owner: str, sc, knows, tasks, S) -> List[str]:
    """What this space reads through its grants, read only, each use logged."""
    out: List[str] = []
    if sc.grants:
        try:
            lines = [x for x in knows.what_apollo_knows(owner, sc) if x.get("via_grant")]
        except Exception:
            lines = []
        by: Dict[str, List[str]] = {}
        for x in lines:
            if x["basis"] == "stated":
                by.setdefault(x["space_id"], []).append(x["text"])
        for g, src in sc.grants:
            got = by.get(src, [])[:8]
            if got:
                S.log_use(db, owner, g, f"Apollo read {len(got)} line(s) for a turn")
                out.append(f"What they told you in “{sc.names.get(src)}” (read only; inform, never change):\n"
                           + "\n".join(f"- {t}" for t in got))
    osc = S.scope(db, owner, sc.space_id, "outcomes")
    for g, src in osc.grants:
        done = [t for t in tasks.list_for(db, owner, state="done", limit=5, space=src) if t.outcome]
        if done:
            S.log_use(db, owner, g, f"Apollo read {len(done)} outcome(s) for a turn")
            out.append(f"What “{osc.names.get(src)}” finished (read only):\n"
                       + "\n".join(f"- {t.title}: {t.outcome}" for t in done))
    return out


def apollo_session_for(db, owner: Optional[str], session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """`{name, crew_id, space_id}` when `session_id` is one of `owner`'s Apollo
    chats (its main chat, or a space's), else `None`."""
    if not owner or not session_id:
        return None
    from core.database import CrewMember
    from src.apollo import spaces as S
    ok, space_id = S.space_of_session(db, owner, session_id)
    if not ok:
        return None
    crew = (db.query(CrewMember)
            .filter(CrewMember.owner == owner,
                    CrewMember.is_default_assistant == True).first())  # noqa: E712
    return {"name": (crew.name if crew else None) or APOLLO_NAME,
            "crew_id": crew.id if crew else None, "space_id": space_id}


def frame_messages(db, owner: Optional[str], session_id: Optional[str]) -> List[Dict[str, Any]]:
    """The context message for a turn in one of `owner`'s Apollo chats, or `[]`."""
    found = apollo_session_for(db, owner, session_id)
    if found is None:
        return []
    from src.prompt_security import own_context_message
    text = build(db, owner, name=found["name"], space_id=found["space_id"])
    db.commit()     # the grant uses `build` logged
    return [own_context_message("Apollo, your partner role", text)]


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
