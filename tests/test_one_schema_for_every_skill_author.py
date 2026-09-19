# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-14` — one SKILL.md schema, and a door a person can describe their way
through.

The row was written as "retarget the teacher's skill-from-trace prompt at a
user description". Re-measured 2026-09-19 and it is not retargetable: three of
that prompt's four `.format()` slots are failure-shaped (`failure_reason`,
`trace`, `untrusted_trace_guard`) and its body says *"the steps that ACTUALLY
worked in the trace"* and *"if the trace did NOT genuinely solve the user's
problem ... output NO_SKILL"*. Substituting a typed description into those slots
tells the model it is holding something it is not.

So the work is a factoring. Before it there were **three** copies of the
schema and they were not the same schema:

  * the teacher's block — eleven keys, **no `tags`**;
  * `SKILL_EXTRACT_PROMPT` — nine keys as prose bullets, **`tags` but no
    `status`/`source`**;
  * and whatever the new caller would have written next.

`tags` is the field the whole-token boost in `get_relevant_skills` keys off, so
the teacher could not ask for the single strongest retrieval signal there is.
`services.memory.skill_prompts` is the one statement now; each caller writes its
own framing above it.

Every test here drives the builders and the drafter. Two of them compare
rendered prompt text, which is the thing under test rather than a proxy for it:
the claim being made is "these three prompts show the model the same schema",
and the only way to check that is to look at what the three prompts say.
"""

import json

import pytest

from services.memory import skill_extractor
from services.memory.skill_prompts import (
    FIELD_NAMES, PORTABILITY_RULES, skill_field_guidance, skill_json_block,
    skill_schema_section,
)
from src.teacher_escalation import _skill_from_trace_prompt


def _trace_prompt():
    return _skill_from_trace_prompt(
        user_request="get the cluster back",
        failure_reason="the student timed out",
        untrusted_trace_guard="<<GUARD>>",
        trace="- shell: 'systemctl restart pg'",
    )


# ── the factoring ──────────────────────────────────────────────────────────

def test_every_name_in_the_schema_is_a_field_the_store_can_write():
    """The schema is checked against the writer, not against itself.

    `FIELD_NAMES` is derived from the same tuple the prompts render, so a test
    that iterated it would agree with any typo made in it. `add_skill` is the
    one writer every path funnels through, so a name that is not one of its
    parameters is a field the model would be asked for and the store would
    silently drop."""
    import inspect

    from services.memory.skills import SkillsManager

    accepted = set(inspect.signature(SkillsManager.add_skill).parameters)
    for field in FIELD_NAMES:
        assert field in accepted, f"{field!r} is not something add_skill writes"
    # Named explicitly because this is the one the teacher's copy was missing,
    # and it is the field `get_relevant_skills` gives the strongest boost to.
    assert "tags" in FIELD_NAMES


def test_all_three_prompts_show_the_model_the_same_field_set():
    """`Law 13`. The teacher used to omit `tags` and the extractor used to omit
    nothing else; there is one list now and all three ask for it."""
    prompts = {
        "teacher": _trace_prompt(),
        "extractor": skill_extractor.skill_extract_prompt(3, 4),
        "description": skill_extractor.skill_from_description_prompt(),
    }
    for label, text in prompts.items():
        for field in FIELD_NAMES:
            assert f'"{field}"' in text, f"{label} does not ask for {field}"


def test_the_schema_block_is_one_string_not_three_copies():
    """Every asked-for line of the rendered JSON template appears verbatim in
    all three prompts. A second copy edited by hand fails here on its first
    divergence. Compared line by line rather than as one blob because the
    teacher pins three extra keys at the top of its block — which is the one
    thing the three are *allowed* to differ on."""
    lines = [ln for ln in skill_json_block(fenced=False).splitlines()
             if ln.strip() not in ("{", "}")]
    assert len(lines) == len(FIELD_NAMES)
    for text in (_trace_prompt(),
                 skill_extractor.skill_from_description_prompt(),
                 skill_extractor.skill_extract_prompt(3, 4)):
        for ln in lines:
            assert ln.rstrip(",") in text, f"schema line missing: {ln!r}"


def test_the_portability_rules_are_one_string_too():
    assert PORTABILITY_RULES in _trace_prompt()
    assert PORTABILITY_RULES in skill_extractor.skill_extract_prompt(3, 4)
    assert PORTABILITY_RULES in skill_extractor.skill_from_description_prompt()


def test_the_field_guidance_is_one_string_too():
    guidance = skill_field_guidance()
    assert guidance in _trace_prompt()
    assert guidance in skill_extractor.skill_extract_prompt(3, 4)
    assert guidance in skill_extractor.skill_from_description_prompt()


def test_a_caller_pins_bookkeeping_instead_of_asking_for_it():
    """`status` and `source` decide whether a skill is catalogued and how the
    injection floor treats it. A model choosing them would be choosing policy,
    so the teacher pins them as literals and the block carries the value."""
    block = skill_json_block({"action": "add", "status": "draft",
                              "source": "teacher-escalation"}, fenced=False)
    assert '"status": "draft"' in block
    assert '"source": "teacher-escalation"' in block
    assert json.loads(block.replace("<short-kebab-case-slug>", "x")
                      .replace("<one line, under 200 characters>", "x")
                      .replace("<single lowercase word>", "x")
                      .replace("<the trigger, in the words a user would say>", "x")
                      .replace("<specific tool name and arg shape>", "x")
                      .replace("<failure mode and how to recover>", "x")
                      .replace("<the check that proves it worked>", "x")
                      .replace("<keyword>", "x"))["status"] == "draft"


def test_a_teacher_draft_is_still_stamped_as_a_teacher_draft():
    """`source` is not cosmetic: `index_for` catalogues a draft only when it
    reads `teacher-escalation`, and `get_relevant_skills` fails a
    teacher-written draft closed on a missing confidence where it lets a
    hand-written one through. Pinning the wrong value here would move a
    teacher skill onto the user's policy silently."""
    text = _trace_prompt()
    assert '"source": "teacher-escalation"' in text
    assert '"status": "draft"' in text
    assert '"action": "add"' in text


