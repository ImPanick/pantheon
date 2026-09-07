# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-run a receipt: same inputs, same configuration, new run (`P4-26`).

The only honest way to answer *"did that change help"*. Every prompt change,
model swap, skill edit and retrieval tweak in this codebase is currently
evaluated by vibes, and `P14-03`'s eval harness cannot exist until a single case
can be re-run — which is why this row sits in front of it.

THE PART THAT IS NOT OBVIOUS: A RECEIPT IS NOT ENOUGH ON ITS OWN.

`P4-25` deliberately keeps message content **out** of a receipt, because that is
what makes one portable (`P4-27`) — a receipt containing the conversation is one
nobody can hand over. So a receipt carries the *configuration*, and the *inputs*
live in `chat_messages` for the session it names.

A replay therefore joins the two, and that has a consequence worth stating
plainly rather than discovering later: **a receipt exported to somebody else
cannot be re-run by them.** They can read what was configured; they cannot
reproduce the conversation, because it was never in the file. That is the
correct trade — portability was the point — and it is why `rerun_plan` reports
what it is missing instead of quietly running a shorter conversation.

DRIFT IS THE PRODUCT, NOT AN ERROR.

*"Same configuration"* is a claim, and between two runs the model can be gone,
the endpoint renamed, a skill edited, a tool's schema changed. Substituting
silently would make every answer this row exists to give a lie. So the plan
returns what it CAN reproduce alongside a list of what it cannot, and a replay
records that list on the new run. `P4-28` then diffs two receipts knowing which
differences were chosen and which were inflicted.

A REPLAY DOES NOT TOUCH THE SESSION.

