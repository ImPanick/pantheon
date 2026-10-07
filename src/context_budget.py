# SPDX-License-Identifier: AGPL-3.0-or-later
"""Adaptive input-token budget for the agent loop (#1170).

The agent soft-trims its input context to ``agent_input_token_budget`` (default
6000). The old computation was ``min(context_length or budget, budget)``, which
made the 6000 default a hard ceiling for *every* model — so a 128K or 1M context
model was silently capped at 6000 input tokens even though it can hold far more.

This derives the effective budget from the model's discovered context window when
the user has NOT set an explicit budget, while still honouring an explicit setting
exactly (clamped to the window). Pure and side-effect free so it is unit-testable.
"""

# Generous ceiling so long-context models are unblocked without sending a
# pathologically large prompt every agent turn. Tunable; chosen to fully cover
# 128K models and give 1M models a large but bounded budget.
DEFAULT_HARD_MAX = 200_000
DEFAULT_BUDGET = 6000
DEFAULT_HEADROOM = 0.85


def _int_or_zero(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def compute_input_token_budget(
    configured: int,
    context_length: int,
    explicit: bool,
    *,
    default: int = DEFAULT_BUDGET,
    headroom: float = DEFAULT_HEADROOM,
    hard_max: int = DEFAULT_HARD_MAX,
) -> int:
    """Return the effective soft input-token budget.

    Args:
        configured: the value read from settings (may be the default).
        context_length: the model's discovered context window. Pass 0 when the
            window is unknown / only a bare fallback — auto-scaling then stays
            conservative instead of trusting an unproven window (review on #4122).
        explicit: True if the user set a NON-default budget. The default value is
            the "auto" sentinel (scale to the window); any other value is an
            explicit cap. (A deliberately-chosen default can't be distinguished
            from a materialized default by value, so the default reads as auto.)

    Rules:
        - Explicit user budget is honoured exactly, only clamped to the model's
          window when that window is known (the user's deliberate choice wins;
          ``hard_max`` is an auto-budget ceiling only — see #1230).
        - Otherwise (auto), scale to ``headroom`` of the context window, capped at
          ``hard_max`` — so long-context models use their capacity.
        - When the window is unknown (context_length <= 0), use the conservative
          ``default`` budget and do NOT scale off the fallback.
    """
    configured = _int_or_zero(configured)
    context_length = _int_or_zero(context_length)

    if explicit and configured > 0:
        return min(configured, context_length) if context_length > 0 else configured

    if context_length > 0:
        scaled = int(context_length * headroom)
        return max(1, min(scaled, hard_max))

    return configured if configured > 0 else default


def agent_input_budget(context_length: int, get_setting) -> int:
    """The input-token budget the agent loop trims one request to; 0 = no trim.

    `P23-04` (CHAT-M-4). One computation for the two places that need it: the
    agent loop, which trims to it, and the context wheel, which says how full
    it is. Measured on `9560d50`: on an endpoint that reports no window the
    loop trimmed to 6,000 tokens (`Trimming messages: 5002 tokens > 4976
    budget (ctx=6000)`) while the wheel drew the 128K fallback and "Free space
    113K". The 6,000 floor is a reviewed decision (#4122, tracker H18) and
    stays; what the wheel draws is this.

    ``context_length`` is the *proven* window (0 when unknown — never the bare
    fallback, the review's point on #4122); ``get_setting(key, default)`` reads
    the two settings the loop reads.
    """
    soft = _int_or_zero(get_setting("agent_input_token_budget", DEFAULT_BUDGET))
    if soft <= 0:
        return 0
    try:
        hard_max = int(get_setting("agent_input_token_hard_max", DEFAULT_HARD_MAX) or DEFAULT_HARD_MAX)
    except (TypeError, ValueError):
        hard_max = DEFAULT_HARD_MAX
    if hard_max <= 0:
        hard_max = DEFAULT_HARD_MAX
    return compute_input_token_budget(soft, context_length, budget_is_explicit(soft), hard_max=hard_max)


def budget_is_explicit(configured: int, *, default: int = DEFAULT_BUDGET) -> bool:
    """Whether a configured agent_input_token_budget is a deliberate explicit cap.

    The default value is the "auto" sentinel (scale to the model's window), so only
    a NON-default positive value counts as explicit. This keys off the VALUE, not
    settings *presence* — the settings-save path materializes every default into
    settings.json, so a persisted default must still read as auto (the regression
    #4121 / #1230 are about). Centralised here so the materialized-default contract
    is unit-testable and can't silently regress to a presence check.
    """
    configured = int(configured or 0)
    return configured > 0 and configured != default


# ── The character budgets (`P12-04`) ────────────────────────────────────────
#
# Everything above this line is the *token* budget for the agent loop (#1170).
# Everything below is the *character* budget for what an attachment may put
# into one chat turn. They are two different questions about the same window,
# and they live in one module because `Law 14` asks for the existing scaffolding
# to be extended rather than an eighth budget authored beside seven others —
# which is the outcome this row's own path correction exists to prevent.
#
# **The seven, re-measured 2026-09-18** (scope: character/count budgets applied
# to attachment or injected content on the chat-ingest path, in non-test
# Python). Six are character counts in `src/document_processor.py`:
#
#   24,000  the shared budget one turn's attachments share   (`:29`)
#   30,000  one text attachment                              (`:933`, first arm)
#   10,000  one `.log` attachment                            (`:933`, second arm)
#   15,000  what the PDF extractor keeps                     (`:1033`)
#   15,000  the Office/EPUB markdown inlined into the turn   (`:1042`)
#   15,000  the PDF body inlined into the turn               (`:1427`)
#
# The seventh is `skill_max_injected` in `src/agent_loop.py`, a count rather
# than a character budget, and already a setting.
#
# The row named five of the seven and called the fourth "the PDF's 15,000" as
# though there were one. There are **three separate 15,000s**, they answer three
# different questions, and an operator raising "the PDF budget" would have moved
# one of them.
#
# SETTINGS-ONLY. None of the six had a `PANTHEON_*` variable, so `Law 1`
# requires nothing and a new variable would be a new place the same number can
# be set (`Law 13`) — the reasoning `P12-05b` applied to the throttles.
CONTEXT_BUDGETS: dict[str, int] = {
    "context_attachment_total_chars": 24000,
    "context_text_file_chars": 30000,
    "context_log_file_chars": 10000,
    "context_pdf_extract_chars": 15000,
    "context_office_inline_chars": 15000,
    "context_pdf_inline_chars": 15000,
}

#: The key that is the ceiling rather than one more budget beside the others.
#: This is what makes the six *one coherent budget*: a turn has this many
#: characters for attachments, and no single file's budget may exceed it.
CONTEXT_BUDGET_CEILING = "context_attachment_total_chars"

#: A budget of zero drops every attachment while reading as a configured
#: number, which is the shape `FORBIDDEN.md` Part 2 refuses for the upload caps.
#: The ceiling is sanity, not policy.
MIN_CONTEXT_BUDGET_CHARS = 1
MAX_CONTEXT_BUDGET_CHARS = 2_000_000

#: What each budget bounds, in the words a person setting it would use. One
#: sentence each, because a settings row reading `context_pdf_inline_chars`
#: with no explanation is `Law 15`'s tutorial requirement in miniature.
CONTEXT_BUDGET_LABELS: dict[str, str] = {
    "context_attachment_total_chars":
        "Total characters all attachments in one message may use",
    "context_text_file_chars": "One text or code attachment",
    "context_log_file_chars": "One .log attachment",
    "context_pdf_extract_chars": "Text kept from a PDF when it is extracted",
    "context_office_inline_chars": "Word/Excel/EPUB text placed in the message",
    "context_pdf_inline_chars": "PDF text placed in the message",
}


def resolve_context_budget_detail(key: str, owner=None, *, ceiling_default=None,
                                  ceiling=None):
    """One character budget and the layer that decided it.

    Resolved through **role profile → instance setting → built-in default** by
    `limit_policy.resolve_int_limit`, which is `settings.resolve_limit` under
    the short source names. There is no environment leg because none of these
    six has an environment variable; `env_name=None` is the same choice
    `events_retention_days` already documents.

    `ceiling_default` is the built-in default for the shared ceiling, supplied
    by the caller that owns a module constant for it —
    `document_processor.MAX_INLINE_ATTACHMENT_CHARS`, which survives (`Law 1`)
    and is read as a live attribute so a test that sets it still decides,
    exactly as `P12-03` left the byte caps.

    Every per-file budget is clamped to the resolved ceiling. That clamp is the
    row's *"single coherent budget"*: without it, a per-file cap of 30,000
    against a shared budget of 24,000 means the first attachment is truncated
    twice, by two numbers, with two different markers — and a role lowering the
    ceiling would not lower anything a single large file could claim.
    """
    from src.limit_policy import ResolvedLimit, resolve_int_limit

    if key not in CONTEXT_BUDGETS:
        raise KeyError(f"{key} is not a context budget")

    if ceiling is None:
        ceiling = resolve_int_limit(
            CONTEXT_BUDGET_CEILING,
            default=(CONTEXT_BUDGETS[CONTEXT_BUDGET_CEILING]
                     if ceiling_default is None else int(ceiling_default)),
            env_name=None, owner=owner,
            minimum=MIN_CONTEXT_BUDGET_CHARS, maximum=MAX_CONTEXT_BUDGET_CHARS,
        )
    elif not isinstance(ceiling, ResolvedLimit):
        # An already-resolved number, handed down by a caller that resolved it
        # once for the whole turn. `P12-03`'s rule: a multi-file message must
        # not have two different budgets applied to it because a settings save
        # landed between its first attachment and its last.
        ceiling = ResolvedLimit(value=int(ceiling), source="turn")
    if key == CONTEXT_BUDGET_CEILING:
        return ceiling

    own = resolve_int_limit(
        key, default=CONTEXT_BUDGETS[key], env_name=None, owner=owner,
        minimum=MIN_CONTEXT_BUDGET_CHARS, maximum=MAX_CONTEXT_BUDGET_CHARS,
    )
    if own.value <= ceiling.value:
        return own
    # `Law 10`: the operator asked for 30,000 and got 24,000 because the turn
    # only has 24,000. That is a clamp, and saying so is the difference between
    # "your number" and "your number, reduced".
    return ResolvedLimit(value=ceiling.value, source=own.source, clamped=True)


def resolve_context_budget(key: str, owner=None, *, ceiling_default=None,
                           ceiling=None) -> int:
    """The effective character budget. See `resolve_context_budget_detail`."""
    return resolve_context_budget_detail(
        key, owner, ceiling_default=ceiling_default, ceiling=ceiling).value


def fit_to_context_budget(text: str, key: str, owner=None, *,
                          ceiling_default=None, ceiling=None, marker: str = ""):
    """`(text, marker)` — `text` cut to `key`'s budget, `marker` empty if it fit.

    The one place a character budget is *applied*. Six call sites in
    `src/document_processor.py` each had their own `if len(x) > N: x = x[:N]`,
    and three of the six used the same literal for three different decisions.
    """
    text = text or ""
    limit = resolve_context_budget(key, owner, ceiling_default=ceiling_default,
                                   ceiling=ceiling)
    if len(text) <= limit:
        return text, ""
    return text[:limit], marker


def context_budget_report(owner=None, *, ceiling_default=None) -> dict:
    """Every character budget, its effective value, and who decided it.

    `P12-09`'s denominator and `P12-07`'s form, from one call. The *numerator* —
    what a given turn is actually spending — is `consumption`, which the caller
    fills in from `document_processor.build_user_content`'s own accounting; it
    is absent rather than zero when nothing has been measured, because a budget
    with an unmeasured spend and a budget with a spend of zero are different
    things to draw (`Law 10`).
    """
    budgets = []
    for key in CONTEXT_BUDGETS:
        detail = resolve_context_budget_detail(
            key, owner, ceiling_default=ceiling_default)
        budgets.append({
            "key": key,
            "label": CONTEXT_BUDGET_LABELS[key],
            "chars": detail.value,
            "source": detail.source,
            "clamped": detail.clamped,
            "is_ceiling": key == CONTEXT_BUDGET_CEILING,
        })
    return {"budgets": budgets, "ceiling_key": CONTEXT_BUDGET_CEILING}


# ── The prompt-assembly budgets (`P8-21`) ───────────────────────────────────
#
# A third family, and it is a family rather than a constant because the module
# already resolves two others through one path and `Law 14` asks for that path
# to be extended rather than copied. The attachment budgets above share a
# **ceiling** because they are all one turn's attachments; these do not, because
# a catalogue the model is shown and a PDF a person dropped in are not competing
# for the same allowance — clamping the skills index to
# `context_attachment_total_chars` would mean an operator who lowered their
# attachment budget silently truncated their skills catalogue, and a clamp that
# says "your number, reduced" for an unrelated reason is exactly the ambiguity
# `Law 10` refuses.
#
# **Measured 2026-09-19, because the row's number was wrong in both directions.**
# `P8-21` says the index "costs ~15 tokens per published skill on every single
# request". Rendering the real block through `render_skill_index_block` with the
# whole bundled library published: **286 entries, 80,610 characters, 24,187
# tokens** by `model_context.estimate_tokens` — **84.6 tokens per entry**, median
# entry line 275 characters, longest 1,001. That is 5.6× the row's figure, and
# the block alone is four times the 6,000-token default
# `agent_input_token_budget`.
#
# And it is not "every single request": all 286 bundled skills parse as drafts
# (no `status:` in their frontmatter), and `index_for` admits only published
# skills plus teacher-escalation drafts, so a **stock install renders 0
# characters**. The cost arrives on the first publish click, and then grows with
# no bound at all — which is what this budget is for.
#
# The default binds at roughly 43 entries of the measured median size. No
# install in this repo's history reaches that, so the default changes nothing
# today and exists to bound the growth rather than to cut anybody's library.
SKILL_INDEX_BUDGET = "context_skill_index_chars"

PROMPT_BUDGETS: dict[str, int] = {
    SKILL_INDEX_BUDGET: 12000,
}

PROMPT_BUDGET_LABELS: dict[str, str] = {
    SKILL_INDEX_BUDGET: "Skills catalogue listed in the system prompt",
}

MIN_PROMPT_BUDGET_CHARS = 200
MAX_PROMPT_BUDGET_CHARS = 2_000_000


def resolve_prompt_budget_detail(key: str, owner=None):
    """One prompt-assembly budget and the layer that decided it.

    Same resolver, same four layers, same `env_name=None` settings-only choice
    the six character budgets above already document — the only difference is
    that these are not clamped to the attachment ceiling, for the reason stated
    above the registry.
    """
    from src.limit_policy import resolve_int_limit

    if key not in PROMPT_BUDGETS:
        raise KeyError(f"{key} is not a prompt budget")
    return resolve_int_limit(
        key, default=PROMPT_BUDGETS[key], env_name=None, owner=owner,
        minimum=MIN_PROMPT_BUDGET_CHARS, maximum=MAX_PROMPT_BUDGET_CHARS,
    )


def resolve_prompt_budget(key: str, owner=None) -> int:
    """The effective character budget. See `resolve_prompt_budget_detail`."""
    return resolve_prompt_budget_detail(key, owner).value


# ── The seventh budget (`P2-09` / `B750`) ───────────────────────────────────
#
# `P12-04` brought six of seven under the policy and said plainly why it could
# not bring the seventh: `skill_max_injected`'s only consumer is
# `src/agent_loop.py`, which that row did not own, and a seventh key with no
# consumer is `Law 13`'s unwired half. It is wired here, in the same commit as
# its consumer.
#
# It is a COUNT, not a character budget, and it is deliberately **not** clamped
# to `context_attachment_total_chars` — same reasoning as the prompt budgets
# above: a person's attachments and the skills the model is shown are not
# competing for one allowance, and a clamp that says *"your number, reduced"*
# for an unrelated reason is the ambiguity `Law 10` refuses.
#
# **`B750` named three defects, and two of the three reproduce exactly.**
# Measured 2026-09-19 at `src/agent_loop.py:3144-3156`:
#
#   1. `_prefs.get("skill_max_injected", get_setting(...))` — a **per-user pref
#      silently beats everything**, so the role layer was never consulted.
#      True, and it is what this fixes.
#   2. `max(0, min(12, …))` — a **second clamp beside the resolver's**. True.
#      The 12 now lives here, once, and `resolve_int_limit` applies it.
#   3. *"`> 0` is its own off switch, which the other six budgets deliberately
#      do not have."* — **CORRECTED 2026-09-19.** It is not undocumented drift:
#      `static/index.html` ships the input as `min="0" max="12"` with the
#      caption *"Set to 0 to disable skill injection"* right under it. `B750`'s
#      prescribed `minimum=1` would silently turn a stored 0 into 1 for every
#      person who used that affordance, which is a `Law 1` subtraction of a
#      documented control. So **0 survives, as the USER's sentinel only.**
#
# The shape that keeps all of it: **the policy layers are a ceiling and the
# preference chooses within it.** A role that says 1 gives that person 1 even
# if their pref says 12; a person who typed 0 still gets none. The floor on the
# policy layers stays 1, so `role_limit_ranges`'s *"the floor is 1 on every
# key"* is still true and a role cannot switch somebody's skills off through a
# limit — `skills_enabled` is the switch for that, and it already exists.
SKILL_INJECTION_LIMIT = "skill_max_injected"

#: The shipped default, and the number three places used to state separately.
SKILL_INJECTION_DEFAULT = 3

#: The hard ceiling. It was `max(0, min(12, …))` in `src/agent_loop.py` and
#: `max="12"` in `static/index.html`, and raising the setting alone did nothing
#: above 12 because neither knew about the other.
MAX_SKILL_INJECTION = 12
MIN_SKILL_INJECTION = 1

#: What a user preference of 0 means. Not a limit — a switch, with its own
#: caption in the UI. `Law 10`: it is named rather than left as a bare `> 0`
#: test that reads as a guard against nonsense input.
SKILL_INJECTION_OFF = 0


def resolve_skill_injection_detail(owner=None, *, preference=None):
    """How many skills this turn may inject, and the layer that decided it.

    `preference` is the person's own `skill_max_injected` pref, or `None` when
    they have not set one. It CHOOSES WITHIN the policy; it does not beat it.

    * no preference          → the policy's number (role → setting → default)
    * preference `0`         → none, the documented off switch
    * preference `n > 0`     → `n`, capped at `MAX_SKILL_INJECTION`, and capped
                               further by the policy **only when somebody
                               actually set one**

    **That last clause is the whole design and it is `Law 1`.** The built-in
    default is not a ceiling anybody chose: before this, a person who typed 12
    into the `max="12"` input got 12, and resolving their preference against an
    unset default of 3 would have silently taken nine of them away. So the
    preference is capped by the policy **only when the policy came from a role
    profile or an instance setting** — an administrator's number — and not when
    it came from the shipped default. `resolve_int_limit` already reports which
    layer answered, so this is read off the verdict rather than guessed
    (`Law 10`).
    """
    from src.limit_policy import ResolvedLimit, resolve_int_limit

    policy = resolve_int_limit(
        SKILL_INJECTION_LIMIT, default=SKILL_INJECTION_DEFAULT, env_name=None,
        owner=owner, minimum=MIN_SKILL_INJECTION, maximum=MAX_SKILL_INJECTION,
    )
    if preference is None:
        return policy
    try:
        wanted = int(preference)
    except (TypeError, ValueError):
        return policy
    if wanted <= SKILL_INJECTION_OFF:
        return ResolvedLimit(value=SKILL_INJECTION_OFF, source="user preference")
    wanted = min(wanted, MAX_SKILL_INJECTION)
    administered = policy.source != "default"
    if not administered or wanted <= policy.value:
        return ResolvedLimit(value=wanted, source="user preference")
    # They asked for more than their administrator allows and got the
    # administrator's number. Saying `clamped` is the difference between "your
    # number" and "your number, reduced".
    return ResolvedLimit(value=policy.value, source=policy.source, clamped=True)


def resolve_skill_injection(owner=None, *, preference=None) -> int:
    """The effective skill-injection count. See `resolve_skill_injection_detail`."""
    return resolve_skill_injection_detail(owner, preference=preference).value


# ── What is consuming the window right now (`P12-09`) ───────────────────────
#
# `P12-09` asks for a live breakdown at the composer: system prompt, skills,
# retrieved memory, attachments, history. Only one of those five is assembled
# where a limit is applied — the attachments — and `build_user_content` has
# always computed exactly how many characters each one spent and then dropped
# the number on the floor. That half is measured here, from the product's own
# accounting rather than from a second computation beside it (`Law 14`).
#
# **The other four are not measured, and they say so.** They are assembled in
# `src/agent_loop.py`, which is not this row's to edit, and an unmeasured
# segment reported as `0` is a meter that draws a lie (`Law 10`). Each carries
# `measured: false` until the one emit named on the row lands.
CONTEXT_SEGMENTS = ("system", "skills", "memory", "attachments", "history")

#: What each segment is, in the words the composer should print beside its bar.
CONTEXT_SEGMENT_LABELS: dict[str, str] = {
    "system": "System prompt",
    "skills": "Skills",
    "memory": "Retrieved memory",
    "attachments": "Attachments",
    "history": "Conversation history",
}


def context_window_report(owner=None, *, turn: dict | None = None,
                          prompt: dict | None = None,
                          ceiling_default=None) -> dict:
    """The composer's payload: the budgets, and what is spending them.

    `turn` is `build_user_content`'s `budget_report` out-parameter — the real
    accounting from the real path, or `None` when nothing has been measured.

    `prompt` is the same thing for the prompt assembler: `{"skill_index_chars":
    N}` as `render_skill_index_block` actually rendered it. `P8-21` measures the
    skills segment and nothing else — `system`, `memory` and `history` are still
    assembled in `src/agent_loop.py` with nothing emitting their sizes, and they
    stay `measured: false` rather than drawing a zero (`Law 10`).

    The token figures go through `model_context.estimate_tokens`, which is the
    product's one estimator. A second one would answer a slightly different
    number than the trimmer uses, and a meter that disagrees with the thing it
    is metering is worse than no meter (`Law 7`).
    """
    report = context_budget_report(owner, ceiling_default=ceiling_default)
    segments = []
    for key in CONTEXT_SEGMENTS:
        entry = {"key": key, "label": CONTEXT_SEGMENT_LABELS[key],
                 "measured": False}
        if key == "skills" and prompt is not None and "skill_index_chars" in prompt:
            chars = int(prompt.get("skill_index_chars") or 0)
            entry.update({
                "measured": True,
                "chars": chars,
                "tokens": _estimate_tokens_for_chars(chars),
                "budget_chars": resolve_prompt_budget(SKILL_INDEX_BUDGET, owner),
                "truncated": bool(prompt.get("skill_index_truncated")),
                "omitted": int(prompt.get("skill_index_omitted") or 0),
            })
        if key == "attachments" and turn is not None:
            chars = int(turn.get("used_chars") or 0)
            entry.update({
                "measured": True,
                "chars": chars,
                "tokens": _estimate_tokens_for_chars(chars),
                "budget_chars": int(turn.get("total_chars") or 0),
                "remaining_chars": int(turn.get("remaining_chars") or 0),
                "items": list(turn.get("attachments") or []),
            })
        segments.append(entry)
    report["segments"] = segments
    report["measured_segments"] = [s["key"] for s in segments if s["measured"]]
    # Named rather than implied: a composer that draws four empty bars without
    # being told why has a `Law 15` problem, and so does the next agent.
    report["unmeasured_reason"] = (
        "system, memory and history are assembled in src/agent_loop.py and are "
        "not yet emitted per turn — see P12-09, B750 and B751. skills is "
        "measured when the caller hands in what render_skill_index_block "
        "rendered (P8-21)."
    )
    return report


def _estimate_tokens_for_chars(chars: int) -> int:
    """The product's own estimator, asked about a block of this many chars."""
    from src.model_context import estimate_tokens
    return estimate_tokens([{"role": "user", "content": "x" * max(0, int(chars))}])


# ── `B892`. What the whole window is spent on ─────────────────────────────────
#
# The meter above answers one question: how much of the attachment allowance a
# message spends, in characters. The person asks a bigger one — "what is using
# my context window?" — and the answer has to name every part of the request:
# the system prompt, the tool definitions sent with it, the skill index, saved
# memory, retrieved context, attachments and the conversation itself.
# `measure_request_segments` answers it for a request as it was actually
# assembled (`src/agent_loop.py` emits it as `metrics["context_breakdown"]`),
# and `session_context_breakdown` recombines that with the chat's history as it
# stands now, which is what `GET /api/session/{id}/context` serves.
#
# One estimator. Every figure below is `model_context.estimate_tokens` asked
# about the message or the slice of text it came from, so the categories add
# up to what the compaction gate and the trimmer measure (`Law 7`). Pictures
# and audio are not counted by that estimator, so they are listed as uncounted
# rather than given an invented number (`Law 10`).

import json as _json
import os as _os
import re as _re

CONTEXT_BREAKDOWN_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("system", "System prompt"),
    ("tools", "Tool definitions"),
    ("skills", "Skills"),
    ("memory", "Memories"),
    ("retrieved", "Retrieved context"),
    ("attachments", "Attachments"),
    ("conversation", "Chat"),
)

