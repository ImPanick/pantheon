# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-00b` — long-term knowledge attaches to the thing it is about.

The row's complaint: *"Memory today is owner-scoped and session-linked; there is
no notion of a project that outlives either."* Before this, `project` existed
only as a **category** string — a memory could be filed as *being about a
project* without saying which — so nothing survived a session boundary attached
to the work it concerned. Its `Verify` is a behaviour and not a schema: *start a
new session months later, ask about a project, and the answer carries what was
learned before without being re-explained.*

**A normalised label, not an entity.** A memory carries two fields: `project`,
the slug that filters and retrieval key off, and `project_label`, the name as
whoever wrote it wrote it. Both or neither — a slug with no label cannot be
shown and a label with no slug cannot be grouped.

The slug is what makes it a *thing* rather than a string: `Pantheon`,
`pantheon` and `pantheon!!` are one project typed three ways, and storing the
label alone makes them three. **There is exactly one implementation of that
rule and it is server-side.** That is a deliberate choice against this phase's
own grain — it already carries two rules mirrored into the browser
(`normalise_confidence` and `MEMORY_ENGINE_LABELS`), and each has cost a real
defect, the first of them the same day as this row. The Brain sends a raw label
and is offered the labels the store already knows, so no browser copy exists.

**The field earns its place in retrieval, which is `P13-02`'s test applied
here**: *"An edge that only exists to be drawn is not worth storing."* Naming a
project in a question lifts that project's memories; a memory of another
project is **not** demoted and never excluded, because hiding the fact that the
identical decision was taken elsewhere is usually the most useful thing a
reader could be told — the restraint `co_occurs` shows and the flattening
`D-2026-08-26-03` protects against. And because the boost multiplies the
keyword score, it **sharpens and cannot invent**: a memory that shares no words
with the question scores zero either way, so naming a project pulls up what
already matched rather than surfacing everything ever filed under it. A project
is a filter on the page; in the scorer it is a tiebreaker.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import memory_retrieval as mr  # noqa: E402
from src.memory import (MemoryManager, PROJECT_SLUG_MAX,  # noqa: E402
                        project_index, project_slug)


@pytest.fixture
def manager(tmp_path):
    return MemoryManager(str(tmp_path))


# ── The slug ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,slug", [
    ("Pantheon", "pantheon"),
    ("pantheon", "pantheon"),
    ("PANTHEON", "pantheon"),
    ("  Pantheon  ", "pantheon"),
    ("pantheon!!", "pantheon"),
    ("The Pantheon Harness", "the-pantheon-harness"),
    ("Odysseus / fork", "odysseus-fork"),
    ("P13-00b", "p13-00b"),
])
def test_one_project_typed_many_ways_is_one_project(label, slug):
    assert project_slug(label) == slug


@pytest.mark.parametrize("label", [
    None, "", "   ", "---", "!!!", True, False,
    "the theming work we discussed on Tuesday afternoon before the release",
])
def test_what_is_not_a_name_is_not_a_project(label):
    """Including the case that matters most: a label long enough to be a
    sentence has *described* a memory rather than named a project, and letting
    it through makes a list of one-row projects nobody can filter by."""
    assert project_slug(label) is None


def test_the_length_cap_is_a_name_not_a_sentence():
    assert project_slug("a" * PROJECT_SLUG_MAX) == "a" * PROJECT_SLUG_MAX
    assert project_slug("a" * (PROJECT_SLUG_MAX + 1)) is None


def test_the_slug_rule_has_no_browser_copy():
    """The choice this row made against the phase's own grain. Two mirrored
    rules in this phase have each cost a defect — `normalise_confidence`
    disagreed with its browser twin about `""` and about infinity on the same
    day as this row — so the slug is computed on the server only and the Brain
    is *offered* labels instead of computing them."""
    for path in sorted((ROOT / "static").rglob("*.js")):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "projectSlug" not in text, (
            f"{path.relative_to(ROOT)} has a browser copy of the slug rule; "
            "it should ask /api/memory/projects for the labels instead")


# ── The record ──────────────────────────────────────────────────────────────

