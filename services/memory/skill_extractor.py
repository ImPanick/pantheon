# SPDX-License-Identifier: AGPL-3.0-or-later
"""
skill_extractor.py

Background auto-extraction of skills from complex agent runs.
When the agent takes >= 2 rounds or >= 2 tool calls to complete a task,
we ask the LLM to distill the approach into a reusable skill.
"""

import json
import logging
from typing import Optional

from .skill_prompts import (
    PORTABILITY_RULES, skill_field_guidance, skill_json_block,
)

logger = logging.getLogger(__name__)

# `P8-14`. The schema half of this prompt moved to `skill_prompts`, which is
# now the one place that says what a SKILL.md answer looks like — the teacher's
# trace prompt and the describe-it-yourself path compose the same block under
# their own framing. `P8-17` had put this prompt on the teacher's field *names*
# and the roadmap recorded them as one schema; they were not, because this one
# asked for `tags` and the teacher's did not. Both do now.
#
# What stays here is the half that is about a session, and it is the half that
# earns its keep: the "return null" list is what stops the extractor filing a
# grocery run or a Q&A as a procedure, and it is written about conversations.
SKILL_EXTRACT_FRAMING = (
    "You are analyzing an AI agent's work session. The agent took {rounds} rounds "
    "and {tool_count} tool calls to complete the task.\n\n"
    "Extract a reusable 'skill' ONLY IF the session contains a concrete, "
    "repeatable procedure the agent could follow to solve a similar problem "
    "ON THE COMPUTER next time (e.g. a sequence of shell commands, code, file "
    "edits, API calls, or tool usage).\n\n"
    "Return null (the bare word, no JSON) when the session is NOT a reusable "
    "computer procedure, including:\n"
    "- The real work happened OUTSIDE the computer (the user did something "
    "physically, in person, on another device, or by hand) and the agent only "
    "discussed or advised it.\n"
    "- A one-off, personal, or context-specific task that won't recur "
    "(personal errands, a specific person/place/date, casual conversation).\n"
    "- A pure question/answer or explanation with no transferable method.\n"
    "- The agent failed, gave up, or the approach is not worth repeating."
)

# This path posts the parsed object straight to `add_skill`, which sets
# `status` and `source` itself, so the model is asked for the nine content
# fields and nothing else.
SKILL_EXTRACT_CLOSING = (
    "Be conservative: if in doubt, return null.\n"
    "Return ONLY valid JSON (or the bare word null), no markdown fences — the "
    "fenced form is accepted, but the bare object is what is wanted."
)


def skill_extract_prompt(rounds: int, tool_count: int) -> str:
    """Framing, then the shared SKILL.md schema, then the closing rule.

    Built rather than one `.format()`-ed blob because the shared schema block
    is JSON and its braces would have to be doubled to survive `str.format` —
    which is precisely the hand-maintenance that let the copies drift.
    """
    return "\n\n".join([
        SKILL_EXTRACT_FRAMING.format(rounds=rounds, tool_count=tool_count),
        "When (and only when) a genuine reusable procedure exists, return a "
        "JSON object matching the SKILL.md schema:",
        skill_json_block(fenced=False),
        skill_field_guidance(),
        PORTABILITY_RULES,
        SKILL_EXTRACT_CLOSING,
    ])


# ---------------------------------------------------------------------------
# `P8-14` — "draft from my last session", said in a person's own words.
# ---------------------------------------------------------------------------
#
# The third caller of the shared schema, and the one the row exists for. The
# other two read machine material: `skill_extract_prompt` gets a transcript
# the agent produced, `_skill_from_trace_prompt` gets a tool trace. This one
# gets a sentence somebody typed, and the framing has to say so — a person
# describing what they did writes "I ssh'd in and restarted it", not a list of
# tool calls with argument shapes, and a prompt that demands the second from
# the first gets nothing back.
#
# **Nothing here writes.** The draft is returned to the caller to review, edit
# and save through the ordinary add path, the same posture `POST
# /api/skills/lint` takes: the question is answered, the library is not
# touched.
SKILL_FROM_DESCRIPTION_FRAMING = (
    "A person is describing something they worked out how to do, in their own "
    "words, so that the assistant can do it for them next time. Turn their "
    "description into a reusable SKILL.md procedure.\n\n"
    "They are not writing a specification and they have not seen the schema. "
    "Expect prose, missing steps and tool names given as everyday words "
    "(\"I looked it up\", \"I restarted the thing\"). Your job is to make the "
    "procedure explicit:\n"
    "- Name the actual tool for each step where you can tell which one they "
    "mean, and say what it is called rather than what they called it.\n"
    "- Where a step is genuinely missing, write the step you are confident "
    "belongs there. Do NOT invent a step you are guessing at — a short correct "
    "procedure beats a long speculative one.\n"
    "- `pitfalls` and `verification` are usually the parts a person leaves "
    "out. If they mentioned something going wrong, that is a pitfall. If they "
    "said how they knew it worked, that is a verification. Empty arrays are "
    "fine and are better than invented ones.\n\n"
    "Return the bare word null, and nothing else, ONLY if the description "
    "names no repeatable procedure at all — a question, an opinion, or one "
    "thing that happened once and will not happen again. A description that "
    "is thin is still a skill: draft it and keep `confidence` low."
)


