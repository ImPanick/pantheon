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

**`B915`** (at the end): the turn's other notes — the step limit, the tool
budget, a teacher's takeover, the skill notes — kept for the saved reply by the
route, through `AgentNotes`.
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
#: `P7-12`. Rounds that brought nothing new — the information ledger's stop.
KIND_NO_NEW_INFORMATION = "no_new_information"

#: `P7-12`. How many rounds in a row may bring nothing new before the loop
#: stops them. Four, the stall detector's own number: the ledger is a sharper
#: test of the same thing, not a more impatient one.
ROUNDS_WITHOUT_NEW_INFORMATION = 4

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


def information_key(text: Any) -> Optional[str]:
    """`P7-12`. One piece of information's identity: a tool result, or the
    model's own words in a round. Whitespace and case do not make text new;
    anything else does. `None` for nothing at all, which is never new."""
    flat = " ".join(str(text or "").split()).casefold()
    if not flat:
        return None
    return hashlib.sha256(flat.encode("utf-8", "replace")).hexdigest()[:32]


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


def no_new_information_stop(
    *,
    round_num: int,
    tool_blocks: Sequence[Any],
    call_freq: Counter,
    rounds: int,
    detail: str,
    switched_off: Iterable[str] = (),
) -> Dict[str, Any]:
    """The `loop_breaker_triggered` event for the information ledger. `P7-12`.

    `D-2026-09-08-04` made loop detection the precondition for letting the
    agent raise its own step limit, and said what *smarter* means: round-count
    is not a loop signal — the same call with the same arguments is, cycling
    between two states is, and *"producing no new information across N rounds —
    no new file read, no new command, no new content"* is. The stall detector
    above counts a repeated call only in a round that wrote nothing, over the
    last six rounds; a model that narrates ("Checking again.") or cycles over a
    longer period never trips it, and meets only the fifteen-call backstop.
    This stop is the third signal: `rounds` rounds in a row with no call not
    already made in this reply, no result not already seen, and no words not
    already written.

    Same event, same keys, same `next` as the loop-breaker (`Law 1`), with its
    own `kind` and the count of empty rounds.
    """
    block, count = _repeated_call(tool_blocks, call_freq)
    tool = str(getattr(block, "tool_type", "") or "a tool")
    return {
        "type": "loop_breaker_triggered",
        "reason": "loop_breaker_no_new_information",
        "kind": KIND_NO_NEW_INFORMATION,
        "round": round_num,
        "tool": tool,
        "count": count,
        **safe_arguments(tool, getattr(block, "content", None)),
        "message": (
            f"Stopped: {int(rounds)} rounds in a row brought nothing new — every "
            f"call had already been made in this reply and gave the same result "
            f"(it called {tool} {_times(count)})."
        ),
        "next": (
            "That last attempt was not run, and tools are off for the rest of "
            "this reply, so the answer below uses only what it had already "
            "found. To go further, tell it what to try instead, or run it "
            "yourself and paste the result."
            + _switched_off_note(switched_off)
        ),
        "detail": detail,
        "rounds_without_new_information": int(rounds),
    }


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


# ── `B915` · The turn's other notes, kept for the reply they belong to ─────────
#
# Six events draw a line into the chat history beside the reply, the way the
# two stops above do: the step limit and its Continue offer, the tool budget, a
# teacher taking over, and what became of a skill. None was saved, so a reload
# dropped every one — Continue ▸ with it — and a resumed stream, which ends in a
# reload, lost them too.
#
# They are collected where the reply is saved, not on the loop's metrics
# envelope as the stops are, because three of them cannot ride that envelope:
# `teacher_takeover`, `escalation_failed` and `skill_save_failed` are sent by
# `run_teacher_inline` *after* the loop's `metrics` (and one `escalation_failed`
# before any later one exists), and a turn the teacher answered is saved from
# the teacher's own `metrics`, which the loop that sent the student's notes
# never sees. The route sees every frame of the turn in order, so it keeps them
# here and saves them as `agent_notes`, each exactly as streamed plus where it
# goes.

#: The events that draw a note. `AGENT_NOTE_TYPES` in `static/js/agentStops.js`
#: is the browser's copy, and a test holds the two equal. `B921` added
#: `compacted`: an agent turn's context summarised to fit, said live by a toast
#: and saved nowhere a reload drew from.
AGENT_NOTE_TYPES = ("rounds_exhausted", "budget_exceeded", "teacher_takeover",
                    "skill_saved", "escalation_failed", "skill_save_failed",
                    "compacted")