#: The parts a request carries besides the chat itself, measured on the last
#: request that was actually sent. The other two are re-measured from history.
REQUEST_OVERHEAD_CATEGORIES = ("system", "tools", "skills", "memory", "retrieved")

#: Items listed under one category before the rest are folded into one line.
BREAKDOWN_ITEM_LIMIT = 24

#: What an attachment *is*. Attachments are not all documents: a person attaches
#: code, photos, spreadsheets and logs, and the composer names each for what it
#: is instead of describing everything as text.
ATTACHMENT_KIND_LABELS: dict[str, str] = {
    "image": "Image",
    "code": "Code",
    "text": "Text",
    "document": "Document",
    "spreadsheet": "Spreadsheet",
    "audio": "Audio",
    "file": "File",
}

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic",
              ".heif", ".tif", ".tiff", ".avif", ".ico"}
_AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"}
_SHEET_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".ods", ".numbers"}
_DOCUMENT_EXT = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".epub", ".pptx", ".ppt",
                 ".odp", ".pages"}
_TEXT_EXT = {".txt", ".md", ".markdown", ".rst", ".log", ".text", ".adoc"}
_CODE_EXT = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java", ".kt", ".kts",
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".cs", ".go", ".rs", ".rb",
    ".php", ".swift", ".m", ".mm", ".scala", ".lua", ".pl", ".pm", ".r", ".jl",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd", ".sql", ".html",
    ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".json",
    ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml", ".proto",
    ".graphql", ".gql", ".dart", ".ex", ".exs", ".erl", ".hs", ".clj", ".elm",
    ".zig", ".nim", ".tf", ".gradle", ".cmake", ".mk", ".dockerfile", ".ipynb",
}
_CODE_NAMES = {"dockerfile", "makefile", "cmakelists.txt", "gemfile", "rakefile",
               "procfile", "jenkinsfile", "vagrantfile"}


