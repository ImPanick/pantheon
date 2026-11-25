# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one place a run consults the reasoning cache.

`around` wraps an agent loop's stream (`stream_agent_loop`, not yet started).
The chat route wraps a chat or Apollo turn; the scheduler wraps a scheduled
run or an Apollo goal run. What happens depends on the person's mode
(`roles.mode_for`) and on the closest entry in the run's scope:

  * **off**, no request, or no embedding client: the stream goes by untouched.
  * **a live entry and the person chose Live**: the entry answers. The loop is
    closed without ever starting, the reply goes out as the loop's own text
    would, preceded by one `reasoning_cache` event that says it came from the
    cache and what each step did. Any miss or error, and the loop runs as
    though the cache were not there.
  * **any other match** (Shadow, or a Live person whose entry is still in
    Shadow): the loop answers, and afterwards, as background work, the entry
    answers the same request and the two replies are judged. Agreement counts
    toward Live; disagreement sets the count back, and twice retires it.
  * **no match, in a run built to repeat** (a scheduled run or an Apollo goal
    run, `build_from=True`): once the loop finished cleanly, the builder tries
    to make an entry of it, in the background.

Nothing here changes a byte of a stream it does not answer.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple

from src.reasoning_cache import builder, invoke, roles, store
from src.reasoning_cache.sandbox import CodeRefused

logger = logging.getLogger(__name__)

EVENT = "reasoning_cache"
#: Events after which a run is not one to learn from or to judge against.
UNCLEAN_TYPES = frozenset({"agent_terminal", "ask_user", "tool_blocked",
                           "rounds_exhausted", "budget_exceeded",
                           "loop_breaker_triggered", "intent_nudge_exhausted"})

_background: Set[asyncio.Task] = set()