def test_the_shared_half_says_nothing_about_where_the_material_came_from():
    """The point of the split. If the shared block mentioned a trace it could
    not be composed by a prompt reading a person's typed sentence."""
    shared = skill_schema_section().lower()
    # Phrases, not bare words: the portability rules quote a literal
    # `tmux new-session` as an example of what NOT to bake into a procedure,
    # and a bare-substring check would read that shell command as a claim
    # about where the material came from (`Law 20` — test the meaning).
    for phrase in ("the trace", "your trace", "this session", "the session",
                   "the conversation", "no_skill", "the student",
                   "smaller student model"):
        assert phrase not in shared, (
            f"the shared schema section is input-specific: says {phrase!r}")


def test_only_the_trace_prompt_talks_about_a_trace():
    """And the description prompt must not, which is the row's whole
    correction — the failure-shaped framing is what made the original
    'just swap the format slots' plan wrong."""
    described = skill_extractor.skill_from_description_prompt()
    assert "trace" not in described.lower()
    assert "NO_SKILL" not in described
    assert "trace" in _trace_prompt().lower()
    assert "NO_SKILL" in _trace_prompt()


def test_the_trace_prompt_still_carries_its_four_slots():
    """`Law 1` — the factoring took nothing away from the teacher path."""
    text = _trace_prompt()
    assert "get the cluster back" in text
    assert "the student timed out" in text
    assert "<<GUARD>>" in text
    assert "systemctl restart pg" in text


def test_asking_for_a_field_that_is_not_in_the_schema_is_an_error():
    with pytest.raises(ValueError):
        skill_json_block(fields=["name", "invented_field"])


# ── the new door: a person's own words ─────────────────────────────────────

GOOD = """Here you go:

```json
{
  "name": "restart-the-print-spooler",
  "description": "Clear a stuck print queue by restarting the spooler service",
  "category": "system",
  "when_to_use": "When jobs pile up in the queue and nothing prints",
  "procedure": ["Stop the spooler service", "Delete the files in the spool dir",
                "Start the service again"],
  "pitfalls": ["Deleting the spool dir itself instead of its contents"],
  "verification": ["A test page prints"],
  "tags": ["printer", "spooler", "windows"],
  "confidence": 0.7
}
```"""