def attachment_kind(name: str | None, mime: str | None = "") -> str:
    """One of `ATTACHMENT_KIND_LABELS`, from the file's name and type.

    The name wins over the type for code: browsers report most source files as
    `text/plain` or nothing at all, and "Text" is the wrong word for a `.py`.
    `static/js/contextUsage.js` (`attachmentKind`) answers the same question
    for a file that has not been sent yet, from the same lists.
    """
    base = _os.path.basename(str(name or "")).lower()
    ext = _os.path.splitext(base)[1]
    mime = str(mime or "").lower()
    if ext in _IMAGE_EXT or mime.startswith("image/"):
        return "image"
    if ext in _AUDIO_EXT or mime.startswith("audio/"):
        return "audio"
    if ext in _SHEET_EXT or "spreadsheet" in mime or mime in {
            "text/csv", "text/tab-separated-values", "application/vnd.ms-excel"}:
        return "spreadsheet"
    if ext in _DOCUMENT_EXT or mime == "application/pdf" or "wordprocessing" in mime \
            or "presentation" in mime or mime == "application/epub+zip":
        return "document"
    if ext in _CODE_EXT or base in _CODE_NAMES:
        return "code"
    if ext in _TEXT_EXT or mime.startswith("text/"):
        return "text"
    return "file"