def latest_request(messages: List[Dict[str, Any]]) -> str:
    """The newest user message's words (text parts only)."""
    for msg in reversed(messages or []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "\n".join(str(p.get("text") or "") for p in content
                             if isinstance(p, dict) and p.get("type") == "text").strip()
        return ""
    return ""


def _chars(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for msg in messages or []:
        content = msg.get("content")
        total += len(content) if isinstance(content, str) else len(json.dumps(content or ""))
    return total


def _sse(payload: Any) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _later(coro) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


def _db_call(fn, *args, **kwargs):
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        return fn(db, *args, **kwargs)
    finally:
        db.close()


def chat_scope(db, owner: str, session_id: Optional[str]) -> Tuple[str, bool]:
    """`(scope, local_only)` for a chat turn: an Apollo chat or one of its
    tasks' chats takes its space's scope, anything else the person's
    ordinary-chat scope."""
    from core.database import ApolloTask
    from src.apollo import spaces
    is_apollo, space_id = spaces.space_of_session(db, owner, session_id)
    if not is_apollo and session_id:
        task = (db.query(ApolloTask)
                .filter(ApolloTask.owner == owner, ApolloTask.session_id == session_id)
                .first())
        if task is not None:
            is_apollo, space_id = True, task.space_id
    local = bool(spaces.local_only_for_session(db, owner, session_id))
    return store.scope_for(space_id=space_id, apollo=is_apollo), local

def run_scope(db, owner: str, task_id: Optional[str],
              agent: Optional[Dict[str, Any]]) -> Tuple[str, bool]:
    """`(scope, local_only)` for a scheduled run: an Apollo goal run takes its
    goal's space, a hired agent's run its agent, anything else its task."""
    agent = agent or {}
    if agent.get("hire_id"):
        from src.apollo import spaces
        from src.apollo.runs import apollo_task_for_hire
        goal = apollo_task_for_hire(db, agent["hire_id"])
        if goal is not None:
            local = bool(spaces.local_only_for_space(db, owner, goal.space_id))
            return store.scope_for(space_id=goal.space_id, apollo=True), local
    return store.scope_for(agent_id=agent.get("agent_id"), task_id=task_id), False

async def _shadow(owner: str, entry: Dict[str, Any], request: str, model_reply: str,
                  session_id: Optional[str], disabled_tools: Optional[Set[str]],
                  untrusted_seen: bool) -> None:
    """Run the entry beside a reply the model already gave, and record the verdict."""
    try:
        from src.interactive_gate import wait_for_interactive_quiet
        await wait_for_interactive_quiet("reasoning cache shadow check")
        try:
            result = await invoke.answer(entry, request, owner, workload="background",
                                         session_id=session_id, disabled_tools=disabled_tools,
                                         untrusted_seen=untrusted_seen)
            agreed = await builder.judges_agree(owner, request, model_reply, result.reply)
        except invoke.Miss:
            return   # the request did not carry the entry's values: no verdict
        except CodeRefused as exc:
            await asyncio.to_thread(_db_call, store.retire, owner, entry["id"],
                                    f"Its code no longer passes the sandbox: {exc}")
            return
        except Exception:
            agreed = False
        await asyncio.to_thread(_db_call, store.record_shadow, owner, entry["id"], agreed,
                                roles.agreements_needed())
    except Exception as exc:
        logger.info("reasoning cache: shadow check skipped (%s)", exc)


async def around(run: AsyncGenerator[str, None], *, owner: Optional[str], scope: str,
                 messages: List[Dict[str, Any]], workload: str = "foreground",
                 session_id: Optional[str] = None,
                 disabled_tools: Optional[Set[str]] = None,
                 untrusted_seen: bool = False,
                 build_from: bool = False,
                 local_only: bool = False,
                 consult: bool = True,
                 request: Optional[str] = None) -> AsyncGenerator[str, None]:
    """Yield the run's stream, or the cache's answer in its place (see the
    module's docstring). `consult=False` is the caller saying this turn is not
    one the cache may answer or learn from (an approval being replayed, a plan,
    an open document, an attachment, Nobody); `local_only` is a run inside a
    space pinned to local models. `request` is what the run was asked, when
    that is more than its newest user message (a scheduled run's trigger)."""
    mode = roles.mode_for(owner) if consult else "off"
    if mode != "off" and local_only:
        try:
            if not await asyncio.to_thread(roles.all_local, owner):
                mode = "off"
        except Exception:
            mode = "off"
    if mode != "off" and request is None:
        request = latest_request(messages)
    request = (request or "").strip()
    if mode == "off" or not request or not owner:
        async for chunk in run:
            yield chunk
        return

    match = None
    try:
        vector = await asyncio.to_thread(roles.embed, request)
        if vector:
            match = await asyncio.to_thread(_db_call, store.best_match, owner, scope,
                                            vector, roles.match_threshold())
    except Exception as exc:
        logger.info("reasoning cache: lookup skipped (%s)", exc)
    entry = match[0] if match else None

    if entry and entry["status"] == store.LIVE and mode == "live":
        try:
            result = await invoke.answer(entry, request, owner, workload=workload,
                                         session_id=session_id, disabled_tools=disabled_tools,
                                         untrusted_seen=untrusted_seen)
        except CodeRefused as exc:
            await asyncio.to_thread(_db_call, store.retire, owner, entry["id"],
                                    f"Its code no longer passes the sandbox: {exc}")
            result = None
        except Exception as exc:
            logger.info("reasoning cache: entry %s missed (%s)", entry["id"], exc)
            result = None
        if result is not None:
            await run.aclose()
            yield _sse({"type": EVENT, "state": "served", "entry_id": entry["id"],
                        "applies_when": entry.get("applies_when") or "",
                        "narration": result.narration,
                        "tokens_saved_estimate": int(entry.get("source_tokens") or 0)})
            yield _sse({"delta": result.reply})
            yield "data: [DONE]\n\n"
            await asyncio.to_thread(_db_call, store.record_served, owner, entry["id"],
                                    int(entry.get("source_tokens") or 0))
            return

    reply: List[str] = []
    steps: List[builder.ToolStep] = []
    clean, done, used_tokens = True, False, 0
    async for chunk in run:
        yield chunk
        if chunk.startswith("data: [DONE]"):
            done = True
            continue
        if not chunk.startswith("data: "):
            continue
        try:
            data = json.loads(chunk[6:])
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        kind = data.get("type")
        if "delta" in data and not data.get("thinking") and not data.get("link"):
            reply.append(str(data["delta"]))
        elif "error" in data and kind is None:
            clean = False
        elif kind in UNCLEAN_TYPES:
            clean = False
        elif kind == "tool_start":
            steps.append(builder.ToolStep(tool=str(data.get("tool") or ""),
                                          command=str(data.get("full_command") or data.get("command") or ""),
                                          effects=[str(e) for e in data.get("effects") or []]))
        elif kind == "tool_output":
            for step in reversed(steps):
                if step.tool == data.get("tool") and not step.output:
                    step.output = str(data.get("output") or "")
                    break
        elif kind == "metrics":
            usage = data.get("data") or {}
            used_tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)

    answer = "".join(reply).strip()
    if not (done and clean and answer):
        return
    if entry is not None:
        _later(_shadow(owner, entry, request, answer, session_id, disabled_tools,
                       untrusted_seen))
    elif build_from:
        transcript = builder.Transcript(
            request=request, answer=answer, tools=steps, finished_cleanly=True,
            source_tokens=used_tokens or (_chars(messages) + len(answer)) // 4)
        _later(builder.build(owner, scope, transcript))
