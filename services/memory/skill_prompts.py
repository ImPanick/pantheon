# SPDX-License-Identifier: AGPL-3.0-or-later
# services/memory/skill_prompts.py
"""One statement of what a SKILL.md answer looks like, for every prompt that
asks a model for one.

`P8-14`. Three prompts asked a model to write a skill and each carried its own
copy of the schema:

  * `src/teacher_escalation.py::_TEACHER_SKILL_FROM_TRACE_PROMPT` — eleven keys
    in a fenced JSON block, **no `tags`**.
  * `services/memory/skill_extractor.py::SKILL_EXTRACT_PROMPT` — nine keys as
    prose bullets, **`tags` but no `status`/`source`**.
  * and the one `P8-14` exists to add.

`P8-17` moved the second onto the first's field *names* and the roadmap records
them as "the same schema". They were never the same: they disagreed about
`tags`, which is the field the whole-token boost in `get_relevant_skills`
depends on, so the extractor could ask for it and the teacher could not. That is
`Law 13` — a feature set in one of N places — and writing a third copy for the
new caller is how it becomes four.

**What is shared and what is not.** The schema and the portability rules are
functions of the SKILL.md format and of nothing else: they read identically
whether the model is looking at a tool trace, a conversation or a sentence the
user typed. The *framing* — what the model is holding, and when it should
decline — is the opposite, and is why `P8-14` is a factoring rather than a
retarget: the trace prompt's body says "the steps that ACTUALLY worked in the
trace" and "if the trace did NOT genuinely solve the user's problem … output
NO_SKILL", which is a lie to the model about its input when the input is a
person's description. Each caller writes its own framing and composes the
shared half underneath.

Nothing here talks to a model or to disk. It builds strings.
"""

from __future__ import annotations

import json
from typing import Dict, Optional, Sequence, Tuple

# Every field a skill-authoring prompt may ask for, in the order a SKILL.md
# reads, with the JSON placeholder and the one thing an author needs told about
# it. The guidance is the extractor's, which was the better-written of the two
# copies — it says *why* the field matters, and "retrieval matches requests
# against this text" is the sentence that stops a model writing a `when_to_use`
# nobody's request will ever match.
#
# `tags` and `confidence` are here because the store reads them
# (`get_relevant_skills` boosts on a whole-token tag match; the injection floor
# compares against `confidence`). Bookkeeping a caller pins rather than asks for
# — `action`, `status`, `source` — is passed as `pinned` instead, so it appears
# in the JSON template without inviting the model to invent a value.
_FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("name", '"<short-kebab-case-slug>"',
     'short kebab-case slug — the skill\'s id, e.g. "rotate-nginx-logs"'),
    ("description", '"<one line, under 200 characters>"',
     "ONE line, under 200 characters. This is the only sentence the assistant "
     "sees about this skill when deciding whether to open it."),
    ("category", '"<single lowercase word>"',
     'one lowercase word grouping it — "dev", "email", "system", "media", '
     '"research", etc.'),
    ("when_to_use", '"<the trigger, in the words a user would say>"',
     "the trigger, in the words a user would actually say. Retrieval matches "
     "requests against this text, so a vague one means the skill is never "
     "found."),
    ("procedure", '["Step 1: <specific tool name and arg shape>", "Step 2: ..."]',
     "array of 3-7 short steps, each naming the SPECIFIC tool and argument "
     "shape to use, generalised away from this particular request"),
    ("pitfalls", '["<failure mode and how to recover>"]',
     "array of failure modes and how to recover from each. Use [] only if "
     "there genuinely were none."),
    ("verification", '["<the check that proves it worked>"]',
     "array of checks that confirm the procedure actually worked — the "
     'commands or observations that prove it, not "check it looks right"'),
    ("tags", '["<keyword>", "<keyword>"]',
     "array of 3-5 keywords. A whole-word match against one of these is the "
     "strongest retrieval signal there is, so use the words a person would "
     "type."),
    ("confidence", "0.8",
     "0.0-1.0, how reliable AND reusable this procedure is"),
)

FIELD_NAMES: Tuple[str, ...] = tuple(f for f, _p, _g in _FIELDS)

# Input-agnostic by construction: it is about the machine the skill will run on
# later, not about where the skill came from. Lifted verbatim from the teacher's
# trace prompt, which is the only place it has ever existed.
PORTABILITY_RULES = """\
**PORTABILITY — CRITICAL.** Skills are shared across users. Strip every
user-specific token before writing the procedure:
  - Replace hostnames/IPs with placeholders (`<gpu_host>` etc.) or say to
    discover them at runtime via `list_serve_presets` / `list_cached_models`.
  - Replace user-specific paths (`/home/<user>/...`) with the wrapped tool
    that picks the right binary on whatever machine runs the skill.
  - Don't bake in the specific model repo_id you happened to use unless the
    skill is about that exact model.
  - Reference the high-level tools (`serve_model`, `stop_served_model`,
    `serve_preset`, `list_cached_models`, `search_hf_models`, etc.) rather
    than `ssh <host> 'tmux new-session ... vllm serve ...'` shell
    incantations. Raw shell launches bypass the cookbook tracker and don't
    reproduce on another user's box."""


def skill_json_block(
    pinned: Optional[Dict[str, object]] = None,
    *,
    fields: Optional[Sequence[str]] = None,
    fenced: bool = True,
) -> str:
    """The JSON template a model is asked to fill in.

    `pinned` is bookkeeping the caller already knows the answer to — it is
    printed as a literal value rather than a placeholder, so the model copies it
    instead of choosing. `fields` narrows the asked-for set; the default is all
    of `FIELD_NAMES` in SKILL.md order.
    """
    wanted = list(fields) if fields is not None else list(FIELD_NAMES)
    unknown = [f for f in wanted if f not in FIELD_NAMES]
    if unknown:
        raise ValueError(f"not SKILL.md fields: {unknown}")
    lines = []
    for key, value in (pinned or {}).items():
        lines.append(f'  "{key}": {json.dumps(value)},')
    for name, placeholder, _guidance in _FIELDS:
        if name in wanted:
            lines.append(f'  "{name}": {placeholder},')
    if lines:
        lines[-1] = lines[-1].rstrip(",")
    body = "{\n" + "\n".join(lines) + "\n}"
    return f"```json\n{body}\n```" if fenced else body


def skill_field_guidance(fields: Optional[Sequence[str]] = None) -> str:
    """One bullet per field, saying what it is for."""
    wanted = list(fields) if fields is not None else list(FIELD_NAMES)
    return "\n".join(
        f'- "{name}": {guidance}'
        for name, _p, guidance in _FIELDS if name in wanted
    )


def skill_schema_section(
    pinned: Optional[Dict[str, object]] = None,
    *,
    fields: Optional[Sequence[str]] = None,
    portability: bool = True,
) -> str:
    """The whole shared half: the template, what each field is for, and — unless
    the caller is writing a skill that cannot leave this machine — the
    portability rules.

    Composed under a caller's own framing. It says nothing about where the
    material came from, because that is the half that is not shared.
    """
    parts = [
        "Output ONE fenced JSON code block matching this schema and nothing "
        "else:",
        skill_json_block(pinned, fields=fields),
        skill_field_guidance(fields),
    ]
    if portability:
        parts.append(PORTABILITY_RULES)
    return "\n\n".join(parts)
