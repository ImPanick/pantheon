# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P4-10` — what the agent loop says when it stops itself.

Two guards in `stream_agent_loop` end work the model did not choose to end:

  * **the loop-breaker** — the same call over and over. It trips on a *runaway*
    (one exact call requested 15 times in a turn) or on a *stall* (four rounds in
    a row that only repeated calls already made and wrote nothing). It does not
    end the turn; it refuses that round's calls, switches tools off, and asks
    the model for its best answer from what it already has.
  * **the unkept promise** — the model writes "Let me check the logs" and ends
    its reply without making the call. It is nudged twice; the third time the
    turn ends.

Both used to report a fixed sentence. The loop-breaker's said *"The loop-breaker
detected repeated tool calls without new progress"* whichever of its two
conditions fired, and never which tool, how often or with what — the count was
never computed, only compared. The unkept-promise stop put the phrase it caught
on the wire as `matched` and the browser printed the fixed sentence instead. So
the one thing a person needs to decide what to do next — *what was it doing?* —
was the one thing neither stop said.

Everything here is a pure function of values the loop already holds, so both
reports are composed in one place and the live event, the saved record and any
other client that draws them read the same words (`Law 7`).

**Identity of a call.** `call_signature` is also what the loop-breaker *counts*
with. It used to key on the first 120 characters of the arguments, so two calls
that differed only after character 120 were "identical": the sentence this row
asks for would have been false for any long command, and a batch of distinct
calls with a long shared prefix — the "18 calendar events" case
`tests/test_loop_breaker_runaway.py` was written for — was aborted exactly as it
was before that fix, just with longer arguments. A digest of the whole text
makes "identical" mean identical, in one definition both uses share.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: The `kind` enum on a stop event (`Law 10`: an enum, not a boolean).
KIND_IDENTICAL_CALLS = "identical_calls"
KIND_NO_PROGRESS = "no_progress"
KIND_UNKEPT_PROMISE = "unkept_promise"

#: `arguments_state` — whether the repeated call's arguments are on the event.
ARGS_SHOWN = "shown"
ARGS_WITHHELD = "withheld"
ARGS_EMPTY = "empty"

#: How much of the arguments a stop line quotes. Enough to recognise the call;
#: the full text is on the tool card above it (`P4-09`).
ARGUMENTS_LIMIT = 80
#: How much of the promised action the unkept-promise line quotes.
PHRASE_LIMIT = 100

# Tools whose arguments are about credentials by definition (`tool_security`
# names each one's reach). Their arguments are never quoted, whatever they say.
_CREDENTIAL_TOOLS = frozenset({"vault_get", "vault_unlock", "vault_search", "manage_tokens"})

# Words that say an argument may carry a credential. Deliberately broad and
# deliberately a *withhold* rule rather than a mask: `diagnostic_bundle.redact`
# already masks what it can recognise (known key prefixes, `token=`/`api_key=`
# assignments, URL userinfo and query strings, long opaque strings), and it
# cannot recognise `PASSWORD=hunter2` or `sshpass -p hunter2`. A false positive
# here costs one line of context — the call is still named and counted, and its
# arguments are on the card above — and a false negative costs a secret.
_MAY_HOLD_CREDENTIAL = re.compile(
    r"(?i)(pass(?:word|wd|phrase)|sshpass|secret|token|api[_-]?key|apikey|"
    r"authori[sz]ation|bearer|credential|private[_ -]?key|cookie|-----BEGIN|"
    r"\bAKIA[0-9A-Z]{12,})"
)


def call_signature(tool_type: Any, content: Any) -> str:
    """One call's identity: its tool and a digest of its whole argument text.

    The loop-breaker keys both of its counters on this, and the stop report
    reads the counts back through it, so "identical" is one definition used
    three times rather than three that could drift (`Law 7`). Leading and
    trailing whitespace is not part of a call, as before; everything between is.
    """
    text = content if isinstance(content, str) else ("" if content is None else str(content))
    digest = hashlib.sha256(text.strip().encode("utf-8", "replace")).hexdigest()[:32]
    return f"{tool_type}:{digest}"


