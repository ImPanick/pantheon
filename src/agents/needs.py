# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1448` · An agent's `needs`, checked against the model it would run on.

A manifest declares `needs.min_context` (the smallest context window it was
written for) and `needs.native_tools` (`required` / `preferred` / `none`), and
`manifest.py` validates both. Until this module nothing read them: 162 shipped
agents named a window and 20 required native tool calls, and an agent hired on
an 8K fenced-only model ran with no word about either. A declared requirement
that changes nothing is a promise the hall makes and the runtime ignores.

So the two are compared with what Pantheon actually knows about the route:

  * **the window** — `model_context.get_context_length_known`, and only when it
    is *known* (endpoint-reported or in the known-models table). A fallback
    guess is not evidence the model is too small, so it says nothing.
  * **native tools** — `agent_loop.tool_schema_offer` for that endpoint: only
    `fenced` (the endpoint says it has no tool calls, or it is an Ollama
    surface) is a shortfall. `both` means nobody has said, and the schemas are
    sent, so it is not.

It **warns, it does not refuse**. A model a little under an agent's window may
still do the job, and the fit badge (`fit.py`) is the measurement; this is the
sentence that tells the person, before they summon and again when it runs, that
the agent asked for more than this model has.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def route_facts(endpoint_url: Optional[str], model: Optional[str],
                owner: Optional[str] = None) -> Dict[str, Any]:
    """What is known about a route: `{"model", "context" (int or None when not
    known), "tools" ("native" | "both" | "fenced" | None)}`. Never raises — a
    route that can't be looked at has no facts, and no facts warn nothing."""
    facts: Dict[str, Any] = {"model": model, "context": None, "tools": None}
    if not endpoint_url or not model:
        return facts
    try:
        from src.model_context import get_context_length_known
        ctx, known = get_context_length_known(endpoint_url, model)
        if known and isinstance(ctx, int) and ctx > 0:
            facts["context"] = ctx
    except Exception:
        pass  # an unreadable window is an unknown one, and unknown warns nothing
    try:
        from src.agent_loop import _agent_route_schema_offer
        facts["tools"] = _agent_route_schema_offer(endpoint_url, model, owner)
    except Exception:
        pass  # no endpoint row to read: the transport is unknown, which warns nothing
    return facts


def owner_route_facts(owner: Optional[str]) -> Dict[str, Any]:
    """The facts for the route `owner`'s hires run on — scheduled work's
    endpoint and model (the same route `fit.model_for` names)."""
    try:
        from src.task_endpoint import resolve_task_endpoint
        url, model, _h = resolve_task_endpoint(owner=owner or None)
    except Exception:
        url, model = None, None
    return route_facts(url, model, owner)


def _k(n: int) -> str:
    return f"{n // 1000}K" if n >= 1000 and n % 1000 == 0 else f"{n:,}"


def shortfall(needs: Dict[str, Any], facts: Dict[str, Any]) -> List[str]:
    """One sentence per need this route does not meet; empty when it meets them
    or when there isn't enough known to say."""
    out: List[str] = []
    model = facts.get("model") or "this model"
    want = int((needs or {}).get("min_context") or 0)
    have = facts.get("context")
    if want and isinstance(have, int) and have < want:
        out.append(f"It was written for a context window of at least {_k(want)} tokens; "
                   f"{model} has {_k(have)}, so long inputs may not fit.")
    if (needs or {}).get("native_tools") == "required" and facts.get("tools") == "fenced":
        out.append(f"It needs a model that calls tools natively; {model} is set to the "
                   "fenced form on its endpoint, so its tool calls may not land.")
    return out