It is a diagnostic, not a conversation. Appending its output to history would
change the thing being measured and, worse, would put a machine-generated turn
in front of the person the next time they scrolled up.
"""
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _messages_before(session_id: str, before_ts) -> List[Dict[str, str]]:
    """The conversation as it stood when the run started.

    Ordered by `(timestamp, id)` rather than timestamp alone: two messages
    written in the same second are ordered arbitrarily otherwise, and a replay
    that reverses a user/assistant pair is not a replay of anything.
    """
    from core.database import SessionLocal, ChatMessage
    db = SessionLocal()
    try:
        q = db.query(ChatMessage).filter(ChatMessage.session_id == session_id)
        if before_ts is not None:
            q = q.filter(ChatMessage.timestamp < before_ts)
        rows = q.order_by(ChatMessage.timestamp.asc(), ChatMessage.id.asc()).all()
        return [{"role": r.role, "content": r.content or ""} for r in rows
                if r.role in ("user", "assistant", "system")]
    finally:
        db.close()


def _skill_drift(recorded: List[Dict[str, Any]]) -> List[str]:
    """Skills that are gone, or whose confidence has moved since the run."""
    drift: List[str] = []
    if not recorded:
        return drift
    try:
        # `SkillsManager`, not `SkillManager`, and it takes a data dir. The
        # first draft guessed both and the `except` below turned the resulting
        # ImportError into a drift line reading "skills could not be read" —
        # which is honest, and would have stayed there forever looking like a
        # property of the install rather than a typo.
        from services.memory.skills import SkillsManager
        from core.constants import DATA_DIR
        current = {s.get("name"): s for s in (SkillsManager(DATA_DIR).load_all() or [])}
    except Exception as e:
        return [f"skills could not be read ({type(e).__name__}: {e}); "
                f"cannot say whether {len(recorded)} injected skill(s) still match"]
    for entry in recorded:
        name = entry.get("name")
        now = current.get(name)
        if now is None:
            drift.append(f"skill {name!r} no longer exists")
            continue
        was, is_now = entry.get("confidence"), now.get("confidence")
        if was is not None and is_now is not None and abs(float(was) - float(is_now)) > 1e-9:
            drift.append(f"skill {name!r} confidence {was} → {is_now}")
    return drift


def rerun_plan(run_id: str) -> Dict[str, Any]:
    """What it would take to re-run this receipt, and what has moved since.

    Returns `{run_id, session_id, model, endpoint, sampling, messages,
    drift, runnable}`. `runnable` is False when something the replay genuinely
    needs is absent — and the reason is in `drift`, never guessed around.
    """
    from src.events import receipt

    out: Dict[str, Any] = {"run_id": run_id, "runnable": False, "drift": [],
                           "messages": [], "sampling": {}, "model": None,
                           "endpoint": None, "session_id": None}
    r = receipt(run_id)
    if r.get("error"):
        out["drift"].append(f"receipt unavailable: {r['error']}")
        return out
    if not r.get("rounds"):
        out["drift"].append("this run recorded no model round; there is nothing to re-run")
        return out

    first = r["rounds"][0]
    out["model"] = first.get("model")
    out["endpoint"] = first.get("endpoint")
    out["session_id"] = r.get("session_id")
    config = r.get("config") or {}
    out["sampling"] = config.get("sampling") or {}
    out["recorded_tools"] = config.get("tools") or []
    out["recorded_skills"] = config.get("skills") or []

    if not config:
        # Not fatal: the model and sampling can still be read off the round.
        # Fatal would be pretending otherwise.
        out["drift"].append("no run_config was recorded for this run; "
                            "tools and skills cannot be compared")

    if not out["session_id"]:
        out["drift"].append("the receipt names no session, so its inputs cannot be found "
                            "(a receipt exported from another machine carries no messages)")
        return out

    ts = first.get("ts")
    from datetime import datetime
    before = None
    if ts:
        try:
            before = datetime.fromisoformat(ts)
        except ValueError:
            before = None
    try:
        out["messages"] = _messages_before(out["session_id"], before)
    except Exception as e:
        out["drift"].append(f"inputs could not be read: {type(e).__name__}: {e}")
        return out

    if not out["messages"]:
        out["drift"].append("no messages survive for that session; the conversation was "
                            "deleted or the run predates it")
        return out
    if not out["model"]:
        out["drift"].append("the run recorded no model")
        return out

    out["drift"].extend(_skill_drift(out["recorded_skills"]))
    # Skill drift is reported, not disqualifying: re-running with today's skills
    # against yesterday's configuration is often exactly the comparison someone
    # wants, and refusing it would make the honest answer unavailable.
    out["runnable"] = True
    return out


def describe(plan: Dict[str, Any]) -> str:
    """One paragraph a person can read before spending a model call on it."""
    if not plan.get("runnable"):
        why = "; ".join(plan.get("drift") or ["unknown"])
        return f"Cannot re-run {plan.get('run_id')}: {why}"
    bits = [f"{len(plan['messages'])} message(s)", f"model {plan.get('model')}"]
    if plan.get("sampling"):
        bits.append(", ".join(f"{k}={v}" for k, v in sorted(plan["sampling"].items())))
    line = f"Re-run {plan['run_id']}: " + " · ".join(bits)
    if plan.get("drift"):
        line += f"\nChanged since the original run: " + "; ".join(plan["drift"])
    return line


async def replay(run_id: str, *, model: Optional[str] = None) -> Dict[str, Any]:
    """Execute the plan and return the new run's id beside the original's.

    `model` overrides the recorded one — which is the entire point for *"is the
    new model better"*, and is recorded as deliberate drift so `P4-28` can tell
    a choice from an accident.

    The new run gets its own `run_id`, and its `run_config` carries `replay_of`.
    That is what pairs them; without it a re-run is just another turn in the
    table and the comparison has to be reconstructed by timestamp, which is a
    guess.
    """
    from src import events as ev

    plan = rerun_plan(run_id)
    result: Dict[str, Any] = {"replay_of": run_id, "plan": plan,
                              "run_id": None, "output": None, "error": None}
    if not plan.get("runnable"):
        result["error"] = "; ".join(plan.get("drift") or ["not runnable"])
        return result

    chosen_model = model or plan["model"]
    deliberate = []
    if model and model != plan["model"]:
        deliberate.append(f"model {plan['model']} → {model} (requested)")

    # A fresh identity for the replay. `mark_turn_start` only acts when the
    # ContextVar is unset, so a replay running inside a request that already has
    # a run would otherwise inherit it and write its rows onto somebody else's
    # receipt.
    ev._turn_started.set(None)
    ev._run_id.set(None)
    ev.mark_turn_start()
    new_run = ev.current_run_id()
    result["run_id"] = new_run

    ev.record_run_config(
        sampling=plan.get("sampling") or {},
        session_id=plan.get("session_id"),
    )
    ev.record_event("replay", name=chosen_model, session_id=plan.get("session_id"),
                    outcome="ok",
                    detail={"replay_of": run_id,
                            "drift": plan.get("drift") or [],
                            "deliberate": deliberate,
                            "messages": len(plan["messages"])})

    try:
        from src.llm_core import llm_call_async
    except Exception as e:
        result["error"] = f"llm entry point unavailable: {type(e).__name__}: {e}"
        return result

    try:
        url, headers = _endpoint_for(chosen_model, plan.get('owner'))
        sampling = plan.get("sampling") or {}
        result["output"] = await llm_call_async(
            url, chosen_model, plan["messages"],
            temperature=sampling.get("temperature", 0.2),
            max_tokens=sampling.get("max_tokens", 1024),
            headers=headers,
            session_id=plan.get("session_id"),
        )
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        ev.record_event("replay", name=chosen_model, outcome="error",
                        detail={"replay_of": run_id, "error": str(e)[:400]})
    return result


def _endpoint_for(model: str, owner: Optional[str] = None):
    """(url, headers) for a model, through the resolver the app already uses.

    `Law 14` — endpoint resolution has an owner, and a replay that resolved its
    own would drift from the real path, which would make it useless for the one
    question it exists to answer.

    **The first draft called `resolve_endpoint_for_model`, which does not
    exist**, inside a `try/except` that would have swallowed the ImportError and
    silently fallen back to a hardcoded default host — a replay that quietly ran
    somewhere else and reported success. That is `B32`'s shape for the third
    time, and it is why `test_replay_calls_functions_that_exist` resolves every
    imported name in this module against its real module.
    """
    from src.endpoint_resolver import resolve_endpoint
    url, _resolved_model, headers = resolve_endpoint(
        "default", fallback_model=model, owner=owner)
    return url, (headers or {})
