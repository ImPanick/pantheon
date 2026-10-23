# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-01` / `P24-02` — an agent is one file, the lint is the one rule for it,
and the catalogue is two layers.

**Measured before this file, on `a28041c`:** there was no `AGENT.md`, no
`src/agents/` and no `library/pantheon/agents/`; a "pre-configured agent" could
only be a crew member a person built by hand.

Driven through the real `src.agents.manifest.parse_manifest` and
`src.agents.catalogue`, against the real shipped files and a per-person layer
in a temporary data folder. Every refusal is asserted by its sentence, because
the sentence is what a person who wrote the file reads (`Law 10`).
"""

from __future__ import annotations

import os
import textwrap

import pytest

from src.agents import catalogue as C
from src.agents.manifest import (
    SECTION_IDS, ManifestRefused, parse_frontmatter, parse_manifest,
)

GOOD = textwrap.dedent('''\
    ---
    id: test-agent
    name: Test Agent
    tagline: Proves the lint.
    section: research
    version: 1.0.0
    inputs:
      - {key: topics, kind: list, label: Topics}
      - {key: at, kind: time, label: When, default: "07:00"}
    triggers:
      - {on: daily, at: "{at}"}
    tools: [web_search]
    effects: {read_public: allow}
    budget: {max_steps: 10}
    memory: own
    ---
    1. Search each topic and say what is new, with its source.
    ''')


def _with(old: str, new: str) -> str:
    assert old in GOOD, old
    return GOOD.replace(old, new)


def test_a_good_manifest_reads_whole():
    m = parse_manifest(GOOD)
    assert (m.id, m.name, m.section, m.version, m.wave, m.memory) == (
        "test-agent", "Test Agent", "research", "1.0.0", 2, "own")
    assert m.tools == ("web_search",)
    assert m.inputs[1] == {"key": "at", "kind": "time", "label": "When", "default": "07:00"}
    assert m.triggers == ({"on": "daily", "at": "{at}"},)
    assert m.budget == {"runs_per_day": 24, "max_steps": 10, "max_minutes": 10}
    assert m.runbook.startswith("1. Search")
    assert m.to_public()["starts_on"] == "daily at 07:00"


@pytest.mark.parametrize("old,new,sentence", [
    ("tools: [web_search]", "tools: [web_search, launch_rockets]",
     "“launch_rockets” is not a tool Pantheon has."),
    ("effects: {read_public: allow}", "effects: {telepathy: allow}", "“telepathy” is not an effect."),
    ("effects: {read_public: allow}", "effects: {read_public: maybe}",
     "Effect “read_public” is “maybe”; it can only be allow, ask or never."),
    ('  - {on: daily, at: "{at}"}', "  - {on: lunar}", "Trigger 1 starts on “lunar”"),
    ('  - {on: daily, at: "{at}"}', "  - {on: event, event: rain_started}",
     "Trigger 1 waits for “rain_started”, which is not an event Pantheon raises"),
    ('  - {on: daily, at: "{at}"}', '  - {on: daily, at: "{topics}"}',
     "Trigger 1 takes its time from “topics”, which is not a time input."),
    ('  - {on: daily, at: "{at}"}', '  - {on: cron, cron: "* * * * *"}', "Trigger 1: That schedule runs every"),
    ("kind: list, label: Topics}", "kind: crystal, label: Topics}", "Input “topics” has kind “crystal”"),
    ("section: research", "section: astrology", "The section “astrology” is not one of the hall's sections."),
    ("memory: own", "memory: forever", "“memory” is one of: own, shared, none."),
    ("memory: own", "memory: shared", "“memory: shared” needs manage_memory among the tools."),
    ("budget: {max_steps: 10}", "budget: {max_steps: 900}", "“budget.max_steps” must be a whole number from 1 to 60."),
    ("version: 1.0.0", "version: one", "The version “one” is not like 1.0.0."),
    ("id: test-agent", "id: Test Agent!", "The id “Test Agent!” is not lower-case words joined by dashes."),
    ("memory: own", "memory: own\nsecret: yes", "The frontmatter has a field nothing reads: secret."),
    ("tools: [web_search]", "tools: []", "“tools” is empty"),
    ("1. Search each topic and say what is new, with its source.", "Do it.",
     "The runbook under the frontmatter is empty"),
])
def test_each_kind_of_mistake_is_refused_in_a_sentence(old, new, sentence):
    with pytest.raises(ManifestRefused) as refused:
        parse_manifest(_with(old, new))
    assert sentence in refused.value.sentence


def test_a_file_with_no_frontmatter_says_so():
    with pytest.raises(ManifestRefused, match="starts with a line of three dashes"):
        parse_manifest("# Just a runbook\n")
    with pytest.raises(ManifestRefused, match="never closed"):
        parse_manifest("---\nid: x\n")


def test_the_frontmatter_subset_reads_what_a_manifest_writes():
    fm = parse_frontmatter(textwrap.dedent('''\
        a: plain words # a comment
        b: [x, "y, z", 'w']
        c: {k: v, n: 3, t: true, q: "it's: fine"}
        d:
          - {key: x, label: The project's folder}
          - "quoted"
        e:
          k1: allow
          k2: ask
        '''))
    assert fm == {"a": "plain words", "b": ["x", "y, z", "w"],
                  "c": {"k": "v", "n": 3, "t": True, "q": "it's: fine"},
                  "d": [{"key": "x", "label": "The project's folder"}, "quoted"],
                  "e": {"k1": "allow", "k2": "ask"}}


def test_an_unclosed_bracket_is_refused_not_guessed():
    with pytest.raises(ManifestRefused, match="A list is not closed"):
        parse_frontmatter("tools: [a, b\n")
    with pytest.raises(ManifestRefused, match="left open"):
        parse_frontmatter("tools: [a, {b: c]\n")


# ── the shipped roster ──────────────────────────────────────────────────────

STARTERS = {
    "inbox-triage", "follow-up-chaser", "meeting-catcher", "morning-brief", "weekly-review",
    "topic-watcher", "deep-researcher", "release-watcher", "proofreader", "notes-gardener",
    "site-builder", "repo-doctor", "dependency-watch", "server-health", "model-steward",
    "backup-verifier", "contact-keeper", "form-responder",
}


def test_every_shipped_agent_passes_its_lint_and_the_starters_are_all_there(tmp_path):
    agents, broken = C.catalogue("ada", data_dir=str(tmp_path))
    assert broken == []
    assert {m.id for m in agents} == STARTERS
    assert all(m.wave == 1 and m.section in SECTION_IDS and m.source == "shipped" for m in agents)
    assert {m.id for m in agents if m.starred} == {
        "inbox-triage", "morning-brief", "topic-watcher", "site-builder", "server-health"}


def test_the_hall_order_is_section_then_starred_then_name(tmp_path):
    agents, _ = C.catalogue("ada", data_dir=str(tmp_path))
    order = {s: n for n, s in enumerate(SECTION_IDS)}
    keys = [(order[m.section], not m.starred, m.wave, m.name.lower()) for m in agents]
    assert keys == sorted(keys)


# ── the two layers ──────────────────────────────────────────────────────────

def _own(tmp_path, owner, folder, text):
    root = C.own_root(owner, str(tmp_path))
    os.makedirs(os.path.join(root, folder), exist_ok=True)
    with open(os.path.join(root, folder, "AGENT.md"), "w", encoding="utf-8") as fh:
        fh.write(text)


def test_a_persons_copy_shadows_the_shipped_agent_for_them_alone(tmp_path):
    shipped = C.get_agent("ada", "morning-brief", data_dir=str(tmp_path))
    mine = (open(shipped.path, encoding="utf-8").read()
            .replace("name: Morning Brief", "name: Ada's Brief"))
    _own(tmp_path, "ada", "morning-brief", mine)
    assert C.get_agent("ada", "morning-brief", data_dir=str(tmp_path)).name == "Ada's Brief"
    assert C.get_agent("bob", "morning-brief", data_dir=str(tmp_path)).name == "Morning Brief"
    ada, _ = C.catalogue("ada", data_dir=str(tmp_path))
    assert [m.source for m in ada if m.id == "morning-brief"] == ["own"]
    assert len([m for m in ada if m.id == "morning-brief"]) == 1


def test_a_broken_own_file_is_listed_broken_and_takes_nothing_away(tmp_path):
    _own(tmp_path, "ada", "morning-brief", "---\nid: morning-brief\n---\n")
    agents, broken = C.catalogue("ada", data_dir=str(tmp_path))
    assert [b["folder"] for b in broken] == ["morning-brief"]
    assert "“name” is missing." == broken[0]["sentence"]
    assert C.get_agent("ada", "morning-brief", data_dir=str(tmp_path)).source == "shipped"
    assert "morning-brief" in {m.id for m in agents}


def test_a_folder_must_carry_its_own_id(tmp_path):
    _own(tmp_path, "ada", "mine", GOOD)
    agents, broken = C.catalogue("ada", data_dir=str(tmp_path))
    assert broken and "they have to match" in broken[0]["sentence"]
    assert "test-agent" not in {m.id for m in agents}


def test_an_own_agent_is_hireable_by_its_person(tmp_path):
    _own(tmp_path, "ada", "test-agent", GOOD)
    assert C.get_agent("ada", "test-agent", data_dir=str(tmp_path)).source == "own"
    assert C.get_agent("bob", "test-agent", data_dir=str(tmp_path)) is None


@pytest.mark.parametrize("bad", ["../morning-brief", "a/b", ".hidden", ""])
def test_an_agent_id_cannot_walk_out_of_the_catalogue(tmp_path, bad):
    assert C.get_agent("ada", bad, data_dir=str(tmp_path)) is None
