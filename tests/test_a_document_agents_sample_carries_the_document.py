# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1604` — a document agent's `sample.json` carries the document it wrote.

`P24-17`'s sample report is what the hall shows under an agent: the case's
report — what it read, what it wrote with, its checks and its answer. For an
agent whose work is a document, the answer is a line like "3 suggestions: 1
spelling, 1 wrong word, 1 consistency." and the Proofreading document itself —
the thing a person is deciding whether to hire — was nowhere in it.

The harness now keeps the documents a run wrote (made, or changed from what
the world gave it), the sample carries them, and the hall draws them
(`tests/test_the_agents_hall_js.py`). Driven through the real harness; the
shipped samples are checked against their manifests' own `delivers`.
"""

from __future__ import annotations

import asyncio
import json
import os

from src.agents import evals as E
from src.agents.catalogue import get_agent
from src.agents.runtime import _fill, _missing_words
from tests.test_an_agent_has_substance import AT_THE_BAR


def test_the_harness_keeps_the_document_a_run_wrote_and_not_the_one_it_was_given():
    m = get_agent(None, "proofreader")
    case = next(c for c in E.load_evals(m) if c["id"] == "a-letter-with-three-mistakes")
    (r,) = asyncio.run(E.run_agent(m, cases=[case]))
    sample = E.sample_report(r)
    titles = [d["title"] for d in sample.get("documents") or []]
    assert titles == ["Proofreading — Q3 letter to members"], titles
    assert "## Suggestions" in sample["documents"][0]["content"]
    assert "whose dues" in sample["documents"][0]["content"]


def test_a_run_that_writes_no_document_has_none_in_its_sample():
    m = get_agent(None, "server-health")
    (r,) = asyncio.run(E.run_agent(m, cases=E.load_evals(m)[:1]))
    assert r.documents == [] and "documents" not in E.sample_report(r)


def test_every_document_agents_sample_carries_its_document():
    """The row's Verify, over every agent at the bar whose first case delivers
    a document: its `sample.json` carries a document with the title and the
    headings its `delivers` names."""
    checked = 0
    for aid in sorted(AT_THE_BAR):
        m = get_agent(None, aid)
        promised = [d for d in m.delivers if d.get("kind") == "document"]
        with open(os.path.join(E.agent_dir(m), "sample.json"), encoding="utf-8") as fh:
            sample = json.load(fh)
        if not promised or not any(c.get("check", "").startswith("a document") for c in sample.get("checks") or []):
            continue
        case = next(c for c in E.load_evals(m) if c["id"] == sample["case"])
        docs = sample.get("documents") or []
        for d in promised:
            title = _fill(str(d.get("title") or ""), case.get("inputs") or {})
            hit = [x for x in docs if title.lower() in (x.get("title") or "").lower()]
            assert hit, f"{aid}'s sample.json does not carry “{title}”: {[x.get('title') for x in docs]}"
            assert not _missing_words(hit[-1]["content"], d.get("must_contain") or []), aid
        checked += 1
    assert checked >= 3, f"only {checked} document agents were checked — the test measures nothing"
