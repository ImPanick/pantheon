# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turning one finished run into an entry: the paper's build, for any model.

One conversation with the builder model, append-only so a local server reuses
its prefix from step to step (the paper's builder read about 290k tokens per
entry, nearly all of them cache reads):

  1. isolate the input and the output;
  2. decompose the work into steps;
  3. recognise the parameters: the values that change from one request of
     this kind to the next;
  4. plan the functions;
  5. implement them, with two made-up requests of the same kind and the
     parameter values each states.

Then the checks, any failure of which goes back to step 5 with the reason, at
most `MAX_ATTEMPTS` times:

  * the code passes the sandbox's allowlist;
  * the target model, reading the original request, pulls out the same
    parameter values the builder named (an extraction round trip);
  * run on them, the code's reply is judged the same answer as the model's,
    by the builder and the judge both;
  * the target model pulls each made-up request's values out correctly.

Only a run that finished cleanly, used read-only tools and left a reply is
built from (`worth_building`). Building waits for Pantheon to be quiet and
calls its models as background work, which a person's turn always overtakes.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from src.reasoning_cache import roles, store
from src.reasoning_cache.invoke import (READ_EFFECT_NAMES, Miss, answer as run_answer,
                                        extract_params, first_json_object)
from src.reasoning_cache.sandbox import FINAL_REPLY_KEY, CodeRefused, EntryFailed, check_code

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_TOOL_OUTPUT_CHARS = 3000
MAX_ANSWER_CHARS = 12000
MIN_ANSWER_CHARS = 20

_build_lock = asyncio.Lock()


@dataclass
class ToolStep:
    tool: str
    command: str
    effects: List[str]
    output: str = ""


@dataclass
class Transcript:
    """What a finished run did, as the gate saw it go by."""
    request: str
    answer: str
    tools: List[ToolStep] = field(default_factory=list)
    finished_cleanly: bool = False
    source_tokens: int = 0


def worth_building(t: Transcript) -> Optional[str]:
    """Why a run is not built from, or None when it is."""
    if not t.finished_cleanly:
        return "the run did not finish cleanly"
    if len((t.answer or "").strip()) < MIN_ANSWER_CHARS:
        return "the run left no reply worth keeping"
    if not (t.request or "").strip():
        return "there is no request"
    for step in t.tools:
        if not step.effects or not set(step.effects) <= READ_EFFECT_NAMES:
            return f"{step.tool} does more than read"
    return None


BUILDER_SYSTEM = f"""You turn one finished piece of work into small Python functions, so that the next request of the same kind, with different values, can be answered by running them instead of asking a large model.

The functions run in a sandbox with plain Python only: no imports, no classes, no files, no names or attributes that start with an underscore, no str.format (use f-strings), no print. These primitives are available as plain functions:
- lm(prompt) -> str: a small language model, for judgement or wording a few sentences. Keep prompts short and self-contained.
- extract(text, what) -> str: a small model returns only `what` from `text`.
- convert(value, kind) -> value: kind is "int", "float", "bool", "list", "dict" or "str".
- invoke_tool(name, content) -> str: one of the tools the original work used, with the same kind of content. Read-only tools only.
- narrate(text): one line saying what a step did, for the person to read.

The root function is named solve, takes one dict of parameters keyed by their natural-language names, and returns a dict whose key "{FINAL_REPLY_KEY}" holds the reply to the person as a string. Other keys may hold intermediate values. Do plain arithmetic, sorting, counting and formatting in Python, not with lm. Reproduce the shape and substance of the original reply."""

STEPS = (
    "Step 1, isolate. In a few lines: what did the person give (the input), and what did they get back (the output)?",
    "Step 2, decompose. List the steps that took the input to the output, one line each, and mark each step as code, lm, extract or invoke_tool.",
    'Step 3, parameters. Which values in the request would change from one request of this kind to the next? Answer with a JSON list only: [{"name": "a short natural-language name", "description": "what it is", "example": "its value in this request, copied exactly"}]. Use an empty list if nothing would change.',
    "Step 4, plan. The functions you will write, one line each, root (solve) last.",
    'Step 5, implement. Answer with one JSON object only: {"applies_when": "one sentence describing every request this answers", "code": "the Python source", "variants": [{"request": "a made-up request of the same kind with different values", "parameters": {"name": "value"}}, {"request": "...", "parameters": {}}]}',
)


def transcript_message(t: Transcript) -> str:
    parts = ["The request:\n" + t.request.strip()]
    for i, step in enumerate(t.tools, 1):
        parts.append(f"Tool call {i}: {step.tool}\nContent: {step.command[:600]}\n"
                     f"Output:\n{(step.output or '')[:MAX_TOOL_OUTPUT_CHARS]}")
    parts.append("The reply the person got:\n" + t.answer.strip()[:MAX_ANSWER_CHARS])
    return "\n\n".join(parts)


async def judges_agree(owner: Optional[str], request: str, expected: str, got: str) -> bool:
    """The builder and the judge both say the two replies give the same answer."""
    prompt = (
        "Two replies to the same request follow. Do they give the same substantive "
        "answer: the same facts, numbers and conclusions? Wording, order and length "
        "may differ. Answer AGREE or DISAGREE on the first line, then one sentence.\n\n"
        f"Request:\n{request.strip()[:4000]}\n\nReply A:\n{expected.strip()[:MAX_ANSWER_CHARS]}"
        f"\n\nReply B:\n{got.strip()[:MAX_ANSWER_CHARS]}")
    for role in ("builder", "judge"):
        verdict = await roles.call(role, owner, [{"role": "user", "content": prompt}],
                                   max_tokens=120, workload="background")
        first = (verdict or "").strip().split()
        if not first or first[0].strip("*:.,").upper() != "AGREE":
            return False
    return True