def test_a_memory_records_both_the_slug_and_the_name(manager):
    entry = manager.add_entry("Theming uses light-dark()", project="Pantheon")
    assert entry["project"] == "pantheon"
    assert entry["project_label"] == "Pantheon", (
        "the label a person reads was replaced by the slug")


def test_both_or_neither(manager):
    """A slug with no label cannot be shown; a label with no slug cannot be
    grouped. A label that does not survive slugging stores nothing rather than
    half a project."""
    for junk in (None, "", "---", "a" * 99):
        entry = manager.add_entry("A fact", project=junk)
        assert entry["project"] is None and entry["project_label"] is None


def test_a_memory_written_before_this_row_reads_not_recorded(manager):
    """The same call `mentions` and `confidence` made, for the same reason: the
    store cannot know which project an old fact was about, and guessing one
    from its text is the invented value `_validate_entries` exists to refuse."""
    rows = manager._validate_entries([{"text": "an old memory"}])
    assert rows[0]["project"] is None and rows[0]["project_label"] is None


def test_a_hand_edited_or_imported_label_is_grouped_not_orphaned(manager):
    """Re-slugged on load rather than trusted. Somebody editing the JSON by
    hand, or an import, writes a label and no slug — or a slug with the wrong
    case — and either way it has to land in the project it names instead of
    becoming a project of one."""
    rows = manager._validate_entries([
        {"text": "a", "project_label": "The Harness"},
        {"text": "b", "project": "PANTHEON  "},
        {"text": "c", "project": "Pantheon", "project_label": "Pantheon"},
        {"text": "d", "project": "!!!", "project_label": "!!!"},
    ])
    assert rows[0]["project"] == "the-harness" and rows[0]["project_label"] == "The Harness"
    assert rows[1]["project"] == "pantheon"
    assert rows[2]["project"] == "pantheon" and rows[2]["project_label"] == "Pantheon"
    assert rows[3]["project"] is None and rows[3]["project_label"] is None


# ── The index ───────────────────────────────────────────────────────────────

def test_the_earliest_name_wins_so_a_filter_does_not_rename_itself():
    """Not the commonest. A project's name is what it was called when it
    started, and letting a majority rename it means a filter's own label
    changes under the reader as memories accumulate."""
    index = project_index([
        {"project": "pantheon", "project_label": "PANTHEON", "timestamp": 300},
        {"project": "pantheon", "project_label": "pantheon harness", "timestamp": 100},
        {"project": "pantheon", "project_label": "Pantheon", "timestamp": 200},
    ])
    assert index["pantheon"]["label"] == "pantheon harness"
    assert index["pantheon"]["memories"] == 3


def test_the_index_carries_the_dates_the_page_needs():
    """`P13-07` has to *"state plainly how fresh the analysis is"*, and
    `last_seen` is that sentence's only honest source."""
    index = project_index([
        {"project": "a", "project_label": "A", "timestamp": 10},
        {"project": "a", "project_label": "A", "timestamp": 90},
        {"project": "b", "project_label": "B", "timestamp": 50},
    ])
    assert index["a"]["first_seen"] == 10 and index["a"]["last_seen"] == 90
    assert index["b"]["first_seen"] == index["b"]["last_seen"] == 50


def test_memories_with_no_project_are_not_a_project():
    index = project_index([{"project": None}, {"text": "x"}, {}, None, "junk"])
    assert index == {}


# ── Retrieval: the field has to change what a search returns ───────────────

CORPUS = [
    {"id": "1", "text": "theming uses light-dark for elevation", "timestamp": 1,
     "project": "pantheon", "project_label": "Pantheon"},
    {"id": "2", "text": "theming uses a single hard-coded shadow", "timestamp": 1,
     "project": "odysseus", "project_label": "Odysseus"},
    {"id": "3", "text": "theming is handled by the design team", "timestamp": 1},
    {"id": "4", "text": "the owner prefers terse commit messages", "timestamp": 1,
     "project": "pantheon", "project_label": "Pantheon"},
]


