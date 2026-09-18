# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-17` — the extractor was writing the format the format replaced.

`maybe_extract_skill` is where most of a real user's library comes from: it fires
after any agent run that took two rounds or two tool calls, with no click. Its
prompt asked for `title` / `problem` / `solution` / `steps` / `tags` /
`confidence` — the pre-SKILL.md shape — and passed exactly those through to
`add_skill`. Measured 2026-09-18: **no auto-extracted skill has ever had a
Pitfalls section, a Verification section, or a category other than `general`**,
because none of those three words appeared anywhere on the path. The schema has
supported all of them since the format was written, and `skill_format.py`
renders each as a `##` heading the moment it is non-empty.

That is not a missing feature; it is the whole library arriving structurally
poorer than the format it is stored in, from the one path nobody chooses.

The old shape is still accepted, and that is not politeness. A 7B model handed a
nine-field schema will sometimes answer in the four-field one it has seen more
of, and dropping that answer turns a partly-filled skill into no skill at all.
"""

import pytest

from services.memory import skill_extractor
from services.memory.skills import SkillsManager

MODERN = """{
  "name": "restore-postgres-from-wal",
  "description": "Restore a Postgres cluster to a point in time from WAL archives",
  "category": "database",
  "when_to_use": "When a bad migration has to be undone and the nightly dump is too old",
  "procedure": ["Stop the cluster", "Restore the base backup", "Write recovery.signal"],
  "pitfalls": ["Starting the cluster before recovery.signal exists replays nothing"],
  "verification": ["SELECT pg_is_in_recovery() returns false once it is done"],
  "tags": ["postgres", "backup", "wal"],
  "confidence": 0.9
}"""

LEGACY = """{
  "title": "Restore Postgres from WAL",
  "problem": "a bad migration had to be undone",
  "solution": "replay the write-ahead log to a point in time",
  "steps": ["Stop the cluster", "Restore the base backup"],
  "tags": ["postgres"],
  "confidence": 0.9
}"""


class _FakeSession:
    session_id = "s1"

    def get_context_messages(self):
        return [
            {"role": "user", "content": "The migration broke production, get it back"},
            {"role": "assistant", "content": "Replaying WAL to 14:02..."},
        ]


async def _extract(monkeypatch, tmp_path, response, owner=None):
    async def fake_llm_call_async(*a, **k):
        return response

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)
    sm = SkillsManager(str(tmp_path), library_root="")
    entry = await skill_extractor.maybe_extract_skill(
        _FakeSession(), sm, endpoint_url="http://endpoint", model="test-model",
        headers={}, round_count=3, tool_count=3, owner=owner,
    )
    return sm, entry


@pytest.mark.asyncio
async def test_an_extracted_skill_has_the_sections_the_format_supports(monkeypatch, tmp_path):
    sm, entry = await _extract(monkeypatch, tmp_path, MODERN)
    assert entry is not None

    md = sm.read_skill_md(entry["name"], owner=None)
    assert "## Pitfalls" in md, "extracted skills still have no Pitfalls section"
    assert "## Verification" in md, "extracted skills still have no Verification section"
    assert "## When to Use" in md
    assert "recovery.signal exists replays nothing" in md
    assert "pg_is_in_recovery" in md


@pytest.mark.asyncio
async def test_it_stops_filing_everything_under_general(monkeypatch, tmp_path):
    sm, entry = await _extract(monkeypatch, tmp_path, MODERN)
    assert entry["category"] == "database", (
        "the category the model chose was dropped and the skill filed under "
        f"{entry['category']!r}"
    )


@pytest.mark.asyncio
async def test_the_trigger_text_retrieval_matches_on_is_carried(monkeypatch, tmp_path):
    # `when_to_use` is the field `get_relevant_skills` scores a request against.
    # Before this, the extractor's `problem` landed there only by accident of
    # `add_skill`'s old-shape fallback, and the prompt never asked for one.
    sm, entry = await _extract(monkeypatch, tmp_path, MODERN)
    assert "bad migration" in entry["when_to_use"]
    hits = sm.get_relevant_skills("a bad migration has to be undone",
                                  sm.load(owner=None), threshold=0.1)
    assert [h["name"] for h in hits] == [entry["name"]]


@pytest.mark.asyncio
async def test_the_name_the_model_chose_becomes_the_slug(monkeypatch, tmp_path):
    _sm, entry = await _extract(monkeypatch, tmp_path, MODERN)
    assert entry["name"] == "restore-postgres-from-wal"


@pytest.mark.asyncio
async def test_a_four_field_answer_still_produces_a_skill(monkeypatch, tmp_path):
    # Back-compat, and it is load-bearing: this is what a small local model
    # answers roughly half the time.
    sm, entry = await _extract(monkeypatch, tmp_path, LEGACY)
    assert entry is not None
    assert entry["description"] == "Restore Postgres from WAL"
    assert entry["when_to_use"] == "a bad migration had to be undone"
    assert entry["procedure"] == ["Stop the cluster", "Restore the base backup"]
    md = sm.read_skill_md(entry["name"], owner=None)
    assert "## When to Use" in md
    assert "## Procedure" in md


@pytest.mark.asyncio
async def test_an_answer_with_no_steps_at_all_is_dropped(monkeypatch, tmp_path):
    sm, entry = await _extract(monkeypatch, tmp_path, """{
      "name": "vague", "description": "something happened",
      "when_to_use": "sometimes", "procedure": [], "tags": [], "confidence": 0.9
    }""")
    assert entry is None
    assert sm.load(owner=None) == []


@pytest.mark.asyncio
async def test_a_deduped_extraction_does_not_announce_a_skill_that_was_not_created(
        monkeypatch, tmp_path):
    # `do_manage_skills` returns before firing `skill_added` on the dedup branch,
    # with a comment saying why: nothing was saved. The extractor fired anyway,
    # so a `skill_added` automation could run for a skill that does not exist.
    fired = []
    import src.event_bus as event_bus
    monkeypatch.setattr(event_bus, "fire_event",
                        lambda *a, **k: fired.append(a), raising=False)

    sm, first = await _extract(monkeypatch, tmp_path, MODERN)
    assert first is not None and not first.get("_deduped")
    assert len(fired) == 1

    async def fake_llm_call_async(*a, **k):
        return MODERN

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)
    second = await skill_extractor.maybe_extract_skill(
        _FakeSession(), sm, endpoint_url="http://endpoint", model="test-model",
        headers={}, round_count=3, tool_count=3, owner=None,
    )
    # Either the title-duplicate guard or `add_skill`'s own dedup catches it;
    # both mean nothing new was written, and neither may claim otherwise.
    assert second is None or second.get("_deduped")
    assert len(fired) == 1, "skill_added fired for a skill that was not created"
    assert len(sm.load(owner=None)) == 1