def _clean_parameters(value: Any) -> List[Dict[str, str]]:
    if isinstance(value, dict):
        value = value.get("parameters")
    out, seen = [], set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())[:80]
        if not name or name in seen or name.startswith("_"):
            continue
        seen.add(name)
        out.append({"name": name, "description": str(item.get("description") or "")[:300],
                    "example": str(item.get("example") if item.get("example") is not None else "")})
    return out


def _json_list(text: str) -> Any:
    start, end = (text or "").find("["), (text or "").rfind("]")
    if start == -1 or end <= start:
        return first_json_object(text) or []
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return first_json_object(text) or []


async def _say(owner: Optional[str], convo: List[Dict[str, str]], ask: str,
               max_tokens: int = 1500) -> str:
    convo.append({"role": "user", "content": ask})
    reply = await roles.call("builder", owner, convo, max_tokens=max_tokens,
                             workload="background")
    convo.append({"role": "assistant", "content": reply})
    return reply


async def _check(owner: Optional[str], t: Transcript, parameters: List[Dict[str, str]],
                 code: str, variants: Sequence[Any]) -> Optional[str]:
    """Why this implementation fails, or None when it passes every check."""
    try:
        check_code(code, "solve")
    except CodeRefused as exc:
        return f"The sandbox refused the code: {exc}."
    names = [p["name"] for p in parameters]
    try:
        got = await extract_params(owner, t.request, parameters, workload="background")
    except Miss as exc:
        return f"The small model could not find a parameter in the original request: {exc}."
    expected = {p["name"]: p["example"] for p in parameters}
    if not roles.same_params(expected, got, names):
        return (f"From the original request the small model read {json.dumps(got)}, "
                f"not {json.dumps(expected)}. Name and describe the parameters so the "
                "values are unambiguous.")
    entry = {"code": code, "root": "solve", "parameters": parameters,
             "tools": [s.tool for s in t.tools]}
    try:
        result = await run_answer(entry, t.request, owner, workload="background")
    except (Miss, EntryFailed, CodeRefused) as exc:
        return f"Running the code on the original request failed: {exc}."
    if not await judges_agree(owner, t.request, t.answer, result.reply):
        return ("Run on the original request, the code's reply does not give the same "
                f"answer as the original reply. It said:\n{result.reply[:2000]}")
    for v in variants if isinstance(variants, list) else []:
        if not isinstance(v, dict) or not str(v.get("request") or "").strip():
            continue
        want = {str(k): val for k, val in (v.get("parameters") or {}).items()}
        try:
            read = await extract_params(owner, str(v["request"]), parameters,
                                        workload="background")
        except Miss as exc:
            return f"For the made-up request {v['request']!r} the small model missed: {exc}."
        if not roles.same_params(want, read, names):
            return (f"For the made-up request {v['request']!r} the small model read "
                    f"{json.dumps(read)}, not {json.dumps(want)}.")
    return None


async def build(owner: str, scope: str, t: Transcript) -> Optional[str]:
    """Build and keep one entry, or return None. Never raises: a build that
    fails costs background time and nothing else."""
    if worth_building(t) is not None or _build_lock.locked():
        return None
    async with _build_lock:
        try:
            from src.interactive_gate import wait_for_interactive_quiet
            await wait_for_interactive_quiet("reasoning cache build")
            return await _build(owner, scope, t)
        except Exception as exc:
            logger.info("reasoning cache: no entry built for %s (%s)", scope, exc)
            return None


async def _build(owner: str, scope: str, t: Transcript) -> Optional[str]:
    vector = await asyncio.to_thread(roles.embed, t.request)
    if not vector:
        return None
    convo: List[Dict[str, str]] = [
        {"role": "system", "content": BUILDER_SYSTEM},
        {"role": "user", "content": transcript_message(t)},
        {"role": "assistant", "content": "I have read the work. Ready for step 1."},
    ]
    for ask in STEPS[:2]:
        await _say(owner, convo, ask)
    parameters = _clean_parameters(_json_list(await _say(owner, convo, STEPS[2])))
    await _say(owner, convo, STEPS[3])
    ask = STEPS[4]
    for _attempt in range(MAX_ATTEMPTS):
        spec = first_json_object(await _say(owner, convo, ask, max_tokens=4000)) or {}
        code = str(spec.get("code") or "")
        why = await _check(owner, t, parameters, code, spec.get("variants") or [])
        if why is None:
            from core.database import SessionLocal

            def _keep() -> str:
                db = SessionLocal()
                try:
                    return store.add_entry(
                        db, owner, scope,
                        applies_when=str(spec.get("applies_when") or "")[:2000],
                        request=t.request, answer=t.answer, embedding=vector,
                        parameters=parameters, code=code, root="solve",
                        tools=[s.tool for s in t.tools], source_tokens=t.source_tokens,
                        builder_model=roles.model_name("builder", owner))
                finally:
                    db.close()
            return await asyncio.to_thread(_keep)
        ask = f"That did not pass. {why}\nWrite step 5 again, as one JSON object only."
    return None