@pytest.mark.parametrize("query,expected", [
    ("what did we decide about Pantheon theming?", "pantheon"),
    ("odysseus theming", "odysseus"),
    ("theming", None),
    ("nothing here", None),
    ("", None),
])
def test_a_question_names_a_project_only_if_the_store_knows_it(query, expected):
    """Read from the question against the corpus rather than from session
    state. A session-scoped "current project" has to be set by somebody and is
    wrong the moment a person changes subject mid-chat; inferring it from the
    text in general is a guess that goes wrong quietly. Only a name a memory
    already claims can be matched."""
    assert mr._query_project(query, CORPUS) == expected


def test_the_longest_name_wins():
    """Otherwise the shorter name inside the longer one always answers first."""
    corpus = [
        {"id": "a", "text": "x", "project": "pantheon", "project_label": "Pantheon"},
        {"id": "b", "text": "y", "project": "pantheon-harness",
         "project_label": "Pantheon Harness"},
    ]
    assert mr._query_project("about the Pantheon Harness", corpus) == "pantheon-harness"


def test_naming_a_project_lifts_it_without_hiding_the_others():
    """The whole design in one assertion. The named project's memory comes
    first; the other project's memory is still **returned**, because hiding
    that the same decision was taken elsewhere is the flattening this row
    refuses."""
    got = mr.retrieve("what did we decide about Pantheon theming?", CORPUS, k=4)
    ids = [row.get("id") for row in got]
    assert ids[0] == "1", f"the named project did not rank first: {ids}"
    assert "2" in ids, "the other project's memory was excluded, not just outranked"
    assert ids.index("1") < ids.index("2")


def test_the_boost_sharpens_and_cannot_invent():
    """Memory 4 is tagged `pantheon` and shares no words with a theming
    question, so naming the project must not drag it in. A project is a filter
    on the Brain's page; in the scorer it is a tiebreaker."""
    got = mr.retrieve("what did we decide about Pantheon theming?", CORPUS, k=4)
    assert "4" not in [row.get("id") for row in got], (
        "an unrelated memory surfaced because its project was named")


def test_a_memory_with_no_project_is_neutral_not_penalised():
    """Nearly every memory written before this row has no project, and
    penalising them would rank the whole corpus below whatever was tagged
    first."""
    assert mr._project_boost("pantheon", {"project": None}) == 1.0
    assert mr._project_boost("pantheon", {}) == 1.0
    assert mr._project_boost("pantheon", {"project": "odysseus"}) == 1.0
    assert mr._project_boost("pantheon", {"project": "pantheon"}) == mr._PROJECT_BOOST
    assert mr._project_boost(None, {"project": "pantheon"}) == 1.0


def test_the_boost_is_a_tiebreaker_not_an_override():
    """Below `identity`'s 1.4: naming a project says which memories matter and
    nothing about which *kind*, so it must not outrank the cue that says a
    question is about who the person is."""
    identity = next(b for name, _c, b in mr._INTENT_CUES if name == "identity")
    assert mr._PROJECT_BOOST < identity


# ── The Verify, end to end ─────────────────────────────────────────────────

def test_a_new_session_months_later_carries_what_the_project_learned(tmp_path):
    """The row's own `Verify`, driven rather than paraphrased.

    *"Start a new session months later, ask about a project, and the answer
    carries what was learned before without being re-explained."* So the
    memories are written through one manager and read through a **second one
    built over the same directory** — which is what a new session is, and what
    makes this a test of permanence rather than of a dict that happened to
    still be in memory. The question carries no session, no owner and no
    project argument: the only thing connecting it to what was learned is the
    name in the question."""
    writing = MemoryManager(str(tmp_path))
    writing.save([
        writing.add_entry("elevation is a shadow everywhere, never ink at low alpha",
                          project="Pantheon", source="auto"),
        writing.add_entry("elevation is one hard-coded rgba per surface",
                          project="Odysseus", source="auto"),
        writing.add_entry("prefers tea", source="user"),
    ])

    later = MemoryManager(str(tmp_path))
    rows = later.load()
    assert {row["project"] for row in rows} == {"pantheon", "odysseus", None}, (
        "the projects did not survive the trip through disk")

    got = mr.retrieve("how does Pantheon do elevation?", rows, k=3)
    assert got, "nothing came back at all"
    assert got[0]["project"] == "pantheon", (
        f"the project's own answer did not come first: "
        f"{[(r.get('project'), r.get('text')[:30]) for r in got]}")
    assert any(row.get("project") == "odysseus" for row in got), (
        "the other project's answer was hidden rather than outranked")