def skill_from_description_prompt() -> str:
    """Framing for a typed description, then the shared SKILL.md schema.

    Deliberately takes no arguments: everything that varies is the person's
    text, which goes in the user turn rather than being interpolated into the
    system prompt. `P8-14` — the trace prompt's four `.format()` slots are what
    made it look retargetable when it was not.
    """
    return "\n\n".join([
        SKILL_FROM_DESCRIPTION_FRAMING,
        "Output ONE fenced JSON code block matching this schema and nothing "
        "else:",
        skill_json_block(),
        skill_field_guidance(),
        PORTABILITY_RULES,
    ])


async def draft_skill_from_description(
    description: str,
    *,
    endpoint_url: str,
    model: str,
    headers: Optional[dict] = None,
    timeout: int = 60,
) -> Optional[dict]:
    """Draft a skill from what a person typed. Returns the nine content fields,
    or None when the model declined or answered with nothing usable.

    Parsing is `_extract_json_object` + `_normalise_extracted`, the same two
    functions the session extractor uses (`Law 14`) — which is what buys this
    path the four-field fallback `P8-17` found was load-bearing for small local
    models, for free and without a second normaliser to keep in step.
    """
    text = (description or "").strip()
    if not text:
        return None
    if not model:
        logger.debug("[skill-draft] no model configured, skipping")
        return None

    from src.llm_core import llm_call_async

    try:
        response = await llm_call_async(
            endpoint_url,
            model,
            [
                {"role": "system", "content": skill_from_description_prompt()},
                {"role": "user", "content": f"What they did:\n{text}"},
            ],
            headers=headers or {},
            timeout=timeout,
        )
    except Exception as e:
        logger.warning("[skill-draft] model call failed: %s", e)
        return None

    if not response or response.strip().lower() == "null":
        return None

    # Same reasoning-model preamble strip the session extractor needs: a
    # thinking model emits its chain of thought before the JSON however firmly
    # the prompt asks for raw JSON.
    try:
        from src.text_helpers import strip_think as _strip_think
        response = _strip_think(response, prose=True, prompt_echo=True)
    except Exception:
        pass

    data = _extract_json_object(response)
    if not isinstance(data, dict):
        return None
    draft = _normalise_extracted(data)
    if not draft.get("description") and not draft.get("procedure"):
        # A shape with neither a sentence nor a step is not a draft a person
        # can edit into a skill; say nothing rather than hand back a husk.
        return None
    return draft


# Skills the model is unsure about (or that read as one-offs) add clutter —
# drop anything below this confidence.
MIN_CONFIDENCE = 0.6

# How many recent messages to include
CONTEXT_WINDOW = 12


def _normalise_extracted(data: dict) -> dict:
    """The modern SKILL.md field set, whichever shape the model answered in.

    `P8-17`. The prompt above asked for `title` / `problem` / `solution` /
    `steps` and the call below passed exactly those four through, so **every
    skill this extractor has ever written had an empty Pitfalls section, an
    empty Verification section, and `category: general`** — four of the fields
    the schema supports, unreachable from the path that produces most of a
    user's library. The fields are asked for now.

    The old keys are still accepted, and that is not politeness: a 7B local
    model handed a nine-field schema will sometimes answer with the four-field
    one it has seen more of on the internet, and dropping that response would
    turn a partially-filled skill into no skill at all.
    """
    def _txt(*keys) -> str:
        for k in keys:
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _lst(*keys) -> list:
        for k in keys:
            v = data.get(k)
            if isinstance(v, list):
                items = [str(x).strip() for x in v if str(x).strip()]
                if items:
                    return items
            elif isinstance(v, str) and v.strip():
                return [v.strip()]
        return []

    return {
        "name": _txt("name"),
        "description": _txt("description", "title"),
        "category": _txt("category") or "general",
        "when_to_use": _txt("when_to_use", "problem"),
        "procedure": _lst("procedure", "steps"),
        "pitfalls": _lst("pitfalls"),
        "verification": _lst("verification"),
        "tags": _lst("tags"),
        # Old shape only: with a `procedure` present `add_skill` ignores it, so
        # this carries a four-field answer's prose body and nothing else.
        "solution": _txt("solution"),
    }


