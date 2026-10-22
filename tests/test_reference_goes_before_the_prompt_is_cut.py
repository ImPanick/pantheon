# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1425`: when a turn does not fit, the skills block goes before the system
prompt is cut.

Found by `tests/test_the_agent_works_the_workstation_screen.py::
test_a_model_without_native_tools_is_shown_the_fenced_form`, which went red
with `B1419`'s shipped skills (green on `d0dd72c`, red on `5a7c75c`): under the
default 6,000-token agent budget the trimmer kept 10,319 characters of matched
procedures *about* the `computer` tool and cut the leading system prompt — the
tool's own section included — to its first 2,000 characters. A model told how
to use a tool it is no longer told it has.

Driven through the real `trim_for_context` with messages shaped by the real
`own_context_message`.
"""
from __future__ import annotations

from src.context_compactor import SHED_BEFORE_THE_PROMPT, trim_for_context
from src.prompt_security import own_context_message
from src.model_context import estimate_tokens

SYSTEM = "TOOLS: " + ("use the computer tool like this. " * 400) + "END-OF-TOOLS"


def _turn(skills_chars=10_000, memory_chars=0):
    msgs = [{"role": "system", "content": SYSTEM}]
    if skills_chars:
        msgs.append(own_context_message("skills", "procedure. " * (skills_chars // 11)))
    if memory_chars:
        msgs.append(own_context_message("memory", "a fact. " * (memory_chars // 8)))
    msgs.append({"role": "user", "content": "open the page"})
    return msgs


def _budget_that_fits_the_prompt_but_not_both():
    return estimate_tokens([{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": "open the page"}]) + 200


def test_the_skills_block_is_shed_and_the_prompt_survives_whole():
    budget = _budget_that_fits_the_prompt_but_not_both()
    out = trim_for_context(_turn(), budget, reserve_tokens=0)
    assert out[0]["content"] == SYSTEM, "the tools' own instructions were cut"
    assert not any((m.get("metadata") or {}).get("source") == "skills" for m in out)
    assert out[-1]["content"] == "open the page"


def test_a_skills_block_that_fits_is_kept():
    budget = estimate_tokens(_turn()) + 50
    out = trim_for_context(_turn(), budget, reserve_tokens=0)
    assert any((m.get("metadata") or {}).get("source") == "skills" for m in out)


def test_only_the_named_sources_are_shed():
    """The person's own memory is not reference the model can fetch back; it
    keeps the trimmer's old rule."""
    assert SHED_BEFORE_THE_PROMPT == frozenset({"skills"})
    budget = _budget_that_fits_the_prompt_but_not_both()
    out = trim_for_context(_turn(skills_chars=0, memory_chars=10_000), budget, reserve_tokens=0)
    assert any((m.get("metadata") or {}).get("source") == "memory" for m in out)


def test_with_nothing_to_shed_the_old_cut_still_happens():
    tiny = 300
    out = trim_for_context(_turn(skills_chars=0), tiny, reserve_tokens=0)
    assert out[0]["content"].endswith("[System prompt truncated for context limits]")


def test_when_the_prompt_is_cut_either_way_the_block_stays():
    """Shedding is for saving the prompt. A window too small for the prompt
    alone cuts it with or without the block, and then losing the block too
    would be two losses for none saved."""
    turn = _turn()
    cut = dict(turn[0], content=SYSTEM[:2000] + "\n[System prompt truncated for context limits]")
    budget = estimate_tokens([cut] + turn[1:]) + 20
    assert budget < estimate_tokens([turn[0], turn[-1]]), "premise: the prompt alone does not fit"
    out = trim_for_context(turn, budget, reserve_tokens=0)
    assert out[0]["content"].endswith("[System prompt truncated for context limits]")
    assert any((m.get("metadata") or {}).get("source") == "skills" for m in out)