# ── The extractor passes it through ────────────────────────────────────────

def _extractor():
    """Loaded by path, as `test_memory_extractor_vector_cross_tenant.py` does:
    importing `services.memory` pulls in the whole search stack."""
    path = ROOT / "services" / "memory" / "memory_extractor.py"
    spec = importlib.util.spec_from_file_location("memory_extractor_project_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _llm_returning(monkeypatch, payload: str):
    stub = types.ModuleType("src.llm_core")

    async def llm_call_async(*a, **k):
        return payload

    stub.llm_call_async = llm_call_async
    # `setitem`, not assignment: a raw assignment leaves this stub in
    # `sys.modules` for every later test that imports the real module, which
    # the sibling file learned the hard way and says so.
    package = sys.modules.get("src") or types.ModuleType("src")
    monkeypatch.setitem(sys.modules, "src", package)
    monkeypatch.setitem(sys.modules, "src.llm_core", stub)


class _Session:
    def __init__(self):
        self.session_id = "s1"
        self.owner = None

    def get_context_messages(self):
        return [{"role": "user", "content": "In Pantheon we settled on light-dark()."},
                {"role": "assistant", "content": "Noted."}]


def test_the_extractor_files_the_fact_under_the_project_the_model_named(monkeypatch, tmp_path):
    """The gap a mutation found. Every other case here calls `add_entry`
    directly, so deleting `project=project` from the extractor's own call
    changed nothing any test could see — and that one line is the entire path
    by which a project is ever recorded in normal use.

    It matters more than it looks because of how it fails: `extract_and_store`
    wraps its whole body in `except Exception`, so a mistake on that line costs
    the batch **every** fact and logs "Memory extraction failed" — which is
    exactly how `project` first broke a sibling test, and the test read as a
    cross-tenant dedup bug."""
    extractor = _extractor()
    _llm_returning(monkeypatch, '[{"text": "Theming settled on light-dark()", '
                                '"category": "fact", "confidence": 0.9, '
                                '"project": "Pantheon"}]')
    manager = MemoryManager(str(tmp_path))
    asyncio.run(extractor.extract_and_store(
        _Session(), manager, None, "http://localhost/v1", "m"))

    rows = manager.load()
    assert rows, "the extractor stored nothing at all"
    assert rows[0]["project"] == "pantheon", (
        f"the model named a project and it was not recorded: {rows[0].get('project')!r}")
    assert rows[0]["project_label"] == "Pantheon", "the name a person reads was lost"


def test_a_fact_with_no_project_is_stored_with_none(monkeypatch, tmp_path):
    """The common case, and the one the prompt tells the model to prefer: most
    facts are about the person rather than about a project, and inventing one
    for a general preference makes a filter that hides it from every other
    project."""
    extractor = _extractor()
    _llm_returning(monkeypatch, '[{"text": "Prefers tea", "category": "preference", '
                                '"confidence": 0.9}]')
    manager = MemoryManager(str(tmp_path))
    asyncio.run(extractor.extract_and_store(
        _Session(), manager, None, "http://localhost/v1", "m"))
    rows = manager.load()
    assert rows, "the extractor stored nothing at all"
    assert rows[0]["project"] is None and rows[0]["project_label"] is None


def test_the_prompt_asks_for_a_project_and_says_when_to_omit_it(monkeypatch):
    """A prompt that asked for the field without saying *most facts have no
    project* is how every memory ends up filed under whatever was mentioned
    last — a corpus of one-memory projects, which is worse than none."""
    extractor = _extractor()
    prompt = extractor.EXTRACT_SYSTEM_PROMPT
    assert "'project'" in prompt, "the prompt does not ask for a project"
    lowered = prompt.lower()
    assert "omit" in lowered, "the prompt never says a project may be left out"
    assert "most facts have no project" in lowered, (
        "the prompt asks for a project without saying it is usually absent")