def _positive_round(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


# ── `B939` / `B941` · Two runs, one reply ───────────────────────────────────
#
# A reply can be the work of two runs of the agent loop: a student's and the
# teacher's that took over from it (`B939`), or a run that hit the step limit
# and the one Continue ▸ started (`B941`). Each run keeps its own record — its
# rounds numbered from 1, and its own figures — and the reply was saved from one
# of them. The teacher's record replaced the student's, so a reload drew the
# teacher's rounds and none of the student's; Continue's merge kept the
# continuation's rounds and none of the first run's. The live stream drew both
# runs, one after the other. `merge_runs` is the one way two records become
# one: the second run's rounds numbered after the first's, and the first run's
# own figures kept as an `earlier_runs` entry, which history replay labels that
# run's rounds from and draws its footer from, as the live stream did.

#: The parts of a run's record that are one entry per round, in round order.
ROUND_LISTS = ("round_texts", "round_models", "round_endpoint_ids", "round_endpoint_labels")
#: The events in a run's record that name the round they belong to.
ROUND_EVENTS = ("tool_events", "agent_stops", "verifier_findings")
#: Everything about a record that is per round, or about the whole reply
#: rather than one run of it. What is left is the run's own figures.
RUN_KEYS = ROUND_LISTS + ROUND_EVENTS + ("agent_notes", "earlier_runs")
#: Left out of an earlier run's figures: the last request's breakdown, which
#: `GET /api/session/{id}/context` reads from the reply's own record (`B892`)
#: and nothing reads for an earlier run.
_NOT_AN_EARLIER_RUNS_FIGURE = ("context_breakdown",)


def rounds_in(record: Any) -> int:
    """How many of a reply's rounds a run's record holds, counted as history
    replay counts them (`addMessage`): its per-round lists, or the last round
    one of its events names, whichever is further."""
    if not isinstance(record, dict):
        return 0
    count = max((len(record.get(key) or []) for key in ROUND_LISTS), default=0)
    for key in ROUND_EVENTS:
        for event in record.get(key) or []:
            if isinstance(event, dict):
                count = max(count, _positive_round(event.get("round")) or 0)
    return count


def _shifted(event: Dict[str, Any], by: int, *, roundless: Optional[int]) -> Dict[str, Any]:
    """`event` with its round moved `by` rounds later. A round of `0` (before
    the run's first) becomes the round before that run's first, too. An event
    with no round keeps none unless `roundless` says where such an event is."""
    out = dict(event)
    try:
        number = int(out.get("round"))
    except (TypeError, ValueError):
        number = None
    if number is not None and number >= 0:
        out["round"] = number + by
    elif roundless is not None:
        out["round"] = roundless + by
    return out


def merge_notes(first: Iterable[Any], second: Iterable[Any], first_rounds: int) -> List[Dict[str, Any]]:
    """Two runs' `agent_notes`, as one reply's. A note in a round keeps it, the
    second run's moved after the first run's rounds; a note the first run drew
    at its end (no round) is after its last round now, because the second run's
    rounds follow it; one the second run drew at its end stays at the end."""
    notes = []
    for note in first or ():
        if isinstance(note, dict):
            out = dict(note)
            if out.get("round") is None:
                out["round"] = first_rounds
            notes.append(out)
    for note in second or ():
        if isinstance(note, dict):
            out = dict(note)
            if out.get("round") is not None:
                out = _shifted(out, first_rounds, roundless=None)
            notes.append(out)
    return notes


def run_figures(record: Any) -> Dict[str, Any]:
    """A run's own figures: its record without what is per round or about the
    whole reply. What its footer is drawn from and its rounds labelled from."""
    if not isinstance(record, dict):
        return {}
    return {key: value for key, value in record.items()
            if key not in RUN_KEYS and key not in _NOT_AN_EARLIER_RUNS_FIGURE}


def merge_runs(first: Any, second: Any) -> Dict[str, Any]:
    """One reply's record from two runs', `second` after `first`.

    The reply's figures are the last run's (`second`'s): its footer is the one
    the turn ends on. Its rounds are the first run's and then the second's,
    each of the second run's events and notes moved by the first run's round
    count. The first run's own figures are appended to `earlier_runs` with
    `last_round`, the reply's round its last round is, and a run that already
    had earlier runs keeps them, moved with its rounds."""
    first = dict(first) if isinstance(first, dict) else {}
    second = dict(second) if isinstance(second, dict) else {}
    offset = rounds_in(first)
    merged = {key: value for key, value in second.items() if key not in RUN_KEYS}
    for key in ROUND_LISTS:
        before = list(first.get(key) or [])
        after = list(second.get(key) or [])
        if not before and not after:
            continue
        pad = "" if key == "round_texts" else None
        merged[key] = before + [pad] * (offset - len(before)) + after
    for key in ROUND_EVENTS:
        events = [dict(e) for e in first.get(key) or [] if isinstance(e, dict)]
        # A tool event with no round is drawn in round 1 (`ev.round ?? 1`).
        roundless = 1 if key == "tool_events" else None
        events += [_shifted(e, offset, roundless=roundless)
                   for e in second.get(key) or [] if isinstance(e, dict)]
        if events:
            merged[key] = events
    notes = merge_notes(first.get("agent_notes"), second.get("agent_notes"), offset)
    if notes:
        merged["agent_notes"] = notes
    earlier = [dict(run) for run in first.get("earlier_runs") or [] if isinstance(run, dict)]
    earlier.append(dict(run_figures(first), last_round=offset))
    for run in second.get("earlier_runs") or []:
        if isinstance(run, dict):
            moved = dict(run)
            moved["last_round"] = (_positive_round(run.get("last_round")) or 0) + offset
            earlier.append(moved)
    merged["earlier_runs"] = earlier
    return merged


#: `B941`. What Continue ▸ sends after the step limit (`continueAfterStepLimit`,
#: `static/js/agentStops.js`, where it is `STEP_LIMIT_CONTINUE_PROMPT`; a test
#: holds the two equal). A hidden prompt, like the interrupted reply's: Continue's
#: merge takes it out from between the two replies it joins.
STEP_LIMIT_CONTINUE_PROMPT = (
    "You hit the step limit before finishing — the task is not complete. Continue "
    "from exactly where you left off and keep going until it is done. Do NOT "
    "repeat work already done.")

#: The hidden prompts a Continue sends, which its merge removes. The interrupted
#: reply's has always been recognised by this phrase (`merge_last_assistant`).
CONTINUE_PROMPT_MARKERS = ("previous response was interrupted", STEP_LIMIT_CONTINUE_PROMPT)


def is_continue_prompt(content: Any) -> bool:
    """Whether a user message is a prompt a Continue sent, not something typed."""
    text = content if isinstance(content, str) else ""
    return any(marker in text for marker in CONTINUE_PROMPT_MARKERS)


class AgentNotes:
    """The notes one turn drew, in order, for the reply they are saved with.

    `observe` every frame the turn streams; `saved()` returns the notes with
    `round` set to the round of the **saved record** each one followed, which is
    how history replay places them (`addMessage`): after that round's text,
    tools and stops; `0` for before the first round; no `round` for the end.

    A turn the teacher answered is saved as one reply of two runs (`B939`,
    `merge_runs`): the student's rounds, then the teacher's numbered after
    them. So the student's notes stay in their rounds, the takeover banner
    follows the student's last round, what the teacher's own run drew goes in
    its rounds (moved after the student's), and what came after the teacher's
    run is at the end. A turn saved from the student's record alone keeps its
    notes in their rounds, and the takeover and everything after it at the end.
    """

    def __init__(self) -> None:
        self._seen: List[tuple] = []     # (event, phase, round in its own run)
        self._round = 1                  # the round now streaming, in its run's numbering
        self._taken_over = False
        self._teacher_record = False     # the record to be saved is the teacher's
        self._student_rounds = 0         # `B939`: the student's rounds, before the teacher's

    def observe(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        kind = data.get("type")
        teacher = data.get("teacher") is True
        if kind == "agent_step":
            self._round = _positive_round(data.get("round")) or self._round
        elif kind in ("metrics", "agent_terminal"):
            # The route saves the last of these it saw, so its run is the record.
            self._teacher_record = teacher
            if not teacher:
                self._student_rounds = rounds_in(data.get("data"))
        elif kind == "teacher_takeover":
            self._seen.append((dict(data), "takeover", self._round))
            self._taken_over = True
            self._round = 1              # the teacher's run numbers its own rounds
        elif kind == "compacted":
            # `B921`. A compaction shapes the request of the round now starting,
            # so it is drawn before that round: after the one before it, or
            # before the first (`0`).
            phase = "teacher" if teacher else ("after" if self._taken_over else "student")
            self._seen.append((dict(data), phase, self._round - 1))
        elif kind in AGENT_NOTE_TYPES:
            phase = "teacher" if teacher else ("after" if self._taken_over else "student")
            self._seen.append((dict(data), phase, _positive_round(data.get("round")) or self._round))

    def saved(self) -> List[Dict[str, Any]]:
        if self._teacher_record:
            # `B939`. Each run's notes in its own numbering — the student's in
            # their rounds and the takeover at the end of its run; the teacher's
            # in its rounds and what followed its run at the end — and then
            # joined as `merge_runs` joins the two records they are saved with.
            student, teacher = [], []
            for event, phase, round_ in self._seen:
                note = dict(event)
                note.pop("round", None)
                if phase in ("student", "teacher"):
                    note["round"] = round_
                (student if phase in ("student", "takeover") else teacher).append(note)
            return merge_notes(student, teacher, self._student_rounds)
        notes = []
        for event, phase, round_ in self._seen:
            note = dict(event)
            note.pop("round", None)
            if phase == "student":
                note["round"] = round_
            notes.append(note)
        return notes


__all__: List[str] = [
    "ARGS_EMPTY", "ARGS_SHOWN", "ARGS_WITHHELD",
    "KIND_IDENTICAL_CALLS", "KIND_NO_NEW_INFORMATION", "KIND_NO_PROGRESS",
    "KIND_UNKEPT_PROMISE", "ROUNDS_WITHOUT_NEW_INFORMATION",
    "call_signature", "information_key", "loop_breaker_stop", "no_new_information_stop",
    "safe_arguments", "unkept_promise_stop",
    "AGENT_NOTE_TYPES", "AgentNotes",
    "ROUND_LISTS", "ROUND_EVENTS", "RUN_KEYS", "rounds_in", "merge_notes", "run_figures",
    "merge_runs", "STEP_LIMIT_CONTINUE_PROMPT", "CONTINUE_PROMPT_MARKERS", "is_continue_prompt",
]