def run_warnings(plan, endpoint_url: Optional[str], model: Optional[str]) -> List[str]:
    """The lines a hired agent's run records when the route it actually got
    falls short of its needs — `task_scheduler` writes each as a progress step.
    Empty for a run that is not an agent's, or a route that meets them."""
    if plan is None:
        return []
    try:
        from src.agents.catalogue import get_agent
        manifest = get_agent(plan.owner, plan.agent_id)
    except Exception:
        manifest = None
    if manifest is None:
        return []
    try:
        facts = route_facts(endpoint_url, model, plan.owner)
        return [f"{plan.name}: {line}" for line in shortfall(manifest.needs or {}, facts)]
    except Exception:
        # A warning that cannot be worked out must never stop the run it warns about.
        return []


def check(manifest, facts: Dict[str, Any]) -> Dict[str, Any]:
    """`{"model", "short": [sentences]}` for `manifest` on the route `facts`
    describes — what the hall shows beside the fit badge."""
    return {"model": facts.get("model"), "short": shortfall(getattr(manifest, "needs", {}) or {}, facts)}


# ── `B1623` · the programs an agent runs, checked before it is hired ────────
#
# `needs` said nothing about the programs a runbook runs, and the workstation
# installs none of exiftool, ffmpeg, a postgres or mysql server or an ssh
# client (`workstation/provision.sh`), so Photo Organiser, Video Clipper,
# Restore Drill and Vulnerability Scanner were hired, ran, and answered "NO
# EXIFTOOL" with the install line — after the hire, on a schedule, every time.
# `needs.programs` names them, and the hire asks first: in the person's
# workstation when their tools run there (`workstation_access.routes_tools`),
# otherwise on the machine Pantheon runs them on.
#
# Unlike the window and native tools above, a missing program **refuses** the
# hire: no model a little short of it can do the job, and the sentence says
# what to install and where. What cannot be asked — a workstation that is
# down — says nothing and refuses nothing: the run says it then, as before.

WORKSTATION = "your workstation"
HERE = "the machine Pantheon runs your tools on"


def programs_for(manifest, inputs: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The declared programs this hire needs: those with no `when`, and those
    whose `when` the hire's inputs match."""
    inputs = inputs or {}
    out = []
    for p in (getattr(manifest, "needs", {}) or {}).get("programs") or ():
        when = p.get("when") or {}
        if all(str(inputs.get(k)) == str(v) for k, v in when.items()):
            out.append(p)
    return out


async def missing_programs(manifest, owner: Optional[str],
                           inputs: Optional[Dict[str, Any]] = None):
    """`(missing, where)`: the declared programs where this person's tools
    run does not have, and the words for that place. `missing` is `None` when
    the place could not be asked."""
    import shlex
    import shutil
    wanted = programs_for(manifest, inputs)
    if not wanted:
        return [], ""
    names = sorted({p["name"] for p in wanted})
    from src.workstation_access import routes_tools
    if routes_tools(owner):
        try:
            from src.workstation_access import sync_config, workstation_for
            client, account = workstation_for(owner)
            await sync_config(client)
            r = await client.exec(account, "for p in " + " ".join(shlex.quote(n) for n in names)
                                  + '; do command -v "$p" >/dev/null 2>&1 || echo "$p"; done',
                                  timeout_s=20)
        except Exception:
            return None, WORKSTATION      # cannot be asked: the run says it, as before
        if r.get("exit_code") not in (0, None):
            return None, WORKSTATION
        absent = set(str(r.get("stdout") or "").split())
        where = WORKSTATION
    else:
        absent = {n for n in names if shutil.which(n) is None}
        where = HERE
    return [p for p in wanted if p["name"] in absent], where


def missing_sentence(manifest, missing: List[Dict[str, Any]], where: str) -> str:
    """The hire's refusal, naming what to install, where, and how."""
    names = [p["name"] for p in missing]
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    installs = list(dict.fromkeys(p["install"] for p in missing if p.get("install")))
    them = "it" if len(names) == 1 else "them"
    how = (f" Install {them} once — {'; '.join(installs)} — then hire it." if installs
           else f" Install {them} there, then hire it.")
    return f"{manifest.name} runs {listed}, which {where} does not have, so it cannot do its job yet.{how}"