# The blocks `src/document_processor.py` appends to a user message, one per
# attachment. The typed message is everything before the first of them.
_ATTACHMENT_BLOCK = _re.compile(
    r"(?m)^=== File: (?P<file>[^\n]+?) ===$"
    r"|\[(?P<tag>PDF content|Document content|Attached document|Attached file|"
    r"Form attached|PDF attached|Attachment omitted from inline context|"
    r"Attachment content truncated|Image attached but could not be processed|"
    r"Audio attached but could not be processed)"
    r"(?:(?: — |: )(?P<title>[^\]\n]+?))?(?=\]| —|\. )"
)
_TAG_KIND = {
    "PDF content": "document", "PDF attached": "document", "Form attached": "document",
    "Document content": "document", "Attached document": "document",
    "Image attached but could not be processed": "image",
    "Audio attached but could not be processed": "audio",
}
_SKILL_ENTRY = _re.compile(r"^- `([^`]+)`")


def _estimator():
    from src.model_context import estimate_tokens
    return estimate_tokens


def _text_tokens(text: str) -> int:
    """`estimate_tokens` on a slice of text, less the per-message overhead."""
    est = _estimator()
    empty = est([{"role": "user", "content": ""}])
    return max(0, est([{"role": "user", "content": str(text or "")}]) - empty)


