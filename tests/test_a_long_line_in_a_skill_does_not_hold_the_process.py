# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2103` — a SKILL.md line with a long run of whitespace is read in time
linear in its length.

**Before the fix** `services/memory/skill_format._HEADING_RE` was
`^##\\s+(.*?)\\s*$`. On a line that starts `## ` and holds a long run of
whitespace before more text, the lazy title and the trailing `\\s*` tried every
split of that run: `## a`, 20,000 spaces and `b` took a second here, 40,000
took four, and the time grows with the square of the run. Python's `re` holds
the GIL while it matches, so every skill load that read such a file (the
catalogue, the editor, the agent's `use_skill`) stalled the whole process.
CodeQL's polynomial-regex query named it on the port's pull request.

Now the pattern is `^##\\s+(.*)`, which cannot fail after `## `, so nothing
is tried twice; each caller strips the title, so every heading reads as before.
"""
import time

from services.memory.skill_format import Skill, parse_body

#: The old pattern took about four seconds on this line here; the new one a
#: few microseconds. The bound leaves a slow runner a wide margin either way.
RUN = 40_000
BOUND_SECONDS = 1.0


def _timed(fn, *args):
    started = time.perf_counter()
    result = fn(*args)
    return result, time.perf_counter() - started


def test_a_long_run_of_spaces_after_a_heading_is_read_at_once():
    body = "## When to Use\n\nAlways.\n\n## Notes" + " " * RUN + "x\n\nA note.\n"
    parsed, took = _timed(parse_body, body)
    assert took < BOUND_SECONDS, f"{took:.2f}s for one {RUN}-space line"
    assert parsed["when_to_use"] == "Always."
    assert parsed["body_extra"].startswith("## Notes")
    assert parsed["body_extra"].endswith("A note.")


def test_a_whole_skill_with_such_a_line_loads_at_once():
    text = ("---\nname: long-line\ndescription: A skill with one long line\n---\n\n"
            "## Procedure\n\n1. First" + "\t" * RUN + "step\n2. Second\n\n"
            "## Pitfalls" + " " * RUN + "!\n")
    skill, took = _timed(Skill.from_markdown, text)
    assert took < BOUND_SECONDS, f"{took:.2f}s for a SKILL.md with a {RUN}-character run"
    assert skill.procedure[1] == "Second"
    assert skill.procedure[0].startswith("First") and skill.procedure[0].endswith("step")


def test_every_heading_reads_as_it_did():
    body = ("##   Procedure  \t\n- one\n"
            "##Pitfalls\n"          # no whitespace after `##`: not a heading
            "### Verification\n"    # a third `#`: not this parser's heading
            "## Verification\t\n- it ran\n"
            "##\tWhen to Use\nAlways.\n")
    parsed = parse_body(body)
    assert parsed["procedure"] == ["one ##Pitfalls ### Verification"]
    assert parsed["verification"] == ["it ran"]
    assert parsed["when_to_use"] == "Always."
