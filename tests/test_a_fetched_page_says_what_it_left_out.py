# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1403`, `B1402`. What a truncated fetch tells the model, and what the
delivery register is not allowed to mean.

Both rows come from the same measured session (the owner's LM Studio request
logs, 2026-10-16), and both are about the same failure from different sides:
the model was set up to answer without the material and did.

`B1403` — the person pasted an official news URL and asked for the raid's mobs
and rewards. Pantheon fetched it correctly and injected **10,116 characters**:
10,000 of page under the shared `MAX_OUTPUT_CHARS`, plus the header. The cut
landed before the article's own `Loot` section, so what arrived was a table of
contents *promising* loot, 10 KB of release-date preamble, and `[...truncated]`
as the last four words. The model invented a reward currency and called it
sourced. A fetched page is not tool output — it is the document the turn exists
for — so it gets its own, larger budget, and when it is still cut the notice
leads and says not to guess the rest.

`B1402` — the same turn carried the delivery register, correctly: the person
had written *"I shouldn't have to tell you to use internet search tools."* The
register told the model *"Keep this reply shorter than usual… lead with the
answer. Make the obvious call rather than asking a clarifying question."* Right
about delivery, and the thing they were impatient about was the work not being
done. So the guard now says what it never said: brevity is about words, never
about steps.
"""

from __future__ import annotations

import re

from src.constants import MAX_FETCH_OUTPUT_CHARS, MAX_OUTPUT_CHARS


# ── B1403: the budget ──────────────────────────────────────────────────────


def test_a_fetched_page_has_more_room_than_shell_output():
    """The two caps are different numbers for different things, and the fetch
    one is bigger. They were one shared 10,000, which is plenty for `bash` and
    not enough for an article."""
    assert MAX_FETCH_OUTPUT_CHARS > MAX_OUTPUT_CHARS
    # Enough for the long-form pages this tool gets pointed at. The measured
    # article was ~40k; most news pages are well inside this.
    assert MAX_FETCH_OUTPUT_CHARS >= 30_000
    # And still a budget: a local model's whole window is often 32k tokens, so
    # an unbounded page would take the turn with it.
    assert MAX_FETCH_OUTPUT_CHARS <= 60_000


def test_the_other_tools_keep_the_smaller_cap():
    """`B1403` widened one tool, not every tool. `bash` dumping 30 KB into a
    turn is the context problem this cap exists for."""
    assert MAX_OUTPUT_CHARS == 10_000


def _truncate_like_web_fetch(output: str) -> str:
    """The branch under test, lifted from `WebFetchTool.execute` by reading it
    rather than by re-implementing the policy (`Law 7`).

    Driving the real `execute` needs a live HTTP fetch; this reads the module's
    own source so the shape asserted below cannot drift from the shipped one
    without this helper failing to find it.
    """
    import inspect

    from src.agent_tools import web_tools

    src = inspect.getsource(web_tools.WebFetchTool.execute)
    assert "MAX_FETCH_OUTPUT_CHARS" in src, "the fetch path no longer uses its own cap"
    assert "TRUNCATED: this page is" in src, "the leading notice is gone"
    return src


def test_the_truncation_notice_leads_and_says_not_to_guess():
    """The half that matters more than the number.

    `[...truncated]` at the end of 10,000 characters is a marker nobody reads,
    and the model's response to a page that stops mid-way was to invent the
    rest. The notice now goes **first** — the same reasoning the `size_note`
    above it already follows — and says the three things the model has to know:
    how much it is missing, that the rest is not below, and that it must not
    fill the gap from memory.
    """
    src = _truncate_like_web_fetch("")
    # It leads: the notice is concatenated BEFORE the output slice.
    assert re.search(r"output\s*=\s*_cut_note\s*\+\s*output\[:_kept\]", src), src[-600:]
    # It says how much is missing, in both directions.
    assert "characters and you are" in src
    assert "The rest is NOT below" in src
    # And the instruction that answers the measured failure.
    assert "Do not" in src and "from memory" in src
    assert "do not describe" in src and "as sourced" in src
    # The trailing marker stays, pointing at the notice rather than standing alone.
    assert "see the notice at the top" in src


# ── B1402: what the register is not allowed to mean ────────────────────────


def test_the_register_guard_forbids_doing_less_work():
    """The clause, on the real rendered register.

    The register fired correctly on a frustrated turn. Every line of it is
    right about delivery and silent about whether to do the work, and the model
    read it as permission to answer fast from memory.
    """
    from src.memory_style import register_text

    text = register_text({"length": "shorter", "hedging": "none", "clarify": "act"})
    assert text, "the register rendered nothing for a pressure reading"
    # The lines that were already there, unchanged — this row adds, it does not
    # soften the feature. "The move under pressure is shorter, not softer."
    assert "Keep this reply shorter than usual." in text
    assert "lead with the answer" in text
    # And the limit that was missing.
    assert "never means do less work" in text
    assert "do that first" in text
    assert "unsourced answer delivered quickly" in text


def test_a_neutral_register_still_says_nothing():
    """`P13-19`'s rule, unchanged: a turn where the assistant should behave
    normally is a turn with nothing extra on the wire. The new clause must not
    leak onto every turn — it rides inside the register or not at all."""
    from src.memory_style import REGISTER_NEUTRAL, register_text

    assert register_text(REGISTER_NEUTRAL) == ""
    assert register_text(None) == ""
    assert register_text({}) == ""
