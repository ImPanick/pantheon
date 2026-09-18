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
                          ceiling_default=None) -> dict:
    """The composer's payload: the budgets, and what is spending them.

    `turn` is `build_user_content`'s `budget_report` out-parameter — the real
    accounting from the real path, or `None` when nothing has been measured.

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
        "system, skills, memory and history are assembled in src/agent_loop.py "
        "and are not yet emitted per turn — see P12-09, B750 and B751."
    )
    return report


def _estimate_tokens_for_chars(chars: int) -> int:
    """The product's own estimator, asked about a block of this many chars."""
    from src.model_context import estimate_tokens
    return estimate_tokens([{"role": "user", "content": "x" * max(0, int(chars))}])
