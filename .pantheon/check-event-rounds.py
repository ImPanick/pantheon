#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P4-11` — every agent-thread event says which round it belongs to.

The round has been on the wire since the first version of the agent loop, and
it was on *most* events. The gaps were invisible because nothing rendered it:

  * the streamed `tool_output` had no round, while the `tool_start` before it
    and the persisted `tool_event` after it both did — the same action answered
    "which round?" after a reload and refused to answer it live;
  * the approved-action replay hardcoded `0` at four sites, so the one card in
    the thread the user personally authorised named a round no other card has;
  * the one-shot image path sent no round at all;
  * the skill-test replay log kept the round on `agent_step` and dropped it
    from the tool cards inside the step.

Four different files, one rule. That is what a checker is for: the rule holds
for the next emit site too, and nobody has to remember it.

What counts as a problem:

  **missing.**   A dict literal that declares itself a thread event and has no
                 `round` key and no `**` spread that could carry one.
  **inherited,   A dict that gets its round from a `**spread`. Legitimate —
  undeclared.**  `teacher_escalation` re-sends its own persisted event — but
                 the claim has to be written down here so it is checked rather
                 than assumed.
  **zero.**      A literal `round` below 1. Rounds are 1-based; `0` is the
                 exact hardcode this row removed, and the reason it is a rule
                 and not a fix.

Usage:  python3 .pantheon/check-event-rounds.py [--list]
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The events that build or advance a card in the agent thread. `metrics`,
# `ask_user`, `delta` and the rest are not thread cards and have no round.
EVENT_TYPES = {"tool_start", "tool_progress", "tool_output", "agent_step"}

# (file, event type, name spread in) -> why that spread carries the round.
# A spread is the only way a thread event may omit `round`, and only here.
INHERITS: dict[tuple[str, str, str], str] = {
    ("src/teacher_escalation.py", "tool_output", "approval_tool_event"): (
        "re-sends the escalation's own persisted event, which sets "
        "`round: approval_round` two lines above"
    ),
}

SKIP_PREFIXES = ("tests/", ".pantheon/", "scripts/")


def _tracked_python() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.split() if not f.startswith(SKIP_PREFIXES)]


def _event_type(node: ast.Dict) -> str | None:
    for key, value in zip(node.keys, node.values):
        if (isinstance(key, ast.Constant) and key.value == "type"
                and isinstance(value, ast.Constant) and value.value in EVENT_TYPES):
            return value.value
    return None


def _sites() -> list[tuple[str, int, str, ast.Dict]]:
    found = []
    for rel in _tracked_python():
        try:
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict) and (kind := _event_type(node)):
                found.append((rel, node.lineno, kind, node))
    return found


def main() -> int:
    listing = "--list" in sys.argv
    problems: list[str] = []
    claimed: set[tuple[str, str, str]] = set()
    explicit = inherited = 0

    for rel, line, kind, node in sorted(_sites(), key=lambda s: (s[0], s[1])):
        pairs = dict(zip(node.keys, node.values))
        round_value = next(
            (v for k, v in pairs.items()
             if isinstance(k, ast.Constant) and k.value == "round"),
            None,
        )
        spreads = [ast.unparse(v) for k, v in pairs.items() if k is None]

        if round_value is not None:
            explicit += 1
            if (isinstance(round_value, ast.Constant)
                    and isinstance(round_value.value, int)
                    and not isinstance(round_value.value, bool)
                    and round_value.value < 1):
                problems.append(
                    f"{rel}:{line}: `{kind}` hardcodes round "
                    f"{round_value.value}. Rounds are 1-based — this is the "
                    "literal P4-11 removed, and a card showing it names a "
                    "round no other card in the thread has."
                )
            if listing:
                print(f"{'explicit':<10} {rel}:{line}  {kind}  "
                      f"round={ast.unparse(round_value)}")
            continue

        matched = [s for s in spreads if (rel, kind, s) in INHERITS]
        if matched:
            inherited += 1
            claimed.add((rel, kind, matched[0]))
            if listing:
                print(f"{'inherited':<10} {rel}:{line}  {kind}  **{matched[0]}")
            continue

        if spreads:
            problems.append(
                f"{rel}:{line}: `{kind}` has no round of its own and spreads "
                f"{', '.join('**' + s for s in spreads)}. If one of those "
                "carries the round, say so in INHERITS; if none does, the "
                "event reaches a card that cannot name its round."
            )
        else:
            problems.append(
                f"{rel}:{line}: `{kind}` carries no round. Every card in the "
                "agent thread names the round it belongs to; an event without "
                "one draws a card that cannot."
            )

    for key in sorted(set(INHERITS) - claimed):
        problems.append(
            f"INHERITS claims {key[0]} spreads `{key[2]}` into a `{key[1]}` "
            "and there is no such site any more — remove the entry so the map "
            "stays a description of the tree."
        )

    print(f"thread events {explicit + inherited}  ·  explicit {explicit}  ·  "
          f"inherited {inherited}  ·  PROBLEMS {len(problems)}")
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