FOUR_FIELD = """{
  "title": "Restart the print spooler",
  "problem": "jobs pile up and nothing prints",
  "solution": "restart the spooler and clear the queue",
  "steps": ["Stop the service", "Clear the queue", "Start it"],
  "tags": ["printer"]
}"""


async def _draft(monkeypatch, response, text="I cleared the stuck print queue"):
    async def fake_llm_call_async(*a, **k):
        return response
    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)
    return await skill_extractor.draft_skill_from_description(
        text, endpoint_url="http://endpoint", model="test-model", headers={})


@pytest.mark.asyncio
async def test_a_person_describes_what_they_did_and_gets_the_whole_schema(monkeypatch):
    """The row's `Verify:`, at the layer the CLI and a future Workshop button
    both call. Nothing here says "trace" and nothing here reads a transcript."""
    draft = await _draft(monkeypatch, GOOD)
    assert draft["name"] == "restart-the-print-spooler"
    assert draft["category"] == "system"
    assert draft["when_to_use"].startswith("When jobs pile up")
    assert len(draft["procedure"]) == 3
    assert draft["pitfalls"] and draft["verification"] and draft["tags"]


@pytest.mark.asyncio
async def test_a_small_model_answering_in_the_old_shape_still_gets_a_draft(monkeypatch):
    """`Law 14` bought this for free: parsing is the extractor's
    `_normalise_extracted`, so `P8-17`'s four-field fallback — which it
    measured as load-bearing for 7B local models — covers this path too,
    without a second normaliser to keep in step."""
    draft = await _draft(monkeypatch, FOUR_FIELD)
    assert draft["description"] == "Restart the print spooler"
    assert draft["when_to_use"] == "jobs pile up and nothing prints"
    assert draft["procedure"] == ["Stop the service", "Clear the queue", "Start it"]


@pytest.mark.asyncio
async def test_the_model_is_allowed_to_say_that_is_not_a_procedure(monkeypatch):
    assert await _draft(monkeypatch, "null") is None
    assert await _draft(monkeypatch, "") is None


@pytest.mark.asyncio
async def test_a_husk_with_no_sentence_and_no_steps_is_not_handed_back(monkeypatch):
    """An object with neither a description nor a procedure is not something a
    person can edit into a skill; returning it would make the caller show an
    empty form and call it a draft."""
    assert await _draft(monkeypatch, '{"tags": ["printer"], "confidence": 0.2}') is None


@pytest.mark.asyncio
async def test_a_thinking_model_s_preamble_does_not_lose_the_draft(monkeypatch):
    """Same reasoning-preamble strip the session extractor needs — without it
    the JSON parse bombs on character 0 and the feature looks broken."""
    draft = await _draft(monkeypatch, "<think>Let me work out the steps.</think>\n" + GOOD)
    assert draft is not None and draft["name"] == "restart-the-print-spooler"


@pytest.mark.asyncio
async def test_an_empty_description_never_reaches_a_model(monkeypatch):
    calls = []

    async def fake_llm_call_async(*a, **k):
        calls.append(a)
        return GOOD
    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)
    assert await skill_extractor.draft_skill_from_description(
        "   ", endpoint_url="http://e", model="m") is None
    assert calls == []


@pytest.mark.asyncio
async def test_with_no_model_configured_it_declines_rather_than_calling_nothing(monkeypatch):
    assert await skill_extractor.draft_skill_from_description(
        "I did a thing", endpoint_url="http://e", model="") is None


@pytest.mark.asyncio
async def test_the_persons_words_go_in_the_user_turn_not_the_system_prompt(monkeypatch):
    """`P8-14`'s correction in one assertion: the prompt has no slot to
    interpolate a description into, because interpolating it into a framing
    written for something else is the mistake the row exists to avoid."""
    seen = {}

    async def fake_llm_call_async(url, model, messages, **k):
        seen["messages"] = messages
        return GOOD
    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)
    await skill_extractor.draft_skill_from_description(
        "I power-cycled the switch", endpoint_url="http://e", model="m")
    system, user = seen["messages"]
    assert system["role"] == "system" and "power-cycled" not in system["content"]
    assert user["role"] == "user" and "I power-cycled the switch" in user["content"]