def _split_attachments(text: str) -> tuple[str, list[dict]]:
    """The typed part of a user message, and one entry per attachment block."""
    text = str(text or "")
    matches = list(_ATTACHMENT_BLOCK.finditer(text))
    if not matches:
        return text, []
    blocks = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start():end]
        if m.group("file"):
            name = m.group("file").strip()
            kind = attachment_kind(name)
            if kind == "file":
                kind = "text"
        else:
            tag = m.group("tag")
            title = (m.group("title") or "").strip()
            name = title or tag
            kind = attachment_kind(title) if title else "file"
            if kind == "file":
                kind = _TAG_KIND.get(tag, "file")
        blocks.append({"name": name, "kind": kind, "chars": len(body),
                       "tokens": _text_tokens(body)})
    return text[:matches[0].start()], blocks


def _meta(msg: dict) -> dict:
    meta = msg.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _is_memory_message(msg: dict) -> bool:
    source = str(_meta(msg).get("source") or "").lower()
    if source.startswith("saved memory") or source.startswith("memory"):
        return True
    content = msg.get("content")
    return isinstance(content, str) and (
        "Core facts about the user:" in content
        or "Saved user memory facts" in content
        or "Memory context. Do not reference unless" in content
    )


def _skill_index_slice(text: str) -> str:
    """The skill index inside a system prompt, exactly as it was rendered."""
    try:
        from services.memory.skill_injection import INDEX_HEADING, INDEX_PREAMBLE
    except Exception:  # pragma: no cover - both are literals
        return ""
    start = text.find(INDEX_HEADING)
    if start < 0:
        return ""
    lines = text[start:].split("\n")
    kept = [lines[0]]
    for line in lines[1:]:
        s = line.strip()
        if (not s or s == INDEX_PREAMBLE or s.startswith("- `")
                or (s.startswith("**") and s.endswith("**"))):
            kept.append(line)
            continue
        break
    return "\n".join(kept)