def _skill_dicts(skills):
    for skill in skills or []:
        if isinstance(skill, dict):
            yield skill


def _has_duplicate_title(skills, title: str) -> bool:
    wanted = title.lower()
    for skill in _skill_dicts(skills):
        existing = skill.get("title", "")
        if isinstance(existing, str) and existing.lower() == wanted:
            return True
    return False


def _extract_json_object(text: str) -> Optional[dict]:
    """Best-effort extraction of a JSON object from an LLM response.

    The response may be wrapped in code fences or surrounded by prose. Uses
    json.JSONDecoder().raw_decode() to locate the boundaries of complete JSON
    objects starting at each '{' position. Nested objects are filtered out to
    keep only top-level candidates. If multiple non-overlapping valid JSON
    objects are found, it is treated as ambiguous and returns None. Otherwise,
    returns the single valid candidate dictionary.
    """
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    decoder = json.JSONDecoder()
    candidates = []

    start = s.find("{")
    while start != -1:
        try:
            obj, idx = decoder.raw_decode(s[start:])
            end_pos = start + idx
            if isinstance(obj, dict):
                candidates.append((start, end_pos, obj))
        except (json.JSONDecodeError, ValueError):
            pass
        start = s.find("{", start + 1)

    # Filter out nested candidates to identify top-level dictionaries
    top_level = []
    for c in candidates:
        is_nested = False
        for other in candidates:
            if other == c:
                continue
            if other[0] <= c[0] and c[1] <= other[1]:
                is_nested = True
                break
        if not is_nested:
            top_level.append(c)

    if not top_level:
        return None

    if len(top_level) > 1:
        logger.debug(
            "[skill-extract] Found multiple non-overlapping JSON objects: %s",
            [item[2].get("title") for item in top_level]
        )
        return None

    return top_level[0][2]