def _one_line(text: str, limit: int) -> str:
    """`text` on one line, whitespace collapsed, cut at `limit` with an ellipsis."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: max(1, limit - 1)].rstrip() + "…"


def safe_arguments(tool_type: Any, content: Any) -> Dict[str, str]:
    """What a stop line may quote of a call's arguments.

    Returns ``{"arguments_state": "shown", "arguments": "<excerpt>"}``,
    ``{"arguments_state": "withheld"}`` or ``{"arguments_state": "empty"}``.

    Shown means: not a credential tool, no credential word anywhere in the raw
    text, then passed through `diagnostic_bundle.redact` — the same redactor the
    support bundle and the failure log use (`Law 14`: one redactor) — and cut to
    one line of `ARGUMENTS_LIMIT` characters. If the redactor cannot run, the
    arguments are withheld: a failed redaction must never put the unredacted
    text in its place (`_failure_detail` in `src/tool_execution.py` holds the
    same rule).
    """
    text = content if isinstance(content, str) else ("" if content is None else str(content))
    if not text.strip():
        return {"arguments_state": ARGS_EMPTY}
    if str(tool_type or "") in _CREDENTIAL_TOOLS or _MAY_HOLD_CREDENTIAL.search(text):
        return {"arguments_state": ARGS_WITHHELD}
    try:
        from src.diagnostic_bundle import redact
        masked = redact(text)
    except Exception:
        return {"arguments_state": ARGS_WITHHELD}
    excerpt = _one_line(masked, ARGUMENTS_LIMIT)
    if not excerpt:
        return {"arguments_state": ARGS_EMPTY}
    return {"arguments_state": ARGS_SHOWN, "arguments": excerpt}


def _times(n: int) -> str:
    if n == 1:
        return "once"
    if n == 2:
        return "twice"
    return f"{n} times"


def _repeated_call(tool_blocks: Sequence[Any], call_freq: Counter):
    """The call in this round that was requested most often this turn.

    Every block in the tripping round was counted before the check ran, so its
    count includes this last, refused request. Ties go to the first block, which
    is the order the model wrote them in.
    """
    best, best_n = None, 0
    for block in tool_blocks or ():
        n = call_freq.get(call_signature(getattr(block, "tool_type", None),
                                         getattr(block, "content", None)), 0)
        if n > best_n:
            best, best_n = block, n
    return best, best_n


def _switched_off_note(switched_off: Iterable[str]) -> str:
    names = [str(t) for t in switched_off or () if t]
    if not names:
        return ""
    joined = " and ".join(names)
    one = len(names) == 1
    return (f" {joined} {'is' if one else 'are'} switched off for this chat — "
            f"turn {'it' if one else 'them'} on if it needs {'it' if one else 'them'}.")


def loop_breaker_stop(
    *,
    round_num: int,
    tool_blocks: Sequence[Any],
    call_freq: Counter,
    runaway: bool,
    rounds_without_progress: int,
    detail: str,
    switched_off: Iterable[str] = (),
) -> Dict[str, Any]:
    """The `loop_breaker_triggered` event for one trip.

    `type`, `reason`, `message`, `round` and `detail` are the keys the event has
    always carried and keep their meaning (`Law 1`); `message` is now the
    specific sentence instead of the fixed one. Added: `kind`, `tool`, `count`,
    `rounds_without_progress` (a stall only), the argument excerpt or the fact it
    was withheld, and `next` — what the person can do about it (`Law 15`).
    """
    block, count = _repeated_call(tool_blocks, call_freq)
    tool = str(getattr(block, "tool_type", "") or "a tool")
    kind = KIND_IDENTICAL_CALLS if runaway else KIND_NO_PROGRESS
    message = f"Stopped: called {tool} with identical arguments {_times(count)}"
    if kind == KIND_NO_PROGRESS:
        message += (f", {int(rounds_without_progress)} rounds in a row "
                    "without writing anything")
    message += "."
    event: Dict[str, Any] = {
        "type": "loop_breaker_triggered",
        "reason": "loop_breaker_stall",
        "kind": kind,
        "round": round_num,
        "tool": tool,
        "count": count,
        **safe_arguments(tool, getattr(block, "content", None)),
        "message": message,
        "next": (
            "That last attempt was not run, and tools are off for the rest of "
            "this reply, so the answer below uses only what it had already "
            "found. To go further, tell it what to try instead, or run it "
            "yourself and paste the result."
            + _switched_off_note(switched_off)
        ),
        "detail": detail,
    }
    if kind == KIND_NO_PROGRESS:
        event["rounds_without_progress"] = int(rounds_without_progress)
    return event


def unkept_promise_stop(
    *,
    round_num: int,
    phrases: Sequence[str],
    nudges: int,
) -> Dict[str, Any]:
    """The `intent_nudge_exhausted` event for one stop.

    `phrases` is every action the model announced without calling a tool this
    turn, oldest first, the one that ended the turn last. When they are all the
    same sentence the line quotes it with the count; when they differ it counts
    the announcements and quotes the last, because *said "X" three times* would
    be false.

    The phrase is quoted as the model wrote it, apart from whitespace and length:
    it is the model's own reply text, already on screen in the bubble directly
    above, so a redaction here would make the two disagree and hide nothing.
    `matched` keeps the raw last phrase exactly as before (`Law 1`).
    """
    said = [_one_line(p, PHRASE_LIMIT) for p in (phrases or ()) if str(p or "").strip()]
    announced = len(said)
    last = said[-1] if said else ""
    if said and len(set(said)) == 1:
        message = f"Stopped: said “{last}” {_times(announced)} without making a call."
    elif said:
        message = (f"Stopped: said it would act {_times(announced)} without making "
                   f"a call — last: “{last}”.")
    else:
        message = "Stopped: it said it would act and did not make a call."
    return {
        "type": "intent_nudge_exhausted",
        "reason": "intent_without_action_nudge_cap",
        "kind": KIND_UNKEPT_PROMISE,
        "round": round_num,
        "nudges": nudges,
        "announced": announced,
        "matched": str(phrases[-1]).strip() if phrases else "",
        "message": message,
        "next": (
            "Nothing was run. Ask again and name the exact command or file, "
            "or pick a model that is better at calling tools."
        ),
    }


__all__: List[str] = [
    "ARGS_EMPTY", "ARGS_SHOWN", "ARGS_WITHHELD",
    "KIND_IDENTICAL_CALLS", "KIND_NO_PROGRESS", "KIND_UNKEPT_PROMISE",
    "call_signature", "loop_breaker_stop", "safe_arguments", "unkept_promise_stop",
]