def _fold(items: list[dict], limit: int = BREAKDOWN_ITEM_LIMIT) -> list[dict]:
    """The largest `limit` items, and one line saying what the rest add up to."""
    counted = sorted(items, key=lambda it: -(it.get("tokens") or 0))
    if len(counted) <= limit:
        return counted
    head, rest = counted[:limit], counted[limit:]
    head.append({"name": f"{len(rest)} more",
                 "tokens": sum(int(it.get("tokens") or 0) for it in rest),
                 "folded": len(rest)})
    return head


def _classify(msg: dict, index: int, history: bool) -> tuple[str, str]:
    """Which category one whole message belongs to, and what to call it."""
    role = str(msg.get("role") or "")
    meta = _meta(msg)
    source = str(meta.get("source") or "")
    injected = str(msg.get("_agent_injected") or "")
    if _is_memory_message(msg):
        return "memory", source or "Saved memory"
    if meta.get("trusted") is False or injected == "context":
        if "skill" in source.lower():
            return "skills", source
        return "retrieved", source or "Retrieved context"
    if role == "system":
        if not history and (injected in {"prompt", "merged_prompt"} or index == 0):
            return "system", "Instructions"
        return "conversation", "Summaries and notes"
    return "conversation", role or "user"


def measure_request_segments(messages, tools=None, *, history: bool = False) -> dict:
    """Split one request into the categories above, in tokens.

    `messages` is the list as it went to the model; `tools` is the tool schema
    list sent with it. `history=True` measures a chat's stored history instead,
    where no message is the system prompt. Returns `{"categories": [...],
    "total_tokens": N, "uncounted": [...]}`; each category carries `key`,
    `label`, `tokens` and `items`.
    """
    est = _estimator()
    totals = {key: 0 for key, _ in CONTEXT_BREAKDOWN_CATEGORIES}
    items: dict[str, list[dict]] = {key: [] for key, _ in CONTEXT_BREAKDOWN_CATEGORIES}
    convo: dict[str, list[int]] = {}
    uncounted: list[dict] = []
    role_names = {"user": "Your messages", "assistant": "Replies and tool calls",
                  "tool": "Tool results"}

    for index, msg in enumerate(messages or []):
        if not isinstance(msg, dict):
            continue
        whole = est([msg])
        category, name = _classify(msg, index, history)
        content = msg.get("content")
        if category == "system":
            skills = _skill_index_slice(content if isinstance(content, str) else "")
            skill_tokens = min(whole, _text_tokens(skills)) if skills else 0
            totals["skills"] += skill_tokens
            totals["system"] += whole - skill_tokens
            items["system"].append({"name": name, "tokens": whole - skill_tokens})
            for line in skills.split("\n"):
                m = _SKILL_ENTRY.match(line.strip())
                if m:
                    items["skills"].append({"name": m.group(1),
                                            "tokens": _text_tokens(line)})
            continue
        if category != "conversation":
            totals[category] += whole
            items[category].append({"name": name, "tokens": whole})
            continue

        texts: list[str] = []
        if isinstance(content, str):
            texts = [content]
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                kind = part.get("type")
                if kind == "text":
                    texts.append(str(part.get("text") or ""))
                elif kind in {"image_url", "input_image", "image", "audio", "input_audio"}:
                    what = "image" if "image" in kind else "audio"
                    entry = {"name": ATTACHMENT_KIND_LABELS[what], "kind": what,
                             "tokens": None, "uncounted": True}
                    uncounted.append(dict(entry))
                    items["attachments"].append(entry)
        attach_tokens = 0
        if str(msg.get("role") or "") == "user":
            for text in texts:
                _typed, blocks = _split_attachments(text)
                for block in blocks:
                    attach_tokens += block["tokens"]
                    items["attachments"].append(block)
        attach_tokens = min(attach_tokens, whole)
        totals["attachments"] += attach_tokens
        totals["conversation"] += whole - attach_tokens
        label = role_names.get(name, name)
        row = convo.setdefault(label, [0, 0])
        row[0] += 1
        row[1] += whole - attach_tokens

    items["conversation"] = [{"name": label, "count": count, "tokens": tokens}
                             for label, (count, tokens) in convo.items()]

    for schema in tools or []:
        if not isinstance(schema, dict):
            continue
        fn = schema.get("function") if isinstance(schema.get("function"), dict) else schema
        tokens = _text_tokens(_json.dumps(schema, ensure_ascii=False, sort_keys=True))
        totals["tools"] += tokens
        items["tools"].append({"name": str((fn or {}).get("name") or "tool"),
                               "tokens": tokens})

    categories = []
    for key, label in CONTEXT_BREAKDOWN_CATEGORIES:
        entry = {"key": key, "label": label, "tokens": int(totals[key]),
                 "items": items[key] if key == "conversation" else _fold(items[key])}
        if key == "tools":
            entry["count"] = len(items["tools"])
        categories.append(entry)
    return {
        "categories": categories,
        "total_tokens": int(sum(totals.values())),
        "uncounted": uncounted,
    }