async def maybe_extract_skill(
    session,
    skills_manager,
    endpoint_url: str,
    model: str,
    headers: dict,
    round_count: int,
    tool_count: int,
    owner: Optional[str] = None,
):
    """Extract a skill if the agent run was complex enough."""
    if not model:
        logger.debug("[skill-extract] No model provided, skipping")
        return None

    # Quiet by default; flip to DEBUG when chasing extractor issues.
    logger.debug(
        "[skill-extract] start: rounds=%d tools=%d model=%s owner=%s",
        round_count, tool_count, model, owner,
    )
    if round_count < 2 and tool_count < 2:
        logger.debug("[skill-extract] BELOW threshold (need rounds>=2 or tools>=2)")
        return None

    try:
        from src.llm_core import llm_call_async

        # Get recent messages
        history = session.get_context_messages()
        recent = history[-CONTEXT_WINDOW:] if len(history) > CONTEXT_WINDOW else history
        if not recent:
            logger.debug("[skill-extract] no recent messages, skipping")
            return None

        # Strip media (images/audio) from messages
        stripped_recent = []
        for msg in recent:
            content = msg.get("content", "")
            if isinstance(content, list):
                text_only = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
                if not text_only and content:
                    continue
                content = text_only
            stripped_recent.append({"role": msg.get("role"), "content": content})

        if not stripped_recent:
            return None

        # Build conversation summary for extraction
        conv_lines = []
        for msg in stripped_recent:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                )
            # Truncate long messages
            if len(content) > 500:
                content = content[:500] + "..."
            conv_lines.append(f"[{role}] {content}")

        conversation = "\n".join(conv_lines)

        prompt = skill_extract_prompt(round_count, tool_count)

        import time as _time
        _t0 = _time.monotonic()
        logger.debug(
            "[skill-extract] calling LLM (endpoint=%s, ctx=%d msgs, timeout=30s)",
            endpoint_url, len(recent),
        )
        response = await llm_call_async(
            endpoint_url,
            model,
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Conversation:\n{conversation}"},
            ],
            headers=headers,
            timeout=30,
        )
        logger.debug(
            "[skill-extract] LLM returned in %.1fs (len=%d, head=%r)",
            _time.monotonic() - _t0, len(response or ""), (response or "")[:80],
        )

        if not response or response.strip().lower() == "null":
            logger.debug(
                "[skill-extract] LLM declined (returned null/empty) — "
                "session deemed not a reusable procedure"
            )
            return None

        # Some models (MiniMax, Qwen-Thinker, DeepSeek-R1) emit their
        # chain-of-thought BEFORE the JSON output even when asked for
        # raw JSON. `strip_think(prose=True, prompt_echo=True)` removes
        # <think>…</think> tags AND prose-style "Let me analyze this…"
        # preambles. Without it, json.loads bombed on character 0 every
        # time and the silent-bail looked like "extractor doesn't work".
        try:
            from src.text_helpers import strip_think as _strip_think
            response = _strip_think(response, prose=True, prompt_echo=True)
        except Exception:
            pass

        # Parse JSON. The object may be wrapped in code fences or surrounded by
        # commentary (and may contain a stray/invalid brace fragment before
        # the real object — including one that makes the response itself look
        # like it starts with '{'), so use a tolerant extractor that tries the
        # whole string first and then each '{' candidate left-to-right.
        data = _extract_json_object(response)
        if not data:
            logger.debug("[skill-extract] no JSON object found in response, dropping")
            return None

        fields = _normalise_extracted(data)
        title = fields["description"]
        if not title:
            logger.debug("[skill-extract] LLM returned object with no description/title, dropping")
            return None
        if not fields["procedure"] and not fields["solution"]:
            logger.debug("[skill-extract] '%s' has no procedure — dropping", title)
            return None

        # Honour the model's own reliability/reusability estimate — low-
        # confidence extractions are usually one-offs or shaky procedures.
        try:
            _conf = float(data.get("confidence", 0.7))
        except (TypeError, ValueError):
            _conf = 0.7
        if _conf < MIN_CONFIDENCE:
            logger.debug(
                "[skill-extract] '%s' below confidence floor (%.2f < %.2f) — dropped",
                title, _conf, MIN_CONFIDENCE,
            )
            return None

        # Check for duplicate skills
        existing = skills_manager.load(owner=owner)
        if _has_duplicate_title(existing, title):
            logger.debug("[skill-extract] '%s' already exists — dropped as duplicate", title)
            return None

        # Auto-publish gate: if the user has `auto_approve_skills` on, the
        # newly-extracted skill is created `published` immediately rather
        # than waiting for the next audit batch. The audit still runs later
        # and can demote it back to `draft` (or delete) on failure. Default
        # ON matches the UI label "Auto-approve skills".
        _initial_status = "draft"
        try:
            from routes.prefs_routes import _load_for_user as _load_prefs
            _prefs = _load_prefs(owner) or {}
            if _prefs.get("auto_approve_skills", True):
                _initial_status = "published"
        except Exception:
            pass

        entry = skills_manager.add_skill(
            name=fields["name"] or None,
            description=fields["description"],
            category=fields["category"],
            when_to_use=fields["when_to_use"],
            procedure=fields["procedure"],
            pitfalls=fields["pitfalls"],
            verification=fields["verification"],
            tags=fields["tags"],
            source="learned",
            confidence=data.get("confidence", 0.7),
            session_id=getattr(session, "session_id", None),
            owner=owner,
            status=_initial_status,
            # Old-shape carrier: `add_skill` uses it only when `procedure` is
            # empty, which is the four-field answer this still accepts.
            solution=fields["solution"],
        )
        if entry.get("_deduped"):
            # Nothing was written, so nothing was added. `do_manage_skills`
            # already returns before firing on this branch, with the comment
            # saying why; the extractor fired anyway, and a `skill_added` event
            # for a skill that does not exist is a trigger firing on nothing.
            logger.debug("[skill-extract] '%s' matched existing `%s` — not created",
                         title, entry.get("_duplicate_of"))
            return entry
        try:
            from src.event_bus import fire_event
            fire_event("skill_added", owner, {"name": entry.get("name") or title})
        except Exception:
            logger.debug("skill_added event dispatch failed", exc_info=True)
        logger.info("Auto-extracted skill: %s (id=%s)", title, entry["id"])
        return entry

    except json.JSONDecodeError as e:
        logger.debug("[skill-extract] non-JSON LLM response, dropping: %s", e)
        return None
    except Exception as e:
        # Real exceptions stay INFO+warning so they don't get lost when
        # users only have default log level. `exc_info=True` ships the
        # full traceback so timeouts vs auth vs import errors are
        # distinguishable from outside.
        logger.warning("[skill-extract] FAILED: %s", e, exc_info=True)
        return None
