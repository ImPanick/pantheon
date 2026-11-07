# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2029`. Deep research stopped before any search when its model planned none.

Each round asks the model for a JSON list of search queries. A first-round
reply with no list in it (an empty reply, "OK", a numbered or bulleted list,
prose) gave no queries, and the run ended there as `no_queries` without a
single search, although the question itself is a fair first search and the
extraction step reads a reply that is not JSON. `P23-02` made the card say
"The model gave no search queries."; it did not search.

Now the first round of a new run searches for the question, trimmed ("What
is new in Lisbon?" searches "new in Lisbon"), and says so. A later round, a
follow-up run (it already has a report) and a planner call that failed give
no queries as before, so a model that keeps failing still stops as
`no_queries`, one round later.

After upstream Odysseus 218d7624, which falls back in every round with three
variants of the question; this falls back once, with the question alone.
"""
import asyncio

import pytest

from src.deep_research import DeepResearcher

QUESTION = "What is new in Lisbon?"
SAID = {"phase": "warning",
        "message": "The model gave no search queries; searching for the question itself."}


def _planner(reply):
    """A researcher built without its __init__ whose model answers `reply`
    (or raises it); returns it and the progress events it sends."""
    r = DeepResearcher.__new__(DeepResearcher)
    r.research_plan = ""
    r.queries_used = set()
    said = []
    r._progress = said.append

    async def _llm(messages, **kwargs):
        if isinstance(reply, Exception):
            raise reply
        return reply

    r._llm = _llm
    return r, said


@pytest.mark.parametrize("reply", ["", "OK", "1. lisbon news 2026\n2. lisbon events",
                                   "Here are queries: lisbon news, lisbon events"],
                         ids=["empty", "ok", "numbered list", "prose"])
def test_a_new_runs_first_round_searches_the_question_when_the_model_gives_none(reply):
    r, said = _planner(reply)

    assert asyncio.run(r._generate_queries(QUESTION, "", 1)) == ["new in Lisbon"]
    assert r.queries_used == {"new in Lisbon"}
    assert said == [SAID]

    # Only there. A later round and a follow-up run give none, as before ...
    later, said_later = _planner(reply)
    assert asyncio.run(later._generate_queries(QUESTION, "", 2)) == []
    followup, said_followup = _planner(reply)
    assert asyncio.run(followup._generate_queries(QUESTION, "The report so far.", 1)) == []
    assert said_later == said_followup == []
    # ... and so does a planner call that failed.
    failed, said_failed = _planner(TimeoutError("planner timed out"))
    assert asyncio.run(failed._generate_queries(QUESTION, "", 1)) == []
    assert said_failed == [{"phase": "warning", "message": "Query generation failed: planner timed out"}]


def test_a_run_whose_model_plans_nothing_searches_once_and_still_says_why_it_stopped():
    r = DeepResearcher("http://model.test", "scripted", max_rounds=3)
    searched = []

    async def _plan(_question):
        return "plan"

    async def _category(_question):
        return ""

    async def _llm(_messages, **_kwargs):
        return ""

    async def _search(queries, _question):
        searched.append(list(queries))
        return []

    r._create_plan, r._classify_category, r._llm = _plan, _category, _llm
    r._search_and_extract = _search

    answer = asyncio.run(r.research(QUESTION))

    assert searched == [["new in Lisbon"]]
    assert r.stopped == "no_queries"
    assert answer == "No information could be gathered for this question."


@pytest.mark.parametrize("question,query", [
    ("What is new in Lisbon?", "new in Lisbon"),
    ("  please   how do   solar panels work?! ", "solar panels work"),
    ("Please summarise this week's fusion news.", "summarise this week's fusion news"),
    ("Lisbon housing prices 2026", "Lisbon housing prices 2026"),
    ("Whatever happened to Lisbon's trams?", "Whatever happened to Lisbon's trams"),
    ("???", ""),
    ("", ""),
], ids=["opener", "please and spacing", "please alone", "plain", "no opener", "punctuation", "empty"])
def test_the_question_becomes_one_plain_search(question, query):
    from src.deep_research import _question_as_query

    assert _question_as_query(question) == query


def test_a_long_question_is_cut_at_a_word():
    from src.deep_research import _question_as_query

    query = _question_as_query("Compare the tram, metro and ferry networks of Lisbon, " * 10)
    assert 0 < len(query) <= 200
    assert ("Compare the tram, metro and ferry networks of Lisbon, " * 10).startswith(query)
    assert not query.endswith(",")