def session_context_breakdown(history_messages, last_request: dict | None) -> dict:
    """The window as it stands: overhead from the last request, history now.

    `last_request` is the `context_breakdown` the most recent reply was sent
    with, or `None` for a chat that has not had one since this shipped. The
    overhead categories it cannot answer say `measured: False` — a chat that
    has not been answered yet has not sent a system prompt, and drawing a zero
    there would read as "costs nothing".
    """
    live = measure_request_segments(history_messages, history=True)
    by_key = {c["key"]: c for c in live["categories"]}
    last_by_key = {}
    if isinstance(last_request, dict):
        for cat in last_request.get("categories") or []:
            if isinstance(cat, dict) and cat.get("key"):
                last_by_key[cat["key"]] = cat
    categories = []
    for key, label in CONTEXT_BREAKDOWN_CATEGORIES:
        prior = last_by_key.get(key) if key in REQUEST_OVERHEAD_CATEGORIES else None
        if prior is not None:
            entry = {"key": key, "label": label,
                     "tokens": int(prior.get("tokens") or 0) + by_key[key]["tokens"],
                     "items": list(prior.get("items") or []) + by_key[key]["items"],
                     "measured": True, "source": "last_request"}
            if "count" in prior:
                entry["count"] = prior["count"]
        elif key in REQUEST_OVERHEAD_CATEGORIES and not by_key[key]["tokens"]:
            entry = {"key": key, "label": label, "tokens": 0, "items": [],
                     "measured": False, "source": None}
        else:
            entry = dict(by_key[key], measured=True, source="history")
        categories.append(entry)
    return {
        "categories": categories,
        "total_tokens": int(sum(c["tokens"] for c in categories if c.get("measured"))),
        "uncounted": live["uncounted"],
        "source": "last_request" if last_by_key else "history",
    }
